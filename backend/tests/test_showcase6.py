"""Showcase round 6: a new scale carries everything placed relative to the scene (synthetic data only)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import sceneimport as SI, missions_tpl as MT, newmap


def a_map():
    return dict(name='Map11_CityTest', arrival=dict(pos=[26.0, 30.1, 30.0], orient=[0, 0, 0, 1], floor='none'),
                **{'return': dict(pos=[26.0, 31.1, 24.0], size=[6, 6, 2])},
                entries=[dict(id='e1', block='host.submap', pos=[-237.0, 2.5, -43.66], size=[12, 6, 2], arrive=dict(pos=[26.0, 30.1, 30.0], yaw=0.0),
                              back=dict(pos=[26.0, 29.8, 8.0], size=[12, 6, 2], spot=dict(pos=[-229.0, 2.5, -43.66], yaw=270.0)))],
                look=dict(preset='city_day', fog=dict(near=90.0, far=380.0)), scene=dict(ground_y=29.1, params=dict(scale=1.0)))


class RescaleMap(unittest.TestCase):
    def test_places_in_the_scene_double_with_a_doubled_scale(self):
        m = SI.rescale_map(a_map(), 2.0)
        self.assertEqual(m['arrival']['pos'], [52.0, 59.2, 60.0])          # a standing place keeps its one metre above the floor
        e = m['entries'][0]
        self.assertEqual(e['arrive']['pos'], [52.0, 59.2, 60.0])
        self.assertEqual(e['back']['pos'][0], 52.0)
        self.assertEqual(e['back']['pos'][2], 16.0)
        self.assertEqual(m['look']['fog'], dict(near=180.0, far=760.0))
        self.assertEqual(m['scene']['ground_y'], 58.2)

    def test_what_lies_in_the_host_map_stays(self):
        e = SI.rescale_map(a_map(), 2.0)['entries'][0]
        self.assertEqual(e['pos'], [-237.0, 2.5, -43.66])
        self.assertEqual(e['size'], [12, 6, 2])
        self.assertEqual(e['back']['spot'], dict(pos=[-229.0, 2.5, -43.66], yaw=270.0))
        self.assertEqual(e['back']['size'], [12, 6, 2])

    def test_a_box_moves_out_with_the_floor_and_still_surrounds_the_player(self):
        b = SI.rescale_map(a_map(), 2.0)['entries'][0]['back']        # 29.8 with the floor at 29.1 (0.7 above it); at double scale the floor is 58.2, the middle 59.6
        self.assertAlmostEqual(b['pos'][1], 59.6, places=2)
        floor, top = 58.2, b['pos'][1] + b['size'][1] / 2
        self.assertGreater(top - (floor + 1.8), 0.5)                   # a standing player's head is inside

    def test_the_original_is_untouched_and_a_unit_ratio_is_the_identity(self):
        m = a_map()
        SI.rescale_map(m, 3.0)
        self.assertEqual(m, a_map())
        self.assertEqual(SI.rescale_map(m, 1.0), m)


class RescaleMissions(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.t.name, 'home'), TODMS_CACHE=os.path.join(self.t.name, 'cache'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def test_hosts_and_mission_points_follow_a_new_scale(self):
        proj = dict(name='City', hosts=[dict(id='city', kind='new_map', newmap_id='abc', map_index=0, area=[-150.0, -150.0, 150.0, 150.0], ground_y=29.5),
                                        dict(id='dt', kind='existing', block='b.submap', area=[0, 0, 50, 50], ground_y=2.5)],
                    missions=[dict(id='run', type='ghost', host='city', index=79,
                                   params=dict(giver_pos=[26.0, None, 44.0], giver_size=5.0, goal=[26.0, None, 90.0], goal_width=14.0,
                                               guards=[[19.0, None, 54.0], [30.0, 30.0, 60.0]], name='RUN')),
                              dict(id='other', type='ghost', host='dt', index='auto', params=dict(goal=[10.0, None, 10.0]))])
        MT.save_project(proj, 'p1')
        self.assertEqual(MT.rescale_hosts('abc', 2.0), 1)
        got = MT.get_project('p1')['project']
        self.assertEqual(got['hosts'][0]['area'], [-300.0, -300.0, 300.0, 300.0])
        self.assertEqual(got['hosts'][0]['ground_y'], 59.0)
        self.assertEqual(got['hosts'][1]['area'], [0, 0, 50, 50])
        p = got['missions'][0]['params']
        self.assertEqual(p['giver_pos'], [52.0, None, 88.0])
        self.assertEqual(p['goal'], [52.0, None, 180.0])
        self.assertEqual(p['guards'], [[38.0, None, 108.0], [60.0, 60.0, 120.0]])
        self.assertEqual((p['giver_size'], p['goal_width'], p['name']), (5.0, 14.0, 'RUN'))      # sizes and texts stay
        self.assertEqual(got['missions'][1]['params']['goal'], [10.0, None, 10.0])


class EntranceMarker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = newmap.load_recipe()

    def test_the_default_is_a_slim_beam_and_the_church_icon(self):
        s0, s1 = self.R.marker_sprites(None)
        self.assertEqual(s0['sprite_size'], [5.0, 10.0, 1.0])
        self.assertEqual(s1['texture'], '/Textures/Hud/ExitMap_Church.BMP')
        self.assertLess(s0['sprite_size'][0], self.R.SPRITE0['sprite_size'][0])

    def test_a_choice_of_icon_none_and_full_beam(self):
        s0, s1 = self.R.marker_sprites(dict(icon='downtown', beam='full'))
        self.assertEqual(s0['sprite_size'], self.R.SPRITE0['sprite_size'])
        self.assertEqual(s1['texture'], '/Textures/Hud/ExitMap_Downtown_South.BMP')
        s0, s1 = self.R.marker_sprites(dict(icon='none', beam='none'))
        self.assertEqual(s0['sprite_size'], [0.01] * 3)
        self.assertEqual(s1['sprite_size'], [0.01] * 3)

    def test_a_quiet_loader_draws_nothing(self):
        s0, s1 = self.R.marker_sprites(dict(icon='angel', beam='full'), quiet=True)
        self.assertEqual((s0['sprite_size'], s1['sprite_size']), ([0.01] * 3, [0.01] * 3))

    def test_the_loader_carries_the_marker(self):
        op = self.R.loader_op('X', [0, 0, 0], [0, 0, 0, 1], [12, 6, 2], 'T', None, None, marker=dict(icon='harbour', beam='none'))
        sprites = [c for c in op['child_sets'] if c['type'].startswith('generic_object_effect')]
        self.assertEqual(sprites[1]['set']['texture'], '/Textures/Hud/ExitMap_Harbour.BMP')
        self.assertEqual(sprites[0]['set']['sprite_size'], [0.01] * 3)

    def test_an_unknown_kind_is_refused_by_the_recipe_and_by_the_project(self):
        with self.assertRaises(self.R.RecipeError):
            self.R.marker_spec(dict(icon='castle'))
        with self.assertRaises(self.R.RecipeError):
            self.R.marker_spec(dict(beam='huge'))
        with self.assertRaises(ValueError):
            newmap._entry_options(dict(marker=dict(icon='castle')))
        with self.assertRaises(ValueError):
            newmap._entry_options(dict(marker='church'))
        newmap._entry_options(dict(marker=dict(icon='none')))

    def test_both_lists_name_the_same_kinds(self):
        self.assertEqual(set(newmap.MARKER_ICONS), set(self.R.MARKER_ICONS) | {'none'})
        self.assertEqual(tuple(newmap.MARKER_BEAMS), tuple(self.R.MARKER_BEAMS))


if __name__ == '__main__':
    unittest.main()
