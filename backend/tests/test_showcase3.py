"""Showcase round 3: water where a scene has no floor, the city day look (synthetic data only)."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import sceneimport as SI
from todms.mapgen import look


def floor_with_hole(size=100.0, hole=(30.0, 30.0, 80.0, 80.0), step=10.0, y=21.0):
    """Flat floor (below the water level) of square cells (two triangles each) with a rectangular hole."""
    P, T = [], []
    for i in range(int(size / step)):
        for j in range(int(size / step)):
            x, z = i * step, j * step
            cx, cz = x + step / 2, z + step / 2
            if hole[0] <= cx <= hole[2] and hole[1] <= cz <= hole[3]:
                continue
            k = len(P)
            P += [(x, y, z), (x + step, y, z), (x + step, y, z + step), (x, y, z + step)]
            T += [(k, k + 2, k + 1), (k, k + 3, k + 2)]
    return SimpleNamespace(P=np.array(P, np.float32), T=np.array(T, np.int64))


class VoidWater(unittest.TestCase):
    def test_a_hole_in_the_floor_and_the_rim_get_water_and_the_floor_does_not(self):
        bodies = SI.void_water(floor_with_hole(), 25.0, reach=60.0, cell=4.0, min_area=800.0)
        self.assertTrue(bodies)
        inner = [b for b in bodies if b['rule'] == 'reset']
        outer = [b for b in bodies if b['rule'] == 'none']
        self.assertTrue(inner and outer)
        self.assertTrue(all(b['level'] == 25.0 for b in bodies))
        pond = max(inner, key=lambda b: (b['rect'][2] - b['rect'][0]) * (b['rect'][3] - b['rect'][1]))
        x0, z0, x1, z1 = pond['rect']
        self.assertGreaterEqual(x0, 28.0)
        self.assertLessEqual(x1, 82.0)
        self.assertGreaterEqual(z0, 28.0)
        self.assertLessEqual(z1, 82.0)
        for b in bodies:                                   # no water over floor cells
            bx0, bz0, bx1, bz1 = b['rect']
            ox = min(bx1, 30.0) - max(bx0, 0.0)
            oz = min(bz1, 100.0) - max(bz0, 0.0)
            if ox > 0 and oz > 0:
                self.assertTrue(b['rect'][0] >= 28.0 and b['rect'][2] <= 82.0 and b['rect'][1] >= 28.0 and b['rect'][3] <= 82.0, b)

    def test_a_scene_with_a_full_floor_has_water_only_outside(self):
        bodies = SI.void_water(floor_with_hole(hole=(-1, -1, -1, -1)), 25.0, reach=60.0, cell=4.0, min_area=800.0)
        self.assertTrue(bodies)
        self.assertTrue(all(b['rule'] == 'none' for b in bodies))


    def test_a_street_high_above_the_water_does_not_keep_it_away(self):
        bodies = SI.void_water(floor_with_hole(y=30.0), 25.0, reach=60.0, cell=4.0, min_area=800.0)
        self.assertTrue(any(b['rect'][0] <= 10.0 <= b['rect'][2] and b['rect'][1] <= 10.0 <= b['rect'][3] for b in bodies))        # water runs under the street
        self.assertTrue(all(b['rule'] == 'none' for b in bodies if b['rect'][0] <= 10.0 <= b['rect'][2] and b['rect'][1] <= 10.0 <= b['rect'][3]))    # but a street is no place for a reset


class CityDay(unittest.TestCase):
    def test_the_city_day_look_has_the_lights_of_downtown_and_a_clear_sky(self):
        p = look.presets()['city_day']['look']
        self.assertEqual(p['ambient']['color'], [0.3412, 0.4275, 0.5765])
        self.assertEqual(p['sun']['brightness'], 2.0)
        self.assertEqual(p['sky'], look.presets()['clear_day']['look']['sky'])
        r = look.resolve(dict(preset='city_day'))
        self.assertEqual(r['ambient']['brightness'], 0.6)


if __name__ == '__main__':
    unittest.main()
