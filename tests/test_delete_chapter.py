"""DELETE /api/series/<id>/chapters/<cid>: the chapter is gone, file included."""
import os
import unittest

import store
from tests.harness import ServerTest, http, http_json


class DeleteChapter(ServerTest):
    def test_borra_capitulo_archivo_y_favs(self):
        c = store.connect()
        folder = store.series_folder(c, 'sintetica-uno')
        src = c.execute("select source_file from chapters where series_id='sintetica-uno' and id='c2'").fetchone()['source_file']
        c.close()
        self.assertTrue(os.path.exists(os.path.join(folder, src)))
        http_json(self.base, 'POST', '/api/favs', {'kind': 'page', 'series': 'sintetica-uno', 'chapter': 'c2', 'page': 1})
        self.assertEqual(http(self.base, 'GET', '/api/thumbs/s/sintetica-uno/c2/1.webp')[0], 200)
        code, _ = http_json(self.base, 'DELETE', '/api/series/sintetica-uno/chapters/c2')
        self.assertEqual(code, 200)
        cat = {s['id']: s for s in http_json(self.base, 'GET', '/api/catalog')[1]}
        self.assertEqual([ch['id'] for ch in cat['sintetica-uno']['chapters']], ['c1'])
        self.assertFalse(os.path.exists(os.path.join(folder, src)))
        self.assertEqual(http(self.base, 'GET', '/api/pages/sintetica-uno/c2/1.jpg')[0], 404)
        self.assertFalse([f for f in http_json(self.base, 'GET', '/api/favs')[1] if f.get('chapter') == 'c2'])
        self.assertEqual(http_json(self.base, 'DELETE', '/api/series/sintetica-uno/chapters/c2')[0], 404)


if __name__ == '__main__':
    unittest.main()
