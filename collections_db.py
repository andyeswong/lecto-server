"""Collections: user-made groups of series, across libraries (device and server).

Unlike the catalog, this is user data, not derived from files: it lives only in store.db,
so it is the same on every device that talks to this server.

    collections(id, name, position, created)
    collection_series(collection_id, series_id, position, added)

A series can be in any number of collections. Order inside a collection is the order the
client sends; collections are ordered by `position` (creation order unless moved).
"""
import secrets
import time

SCHEMA = """
create table if not exists collections(
  id text primary key, name text not null, position integer not null, created real);
create table if not exists collection_series(
  collection_id text not null, series_id text not null, position integer not null, added real,
  primary key(collection_id, series_id));
"""
NAME_MAX = 60


class Invalid(ValueError):
    pass


def init(c):
    c.executescript(SCHEMA)


def _name(c, name, exclude_id=None):
    if not isinstance(name, str) or not name.strip():
        raise Invalid('name is required')
    name = ' '.join(name.split())[:NAME_MAX]
    clash = c.execute('select id from collections where lower(name)=lower(?) and id is not ?', (name, exclude_id)).fetchone()
    if clash:
        raise Invalid(f'there is already a collection called "{name}"')
    return name


def _series(c, ids):
    if not isinstance(ids, list):
        raise Invalid('series must be a list of series ids')
    known = {r[0] for r in c.execute('select id from series')}
    out = []
    for i in ids:
        if i in known and i not in out:  # unknown ids are dropped, duplicates collapsed
            out.append(i)
    return out


def get(c, cid):
    row = c.execute('select id, name from collections where id=?', (cid,)).fetchone()
    if not row:
        return None
    series = [r[0] for r in c.execute('select series_id from collection_series where collection_id=? order by position', (cid,))]
    return {'id': row[0], 'name': row[1], 'series': series}


def list_all(c):
    return [get(c, r[0]) for r in c.execute('select id from collections order by position, created')]


def _set_series(c, cid, ids):
    c.execute('delete from collection_series where collection_id=?', (cid,))
    now = time.time()
    c.executemany('insert into collection_series values (?,?,?,?)', [(cid, s, i, now) for i, s in enumerate(ids)])


def create(c, body):
    import store
    with store._write_lock, c:
        name = _name(c, body.get('name'))
        ids = _series(c, body.get('series', []))
        cid = secrets.token_hex(4)
        pos = c.execute('select coalesce(max(position), -1) + 1 from collections').fetchone()[0]
        c.execute('insert into collections values (?,?,?,?)', (cid, name, pos, time.time()))
        _set_series(c, cid, ids)
    return get(c, cid)


def update(c, cid, body):
    import store
    if not get(c, cid):
        return None
    with store._write_lock, c:
        if 'name' in body:
            c.execute('update collections set name=? where id=?', (_name(c, body['name'], cid), cid))
        if 'series' in body:
            _set_series(c, cid, _series(c, body['series']))
        if 'position' in body:
            ids = [r[0] for r in c.execute('select id from collections where id != ? order by position, created', (cid,))]
            ids.insert(max(0, min(len(ids), int(body['position']))), cid)
            c.executemany('update collections set position=? where id=?', [(i, x) for i, x in enumerate(ids)])
    return get(c, cid)


def delete(c, cid):
    import store
    with store._write_lock, c:
        n = c.execute('delete from collections where id=?', (cid,)).rowcount
        c.execute('delete from collection_series where collection_id=?', (cid,))
    return n > 0
