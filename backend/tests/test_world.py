import os
import unittest

from todms import world, newmap, paths


class WorldTests(unittest.TestCase):
    def test_bounds_cover_the_shipped_maps(self):
        b = world.bounds()
        self.assertTrue(any(v['kind'] == 'map' for v in b.values()))
        self.assertTrue(all(len(v['box']) == 4 for v in b.values()))
        lay = world.atlas_default_layout(None)
        self.assertEqual(len(set(map(tuple, lay.values()))), len(lay))

    def test_every_template_is_a_valid_recipe(self):
        for t in world.TEMPLATES:
            p = world.start_project(t['id'], 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, ['Map11_RunawayTrain'])
            newmap.validate(p)
            m = p['maps'][0]
            self.assertEqual(len(m['name']), len('Map10_RunawayTrain'))
            self.assertNotEqual(m['name'].lower(), 'map11_runawaytrain')
            self.assertNotIn('atlas', m)

    def test_names_do_not_repeat(self):
        a = world.start_project('desert', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [])['maps'][0]['name']
        b = world.start_project('desert', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [a])['maps'][0]['name']
        self.assertNotEqual(a, b)

    def test_size_presets_grow(self):
        s = {x['id']: x for x in world.size_presets('desert')}
        self.assertLess(s['small']['meters'][0]['used'], s['large']['meters'][0]['used'])
        self.assertTrue(all(0 <= m['pct'] <= 100 for x in s.values() for m in x['meters']))

    def test_arrival_checks_find_a_buried_spot(self):
        m = world.start_project('desert', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [])['maps'][0]
        self.assertEqual(world.arrival_checks(m), [])
        m['entries'][0]['arrive']['pos'][1] = -40
        r = world.arrival_checks(m)
        self.assertTrue(any(x['level'] == 'error' and 'under the ground' in x['title'] for x in r))
        m['entries'][0]['arrive']['pos'] = [9000, 0, 0]
        self.assertTrue(any('outside the map ground' in x['title'] for x in world.arrival_checks(m)))

    def test_arrival_inside_the_way_back_box(self):
        m = world.start_project('desert', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [])['maps'][0]
        m['entries'][0]['back']['pos'] = list(m['entries'][0]['arrive']['pos'])
        self.assertTrue(any('way back' in x['title'] for x in world.arrival_checks(m)))

    def test_edge_profile(self):
        m = world.start_project('canyon', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [])['maps'][0]
        p = world.edge_profile(m, 'e', 8)
        self.assertEqual(len(p['points']), 9)
        self.assertEqual(len(p['heights']), 9)
        self.assertIsNone(world.edge_profile({'name': 'x'}, 'e'))

    def test_footprint_without_a_game_is_quiet(self):
        self.assertEqual(world.host_footprint(None, {'pos': [0, 0, 0]}), [])

    def test_portal_overlap(self):
        class W:                                  # a workspace with no host data
            game = True
            catalog = dict(maps=[])
        e = dict(block='a.submap', pos=[0, 0, 0], size=[12, 6, 2])
        r = world.host_footprint(W, e, [('other', 'a.submap', [1, 0, 0], [12, 6, 2], 0)])
        self.assertTrue(any(x['level'] == 'error' for x in r))

    def test_light_compare_flags_a_dark_neighbour(self):
        m = dict(look=dict(preset='clear_day', sun=dict(brightness=0.1)))
        r = world.light_compare(m, 'mainmap_map01_dea_hq_us_border.map')
        self.assertTrue(any(x['code'] == 'light' for x in r))
        self.assertEqual(world.light_compare(dict(look=dict(preset='dawn')), 'mainmap_map01_dea_hq_us_border.map'), [])

    def test_export_round_trip(self):
        import tempfile
        p = world.start_project('blank', 'small', 'map10_runawaytrain', 'Map10_RunawayTrain', None, [])
        with tempfile.TemporaryDirectory() as d:
            r = world.export_recipe(p, d)
            self.assertTrue(os.path.isfile(r['path']))
            self.assertEqual(newmap.read(r['path'])['maps'][0]['name'], p['maps'][0]['name'])


if __name__ == '__main__':
    unittest.main()
