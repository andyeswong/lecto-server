"""Verifica que las escrituras concurrentes no causan 'database is locked' con el write lock."""
import threading
import unittest

from tests.harness import ServerTest, http_json


class ConcurrentWritesTest(ServerTest):
    """16 workers haciendo escrituras simultaneas: crear favs y colecciones.
    Con el write lock de store._write_lock, no hay 'database is locked'."""

    def test_16_workers_crear_favs_concurrentes(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        sid = cat[0]['id']
        cid = cat[0]['chapters'][0]['id']
        errors = []
        codes = []

        def worker():
            try:
                code, _ = http_json(self.base, 'POST', '/api/favs',
                                    body={'kind': 'page', 'series': sid, 'chapter': cid, 'page': 1})
                codes.append(code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f'no debe haber errores: {errors[:3]}')
        # todos 200 o 201 (200 si ya existe, 201 si es nuevo)
        for code in codes:
            self.assertIn(code, (200, 201), f'codigo inesperado: {code}')

    def test_16_workers_crear_colecciones_concurrentes(self):
        errors = []
        codes = []

        def worker(i):
            try:
                code, _ = http_json(self.base, 'POST', '/api/collections',
                                    body={'name': f'conc-{threading.get_ident()}-{i}'})
                codes.append(code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f'no debe haber errores: {errors[:3]}')
        for code in codes:
            self.assertIn(code, (201, 400))

    def test_16_workers_series_reading_concurrentes(self):
        """El patron que fallo en produccion: PUT series/reading (SELECT + I/O + INSERT)."""
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        sids = [s['id'] for s in cat[:4]]
        errors = []
        codes = []

        def worker(sid):
            for _ in range(3):
                try:
                    code, _ = http_json(self.base, 'PUT', f'/api/series/{sid}/reading',
                                        body={'direction': 'rtl'})
                    codes.append(code)
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(sids[i % len(sids)],)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f'no debe haber errores: {errors[:3]}')
        for code in codes:
            self.assertEqual(code, 200, f'PUT series/reading debe ser 200, no {code}')

        # limpiar: resetear los overrides
        for sid in sids:
            http_json(self.base, 'PUT', f'/api/series/{sid}/reading', body={'direction': None})


if __name__ == '__main__':
    unittest.main(verbosity=2)
