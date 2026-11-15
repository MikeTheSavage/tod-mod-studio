"""Mission templates: projects, combining projects into one build, slot rules, install/uninstall (synthetic archives in temp folders only)."""
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
from todms import game, missions_tpl as MT, newmap


def zip_at(p, entries):
    with zipfile.ZipFile(p, 'w') as z:
        for e in entries:
            z.writestr(e, b'x')


def project(name='Pack A', n=2, newmap_id=None):
    hosts = [dict(id='yard', kind='new_map', newmap_id=newmap_id, map_index=0)] if newmap_id else \
        [dict(id='dt', kind='existing', block='submap01_map02_lostoros_downtown.submap', map_ids_from_slot=33, area=[0, 0, 50, 50], ground_y=2.5)]
    return dict(name=name, hosts=hosts, missions=[dict(id='m%d' % i, type='ghost', host=hosts[0]['id'], index='auto', params={}) for i in range(n)])


class Projects(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.t.name, 'home'), TODMS_CACHE=os.path.join(self.t.name, 'cache'))
        self.env.start()
        self.folder = os.path.join(self.t.name, 'game')
        os.makedirs(self.folder)
        Path(self.folder, 'configpc.txt').write_bytes(b'fullscreen = 1\r\nfilesystem = hd_override.zip, blocks.naz, sounds.naz\r\n')
        self.ws = SimpleNamespace(game=SimpleNamespace(folder=self.folder))

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def test_save_list_delete_and_bad_input(self):
        p = MT.save_project(project())
        self.assertEqual([x['id'] for x in MT.list_projects()], [p['id']])
        with self.assertRaises(ValueError):
            MT.save_project(dict(project(), name=' '))
        bad = project()
        bad['missions'].append(dict(bad['missions'][0]))
        with self.assertRaises(ValueError):
            MT.save_project(bad)
        MT.delete_project(self.ws, p['id'])
        self.assertEqual(MT.list_projects(), [])

    def test_samples_open_as_a_new_map_project_plus_a_mission_project(self):
        info = {s['key']: s for s in MT.sample_info()}
        self.assertTrue(info['mesa']['uses_all_slots'])
        self.assertEqual(info['mesa']['missions'], 17)
        p = MT.open_sample('yard')
        self.assertEqual(len(p['project']['missions']), 2)
        self.assertEqual(newmap.get_project(p['project']['hosts'][0]['newmap_id'])['params']['maps'][0]['name'], 'Map11_ScrapyardTwo')

    def test_compose_one_project_keeps_plain_ids_and_adds_the_new_map(self):
        p = MT.open_sample('yard')
        lp, idmap, hostmap = MT.compose([(p['id'], MT.snapshot_of(p['id'], p['project']))])
        self.assertEqual([m['id'] for m in lp['missions']], ['yard_showdown', 'yard_ghost'])
        self.assertEqual(len(lp['new_map']['maps']), 1)

    def test_compose_two_projects_prefixes_ids_shares_maps_and_keeps_pinned_indices(self):
        a = MT.open_sample('yard')
        for m in a['project']['missions']:
            m['index'] = 'auto'
        b = MT.save_project(project('Pack B', 1, newmap_id=a['id']))
        ents = [(a['id'], MT.snapshot_of(a['id'], a['project'])), (b['id'], MT.snapshot_of(b['id'], b['project']))]
        lp, idmap, hostmap = MT.compose(ents, {(a['id'], 'yard_ghost'): ('ghost', 75)})
        self.assertEqual(len(lp['new_map']['maps']), 1)               # the same New maps project is built once
        ghost = [m for m in lp['missions'] if m['id'].endswith('yard_ghost')][0]
        self.assertEqual(ghost['index'], 75)
        self.assertTrue(all('~' in m['id'] for m in lp['missions']))
        self.assertEqual(idmap[ghost['id']], (a['id'], 'yard_ghost'))
        self.assertEqual({h['map_index'] for h in lp['hosts']}, {0})

    def test_a_pin_is_ignored_when_the_mission_type_changed(self):
        a = MT.open_sample('yard')
        lp, _, _ = MT.compose([(a['id'], MT.snapshot_of(a['id'], a['project']))], {(a['id'], 'yard_ghost'): ('hold', 75)})
        self.assertEqual([m for m in lp['missions'] if m['id'] == 'yard_ghost'][0]['index'], 79)

    def test_game_chain_never_stacks_our_mission_package(self):
        zip_at(os.path.join(self.folder, 'hd_override.zip'), ['a'])
        zip_at(os.path.join(self.folder, game.MISSIONS_ZIP), ['a'])
        Path(self.folder, 'blocks.naz').write_bytes(b'x')
        Path(self.folder, 'configpc.txt').write_bytes(b'filesystem = todms_missions.zip, hd_override.zip, blocks.naz\r\n')
        with patch.object(game.Game, '__init__', lambda s, f: setattr(s, 'folder', f)):
            self.assertEqual(game.Game(self.folder).chain('effective'), ['hd_override.zip', 'blocks.naz'])

    def test_archive_slot_budget_is_eight(self):
        Path(self.folder, 'configpc.txt').write_bytes(b'filesystem = ' + b', '.join(b'a%d.zip' % i for i in range(7)) + b', blocks.naz\r\n')
        with self.assertRaises(ValueError) as cm:
            MT._slot_check(self.folder, MT.ZIP, [MT.ZIP])
        self.assertIn('only load 8', str(cm.exception))
        self.assertEqual(len(MT._slot_check(self.folder, MT.ZIP, [MT.ZIP, 'a0.zip'])), 8)

    def test_install_replaces_the_new_map_package_and_uninstall_removes_everything(self):
        p = MT.open_sample('yard')
        nid = p['project']['hosts'][0]['newmap_id']
        zip_at(os.path.join(self.folder, 'todms_newmap_%s.zip' % nid), ['other'])
        newmap.write(os.path.join(self.folder, 'todms_newmaps.json'), {nid: dict(zip='todms_newmap_%s.zip' % nid, revision='r')})
        Path(self.folder, 'configpc.txt').write_bytes(('filesystem = todms_newmap_%s.zip, blocks.naz\r\n' % nid).encode())
        z = os.path.join(self.t.name, 'built.zip')
        zip_at(z, ['data_pc/overdose_the_game/overdose/shared/overdose.main'])
        res = dict(index_of={p['id']: {'yard_showdown': 71, 'yard_ghost': 79}})
        ents = [(p['id'], MT.snapshot_of(p['id'], p['project']))]
        with patch.object(game, 'game_running', return_value=False):
            line, out = MT._deploy(self.ws, z, newmap.file_hash(z), None, [nid])
            self.assertEqual(out, [nid])
            self.assertEqual(line, 'filesystem = todms_missions.zip, blocks.naz')
            self.assertFalse(os.path.exists(os.path.join(self.folder, 'todms_newmap_%s.zip' % nid)))
            newmap.write(MT.record_path(self.folder), dict(zip=MT.ZIP, projects=MT._project_records(ents, res), migrate_entries=['71:2964:33']))
            self.assertEqual(MT.installed_newmap_ids(self.folder), [nid])
            with self.assertRaises(ValueError) as cm:                  # the plain map cannot be installed on top
                newmap.install(self.ws, nid)
            self.assertIn('part of your mission templates', str(cm.exception))
            self.assertEqual(MT.installed(self.folder)['projects'][p['id']]['indices']['yard_ghost'], ['ghost', 79])
            MT.uninstall(self.ws, p['id'])
        self.assertFalse(os.path.exists(os.path.join(self.folder, MT.ZIP)))
        self.assertFalse(os.path.exists(MT.record_path(self.folder)))
        self.assertNotIn('todms_missions', Path(self.folder, 'configpc.txt').read_text(encoding='latin-1'))

    def test_a_package_that_repeats_a_mod_archive_entry_is_refused(self):
        z = os.path.join(self.t.name, 'built.zip')
        zip_at(z, ['same.block'])
        zip_at(os.path.join(self.folder, game.MOD_ZIP), ['same.block'])
        with self.assertRaises(ValueError):
            MT._deploy(self.ws, z, 'x', None, [])


class VendorChecks(unittest.TestCase):
    def check(self, script):
        r = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts' / script), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    @unittest.skipUnless(os.path.isdir(os.environ.get('TOD_NEWMAP_SRC', '')), 'needs the new-map recipe source (TOD_NEWMAP_SRC)')
    def test_vendored_new_map_recipe_matches_its_source(self):
        self.check('vendor_newmap.py')

    @unittest.skipUnless(os.path.isdir(os.environ.get('TOD_MISSIONS_SRC', '')), 'needs the mission template source (TOD_MISSIONS_SRC)')
    def test_vendored_mission_library_matches_its_source(self):
        self.check('vendor_missions.py')

    def test_there_is_one_submaptool_with_clone_of_file(self):
        self.assertIn('clone_of_file', (ROOT / 'backend/vendor/tools/level_streaming/submaptool.py').read_text(encoding='utf-8'))
        self.assertFalse((ROOT / 'backend/vendor/newmap/level_streaming').exists())


class SaveUpdate(unittest.TestCase):
    def test_the_save_update_passes_giver_threads_to_the_library_and_reports_skipped_sections(self):
        from contextlib import contextmanager
        from todms import saves
        seen = {}

        class FakeLib:
            @staticmethod
            def migrate_save_copy(manifest, src, out, migrate_py=None):
                import json
                seen['manifest'] = json.load(open(manifest))
                return dict(patched=[dict(mission=71, block='a.submap', key='3:16ff')],
                            skipped=[dict(mission=72, block='b.map', reason='this save does not contain the section "b.map"')])

        @contextmanager
        def fake_session(ws):
            yield FakeLib

        rec = dict(migrate_entries=['71:2964:33', '72:2965:33'], thread_keys=[dict(block='a.submap', index=5887, mission=71)])
        with tempfile.TemporaryDirectory() as d, patch.object(MT, 'installed', return_value=rec), patch.object(MT, 'session', fake_session),                 patch.object(saves, '_modules', return_value=(None, None)), patch.object(saves, 'out_dir', return_value=d):
            r = saves.migrate_missions(SimpleNamespace(game=SimpleNamespace(folder='x')), os.path.join(d, 'Slot00'))
        self.assertEqual(seen['manifest']['thread_keys'][0]['index'], 5887)
        self.assertEqual(r['givers_patched'], 1)
        self.assertEqual(len(r['notes']), 1)
        self.assertIn('reloaded once', r['notes'][0])


if __name__ == '__main__':
    unittest.main()
