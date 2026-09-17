"""Společný vizuální styl a drobné prvky rozhraní."""
from html import escape
from pathlib import Path
import streamlit as st


def style():
    st.html('<style>' + Path(__file__).with_name('style.css').read_text() + '</style>')


def heading(eyebrow, title, subtitle):
    st.html(f'<div class="page-heading"><div class="eyebrow">{escape(eyebrow)}</div>'
            f'<h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>')


def flash(message):
    st.session_state['_flash'] = message


def show_flash():
    if message := st.session_state.pop('_flash', None):
        st.success(message, icon=':material/check_circle:')


def admin_note():
    st.caption('Vývojová verze · Správa je zatím přístupná bez přihlášení.')


def badge(text, tone='green'):
    return f'<span class="badge {tone}">{escape(text)}</span>'
