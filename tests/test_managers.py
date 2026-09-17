import json
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch
import test_app
import managers
import storage
from domain import today, StorageError


class ManagerTests(unittest.TestCase):
    setUp = test_app.StorageTests.setUp
    tearDown = test_app.StorageTests.tearDown

    def test_default_change_keeps_assignments_and_new_stays_use_new_default(self):
        first = managers.default_id()
        day = today() + timedelta(days=2)
        storage.add_reservation('Host', 'Test', 'a@example.com', day, day+timedelta(days=1), None, 'old')
        second = managers.add('Druhý správce', 'second@example.com')
        managers.set_default(second)
        storage.add_reservation('Host', 'Test', 'a@example.com', day+timedelta(days=2), day+timedelta(days=3), None, 'new')
        rows = storage.load_reservations(True)
        self.assertEqual([r['manager_id'] for r in rows], [first, second])
        managers.assign('old', second)
        self.assertEqual(storage.load_reservations(True)[0]['manager_id'], second)
        for invalid in ['', 'missing']:
            with self.assertRaises(StorageError):
                managers.assign('old', invalid)
        with self.assertRaises(StorageError):
            managers.add('Duplicitní', 'SECOND@example.com')

    def test_backfill_preserves_cleaner_and_other_values(self):
        values = ['Host','Test','a@example.com','2030-01-01','2030-01-02','Zaplaceno','legacy','created',2500,'cleaner@example.com']
        with storage._db() as db:
            db.execute('INSERT INTO records VALUES (?,?,?)', ('res','legacy',json.dumps(values)))
        managers.backfill()
        managers.backfill()
        raw = storage._local_rows('res')[0]
        self.assertEqual(raw[:10], values)
        self.assertEqual(raw[10], managers.default_id())

    def test_missing_default_blocks_new_booking(self):
        with storage._db() as db:
            db.execute("DELETE FROM records WHERE kind='manager_settings'")
        day = today() + timedelta(days=2)
        with self.assertRaises(StorageError):
            storage.add_reservation('Host','Test','a@example.com',day,day+timedelta(days=1),None,'missing')
        self.assertEqual(storage.load_reservations(True), [])

    def test_header_lookup_and_backfill_write_only_empty_manager_cells(self):
        sheet = MagicMock()
        rows = [['Host','Test','a@example.com','2030-01-01','2030-01-02','Zaplaceno','stay','','', 'cleaner', 'note', ''],
                ['Host','Test','a@example.com','2030-02-01','2030-02-02','Zaplaceno','stay2','','','cleaner2','note2','other']]
        with patch('audit.commit') as audit_commit, patch.object(storage,'connected',return_value=True), patch.object(managers,'default_id',return_value='default'), patch.object(managers,'reservation_sheet',return_value=(sheet,rows,11)):
            managers.backfill()
        requests, events = audit_commit.call_args.args
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['updateCells']['range']['startRowIndex'], 1)
        self.assertEqual(requests[0]['updateCells']['range']['startColumnIndex'], 11)
        self.assertEqual(events[0][2], 'stay')
        decoded = storage._decode_res(rows,9,11)
        self.assertEqual(decoded[1]['manager_id'],'other')
        self.assertEqual(decoded[1]['cleaner_email'],'cleaner2')

    def test_ui_add_and_set_default(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('import page_managers\npage_managers.render()').run()
        app.text_input(key='manager_name').input('Nový správce')
        app.text_input(key='manager_email').input('new@example.com')
        next(b for b in app.button if b.label=='Přidat správce').click().run()
        self.assertFalse(app.exception)
        new = next(p for p in managers.load()[0] if p['email']=='new@example.com')
        app.selectbox[0].select(new['id'])
        next(b for b in app.button if b.label=='Nastavit výchozího správce').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(managers.default_id(),new['id'])

    def test_empty_google_sheet_is_initialized_and_can_be_read_before_setup(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [[]]
        book = MagicMock()
        book.worksheet.return_value = sheet
        with patch.object(storage, '_document', return_value=book):
            self.assertEqual(managers._sheet(), (sheet, [], ''))
            self.assertEqual(managers._sheet(create=True), (sheet, [], ''))
        sheet.update.assert_called_once_with(range_name='A1:D1', values=[managers.HEADER], value_input_option='RAW')
