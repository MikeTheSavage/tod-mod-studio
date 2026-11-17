"""Baked lighting of new geometry: ray casting, the bake, the lighting record writer, the calibration against the shipped maps, the alpha
flags of the model writers.

The game tests use a proof copy of the game in env TODMS_PROOF (skipped when unset); they read blocks and write nothing outside a temp folder.
"""
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
HAVE_GAME = os.path.isdir(os.path.join(PROOF, 'game'))

from todms import paths, bake, raycast, lightrec            # noqa: E402

paths.ensure_cpu_guard()


def brute(tris, o, d, tmax, tmin=1e-4):
    out = np.zeros(len(o), bool)
    tmax = np.broadcast_to(np.asarray(tmax, float), (len(o),))
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    for i in range(len(o)):
        p = np.cross(d[i], e2)
        det = (e1 * p).sum(1)
        ok = np.abs(det) > 1e-12
        idet = 1 / np.where(ok, det, 1)
        tv = o[i] - v0
        u = (tv * p).sum(1) * idet
        q = np.cross(tv, e1)
        v = (d[i] * q).sum(1) * idet
        tt = (e2 * q).sum(1) * idet
        out[i] = (ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (tt > tmin) & (tt < tmax[i])).any()
    return out


def rb(path):
    with open(path, 'rb') as f:
        return f.read()


def quad(a, b, c, d):
    return [(a, b, c), (a, c, d)]


def ground_and_wall():
    """A 40 x 40 m ground at y 0 and a 6 m tall wall at x = 5 (z -10..10), as triangles."""
    g = quad((-20, 0, -20), (-20, 0, 20), (20, 0, 20), (20, 0, -20))
    w = quad((5, 0, -10), (5, 6, -10), (5, 6, 10), (5, 0, 10))
    return np.array(g + w, np.float64)


class TestRayCast(unittest.TestCase):
    def test_agrees_with_brute_force(self):
        rng = np.random.default_rng(4)
        c = rng.uniform(-30, 30, (3000, 1, 3))
        tris = c + rng.normal(0, 1.2, (3000, 3, 3))
        tree = raycast.Tree(tris, split=0)
        m = 400
        o = rng.uniform(-30, 30, (m, 3))
        d = rng.normal(size=(m, 3))
        d /= np.linalg.norm(d, axis=1)[:, None]
        tmax = rng.uniform(1, 25, m)
        self.assertTrue((tree.occluded(o, d, tmax) == brute(tris, o, d, tmax)).all())

    def test_long_triangles_are_cut_and_still_agree(self):
        tris = np.array([[(0, 0, 0), (60, 30, 0), (0, 30, 60)], [(5, 5, 5), (6, 5, 5), (5, 6, 5)]], np.float64)
        cut = raycast.split_long(tris, 6.0)
        self.assertGreater(len(cut), len(tris))
        area = lambda t: 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()
        self.assertAlmostEqual(area(cut), area(tris), places=6)
        rng = np.random.default_rng(5)
        o = rng.uniform(-5, 65, (300, 3))
        d = rng.normal(size=(300, 3))
        d /= np.linalg.norm(d, axis=1)[:, None]
        self.assertTrue((raycast.Tree(tris).occluded(o, d, 100.0) == brute(tris, o, d, 100.0)).all())

    def test_padding_leaves_never_pass(self):
        # 5 triangles: the tree is padded to 2 leaves of 4; a ray far from them must touch no node at all
        tris = np.array(quad((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)) + quad((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)) + [((0, 0, 2), (1, 0, 2), (0, 1, 2))], np.float64)
        tree = raycast.Tree(tris, split=0)
        far = tree.occluded(np.array([[50.0, 50, 50]] * 8), np.tile([0.0, 1.0, 0.0], (8, 1)), 1000.0)
        self.assertFalse(far.any())
        self.assertTrue(tree.occluded([[0.5, 0.5, -1.0]], [[0.0, 0.0, 1.0]], 10.0).all())

    def test_the_open_ground_test_never_clears_a_blocked_ray(self):
        rng = np.random.default_rng(8)
        tris = ground_and_wall()
        tree = raycast.Tree(np.concatenate([tris, rng.uniform(-15, 15, (60, 1, 3)) + rng.normal(0, 1.0, (60, 3, 3))]), split=0)
        o = np.concatenate([rng.uniform(-18, 18, (600, 1)), rng.uniform(0.03, 4.0, (600, 1)), rng.uniform(-18, 18, (600, 1))], 1)
        for d in ([0.5, 0.3, 0.2], [-0.8, 0.2, 0.1], [0.1, 0.9, 0.3]):
            d = np.asarray(d) / np.linalg.norm(d)
            clear = tree.clear_sun(o, d, 60.0, 0.5)
            blocked = tree.occluded(o, np.tile(d, (600, 1)), 60.0, tmin=0.5)
            self.assertFalse((clear & blocked).any())
            self.assertGreater(clear.sum(), 0)

    def test_empty_scene_and_no_rays(self):
        self.assertFalse(raycast.Tree(np.zeros((0, 3, 3))).occluded([[0, 0, 0]], [[0, 1, 0]], 10.0).any())
        self.assertEqual(len(raycast.Tree(ground_and_wall()).occluded(np.zeros((0, 3)), np.zeros((0, 3)), 1.0)), 0)


LIGHTS = dict(sun_dir=np.array([-0.6, -0.8, 0.0]), sun=np.array([1.0, 1.0, 1.0]), ambient=np.array([0.25, 0.25, 0.30]))


class TestBake(unittest.TestCase):
    def setUp(self):
        self.tree = raycast.Tree(ground_and_wall())

    def bake(self, P, N, q='normal'):
        P, N = np.asarray(P, float), np.asarray(N, float)
        col, st = bake.bake_vertices(P, N, LIGHTS, self.tree, q)
        return col

    def test_sun_shadow_and_ambient(self):
        up = [0, 1, 0]
        # the sun travels towards -x and down: a wall at x = 5 shades the ground behind it (x > 5 is lit from the side where the sun is?)
        # sun_dir (-0.6, -0.8, 0): light comes from +x. The wall at x = 5 throws its shadow towards -x: x = 5 - 0.75 * 6 = 0.5 .. 5.
        lit = self.bake([[12, 0, 0], [-10, 0, 0]], [up, up])
        shade = self.bake([[3.0, 0, 0]], [up])
        sun = LIGHTS['sun'] * 0.8
        np.testing.assert_allclose(lit[0], LIGHTS['ambient'] + sun, atol=0.06)          # open ground: ambient + sun * N.L (a little sky is the wall)
        np.testing.assert_allclose(lit[1], LIGHTS['ambient'] + sun, atol=0.06)
        self.assertLess(shade[0].max(), lit[0].max() - 0.5)                                  # in the wall's shadow: ambient only (a little occluded)
        self.assertLess(shade[0, 0], 0.30)

    def test_facing_away_from_the_sun_gets_ambient_only(self):
        c = self.bake([[-10, 3, 0]], [[-1, 0, 0]])
        self.assertLess(c[0, 0], 0.26)

    def test_sky_occlusion_darkens_a_corner(self):
        open_ground = self.bake([[-10, 0, 0]], [[0, 1, 0]])
        corner = self.bake([[4.7, 0, 0]], [[0, 1, 0]])                 # at the foot of the wall, in its shadow
        self.assertLess(corner[0, 2], open_ground[0, 2])

    def test_deterministic_and_order_free(self):
        rng = np.random.default_rng(2)
        P = np.stack([rng.uniform(-18, 18, 200), np.zeros(200), rng.uniform(-18, 18, 200)], 1)
        N = np.tile([0.0, 1.0, 0.0], (200, 1))
        a = self.bake(P, N)
        b = self.bake(P, N)
        self.assertTrue((a == b).all())
        perm = rng.permutation(200)
        c = self.bake(P[perm], N[perm])
        self.assertTrue((c == a[perm]).all())                           # a vertex's colour does not depend on the others

    def test_equal_positions_get_equal_colours(self):
        a = self.bake([[1.0, 0, 2.0], [1.0, 0, 2.0]], [[0, 1, 0], [0, 1, 0]], 'high')
        self.assertTrue((a[0] == a[1]).all())

    def test_d3dcolor_round_trip(self):
        c = np.array([[0.0, 0.5, 1.0], [0.2, 0.4, 0.6]])
        d = bake.to_d3dcolor(c)
        self.assertEqual(int(d[0]), 0xFF0080FF)
        np.testing.assert_allclose(bake.from_d3dcolor(d), c, atol=1.0 / 255)

    def test_strip_to_list_turns_every_second_triangle(self):
        self.assertEqual(bake.strip_to_list([0, 1, 2, 3]).reshape(-1, 3).tolist(), [[0, 1, 2], [2, 1, 3]])
        self.assertEqual(bake.strip_to_list([0, 1, 2, 2, 3, 3]).reshape(-1, 3).tolist(), [[0, 1, 2]])        # degenerate triangles dropped
        self.assertEqual(len(bake.strip_to_list([0, 1])), 0)

    def test_sun_convention_is_the_inverse_of_the_stored_orient(self):
        from todms.mapgen import look
        for az, el in ((0, 45), (90, 30), (200, 60), (135, 40)):
            d = bake.sun_direction(look.aim_to_orient(az, el))
            want = np.array([math.sin(math.radians(az)) * math.cos(math.radians(el)), -math.sin(math.radians(el)),
                             math.cos(math.radians(az)) * math.cos(math.radians(el))])
            np.testing.assert_allclose(d, want, atol=1e-4)
        # Map03's own sun: it travels towards -x and slightly +z, 29 degrees down (walls facing +x are the lit ones in the shipped bake)
        d = bake.sun_direction([-0.3523, -0.4845, 0.7341, -0.3193])
        np.testing.assert_allclose(d, [-0.827, -0.487, 0.282], atol=2e-3)


def mesh_desc(n_vertices, seed, indices=None):
    rng = np.random.default_rng(seed)
    idx = np.arange(max(3, n_vertices - n_vertices % 3), dtype=np.uint16) % n_vertices if indices is None else np.asarray(indices, np.uint16)
    return dict(colours=bake.to_d3dcolor(rng.uniform(0, 1, (n_vertices, 3))), indices=idx)


class TestRecord(unittest.TestCase):
    def build(self, paths_n=5):
        inst = []
        for i in range(paths_n):
            ms = [dict(pivot=0, mesh=j, **mesh_desc(4 + 3 * j + i, 10 * i + j)) for j in range(1 + i % 3)]
            inst.append(dict(path=((1000 + 7 * (paths_n - i), -5 * i - 1),), meshes=ms))
        return inst, lightrec.build('/data/Maps/Test/TEST.lighting', inst)

    def parse(self, info, payload):
        lightrec.HL()
        import tod_hd_lighting as HL
        rec = HL._Rec(info, 0, len(info), len(payload), 0, 'x')
        return HL, rec

    def test_strict_reader_accepts_what_build_writes(self):
        inst, (info, payload, summ) = self.build(6)
        HL, rec = self.parse(info, payload)
        self.assertFalse(rec.problems)
        self.assertTrue(all(rec.checks.values()), rec.checks)
        self.assertEqual(summ['instances'], 6)
        self.assertEqual(len(rec.entries), summ['entries'])
        self.assertEqual(len(info) % 16, 0)

    def test_engine_lookups_find_every_mesh(self):
        inst, (info, payload, summ) = self.build(7)
        HL, rec = self.parse(info, payload)
        uid_pos = {tuple(p): k for k, p in enumerate(rec.uid_keys)}
        for i in inst:
            ik = rec.uid_values[uid_pos[tuple(i['path'])]]
            for m in i['meshes']:
                pos = HL.engine_search([tuple(k) for k in rec.keys], HL.build_key(ik, m['pivot'], m['mesh'], len(m['colours']), len(m['indices']), False))
                self.assertIsNotNone(pos)
                e = rec.entries[rec.values[pos]]
                self.assertEqual(e['buffer']['count'], len(m['colours']))
                self.assertEqual(e['buffer']['index_count'], len(m['indices']))
                cols = np.frombuffer(payload, '<u4', e['buffer']['count'], e['buffer']['data_offset'])
                self.assertTrue((cols == m['colours']).all())
                cp = np.frombuffer(bytes(info[e['buffer']['index_copy_offset']:e['buffer']['index_copy_offset'] + 2 * len(m['indices'])]), '<u2')
                self.assertTrue((cp == m['indices']).all())

    def test_a_wrong_count_is_not_found(self):
        inst, (info, payload, summ) = self.build(3)
        HL, rec = self.parse(info, payload)
        m = inst[0]['meshes'][0]
        ik = rec.uid_values[[tuple(p) for p in rec.uid_keys].index(tuple(inst[0]['path']))]
        pos = HL.engine_search([tuple(k) for k in rec.keys], HL.build_key(ik, 0, 0, len(m['colours']) + 1, len(m['indices']), False))
        self.assertIsNone(pos)

    def test_small_meshes_keep_four_colour_slots(self):
        info, payload, summ = lightrec.build('/data/Maps/T.lighting', [dict(path=((1, 2),), meshes=[dict(pivot=0, mesh=0, **mesh_desc(3, 1))])])
        self.assertEqual(len(payload), 16)
        HL, rec = self.parse(info, payload)
        self.assertEqual(rec.entries[0]['buffer']['count'], 3)

    def test_refusals(self):
        with self.assertRaises(lightrec.RecordError):
            lightrec.build('x', [])
        d = dict(path=((1, 1),), meshes=[dict(pivot=0, mesh=0, **mesh_desc(5, 1))])
        with self.assertRaises(lightrec.RecordError):
            lightrec.build('x', [d, dict(d)])                           # one path twice
        d2 = dict(path=((1, 1),), meshes=[dict(pivot=0, mesh=0, **mesh_desc(5, 1)), dict(pivot=0, mesh=0, **mesh_desc(5, 2))])
        with self.assertRaises(lightrec.RecordError):
            lightrec.build('x', [d2])                                   # one mesh twice

    def mixed(self):
        """Instances that hold per-vertex entries and single-colour entries side by side (a shipped record has both)."""
        inst = []
        for i in range(6):
            ms = [dict(pivot=0, mesh=0, **mesh_desc(5 + i, 100 + i)),
                  dict(pivot=0, mesh=1, single=int(bake.to_d3dcolor(np.array([[0.2 + 0.1 * i, 0.5, 0.7]]))[0]), vcount=8 + i, icount=12 + 3 * i),
                  dict(pivot=1, mesh=0, single=0xFF102030 + i, vcount=4, icount=6)]
            if i % 2:
                ms = ms[1:]
            inst.append(dict(path=((900 + 3 * (6 - i), -7 * i - 1),), meshes=ms))
        return inst, lightrec.build('/data/Maps/Test/MIXED.lighting', inst)

    def test_single_colour_entries_are_written_and_read_back(self):
        inst, (info, payload, summ) = self.mixed()
        HL, rec = self.parse(info, payload)
        self.assertFalse(rec.problems)
        self.assertTrue(all(rec.checks.values()), rec.checks)
        n_single = sum(1 for i in inst for m in i['meshes'] if m.get('single') is not None)
        self.assertEqual(summ['single_entries'], n_single)
        self.assertEqual(len(rec.entries), sum(len(i['meshes']) for i in inst))
        self.assertEqual(len(info) % 16, 0)
        # the payload holds the per-vertex colours only
        self.assertEqual(len(payload), sum(4 * max(4, len(m['colours'])) for i in inst for m in i['meshes'] if m.get('single') is None))
        uid_pos = {tuple(p): k for k, p in enumerate(rec.uid_keys)}
        for i in inst:
            ik = rec.uid_values[uid_pos[tuple(i['path'])]]
            for m in i['meshes']:
                if m.get('single') is None:
                    continue
                pos = HL.engine_search([tuple(k) for k in rec.keys], HL.build_key(ik, m['pivot'], m['mesh'], m['vcount'], m['icount'], True))
                self.assertIsNotNone(pos)
                e = rec.entries[rec.values[pos]]
                self.assertIsNone(e['buffer'])
                self.assertEqual(e['colour'], m['single'])
                # the same counts without the single flag are a different key
                self.assertIsNone(HL.engine_search([tuple(k) for k in rec.keys], HL.build_key(ik, m['pivot'], m['mesh'], m['vcount'], m['icount'], False)))

    def test_describe_hands_single_entries_back_to_build(self):
        inst, (info, payload, summ) = self.mixed()
        HL, rec = self.parse(info, payload)

        class Blk:
            payloads = [payload]
        rec.index = 0
        again = lightrec.describe(rec, Blk)
        info2, payload2, summ2 = lightrec.build('/data/Maps/Test/MIXED.lighting', again)
        self.assertEqual((info, payload), (info2, payload2))
        self.assertEqual(sum(1 for i in again for m in i['meshes'] if m.get('single') is not None), summ['single_entries'])

    def test_single_entry_needs_counts(self):
        with self.assertRaises(lightrec.RecordError):
            lightrec.build('x', [dict(path=((1, 1),), meshes=[dict(pivot=0, mesh=0, single=0xFF000000, vcount=0, icount=3)])])

    def test_deterministic(self):
        a = self.build(4)[1]
        b = self.build(4)[1]
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])


class TestAlphaFlags(unittest.TestCase):
    def test_import_flags(self):
        from todct import modelimport as MI
        self.assertEqual(MI.smb_flags('opaque'), 0xBA1BC000)
        self.assertEqual(MI.smb_flags('mask'), 0xBA1BC040)
        self.assertEqual(MI.smb_flags('blend'), 0xBA1BC020)

    def test_mapgen_textures_carry_their_alpha(self):
        from todms.mapgen import core
        o = core.Out('t')
        o.texture('W', 'water', 128, 'RGBA32', 1)
        o.texture('F', 'fence', 128, 'RGBA32', 1)
        o.texture('G', 'glass', 128, 'RGBA32', 1)
        o.texture('D', 'dirt', 128, 'DXT1', 1)
        self.assertEqual({k: v.get('alpha') for k, v in o.textures.items()}, dict(W='blend', F='cutout', G='blend', D=None))

    def test_fence_is_cut_out_and_glass_is_see_through(self):
        from todms.mapgen import texkinds
        f = texkinds.render('fence', 64, 1)
        g = texkinds.render('glass', 64, 1)
        self.assertEqual(f.shape[-1], 4)
        self.assertTrue(set(np.unique(f[..., 3])) <= {0.0, 1.0})                     # 1-bit alpha
        self.assertGreater((f[..., 3] == 0).mean(), 0.5)
        mid = ((g[..., 3] > 0.1) & (g[..., 3] < 0.9)).mean()
        self.assertGreater(mid, 0.5)                                                 # a pane: partly see-through
        self.assertEqual(texkinds.ALPHA['fence'], 'cutout')

    def test_blockout_panels(self):
        from todms.mapgen import blockout, core
        m = dict(blockout=[dict(id='f', pos=[0, 0, 0], size=[6, 2, 0.1], material='fence'), dict(id='g', pos=[10, 0, 0], size=[3, 2, 0.1], material='glass'),
                           dict(id='b', pos=[20, 0, 0], size=[3, 2, 3])])
        out = core.Out('t')
        blockout.build(m, out)
        self.assertEqual(set(out.textures), {'B_Grey', 'B_Fence', 'B_Glass'})
        self.assertEqual(out.textures['B_Fence']['alpha'], 'cutout')
        self.assertEqual(out.textures['B_Glass']['alpha'], 'blend')
        self.assertEqual(out.textures['B_Fence']['format'], 'RGBA32')


@unittest.skipUnless(HAVE_GAME, 'needs the proof copy')
class TestOnGameData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, TODMS_HOME=os.path.join(cls.t.name, 'home'), TODMS_CACHE=os.path.join(cls.t.name, 'cache'),
                             TODMS_SAVES=os.path.join(cls.t.name, 'saves'))
        cls.env.start()
        from todms import workspace
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))
        from todct import tools as TT
        cls.K = TT.load()
        cls.T = cls.K.ft.types()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.t.cleanup()

    def read(self, entry):
        ft = self.K.ft
        e = ft.resolve_entry(entry)
        return ft.archive().read(e), os.path.splitext(e)[1]

    def test_calibration_against_a_shipped_map(self):
        """Hacienda: its own baked colours against ours. The convention (+Z axis, inverse of the stored orient) must beat every other reading
        and the model must follow the shipped colours (correlation), and shadows must bring the brightness closer even where the correlation
        does not move (the shipped bake has lights of its own that the sun does not explain)."""
        from todms import bakecal
        raw, ext = self.read('mainmap_map08_hacienda.map')
        sample = bakecal.shipped_sample(raw, ext, self.K, self.T, max_vertices=8000)
        self.assertGreater(sample['instances'], 10)
        tree = raycast.Tree(sample['occ'])
        block = 'mainmap_map08_hacienda.map'
        mine = bakecal.calibrate(sample, bakecal.lights_of(block), tree)
        self.assertGreater(mine['corr_sun'], 0.35, mine)
        self.assertGreater(mine['corr_shadow'], 0.30, mine)
        self.assertLess(mine['mae_shadow'], mine['mae_sun'], mine)
        best_other = 0.0
        for ax in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            for conj in (True, False):
                if ax == (0, 0, 1) and conj:
                    continue
                lt = bakecal.lights_of(block, axis=ax, conj=conj)
                if lt['sun_dir'][1] >= 0:                                   # a sun that shines upwards is no reading
                    continue
                c = bakecal.calibrate(sample, lt, tree)
                best_other = max(best_other, c['corr_sun'])
        self.assertGreater(mine['corr_sun'], best_other, (mine, best_other))
        print('calibration (Hacienda, %d vertices): sun only corr %.3f mae %.3f, with shadows corr %.3f mae %.3f; best other reading corr %.3f'
              % (mine['vertices'], mine['corr_sun'], mine['mae_sun'], mine['corr_shadow'], mine['mae_shadow'], best_other))

    def test_the_writer_reproduces_a_shipped_record(self):
        """A shipped record's per-vertex entries, written again by lightrec, read back identical and strict."""
        raw, ext = self.read('mainmap_map10_runawaytrain.map')
        recs, blk = lightrec.read(raw, ext)
        r = recs[0]
        desc = lightrec.describe(r, blk)
        self.assertGreater(len(desc), 100)
        info, pay, summ = lightrec.build(r.name, desc)
        import tod_hd_game as G
        b2 = G.Block(raw, ext)
        b2.info = bytearray(blk.info[:r.R]) + bytearray(info) + bytearray(blk.info[r.end:])
        pl = list(blk.payloads)
        pl[r.index] = pay
        b2.payloads = pl
        out = b2.serialize()
        recs2, blk2 = lightrec.read(out, ext)
        d2 = lightrec.describe(recs2[0], blk2)

        def norm(d):
            return {tuple(i['path']): {(m['pivot'], m['mesh'], len(m['colours']), len(m['indices'])): (m['colours'].tobytes(), m['indices'].tobytes())
                                       for m in i['meshes'] if m.get('single') is None} for i in d}
        self.assertEqual(norm(desc), norm(d2))

    def test_the_writer_reproduces_shipped_single_colour_entries(self):
        """A shipped record holds per-vertex and single-colour entries; written again they read back identical and pass the strict reader
        (the exact size pass, every key found by the engine's search)."""
        import tod_hd_game as G
        for entry in ('mainmap_map10_runawaytrain.map', 'submap01_map02_lostoros_downtown.submap'):
            raw, ext = self.read(entry)
            recs, blk = lightrec.read(raw, ext)
            r = recs[0]
            desc = lightrec.describe(r, blk)
            n_single = sum(1 for i in desc for m in i['meshes'] if m.get('single') is not None)
            self.assertGreater(n_single, 100)
            self.assertEqual(sum(len(i['meshes']) for i in desc), len(r.keys))
            info, pay, summ = lightrec.build(r.name, desc)
            self.assertEqual(len(info), r.end - r.R)
            self.assertEqual(summ['single_entries'], n_single)
            b2 = G.Block(raw, ext)
            b2.info = bytearray(blk.info[:r.R]) + bytearray(info) + bytearray(blk.info[r.end:])
            pl = list(blk.payloads)
            pl[r.index] = pay
            b2.payloads = pl
            recs2, blk2 = lightrec.read(b2.serialize(), ext)
            d2 = lightrec.describe(recs2[0], blk2)

            def norm(d):
                o = {}
                for i in d:
                    for m in i['meshes']:
                        k = (tuple(i['path']), m['pivot'], m['mesh'])
                        o[k] = (m['single'], m['vcount'], m['icount']) if m.get('single') is not None else (m['colours'].tobytes(), m['indices'].tobytes())
                return o
            self.assertEqual(norm(desc), norm(d2))

    def geometry(self, **extra):
        """A tiny generated map through the real geometry builder -> (geo, expanded map entry, work dir)."""
        from todms import mapgen
        from todms.mapgen import geoplug
        from todms.newmap_recipe import make_new_map as MM
        p = dict(package='T', maps=[dict(name='Map11_BakeProofs12', source='map10_runawaytrain',
                                         terrain=dict(size=[16, 16], cell=2.0, chunk=16, strokes=[dict(tool='raise', pos=[0, 0], radius=12, strength=2)]),
                                         ground_paint=dict(palette=['dirt', 'grass'], default='grass'),
                                         look=dict(preset='clear_day'),
                                         blockout=[dict(id='fence', pos=[-6, 0.0, -6], size=[8, 2, 0.12], material='fence'),
                                                   dict(id='glass', pos=[6, 0.0, -6], size=[3, 2.4, 0.08], material='glass'),
                                                   dict(id='wall', pos=[0, 0.0, 6], size=[1, 3, 6])], **extra)])
        res = mapgen.expand_full(p)
        m = res['params']['maps'][0]
        MM.ex_bind()
        geo_in = dict(m, new_geometry=MM.shipped_into_geometry(m))
        geoplug.set_alpha({t['name']: t.get('alpha') for t in geo_in['new_geometry']['textures'] if t.get('alpha')})
        out = os.path.join(self.t.name, 'geo')
        geo = MM.NG.build(geo_in, MM.SOURCES['map10_runawaytrain'], 'Map11_BakeProofs12', out, MM.geo_K(), MM.ft.types())
        return MM, geo, m

    def test_geometry_block_is_baked_and_read_back(self):
        """A small generated map through the real geometry builder: the block gets a lighting record, every placed node is statically lit and
        found by the engine lookup, a cut-out fence and a see-through pane carry their flags, the fall-back leaves the block as it was."""
        from todms import bakestep
        MM, geo, m = self.geometry()
        raw0 = rb(geo['map_file'])
        rep = bakestep.run(geo, m, MM.geo_K(), MM.ft.types())
        self.assertEqual(rep['status'], 'baked', rep)
        self.assertEqual(rep['instances'], len(geo['report']['placements']))
        self.assertTrue(rep['checks'])
        raw = rb(geo['map_file'])
        self.assertNotEqual(raw, raw0)
        recs, blk = lightrec.read(raw, '.map')
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(recs[0].paths), rep['instances'])
        # the old record's 1 MB of colours is gone: the new payload is just what was baked
        self.assertEqual(len(blk.payloads[recs[0].index]), rep['payload_bytes'])
        # every placed node is statically lit
        root = [r for r in blk.records if r['type'] == 4 and r['name'].endswith(geo['root_fragment'])][0]
        d = self.K.fe.FragDoc(blk.payloads[root['index']], self.T, root['name'])
        for pl in geo['report']['placements']:
            self.assertTrue(d.get(int(pl['node'], 16), 'statically_lit'), pl['name'])
        # alpha flags on the meshes of the panel models
        models = bake.read_models(raw, '.map')
        fl = {}
        for k, mod in models.items():
            for me in mod['pivots'][0] if mod['pivots'] else []:
                fl.setdefault(k.rsplit('/', 1)[-1], set()).add(me['flags'])
        self.assertIn(0xBA1BC040, set().union(*[fl[k] for k in fl if 'blockout' in k]), fl)       # the fence: alpha test
        self.assertIn(0xBA1BC020, set().union(*[fl[k] for k in fl if 'blockout' in k]), fl)       # the glass pane: alpha blend
        # baking again from the unbaked block gives the same bytes (deterministic)
        MM2, geo2, m2 = self.geometry()
        rep2 = bakestep.run(geo2, m2, MM2.geo_K(), MM2.ft.types())
        self.assertEqual(rb(geo2['map_file']), raw)

    def test_bake_off_and_failure_leave_the_block_alone(self):
        from todms import bakestep
        MM, geo, m = self.geometry(bake=dict(enabled=False))
        raw0 = rb(geo['map_file'])
        rep = bakestep.run(geo, m, MM.geo_K(), MM.ft.types())
        self.assertEqual(rep['status'], 'skipped')
        self.assertEqual(rb(geo['map_file']), raw0)
        m2 = dict(m, bake=dict(quality='nonsense'), lighting=m['lighting'])
        rep = bakestep.run(geo, m2, MM.geo_K(), MM.ft.types())
        self.assertEqual(rep['status'], 'skipped')
        self.assertIn('quality', rep['reason'])
        self.assertEqual(rb(geo['map_file']), raw0)
        m3 = dict(m, lighting=dict(m['lighting'], sun={'color': [1, 1, 1]}))              # no sun direction: nothing to bake with
        rep = bakestep.run(geo, m3, MM.geo_K(), MM.ft.types())
        self.assertEqual(rep['status'], 'skipped')
        self.assertEqual(rb(geo['map_file']), raw0)


if __name__ == '__main__':
    unittest.main()
