"""Showcase worker: map names built from words, new_geometry in extension sections, bake coverage."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


class MapNames(unittest.TestCase):
    def test_words_not_filler_letters(self):
        from todms import world
        self.assertEqual(world.suggest_map_name('Showcase'), 'Map11_ShowcaseCity')
        self.assertEqual(world.suggest_map_name('Mesa Compound'), 'Map11_MesaCompound')
        self.assertEqual(world.suggest_map_name('KX24 Downtown'), 'Map11_KX24Downtown')

    def test_always_the_exact_length(self):
        from todms import world
        for title in ['', 'x', 'Showcase', 'A very long title that cannot fit', 'Neon Harbor District', '12345678901234567890', 'ab cd']:
            for n in (18, 20, 14):
                self.assertEqual(len(world.suggest_map_name(title, n)), n, (title, n))

    def test_taken_names_are_skipped(self):
        from todms import world
        first = world.suggest_map_name('Showcase')
        second = world.suggest_map_name('Showcase', 18, [first])
        self.assertNotEqual(first, second)
        self.assertEqual(len(second), 18)
        self.assertTrue(second.startswith('Map11_Showcase'))

    def test_only_letters_and_digits(self):
        from todms import world
        self.assertRegex(world.suggest_map_name('Rock & Roll! (1)'), r'^Map11_[A-Za-z0-9]{12}$')


class Streets(unittest.TestCase):
    class Soup:
        def __init__(self, P, T, cls):
            self.P, self.T, self._c = P, T, cls

        def tri_class(self):
            return self._c

    def road(self, x0, x1, z0, z1, y, cls, P, T, C):
        n = len(P)
        P += [[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]]
        T += [[n, n + 2, n + 1], [n, n + 3, n + 2]]                  # counter-clockwise seen from above: the normal points up
        C += [cls, cls]

    def test_a_street_spot_sits_on_the_road_and_faces_down_it(self):
        import numpy as np
        from todms import sceneimport as SI
        P, T, C = [], [], []
        for k in range(10):                                              # a road 6 m wide and 100 m long along z, in 10 m pieces
            self.road(-3.0, 3.0, -50.0 + 10 * k, -40.0 + 10 * k, 12.0, 1, P, T, C)
        self.road(-60.0, -40.0, -60.0, -40.0, 12.0, 2, P, T, C)          # a concrete yard that is not a street
        soup = self.Soup(np.array(P, np.float32), np.array(T, np.int64), np.array(C, np.int64))
        spots = SI.street_spots(soup, {1: 'Asphalt', 2: 'Concrete'})
        self.assertEqual(len(spots), 1)
        sp = spots[0]
        self.assertAlmostEqual(sp['pos'][1], 13.0, places=1)             # a metre above the road
        self.assertLess(abs(sp['pos'][0]), 3.0)
        yaw = sp['yaw']
        self.assertTrue(min(abs(yaw - 0.0), abs(yaw - 180.0), abs(yaw - 360.0)) < 5.0, yaw)    # along z: 0 faces +z, 180 faces -z
        self.assertGreater(sp['length'], 40.0)

    def test_no_road_no_spot(self):
        import numpy as np
        from todms import sceneimport as SI
        P, T, C = [], [], []
        self.road(0, 20, 0, 20, 5.0, 2, P, T, C)
        soup = self.Soup(np.array(P, np.float32), np.array(T, np.int64), np.array(C, np.int64))
        self.assertEqual(SI.street_spots(soup, {2: 'Concrete'}), [])


HOST = 'submap01_map02_lostoros_downtown.submap'
PROOF = os.path.join(os.environ.get('TODMS_PROOF', '/no-proof-copy'), 'game')


class ExtensionGeometry(unittest.TestCase):
    """new_geometry inside an extension section, against the real blocks (read only); skipped without the proof game."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(PROOF, 'blocks.naz')):
            raise unittest.SkipTest('needs the read-only proof game')
        import tempfile
        from todms.workspace import Workspace
        cls.ws = Workspace()
        cls.ws.set_game(PROOF)
        cls.dir = tempfile.mkdtemp(prefix='showcase_')

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(getattr(cls, 'dir', ''), ignore_errors=True)

    def build(self, mode, label, region=None, extra=None):
        from todms import newmap
        carry = dict(mode=mode)
        if region:
            carry['region'] = region
        host = dict(block=HOST, enter=dict(pos=[-237, 2.5, -43.66], size=[12, 6, 2]), leave=dict(pos=[-255, 2.5, -43.66], size=[12, 6, 2]))
        ng = dict(folder='ExtShowcase', textures=[dict(name='T1', kind='concrete', size=64, format='DXT1')],
                  models=[dict(name='EXTBOX', parts=[dict(type='box', min=[-5, 0, -5], max=[5, 4, 5], tex='T1')])],
                  placements=[dict(model='EXTBOX', pos=[-300.0, 2.0, -60.0], name='EB1'), dict(model='EXTBOX', pos=[-320.0, 2.0, -60.0], name='EB2')])
        ext = dict(name='Block', placement='extension', host=host, carry=carry, new_geometry=ng, **(extra or {}))
        out = os.path.join(self.dir, label)
        os.makedirs(out)
        p = os.path.join(out, 'params.json')
        newmap.write(p, dict(package='T', maps=[ext]))
        return newmap.run_argv([p, '--out', out], self.ws), out

    def test_new_geometry_builds_into_an_extension_that_carries_nothing(self):
        rep, out = self.build('nothing', 'nothing')
        bad = [c for c in rep['checks'] if c['result'] == 'FAIL']
        self.assertEqual(rep['result'], 'PASS', bad[:3])
        g = [x for x in rep['geometry'] if x['map'] == 'Block'][0]
        self.assertEqual([p['name'] for p in g['placements']], ['EB1', 'EB2'])
        self.assertTrue(all(c['ok'] for c in g['checks']))
        self.assertTrue(rep['manifest']['sections'][0]['new_geometry'])
        self.assertEqual(g['bake']['status'], 'baked', g['bake'].get('reason'))
        self.assertTrue(any('baked lighting read back' in c['check'] and c['result'] == 'PASS' for c in rep['checks']), [c['check'] for c in rep['checks']])

    def test_an_extension_can_land_the_player_on_a_spot_and_hold_a_car(self):
        rep, out = self.build('nothing', 'spots', extra=dict(teleports=[dict(name='ROAD_SPOT', pos=[-300.0, 6.5, -40.0], yaw=180.0)],
                                                           vehicles=[dict(pos=[-296.0, 6.2, -44.0], yaw=180.0)]))
        self.assertEqual(rep['result'], 'PASS', [c for c in rep['checks'] if c['result'] == 'FAIL'][:3])

    def test_new_geometry_builds_into_an_extension_that_carries_a_region(self):
        rep, out = self.build('region', 'region', region=[-270, -80, -200, -10])
        bad = [c for c in rep['checks'] if c['result'] == 'FAIL']
        self.assertEqual(rep['result'], 'PASS', bad[:3])
        g = [x for x in rep['geometry'] if x['map'] == 'Block'][0]
        self.assertEqual(len(g['placements']), 2)
        # the host's baked drawing is kept (its single-colour entries too) and the new geometry is baked with it
        self.assertEqual(g['bake']['status'], 'baked', g['bake'].get('reason'))
        self.assertGreater(g['bake']['carried_instances'], 0)

    def test_new_geometry_is_baked_beside_a_host_that_carries_everything(self):
        rep, out = self.build('all', 'all')
        self.assertEqual(rep['result'], 'PASS', [c for c in rep['checks'] if c['result'] == 'FAIL'][:3])
        g = [x for x in rep['geometry'] if x['map'] == 'Block'][0]
        self.assertEqual(g['bake']['status'], 'baked', g['bake'].get('reason'))
        self.assertGreater(g['bake']['carried_instances'], 0)
        self.assertTrue(any('baked lighting read back' in c['check'] and c['result'] == 'PASS' for c in rep['checks']), [c['check'] for c in rep['checks']])


if __name__ == '__main__':
    unittest.main()


class BakeLevel(unittest.TestCase):
    def test_the_level_matches_the_shipped_maps(self):
        import numpy as np
        from todms import bake
        rng = np.random.default_rng(3)
        dark = np.clip(rng.random((5000, 3)) * 0.45, 0, 1)                    # a dense district: plain sun and ambient bake dark
        out, rep = bake.calibrate_level(dark)
        lum = out @ bake.LUM_W
        self.assertAlmostEqual(float(lum.mean()), bake.LEVEL_TARGET_MEAN, delta=0.02)
        self.assertGreaterEqual(float(lum.min()) * 1.0, bake.LEVEL_FLOOR - 0.01)       # nothing below the shipped shadow floor
        self.assertGreater(rep['gain'], 1.0)
        self.assertLessEqual(float(out.max()), 1.0)

    def test_a_bright_bake_is_left_alone_except_the_floor(self):
        import numpy as np
        from todms import bake
        bright = np.full((100, 3), 0.8)
        out, rep = bake.calibrate_level(bright)
        self.assertEqual(rep['gain'], 1.0)
        self.assertTrue(np.allclose(out, bright))
