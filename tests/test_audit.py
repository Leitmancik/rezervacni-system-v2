import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock
import json
import test_app
import storage
import managers
import audit
from domain import today

class AuditTests(unittest.TestCase):
    setUp = test_app.StorageTests.setUp
    tearDown = test_app.StorageTests.tearDown

    def test_create_changes_noop_and_deletion_snapshot(self):
        day=today()+timedelta(days=2)
        storage.add_reservation('Host','Test','h@example.com',day,day+timedelta(days=1),None,'stay')
        storage.add_reservation('Host','Test','h@example.com',day,day+timedelta(days=1),None,'stay')
        storage.set_status('stay','confirmed')
        storage.set_status('stay','confirmed')
        second=managers.add('Second','s@example.com')
        managers.assign('stay',second)
        storage.add_cleaner('Cleaner','c@example.com')
        storage.assign_cleaner('stay','c@example.com')
        storage.delete_reservation('stay')
        storage.delete_reservation('stay')
        events=audit.load()[::-1]
        self.assertEqual([e[3] for e in events],['Vytvoření','Změna','Změna','Změna','Smazání'])
        self.assertEqual(json.loads(events[1][6]),{'Stav':'Potvrzeno - čeká na zaplacení'})
        deleted=json.loads(events[-1][5])
        self.assertEqual(deleted['Úklid - e-mail'],'c@example.com')
        self.assertEqual(deleted['Správce ID'],second)
        self.assertEqual(deleted['email'],'h@example.com')
        self.assertEqual(storage.load_reservations(True),[])

    def test_limit_keeps_latest_thousand_and_transaction_rolls_back(self):
        with storage._db() as db:
            for i in range(1005):
                audit.local(db,str(i),None,[str(i)])
        self.assertEqual(len(audit.load()),1000)
        self.assertEqual(audit.load()[0][2],'1004')
        self.assertEqual(audit.load()[-1][2],'5')
        day=today()+timedelta(days=2)
        with patch.object(audit,'local',side_effect=RuntimeError('fail')):
            with self.assertRaises(storage.StorageError):
                storage.add_reservation('Host','Test','h@example.com',day,day+timedelta(days=1),None,'failed')
        self.assertEqual(storage.load_reservations(True),[])

    def test_google_commit_is_single_batch_including_retention(self):
        sheet=MagicMock(); sheet.id=9
        book=MagicMock()
        event=audit.event('stay',{'Stav':'old'},{'Stav':'new'})
        change={'updateCells':{'range':{'sheetId':2}}}
        with patch.object(audit,'_sheet',return_value=(sheet,[['old']]*1000)), patch.object(storage,'_document',return_value=book):
            audit.commit([change],[event])
        book.batch_update.assert_called_once()
        requests=book.batch_update.call_args.args[0]['requests']
        self.assertEqual(requests[0],change)
        self.assertEqual(requests[1]['appendCells']['sheetId'],9)
        self.assertEqual(requests[2]['deleteDimension']['range']['startIndex'],1)
        self.assertEqual(requests[2]['deleteDimension']['range']['endIndex'],2)
