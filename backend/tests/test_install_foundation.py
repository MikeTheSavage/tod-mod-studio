"""F1a: the unified pack, the shared archive checks, staleness, the install journal, save snapshots, restore and verify.
Everything runs on synthetic archives in temporary folders (no game, no real saves)."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import archives, game, journal, limits, mods, pack, restore, saves, snapshots, newmap, missions_tpl


def zip_at(p, entries, stored=True, comment=b''):
    with zipfile.ZipFile(p, 'w', compression=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED) as z:
        for name, data in (entries.items() if isinstance(entries, dict) else [(e, b'x') for e in entries]):
            z.writestr(name, data)
        z.comment = comment


OK_PARAMS = dict(maps=[dict(name='Map11', source='s', arrival=dict(pos=[0, 0, 0]), **{'return': dict(pos=[0, 0, 0])})])


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        r = self.t.name
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(r, 'home'), TODMS_CACHE=os.path.join(r, 'cache'),
                              TODMS_SAVES=os.path.join(r, 'saves'))
        self.env.start()
        self.run_patch = patch.object(game, 'game_running', return_value=False)
        self.run_patch.start()
        self.folder = os.path.join(r, 'game')
        os.makedirs(self.folder)
        os.makedirs(os.path.join(r, 'saves'))
        Path(self.folder, 'configpc.txt').write_bytes(b'fullscreen = 1\r\nfilesystem = hd_override.zip, blocks.naz, sounds.naz\r\n')
        for n in ('hd_override.zip',):
            zip_at(os.path.join(self.folder, n), ['data/hd.block'])
        for n in ('blocks.naz', 'sounds.naz'):
            Path(self.folder, n).write_bytes(b'naz')
        self.ws = SimpleNamespace(game=SimpleNamespace(folder=self.folder, naz=os.path.join(self.folder, 'blocks.naz'),
                                                       signature=self._sig, has_hd=lambda: True), base_mode='effective', settings={})
        self.stages = {}
        self.old = dict(pack.STAGES)
        pack.STAGES['mods'] = self._mods_stage
        pack.STAGES['newmaps'] = self._newmap_stage
        pack.STAGES['missions'] = self._missions_stage

    def tearDown(self):
        pack.STAGES.update(self.old)
        pack.CRASH_HOOK = None
        self.run_patch.stop()
        self.env.stop()
        self.t.cleanup()

    # ---- fake stages: the content depends on the inputs and on which earlier stage touched the same block
    def _sig(self):
        return game.chain_signature(self.folder, ['hd_override.zip', 'blocks.naz'])

    def _mk(self, kind, entries):
        p = os.path.join(pack.stage_dir(), '%s_%s.zip' % (kind, 'f' * 23 + str(len(os.listdir(pack.stage_dir())))))
        zip_at(p, entries)
        return p

    def _mods_stage(self, ws, ids, prior, hints, progress):
        z = self._mk('mods', {'shared/overdose.main': b'main:' + ','.join(ids).encode(), 'shared/mod.block': b'mod'})
        return dict(name='mods', zip=z, meta=dict(blocks=[dict(entry='shared/overdose.main', base='blocks.naz', bytes=4)], save_safe=True))

    def _newmap_stage(self, ws, newmaps, superseded, prior, hints, progress):
        out, recs = [], {}
        for pid, rec in newmaps.items():
            if pid in superseded:
                continue
            base = b'main:' + ','.join(sorted(newmaps)).encode()
            seen = zipfile.ZipFile(prior[-1]).read('shared/overdose.main') if prior else b''
            z = self._mk('newmap', {'shared/overdose.main': base + b'|' + seen, 'maps/%s.map' % pid: b'map'})
            out.append(dict(name='newmap:' + pid, zip=z))
            prior = list(prior) + [z]
            recs[pid] = rec
        return out, recs

    def _missions_stage(self, ws, missions, prior, hints, progress):
        ents, pins = pack.ents_pins(missions)
        if not ents:
            return None
        seen = zipfile.ZipFile(prior[-1]).read('shared/overdose.main') if prior else b''
        z = self._mk('missions', {'shared/overdose.main': b'missions|' + seen, 'shared/mission.block': b'm'})
        meta = dict(index_of={p: {m['id']: 71 + i for i, m in enumerate(s['project']['missions'])} for p, s in ents}, migrate_entries=['71:1:33'],
                    thread_keys=[], missions=[dict(id='m')], sha256=journal.file_sha(z))
        return dict(name='missions', zip=z, meta=meta, ents=ents)

    def mission_input(self, pid='p1'):
        return dict(projects={pid: dict(name='P', project=dict(missions=[dict(id='m0', type='ghost')]), newmaps={})})

    def line(self):
        return game.filesystem_line(game.read_configpc(self.folder))

    def pack_entry(self, name):
        return zipfile.ZipFile(os.path.join(self.folder, game.PACK_ZIP)).read(name)


class Limits(unittest.TestCase):
    def test_table_has_every_audit_row_and_the_fields(self):
        rows = limits.rows()
        ids = {r['id'] for r in rows}
        self.assertTrue({'P%d' % i for i in range(1, 15)} <= ids)
        self.assertTrue({'L%d' % i for i in range(1, 19)} <= ids)
        self.assertTrue({'M%d' % i for i in range(1, 10)} <= ids)
        self.assertTrue({'X1', 'X2'} <= ids)
        for r in rows:
            self.assertEqual(set(r) - {'meter_max', 'meter_note'}, {'id', 'label', 'value', 'unit', 'scope', 'effect', 'confidence', 'source', 'enforce'})
            self.assertIn(r['enforce'], ('refuse', 'warn'))

    def test_the_code_reads_its_numbers_from_the_table(self):
        from todms import checks
        self.assertEqual(limits.value('P1'), 8)
        self.assertEqual(limits.value('P2'), 0x7FFFFFFF)
        self.assertEqual(missions_tpl.SLOT_LIMIT, 8)
        self.assertEqual(missions_tpl.MISSION_SLOTS, 17)
        self.assertEqual((checks.MAX_NODES, checks.LIVE_CARS, checks.MAIN_ASSETS), (32767, 4, 90 * 1024 * 1024))

    def test_gog_has_five_archives(self):
        self.assertEqual(len(game.GOG_ARCHIVES), 5)
        self.assertEqual(game.DEFAULT_FS, game.GOG_ARCHIVES[:4])


class Slots(Env):
    def test_counts_listed_names_that_exist_and_language_variants(self):
        for n in ('videos00.naz', 'uk_sounds.naz'):
            Path(self.folder, n).write_bytes(b'x')
        r = archives.slot_count(self.folder, ['hd_override.zip', 'blocks.naz', 'sounds.naz', 'videos00.naz', 'ghost.zip'])
        self.assertEqual(r['count'], 5)                       # ghost.zip is missing: no slot; uk_sounds.naz is the variant of sounds.naz
        self.assertIn('uk_sounds.naz', r['users'])

    def test_a_directory_and_an_empty_file_take_a_slot(self):
        os.makedirs(os.path.join(self.folder, 'dir.zip'))
        Path(self.folder, 'empty.zip').write_bytes(b'')
        self.assertEqual(archives.slot_count(self.folder, ['dir.zip', 'empty.zip'])['count'], 2)

    def test_the_ninth_slot_is_refused(self):
        names = ['a%d.zip' % i for i in range(8)]
        for n in names:
            zip_at(os.path.join(self.folder, n), ['x'])
        with self.assertRaisesRegex(ValueError, 'only load 8'):
            archives.slot_check(self.folder, names, add='todms_pack.zip')
        self.assertEqual(archives.slot_check(self.folder, names, add='todms_pack.zip', remove=['a0.zip'])['count'], 8)


class ZipRules(Env):
    def test_stored_names_comment_and_extra_lengths(self):
        good = os.path.join(self.folder, 'good.zip')
        zip_at(good, {'data/a.block': b'1'})
        self.assertEqual(archives.zip_rules(good), [])
        z = os.path.join(self.folder, 'deflated.zip')
        zip_at(z, {'a.block': b'1' * 200}, stored=False)
        self.assertIn('compressed', archives.zip_rules(z)[0])
        z = os.path.join(self.folder, 'commented.zip')
        zip_at(z, {'a.block': b'1'}, comment=b'hi')
        self.assertIn('comment', archives.zip_rules(z)[0])
        z = os.path.join(self.folder, 'bad name.zip')
        zip_at(z, {'a.block': b'1'})
        self.assertTrue(archives.zip_rules(z))
        z = os.path.join(self.folder, 'names.zip')
        zip_at(z, {'data/Has Space.block': b'1', 'data/uk_x.block': b'1', 'data/UPPER.block': b'1'})
        self.assertEqual(len(archives.zip_rules(z)), 4)       # space, uk_ prefix, upper case, space again
        z = os.path.join(self.folder, 'extra.zip')            # local extra field longer than the central one
        zi = zipfile.ZipInfo('a.block')
        zi.extra = b''
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr(zi, b'1')
        with open(z, 'rb') as f:
            raw = bytearray(f.read())
        raw[28:30] = (4).to_bytes(2, 'little')
        raw[30 + len('a.block'):30 + len('a.block')] = b'\x00\x00\x00\x00'
        with open(z, 'wb') as f:
            f.write(bytes(raw))
        self.assertTrue(any('extra' in p for p in archives.zip_rules(z)))

    def test_configpc_needs_a_final_newline(self):
        self.assertEqual(archives.config_problems(self.folder), [])
        Path(self.folder, 'configpc.txt').write_bytes(b'filesystem = blocks.naz')
        self.assertIn('new line', archives.config_problems(self.folder)[0])

    def test_size_soft_and_hard_limits(self):
        p = os.path.join(self.folder, 'big.zip')
        zip_at(p, ['x'])
        with patch('os.path.getsize', return_value=1_950_000_000):
            self.assertEqual(archives.size_check(p)[0][0], 'warn')
        with patch('os.path.getsize', return_value=0x7FFFFFFF):
            self.assertEqual(archives.size_check(p)[0][0], 'error')
        self.assertEqual(archives.size_check(p), [])

    def test_a_pack_over_the_hard_limit_is_refused_before_anything_is_written(self):
        zip_at(os.path.join(pack.stage_dir(), 'x'), ['a'])      # make sure the stage folder exists
        with patch.object(archives, 'size_check', return_value=[('error', 'too big')]):
            before = Path(self.folder, 'configpc.txt').read_bytes()
            with self.assertRaisesRegex(ValueError, 'too big'):
                pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        self.assertFalse(Path(self.folder, game.PACK_ZIP).exists())
        self.assertFalse(Path(self.folder, journal.NAME).exists())
        self.assertFalse(Path(self.folder, game.PACK_ZIP + '.part').exists())


class Hashes(Env):
    def test_same_hash_different_name_is_refused(self):
        a = archives.name_crc('data/a.block')
        self.assertEqual(archives.crc_conflicts(['Data/A.block'], [('x.zip', {a: 'data/a.block'})]), [])      # same name: a normal override
        bad = archives.crc_conflicts(['data/a.block'], [('blocks.naz', {a: 'data/other.block'})])
        self.assertIn('same name hash', bad[0])
        self.assertIn('blocks.naz', bad[0])

    def test_the_hash_is_the_engines(self):
        self.assertEqual(archives.tod_crc(b''), archives.tod_crc(b''))
        try:
            from todms import paths
            paths.setup_tools()
            import todblock
        except Exception:
            self.skipTest('vendored tools not importable here')
        for n in (b'data_pc/overdose_the_game/overdose/shared/overdose.main', b'a'):
            self.assertEqual(archives.tod_crc(n), todblock.tod_crc(n))

    def test_a_pack_that_hashes_like_another_chain_entry_is_refused(self):
        other = os.path.join(self.folder, 'hd_override.zip')
        zip_at(other, ['shared/overdose.main'])
        clash = [('hd_override.zip', {archives.name_crc('shared/overdose.main'): 'shared/something.else'})]
        z = os.path.join(self.folder, 'p.zip')
        zip_at(z, ['shared/overdose.main'])
        with self.assertRaisesRegex(ValueError, 'clashes'):
            archives.preflight(self.folder, ['hd_override.zip', 'blocks.naz'], z, 'todms_pack.zip', others=clash)


class Pack(Env):
    def test_one_pack_with_all_three_parts_and_a_later_stage_wins(self):
        r = pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertEqual(self.line(), [game.PACK_ZIP, 'hd_override.zip', 'blocks.naz', 'sounds.naz'])
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'main:m1')
        pack.apply(self.ws, 'install a new map', newmaps={'nm': dict(params=OK_PARAMS, revision='r')})
        pack.apply(self.ws, 'install missions', missions=self.mission_input())
        names = sorted(f for f in os.listdir(self.folder) if f.startswith('todms_') and f.endswith('.zip'))
        self.assertEqual(names, [game.PACK_ZIP])                                    # ONE archive
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'missions|main:nm|main:m1')   # missions read the new map's output, which read the mods
        self.assertEqual(self.pack_entry('maps/nm.map'), b'map')
        self.assertEqual(self.pack_entry('shared/mod.block'), b'mod')
        rec = pack.read_record(self.folder)
        self.assertEqual(rec['stages'], ['mods', 'newmap:nm', 'missions'])
        self.assertEqual(rec['owner']['shared/overdose.main'], 'missions')
        self.assertEqual(archives.slot_count(self.folder, self.line())['count'], 4)

    def test_removing_one_part_keeps_the_others(self):
        pack.apply(self.ws, 'x', mods=['m1'], newmaps={'nm': dict(params=OK_PARAMS)}, missions=self.mission_input())
        pack.apply(self.ws, 'remove missions', missions={})
        self.assertEqual(pack.read_record(self.folder)['stages'], ['mods', 'newmap:nm'])
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'main:nm|main:m1')
        self.assertFalse(Path(self.folder, pack.MISSIONS_RECORD).exists())
        pack.apply(self.ws, 'remove mods', mods=[])
        self.assertEqual(pack.read_record(self.folder)['stages'], ['newmap:nm'])
        self.assertTrue(pack.read_inputs(self.folder)['newmaps'])
        self.assertEqual(pack.read_inputs(self.folder)['mods'], [])
        pack.apply(self.ws, 'remove a new map', newmaps={})
        self.assertFalse(Path(self.folder, game.PACK_ZIP).exists())
        self.assertEqual(self.line(), ['hd_override.zip', 'blocks.naz', 'sounds.naz'])
        self.assertFalse(Path(self.folder, pack.RECORD).exists())

    def test_a_map_used_as_a_mission_host_is_not_built_twice(self):
        proj = dict(missions=[dict(id='m0', type='ghost')])
        pack.apply(self.ws, 'x', newmaps={'nm': dict(params=OK_PARAMS)})
        pack.apply(self.ws, 'install missions', missions=dict(projects={'p': dict(name='P', project=proj, newmaps={'nm': {'maps': []}})}))
        self.assertEqual(pack.read_record(self.folder)['stages'], ['missions'])
        self.assertEqual(pack.read_inputs(self.folder)['newmaps'], {})
        self.assertEqual(pack.read_inputs(self.folder)['missions']['taken_out_new_maps'], ['nm'])

    def test_single_stage_pack_is_the_stage_archive_byte_for_byte(self):
        pack.apply(self.ws, 'install missions', missions=self.mission_input())
        stage = [f for f in os.listdir(pack.stage_dir()) if f.startswith('missions_')][0]
        self.assertEqual(Path(self.folder, game.PACK_ZIP).read_bytes(), Path(pack.stage_dir(), stage).read_bytes())

    def test_missions_stage_reads_the_earlier_stages_through_the_overlay(self):
        pack.STAGES['missions'] = self.old['missions']
        calls = []

        def fake_build_set(ws, ents, pins, out, progress=None, pid=None, extra_chain=(), overlay_entries=None):
            calls.append((list(extra_chain), overlay_entries))
            os.makedirs(out, exist_ok=True)
            zip_at(os.path.join(out, 'm.zip'), {'shared/mission.block': b'm'})
            return dict(ok=True, zip=os.path.join(out, 'm.zip'), index_of={}, migrate_entries=[], missions=[])
        prior = os.path.join(self.folder, 'prior.zip')
        zip_at(prior, ['data_pc/overdose_the_game/overdose/shared/mm010.mission'])
        with patch.object(missions_tpl, 'build_set', fake_build_set), patch.object(missions_tpl, 'chain_signature', return_value=[]):
            pack._stage_missions(self.ws, self.mission_input(), [prior], {}, None)
            pack._stage_missions(self.ws, self.mission_input('p2'), [], {}, None)
        self.assertEqual(calls[0][0], [prior])
        self.assertIn('data_pc/overdose_the_game/overdose/shared/mm010.mission', calls[0][1])
        self.assertIn('data_pc/overdose_the_game/overdose/shared/overdose.main', calls[0][1])           # the default entries stay
        self.assertEqual(calls[1], ([], None))                                                           # no earlier stage: the builder runs exactly as before

    def test_a_failing_missions_build_on_top_of_a_new_map_says_so_and_changes_nothing(self):
        def boom(*a, **k):
            raise ValueError('last fragment Map_LoaderBeam is instantiated more than once')
        pack.apply(self.ws, 'install a new map', newmaps={'nm': dict(params=OK_PARAMS)})
        before = (Path(self.folder, 'configpc.txt').read_bytes(), Path(self.folder, game.PACK_ZIP).read_bytes())
        pack.STAGES['missions'] = boom
        with self.assertRaisesRegex(ValueError, 'cannot be installed together'):
            pack.apply(self.ws, 'install missions', missions=self.mission_input())
        self.assertEqual((Path(self.folder, 'configpc.txt').read_bytes(), Path(self.folder, game.PACK_ZIP).read_bytes()), before)
        self.assertFalse(Path(self.folder, journal.NAME).exists())
        self.assertFalse(Path(self.folder, pack.MISSIONS_RECORD).exists())
        with self.assertRaisesRegex(ValueError, 'Map_LoaderBeam'):                        # without a new map the library's own message stays
            pack.apply(self.ws, 'install missions', newmaps={}, missions=self.mission_input())

    def test_installing_refuses_while_the_game_runs(self):
        with patch.object(game, 'game_running', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'close it first'):
                pack.apply(self.ws, 'x', mods=['m1'])
        self.assertFalse(Path(self.folder, journal.NAME).exists())


class Migration(Env):
    def test_the_old_three_archives_become_one_pack_in_the_same_order(self):
        zip_at(os.path.join(self.folder, game.MOD_ZIP), {'shared/overdose.main': b'mods', 'shared/mod.block': b'mod'})
        zip_at(os.path.join(self.folder, 'todms_newmap_nm.zip'), {'shared/overdose.main': b'newmap', 'maps/nm.map': b'map'})
        zip_at(os.path.join(self.folder, game.MISSIONS_ZIP), {'shared/overdose.main': b'missions', 'shared/mission.block': b'm'})
        Path(self.folder, 'configpc.txt').write_bytes(b'fullscreen = 1\r\nfilesystem = todms_missions.zip, todms_newmap_nm.zip, todms_mods.zip, hd_override.zip, blocks.naz, sounds.naz\r\n')
        journal.atomic_json(pack.installed_json(), dict(installed='2026-01-01T00:00:00', mods=['m1'], zip='x'))
        newmap.write(os.path.join(self.folder, pack.NEWMAP_RECORD), {'nm': dict(zip='todms_newmap_nm.zip', revision='r')})
        newmap.write(os.path.join(self.folder, pack.MISSIONS_RECORD), dict(zip=game.MISSIONS_ZIP, projects={'p': dict(name='P', project={}, newmaps={}, indices={})}))
        r = pack.migrate(self.ws)
        self.assertEqual(r['migrated'], ['todms_missions.zip', 'todms_newmap_nm.zip', 'todms_mods.zip'])
        self.assertEqual(self.line(), [game.PACK_ZIP, 'hd_override.zip', 'blocks.naz', 'sounds.naz'])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes().count(b'\r\n'), 2)               # line endings kept
        self.assertEqual(sorted(f for f in os.listdir(self.folder) if f.startswith('todms_') and f.endswith('.zip')), [game.PACK_ZIP])
        self.assertEqual(self.pack_entry('shared/overdose.main'), b'missions')            # the first archive on the line used to win
        self.assertEqual(self.pack_entry('maps/nm.map'), b'map')
        self.assertEqual(self.pack_entry('shared/mod.block'), b'mod')
        inp = pack.read_inputs(self.folder)
        self.assertEqual(inp['mods'], ['m1'])
        self.assertIn('nm', inp['newmaps'])
        self.assertNotIn('zip', inp['newmaps']['nm'])
        self.assertEqual(inp['missions']['zip'], game.PACK_ZIP)
        self.assertIsNone(pack.migrate(self.ws))                                          # nothing left to do
        self.assertFalse(Path(self.folder, journal.NAME).exists())


class Journal(Env):
    def installed_state_ok(self):
        self.assertEqual(self.line()[0], game.PACK_ZIP)
        rec = pack.read_record(self.folder)
        self.assertEqual(journal.file_sha(os.path.join(self.folder, game.PACK_ZIP)), rec['sha256'])
        self.assertEqual(pack.read_inputs(self.folder)['mods'], ['m1'])
        self.assertFalse(Path(self.folder, journal.NAME).exists())

    def crash_after(self, step):
        def hook(i):
            if i == step:
                raise journal.SimulatedCrash()
        pack.CRASH_HOOK = hook
        with self.assertRaises(journal.SimulatedCrash):
            pack.apply(self.ws, 'install mods', mods=['m1'])
        pack.CRASH_HOOK = None
        self.assertTrue(Path(self.folder, journal.NAME).exists())

    def test_a_crash_after_each_of_the_three_writes_is_finished_on_the_next_start(self):
        for step in (0, 1, 2):
            with self.subTest(step=step):
                self.crash_after(step)
                self.assertEqual(journal.reconcile(self.folder)['action'], 'rolled_forward')
                self.installed_state_ok()
                pack.apply(self.ws, 'remove mods', mods=[])                                  # back to a clean game for the next round
                self.assertEqual(self.line(), ['hd_override.zip', 'blocks.naz', 'sounds.naz'])

    def test_a_crash_before_the_pack_is_in_place_rolls_back_cleanly(self):
        before = Path(self.folder, 'configpc.txt').read_bytes()
        # the writes had not started: the archive is only half copied
        orig = journal.perform

        def die_early(folder, target, hook=None):
            Path(folder, target['pack_tmp']).write_bytes(Path(folder, target['pack_tmp']).read_bytes()[:10])
            raise journal.SimulatedCrash()
        with patch.object(journal, 'perform', die_early):
            with self.assertRaises(journal.SimulatedCrash):
                pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertEqual(journal.reconcile(self.folder)['action'], 'rolled_back')
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        self.assertFalse(Path(self.folder, game.PACK_ZIP + '.part').exists())
        self.assertFalse(Path(self.folder, game.PACK_ZIP).exists())
        self.assertEqual(pack.read_inputs(self.folder)['mods'], [])
        self.assertFalse(Path(self.folder, journal.NAME).exists())

    def test_a_crash_while_building_leaves_the_game_untouched(self):
        before = sorted(os.listdir(self.folder))
        def boom(*a, **k):
            raise RuntimeError('build failed')
        pack.STAGES['mods'] = boom
        with self.assertRaisesRegex(RuntimeError, 'build failed'):
            pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertEqual(sorted(os.listdir(self.folder)), before)
        # and an intent record left by a killed app is discarded at the next start
        journal.begin(self.folder, 'install mods', journal.capture(self.folder, pack.record_paths(self.folder)))
        Path(self.folder, game.PACK_ZIP + '.part').write_bytes(b'half')
        self.assertEqual(journal.reconcile(self.folder)['action'], 'discarded')
        self.assertEqual(sorted(os.listdir(self.folder)), before)

    def test_installed_json_is_written_atomically(self):
        p = os.path.join(self.t.name, 'x.json')
        journal.atomic_json(p, dict(a=1))
        self.assertFalse(os.path.exists(p + '.part'))
        with open(p) as f:
            self.assertEqual(json.load(f), dict(a=1))


class Stale(Env):
    def test_a_changed_chain_archive_is_reported(self):
        self.assertFalse(pack.stale(self.ws)['stale'])                                     # nothing installed
        pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertFalse(pack.stale(self.ws)['stale'])
        with open(pack.installed_json()) as f:
            inst = json.load(f)
        self.assertEqual(inst['chain_signature'][0][0], 'hd_override.zip')                  # recorded in installed.json too
        zip_at(os.path.join(self.folder, 'hd_override.zip'), ['data/hd.block', 'data/new.block'])
        s = pack.stale(self.ws)
        self.assertTrue(s['stale'])
        self.assertEqual(s['changed'], ['hd_override.zip'])
        pack.rebuild(self.ws)
        self.assertFalse(pack.stale(self.ws)['stale'])
        self.assertEqual(pack.read_inputs(self.folder)['mods'], ['m1'])


class Snapshots(Env):
    def fill(self, n):
        for i in range(11):
            Path(self.t.name, 'saves', 'Slot%02d' % i).write_bytes(bytes([n]) * 64)
        Path(self.t.name, 'saves', 'BFSlot03').write_bytes(b'bf' + bytes([n]))
        Path(self.t.name, 'saves', 'TODGameplay_display.txt').write_text('res=%d' % n)

    def test_rotation_keeps_the_last_twenty_and_includes_sidecars(self):
        for n in range(25):
            self.fill(n)
            s = snapshots.take(saves.saves_dir(), 'test %d' % n)
        listed = snapshots.list_snapshots()
        self.assertEqual(len(listed), 20)
        self.assertEqual(listed[0]['label'], 'test 24')
        self.assertEqual(listed[0]['files'], 13)
        d = Path(snapshots.root(), listed[0]['id'], 'saves')
        self.assertTrue((d / 'BFSlot03').exists() and (d / 'TODGameplay_display.txt').exists())

    def test_an_unchanged_folder_is_not_copied_again(self):
        self.fill(1)
        a = snapshots.take(saves.saves_dir(), 'a')
        b = snapshots.take(saves.saves_dir(), 'b')
        self.assertTrue(b.get('reused'))
        self.assertEqual(len(snapshots.list_snapshots()), 1)

    def test_restore_takes_its_own_snapshot_first_and_replaces_whole_files(self):
        self.fill(1)
        a = snapshots.take(saves.saves_dir(), 'one')
        self.fill(2)
        Path(self.t.name, 'saves', 'Extra').write_bytes(b'new')
        r = snapshots.restore(a['id'], saves.saves_dir())
        self.assertEqual(Path(self.t.name, 'saves', 'Slot03').read_bytes(), bytes([1]) * 64)
        self.assertFalse(Path(self.t.name, 'saves', 'Extra').exists())
        self.assertEqual(Path(self.t.name, 'saves', 'BFSlot03').read_bytes(), b'bf\x01')
        self.assertEqual(len(snapshots.list_snapshots()), 2)                                # the state before the restore is kept
        snapshots.restore(r['backup']['id'], saves.saves_dir())
        self.assertEqual(Path(self.t.name, 'saves', 'Slot03').read_bytes(), bytes([2]) * 64)
        self.assertEqual(Path(self.t.name, 'saves', 'Extra').read_bytes(), b'new')

    def test_every_install_copies_the_saves_first(self):
        self.fill(7)
        pack.apply(self.ws, 'install mods', mods=['m1'])
        s = snapshots.list_snapshots()
        self.assertEqual([x['label'] for x in s], ['install mods'])
        pack.apply(self.ws, 'remove mods', mods=[])
        self.assertEqual(len(snapshots.list_snapshots()), 1)                                 # unchanged saves: no second copy

    def test_the_saves_folder_can_be_overridden(self):
        self.assertEqual(saves.saves_dir(), os.path.join(self.t.name, 'saves'))


class Restore(Env):
    def test_restore_to_vanilla_removes_every_archive_and_config_entry(self):
        before = Path(self.folder, 'configpc.txt').read_bytes()
        pack.apply(self.ws, 'x', mods=['m1'], newmaps={'nm': dict(params=OK_PARAMS)}, missions=self.mission_input())
        self.assertEqual(self.line()[0], game.PACK_ZIP)
        r = restore.restore_vanilla(self.ws)
        self.assertEqual(r['left'], [])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        for n in (game.PACK_ZIP, pack.RECORD, pack.NEWMAP_RECORD, pack.MISSIONS_RECORD, journal.NAME):
            self.assertFalse(Path(self.folder, n).exists(), n)
        self.assertTrue(Path(self.folder, 'hd_override.zip').exists())                      # other archives are never touched
        self.assertEqual(pack.read_inputs(self.folder), dict(mods=[], newmaps={}, missions={}, alloc=dict(format=1, owners={})))
        self.assertTrue(restore.list_backups(self.ws))                                       # a backup was taken first

    def test_backup_list_restore_and_delete(self):
        pack.apply(self.ws, 'install mods', mods=['m1'])
        pack.apply(self.ws, 'remove mods', mods=[])
        items = restore.list_backups(self.ws)
        points = [b for b in items if b['kind'] == 'restore point']
        self.assertEqual([b['label'] for b in points], ['remove mods', 'install mods'])
        self.assertTrue(all(b['created'] and b['bytes'] > 0 for b in points))
        restore.restore_backup(self.ws, points[0]['id'])                                     # the state before "remove mods": m1 installed
        self.assertEqual(pack.read_inputs(self.folder)['mods'], ['m1'])
        self.assertEqual(self.line()[0], game.PACK_ZIP)
        n = len(restore.list_backups(self.ws))
        self.assertEqual(restore.delete_backups(self.ws, [points[1]['id']])['deleted'], 1)
        self.assertEqual(len(restore.list_backups(self.ws)), n - 1)

    def test_a_config_file_backup_can_be_restored(self):
        pack.apply(self.ws, 'install mods', mods=['m1'])
        restore.restore_backup(self.ws, 'file:configpc.txt.todms_backup')
        self.assertEqual(self.line(), ['hd_override.zip', 'blocks.naz', 'sounds.naz'])

    def test_verify_records_then_detects_a_change_and_repairs_from_a_backup(self):
        names = game.GOG_ARCHIVES + ['TOD.exe']
        for n in names:
            Path(self.folder, n).write_bytes(n.encode())
        with patch.dict(restore.KNOWN, {}, clear=True):
            a = restore.verify(self.ws)
            self.assertEqual({f['status'] for f in a['files']}, {'recorded'})
            self.assertEqual({f['status'] for f in restore.verify(self.ws)['files']}, {'ok'})
            shutil_copy = Path(self.folder, 'sounds.naz').read_bytes()
            Path(self.folder, 'sounds.naz.todms_backup').write_bytes(shutil_copy)
            Path(self.folder, 'sounds.naz').write_bytes(b'tampered')
            b = {f['name']: f for f in restore.verify(self.ws)['files']}
            self.assertEqual(b['sounds.naz']['status'], 'changed')
            self.assertTrue(b['sounds.naz']['backup'])
            self.assertFalse(b['blocks.naz']['backup'])
            self.assertEqual(restore.repair(self.ws, ['sounds.naz', 'blocks.naz'])['restored'], ['sounds.naz'])
            self.assertEqual({f['status'] for f in restore.verify(self.ws)['files']}, {'ok'})

    def test_verify_knows_the_gog_files(self):
        self.assertEqual(restore.KNOWN['TOD.exe']['md5'], game.GOG_EXE_MD5)
        self.assertEqual(len(restore.KNOWN['blocks.naz']['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
