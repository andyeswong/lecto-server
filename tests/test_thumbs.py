"""Contrato de thumbs: 3 tamanos, invalido=400, concurrente sin duplicar."""
import os
import shutil
import threading
import unittest

from tests.harness import ServerTest, http


class ThumbsTest(ServerTest):

    def test_tres_tamanos(self):
        for size in ('s', 'm', 'l'):
            code, hdrs, body = http(self.base, 'GET', f'/api/thumbs/{size}/sintetica-uno/c1/1.webp')
            self.assertEqual(code, 200, f'size={size}')
            self.assertTrue(hdrs.get('Content-Type', '').startswith('image/webp'))
            self.assertGreater(len(body), 50)

    def test_tamano_invalido_400(self):
        code, _, _ = http(self.base, 'GET', '/api/thumbs/x/sintetica-uno/c1/1.webp')
        self.assertEqual(code, 400)

    def test_pagina_inexistente_404(self):
        code, _, _ = http(self.base, 'GET', '/api/thumbs/s/sintetica-uno/c1/999.webp')
        self.assertEqual(code, 404)

    def test_concurrente_mismo_thumb_no_duplica(self):
        """N hilos piden el mismo thumb que falta: todos 200, el archivo existe uno."""
        # borrar el cache de un thumb para forzar render
        import store, thumbs
        dst = thumbs.thumb_path('l', 'sintetica-uno', 'c2', 1)
        if os.path.exists(dst):
            os.remove(dst)
        results = []
        def fetch():
            code, _, _ = http(self.base, 'GET', '/api/thumbs/l/sintetica-uno/c2/1.webp')
            results.append(code)
        threads = [threading.Thread(target=fetch) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, [200] * 8)
        self.assertTrue(os.path.exists(dst), 'el thumb debe existir tras las peticiones')

    def test_warm_endpoint(self):
        code, _, body = http(self.base, 'POST', '/api/thumbs/warm')
        self.assertEqual(code, 200)
        self.assertGreater(len(body), 2)

    def test_cache_control_inmutable(self):
        code, hdrs, _ = http(self.base, 'GET', '/api/thumbs/s/sintetica-uno/c1/1.webp')
        self.assertEqual(code, 200)
        self.assertIn('immutable', hdrs.get('Cache-Control', ''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
