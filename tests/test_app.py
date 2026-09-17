"""Regrese cen, navazujících pobytů a rezervačního toku."""
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
os.environ['CHALUPA_DEMO'] = '1'
from domain import conflict, half_states, quote, today, parse_money, StorageError, validate_reservation, created_label
import storage

class DomainTests(unittest.TestCase):
    def test_turnover(self):
        r = dict(date_from=date(2030, 1, 2), date_to=date(2030, 1, 5), status='confirmed')
        self.assertIsNone(conflict(date(2030, 1, 5), date(2030, 1, 7), [r]))
        self.assertIsNotNone(conflict(date(2030, 1, 4), date(2030, 1, 7), [r]))
        self.assertEqual(half_states(date(2030, 1, 2), [r]), ('free', 'confirmed'))
        self.assertEqual(half_states(date(2030, 1, 5), [r]), ('confirmed', 'free'))

    def test_creation_time_precision_and_timezone(self):
        self.assertEqual(created_label('2030-07-02T12:34:56+00:00'),
                         '02. 07. 2030 · 14:34:56')
        self.assertEqual(created_label('2030-01-02T12:34:56+00:00'),
                         '02. 01. 2030 · 13:34:56')
        self.assertIn('sekundy nejsou uložené', created_label('2030-01-02 12:34'))
        self.assertEqual(created_label(''), 'Čas vytvoření není uložen')
        self.assertEqual(created_label('2026-09-15 5:12:34'), '15. 09. 2026 · 05:12:34')

    def test_legacy_and_new_statuses(self):
        for label, expected in [('Potvrzeno', 'confirmed'),
                                ('Potvrzeno - čeká na zaplacení', 'confirmed'),
                                ('Zaplaceno', 'paid'), ('Čeká na potvrzení', 'pending')]:
            row = ['Test', 'Host', 'test@example.com', '2030-01-02',
                   '2030-01-04', label, 'id', '2030-01-01T12:34:56+01:00', 3000]
            reservation = storage._decode_res([row])[0]
            self.assertEqual(reservation['status'], expected)
            self.assertIsNotNone(conflict(date(2030, 1, 3), date(2030, 1, 5), [reservation]))

    def test_seasons(self):
        p = [dict(date_from=None, date_to=None, price=100),
             dict(date_from=date(2030, 1, 1), date_to=date(2030, 1, 31), price=200),
             dict(date_from=date(2030, 1, 5), date_to=date(2030, 1, 5), price=300)]
        self.assertEqual(quote(date(2030, 1, 4), date(2030, 1, 7), p)[0], 700)
        self.assertEqual(quote(date(2030, 1, 31), date(2030, 2, 2), p)[0], 300)
        self.assertIsNone(quote(date(2030, 1, 1), date(2030, 1, 2), [])[0])

    def test_money(self):
        for text, value in [('15 000 Kč',15000),('15.000',15000),('1500,50',1500.5)]:
            self.assertEqual(parse_money(text), value)
        for value in ('nan', '-100', 'abc'):
            with self.assertRaises(StorageError): parse_money(value)

    def test_validation(self):
        start = today() + timedelta(days=1)
        for first, last, email, end in [('', 'Host', 'test@example.com', start+timedelta(days=1)), ('Test', 'Host', 'bad', start+timedelta(days=1)), ('Test', 'Host', 'test@example.com', start)]:
            with self.assertRaises(StorageError):
                validate_reservation(first, last, email, start, end)

    def test_invalid_rows_fail_closed(self):
        with self.assertRaises(StorageError):
            storage._decode_res([['Host', 'Test', '', 'chyba', '2030-01-02']])
        with self.assertRaises(StorageError):
            storage._decode_prices([['2030-01-02', '', 2000, 'Sezóna', 'id']])

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, CHALUPA_DB=self.tmp.name + '/test.sqlite3')
        self.env.start()
        storage.refresh()
        import managers
        managers.add('Test správce', 'manager@example.com')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        storage.refresh()

    def test_write_flow_and_snapshot(self):
        start, end = today()+timedelta(days=3), today()+timedelta(days=5)
        storage.save_price(None, None, None, 2500, 'Základ')
        for _ in range(2):
            storage.add_reservation('Test', 'Host', 'test@example.com', start, end, 5000, 'r1')
        self.assertEqual(len(storage.load_reservations(True)), 1)
        with self.assertRaises(StorageError):
            storage.add_reservation('Test', 'Host', 'test@example.com', start, end, 5000, 'r2')
        storage.set_status('r1', 'confirmed')
        storage.save_price(None, None, None, 3000, 'Základ')
        self.assertEqual(storage.load_reservations(True)[0]['price'], 5000)
        self.assertEqual(storage.load_reservations(True)[0]['status'], 'confirmed')
        storage.add_reservation('Test', 'Host', 'test@example.com', end, end+timedelta(days=1), 3000, 'r3')
        storage.delete_reservation('r1')
        storage.delete_reservation('r1')
        self.assertEqual(len(storage.load_reservations(True)), 1)

    def test_stale_price(self):
        storage.save_price(None, None, None, 3000, 'Základ')
        start = today()+timedelta(days=5)
        with self.assertRaises(StorageError):
            storage.add_reservation('Test', 'Host', 'test@example.com', start, start+timedelta(days=1), 2500, 'r1')
        self.assertEqual(storage.load_reservations(True), [])

    def test_live_fresh_check_and_raw_write(self):
        start = today()+timedelta(days=5)
        sheet = MagicMock()
        with patch('managers.default_id', return_value='manager'), patch('managers.reservation_sheet', return_value=(sheet, [], 11)), patch.object(storage, 'connected', return_value=True), patch.object(storage, '_sheet', return_value=(sheet, [])) as read, patch.object(storage, 'load_prices', return_value=[]) as prices:
            storage.add_reservation('=formula', 'Host', 'test@example.com', start, start+timedelta(days=1), None, 'r4')
        self.assertEqual(sheet.append_row.call_args.args[0][11], 'manager')
        read.assert_called_once_with('Rezervace', storage.RES_HEADER)
        prices.assert_called_once_with(force=True)
        self.assertEqual(sheet.append_row.call_args.kwargs['value_input_option'], 'RAW')

    def test_missing_price_id_renders_without_duplicate_forms(self):
        from streamlit.testing.v1 import AppTest
        import json
        with storage._db() as db:
            db.execute('INSERT INTO records VALUES (?,?,?)', ('prices', 'localrow', json.dumps(['2030-01-01', '2030-01-05', 1000, 'Bez ID', ''])))
        app = AppTest.from_string('import page_pricing\npage_pricing.render()', default_timeout=30).run()
        self.assertFalse(app.exception)

    def test_multiple_status_filter(self):
        from streamlit.testing.v1 import AppTest
        start = today() + timedelta(days=10)
        for index, status in enumerate(('pending', 'confirmed', 'paid')):
            arrival = start + timedelta(days=index * 3)
            rid = f'filter-{index}'
            storage.add_reservation('Test', 'Host', 'test@example.com',
                                    arrival, arrival + timedelta(days=1), None, rid)
            storage.set_status(rid, status)
        app = AppTest.from_string('import page_reservations\npage_reservations.render()', default_timeout=30).run()
        for selection, count in [([], 3), (['Čeká na potvrzení', 'Zaplaceno'], 2),
                                 (['Potvrzeno - čeká na zaplacení'], 1), ([], 3)]:
            app.multiselect[0].set_value(selection).run()
            self.assertFalse(app.exception)
            self.assertEqual(len([s for s in app.selectbox if s.label == 'Stav rezervace']), count)

    def test_ui_guest_and_admin(self):
        from streamlit.testing.v1 import AppTest
        storage.save_price(None, None, None, 2000, 'Základ')
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'), default_timeout=30).run()
        self.assertFalse(at.exception)
        start, end = today()+timedelta(days=1), today()+timedelta(days=3)
        next(b for b in at.button if b.key and b.key.startswith('day-'+start.isoformat())).click().run()
        next(b for b in at.button if b.key and b.key.startswith('day-'+end.isoformat())).click().run()
        self.assertEqual(at.date_input(key='arrival').value, start)
        self.assertEqual(at.date_input(key='departure').value, end)
        for field, value in zip(at.text_input, ['Test', 'Host', 'test@example.com']): field.input(value)
        next(b for b in at.button if b.label == 'Odeslat žádost o rezervaci').click().run()
        self.assertFalse(at.exception)
        self.assertTrue(at.success)
        self.assertEqual(len(storage.load_reservations(True)), 1)
        self.assertEqual(storage.load_reservations(True)[0]['price'], 4000)
        admin = AppTest.from_string('import page_reservations\npage_reservations.render()', default_timeout=30).run()
        self.assertFalse(admin.exception)
        next(s for s in admin.selectbox if s.label == 'Stav rezervace').select('confirmed').run()
        self.assertFalse(admin.exception)
        self.assertEqual(storage.load_reservations(True)[0]['status'], 'confirmed')
        original = storage.load_reservations(True)[0]
        for state in ('paid', 'pending', 'confirmed', 'paid'):
            next(s for s in admin.selectbox if s.label == 'Stav rezervace').select(state).run()
            self.assertFalse(admin.exception)
            current = storage.load_reservations(True)[0]
            self.assertEqual(current['status'], state)
            self.assertEqual(current['created_at'], original['created_at'])
            self.assertEqual(current['price'], original['price'])
        admin.multiselect[0].set_value(['Zaplaceno']).run()
        self.assertFalse(admin.exception)
        self.assertEqual(len([s for s in admin.selectbox if s.label == 'Stav rezervace']), 1)
        calendar = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'), default_timeout=30).run()
        self.assertFalse(calendar.exception)
        from page_reservations import export_frame
        exported = export_frame([current])
        self.assertEqual(exported.iloc[0]['Stav'], 'Zaplaceno')
        self.assertEqual(exported.iloc[0]['Vytvořeno'], original['created_at'])
        prices = AppTest.from_string('import page_pricing\npage_pricing.render()', default_timeout=30).run()
        self.assertFalse(prices.exception)

    def test_progressive_form_and_month_navigation(self):
        from streamlit.testing.v1 import AppTest
        from domain import shift_month
        storage.save_price(None, None, None, 2000, 'Základ')
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'), default_timeout=30).run()
        self.assertEqual(len(app.text_input), 0)
        # A small screen shows one month, so a cross-month stay needs navigation.
        end = shift_month(today().replace(day=1), 2)
        start = end - timedelta(days=1)
        app.button(key='next_month').click().run()
        next(b for b in app.button if b.key and b.key.startswith('day-'+start.isoformat())).click().run()
        self.assertEqual(len(app.text_input), 0)
        app.button(key='next_month').click().run()
        next(b for b in app.button if b.key and b.key.startswith('day-'+end.isoformat())).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.date_input(key='arrival').value, start)
        self.assertEqual(app.date_input(key='departure').value, end)
        self.assertEqual(len(app.text_input), 3)
        next(b for b in app.button if b.label == 'Vybrat jiný termín').click().run()
        self.assertIsNone(app.date_input(key='arrival').value)
        self.assertIsNone(app.date_input(key='departure').value)
        self.assertEqual(len(app.text_input), 0)

if __name__ == '__main__': unittest.main()
