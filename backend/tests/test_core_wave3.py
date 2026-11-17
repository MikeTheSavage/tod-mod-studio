"""Wave 3 core: map numbers, recipe v2 (entrances, extension sections), the merged pack, the ledger rows, removal and the start_mission fix.
Pure tests run anywhere; the ones marked real read the proof game folder (read only) and skip without it."""
import copy
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from todms import compat, game, ledger, limits, mapalloc, mapnet, newmap, pack, saves
from test_install_foundation import Env, zip_at, OK_PARAMS

PROOF = Path(os.environ.get('TODMS_PROOF', '/no-proof-copy')) / 'game'


def mp(name='Map11_RunawayTrain', **kw):
    m = dict(name=name, source='map10_runawaytrain', arrival=dict(pos=[10, 4, 10]), **{'return': dict(pos=[10, 5, 0], target_map='A', target_submap='B', teleport_to='T')})
    m.update(kw)
    return m


def project(*maps, uid=None):
    p = dict(package='t', maps=list(maps))
    if uid:
        p['uid'] = uid
    return p


def entry(**kw):
    return dict(dict(id='e1', block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66], size=[12, 6, 2]), **kw)


class Allocation(unittest.TestCase):
    def test_numbers_are_given_in_install_order_and_start_at_the_games_own_limits(self):
        a = mapalloc.assign({}, [('a', project(mp('Map11_RunawayTrain')), 'A'), ('b', project(mp('Map12_RunawayTrain')), 'B')])
        self.assertEqual(a['owners']['a']['maps'], [dict(map_id=9, submap_id=21)])
        self.assertEqual(a['owners']['b']['maps'], [dict(map_id=10, submap_id=22)])
        lim = mapalloc.limits(a)
        self.assertEqual((lim['maps_max'], lim['submaps_max'], lim['total_maps'], lim['holes']), (11, 23, 11, []))

    def test_numbers_stay_with_a_map_when_another_is_removed_and_added(self):
        a = mapalloc.assign({}, [('a', project(mp()), 'A'), ('b', project(mp('Map12_RunawayTrain')), 'B')])
        b_before = a['owners']['b']['maps']
        a2 = mapalloc.assign(a, [('b', project(mp('Map12_RunawayTrain')), 'B')])             # A removed
        self.assertEqual(a2['owners']['b']['maps'], b_before)
        self.assertEqual(mapalloc.limits(a2)['holes'], [9])                                  # the gap is reported, not closed
        a3 = mapalloc.assign(a2, [('b', project(mp('Map12_RunawayTrain')), 'B'), ('c', project(mp('Map13_RunawayTrain')), 'C')])
        self.assertEqual(a3['owners']['c']['maps'], [dict(map_id=9, submap_id=21)])          # the freed numbers are used again, lowest first
        self.assertEqual(a3['owners']['b']['maps'], b_before)

    def test_a_project_that_gains_a_map_keeps_the_numbers_it_had(self):
        a = mapalloc.assign({}, [('a', project(mp()), 'A')])
        a2 = mapalloc.assign(a, [('a', project(mp(), mp('Map12_RunawayTrain')), 'A'), ('b', project(mp('Map13_RunawayTrain')), 'B')])
        self.assertEqual(a2['owners']['a']['maps'], [dict(map_id=9, submap_id=21), dict(map_id=10, submap_id=22)])
        self.assertEqual(a2['owners']['b']['maps'], [dict(map_id=11, submap_id=23)])

    def test_an_extension_section_takes_a_section_number_only(self):
        ext = dict(name='Yard', placement='extension', host=dict(block='x'))
        a = mapalloc.assign({}, [('a', project(mp(), ext), 'A')])
        self.assertEqual(a['owners']['a']['maps'], [dict(map_id=9, submap_id=21)])
        self.assertEqual(a['owners']['a']['sections'], [22])
        inj = mapalloc.inject(project(mp(), ext), a['owners']['a'])
        self.assertEqual((inj['maps'][0]['map_id'], inj['maps'][0]['submap_id'], inj['maps'][1]['section_id']), (9, 21, 22))
        self.assertNotIn('map_id', inj['maps'][1])

    def test_more_than_thirteen_maps_is_flagged_not_measured(self):
        owners = [('k%d' % i, project(mp('Map%02d_RunawayTrain' % (11 + i))), 'x') for i in range(5)]
        lim = mapalloc.limits(mapalloc.assign({}, owners))
        self.assertEqual((lim['total_maps'], lim['over_measured']), (14, 1))

    def test_default_numbers_are_recognised(self):
        self.assertTrue(mapalloc.is_default(None))
        self.assertTrue(mapalloc.is_default(dict(maps=[dict(map_id=9, submap_id=21)], sections=[])))
        self.assertFalse(mapalloc.is_default(dict(maps=[dict(map_id=10, submap_id=22)], sections=[])))

    def test_the_owner_is_the_projects_permanent_uid(self):
        self.assertEqual(mapalloc.key_of(dict(uid='abc12345'), 'p1'), 'abc12345')
        self.assertEqual(mapalloc.key_of({}, 'p1'), 'p_p1')


class Validation(unittest.TestCase):
    def test_a_lock_by_cash_items_or_time_is_refused_with_a_reason(self):
        for k in ('cash', 'item', 'time_of_day'):
            with self.assertRaisesRegex(ValueError, 'cannot be locked by %s' % k):
                newmap.validate(project(mp(entries=[entry(lock={k: 5})])))
        newmap.validate(project(mp(entries=[entry(lock=dict(mission=79))])))

    def test_a_map_needs_one_unlocked_way_out(self):
        m = mp(entries=[entry(one_way=True, back=dict(pos=[0, 0, 0]))])
        m.pop('return')
        with self.assertRaisesRegex(ValueError, 'way out'):
            newmap.validate(project(m))
        m2 = mp(entries=[entry(back=dict(pos=[0, 0, 0]))])
        m2.pop('return')
        newmap.validate(project(m2))

    def test_entrance_options(self):
        newmap.validate(project(mp(entries=[entry(arrive=dict(pos=[1, 2, 3], yaw=90), prompt='use', vehicle=True,
                                                  back=dict(pos=[1, 2, 3], spot=dict(pos=[4, 5, 6], yaw=180)))])))
        with self.assertRaisesRegex(ValueError, 'touch or use'):
            newmap.validate(project(mp(entries=[entry(prompt='kick')])))
        with self.assertRaisesRegex(ValueError, 'true or false'):
            newmap.validate(project(mp(entries=[entry(vehicle='yes')])))

    def test_extension_and_aligned(self):
        ext = dict(name='Yard', placement='extension', host=dict(block='submap01_map02_lostoros_downtown.submap',
                   enter=dict(pos=[-237, 2.5, -43]), leave=dict(pos=[-255, 2.5, -43])), carry=dict(mode='all'))
        newmap.validate(project(ext))
        bad = copy.deepcopy(ext)
        bad['carry'] = dict(mode='some')
        with self.assertRaises(ValueError):
            newmap.validate(project(bad))
        bad = copy.deepcopy(ext)
        bad['carry'] = dict(mode='region')
        with self.assertRaisesRegex(ValueError, 'region'):
            newmap.validate(project(bad))
        newmap.validate(project(mp(placement='aligned', neighbour=dict(map='Map02', edge='east', offset=[0, 0, 100]))))
        with self.assertRaisesRegex(ValueError, 'neighbour'):
            newmap.validate(project(mp(placement='aligned')))

    def test_a_saved_project_gets_a_permanent_uid(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, TODMS_HOME=t):
            p = newmap.save_project(project(mp()))
            uid = p['params']['uid']
            self.assertTrue(uid)
            again = newmap.save_project(newmap.get_project(p['id'])['params'], p['id'])
            self.assertEqual(again['params']['uid'], uid)


class Expansion(unittest.TestCase):
    def test_without_the_generator_the_recipe_passes_through(self):
        p = project(mp())
        with patch.dict(sys.modules, {'todms.mapgen': None}) if False else patch.object(newmap.importlib.util, 'find_spec', return_value=None):
            sys.modules.pop('todms.mapgen', None)
            self.assertIs(newmap.expand(p), p)

    def test_the_generator_is_called_when_it_exists(self):
        stub = types.ModuleType('todms.mapgen')
        seen = []

        def expand(params):
            seen.append(params)
            out = copy.deepcopy(params)
            out['maps'][0]['walls'] = [dict(name='W', pos=[0, 0, 0], size=[1, 1, 1])]
            return out
        stub.expand = expand
        p = project(mp(terrain='hills'))
        with patch.dict(sys.modules, {'todms.mapgen': stub}):
            out = newmap.expand(p)
            prep = newmap.prepared(p, dict(maps=[dict(map_id=11, submap_id=23)], sections=[]))
        self.assertEqual(out['maps'][0]['walls'][0]['name'], 'W')
        self.assertNotIn('walls', p['maps'][0])                                  # the caller's recipe is not touched
        self.assertEqual((prep['maps'][0]['map_id'], prep['maps'][0]['submap_id']), (11, 23))
        self.assertEqual(len(seen), 2)

    def test_a_module_without_expand_changes_nothing(self):
        stub = types.ModuleType('todms.mapgen')
        p = project(mp())
        with patch.dict(sys.modules, {'todms.mapgen': stub}):
            self.assertIs(newmap.expand(p), p)


class RecipeHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = newmap.load_recipe()

    def test_ids_follow_the_limits_and_honour_given_numbers(self):
        ids, mm, sm = self.r.plan_ids([dict(), dict()], 9, 21)
        self.assertEqual((ids, mm, sm), ([(9, 21), (10, 22)], 11, 23))
        ids, mm, sm = self.r.plan_ids([dict(map_id=10, submap_id=22)], 9, 21)
        self.assertEqual((ids, mm, sm), ([(10, 22)], 11, 23))                    # a gap below stays; the limits cover the highest number
        ids, mm, sm = self.r.plan_ids([dict(placement='extension', section_id=21)], 9, 21)
        self.assertEqual((ids, mm, sm), ([(None, 21)], 9, 22))
        with self.assertRaisesRegex(Exception, 'repeat'):
            self.r.plan_ids([dict(map_id=9), dict(map_id=9)], 9, 21)

    def test_facing_by_yaw(self):
        q = self.r.arrive_orient(dict(yaw=90))
        self.assertAlmostEqual(q[1], math.sqrt(0.5), 6)
        self.assertAlmostEqual(q[3], math.sqrt(0.5), 6)
        self.assertEqual(self.r.arrive_orient(dict(orient=[0, 1, 0, 0])), [0, 1, 0, 0])
        self.assertEqual(self.r.arrive_orient({}), [0.0, 0.0, 0.0, 1.0])

    def test_facing_direction_measured_in_game(self):
        # runs p1_face0 / p1_face90 (wave 3 proofs): a step from a yaw 0 arrival went +z, from yaw 90 it went -x
        for yaw, want in ((0, (0, 1)), (90, (-1, 0)), (180, (0, -1)), (270, (1, 0))):
            x, z = self.r.facing_vector(yaw)
            self.assertAlmostEqual(x, want[0], 6)
            self.assertAlmostEqual(z, want[1], 6)

    def test_loader_options_use_lock_and_section_swap(self):
        plain = self.r.loader_op('L', [0, 0, 0], [0, 0, 0, 1], [4, 4, 2], 'T', 'SPOT', {})
        self.assertNotIn('flags', plain['set'])
        self.assertEqual(len(plain['child_sets']), 3)
        use = self.r.loader_op('L', [0, 0, 0], [0, 0, 0, 1], [4, 4, 2], 'T', 'SPOT', {}, use=True, locked=True)
        self.assertNotIn('flags', use['set'])                                     # the lock is a folder around the box (flags 1 on the box did nothing in game)
        lk = self.r.locked_loader_op('L', [1, 2, 3], [0, 0, 0, 1], [4, 4, 2], 'T', 'SPOT', {}, use=True)
        self.assertEqual(lk['set']['flags'], 1)                                  # the holding Folder starts disabled (shipped way)
        self.assertEqual(lk['child_sets'][0]['set']['pos'], [1, 2, 3])
        self.assertEqual(lk['child_sets'][1]['set'], dict(TrueOn=2))
        self.assertEqual(use['child_sets'][0]['set'], dict(TrueOn=2))             # fires on USE
        swap = self.r.loader_op('L', [0, 0, 0], [0, 0, 0, 1], [4, 4, 2], 'SUBMAP06', None, {})
        self.assertNotIn('Teleport_to', swap['child_sets'][0]['set'])
        gate = self.r.gate_op('G', ['a', 'b'], 79, {}, [0, 4, 0])
        cond = gate['child_sets'][0]['set']
        self.assertEqual((cond['TrueOn'], cond['LastMission']), (6, 79))
        self.assertEqual([c['set']['TargetName'] for c in gate['child_sets'][1:]], ['a', 'b', 'a', 'b'])
        self.assertTrue(all(c['set']['ActionType'] == 5 for c in gate['child_sets'][1:]))

    def test_the_lock_refusals_and_the_way_out_check(self):
        checks = []
        with self.assertRaisesRegex(Exception, 'cannot be locked by cash'):
            self.r.check_loader_options(mp(entries=[entry(lock=dict(cash=100))]), checks)
        checks = []
        m = mp(entries=[entry(one_way=True, back=dict(pos=[0, 0, 0]))])
        m.pop('return')
        self.r.check_loader_options(m, checks)
        self.assertEqual(checks[-1]['result'], 'FAIL')
        checks = []
        self.r.check_loader_options(mp(entries=[entry(one_way=True)]), checks)
        self.assertEqual(checks[-1]['result'], 'PASS')

    def test_arrival_must_be_clear_of_the_way_out(self):
        m = mp(arrival=dict(pos=[10, 4, 10]))
        m['return'] = dict(pos=[10, 5, 0], size=[8, 8, 2], orient=[0, 0, 0, 1], target_map='A', target_submap='B', teleport_to='T')
        checks = []
        self.r.check_arrival_clear(m, [('arrival', [10, 5, 0.5])], checks)
        self.assertEqual(checks[-1]['result'], 'FAIL')                             # inside the box
        checks = []
        self.r.check_arrival_clear(m, [('arrival', [10, 5, 3.0])], checks)
        self.assertEqual(checks[-1]['result'], 'WARN')                             # 2 m from the face
        checks = []
        self.r.check_arrival_clear(m, [('arrival', [10, 5, 9.0])], checks)
        self.assertEqual(checks[-1]['result'], 'PASS')
        checks = []                                                                # an entrance's own way back counts too
        m2 = mp(entries=[entry(back=dict(pos=[50, 5, 50], size=[4, 4, 4]))])
        self.r.check_arrival_clear(m2, [('arrival', [50, 5, 51])], checks)
        self.assertTrue(any(c['result'] == 'FAIL' for c in checks))

    def test_a_turned_box(self):
        q = [0, math.sqrt(0.5), 0, math.sqrt(0.5)]                                 # 90 degrees about Y: the long side now runs along x
        self.assertTrue(self.r._in_box([5, 0, 0], [0, 0, 0], q, [2, 2, 12]))
        self.assertFalse(self.r._in_box([0, 0, 5], [0, 0, 0], q, [2, 2, 12]))


class PackCoexistence(Env):
    """The pack with fake stages that record what they are asked to build (no game needed)."""

    def newmaps(self, *ids):
        return {i: dict(params=project(mp('Map%d_RunawayTrain' % (11 + n)), uid='uid%05d' % n), name=i) for n, i in enumerate(ids)}

    def test_the_allocation_is_recorded_with_the_pack_and_stays_when_another_map_goes(self):
        pack.apply(self.ws, 'install a new map', newmaps=self.newmaps('a', 'b'))
        al = mapalloc.read(self.folder)
        self.assertEqual(al['owners']['uid00000']['maps'], [dict(map_id=9, submap_id=21)])
        self.assertEqual(al['owners']['uid00001']['maps'], [dict(map_id=10, submap_id=22)])
        recs = self.newmaps('a', 'b')
        recs.pop('a')
        pack.apply(self.ws, 'remove a new map', newmaps=recs)
        al = mapalloc.read(self.folder)
        self.assertEqual(list(al['owners']), ['uid00001'])
        self.assertEqual(al['owners']['uid00001']['maps'], [dict(map_id=10, submap_id=22)])
        pack.apply(self.ws, 'remove a new map', newmaps={})
        self.assertFalse(os.path.exists(mapalloc.path(self.folder)))

    def test_a_switched_off_map_keeps_its_numbers_and_adds_nothing(self):
        recs = self.newmaps('a', 'b')
        pack.apply(self.ws, 'install a new map', newmaps=recs)
        recs['a']['disabled'] = True
        seen = []

        def stage(ws, newmaps, superseded, prior, hints, progress):
            seen.append(sorted(newmaps))
            return self.old['newmaps'](ws, newmaps, superseded, prior, hints, progress) if False else ([], {k: v for k, v in newmaps.items()})
        with patch.dict(pack.STAGES, {'newmaps': stage}):
            pack.build(self.ws, dict(mods=[], newmaps=recs, missions={}, alloc=mapalloc.read(self.folder)))
        self.assertTrue(mapalloc.read(self.folder)['owners']['uid00000'])        # still reserved

    def test_two_maps_are_built_in_one_pass(self):
        calls = []

        def fake_build(ws, params, out_dir, overlay=None, progress=None, alloc_entry=None, expanded=False):
            calls.append((params, overlay, expanded))
            os.makedirs(out_dir, exist_ok=True)
            z = os.path.join(out_dir, 'stream_override.zip')
            zip_at(z, {'shared/overdose.main': b'm'})
            return z
        recs = self.newmaps('a', 'b')
        alloc = mapalloc.assign({}, pack.owners_of(dict(newmaps=recs, missions={})))
        with patch.object(newmap, 'build_params', fake_build), patch.object(pack, 'STAGES', dict(pack.STAGES, newmaps=self.old['newmaps'])):
            out, got = pack._stage_newmaps(self.ws, recs, set(), [], dict(alloc=alloc), None)
        self.assertEqual(len(calls), 1)                                          # ONE pass: shared host blocks are replayed once
        self.assertEqual([m['name'] for m in calls[0][0]['maps']], ['Map11_RunawayTrain', 'Map12_RunawayTrain'])
        self.assertEqual([(m['map_id'], m['submap_id']) for m in calls[0][0]['maps']], [(9, 21), (10, 22)])
        self.assertTrue(calls[0][2])
        self.assertEqual([s['name'] for s in out], ['newmaps'])
        self.assertEqual(sorted(got), ['a', 'b'])

    def test_missions_and_standalone_maps_share_one_pass(self):
        seen = {}

        def fake_set(ws, ents, pins, out, progress=None, pid=None, extra_chain=(), overlay_entries=None, alloc=None, extra_maps=None):
            seen.update(extra=extra_maps, alloc=alloc, chain=list(extra_chain))
            os.makedirs(out, exist_ok=True)
            zip_at(os.path.join(out, 'm.zip'), {'shared/overdose.main': b'm'})
            return dict(ok=True, zip=os.path.join(out, 'm.zip'), index_of={}, migrate_entries=[], missions=[])
        from todms import missions_tpl
        recs = self.newmaps('a', 'b')
        with patch.object(missions_tpl, 'build_set', fake_set), patch.object(missions_tpl, 'chain_signature', return_value=[]), \
                patch.dict(pack.STAGES, dict(self.old)):
            state = dict(mods=[], newmaps=recs, missions=self.mission_input(), alloc=mapalloc.assign({}, pack.owners_of(dict(newmaps=recs, missions={}))))
            b = pack.build(self.ws, state, hints={'missions_built': None})
        self.assertEqual([n for n, _ in seen['extra']], ['a', 'b'])              # both maps ride in the missions pass
        self.assertEqual(seen['chain'], [])                                      # no map stage in front: one overdose.main edit
        self.assertEqual([s['name'] for s in b['stages']], ['missions'])
        self.assertEqual(sorted(b['newmaps']), ['a', 'b'])                       # and both stay recorded for a later removal of the missions

    def test_missions_in_front_of_a_frozen_map_keep_the_old_chain(self):
        from todms import missions_tpl
        frozen = os.path.join(self.folder, 'frozen.zip')
        zip_at(frozen, {'shared/overdose.main': b'f'})
        recs = self.newmaps('a')
        recs['a']['frozen'] = frozen
        hints = {}
        with patch.dict(pack.STAGES, dict(self.old)), patch.object(missions_tpl, 'chain_signature', return_value=[]):
            pack.STAGES['missions'] = lambda *a, **k: None
            pack.build(self.ws, dict(mods=[], newmaps=recs, missions=self.mission_input(), alloc={}), hints=hints)
        self.assertNotIn('extra_maps', hints)


class SharedHosts(unittest.TestCase):
    def test_a_block_several_things_add_to_is_listed(self):
        nm = {'a': dict(name='A', params=project(mp(entries=[entry()]))), 'b': dict(name='B', params=project(mp('Map12_RunawayTrain', entries=[entry(id='x')])))}
        ms = dict(projects={'p': dict(name='Ghost', project=dict(hosts=[dict(kind='existing', block='submap01_map02_lostoros_downtown.submap')]), newmaps={})})
        out = compat.shared_hosts([], nm, ms)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['block'], 'submap01_map02_lostoros_downtown.submap')
        self.assertEqual({o['kind'] for o in out[0]['owners']}, {'new map', 'missions'})
        self.assertEqual(compat.shared_hosts([], {'a': nm['a']}, None), [])      # one owner alone is no sharing

    def test_a_switched_off_map_is_not_listed(self):
        nm = {'a': dict(name='A', params=project(mp(entries=[entry()])), disabled=True),
              'b': dict(name='B', params=project(mp('Map12_RunawayTrain', entries=[entry(id='x')])))}
        self.assertEqual(compat.shared_hosts([], nm, None), [])


class Links(unittest.TestCase):
    def test_the_atlas_link_layer(self):
        ext = dict(name='Yard', placement='extension', host=dict(block='submap01_map02_lostoros_downtown.submap', enter=dict(pos=[1, 2, 3]),
                                                                 leave=dict(pos=[4, 5, 6])))
        p = project(mp(entries=[entry(vehicle=True, lock=dict(mission=79), arrive=dict(pos=[1, 1, 1]), back=dict(pos=[2, 2, 2])),
                                entry(id='e2', one_way=True)]), ext)
        out = mapnet.links_from([('k', 'Test', p)])
        kinds = [(x['kind'], x.get('entry')) for x in out['links']]
        self.assertIn(('enter', 'e1'), kinds)
        self.assertIn(('back', 'e1'), kinds)
        self.assertIn(('enter', 'e2'), kinds)
        self.assertIn(('section', None), kinds)
        self.assertIn(('section_back', None), kinds)
        e1 = [x for x in out['links'] if x['kind'] == 'enter' and x['entry'] == 'e1'][0]
        self.assertTrue(e1['vehicle'])
        self.assertEqual(e1['lock'], dict(mission=79))
        e2 = [x for x in out['links'] if x['kind'] == 'enter' and x['entry'] == 'e2'][0]
        self.assertTrue(e2['one_way'])
        self.assertEqual(sorted(m['name'] for m in out['maps']), ['Map11_RunawayTrain', 'Yard'])

    def test_plain_labels(self):
        self.assertEqual(mapnet.block_label('submap01_map02_lostoros_downtown.submap'), 'Map02 los toros downtown, section 1')
        self.assertEqual(mapnet.block_label('mainmap_map04_lostoros_train_harbour.map'), 'Map04 los toros train harbour')


class LedgerRows(unittest.TestCase):
    def ws(self, folder=None):
        return types.SimpleNamespace(game=types.SimpleNamespace(folder=folder) if folder else None, catalog=dict(maps=[0] * 9))

    def test_rows_exist_with_plain_labels_and_no_ids(self):
        for lid in ('Q_main', 'Q_aux', 'S_nodes', 'L5', 'L8', 'L8_sections'):
            r = limits.get(lid)
            self.assertFalse(r['label'][:1].isupper() is False)
            self.assertNotRegex(r['label'], r'\b[LPQS]\d')
        self.assertEqual(limits.meter_max('Q_main'), 10000)
        self.assertEqual(limits.meter_max('Q_aux'), 12200)
        self.assertEqual(limits.meter_max('S_nodes'), 3000)
        self.assertEqual(limits.meter_max('L5'), 8)

    def test_quadtree_estimates_put_the_host_at_the_front(self):
        rows = {r['id']: r for r in ledger.meter_newmap(self.ws(), project(mp(entries=[entry()])), 'p')}
        aux = rows['Q_aux']
        self.assertEqual(aux['mode'], 'estimate')
        top = aux['items'][0]
        self.assertTrue(top['label'].startswith('Host section'))
        self.assertGreater(top['used'], 9808)                                   # Downtown at 80 percent plus the loaders
        self.assertEqual(aux['max'], 12200)
        self.assertEqual(aux['status'], 'amber')
        self.assertEqual(rows['Q_main']['max'], 10000)

    def test_a_section_copy_starts_from_the_host_section(self):
        ext = dict(name='Yard', placement='extension', host=dict(block='submap01_map02_lostoros_downtown.submap'))
        rows = {r['id']: r for r in ledger.meter_newmap(self.ws(), project(ext), 'p')}
        self.assertTrue(any(i['label'] == 'Yard' and i['used'] > 9808 for i in rows['Q_aux']['items']))

    def test_live_characters_beyond_eight_wait(self):
        cops = [dict(pos=[i * 2.0, 0, 0]) for i in range(12)]
        rows = {r['id']: r for r in ledger.meter_newmap(self.ws(), project(mp(enemies=cops)), 'p')}
        r = rows['L5']
        self.assertEqual(r['used'], 12)
        self.assertEqual(r['status'], 'red')
        self.assertIn('wait', r['items'][0]['label'])
        far = [dict(pos=[i * 100.0, 0, 0]) for i in range(12)]
        self.assertEqual({r['id']: r for r in ledger.meter_newmap(self.ws(), project(mp(enemies=far)), 'p')}['L5']['used'], 1)

    def test_save_capacity_counts_nodes_that_change(self):
        rows = {r['id']: r for r in ledger.meter_newmap(self.ws(), project(mp(enemies=[dict(pos=[0, 0, 0])], pickups=[dict(kind='health', pos=[0, 0, 0])])), 'p')}
        self.assertEqual(rows['S_nodes']['used'], 7 + 1)
        self.assertEqual(rows['S_nodes']['max'], 3000)

    def test_map_count_past_the_measured_thirteen_is_amber_not_red(self):
        with tempfile.TemporaryDirectory() as t:
            ws = self.ws(t)
            ws.catalog = dict(maps=[0] * 9)
            many = project(*[mp('Map%02d_RunawayTrain' % (11 + i)) for i in range(5)])
            r = ledger.meter_maps(ws, many, 'p')
            self.assertEqual((r['used'], r['max'], r['status']), (14, 13, 'amber'))
            self.assertIn('not measured', r['reason'])
            self.assertNotEqual(ledger.meter_maps(ws, project(mp()), 'p')['status'], 'red')

    def test_sections_row_counts_the_numbers_in_use(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, mapalloc.NAME).write_text(json.dumps(dict(format=1, owners={'o': dict(maps=[dict(map_id=9, submap_id=21)], sections=[22])})))
            rows = {r['id']: r for r in ledger.meter_newmap(self.ws(t), project(mp()), 'p')}
            self.assertEqual(rows['L8_sections']['used'], 21 + 2 + 1)


class RemovalReport(unittest.TestCase):
    def slot(self, folder, name, ids):
        b = bytearray(0x50000)
        struct.pack_into('<6i', b, 0x3C, *ids)
        Path(folder, name).write_bytes(bytes(b))

    def test_saves_standing_on_a_map_are_found_by_their_folder_ids(self):
        with tempfile.TemporaryDirectory() as t:
            self.slot(t, 'Slot00', [-1, 0x100019, 0x10001A, 0x100100, -1, 0x100200])
            self.slot(t, 'Slot01', [-1, 0x100040, 0x100041, 0x100100, -1, 0x100200])
            Path(t, 'notes.txt').write_text('x')
            hit = mapnet.saves_on([0x100040], [('your saves', t)])
            self.assertEqual(hit, [dict(where='your saves', name='Slot01')])
            self.assertEqual(mapnet.saves_on([0x100777], [('your saves', t)]), [])

    def test_project_folder_names(self):
        self.assertEqual(mapnet.project_folder_names(project(mp(), dict(name='Y', placement='extension'))),
                         ['MAINMAP_Map11_RunawayTrain', 'SUBMAP01_Map11_RunawayTrain'])


class StartMissionFix(unittest.TestCase):
    def test_the_editor_takes_the_award_submap(self):
        import inspect
        sys.path.insert(0, str(ROOT / 'backend' / 'vendor' / 'tools' / 'save_editor'))
        src = Path(ROOT / 'backend/vendor/tools/save_editor/editlib.py').read_text(encoding='utf-8')
        self.assertIn('def start_mission(s, m, player_at_teleport=True, submap=None)', src)
        self.assertIn("sub_no = info['Mission_start_submap'] if submap is None else int(submap)", src)

    def test_make_passes_the_award_submap_and_marks_the_save_not_playable(self):
        calls = {}

        class Ed:
            class Save:
                def __init__(self, j):
                    pass
                def move_player(self, *a):
                    return None

            @staticmethod
            def start_mission(s, m, player_at_teleport=True, submap=None):
                calls.update(m=m, submap=submap)
                return dict(mission=m, moved=None, blocks={})

        class Sv:
            GAME_DIR = ''

            @staticmethod
            def decode(b):
                return dict(checks={}, parse_problems=[])

            @staticmethod
            def encode(j):
                return b'x' * 4

        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, TODMS_HOME=t, TODMS_SAVES=t):
            src = Path(t, 'src')
            src.write_bytes(b'x')
            with patch.object(saves, '_modules', return_value=(Sv, Ed)), patch.object(saves, 'award_submaps', return_value={20: 9}), \
                    patch.object(Sv, 'decode', side_effect=lambda b: dict(checks={'a': True}, parse_problems=[])):
                try:
                    r = saves.make(types.SimpleNamespace(game=types.SimpleNamespace(folder=t)), str(src), start_mission=20, dest=t)
                except Exception:
                    r = None
        self.assertEqual(calls, dict(m=20, submap=9))
        if r:
            self.assertIn('not_playable', [x[0] for x in r['log']])

    def test_the_test_game_never_asks_for_a_start_mission_save(self):
        from todms import testgame
        got = {}

        def fake_make(ws, source, **kw):
            got.update(kw)
            return dict(path='x', log=[], notes=[])
        with tempfile.TemporaryDirectory() as t:
            src = Path(t, 'Slot00')
            src.write_bytes(b'x')
            with patch.object(saves, 'make', fake_make), patch.object(saves, 'saves_dir', return_value=t),                     patch.object(saves, 'install', return_value=dict(slot='Slot00')):
                out = testgame.put_save(types.SimpleNamespace(game=None), dict(folder=t), dict(source=str(src), start_mission=20), False)
        self.assertIsNone(got['start_mission'])
        self.assertIn(saves.START_MISSION_NOTE, out['notes'])

    def test_award_submaps_real(self):
        if not (PROOF / 'blocks.naz').exists():
            self.skipTest('needs the read-only proof game')
        from todms.workspace import Workspace
        ws = Workspace()
        ws.set_game(str(PROOF))
        got = saves.award_submaps(ws)
        for m, sub in {5: 7, 8: 14, 10: 7, 18: 16, 20: 9, 23: 10, 0: 10, 21: 18}.items():
            self.assertEqual(got.get(m), sub, m)


class RecipeReal(unittest.TestCase):
    """The recipe against the real blocks (read only): numbers, entrance options, an extension section."""

    @classmethod
    def setUpClass(cls):
        if not (PROOF / 'blocks.naz').exists():
            raise unittest.SkipTest('needs the read-only proof game')
        from todms.workspace import Workspace
        cls.ws = Workspace()
        cls.ws.set_game(str(PROOF))

    def gen(self, params):
        r = newmap.load_recipe()
        old = (r.ft._arch, r.ft.GOG_NAZ)
        r.ft._arch, r.ft.GOG_NAZ = self.ws.game.base(), self.ws.game.naz
        try:
            with tempfile.TemporaryDirectory() as t:
                return r.gen_spec(params, t)
        finally:
            r.ft._arch, r.ft.GOG_NAZ = old

    def base(self, **kw):
        m = dict(name='Map11_RunawayTrain', source='map10_runawaytrain', arrival=dict(pos=[980.5, 4.7, 337.0], floor='vanilla'),
                 entries=[dict(id='e1', block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66], size=[12, 6, 2])],
                 **{'return': dict(pos=[980.5, 6, 330], target_map='MAINMAP_Map02_LosToros_Downtown', target_submap='SUBMAP01_Map02_LosToros_Downtown',
                                   teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill', teleport_block='overdose.main')})
        m.update(kw)
        return m

    def test_given_numbers_raise_the_limits_to_cover_them(self):
        spec, man = self.gen(project(self.base(map_id=10, submap_id=22)))
        self.assertEqual((man['maps'][0]['map_id'], man['maps'][0]['submap_id']), (10, 22))
        self.assertEqual(man['new_limits'], dict(MAPS_MAX=11, SUBMAPS_MAX=23))
        main = spec['blocks'][0]['ops']
        self.assertEqual([o['value'] for o in main[:2]], [11, 23])

    def test_entrance_options_become_nodes(self):
        e = dict(id='e1', block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66], size=[12, 6, 2], vehicle=True, prompt='use',
                 lock=dict(mission=79), arrive=dict(pos=[1000, 5, 1000], yaw=90),
                 back=dict(pos=[1000, 5, 990], size=[10, 8, 2], spot=dict(pos=[-230, 2.5, -40], yaw=180)))
        spec, man = self.gen(project(self.base(entries=[e])))
        blocks = {b['block']: b['ops'] for b in spec['blocks']}
        host = blocks['submap01_map02_lostoros_downtown.submap']
        names = [o['name'] for o in host]
        self.assertIn('TriggerLoad_MAINMAP_Map11_RunawayTrain_E1', names)
        self.assertIn('GATE_Map11_RunawayTrain_E1', names)
        self.assertIn('RET_Map11_RunawayTrain_E1', names)                        # the landing node in the host block
        loader = [o for o in host if o['name'] == 'TriggerLoad_MAINMAP_Map11_RunawayTrain_E1'][0]
        self.assertEqual(loader['set']['flags'], 1)                             # locked: the loader sits in a disabled Folder
        gate = [o for o in host if o['name'] == 'GATE_Map11_RunawayTrain_E1'][0]
        self.assertEqual({c['set']['TargetName'] for c in gate['child_sets'][1:]}, {'TriggerLoad_MAINMAP_Map11_RunawayTrain_E1', 'TriggerLoad_SUBMAP_Map11_RunawayTrain_E1'})
        self.assertGreaterEqual(loader['child_sets'][0]['set']['width'], 16)     # vehicle box
        self.assertEqual(loader['child_sets'][1]['set'], dict(TrueOn=2))
        self.assertEqual(loader['child_sets'][2]['set']['Teleport_to'], 'ARR_Map11_RunawayTrain_E1')
        newb = [o['name'] for b, ops in blocks.items() if 'map11' in b for o in ops]
        self.assertIn('ARR_Map11_RunawayTrain_E1', newb)
        self.assertIn('TriggerLoad_MAINMAP_Ret_E1', newb)
        man_e = man['maps'][0]['entries'][0]
        self.assertEqual(man_e['back']['spot_node'], 'RET_Map11_RunawayTrain_E1')
        self.assertEqual(man_e['back']['target_submap'], 'SUBMAP01_Map02_LosToros_Downtown')   # found from the game's registry
        self.assertEqual(man['maps'][0]['entries'][0]['lock'], dict(mission=79))

    def test_a_one_way_entrance_gets_no_way_back_of_its_own(self):
        e = dict(id='e1', block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66], one_way=True, back=dict(pos=[1000, 5, 990]))
        spec, man = self.gen(project(self.base(entries=[e])))
        self.assertIsNone(man['maps'][0]['entries'][0]['back'])
        self.assertEqual([x['id'] for x in man['maps'][0]['exits']], ['return'])

    def test_an_extension_section_follows_the_s1_route(self):
        ext = dict(name='Yard', placement='extension', host=dict(block='submap01_map02_lostoros_downtown.submap',
                   enter=dict(pos=[-237, 2.5, -43.66], size=[12, 6, 2]), leave=dict(pos=[-255, 2.5, -43.66], size=[12, 6, 2])),
                   carry=dict(mode='all'), walls=[dict(name='WALL', pos=[-231, 2.7, -43.66], size=[2, 3, 6])])
        spec, man = self.gen(project(ext))
        sec = man['sections'][0]
        self.assertEqual((sec['name'], sec['section_id'], sec['carry']), ('SUBMAP06_Map02_LosToros_Downtown', 21, 'all'))
        self.assertTrue(sec['load_screen'])
        self.assertEqual(man['new_limits']['SUBMAPS_MAX'], 22)
        self.assertEqual(man['new_limits']['MAPS_MAX'], 9)                       # a section is no map
        nb = spec['new_blocks'][0]
        self.assertEqual(nb['clone_of'], 'submap01_map02_lostoros_downtown.submap')
        self.assertEqual(nb['rename_root'], ['SUBMAP01_Map02_LosToros_Downtown.fragment', 'SUBMAP06_Map02_LosToros_Downtown.fragment'])
        main = spec['blocks'][0]['ops']
        folder = [o for o in main if o.get('name') == 'SUBMAP06_Map02_LosToros_Downtown'][0]
        self.assertEqual(folder['set']['Specific_ID'], 21)
        self.assertEqual(folder['parent']['entity'], '0x00100018')
        self.assertEqual(folder['entity'], '0x0010001A')
        into = [o for b in spec['blocks'] if b['block'] == 'submap01_map02_lostoros_downtown.submap' for o in b['ops']][0]
        self.assertEqual(into['child_sets'][0]['set']['TargetName'], 'SUBMAP06_Map02_LosToros_Downtown')
        self.assertNotIn('Teleport_to', into['child_sets'][0]['set'])             # a section swap keeps the map and the player's place

    def test_a_carry_mode_that_does_not_exist_or_a_region_without_corners_is_refused_plainly(self):
        host = dict(block='submap01_map02_lostoros_downtown.submap', enter=dict(pos=[0, 0, 0]), leave=dict(pos=[1, 0, 0]))
        with self.assertRaisesRegex(Exception, 'all, region or nothing'):
            self.gen(project(dict(name='Yard', placement='extension', host=host, carry=dict(mode='sideways'))))
        with self.assertRaisesRegex(Exception, 'rectangle'):
            self.gen(project(dict(name='Yard', placement='extension', host=host, carry=dict(mode='region'))))


if __name__ == '__main__':
    unittest.main()
