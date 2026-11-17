"""Showcase round 9: the plan of a scene (minimap and placement view), step limit of the collision, backdrop. Synthetic data only."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, HERE)
import scenefix  # noqa: E402
from test_scene import Base, params  # noqa: E402
from todms import scenplan  # noqa: E402


def soup(boxes=(), road=None):
    """A ground (z -60..0), a road strip along x on it (z -8..0) and tall boxes. -> P, T, road_tri"""
    parts = []
    P0, _, _, T0 = scenefix.grid_plane(-60, -60, 60, 0, 16, 0.0)
    parts.append((P0, T0, False))
    Pr, _, _, Tr = scenefix.grid_plane(-60, -8, 60, 0, 12, 0.0)
    parts.append((Pr, Tr, True))
    for (cx, cz, w, d, h) in boxes:
        Pb, _, _, Tb = scenefix.box(cx, cz, w, d, h)
        parts.append((Pb, Tb, False))
    P, T, R = [], [], []
    for p, t, r in parts:
        T.append(t + sum(len(x) for x in P))
        P.append(p)
        R.append(np.full(len(t), r))
    return np.concatenate(P), np.concatenate(T), np.concatenate(R)


class Plan(unittest.TestCase):
    def make(self):
        P, T, R = soup(boxes=[(30, 14, 16, 8, 14), (-30, 14, 10, 10, 9), (0, 59, 4, 2, 30)])
        return scenplan.make(P, T, R, 0.0, water=[[-60, 24, 60, 56]], cell=1.0)

    def test_roads_ground_buildings_and_water_are_told_apart(self):
        pl = self.make()
        self.assertEqual(scenplan.at(pl, 0.0, -4.0), scenplan.ROAD)
        self.assertEqual(scenplan.at(pl, 0.0, -40.0), scenplan.GROUND)
        self.assertEqual(scenplan.at(pl, 30.0, 14.0), scenplan.BUILDING)
        self.assertEqual(scenplan.at(pl, -30.0, 14.0), scenplan.BUILDING)
        self.assertEqual(scenplan.at(pl, 0.0, 40.0), scenplan.WATER)
        self.assertEqual(scenplan.at(pl, 500.0, 500.0), scenplan.NONE)

    def test_a_roof_over_a_street_does_not_hide_the_street(self):
        # an arcade: a deck 6 m up over the road strip, with the road still under it
        P, T, R = soup()
        Pd, _, _, Td = scenefix.grid_plane(-10, -6, 10, -1, 2, 6.0)
        P2 = np.concatenate([P, Pd])
        T2 = np.concatenate([T, Td + len(P)])
        R2 = np.concatenate([R, np.zeros(len(Td), bool)])
        pl = scenplan.make(P2, T2, R2, 0.0, cell=1.0)
        self.assertEqual(scenplan.at(pl, 0.0, -3.0), scenplan.ROAD)

    def test_bounds_follow_the_content(self):
        pl = self.make()
        b = scenplan.bounds(pl)
        self.assertLessEqual(b[0], -59.0)
        self.assertGreaterEqual(b[2], 59.0)
        self.assertLessEqual(b[1], -59.0)
        self.assertGreaterEqual(b[3], 59.0)

    def test_an_empty_scene_has_no_plan(self):
        self.assertIsNone(scenplan.make(np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, bool), 0.0))

    def test_the_file_round_trips_and_the_view_covers_the_grid(self):
        pl = self.make()
        d = tempfile.mkdtemp()
        try:
            info = scenplan.write(d, pl)
            back = scenplan.read(d, info)
            self.assertTrue((back['grid'] == pl['grid']).all())
            self.assertEqual(info['cells']['building'], int((pl['grid'] == scenplan.BUILDING).sum()))
            v = scenplan.view(d, info)
            self.assertEqual(len(v['rect']), 4)
            self.assertAlmostEqual(v['rect'][2] - v['rect'][0], pl['grid'].shape[1] * pl['cell'], places=2)
            self.assertIsNone(scenplan.read(d, dict(info, file='gone.png')))
            self.assertIsNone(scenplan.read(d, dict(info, w=info['w'] + 1)))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_distance_field_is_negative_inside_and_in_metres(self):
        pl = self.make()
        f = scenplan.sdf(pl['grid'], scenplan.BUILDING, pl['cell'])
        v = scenplan.bilinear(f, pl, np.array([30.0, 38.5]), np.array([14.0, 14.0]))
        self.assertLess(v[0], -2.0)                      # the middle of a 16 x 8 m block is 4 m from its edge
        self.assertGreater(v[1], 0.0)                    # 8.5 m east of the middle, 0.5 m beyond the east edge


class MinimapFromPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mm9_')
        self.p = patch.dict(os.environ, TODMS_HOME=os.path.join(self.tmp, 'home'), TODMS_CACHE=os.path.join(self.tmp, 'cache'), TODMS_SAVES=os.path.join(self.tmp, 's'))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pack(self):
        from todms import minimap as mm
        P, T, R = soup(boxes=[(30, 14, 16, 8, 14), (0, 59, 4, 2, 30)])
        pl = scenplan.make(P, T, R, 0.0, water=[[-60, 24, 60, 56]], cell=1.0)
        m = dict(name='Map11_PlanTest', _plan=pl, edges=[dict(id='rim', kind='invisible', rect=[-59, -59, 59, 59], height=20.0)])
        info = mm.build(m, os.path.join(self.tmp, 'out'), None, None)
        with open(os.path.join(self.tmp, 'out', info['file']), 'rb') as f:
            return mm, info, f.read(), pl

    def test_the_pack_shows_the_streets_buildings_and_water_where_the_dll_looks(self):
        mm, info, pack, pl = self.pack()
        road = mm.sample(pack, info, 0.0, -4.0)
        self.assertGreater(road[3], 150)
        self.assertLess(abs(road[0] - mm.INK['road'][0]), 40)
        water = mm.sample(pack, info, 0.0, 40.0)
        self.assertGreater(water[3], 100)
        self.assertGreater(water[2], water[0])
        bld = mm.sample(pack, info, 30.0, 14.0)
        self.assertGreater(bld[3], 60)
        # outside the scene is paper
        self.assertLess(mm.sample(pack, info, -57.0, -57.0)[3] + 0, 255)
        self.assertEqual(info['bounds'][0] < -59 and info['bounds'][2] > 59, True)

    def test_the_calibration_checks_pass(self):
        mm, info, pack, pl = self.pack()
        rows = mm.calibrate(os.path.join(self.tmp, 'out'), info)
        names = [r['check'] for r in rows]
        self.assertTrue(any('scene plan' in n and 'road' in n for n in names), names)
        self.assertTrue(any('scene plan' in n and 'building' in n for n in names), names)
        self.assertTrue(any('scene plan' in n and 'water' in n for n in names), names)
        self.assertEqual([r for r in rows if r['result'] != 'PASS'], [])

    def test_the_occupancy_marks_the_ground_of_the_scene(self):
        mm, info, pack, pl = self.pack()
        with open(os.path.join(self.tmp, 'out', info['occ'])) as f:
            lines = f.read().split()
        self.assertTrue(lines[0] == 'occ')
        rows = lines[6:]
        self.assertTrue(any('1' in r for r in rows))
        self.assertTrue(any('0' in r for r in rows))

    def test_a_plan_with_nothing_in_it_is_refused(self):
        from todms import minimap as mm
        pl = dict(grid=np.zeros((8, 8), np.uint8), x0=0.0, z1=8.0, cell=1.0)
        with self.assertRaises(mm.MinimapError):
            mm.build(dict(name='Map11_Empty', _plan=pl), os.path.join(self.tmp, 'o2'), None, None)


class SendWritesThePlan(Base):
    def test_send_keeps_a_plan_beside_the_project_and_the_views_read_it(self):
        from todms import newmap, sceneimport as SI, missions_tpl as MT
        r = self.open()
        res = SI.send(r['sid'], params(), dict(kind='newmap', name='TestScene'))
        proj = newmap.get_project(res['id'])
        m = proj['params']['maps'][0]
        info = m['scene']['plan']
        self.assertTrue(os.path.exists(os.path.join(proj['path'], info['file'])))
        self.assertGreater(info['cells']['road'] + info['cells']['ground'], 1000)
        v = MT.plan_view(res['id'], m)
        self.assertTrue(v['png'])
        self.assertEqual(len(v['rect']), 4)
        pl = scenplan.read(proj['path'], info)
        # the synthetic city is one ground plane (dark: it reads as road) with boxes standing on it
        self.assertIn(scenplan.at(pl, 0.0, 0.0), (scenplan.GROUND, scenplan.ROAD))

    def test_the_minimap_of_a_project_draws_from_the_plan(self):
        from todms import newmap, sceneimport as SI
        from todms.workspace import Workspace
        r = self.open()
        res = SI.send(r['sid'], params(), dict(kind='newmap', name='TestScene'))
        out = newmap.minimap(Workspace(), res['id'])
        self.assertEqual(len(out['maps']), 1)
        self.assertGreater(out['maps'][0]['tiles'], 0)
        self.assertEqual([c for c in out['checks'] if c['result'] == 'FAIL'], [])


class Steps(unittest.TestCase):
    """The player climbs 1.55 m and not 1.6 m (measured in game); the plan counts the ledges above that."""

    def scene(self, heights):
        P, T, R = soup()
        for k, h in enumerate(heights):                       # a block every 20 m along x, h metres tall (a plinth when h is small)
            Pb, _, _, Tb = scenefix.box(-45.0 + 20.0 * k, -30.0, 10.0, 10.0, h)
            T = np.concatenate([T, Tb + len(P)])
            P = np.concatenate([P, Pb])
            R = np.concatenate([R, np.zeros(len(Tb), bool)])
        return scenplan.make(P, T, R, 0.0, cell=1.0)

    def test_a_kerb_and_a_plinth_below_the_limit_are_no_problem(self):
        st = self.scene([0.5, 1.2])['steps']
        self.assertEqual(st['count'], 0)
        self.assertEqual(st['limit'], scenplan.STEP_LIMIT)

    def test_a_ledge_above_the_limit_is_counted_with_its_height_and_place(self):
        st = self.scene([0.5, 2.0, 3.0])['steps']
        self.assertEqual(st['count'], 2)
        self.assertAlmostEqual(st['highest'], 3.0, delta=0.1)
        x, z, h = st['places'][0]
        self.assertAlmostEqual(h, 3.0, delta=0.1)
        self.assertLess(abs(z + 30.0), 8.0)

    def test_a_wall_is_not_a_step(self):
        st = self.scene([9.0])['steps']
        self.assertEqual(st['count'], 0)

    def test_the_build_check_warns_with_the_count_and_passes_without(self):
        from todms.newmap_recipe import make_new_map as MM
        rows = []
        MM.check_scene_steps(dict(name='M', mapgen=dict(scene_steps=dict(limit=1.5, count=2, highest=3.0, places=[[1.0, 2.0, 3.0], [4.0, 5.0, 2.0]]))), rows)
        self.assertEqual(rows[0]['result'], 'WARN')
        self.assertIn('2 places', rows[0]['evidence'])
        rows = []
        MM.check_scene_steps(dict(name='M', mapgen=dict(scene_steps=dict(limit=1.5, count=0, highest=0.0, places=[]))), rows)
        self.assertEqual(rows[0]['result'], 'PASS')
        rows = []
        MM.check_scene_steps(dict(name='M'), rows)               # not a scene: no row
        self.assertEqual(rows, [])


class Skyline(unittest.TestCase):
    def tmap(self, **bd):
        m = dict(name='Map11_SkyTest', edges=[dict(id='rim', kind='invisible', rect=[-100.0, -80.0, 100.0, 80.0], height=50.0)],
                 scene=dict(ground_y=10.0, plan=dict(heights=[40.0, 80.0, 120.0], x0=-100.0, z1=80.0, cell=1.0, w=200, h=160)),
                 backdrop=dict(kind='skyline', height='scene', **bd))
        return m

    def build(self, m):
        from todms.mapgen import core, backdrop, texkinds
        texkinds.register()
        out = core.Out(m['name'])
        return out, backdrop.build(m, out)

    def test_a_ring_of_towers_stands_outside_the_rim(self):
        from todms.mapgen import meshkit
        out, st = self.build(self.tmap(count=60))
        self.assertEqual(st['towers'], 60)
        self.assertEqual(sorted(md['name'] for md in out.models), ['BACKDROP_E', 'BACKDROP_N', 'BACKDROP_S', 'BACKDROP_W'])
        self.assertEqual(len(out.placements), 4)
        for md in out.models:
            meshes, hulls = meshkit.read_part(md['parts'][0])
            self.assertEqual(hulls, [])                                  # nothing to collide with
            P = np.concatenate([me['P'] for me in meshes])
            inside = (P[:, 0] > -100.0) & (P[:, 0] < 100.0) & (P[:, 2] > -80.0) & (P[:, 2] < 80.0)
            self.assertFalse(inside.any(), md['name'])                   # all of it lies beyond the rim
            self.assertGreaterEqual(float(P[:, 1].min()), 4.0 - 1e-3)    # base 6 m under the street level (y 10)
        self.assertIn('B_Skyline', out.textures)

    def test_heights_follow_the_scene_and_the_ring_is_the_same_every_time(self):
        m = self.tmap(count=40)
        a = self.build(m)[0]
        b = self.build(m)[0]
        self.assertEqual(a.models, b.models)
        from todms.mapgen import meshkit
        top = max(float(np.concatenate([me['P'] for me in meshkit.read_part(md['parts'][0])[0]])[:, 1].max()) for md in a.models)
        self.assertLess(top, 4.0 + 120.0 * 1.5 + 1.0)                     # no taller than the scene's tallest times the stretch
        c = self.build(dict(m, backdrop=dict(m['backdrop'], seed=7)))[0]
        self.assertNotEqual(a.models, c.models)

    def test_a_fixed_height_range_and_a_base(self):
        from todms.mapgen import meshkit
        out, st = self.build(dict(self.tmap(count=30), backdrop=dict(kind='skyline', height=[50.0, 60.0], base=0.0, count=30)))
        P = np.concatenate([me['P'] for md in out.models for me in meshkit.read_part(md['parts'][0])[0]])
        self.assertAlmostEqual(float(P[:, 1].min()), 0.0, places=3)
        self.assertLessEqual(float(P[:, 1].max()), 60.0 + 1e-3)

    def test_off_and_bad_settings(self):
        from todms.mapgen import core, backdrop
        self.assertIsNone(self.build(dict(self.tmap(), backdrop=dict(kind='none')))[1])
        self.assertIsNone(self.build(dict(self.tmap(), backdrop=None))[1])
        with self.assertRaises(core.MapgenError):
            self.build(dict(self.tmap(), backdrop=dict(kind='skyline', count=0)))
        with self.assertRaises(core.MapgenError):
            self.build(dict(self.tmap(), backdrop=dict(kind='castle')))
        with self.assertRaises(core.MapgenError):
            self.build(dict(self.tmap(), backdrop=dict(kind='skyline', height=[90.0, 20.0])))

    def test_without_a_rim_it_says_so_and_draws_nothing(self):
        from todms.mapgen import core, backdrop
        out = core.Out('M')
        self.assertIsNone(backdrop.build(dict(name='M', backdrop=dict(kind='skyline')), out))
        self.assertTrue(out.notes)

    def test_expansion_hands_the_ring_to_the_builder(self):
        from todms import mapgen
        m = dict(self.tmap(count=24), look=dict(preset='city_day'))
        res = mapgen.expand_full(dict(package='T', maps=[m]))
        mm = res['params']['maps'][0]
        names = [md['name'] for md in mm['new_geometry']['models']]
        self.assertIn('BACKDROP_N', names)
        self.assertEqual(res['stats']['Map11_SkyTest']['backdrop']['towers'], 24)
        self.assertNotIn('backdrop', mm)


if __name__ == '__main__':
    unittest.main()
