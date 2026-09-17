"""Seznam správců a výchozí odpovědnost za nové rezervace."""
from html import escape
import streamlit as st
import managers
import storage
from domain import StorageError
import ui


def render():
    ui.heading('PRO MAJITELE / SPRÁVCE', 'Správci chalupy',
               'Každá rezervace má svého správce. Určete, kdo převezme nové pobyty.')
    ui.admin_note()
    ui.show_flash()
    if st.session_state.pop('_reset_manager_form', False):
        for key in ('manager_name', 'manager_email'):
            st.session_state.pop(key, None)
    try:
        people, default = managers.load()
    except StorageError as error:
        st.error(str(error))
        return
    if people:
        with st.container(border=True):
            st.markdown('### Výchozí správce')
            st.caption('Automaticky dostává nové rezervace. Již přiřazené pobyty zůstávají původnímu správci.')
            options = [p['id'] for p in people]
            labels = {p['id']: p['name'] + ' · ' + p['email'] for p in people}
            with st.form('default_manager'):
                selected = st.selectbox('Kdo převezme nové rezervace?', options,
                                        index=options.index(default) if default in options else 0,
                                        format_func=labels.get)
                save = st.form_submit_button('Nastavit výchozího správce', type='primary', width='stretch')
            if save:
                try:
                    managers.set_default(selected)
                except StorageError as error:
                    st.error(str(error))
                else:
                    ui.flash('Výchozí správce byl nastaven. Rezervace bez správce byly doplněny.')
                    st.rerun()
    else:
        st.info('Přidejte prvního správce. Stane se výchozím a převezme rezervace bez přiřazení.')
    listing, form = st.columns([1.65, 1], gap='large')
    with form, st.container(border=True):
        st.markdown('### Přidat správce')
        with st.form('manager_form'):
            name = st.text_input('Jméno a příjmení', key='manager_name', max_chars=100)
            email = st.text_input('E-mail', key='manager_email', max_chars=254)
            add = st.form_submit_button('Přidat správce', type='primary', width='stretch')
        st.caption('Kontaktní údaje slouží k evidenci. Přidání správce neposílá e-mail ani nevytváří přihlášení.')
        if add:
            try:
                managers.add(name, email)
            except StorageError as error:
                st.error(str(error))
            else:
                st.session_state['_reset_manager_form'] = True
                ui.flash('Správce byl přidán.')
                st.rerun()
    with listing:
        st.markdown('### Seznam správců')
        for person in people:
            with st.container(border=True):
                st.html('<p class="res-title">' + escape(person['name']) + '</p><p class="res-detail">' + escape(person['email']) + '</p>')
                if person['id'] == default:
                    st.caption('✓ Výchozí správce')
        st.caption('Správce konkrétního pobytu změníte na záložce Rezervace.')
