"""Ingest CBZ/CBR files into the store, then render their thumbnails.

    python3 ingest.py <dir>            # <dir>/<Series name>/<chapter>.cbz|cbr + info.json (see info.py)
    python3 ingest.py <dir> --force    # re-import chapters already in the store

Incremental: a chapter whose source file (name + size) is already indexed is skipped.
Each chapter is written to a temp dir and renamed into place, so a crash never leaves
a half-imported chapter visible to the server.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from PIL import Image

import info as infofile
import store
import thumbs

MAX_W = 1400
IMG = re.compile(r'\.(jpe?g|png|webp|gif)$', re.I)

# Patrones de numero de capitulo, en orden de prioridad. Cada uno captura el
# numero en grupo 1. Se buscan sobre el nombre sin extension.
_CHAPTER_PATTERNS = [
    # "Capitulo 12.5 Título_hex" (formato propio de Lecto)
    re.compile(r'Cap[ií]tulo\s+([0-9.]+)\s*(.*?)_[0-9a-f]{6}$', re.I),
    # "Capitulo 12.5", "Chapter 12.5", "Ch.12", "Chap.12.5", "Cap.12.5"
    # (sin \b final: "Capitulo" es palabra mas larga y \bcap\b no lo pilla)
    re.compile(r'(?:cap[ií]tulo|chapter|chap|ch|cap)\.?\s*([0-9]+(?:\.[0-9]+)?)', re.I),
    # "c003" standalone (de "Vol. 01 c003") -- va antes que vol para no capturar el vol
    re.compile(r'\bc\b\.?\s*([0-9]+(?:\.[0-9]+)?)', re.I),
    # "#12" o "#12.5"
    re.compile(r'#([0-9]+(?:\.[0-9]+)?)'),
    # "Vol. 01", "v01", "Tomo 3" (ultimo recurso: si no hay chapter, el tomo ordena)
    re.compile(r'\b(?:vol|volume|tomo|v)\.?\s*([0-9]+)', re.I),
]

# Sufijos que indican que viene un titulo despues del numero: _ -espacio
_TITLE_SEP = re.compile(r'[_\-\s]+(.+)$')


def chapter_meta(fn):
    """Devuelve (numero, titulo) de un nombre de archivo de capitulo.

    Soporta los formatos comunes: "Capitulo 12.5 Titulo", "Chapter 12.5",
    "Ch.12", "Cap.12", "#12", "Vol. 01 c003", "v01 c003", "Tomo 3". Si no se
    puede sacar un numero de ningun patron, usa 0.0 (el orden natural del
    nombre de archivo decide el orden; el desambiguador evita colisiones).
    El titulo es lo que sobra despues del numero, o el nombre del archivo sin
    extension si no hay match.
    """
    base = os.path.splitext(fn)[0]
    for pat in _CHAPTER_PATTERNS:
        m = pat.search(base)
        if not m:
            continue
        num = float(m.group(1))
        # intentar sacar un titulo de lo que queda despues del match
        after = base[m.end():]
        title = ''
        tm = _TITLE_SEP.match(after)
        if tm:
            title = tm.group(1).strip()
        return num, title
    # sin match: numero 0, el nombre del archivo es el titulo
    return 0.0, base


def natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', path)]


def extract(path, dst):
    if path.lower().endswith('.cbz'):
        with zipfile.ZipFile(path) as z:
            z.extractall(dst)
    else:
        subprocess.run(['bsdtar', '-xf', path, '-C', dst], check=True)
    files = [os.path.join(d, f) for d, _, fs in os.walk(dst) for f in fs if IMG.search(f)]
    return sorted(files, key=lambda p: natural(os.path.relpath(p, dst)))


def _chapter_id(num, cid, taken, fn, sid):
    """Desambigua un cid si ya esta tomado por otro archivo.

    Si dos archivos dan el mismo cid (p. ej. "Capitulo 1.cbz" y "Chapter 1.cbz"),
    se anade un sufijo _2, _3... y se avisa por log. El cid base es c<numero>; el
    desambiguador solo actua cuando hay colision real.
    """
    base = cid
    n = 2
    while cid in taken:
        cid = f'{base}_{n}'
        n += 1
    if cid != base:
        print(f'warn: {sid}: "{fn}" colisiona con otro capitulo; renombrado a {cid}', flush=True)
    taken.add(cid)
    return cid


def import_chapter(c, sid, src, force, taken_ids):
    fn = os.path.basename(src)
    num, title = chapter_meta(fn)
    cid = _chapter_id(num, f'c{num:g}'.replace('.', '_'), taken_ids, fn, sid)
    size = os.path.getsize(src)
    row = c.execute('select source_file, source_size from chapters where series_id=? and id=?', (sid, cid)).fetchone()
    if row and row['source_file'] == fn and row['source_size'] == size and not force:
        return cid, 0
    final = os.path.join(store.PAGES, sid, cid)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f'.{cid}-', dir=os.path.dirname(final))
    dims = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, p in enumerate(extract(src, tmp), 1):
            with Image.open(p) as im:
                im = im.convert('RGB')
                if im.width > MAX_W:
                    im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
                out = os.path.join(staging, f'{i:03d}.jpg')
                im.save(out, quality=84)
                dims.append((i, im.width, im.height, os.path.getsize(out)))
    if os.path.exists(final):
        shutil.rmtree(final)
    os.replace(staging, final)
    # Old thumbs belong to the previous import of this chapter.
    for sz in thumbs.SIZES:
        shutil.rmtree(os.path.join(store.THUMBS, sz, sid, cid), ignore_errors=True)
    with c:
        c.execute('delete from pages where series_id=? and chapter_id=?', (sid, cid))
        c.executemany('insert into pages values (?,?,?,?,?,?)', [(sid, cid, n, w, h, b) for n, w, h, b in dims])
        c.execute('insert or replace into chapters values (?,?,?,?,?,?,?)', (sid, cid, num, title, fn, size, time.time()))
    return cid, len(dims)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root, force = os.path.expanduser(sys.argv[1]), '--force' in sys.argv
    c = store.connect()
    for folder in sorted(os.listdir(root)):
        sp = os.path.join(root, folder)
        if not os.path.isdir(sp):
            continue
        info = infofile.load(sp)
        sid = info['id']
        files = sorted((f for f in os.listdir(sp) if f.lower().endswith(('.cbz', '.cbr'))), key=lambda f: chapter_meta(f)[0])
        # taken_ids: cids ya reclamados por OTROS archivos en esta ronda de
        # ingest (no de la DB). El desambiguador solo actua cuando dos archivos
        # distintos colisionan al mismo cid; no debe dispararse al reimportar
        # con --force un capitulo que ya existe bajo el mismo cid.
        taken = set()
        got = [import_chapter(c, sid, os.path.join(sp, f), force, taken) for f in files]
        store.put_series(c, sp, info)
        print(f'{sid}: ' + ', '.join(f'{cid} ({n} pág. nuevas)' if n else f'{cid} (ya estaba)' for cid, n in got), flush=True)

    t = time.time()
    w = thumbs.Warmer()
    n = w.warm_missing(c)
    w.wait()
    print(f'thumbnails: {n} generados en {time.time() - t:.1f}s, {w.status()["failed"]} fallidos')
    print(store.stats(c))


if __name__ == '__main__':
    main()
