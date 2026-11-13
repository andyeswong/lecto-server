"""GET /api/pages/<s>/<c>/<n>.png: the page converted to PNG and sent as a download."""
import io
import unittest

from PIL import Image

from tests.harness import ServerTest, http


class PagePng(ServerTest):
    def test_png_es_descarga_con_el_mismo_tamano(self):
        code, hdrs, body = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.png')
        self.assertEqual(code, 200)
        self.assertEqual(hdrs['Content-Type'], 'image/png')
        self.assertIn('attachment; filename="sintetica-uno-c1-p001.png"', hdrs['Content-Disposition'])
        _, _, jpg = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg')
        with Image.open(io.BytesIO(body)) as png, Image.open(io.BytesIO(jpg)) as src:
            self.assertEqual(png.format, 'PNG')
            self.assertEqual(png.size, src.size)

    def test_png_de_pagina_inexistente(self):
        code, _, _ = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/999.png')
        self.assertEqual(code, 404)


class PagePngToken(ServerTest):
    token = 'clave-png'

    def test_png_exige_clave(self):
        code, _, _ = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.png')
        self.assertEqual(code, 401)
        code, _, _ = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.png', token=self.token)
        self.assertEqual(code, 200)


if __name__ == '__main__':
    unittest.main()
