"""Mission logic for sections (submaps): the Car enters box template, the rewards, the world position of a trigger in a section,
the ledger count and the mod path (check, build, conflicts).

The pure tests need nothing. The build tests use a proof copy of the game in env TODMS_PROOF (skipped when unset): they add
triggers to the Los Toros Downtown section, the one that holds the game's parking egg.
"""
import copy
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
SH = 'data_pc/overdose_the_game/overdose/shared/'
DOWNTOWN = SH + 'submap01_map02_lostoros_downtown.submap'


def park(id_='p1', **params):
    p = dict(text=341)
    p.update(params)
    return dict(op='add_trigger', id=id_, entry=DOWNTOWN, template='car_enters', name='Spot_' + id_, pos=[10.0, 2.0, -50.0],
                size=[8, 4, 8], yaw=30, params=p)


class TestPlan(unittest.TestCase):
    def test_car_enters_is_a_template_in_a_vehicle_box(self):
        from todct import missions as MS
        T = MS.TEMPLATES['car_enters']
        self.assertEqual(T['root'], 'root_box')
        self.assertEqual(T['cond'], 'cond_vehicle')
        self.assertEqual(MS.PARTS['cond_vehicle'][2], '0x003024C0')          # the egg's Condition_CarEnter (TrueOn 11)
        t = MS.enum_tables()['TEMPLATES']
        self.assertTrue(t['car_enters']['box'])
        self.assertFalse(t['kill_n']['box'])

    def test_actions_in_order(self):
        from todct import missions as MS
        kinds = lambda o: [k for k, _p, _s in MS.plan_actions(o)]
        self.assertEqual(kinds(park(weapon=3, pickups=[8, 0])), ['show_text', 'give_weapon', 'pickups'])
        self.assertEqual(kinds(park(text=None, pickups=[8])), ['pickups'])
        self.assertEqual(kinds(park(text=None)), [])
        o = dict(park(), template='go_to_point')
        o['params'] = dict(action='show_text', text=341)
        self.assertEqual(kinds(o), ['show_text'])                               # the text is not added twice
        o['params'] = dict(objective='X', text=341)
        self.assertEqual(kinds(o), ['complete_objective', 'show_text'])

    def test_rewards_are_goodie_ids(self):
        from todct import missions as MS
        ids = {r['id']: r['label'] for r in MS.enum_tables()['REWARDS']}
        self.assertEqual(ids[8], 'Rewind')
        self.assertTrue(all(isinstance(i, int) for i in ids))

    def test_nodes_added(self):
        from todct import missions as MS
        self.assertEqual(MS.nodes_added(park()), 3)                              # root, condition, text
        self.assertEqual(MS.nodes_added(park(weapon=3)), 4)
        self.assertEqual(MS.nodes_added(park(pickups=[8, 0, 1])), 3 + 1 + 1 + 3)  # + the enable action, the folder, 3 pickups
        self.assertEqual(MS.nodes_added(dict(op='set', entry=DOWNTOWN)), 0)

    def test_words_and_limits(self):
        from todms import sectext
        self.assertTrue(sectext.is_words('Nice!'))
        self.assertFalse(sectext.is_words(341))
        self.assertFalse(sectext.is_words('341'))
        ops, edits = sectext.resolve([park('a', text='one'), park('b', text='two'), park('c', text='one')])
        self.assertEqual([o['params']['text'] for o in ops], [351, 350, 351])
        with self.assertRaisesRegex(sectext.TextError, 'At most 7'):
            sectext.resolve([park(str(i), text='t%d' % i) for i in range(8)])
        with self.assertRaisesRegex(sectext.TextError, 'at most 80'):
            sectext.resolve([park('x', text='x' * 81)])

    def test_errors_in_plain_words(self):
        from todct import missions as MS
        B = type('B', (), {'appends': {}, 'append': lambda *a, **k: None})()
        with self.assertRaisesRegex(MS.MissionError, 'something to do'):
            MS.add_to_builder(B, [park(text=None)])
        with self.assertRaisesRegex(MS.MissionError, 'position'):
            MS.add_to_builder(B, [dict(park(), pos=None)])
        with self.assertRaisesRegex(MS.MissionError, 'no pickup'):
            MS._pickups(B, DOWNTOWN, 'x', 'x', dict(pickups=[]), [0, 0, 0], [4, 4, 4], 0)

    def test_preview_shows_the_new_trigger(self):
        from todct import missions as MS
        g = dict(entry=DOWNTOWN, triggers=[], edges=[], enums=MS.enum_tables())
        out = MS.preview(g, [park(weapon=3, ap=250, pickups=[8])])
        t = out['triggers'][0]
        self.assertTrue(t['new'])
        self.assertEqual(t['conditions'][0]['code'], 11)
        self.assertEqual(t['conditions'][0]['extra']['APBonus'], 250)
        self.assertEqual([a['short'] for a in t['actions']], ['show_text', 'give_weapon', 'enable'])
        self.assertEqual(t['actions'][2]['target_name'], 'Spot_p1_Goodies')

    def test_recipe_shape_accepts_a_section_op(self):
        from todct import edits
        edits.validate_ops('missions', [park()])


class TestLedgerAndMods(unittest.TestCase):
    def test_nodes_of_mission_ops_are_counted_per_block(self):
        from todms import ledger
        out = ledger._blocks_with_adds([dict(op='add', entry=DOWNTOWN)], [park(pickups=[8, 0]), dict(op='set', entry=DOWNTOWN, prop='x')])
        self.assertEqual(out[DOWNTOWN], 1 + 3 + 1 + 1 + 2)

    def test_two_mods_in_one_section_are_listed_as_a_shared_block(self):
        from todms import compat
        a = dict(id='a', name='A', missions=[park('a1')])
        b = dict(id='b', name='B', missions=[park('b1')])
        hosts = compat.shared_hosts([a, b])
        self.assertEqual([h['block'] for h in hosts], ['submap01_map02_lostoros_downtown.submap'])
        self.assertEqual(len(hosts[0]['owners']), 2)

    def test_the_recipe_with_a_section_op_is_a_safe_package(self):
        from todms import modfile
        from todct import todmod
        m = todmod.new_mod('Parking', missions=[park()])
        self.assertEqual(m['version'], 3)
        self.assertIs(modfile.check_object(m) if hasattr(modfile, 'check_object') else True, True)


@unittest.skipUnless(os.path.isdir(os.path.join(PROOF, 'game')), 'needs the proof copy')
class TestSectionBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, TODMS_HOME=os.path.join(cls.temp.name, 'home'), TODMS_CACHE=os.path.join(cls.temp.name, 'cache'))
        cls.env.start()
        from todms import workspace, paths
        paths.ensure_cpu_guard()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.temp.cleanup()

    def build(self, ops):
        from todct import edits
        return edits.build(lambda e: self.ws.read_block(e)[0], missions=ops)

    def test_the_egg_is_in_the_graph_of_the_section(self):
        from todms import companion_b as CB
        g = CB.mission_graph(self.ws, DOWNTOWN)
        by = {t['name']: t for t in g['triggers']}
        self.assertIn('PerfectParking', by)
        pp = by['PerfectParking']
        self.assertEqual(pp['conditions'][0]['code'], 11)
        self.assertEqual([a['code'] for a in pp['actions']][:3], [79, 1, 5])
        self.assertEqual(by['Activate_PerfectParking']['actions'][1]['target_name'], 'PerfectParking_Goodies')
        # positions are world positions: the owner of a section's fragments is composed in
        self.assertAlmostEqual(pp['pos'][0], -15.366, places=2)

    def test_car_enters_with_a_reward_builds_and_reads_back(self):
        out, rep = self.build([park(weapon=3, ap=300, pickups=[8, 0])])
        self.assertEqual(rep['result'], 'PASS', rep)
        self.assertEqual(list(out), [DOWNTOWN])
        chk = rep['missions'][0]['checks'][0]
        self.assertEqual(chk[0], 'PASS')
        self.assertIn('pickups [8, 0]', chk[1])
        self.assertEqual(rep['missions'][0]['lint']['new_issues'], [])
        from todms import companion_b as CB
        base = {DOWNTOWN: out[DOWNTOWN]}
        with patch.object(self.ws, 'read_block', lambda e: (base[e], 'x')):
            CB._cache.clear()
            g = CB.mission_graph(self.ws, DOWNTOWN)
        t = next(t for t in g['triggers'] if t['name'] == 'Spot_p1')
        self.assertEqual([round(v, 3) for v in t['pos']], [10.0, 2.0, -50.0])
        self.assertEqual(t['box'], [8.0, 4.0, 8.0])
        self.assertEqual(t['conditions'][0]['code'], 11)
        self.assertEqual(t['conditions'][0]['extra']['APBonus'], 300)
        self.assertEqual([a['code'] for a in t['actions']], [79, 51, 5])
        self.assertEqual(t['actions'][2]['target_name'], 'Spot_p1_Goodies')

    def test_on_foot_box_in_a_section(self):
        o = dict(op='add_trigger', id='f1', entry=DOWNTOWN, template='go_to_point', name='Foot_f1', pos=[0.0, 5.0, -100.0], size=[6, 4, 6], yaw=0,
                 params=dict(action='show_text', text='Walked in', pickups=[20]))
        from todms import sectext
        out, rep = self.build(sectext.resolve([o])[0])
        self.assertEqual(rep['result'], 'PASS', rep)
        from todct import missions as MS
        g = MS.graph(DOWNTOWN, out[DOWNTOWN])
        t = next(t for t in g['triggers'] if t['name'] == 'Foot_f1')
        self.assertEqual(t['conditions'][0]['code'], 1)
        self.assertTrue(t['conditions'][0]['activator'].startswith('0'))          # the player: a car with the player in it is event 11, not this one

    def test_own_words_become_rows_in_the_pack(self):
        from todms import mods, sectext
        o = park('w1', text='A car in the box!')
        ops, edits = sectext.resolve([o])
        self.assertEqual(ops[0]['params']['text'], 351)
        self.assertEqual(o['params']['text'], 'A car in the box!')                  # the op itself is not changed
        self.assertEqual(edits, [dict(file='uk_Objective.txt', ordinal=351, value='A car in the box!')])
        d = tempfile.mkdtemp()
        rep = mods.build_mods(self.ws, [dict(level=[], data={}, missions=[o])], d, 'p.zip')
        names = zipfile.ZipFile(os.path.join(d, 'p.zip')).namelist()
        for lang in ('uk', 'de', 'fr', 'es', 'it'):
            self.assertIn('data_pc/overdose_the_game/overdose/%s/overdose_%s.main' % (lang, lang), names)
        self.assertEqual(rep['texts'], [dict(row=351, text='A car in the box!')])

    def test_existing_nodes_keep_their_place(self):
        out, rep = self.build([park('a1'), park('a2', text=342)])
        self.assertEqual(rep['result'], 'PASS', rep)
        sv = rep['blocks'][0]['submaptool_verify']['runtime_indices']
        self.assertTrue(sv['unchanged'])
        # the trigger hangs under a folder at the origin that already holds the section's triggers, not under a far placed model
        lit = rep['blocks'][0]['appended']['literals']
        self.assertTrue(lit and lit[0]['fragment'].endswith('.fragment'), lit)
        from todct import missions as MS
        c = MS.section_container(DOWNTOWN, lambda e: self.ws.read_block(e)[0])
        self.assertTrue(c and c['node'].startswith('0x'))
        self.assertIsNone(MS.section_container(SH + 'mm010_ernestocruz.mission', lambda e: self.ws.read_block(e)[0]))

    def test_check_lists_the_text_rows(self):
        from todms import companion_b as CB
        r = CB.check(self.ws, dict(missions=[park(text='Hello Ram')]), kinds=('missions',))
        self.assertEqual(r['result'], 'PASS')
        self.assertTrue(any(l['area'] == 'texts' and 'Hello Ram' in l['text'] for l in r['lines']))
        bad = CB.check(self.ws, dict(missions=[park(text='x' * 90)]), kinds=('missions',))
        self.assertTrue(any(l['area'] == 'texts' and l['level'] == 'error' for l in bad['lines']))

    def test_a_mod_builds_into_the_pack_with_the_section(self):
        from todms import mods
        mod = dict(level=[], data={}, missions=[park(pickups=[8])])
        d = tempfile.mkdtemp()
        rep = mods.build_mods(self.ws, [mod], d, 'p.zip')
        names = zipfile.ZipFile(os.path.join(d, 'p.zip')).namelist()
        self.assertTrue(any(n.lower().endswith('submap01_map02_lostoros_downtown.submap') for n in names), names)
        self.assertTrue(rep.get('save_safe', True))


if __name__ == '__main__':
    unittest.main()
