"""Kontakty úklidu a přiřazení k pobytu bez zásahů do živých dat."""
import os
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

os.environ['CHALUPA_DEMO'] = '1'
import test_app
from domain import StorageError, today
import storage


class CleaningTests(unittest.TestCase):
    setUp = test_app.StorageTests.setUp
    tearDown = test_app.StorageTests.tearDown

    def test_contact_validation_and_duplicate_email(self):
        for name, email in [('', 'a@example.com'), ('Tým', 'neplatne')]:
            with self.assertRaises(StorageError):
                storage.add_cleaner(name, email)
        storage.add_cleaner('  Úklidová firma  ', '  Firma@example.com  ')
        self.assertEqual(storage.load_cleaners(True), [
            {'name': 'Úklidová firma', 'email': 'Firma@example.com'}])
        with self.assertRaises(StorageError):
            storage.add_cleaner('Jiný název', 'firma@example.com')

    def test_assignment_change_and_removal_preserve_reservation(self):
        day = today() + timedelta(days=2)
        storage.add_reservation('Host', 'Test', 'host@example.com',
                                day, day + timedelta(days=3), None, 'stay')
        before = storage.load_reservations(True)[0]
        storage.add_cleaner('Firma', 'firma@example.com')
        storage.add_cleaner('Osoba', 'osoba@example.com')
        for email in ['firma@example.com', 'osoba@example.com', '']:
            storage.assign_cleaner('stay', email)
            after = storage.load_reservations(True)[0]
            self.assertEqual(after['cleaner_email'], email)
            self.assertEqual({k: v for k, v in before.items()
                              if k != 'cleaner_email'},
                             {k: v for k, v in after.items()
                              if k != 'cleaner_email'})
        with self.assertRaises(StorageError):
            storage.assign_cleaner('stay', 'missing@example.com')
        with self.assertRaises(StorageError):
            storage.assign_cleaner('missing', 'firma@example.com')

    def test_blank_sheet_with_empty_row_gets_header(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [[]]
        book = MagicMock()
        book.worksheet.return_value = sheet
        with patch.object(storage, '_document', return_value=book):
            _, rows = storage._cleaning_sheet(create=True)
        self.assertEqual(rows, [])
        sheet.update.assert_called_once_with(
            range_name='A1:B1', values=[storage.CLEANING_HEADER],
            value_input_option='RAW')

    def test_sheet_setup_preserves_existing_columns(self):
        sheet = MagicMock()
        sheet.col_count = 12
        header = storage.RES_HEADER + ['Poznámka']
        rows = [[''] * 10 + ['Existující data bez hlavičky']]
        with patch.object(storage, '_sheet', return_value=(sheet, rows, header)):
            _, _, index = storage._reservation_assignment_sheet(create=True)
        self.assertEqual(index, 11)
        sheet.update.assert_called_once_with(
            range_name='L1', values=[[storage.CLEANER_COLUMN]],
            value_input_option='RAW')

    def test_live_assignment_writes_only_assignment_cell(self):
        sheet = MagicMock()
        rows = [['Host', 'Test', 'host@example.com', '2030-01-01',
                 '2030-01-02', 'Potvrzeno', 'stay', '', 2500]]
        with patch.object(storage, 'connected', return_value=True), \
                patch.object(storage, 'load_cleaners', return_value=[
                    {'name': 'Firma', 'email': 'firma@example.com'}]), \
                patch.object(storage, '_reservation_assignment_sheet',
                             return_value=(sheet, rows, 9)):
            storage.assign_cleaner('stay', 'firma@example.com')
        sheet.update.assert_called_once_with(
            range_name='J2', values=[['firma@example.com']],
            value_input_option='RAW')

    def test_live_contact_raw_and_lost_response(self):
        sheet = MagicMock()
        with patch.object(storage, 'connected', return_value=True), \
                patch.object(storage, '_cleaning_sheet', return_value=(sheet, [])):
            storage.add_cleaner('=Text', 'firma@example.com')
        sheet.append_row.assert_called_once_with(
            ['=Text', 'firma@example.com'], value_input_option='RAW')
        sheet.append_row.side_effect = TimeoutError
        with patch.object(storage, 'connected', return_value=True), \
                patch.object(storage, '_cleaning_sheet', return_value=(sheet, [])), \
                patch.object(storage, 'load_cleaners', return_value=[
                    {'name': 'Firma', 'email': 'firma@example.com'}]):
            storage.add_cleaner('Firma', 'firma@example.com')

    def test_ui_add_and_assign(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string(
            'import page_cleaning\npage_cleaning.render()').run()
        app.text_input(key='cleaner_name').input('Úklidová firma')
        app.text_input(key='cleaner_email').input('firma@example.com')
        next(b for b in app.button if b.label == 'Přidat do týmu').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertEqual(app.text_input(key='cleaner_name').value, '')
        self.assertEqual(len(storage.load_cleaners(True)), 1)
        day = today() + timedelta(days=2)
        storage.add_reservation('Host', 'Test', 'host@example.com',
                                day, day+timedelta(days=2), None, 'stay')
        admin = AppTest.from_string(
            'import page_reservations\npage_reservations.render()').run()
        admin.selectbox(key='cleaner_choice_stay_').select('firma@example.com')
        next(b for b in admin.button if b.label == 'Uložit přiřazení').click().run()
        self.assertFalse(admin.exception)
        self.assertEqual(storage.load_reservations(True)[0]['cleaner_email'],
                         'firma@example.com')
