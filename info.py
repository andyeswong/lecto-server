"""Per-series metadata file: <series folder>/info.json.

Modelled on Mihon's local source (source-local/.../LocalSource.kt): every series folder carries
its own metadata file next to its chapters and an optional cover.jpg. Mihon uses ComicInfo.xml,
which only describes comics; ours is format-neutral so the same file describes a manga, a comic
or an ebook.

Reading settings work like Mihon's per-manga `viewer_flags`: a series stores only what the user
changed for it; anything missing falls back to the global defaults (store/settings.json).
Nothing is inferred from the kind: a manga is not assumed to be right-to-left.

    {
      "schema": 1,
      "id": "little-nemo",                       stable id, used in URLs; never derived again after creation
      "title": "Little Nemo in Slumberland",
      "author": "Winsor McCay", "artist": "Winsor McCay",
      "description": "", "genres": ["Fantasia"], "status": "completed",
      "kind": "manga",                       label only: manga | manhwa | manhua | comic | ebook | other
      "language": "es",
      "source": "device",                    where the files live: device | server
      "cover": {"chapter": "c1", "page": 3}, or absent to use page 1 of the first chapter
      "reading": {"direction": "rtl"}        overrides only, see READING
    }

When a folder has no info.json, one is created from what the files already say, in Mihon's
order: top-level ComicInfo.xml, legacy details.json, ComicInfo.xml inside the first chapter,
and finally the folder name.
"""
import json
import os
import re
import threading
import zipfile
import xml.etree.ElementTree as ET

import store

INFO_FILE = 'info.json'
SCHEMA = 1
KINDS = ('manga', 'manhwa', 'manhua', 'comic', 'ebook', 'other')
SOURCES = ('device', 'server')
SOURCE_ALIASES = {'tablet': 'device', 'servidor': 'server'}  # values written before 2026-11-08
STATUSES = ('unknown', 'ongoing', 'completed', 'hiatus', 'cancelled')

# Overlay para bibliotecas de solo lectura: si la carpeta de la serie no se
# puede escribir, info.json y los overrides de lectura van aqui. El formato
# canonico sigue siendo info.json en la carpeta; el overlay es solo el respaldo
# cuando no hay permiso de escritura.
OVERLAY_DIR = os.path.join(store.ROOT, 'info')


def _overlay_path(sid):
    return os.path.join(OVERLAY_DIR, f'{sid}.json')

# Reading settings: allowed values. The first value of each is the factory default.
READING = {
    'direction': ('ltr', 'rtl'),                      # page order for paged layouts
    'layout': ('auto', 'single', 'double', 'scroll'),  # auto = double in landscape, single in portrait
    'fit': ('screen', 'width'),
    'coverAlone': (True, False),                      # double layout: first page on its own
    'background': ('black', 'gray', 'white'),
}
FACTORY = {k: v[0] for k, v in READING.items()}
SETTINGS_FILE = os.path.join(store.ROOT, 'settings.json')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'serie'


def clean_reading(patch, allow_null):
    """Validate a partial reading dict. None removes an override when allow_null."""
    if not isinstance(patch, dict):
        raise ValueError('reading must be an object')
    out = {}
    for k, v in patch.items():
        if k not in READING:
            raise ValueError(f'unknown reading setting: {k}')
        if v is None and allow_null:
            out[k] = None
        elif v in READING[k] and type(v) is type(READING[k][0]):
            out[k] = v
        else:
            raise ValueError(f'{k} must be one of {list(READING[k])}')
    return out


def write_json(path, data):
    # .tmp unico por thread: dos PUT concurrentes en la misma serie no deben
    # pisar el .tmp del otro en os.replace.
    tmp = f'{path}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)


# ---- global defaults ------------------------------------------------------
def defaults():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            saved = json.load(f).get('reading', {})
        return {**FACTORY, **clean_reading(saved, False)}
    except (OSError, ValueError):
        return dict(FACTORY)


def set_defaults(patch):
    cur = defaults()
    for k, v in clean_reading(patch, True).items():
        cur[k] = FACTORY[k] if v is None else v
    os.makedirs(store.ROOT, exist_ok=True)
    write_json(SETTINGS_FILE, {'reading': cur})
    return cur


# ---- seeding from existing metadata --------------------------------------
def _comicinfo(root):
    get = lambda tag: (root.findtext(tag) or '').strip()
    genres = [g.strip() for g in get('Genre').split(',') if g.strip()]
    return {'title': get('Series') or get('Title'), 'author': get('Writer'), 'artist': get('Penciller'),
            'description': get('Summary'), 'genres': genres, 'language': get('LanguageISO')}


def _kind_from(genres):
    low = {g.lower() for g in genres}
    for k in ('manhwa', 'manhua', 'manga', 'comic'):
        if k in low:
            return k
    return 'other'


def seed(folder):
    """Metadata found in the folder's files, without any reading settings."""
    name = os.path.basename(folder.rstrip('/'))
    meta = {'title': name}
    top = os.path.join(folder, 'ComicInfo.xml')
    legacy = next((os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith('.json') and f != INFO_FILE), None)
    archives = sorted(f for f in os.listdir(folder) if f.lower().endswith('.cbz'))
    try:
        if os.path.exists(top):
            meta.update({k: v for k, v in _comicinfo(ET.parse(top).getroot()).items() if v})
        elif legacy:
            with open(legacy, encoding='utf-8') as f:
                d = json.load(f)
            meta.update({k: d[k] for k in ('title', 'author', 'artist', 'description') if d.get(k)})
            if d.get('genre'):
                meta['genres'] = d['genre']
        elif archives:
            with zipfile.ZipFile(os.path.join(folder, archives[0])) as z:
                if 'ComicInfo.xml' in z.namelist():
                    meta.update({k: v for k, v in _comicinfo(ET.fromstring(z.read('ComicInfo.xml'))).items() if v})
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as e:
        print(f'metadatos ilegibles en {folder}: {e}')
    meta.setdefault('genres', [])
    meta['kind'] = _kind_from(meta['genres'])
    return meta


# ---- read / write ----------------------------------------------------------
def normalize(d, folder):
    title = d.get('title') or os.path.basename(folder)
    out = {
        'schema': SCHEMA,
        'id': d.get('id') if store.valid(d.get('id', '')) else slug(title),
        'title': title,
        'author': d.get('author', ''),
        'artist': d.get('artist', ''),
        'description': d.get('description', ''),
        'genres': list(d.get('genres', [])),
        'status': d.get('status') if d.get('status') in STATUSES else 'unknown',
        'kind': d.get('kind') if d.get('kind') in KINDS else 'other',
        'language': d.get('language', ''),
        'source': (lambda s: s if s in SOURCES else 'server')(SOURCE_ALIASES.get(d.get('source'), d.get('source'))),
        'reading': {k: v for k, v in clean_reading(d.get('reading', {}), False).items()},
    }
    if isinstance(d.get('cover'), dict) and store.valid(str(d['cover'].get('chapter', ''))):
        out['cover'] = {'chapter': d['cover']['chapter'], 'page': max(1, int(d['cover'].get('page', 1)))}
    return out


def _can_write(folder):
    """True si se puede escribir en la carpeta de la serie (info.json)."""
    try:
        test = os.path.join(folder, '.lecto-write-test')
        fd = os.open(test, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        os.close(fd)
        os.unlink(test)
        return True
    except OSError:
        return False


def load(folder):
    """info.json of a series folder.

    Lee de <folder>/info.json si existe. Si no, intenta el overlay
    (store/info/<id>.json) para bibliotecas de solo lectura. Si no hay en
    ninguno, crea el info a partir de los metadatos existentes (seed) y lo
    escribe donde pueda: la carpeta si se puede escribir, el overlay si no.
    """
    path = os.path.join(folder, INFO_FILE)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return normalize(json.load(f), folder)
    # no hay info.json en la carpeta: probar el overlay (biblioteca :ro)
    # el id del overlay se deriva del seed provisional (necesitamos un id estable)
    seed_info = normalize(seed(folder), folder)
    overlay = _overlay_path(seed_info['id'])
    if os.path.exists(overlay):
        with open(overlay, encoding='utf-8') as f:
            return normalize(json.load(f), folder)
    # no hay en ningun lado: crear y escribir donde se pueda
    if _can_write(folder):
        write_json(path, seed_info)
        print(f'creado {path}')
    else:
        os.makedirs(OVERLAY_DIR, exist_ok=True)
        write_json(overlay, seed_info)
        print(f'creado (overlay) {overlay}')
    return seed_info


def save(folder, info):
    """Escribe info.json en la carpeta si se puede; si no, en el overlay."""
    if _can_write(folder):
        write_json(os.path.join(folder, INFO_FILE), info)
    else:
        os.makedirs(OVERLAY_DIR, exist_ok=True)
        write_json(_overlay_path(info['id']), info)


def patch_reading(folder, patch):
    info = load(folder)
    for k, v in clean_reading(patch, True).items():
        if v is None:
            info['reading'].pop(k, None)
        else:
            info['reading'][k] = v
    save(folder, info)
    return info
