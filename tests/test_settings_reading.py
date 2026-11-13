"""Contrato de settings y reading: defaults globales, overrides por serie, null=reset."""
import unittest

from tests.harness import ServerTest, http_json


class SettingsReadingTest(ServerTest):

    def test_get_settings_tiene_defaults_y_opciones(self):
        code, s = http_json(self.base, 'GET', '/api/settings')
        self.assertEqual(code, 200)
        self.assertIn('reading', s)
        self.assertIn('options', s)
        self.assertEqual(s['reading']['layout'], 'auto')  # factory default
        self.assertEqual(s['options']['layout'], ['auto', 'single', 'double', 'scroll'])

    def test_put_global_reading_cambia_default(self):
        code, s = http_json(self.base, 'PUT', '/api/settings/reading', {'layout': 'double'})
        self.assertEqual(code, 200)
        self.assertEqual(s['reading']['layout'], 'double')
        # persiste
        code, s = http_json(self.base, 'GET', '/api/settings')
        self.assertEqual(s['reading']['layout'], 'double')

    def test_put_global_reading_null_resetea_factory(self):
        http_json(self.base, 'PUT', '/api/settings/reading', {'layout': 'single'})
        code, s = http_json(self.base, 'PUT', '/api/settings/reading', {'layout': None})
        self.assertEqual(code, 200)
        self.assertEqual(s['reading']['layout'], 'auto')

    def test_put_global_reading_valor_invalido_400(self):
        code, s = http_json(self.base, 'PUT', '/api/settings/reading', {'layout': 'weird'})
        self.assertEqual(code, 400)
        code, s = http_json(self.base, 'PUT', '/api/settings/reading', {'noexiste': 1})
        self.assertEqual(code, 400)

    def test_series_reading_override(self):
        code, s = http_json(self.base, 'PUT', '/api/series/sintetica-uno/reading', {'direction': 'rtl'})
        self.assertEqual(code, 200)
        self.assertEqual(s['reading']['direction'], 'rtl')
        # el override aparece en el catalog
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        uno = next(x for x in cat if x['id'] == 'sintetica-uno')
        self.assertEqual(uno['reading']['direction'], 'rtl')

    def test_series_reading_null_quita_override(self):
        http_json(self.base, 'PUT', '/api/series/sintetica-uno/reading', {'direction': 'rtl'})
        code, s = http_json(self.base, 'PUT', '/api/series/sintetica-uno/reading', {'direction': None})
        self.assertEqual(code, 200)
        self.assertNotIn('direction', s['reading'])

    def test_series_reading_serie_inexistente_404(self):
        code, _ = http_json(self.base, 'PUT', '/api/series/no-existe/reading', {'direction': 'rtl'})
        self.assertEqual(code, 404)

    def test_info_json_se_escribe(self):
        """El override se persiste en el info.json de la carpeta de la serie."""
        http_json(self.base, 'PUT', '/api/series/sintetica-dos/reading', {'fit': 'width'})
        import json, os
        path = os.path.join(self.library, 'sintetica-dos', 'info.json')
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data['reading']['fit'], 'width')


if __name__ == '__main__':
    unittest.main(verbosity=2)
