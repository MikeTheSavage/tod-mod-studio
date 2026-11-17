"""Large-scene import: streamed glb, region cut, clean-up, pictures (dedupe, atlas, alpha), chunk budgets, collision, recipe output.

Everything runs on small synthetic scenes made in code (tests/scenefix.py); no real capture is read.
"""
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
import scenefix  # noqa: E402


def env(tmp):
    return patch.dict(os.environ, TODMS_HOME=os.path.join(tmp, 'home'), TODMS_CACHE=os.path.join(tmp, 'cache'), TODMS_SAVES=os.path.join(tmp, 'saves'))


REGION = [[-70, -70], [70, -70], [70, 70], [-70, 70]]


def params(**kw):
    p = dict(scale=1.0, region=dict(polygon=REGION, mode='clip'), name='TestScene')
    p.update(kw)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='scene_')
        self.p = env(self.tmp)
        self.p.start()
        self.glb = os.path.join(self.tmp, 'city.glb')
        self.info = scenefix.city(self.glb)

    def tearDown(self):
        self.p.stop()
        from todms import sceneimport as SI
        for s in list(SI.SESSIONS.values()):
            s.close()
        SI.SESSIONS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, path=None):
        from todms import sceneimport as SI
        return SI.open_scene(path or self.glb)


class TestIndex(Base):
    def test_open_counts_and_materials(self):
        r = self.open()
        self.assertEqual(r['prims'], self.info['prims'])
        self.assertEqual(r['triangles'], self.info['tris'])
        self.assertEqual(r['materials'], 6)          # asphalt, brick_a, brick_b, grass, fence, sign (as classes)
        self.assertEqual(r['images'], 6)

    def test_zup_node_turn_gives_the_same_geometry(self):
        a = self.open()
        z = os.path.join(self.tmp, 'zup.glb')
        scenefix.city(z, zup=True)
        b = self.open(z)
        self.assertTrue(b['up_guess']['turned'])
        self.assertFalse(a['up_guess']['turned'])
        np.testing.assert_allclose(a['extent'], b['extent'], atol=1e-3)
        np.testing.assert_allclose(a['min'], b['min'], atol=1e-3)

    def test_overview_covers_the_scene(self):
        from todms import sceneimport as SI
        r = self.open()
        ov = SI.overview(r['sid'], dict(up='y', mirror='z'))
        self.assertTrue(ov['png'].startswith('data:image/png;base64,'))
        self.assertGreater(ov['max'][0] - ov['min'][0], 900)       # the stray island is in the overview


class TestRegion(Base):
    def test_counts_clip_and_whole(self):
        from todms import sceneimport as SI
        r = self.open()
        full = SI.count_region(r['sid'], params())
        half = SI.count_region(r['sid'], params(region=dict(polygon=[[-70, -70], [0, -70], [0, 70], [-70, 70]], mode='clip')))
        self.assertLess(half['triangles'], full['triangles'])
        self.assertGreater(half['triangles'], 0)
        whole = SI.count_region(r['sid'], params(region=dict(polygon=[[-70, -70], [0, -70], [0, 70], [-70, 70]], mode='whole')))
        self.assertGreaterEqual(whole['triangles'], half['triangles'])
        self.assertEqual(full['materials'], 6)
        self.assertLessEqual(full['textures'], 6)

    def test_island_is_outside_the_region(self):
        from todms import sceneimport as SI
        r = self.open()
        c = SI.count_region(r['sid'], params(region=dict(polygon=[[800, -1000], [1000, -1000], [1000, -800], [800, -800]], mode='clip')))
        self.assertEqual(c['triangles'], 10)                        # five faces of the island box, two triangles each (the game's z is mirrored)

    def test_scale_changes_the_selection(self):
        from todms import sceneimport as SI
        r = self.open()
        a = SI.count_region(r['sid'], params(scale=1.0))
        b = SI.count_region(r['sid'], params(scale=0.5))
        self.assertEqual(a['triangles'], b['triangles'])          # same triangles inside a region that holds the whole city either way
        small = SI.count_region(r['sid'], params(scale=2.0))
        self.assertLess(small['triangles'], a['triangles'])

    def test_selection_is_centred_at_place(self):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        sel = SI.select(sess, SI.merged(params(place=[10, 0, -5])))
        P = sel['soup'].P
        self.assertAlmostEqual(float((P[:, 0].min() + P[:, 0].max()) / 2), 10.0, places=3)
        self.assertAlmostEqual(float(P[:, 1].min()), 0.0, places=4)
        self.assertAlmostEqual(float((P[:, 2].min() + P[:, 2].max()) / 2), -5.0, places=3)


class TestClean(Base):
    def run_clean(self, region=None, **clean):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        p = SI.merged(params(clean=clean, **({'region': region} if region else {})))
        return SI.run_clean(sess, p)

    def test_duplicates_and_strays_are_removed_and_reported(self):
        big = dict(polygon=[[-1000, -1000], [1000, -1000], [1000, 1000], [-1000, 1000]], mode='clip')
        res = self.run_clean(region=big)
        rep = res['report']
        self.assertGreater(rep['exact'], 0)                         # the second road draw is a copy of the third
        self.assertGreater(rep['near'], 0)                          # and both lie 1 mm over the ground
        self.assertEqual(rep['far_islands'] + rep['tiny_islands'], 1)  # the island 900 m away
        self.assertGreater(rep['far'], 0)
        P = res['soup'].P
        self.assertLess(float(P[:, 0].max() - P[:, 0].min()), 200)      # the island is gone: only the 120 m block is left
        self.assertEqual(rep['triangles_out'], res['soup'].tris)

    def test_zup_equals_yup_after_clean(self):
        from todms import sceneimport as SI
        a = self.run_clean()
        z = os.path.join(self.tmp, 'zup.glb')
        scenefix.city(z, zup=True)
        r = SI.open_scene(z)
        b = SI.run_clean(SI.get(r['sid']), SI.merged(params()))
        self.assertEqual(a['soup'].tris, b['soup'].tris)
        np.testing.assert_allclose(np.sort(a['soup'].P[:, 1]), np.sort(b['soup'].P[:, 1]), atol=1e-3)

    def test_strays_can_be_kept(self):
        big = dict(polygon=[[-1000, -1000], [1000, -1000], [1000, 1000], [-1000, 1000]], mode='clip')
        res = self.run_clean(region=big, strays=False)
        self.assertEqual(res['report']['far'], 0)

    def test_deterministic(self):
        a = self.run_clean()
        b = self.run_clean()
        self.assertEqual(a['soup'].digest(), b['soup'].digest())
        from todct import scenekit as SK
        c, _ = SK.clean(a['soup'])
        self.assertEqual(c.digest(), a['soup'].digest())            # clean of a clean scene changes nothing

    def test_split_vertices_are_welded(self):
        from todct import scenekit as SK
        P = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32)
        N = np.tile(np.array([[0, 1, 0]], np.float32), (6, 1))
        UV = np.array([[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]], np.float32)
        soup = SK.Soup(P, N, UV, np.zeros(6, np.int32), np.array([[0, 1, 2], [3, 4, 5]], np.int64))
        out, rep = SK.clean(soup)
        self.assertEqual(rep['vertices_welded'], 2)
        self.assertEqual(len(out.P), 4)
        self.assertEqual(out.tris, 2)


class TestTextures(Base):
    def prep(self, **tex):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        p = SI.merged(params(textures=tex))
        return sess, p, SI.run_textures(sess, p)

    def test_same_pixels_are_one_picture(self):
        _, _, t = self.prep(atlas=False)
        rep = t['report']
        self.assertEqual(rep['classes'], 6)
        self.assertEqual(rep['slots'], 5)                           # brick_a and brick_b share their pixels
        self.assertEqual(rep['duplicates_merged'], 1)
        names = {t_['name'] for t_ in t['textures']}
        self.assertEqual(len(names), 5)

    def test_shoulder_keeps_highlight_detail(self):
        from todms import sceneimport as SI
        v = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        out = SI.shoulder(v * 1.6)
        self.assertTrue((np.diff(out) > 0).all())                         # strictly rising: no flat clipped plateau
        self.assertLess(float(out.max()), 1.0)
        self.assertAlmostEqual(float(SI.shoulder(0.5)), 0.5, places=6)    # below the knee nothing changes
        hard = np.clip(v * 1.6, 0, 1)
        self.assertGreater(int((hard >= 1.0).sum()), 60)                  # a hard clip would flatten a big part of the range
        self.assertEqual(int((out >= 0.999).sum()), 0)

    def test_exposure_does_not_clip_light_pictures(self):
        _, p, t = self.prep(atlas=False)
        self.assertIn('highlight', t['report'])
        self.assertGreaterEqual(t['report']['exposure'], 1.0)
        self.assertLessEqual(t['report']['exposure'], 2.5)
        # the gain is capped so the weighted 99th percentile of the highlights stays within exposure_peak before the shoulder
        self.assertLessEqual(t['report']['exposure'] * t['report']['highlight'], 1.3 + 1e-3 + (0 if t['report']['exposure'] > 1.0 else 10))

    def test_explicit_exposure_goes_through_the_shoulder(self):
        _, p, t = self.prep(atlas=False, exposure=2.0)
        self.assertEqual(t['report']['exposure'], 2.0)
        import io
        from PIL import Image
        for tx in t['textures']:
            from todms import assetstore
            pic = np.asarray(Image.open(io.BytesIO(assetstore.get(tx['sha']))).convert('RGB'))
            self.assertLess(int(pic.max()), 255)                            # nothing reaches pure white through the shoulder

    def test_alpha_kinds_and_formats(self):
        _, _, t = self.prep(atlas=False)
        kinds = set(t['class_kind'].values())
        self.assertEqual(kinds, {'opaque', 'cutout'})
        fmt = {x['alpha']: x['format'] for x in t['textures']}
        self.assertEqual(fmt['cutout'], 'RGBA32')
        self.assertEqual(fmt['opaque'], 'DXT1')

    def test_override_alpha(self):
        sess, p, t = self.prep(atlas=False)
        cutout_class = [c for c, k in t['class_kind'].items() if k == 'cutout'][0]
        from todms import sceneimport as SI
        p2 = SI.merged(params(textures=dict(atlas=False, alpha={str(cutout_class): 'opaque'})))
        t2 = SI.run_textures(sess, p2)
        self.assertEqual(set(t2['class_kind'].values()), {'opaque'})

    def test_tiling_texture_is_not_atlased(self):
        _, _, t = self.prep(atlas=True, atlas_max_px=64)
        self.assertGreaterEqual(t['report']['wrapping'], 1)         # the ground's uv runs 0..6
        ground = [c for c, v in t['class_tex'].items() if not v.get('tile')]
        self.assertTrue(ground)
        for c in ground:
            self.assertEqual(t['class_tex'][c]['xf'], [1.0, 1.0, 0.0, 0.0])

    def test_atlas_remaps_uv_inside_its_tile(self):
        from todms import sceneimport as SI
        sess, p, t = self.prep(atlas=True, atlas_max_px=64)
        tiled = {c: v for c, v in t['class_tex'].items() if v.get('tile')}
        self.assertTrue(tiled)
        self.assertGreater(t['report']['atlased'], 1)
        cl = SI.run_clean(sess, p)
        soup = cl['soup']
        for c, v in tiled.items():
            m = soup.VM == c
            uv = soup.UV[m].astype(np.float64)
            sx, sy, ox, oy = v['xf'][0], v['xf'][1], v['xf'][2], v['xf'][3]
            out = uv * np.array([sx, sy]) + np.array([ox, oy])
            self.assertTrue((out >= 0).all() and (out <= 1).all())

    def test_whole_repeat_shift_is_atlased_with_the_offset(self):
        from todms import sceneimport as SI
        sess, p, t = self.prep(atlas=True, atlas_max_px=64)
        sign = [i for i, c in enumerate(sess.classes) if c['name'] == 'sign'][0]
        self.assertTrue(t['class_tex'][sign].get('tile'))
        soup = SI.run_clean(sess, p)['soup']
        sx, sy, ox, oy = t['class_tex'][sign]['xf']
        uv = soup.UV[soup.VM == sign].astype(np.float64) * np.array([sx, sy]) + np.array([ox, oy])
        self.assertTrue((uv >= 0).all() and (uv <= 1).all())
        # the picture is the same one the plain sign would show: uv 0..1 of the file maps to the tile
        self.assertTrue(float(uv.max() - uv.min()) > 0)

    def test_atlas_page_is_no_bigger_than_its_tiles(self):
        _, _, t = self.prep(atlas=True, atlas_max_px=64)
        pages = [x for x in t['textures'] if x['atlas']]
        self.assertTrue(pages)
        for x in pages:
            self.assertLessEqual(x['size'], 64)

    def test_texture_budget_shrinks_pictures(self):
        _, _, big = self.prep(atlas=False, max_tex=256)
        _, _, small = self.prep(atlas=False, max_tex=256, budget_mb=0.001)
        self.assertLess(small['report']['bytes'], big['report']['bytes'])
        self.assertGreater(small['report']['shrunk'], 0)

    def test_every_texture_is_within_the_engine_rules(self):
        from todct import texture as TX
        _, _, t = self.prep()
        for x in t['textures']:
            self.assertTrue(TX.is_pow2(x['size']))
            self.assertLessEqual(x['bytes'], 1351384)
            self.assertEqual(x['bytes'], TX.payload_size(x['format'], x['size'], x['size'], TX.full_chain(x['size'], x['size'])))


class TestChunks(Base):
    def chunks(self, **sec):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        p = SI.merged(params(sections=sec))
        return SI.run_chunks(sess, p), sess, p

    def test_defaults_make_sections_and_objects(self):
        ch, _, _ = self.chunks(section_m=64)
        self.assertGreater(len(ch['sections']), 1)
        self.assertGreaterEqual(len(ch['objects']), len(ch['sections']))
        self.assertEqual(sum(o['tris'] for o in ch['objects']), ch['stats']['tris_out'])

    def test_object_budget_splits_cells(self):
        small, _, _ = self.chunks(object_verts=60, object_bytes=3000, min_cell=2)
        large, _, _ = self.chunks()
        self.assertGreater(len(small['objects']), len(large['objects']))
        for o in small['objects']:
            self.assertLessEqual(o['max_submesh'], 60000)
        self.assertLessEqual(max(o['max_submesh'] for o in small['objects']), 120)

    def test_every_triangle_lands_in_exactly_one_object(self):
        from todms import sceneimport as SI
        ch, sess, p = self.chunks(object_verts=80, object_bytes=4000, min_cell=2)
        cl = SI.run_clean(sess, p)
        seen = np.concatenate([o['idx'] for o in ch['objects']])
        self.assertEqual(len(seen), len(np.unique(seen)))
        self.assertEqual(len(seen), cl['soup'].tris)

    def test_section_budget_reduces_triangles(self):
        full, _, _ = self.chunks(section_m=200, section_tris=1000000)
        cut, _, _ = self.chunks(section_m=200, section_tris=200)
        self.assertEqual(full['stats']['reduced_objects'], 0)
        self.assertGreater(cut['stats']['reduced_objects'], 0)
        self.assertLess(cut['stats']['tris_out'], full['stats']['tris_out'])
        self.assertEqual(cut['stats']['tris_in'], full['stats']['tris_in'])
        meters = {m['id']: m for m in cut['meters']}
        self.assertIn('G2', meters)

    def test_double_sided_cutout_gets_reversed_copies(self):
        a, _, _ = self.chunks(double_sided=True)
        b, _, _ = self.chunks(double_sided=False)
        self.assertGreater(a['stats']['tris_out'], b['stats']['tris_out'])

    def test_deterministic_models(self):
        from todms import sceneimport as SI
        a, _, _ = self.chunks()
        b, _, _ = self.chunks()
        pa = [json.dumps(o['mesh'].part(), sort_keys=True) for o in a['objects']]
        pb = [json.dumps(o['mesh'].part(), sort_keys=True) for o in b['objects']]
        self.assertEqual(pa, pb)


class TestCollision(Base):
    def test_pieces_within_the_engine_limits(self):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        p = SI.merged(params())
        co = SI.run_collision(sess, p)
        self.assertGreater(co['stats']['pieces'], 5)
        self.assertLessEqual(co['stats']['max_hull_verts'], 255)
        self.assertLessEqual(co['stats']['max_hulls'], 2000)
        self.assertGreater(co['stats']['skipped_cutout'], 0)       # the fence has none
        for pcs in co['per_object'].values():
            for pc in pcs:
                self.assertLessEqual(len(pc['points']), 255)

    def test_collision_can_be_switched_off(self):
        from todms import sceneimport as SI
        r = self.open()
        co = SI.run_collision(SI.get(r['sid']), SI.merged(params(collision=dict(enabled=False))))
        self.assertEqual(co['stats']['pieces'], 0)

    def test_floor_is_solid_under_the_arrival(self):
        from todms import sceneimport as SI
        r = self.open()
        sess = SI.get(r['sid'])
        p = SI.merged(params())
        cl = SI.run_clean(sess, p)
        ar = SI.arrival_spot(cl['soup'])
        co = SI.run_collision(sess, p)
        ch = SI.run_chunks(sess, p)
        hit = False
        for ob in ch['objects']:
            o = np.array(ob['origin'])
            for pc in co['per_object'].get(ob['id'], []):
                pts = pc['points'] + o
                lo, hi = pts.min(0), pts.max(0)
                if lo[0] <= ar[0] <= hi[0] and lo[2] <= ar[2] <= hi[2] and lo[1] <= ar[1] - 1.0 <= hi[1] + 0.3:
                    hit = True
        self.assertTrue(hit)


class TestSend(Base):
    def send(self, **kw):
        from todms import sceneimport as SI
        r = self.open()
        return SI.send(r['sid'], params(**kw), dict(kind='newmap', name='TestScene')), r

    def test_project_is_small_and_has_one_placement_per_object(self):
        from todms import newmap, sceneimport as SI
        res, r = self.send(sections=dict(object_verts=100, object_bytes=5000, min_cell=2))
        proj = newmap.get_project(res['id'])['params']
        m = proj['maps'][0]
        ng = m['new_geometry']
        self.assertEqual(len(ng['models']), len(ng['placements']))
        self.assertEqual(len(ng['models']), res['models'])
        self.assertLess(len(json.dumps(proj)), 400000)
        for md in ng['models']:
            self.assertEqual(md['parts'][0]['type'], 'mapgen')
            self.assertIn('ref', md['parts'][0])
        for t in ng['textures']:
            self.assertTrue(t['kind'].startswith('scene:'))
        self.assertEqual(m['placement'] if 'placement' in m else 'separate', 'separate')
        self.assertEqual(m['scene']['kind'], 'scene')

    def test_parts_read_back_and_fit_the_engine(self):
        from todms import newmap
        from todms.mapgen import meshkit
        res, _ = self.send()
        ng = newmap.get_project(res['id'])['params']['maps'][0]['new_geometry']
        tex = {t['name'] for t in ng['textures']}
        tris = 0
        for md in ng['models']:
            meshes, hulls = meshkit.read_part(md['parts'][0])
            for me in meshes:
                self.assertIn(me['tex'], tex)
                self.assertLessEqual(len(me['P']), 60000)
                self.assertEqual(int(me['I'].max()) < len(me['P']), True)
                tris += len(me['I'])
            for pts, surf, mat in hulls:
                self.assertLessEqual(len(pts), 255)
        self.assertGreater(tris, 100)

    def test_ledger_sees_the_scene(self):
        from todms import newmap, mapgen, ledger
        res, _ = self.send()
        params_ = newmap.get_project(res['id'])['params']
        full = mapgen.expand_full(params_)
        st = list(full['stats'].values())[0]
        self.assertGreater(st['triangles'], 100)
        ring = (st.get('backdrop') or {}).get('models', 0)                                     # the far towers are models too
        self.assertEqual(st['models'], len(params_['maps'][0]['new_geometry']['models']) + len(params_['maps'][0].get('water') or []) + ring)     # and the sea tiles
        rows = {r['id']: r for r in ledger.mapgen_rows(full['stats'])}
        self.assertGreater(rows['G2']['used'], 0)
        self.assertGreater(rows['M1']['used'], 0)
        self.assertGreater(rows['P6']['used'], 0)
        self.assertEqual(rows['M1']['status'], 'ok')

    def test_scene_texture_kind_reaches_the_builder_generator(self):
        from todms import newmap, mapgen
        res, _ = self.send()
        ng = newmap.get_project(res['id'])['params']['maps'][0]['new_geometry']
        full = mapgen.expand_full(newmap.get_project(res['id'])['params'])
        sys.path.insert(0, os.path.join(ROOT, 'backend', 'vendor', 'newmap'))
        import tex_gen
        for t in ng['textures']:
            img = tex_gen.generate(t['kind'], t['size'], t['seed'])
            self.assertEqual(img.shape[:2], (t['size'], t['size']))
            self.assertEqual(img.shape[2], 3 if t['format'] == 'DXT1' else 4)
            self.assertTrue(np.isfinite(img).all())
        self.assertTrue(full['params']['maps'][0]['new_geometry']['models'])

    def test_resend_is_byte_identical(self):
        from todms import newmap
        a, r = self.send()
        pa = json.dumps(newmap.get_project(a['id'])['params'], sort_keys=True)
        from todms import sceneimport as SI
        b = SI.send(r['sid'], params(), dict(kind='newmap', name='TestScene', id=a['id']))
        pb = json.dumps(newmap.get_project(b['id'])['params'], sort_keys=True)
        pa2 = json.loads(pa)
        pa2.pop('uid', None)
        pb2 = json.loads(pb)
        pb2.pop('uid', None)
        self.assertEqual(json.dumps(pa2, sort_keys=True), json.dumps(pb2, sort_keys=True))

    def test_map_name_has_the_clone_sources_length(self):
        from todms import newmap, sceneimport as SI
        res, _ = self.send()
        m = newmap.get_project(res['id'])['params']['maps'][0]
        self.assertEqual(len(m['name']), 18)
        self.assertEqual(m['new_geometry']['folder'], m['name'])
        self.assertEqual(SI.map_name_for('A long title that does not fit at all'), 'Map11_ALongTitleAt')
        self.assertEqual(len(SI.map_name_for('x')), 18)

    def test_section_needs_a_host(self):
        from todms import sceneimport as SI
        r = self.open()
        with self.assertRaises(SI.SceneError):
            SI.send(r['sid'], params(), dict(kind='section', name='X'))


class TestSamples(Base):
    def test_preview_glbs(self):
        from todms import sceneimport as SI
        r = self.open()
        s = SI.sample_glb(r['sid'], dict(up='y', mirror='z'), [0, 0], 30)
        self.assertTrue(s['url'].endswith('.glb'))
        d = SI.stage_glb(r['sid'], params(), 'clean')
        self.assertGreater(d['triangles'], 100)
        from todms import paths
        self.assertTrue(os.path.exists(os.path.join(paths.cache_dir(), 'scene', 'preview', os.path.basename(d['url']))))

    def test_report_runs_every_stage(self):
        from todms import sceneimport as SI
        r = self.open()
        rep = SI.report(r['sid'], params(), 'collision')
        for k in ('select', 'clean', 'textures', 'chunks', 'collision'):
            self.assertIn(k, rep)
        self.assertTrue(all(m['id'] for m in rep['chunks']['meters']))


if __name__ == '__main__':
    unittest.main()
