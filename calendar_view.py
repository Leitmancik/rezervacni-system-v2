"""Klikací kalendář se samostatným zobrazením příjezdu a odjezdu."""
import calendar
from datetime import timedelta
from itertools import product
import streamlit as st
from domain import (MONTHS, half_states, shift_month, today, conflict,
                    date_label, price_for_night, money)

COLORS = {'free': '#f7f8f1', 'confirmed': '#f5b5b5', 'paid': '#f5b5b5', 'pending': '#f7ce91'}
LABELS = {'free': 'volno', 'confirmed': 'potvrzeno – čeká na zaplacení', 'paid': 'zaplaceno', 'pending': 'čeká na potvrzení'}


def choose(day):
    start = st.session_state.get('arrival')
    end = st.session_state.get('departure')
    if start is None or end is not None or day <= start:
        st.session_state['arrival'] = day
        st.session_state['departure'] = None
    else:
        st.session_state['departure'] = day
    st.session_state.pop('_request', None)


def clear():
    st.session_state['arrival'] = None
    st.session_state['departure'] = None
    st.session_state.pop('_request', None)


def move(offset):
    st.session_state['month'] = shift_month(st.session_state['month'], offset)


def render(reservations, prices):
    rules = []
    for morning, afternoon in product(COLORS, repeat=2):
        rules.append(f'[class*="st-key-day-"][class*="-{morning}-{afternoon}-"] button'
                     '{background:linear-gradient(135deg,' + COLORS[morning] + ' 50%,' + COLORS[afternoon] + ' 50%)}')
    st.html('<style>' + ''.join(rules) + '</style>')
    st.session_state.setdefault('month', today().replace(day=1))
    with st.container(key='calendar'):
        st.markdown('### Kdy si přijedete odpočinout?')
        start, end = st.session_state.get('arrival'), st.session_state.get('departure')
        st.caption('Ještě den odjezdu a máte vybráno.' if start and not end else
                   'Termín je vybraný. Cenu a žádost najdete v části Váš pobyt.' if start and end else
                   'Nejdřív příjezd, potom odjezd. Vyberte je přímo v kalendáři.')
        with st.container(key='calendar-nav'):
            nav = st.columns([1, 2, 1])
        nav[0].button('←', key='previous_month', help='Předchozí měsíc',
                      on_click=move, args=(-1,), width='stretch',
                      disabled=st.session_state['month'] <= today().replace(day=1))
        if nav[1].button('Tento měsíc', width='stretch'):
            st.session_state['month'] = today().replace(day=1)
            st.rerun()
        nav[2].button('→', key='next_month', help='Následující měsíc',
                      on_click=move, args=(1,), width='stretch')
        with st.container(key='calendar-months'):
            for col, offset in zip(st.columns(2, gap='large'), (0, 1)):
                with col, st.container(key='first-month' if offset == 0 else 'second-month'):
                    month(shift_month(st.session_state['month'], offset), reservations, prices)
        st.html('<div class="legend"><span><i class="dot free"></i>Volno</span>'
                '<span><i class="dot pending"></i>Čeká na potvrzení</span>'
                '<span><i class="dot confirmed"></i>Potvrzeno – čeká na zaplacení</span>'
                '<span><i class="dot paid"></i>Zaplaceno</span>'
                '<span><i class="dot change"></i>Příjezd / odjezd</span></div>')
        st.caption('Odjezd i nový příjezd mohou být ve stejný den. Čekající rezervace termín také blokují.')
        st.button('Vybrat jiný termín', type='tertiary', on_click=clear, disabled=start is None)
        st.html('<div class="info-strip"><span>Příjezd <b>od 15:00</b></span>'
                '<span>Odjezd <b>do 11:00</b></span><span>Cena <b>za celou chalupu / noc</b></span></div>')


def month(first, reservations, prices):
    st.html(f'<div class="calendar-title">{MONTHS[first.month - 1]} {first.year}</div>')
    for col, day_name in zip(st.columns(7), ['PO', 'ÚT', 'ST', 'ČT', 'PÁ', 'SO', 'NE']):
        col.html(f'<div class="weekday">{day_name}</div>')
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    while len(weeks) < 6:
        weeks.append([weeks[-1][-1] + timedelta(days=i) for i in range(1, 8)])
    start, end = st.session_state.get('arrival'), st.session_state.get('departure')
    for week in weeks:
        for col, day in zip(st.columns(7), week):
            with col:
                if day.month != first.month:
                    st.html('<div class="calendar-empty"></div>')
                    continue
                morning, afternoon = half_states(day, reservations)
                selected = day == start or day == end
                between = start and end and start < day < end
                state = 'selected' if selected else 'between' if between else 'idle'
                disabled = day < today()
                if start and end is None and day > start:
                    disabled = disabled or bool(conflict(start, day, reservations)) or (day - start).days > 365
                else:
                    disabled = disabled or afternoon != 'free'
                key = f'day-{day.isoformat()}-{morning}-{afternoon}-{state}'
                if day == today():
                    key += '-today'
                help_text = (f'{date_label(day)} · dopoledne {LABELS[morning]}, '
                             f'odpoledne {LABELS[afternoon]} · '
                             f'{money(price_for_night(day, prices))} / noc')
                st.button(str(day.day), key=key, help=help_text, disabled=disabled,
                          on_click=choose, args=(day,), width='stretch')
