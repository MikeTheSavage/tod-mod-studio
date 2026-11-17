"""Wave 4: compatibility (conflicts, load order, smart merge, requirements, versions, profiles), sharing (mod page, collections, pieces,
safety check, community catalogue), distribution (update check, portable mode, migration with backup, report a problem, uninstall hook).
Library, settings and game folders are temporary; the game tests use a proof copy of the game in env TODMS_PROOF read-only (skipped when unset)."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, HERE)
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
HAVE_GAME = os.path.isdir(os.path.join(PROOF, 'game'))

from todms import archives, cli, community, compat, game, journal, migrate, modfile, modshare, mods, pack, paths, profiles, support  # noqa: E402
from test_install_foundation import Env, zip_at  # noqa: E402

E1 = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
E2 = 'data_pc/overdose_the_game/overdose/shared/submap01_map09_jungle.submap'
FR = 'data_pc/overdose_the_game/overdose/shared/frag_a.fragment'


def recipe(name, level=None, data=None, **kw):
    return dict(format='todms-mod', version=1, name=name, author='tester', description='', level=level or [], data=data or {}, view=None, **kw)


def setop(node, prop, value, entry=E2):
    return dict(op='set', entry=entry, frag=FR, node=node, prop=prop, value=value)


class Home(unittest.TestCase):
    """A temporary library and settings folder."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        r = self.t.name
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(r, 'home'), TODMS_CACHE=os.path.join(r, 'cache'), TODMS_SAVES=os.path.join(r, 'saves'))
        self.env.start()
        mods._UPGRADED.clear()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def add(self, name, enabled=True, **kw):
        m = mods.save_mod(recipe(name, **kw))
        if enabled:
            o = mods.load_order()
            mods.set_state(o['order'], o['enabled'] + [m['id']])
        return m['id']

    def write(self, name, obj):
        p = os.path.join(self.t.name, name)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(obj, f)
        return p


# ------------------------------------------------------------------------------------------------ conflicts and requirements
class TestCompat(unittest.TestCase):
    def mods3(self):
        a = dict(id='a', name='A', level=[setop('0x00000010', 'Health', 5), setop('0x00000011', 'Speed', 1)], data={'weapons': {'weapons.AK.ClipSize': 30}})
        b = dict(id='b', name='B', level=[setop('0x00000010', 'Health', 9), setop('0x00000012', 'Speed', 2)], data={'weapons': {'weapons.AK.ClipSize': 30, 'weapons.AK.ReloadTime': 2}})
        c = dict(id='c', name='C', level=[setop('0x00000010', 'Health', 7)], data={'weapons': {'weapons.AK.ClipSize': 50}})
        return a, b, c

    def test_the_same_value_set_to_different_things_is_a_clash_and_the_last_mod_wins(self):
        a, b, c = self.mods3()
        r = compat.conflicts([a, b, c])
        health = next(x for x in r['clashes'] if 'Health' in x['label'])
        self.assertEqual([m['id'] for m in health['mods']], ['a', 'b', 'c'])
        self.assertEqual(health['winner'], 'c')
        self.assertTrue(health['mods'][-1]['wins'])
        clip = next(x for x in r['clashes'] if 'ClipSize' in x['label'])
        self.assertEqual(clip['winner'], 'c')
        self.assertEqual([m['id'] for m in clip['mods']], ['a', 'b', 'c'])      # B repeats A's 30 but C differs: all three listed

    def test_swapping_the_order_changes_the_winner(self):
        a, b, c = self.mods3()
        r = compat.conflicts([c, b, a])
        health = next(x for x in r['clashes'] if 'Health' in x['label'])
        self.assertEqual(health['winner'], 'a')

    def test_equal_values_are_not_a_clash_and_different_values_in_one_block_are_merged(self):
        a, b, _ = self.mods3()
        r = compat.conflicts([a, b])
        self.assertFalse(any('ClipSize' in x['label'] for x in r['clashes']))
        self.assertFalse(any('Speed' in x['label'] for x in r['clashes']))      # different nodes
        self.assertTrue(any(m['block'] == 'submap01_map09_jungle.submap' for m in r['merged']))
        self.assertEqual(r['by_mod']['a']['merged'] >= 1, True)

    def test_delete_against_an_edit_and_models_textures_collision(self):
        a = dict(id='a', name='A', level=[dict(op='delete', entry=E2, frag=FR, node='0x00000010', mode='disable')],
                 models=[dict(id='m', mode='replace', target='/data/x/y.model')], textures=[dict(id='t', target='/data/t/z.bmp', crop=None)],
                 collision=[dict(id='s1', pieces=[1])])
        b = dict(id='b', name='B', level=[setop('0x00000010', 'Health', 1)],
                 models=[dict(id='m2', mode='replace', target='/DATA/x/y.model', params=dict(scale=2))], textures=[dict(id='t2', target='/data/t/z.bmp', crop=[0, 0, 1, 1])],
                 collision=[dict(id='s1', pieces=[2])])
        r = compat.conflicts([a, b])
        kinds = sorted(x['kind'] for x in r['clashes'])
        self.assertEqual(kinds, ['collision', 'model', 'removed', 'texture'])

    def test_versions_compare_as_numbers(self):
        self.assertGreater(compat.vcmp('1.10', '1.9'), 0)
        self.assertEqual(compat.vcmp('1.0', '1'), 0)
        self.assertLess(compat.vcmp('1.0.10', '1.1'), 0)

    def test_requirements_say_what_is_missing_in_plain_words(self):
        lib = {'gp': dict(name='Needs G+', requires=dict(gameplay_plus=True)),
               'van': dict(name='Vanilla only', requires=dict(gameplay_plus=False)),
               'new': dict(name='New app', requires=dict(min_app='9.0')),
               'dep': dict(name='Dependent', requires=dict(mods=[dict(id='base', version='2.0')])),
               'base': dict(name='Base', page=dict(version='1.5'))}
        env = dict(app='1.0.10', gameplay_plus=False)
        texts = {u['mod']: u['text'] for u in compat.check_requirements(lib, ['gp', 'van', 'new', 'dep', 'base'], env)}
        self.assertEqual(set(texts), {'gp', 'new', 'dep'})
        self.assertIn('needs Gameplay+', texts['gp'])
        self.assertIn('Mod Studio 9.0', texts['new'])
        self.assertIn('version 2.0 or newer. You have 1.5', texts['dep'])
        env2 = dict(app='1.0.10', gameplay_plus=True)
        t2 = [u['mod'] for u in compat.check_requirements(lib, ['gp', 'van'], env2)]
        self.assertEqual(t2, ['van'])
        t3 = compat.check_requirements(lib, ['dep'], env)
        self.assertIn('not switched on', t3[0]['text'])
        self.assertIn('which you do not have', compat.check_requirements(dict(dep=lib['dep']), ['dep'], env)[0]['text'])

    def test_game_variant_says_what_is_supported(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'goggame-1.info').write_text('x')
            Path(d, 'uk_sounds.naz').write_bytes(b'x')
            g = SimpleNamespace(folder=d, is_gog_exe=True, exe_md5='m', names=lambda: [])
            v = compat.variant(g)
            self.assertEqual((v['store'], v['language'], v['supported']), ('gog', 'en', True))
            g2 = SimpleNamespace(folder=d, is_gog_exe=False, exe_md5='m', names=lambda: [])
            os.remove(os.path.join(d, 'goggame-1.info'))
            v2 = compat.variant(g2)
            self.assertEqual((v2['store'], v2['supported']), ('retail', False))
            self.assertIn('not tested', v2['text'])


class TestCombine(Home):
    def test_two_mods_with_different_values_both_apply_and_the_same_value_follows_the_order(self):
        a = recipe('A', data={'weapons': {'weapons.AK.ClipSize': 99, 'weapons.AK.speed': 5}})
        b = recipe('B', data={'weapons': {'weapons.AK.ReloadTime': 1.5, 'weapons.AK.ClipSize': 55}})
        _, data, _ = mods.combined([a, b])
        self.assertEqual(data['weapons'], {'weapons.AK.ClipSize': 55, 'weapons.AK.speed': 5, 'weapons.AK.ReloadTime': 1.5})
        _, data2, _ = mods.combined([b, a])
        self.assertEqual(data2['weapons']['weapons.AK.ClipSize'], 99)
        self.assertEqual(data2['weapons']['weapons.AK.ReloadTime'], 1.5)

    def test_a_shared_uid_is_renamed_for_the_later_mod_so_both_objects_exist(self):
        add = lambda n: dict(op='add', uid='n1', entry=E2, template=dict(entry=E2, frag=FR, node='0x00000001'), name=n, pos=[0, 0, 0])
        level, _, _ = mods.combined([recipe('A', level=[add('x')]), recipe('B', level=[add('y')])])
        self.assertEqual([o['uid'] for o in level], ['n1', 'n1~1'])


# ------------------------------------------------------------------------------------------------ the pack: dependencies, profiles
class TestInstall(Env):
    def setUp(self):
        super().setUp()
        mods._UPGRADED.clear()
        self.run_patch2 = patch.object(mods, 'game_running', return_value=False)
        self.run_patch2.start()

    def tearDown(self):
        self.run_patch2.stop()
        super().tearDown()

    def add(self, name, **kw):
        return mods.save_mod(recipe(name, **kw))['id']

    def test_install_refuses_a_mod_whose_needs_are_not_met_and_writes_nothing(self):
        a = self.add('Needs more', requires=dict(gameplay_plus=True))
        mods.set_state([a], [a])
        before = Path(self.folder, 'configpc.txt').read_bytes()
        with self.assertRaisesRegex(ValueError, 'needs Gameplay\\+'):
            mods.install(self.ws)
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        self.assertFalse(os.path.exists(os.path.join(self.folder, game.PACK_ZIP)))
        Path(self.folder, 'TODGameplay.dll').write_bytes(b'x')
        mods.install(self.ws)
        self.assertTrue(os.path.exists(os.path.join(self.folder, game.PACK_ZIP)))

    def test_a_required_mod_must_be_switched_on_with_the_right_version(self):
        base = self.add('Base', page=dict(version='1.0'))
        dep = self.add('Dep', requires=dict(mods=[dict(id=base, version='1.2')]))
        mods.set_state([base, dep], [dep])
        with self.assertRaisesRegex(ValueError, 'not switched on'):
            mods.install(self.ws)
        mods.set_state([base, dep], [base, dep])
        with self.assertRaisesRegex(ValueError, 'version 1.2 or newer. You have 1.0'):
            mods.install(self.ws)
        m = mods.get_mod(base)
        m['page']['version'] = '1.3'
        mods.save_mod(m)
        mods.install(self.ws)

    def test_switching_profile_rebuilds_the_pack_and_copies_the_saves_first(self):
        a, b = self.add('A'), self.add('B')
        Path(self.t.name, 'saves', 'slot1').write_bytes(b'save')
        mods.set_state([a, b], [a])
        profiles.listing()
        mods.install(self.ws)
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'main:' + a.encode())
        profiles.create('Experimental')
        r = profiles.switch(self.ws, 'Experimental', rebuild=False)
        mods.set_state([b, a], [b, a])
        self.assertEqual(profiles.listing()['active'], 'Experimental')
        r = profiles.switch(self.ws, 'Main')
        self.assertEqual(profiles.listing()['active'], 'Main')
        self.assertEqual(mods.load_order()['enabled'], [a])
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'main:' + a.encode())
        self.assertIsNotNone(r['snapshot'])
        Path(self.t.name, 'saves', 'slot1').write_bytes(b'save changed while playing')
        r = profiles.switch(self.ws, 'Experimental')
        self.assertEqual(mods.load_order()['enabled'], [b, a])
        self.assertEqual(self.pack_entry('shared/overdose.main'), ('main:%s,%s' % (b, a)).encode())      # the order of the profile decides
        from todms import snapshots
        self.assertTrue(any('profile' in s['label'] for s in snapshots.list_snapshots()))
        self.assertEqual([p['name'] for p in profiles.listing()['profiles'] if p['active']], ['Experimental'])
        with self.assertRaisesRegex(ValueError, 'another profile'):
            profiles.delete('Experimental')
        profiles.delete('Main')

    def test_a_switch_that_install_refuses_is_undone(self):
        a = self.add('Plain')
        needs = self.add('Needs', requires=dict(gameplay_plus=True))
        mods.set_state([a, needs], [a])
        profiles.listing()
        profiles.create('Other')
        profiles.switch(self.ws, 'Other', rebuild=False)
        mods.set_state([a, needs], [needs])
        profiles.switch(self.ws, 'Main', rebuild=False)
        with self.assertRaises(ValueError):
            profiles.switch(self.ws, 'Other')
        self.assertEqual(profiles.listing()['active'], 'Main')
        self.assertEqual(mods.load_order()['enabled'], [a])


# ------------------------------------------------------------------------------------------------ sharing
class TestPageAndVersions(Home):
    def test_page_fields_are_kept_limited_and_listed(self):
        shot = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 50).decode()
        m = mods.save_mod(recipe('P', page=dict(version='2.1', credits='me', reuse=False, license='by me', changelog=[dict(version='2.1', text='x')],
                                                 screenshots=[dict(name='a', data=shot)] * 8)))
        self.assertEqual(len(m['page']['screenshots']), 6)
        self.assertEqual(m['schema'], migrate.CURRENT)
        row = mods.list_mods()[0]
        self.assertEqual((row['version'], row['reuse'], row['shots']), ('2.1', False, 6))
        with self.assertRaisesRegex(ValueError, 'version must be numbers'):
            mods.save_mod(recipe('P', page=dict(version='x.y')))
        with self.assertRaisesRegex(ValueError, 'screenshot'):
            mods.save_mod(recipe('P', page=dict(screenshots=[dict(name='a', data=base64.b64encode(b'nope').decode())])))

    def test_a_newer_version_updates_in_place_and_keeps_order_and_state(self):
        a = self.add('First', page=dict(version='1.0'))
        b = self.add('Mod B', page=dict(version='1.0'))
        c = self.add('Third')
        mods.set_state([a, b, c], [b])
        share = mods.share_dict(b)
        share['page']['version'] = '1.1'
        share['level'] = [setop('0x00000010', 'Health', 3)]
        r = mods.import_obj(json.loads(json.dumps(share)))
        self.assertEqual(r['import']['status'], 'updated')
        self.assertEqual(r['import']['from_version'], '1.0')
        self.assertEqual(r['id'], b)
        self.assertEqual(mods.load_order()['order'], [a, b, c])
        self.assertEqual(mods.load_order()['enabled'], [b])
        self.assertEqual(len(mods.get_mod(b)['level']), 1)
        self.assertEqual(len(os.listdir(os.path.join(mods.lib_dir(), b, 'history'))), 1)
        again = mods.import_obj(json.loads(json.dumps(mods.share_dict(b))))
        self.assertEqual(again['import']['status'], 'same')
        old = dict(share)
        old['page'] = dict(share['page'], version='0.9')
        with self.assertRaisesRegex(ValueError, 'newer version'):
            mods.import_obj(old)

    def test_a_mod_that_may_not_be_edited_cannot_be_opened_or_shared_again(self):
        m = mods.save_mod(recipe('Locked', page=dict(reuse=False)))
        p = self.write('l.todmod', mods.share_dict(m['id']))
        mods.delete_mod(m['id'])
        r = modshare.import_any(p)
        with self.assertRaises(PermissionError):
            mods.get_mod(r['id'], for_edit=True)
        with self.assertRaises(PermissionError):
            mods.export_mod(r['id'], os.path.join(self.t.name, 'again.todmod'))
        self.assertTrue(mods.get_mod(r['id']))                       # it still installs
        mine = mods.save_mod(recipe('Mine', page=dict(reuse=False)))
        self.assertTrue(mods.get_mod(mine['id'], for_edit=True))     # the author's own mod stays editable


class TestCollectionsAndPieces(Home):
    def test_a_collection_round_trips_with_its_order(self):
        a, b, c = self.add('One', enabled=False, level=[setop('0x00000010', 'Health', 1)]), self.add('Two', enabled=False), self.add('Three', enabled=False)
        path = os.path.join(self.t.name, 'set.todcollection')
        modshare.export_collection([c, a, b], path, 'My set', 'me', 'three mods')
        self.assertTrue(modfile.check_file(path)['ok'])
        names = {i: mods.get_mod(i)['name'] for i in (a, b, c)}
        shutil_home = os.environ['TODMS_HOME']
        for i in (a, b, c):
            mods.delete_mod(i)
        self.assertEqual(mods.list_mods(), [])
        keep = self.add('Mine already', enabled=True)
        r = modshare.import_any(path)
        self.assertEqual(r['kind'], 'collection')
        self.assertEqual([x['status'] for x in r['mods']], ['added'] * 3)
        o = mods.load_order()
        self.assertEqual(o['order'], [keep, c, a, b])                        # the collection's order, after the mods already there
        self.assertEqual(o['enabled'], [keep, c, a, b])
        self.assertEqual({i: mods.get_mod(i)['name'] for i in (a, b, c)}, names)
        r2 = modshare.import_any(path)
        self.assertEqual([x['status'] for x in r2['mods']], ['same'] * 3)
        self.assertEqual(mods.load_order()['order'], [keep, c, a, b])
        self.assertTrue(shutil_home)

    def test_pieces_prefab_routes_tuning_and_mission(self):
        from todms import userlib, missions_tpl
        pf = dict(id='pf1', name='Barricade', items=[dict(dpos=[0, 0, 0], rot=[0, 0, 0, 1]), dict(dpos=[1, 0, 2], rot=[0, 0, 0, 1])], extent=2)
        userlib.save_key('prefabs', [pf])
        p1 = os.path.join(self.t.name, 'a.todpiece')
        modshare.export_piece('prefab', 'pf1', p1)
        userlib.save_key('prefabs', [])
        r = modshare.import_any(p1)
        self.assertEqual((r['kind'], r['name']), ('prefab', 'Barricade'))
        self.assertEqual([x['name'] for x in userlib.load()['prefabs']], ['Barricade'])
        r = modshare.import_any(p1)                                            # the same piece again gets its own id
        self.assertEqual(len(userlib.load()['prefabs']), 2)
        self.assertEqual(len({x['id'] for x in userlib.load()['prefabs']}), 2)
        m = self.add('Roads', enabled=False, nav=[dict(op='move', entry=E2, frag=FR, node='0x00000010', pos=[1, 2, 3])],
                     data={'weapons': {'weapons.AK.ClipSize': 4}, 'camera': {'x': 1}})
        p2 = os.path.join(self.t.name, 'r.todpiece')
        modshare.export_piece('routes', m, p2)
        r = modshare.import_any(p2)
        got = mods.get_mod(r['id'])
        self.assertEqual((got['nav'][0]['pos'], got['version'], got['level']), ([1, 2, 3], 3, []))
        p3 = os.path.join(self.t.name, 't.todpiece')
        modshare.export_piece('tuning', dict(mod=m, editor='weapons'), p3, name='Big clips')
        got = mods.get_mod(modshare.import_any(p3)['id'])
        self.assertEqual(got['data'], {'weapons': {'weapons.AK.ClipSize': 4}})
        with self.assertRaisesRegex(ValueError, 'no routes'):
            modshare.export_piece('routes', self.add('Empty', enabled=False), os.path.join(self.t.name, 'x.todpiece'))
        proj = dict(name='Yard', hosts=[dict(id='yard', kind='existing', block='submap01_map09_jungle.submap')],
                    missions=[dict(id='m_one', type='ghost', host='yard', params={}), dict(id='m_two', type='ghost', host='yard', params={})])
        pid = missions_tpl.save_project(proj)['id']
        p4 = os.path.join(self.t.name, 'm.todpiece')
        modshare.export_piece('mission', dict(project=pid, mission='m_two'), p4)
        got = modshare.import_any(p4)
        self.assertEqual(got['kind'], 'mission')
        imported = missions_tpl.get_project(got['id'])['project']
        self.assertEqual([x['id'] for x in imported['missions']], ['m_two'])
        self.assertEqual(imported['hosts'][0]['id'], 'yard')

    def test_a_piece_with_a_bad_prefab_is_refused(self):
        p = self.write('b.todpiece', dict(format='todms-piece', schema=5, kind='prefab', name='x', data=dict(prefab=dict(items=[dict(dpos='no')]))))
        with self.assertRaisesRegex(ValueError, 'not in the expected form'):
            modshare.import_any(p)


# ------------------------------------------------------------------------------------------------ safety check
def blob(data):
    return base64.b64encode(zlib.compress(data)).decode()


class TestSafety(Home):
    def refused(self, obj, text=None):
        p = self.write('bad.todmod', obj)
        before = mods.list_mods()
        with self.assertRaises(modfile.Unsafe) as cm:
            modshare.import_any(p)
        self.assertEqual(mods.list_mods(), before)             # nothing reached the library
        if text:
            self.assertIn(text, str(cm.exception))
        return cm.exception

    def mod(self, **kw):
        return dict(recipe('Evil'), **kw)

    def test_executable_content_is_refused(self):
        exe = b'MZ' + b'\x90' * 200
        sha = hashlib.sha256(exe).hexdigest()[:32]
        self.refused(self.mod(blobs={sha: blob(exe)}), 'a Windows program')
        self.refused(self.mod(blobs={'0123456789abcdef0123': blob(b'plain text')}), 'not a picture')
        self.refused(self.mod(level=[dict(op='set', entry='data/run.exe', frag='f', node='0x00000001', prop='p', value=1)]), 'program file')
        p = os.path.join(self.t.name, 'prog.todmod')
        Path(p).write_bytes(b'MZ\x90\x00' + b'\x00' * 400)
        with self.assertRaises(modfile.Unsafe):
            modshare.import_any(p)

    def test_path_tricks_and_unexpected_entries_are_refused(self):
        self.refused(self.mod(models=[dict(id='m', mode='replace', target='../../Windows/system32/x.model')]), 'outside the game data')
        self.refused(self.mod(level=[dict(op='set', entry='C:/Windows/x', frag='f', node='0x00000001', prop='p', value=1)]), 'outside the game data')
        self.refused(self.mod(run_this='cmd /c calc'), 'mods do not have')
        self.refused(self.mod(id='../../evil'), 'id that is not allowed')
        self.refused(self.mod(page=dict(version='1.0', script='x')), 'unexpected entry')
        self.refused(self.mod(page=dict(screenshots=[dict(data=base64.b64encode(b'MZ' + b'0' * 20).decode())])), 'not a picture')
        self.refused(self.mod(page=dict(screenshots=[dict(data=base64.b64encode(b'\x89PNG' + b'0' * 800000).decode())])), 'too large')

    def test_a_scene_with_python_objects_and_a_bomb_are_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('a.npy', b'\x93NUMPY\x01\x00v\x00' + b"{'descr': '|O', 'fortran_order': False, 'shape': (1,), }" + b' ' * 60 + b'\n')
        self.refused(self.mod(blobs={'0123456789abcdef0123': blob(buf.getvalue())}), 'unexpected content')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('run.bat', b'@echo off')
        self.refused(self.mod(blobs={'0123456789abcdef0123': blob(buf.getvalue())}), 'unexpected content')
        with patch.object(modfile, 'MAX_BLOB', 1000):
            self.refused(self.mod(blobs={'0123456789abcdef0123': blob(b'BM' + b'0' * 5000)}), 'too large')

    def test_a_zip_package_may_only_hold_the_mod_and_its_pictures(self):
        def pack_zip(entries):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                for n, d in entries.items():
                    z.writestr(n, d)
            return buf.getvalue()
        good = pack_zip({'mod.json': json.dumps(recipe('Packaged')), 'screenshots/one.png': b'\x89PNG\r\n\x1a\n' + b'0' * 20, 'readme.txt': b'hi'})
        kind, obj, _ = modfile.parse(good)
        self.assertEqual((kind, obj['name'], len(obj['page']['screenshots'])), ('mod', 'Packaged', 1))
        for entries, text in (({'mod.json': '{}', 'tool.exe': b'MZ'}, 'program file'), ({'mod.json': '{}', '../up.json': b'{}'}, 'outside'),
                              ({'mod.json': '{}', 'extra/readme.dll': b'x'}, 'program file'), ({'mod.json': '{}', 'other.dat': b'x'}, 'mods do not have')):
            with self.assertRaises(modfile.Unsafe) as cm:
                modfile.parse(pack_zip(entries))
            self.assertIn(text, str(cm.exception))

    def test_a_clean_file_passes_and_old_versions_and_collections_are_checked_too(self):
        p = self.write('ok.todmod', self.mod(level=[setop('0x00000010', 'Health', 5)]))
        self.assertTrue(modfile.check_file(p)['ok'])
        bad = dict(format='todms-collection', mods=[self.mod(blobs={'0123456789abcdef0123': blob(b'MZ....')})])
        with self.assertRaises(modfile.Unsafe):
            modfile.parse(json.dumps(bad).encode())
        self.assertFalse(modfile.check_file(self.write('n.todmod', dict(format='other')))['ok'])


# ------------------------------------------------------------------------------------------------ the catalogue and the update check
class TestOnline(Home):
    def files(self):
        d = os.path.join(self.t.name, 'site')
        os.makedirs(d)
        a = self.add('Catalogue mod', enabled=False, level=[setop('0x00000010', 'Health', 5)], page=dict(version='1.0'))
        pa = os.path.join(d, 'cat-mod.todmod')
        mods.export_mod(a, pa)
        mods.delete_mod(a)
        sha = hashlib.sha256(open(pa, 'rb').read()).hexdigest()
        cat = dict(format='todms-catalogue', name='Local', mods=[
            dict(id=a, name='Catalogue mod', author='me', version='1.0', description='d', url='cat-mod.todmod', sha256=sha, size=100),
            dict(id='tampered', name='Tampered', version='1.0', url='cat-mod.todmod', sha256='0' * 64),
            dict(id='nohash', name='No hash', version='1.0', url='cat-mod.todmod')])
        json.dump(cat, open(os.path.join(d, 'catalogue.json'), 'w'))
        return d, a

    def settings(self, d, **kw):
        return dict(dict(online=True, community_url=Path(d, 'catalogue.json').as_uri(), update_url=Path(d, 'latest.json').as_uri()), **kw)

    def test_nothing_goes_anywhere_until_the_person_opts_in(self):
        with self.assertRaisesRegex(community.Offline, 'Online features are off'):
            community.catalogue({})
        with self.assertRaisesRegex(community.Offline, 'No address'):
            community.catalogue(dict(online=True))
        with patch('urllib.request.urlopen') as u:
            with self.assertRaises(community.Offline):
                community.check_update(dict(online=False, update_url='https://example.invalid/x.json'))
            u.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'https'):
            community.catalogue(dict(online=True, community_url='http://example.invalid/x.json'))
        for k in ('community_url', 'update_url', 'online'):
            self.assertNotIn(k, __import__('todms.workspace', fromlist=['x']).Workspace.__init__.__code__.co_consts)

    def test_browse_and_get_a_mod_from_a_local_catalogue_with_the_hash_checked(self):
        d, a = self.files()
        st = self.settings(d)
        rows = community.catalogue(st)['rows']
        self.assertEqual([r['state'] for r in rows], ['new', 'new', 'new'])
        r = community.get_entry(st, a)
        self.assertEqual((r['kind'], r['status'], r['id']), ('mod', 'added', a))
        self.assertEqual(mods.get_mod(a)['origin'], 'imported')
        self.assertEqual(community.catalogue(st)['rows'][0]['state'], 'installed')
        with self.assertRaisesRegex(ValueError, 'does not match its fingerprint'):
            community.get_entry(st, 'tampered')
        with self.assertRaisesRegex(ValueError, 'no fingerprint'):
            community.get_entry(st, 'nohash')
        self.assertEqual(len(mods.list_mods()), 1)

    def test_a_catalogue_entry_that_is_not_safe_is_refused_after_the_hash(self):
        d, a = self.files()
        bad = os.path.join(d, 'cat-mod.todmod')
        obj = json.load(open(bad))
        obj['evil'] = 1
        data = json.dumps(obj).encode()
        open(bad, 'wb').write(data)
        cat = json.load(open(os.path.join(d, 'catalogue.json')))
        cat['mods'][0]['sha256'] = hashlib.sha256(data).hexdigest()
        json.dump(cat, open(os.path.join(d, 'catalogue.json'), 'w'))
        with self.assertRaises(modfile.Unsafe):
            community.get_entry(self.settings(d), a)
        self.assertEqual(mods.list_mods(), [])

    def test_update_check_against_a_local_json_downloads_only_with_a_matching_hash(self):
        d, _ = self.files()
        setup = b'MZ' + b'\x00' * 300
        Path(d, 'setup.exe').write_bytes(setup)
        latest = dict(version='9.9.9', url='setup.exe', sha256=hashlib.sha256(setup).hexdigest(), changes=['Faster', 'Fixed'])
        json.dump(latest, open(os.path.join(d, 'latest.json'), 'w'))
        st = self.settings(d)
        r = community.check_update(st, current='1.0.10')
        self.assertEqual((r['available'], r['version'], r['changes']), (True, '9.9.9', ['Faster', 'Fixed']))
        self.assertFalse(community.check_update(st, current='9.9.9')['available'])
        got = community.download_update(st, current='1.0.10')
        self.assertTrue(os.path.isfile(got['path']))
        with self.assertRaisesRegex(ValueError, 'confirm'):
            community.run_update(got['path'], False)
        r = community.run_update(got['path'], True, launch=False)
        self.assertIn('--silent', r['command'])
        self.assertFalse(r['started'])
        with self.assertRaisesRegex(ValueError, 'not a downloaded update'):
            community.run_update(os.path.join(d, 'setup.exe'), True, launch=False)
        latest['sha256'] = '1' * 64
        json.dump(latest, open(os.path.join(d, 'latest.json'), 'w'))
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            community.download_update(st, current='1.0.10')
        latest.pop('sha256')
        json.dump(latest, open(os.path.join(d, 'latest.json'), 'w'))
        with self.assertRaisesRegex(ValueError, 'no fingerprint'):
            community.download_update(st, current='1.0.10')


# ------------------------------------------------------------------------------------------------ distribution
class TestDistribution(Home):
    def old_recipe(self):
        m = recipe('Old', level=[setop('0x00000010', 'Health', 5)])
        m.update(id='old-mod-1', assets=[dict(x=1)], source='unreal')
        return m

    def test_opening_an_older_mod_upgrades_it_after_a_backup(self):
        d = os.path.join(mods.lib_dir(), 'old-mod-1')
        os.makedirs(d)
        p = os.path.join(d, 'mod.json')
        original = json.dumps(self.old_recipe(), indent=1)
        Path(p).write_text(original)
        m = mods.get_mod('old-mod-1')
        self.assertEqual((m['schema'], m['page']['version'], 'assets' in m, 'source' in m), (migrate.CURRENT, '1.0', False, False))
        backups = os.listdir(migrate.backup_dir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(Path(migrate.backup_dir(), backups[0]).read_text(), original)         # the backup is the file as it was
        mods.get_mod('old-mod-1')
        self.assertEqual(len(os.listdir(migrate.backup_dir())), 1)                              # a current file is never touched again

    def test_importing_an_older_file_keeps_the_file_and_makes_a_backup_copy(self):
        p = self.write('old.todmod', self.old_recipe())
        before = Path(p).read_bytes()
        r = modshare.import_any(p)
        self.assertEqual(Path(p).read_bytes(), before)
        self.assertTrue(os.path.isfile(r['backup']))
        self.assertEqual(Path(r['backup']).read_bytes(), before)
        self.assertEqual(mods.get_mod(r['id'])['schema'], migrate.CURRENT)
        newer = self.old_recipe()
        newer['schema'] = migrate.CURRENT + 1
        with self.assertRaisesRegex(ValueError, 'newer Mod Studio'):
            modshare.import_any(self.write('new.todmod', newer))

    def test_library_listing_upgrades_every_old_mod_once(self):
        for i in range(3):
            d = os.path.join(mods.lib_dir(), 'm%d' % i)
            os.makedirs(d)
            Path(d, 'mod.json').write_text(json.dumps(dict(self.old_recipe(), id='m%d' % i)))
        self.assertEqual(len(mods.list_mods()), 3)
        self.assertEqual(len(os.listdir(migrate.backup_dir())), 3)
        mods._UPGRADED.clear()
        mods.list_mods()
        self.assertEqual(len(os.listdir(migrate.backup_dir())), 3)

    def test_portable_mode_keeps_everything_next_to_the_program(self):
        root = os.path.join(self.t.name, 'app')
        os.makedirs(os.path.join(root, 'backend'))
        env = {k: v for k, v in os.environ.items() if k not in ('TODMS_HOME', 'TODMS_CACHE')}
        with patch.dict(os.environ, env, clear=True), patch.object(paths, 'BACKEND', os.path.join(root, 'backend')):
            self.assertIsNone(paths.portable_root())
            Path(root, 'portable.txt').write_text('')
            self.assertEqual(paths.user_dir(), os.path.join(root, 'data', 'home'))
            self.assertEqual(paths.cache_dir(), os.path.join(root, 'data', 'cache'))
            with patch.dict(os.environ, TODMS_HOME=os.path.join(self.t.name, 'elsewhere')):
                self.assertEqual(paths.user_dir(), os.path.join(self.t.name, 'elsewhere'))

    def test_report_a_problem_makes_a_bundle_and_a_text_file_and_sends_nothing(self):
        ws = SimpleNamespace(game=None)
        self.add('Listed')
        with patch('urllib.request.urlopen') as u, patch('socket.socket') as s:
            r = support.report_problem(ws, 'It crashed in %s' % os.path.expanduser('~'), 'I clicked Install')
            u.assert_not_called()
            s.assert_not_called()
        self.assertTrue(os.path.isfile(r['bundle']) and os.path.isfile(r['text']))
        text = Path(r['text']).read_text()
        self.assertIn('Nothing was sent anywhere', text)
        self.assertNotIn(os.path.expanduser('~'), text)
        with zipfile.ZipFile(r['bundle']) as z:
            self.assertIn('what_happened.txt', z.namelist())
            self.assertIn('Listed', z.read('mods.txt').decode())

    def test_command_line_files_and_the_uninstall_hook(self):
        good = self.write('a.todmod', recipe('x'))
        junk = self.write('a.txt', {})
        self.assertEqual(cli.open_files([good, junk, os.path.join(self.t.name, 'missing.todmod'), '--flag']), [os.path.abspath(good)])
        self.assertIsNone(cli.main([good]))
        calls = {}
        fake = SimpleNamespace(game=SimpleNamespace(folder=self.t.name))
        Path(self.t.name, 'configpc.txt.todms_backup').write_text('x')
        with patch('todms.workspace.Workspace', return_value=fake), patch('todms.restore.restore_vanilla', side_effect=lambda ws: calls.setdefault('r', 1) and dict(left=[])), \
                patch.object(game, 'game_running', return_value=False):
            os.makedirs(os.path.join(mods.lib_dir(), '..', 'backups', 'b1'), exist_ok=True)
            r = cli.restore_vanilla(remove=True, out=os.path.join(self.t.name, 'r.json'))
        self.assertEqual((r['ok'], r['restored'], calls['r']), (True, True, 1))
        self.assertGreaterEqual(r['removed_backups'], 2)
        self.assertFalse(os.path.exists(os.path.join(self.t.name, 'configpc.txt.todms_backup')))
        with patch('todms.workspace.Workspace', return_value=fake), patch.object(game, 'game_running', return_value=True):
            self.assertFalse(cli.restore_vanilla()['ok'])



# ------------------------------------------------------------------------------------------------ the installer (never runs setup)
class FakeReg:
    HKEY_CURRENT_USER = 'HKCU'
    REG_SZ = 1

    def __init__(self):
        self.vals, self.keys = {}, set()

    def CreateKey(self, root, path):
        self.keys.add(path)
        return path

    def SetValueEx(self, key, name, _r, _t, value):
        self.vals[(key, name)] = value

    def OpenKey(self, root, path):
        if path not in self.keys:
            raise OSError('no key')
        return path

    def QueryValueEx(self, key, name):
        return (self.vals[(key, name)], 1)

    def DeleteKey(self, root, path):
        if path not in self.keys:
            raise OSError('no key')
        self.keys.discard(path)


class TestSetupRegistration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('setup_main_under_test', os.path.join(ROOT, 'scripts', 'setup_main.py'))
        cls.sm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sm)

    def test_the_three_extensions_open_the_program_with_the_path(self):
        reg = FakeReg()
        self.sm.register_associations('C:\\Apps\\TODModStudio.exe', lambda *_: None, reg, 'Software\\Test')
        for ext in ('.todmod', '.todcollection', '.todpiece'):
            progid = reg.vals[('Software\\Test\\' + ext, '')]
            self.assertTrue(progid.startswith('TODModStudio.'))
            self.assertEqual(reg.vals[('Software\\Test\\%s\\shell\\open\\command' % progid, '')], '"C:\\Apps\\TODModStudio.exe" "%1"')
        self.sm.unregister_associations(reg, 'Software\\Test')
        self.assertEqual(reg.keys, set())

    def test_an_extension_someone_else_took_over_is_left_alone(self):
        reg = FakeReg()
        self.sm.register_associations('x.exe', lambda *_: None, reg, 'R')
        reg.vals[('R\\.todmod', '')] = 'Other.App'
        self.sm.unregister_associations(reg, 'R')
        self.assertIn('R\\.todmod', reg.keys)
        self.assertNotIn('R\\.todpiece', reg.keys)

    def test_the_uninstaller_restores_the_game_first_and_stops_if_that_fails(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, self.sm.EXE).write_bytes(b'x')
            calls = []

            def run(cmd, **kw):
                calls.append(cmd)
                Path(cmd[cmd.index('--result') + 1]).write_text(json.dumps(dict(ok=False, error='Total Overdose is running: close it first.')))
                return SimpleNamespace(returncode=1)
            with patch.object(self.sm.subprocess, 'run', run), patch.dict(os.environ, TEMP=d):
                with self.assertRaisesRegex(RuntimeError, 'Nothing was uninstalled'):
                    self.sm.restore_game(d, True, lambda *_: None)
            self.assertIn('--restore-vanilla', calls[0])
            self.assertIn('--remove-backups', calls[0])


# ------------------------------------------------------------------------------------------------ on the game
@unittest.skipUnless(HAVE_GAME, 'needs the proof copy')
class TestMergeOnTheGame(unittest.TestCase):
    """Two mods edit values of overdose.main: different values both apply, the same value follows the load order."""

    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, TODMS_HOME=os.path.join(cls.t.name, 'home'), TODMS_CACHE=os.path.join(cls.t.name, 'cache'),
                             TODMS_SAVES=os.path.join(cls.t.name, 'saves'))
        cls.env.start()
        from todms import workspace
        paths.ensure_cpu_guard()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))
        from todms import dataed
        data = dataed.weapons_read(cls.ws)
        cls.key = {}
        for g in data['groups']:
            for f in g['fields']:
                if f['label'] in ('ClipSize', 'ReloadTime', 'BulletsPerShot') and f['key'].startswith('weapons.'):
                    cls.key.setdefault(f['label'], f['key'])
                    cls.key['gun_' + f['label']] = f['key'].split('.')[1]
            if len(cls.key) >= 6:
                break
        gun = cls.key['gun_ClipSize']
        cls.clip = 'weapons.%s.ClipSize' % gun
        cls.reload = 'weapons.%s.ReloadTime' % gun
        cls.fields = {f['label']: f['value'] for g in data['groups'] for f in g['fields'] if f['key'] in (cls.clip, cls.reload)}

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.t.cleanup()

    def build(self, mod_list):
        out = tempfile.mkdtemp(dir=self.t.name)
        rep = mods.build_mods(self.ws, mod_list, out, 'a.zip')
        return dict(rep.pop('_outs'))

    def values(self, outs):
        from todms import dataed
        raw = outs[game.MAIN_ENTRY]
        shim = SimpleNamespace(read_block=lambda e: (raw, 'x'))
        d = dataed.weapons_read(shim)
        return {f['key']: f['value'] for g in d['groups'] for f in g['fields']}

    def test_different_values_both_apply_and_the_same_value_follows_the_load_order(self):
        clip0, rel0 = self.fields['ClipSize'], self.fields['ReloadTime']
        a = recipe('A', data={'weapons': {self.clip: 77}})
        b = recipe('B', data={'weapons': {self.reload: rel0 + 1.0}})
        v = self.values(self.build([a, b]))
        self.assertEqual(v[self.clip], 77)
        self.assertAlmostEqual(v[self.reload], rel0 + 1.0, places=3)
        c = recipe('C', data={'weapons': {self.clip: 33}})
        self.assertEqual(self.values(self.build([a, c]))[self.clip], 33)
        self.assertEqual(self.values(self.build([c, a]))[self.clip], 77)
        self.assertNotEqual(clip0, 77)
        r = compat.conflicts([dict(a, id='a'), dict(c, id='c')])
        self.assertEqual(r['clashes'][0]['winner'], 'c')

    def test_two_moves_of_one_object_keep_position_and_facing(self):
        from todms import build
        import fragtool as ft
        seen = {}

        def fake_apply(raw, ext, ops, T):
            seen['ops'] = ops
            raise ft.Fail('stop here')
        with patch.object(build.ft, 'apply_ops', fake_apply), patch.object(build.tb, 'Block') as B, patch.object(build.ft, 'fragments', return_value=([(1, FR)], None)):
            B.return_value = SimpleNamespace(payloads={1: b''})
            ops = [dict(op='move', entry=E2, frag=FR, node='0x00000010', pos=[1, 2, 3], rot=None),
                   dict(op='move', entry=E2, frag=FR, node='0x00000010', pos=None, rot=[0, 0, 0, 1])]
            with self.assertRaises(build.BuildError):
                build.stage_a(E2, b'', ops, None, {})
        (m,) = seen['ops']
        self.assertEqual(m['pos'], [1.0, 2.0, 3.0])
        self.assertIn('orient', m)


if __name__ == '__main__':
    unittest.main()
