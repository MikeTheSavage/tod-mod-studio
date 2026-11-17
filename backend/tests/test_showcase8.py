"""Showcase round 8: a car needs the vehicle database in the map block (synthetic data only)."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import paths
paths.setup_tools()
try:
    from todms.newmap_recipe import make_new_map as MM  # noqa: E402  (needs the tables a prepared cache holds)
except FileNotFoundError:
    MM = None


@unittest.skipIf(MM is None, 'needs a prepared cache (tables)')
class VehicleDataCheck(unittest.TestCase):
    def run_check(self, present, entries):
        MM.GEO_VEHICLE_DATA['Map99_Test'] = present
        checks = []
        MM.check_vehicle_data(dict(name='Map99_Test', new_geometry={'folder': 'x'}, entries=entries), checks)
        return checks

    def test_a_map_that_keeps_the_database_passes(self):
        self.assertEqual(self.run_check(True, [dict(id='e1', vehicle=True)])[0]['result'], 'PASS')

    def test_a_vehicle_entrance_into_a_map_without_it_fails(self):
        c = self.run_check(False, [dict(id='e1', vehicle=True)])[0]
        self.assertEqual(c['result'], 'FAIL')
        self.assertIn('e1', c['evidence'])

    def test_a_map_without_it_and_no_vehicle_entrance_warns(self):
        self.assertEqual(self.run_check(False, [dict(id='e1')])[0]['result'], 'WARN')

    def test_a_map_without_geometry_is_not_judged(self):
        checks = []
        MM.check_vehicle_data(dict(name='Map98_Plain', entries=[]), checks)
        self.assertEqual(checks, [])


@unittest.skipIf(MM is None, 'needs a prepared cache (tables)')
class BuildKeepsTheDatabase(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.real = (MM.NG.build, MM.geo_K, MM.ft, MM._has_vehicle_data)

        def fake_build(geo_in, src, name, out, K, T):
            self.seen.append(list(MM.NG.DROP_FOLDERS))
            return dict(map_file='x.map', report={})
        MM.NG.build = fake_build
        MM.geo_K = lambda: None
        MM.ft = SimpleNamespace(types=lambda: None)
        MM._has_vehicle_data = lambda path: True
        self.before = list(MM.NG.DROP_FOLDERS)

    def tearDown(self):
        MM.NG.build, MM.geo_K, MM.ft, MM._has_vehicle_data = self.real

    def test_the_default_keeps_the_vehicle_folder_out_of_the_drop_list(self):
        geo = MM.build_geometry(dict(new_geometry={'folder': 'x'}), {}, 'Map99_Test', 'out')
        self.assertNotIn(MM.VEHICLE_DATA_FOLDER, self.seen[0])
        self.assertIn('MM120_RunawayTrainFolder', self.seen[0])          # the rest of the train level is still dropped
        self.assertTrue(geo['report']['vehicle_data'])

    def test_vehicle_data_false_drops_it_like_before(self):
        MM.build_geometry(dict(new_geometry={'folder': 'x', 'vehicle_data': False}), {}, 'Map99_Test', 'out')
        self.assertIn(MM.VEHICLE_DATA_FOLDER, self.seen[0])

    def test_the_drop_list_is_restored_afterwards(self):
        MM.build_geometry(dict(new_geometry={'folder': 'x'}), {}, 'Map99_Test', 'out')
        self.assertEqual(MM.NG.DROP_FOLDERS, self.before)

    def test_the_drop_list_is_restored_when_the_build_fails(self):
        def boom(*a):
            raise RuntimeError('no')
        MM.NG.build = boom
        with self.assertRaises(RuntimeError):
            MM.build_geometry(dict(new_geometry={'folder': 'x'}), {}, 'Map99_Test', 'out')
        self.assertEqual(MM.NG.DROP_FOLDERS, self.before)


if __name__ == '__main__':
    unittest.main()
