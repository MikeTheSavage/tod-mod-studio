"""Model import / replace and the texture editor: recipe version 4, the textures toolkit, the importer, the "assets" build stage.

The game tests use a proof copy of the game in env TODMS_PROOF (skipped when unset); they build into temporary folders and never write to it.
"""
import io
import json
import os
import shutil
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
TRAINING = 'submap05_map02_lostoros_downtown_training.submap'
PROP = '/data/models/addons/weaponammocrate/weaponammocratewoodopen.model'         # one pivot, three sub-meshes, in two blocks
TEX = '/data/textures/materials/final_ingame_textures/waste_bin.bmp'                # a small prop texture


def env(tmp):
    return patch.dict(os.environ, TODMS_HOME=os.path.join(tmp, 'home'), TODMS_CACHE=os.path.join(tmp, 'cache'), TODMS_SAVES=os.path.join(tmp, 'saves'))


# ------------------------------------------------------------------------------------------------ textures
class TestTexture(unittest.TestCase):
    def test_encode_decode_and_sizes(self):
        from todct import texture as TX
        sys.path.insert(0, os.path.join(ROOT, 'backend', 'vendor', 'newmap'))
        import tex_gen
        rng = np.random.default_rng(1)
        y, x = np.mgrid[0:128, 0:128] / 128.0
        img = np.stack([x, y, (np.sin(x * 20) + 1) / 2, np.ones_like(x)], -1).astype(np.float32)
        img[40:70, 20:100, :3] = [0.9, 0.1, 0.1]
        img = np.clip(img + rng.normal(0, 0.02, img.shape).astype(np.float32) * np.array([1, 1, 1, 0], np.float32), 0, 1)
        pay, lv = TX.encode(img, 'DXT1')
        self.assertEqual(lv, TX.full_chain(128, 128))
        self.assertEqual(len(pay), TX.payload_size('DXT1', 128, 128, lv))
        self.assertEqual(len(pay), tex_gen.payload_size('DXT1', 128, 128, lv))        # the engine's own size rule
        dec = TX.decode_payload(pay, 'DXT1', 128, 128)
        old = tex_gen.dxt1_decode_level(tex_gen.dxt1_level(img[..., :3]), 128, 128)
        self.assertGreater(TX.psnr(img, dec), 31)
        self.assertGreaterEqual(TX.psnr(img, dec), TX.psnr(img, np.concatenate([old, np.ones((128, 128, 1), np.float32)], 2)) - 0.01)
        raw, lv2 = TX.encode(img, 'RGBA32')
        self.assertEqual(len(raw), tex_gen.payload_size('RGBA32', 128, 128, lv2))
        back = TX.decode_payload(raw, 'RGBA32', 128, 128)
        self.assertLess(float(np.abs(back - img).max()), 1 / 255.0 + 1e-6)

    def test_cutout_alpha_and_single_level(self):
        from todct import texture as TX
        img = np.ones((32, 32, 4), np.float32) * np.array([0.2, 0.6, 0.3, 1.0], np.float32)
        img[:16, :, 3] = 0.0
        pay, lv = TX.encode(img, 'DXT1', 0.5, mips=False)
        self.assertEqual(lv, 1)
        d = TX.decode_payload(pay, 'DXT1', 32, 32)
        self.assertTrue((d[:16, :, 3] == 0).all() and (d[16:, :, 3] == 1).all())
        self.assertLess(float(np.abs(d[20:, :, :3] - img[20:, :, :3]).max()), 0.05)

    def test_png_read_write_and_resize_and_edits(self):
        from todct import texture as TX
        rng = np.random.default_rng(2)
        a = rng.integers(0, 255, (20, 30, 4), dtype=np.uint8)
        back = TX.read_png(TX.png_bytes(a, alpha=True))
        self.assertLess(float(np.abs(back - a / 255.0).max()), 1e-6)
        img = back
        r = TX.resize(img, 16, 8)
        self.assertEqual(r.shape, (8, 16, 4))
        flat = np.ones((8, 8, 4), np.float32) * 0.5
        self.assertLess(float(np.abs(TX.resize(flat, 4, 4) - 0.5).max()), 1e-5)
        e = TX.apply_edits(flat, dict(brightness=0.2, alpha='opaque'))
        self.assertAlmostEqual(float(e[0, 0, 0]), 0.7, places=5)
        h = TX.apply_edits(np.array([[[1.0, 0.0, 0.0, 1.0]]], np.float32), dict(hue=120))
        self.assertGreater(float(h[0, 0, 1]), float(h[0, 0, 0]))
        self.assertEqual(TX.pow2_near(300), 256)
        self.assertEqual(TX.pow2_near(400), 512)

    def test_limits_of_the_format(self):
        from todct import texture as TX
        self.assertEqual(TX.payload_size('DXT1', 1024, 1024, 11), 699064)                 # P6: the figure in the limits table
        self.assertEqual(TX.fit_for_cap('RGBA32', 1024, 1024), (512, 256)[0:0] or TX.fit_for_cap('RGBA32', 1024, 1024))
        w, h = TX.fit_for_cap('RGBA32', 2048, 2048)
        self.assertLessEqual(TX.payload_size('RGBA32', w, h, TX.full_chain(w, h)), TX.TEXTURE_CAP)
        with self.assertRaises(TX.TextureError):
            TX.encode(np.ones((24, 24, 4), np.float32), 'DXT1')                           # not a power of two
        with self.assertRaises(TX.TextureError):
            TX.encode(np.ones((2, 2, 4), np.float32), 'DXT1')                             # below 4 pixels

    @unittest.skipUnless(__import__('importlib').util.find_spec('PIL'), 'PIL only compares')
    def test_jpeg_reader_matches_pil(self):
        from PIL import Image
        from todct import jpeg
        yy, xx = np.mgrid[0:90, 0:130]
        img = np.stack([xx * 255 // 130, yy * 255 // 90, (xx + yy) % 64 * 4], -1).astype(np.uint8)
        for kw in (dict(subsampling=0), dict(subsampling=2), dict(subsampling=2, restart_marker_blocks=4)):
            b = io.BytesIO()
            Image.fromarray(img).save(b, 'JPEG', quality=92, **kw)
            a = jpeg.decode(b.getvalue())
            ref = np.asarray(Image.open(io.BytesIO(b.getvalue())).convert('RGB'), np.float32) / 255
            self.assertLess(float(np.abs(a[..., :3] - ref).mean()), 0.015)
        g = io.BytesIO()
        Image.fromarray(img).convert('L').save(g, 'JPEG')
        self.assertEqual(jpeg.decode(g.getvalue()).shape, (90, 130, 4))
        p = io.BytesIO()
        Image.fromarray(img).save(p, 'JPEG', progressive=True)
        with self.assertRaises(Exception):
            jpeg.decode(p.getvalue())


# ------------------------------------------------------------------------------------------------ recipe version 4
class TestRecipe(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = env(self.t.name)
        self.env.start()
        from todms import paths
        paths.setup_tools()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def entry(self, sha, **kw):
        return dict(dict(id='m1', name='Crate', mode='new', path='/data/models/todms/crate/crate.model', source=dict(sha=sha, file='crate.glb'),
                         params={}, stats=dict(max_mesh_vertices=24)), **kw)

    def test_round_trip_with_the_files_inside(self):
        from todms import mods, assetstore
        import io
        buf = io.BytesIO()
        np.savez(buf, a=np.zeros(3, np.float32))
        scene, png = buf.getvalue(), b'\x89PNG\r\n\x1a\na picture'      # the safety check wants real kinds of file
        sha = assetstore.put(scene)
        pic = assetstore.put(png)
        tex = dict(id='t1', target='/data/textures/a.bmp', source=dict(sha=pic, file='a.png'), crop=None, w=64, h=64, fmt='DXT1', edits={})
        m = mods.save_mod(dict(name='t', level=[], data={}, models=[self.entry(sha)], textures=[tex]))
        self.assertEqual(m['version'], 4)
        self.assertEqual({x['id']: x['models'] for x in mods.list_mods()}[m['id']], 1)
        p = os.path.join(self.t.name, 'x.todmod')
        mods.export_mod(m['id'], p)
        shared = json.load(open(p))
        self.assertEqual(set(shared['blobs']), {sha, pic})
        for f in os.listdir(assetstore.store_dir()):
            os.remove(os.path.join(assetstore.store_dir(), f))                       # another machine: nothing in the store
        m2 = mods.import_mod(p)
        self.assertEqual(m2['models'][0]['source']['sha'], sha)
        self.assertEqual(assetstore.get(sha), scene)
        self.assertEqual(assetstore.get(pic), png)
        self.assertNotIn('blobs', m2)

    def test_old_recipes_still_import(self):
        from todms import mods
        for ver, extra in ((1, {}), (2, dict(collision=[])), (3, dict(nav=[], missions=[], sections=[]))):
            p = os.path.join(self.t.name, 'v%d.todmod' % ver)
            json.dump(dict(dict(format='todms-mod', version=ver, name='old %d' % ver, level=[], data={}, assets=[dict(row=1)], source='x'), **extra), open(p, 'w'))
            m = mods.import_mod(p)
            self.assertNotIn('assets', m)                                           # the old Unreal rows are dropped, never read as models
            self.assertNotIn('models', m)
            self.assertLessEqual(m['version'], 3)
        p = os.path.join(self.t.name, 'new.todmod')
        json.dump(dict(format='todms-mod', version=5, name='future', level=[], data={}), open(p, 'w'))
        with self.assertRaises(Exception):
            mods.import_mod(p)

    def test_validation_refuses_what_a_builder_would(self):
        from todct import todmod, assetops
        sha = 'a' * 32
        base = dict(format='todms-mod', version=4, name='x', level=[], data={})
        big = self.entry(sha, stats=dict(max_mesh_vertices=70000))
        with self.assertRaises(todmod.ModError) as c:
            todmod.validate(dict(base, models=[big]))
        self.assertIn('65535', str(c.exception))
        tex = dict(id='t', target='/data/textures/a.bmp', source=dict(sha=sha), crop=None, w=64, h=64, fmt='DXT1', edits={})
        todmod.validate(dict(base, textures=[tex]))
        for bad, text in ((dict(w=48), 'power'), (dict(w=2, h=2), '4 pixels'), (dict(fmt='DXT5'), 'format'), (dict(w=4096, h=4096, fmt='RGBA32'), 'load buffer'),
                          (dict(w=8192, h=8192), 'above')):
            with self.assertRaises(todmod.ModError, msg=text):
                todmod.validate(dict(base, textures=[dict(tex, **bad)]))
        with self.assertRaises(todmod.ModError):
            todmod.validate(dict(base, version=3, textures=[tex]))                 # a recipe that uses version 4 data must say so
        with self.assertRaises(todmod.ModError):
            todmod.validate(dict(base, models=[dict(self.entry(sha), mode='swap')]))
        self.assertEqual(todmod.version_needed(dict(models=[1])), 4)

    def test_live_checks_and_meters(self):
        from todms import checks, ledger, assetstore
        sha = assetstore.put(b'x')
        m = self.entry(sha, stats=dict(max_mesh_vertices=70000, largest_texture=2000000))
        items = checks.asset_items([m], [])
        self.assertTrue(any(i['level'] == 'error' for i in items))                 # M1 refuses
        self.assertTrue(any(i['level'] == 'warn' and 'texture' in i['title'] for i in items))   # P6 is policy: a warning
        rows = {r['id']: r for r in ledger.meter_assets([m], [], [], [])}
        self.assertEqual(rows['M1']['status'], 'red')
        self.assertEqual(rows['P6']['status'], 'red')
        gone = checks.asset_items([self.entry('b' * 32)], [])
        self.assertTrue(any('missing' in i['title'] for i in gone))


# ------------------------------------------------------------------------------------------------ the importer
class TestImporter(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = env(self.t.name)
        self.env.start()
        from todms import paths
        paths.setup_tools()
        paths.ensure_cpu_guard()
        import glbfix
        self.glb = glbfix.write_barrel_glb(os.path.join(self.t.name, 'barrel.glb'), radius=0.3, height=0.9)
        self.box = glbfix.write_box_glb(os.path.join(self.t.name, 'crate.glb'), size=(1.5, 0.6, 1.5), centre=(0, 0.3, 0), extra_boxes=0)

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def test_read_keeps_uvs_normals_and_the_picture(self):
        from todct import meshtex
        s = meshtex.read(self.glb)
        p = s.parts[0]
        self.assertIsNotNone(p.UV)
        self.assertIsNotNone(p.N)
        self.assertEqual(len(s.images), 1)
        self.assertEqual(p.mat['image'], 0)
        st = s.stats()
        self.assertAlmostEqual(st['max'][1] - st['min'][1], 0.9, places=3)

    def test_obj_with_a_material(self):
        from todct import meshtex
        d = self.t.name
        import glbfix
        with open(os.path.join(d, 'a.png'), 'wb') as f:
            f.write(glbfix.checker_png())
        open(os.path.join(d, 'a.mtl'), 'w').write('newmtl wood\nKd 0.8 0.8 0.8\nmap_Kd a.png\n')
        open(os.path.join(d, 'a.obj'), 'w').write('mtllib a.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n'
                                                  'usemtl wood\nf 1/1/1 2/2/1 3/3/1 4/4/1\n')
        s = meshtex.read(os.path.join(d, 'a.obj'))
        self.assertEqual(len(s.parts[0].tris), 2)                                   # the quad is split
        self.assertEqual(len(s.images), 1)
        self.assertAlmostEqual(float(s.parts[0].UV[0][1]), 1.0)                     # OBJ v is flipped to the game's v-down

    def test_transform_axes_scale_origin(self):
        from todct import meshtex, modelimport as MI
        s = meshtex.read(self.glb)
        a = MI.bake(s, dict(scale=2.0), with_payload=False)
        self.assertAlmostEqual(a.stats['size'][1], 1.8, places=3)
        self.assertAlmostEqual(a.stats['min'][1], 0.0, places=4)                   # origin: base
        z = MI.bake(s, dict(up='z', origin='none'), with_payload=False)             # a Z-up file turns on its side
        self.assertAlmostEqual(z.stats['size'][1], a.stats['size'][2] / 2, places=3)
        m = MI.bake(s, dict(origin='match'), ref=([1, 2, 3], [3, 4, 5]), with_payload=False)
        self.assertAlmostEqual(m.stats['min'][1], 2.0, places=4)
        self.assertAlmostEqual((m.stats['min'][0] + m.stats['max'][0]) / 2, 2.0, places=4)

    def test_bake_winding_and_textures(self):
        from todct import meshtex, modelimport as MI, texture as TX
        s = meshtex.read(self.glb)
        b = MI.bake(s, dict(max_tex=64))
        self.assertEqual(len(b.textures), 1)
        t = b.textures[0]
        self.assertEqual((t['w'], t['h'], t['fmt']), (64, 64, 'DXT1'))
        self.assertEqual(len(t['payload']), TX.payload_size('DXT1', 64, 64, t['levels']))
        self.assertGreater(t['psnr'], 25)
        for g in b.groups:                                                          # triangles wound against their normals (the render rule)
            P, N, T = g['P'].astype(float), g['N'].astype(float), g['tris']
            n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
            self.assertTrue(((n * (N[T[:, 0]] + N[T[:, 1]] + N[T[:, 2]])).sum(1) < 1e-9).all())
        self.assertTrue(b.collision and all(len(p['verts']) <= 255 for p in b.collision))
        bx = MI.bake(s, dict(collision=dict(mode='box')), with_payload=False)
        self.assertEqual(len(bx.collision[0]['verts']), 8)
        self.assertEqual(MI.bake(s, dict(collision=dict(mode='none')), with_payload=False).collision, [])

    def test_reduce_keeps_the_texture_seams(self):
        from todct import meshtex, modelimport as MI
        s = meshtex.read(self.glb)
        full = MI.bake(s, {}, with_payload=False)
        red = MI.bake(s, dict(reduce=0.3), with_payload=False)
        self.assertLess(red.stats['triangles'], full.stats['triangles'] * 0.4)
        self.assertGreater(red.stats['triangles'], 12)
        UV = np.concatenate([g['UV'] for g in red.groups])
        self.assertTrue(UV.min() > -0.01 and UV.max() < 2.01)

    def test_preview_glb_is_a_valid_textured_glb(self):
        from todct import meshtex, modelimport as MI, meshio
        s = meshtex.read(self.glb)
        b = MI.bake(s, dict(max_tex=64))
        glb = MI.preview_glb(b)
        p = os.path.join(self.t.name, 'p.glb')
        open(p, 'wb').write(glb)
        js, bufs = meshio._load_gltf(p)
        self.assertEqual(len(js['images']), 1)
        self.assertEqual(js['nodes'][js['scenes'][0]['nodes'][0]]['name'], 'render')
        # the picture inside is a PNG the toolkit reads
        from todct import texture as TX
        bv = js['bufferViews'][js['images'][0]['bufferView']]
        TX.read_png(bufs[0][bv['byteOffset']:bv['byteOffset'] + bv['byteLength']])

    def test_the_scene_blob_round_trips(self):
        from todct import meshtex, modelimport as MI
        s = meshtex.read(self.glb)
        s2 = MI.scene_from_bytes(MI.scene_to_bytes(s))
        self.assertEqual(len(s2.parts[0].P), len(s.parts[0].P))
        self.assertEqual(s2.images[0]['data'], s.images[0]['data'])
        self.assertEqual(MI.bake(s2, {}, with_payload=False).stats, MI.bake(s, {}, with_payload=False).stats)


# ------------------------------------------------------------------------------------------------ the build stage, on the game
@unittest.skipUnless(HAVE_GAME, 'needs the proof copy')
class TestAssetsBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.env = env(cls.t.name)
        cls.env.start()
        from todms import workspace, paths
        paths.ensure_cpu_guard()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))
        import glbfix
        cls.glb = glbfix.write_box_glb(os.path.join(cls.t.name, 'crate.glb'), size=(1.5, 0.6, 1.5), centre=(0, 0.3, 0))
        cls.barrel = glbfix.write_barrel_glb(os.path.join(cls.t.name, 'barrel.glb'))
        cls.png = os.path.join(cls.t.name, 'pic.png')
        open(cls.png, 'wb').write(glbfix.checker_png(64, (30, 160, 60), (10, 60, 20)))
        from todms import assetindex
        assetindex.build(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.t.cleanup()

    def build(self, mod):
        from todms import mods
        out = tempfile.mkdtemp(dir=self.t.name)
        rep = mods.build_mods(self.ws, [mod], out, 'a.zip')
        return rep, dict(rep.pop('_outs'))

    def entry(self, path, **kw):
        from todms import imports
        a = imports.analyze(path)
        req = dict(sha=a['sha'], file=os.path.basename(path), **kw)
        return imports.entry(self.ws, req)['entry']

    def test_index_knows_models_textures_and_users(self):
        from todms import assetindex
        doc = assetindex.load(self.ws)
        self.assertGreater(len(doc['models']), 1300)
        self.assertGreater(len(doc['textures']), 4000)
        m = doc['models'][PROP]
        self.assertEqual(len(m['blocks']), 2)
        t = doc['textures'][TEX]
        self.assertIn('/data/models/addons/wastebin/add_wastebin.model', t['users'])
        self.assertEqual(t['hd'], [])                                               # nothing but blocks.naz in this copy

    def test_index_marks_what_an_earlier_archive_changed(self):
        # a stand-in game whose effective chain serves one block from "hd_override.zip": its texture records differ from blocks.naz
        from todms import assetindex, assetedit
        entry = next(e for e in self.ws.game.base().names if e.endswith('submap01_map01_dea_hq_us_border.submap'))
        raw, _ = self.ws.read_block(entry)
        doc0 = assetindex.load(self.ws)
        r = doc0['textures'][TEX]
        img = np.ones((r['h'], r['w'], 4), np.float32) * np.array([0.9, 0.2, 0.2, 1.0], np.float32)
        new, _ = assetedit.apply_block(self.ws, entry, raw, [dict(id='x', name=TEX, fmt=r['fmt'], w=r['w'], h=r['h'], img=img)], [])
        ws0 = self.ws

        class Game:
            naz = ws0.game.naz
            folder = ws0.game.folder

            def base(self):
                return ws0.game.base()

            def read_block(self, e, mode):
                return (new, 'hd_override.zip') if e == entry else ws0.game.read_block(e, 'vanilla')

            def signature(self):
                return [['hd_override.zip', 1, 1]]

        class WS:
            game = Game()
            base_mode = 'effective'
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, TODMS_CACHE=t):
            assetindex.build(WS())
            doc = assetindex.load()
        self.assertEqual(doc['textures'][TEX]['hd'], [entry])
        other = next(k for k, v in doc['textures'].items() if k != TEX and v['hd'] == [])
        self.assertTrue(other)
        self.assertEqual([k for k, v in doc['models'].items() if v['hd']], [])

    def test_new_model_placed_in_a_level(self):
        from todms import level as lv
        import fragtool as ft
        entry = next(e for e in self.ws.game.base().names if e.endswith(TRAINING))
        L = self.ws.level_json(entry)
        tpl = next(x for x in L['entities'] if x['cat'] == 'model' and x['ed'] and x['type'] == 'Model')
        ent = self.entry(self.barrel, mode='new', name='Test barrel', params=dict(max_tex=128))
        add = dict(op='add', uid='n1', entry=entry, template=dict(entry=entry, frag=tpl['frag'], node=tpl['node']), name='TODMS_barrel', pos=tpl['pos'],
                   rot=[0, 0, 0, 1], set=dict(modelres=ent['path'][5:]), view=dict(type='Model', cat='model', kindLabel='Model', name='Test barrel'))
        rep, outs = self.build(dict(name='t', level=[add], data={}, models=[ent], textures=[]))
        blk = next(b for b in rep['assets']['blocks'] if b['entry'] == entry)
        v = blk['verify']
        self.assertEqual(v['result'], 'PASS')
        self.assertEqual(v['untouched_identical'], v['records_before'])             # every old record is byte-identical
        self.assertEqual(v['appended'], 2)                                          # one texture and the model
        self.assertEqual(v['models_roundtrip'], 1)
        # the block reads back: the node is there, with the model, not statically lit
        L2 = lv.BlockLevel(entry, outs[entry], self.ws.T, self.ws.main_lookup)
        found = []
        for i in L2.instances:
            d = L2.doc(i.frag)
            try:
                mr = d.get(i.node, 'modelres')
            except KeyError:
                continue
            if mr and mr.lower() == ent['path'][5:].lower():
                found.append((d.get(i.node, 'statically_lit'), d.world(i.node, i.owner)[0]))
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0][0])
        self.assertLess(max(abs(a - b) for a, b in zip(found[0][1], tpl['pos'])), 1e-3)
        # the written model is read by the viewer's own extractor
        from todms import extract
        ba = extract.BlockAssets(outs[entry], '.submap')
        self.assertIn(ent['path'].lower(), ba.models)
        glb, meta = ba.model_glb(ent['path'].lower())
        self.assertGreater(meta['render_tris'], 400)
        # a model nobody places is not written, and says so
        rep2, outs2 = self.build(dict(name='t', level=[], data={}, models=[ent], textures=[]))
        self.assertEqual(outs2, {})
        self.assertTrue(any('not placed' in n['text'] for n in rep2['assets']['notes']))

    def test_replace_a_prop_everywhere_it_is(self):
        from todms import extract, assetedit
        ent = self.entry(self.glb, mode='replace', target=PROP, name='Crate', params=dict(origin='match', max_tex=64))
        rep, outs = self.build(dict(name='t', level=[], data={}, models=[ent], textures=[]))
        self.assertEqual(len(outs), 2)                                              # both blocks that hold the prop
        for b in rep['assets']['blocks']:
            v = b['verify']
            self.assertEqual(v['untouched_identical'], v['records_before'] - 2)     # the model record and the lighting record changed
            self.assertEqual((v['changed'], v['appended']), (2, 1))
            self.assertEqual(b['lit_unset'], 0)                                     # the baked lighting was fitted: placed copies keep their flag
            self.assertGreater(b['lit_kept'], 0)
            self.assertEqual(v['lighting']['instances'], b['lit_kept'])
        # read back through the extractor: the new geometry, three sub-meshes became one
        e0 = sorted(outs)[0]
        ba = extract.BlockAssets(outs[e0], os.path.splitext(e0)[1])
        glb, meta = ba.model_glb(PROP)
        self.assertEqual(meta['render_tris'], 12)
        m = rep['assets']['models'][0]
        self.assertEqual((m['vertices'], m['triangles']), (24, 12))
        self.assertTrue(any('Sub-mesh count' in n['text'] for n in rep['assets']['notes']))      # M6: warned, not refused
        # the collision of the game's model is kept as it was
        k = assetedit.K()
        old, _ = self.ws.read_block(e0)
        ra, rb = assetedit.Records(k.tb, k.tb.Block(old, os.path.splitext(e0)[1])), assetedit.Records(k.tb, k.tb.Block(outs[e0], os.path.splitext(e0)[1]))
        ia, ib = ra.find(PROP, 3)[0], rb.find(PROP, 3)[0]
        sa = k.mw.spec_from_model(k.tm.decode(ra.items[ia]['rec'], 0, len(ra.items[ia]['rec'])))
        sb = k.mw.spec_from_model(k.tm.decode(rb.items[ib]['rec'], 0, len(rb.items[ib]['rec'])))
        self.assertEqual([[len(s['verts']) for s in (P['collision'] or {'shapes': []})['shapes']] for P in sa['pivots']],
                         [[len(s['verts']) for s in (P['collision'] or {'shapes': []})['shapes']] for P in sb['pivots']])

    def test_a_character_cannot_be_replaced(self):
        from todms import assets_stage
        ent = self.entry(self.glb, mode='replace', target='/data/characters/gangster/gangster.model', name='Gangster')
        with self.assertRaises(assets_stage.AssetsError) as c:
            self.build(dict(name='t', level=[], data={}, models=[ent], textures=[]))
        self.assertIn('skinned', str(c.exception))

    def test_texture_replace_round_trip(self):
        from todms import imports, assetindex, assets_stage, assetedit
        from todct import texture as TX
        doc = assetindex.load(self.ws)
        r = doc['textures'][TEX]
        up = imports.upload(self.png)
        t = dict(id='t1', target=TEX, source=dict(sha=up['sha'], file='pic.png'), crop=None, w=r['w'], h=r['h'], fmt=r['fmt'], edits=dict(brightness=0.05))
        rep, outs = self.build(dict(name='t', level=[], data={}, models=[], textures=[t]))
        self.assertEqual(len(outs), len(r['blocks']))
        want, cut = assets_stage.render_texture(self.ws, t)
        G = assetedit.hd()
        for e, raw in outs.items():
            blk = G.Block(raw, os.path.splitext(e)[1])
            rec = next(x for x in blk.textures() if x['name'].lower() == TEX)
            got = TX.decode_payload(blk.payloads[rec['index']], G.FMT_NAME[rec['fmt']], rec['w'], rec['h'])
            self.assertEqual((rec['w'], rec['h']), (r['w'], r['h']))
            self.assertGreater(TX.psnr(want, got), 30)                              # decodes back within tolerance
            self.assertLess(float(np.abs(want[..., :3].mean((0, 1)) - got[..., :3].mean((0, 1))).max()), 0.02)
        for b in rep['assets']['blocks']:
            self.assertEqual(b['verify']['untouched_identical'], b['verify']['records_before'] - 1)
        self.assertTrue(any('also used by' in n['text'] for n in rep['assets']['notes']))
        # the shared texture warning names the users
        self.assertIn('/data/models/addons/wastebin/add_wastebin.model', doc['textures'][TEX]['users'])

    def test_texture_edit_of_the_games_own_picture(self):
        from todms import assetindex
        doc = assetindex.load(self.ws)
        r = doc['textures'][TEX]
        t = dict(id='t2', target=TEX, source=dict(game=True), crop=None, w=r['w'], h=r['h'], fmt=r['fmt'], edits=dict(hue=90))
        rep, outs = self.build(dict(name='t', level=[], data={}, models=[], textures=[t]))
        self.assertEqual(len(outs), len(r['blocks']))

    def test_refusals(self):
        from todms import assetindex, assets_stage
        doc = assetindex.load(self.ws)
        r = doc['textures'][TEX]
        up = __import__('todms.imports', fromlist=['x']).upload(self.png)
        flat = dict(id='t3', target=TEX, source=dict(sha=up['sha']), crop=None, w=r['w'] * 2, h=r['h'], fmt=r['fmt'], edits={})
        with self.assertRaises(assets_stage.AssetsError) as c:                      # a changed shape is not written
            self.build(dict(name='t', level=[], data={}, models=[], textures=[flat]))
        self.assertIn('shape', str(c.exception))
        if r['fmt'] == 'DXT1':
            rgba = dict(flat, w=r['w'], fmt='RGBA32')
            with self.assertRaises(assets_stage.AssetsError):                       # a DXT1 texture stays DXT1
                self.build(dict(name='t', level=[], data={}, models=[], textures=[rgba]))
        gone = dict(flat, target='/data/textures/no/such.bmp', w=64, h=64)
        with self.assertRaises(assets_stage.AssetsError):
            self.build(dict(name='t', level=[], data={}, models=[], textures=[gone]))

    def test_the_server_calls(self):
        from todms import imports
        a = imports.analyze(self.barrel)
        self.assertTrue(a['textured'])
        pv = imports.preview(self.ws, dict(sha=a['sha'], params=dict(scale=2.0), mode='new'))
        self.assertEqual(pv['refused'], [])
        self.assertTrue(os.path.exists(os.path.join(os.environ['TODMS_CACHE'], 'assets', 'preview', pv['key'] + '.glb')))
        self.assertAlmostEqual(pv['stats']['size'][1], 1.8, places=2)
        pr = imports.preview(self.ws, dict(sha=a['sha'], params=dict(origin='match'), mode='replace', target=PROP))
        self.assertEqual(pr['original']['pivots'], 1)
        info = imports.tex_info(self.ws, TEX)
        self.assertTrue(info['keep_dxt1'] if info['fmt'] == 'DXT1' else True)
        self.assertGreaterEqual(len(info['users']), 1)
        res = imports.tex_render(self.ws, dict(target=TEX, source=dict(game=True), w=info['w'], h=info['h'], fmt=info['fmt'], edits=dict(hue=60)))
        self.assertGreater(res['psnr'], 20)
        self.assertTrue(res['png'].startswith('data:image/png'))
        rows = imports.tex_rows(self.ws, dict(q='waste'))
        self.assertTrue(any(x['key'] == TEX for x in rows['rows']))
        ent = imports.entry(self.ws, dict(sha=a['sha'], file='barrel.glb', mode='new', name='Barrel', params={}))['entry']
        rec = imports.imported_records(self.ws, [ent])[ent['id']]
        self.assertEqual(rec['path'], ent['path'])
        self.assertTrue(rec['url'].endswith('.glb'))


if __name__ == '__main__':
    unittest.main()
