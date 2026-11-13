"""/api/vault: series kept out of the catalog behind a PIN."""
import unittest

import vault_db
from tests.harness import ServerTest, http_json


def ids(base):
    return {s['id'] for s in http_json(base, 'GET', '/api/catalog')[1]}


class Vault(ServerTest):
    def tearDown(self):
        http_json(self.base, 'POST', '/api/vault/reset', {})
        vault_db._fails.update(n=0, until=0.0)

    def test_flujo_completo(self):
        self.assertEqual(http_json(self.base, 'GET', '/api/vault'), (200, {'configured': False}))
        code, _ = http_json(self.base, 'POST', '/api/vault/add', {'series': ['sintetica-uno']})
        self.assertEqual(code, 400)                                   # no PIN yet
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/create', {'pin': '12'})[0], 400)
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/create', {'pin': '4321'})[0], 201)
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/create', {'pin': '9999'})[0], 400)  # only once
        self.assertIn('sintetica-uno', ids(self.base))
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/add', {'series': ['sintetica-uno', 'no-existe']})[0], 200)
        self.assertNotIn('sintetica-uno', ids(self.base))             # out of the catalog
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/open', {'pin': '0000'})[0], 403)
        code, body = http_json(self.base, 'POST', '/api/vault/open', {'pin': '4321'})
        self.assertEqual(code, 200)
        self.assertEqual([s['id'] for s in body['series']], ['sintetica-uno'])
        self.assertTrue(body['series'][0]['chapters'])                # full entries, readable
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/remove', {'pin': '1111', 'series': ['sintetica-uno']})[0], 403)
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/remove', {'pin': '4321', 'series': ['sintetica-uno']})[0], 200)
        self.assertIn('sintetica-uno', ids(self.base))

    def test_intentos_limitados(self):
        http_json(self.base, 'POST', '/api/vault/create', {'pin': '4321'})
        codes = [http_json(self.base, 'POST', '/api/vault/open', {'pin': '0000'})[0] for _ in range(6)]
        self.assertEqual(codes[:5], [403] * 5)
        self.assertEqual(codes[5], 429)
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/open', {'pin': '4321'})[0], 429)  # even the right one waits

    def test_reset_devuelve_las_series(self):
        http_json(self.base, 'POST', '/api/vault/create', {'pin': '4321'})
        http_json(self.base, 'POST', '/api/vault/add', {'series': ['sintetica-dos']})
        self.assertNotIn('sintetica-dos', ids(self.base))
        http_json(self.base, 'POST', '/api/vault/reset', {})
        self.assertIn('sintetica-dos', ids(self.base))
        self.assertEqual(http_json(self.base, 'GET', '/api/vault'), (200, {'configured': False}))


class VaultToken(ServerTest):
    token = 'clave-vault'

    def test_exige_clave(self):
        self.assertEqual(http_json(self.base, 'GET', '/api/vault')[0], 401)
        self.assertEqual(http_json(self.base, 'POST', '/api/vault/create', {'pin': '4321'})[0], 401)


if __name__ == '__main__':
    unittest.main()
