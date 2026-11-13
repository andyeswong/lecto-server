"""GET /api/info: public handshake, with and without a token configured."""
import unittest

from tests.harness import ServerTest, http_json


class InfoOpen(ServerTest):
    def test_info_sin_token(self):
        code, body = http_json(self.base, 'GET', '/api/info')
        self.assertEqual(code, 200)
        self.assertEqual(body['server'], 'lecto')
        self.assertFalse(body['auth'])
        self.assertTrue(body['session'])


class InfoToken(ServerTest):
    token = 'clave-info'

    def test_info_es_publico_y_avisa_auth(self):
        code, body = http_json(self.base, 'GET', '/api/info')
        self.assertEqual(code, 200)
        self.assertTrue(body['auth'])
        self.assertFalse(body['session'])
        code, _ = http_json(self.base, 'GET', '/api/catalog')
        self.assertEqual(code, 401)

    def test_info_session_con_bearer(self):
        code, body = http_json(self.base, 'GET', '/api/info', token=self.token)
        self.assertEqual(code, 200)
        self.assertTrue(body['session'])


if __name__ == '__main__':
    unittest.main()
