"""/api/favs: series, pages and crops the reader kept."""
import io
import unittest

from PIL import Image

from tests.harness import ServerTest, http, http_json


class Favs(ServerTest):
    def test_serie_pagina_y_duplicados(self):
        code, s = http_json(self.base, 'POST', '/api/favs', {'kind': 'series', 'series': 'sintetica-uno'})
        self.assertEqual(code, 201)
        self.assertEqual(s['kind'], 'series')
        code, again = http_json(self.base, 'POST', '/api/favs', {'kind': 'series', 'series': 'sintetica-uno'})
        self.assertEqual((code, again['id']), (200, s['id']))  # kept once
        code, p = http_json(self.base, 'POST', '/api/favs', {'kind': 'page', 'series': 'sintetica-uno', 'chapter': 'c1', 'page': 2})
        self.assertEqual(code, 201)
        self.assertEqual((p['chapter'], p['page']), ('c1', 2))
        code, lst = http_json(self.base, 'GET', '/api/favs')
        self.assertEqual([f['id'] for f in lst], [p['id'], s['id']])  # newest first
        code, _ = http_json(self.base, 'DELETE', f"/api/favs/{p['id']}")
        self.assertEqual(code, 200)
        code, lst = http_json(self.base, 'GET', '/api/favs')
        self.assertEqual([f['id'] for f in lst], [s['id']])
        http_json(self.base, 'DELETE', f"/api/favs/{s['id']}")

    def test_rechaza_lo_que_no_existe(self):
        for body in ({'kind': 'nope', 'series': 'sintetica-uno'},
                     {'kind': 'series', 'series': 'no-existe'},
                     {'kind': 'page', 'series': 'sintetica-uno', 'chapter': 'c1', 'page': 999},
                     {'kind': 'crop', 'series': 'sintetica-uno', 'chapter': 'c1', 'page': 1, 'rect': [0.1, 0.1, 0.01, 0.5]},
                     {'kind': 'crop', 'series': 'sintetica-uno', 'chapter': 'c1', 'page': 1, 'rect': 'x'}):
            code, _ = http_json(self.base, 'POST', '/api/favs', body)
            self.assertEqual(code, 400, body)
        code, _ = http_json(self.base, 'DELETE', '/api/favs/000000000000')
        self.assertEqual(code, 404)

    def test_recorte_imagen_y_png(self):
        code, f = http_json(self.base, 'POST', '/api/favs', {'kind': 'crop', 'series': 'sintetica-uno', 'chapter': 'c1', 'page': 1, 'rect': [0.25, 0.5, 0.5, 0.5]})
        self.assertEqual(code, 201)
        self.assertEqual(f['rect'], [0.25, 0.5, 0.5, 0.5])
        _, _, jpg = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg')
        W, H = Image.open(io.BytesIO(jpg)).size
        code, hdrs, body = http(self.base, 'GET', f"/api/favs/{f['id']}.png")
        self.assertEqual(code, 200)
        self.assertIn('-panel.png', hdrs['Content-Disposition'])
        self.assertEqual(Image.open(io.BytesIO(body)).size, (round(0.75 * W) - round(0.25 * W), H - round(0.5 * H)))
        code, hdrs, body = http(self.base, 'GET', f"/api/favs/{f['id']}.webp")
        self.assertEqual((code, hdrs['Content-Type']), (200, 'image/webp'))
        self.assertEqual(Image.open(io.BytesIO(body)).format, 'WEBP')
        http_json(self.base, 'DELETE', f"/api/favs/{f['id']}")
        code, _, _ = http(self.base, 'GET', f"/api/favs/{f['id']}.webp")
        self.assertEqual(code, 404)


class FavsToken(ServerTest):
    token = 'clave-favs'

    def test_exige_clave(self):
        code, _ = http_json(self.base, 'GET', '/api/favs')
        self.assertEqual(code, 401)
        code, _ = http_json(self.base, 'POST', '/api/favs', {'kind': 'series', 'series': 'sintetica-uno'})
        self.assertEqual(code, 401)


if __name__ == '__main__':
    unittest.main()
