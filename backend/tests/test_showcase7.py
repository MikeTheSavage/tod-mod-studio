"""Showcase round 7: convex collision hulls keep one face per plane (synthetic data only)."""
import itertools
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import paths
paths.setup_tools()
from todct import tools, hullclean, geom
from vendor.newmap import geomkit  # noqa: E402  (the recipe's hull_of, vendored)


def prism(k, r=5.0, h=0.3):
    ang = [2 * math.pi * i / k for i in range(k)]
    top = [(math.cos(a) * r, 0.0, math.sin(a) * r) for a in ang]
    return top + [(x, -h, z) for x, y, z in top]


def layers_at(V, F, x, z, up=True):
    """How many faces of one facing (up or down) lie over the point (x, z) of the ground plane."""
    n = 0
    for f in F:
        a, b, c = (np.array(V[i], float) for i in f[:3])
        ny = np.cross(b - a, c - a)[1]
        if (ny > 1e-9) != up or abs(ny) < 1e-9:
            continue
        def s(p, q, r):
            return (p[0] - r[0]) * (q[2] - r[2]) - (q[0] - r[0]) * (p[2] - r[2])
        p = (x, 0.0, z)
        d = (s(p, a, b), s(p, b, c), s(p, c, a))
        if not (any(v < 0 for v in d) and any(v > 0 for v in d)):
            n += 1
    return n


class OneLayer(unittest.TestCase):
    def setUp(self):
        self.mw = tools.load().mw

    def test_flat_top_is_one_layer_for_any_corner_count(self):
        for k in (3, 4, 5, 6, 8, 12, 20):
            V, F = self.mw.convex_hull(prism(k))
            self.assertEqual(layers_at(V, F, 0.1, 0.1, True), 1, 'top of the %d-gon prism' % k)
            self.assertEqual(layers_at(V, F, 0.1, 0.1, False), 1, 'bottom of the %d-gon prism' % k)

    def test_face_count_is_the_quickhull_count(self):
        for k in (4, 6, 8, 12):
            V, F = self.mw.convex_hull(prism(k))
            Q, G = geom.convex_hull(np.asarray(prism(k), float))
            self.assertEqual(len(F), len(G))
            self.assertEqual(len(F), 2 * (k - 2) + 2 * k)       # two caps and k side quads, each cut in triangles

    def test_hull_is_closed_and_convex(self):
        V, F = self.mw.convex_hull(prism(8))
        edges = {}
        for f in F:
            for i in range(3):
                e = (f[i], f[(i + 1) % 3])
                edges[e] = edges.get(e, 0) + 1
        self.assertTrue(all(edges.get((b, a)) == 1 and n == 1 for (a, b), n in edges.items()), 'every edge is shared by two faces, opposite ways')
        self.assertTrue(geom.is_convex_hull_of(np.asarray(V, float), F, np.asarray(prism(8), float), tol=1e-3))

    def test_box_and_tetra_keep_their_faces(self):
        box = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
        V, F = self.mw.convex_hull(box)
        self.assertEqual((len(V), len(F)), (8, 12))
        V, F = self.mw.convex_hull([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
        self.assertEqual((len(V), len(F)), (4, 4))

    def test_points_on_edges_and_inside_faces_drop_out(self):
        pts = prism(4) + [(0.0, 0.0, 0.0), (2.5, 0.0, 2.5)]          # a centre point and an edge midpoint of the top
        V, F = self.mw.convex_hull(pts)
        self.assertEqual(layers_at(V, F, 0.1, 0.1, True), 1)

    def test_recipe_path_goes_through_the_clean_hull(self):
        for k in (6, 12, 24):
            V, F = geomkit.hull_of(self.mw, prism(k))
            self.assertEqual(layers_at(V, F, 0.1, 0.1, True), 1, '%d points' % (2 * k))


class Overlap(unittest.TestCase):
    def test_stacked_triangles_are_found(self):
        V = [(math.cos(2 * math.pi * i / 6) * 4, 0.0, math.sin(2 * math.pi * i / 6) * 4) for i in range(6)]
        stacked = [list(t) for t in itertools.combinations(range(6), 3)]       # every corner triple, as the gift-wrap used to write them
        self.assertTrue(hullclean.overlaps(V, stacked))
        fan = [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]]
        self.assertEqual(hullclean.overlaps(V, fan), [])

    def test_clean_turns_stacked_into_a_fan(self):
        V = [(math.cos(2 * math.pi * i / 6) * 4, 0.0, math.sin(2 * math.pi * i / 6) * 4) for i in range(6)]
        stacked = [list(t) for t in itertools.combinations(range(6), 3)]       # every corner triple, as the gift-wrap used to write them
        V2, F2 = hullclean.clean(V, stacked)
        self.assertEqual(len(F2), 4)
        self.assertEqual(hullclean.overlaps(V2, F2), [])

    def test_build_check_counts_stacked_hulls_and_passes_clean_ones(self):
        mw = tools.load().mw
        hullclean.audit_reset()
        V, F = mw.convex_hull(prism(8))
        mw.hull_shape(V, F, pivot=0, surf=0, facemat=0, aux_name='ok.model')
        self.assertEqual(hullclean.audit_check()['result'], 'PASS')
        hullclean.audit_reset()
        raw = [(math.cos(2 * math.pi * i / 6) * 4, 0.0, math.sin(2 * math.pi * i / 6) * 4) for i in range(6)] + [(0.0, -1.0, 0.0)]
        stacked = [list(t) for t in itertools.combinations(range(6), 3)]       # every corner triple, as the gift-wrap used to write them
        for i in range(6):
            stacked.append([i, (i + 1) % 6, 6])
        mw.hull_shape(raw, stacked, pivot=0, surf=0, facemat=0, aux_name='bad.model')
        row = hullclean.audit_check()
        self.assertEqual(row['result'], 'WARN')
        self.assertIn('bad.model', row['evidence'])
        hullclean.audit_reset()


def slab(x0, z0, x1, z1, y, th=0.4, down=False):
    """A flat box slab the way scenekit writes one: top corners first, then the bottom ones (`down`: wound the other way, faces swapped)."""
    top = [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)]
    bot = [(a, b - th, c) for a, b, c in top]
    return dict(points=np.array(bot + top if down else top + bot, float), surface=0, tris=1)


class ThinStacks(unittest.TestCase):
    def test_duplicates_and_reversed_duplicates_collapse_to_one(self):
        from todct import scenekit as SK
        ps = [slab(0, 0, 8, 8, 10.0), slab(0, 0, 8, 8, 10.0), slab(0, 0, 8, 8, 10.02, down=True), slab(0.2, 0.2, 7.8, 7.8, 9.9)]
        kept, dropped = SK.thin_stacks(ps)
        self.assertEqual((len(kept), dropped), (1, 3))

    def test_the_topmost_layer_stays(self):
        from todct import scenekit as SK
        kept, _ = SK.thin_stacks([slab(0, 0, 6, 6, 5.0), slab(0, 0, 6, 6, 5.3)])
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(float(kept[0]['points'][:, 1].max()), 5.3)

    def test_floors_on_different_levels_both_stay(self):
        from todct import scenekit as SK
        kept, dropped = SK.thin_stacks([slab(0, 0, 8, 8, 0.0), slab(0, 0, 8, 8, 6.0)])       # a bridge over a road
        self.assertEqual((len(kept), dropped), (2, 0))

    def test_neighbours_and_partial_overlaps_stay(self):
        from todct import scenekit as SK
        kept, dropped = SK.thin_stacks([slab(0, 0, 5, 5, 1.0), slab(5, 0, 10, 5, 1.0), slab(3, 0, 14, 5, 1.0)])
        self.assertEqual(dropped, 0)

    def test_walls_are_kept_and_zero_tolerance_turns_it_off(self):
        from todct import scenekit as SK
        wall = dict(points=np.array([(0, 0, 0), (0, 3, 0), (4, 3, 0), (4, 0, 0), (0, 0, .4), (0, 3, .4), (4, 3, .4), (4, 0, .4)], float), surface=0, tris=1)
        self.assertEqual(SK.thin_stacks([wall, wall])[1], 0)
        self.assertEqual(SK.thin_stacks([slab(0, 0, 4, 4, 0.0)] * 2, tol_m=0.0)[1], 0)


class KeptScene(unittest.TestCase):
    def test_a_resend_keeps_the_projects_ground_level(self):
        from todms import sceneimport as SI
        out = SI.kept_scene(dict(scene=dict(ground_y=58.2)), dict(ground_y=23.58, kind='scene', stats=1))
        self.assertEqual((out['ground_y'], out['stats']), (58.2, 1))
        self.assertEqual(SI.kept_scene({}, dict(ground_y=23.58))['ground_y'], 23.58)


if __name__ == '__main__':
    unittest.main()
