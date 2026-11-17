"""Showcase round 5: glass pictures are told from decals and trees, and drawn see-through (synthetic data only)."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from todms import sceneimport as SI


def facts(mean_alpha=0.86, amin=0.75, clear=0.0):
    return dict(clear=clear, amin=amin, amean=mean_alpha, hard=0.1, bad=False)


class GlassTest(unittest.TestCase):
    def test_a_pale_blue_pane_with_alpha_on_a_wall_is_glass(self):
        self.assertTrue(SI.is_glass(facts(), 'opaque', 0.9, [0.65, 0.72, 0.75]))

    def test_a_grey_decal_on_the_ground_is_not_glass(self):
        self.assertFalse(SI.is_glass(facts(0.43, 0.29), 'opaque', 0.0, [0.42, 0.40, 0.40]))

    def test_a_grey_picture_on_a_wall_is_not_glass_unless_the_material_says_blend(self):
        self.assertFalse(SI.is_glass(facts(), 'opaque', 1.0, [0.40, 0.40, 0.40]))
        self.assertTrue(SI.is_glass(facts(), 'blend', 1.0, [0.40, 0.40, 0.40]))

    def test_a_tree_card_and_a_fully_opaque_picture_are_not_glass(self):
        self.assertFalse(SI.is_glass(facts(0.6, 0.0, 0.4), 'opaque', 1.0, [0.2, 0.2, 0.4]))
        self.assertFalse(SI.is_glass(facts(1.0, 1.0), 'opaque', 1.0, [0.5, 0.5, 0.7]))

    def test_the_glass_alpha_is_scaled_down(self):
        img = np.ones((4, 4, 4), np.float32)
        img[..., 3] = 0.8
        out = SI._square_rgba(img, 4, (1, 1, 1), 'blend', 1.0, 0.55)
        self.assertAlmostEqual(float(out[0, 0, 3]), 0.44, places=2)
        self.assertAlmostEqual(float(SI._square_rgba(img, 4, (1, 1, 1), 'blend', 1.0, None)[0, 0, 3]), 0.8, places=2)

    def test_class_vertical_tells_walls_from_floors(self):
        P = np.array([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], np.float32)
        T = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7)], np.int64)
        VM = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        soup = SimpleNamespace(P=P, T=T, VM=VM, tri_class=lambda: VM[T[:, 0]])
        v = SI.class_vertical(soup)
        self.assertLess(v[0], 0.01)
        self.assertGreater(v[1], 0.99)


class RecipeTextures(unittest.TestCase):
    def test_cutout_and_blend_pictures_keep_their_alpha_kind_in_the_recipe(self):
        out = SI.recipe_textures([dict(name='A', kind='scene:a', size=64, format='DXT1', alpha='opaque', sha='x'),
                                  dict(name='B', kind='scene:b', size=128, format='RGBA32', alpha='cutout', sha='y'),
                                  dict(name='C', kind='scene:c', size=64, format='RGBA32', alpha='blend', sha='z')])
        self.assertNotIn('alpha', out[0])
        self.assertEqual(out[1]['alpha'], 'cutout')
        self.assertEqual(out[2]['alpha'], 'blend')
        self.assertNotIn('sha', out[1])


class MoreVoidWater(unittest.TestCase):
    def test_many_separate_holes_all_get_water(self):
        from test_showcase3 import floor_with_hole
        soup = floor_with_hole(size=400.0, hole=(-1, -1, -1, -1), step=10.0, y=21.0)
        # punch six holes of 60 m by dropping every floor cell inside them
        P, T = soup.P, soup.T
        keep = np.ones(len(T), bool)
        holes = [(20, 20), (150, 20), (280, 20), (20, 200), (150, 200), (280, 200)]
        for t in range(len(T)):
            c = P[T[t]].mean(0)
            if any(hx <= c[0] <= hx + 60 and hz <= c[2] <= hz + 60 for hx, hz in holes):
                keep[t] = False
        soup = SimpleNamespace(P=P, T=T[keep])
        bodies = SI.void_water(soup, 25.0, reach=40.0, cell=4.0, min_area=800.0)
        for hx, hz in holes:
            cx, cz = hx + 30, hz + 30
            self.assertTrue(any(b['rect'][0] <= cx <= b['rect'][2] and b['rect'][1] <= cz <= b['rect'][3] for b in bodies), (hx, hz))


class LookEmission(unittest.TestCase):
    def test_the_city_day_lights_light_the_player_and_the_static_meshes(self):
        from todms.mapgen import look
        r = look.resolve(dict(preset='city_day'))
        for k in ('sun', 'ambient'):
            self.assertTrue(r[k]['dynamic_emission'] and r[k]['static_emission'], k)

    def test_a_shipped_preset_keeps_the_flags_of_its_source(self):
        from todms.mapgen import look
        r = look.resolve(dict(preset='train_dust'))               # Map10's own lights have both off
        self.assertFalse(r['sun']['dynamic_emission'])
        self.assertFalse(r['sun']['static_emission'])
        r = look.resolve(dict(preset='clear_day'))                # Hacienda's have both on
        self.assertTrue(r['sun']['dynamic_emission'] and r['sun']['static_emission'])

    def test_apply_look_writes_the_flags(self):
        from todms.mapgen import look
        calls = []

        class Doc:
            def created_ids(self):
                return [1]

            def type_of(self, n):
                return 'default_global_light(Light)'

            def get(self, n, prop, default=None):
                return dict(light_type=2, dynamic_emission=False, static_emission=False).get(prop)

            def set_prop(self, n, prop, value, note=True):
                calls.append((prop, value))
        look.apply_look({'f': Doc()}, dict(sun=dict(color=[1, 1, 1], brightness=1.0, dynamic_emission=True, static_emission=True)))
        self.assertIn(('dynamic_emission', True), calls)
        self.assertIn(('static_emission', True), calls)


class LandingClear(unittest.TestCase):
    def entry(self, spot_pos, yaw):
        return dict(id='e1', block='host.submap', pos=[-237.0, 2.5, -43.66], orient=[0, 0.70710678, 0, 0.70710678], size=[12, 6, 2],
                    back=dict(pos=[26.0, 29.8, 8.0], size=[12, 6, 2], spot=dict(pos=spot_pos, yaw=yaw)))

    def run_check(self, spot_pos, yaw):
        from todms.newmap_recipe import make_new_map as MM
        checks = []
        MM.check_landing_clear(dict(name='Map99_Test', entries=[self.entry(spot_pos, yaw)]), checks)
        return checks[0]['result']

    def test_a_landing_beside_the_loader_looking_at_it_warns(self):
        self.assertEqual(self.run_check([-229.0, 2.5, -43.66], 90.0), 'WARN')       # yaw 90 looks along -x, at the box

    def test_a_landing_beside_the_loader_looking_away_but_very_close_warns(self):
        self.assertEqual(self.run_check([-234.0, 2.5, -43.66], 270.0), 'WARN')

    def test_a_landing_a_few_metres_off_looking_away_passes(self):
        self.assertEqual(self.run_check([-229.0, 2.5, -43.66], 270.0), 'PASS')

    def test_a_far_landing_passes(self):
        self.assertEqual(self.run_check([-200.0, 2.5, -43.66], 90.0), 'PASS')


class FlushSlabs(unittest.TestCase):
    def floor(self, flip):
        P = np.array([(0, 3, 0), (10, 3, 0), (10, 3, 10), (0, 3, 10)], np.float32)
        T = np.array([(0, 2, 1), (0, 3, 2)] if not flip else [(0, 1, 2), (0, 2, 3)], np.int64)
        N = np.tile(np.array([[0, 1, 0]], np.float32), (4, 1))
        return P, T, N

    def top_of(self, pcs):
        return max(float(p['points'][:, 1].max()) for p in pcs)

    def test_the_slab_top_is_the_drawn_floor_whichever_way_the_triangles_wind(self):
        from todct import scenekit as SK
        for flip in (False, True):
            P, T, N = self.floor(flip)
            pcs = SK.collision(P, T, np.ones(len(T), bool), np.zeros(len(T), np.int64), dict(cell_m=20.0), None, N=N)
            self.assertTrue(pcs)
            self.assertAlmostEqual(self.top_of(pcs), 3.0, places=3)
            self.assertAlmostEqual(min(float(p['points'][:, 1].min()) for p in pcs), 2.6, places=3)

    def test_the_old_centred_slab_is_still_available(self):
        from todct import scenekit as SK
        P, T, N = self.floor(False)
        pcs = SK.collision(P, T, np.ones(len(T), bool), np.zeros(len(T), np.int64), dict(cell_m=20.0, flush=False), None, N=N)
        self.assertAlmostEqual(self.top_of(pcs), 3.2, places=3)


if __name__ == '__main__':
    unittest.main()
