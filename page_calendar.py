"""Veřejný kalendář a odeslání žádosti o rezervaci."""
import uuid
from html import escape
import streamlit as st
import storage
import billing
from domain import today, quote, money, nights_label, date_label, conflict, StorageError
import calendar_view
import ui


def render():
    st.html('<div class="hero"><div class="hero-copy"><div class="eyebrow">CHALUPA · VERNÍŘOVICE</div>'
            '<h1>Na chvíli <em>vypnout.</em><br>A být spolu.</h1>'
            '<p>Najděte si čas na chalupu. Vyberte termín, ověřte cenu '
            'a pošlete žádost o rezervaci.</p>'
            '<div class="hero-tags"><span>Celá chalupa pro vás</span><span>Cena před odesláním</span></div>'
            '</div><div class="landscape" aria-hidden="true"><div class="sun"></div>'
            '<div class="hill hill-back"></div><div class="hill hill-front"></div>'
            '<div class="cabin"><div class="cabin-window"></div><div class="cabin-door"></div></div>'
            '<div class="landscape-label">Méně plánů. Více pohody.</div></div></div>')
    ui.show_flash()
    if st.button('Obnovit dostupnost', icon=':material/refresh:', type='tertiary'):
        storage.refresh()
    try:
        reservations, prices = storage.load_reservations(), storage.load_prices()
    except StorageError as error:
        st.error(str(error))
        return
    left, right = st.columns([1.9, 1], gap='large')
    with left:
        calendar_view.render(reservations, prices)
    with right, st.container(key='booking'):
        booking(reservations, prices)
    st.html('<div class="footer">CHALUPA · Místo pro společné chvíle</div>')


def booking(reservations, prices):
    st.html('<div class="section-label">01 / Termín a cena</div>')
    st.markdown('### Naplánujte si dovolenou')
    st.session_state.setdefault('arrival', None)
    st.session_state.setdefault('departure', None)
    with st.container(key='booking-dates'):
        fields = st.columns(2)
    start = fields[0].date_input('Příjezd', key='arrival', min_value=today(),
                                format='DD.MM.YYYY', value=None)
    end = fields[1].date_input('Odjezd', key='departure', min_value=today(),
                              format='DD.MM.YYYY', value=None)
    valid = start and end and start >= today() and end > start and (end - start).days <= 365
    total, breakdown = (None, [])
    if start and start < today():
        st.warning('Příjezd vyberte nejdříve na dnešek.')
    elif start and end and end <= start:
        st.warning('Odjezd vyberte alespoň den po příjezdu.')
    elif start and end and (end - start).days > 365:
        st.warning('Pobyt může mít nejvýše 365 nocí.')
    elif valid and conflict(start, end, reservations):
        st.warning('Část tohoto termínu je obsazená. Zvolte jiný pobyt.')
        valid = False
    if valid:
        st.html('<div class="availability-ok">✓ Termín je volný</div>')
        total, breakdown = quote(start, end, prices)
        st.html(f'<div class="price-line"><span>{nights_label((end-start).days)}</span>'
                '<span>celá chalupa</span></div>'
                f'<div class="price-line price-total"><span>Celkem</span><span>{money(total)}</span></div>')
        with st.expander('Rozpis ceny po nocích'):
            for day, amount in breakdown:
                st.text(f'{date_label(day)}  ·  {money(amount)}')
        if total is None:
            st.info('Pro část pobytu není stanovená cena. Majitel ji upřesní před potvrzením.')
    else:
        message = ('Teď vyberte den odjezdu.' if start and not end else
                   'Vyberte příjezd a odjezd.<br>Potom se zobrazí cena vašeho pobytu.' if not start else
                   'Upravte termín a ověřte dostupnost znovu.')
        st.html(f'<div class="booking-empty">{message}</div>')
        st.caption('Příjezd od 15:00 · Odjezd do 11:00')
        return
    st.divider()
    st.html('<div class="section-label">02 / Kontaktní údaje</div>')
    with st.form('guest_form', clear_on_submit=False):
        st.markdown('**Na koho bude rezervace?**')
        first = st.text_input('Jméno', max_chars=100, placeholder='Vaše jméno')
        last = st.text_input('Příjmení', max_chars=100, placeholder='Vaše příjmení')
        email = st.text_input('E-mail', max_chars=254, placeholder='vy@priklad.cz')
        billing_data = billing.fields()
        submitted = st.form_submit_button('Odeslat žádost o rezervaci', type='primary',
                                         width='stretch', disabled=not valid)
        st.caption('Teď nic neplatíte. Termín potvrdí majitel.' +
                   (' Po schválení vám přijde zálohová faktura s údaji k platbě.' if billing.enabled() else
                    ' Potvrzení přijetí žádosti uvidíte zde.'))
    if submitted:
        fingerprint = (first.strip(), last.strip(), email.strip(), start, end, tuple(billing_data.items()))
        request = st.session_state.get('_request')
        if not request or request[0] != fingerprint:
            request = (fingerprint, uuid.uuid4().hex[:12])
            st.session_state['_request'] = request
        try:
            rid = storage.add_reservation(first, last, email, start, end, total, request[1], billing_data=billing_data)
        except StorageError as error:
            storage.refresh()
            st.error(str(error))
        else:
            ui.flash(f'Žádost o rezervaci {date_label(start)} – {date_label(end)} '
                     f'byla uložena. Čeká na potvrzení majitelem. Kód: {rid}.')
            st.session_state['_reset_booking'] = True
            st.rerun()
