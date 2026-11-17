"""Test in game: the private test copy (hard links, its own configpc.txt, safe removal), the engine log summary, the crash report,
the bisect search, the support bundle's scrubbing and the test-save placement. No game is launched."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import bisect_mods, debuglog, game as gm, paths, saves, support, testgame

LOG = """Opening zip <todms_pack.zip> into slot 0
Opening zip <blocks.naz> into slot 1
The chunksize (-1) of the StreamedWAV loader does not match (iChannels(-1))!!
read asset block file: /data_pc/overdose_the_game/overdose/shared/overdose.main
BLOCK IN MEMORY: StartMap
**************************************************
              ASSET MEMORY USAGE:
MainAssetBlock   : 18.637MB, Max 18.637MB
MissionAssetBlock: 0.000MB, Max 0.000MB
PlayerdataBlock  : 0.000MB, Max 0.000MB
Load Time: 'Re-initialization'. 51ms of 95ms.
Could not read the asset block file: /data_pc/x/y.mission
Read asset block file: /data_pc/overdose_the_game/Overdose/shared/mm010.mission
"""


class FakeGame:
    def __init__(self, folder):
        self.folder = folder


class FakeWs:
    def __init__(self, folder):
        self.game = FakeGame(folder)


def make_game(root):
    g = os.path.join(root, 'game')
    os.makedirs(g)
    for n, size in (('blocks.naz', 5000), ('sounds.naz', 3000), ('TOD.exe', 800), ('dpconfig.dpc', 40), ('hd_override_1.zip', 600)):
        with open(os.path.join(g, n), 'wb') as f:
            f.write(b'x' * size)
    with open(os.path.join(g, 'configpc.txt'), 'w') as f:
        f.write('fullscreen = false\nfilesystem = todms_pack.zip, hd_override_1.zip, blocks.naz, sounds.naz\n')
    with open(os.path.join(g, 'todms_pack.zip'), 'wb') as f:
        f.write(b'old pack')
    with open(os.path.join(g, 'tod_old_log.txt'), 'w') as f:
        f.write('log')
    return g


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='todms_tg_')
        self.home = os.path.join(self.tmp, 'home')
        os.makedirs(self.home)
        self.env = patch.dict(os.environ, {'TODMS_HOME': self.home, 'TODMS_SAVES': os.path.join(self.tmp, 'saves')})
        self.env.start()
        self.game = make_game(self.tmp)
        self.ws = FakeWs(self.game)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class CopyTest(Base):
    def test_plan_is_linked_on_the_same_drive_and_small(self):
        p = testgame.plan(self.game)
        self.assertEqual(p['mode'], 'linked')
        self.assertFalse(p['needs_confirm'])
        self.assertGreater(p['link_bytes'], p['real_bytes'])
        self.assertTrue(p['dest'].startswith(self.tmp))

    def test_copy_links_archives_and_copies_the_rest(self):
        rec = testgame.make_copy(self.ws)
        d = rec['folder']
        self.assertTrue(os.path.samefile(os.path.join(self.game, 'blocks.naz'), os.path.join(d, 'blocks.naz')))
        self.assertTrue(os.path.samefile(os.path.join(self.game, 'hd_override_1.zip'), os.path.join(d, 'hd_override_1.zip')))
        for real in ('TOD.exe', 'dpconfig.dpc'):
            self.assertFalse(os.path.samefile(os.path.join(self.game, real), os.path.join(d, real)), real)
        # our own archive, old logs and records never go into a copy
        self.assertFalse(os.path.exists(os.path.join(d, 'todms_pack.zip')))
        self.assertFalse(os.path.exists(os.path.join(d, 'tod_old_log.txt')))
        self.assertTrue(os.path.exists(os.path.join(d, testgame.MARKER)))
        self.assertEqual([i['id'] for i in testgame.list_installs()], [rec['id']])
        # a second call refreshes the same copy
        again = testgame.make_copy(self.ws)
        self.assertEqual(again['id'], rec['id'])
        self.assertEqual(len(testgame.list_installs()), 1)

    def test_a_write_in_the_copy_never_reaches_the_game(self):
        rec = testgame.make_copy(self.ws)
        before = open(os.path.join(self.game, 'TOD.exe'), 'rb').read()
        with open(os.path.join(rec['folder'], 'TOD.exe'), 'wb') as f:
            f.write(b'changed')
        self.assertEqual(open(os.path.join(self.game, 'TOD.exe'), 'rb').read(), before)

    def test_remove_unlinks_and_leaves_the_game(self):
        rec = testgame.make_copy(self.ws)
        testgame.remove_install(rec['id'], self.game)
        self.assertFalse(os.path.exists(rec['folder']))
        self.assertEqual(os.path.getsize(os.path.join(self.game, 'blocks.naz')), 5000)
        self.assertEqual(testgame.list_installs(), [])

    def test_remove_refuses_a_folder_without_the_marker(self):
        rec = testgame.make_copy(self.ws)
        os.remove(os.path.join(rec['folder'], testgame.MARKER))
        with self.assertRaises(ValueError):
            testgame.remove_install(rec['id'], self.game)
        self.assertTrue(os.path.isdir(rec['folder']))

    def test_remove_refuses_the_game_folder(self):
        rec = dict(id='zz', role='test', folder=self.game, source=self.game)
        testgame.save_installs([rec])
        with self.assertRaises(ValueError):
            testgame.remove_install('zz', self.game)
        self.assertTrue(os.path.exists(os.path.join(self.game, 'blocks.naz')))

    def test_a_cross_drive_copy_needs_a_yes(self):
        with patch.object(testgame, '_same_volume', return_value=False):
            r = testgame.make_copy(self.ws)
            self.assertIn('confirm', r)
            self.assertEqual(r['confirm']['mode'], 'copied')
            self.assertGreater(r['confirm']['extra_bytes'], 5000)
            self.assertEqual(testgame.list_installs(), [])
            rec = testgame.make_copy(self.ws, allow_full=True)
            self.assertEqual(rec['mode'], 'copied')
            self.assertFalse(os.path.samefile(os.path.join(self.game, 'blocks.naz'), os.path.join(rec['folder'], 'blocks.naz')))

    def test_dest_must_be_new(self):
        d = os.path.join(self.tmp, 'busy')
        os.makedirs(d)
        open(os.path.join(d, 'a.txt'), 'w').close()
        with self.assertRaises(ValueError):
            testgame.make_copy(self.ws, d)


class ConfigTest(Base):
    def _copy(self):
        rec = testgame.make_copy(self.ws)
        return rec['folder']

    def test_pack_first_own_old_archives_out_and_a_log_key(self):
        d = self._copy()
        r = testgame.write_config(self.game, d, gm.PACK_ZIP, [gm.PACK_ZIP])
        lines = gm.read_configpc(d)
        self.assertEqual(gm.filesystem_line(lines)[0], 'todms_pack.zip')
        self.assertEqual(gm.filesystem_line(lines).count('todms_pack.zip'), 1)
        self.assertIn('fullscreen = false', lines)
        self.assertEqual(debuglog.configured_log(lines), testgame.LOG_NAME)
        self.assertTrue(r['own_log'])
        self.assertTrue(open(os.path.join(d, 'configpc.txt'), 'rb').read().endswith(b'\n'))
        # the game's own configpc.txt is untouched
        self.assertNotIn('logdumpfile', open(os.path.join(self.game, 'configpc.txt')).read())

    def test_an_existing_log_key_is_kept(self):
        with open(os.path.join(self.game, 'configpc.txt'), 'a') as f:
            f.write('logdumpfile = hd_log.txt\n')
        d = self._copy()
        r = testgame.write_config(self.game, d, None, [gm.PACK_ZIP])
        lines = gm.read_configpc(d)
        self.assertEqual(debuglog.configured_log(lines), 'hd_log.txt')
        self.assertEqual(sum(1 for ln in lines if ln.lower().startswith('logdumpfile')), 1)
        self.assertFalse(r['own_log'])
        self.assertNotIn('todms_pack.zip', gm.filesystem_line(lines))
        self.assertEqual(testgame.log_path(d), os.path.join(d, 'hd_log.txt'))


class LogTest(unittest.TestCase):
    def test_summary(self):
        s = debuglog.summarize(LOG)
        self.assertEqual(s['zips'][0], dict(name='todms_pack.zip', slot=0))
        self.assertEqual(s['blocks_loaded'], 1)
        main = next(p for p in s['pools'] if p['name'] == 'Main')
        self.assertEqual(main['peak'], 18.64)
        self.assertEqual(main['cap'], 90.0)
        self.assertEqual(main['pct'], 21)
        self.assertEqual(s['problem_count'], 1)                  # the StreamedWAV line is noise
        self.assertIn('Could not read', s['problems'][0]['line'])
        self.assertTrue(s['loading'].endswith('mm010.mission'))

    def test_crash_report_only_on_abnormal_exit(self):
        self.assertIsNone(debuglog.crash_report(0, LOG))
        c = debuglog.crash_report(0xC0000005, LOG)
        self.assertIn('access violation', c['why'])
        self.assertTrue(c['loading'].endswith('mm010.mission'))
        self.assertEqual(c['last_block'], 'StartMap')
        self.assertTrue(c['tail'])

    def test_read_chunk_follows_a_growing_and_a_truncated_file(self):
        d = tempfile.mkdtemp(prefix='todms_lg_')
        try:
            p = os.path.join(d, 'l.txt')
            open(p, 'w').write('one\n')
            a = debuglog.read_chunk(p, 0)
            open(p, 'a').write('two\n')
            b = debuglog.read_chunk(p, a['offset'])
            self.assertEqual(b['text'].strip(), 'two')
            open(p, 'w').write('x\n')
            c = debuglog.read_chunk(p, b['offset'])
            self.assertEqual(c['text'].strip(), 'x')
            self.assertFalse(debuglog.read_chunk(os.path.join(d, 'none'), 0)['exists'])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class BisectTest(unittest.TestCase):
    def run_search(self, ids, bad_set):
        """bad_set: the mods that must ALL be on for the problem to show."""
        st = bisect_mods.start(ids)
        n = 0
        while bisect_mods.pending(st) is not None:
            test = bisect_mods.pending(st)
            st = bisect_mods.answer(st, set(bad_set) <= set(test))
            n += 1
            self.assertLess(n, 20)
        return st, n

    def test_finds_every_single_culprit(self):
        ids = ['m%d' % i for i in range(7)]
        for c in ids:
            st, n = self.run_search(ids, {c})
            self.assertEqual((st['verdict'], st['culprit']), ('one', c))
            self.assertLessEqual(n, 4)

    def test_two_mods_that_need_each_other_are_reported(self):
        st, _ = self.run_search(['a', 'b', 'c', 'd'], {'a', 'd'})
        self.assertEqual(st['verdict'], 'several')

    def test_a_single_mod_that_shows_it_alone_ends_the_search(self):
        st = bisect_mods.start(['a', 'b', 'c'])
        self.assertEqual(bisect_mods.pending(st), ['a'])
        st = bisect_mods.answer(st, True)
        self.assertEqual((st['phase'], st['verdict'], st['culprit']), ('done', 'one', 'a'))
        self.assertIsNone(bisect_mods.pending(st))

    def test_one_mod_only(self):
        st = bisect_mods.start(['solo'])
        self.assertEqual(bisect_mods.pending(st), ['solo'])
        self.assertEqual(bisect_mods.answer(st, True)['culprit'], 'solo')
        self.assertEqual(bisect_mods.start([])['verdict'], 'none')

    def test_answer_does_not_change_its_argument(self):
        st = bisect_mods.start(['a', 'b', 'c'])
        before = json.dumps(st)
        bisect_mods.answer(st, True)
        self.assertEqual(json.dumps(st), before)


class SupportTest(Base):
    def test_scrub_replaces_the_user_folder(self):
        home = os.path.expanduser('~')
        t = 'a %s\\x and %s and D:\\Users\\Other\\Documents and "%s"' % (home, home.replace('\\', '/'), home.replace('\\', '\\\\'))
        s = support.scrub(t)
        self.assertNotIn(os.path.basename(home), s)
        self.assertEqual(s.count('%USERPROFILE%'), 4)

    def test_bundle_has_what_helps_and_no_saves(self):
        with patch.object(testgame, 'current', return_value=dict(id='r', status='exited', exit_code=0, log=os.path.join(self.tmp, 'none.txt'))):
            ws = type('W', (), {})()
            ws.game = type('G', (), dict(folder=self.game, exe_md5='abc', is_gog_exe=True, has_hd=lambda s: True,
                                          chain=lambda s, m='effective': ['hd_override_1.zip', 'blocks.naz']))()
            with patch.object(support.mods, 'list_mods', return_value=[dict(name='Jungle', enabled=True, level_ops=3, data_values=0)]):
                r = support.build(ws, dict(note='see %s' % os.path.expanduser('~')))
        with zipfile.ZipFile(r['path']) as z:
            names = z.namelist()
            text = ' '.join(z.read(n).decode('utf-8', 'replace') for n in names)
        self.assertIn('info.txt', names)
        self.assertIn('mods.txt', names)
        self.assertIn('configpc.txt', names)
        self.assertFalse([n for n in names if n.lower().startswith('slot')])
        self.assertNotIn(os.path.basename(os.path.expanduser('~')), text)
        self.assertIn('Jungle', text)


class SaveTest(Base):
    def test_isolated_profile_holds_settings_and_the_test_save_only(self):
        real = os.environ['TODMS_SAVES']
        os.makedirs(real)
        for n, size in (('Slot00', 0x50000), ('Slot03', 0x50000), ('Slot11', 544), ('TODGameplay_display.txt', 5)):
            open(os.path.join(real, n), 'wb').write(b'0' * size)
        rec = testgame.make_copy(self.ws)
        made = os.path.join(self.tmp, 'made')
        open(made, 'wb').write(b'save')
        with patch.object(saves, 'make', return_value=dict(path=made, log=[], notes=['n'], player=[1, 2, 3])) as mk:
            out = testgame.put_save(self.ws, rec, dict(source=os.path.join(real, 'Slot03'), pos=[1, 2, 3], god=True), True)
        self.assertEqual(out['mode'], 'isolated')
        self.assertEqual(mk.call_args.kwargs['god'], True)
        self.assertEqual(sorted(os.listdir(out['folder'])), ['Slot00', 'Slot11', 'TODGameplay_display.txt'])
        self.assertEqual(open(os.path.join(out['folder'], 'Slot00'), 'rb').read(), b'save')
        self.assertEqual(sorted(os.listdir(real)), ['Slot00', 'Slot03', 'Slot11', 'TODGameplay_display.txt'])    # the real folder is untouched

    def test_shared_folder_is_snapshotted_and_put_back(self):
        real = os.environ['TODMS_SAVES']
        os.makedirs(real)
        for n in ('Slot00', 'Slot01'):
            open(os.path.join(real, n), 'wb').write((n.encode() * 100000)[:0x50000])
        rec = testgame.make_copy(self.ws)
        made = os.path.join(self.tmp, 'made')
        open(made, 'wb').write(b'S' * 0x50000)
        with patch.object(saves, 'make', return_value=dict(path=made, log=[], notes=[], player=None)):
            put = testgame.put_save(self.ws, rec, dict(source=os.path.join(real, 'Slot01')), False)
        self.assertEqual(put['mode'], 'shared')
        self.assertEqual(put['slot'], 'Slot02')                   # a free slot, never one of the player's
        self.assertTrue(os.path.exists(os.path.join(real, 'Slot02')))
        # the game "ran": the run record is finished and the snapshot goes back
        st = dict(id='r1', status='running', pid=1, log=os.path.join(self.tmp, 'nolog'), install=rec['id'], keep=False, saves=put)
        testgame._set(st)
        testgame.finish('r1', 0)
        self.assertEqual(sorted(os.listdir(real)), ['Slot00', 'Slot01'])
        self.assertEqual(testgame.current().get('notes'), ["Your saves were put back as they were before the test."])
        self.assertFalse(os.path.exists(rec['folder']))           # the test copy went away with the run
        cur = testgame.current()
        self.assertEqual(cur['status'], 'exited')
        self.assertTrue(cur['install_removed'])

    def test_a_kept_install_stays(self):
        rec = testgame.make_copy(self.ws)
        testgame._set(dict(id='r2', status='running', pid=1, log=os.path.join(self.tmp, 'nolog'), install=rec['id'], keep=True, saves=None))
        testgame.finish('r2', 0xC0000005)
        self.assertTrue(os.path.exists(rec['folder']))
        self.assertIn('access violation', testgame.current()['crash']['why'])


if __name__ == '__main__':
    unittest.main()
