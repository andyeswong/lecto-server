"""Thumbnail engine.

- Fixed sizes only (a whitelist), so a client cannot make the server render arbitrary widths.
- Disk cache is the source of truth: a thumb exists or it does not. Writes go to a temp
  file and are renamed into place, so a reader never sees a half-written WebP.
- On-demand: `ensure()` renders on a cache miss; concurrent requests for the same thumb
  wait on one lock instead of rendering it twice.
- Warm-up: `Warmer` renders every missing thumb in a thread pool (Pillow releases the GIL
  while decoding and resizing), used after ingest and at server start.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import store

# name -> target width in px. s: filmstrip / chapter rows, m: scrubber preview, l: covers.
SIZES = {'s': 120, 'm': 280, 'l': 560}
QUALITY = {'s': 70, 'm': 76, 'l': 80}

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def thumb_path(size, sid, cid, n):
    return os.path.join(store.THUMBS, size, sid, cid, f'{int(n):03d}.webp')


def render(src, dst, size):
    w = SIZES[size]
    with Image.open(src) as im:
        im.draft('RGB', (w * 2, w * 6))  # JPEG: decode at a reduced scale, much faster
        im = im.convert('RGB')
        if im.width > w:
            im = im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = f'{dst}.{threading.get_ident()}.tmp'
        im.save(tmp, 'WEBP', quality=QUALITY[size], method=4)
    os.replace(tmp, dst)


def ensure(size, sid, cid, n):
    """Path to the thumb, rendering it if needed. None if the page does not exist."""
    if size not in SIZES or not store.valid(sid, cid):
        return None
    dst = thumb_path(size, sid, cid, n)
    if os.path.exists(dst):
        return dst
    src = store.page_path(sid, cid, n)
    if not os.path.exists(src):
        return None
    with _guard:
        lock = _locks.setdefault(dst, threading.Lock())
    with lock:
        if not os.path.exists(dst):
            render(src, dst, size)
    with _guard:
        _locks.pop(dst, None)
    return dst


class Warmer:
    def __init__(self, workers=None):
        self.pool = ThreadPoolExecutor(max_workers=workers or max(2, (os.cpu_count() or 4) // 2), thread_name_prefix='thumb')
        self.lock = threading.Lock()
        self.queued = self.done = self.failed = 0

    def _one(self, key):
        try:
            ensure(*key)
            with self.lock:
                self.done += 1
        except Exception as e:  # a broken page must not stop the rest
            with self.lock:
                self.failed += 1
            print('thumb failed', key, e, flush=True)

    def warm_missing(self, conn, sizes=tuple(SIZES)):
        n = 0
        for row in store.iter_pages(conn):
            for size in sizes:
                key = (size, row['series_id'], row['chapter_id'], row['n'])
                if not os.path.exists(thumb_path(*key)):
                    self.pool.submit(self._one, key)
                    n += 1
        with self.lock:
            self.queued += n
        return n

    def wait(self):
        self.pool.shutdown(wait=True)

    def status(self):
        with self.lock:
            return {'queued': self.queued, 'done': self.done, 'failed': self.failed, 'pending': self.queued - self.done - self.failed}


def disk_usage():
    out = {}
    for size in SIZES:
        files = b = 0
        for d, _, fs in os.walk(os.path.join(store.THUMBS, size)):
            for f in fs:
                if f.endswith('.webp'):
                    files += 1
                    b += os.path.getsize(os.path.join(d, f))
        out[size] = {'width': SIZES[size], 'files': files, 'bytes': b}
    return out
