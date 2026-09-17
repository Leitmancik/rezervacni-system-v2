"""Základní cena a cenová období nad společnou tabulkou."""
from datetime import timedelta
from html import escape
import streamlit as st
import storage
from domain import money, date_label, today, StorageError
import ui


@st.dialog('Odstranit cenové období?')
def remove(period):
    st.write(period['label'] or 'Cenové období')
    st.write('Odstranění se projeví v obou aplikacích. Ceny již uložených rezervací zůstanou stejné.')
    if st.button('Odstranit období', type='primary'):
        try:
            storage.delete_price(period['id'])
        except StorageError as error:
            st.error(str(error))
        else:
            ui.flash('Cenové období bylo odstraněno.')
            st.rerun()


def editor(period=None):
    rid = period['id'] if period else None
    key = rid or 'new'
    with st.form('price_' + key):
        label = st.text_input('Název období', value=period['label'] if period else '',
                              placeholder='Například letní prázdniny', max_chars=100)
        a, b = st.columns(2)
        start = a.date_input('Od', value=period['date_from'] if period else today(),
                            format='DD.MM.YYYY', key='pstart_'+key)
        end = b.date_input('Do (včetně této noci)',
                          value=period['date_to'] if period else today()+timedelta(days=7),
                          format='DD.MM.YYYY', key='pend_'+key)
        price = st.number_input('Cena za noc (Kč)', min_value=0.0,
                                value=float(period['price']) if period else 0.0, step=100.0)
        submitted = st.form_submit_button('Uložit období', type='primary', width='stretch')
    if submitted:
        try:
            if period and not rid:
                raise StorageError('Období nemá ID. Doplňte jej nejprve v tabulce.')
            storage.save_price(rid, start, end, price, label)
        except StorageError as error:
            st.error(str(error))
        else:
            ui.flash('Cenové období bylo uloženo.')
            st.rerun()


def render():
    ui.heading('PRO MAJITELE / CENOTVORBA', 'Ceník pobytů',
               'Nastavte běžnou cenu za noc a výjimky pro sezónu, svátky nebo víkendy.')
    ui.admin_note()
    ui.show_flash()
    if st.button('Obnovit ceník', icon=':material/refresh:', type='tertiary'):
        storage.refresh()
    try:
        prices = storage.load_prices()
    except StorageError as error:
        st.error(str(error))
        return
    base = next((p for p in prices if p['date_from'] is None), None)
    left, right = st.columns([1, 1.65], gap='large')
    with left, st.container(border=True):
        st.html('<div class="section-label">Základ pobytu</div>')
        st.markdown('### Běžná cena za noc')
        st.caption('Platí pro všechny noci mimo cenová období.')
        with st.form('base_price'):
            amount = st.number_input('Cena za celou chalupu (Kč)', min_value=0.0,
                                     value=float(base['price']) if base else 0.0, step=100.0)
            submitted = st.form_submit_button('Uložit základní cenu', type='primary', width='stretch')
        if submitted:
            try:
                storage.save_price(base['id'] if base else None, None, None, amount, 'Základní cena')
            except StorageError as error:
                st.error(str(error))
            else:
                ui.flash('Základní cena byla uložena.')
                st.rerun()
        st.divider()
        st.markdown('**Jak se cena počítá**')
        st.caption('Při překryvu má přednost kratší období. U stejně dlouhých období '
                   'rozhoduje jejich pořadí v tabulce. Datum „Do“ zahrnuje i noc začínající tímto dnem.')
        st.caption('Změna ceníku nepřepisuje cenu existujících rezervací.')
    with right:
        st.markdown('### Sezóna a výjimečné termíny')
        with st.expander('＋ Přidat cenové období', expanded=False):
            editor()
        seasons = sorted((p for p in prices if p['date_from'] is not None), key=lambda p:p['date_from'])
        if not seasons:
            st.info('Zatím nejsou nastavena žádná cenová období.')
        for i, period in enumerate(seasons):
            with st.container(border=True):
                a, b = st.columns([2, 1])
                a.html(f'<p class="res-title">{escape(period["label"] or "Cenové období")}</p>'
                       f'<p class="res-detail">{date_label(period["date_from"])} – {date_label(period["date_to"])}</p>')
                b.markdown('**' + money(period['price']) + ' / noc**')
                overlaps = [p for p in seasons if p is not period and
                            period['date_from'] <= p['date_to'] and p['date_from'] <= period['date_to']]
                if overlaps:
                    st.caption('Překryv s jiným obdobím · cenu určuje kratší období.')
                if not period['id']:
                    st.caption('Období nemá ID. Pro úpravy jej doplňte ve společné tabulce.')
                    continue
                with st.expander('Upravit období'):
                    editor(period)
                    if st.button('Odstranit období', key=f'delprice_{i}', type='tertiary', disabled=not period['id']):
                        remove(period)
