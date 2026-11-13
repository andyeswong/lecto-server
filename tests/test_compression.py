"""Contrato de compresion gzip: catalog JSON, estaticos de texto, imagenes sin comprimir."""
import gzip
import json
import os
import unittest

from tests.harness import ServerTest, http, http_json


class GzipTest(ServerTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # crear un estatico de texto en el web dir para probar send_file con gzip
        cls.js_path = os.path.join(cls.web, '_expo', 'static', 'js', 'test.js')
        os.makedirs(os.path.dirname(cls.js_path), exist_ok=True)
        cls.js_body = 'console.log("hello");\n' * 200  # > 1 KB
        with open(cls.js_path, 'w') as f:
            f.write(cls.js_body)

    def test_catalog_con_gzip(self):
        """El catalog JSON se sirve con Content-Encoding: gzip cuando el cliente lo acepta."""
        code, hdrs, body = http(self.base, 'GET', '/api/catalog',
                                headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get('Content-Encoding'), 'gzip')
        self.assertIn('Accept-Encoding', hdrs.get('Vary', ''))
        decoded = json.loads(gzip.decompress(body))
        self.assertIsInstance(decoded, list)

    def test_catalog_sin_gzip(self):
        """Sin Accept-Encoding: gzip, el body llega plano."""
        code, hdrs, body = http(self.base, 'GET', '/api/catalog')
        self.assertEqual(code, 200)
        self.assertNotIn('Content-Encoding', hdrs)
        self.assertGreater(len(body), 100)

    def test_estatico_js_con_gzip(self):
        code, hdrs, body = http(self.base, 'GET', '/_expo/static/js/test.js',
                                headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get('Content-Encoding'), 'gzip')
        decoded = gzip.decompress(body).decode()
        self.assertIn('console.log', decoded)

    def test_imagen_no_se_comprime(self):
        """Las paginas JPEG no llevan Content-Encoding aunque el cliente acepte gzip."""
        code, hdrs, body = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg',
                                headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertNotIn('Content-Encoding', hdrs)
        self.assertGreater(len(body), 100)

    def test_thumb_no_se_comprime(self):
        code, hdrs, body = http(self.base, 'GET', '/api/thumbs/s/sintetica-uno/c1/1.webp',
                                headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertNotIn('Content-Encoding', hdrs)

    def test_cuerpo_pequeno_no_se_comprime(self):
        """Un JSON de respuesta menor a GZIP_MIN (1 KB) no se comprime."""
        code, hdrs, body = http(self.base, 'GET', '/api/settings',
                                headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        # /api/settings es pequeno: no debe comprimirse
        self.assertNotIn('Content-Encoding', hdrs)

    def test_api_desconocida_devuelve_json_404(self):
        """Una ruta /api/inexistente devuelve JSON 404, no HTML 200 (SPA fallback)."""
        code, hdrs, body = http(self.base, 'GET', '/api/no-existe')
        self.assertEqual(code, 404)
        self.assertTrue(hdrs.get('Content-Type', '').startswith('application/json'))

    def test_web_ausente_404_claro(self):
        """Si no hay index.html en WEB, la raiz devuelve 404 con mensaje, no 500."""
        import tempfile, shutil
        from tests.harness import start_server
        empty_web = tempfile.mkdtemp()
        try:
            os.environ['LECTO_LOG'] = ''
            httpd, base = start_server(tempfile.mkdtemp(), empty_web)
            code, _, body = http(base, 'GET', '/')
            self.assertEqual(code, 404)
            httpd.shutdown()
            httpd.server_close()
        finally:
            os.environ['LECTO_LOG'] = '1'
            shutil.rmtree(empty_web, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
