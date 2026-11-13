"""Vault ("Caja fuerte"): series kept out of the catalog behind a PIN, shared by every device.

    <store>/vault.json   {"salt": hex, "hash": sha256(salt:pin), "series": [ids]}

The catalog never lists vault series; their entries come only from open(pin). This is privacy
in the app, not access control: pages and thumbnails of a vault series are still served to
whoever already has the server's token and knows the ids.

Wrong PINs are rate limited per server process: after 5 in a row, 30 s of 429.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

import store

PIN = re.compile(r'^\d{4,6}$')
MAX_FAILS, LOCK_S = 5, 30

_lock = threading.Lock()
_fails = {'n': 0, 'until': 0.0}


class Invalid(ValueError):
    pass


class Locked(Exception):
    pass


def _path():
    return os.path.join(store.ROOT, 'vault.json')


def _read():
    try:
        with open(_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(v):
    os.makedirs(store.ROOT, exist_ok=True)
    tmp = _path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(v, f)
    os.replace(tmp, _path())


def _digest(salt, pin):
    return hashlib.sha256(f'{salt}:{pin}'.encode()).hexdigest()


def _pin(pin):
    if not isinstance(pin, str) or not PIN.match(pin):
        raise Invalid('pin must be 4 to 6 digits')
    return pin


def series_ids():
    v = _read()
    return list(v.get('series', [])) if v else []


def version():
    """Changes whenever the vault does (the catalog cache keys on it)."""
    try:
        return os.path.getmtime(_path())
    except OSError:
        return 0


def status():
    return {'configured': _read() is not None}


def create(pin):
    with _lock:
        if _read() is not None:
            raise Invalid('the vault already has a PIN')
        salt = secrets.token_hex(16)
        _write({'salt': salt, 'hash': _digest(salt, _pin(pin)), 'series': []})


def check(pin):
    """True if the PIN opens the vault. Raises Locked while too many wrong tries are cooling down."""
    with _lock:
        if time.time() < _fails['until']:
            raise Locked()
        v = _read()
        ok = bool(v) and isinstance(pin, str) and hmac.compare_digest(_digest(v['salt'], pin), v['hash'])
        if ok:
            _fails['n'] = 0
        else:
            _fails['n'] += 1
            if _fails['n'] >= MAX_FAILS:
                _fails['n'], _fails['until'] = 0, time.time() + LOCK_S
        return ok


def add(ids, known):
    """Hiding needs no PIN (only a vault that exists)."""
    with _lock:
        v = _read()
        if v is None:
            raise Invalid('create the vault PIN first')
        if not isinstance(ids, list):
            raise Invalid('series must be a list of ids')
        v['series'] = list(dict.fromkeys(v.get('series', []) + [i for i in ids if i in known]))
        _write(v)


def remove(ids):
    with _lock:
        v = _read()
        if v is None:
            return
        v['series'] = [i for i in v.get('series', []) if i not in set(ids or [])]
        _write(v)


def reset():
    """Forgotten PIN: the vault is emptied and its series go back to the catalog."""
    with _lock:
        try:
            os.remove(_path())
        except OSError:
            pass
