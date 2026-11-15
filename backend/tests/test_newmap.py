"""New-map recipes, vendor provenance, and installation (synthetic archives in temporary game folders only)."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import game, mods, newmap, paths

PROOF = os.environ.get('TODMS_PROOF', '')   # a proof copy of the game: PROOF/game holds blocks.naz (read only)


def params():
    return dict(package='Test map', maps=[dict(name='Map11_RunawayTrain', source='map10_runawaytrain',
        arrival=dict(pos=[980.5, 4.7, 337], orient=[0, 0, 0, 1], floor='vanilla'),
        entry=dict(block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66],
                   parent=dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'),
                   size=[12, 6, 2], orient=[0, .70710678, 0, .70710678]),
        teleports=[dict(name='SPOT_1', pos=[980.5, 4.7, 341], orient=[0, 0, 0, 1])],
        return_=None)])


def recipe_params():
    p = params()
    m = p['maps'][0]
    m.pop('return_')
    m['return'] = dict(pos=[980.5, 6, 330], size=[8, 8, 2], target_map='MAINMAP_Map02_LosToros_Downtown',
                       target_submap='SUBMAP01_Map02_LosToros_Downtown',
                       teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill', teleport_block='overdose.main')
    return p


def zip_at(p, entries):
    with zipfile.ZipFile(p, 'w') as z:
        for entry in entries:
            z.writestr(entry, b'test')


class NewMaps(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.temp.name, 'home'),
                              TODMS_CACHE=os.path.join(self.temp.name, 'cache'))
        self.env.start()
        self.folder = os.path.join(self.temp.name, 'game')
        os.makedirs(self.folder)
        self.ws = SimpleNamespace(game=SimpleNamespace(folder=self.folder))
        Path(self.folder, 'configpc.txt').write_bytes(b'fullscreen = 1\r\nfilesystem = hd_override.zip, blocks.naz, sounds.naz\r\n')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def built(self, entries=('a.submap',)):
        p = newmap.save_project(recipe_params())
        d = Path(p['path'], 'runs', 'test')
        d.mkdir(parents=True)
        z = d / 'stream_override.zip'
        zip_at(z, entries)
        newmap.write(os.path.join(p['path'], 'build.json'), dict(folder=str(d), sha256=newmap.file_hash(z),
                     revision=newmap.revision(p['params']), report=dict(result='PASS')))
        return p

    def test_params_round_trip_and_import(self):
        p = recipe_params()
        p['unrecognised_future_option'] = {'keep': [1, 2, 3]}
        m = p['maps'][0]
        m['entries'] = [dict(m.pop('entry'), id='alley', arrive_at='SPOT_1')]
        m['entries'].append(dict(m['entries'][0], id='bridge'))
        saved = newmap.save_project(p)
        self.assertEqual(newmap.get_project(saved['id'])['params'], p)
        self.assertEqual(newmap.import_project(os.path.join(saved['path'], 'params.json'))['params'], p)
        build = Path(self.temp.name, 'import-build')
        build.mkdir()
        newmap.write(str(build / 'manifest.json'), dict(package='Test', maps=[], base_limits={}))
        newmap.write(str(build / 'params.json'), p)
        self.assertEqual(newmap.import_project(str(build))['params'], p)

    def test_validation(self):
        p = recipe_params()
        p['maps'][0]['entries'] = [dict(p['maps'][0]['entry'], id='one', arrive_at='missing')]
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            newmap.save_project(p)
        with self.assertRaises(ValueError):
            newmap.directory('../escape')

    def test_old_manifest_import_spots(self):
        m = recipe_params()['maps'][0]
        d = Path(self.temp.name, 'old-build')
        d.mkdir()
        mapblock, subblock = 'mainmap_map11_runawaytrain.map', 'submap01_map11_runawaytrain.submap'
        newmap.write(str(d / 'manifest.json'), dict(package='Old', base_limits={}, maps=[dict(
            name=m['name'], source=m['source'], arrival=m['arrival'], entry=m['entry'],
            arrival_node='ARRIVAL_TEST', map_block=mapblock, submap_block=subblock)]))
        template = dict(op='graft', from_block='source.map', from_fragment='source.fragment', entity='0x1')
        ops = [dict(template, name='ARRIVAL_TEST', pos=m['arrival']['pos']),
               dict(template, name='SPOT_1', pos=m['teleports'][0]['pos'], orient=[0, .70710678, 0, .70710678])]
        for name, target in [('TriggerLoad_MAINMAP_Return', 'target_map'), ('TriggerLoad_SUBMAP_Return', 'target_submap')]:
            ops.append(dict(name=name, pos=m['return']['pos'], set=dict(width=8, height=8, length=2),
                            child_sets=[dict(set=dict(TargetName=m['return'][target], Teleport_to=m['return']['teleport_to']))]))
        newmap.write(str(d / 'spec.json'), dict(blocks=[dict(block=mapblock, ops=ops)]))
        imported = newmap.import_project(str(d))['params']
        self.assertIn('import_warning', imported)
        self.assertEqual(imported['maps'][0]['return']['target_map'], m['return']['target_map'])
        self.assertEqual(imported['maps'][0]['teleports'][0]['name'], 'SPOT_1')
        manifest = newmap.read(str(d / 'manifest.json'))
        mm = manifest['maps'][0]
        mm['entries'] = [dict(mm['entry'], id='one')]
        mm['teleports'] = [dict(name='SPOT_1', pos=m['teleports'][0]['pos'])]
        newmap.write(str(d / 'manifest.json'), manifest)
        latest = newmap.import_project(str(d))['params']['maps'][0]
        self.assertEqual(len(newmap.entries(latest)), 1)  # Manifest entry summary is not another entrance.
        self.assertEqual(latest['teleports'][0]['orient'], [0, .70710678, 0, .70710678])

    @patch('todms.game.game_running', return_value=False)
    def test_install_uninstall_order_and_backup(self, running):
        p = self.built()
        zip_at(Path(self.folder, game.MOD_ZIP), ['unrelated.map'])
        mods.set_filesystem(self.folder, game.MOD_ZIP)
        before = Path(self.folder, 'configpc.txt').read_bytes()
        result = newmap.install(self.ws, p['id'])
        fs = game.filesystem_line(game.read_configpc(self.folder))
        self.assertEqual(fs, [result['zip'], game.MOD_ZIP, 'hd_override.zip', 'blocks.naz', 'sounds.naz'])
        newmap.install(self.ws, p['id'])
        self.assertEqual(game.filesystem_line(game.read_configpc(self.folder)), fs)
        self.assertTrue(Path(self.folder, 'configpc.txt.todms_backup').exists())
        self.assertTrue(Path(self.folder, result['zip'] + '.todms_backup').exists())
        newmap.uninstall(self.ws, p['id'])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        self.assertFalse(Path(self.folder, result['zip']).exists())
        self.assertTrue(Path(self.folder, game.MOD_ZIP).exists())

    @patch('todms.game.game_running', return_value=False)
    def test_conflict_refused_both_directions(self, running):
        p = self.built(['data_pc/a.submap'])
        modzip = Path(self.folder, game.MOD_ZIP)
        zip_at(modzip, ['data_pc/a.submap'])
        before = Path(self.folder, 'configpc.txt').read_bytes()
        with self.assertRaisesRegex(ValueError, 'same block'):
            newmap.install(self.ws, p['id'])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        modzip.unlink()
        newmap.install(self.ws, p['id'])
        candidate = Path(self.temp.name, 'mod.zip')
        zip_at(candidate, ['data_pc/a.submap'])
        with self.assertRaisesRegex(ValueError, 'same block'):
            newmap.check_mod_conflicts(self.folder, str(candidate))

    @patch('todms.game.game_running', return_value=False)
    def test_stale_and_modified_build_refused(self, running):
        p = self.built()
        b = newmap.get_project(p['id'])['build']
        Path(b['folder'], 'stream_override.zip').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            newmap.install(self.ws, p['id'])
        p['params']['package'] = 'Edited'
        newmap.save_project(p['params'], p['id'])
        with self.assertRaisesRegex(ValueError, 'this version'):
            newmap.install(self.ws, p['id'])

    @patch('todms.game.game_running', return_value=True)
    def test_running_game_refused(self, running):
        p = self.built()
        with self.assertRaisesRegex(RuntimeError, 'close it first'):
            newmap.install(self.ws, p['id'])
        with self.assertRaisesRegex(RuntimeError, 'close it first'):
            newmap.uninstall(self.ws, p['id'])

    @unittest.skipUnless(os.path.isdir(os.environ.get('TOD_NEWMAP_SRC', '')), 'needs the new-map recipe source (TOD_NEWMAP_SRC)')
    def test_vendor_check(self):
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/vendor_newmap.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_two_entry_recipe_check(self):
        if not PROOF or not (Path(PROOF, 'game') / 'blocks.naz').exists():   # newmap.info() needs the tables built from it
            self.skipTest('needs a read-only proof copy of blocks.naz for a real recipe check')
        if not newmap.info()['entries_supported']:
            self.skipTest('vendored make_new_map.py does not support entries yet; re-vendor when the recipe worker finishes')
        self.run_recipe_check(two=True)

    def test_legacy_recipe_check(self):
        self.run_recipe_check(two=False)

    def test_full_recipe_build(self):
        proof = Path(PROOF, 'game')
        if not PROOF or not (proof / 'blocks.naz').exists():
            self.skipTest('needs read-only proof data for a full recipe build')
        from todms.workspace import Workspace
        ws = Workspace()
        ws.set_game(str(proof))
        params = recipe_params()
        if newmap.info()['entries_supported']:
            m = params['maps'][0]
            e = m.pop('entry')
            second = dict(e, id='bridge', pos=[-237, 2.5, -58], arrive_at='SPOT_1')
            second.pop('parent')  # Exercise the recipe's default parent too.
            m['entries'] = [dict(e, id='alley'), second]
        p = newmap.save_project(params)
        r = newmap.run(ws, p['id'])
        self.assertEqual(r['report']['result'], 'PASS', r['report'])
        self.assertIn('sha256', r)
        self.assertIn(game.MAIN_ENTRY, newmap.archive_entries(os.path.join(r['folder'], 'stream_override.zip')))
        self.assertFalse([c for c in r['report']['checks'] if c['result'] == 'FAIL'])

    def test_entry_hosts(self):
        proof = Path(PROOF, 'game')
        if not PROOF or not (proof / 'blocks.naz').exists():
            self.skipTest('needs a read-only proof copy of blocks.naz')
        from todms.workspace import Workspace
        ws = Workspace()
        ws.set_game(str(proof))
        r = newmap.entry_hosts(ws)
        if not r['supported']:
            self.skipTest('the vendored recipe has no entry-host listing')
        h = {x['block']: x for x in r['hosts']}
        self.assertTrue(h['submap01_map02_lostoros_downtown.submap']['offer'])
        self.assertTrue(h['submap01_map02_lostoros_downtown.submap']['proven'].startswith('proven'))
        self.assertFalse(h['submap03_map02_lostoros_downtown.submap']['offer'])
        self.assertTrue(h['submap03_map02_lostoros_downtown.submap']['reason'])

    def run_recipe_check(self, two=False):
        proof = Path(PROOF, 'game')
        if not PROOF or not (proof / 'blocks.naz').exists():
            self.skipTest('needs a read-only proof copy of blocks.naz for a real recipe check')
        from todms.workspace import Workspace
        ws = Workspace()
        ws.set_game(str(proof))   # Reads game data only; all settings/tables/build outputs are under the temp home.
        p = recipe_params()
        if two:
            m = p['maps'][0]
            e = m.pop('entry')
            m['entries'] = [dict(e, id='alley'), dict(e, id='bridge', pos=[-237, 2.5, -58], arrive_at='SPOT_1')]
        saved = newmap.save_project(p)
        oldargv = sys.argv
        import fragtool as ft
        oldarchive = ft._arch
        r = newmap.run(ws, saved['id'], check_only=True)
        self.assertIs(sys.argv, oldargv)
        self.assertIs(ft._arch, oldarchive)
        self.assertTrue(Path(r['folder'], 'recipe_report.json').exists())
        self.assertFalse(Path(r['folder'], 'stream_override.zip').exists())
        self.assertEqual(r['report']['result'], 'CHECK-ONLY', r['report'])
        self.assertFalse([c for c in r['report']['checks'] if c['result'] == 'FAIL'])
        spec = newmap.read(os.path.join(r['folder'], 'spec.json'))
        if two:
            ops = [o for b in spec['blocks'] for o in b['ops'] if 'TriggerLoad_' in o.get('name', '')]
            self.assertEqual(len(ops), 6)   # Two entry pairs and the return pair.


if __name__ == '__main__':
    unittest.main()
