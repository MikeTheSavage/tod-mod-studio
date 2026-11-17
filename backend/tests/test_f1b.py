"""F1b: the ceiling ledger (vanilla + packages + project), the meter colours, the install gate, the Problems list, autosave and snapshots.
No game and no real data: a fake workspace with a tiny block baseline, temporary home and cache folders."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from todms import checks, game, ledger, limits, pack, problems, projstore
from test_install_foundation import Env

BLOCK = 'data_pc/overdose_the_game/maps/map06/map06.map'


class FakeWs:
    """Just enough of the workspace for the ledger: a cached level json per block."""
    def __init__(self, root, nodes=1000):
        self.root, self.nodes = root, nodes
        self.game = None
        self.catalog = dict(maps=[dict(id='map%02d' % i) for i in range(1, 10)])

    def block_key(self, entry):
        return entry.replace('/', '_')

    def block_dir(self, key):
        d = os.path.join(self.root, key)
        os.makedirs(d, exist_ok=True)
        return d

    def level_json(self, entry, progress=None):
        return dict(nodes=self.nodes, info_bytes=2_000_000, block_bytes=3_000_000, next_runtime=self.nodes + 1, entities=[])


def add_op(i, entry=BLOCK, pos=(0, 0, 0), car=False, **set_):
    o = dict(op='add', uid='u%d' % i, entry=entry, name='n%d' % i, pos=list(pos), rot=[0, 0, 0, 1], set=set_)
    if car:
        o['view'] = dict(cat='vehicle', type='vehicle_placeholder(x)')
    return o


class Env2(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        r = self.t.name
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(r, 'home'), TODMS_CACHE=os.path.join(r, 'cache'))
        self.env.start()
        self.ws = FakeWs(os.path.join(r, 'blocks'))
        self.no_pkg = patch.object(ledger, 'installed_ops', return_value=([], [], []))
        self.no_pkg.start()

    def tearDown(self):
        self.no_pkg.stop()
        self.env.stop()
        self.t.cleanup()

    def row(self, rep, lid):
        return next(r for r in rep['rows'] if r['id'] == lid)


class LedgerMaths(Env2):
    def test_used_is_vanilla_plus_packages_plus_project(self):
        self.no_pkg.stop()
        with patch.object(ledger, 'installed_ops', return_value=([add_op(i) for i in range(5)], [], ['other'])):
            rep = ledger.compute(self.ws, 'level', dict(level=[add_op(10 + i) for i in range(3)]))
        r = self.row(rep, 'L1')
        self.assertEqual(r['parts'], dict(vanilla=1000, packages=5, project=3))
        self.assertEqual(r['used'], 1008)
        self.assertEqual(r['max'], 32767)
        self.assertEqual(r['items'][0]['entry'], BLOCK)
        self.no_pkg.start()

    def test_the_worst_block_is_the_one_shown(self):
        ops = [add_op(1, entry='a/x.map'), add_op(2, entry='b/y.map'), add_op(3, entry='b/y.map')]
        rep = ledger.compute(self.ws, 'level', dict(level=ops))
        self.assertEqual(self.row(rep, 'L1')['items'][0]['entry'], 'b/y.map')
        self.assertEqual(self.row(rep, 'L1')['used'], 1002)

    def test_a_check_replaces_the_one_node_per_object_estimate(self):
        rep = ledger.compute(self.ws, 'level', dict(level=[add_op(1)]), heavy=dict(L1={BLOCK: 7}))
        r = self.row(rep, 'L1')
        self.assertEqual((r['parts']['project'], r['mode']), (7, 'check'))

    def test_the_baseline_is_cached_next_to_the_level_cache(self):
        ledger.baseline(self.ws, BLOCK)
        p = os.path.join(self.ws.block_dir(self.ws.block_key(BLOCK)), 'ledger.json')
        self.assertEqual(json.load(open(p))['nodes'], 1000)
        self.ws.nodes = 5                                   # the cache answers, the level is not read again
        self.assertEqual(ledger.baseline(self.ws, BLOCK)['nodes'], 1000)

    def test_placed_cars_are_counted_within_100_m(self):
        ops = [add_op(i, pos=(i, 0, 0), car=True) for i in range(6)] + [add_op(9, pos=(900, 0, 0), car=True)]
        r = self.row(ledger.compute(self.ws, 'level', dict(level=ops)), 'L4')
        self.assertEqual(r['used'], 6)
        self.assertEqual(r['status'], 'red')
        self.assertEqual(r['enforce'], 'warn')                 # extra cars only stay static: a warning

    def test_collision_piece_sizes(self):
        piece = dict(verts=[[0, 0, 0]] * 300, faces=[[0, 1, 2]] * 10)
        rep = ledger.compute(self.ws, 'level', dict(level=[], collision=[dict(id='s', pieces=[piece])]))
        self.assertEqual(self.row(rep, 'L15')['used'], 300)
        self.assertEqual(self.row(rep, 'L15')['status'], 'red')
        self.assertEqual(self.row(rep, 'L15_index')['used'], 40)

    def test_coordinates_and_box_sizes(self):
        ops = [add_op(1, pos=(20000, 0, 0), width=600, height=1, length=1)]
        rep = ledger.compute(self.ws, 'level', dict(level=ops))
        self.assertEqual(self.row(rep, 'L16_pos')['status'], 'red')
        self.assertEqual(self.row(rep, 'L16_box')['used'], 600)

    def test_mission_slots_and_text_length(self):
        project = dict(missions=[dict(id='a', text='x' * 1500), dict(id='b', text='short')])
        rep = ledger.compute(self.ws, 'mission', project, pid='p1')
        self.assertEqual(self.row(rep, 'L7')['used'], 2)
        t = self.row(rep, 'L11')
        self.assertEqual((t['used'], t['status']), (1500, 'red'))

    def test_map_ids_use_the_proven_ceiling_of_thirteen(self):
        rep = ledger.compute(self.ws, 'newmap', dict(maps=[dict() for _ in range(5)]), pid='n1')
        r = self.row(rep, 'L8')
        self.assertEqual((r['parts']['vanilla'], r['parts']['project'], r['used'], r['max']), (9, 5, 14, 13))
        self.assertEqual(r['status'], 'amber')          # past the measured 13 is a warning, not a stop

    def test_heavy_rows_wait_for_a_check(self):
        rep = ledger.compute(self.ws, 'level', dict(level=[]))
        for lid in ('P8', 'P5'):
            r = self.row(rep, lid)
            self.assertEqual((r['status'], r['reason'], r['mode']), ('grey', 'run Check', 'check'))
        heavy = dict(P8=dict(used=80 * 1048576, parts=dict(vanilla=70 * 1048576, packages=0, project=10 * 1048576), items=[]),
                     P5=dict(used=2_900_000, parts={}, items=[]))
        rep = ledger.compute(self.ws, 'level', dict(level=[]), heavy=heavy)
        self.assertEqual(self.row(rep, 'P8')['status'], 'amber')
        self.assertEqual(self.row(rep, 'P5')['status'], 'red')

    def test_heavy_numbers_come_from_the_check_stats(self):
        zp = os.path.join(self.t.name, 'z.zip')
        Path(zp).write_bytes(b'x' * 123)
        stats = dict(blocks={BLOCK: dict(nodes=10, info_bytes=5_000_000, max_payload=3_000_000)}, p8=(40_000_000, 1_500_000))
        h = ledger.heavy_from_stats(self.ws, stats, dict(blocks=[dict(entry=BLOCK, stage_b=dict(grafted=[dict(nodes=2), dict(nodes=3)]))]), {}, zp)
        self.assertEqual(h['P8']['used'], 41_500_000)
        self.assertEqual(h['P5']['used'], 3_000_000)
        self.assertEqual(h['P2'], 123)
        self.assertEqual(h['L1'], {BLOCK: 5})


class Colours(unittest.TestCase):
    def test_green_below_seventy_amber_to_one_hundred_red_above(self):
        top = 32767
        self.assertEqual(limits.status('L1', 0), 'ok')
        self.assertEqual(limits.status('L1', int(top * 0.69)), 'ok')
        self.assertEqual(limits.status('L1', int(top * 0.70) + 1), 'amber')
        self.assertEqual(limits.status('L1', top), 'amber')
        self.assertEqual(limits.status('L1', top + 1), 'red')

    def test_unknown_confidence_is_grey_never_green(self):
        row = dict(limits.get('L1'), id='T1', confidence='UNKNOWN (never measured)', value=10)
        with patch.dict(limits.table(), {'T1': row}):
            self.assertEqual(limits.status('T1', 0), 'grey')
            self.assertEqual(limits.status('T1', 99), 'grey')
        with patch.dict(limits.table(), {'T1': dict(row, confidence='MEASURED')}):
            self.assertEqual(limits.status('T1', 0), 'ok')

    def test_a_number_nothing_measures_is_grey(self):
        self.assertEqual(limits.status('L1', None), 'grey')
        self.assertEqual(limits.status('P12', 3), 'grey')       # a rule, no number
        self.assertEqual(limits.status('L17', 3), 'grey')       # UNKNOWN

    def test_every_unmeasured_row_of_the_table_is_grey_in_the_ledger(self):
        with tempfile.TemporaryDirectory() as r, patch.dict(os.environ, TODMS_HOME=r, TODMS_CACHE=r):
            with patch.object(ledger, 'installed_ops', return_value=([], [], [])):
                rep = ledger.compute(FakeWs(r), 'level', dict(level=[]))
        self.assertEqual(len(rep['rows']), len(limits.rows()) - 2)           # the two helper rows are not shown
        for r in rep['rows']:
            if limits.is_unknown(limits.get(r['id'])):
                self.assertEqual(r['status'], 'grey', r['id'])
                self.assertNotEqual(r['status'], 'ok')

    def test_refusing_limits_are_the_crash_ones(self):
        for lid in ('P1', 'P2', 'P8', 'M1'):
            self.assertEqual(limits.enforce(lid), 'refuse', lid)
        for lid in ('M6', 'P6', 'L4'):
            self.assertEqual(limits.enforce(lid), 'warn', lid)
        self.assertEqual(limits.level('P8', 100 * 1048576), 'error')
        self.assertEqual(limits.level('P6', 2_000_000), 'warn')

    def test_the_checker_takes_its_level_from_the_same_table(self):
        items, bad = checks.ops_items([add_op(1, width=900, height=1, length=1)])
        self.assertEqual((items[0]['level'], bad), ('error', 1))
        self.assertEqual(items[0]['ref']['uid'], 'u1')


class InstallGate(Env):
    def test_a_red_crash_limit_refuses_the_install_and_changes_nothing(self):
        before = Path(self.folder, 'configpc.txt').read_bytes()
        with patch.object(ledger, 'p8_from_pack', return_value=100 * 1048576):
            with self.assertRaisesRegex(ValueError, 'crashes while loading'):
                pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertEqual(Path(self.folder, 'configpc.txt').read_bytes(), before)
        self.assertFalse(Path(self.folder, game.PACK_ZIP).exists())

    def test_a_green_pool_installs(self):
        with patch.object(ledger, 'p8_from_pack', return_value=30 * 1048576):
            pack.apply(self.ws, 'install mods', mods=['m1'])
        self.assertTrue(Path(self.folder, game.PACK_ZIP).exists())

    def test_the_slot_limit_still_refuses_through_archives(self):
        from todms import archives
        for i in range(9):
            Path(self.folder, 'x%d.zip' % i).write_bytes(b'z')
        names = ['x%d.zip' % i for i in range(9)]
        with self.assertRaises(ValueError):
            archives.slot_check(self.folder, names, add='todms_pack.zip')

    def test_a_mod_with_an_error_is_refused_before_anything_is_touched(self):
        from todms import mods
        d = os.path.join(mods.lib_dir(), 'bad')
        os.makedirs(d)
        json.dump(dict(id='bad', name='Bad', level=[add_op(1, width=900, height=1, length=1)]), open(os.path.join(d, 'mod.json'), 'w'))
        with self.assertRaisesRegex(ValueError, 'Bad'):
            pack.apply(self.ws, 'install mods', mods=['bad'])
        self.assertFalse(Path(self.folder, game.PACK_ZIP).exists())

    def test_removing_is_never_blocked(self):
        with patch.object(ledger, 'p8_from_pack', return_value=100 * 1048576):
            pack.apply(self.ws, 'remove mods', mods=[])


class ProblemsList(Env2):
    def test_every_source_lands_in_one_list_with_a_place_to_jump_to(self):
        ops = [add_op(1, width=900, height=1, length=1), add_op(2, pos=(0, 0, 0))]
        piece = dict(verts=[[0, 0, 0]] * 300, faces=[[0, 1, 2]])
        results = dict(check=dict(checks=[dict(level='error', area='objects', title='Map06: 40000 objects (limit 32767)', detail='',
                                               ref=dict(screen='level', entry=BLOCK)),
                                          dict(level='ok', area='saves', title='fine')]),
                       nav=dict(lines=[dict(area='nav', level='error', text='route 3 has no points')]),
                       sections=dict(lines=[dict(area='sections', level='warning', text='gap of 5 m')]))
        out = problems.collect(self.ws, 'level', dict(level=ops, collision=[dict(id='s', pieces=[piece])]), results=results)
        by = {p['title']: p for p in out['problems']}
        self.assertEqual(by['box size 900.00 m is outside 0.05 .. 512 m']['jump']['uid'], 'u1')
        self.assertEqual(by['Map06: 40000 objects (limit 32767)']['jump']['entry'], BLOCK)
        self.assertEqual(by['route 3 has no points']['jump']['screen'], 'routes')
        self.assertEqual(by['gap of 5 m']['level'], 'warn')
        self.assertEqual(by['gap of 5 m']['jump']['screen'], 'sections')
        self.assertTrue(any(p['jump'].get('screen') == 'collision' for p in out['problems']))
        self.assertNotIn('fine', by)
        self.assertGreaterEqual(out['errors'], 3)
        self.assertEqual(out['problems'][0]['level'], 'error')                          # errors first

    def test_red_and_amber_meters_become_problems(self):
        heavy = dict(P8=dict(used=100 * 1048576, parts={}, items=[]), P5=dict(used=2_500_000, parts={}, items=[]))     # P8 red, P5 amber
        out = problems.collect(self.ws, 'level', dict(level=[]), heavy=heavy)
        lv = {p['title'].split(':')[0]: p['level'] for p in out['problems'] if p['source'] == 'limits'}
        self.assertEqual(lv['MAIN_ASSETS pool'], 'error')                  # a crash-class limit
        self.assertEqual(lv['Largest single asset payload in a block'], 'warn')

    def test_a_policy_limit_only_warns(self):
        project = dict(missions=[dict(id='a', text='x' * 1500)])
        out = problems.collect(self.ws, 'mission', project, pid='p')
        t = next(p for p in out['problems'] if p['source'] == 'limits' and p['title'].startswith('Text'))
        self.assertEqual(t['level'], 'warn' if limits.enforce('L11') == 'warn' else 'error')

    def test_new_map_and_mission_project_rules_are_listed(self):
        out = problems.collect(self.ws, 'newmap', dict(maps=[]))
        self.assertTrue(any(p['level'] == 'error' and p['jump']['screen'] == 'newmaps' for p in out['problems']))
        out = problems.collect(self.ws, 'mission', dict(name='', hosts=[], missions=[]), results=dict(tpl=dict(messages=[
            dict(level='error', where='m1', text='The goal zone overlaps the giver')])))
        self.assertTrue(any(p['jump'].get('mission') == 'm1' for p in out['problems']))

    def test_an_empty_clean_project_has_no_problems(self):
        out = problems.collect(self.ws, 'level', dict(level=[], collision=[]))
        self.assertEqual((out['errors'], out['warnings']), (0, 0))


class Storage(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.t.name, 'home'), TODMS_CACHE=os.path.join(self.t.name, 'cache'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def test_autosave_survives_a_forced_close_and_is_newer_than_the_saved_file(self):
        from todms import newmap
        saved = newmap.save_project(dict(maps=[dict(name='a', source='s', arrival=dict(pos=[0, 0, 0]), **{'return': dict(pos=[0, 0, 0])})]))
        pid = saved['id']
        self.assertIsNone(projstore.autosaved('newmap', pid))
        edited = dict(saved['params'], package='Edited')
        projstore.autosave('newmap', pid, edited, now=os.path.getmtime(saved['path'] + '/params.json') + 5)
        a = projstore.autosaved('newmap', pid)                          # "after a restart": read from disk, no state in memory
        self.assertEqual(a['project']['package'], 'Edited')
        self.assertTrue(a['newer'])
        projstore.autosave('newmap', pid, edited, now=os.path.getmtime(saved['path'] + '/params.json') - 5)
        self.assertFalse(projstore.autosaved('newmap', pid)['newer'])    # saved after the autosave: nothing to restore
        projstore.clear_autosave('newmap', pid)
        self.assertIsNone(projstore.autosaved('newmap', pid))

    def test_a_never_saved_project_keeps_its_draft(self):
        projstore.autosave('mission', None, dict(name='New', missions=[]))
        a = projstore.autosaved('mission', None)
        self.assertEqual(a['project']['name'], 'New')
        self.assertTrue(a['newer'])

    def test_the_working_level_mod_has_one_current_copy(self):
        projstore.autosave('level', '_current', dict(id=None, name='Mod', level=[add_op(1)]))
        self.assertEqual(len(projstore.autosaved('level', '_current')['project']['level']), 1)

    def test_bad_ids_and_kinds_are_refused(self):
        with self.assertRaises(ValueError):
            projstore.autosave('level', '../x', {})
        with self.assertRaises(ValueError):
            projstore.autosave('nope', 'x', {})

    def test_snapshots_save_list_restore_delete(self):
        a = projstore.snapshot('level', 'm1', 'First', dict(name='v1'), now=1000)
        b = projstore.snapshot('level', 'm1', 'Second', dict(name='v2'), now=2000)
        names = [s['name'] for s in projstore.list_snapshots('level', 'm1')]
        self.assertEqual(names, ['Second', 'First'])                     # newest first
        r = projstore.restore('level', 'm1', a['id'], current=dict(name='now'), now=3000)
        self.assertEqual(r['project'], dict(name='v1'))
        self.assertTrue(r['taken']['auto'])                              # the restore took its own snapshot first
        self.assertEqual(projstore.get_snapshot('level', 'm1', r['taken']['id'])['project'], dict(name='now'))
        self.assertIn('First', r['taken']['name'])
        projstore.delete_snapshot('level', 'm1', b['id'])
        self.assertEqual(sorted(s['name'] for s in projstore.list_snapshots('level', 'm1')),
                         sorted(['First', r['taken']['name']]))

    def test_restore_without_an_open_project_snapshots_the_saved_file(self):
        from todms import newmap
        saved = newmap.save_project(dict(maps=[dict(name='a', source='s', arrival=dict(pos=[0, 0, 0]), **{'return': dict(pos=[0, 0, 0])})],
                                         package='Saved'))
        s = projstore.snapshot('newmap', saved['id'], 'old', dict(maps=[], package='Old'))
        r = projstore.restore('newmap', saved['id'], s['id'])
        self.assertEqual(projstore.get_snapshot('newmap', saved['id'], r['taken']['id'])['project']['package'], 'Saved')

    def test_rotation_drops_the_automatic_snapshots_first(self):
        n = projstore.MAX_SNAPSHOTS
        keep = projstore.snapshot('level', 'm2', 'Named', dict(), now=1)
        for i in range(n + 5):
            projstore.snapshot('level', 'm2', 'auto %d' % i, dict(), auto=True, now=10 + i)
        snaps = projstore.list_snapshots('level', 'm2')
        self.assertEqual(len(snaps), n)
        self.assertIn(keep['id'], [s['id'] for s in snaps])             # the named one outlives the older automatic ones
        self.assertEqual(sum(1 for s in snaps if s['auto']), n - 1)
        self.assertNotIn('auto 0', [s['name'] for s in snaps])
        self.assertIn('auto %d' % (n + 4), [s['name'] for s in snaps])

    def test_rotation_finally_drops_old_named_ones_too(self):
        n = projstore.MAX_SNAPSHOTS
        first = projstore.snapshot('level', 'm3', 'oldest', dict(), now=1)
        for i in range(n):
            projstore.snapshot('level', 'm3', 'n%d' % i, dict(), now=10 + i)
        ids = [s['id'] for s in projstore.list_snapshots('level', 'm3')]
        self.assertEqual(len(ids), n)
        self.assertNotIn(first['id'], ids)

    def test_the_routes(self):
        from todms import server
        server.h_autosave({}, dict(kind='level', project=dict(name='x', level=[])))
        self.assertEqual(server.h_autosave_get(dict(kind='level'), None)['autosave']['project']['name'], 'x')
        server.h_autosave({}, dict(kind='level', clear=True))
        self.assertIsNone(server.h_autosave_get(dict(kind='level'), None)['autosave'])
        r = server.h_projsnaps({}, dict(action='save', kind='level', id='m9', name='Try', project=dict(name='p')))
        self.assertEqual(r['snapshots'][0]['name'], 'Try')
        r = server.h_projsnaps({}, dict(action='restore', kind='level', id='m9', snapshot=r['snapshot']['id'], project=dict(name='cur')))
        self.assertEqual(r['project'], dict(name='p'))
        self.assertEqual(len(server.h_projsnaps_get(dict(kind='level', id='m9'), None)['snapshots']), 2)


if __name__ == '__main__':
    unittest.main()
