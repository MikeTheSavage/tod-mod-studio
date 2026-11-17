"""Showcase round 10: a district gets its own place in the world and everything placed on it follows (synthetic data only)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import sceneimport as SI, missions_tpl as MT, newmap, world


def a_map(place=None):
    sc = dict(ground_y=58.2, params=dict(scale=2.0, **({'place': place} if place else {})), water=dict(level=54.88),
              streets=[dict(pos=[10.0, 20.0, 30.0], yaw=90.0)],
              plan=dict(file='plan.png', x0=-320.0, z1=315.0, cell=1.0, w=640, h=630,
                        steps=dict(limit=1.5, count=1, highest=4.0, places=[[-9.0, 243.9, 4.0]])))
    return dict(name='Map11_CityTest', arrival=dict(pos=[52.0, 59.2, 60.0], orient=[0, 0, 0, 1], floor='none'),
                **{'return': dict(pos=[-51.0, 67.0, -284.0], size=[6, 6, 2])}, teleports=[dict(name='SPOT_1', pos=[1.0, 2.0, 3.0])],
                entries=[dict(id='e1', block='host.submap', pos=[-237.0, 2.5, -43.66], size=[12, 6, 2], arrive=dict(pos=[52.0, 59.2, 60.0], yaw=0.0),
                              back=dict(pos=[52.0, 59.6, 16.0], size=[12, 6, 2], spot=dict(pos=[-216.0, 2.5, -60.0], yaw=270.0))),
                         dict(id='et', block='host.submap', pos=[-237.0, -6.0, -205.0], size=[16, 8, 6], vehicle=True,
                              arrive=dict(pos=[52.0, 59.2, 60.0], yaw=0.0))],
                edges=[dict(id='rim', kind='invisible', rect=[-318.0, -313.6, 318.0, 313.6], height=216.0, kill=dict(below=-30.0, respawn=[52.0, 60.0]))],
                water=[dict(id='sea1', rect=[225.0, -114.6, 323.0, 18.4], level=54.88, reset=[52.0, 60.0])],
                look=dict(preset='city_day', fog=dict(near=180.0, far=760.0)), scene=sc)


class MoveMap(unittest.TestCase):
    def test_the_places_of_the_district_move_together(self):
        m = SI.move_map(a_map(), [3900.0, 0.0, -200.0])
        self.assertEqual(m['arrival']['pos'], [3952.0, 59.2, -140.0])
        self.assertEqual(m['return']['pos'], [3849.0, 67.0, -484.0])
        self.assertEqual(m['teleports'][0]['pos'], [3901.0, 2.0, -197.0])
        for e in m['entries']:
            self.assertEqual(e['arrive']['pos'], [3952.0, 59.2, -140.0])
        self.assertEqual(m['entries'][0]['back']['pos'], [3952.0, 59.6, -184.0])
        self.assertEqual(m['edges'][0]['rect'], [3582.0, -513.6, 4218.0, 113.6])
        self.assertEqual(m['edges'][0]['kill']['respawn'], [3952.0, -140.0])
        self.assertEqual(m['water'][0]['rect'], [4125.0, -314.6, 4223.0, -181.6])
        self.assertEqual(m['water'][0]['reset'], [3952.0, -140.0])
        self.assertEqual(m['scene']['streets'][0]['pos'], [3910.0, 20.0, -170.0])
        self.assertEqual((m['scene']['plan']['x0'], m['scene']['plan']['z1']), (3580.0, 115.0))
        self.assertEqual(m['scene']['plan']['steps']['places'], [[3891.0, 43.9, 4.0]])

    def test_what_lies_in_the_host_map_stays(self):
        m = SI.move_map(a_map(), [3900.0, 0.0, -200.0])
        for e in m['entries']:
            self.assertEqual(e['pos'][0], -237.0)
        self.assertEqual(m['entries'][0]['back']['spot'], dict(pos=[-216.0, 2.5, -60.0], yaw=270.0))
        self.assertEqual(m['entries'][0]['size'], [12, 6, 2])
        self.assertEqual(m['look']['fog'], dict(near=180.0, far=760.0))

    def test_a_height_moves_the_floor_the_sea_and_the_kill_plane(self):
        m = SI.move_map(a_map(), [0.0, 10.0, 0.0])
        self.assertEqual(m['scene']['ground_y'], 68.2)
        self.assertAlmostEqual(m['water'][0]['level'], 64.88)
        self.assertEqual(m['edges'][0]['kill']['below'], -20.0)
        self.assertEqual(m['arrival']['pos'][1], 69.2)

    def test_the_origin_is_the_identity_and_the_original_stays(self):
        m = a_map()
        self.assertEqual(SI.move_map(m, [0, 0, 0]), m)
        SI.move_map(m, [5, 5, 5])
        self.assertEqual(m, a_map())

    def test_there_and_back_again(self):
        m = SI.move_map(SI.move_map(a_map(), [3900.0, 0.0, -200.0]), [-3900.0, 0.0, 200.0])
        self.assertEqual(m['entries'][0]['back']['pos'], [52.0, 59.6, 16.0])
        self.assertEqual(m['scene']['plan']['x0'], -320.0)

    def test_the_place_a_map_was_sent_with(self):
        self.assertEqual(SI.place_of(a_map()), [0.0, 0.0, 0.0])
        self.assertEqual(SI.place_of(a_map([3900, 0, -200])), [3900.0, 0.0, -200.0])

    def test_scale_and_place_together_scale_about_the_middle_of_the_scene(self):
        m = SI.move_map(a_map(), [3900.0, 0.0, -200.0])
        m = SI.move_map(m, [-3900.0, 0.0, 200.0])
        m = SI.rescale_map(m, 2.0)
        m = SI.move_map(m, [100.0, 0.0, 100.0])
        self.assertEqual(m['arrival']['pos'], [204.0, 117.4, 220.0])


class MissionsFollowThePlace(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.t.name, 'home'), TODMS_CACHE=os.path.join(self.t.name, 'cache'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def test_hosts_and_points_move_with_the_place(self):
        proj = dict(name='City', hosts=[dict(id='city', kind='new_map', newmap_id='abc', map_index=0, area=[-300.0, -300.0, 300.0, 300.0], ground_y=59.0),
                                        dict(id='dt', kind='existing', block='b.submap', area=[0, 0, 50, 50], ground_y=2.5)],
                    missions=[dict(id='run', type='ghost', host='city', index=79,
                                   params=dict(giver_pos=[52.0, None, 88.0], giver_size=5.0, goal=[52.0, None, 180.0], goal_width=14.0,
                                               guards=[[38.0, None, 108.0], [60.0, 60.0, 120.0]], name='RUN')),
                              dict(id='other', type='ghost', host='dt', index='auto', params=dict(goal=[10.0, None, 10.0]))])
        MT.save_project(proj, 'p1')
        self.assertEqual(MT.rescale_hosts('abc', 1.0, [0, 0, 0], [3900.0, 0.0, -200.0]), 1)
        got = MT.get_project('p1')['project']
        self.assertEqual(got['hosts'][0]['area'], [3600.0, -500.0, 4200.0, 100.0])
        self.assertEqual(got['hosts'][0]['ground_y'], 59.0)
        self.assertEqual(got['hosts'][1]['area'], [0, 0, 50, 50])
        p = got['missions'][0]['params']
        self.assertEqual(p['giver_pos'], [3952.0, None, -112.0])
        self.assertEqual(p['goal'], [3952.0, None, -20.0])
        self.assertEqual(p['guards'], [[3938.0, None, -92.0], [3960.0, 60.0, -80.0]])
        self.assertEqual((p['giver_size'], p['goal_width'], p['name']), (5.0, 14.0, 'RUN'))
        self.assertEqual(got['missions'][1]['params']['goal'], [10.0, None, 10.0])


class AreaCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = newmap.load_recipe()

    def run_check(self, area):
        out = []
        self.R.check_scene_area(dict(name='Map11_X', mapgen=dict(scene_area=area)), out)
        return out

    def test_a_district_over_downtown_warns_and_names_it(self):
        out = self.run_check([-320.0, -310.0, 320.0, 320.0])
        self.assertEqual(out[0]['result'], 'WARN')
        self.assertIn('map02_lostoros_downtown', out[0]['evidence'])

    def test_free_ground_passes(self):
        out = self.run_check([3580.0, -510.0, 4220.0, 120.0])
        self.assertEqual(out[0]['result'], 'PASS')

    def test_no_scene_no_row(self):
        out = []
        self.R.check_scene_area(dict(name='Map11_X', mapgen={}), out)
        self.assertEqual(out, [])


class WorldViewWarns(unittest.TestCase):
    def test_a_district_on_downtown_is_flagged_in_the_world_checks(self):
        res = world.analyse(None, dict(maps=[a_map()]))
        titles = [i['title'] for i in res['items']]
        self.assertTrue(any('footprint lies over' in t and 'map02_lostoros_downtown' in t for t in titles), titles)

    def test_a_district_on_free_ground_is_clean(self):
        m = SI.move_map(a_map(), [3900.0, 0.0, 0.0])
        res = world.analyse(None, dict(maps=[m]))
        self.assertFalse([i for i in res['items'] if 'footprint lies over' in i['title']])

    def test_the_area_of_a_map_without_a_plan_is_unknown(self):
        self.assertIsNone(world.scene_area(dict(name='x')))


if __name__ == '__main__':
    unittest.main()
