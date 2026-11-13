"""Favs: what the reader kept. A whole series, one page, or a crop of a page (a panel).

User data, like collections: it lives only in store.db and is the same on every device
that talks to this server.

    favs(id, kind, series_id, chapter_id, n, rect, created)

kind   'series' | 'page' | 'crop'
rect   crops only: [x, y, w, h] as fractions of the page (0..1), JSON text

A series or a page can be kept once (adding it again returns the one already kept);
a page can have any number of crops.
"""
import json
import secrets
import time

SCHEMA = """
create table if not exists favs(
  id text primary key, kind text not null, series_id text not null,
  chapter_id text, n integer, rect text, created real not null);
create index if not exists favs_by_target on favs(kind, series_id, chapter_id, n);
"""
KINDS = ('series', 'page', 'crop')
MIN_SIDE = 0.03  # a crop smaller than 3% of the page on a side is a mis-tap, not a panel


class Invalid(ValueError):
    pass


def init(c):
    c.executescript(SCHEMA)


def _row(r):
    out = {'id': r['id'], 'kind': r['kind'], 'series': r['series_id'], 'created': r['created']}
    if r['kind'] != 'series':
        out['chapter'] = r['chapter_id']
        out['page'] = r['n']
    if r['kind'] == 'crop':
        out['rect'] = json.loads(r['rect'])
    return out


def list_all(c):
    return [_row(r) for r in c.execute('select * from favs order by created desc, rowid desc')]


def get(c, fid):
    r = c.execute('select * from favs where id=?', (fid,)).fetchone()
    return _row(r) if r else None


def _rect(v):
    if not (isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) for x in v)):
        raise Invalid('rect must be [x, y, w, h] as fractions of the page')
    x, y, w, h = (float(t) for t in v)
    x, y = max(0.0, x), max(0.0, y)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    if w < MIN_SIDE or h < MIN_SIDE:
        raise Invalid('rect is too small')
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def create(c, body):
    """Returns (fav, created). Adding a series or page already kept returns it unchanged."""
    kind = body.get('kind')
    if kind not in KINDS:
        raise Invalid(f'kind must be one of {list(KINDS)}')
    sid = body.get('series')
    if not c.execute('select 1 from series where id=?', (sid,)).fetchone():
        raise Invalid('no such series')
    cid = n = rect = None
    if kind != 'series':
        cid, n = body.get('chapter'), body.get('page')
        if not isinstance(n, int) or not c.execute('select 1 from pages where series_id=? and chapter_id=? and n=?', (sid, cid, n)).fetchone():
            raise Invalid('no such page')
    if kind == 'crop':
        rect = json.dumps(_rect(body.get('rect')))
    else:
        r = c.execute('select id from favs where kind=? and series_id=? and chapter_id is ? and n is ?', (kind, sid, cid, n)).fetchone()
        if r:
            return get(c, r['id']), False
    fid = secrets.token_hex(6)
    import store
    with store._write_lock, c:
        c.execute('insert into favs values (?,?,?,?,?,?,?)', (fid, kind, sid, cid, n, rect, time.time()))
    return get(c, fid), True


def delete(c, fid):
    import store
    with store._write_lock, c:
        return c.execute('delete from favs where id=?', (fid,)).rowcount > 0
