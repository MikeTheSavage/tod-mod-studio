"""Driving presets: the per-user library keeps them, and a vehicle value that would break the car is refused."""
import os
import tempfile
import unittest


class DrivePresetStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get('TODMS_HOME')
        os.environ['TODMS_HOME'] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop('TODMS_HOME', None)
        else:
            os.environ['TODMS_HOME'] = self._old

    def test_library_keeps_driving_presets(self):
        from todms import userlib
        self.assertEqual(userlib.load()['driving'], {})
        p = {'name': 'Mine', 'type': {'slide_factor': {'mul': 2}}, 'car': {'turn_rate': {'set': 0.2}}}
        userlib.save_key('driving', {'Mine': p})
        self.assertEqual(userlib.load()['driving'], {'Mine': p})
        with self.assertRaises(ValueError):
            userlib.save_key('driving', [p])           # wrong shape is refused
        userlib.save_key('prefabs', [])
        self.assertIn('Mine', userlib.load()['driving'], 'other keys do not touch it')


class VehicleValueGuard(unittest.TestCase):
    def test_mass_and_non_finite_values_are_refused(self):
        from todms import dataed
        for bad in ({'type.Sedan.Mass': 0}, {'type.Sedan.Mass': -5}, {'type.Sedan.slide_factor': float('nan')},
                    {'car.turn_rate': float('inf')}):
            with self.assertRaises(ValueError):
                dataed.vehicles_ops(None, bad)

    def test_a_driving_value_becomes_a_set_op_on_the_main_block(self):
        from todms import dataed
        ops = dataed.vehicles_ops(None, {'type.Sedan.slide_factor': 2.5, 'car.turn_rate': 0.2})
        flat = [o for v in ops.values() for o in v]
        self.assertEqual({(o['prop'], o['value']) for o in flat}, {('slide_factor', 2.5), ('turn_rate', 0.2)})


class DrivingPresetFile(unittest.TestCase):
    """backend/data/driving_presets.json is the one source of the built-in presets (the editor and other tools read it)."""

    def setUp(self):
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))
        spec = importlib.util.spec_from_file_location('pdp', os.path.join(root, 'scripts', 'print_driving_presets.py'))
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.d = self.m.load()

    def test_shape_and_ranges(self):
        d = self.d
        self.assertEqual([p['id'] for p in d['presets']], ['drift', 'arcade', 'heavy', 'vanilla'])
        for p in d['presets']:
            if p.get('restore'):
                continue
            for g in ('type', 'car'):
                for k, spec in (p.get(g) or {}).items():
                    self.assertIn(k, d['fields'][g], p['id'] + ' ' + k)
                    self.assertEqual(len([x for x in spec if x in ('mul', 'add', 'set')]), 1)
        for g in d['fields'].values():
            for k, f in g.items():
                self.assertLess(f['lo'], f['hi'], k)
                self.assertTrue(f['tip'])
        for bad in ('spring_k', 'spring_damping', 'stiffness'):         # no body roll
            self.assertNotIn(bad, d['fields']['type'])
            self.assertNotIn(bad, d['fields']['car'])

    def test_plan_matches_the_rules(self):
        shipped = {'type.Sedan.cornering_stiffness': 1.2, 'type.Sedan.slide_factor': 1.0, 'type.BurritoCart.slide_factor': 0.0,
                   'type.Sedan.lateral_slide_speed': 17.0, 'car.turn_rate': 0.174}
        drift = next(p for p in self.d['presets'] if p['id'] == 'drift')
        out = self.m.plan_all(self.d, drift, shipped)
        self.assertEqual(out['type.Sedan.cornering_stiffness'], 1.5)
        self.assertEqual(out['type.Sedan.slide_factor'], 3.0)
        self.assertNotIn('type.BurritoCart.slide_factor', out)          # zero stays zero
        self.assertEqual(out['car.turn_rate'], 0.25)


if __name__ == '__main__':
    unittest.main()
