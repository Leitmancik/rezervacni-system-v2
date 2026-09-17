"""Odkazy nesmějí samy měnit data; zprávy bez nastavení neodesíláme."""
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import cleaning_mail
import storage
from domain import StorageError

class MailTests(unittest.TestCase):
    def test_not_configured(self):
        with patch.object(storage, 'config', return_value={}):
            self.assertFalse(cleaning_mail.configured())
            with self.assertRaises(StorageError):
                cleaning_mail.call('claim', token='test')

    def test_unsubscribed_column_by_header(self):
        rows = [['Firma', 'test@example.com', 'Poznámka', 'Odhlášeno']]
        self.assertEqual(storage._decode_cleaners(rows, 3)[0]['mail_status'], 'Odhlášeno')
        self.assertEqual(storage._decode_cleaners([['Firma', 'x@example.com']], 3)[0]['mail_status'], 'Přihlášeno')

    def test_claim_requires_button(self):
        with patch.object(cleaning_mail, 'call', return_value={'kind':'claim', 'date':'20. 09. 2030', 'name':'Firma'}) as call:
            app = AppTest.from_string("import streamlit as st\nst.query_params['cleaning_token']='test'\nimport page_cleaning_response\npage_cleaning_response.render()").run()
            self.assertFalse(app.exception)
            call.assert_called_once_with('inspect', token='test')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertIn(unittest.mock.call('claim', token='test'), call.call_args_list)

    def test_unsubscribe_requires_button(self):
        with patch.object(cleaning_mail, 'call', return_value={'kind':'unsubscribe'}) as call:
            app = AppTest.from_string("import streamlit as st\nst.query_params['cleaning_token']='test'\nimport page_cleaning_response\npage_cleaning_response.render()").run()
            self.assertFalse(app.exception)
            call.assert_called_once_with('inspect', token='test')
            app.button[0].click().run()
            self.assertIn(unittest.mock.call('unsubscribe', token='test'), call.call_args_list)
