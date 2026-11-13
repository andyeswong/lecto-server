"""Contrato del overlay de solo lectura: info.json y overrides van al store cuando la carpeta es :ro."""
import json
import os
import stat
import unittest

from tests.harness import ServerTest, http_json


class ReadOnlyOverlayTest(ServerTest):
    """Biblioteca montada de solo lectura: info.json y overrides van al overlay."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # crear una serie en una carpeta de solo lectura
        from tests.fixtures import make_cbz, info_json
        cls.ro_library = os.path.join(cls.store, 'ro-library')
        cls.ro_series = os.path.join(cls.ro_library, 'sintetica-ro')
        os.makedirs(cls.ro_series, exist_ok=True)
        # sin info.json: el seed debe crear el overlay
        make_cbz(os.path.join(cls.ro_series, 'Capitulo 1.cbz'), 2)
        # volver la carpeta de la serie de solo lectura
        os.chmod(cls.ro_series, stat.S_IRUSR | stat.S_IXUSR)
        cls._ro_mode = stat.S_IRUSR | stat.S_IXUSR

    @classmethod
    def tearDownClass(cls):
        # restaurar permisos para poder limpiar
        try:
            os.chmod(cls.ro_series, stat.S_IRWXU)
        except OSError:
            pass
        super().tearDownClass()

    def test_ingest_no_truena_con_carpeta_ro(self):
        from tests.harness import ingest_library
        # la serie ro esta en ro-library, no en self.library; hay que ingerir ro-library
        ingest_library(self.ro_library, force=True)
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        ids = {s['id'] for s in cat}
        self.assertIn('sintetica-ro', ids)

    def test_overlay_se_crea_en_store(self):
        from tests.harness import ingest_library
        ingest_library(self.ro_library, force=True)
        overlay = os.path.join(self.store, 'store', 'info', 'sintetica-ro.json')
        # el overlay dir es <store>/info/; store.ROOT es <store>/store
        import store, info
        overlay = os.path.join(info.OVERLAY_DIR, 'sintetica-ro.json')
        self.assertTrue(os.path.exists(overlay), f'overlay debe existir en {overlay}')

    def test_override_reading_persiste_en_overlay(self):
        from tests.harness import ingest_library
        ingest_library(self.ro_library, force=True)
        code, s = http_json(self.base, 'PUT', '/api/series/sintetica-ro/reading', {'direction': 'rtl'})
        self.assertEqual(code, 200)
        self.assertEqual(s['reading']['direction'], 'rtl')
        # el override NO debe estar en la carpeta (es :ro), sino en el overlay
        import info
        overlay = os.path.join(info.OVERLAY_DIR, 'sintetica-ro.json')
        with open(overlay) as f:
            data = json.load(f)
        self.assertEqual(data['reading']['direction'], 'rtl')
        # la carpeta no debe tener info.json
        self.assertFalse(os.path.exists(os.path.join(self.ro_series, 'info.json')))

    def test_override_aparece_en_catalog(self):
        from tests.harness import ingest_library
        ingest_library(self.ro_library, force=True)
        http_json(self.base, 'PUT', '/api/series/sintetica-ro/reading', {'fit': 'width'})
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        ro = next(s for s in cat if s['id'] == 'sintetica-ro')
        self.assertEqual(ro['reading']['fit'], 'width')

    def test_null_quita_override_en_overlay(self):
        from tests.harness import ingest_library
        ingest_library(self.ro_library, force=True)
        http_json(self.base, 'PUT', '/api/series/sintetica-ro/reading', {'direction': 'rtl'})
        code, s = http_json(self.base, 'PUT', '/api/series/sintetica-ro/reading', {'direction': None})
        self.assertEqual(code, 200)
        self.assertNotIn('direction', s['reading'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
