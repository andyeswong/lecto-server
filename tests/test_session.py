"""Contrato de sesion por cookie: login, logout, cookie aceptada en /api/*."""
import unittest
from http.cookies import SimpleCookie

from tests.harness import ServerTest, http, http_json


class SessionTest(ServerTest):
    token = 'secreto-sesion'

    def _extract_cookie(self, hdrs):
        raw = hdrs.get('Set-Cookie', '')
        if not raw:
            return None
        c = SimpleCookie()
        c.load(raw)
        return c

    def test_login_token_valido_setea_cookie(self):
        code, hdrs, body = http(self.base, 'POST', '/api/session', body={'token': self.token})
        self.assertEqual(code, 200)
        cookie = self._extract_cookie(hdrs)
        self.assertIsNotNone(cookie)
        self.assertIn('lecto_session', cookie)
        self.assertIn('HttpOnly', raw := hdrs.get('Set-Cookie', ''))
        self.assertIn('SameSite=Strict', raw)

    def test_login_token_malo_401(self):
        code, _, _ = http(self.base, 'POST', '/api/session', body={'token': 'malo'})
        self.assertEqual(code, 401)

    def test_login_sin_body_401(self):
        """Sin body (o body sin token), el login falla con 401 (token invalido)."""
        code, _, _ = http(self.base, 'POST', '/api/session')
        self.assertEqual(code, 401)

    def test_cookie_accede_api(self):
        """Tras login, la cookie permite acceder a /api/* sin header."""
        code, hdrs, _ = http(self.base, 'POST', '/api/session', body={'token': self.token})
        cookie = self._extract_cookie(hdrs)
        cookie_str = f'lecto_session={cookie["lecto_session"].value}'
        code, cat = http_json(self.base, 'GET', '/api/catalog', headers={'Cookie': cookie_str})
        self.assertEqual(code, 200)
        self.assertIsInstance(cat, list)

    def test_cookie_mala_401(self):
        code, _, _ = http(self.base, 'GET', '/api/catalog',
                           headers={'Cookie': 'lecto_session=falso'})
        self.assertEqual(code, 401)

    def test_bearer_sigue_funcionando(self):
        """El header Authorization sigue siendo valido (cliente nativo)."""
        code, cat = http_json(self.base, 'GET', '/api/catalog', token=self.token)
        self.assertEqual(code, 200)

    def test_logout_borra_cookie(self):
        code, hdrs, _ = http(self.base, 'DELETE', '/api/session')
        self.assertEqual(code, 200)
        raw = hdrs.get('Set-Cookie', '')
        self.assertIn('Max-Age=0', raw)

    def test_session_no_requiere_auth_previa(self):
        """POST /api/session no requiere token previo (es el login)."""
        code, _, _ = http(self.base, 'POST', '/api/session', body={'token': self.token})
        self.assertEqual(code, 200)

    def test_cookie_funciona_para_imagenes(self):
        """La cookie permite acceder a /api/pages/ (el caso de uso de <img src>)."""
        code, hdrs, _ = http(self.base, 'POST', '/api/session', body={'token': self.token})
        cookie = self._extract_cookie(hdrs)
        cookie_str = f'lecto_session={cookie["lecto_session"].value}'
        code, _, body = http(self.base, 'GET', '/api/pages/sintetica-uno/c1/1.jpg',
                             headers={'Cookie': cookie_str})
        self.assertEqual(code, 200)
        self.assertGreater(len(body), 100)


class SessionDisabledTest(ServerTest):
    """Sin LECTO_TOKEN, el endpoint de sesion devuelve 400."""

    def test_login_sin_token_configurado_400(self):
        code, _, _ = http(self.base, 'POST', '/api/session', body={'token': 'algo'})
        self.assertEqual(code, 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
