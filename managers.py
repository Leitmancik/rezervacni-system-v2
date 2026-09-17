"""Správci a trvalé přiřazení k rezervaci; bez odesílání e-mailů."""
import json
import re
import uuid
import gspread
import storage
from domain import StorageError

HEADER = ['ID', 'Jméno', 'E-mail', 'Výchozí správce ID']
COLUMN = 'Správce ID'


def _sheet(create=False):
    try:
        sheet = storage._document().worksheet('Správci')
    except gspread.exceptions.WorksheetNotFound:
        if not create:
            return None, [], ''
        sheet = storage._document().add_worksheet(title='Správci', rows=100, cols=4)
    raw = sheet.get_all_values()
    if not any(str(cell).strip() for row in raw for cell in row):
        raw = []
    if not raw and not create:
        return sheet, [], ''
    if not raw and create:
        sheet.update(range_name='A1:D1', values=[HEADER], value_input_option='RAW')
        raw = [HEADER]
    if not raw or raw[0][:4] != HEADER:
        raise StorageError('List Správci nemá očekávané sloupce. Existující obsah nebyl změněn.')
    people = [dict(id=r[0], name=r[1], email=r[2]) for r in raw[1:] if len(r) >= 3 and r[0]]
    default = raw[1][3] if len(raw) > 1 and len(raw[1]) > 3 else ''
    return sheet, people, default


def load():
    with storage._errors():
        if storage.connected():
            _, people, default = _sheet()
        else:
            people = storage._local_rows('managers')
            settings = storage._local_rows('manager_settings')
            default = settings[0]['default'] if settings else ''
        if len({p['id'] for p in people}) != len(people):
            raise StorageError('Seznam správců obsahuje duplicitní ID.')
        return people, default


def default_id():
    people, default = load()
    if not default or not any(p['id'] == default for p in people):
        raise StorageError('Nejdříve nastavte výchozího správce na záložce Správce.')
    return default


def reservation_sheet(create=False):
    sheet, rows, header = storage._sheet('Rezervace', storage.RES_HEADER, include_header=True)
    if header.count(COLUMN) > 1:
        raise StorageError('Sloupec Správce ID je v tabulce vícekrát.')
    index = header.index(COLUMN) if COLUMN in header else None
    if index is None and create:
        index = max([len(header)] + [len(r) for r in rows])
        if index >= sheet.col_count:
            sheet.add_cols(index + 1 - sheet.col_count)
        sheet.update(range_name=gspread.utils.rowcol_to_a1(1, index + 1),
                     values=[[COLUMN]], value_input_option='RAW')
    return sheet, rows, index


def add(name, email):
    name, email = name.strip(), email.strip().lower()
    if not name or len(name) > 100:
        raise StorageError('Zadejte jméno o délce 1 až 100 znaků.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise StorageError('Zadejte platný e-mail správce.')
    with storage._lock(), storage._errors():
        people, default = load()
        if any(p['email'].casefold() == email.casefold() for p in people):
            raise StorageError('Správce s tímto e-mailem už existuje.')
        person = dict(id=uuid.uuid4().hex, name=name, email=email)
        if storage.connected():
            sheet, _, _ = _sheet(create=True)
            sheet.append_row(list(person.values()), value_input_option='RAW')
        else:
            with storage._db() as db:
                db.execute('INSERT INTO records VALUES (?,?,?)', ('managers', person['id'], json.dumps(person)))
        if not default:
            set_default(person['id'])
    return person['id']


def set_default(manager_id):
    with storage._lock(), storage._errors():
        _validate(manager_id)
        if storage.connected():
            sheet, _, _ = _sheet()
            sheet.update(range_name='D2', values=[[manager_id]], value_input_option='RAW')
        else:
            with storage._db() as db:
                db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)',
                           ('manager_settings', 'manager-default', json.dumps({'default': manager_id})))
        backfill()
    storage.refresh()


def _validate(manager_id):
    if not manager_id or not any(p['id'] == manager_id for p in load()[0]):
        raise StorageError('Vyberte existujícího správce.')


def backfill():
    """Doplní pouze prázdná přiřazení. Změna výchozího nepřepisuje historii."""
    with storage._lock(), storage._errors():
        manager_id = default_id()
        if storage.connected():
            sheet, rows, index = reservation_sheet(create=True)
            changes = [{'range': gspread.utils.rowcol_to_a1(i + 2, index + 1), 'values': [[manager_id]]}
                       for i, r in enumerate(rows) if any(r) and (len(r) <= index or not r[index].strip())]
            if changes:
                sheet.batch_update(changes, value_input_option='RAW')
        else:
            with storage._db() as db:
                db.execute('BEGIN IMMEDIATE')
                for rid, raw in db.execute("SELECT id,payload FROM records WHERE kind='res'").fetchall():
                    values = json.loads(raw)
                    values += [''] * max(0, 11 - len(values))
                    if not values[10]:
                        values[10] = manager_id
                        db.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(values), rid))
    storage.refresh()


def assign(reservation_id, manager_id):
    with storage._lock(), storage._errors():
        _validate(manager_id)
        if not reservation_id:
            raise StorageError('Rezervace nemá ID.')
        if storage.connected():
            sheet, rows, index = reservation_sheet(create=True)
            matches = [i + 2 for i, r in enumerate(rows) if len(r) > 6 and r[6] == reservation_id]
            if len(matches) != 1:
                raise StorageError('Rezervace nebyla jednoznačně nalezena. Obnovte data.')
            sheet.update(range_name=gspread.utils.rowcol_to_a1(matches[0], index + 1),
                         values=[[manager_id]], value_input_option='RAW')
        else:
            with storage._db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT payload FROM records WHERE kind='res' AND id=?", (reservation_id,)).fetchone()
                if row is None:
                    raise StorageError('Rezervace už neexistuje.')
                values = json.loads(row[0])
                values += [''] * max(0, 11 - len(values))
                values[10] = manager_id
                db.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(values), reservation_id))
    storage.refresh()
