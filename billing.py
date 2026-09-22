"""Fakturační údaje a spojení s trvalou frontou ve společném koordinátoru."""
import json
import re
import streamlit as st
from domain import StorageError

COLUMN = 'Fakturační údaje'
LOCAL_INDEX = 11


def validate(data):
    data = dict(data or {})
    result = {k: str(data.get(k, '')).strip() for k in
              ('street', 'city', 'zip', 'country', 'company', 'registration_no', 'vat_no')}
    result['on_company'] = data.get('on_company') is True
    if any(not result[k] for k in ('street', 'city', 'zip', 'country')):
        raise StorageError('Doplňte fakturační adresu: ulici a číslo domu, obec, PSČ a zemi.')
    if any(len(v) > 200 for v in result.values() if isinstance(v, str)):
        raise StorageError('Fakturační údaj může mít nejvýše 200 znaků.')
    if not re.fullmatch(r'[A-Z]{2}', result['country']):
        raise StorageError('Země musí mít dvoupísmenný kód, například CZ.')
    if result['country'] in ('CZ', 'SK'):
        zipcode = re.sub(r'\s+', '', result['zip'])
        if not re.fullmatch(r'[0-9]{5}', zipcode):
            raise StorageError('PSČ musí obsahovat 5 číslic, například 123 45 nebo 12345.')
        result['zip'] = zipcode[:3] + ' ' + zipcode[3:]
    if result['on_company']:
        if not result['company'] or not result['registration_no']:
            raise StorageError('Pro fakturu na firmu doplňte název firmy a IČO.')
        if result['country'] == 'CZ' and not re.fullmatch(r'\d{8}', result['registration_no']):
            raise StorageError('České IČO musí obsahovat osm číslic.')
    else:
        for k in ('company', 'registration_no', 'vat_no'):
            result[k] = ''
    return result


def fields(data=None):
    """Všechny údaje ve formuláři; checkbox uvnitř st.form nepřepíná render."""
    d = data or {}
    st.markdown('**Fakturační adresa**')
    street = st.text_input('Ulice a číslo domu', value=d.get('street', ''), max_chars=200)
    city = st.text_input('Obec', value=d.get('city', ''), max_chars=200)
    zipcode = st.text_input('PSČ', value=d.get('zip', ''), max_chars=20, placeholder='123 45')
    country = st.text_input('Kód země', value=d.get('country', 'CZ'), max_chars=2,
                            help='CZ = Česko, SK = Slovensko, DE = Německo, AT = Rakousko, PL = Polsko.')
    company = st.checkbox('Vystavit fakturu na firmu', value=d.get('on_company', False))
    st.caption('Následující údaje vyplňte pouze při fakturaci na firmu. Adresa výše je pak sídlem firmy.')
    name = st.text_input('Název firmy', value=d.get('company', ''), max_chars=200)
    registration = st.text_input('IČO', value=d.get('registration_no', ''), max_chars=30)
    vat = st.text_input('DIČ (nepovinné)', value=d.get('vat_no', ''), max_chars=30)
    return dict(street=street, city=city, zip=zipcode, country=country.upper(),
                on_company=company, company=name, registration_no=registration, vat_no=vat)


def enabled():
    import storage
    return bool(storage.config().get('fakturoid', {}).get('enabled'))


def call(action, **payload):
    import storage
    from cleaning_mail import gateway_call
    cfg = storage.config().get('fakturoid', {})
    if not enabled() or not cfg.get('url') or not cfg.get('secret'):
        raise StorageError('Doplňte nastavení koordinátoru fakturace v Secrets.')
    cleaning = storage.config().get('cleaning_mail', {})
    if cleaning.get('enabled') and (cleaning.get('url') != cfg['url'] or cleaning.get('secret') != cfg['secret']):
        raise StorageError('Úklid a fakturace musí používat stejný koordinátor a stejný klíč.')
    if action == 'status':
        payload['require_billing'] = True
    return gateway_call(cfg, action, **payload)


def sheet_column():
    import storage
    import gspread
    sheet, rows, header = storage._sheet('Rezervace', storage.RES_HEADER, include_header=True)
    if header.count(COLUMN) > 1:
        raise StorageError('Sloupec fakturačních údajů je v tabulce vícekrát.')
    if COLUMN not in header:
        index = max([len(header)] + [len(row) for row in rows])
        if index >= sheet.col_count:
            sheet.add_cols(index + 1 - sheet.col_count)
        sheet.update(range_name=gspread.utils.rowcol_to_a1(1, index + 1),
                     values=[[COLUMN]], value_input_option='RAW')
        header += [''] * (index - len(header)) + [COLUMN]
    return sheet, rows, header


def save(rid, data):
    import storage
    import audit
    data = validate(data)
    if enabled():
        return call('billing_details', id=rid, billing=data)
    with storage._lock(), storage._errors():
        if storage.connected():
            sheet, rows, header = sheet_column()
            matches = [(i + 2, row) for i, row in enumerate(rows) if len(row) > 6 and row[6] == rid]
            if len(matches) != 1:
                raise StorageError('Rezervace nebyla jednoznačně nalezena.')
            number, row = matches[0]
            index = header.index(COLUMN)
            value = json.dumps(data, ensure_ascii=False)
            audit.commit([audit.update_cell(sheet, number, index + 1, value)],
                         [audit.event(rid, {COLUMN: row[index] if len(row) > index else ''}, {COLUMN: value})])
        else:
            with storage._db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT payload FROM records WHERE kind='res' AND id=?", (rid,)).fetchone()
                if row is None:
                    raise StorageError('Rezervace už neexistuje.')
                before = json.loads(row[0]); after = list(before)
                after += [''] * max(0, LOCAL_INDEX + 1 - len(after))
                after[LOCAL_INDEX] = json.dumps(data, ensure_ascii=False)
                db.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(after), rid))
                audit.local(db, rid, before, after)
    storage.refresh()


def jobs():
    if not enabled():
        return {}
    return call('billing_list').get('jobs', {})


def panel(reservation, job):
    import ui
    label = job.get('state', 'Dosud nevystavena')
    with st.expander('Fakturace · ' + label):
        if job:
            st.write('Číslo rezervace / variabilní symbol: ' + str(job['vs']))
            if job.get('number'):
                st.write('Faktura: ' + job['number'])
            url = job.get('url', '')
            if url.startswith('https://app.fakturoid.cz/'):
                st.link_button('Otevřít fakturu ve Fakturoidu', url)
            final = job.get('final', {})
            st.write('Vyúčtování: ' + final.get('state', 'Po skončení pobytu a úplném uhrazení zálohy'))
            if final.get('url', '').startswith('https://app.fakturoid.cz/'):
                st.link_button('Otevřít vyúčtovací fakturu', final['url'])
            if final.get('error'):
                st.warning(final['error'])
            if job.get('error'):
                st.warning(job['error'])
            st.caption('Změny vystaveného dokladu a storno vyřiďte ve Fakturoidu. Změna stavu rezervace doklad nestornuje.')
            if (job.get('state') != 'Odesláno' or (final and final.get('state') != 'Odesláno')) and st.button('Znovu ověřit / pokračovat', key='billing_retry_' + reservation['id']):
                try:
                    call('billing_retry', id=reservation['id'])
                except StorageError as error:
                    st.error(str(error))
                else:
                    st.rerun()
            return
        with st.form('billing_details_' + reservation['id']):
            data = fields(reservation.get('billing'))
            submitted = st.form_submit_button('Uložit fakturační údaje')
        if submitted:
            try:
                save(reservation['id'], data)
            except StorageError as error:
                st.error(str(error))
            else:
                ui.flash('Fakturační údaje byly uloženy.')
                st.rerun()
        if enabled() and reservation['status'] == 'confirmed':
            if st.button('Vytvořit fakturu ke schválené rezervaci', key='billing_enqueue_' + reservation['id']):
                try:
                    call('status', id=reservation['id'], status='Potvrzeno - čeká na zaplacení')
                except StorageError as error:
                    st.error(str(error))
                else:
                    st.rerun()
