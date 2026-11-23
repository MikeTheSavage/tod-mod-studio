"""The PSP vehicle reader (todct.ccc) and the vehicle swap (todms.cccveh), on small data made in code in the same format.

No game data is used: the model record, its mesh buffers and its block are built here byte by byte. The game test (replace a
vehicle of a proof copy of the game in env TODMS_PROOF) is skipped when it is unset.
"""
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, HERE)
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
HAVE_GAME = os.path.isdir(os.path.join(PROOF, 'game'))


def _ptr(frm, to):
    return (to - frm) & 0xFFFFFFFF


def make_mesh(seg, verts, uv, nrm, batches, vt, tex, scale=1.0):
    """Append one mesh buffer (batches, vertices) to the segment bytearray -> the 16 byte header (tex index after it)."""
    from todct import ccc
    stride, offs = ccc.vtype_size(vt)
    cnt, nb = len(verts), len(batches)
    ptr = len(seg)
    for k, end in enumerate(batches):
        seg += struct.pack('<6f2H', *([0.0] * 6), end, 0)
    seg += bytes(40)
    ps16 = ((vt >> 7) & 3) == 2
    for i in range(cnt):
        v = bytearray(stride)
        if vt & 3 == 1:
            v[offs['tc']:offs['tc'] + 2] = bytes([int(uv[i][0] * 128) & 255, int(uv[i][1] * 128) & 255])
        elif vt & 3 == 2:
            struct.pack_into('<2H', v, offs['tc'], int(uv[i][0] * 32768) & 0xFFFF, int(uv[i][1] * 32768) & 0xFFFF)
        struct.pack_into('<3b', v, offs['nm'], *[int(round(c * 127)) for c in nrm[i]])
        if ps16:
            struct.pack_into('<3h', v, offs['ps'], *[int(round(c * 32767)) for c in verts[i]])
        else:
            struct.pack_into('<3b', v, offs['ps'], *[int(round(c * 127)) for c in verts[i]])
        seg += v
    return struct.pack('<IIfI', (nb << 23) | cnt, vt, scale, ptr) + struct.pack('<I', tex) + bytes(12)


def build_model(centre=(0, 0, 0), body_quat=(0, 0, 0, 1), wheel_parent=0, far=False, uv_scale=1.0, wheels=1):
    """A three part vehicle: root, Mainbody (a box of 3 sub-meshes' worth: one s16 mesh), Wheel_Left_01 (s8). -> (record bytes, segment)
    centre: the Mainbody's box centre (+0x4c); body_quat: its stored rotation; wheel_parent: the wheel's parent; far: the body's mesh is
    marked a far-view copy; uv_scale: the body mesh's texture scale (the header float)."""
    seg = bytearray()
    cube = [(-1, -1, -1), (1, -1, -1), (-1, 1, -1), (1, 1, -1), (-1, -1, 1), (1, -1, 1)]            # a 6 vertex strip
    nrm = [(0, 0, -1)] * 6
    uv = [(0, 0), (1, 0), (0, 1), (1, 1), (0, 0), (1, 0)]
    h_body = make_mesh(seg, cube, uv, nrm, [6], 0x122, 2, uv_scale)       # tc u16, normal s8, position s16
    h_wheel = make_mesh(seg, [(-1, -1, -1), (1, -1, 1), (-1, 1, -1), (1, 1, 1)], uv[:4], nrm[:4], [4], 0xA2, 3)    # tc u16, normal s8, position s8
    pivots = [(None, (0, 0, 0), (0, 0, 0, 1), (0.5, 0.5, 0.5), -1, None),
              ('Mainbody', (0, 0.5, 0), body_quat, (2.0, 1.0, 4.0), 0, h_body),
              ('Wheel_Left_01', (-1.0, -0.25, 1.5), (0, 0, 0, 1), (0.5, 0.8, 0.8), wheel_parent, h_wheel)]
    if wheels == 4:                                                         # a pair of axles: front and back, left and right
        pivots += [('Wheel_Right_01', (1.0, -0.25, 1.5), (0, 1, 0, 0), (0.5, 0.8, 0.8), wheel_parent, h_wheel),
                   ('Wheel_Left_02', (-1.0, -0.25, -1.5), (0, 0, 0, 1), (0.5, 0.8, 0.8), wheel_parent, h_wheel),
                   ('Wheel_Right_02', (1.0, -0.25, -1.5), (0, 1, 0, 0), (0.5, 0.8, 0.8), wheel_parent, h_wheel)]
    b = bytearray(0x100)
    struct.pack_into('<II', b, 0, 3, 0x64)
    struct.pack_into('<I', b, 0x1c, 0x18)
    struct.pack_into('<I', b, 0x34, len(pivots))
    b += b'/data/textures/vehiclegenerics/set_decals/A.BMP\0' + b'/data/Models/Vehicles/Test/textures/B.bmp\0'
    b += b'/data/Models/Vehicles/Test/textures/Wheel.bmp\0'
    while len(b) % 4:
        b += b'\0'
    pst = len(b)
    struct.pack_into('<I', b, 0x30, pst - 0x30)
    b += bytes(0x58 * len(pivots))
    strs = len(b)
    str_at = {}
    for n in ['Mainbody', 'meshroot'] + [q[0] for q in pivots[2:]]:
        while len(b) % 4:                                   # pointers keep two flag bits: names are word aligned
            b += b'\0'
        str_at[n] = len(b)
        b += n.encode() + b'\0'
    while len(b) % 4:
        b += b'\0'
    recs = len(b)
    b += bytes((0x3c + 0x40) * len(pivots))                  # a gap between the records of two parts
    mesh_at = len(b)
    meshes = []
    for i, (name, pos, q, sc, parent, hdr) in enumerate(pivots):
        o = pst + i * 0x58
        struct.pack_into('<3f4f', b, o, *pos, *q)
        struct.pack_into('<i', b, o + 0x38, parent)
        struct.pack_into('<3f', b, o + 0x40, *sc)
        if i == 1:
            struct.pack_into('<3f', b, o + 0x4c, *centre)
        if name:
            struct.pack_into('<I', b, o + 0x1c, _ptr(o + 0x1c, str_at[name]))
            rec_at = recs + (i - 1) * (0x3c + 0x40)
            while len(b) % 4:
                b += b'\0'
            hdr_at = len(b)
            b += hdr
            struct.pack_into('<I', b, rec_at, _ptr(rec_at, hdr_at))
            struct.pack_into('<I', b, o + 0x24, _ptr(o + 0x24, rec_at))
            if i == 1 and far:
                struct.pack_into('<I', b, rec_at + 0x38, 0x441bc001)             # bit 0 of the last flag word: a far-view copy
        else:
            struct.pack_into('<I', b, o + 0x1c, _ptr(o + 0x1c, str_at['meshroot']))
            struct.pack_into('<I', b, o + 0x24, _ptr(o + 0x24, str_at['meshroot']))
    return bytes(b), bytes(seg)


class TestReader(unittest.TestCase):
    def test_vtype_sizes(self):
        from todct import ccc
        self.assertEqual(ccc.vtype_size(0xA1)[0], 8)
        self.assertEqual(ccc.vtype_size(0xA2)[0], 10)
        self.assertEqual(ccc.vtype_size(0x121)[0], 12)
        self.assertEqual(ccc.vtype_size(0x122)[0], 14)
        self.assertEqual(ccc.vtype_size(0x122)[1], dict(tc=0, nm=4, ps=8))

    def test_model_parts_meshes_and_transforms(self):
        from todct import ccc
        rec, seg = build_model()
        v = ccc.parse_model(rec, seg)
        self.assertEqual([p['name'] for p in v.pivots], ['meshroot', 'Mainbody', 'Wheel_Left_01'])
        self.assertEqual([p['parent'] for p in v.pivots], [-1, 0, 0])
        self.assertEqual(len(v.textures), 3)
        body = v.pivots[1]['meshes'][0]
        self.assertEqual((len(body['P']), body['tex']), (6, 2))
        self.assertLess(float(np.abs(body['P'][0] - (-1, -1, -1)).max()), 1e-3)          # unit box: the part's size scales it later
        self.assertLess(float(np.abs(body['UV'][3] - (1, 1)).max()), 1e-3)
        self.assertEqual(len(body['tris']), 4)                                              # a 6 vertex strip is 4 triangles
        self.assertEqual(body['tris'].tolist(), [[0, 1, 2], [2, 1, 3], [2, 3, 4], [4, 3, 5]])
        wheel = v.pivots[2]['meshes'][0]
        self.assertEqual((len(wheel['P']), wheel['tex'], len(wheel['tris'])), (4, 3, 2))
        s = ccc.vehicle_scene(v)
        P = np.concatenate([p.P for p in s.parts])
        self.assertAlmostEqual(float(P[:, 0].max()), 1.0 + 0.0, places=2)                   # body half width 2.0 * 0.5
        self.assertAlmostEqual(float(P[:, 0].min()), -1.25, places=2)                     # wheel centre -1.0, half width 0.25
        names = sorted(p.mat['pivot'] for p in s.parts)
        self.assertEqual(names, ['Mainbody', 'Wheel_Left_01'])
        w = next(p for p in s.parts if p.mat['pivot'] == 'Wheel_Left_01')
        self.assertEqual(w.mat['origin'], [-1.0, -0.25, 1.5])

    def test_flat_and_damaged_copies_are_dropped(self):
        from todct import ccc
        rec, seg = build_model()
        v = ccc.parse_model(rec, seg)
        v.textures[2] = '/data/textures/vehiclegenerics/set_wreck/Wreck_Body.bmp'
        s = ccc.vehicle_scene(v)
        self.assertEqual([p.mat['pivot'] for p in s.parts], ['Wheel_Left_01'])

    def test_far_view_copies_are_dropped(self):
        from todct import ccc
        v = ccc.parse_model(*build_model(far=True))
        self.assertTrue(v.pivots[1]['meshes'][0]['lod'])
        self.assertFalse(v.pivots[2]['meshes'][0]['lod'])
        self.assertEqual([p.mat['pivot'] for p in ccc.vehicle_scene(v).parts], ['Wheel_Left_01'])

    def test_texture_scale_is_the_header_float(self):
        from todct import ccc
        v = ccc.parse_model(*build_model(uv_scale=0.5))
        self.assertLess(float(np.abs(v.pivots[1]['meshes'][0]['UV'][3] - (0.5, 0.5)).max()), 1e-3)      # raw 1.0 x scale 0.5

    def test_the_box_centre_moves_the_mesh_and_size_scales_it(self):
        from todct import ccc
        s = ccc.vehicle_scene(ccc.parse_model(*build_model(centre=(0, 0.5, 0))))
        body = np.concatenate([p.P for p in s.parts if p.mat['pivot'] == 'Mainbody'])
        # unit box -1..1 x half size (1.0, 0.5, 2.0), centred 0.5 above the part (which sits 0.5 above the root)
        self.assertAlmostEqual(float(body[:, 1].min()), 0.5 + 0.5 - 0.5, places=2)
        self.assertAlmostEqual(float(body[:, 1].max()), 0.5 + 0.5 + 0.5, places=2)
        self.assertAlmostEqual(float(body[:, 2].max()), 2.0, places=2)

    def test_stored_rotation_is_the_conjugate_and_children_follow_their_parents(self):
        from todct import ccc
        q = (0.0, 0.7071068, 0.0, 0.7071068)                                  # +90 degrees about y as stored
        v = ccc.parse_model(*build_model(body_quat=q, wheel_parent=1))
        W = v.world
        # the engine turns the part by the conjugate (-90 degrees about y): a child 1.5 ahead (z) of it lands at x = -1.5
        self.assertLess(float(np.abs(W[1][:3, :3] @ (0, 0, 1) - (-1, 0, 0)).max()), 1e-5)
        wheel = W[2][:3, 3]
        expect = np.array([0, 0.5, 0]) + W[1][:3, :3] @ np.array([-1.0, -0.25, 1.5])         # parent matrix times the local offset
        self.assertLess(float(np.abs(wheel - expect).max()), 1e-5)
        self.assertLess(float(np.abs(wheel - (-1.5, 0.25, -1.0)).max()), 1e-5)
        s = ccc.vehicle_scene(v)
        w = next(p for p in s.parts if p.mat['pivot'] == 'Wheel_Left_01')
        self.assertLess(float(np.abs(np.asarray(w.mat['origin']) - wheel).max()), 1e-5)

    def test_png_writer_reads_back(self):
        from todct import ccc, texture as TX
        rgba = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 128])
        img = TX.read_png(ccc.png_bytes(2, 2, rgba))
        self.assertEqual(img.shape[:2], (2, 2))
        self.assertAlmostEqual(float(img[1, 1, 3]), 128 / 255.0, places=2)

    def test_folder_resolution_and_empty_setting(self):
        from todct import ccc
        self.assertIsNone(ccc.resolve(''))
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(ccc.resolve(t))
            sub = os.path.join(t, 'PSP_GAME', 'USRDIR')
            os.makedirs(sub)
            with open(os.path.join(sub, 'assets00.naz'), 'wb') as f:
                f.write(b'x')
            self.assertEqual(ccc.resolve(t), os.path.join(sub, 'assets00.naz'))
        self.assertEqual(ccc.nice_name('PickUpTruck_Mamma'), 'Mamma pickup truck')
        self.assertEqual(ccc.nice_name('Some_NewThing'), 'Some new thing')


def target_spec(names, pos, y_off=0.2):
    def piv(name, p, parent, meshes=True):
        return dict(name=name, pos=p, quat=(0, 0, 0, 1), parent=parent, meshes=[dict(smb_flags=0)] if meshes else [])
    return dict(pivots=[piv(None, (0, 0, 0), -1, False), piv('MainBody', (0, y_off, 0), 0)] + [piv(n, q, 0) for n, q in zip(names, pos)])


def target_info(spec):
    return dict(spec=spec, skinned=False, mesh_pivots=list(range(1, len(spec['pivots']))), min=np.zeros(3), max=np.ones(3))


class TestVehicleSwap(unittest.TestCase):
    NAMES = ['Wheel_Left_01', 'Wheel_Right_01', 'Wheel_Left_02', 'Wheel_Right_02']

    def scene(self, **kw):
        from todct import ccc
        return ccc.vehicle_scene(ccc.parse_model(*build_model(wheels=4, **kw)))

    def world(self, spec, baked, i):
        from todms import cccveh
        W = cccveh._world(spec)
        return np.concatenate([g['P'].astype(float) @ W[i][:3, :3].T + W[i][:3, 3] for g in baked.by_pivot[i]])

    def test_wheels_land_on_the_target_wheel_parts_and_the_body_is_fitted(self):
        from todms import cccveh
        spec = target_spec(self.NAMES, [(-1.1, -0.6, 1.9), (1.1, -0.6, 1.9), (-1.1, -0.6, -1.9), (1.1, -0.6, -1.9)])
        b = cccveh.bake(self.scene(), dict(collision=dict(mode='none'), mirror=''), target_info(spec))
        self.assertEqual(sorted(b.by_pivot), [1, 2, 3, 4, 5])
        self.assertEqual(b.wheel_pos, {})                                                  # the target's wheel parts stay where they are
        self.assertAlmostEqual(b.fit['track'], 1.1, places=3)                              # wheels 2.0 apart -> 2.2
        self.assertAlmostEqual(b.fit['wheelbase'], 3.8 / 3.0, places=3)                    # 3.0 -> 3.8
        for i in (2, 3, 4, 5):
            wp = np.concatenate([g['P'] for g in b.by_pivot[i]])
            self.assertLess(float(np.abs((wp.min(0) + wp.max(0)) / 2).max()), 0.05)        # centred on its own part: it turns about it
            self.assertAlmostEqual(float(wp[:, 1].max() - wp[:, 1].min()), 0.8, places=2)  # the vehicle's own wheel size
            w = self.world(spec, b, i)
            self.assertLess(float(np.abs((w.min(0) + w.max(0)) / 2 - spec['pivots'][i]['pos']).max()), 0.05)
        body = self.world(spec, b, 1)
        self.assertAlmostEqual(float(body[:, 0].max()), 1.1, places=2)                     # body half width 1.0 x track factor
        self.assertAlmostEqual(float(body[:, 2].max()), 2.0 * b.fit['wheelbase'], places=2)
        # the vehicle's ground (wheel centre -0.25, radius 0.4) lands on the target's (-0.6, radius 0.4 kept): every wheel stands on it
        ground = -0.6 - 0.4
        self.assertAlmostEqual(float(min(self.world(spec, b, i)[:, 1].min() for i in (2, 3, 4, 5))), ground, places=2)
        self.assertAlmostEqual(float(body[:, 1].min()), ground + (0.0 - (-0.25 - 0.4)) * b.fit['height'], places=2)
        for gs in b.by_pivot.values():
            for g in gs:                                                                    # wound against the normals: the render rule
                P, N, T = g['P'].astype(float), g['N'].astype(float), g['tris']
                n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
                self.assertTrue(((n * (N[T[:, 0]] + N[T[:, 1]] + N[T[:, 2]])).sum(1) < 1e-9).all())

    def test_a_target_with_its_own_wheel_names_pairs_by_place(self):
        from todms import cccveh
        spec = target_spec(['Wheel_BR', 'Wheel_FL', 'Wheel_BL', 'Wheel_FR'], [(1.1, -0.6, -1.9), (-1.1, -0.6, 1.9), (-1.1, -0.6, -1.9), (1.1, -0.6, 1.9)])
        b = cccveh.bake(self.scene(), dict(collision=dict(mode='none'), mirror=''), target_info(spec))
        self.assertEqual(sorted(b.by_pivot), [1, 2, 3, 4, 5])
        for i in (2, 3, 4, 5):                                                              # each wheel went to the part at its own corner
            w = self.world(spec, b, i)
            self.assertLess(float(np.abs((w.min(0) + w.max(0)) / 2 - spec['pivots'][i]['pos']).max()), 0.05)
        self.assertTrue(any('no part of that name' in w for w in b.warnings))

    def test_a_vehicle_that_does_not_fit_is_refused(self):
        from todms import cccveh
        spec = target_spec(self.NAMES[:2], [(-1.1, -0.6, 1.9), (1.1, -0.6, 1.9)])
        with self.assertRaises(cccveh.CccVehicleError) as e:
            cccveh.bake(self.scene(), dict(collision=dict(mode='none'), mirror=''), target_info(spec))
        self.assertIn('4 wheels against 2', str(e.exception))
        wide = target_spec(self.NAMES, [(-2.6, -0.6, 1.5), (2.6, -0.6, 1.5), (-2.6, -0.6, -1.5), (2.6, -0.6, -1.5)])
        with self.assertRaises(cccveh.CccVehicleError) as e:
            cccveh.bake(self.scene(), dict(collision=dict(mode='none'), mirror=''), target_info(wide))
        self.assertIn('track', str(e.exception))

    def test_a_vehicle_on_its_own_wheels_is_not_moved(self):
        from todms import cccveh
        spec = target_spec(self.NAMES, [(-1.0, -0.25, 1.5), (1.0, -0.25, 1.5), (-1.0, -0.25, -1.5), (1.0, -0.25, -1.5)], y_off=0.5)
        b = cccveh.bake(self.scene(), dict(collision=dict(mode='none'), mirror=''), target_info(spec))
        for k in ('track', 'wheelbase', 'height', 'wheel'):
            self.assertAlmostEqual(b.fit[k], 1.0, places=3)
        body = self.world(spec, b, 1)
        self.assertAlmostEqual(float(body[:, 1].min()), 0.0, places=2)                      # the body part's box starts at 0.5 - 0.5
        self.assertFalse(any('Fitted' in w for w in b.warnings))


class TestPhysicalChecks(unittest.TestCase):
    """ccc.check_vehicle: the checks that would have caught the wrongly assembled vehicles."""

    @staticmethod
    def box(name, lo, hi):
        from todct import meshtex as MT
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        P = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
        m = MT.default_material()
        m['pivot'] = name
        return MT.Part(name + '#0', P, None, None, np.array([[0, 1, 2]]), m)

    def car(self, lift=0.0, drop_right=False, away=False):
        parts = [self.box('Mainbody', (-0.9, -0.1, -2.0), (0.9, 0.8, 2.0))]
        for n, x, z in (('Wheel_Left_01', -1.0, 1.4), ('Wheel_Right_01', 1.0, 1.4), ('Wheel_Left_02', -1.0, -1.4), ('Wheel_Right_02', 1.0, -1.4)):
            if drop_right and n == 'Wheel_Right_02':
                continue
            y = -0.3 + (lift if n == 'Wheel_Left_02' else 0.0)
            parts.append(self.box(n, (x - 0.15, y - 0.3, z - 0.3), (x + 0.15, y + 0.3, z + 0.3)))
        parts += [self.box('Light_Head_Left', (-0.8, 0.1, 2.0), (-0.5, 0.3, 2.05)), self.box('Light_Head_Right', (0.5, 0.1, 2.0), (0.8, 0.3, 2.05))]
        if away:
            parts.append(self.box('Roof_Grab', (0.0, 3.0, 0.0), (0.1, 3.1, 0.1)))
        return parts

    def test_a_sound_vehicle_passes(self):
        from todct import ccc
        self.assertEqual(ccc.check_vehicle(self.car()), [])

    def test_a_floating_wheel_is_reported(self):
        from todct import ccc
        w = ccc.check_vehicle(self.car(lift=0.4))
        self.assertTrue(any('one ground' in x for x in w), w)

    def test_a_missing_wheel_breaks_the_mirror(self):
        from todct import ccc
        self.assertTrue(any('mirror' in x for x in ccc.check_vehicle(self.car(drop_right=True))))

    def test_a_detached_part_is_reported(self):
        from todct import ccc
        w = ccc.check_vehicle(self.car(away=True))
        self.assertTrue(any('detached' in x for x in w), w)

    def test_a_body_below_the_wheels_ground_is_reported(self):
        from todct import ccc
        parts = self.car()
        parts[0] = self.box('Mainbody', (-0.9, -1.2, -2.0), (0.9, 0.8, 2.0))
        self.assertTrue(any('below the ground' in x for x in ccc.check_vehicle(parts)))

    def test_a_left_part_that_is_not_mirrored_is_reported(self):
        from todct import ccc
        parts = self.car()
        parts[-2] = self.box('Light_Head_Left', (-0.8, 0.1, 1.2), (-0.5, 0.3, 1.25))
        self.assertTrue(any('mirrored' in x for x in ccc.check_vehicle(parts)))

    def test_the_scene_carries_the_warnings_to_the_import_screen(self):
        from todct import ccc
        s = ccc.vehicle_scene(ccc.parse_model(*build_model()))
        self.assertIsInstance(s.warnings, list)


@unittest.skipUnless(HAVE_GAME, 'needs the proof copy')
class TestVehicleOnTheGame(unittest.TestCase):
    """A synthetic vehicle replaces a shipped one: the record is written, read back and the wheels keep their parts."""

    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, TODMS_HOME=os.path.join(cls.t.name, 'home'), TODMS_CACHE=os.path.join(cls.t.name, 'cache'),
                             TODMS_SAVES=os.path.join(cls.t.name, 'saves'))
        cls.env.start()
        from todms import workspace, paths, assetindex
        paths.ensure_cpu_guard()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))
        assetindex.build(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.t.cleanup()

    def test_replace_the_pickup(self):
        from todct import ccc, modelimport as MI
        from todms import imports, mods, assetstore, extract
        target = '/data/models/vehicles/pickuptruck/vehicle.model'
        rec, seg = build_model(wheels=4)
        scene = ccc.vehicle_scene(ccc.parse_model(rec, seg))
        sha = assetstore.put(MI.scene_to_bytes(scene))
        ent = imports.entry(self.ws, dict(sha=sha, file='Test', mode='replace', target=target, name='Test', params=dict(ccc=True, mirror='', origin='none')))['entry']
        out = tempfile.mkdtemp(dir=self.t.name)
        rep = mods.build_mods(self.ws, [dict(name='t', level=[], data={}, models=[ent], textures=[])], out, 'a.zip')
        outs = dict(rep.pop('_outs'))
        self.assertTrue(outs)
        for b in rep['assets']['blocks']:
            self.assertEqual(b['verify']['result'], 'PASS')
        e0 = sorted(outs)[0]
        ba = extract.BlockAssets(outs[e0], os.path.splitext(e0)[1])
        glb, meta = ba.model_glb(target)
        self.assertEqual(meta['render_tris'], 12)                                          # 4 body triangles and 2 for each of the 4 wheels
        self.assertEqual(meta['hulls'] > 0, True)                                          # the vehicle's own collision is kept


if __name__ == '__main__':
    unittest.main()
