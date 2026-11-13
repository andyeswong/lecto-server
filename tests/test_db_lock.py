"""Reproduce el 'database is locked' del servidor Lecto.

El patron que falla (visto en journalctl --user -u lecto, 2026-11-09 08:16-08:17):

  do_PUT /api/series/<id>/reading:
    c = store.connect()
    folder = store.series_folder(c, sid)   # SELECT → inicia transaccion diferida (SHARED)
    info = infofile.patch_reading(folder, body)  # I/O LENTO en HDD USB
    store.put_series(c, folder, info)       # INSERT → promueve SHARED→RESERVED → SQLITE_BUSY

Con 16 workers, dos transacciones como esta compiten por el RESERVED lock. En un
HDD USB (btrfs, nodatacow), el fsync del COMMIT del ganador tarda, y el perdedor
excede el timeout (30s) → "database is locked".

Tambien afecta a favs_db.create (INSERT en with c:) cuando compite con otra
escritura simultanea.

Causa raiz: `with c:` usa BEGIN diferido. Dos transacciones pueden ambas leer
(SHARED), y cuando ambas intentan escribir, una obtiene RESERVED y la otra
SQLITE_BUSY. El I/O lento entre el SELECT y el INSERT alarga la ventana de
contention.

Fix: un write lock a nivel de aplicacion (threading.Lock) que serializa las
escrituras. Las lecturas (WAL) no se ven afectadas. Ver store._write_lock.
"""
import os
import sqlite3
import tempfile
import threading
import time
import unittest


class DatabaseLockReproTest(unittest.TestCase):
    """Reproduce el 'database is locked' del patron SELECT → I/O → INSERT con
    BEGIN diferido, y verifica que el write lock de aplicacion lo resuelve."""

    def setUp(self):
        self.store = tempfile.mkdtemp(prefix='lecto-lock-')
        self.db = os.path.join(self.store, 'store.db')
        c = sqlite3.connect(self.db, timeout=30)
        c.execute('pragma journal_mode=wal')
        c.execute('pragma synchronous=normal')
        c.execute('create table if not exists series(id text primary key, info text)')
        c.execute('create table if not exists favs(id text primary key, kind text)')
        c.commit()
        c.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.store, ignore_errors=True)

    def _patron_diferido(self, db, timeout, sleep_io, sleep_commit, errors, ready):
        """El patron que falla: SELECT → sleep (I/O lento) → INSERT → sleep (commit lento) → COMMIT."""
        ready.wait()
        try:
            c = sqlite3.connect(db, timeout=timeout)
            c.execute('select id from series limit 1').fetchall()  # SELECT → transaccion diferida
            time.sleep(sleep_io)  # simular I/O lento (patch_reading en HDD USB)
            c.execute('insert into favs values (?, ?)', (str(threading.get_ident()), 'page'))
            time.sleep(sleep_commit)  # simular commit/fsync lento en HDD USB
            c.commit()
            c.close()
        except sqlite3.OperationalError as e:
            errors.append(str(e))

    def test_begin_diferido_causa_locked(self):
        """Con BEGIN diferido + I/O lento, dos threads compiten por RESERVED y
        uno excede el timeout → 'database is locked'."""
        errors = []
        ready = threading.Barrier(2)
        threads = [
            threading.Thread(target=self._patron_diferido,
                              args=(self.db, 0.3, 0.5, 0.5, errors, ready)),
            threading.Thread(target=self._patron_diferido,
                              args=(self.db, 0.3, 0.5, 0.5, errors, ready)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertGreater(len(errors), 0,
                           'BEGIN diferido + I/O lento debe causar database is locked')

    def test_write_lock_serializa_y_no_bloquea(self):
        """Con un write lock de aplicacion, las escrituras se serializan y no
        hay 'database is locked' (las lecturas en WAL no se ven afectadas)."""
        write_lock = threading.Lock()
        errors = []

        def patron_con_lock(db, timeout, sleep_io, sleep_commit, ready):
            ready.wait()
            try:
                c = sqlite3.connect(db, timeout=timeout)
                c.execute('select id from series limit 1').fetchall()
                time.sleep(sleep_io)
                with write_lock:  # serializar escrituras a nivel de aplicacion
                    c.execute('insert into favs values (?, ?)',
                              (str(threading.get_ident()), 'page'))
                    time.sleep(sleep_commit)
                    c.commit()
                c.close()
            except sqlite3.OperationalError as e:
                errors.append(str(e))

        ready = threading.Barrier(2)
        threads = [
            threading.Thread(target=patron_con_lock,
                              args=(self.db, 0.3, 0.5, 0.5, ready)),
            threading.Thread(target=patron_con_lock,
                              args=(self.db, 0.3, 0.5, 0.5, ready)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0,
                         'con write lock, no debe haber database is locked')


if __name__ == '__main__':
    unittest.main(verbosity=2)
