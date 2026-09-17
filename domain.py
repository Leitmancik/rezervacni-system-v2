"""Pravidla rezervací a cen nezávislá na uživatelském rozhraní."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

RES_HEADER = ['Jméno', 'Příjmení', 'email', 'Datum - Start', 'Datum - Konec',
              'Stav', 'ID', 'Vytvořeno', 'Cena celkem']
PRICE_HEADER = ['Od', 'Do', 'Cena za noc', 'Popis', 'ID']
STATUS = {'pending': 'Čeká na potvrzení',
          'confirmed': 'Potvrzeno - čeká na zaplacení', 'paid': 'Zaplaceno'}
MONTHS = ['leden', 'únor', 'březen', 'duben', 'květen', 'červen', 'červenec',
          'srpen', 'září', 'říjen', 'listopad', 'prosinec']


class StorageError(Exception):
    """Chyba, kterou lze bezpečně zobrazit uživateli."""


def today():
    return datetime.now(ZoneInfo('Europe/Prague')).date()


def parse_date(value):
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d. %m. %Y', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise StorageError('V tabulce je neplatné datum. Opravte jej před pokračováním.')


def parse_money(value):
    if value is None or str(value).strip() == '':
        return None
    text = str(value).replace('Kč', '').replace('\u00a0', '').replace(' ', '')
    if isinstance(value, str) and re.fullmatch(r'\d{1,3}(\.\d{3})+', text):
        text = text.replace('.', '')
    text = text.replace(',', '.')
    try:
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return float(amount.quantize(Decimal('0.01')))
    except InvalidOperation:
        raise StorageError('V tabulce je neplatná cena. Použijte nezápornou částku.')


def conflict(start, end, reservations):
    return next((r for r in reservations
                 if start < r['date_to'] and r['date_from'] < end), None)


def half_states(day, reservations):
    morning = afternoon = 'free'
    for r in reservations:
        if r['date_from'] < day <= r['date_to']:
            morning = r['status']
        if r['date_from'] <= day < r['date_to']:
            afternoon = r['status']
    return morning, afternoon


def shift_month(day, offset):
    month = day.year * 12 + day.month - 1 + offset
    return date(month // 12, month % 12 + 1, 1)


def price_for_night(day, prices):
    seasons = sorted((p for p in prices if p['date_from'] is not None),
                     key=lambda p: ((p['date_to'] - p['date_from']).days))
    for p in seasons:
        if p['date_from'] <= day <= p['date_to']:
            return p['price']
    return next((p['price'] for p in prices if p['date_from'] is None), None)


def quote(start, end, prices):
    rows = []
    day = start
    while day < end:
        rows.append((day, price_for_night(day, prices)))
        day += timedelta(days=1)
    if not rows or any(price is None for _, price in rows):
        return None, rows
    total = sum(Decimal(str(price)) for _, price in rows)
    return float(total), rows


def validate_reservation(first, last, email, start, end):
    if not first.strip() or not last.strip():
        raise StorageError('Doplňte prosím jméno i příjmení.')
    if len(first.strip()) > 100 or len(last.strip()) > 100:
        raise StorageError('Jméno a příjmení mohou mít nejvýše 100 znaků.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
        raise StorageError('Zadejte prosím platnou e-mailovou adresu.')
    if start is None or end is None or end <= start:
        raise StorageError('Odjezd musí být alespoň den po příjezdu.')
    if start < today():
        raise StorageError('Příjezd nemůže být v minulosti.')
    if (end - start).days > 365:
        raise StorageError('Vyberte pobyt dlouhý nejvýše 365 nocí.')


def money(value):
    if value is None:
        return 'Cena na dotaz'
    digits = 0 if value == int(value) else 2
    return f'{value:,.{digits}f}'.replace(',', '\u00a0').replace('.', ',') + ' Kč'


def nights_label(count):
    return f'{count} ' + ('noc' if count == 1 else 'noci' if 2 <= count <= 4 else 'nocí')


def date_label(day):
    return day.strftime('%d. %m. %Y') if day else '—'


def created_label(value):
    """Zobrazí uloženou přesnost; čas s pásmem převede do Prahy."""
    text = str(value or '').strip()
    if not text:
        return 'Čas vytvoření není uložen'
    # Starším záznamům bez sekund nevymýšlíme přesný okamžik.
    has_seconds = bool(re.search(r'\d{1,2}:\d{2}:\d{2}', text))
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        stamp = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
                    '%d.%m.%Y %H:%M:%S', '%d. %m. %Y %H:%M:%S',
                    '%d.%m.%Y %H:%M', '%d. %m. %Y %H:%M'):
            try:
                stamp = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
    if stamp is None:
        return text
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(ZoneInfo('Europe/Prague'))
    if not has_seconds:
        return text + ' (sekundy nejsou uložené)'
    return stamp.strftime('%d. %m. %Y · %H:%M:%S')
