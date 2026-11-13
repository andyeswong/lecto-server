"""Contrato de catalog y pages: forma, dimensiones, paginas originales."""
import unittest

from tests.harness import ServerTest, http, http_json


class CatalogPagesTest(ServerTest):

    def setUp(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        self.cat = {s['id']: s for s in cat}

    def test_catalog_ordenado_por_titulo(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        titles = [s['title'].lower() for s in cat]
        self.assertEqual(titles, sorted(titles))

    def test_catalog_campos_minimos(self):
        s = self.cat['sintetica-uno']
        for k in ('id', 'title', 'author', 'genres', 'kind', 'cover', 'chapters', 'reading'):
            self.assertIn(k, s)
        self.assertEqual(s['cover'], {'chapter': 'c1', 'page': 1})

    def test_chapter_dims_coinciden_con_pages(self):
        ch = self.cat['sintetica-uno']['chapters'][0]
        self.assertEqual(len(ch['dims']), ch['pages'])
        # pagina normal (800x1200): alta
        self.assertEqual(ch['dims'][1], [800, 1200])

    def test_pagina_jpeg_200(self):
        code, hdrs, body = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg')
        self.assertEqual(code, 200)
        self.assertTrue(hdrs.get('Content-Type', '').startswith('image/jpeg'))
        self.assertGreater(len(body), 100)

    def test_pagina_inexistente_404(self):
        code, _, _ = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/999.jpg')
        self.assertEqual(code, 404)

    def test_serie_inexistente_404(self):
        code, _, _ = http(self.base, 'GET', '/api/pages/no-existe/c1/1.jpg')
        self.assertEqual(code, 404)

    def test_etag_y_304(self):
        code, hdrs, _ = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg')
        etag = hdrs.get('ETag')
        self.assertIsNotNone(etag)
        code2, hdrs2, body2 = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg',
                                   headers={'If-None-Match': etag})
        self.assertEqual(code2, 304)
        self.assertEqual(len(body2), 0)

    def test_stats_responde(self):
        code, stats = http_json(self.base, 'GET', '/api/stats')
        self.assertEqual(code, 200)
        self.assertEqual(stats['store']['series'], 3)
        self.assertGreater(stats['store']['pages'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
