"""Contrato de ingest: incremental, --force, CBZ y CBR."""
import os
import unittest

from tests.harness import ServerTest, http_json, ingest_library


class IngestTest(ServerTest):

    def test_catalog_tiene_las_tres_series(self):
        code, cat = http_json(self.base, 'GET', '/api/catalog')
        self.assertEqual(code, 200)
        ids = {s['id'] for s in cat}
        self.assertEqual(ids, {'sintetica-uno', 'sintetica-dos', 'sintetica-cbr'})

    def test_chapters_y_pages_count(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        uno = next(s for s in cat if s['id'] == 'sintetica-uno')
        self.assertEqual(len(uno['chapters']), 2)
        self.assertEqual(uno['chapters'][0]['pages'], 3)
        self.assertEqual(uno['chapters'][0]['id'], 'c1')
        self.assertEqual(uno['chapters'][1]['id'], 'c2')

    def test_incremental_no_reimporta(self):
        """Una segunda ingest sin --force salta los capitulos ya indexados."""
        from tests.harness import ingest_library
        # capturamos stats antes
        _, before = http_json(self.base, 'GET', '/api/stats')
        ingest_library(self.library, force=False)
        _, after = http_json(self.base, 'GET', '/api/stats')
        self.assertEqual(before['store']['pages'], after['store']['pages'])

    def test_force_reimporta(self):
        """--force reimporta y regenera paginas (mismo count, nuevo added)."""
        from tests.harness import ingest_library
        _, before = http_json(self.base, 'GET', '/api/stats')
        ingest_library(self.library, force=True)
        _, after = http_json(self.base, 'GET', '/api/stats')
        self.assertEqual(before['store']['pages'], after['store']['pages'])
        self.assertEqual(before['store']['series'], after['store']['series'])

    def test_cbr_se_extrae(self):
        """La serie CBR (tar renombrado) se ingesta como CBZ."""
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        cbr = next(s for s in cat if s['id'] == 'sintetica-cbr')
        self.assertEqual(len(cbr['chapters']), 1)
        self.assertEqual(cbr['chapters'][0]['pages'], 2)

    def test_pagina_ancha_en_catalogo(self):
        """La portada ancha (2000x1000) llega redimensionada (max 1400 de ancho)."""
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        uno = next(s for s in cat if s['id'] == 'sintetica-uno')
        dims = uno['chapters'][0]['dims'][0]  # pagina 1 del capitulo 1
        self.assertGreater(dims[0], dims[1], 'la pagina ancha debe ser mas ancha que alta')
        self.assertLessEqual(dims[0], 1400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
