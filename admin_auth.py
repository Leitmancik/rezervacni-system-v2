"""Ochrana správy při zapojené fakturaci; heslo je pouze v serverových Secrets."""
import hashlib
import hmac
import time
import streamlit as st
import storage


def require():
    cfg = storage.config()
    password = str(cfg.get('admin', {}).get('password', ''))
    required = bool(cfg.get('fakturoid', {}).get('enabled') or password)
    if not required:
        return
    if len(password) < 16:
        st.error('Pro správu s fakturací nastavte v Secrets admin.password alespoň na 16 znaků.')
        st.stop()
    signature = hashlib.sha256(password.encode()).hexdigest()
    if hmac.compare_digest(str(st.session_state.get('_admin_auth', '')), signature):
        if st.button('Odhlásit ze správy', key='admin_logout', type='tertiary'):
            st.session_state.pop('_admin_auth', None)
            st.rerun()
        return
    st.subheader('Přihlášení majitele')
    with st.form('admin_login'):
        entered = st.text_input('Heslo', type='password')
        submit = st.form_submit_button('Přihlásit')
    if submit:
        if time.time() < st.session_state.get('_admin_next_attempt', 0):
            st.error('Před dalším pokusem chvíli počkejte.')
        elif hmac.compare_digest(entered.encode(), password.encode()):
            st.session_state['_admin_auth'] = signature
            st.session_state.pop('_admin_next_attempt', None)
            st.rerun()
        else:
            st.session_state['_admin_next_attempt'] = time.time() + 3
            st.error('Nesprávné heslo.')
    st.stop()


def check():
    """Kontrola bez widgetů pro callbacky a samostatné dialogové reruny."""
    from domain import StorageError
    cfg = storage.config()
    password = str(cfg.get('admin', {}).get('password', ''))
    if not cfg.get('fakturoid', {}).get('enabled') and not password:
        return
    signature = hashlib.sha256(password.encode()).hexdigest()
    if len(password) < 16 or not hmac.compare_digest(str(st.session_state.get('_admin_auth', '')), signature):
        raise StorageError('Pro tuto operaci se nejprve přihlaste jako majitel.')
