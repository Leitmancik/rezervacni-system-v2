"""Samostatná aplikace pro hosty a majitele jedné chalupy."""
import streamlit as st
import storage
import ui
import page_calendar
import page_reservations
import page_pricing
import page_cleaning
import page_cleaning_response

st.set_page_config(page_title='Chalupa · Rezervace', page_icon='🌿', layout='wide',
                   initial_sidebar_state='collapsed')
ui.style()
if 'cleaning_token' in st.query_params:
    page_cleaning_response.render()
    st.stop()
if st.session_state.pop('_reset_booking', False):
    for key in ('arrival', 'departure', '_request'):
        st.session_state.pop(key, None)

page = st.navigation([
    st.Page(page_calendar.render, title='Váš pobyt', icon=':material/calendar_month:', default=True, url_path='kalendar'),
    st.Page(page_reservations.render, title='Rezervace', icon=':material/event_available:', url_path='rezervace'),
    st.Page(page_pricing.render, title='Ceník', icon=':material/payments:', url_path='cenotvorba'),
    st.Page(page_cleaning.render, title='Úklid', icon=':material/cleaning_services:', url_path='uklid'),
], position='top')
st.html('<div class="brand"><div class="brand-symbol">⌂</div><div>'
        '<div class="brand-name">CHALUPA</div><small>Vernířovice · Rezervace pobytu</small></div></div>')
if not storage.connected():
    st.info('Ukázkový režim · Používáte samostatná místní data. Změny se nezapisují do společné tabulky.')
page.run()
