"""Biblioteca sintetica para pruebas de contrato del servidor Lecto.

Genera CBZ (y CBR-via-tar) con paginas hechas en Pillow, un info.json por serie
y una portada ancha para probar doble pagina. Nada de mangas reales; corre en CI
sin red ni archivos externos.

El contenedor puede importar esto para su biblioteca de ejemplo:

    from tests.fixtures import make_library
    make_library('/tmp/lecto-demo')

Notas:
- CBR es un tar.gz renombrado a .cbr. bsdtar (libarchive) detecta el formato por
  magic bytes, no por extension, asi que lo extrae igual que un RAR real. Esto
  prueba la rama no-CBZ de ingest.extract() sin necesitar rar/unrar.
- Los nombres de capitulo siguen el patron que ingest.chapter_meta() espera:
  "Capitulo <n> <titulo>_<6hex>.cbz" para que el slug y el numero salgan bien.
"""
import io
import json
import os
import tarfile
import zipfile

from PIL import Image, ImageDraw


# ---- paginas ---------------------------------------------------------------
def page_bytes(w, h, color=(180, 60, 60), text=None):
    """Una pagina JPEG en memoria."""
    im = Image.new('RGB', (w, h), color)
    if text:
        ImageDraw.Draw(im).text((12, 12), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=80)
    return buf.getvalue()


def _page_set(n, wide=False):
    """Lista de (nombre, jpeg_bytes). La pagina 1 es ancha si wide=True."""
    out = []
    for i in range(n):
        if wide and i == 0:
            w, h = 2000, 1000  # ancha: tras ingest (max 1400) queda 1400x700
        else:
            w, h = 800, 1200
        tone = (60 + (i * 37) % 180, 80 + (i * 53) % 160, 100 + (i * 71) % 140)
        out.append((f'{i + 1:03d}.jpg', page_bytes(w, h, color=tone, text=f'p{i + 1}')))
    return out


# ---- archives --------------------------------------------------------------
def make_cbz(path, n, wide=False):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in _page_set(n, wide):
            z.writestr(name, data)


def make_cbr(path, n):
    """CBR como tar.gz: bsdtar lee por magic, no por extension."""
    with tarfile.open(path, 'w:gz') as t:
        for name, data in _page_set(n):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


# ---- series ----------------------------------------------------------------
def info_json(sid, title, **extra):
    base = {
        'schema': 1,
        'id': sid,
        'title': title,
        'author': 'Autor Sintetico',
        'artist': 'Artista Sintetico',
        'description': f'Serie de prueba: {title}',
        'genres': ['Aventura'],
        'status': 'ongoing',
        'kind': 'manga',
        'language': 'es',
        'source': 'server',
        'cover': {'chapter': 'c1', 'page': 1},
    }
    base.update(extra)
    return base


def make_series(parent, sid, title, chapters=2, pages=3, fmt='cbz', wide=False, **info_extra):
    """Crea <parent>/<sid>/ con info.json y <chapters> archivos .cbz|cbr."""
    folder = os.path.join(parent, sid)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'info.json'), 'w', encoding='utf-8') as f:
        json.dump(info_json(sid, title, **info_extra), f, ensure_ascii=False, indent=2)
    make = make_cbz if fmt == 'cbz' else make_cbr
    for ch in range(1, chapters + 1):
        fn = f'Capitulo {ch} Nombre_{ch:06x}.{fmt}'
        if fmt == 'cbz':
            make(os.path.join(folder, fn), pages, wide=(wide and ch == 1))
        else:
            make(os.path.join(folder, fn), pages)
    return folder


def make_library(root):
    """Dos series CBZ + una CBR. Devuelve root."""
    os.makedirs(root, exist_ok=True)
    make_series(root, 'sintetica-uno', 'Serie Uno', chapters=2, pages=3, fmt='cbz', wide=True)
    make_series(root, 'sintetica-dos', 'Serie Dos', chapters=1, pages=2, fmt='cbz', wide=False)
    make_series(root, 'sintetica-cbr', 'Serie CBR', chapters=1, pages=2, fmt='cbr', wide=False)
    return root
