"""Lecto server: library API, page originals, thumbnail engine and the web build.

    GET  /api/catalog                         series, chapters, page dimensions
    GET  /api/pages/<series>/<chapter>/<n>.jpg
    GET  /api/pages/<series>/<chapter>/<n>.png   la misma pagina en PNG, como descarga
    GET  /api/thumbs/<s|m|l>/<series>/<chapter>/<n>.webp   rendered on first request, then cached
    GET  /api/stats                           store, thumb cache and warm-up status
    GET  /api/settings                        global reading defaults + allowed values
    PUT  /api/settings/reading                change global defaults ({"layout": "double"}; null = factory)
    PUT  /api/series/<series>/reading         per-series overrides, written to its info.json (null = use default)
    GET  /api/collections                     [{id, name, series: [ids]}] in display order
    POST /api/collections                     {name, series?} -> the new collection
    PUT  /api/collections/<id>                {name?, series? (full ordered list), position?}
    DELETE /api/collections/<id>
    GET  /api/favs                            [{id, kind, series, chapter?, page?, rect?, created}] newest first
    POST /api/favs                            {kind: series|page|crop, series, chapter?, page?, rect?}
                                              -> 201 new, 200 if that series/page was already kept
    DELETE /api/favs/<id>
    GET  /api/vault                           {configured}
    POST /api/vault/create {pin}              first PIN (4-6 digits)
    POST /api/vault/open {pin}                {series: [catalog entries]} of the vault; 403 wrong PIN, 429 too many
    POST /api/vault/add {series: [ids]}       hide series (no PIN needed)
    POST /api/vault/remove {pin, series}      back to the catalog
    POST /api/vault/reset                     forgotten PIN: empties the vault, its series come back
    DELETE /api/series/<id>/chapters/<cid>    delete a chapter: its file in the library too
    GET  /api/favs/<id>.webp                  a crop as an image (cached); .png as a download
    POST /api/thumbs/warm                     render every missing thumb in the background
    GET  /*                                   the Expo web export (LECTO_WEB)

Config (env vars, sin rutas hardcodeadas de la casa):
    LECTO_STORE     carpeta del indice + originales + thumbs (default ./store)
    LECTO_WEB       carpeta del build web (Expo export)
    LECTO_PORT      puerto (default 8790)
    LECTO_LIBRARY   carpeta a ingerir con ingest.py
    LECTO_TOKEN     si se pone, /api/* exige Authorization: Bearer <token>
    LECTO_CORS      valor de Access-Control-Allow-Origin (default *)
    LECTO_BODY_MAX  tope de body en bytes (default 16384)
    LECTO_LOG       si esta a 1, loguea cada peticion

Arranque:
    python3 server/server.py          # desde el raiz del repo
    python3 server/                   # idem via __main__.py
"""
import gzip
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from PIL import Image

import collections_db
import favs_db
import vault_db
import info as infofile
import store
import thumbs

PORT = int(os.environ.get('LECTO_PORT', '8790'))
WEB = os.path.expanduser(os.environ.get('LECTO_WEB', './web'))
LIBRARY = os.path.expanduser(os.environ.get('LECTO_LIBRARY', './library'))
# Seguridad: si LECTO_TOKEN esta vacio, no hay auth (backwards compatible). Si
# se pone, todo /api/* exige `Authorization: Bearer <token>`. El preflight CORS
# (OPTIONS) nunca lo exige: el navegador no envia el header ahi.
TOKEN = os.environ.get('LECTO_TOKEN', '').strip()
CORS = os.environ.get('LECTO_CORS', '*')
# Sesion por cookie para el cliente web (los <img src> no pueden mandar headers).
# El valor de la cookie es sha256(token): no el token en claro, pero verificable.
SESSION_COOKIE = 'lecto_session'
SESSION_HASH = hashlib.sha256(TOKEN.encode()).hexdigest() if TOKEN else ''
BODY_MAX = int(os.environ.get('LECTO_BODY_MAX', '16384'))
IMMUTABLE = 'public, max-age=31536000, immutable'
# Tipos que comprimimos con gzip: texto. Imagenes (webp, jpg) ya vienen comprimidas.
GZIP_TYPES = frozenset(('text/html', 'text/css', 'text/plain', 'application/json',
                        'application/javascript', 'text/javascript',
                        'application/xml', 'text/xml'))
GZIP_MIN = 1024  # no vale la pena comprimir por debajo de 1 KB

PAGE = re.compile(r'^/api/pages/([a-z0-9_-]+)/([a-z0-9_-]+)/(\d{1,4})\.jpg$')
PAGE_PNG = re.compile(r'^/api/pages/([a-z0-9_-]+)/([a-z0-9_-]+)/(\d{1,4})\.png$')
COLLECTION = re.compile(r'^/api/collections/([0-9a-f]{8})$')
CHAPTER = re.compile(r'^/api/series/([a-z0-9_-]+)/chapters/([a-z0-9_-]+)$')
FAV = re.compile(r'^/api/favs/([0-9a-f]{12})$')
FAV_IMG = re.compile(r'^/api/favs/([0-9a-f]{12})\.(webp|png)$')
SERIES_READING = re.compile(r'^/api/series/([a-z0-9_-]+)/reading$')
THUMB = re.compile(r'^/api/thumbs/([a-z]+)/([a-z0-9_-]+)/([a-z0-9_-]+)/(\d{1,4})\.webp$')

warmer = thumbs.Warmer()
_cat_lock = threading.Lock()
_cat = {'mtime': None, 'body': b''}


def catalog_body():
    """Catalog JSON without the vault's series, rebuilt only when the index or the vault changed."""
    mt = (max((os.path.getmtime(p) for p in (store.DB, store.DB + '-wal') if os.path.exists(p)), default=0), vault_db.version())
    with _cat_lock:
        if _cat['mtime'] != mt:
            c = store.connect()
            hidden = set(vault_db.series_ids())
            _cat['body'] = json.dumps([s for s in store.catalog(c) if s['id'] not in hidden], ensure_ascii=False, separators=(',', ':')).encode()
            c.close()
            _cat['mtime'] = mt
        return _cat['body']


def vault_post(path, body):
    """(status, json) for POST /api/vault/*."""
    try:
        if path == '/api/vault/create':
            vault_db.create(body.get('pin'))
            return 201, vault_db.status()
        if path == '/api/vault/add':
            c = store.connect()
            known = {s['id'] for s in store.catalog(c)}
            c.close()
            vault_db.add(body.get('series'), known)
            return 200, {'ok': True}
        if path == '/api/vault/reset':
            vault_db.reset()
            return 200, vault_db.status()
        if path in ('/api/vault/open', '/api/vault/remove'):
            if not vault_db.check(body.get('pin')):
                return 403, {'error': 'wrong pin'}
            if path == '/api/vault/remove':
                vault_db.remove(body.get('series'))
                return 200, {'ok': True}
            ids = vault_db.series_ids()
            c = store.connect()
            series = [s for s in store.catalog(c) if s['id'] in ids]
            c.close()
            return 200, {'series': series}
    except vault_db.Locked:
        return 429, {'error': 'too many wrong pins, wait 30 s'}
    except ValueError as e:
        return 400, {'error': str(e)}
    return 404, {'error': 'not found'}


def crops_dir():
    return os.path.join(store.ROOT, 'crops')

CROP_MAX = 1200  # longest side of a crop image, px


def crop_box(size, rect):
    w, h = size
    x, y, rw, rh = rect
    return (round(x * w), round(y * h), round((x + rw) * w), round((y + rh) * h))


def crop_webp(fav, src):
    """The crop of a fav as WebP, made once and kept (crops never change; deleting the fav drops it)."""
    out = os.path.join(crops_dir(), f"{fav['id']}.webp")
    if not os.path.exists(out):
        os.makedirs(crops_dir(), exist_ok=True)
        with Image.open(src) as im:
            im = im if im.mode in ('L', 'RGB') else im.convert('RGB')
            im = im.crop(crop_box(im.size, fav['rect']))
            im.thumbnail((CROP_MAX, CROP_MAX))
            tmp = out + '.tmp'
            im.save(tmp, 'WEBP', quality=85)
            os.replace(tmp, out)
    return out


class _Conn:
    """`with self.db() as c`: a store connection closed on exit."""
    def __enter__(self):
        self.c = store.connect()
        return self.c

    def __exit__(self, *exc):
        self.c.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'lecto/1'

    def log_message(self, fmt, *args):
        if os.environ.get('LECTO_LOG'):
            super().log_message(fmt, *args)

    def _accepts_gzip(self):
        return 'gzip' in (self.headers.get('Accept-Encoding', '') or '').lower()

    def _gzip_body(self, body):
        """gzip en memoria. Para cuerpos pequenos o de imagen, devolver None."""
        return gzip.compress(body) if body else None

    def send(self, code, body=b'', ctype='application/json', cache='no-cache'):
        out = body
        encoding = None
        # gzip solo para texto, y solo si el cliente lo acepta y el cuerpo es digno
        if (ctype in GZIP_TYPES and self._accepts_gzip()
                and len(body) >= GZIP_MIN):
            out = self._gzip_body(body)
            encoding = 'gzip'
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(out)))
        self.send_header('Cache-Control', cache)
        if encoding:
            self.send_header('Content-Encoding', encoding)
            self.send_header('Vary', 'Accept-Encoding')
        self.send_header('Access-Control-Allow-Origin', CORS)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(out)

    def send_png_download(self, path, filename, rect=None):
        # Converted on demand: downloads are rare and PNG pages are 3-5x the JPG, not worth storing.
        buf = io.BytesIO()
        with Image.open(path) as im:
            im = im if im.mode in ('L', 'RGB') else im.convert('RGB')
            if rect:
                im = im.crop(crop_box(im.size, rect))
            im.save(buf, 'PNG', optimize=False, compress_level=6)
        body = buf.getvalue()
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Cache-Control', 'private, max-age=3600')
        self.send_header('Access-Control-Allow-Origin', CORS)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_file(self, path, ctype, cache):
        etag = '"%x-%x"' % (int(os.path.getmtime(path)), os.path.getsize(path))
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.end_headers()
            return
        gzip_ok = ctype in GZIP_TYPES and self._accepts_gzip()
        # Estaticos inmutables (/_expo/static/): servir .gz precomprimido si existe
        if gzip_ok and '/_expo/static/' in path.replace(os.sep, '/'):
            gz = path + '.gz'
            if os.path.exists(gz):
                with open(gz, 'rb') as f:
                    body = f.read()
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', cache)
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Vary', 'Accept-Encoding')
                self.send_header('ETag', etag)
                self.send_header('Access-Control-Allow-Origin', CORS)
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)
                return
        with open(path, 'rb') as f:
            body = f.read()
        out = body
        encoding = None
        if gzip_ok and len(body) >= GZIP_MIN:
            out = self._gzip_body(body)
            encoding = 'gzip'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(out)))
        self.send_header('Cache-Control', cache)
        if encoding:
            self.send_header('Content-Encoding', encoding)
            self.send_header('Vary', 'Accept-Encoding')
        self.send_header('ETag', etag)
        self.send_header('Access-Control-Allow-Origin', CORS)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(out)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', CORS)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def _auth_ok(self):
        """True si no hay token configurado, o si llega por Bearer o por cookie."""
        if not TOKEN:
            return True
        if self.headers.get('Authorization', '') == f'Bearer {TOKEN}':
            return True
        # cookie de sesion (para <img src> del cliente web)
        for pair in self.headers.get('Cookie', '').split(';'):
            k, _, v = pair.strip().partition('=')
            if k == SESSION_COOKIE and v == SESSION_HASH:
                return True
        return False

    def _set_session_cookie(self):
        self.send_header('Set-Cookie',
                         f'{SESSION_COOKIE}={SESSION_HASH}; Path=/; HttpOnly; SameSite=Strict')

    def _clear_session_cookie(self):
        self.send_header('Set-Cookie',
                         f'{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')

    def _session_login(self):
        """POST /api/session {token}: valida el token y setea cookie HttpOnly."""
        if not TOKEN:
            return self.json({'error': 'token auth not enabled'}, 400)
        try:
            body = self.body()
        except ValueError as e:
            return self.json({'error': str(e)}, 400)
        if body.get('token') != TOKEN:
            return self.json({'error': 'invalid token'}, 401)
        # enviar la cookie como parte de la misma respuesta (antes de end_headers)
        body_out = b'{"ok":true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body_out)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', CORS)
        self._set_session_cookie()
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body_out)

    def _session_logout(self):
        """DELETE /api/session: borra la cookie de sesion."""
        body_out = b'{"ok":true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body_out)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', CORS)
        self._clear_session_cookie()
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body_out)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        # Public handshake: lets a client check that an address is a library server and
        # whether it needs a token, before asking the user for one. Reveals nothing else.
        if path == '/api/info':
            return self.json({'server': 'lecto', 'api': 1, 'auth': bool(TOKEN), 'session': self._auth_ok()})
        if path.startswith('/api/') and not self._auth_ok():
            return self.json({'error': 'unauthorized'}, 401)
        try:
            if path == '/api/catalog':
                return self.send(200, catalog_body())
            if m := THUMB.match(path):
                size, sid, cid, n = m.groups()
                if size not in thumbs.SIZES:
                    return self.json({'error': f'size must be one of {list(thumbs.SIZES)}'}, 400)
                p = thumbs.ensure(size, sid, cid, int(n))
                return self.send_file(p, 'image/webp', IMMUTABLE) if p else self.json({'error': 'no such page'}, 404)
            if m := PAGE.match(path):
                sid, cid, n = m.groups()
                p = store.page_path(sid, cid, int(n))
                return self.send_file(p, 'image/jpeg', IMMUTABLE) if os.path.exists(p) else self.json({'error': 'no such page'}, 404)
            if m := PAGE_PNG.match(path):
                sid, cid, n = m.groups()
                p = store.page_path(sid, cid, int(n))
                if not os.path.exists(p):
                    return self.json({'error': 'no such page'}, 404)
                return self.send_png_download(p, f'{sid}-{cid}-p{int(n):03d}.png')
            if path == '/api/settings':
                return self.json({'reading': infofile.defaults(), 'options': {k: list(v) for k, v in infofile.READING.items()}})
            if path == '/api/collections':
                with self.db() as c:
                    return self.json(collections_db.list_all(c))
            if path == '/api/favs':
                with self.db() as c:
                    return self.json(favs_db.list_all(c))
            if path == '/api/vault':
                return self.json(vault_db.status())
            if m := FAV_IMG.match(path):
                with self.db() as c:
                    fav = favs_db.get(c, m.group(1))
                if not fav or fav['kind'] != 'crop':
                    return self.json({'error': 'no such crop'}, 404)
                src = store.page_path(fav['series'], fav['chapter'], fav['page'])
                if not os.path.exists(src):
                    return self.json({'error': 'no such page'}, 404)
                if m.group(2) == 'png':
                    return self.send_png_download(src, f"{fav['series']}-{fav['chapter']}-p{fav['page']:03d}-panel.png", fav['rect'])
                return self.send_file(crop_webp(fav, src), 'image/webp', IMMUTABLE)
            if path == '/api/stats':
                c = store.connect()
                out = {'store': store.stats(c), 'thumbs': thumbs.disk_usage(), 'warmer': warmer.status()}
                c.close()
                return self.json(out)
            return self.static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            print('error', path, repr(e), file=sys.stderr, flush=True)
            self.json({'error': str(e)}, 500)

    def db(self):
        return _Conn()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/session':
            return self._session_login()
        if path.startswith('/api/') and not self._auth_ok():
            return self.json({'error': 'unauthorized'}, 401)
        if path == '/api/collections':
            try:
                with self.db() as c:
                    return self.json(collections_db.create(c, self.body()), 201)
            except ValueError as e:
                return self.json({'error': str(e)}, 400)
        if path.startswith('/api/vault/'):
            try:
                body = self.body()
            except ValueError as e:
                return self.json({'error': str(e)}, 400)
            code, out = vault_post(path, body if isinstance(body, dict) else {})
            return self.json(out, code)
        if path == '/api/favs':
            try:
                with self.db() as c:
                    fav, new = favs_db.create(c, self.body())
                return self.json(fav, 201 if new else 200)
            except ValueError as e:
                return self.json({'error': str(e)}, 400)
        if urlparse(self.path).path == '/api/thumbs/warm':
            c = store.connect()
            n = warmer.warm_missing(c)
            c.close()
            return self.json({'queued': n, **warmer.status()})
        self.json({'error': 'not found'}, 404)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > BODY_MAX:
            raise ValueError('body too large')
        return json.loads(self.rfile.read(n) or b'{}')

    def do_PUT(self):
        path = urlparse(self.path).path
        if path.startswith('/api/') and not self._auth_ok():
            return self.json({'error': 'unauthorized'}, 401)
        try:
            if path == '/api/settings/reading':
                return self.json({'reading': infofile.set_defaults(self.body())})
            if m := COLLECTION.match(path):
                with self.db() as c:
                    col = collections_db.update(c, m.group(1), self.body())
                return self.json(col) if col else self.json({'error': 'no such collection'}, 404)
            if m := SERIES_READING.match(path):
                # Separar la lectura (SELECT) de la escritura (INSERT): el I/O
                # de patch_reading (leer/escribir info.json) no debe ocurrir con
                # una transaccion de SQLite abierta, porque alarga la ventana de
                # contention. Cerrar la conexion de lectura antes del I/O.
                c = store.connect()
                folder = store.series_folder(c, m.group(1))
                c.close()
                if not folder:
                    return self.json({'error': 'no such series'}, 404)
                info = infofile.patch_reading(folder, self.body())
                c = store.connect()
                try:
                    store.put_series(c, folder, info)
                finally:
                    c.close()
                return self.json({'reading': info['reading']})
            self.json({'error': 'not found'}, 404)
        except ValueError as e:  # includes bad JSON
            self.json({'error': str(e)}, 400)
        except Exception as e:
            print('error', path, repr(e), file=sys.stderr, flush=True)
            self.json({'error': str(e)}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == '/api/session':
            return self._session_logout()
        if path.startswith('/api/') and not self._auth_ok():
            return self.json({'error': 'unauthorized'}, 401)
        if m := CHAPTER.match(path):
            with self.db() as c:
                ok = store.delete_chapter(c, m.group(1), m.group(2))
            return self.json({'deleted': m.group(2)}) if ok else self.json({'error': 'no such chapter'}, 404)
        if m := FAV.match(path):
            with self.db() as c:
                ok = favs_db.delete(c, m.group(1))
            if ok:
                for ext in ('webp',):
                    try:
                        os.remove(os.path.join(crops_dir(), f'{m.group(1)}.{ext}'))
                    except OSError:
                        pass
            return self.json({'deleted': m.group(1)}) if ok else self.json({'error': 'no such fav'}, 404)
        m = COLLECTION.match(path)
        if not m:
            return self.json({'error': 'not found'}, 404)
        with self.db() as c:
            ok = collections_db.delete(c, m.group(1))
        return self.json({'deleted': m.group(1)}) if ok else self.json({'error': 'no such collection'}, 404)

    def static(self, path):
        if path.startswith('/api/'):
            return self.json({'error': 'not found'}, 404)
        rel = os.path.normpath(path.lstrip('/')) if path != '/' else 'index.html'
        full = os.path.join(WEB, rel)
        if not os.path.realpath(full).startswith(os.path.realpath(WEB)):
            return self.json({'error': 'forbidden'}, 403)
        if not os.path.isfile(full):
            full = os.path.join(WEB, 'index.html')  # SPA fallback
        if not os.path.isfile(full):
            return self.json({'error': 'web build not found'}, 404)
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        cache = IMMUTABLE if '/_expo/static/' in full else 'no-cache'
        self.send_file(full, ctype, cache)


def precompress_statics():
    """Precomprime los bundles inmutables de /_expo/static/ a .gz en disco.

    Idempotente: solo escribe .gz si no existe o si el original cambio.
    Sirve para que send_file() los sirva directamente sin comprimir en vivo.
    """
    static_dir = os.path.join(WEB, '_expo', 'static')
    if not os.path.isdir(static_dir):
        return
    n = 0
    for d, _, fs in os.walk(static_dir):
        for f in fs:
            if f.endswith('.gz'):
                continue
            src = os.path.join(d, f)
            gz = src + '.gz'
            if os.path.exists(gz) and os.path.getmtime(gz) >= os.path.getmtime(src):
                continue
            with open(src, 'rb') as fin:
                data = fin.read()
            with open(gz + '.tmp', 'wb') as fout:
                fout.write(gzip.compress(data))
            os.replace(gz + '.tmp', gz)
            n += 1
    if n:
        print(f'precompress: {n} archivos .gz', flush=True)


def main():
    c = store.connect()
    print(f'lecto en :{PORT} · store {store.ROOT} · {store.stats(c)["pages"]} páginas', flush=True)
    print(f'warm-up: {warmer.warm_missing(c)} thumbnails pendientes', flush=True)
    c.close()
    precompress_statics()
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
