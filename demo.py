"""Vytvoří ukázková data výhradně v místní SQLite databázi."""
import os
os.environ['CHALUPA_DEMO'] = '1'
import json
from datetime import timedelta
from domain import today
import storage

if __name__ == '__main__':
    day = today()
    with storage._db() as db:
        for kind, rid, values in [
            ('prices', 'demo-base', ['', '', 2900, 'Základní cena', 'demo-base']),
            ('res', 'demo-stay-1', ['Ukázkový', 'Host', 'host@example.com',
             (day+timedelta(days=5)).isoformat(), (day+timedelta(days=9)).isoformat(),
             'Potvrzeno', 'demo-stay-1', day.isoformat(), 11600]),
            ('res', 'demo-stay-2', ['Ukázková', 'Rezervace', 'pobyt@example.com',
             (day+timedelta(days=13)).isoformat(), (day+timedelta(days=16)).isoformat(),
             'Čeká na potvrzení', 'demo-stay-2', day.isoformat(), 8700]),
        ]:
            db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?)', (kind, rid, json.dumps(values)))
    import managers
    if not managers.load()[0]:
        managers.add('Ukázkový správce', 'spravce@example.com')
    else:
        managers.backfill()
    print('Ukázková data jsou připravena v místní SQLite databázi.')
