"""Kontakty na úklidový tým pro budoucí nabídky termínů."""
from html import escape

import streamlit as st

import storage
from domain import StorageError
import ui


def render():
    import admin_auth
    admin_auth.require()
    ui.heading(
        'PRO MAJITELE / ÚKLID', 'Úklidový tým',
        'Všichni, kdo se starají o chalupu, přehledně na jednom místě.',
    )
    ui.admin_note()
    ui.show_flash()
    import cleaning_mail
    if not cleaning_mail.configured():
        st.info('E-mailové nabídky úklidu nejsou aktivní. Úklid můžete přiřadit ručně v Rezervacích.')
    if st.session_state.pop('_reset_cleaner_form', False):
        st.session_state.pop('cleaner_name', None)
        st.session_state.pop('cleaner_email', None)
    if st.button('Obnovit seznam', icon=':material/refresh:', type='tertiary'):
        storage.refresh_cleaners()
    try:
        cleaners = storage.load_cleaners()
    except StorageError as error:
        st.error(str(error))
        return

    listing, form = st.columns([1.65, 1], gap='large')
    with form, st.container(border=True):
        st.html('<div class="section-label">Nový kontakt</div>')
        st.markdown('### Přidat do týmu')
        with st.form('cleaner_form'):
            name = st.text_input(
                'Jméno', key='cleaner_name', max_chars=100,
                placeholder='Jméno a příjmení nebo název firmy',
            )
            email = st.text_input(
                'E-mail', key='cleaner_email', max_chars=254,
                placeholder='jmeno@priklad.cz',
            )
            submitted = st.form_submit_button(
                'Přidat do týmu', type='primary', width='stretch',
            )
        st.caption(
            'Nabídky dostávají pouze přihlášené kontakty po aktivaci rozesílky. '
            'Odhlášení z nabídek nemaže již přijaté úklidy.'
        )
        if submitted:
            try:
                storage.add_cleaner(name, email)
            except StorageError as error:
                st.error(str(error))
            else:
                ui.flash('Kontakt byl přidán do úklidového týmu.')
                st.session_state['_reset_cleaner_form'] = True
                st.rerun()

    with listing:
        st.markdown('### Seznam kontaktů')
        st.caption(f'Celkem kontaktů: {len(cleaners)}')
        if not cleaners:
            st.info('Tým je zatím prázdný. Přidejte první kontakt pomocí formuláře.')
            return
        search = st.text_input(
            'Hledat v týmu', placeholder='Jméno nebo e-mail',
        ).strip().casefold()
        filtered = [person for person in cleaners if not search or search in
                    f"{person['name']} {person['email']}".casefold()]
        if not filtered:
            st.info('Pro toto hledání jsme nenašli žádný kontakt.')
        for person in filtered:
            with st.container(border=True):
                st.html(
                    '<p class="res-title">'
                    + escape(person['name'] or 'Bez jména') + '</p>'
                    '<p class="res-detail">'
                    + escape(person['email'] or 'E-mail není vyplněný')
                    + '</p>'
                )
                st.caption('E-mailing: ' + person.get('mail_status', 'Přihlášeno'))
