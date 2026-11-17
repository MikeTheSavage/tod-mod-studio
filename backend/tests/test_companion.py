"""Tests of the companion-tools integration (collision sets, recipe versions, old recipes).

  .venv\\Scripts\\python -m unittest discover -s backend/tests -v

The build test uses a proof copy of the game in env TODMS_PROOF (skipped when unset): the same collision set built by Mod
Studio's build.py stage C must give the bytes the shared core gives on the same base block.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')


def piece():
    V = [[x, y, z] for x in (-500, -499) for y in (-140, -139) for z in (-2190, -2189)]
    return dict(verts=V, faces=[[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]],
                material='Stone', surface='0x02007C00')


class TestMods(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ['TODMS_HOME'] = self.home
        from todms import paths
        paths.setup_tools()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_combined_collision(self):
        from todms import mods
        a = dict(level=[], data={}, collision=[dict(id='x', n=1), dict(id='y', n=1)])
        b = dict(level=[], data={}, collision=[dict(id='x', n=2)])
        level, data, coll = mods.combined([a, b])
        self.assertEqual({s['id']: s['n'] for s in coll}, {'x': 2, 'y': 1})

    def test_version_and_import(self):
        from todms import mods
        from todct import collision as CO
        s = CO.new_set('w', 'map09_jungle', [piece()], 'hull')
        m = mods.save_mod(dict(name='t', level=[], data={}, collision=[s]))
        self.assertEqual(m['version'], 2)
        self.assertEqual(mods.save_mod(dict(name='u', level=[], data={}))['version'], 1)
        p = os.path.join(self.home, 'x.todmod')
        mods.export_mod(m['id'], p)
        m2 = mods.import_mod(p)
        self.assertEqual(len(m2['collision']), 1)
        bad = dict(json.load(open(p)), version=5)          # recipe v4 (models, textures) is read now; v5 is newer than this tool
        json.dump(bad, open(p, 'w'))
        with self.assertRaises(Exception):
            mods.import_mod(p)
        lst = {x['id']: x for x in mods.list_mods()}
        self.assertEqual(lst[m['id']]['collision_sets'], 1)

    def test_old_recipe_with_asset_rows(self):
        """A recipe of an older version carries replacement rows for a tool that is gone (the row layout is the old one): it imports, the rows are
        ignored, the rest (level ops, collision) is kept."""
        from todms import mods
        from todct import collision as CO
        s = CO.new_set('w', 'map09_jungle', [piece()], 'hull', source=dict(editor='old', actor='A'))
        old = dict(format='todms-mod', version=2, id='x', name='old', author='a', description='', created='2026-10-20T00:00:00',
                   updated='2026-10-20T00:00:00', view=None, data={}, collision=[s],
                   level=[dict(op='move', entry='data_pc/overdose_the_game/overdose/shared/mainmap_map09_jungle.map',
                               frag='f', node='0x00000001', pos=[1, 2, 3])],
                   assets=dict(kind='todct-asset-overrides', rows={'data_models_x': {'u' + 'e': '/Game/X', 'kind': 'static', 'path': '/x'}}),
                   source=dict(editor='old'))
        p = os.path.join(self.home, 'old.todmod')
        json.dump(old, open(p, 'w'))
        m = mods.import_mod(p)
        self.assertNotIn('assets', m)
        self.assertEqual(len(m['collision']), 1)
        self.assertEqual(len(m['level']), 1)
        self.assertEqual(m['version'], 2)
        row = {x['id']: x for x in mods.list_mods()}[m['id']]
        self.assertEqual(row['collision_sets'], 1)
        only_assets = dict(old, collision=[], level=[])
        json.dump(only_assets, open(p, 'w'))
        self.assertEqual(mods.import_mod(p)['version'], 1)
        self.assertNotIn('assets', json.load(open(os.path.join(mods.lib_dir(), m['id'], 'mod.json'))))

    def test_old_settings_key_ignored(self):
        from todms import workspace, paths
        json.dump(dict(author='me', **{'old_key': 'C:/nothing'}), open(os.path.join(paths.user_dir(), 'settings.json'), 'w'))
        ws = workspace.Workspace()
        self.assertEqual(ws.settings.get('author'), 'me')
        self.assertTrue(ws.status()['settings'])          # an unknown old key is just carried, nothing reads it


@unittest.skipUnless(os.path.isdir(os.path.join(PROOF, 'game')), 'needs the proof copy')
class TestBuildStageC(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.temp.name, 'home'),
                              TODMS_CACHE=os.path.join(self.temp.name, 'cache'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_stage_c_matches_core(self):
        from todms import workspace, mods
        from todct import collision as CO
        ws = workspace.Workspace()
        ws.set_game(os.path.join(PROOF, 'game'))
        s = CO.new_set('w', 'map09_jungle', [piece()], 'hull')
        out = tempfile.mkdtemp()
        try:
            rep = mods.build_mods(ws, [dict(level=[], data={}, collision=[s])], out, 'c.zip')
            built = dict(rep['_outs'])
            import fragtool as ft
            ctx = CO.MapContext('map09_jungle', CO.map_entries(ft.archive().names, 'map09_jungle'), lambda e: ws.read_block(e)[0])
            core, _ = CO.apply_sets(ctx, [s])
            self.assertEqual(set(core), set(built))
            for e in core:
                self.assertEqual(core[e], built[e])
            blk = rep['blocks'][0]
            self.assertTrue(blk['roundtrip']['identical'])
            self.assertEqual(blk['collision'][0]['pieces'], 1)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
