"""Lighting phase 2: the baked lighting of a replaced model is fitted to its new meshes (todms.lightfit, TOD HD's lighting code).

The game tests use a proof copy of the game in env TODMS_PROOF (skipped when unset); they work on copies of single blocks in memory.
"""
import copy
import hashlib
import json
import os
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
PROP = '/data/models/addons/weaponammocrate/weaponammocratewoodopen.model'          # three single-colour meshes, in two blocks
VENT = '/data/models/addons/airvents/airvent_doubble.model'                         # five meshes, per-vertex baked colours
INDUSTRIAL = 'submap03_map03_lostoros_industrial.submap'
TRAINING = 'submap05_map02_lostoros_downtown_training.submap'


class TestPieces(unittest.TestCase):
    def test_vendored_copies_match_the_record(self):
        d = os.path.join(ROOT, 'backend', 'vendor', 'hd')
        rec = json.load(open(os.path.join(d, 'HD.json')))
        for name in ('tod_hd_game.py', 'tod_hd_lighting.py', 'tod_hd_scatter.py'):
            b = open(os.path.join(d, name), 'rb').read()
            self.assertEqual(hashlib.sha256(b).hexdigest(), rec['files'][name]['sha256'], name)
            self.assertEqual(len(b), rec['files'][name]['bytes'])

    def test_pairing_takes_meshes_of_a_kind_in_order(self):
        from todms import lightfit
        self.assertEqual(lightfit.pairing([0, 0, 0], [0]), [(0, 0)])
        self.assertEqual(lightfit.pairing([0, 0, 1, 1], [0, 1]), [(0, 0), (1, 2)])
        with self.assertRaises(lightfit.LightError):
            lightfit.pairing([0], [0, 0])
        with self.assertRaises(lightfit.LightError):
            lightfit.pairing([0, 0], [0, 1])

    def test_nearest_vertex_and_mean_colour(self):
        from todms import lightfit
        old = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
        new = [(1, 0, 0), (9, 1, 0), (0, 8, 1), (5, 0, 0)]
        self.assertEqual(list(lightfit.nearest(old, new)), [0, 1, 2, 0])                  # ties go to the lowest index
        self.assertEqual(lightfit.mean_colour([0xFF102030, 0xFF304050]), 0xFF203040)
        self.assertEqual(lightfit.mean_colour([0xFFFFFFFF] * 3), 0xFFFFFFFF)


@unittest.skipUnless(HAVE_GAME, 'needs the proof copy')
class TestOnGameBlocks(unittest.TestCase):
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
        import glbfix
        cls.glb = glbfix.write_box_glb(os.path.join(cls.t.name, 'crate.glb'), size=(1.5, 0.6, 1.5), centre=(0, 0.3, 0))
        assetindex.build(cls.ws)
        cls.doc = assetindex.load(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.t.cleanup()

    def crate_entry(self):
        from todms import imports
        a = imports.analyze(self.glb)
        return imports.entry(self.ws, dict(sha=a['sha'], file='crate.glb', mode='replace', target=PROP, name='Crate',
                                           params=dict(origin='match', max_tex=64)))['entry']

    def swap(self, target, tail):
        """Replace `target` in the block whose name ends with `tail`: -> (entry, raw, new bytes, apply_block report)."""
        from todms import assets_stage, assetedit
        ent = self.crate_entry()
        ent = dict(ent, target=target)
        baked, _, _ = assets_stage.bake_model(self.ws, ent, self.doc)
        entry = next(e for e in self.doc['models'][target]['blocks'] if e.endswith(tail))
        raw, _ = self.ws.read_block(entry)
        job = dict(id=ent['id'], name='Crate', mode='replace', target=target, slug='r_test', baked=baked, shapes=None, keep_collision=True)
        new, rep = assetedit.apply_block(self.ws, entry, raw, [], [job])
        return entry, raw, new, rep

    def placed_uids(self, entry, raw, model):
        from todms import level as lv, assets_stage
        L = lv.BlockLevel(entry, raw, self.ws.T, self.ws.main_lookup)
        out = {}
        for i in L.instances:
            d = L.doc(i.frag)
            try:
                mr = d.get(i.node, 'modelres')
            except KeyError:
                continue
            if mr and lv.norm_model(mr) == model:
                out[assets_stage._uid(d, i.node)] = d.get(i.node, 'statically_lit')
        return out

    def test_single_colours_follow_the_new_mesh(self):
        from todms import lightfit
        entry, raw, new, rep = self.swap(PROP, INDUSTRIAL)
        lr = rep['lighting'][0]
        self.assertEqual(lr['status'], 'retargeted')
        self.assertEqual(sorted(lr['instances']), [163, 168, 179])
        self.assertEqual(rep['verify']['lighting']['instances'], 3)
        self.assertEqual(rep['verify']['untouched_identical'], rep['verify']['records_before'] - 2)
        json.dumps(lr)
        HL = lightfit.hl()
        old_rec = HL.lighting_records(raw, '.submap')[0]
        rec = HL.lighting_records(new, '.submap')[0]
        geo = lightfit.model_geometry(HL, new, '.submap', PROP)
        nv, ni = geo['pivots'][0][0]
        self.assertEqual((nv, ni), (24, 36))
        for inst in lr['instances']:
            e = HL.engine_lookup(rec, inst, 0, 0, nv, ni, True)
            self.assertGreaterEqual(e, 0)                                                   # the engine finds the new key
            self.assertEqual(HL.engine_lookup(rec, inst, 0, 0, 87, 128, True), -1)         # and no longer the old one
            olds = [HL.engine_lookup(old_rec, inst, 0, j, c[0], c[1], True) for j, c in enumerate([(87, 128), (36, 51), (8, 8)])]
            want = lightfit.mean_colour([old_rec['entries'][i]['colour'] for i in olds])
            self.assertEqual(rec['entries'][e]['colour'], want)                             # three meshes became one: the mean
        self.assertEqual(len(rec['entries']), len(old_rec['entries']))                      # nothing else in the lighting record moved
        self.assertEqual(len(rec['keys']), len(old_rec['keys']))
        placed = self.placed_uids(entry, new, PROP)                                         # placed copies keep statically_lit, every one is covered
        self.assertEqual(set(placed), {tuple(u) for u in lr['uids']})
        self.assertTrue(all(placed.values()))

    def test_per_vertex_colours_come_from_the_nearest_old_vertex(self):
        from todms import lightfit
        entry, raw, new, rep = self.swap(VENT, TRAINING)
        lr = rep['lighting'][0]
        self.assertEqual(lr['status'], 'retargeted')
        self.assertEqual(lr['regenerated'], len(lr['instances']))
        self.assertEqual(len(lr['instances']), 6)
        self.assertEqual(rep['verify']['lighting']['entries_regenerated'], 6)
        HL = lightfit.hl()
        G = lightfit._game()
        geo_new = lightfit.model_geometry(HL, new, '.submap', VENT)
        geo_old = lightfit.model_geometry(HL, raw, '.submap', VENT)
        nv, ni = geo_new['pivots'][0][0]
        bo, bn = G.Block(raw, '.submap'), G.Block(new, '.submap')
        old_rec, new_rec = HL._parse_block(bo)[0], HL._parse_block(bn)[0]
        P_new = np.asarray(geo_new['geometry'][0][0]['positions'])
        for inst in lr['instances']:
            pos = HL.engine_search(new_rec.keys, HL.build_key(inst, 0, 0, nv, ni, False))
            self.assertIsNotNone(pos)
            b = new_rec.entries[new_rec.values[pos]]['buffer']
            self.assertEqual((b['count'], b['index_count']), (nv, ni))
            cols = np.frombuffer(bn.payloads[new_rec.index], '<u4', b['count'], b['data_offset'])
            P, C = [], []                                                                   # every old near mesh of this instance, together
            for j, (vc, ic) in enumerate(geo_old['pivots'][0]):
                if geo_old['smb_flags'][0][j] & 1:
                    continue
                k = next(k for k, w in enumerate(old_rec.keys) if (w[1] & 0xFFFF) == inst and (w[0] & 0xFFFF) == j and (w[2] & 0xFFFFF) == vc)
                ob = old_rec.entries[old_rec.values[k]]['buffer']
                P.append(np.asarray(geo_old['geometry'][0][j]['positions']))
                C.append(np.frombuffer(bo.payloads[old_rec.index], '<u4', ob['count'], ob['data_offset']))
            P, C = np.concatenate(P), np.concatenate(C)
            for v in (0, nv // 2, nv - 1):
                d = ((P - P_new[v]) ** 2).sum(1)
                self.assertEqual(int(cols[v]), int(C[int(d.argmin())]))
            o = b['index_copy_offset']
            idx = np.frombuffer(bytes(bn.info[o:o + 2 * ni]), '<u2')
            self.assertEqual(list(idx), geo_new['geometry'][0][0]['indices'])
        placed = self.placed_uids(entry, new, VENT)
        self.assertEqual(set(placed), {tuple(u) for u in lr['uids']})                       # exactly this model's own placed copies
        self.assertTrue(all(placed.values()))

    def pre_light(self, target, tail):
        with patch.object(__import__('todms.lightfit', fromlist=['x']), 'retarget_model', side_effect=lambda data, *a, **k: (data, dict(status='none'))):
            return self.swap(target, tail)[2]

    def test_verify_catches_a_wrong_count_and_a_stray_change(self):
        from todms import lightfit
        entry, raw, new, rep = self.swap(PROP, INDUSTRIAL)
        pre = self.pre_light(PROP, INDUSTRIAL)
        self.assertTrue(lightfit.verify(pre, new, '.submap', rep['lighting']))
        bad = json.loads(json.dumps(rep['lighting']))
        bad[0]['patches'][0][2][2] += 1                                                     # a key whose vertex count is wrong
        with self.assertRaises(lightfit.LightError):
            lightfit.verify(pre, new, '.submap', bad)
        stray = bytearray(new)
        stray[-5] ^= 1                                                                      # a byte in an untouched record
        with self.assertRaises(lightfit.LightError):
            lightfit.verify(pre, bytes(stray), '.submap', rep['lighting'])

    def test_more_new_meshes_than_old_falls_back(self):
        from todms import lightfit
        entry, raw, new, rep = self.swap(PROP, INDUSTRIAL)
        HL = lightfit.hl()
        old_geo = lightfit.model_geometry(HL, raw, '.submap', PROP)
        fat = copy.deepcopy(lightfit.model_geometry(HL, new, '.submap', PROP))
        for _ in range(3):                                                                  # four near meshes against three
            fat['pivots'][0].append((8, 8))
            fat['smb_flags'][0].append(0)
        out, lr = lightfit.retarget_model(new, '.submap', PROP, 0, old_geo, fat)
        self.assertEqual(lr['status'], 'fallback')
        self.assertIn('meshes', lr['reason'])
        self.assertEqual(out, new)

    def build(self):
        from todms import mods
        out = tempfile.mkdtemp(dir=self.t.name)
        rep = mods.build_mods(self.ws, [dict(name='t', level=[], data={}, models=[self.crate_entry()], textures=[])], out, 'a.zip')
        rep.pop('_outs')
        return rep

    def test_a_model_that_cannot_be_fitted_is_unlit_as_before(self):
        def fail(data, ext, name, pivot, og, ng):
            return data, dict(model=name, status='fallback', reason='test', instances=[], uids=[], fallback=[], records=[], patches=[], growth=0,
                              regenerated=0)
        with patch('todms.lightfit.retarget_model', side_effect=fail):
            rep = self.build()
        for b in rep['assets']['blocks']:
            self.assertGreater(b['lit_unset'], 0)
            self.assertEqual(b['lit_kept'], 0)
        self.assertTrue(any('baked lighting not fitted' in n['text'] and '(test)' in n['text'] for n in rep['assets']['notes']))

    def test_the_build_reports_the_kept_lighting(self):
        rep = self.build()
        self.assertFalse(any('dark' in n['text'] or 'not fitted' in n['text'] for n in rep['assets']['notes']))
        json.dumps(rep['assets'])


if __name__ == '__main__':
    unittest.main()
