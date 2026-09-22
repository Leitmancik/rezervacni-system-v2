"""Společná Google tabulka; oddělené SQLite pro vývoj bez připojení."""
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import os
import sqlite3
import threading
import time
import uuid

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

from domain import (RES_HEADER, PRICE_HEADER, STATUS, StorageError,
                    parse_date, parse_money, conflict, quote,
                    validate_reservation)


@st.cache_resource
def _lock():
    return threading.RLock()


def config():
    if os.environ.get('CHALUPA_DEMO') == '1':
        return {}
    try:
        return dict(st.secrets)
    except FileNotFoundError:
        return {}


def connected():
    return 'gcp_service_account' in config()


@st.cache_resource(show_spinner=False)
def _document():
    cfg = config()
    if not cfg.get('sheet_id'):
        raise StorageError('V nastavení chybí sheet_id společné tabulky.')
    credentials = Credentials.from_service_account_info(
        dict(cfg['gcp_service_account']),
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    return gspread.authorize(credentials).open_by_key(cfg['sheet_id'])


@contextmanager
def _errors():
    try:
        yield
    except StorageError:
        raise
    except Exception:
        # Technické výjimky mohou obsahovat přístupové údaje nebo osobní data.
        raise StorageError('Data se nepodařilo načíst nebo uložit. Zkontrolujte '
                           'připojení a sdílení tabulky a zkuste to znovu.') from None


def _sheet(name, header, include_header=False):
    sheet = _document().worksheet(name)
    rows = sheet.get_all_values()
    if not rows or rows[0][:len(header)] != header:
        raise StorageError(f'List {name} nemá očekávané sloupce. '
                           'Strukturu tabulky aplikace automaticky nemění.')
    if include_header:
        return sheet, rows[1:], rows[0]
    return sheet, rows[1:]


def _decode_res(rows, cleaner_index=None, manager_index=None, billing_index=None):
    result = []
    ids = set()
    for row in rows:
        if not any(str(c).strip() for c in row):
            continue
        v = list(row) + [''] * max(0, 9 - len(row))
        start, end = parse_date(v[3]), parse_date(v[4])
        if start is None or end is None or end <= start:
            raise StorageError('Některá rezervace nemá platný příjezd a odjezd. '
                               'Dostupnost nelze bezpečně zobrazit.')
        rid = str(v[6]).strip()
        if rid and rid in ids:
            raise StorageError('Tabulka obsahuje duplicitní ID rezervace.')
        ids.add(rid)
        billing_data = json.loads(v[billing_index]) if billing_index is not None and len(v) > billing_index and v[billing_index] else {}
        if not isinstance(billing_data, dict):
            raise StorageError('Neplatné fakturační údaje rezervace.')
        result.append(dict(billing=billing_data, first_name=v[0], last_name=v[1], email=v[2],
                           date_from=start, date_to=end,
                           status=({'Potvrzeno': 'confirmed', **{label: key for key, label in STATUS.items()}}
                                   .get(str(v[5]).strip(), 'pending')),
                           id=rid, created_at=v[7], price=parse_money(v[8]),
                           manager_id=(str(v[manager_index]).strip()
                               if manager_index is not None and len(v) > manager_index else ''),
                           cleaner_email=(str(v[cleaner_index]).strip()
                               if cleaner_index is not None and len(v) > cleaner_index
                               else '')))
    return sorted(result, key=lambda r: r['date_from'])


def _decode_prices(rows):
    result = []
    ids = set()
    for row in rows:
        if not any(str(c).strip() for c in row):
            continue
        v = list(row) + [''] * max(0, 5 - len(row))
        start, end, price = parse_date(v[0]), parse_date(v[1]), parse_money(v[2])
        if ((start is None) != (end is None) or
                (start is not None and end < start) or price is None):
            raise StorageError('Některé cenové období má neplatné datum nebo cenu.')
        rid = str(v[4]).strip()
        if rid and rid in ids:
            raise StorageError('Tabulka obsahuje duplicitní ID cenového období.')
        ids.add(rid)
        result.append(dict(date_from=start, date_to=end, price=price,
                           label=v[3], id=rid))
    if sum(p['date_from'] is None for p in result) > 1:
        raise StorageError('V ceníku je více základních cen. Ponechte pouze jednu.')
    return result


def _db():
    path = Path(os.environ.get('CHALUPA_DB', 'work/reservations.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS records '
               '(kind TEXT, id TEXT PRIMARY KEY, payload TEXT)')
    return db


def _local_rows(kind):
    with _db() as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM records WHERE kind=? ORDER BY rowid', (kind,))]


def _read(kind):
    with _errors():
        import billing
        billing_index = billing.LOCAL_INDEX
        cleaner_index = 9
        manager_index = 10
        if connected():
            if kind == 'res':
                import managers
                _, rows, header = _sheet('Rezervace', RES_HEADER, include_header=True)
                billing_index = header.index(billing.COLUMN) if billing.COLUMN in header else None
                cleaner_index = header.index(CLEANER_COLUMN) if CLEANER_COLUMN in header else None
                manager_index = header.index(managers.COLUMN) if managers.COLUMN in header else None
            else:
                _, rows = _sheet('Cenotvorba', PRICE_HEADER)
        else:
            rows = _local_rows(kind)
        return (_decode_res(rows, cleaner_index, manager_index, billing_index) if kind == 'res'
                else _decode_prices(rows))


def _load(kind, force=False):
    key = '_data_' + kind
    cached = st.session_state.get(key)
    if not force and cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    data = _read(kind)
    st.session_state[key] = (time.monotonic(), data)
    return data


def load_reservations(force=False):
    return _load('res', force)


def load_prices(force=False):
    return _load('prices', force)


def refresh():
    for key in ('_data_res', '_data_prices', '_data_cleaners'):
        st.session_state.pop(key, None)


def add_reservation(first, last, email, start, end, expected_price, request_id, billing_data=None):
    import billing
    if billing_data is not None:
        billing_data = billing.validate(billing_data)
    validate_reservation(first, last, email, start, end)
    with _lock(), _errors():
        if connected():
            sheet, raw = _sheet('Rezervace', RES_HEADER)
            rows = _decode_res(raw)
            if any(r['id'] == request_id for r in rows):
                return request_id
            if conflict(start, end, rows):
                raise StorageError('Termín se mezitím obsadil. Vyberte prosím jiný.')
            price, _ = quote(start, end, load_prices(force=True))
            if price != expected_price:
                raise StorageError('Cena se mezitím změnila. Zkontrolujte nový součet '
                                   'a rezervaci odešlete znovu.')
            import managers
            manager_id = managers.default_id()
            sheet, _, manager_index = managers.reservation_sheet(create=True)
            values = _reservation_values(first, last, email, start, end, price, request_id)
            values += [''] * max(0, manager_index + 1 - len(values))
            values[manager_index] = manager_id
            try:
                import audit
                _, _, header = _sheet('Rezervace', RES_HEADER, include_header=True)
                if billing_data is not None:
                    sheet, _, header = billing.sheet_column()
                    index = header.index(billing.COLUMN)
                    values += [''] * max(0, index + 1 - len(values))
                    values[index] = json.dumps(billing_data, ensure_ascii=False)
                audit.commit([{'appendCells': {'sheetId': sheet.id, 'rows': [{'values': audit.cells(values)}], 'fields': 'userEnteredValue'}}],
                             [audit.event(request_id, None, audit.snapshot(values, header), 'Rezervační formulář')])
            except Exception:
                # Po ztracené odpovědi neopakujeme zápis naslepo.
                if not any(r['id'] == request_id for r in load_reservations(force=True)):
                    raise StorageError('Uložení nelze ověřit. Obnovte data; '
                                       'při opakování se použije stejné ID.') from None
        else:
            with _db() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM records WHERE id=?', (request_id,)).fetchone():
                    return request_id
                raw = [json.loads(r[0]) for r in db.execute(
                    "SELECT payload FROM records WHERE kind='res'")]
                if conflict(start, end, _decode_res(raw)):
                    raise StorageError('Termín se mezitím obsadil. Vyberte prosím jiný.')
                price, _ = quote(start, end, load_prices(force=True))
                if price != expected_price:
                    raise StorageError('Cena se změnila. Zkontrolujte součet a odešlete znovu.')
                import managers
                manager_id = managers.default_id()
                values = _reservation_values(first, last, email, start, end, price, request_id)
                values += ['', manager_id]
                if billing_data is not None:
                    values.append(json.dumps(billing_data, ensure_ascii=False))
                db.execute('INSERT INTO records VALUES (?,?,?)',
                           ('res', request_id, json.dumps(values)))
                import audit
                audit.local(db, request_id, None, values, 'Rezervační formulář')
    refresh()
    return request_id


def _reservation_values(first, last, email, start, end, price, rid):
    return [first.strip(), last.strip(), email.strip(), start.isoformat(),
            end.isoformat(), STATUS['pending'], rid,
            datetime.now(ZoneInfo('Europe/Prague')).isoformat(timespec='seconds'),
            '' if price is None else price]


def _mutate(kind, rid, values=None, status=None, delete=False):
    if not rid:
        raise StorageError('Záznam nemá ID; nejprve jej doplňte ve společné tabulce.')
    with _lock(), _errors():
        if connected():
            name, header, col = ('Rezervace', RES_HEADER, 6) if kind == 'res' else ('Cenotvorba', PRICE_HEADER, 4)
            sheet, rows = _sheet(name, header)
            matches = [i + 2 for i, row in enumerate(rows) if len(row) > col and row[col] == rid]
            if len(matches) > 1:
                raise StorageError('ID není jedinečné. Opravte jej prosím v tabulce.')
            if not matches:
                if delete:
                    return
                if values is not None:
                    sheet.append_row(values, value_input_option='RAW')
                else:
                    raise StorageError('Záznam už neexistuje. Obnovte prosím data.')
            elif kind == 'res':
                import audit
                _, _, headers = _sheet(name, header, include_header=True)
                before = rows[matches[0] - 2]
                after = list(before)
                if delete:
                    requests = [{'deleteDimension': {'range': {'sheetId': sheet.id, 'dimension': 'ROWS', 'startIndex': matches[0]-1, 'endIndex': matches[0]}}}]
                    after = None
                else:
                    after[5] = STATUS[status]
                    requests = [audit.update_cell(sheet, matches[0], 6, STATUS[status])]
                audit.commit(requests, [audit.event(rid, audit.snapshot(before, headers), audit.snapshot(after, headers) if after is not None else None)])
            elif delete:
                sheet.delete_rows(matches[0])
            elif status:
                sheet.update_cell(matches[0], 6, STATUS[status])
            else:
                sheet.update(range_name=f'A{matches[0]}:E{matches[0]}',
                             values=[values], value_input_option='RAW')
        else:
            with _db() as db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT payload FROM records WHERE id=? AND kind=?', (rid, kind)).fetchone()
                before = json.loads(prior[0]) if prior else None
                if delete:
                    db.execute('DELETE FROM records WHERE id=? AND kind=?', (rid, kind))
                elif status:
                    row = db.execute('SELECT payload FROM records WHERE id=? AND kind=?', (rid, kind)).fetchone()
                    if row is None:
                        raise StorageError('Záznam už neexistuje.')
                    payload = json.loads(row[0])
                    payload[5] = STATUS[status]
                    db.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(payload), rid))
                else:
                    db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind, rid, json.dumps(values)))
                if kind == 'res':
                    import audit
                    after = None if delete else payload if status else values
                    audit.local(db, rid, before, after)
    refresh()


def set_status(rid, status):
    if status not in STATUS:
        raise StorageError('Neplatný stav rezervace.')
    import billing
    if billing.enabled():
        return billing.call('status', id=rid, status=STATUS[status])
    import cleaning_mail
    if cleaning_mail.configured():
        return cleaning_mail.call('status', id=rid, status=STATUS[status])
    _mutate('res', rid, status=status)


def delete_reservation(rid):
    import billing
    if billing.enabled():
        return billing.call('delete', id=rid)
    import cleaning_mail
    if cleaning_mail.configured():
        return cleaning_mail.call('delete', id=rid)
    _mutate('res', rid, delete=True)


def save_price(rid, start, end, price, label):
    amount = parse_money(price)
    if amount is None or ((start is None) != (end is None)) or (start and end < start):
        raise StorageError('Zkontrolujte cenu a pořadí dat období.')
    prices = load_prices(force=True)
    if start is None:
        existing = next((p for p in prices if p['date_from'] is None), None)
        if existing:
            if not existing['id']:
                raise StorageError('Základní cena nemá ID. Doplňte jej v tabulce.')
            rid = existing['id']
    if rid and not any(p['id'] == rid for p in prices):
        raise StorageError('Období již neexistuje. Obnovte data.')
    rid = rid or uuid.uuid4().hex[:12]
    _mutate('prices', rid, values=[start.isoformat() if start else '',
            end.isoformat() if end else '', amount, label.strip(), rid])


def delete_price(rid):
    _mutate('prices', rid, delete=True)


# Nový list je samostatný; strukturu rezervací ani ceníku neměníme.
CLEANING_SHEET = 'Úklid'
CLEANING_HEADER = ['Jméno', 'E-mail']


def _cleaning_sheet(create=False, include_header=False):
    document = _document()
    try:
        sheet = document.worksheet(CLEANING_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        if not create:
            return None, []
        try:
            sheet = document.add_worksheet(
                title=CLEANING_SHEET, rows=100, cols=len(CLEANING_HEADER),
            )
        except gspread.exceptions.APIError:
            # List mohl mezitím vzniknout v jiné relaci.
            sheet = document.worksheet(CLEANING_SHEET)
    rows = sheet.get_all_values()
    if not any(str(cell).strip() for row in rows for cell in row):
        rows = []
    if not rows and create:
        sheet.update(range_name='A1:B1', values=[CLEANING_HEADER],
                     value_input_option='RAW')
        rows = [CLEANING_HEADER]
    if not rows:
        return sheet, []
    if rows[0][:2] != CLEANING_HEADER:
        raise StorageError(
            'List Úklid nemá očekávané sloupce Jméno a E-mail. '
            'Existující obsah nebyl změněn.'
        )
    return (sheet, rows[1:], rows[0]) if include_header else (sheet, rows[1:])


def ensure_cleaning_sheet():
    """Při nasazení nebo prvním přidání založí pouze nový list Úklid."""
    if connected():
        with _lock(), _errors():
            _cleaning_sheet(create=True)


def _decode_cleaners(rows, status_index=None):
    people = []
    for row in rows:
        if not any(str(value).strip() for value in row):
            continue
        values = list(row) + [''] * max(0, 2 - len(row))
        person = {'name': str(values[0]).strip(), 'email': str(values[1]).strip()}
        if status_index is not None:
            person['mail_status'] = (str(values[status_index]).strip()
                                     if len(values) > status_index else '') or 'Přihlášeno'
        people.append(person)
    return sorted(people, key=lambda person: person['name'].casefold())


def load_cleaners(force=False):
    cached = st.session_state.get('_data_cleaners')
    if not force and cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    with _errors():
        if connected():
            result = _cleaning_sheet(include_header=True)
            _, rows = result[:2]
            header = result[2] if len(result) > 2 else []
            status_index = header.index('E-mailing') if 'E-mailing' in header else None
        else:
            rows = _local_rows('cleaners')
            status_index = None
        people = _decode_cleaners(rows, status_index)
    st.session_state['_data_cleaners'] = (time.monotonic(), people)
    return people


def refresh_cleaners():
    st.session_state.pop('_data_cleaners', None)


def add_cleaner(name, email):
    """Přidá kontakt, stejný e-mail nesmí být v týmu dvakrát."""
    import re
    name, email = name.strip(), email.strip()
    if not name or len(name) > 100:
        raise StorageError('Zadejte jméno o délce 1 až 100 znaků.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise StorageError('Zadejte prosím platnou e-mailovou adresu.')
    with _lock(), _errors():
        if connected():
            sheet, rows = _cleaning_sheet(create=True)
            people = _decode_cleaners(rows)
            if any(p['email'].casefold() == email.casefold() for p in people):
                raise StorageError('Kontakt s tímto e-mailem už v týmu je.')
            try:
                sheet.append_row([name, email], value_input_option='RAW')
            except Exception:
                # Po ztracené odpovědi nejprve ověříme skutečný zápis.
                people = load_cleaners(force=True)
                if not any(p['email'].casefold() == email.casefold()
                           and p['name'] == name for p in people):
                    raise StorageError(
                        'Uložení kontaktu nelze ověřit. Obnovte seznam '
                        'a před dalším pokusem zkontrolujte, zda už je v týmu.'
                    ) from None
        else:
            with _db() as db:
                db.execute('BEGIN IMMEDIATE')
                rows = [json.loads(r[0]) for r in db.execute(
                    "SELECT payload FROM records WHERE kind='cleaners'")]
                if any(p['email'].casefold() == email.casefold()
                       for p in _decode_cleaners(rows)):
                    raise StorageError('Kontakt s tímto e-mailem už v týmu je.')
                db.execute('INSERT INTO records VALUES (?,?,?)',
                           ('cleaners', uuid.uuid4().hex,
                            json.dumps([name, email])))
    refresh_cleaners()


CLEANER_COLUMN = 'Úklid - e-mail'


def _reservation_assignment_sheet(create=False):
    sheet, rows, header = _sheet('Rezervace', RES_HEADER, include_header=True)
    if header.count(CLEANER_COLUMN) > 1:
        raise StorageError('Sloupec Úklid - e-mail je v tabulce vícekrát.')
    if CLEANER_COLUMN in header:
        return sheet, rows, header.index(CLEANER_COLUMN)
    if not create:
        return sheet, rows, None
    # Nepřesouváme původní sloupce ani nepřepíšeme data bez hlavičky.
    index = max([len(header)] + [len(row) for row in rows])
    if index >= sheet.col_count:
        sheet.add_cols(index + 1 - sheet.col_count)
    sheet.update(range_name=gspread.utils.rowcol_to_a1(1, index + 1),
                 values=[[CLEANER_COLUMN]], value_input_option='RAW')
    return sheet, rows, index


def ensure_cleaning_storage():
    """Připraví nový seznam a sloupec pro přiřazení bez změny dat pobytů."""
    if connected():
        with _lock(), _errors():
            _cleaning_sheet(create=True)
            _reservation_assignment_sheet(create=True)


def assign_cleaner(reservation_id, email):
    """Přiřadí jeden kontakt k úklidu po pobytu; prázdný e-mail jej zruší."""
    if not reservation_id:
        raise StorageError('Rezervace nemá ID. Doplňte jej nejprve v tabulce.')
    email = (email or '').strip()
    import cleaning_mail
    if cleaning_mail.configured():
        return cleaning_mail.call('assign', id=reservation_id, email=email)
    with _lock(), _errors():
        if email:
            person = next((p for p in load_cleaners(force=True)
                           if p['email'].casefold() == email.casefold()), None)
            if person is None:
                raise StorageError('Kontakt už není v týmu. Obnovte seznam.')
            email = person['email']
        if connected():
            sheet, rows, index = _reservation_assignment_sheet(create=True)
            matches = [i + 2 for i, row in enumerate(rows)
                       if len(row) > 6 and str(row[6]).strip() == reservation_id]
            if len(matches) != 1:
                raise StorageError(
                    'Rezervace nebyla jednoznačně nalezena. Obnovte data.'
                )
            import audit
            old = rows[matches[0]-2]
            before = {CLEANER_COLUMN: old[index] if len(old) > index else ''}
            audit.commit([audit.update_cell(sheet, matches[0], index+1, email)],
                         [audit.event(reservation_id, before, {CLEANER_COLUMN: email})])
        else:
            with _db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute(
                    'SELECT payload FROM records WHERE kind=? AND id=?',
                    ('res', reservation_id),
                ).fetchone()
                if row is None:
                    raise StorageError('Rezervace už neexistuje. Obnovte data.')
                values = json.loads(row[0])
                before = list(values)
                values += [''] * max(0, 10 - len(values))
                values[9] = email
                db.execute('UPDATE records SET payload=? WHERE id=?',
                           (json.dumps(values), reservation_id))
                import audit
                audit.local(db, reservation_id, before, values)
    refresh()
