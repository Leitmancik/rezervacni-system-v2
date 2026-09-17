"""Odkazy z e-mailů: načtení nic nepotvrzuje ani neodhlašuje."""
import streamlit as st
import cleaning_mail
from domain import StorageError

TASKS = ['Sundat povlečení', 'Vysát / vytřít podlahy', 'Uklidit nádobí a myčku',
         'Vypustit, vyčistit a napustit vířivku', 'Uklidit krb', 'Uklidit venkovní posezení']


def render():
    st.title('Úklid chalupy Vernířovice')
    token = st.query_params.get('cleaning_token', '')
    if not token or len(token) > 4000:
        st.error('Odkaz není platný.')
        return
    try:
        details = cleaning_mail.call('inspect', token=token)
    except StorageError as error:
        st.error(str(error))
        return
    if details['kind'] == 'unsubscribe':
        st.write('Odhlášení z e-mailových nabídek úklidu')
        st.caption('Již přijaté úklidy zůstávají přiřazené. Kontakt zůstane v seznamu se stavem Odhlášeno.')
        if st.button('Odhlásit z e-mailingu', type='primary'):
            try:
                cleaning_mail.call('unsubscribe', token=token)
            except StorageError as error:
                st.error(str(error))
            else:
                st.success('Odhlášeno. Další nabídky úklidu vám nebudeme posílat.')
        return
    st.subheader(f"{details['date']} · 11:00–15:00")
    st.write('Odměna za celý úklid: **2 500 Kč**')
    st.write(f"Úklidový tým: **{details['name']}**")
    st.markdown('\n'.join('- ' + item for item in TASKS))
    st.write('Přihlášení je závazné. Pokud přijatý úklid neprovedete včas a podle stanoveného standardu, budete odebráni ze seznamu úklidových týmů.')
    if st.button('Závazně přihlásit k úklidu', type='primary'):
        try:
            cleaning_mail.call('claim', token=token)
        except StorageError as error:
            st.error(str(error))
        else:
            st.success('Úklid jste závazně převzali. Váš tým je přiřazen k rezervaci.')
