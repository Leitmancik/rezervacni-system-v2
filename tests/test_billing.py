"""Fakturační data, ochrana správy a směrování potvrzení bez živých dokladů."""
import json
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock
os.environ['CHALUPA_DEMO'] = '1'
import storage
import billing
from domain import today, StorageError, STATUS

ADDRESS = dict(street='Testovací 12', city='Praha', zip='110 00', country='CZ', on_company=False)


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, CHALUPA_DB=self.tmp.name + '/db.sqlite3')
        self.env.start(); storage.refresh()
        import managers
        managers.add('Správce', 'manager@example.com')

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup(); storage.refresh()

    def add(self, data=None):
        start = today() + timedelta(days=5)
        storage.save_price(None, None, None, 2500, 'Cena')
        return storage.add_reservation('Test', 'Host', 'guest@example.com', start,
                                       start + timedelta(days=2), 5000, 'billing-test', billing_data=data)

    def test_address_survives_storage_status_assignment_and_audit(self):
        rid = self.add(ADDRESS)
        storage.set_status(rid, 'confirmed')
        storage.add_cleaner('Úklid', 'clean@example.com')
        storage.assign_cleaner(rid, 'clean@example.com')
        current = storage.load_reservations(True)[0]
        self.assertEqual(current['billing']['street'], ADDRESS['street'])
        self.assertEqual(current['price'], 5000)
        self.assertEqual(current['cleaner_email'], 'clean@example.com')
        import audit
        creation = next(e for e in audit.load() if e[3] == 'Vytvoření')
        self.assertEqual(json.loads(json.loads(creation[6])[billing.COLUMN])['city'], 'Praha')

    def test_company_keeps_ico_as_text(self):
        data = billing.validate(dict(ADDRESS, on_company=True, company='Test s.r.o.', registration_no='01234567', vat_no='CZ01234567'))
        self.add(data)
        self.assertEqual(storage.load_reservations(True)[0]['billing']['registration_no'], '01234567')

    def test_person_discards_unchecked_company_fields(self):
        data = billing.validate(dict(ADDRESS, company='Ignorovat', registration_no='12345678'))
        self.assertEqual(data['company'], '')
        self.assertEqual(data['registration_no'], '')

    def test_missing_and_invalid_fields_block_booking(self):
        for data in ({}, dict(ADDRESS, zip='bad'), dict(ADDRESS, on_company=True), dict(ADDRESS, country='CZE')):
            with self.assertRaises(StorageError): self.add(data)
        self.assertEqual(storage.load_reservations(True), [])

    def test_legacy_can_be_completed(self):
        rid = self.add()
        self.assertEqual(storage.load_reservations(True)[0]['billing'], {})
        billing.save(rid, ADDRESS)
        self.assertEqual(storage.load_reservations(True)[0]['billing']['city'], 'Praha')

    def test_google_decode_uses_header_not_position(self):
        row = ['Test','Host','guest@example.com','2030-01-01','2030-01-02',STATUS['pending'],'id','stamp',100,'unrelated','other',json.dumps(ADDRESS)]
        data = storage._decode_res([row], billing_index=11)[0]
        self.assertEqual(data['billing']['city'], 'Praha')

    def test_active_billing_status_uses_coordinator_even_with_cleaning(self):
        with patch('billing.enabled', return_value=True), patch('billing.call') as call, patch('storage._mutate') as mutate:
            storage.set_status('test', 'confirmed')
            call.assert_called_once_with('status', id='test', status=STATUS['confirmed'])
            mutate.assert_not_called()

    def test_failed_confirmation_does_not_change_local_status(self):
        rid = self.add(ADDRESS)
        with patch('billing.enabled', return_value=True), patch('billing.call', side_effect=StorageError('Chybí konfigurace')):
            with self.assertRaises(StorageError): storage.set_status(rid, 'confirmed')
        self.assertEqual(storage.load_reservations(True)[0]['status'], 'pending')

    def test_admin_missing_password_fails_closed(self):
        from streamlit.testing.v1 import AppTest
        with patch('storage.config', return_value={'fakturoid': {'enabled': True}}):
            app = AppTest.from_string('import page_reservations\npage_reservations.render()').run()
        self.assertFalse(app.exception)
        self.assertIn('admin.password', app.error[0].value)
        self.assertFalse(app.selectbox)

    def test_admin_login(self):
        from streamlit.testing.v1 import AppTest
        cfg = {'admin': {'password': 'test-password-with-20-chars'}}
        with patch('storage.config', return_value=cfg):
            app = AppTest.from_string('import admin_auth\nadmin_auth.require()\nimport streamlit as st\nst.success("Přihlášen")').run()
            self.assertFalse(app.success)
            app.text_input[0].set_value(cfg['admin']['password'])
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.success[0].value, 'Přihlášen')
            next(b for b in app.button if b.key == 'admin_logout').click().run()
            self.assertFalse(app.success)

    def test_details_write_uses_same_coordinator(self):
        with patch('billing.enabled', return_value=True), patch('billing.call') as call:
            billing.save('test', ADDRESS)
            self.assertEqual(call.call_args.args, ('billing_details',))
            self.assertEqual(call.call_args.kwargs['billing']['street'], ADDRESS['street'])

    def test_google_new_column_does_not_overwrite_unknown_data(self):
        sheet = MagicMock(); sheet.col_count = 10
        row = [''] * 14
        with patch('storage._sheet', return_value=(sheet,[row],storage.RES_HEADER + ['Poznámka'])):
            _, _, header = billing.sheet_column()
        self.assertEqual(header.index(billing.COLUMN), 14)
        sheet.update.assert_called_once_with(range_name='O1', values=[[billing.COLUMN]], value_input_option='RAW')

    def test_authenticated_status_callback(self):
        from streamlit.testing.v1 import AppTest
        self.add(ADDRESS)
        cfg = {'admin': {'password': 'test-password-with-20-chars'}}
        with patch('storage.config', return_value=cfg):
            app = AppTest.from_string('import page_reservations\npage_reservations.render()').run()
            app.text_input[0].set_value(cfg['admin']['password'])
            app.button[0].click().run()
            next(s for s in app.selectbox if s.label == 'Stav rezervace').select('confirmed').run()
            self.assertFalse(app.exception)
        self.assertEqual(storage.load_reservations(True)[0]['status'], 'confirmed')

    def test_expired_auth_callback_cannot_mutate(self):
        import page_reservations
        import streamlit as st
        rid = self.add(ADDRESS)
        st.session_state['test_status'] = 'confirmed'
        st.session_state['_admin_auth'] = 'old-password-signature'
        with patch('storage.config', return_value={'admin': {'password': 'new-password-with-20-chars'}}):
            page_reservations.change_status(rid, 'test_status')
        self.assertEqual(storage.load_reservations(True)[0]['status'], 'pending')
        st.session_state.pop('_status_error', None)
        st.session_state.pop('_admin_auth', None)
