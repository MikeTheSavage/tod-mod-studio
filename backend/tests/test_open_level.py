"""Whole-map opening (map block plus every section) and the mesh lookup for the live preview of added objects.

Uses a proof copy of the game in env TODMS_PROOF (skipped when unset).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')


@unittest.skipUnless(os.path.isdir(os.path.join(PROOF, 'game')), 'proof game not present')
class TestOpenLevel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        os.environ['TODMS_HOME'] = cls.home
        os.environ['TODMS_CACHE'] = os.path.join(PROOF, 'cache')
        from todms import workspace
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))

    def test_whole_map_loads_every_section(self):
        m = next(x for x in self.ws.catalog['maps'] if x['id'] == 'map06_virgillos_farm' or x['id'].startswith('map06'))
        r = self.ws.open_level(m['id'], sections='*')
        self.assertEqual(r['entries'], [m['map_block']] + [s['entry'] for s in m['sections']])
        self.assertEqual(len(r['levels']), 1 + len(m['sections']))
        keys = [e['id'] for L in r['levels'] for e in L['entities']]
        self.assertEqual(len(keys), len(set(keys)))          # every entity keeps its own block, ids are unique
        self.assertTrue(any(v.get('url') for v in r['models'].values()))

    def test_single_section_and_block_only_still_work(self):
        m = next(x for x in self.ws.catalog['maps'] if x['id'].startswith('map06'))
        a = self.ws.open_level(m['id'])
        self.assertEqual(a['entries'], [m['map_block']])
        b = self.ws.open_level(m['id'], m['sections'][0]['entry'])
        self.assertEqual(b['entries'], [m['map_block'], m['sections'][0]['entry']])

    def test_find_models_resolves_enemy_and_vehicle(self):
        r = self.ws.find_models(['/data/characters/gangster/gangster.model', '/data/models/vehicles/forklift/vehicle.model',
                                 '/data/models/collectables/goodies/pickup_oneshot_health_big.model'])
        for name, rec in r.items():
            self.assertTrue(rec.get('url'), name)


if __name__ == '__main__':
    unittest.main()
