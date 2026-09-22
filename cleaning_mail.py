"""Serverové spojení s koordinátorem úklidu; tajný klíč nikdy nejde do URL."""
import json
from urllib.request import Request, urlopen
from urllib.error import URLError
import storage
from domain import StorageError


def configured():
    cfg = storage.config().get('cleaning_mail', {})
    return bool(cfg.get('enabled') and cfg.get('url') and cfg.get('secret'))


def call(action, **payload):
    cfg = storage.config().get('cleaning_mail', {})
    if not configured():
        raise StorageError('E-mailové nabídky úklidu ještě nejsou aktivované.')
    return gateway_call(cfg, action, **payload)


def gateway_call(cfg, action, **payload):
    url = str(cfg['url'])
    if not url.startswith('https://script.google.com/macros/s/') or not url.endswith('/exec'):
        raise StorageError('Neplatná adresa koordinátoru.')
    body = json.dumps(dict(payload, action=action, secret=cfg['secret'])).encode()
    try:
        request = Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=35) as response:
            result = json.load(response)
    except (URLError, TimeoutError, ValueError, OSError):
        raise StorageError('Výsledek operace nelze ověřit. Obnovte data a zkuste to znovu; nejprve se ověří uložený výsledek.') from None
    if not result.get('ok'):
        raise StorageError(result.get('message', 'Operaci se nepodařilo dokončit.'))
    storage.refresh()
    return result
