"""Omezený protokol změn. Zápis rezervace a historie je jedna atomická operace."""
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import gspread
import storage

TITLE = 'Historie rezervací'
HEADER = ['Čas (Praha)', 'ID události', 'ID rezervace', 'Událost', 'Zdroj', 'Původní hodnoty', 'Nové hodnoty']
LIMIT = 1000
LOCAL_HEADER = storage.RES_HEADER + ['Úklid - e-mail', 'Správce ID']


def event(rid, before, after, source='Aplikace · bez přihlášení', initial=False):
    before, after = before or {}, after or {}
    if before == after:
        return None
    kind = 'Výchozí stav' if initial else 'Vytvoření' if not before else 'Smazání' if not after else 'Změna'
    if before and after:
        keys = [k for k in dict.fromkeys([*before, *after]) if before.get(k, '') != after.get(k, '')]
        if not keys:
            return None
        before, after = ({k: d.get(k, '') for k in keys} for d in (before, after))
    return [datetime.now(ZoneInfo('Europe/Prague')).isoformat(timespec='milliseconds'), uuid.uuid4().hex,
            rid, kind, source, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)]


def snapshot(values, header=None):
    header = header or LOCAL_HEADER
    return {name: str(values[i]) if i < len(values) else '' for i, name in enumerate(header) if name}


def cells(values):
    return [{'userEnteredValue': {'numberValue': v} if isinstance(v, (int, float))
             else {'stringValue': str(v)}} for v in values]


def update_cell(sheet, row, column, value):
    return {'updateCells': {'range': {'sheetId': sheet.id, 'startRowIndex': row - 1, 'endRowIndex': row,
                                    'startColumnIndex': column - 1, 'endColumnIndex': column},
                            'rows': [{'values': cells([value])}], 'fields': 'userEnteredValue'}}


def _sheet(create=False):
    book = storage._document()
    try:
        sheet = book.worksheet(TITLE)
    except gspread.exceptions.WorksheetNotFound:
        if not create:
            return None, []
        try:
            sheet = book.add_worksheet(title=TITLE, rows=LIMIT + 1, cols=len(HEADER))
        except gspread.exceptions.APIError:
            sheet = book.worksheet(TITLE)
    rows = sheet.get_all_values()
    if not any(any(r) for r in rows):
        if not create:
            return sheet, []
        sheet.update(range_name='A1:G1', values=[HEADER], value_input_option='RAW')
        sheet.freeze(rows=1)
        rows = [HEADER]
    if rows[0] != HEADER:
        raise storage.StorageError('List Historie rezervací má neočekávané sloupce. Změna nebyla provedena.')
    return sheet, rows[1:]


def commit(requests, events):
    """Google Sheets aplikuje datový zápis, audit i ořez v jednom batchUpdate."""
    events = [e for e in events if e]
    if not requests and not events:
        return
    sheet, rows = _sheet(create=True)
    if events:
        requests = requests + [{'appendCells': {'sheetId': sheet.id,
                     'rows': [{'values': cells(e)} for e in events], 'fields': 'userEnteredValue'}}]
        overflow = len(rows) + len(events) - LIMIT
        if overflow > 0:
            requests += [{'deleteDimension': {'range': {'sheetId': sheet.id, 'dimension': 'ROWS',
                                                      'startIndex': 1, 'endIndex': overflow + 1}}}]
    storage._document().batch_update({'requests': requests})


def local(db, rid, before, after, source='Aplikace · bez přihlášení'):
    e = event(rid, snapshot(before) if before is not None else None,
              snapshot(after) if after is not None else None, source)
    if e:
        db.execute('INSERT INTO records VALUES (?,?,?)', ('history', e[1], json.dumps(e)))
        db.execute("DELETE FROM records WHERE kind='history' AND rowid NOT IN "
                   "(SELECT rowid FROM records WHERE kind='history' ORDER BY rowid DESC LIMIT ?)", (LIMIT,))


def load():
    with storage._errors():
        if storage.connected():
            return _sheet()[1][-LIMIT:][::-1]
        return storage._local_rows('history')[-LIMIT:][::-1]
