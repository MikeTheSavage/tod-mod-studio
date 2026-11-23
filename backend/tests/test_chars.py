"""Character bodies: the name table, what an edit needs, and the build that registers and copies a body a block lacks.

The pure tests need nothing. The build test uses a proof copy of the game in env TODMS_PROOF (skipped when unset).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
SH = 'data_pc/overdose_the_game/overdose/shared/'
DOWNTOWN = SH + 'submap01_map02_lostoros_downtown.submap'


class TestNames(unittest.TestCase):
    def test_every_body_has_a_name_and_group(self):
        from todms import names, characters
        self.assertEqual(sorted(names.CHARACTERS), list(range(32)))
        rows = characters.table()
        self.assertEqual([r['id'] for r in rows], list(range(32)))
        for r in rows:
            self.assertTrue(r['name'] and not r['name'].isdigit())

    def test_enemy_bodies_have_a_mesh_and_a_donor(self):
        from todms import characters
        en = characters.enemies()
        self.assertGreaterEqual(len(en), 15)
        for r in en:
            self.assertTrue(r['paths'])
            if not r['resident']:
                e, frag, node, path = characters.donor(r['id'])
                self.assertTrue(e.startswith('data_pc/') and node.startswith('0x'))
        self.assertNotIn(20, [r['id'] for r in en])

    def test_left_out_models_say_why(self):
        from todms import characters
        out = dict((n, why) for n, _, why in characters.left_out())
        self.assertIn(20, out)
        self.assertIn(7, out)

    def test_usual_side_of_an_enemy_is_hostile(self):
        from todms import characters
        self.assertEqual(characters.row(27)['side'], 9)
        self.assertEqual(characters.row(5)['ai'], 15)

    def test_pretty_and_file_names(self):
        from todms import names
        self.assertEqual(names.pretty('Medium_Health'), 'Medium health')
        self.assertEqual(names.pretty('4x4Pickup'), '4x4 pickup')
        self.assertEqual(names.file_name('/data/characters/gangster/gangster.model'), 'Gangster')
        self.assertEqual(names.all_names()['factions']['9'], 'Enemy')

    def test_needed_reads_adds_and_sets(self):
        from todms import characters
        ops = [dict(op='add', entry='a', set=dict(Model=24)), dict(op='set', entry='a', prop='Model', value=5),
               dict(op='set', entry='b', prop='AISubType', value=3), dict(op='add', entry='b', set={})]
        self.assertEqual(characters.needed(ops), {'a': {24, 5}})


@unittest.skipUnless(os.path.isdir(PROOF + r'\game'), 'proof copy absent')
class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        os.environ['TODMS_HOME'] = os.path.join(d, 'home')
        os.environ['TODMS_CACHE'] = os.environ.get('TODMS_CACHE') or os.path.join(d, 'cache')
        from todms import workspace, paths, server
        paths.ensure_cpu_guard()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(PROOF + r'\game')
        server.WS = cls.ws
        cls.tpl = server.h_templates({}, {'entries': [DOWNTOWN]})['enemy']
        cls.out = tempfile.mkdtemp()

    def enemy(self, uid, model, weapon):
        t = self.tpl
        return dict(op='add', uid=uid, entry=DOWNTOWN, template=dict(entry=t['entry'], frag=t['frag'], node=t['node']), deep=True,
                    group='enemy', name='T_' + uid, pos=[-226.0, 1.3, -43.7], rot=[0, 0, 0, 1],
                    set=dict(Model=model, AISubType=3, FactionID=9, WeaponSubType=weapon))

    def test_enemy_with_a_new_body_is_registered_and_its_mesh_copied(self):
        from todms import build, characters
        import todblock as tb
        rep = build.build(self.ws, [self.enemy('e1', 24, 4)], {}, self.out, 'x.zip')
        b = rep['blocks'][0]
        self.assertEqual([m['model'] for m in b['character_models']], [24])
        self.assertTrue(any('mexican_police' in a for a in b['character_assets']))
        self.assertTrue(b['roundtrip']['identical'])
        raw = dict(rep['_outs'])[DOWNTOWN]
        self.assertFalse(characters.missing(self.ws, DOWNTOWN, raw, [24]))
        self.assertTrue(characters.missing(self.ws, DOWNTOWN, self.ws.read_block(DOWNTOWN)[0], [24]))
        self.assertEqual(len(b['stage_b']['grafted']), 2)            # the body node and the fighter

    def test_a_body_the_block_has_needs_nothing_extra(self):
        from todms import build
        rep = build.build(self.ws, [self.enemy('e2', 23, 0)], {}, self.out, 'y.zip')
        self.assertNotIn('character_models', rep['blocks'][0])


    # ---- mission templates and the new-map recipe
    JAVPER = SH + 'subm_20_down_javper_kill.mission'

    def test_retag_block_gives_every_enemy_the_chosen_body(self):
        from todms import characters, level as lv
        raw, _ = self.ws.read_block(self.JAVPER)
        rep = {}
        new = characters.retag_block(self.ws, self.JAVPER, raw, 24, rep)
        self.assertGreater(rep['retagged'], 20)
        self.assertTrue(any('mexican_police' in a for a in rep['character_assets']))
        L = lv.BlockLevel(self.JAVPER, new, self.ws.T, self.ws.main_lookup)
        ents, _ = L.entities('t')
        sides = {(e['sub']['Model'], e['sub']['FactionID']) for e in ents if e['cat'] == 'character'}
        self.assertEqual(sides, {(24, 9), (23, 8)})                  # the enemies changed, Ram's own placeholder did not
        self.assertFalse(characters.missing(self.ws, self.JAVPER, new, [24]))

    def test_retag_refuses_a_body_that_cannot_be_placed(self):
        from todms import characters
        raw, _ = self.ws.read_block(self.JAVPER)
        with self.assertRaises(ValueError):
            characters.retag_block(self.ws, self.JAVPER, raw, 20)

    def test_recipe_registers_the_bodies_its_enemies_need(self):
        from todms.newmap_recipe import make_new_map as MM
        raw, _ = self.ws.read_block(self.JAVPER)
        entries = {self.JAVPER: raw}
        real = [dict(nodes_in='map', enemies=[dict(pos=[0, 0, 0], model=31), dict(pos=[1, 0, 0])])]
        mans = [dict(map_block=self.JAVPER, submap_block=self.JAVPER)]
        checks = []
        MM.ensure_bodies({}, real, mans, entries, checks)
        self.assertTrue(checks and checks[0]['result'] == 'PASS')
        from todms import characters
        self.assertFalse(characters.missing(self.ws, self.JAVPER, entries[self.JAVPER], [31, 23]))
        self.assertGreater(len(entries[self.JAVPER]), len(raw))


class TestMissionProject(unittest.TestCase):
    def test_enemy_body_is_read_beside_the_params(self):
        from todms import missions_tpl as MT
        snaps = {'p': dict(project=dict(missions=[dict(id='a', enemy_body=24), dict(id='b'), dict(id='c', enemy_body='template')]))}
        idmap = {'a': ('p', 'a'), 'b': ('p', 'b'), 'c': ('p', 'c')}
        self.assertEqual(MT.enemy_bodies(snaps, idmap), {'a': 24})

    def test_a_body_that_cannot_be_placed_is_refused_when_saving(self):
        from todms import missions_tpl as MT
        base = dict(name='x', hosts=[], missions=[dict(id='a', enemy_body=20)])
        with self.assertRaises(ValueError):
            MT.check_project(base)
        base['missions'][0]['enemy_body'] = 24
        MT.check_project(base)
        base['missions'][0]['enemy_body'] = 'template'
        MT.check_project(base)


if __name__ == '__main__':
    unittest.main()
