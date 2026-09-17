"""Správa rezervací a export aktuálně vyfiltrovaných záznamů."""
from html import escape
from io import BytesIO
import pandas as pd
import streamlit as st
import storage
from domain import STATUS, StorageError, date_label, money, today, nights_label, created_label
import ui


@st.dialog('Smazat rezervaci?')
def remove(reservation):
    st.write(f"{reservation['first_name']} {reservation['last_name']} · "
             f"{date_label(reservation['date_from'])} – {date_label(reservation['date_to'])}")
    st.write('Rezervace se odstraní i ze společné tabulky a termín se uvolní v obou aplikacích.')
    if st.button('Ano, smazat rezervaci', type='primary', width='stretch'):
        try:
            storage.delete_reservation(reservation['id'])
        except StorageError as error:
            st.error(str(error))
        else:
            ui.flash('Rezervace byla smazána a termín je opět volný.')
            st.rerun()


def safe_cell(value):
    # Export nesmí z textů hosta vytvářet vzorce při otevření v Excelu.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def export_frame(rows):
    columns = ['Jméno', 'Příjmení', 'E-mail', 'Příjezd', 'Odjezd', 'Nocí', 'Stav', 'Cena celkem', 'ID', 'Úklid - e-mail', 'Vytvořeno']
    return pd.DataFrame([
        [safe_cell(r['first_name']), safe_cell(r['last_name']), safe_cell(r['email']),
         r['date_from'].isoformat(), r['date_to'].isoformat(),
         (r['date_to']-r['date_from']).days, STATUS[r['status']], r['price'], safe_cell(r['id']), safe_cell(r.get('cleaner_email', '')), safe_cell(r.get('created_at', ''))]
        for r in rows], columns=columns)


def change_status(rid, key):
    try:
        selected = st.session_state[key]
        storage.set_status(rid, selected)
    except StorageError as error:
        st.session_state['_status_error'] = str(error)
        st.session_state.pop(key, None)
    else:
        import cleaning_mail
        suffix = (' · Nabídka úklidu se odešle přihlášeným týmům, pokud již nebyla vytvořena a úklid není přiřazen.'
                  if selected == 'paid' and cleaning_mail.configured() else
                  ' · Rozesílka úklidu zatím není aktivovaná.' if selected == 'paid' else '')
        ui.flash('Stav rezervace byl změněn na: ' + STATUS[selected] + suffix)


def render():
    ui.heading('PRO MAJITELE / REZERVACE', 'Rezervace pod kontrolou',
               'Potvrďte nové žádosti, evidujte platby a domluvte úklid.')
    ui.admin_note()
    ui.show_flash()
    if error := st.session_state.pop('_status_error', None):
        st.error(error)
    if st.button('Obnovit data', icon=':material/refresh:', type='tertiary'):
        storage.refresh()
    try:
        rows = storage.load_reservations()
    except StorageError as error:
        st.error(str(error))
        return
    try:
        cleaners = storage.load_cleaners()
    except StorageError as error:
        st.warning('Úklidový tým se nepodařilo načíst. ' + str(error))
        cleaners = None
    confirmed = [r for r in rows if r['status'] in ('confirmed', 'paid')]
    pending = sum(r['status'] == 'pending' for r in rows)
    missing = sum(r['price'] is None for r in confirmed)
    revenue = sum(r['price'] or 0 for r in confirmed)
    coming = sum(r['date_to'] > today() for r in rows)
    st.html('<div class="metric-grid">'
            f'<div class="metric-card"><small>Čeká na potvrzení</small><strong>{pending}</strong><span>žádosti k vyřízení</span></div>'
            f'<div class="metric-card"><small>Nadcházející a probíhající</small><strong>{coming}</strong><span>pobyty v kalendáři</span></div>'
            f'<div class="metric-card"><small>Hodnota potvrzených pobytů</small><strong>{money(revenue)}</strong><span>všechny potvrzené · {missing} bez uložené ceny</span></div></div>')
    filters = st.columns([2, 2, 1])
    search = filters[0].text_input('Hledat hosta', placeholder='Jméno, e-mail nebo kód rezervace')
    statuses = filters[1].multiselect(
        'Stav', list(STATUS.values()), placeholder='Všechny stavy',
        help='Můžete vybrat více stavů. Prázdný výběr zobrazí všechny stavy.',
    )
    period = filters[2].selectbox('Období', ['Nadcházející a probíhající', 'Všechny pobyty', 'Minulé pobyty'])
    filtered = [r for r in rows if (
        (not search or search.casefold() in f"{r['first_name']} {r['last_name']} {r['email']} {r['id']}".casefold())
        and (not statuses or STATUS[r['status']] in statuses)
        and (period == 'Všechny pobyty' or (r['date_to'] > today()) == (period == 'Nadcházející a probíhající')))]
    st.caption('Časy vytvoření jsou uvedené v časovém pásmu Europe/Prague. Stav platby zatím měníte ručně.')
    st.caption(f'Zobrazeno {len(filtered)} z {len(rows)} rezervací · Souhrny nahoře zahrnují všechny záznamy.')
    if not filtered:
        st.info('Žádné rezervace pro tento výběr. Zkuste upravit filtry.')
    for i, r in enumerate(filtered):
        with st.container(border=True):
            cols = st.columns([2, 2, 2])
            cols[0].html(f'<p class="res-title">{escape(r["first_name"])} {escape(r["last_name"])}</p>'
                         f'<p class="res-detail">{escape(r["email"])}<br>#{escape(r["id"] or "bez ID")}</p>')
            cols[1].html(f'<p class="res-title">{date_label(r["date_from"])} → {date_label(r["date_to"])}</p>'
                         f'<p class="res-detail">{nights_label((r["date_to"]-r["date_from"]).days)} · {money(r["price"])}</p>'
                         f'<p class="res-detail">Vytvořeno: {escape(created_label(r.get("created_at")))}</p>')
            cols[2].html(ui.badge(STATUS[r['status']], 'green' if r['status'] == 'paid' else 'amber'))
            with cols[2]:
                try:
                    status_key = f"status_{r['id'] or i}_{r['status']}"
                    st.selectbox(
                        'Stav rezervace', list(STATUS),
                        index=list(STATUS).index(r['status']),
                        format_func=STATUS.get,
                        key=status_key,
                        on_change=change_status, args=(r['id'], status_key),
                        disabled=not r['id'],
                    )
                    if st.button('Smazat', key=f'delete_{i}', type='tertiary', disabled=not r['id'], width='stretch'):
                        remove(r)
                except StorageError as error:
                    st.error(str(error))
            if cleaners is not None:
                cleaning_assignment(r, cleaners)
    if filtered:
        frame = export_frame(filtered)
        with st.expander('Exportovat zobrazené rezervace'):
            csv = frame.to_csv(index=False, sep=';').encode('utf-8-sig')
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                frame.to_excel(writer, sheet_name='Rezervace', index=False)
                sheet = writer.sheets['Rezervace']
                sheet.freeze_panes = 'A2'
                sheet.auto_filter.ref = sheet.dimensions
                from openpyxl.styles import Font, PatternFill
                for cell in sheet[1]:
                    cell.font = Font(bold=True, color='FFFFFF')
                    cell.fill = PatternFill('solid', fgColor='234D40')
                for column in sheet.columns:
                    sheet.column_dimensions[column[0].column_letter].width = min(45, max(len(str(c.value or '')) for c in column) + 3)
            a, b = st.columns(2)
            a.download_button('Stáhnout Excel', output.getvalue(), 'rezervace.xlsx',
                              mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', width='stretch')
            b.download_button('Stáhnout CSV', csv, 'rezervace.csv', mime='text/csv', width='stretch')


def cleaning_assignment(reservation, cleaners):
    assigned = reservation.get('cleaner_email', '')
    contacts = {p['email']: p['name'] for p in cleaners if p['email']}
    label = contacts.get(assigned, assigned) if assigned else 'Nepřiřazeno'
    with st.expander(
        f'Úklid · {date_label(reservation["date_to"])} · {label}'
    ):
        st.caption('Úklid po odjezdu hostů v 11:00. Přiřazení neposílá e-mail.')
        if not reservation['id']:
            st.info('Pro přiřazení úklidu nejprve doplňte ID rezervace v tabulce.')
            return
        options = [''] + list(contacts)
        if assigned and assigned not in contacts:
            options.append(assigned)
            st.warning('Přiřazený kontakt už není v seznamu úklidového týmu.')
        if not contacts:
            st.info('Nejdříve přidejte člověka nebo firmu na záložce Úklid.')
        key = reservation['id'] + '_' + assigned
        with st.form('assign_cleaner_' + key):
            choice = st.selectbox(
                'Kdo zajistí úklid?', options,
                index=options.index(assigned),
                format_func=lambda email: (
                    f'{contacts[email]} · {email}' if email in contacts
                    else email or 'Nepřiřazeno'
                ),
                key='cleaner_choice_' + key,
            )
            submitted = st.form_submit_button(
                'Uložit přiřazení', width='stretch',
                disabled=not contacts and not assigned,
            )
        if submitted:
            try:
                storage.assign_cleaner(reservation['id'], choice)
            except StorageError as error:
                st.error(str(error))
            else:
                ui.flash('Úklid byl přiřazen.' if choice else 'Přiřazení úklidu bylo zrušeno.')
                st.rerun()
