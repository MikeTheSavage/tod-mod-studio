"""New-map collision shorthand (box / wedge) builds valid hull sets."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

from todct import collision as CO  # noqa: E402
from todms import newmap  # noqa: E402


class ShorthandShapes(unittest.TestCase):
    def test_box_and_wedge(self):
        cache = os.environ.get('TODMS_CACHE', os.path.join(os.environ.get('TODMS_PROOF', '/no-proof-copy'), 'cache'))
        if not os.path.exists(os.path.join(cache, 'tables', 'global_properties.json')):
            self.skipTest('needs a prepared cache (property tables from a game)')
        os.environ['TODMS_CACHE'] = cache
        M = newmap.load_recipe()
        for shape in ('box', 'wedge'):
            s = {'id': 'c1', 'shape': shape, 'min': [0, 0, 0], 'max': [4, 2, 6], 'rise': '+z'}
            cs = M.shorthand_to_set(s, 'map11_test')
            self.assertEqual(len(cs['pieces']), 1, shape)
            self.assertEqual(CO.validate_set(cs), [], shape)


if __name__ == '__main__':
    unittest.main()
