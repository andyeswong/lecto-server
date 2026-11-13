"""Contrato de seguridad: path traversal, tope de body, CORS, auth por token opcional."""
import os
import unittest

from tests.harness import ServerTest, http, http_json


class PathTraversalTest(ServerTest):
    """Los regex de ruta solo permiten [a-z0-9_-]; el static revisa realpath."""

    def test_pages_no_traversal(self):
        for p in ('/api/pages/..%2f..%2fetc%2fpasswd/c1/1.jpg',
                  '/api/pages/.../c1/1.jpg'):
            code, _, _ = http(self.base, 'GET', p)
            self.assertNotEqual(code, 200, p)

    def test_static_traversal_403(self):
        code, _, _ = http(self.base, 'GET', '/../../etc/passwd')
        self.assertEqual(code, 403)
        code, _, _ = http(self.base, 'GET', '/%2e%2e/%2e%2e/etc/passwd')
        self.assertIn(code, (403, 404))

    def test_thumb_regex_no_traversal(self):
        code, _, _ = http(self.base, 'GET', '/api/thumbs/s/../../../etc/passwd')
        # no hace match el regex -> cae a static -> 403/404
        self.assertNotEqual(code, 200)


class BodyLimitTest(ServerTest):

    def test_body_tope_16kb_400(self):
        big = {'name': 'x' * 20000}
        code, _ = http_json(self.base, 'POST', '/api/collections', big)
        self.assertEqual(code, 400)

    def test_body_pequeno_ok(self):
        code, col = http_json(self.base, 'POST', '/api/collections', {'name': 'chico'})
        self.assertEqual(code, 201)
        http_json(self.base, 'DELETE', f'/api/collections/{col["id"]}')


class CorsTest(ServerTest):
    cors = 'https://ejemplo.test'

    def test_cors_header_refleja_config(self):
        code, hdrs, _ = http(self.base, 'GET', '/api/catalog')
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), 'https://ejemplo.test')

    def test_options_preflight(self):
        code, hdrs, _ = http(self.base, 'OPTIONS', '/api/collections')
        self.assertEqual(code, 204)
        self.assertIn('GET', hdrs.get('Access-Control-Allow-Methods', ''))


class TokenAuthTest(ServerTest):
    token = 'secreto-de-prueba'

    def test_sin_token_401(self):
        code, _ = http_json(self.base, 'GET', '/api/catalog')
        self.assertEqual(code, 401)

    def test_token_malo_401(self):
        code, _ = http_json(self.base, 'GET', '/api/catalog', token='otra-cosa')
        self.assertEqual(code, 401)

    def test_token_bueno_200(self):
        code, cat = http_json(self.base, 'GET', '/api/catalog', token=self.token)
        self.assertEqual(code, 200)
        self.assertIsInstance(cat, list)

    def test_post_sin_token_401(self):
        code, _ = http_json(self.base, 'POST', '/api/collections', {'name': 'no'})
        self.assertEqual(code, 401)

    def test_post_con_token_201(self):
        code, col = http_json(self.base, 'POST', '/api/collections',
                              {'name': 'con-token'}, token=self.token)
        self.assertEqual(code, 201)
        http_json(self.base, 'DELETE', f'/api/collections/{col["id"]}', token=self.token)

    def test_options_sin_token_204(self):
        """El preflight CORS no requiere token (el navegador no lo envia)."""
        code, _, _ = http(self.base, 'OPTIONS', '/api/catalog')
        self.assertEqual(code, 204)


if __name__ == '__main__':
    unittest.main(verbosity=2)
