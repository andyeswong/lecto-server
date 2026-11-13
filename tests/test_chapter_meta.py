"""Contrato de chapter_meta: formatos comunes, desambiguacion, sin colisiones."""
import os
import unittest

from tests.harness import ServerTest, http_json, ingest_library


class ChapterMetaFormatTest(unittest.TestCase):
    """chapter_meta soporta los formatos de nombre comunes."""

    def test_formatos_sacan_numero_correcto(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from ingest import chapter_meta
        cases = [
            ('Capitulo 12.5 Nombre_a1b2c3.cbz', 12.5),
            ('Chapter 12.5.cbz', 12.5),
            ('Ch.12.cbz', 12.0),
            ('Cap.12.5.cbz', 12.5),
            ('#12.5.cbz', 12.5),
            ('Vol. 01 c003.cbz', 1.0),      # vol captura el tomo, no el capitulo
            ('v01 c003.cbz', 1.0),
            ('Tomo 3.cbz', 3.0),
            ('Vol. 01.cbz', 1.0),
            ('Capitulo 1.cbz', 1.0),
            ('Serie Nombre Capitulo 1.cbz', 1.0),
            ('Chapter 12.5 - El Comienzo.cbz', 12.5),
        ]
        for fn, expected_num in cases:
            num, _title = chapter_meta(fn)
            self.assertEqual(num, expected_num, f'{fn}: esperaba {expected_num}, sali {num}')

    def test_sin_numero_da_cero(self):
        from ingest import chapter_meta
        num, title = chapter_meta('random_name.cbz')
        self.assertEqual(num, 0.0)
        self.assertEqual(title, 'random_name')


class ChapterMetaDisambiguationTest(ServerTest):
    """Dos archivos que colisionan al mismo cid se desambiguan, no se pisan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # crear una serie con dos archivos que ambos dan num=1.0
        from tests.fixtures import make_cbz, make_series, info_json
        folder = os.path.join(cls.library, 'sintetica-collision')
        os.makedirs(folder, exist_ok=True)
        info_path = os.path.join(folder, 'info.json')
        import json
        with open(info_path, 'w') as f:
            json.dump(info_json('sintetica-collision', 'Serie Collision'), f)
        # dos archivos: "Capitulo 1.cbz" y "Chapter 1.cbz" -> ambos num=1.0
        make_cbz(os.path.join(folder, 'Capitulo 1.cbz'), 2)
        make_cbz(os.path.join(folder, 'Chapter 1.cbz'), 2)
        ingest_library(cls.library, force=True)

    def test_no_se_pisan(self):
        """La serie debe tener 2 capitulos, no 1."""
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        col = next(s for s in cat if s['id'] == 'sintetica-collision')
        self.assertEqual(len(col['chapters']), 2, 'los dos capitulos colisionantes deben coexistir')

    def test_cids_distintos(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        col = next(s for s in cat if s['id'] == 'sintetica-collision')
        cids = {ch['id'] for ch in col['chapters']}
        self.assertEqual(len(cids), 2)
        self.assertIn('c1', cids)
        self.assertIn('c1_2', cids)


class NoCollisionNormalTest(ServerTest):
    """El caso normal (sin colisiones) sigue funcionando como antes."""

    def test_serie_uno_sigue_teniendo_2_capitulos(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        uno = next(s for s in cat if s['id'] == 'sintetica-uno')
        self.assertEqual(len(uno['chapters']), 2)
        self.assertEqual({ch['id'] for ch in uno['chapters']}, {'c1', 'c2'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
