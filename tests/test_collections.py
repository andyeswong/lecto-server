"""Contrato de collections: CRUD, nombre repetido (case-insensitive), ids desconocidos."""
import unittest

from tests.harness import ServerTest, http_json


class CollectionsTest(ServerTest):

    def setUp(self):
        _, cat = http_json(self.base, 'GET', '/api/catalog')
        self.sids = [s['id'] for s in cat]

    def test_create_list_delete(self):
        code, col = http_json(self.base, 'POST', '/api/collections',
                              {'name': 'Favoritos', 'series': [self.sids[0]]})
        self.assertEqual(code, 201)
        cid = col['id']
        self.assertEqual(col['name'], 'Favoritos')
        self.assertEqual(col['series'], [self.sids[0]])

        code, lst = http_json(self.base, 'GET', '/api/collections')
        self.assertEqual(code, 200)
        self.assertIn(cid, [c['id'] for c in lst])

        code, _ = http_json(self.base, 'DELETE', f'/api/collections/{cid}')
        self.assertEqual(code, 200)

        code, lst = http_json(self.base, 'GET', '/api/collections')
        self.assertNotIn(cid, [c['id'] for c in lst])

    def test_nombre_requerido(self):
        code, _ = http_json(self.base, 'POST', '/api/collections', {'name': ''})
        self.assertEqual(code, 400)
        code, _ = http_json(self.base, 'POST', '/api/collections', {})
        self.assertEqual(code, 400)

    def test_nombre_repetido_case_insensitive(self):
        http_json(self.base, 'POST', '/api/collections', {'name': 'Mi Coleccion'})
        code, _ = http_json(self.base, 'POST', '/api/collections', {'name': 'mi coleccion'})
        self.assertEqual(code, 400)

    def test_nombre_repetido_en_update(self):
        code, a = http_json(self.base, 'POST', '/api/collections', {'name': 'Alpha'})
        http_json(self.base, 'POST', '/api/collections', {'name': 'Beta'})
        # renombrar Beta a Alpha debe fallar
        code, _ = http_json(self.base, 'PUT', f'/api/collections/{a["id"]}', {'name': 'Beta'})
        self.assertEqual(code, 400)
        # pero renombrar a si mismo (mismo nombre) si
        code, _ = http_json(self.base, 'PUT', f'/api/collections/{a["id"]}', {'name': 'Alpha'})
        self.assertEqual(code, 200)

    def test_ids_desconocidos_se_descartan(self):
        code, col = http_json(self.base, 'POST', '/api/collections',
                              {'name': 'Con Desconocidos', 'series': [self.sids[0], 'id-falso', self.sids[1]]})
        self.assertEqual(code, 201)
        self.assertEqual(col['series'], [self.sids[0], self.sids[1]])

    def test_duplicados_colapsados(self):
        code, col = http_json(self.base, 'POST', '/api/collections',
                              {'name': 'Dup', 'series': [self.sids[0], self.sids[0]]})
        self.assertEqual(code, 201)
        self.assertEqual(col['series'], [self.sids[0]])

    def test_update_series_reemplaza(self):
        code, col = http_json(self.base, 'POST', '/api/collections', {'name': 'Replace', 'series': [self.sids[0]]})
        code, col = http_json(self.base, 'PUT', f'/api/collections/{col["id"]}', {'series': [self.sids[1], self.sids[2]]})
        self.assertEqual(code, 200)
        self.assertEqual(col['series'], [self.sids[1], self.sids[2]])

    def test_update_inexistente_404(self):
        code, _ = http_json(self.base, 'PUT', '/api/collections/deadbeef', {'name': 'X'})
        self.assertEqual(code, 404)

    def test_delete_inexistente_404(self):
        code, _ = http_json(self.base, 'DELETE', '/api/collections/deadbeef')
        self.assertEqual(code, 404)

    def test_id_mal_formado_no_matchea(self):
        # 7 hex (no 8) no hace match -> 404
        code, _ = http_json(self.base, 'PUT', '/api/collections/deadbee', {'name': 'X'})
        self.assertEqual(code, 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
