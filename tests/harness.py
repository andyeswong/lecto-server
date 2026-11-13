"""Arranque del servidor en puerto efimero + cliente HTTP para pruebas.

Los modulos del servidor cachean variables de entorno al importar (PORT, WEB,
store.ROOT). Para cada suite se recargan los modulos en orden de dependencia
tras fijar LECTO_STORE/PORT/TOKEN, y se lanza un ThreadingHTTPServer en puerto
0 (efimero). El servidor vivo de ningun servidor en marcha no se toca: este es otro
proceso, otra store, otro puerto.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

_FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

_MODULES = ('collections_db', 'favs_db', 'vault_db', 'store', 'info', 'thumbs', 'server')


def start_server(store_dir, web_dir=None, token=None, cors=None):
    """Fija env, recarga modulos y arranca un servidor efimero. Devuelve (httpd, base_url)."""
    os.environ['LECTO_STORE'] = store_dir
    os.environ['LECTO_PORT'] = '0'
    os.environ['LECTO_WEB'] = web_dir or os.path.join(store_dir, 'web')
    os.environ['LECTO_LOG'] = '1'
    if token is not None:
        os.environ['LECTO_TOKEN'] = token
    else:
        os.environ.pop('LECTO_TOKEN', None)
    if cors is not None:
        os.environ['LECTO_CORS'] = cors
    else:
        os.environ.pop('LECTO_CORS', None)

    import collections_db, favs_db, vault_db, store, info, thumbs, server  # noqa: F401  asegura entrada a sys.modules
    mods = {m: importlib.import_module(m) for m in _MODULES}
    # orden de dependencia: sin deps -> con deps
    for m in ('collections_db', 'store', 'info', 'thumbs', 'server'):
        mods[m] = importlib.reload(mods[m])

    srv = mods['server']
    srv.ThreadingHTTPServer.daemon_threads = True
    httpd = srv.ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{httpd.server_address[1]}'
    return httpd, base


def ingest_library(path, force=False):
    """Corre ingest.main() sobre <path> con biblioteca sintetica."""
    import ingest
    importlib.reload(ingest)
    old = sys.argv
    sys.argv = ['ingest', path] + (['--force'] if force else [])
    try:
        ingest.main()
    finally:
        sys.argv = old


# ---- cliente HTTP ----------------------------------------------------------
def http(base, method, path, body=None, headers=None, token=None, raw=False):
    """Devuelve (status, headers_dict, body_bytes). body es dict -> JSON."""
    url = base + path
    h = dict(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault('Content-Type', 'application/json')
    if token:
        h['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_body = resp.read()
            return resp.status, dict(resp.headers), raw_body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def http_json(base, method, path, body=None, headers=None, token=None):
    """Como http() pero parsea el cuerpo como JSON (None si vacio o invalido)."""
    code, hdrs, raw_body = http(base, method, path, body, headers, token)
    try:
        return code, json.loads(raw_body) if raw_body else None
    except (ValueError, json.JSONDecodeError):
        return code, None


class ServerTest(unittest.TestCase):
    """Suite base: store efimera, biblioteca sintetica ingerida, servidor arriba."""
    token = None
    cors = None

    @classmethod
    def setUpClass(cls):
        cls.store = tempfile.mkdtemp(prefix='lecto-test-')
        cls.web = tempfile.mkdtemp(prefix='lecto-web-')
        cls.httpd, cls.base = start_server(cls.store, cls.web, token=cls.token, cors=cls.cors)
        from tests.fixtures import make_library
        cls.library = os.path.join(cls.store, 'library')
        make_library(cls.library)
        ingest_library(cls.library)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.store, ignore_errors=True)
        shutil.rmtree(cls.web, ignore_errors=True)
