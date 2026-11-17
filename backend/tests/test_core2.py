"""Wave 3 core2: the builder's block-level writers (look and sky, triggers, traffic routes, the game's own pictures and models), extension
carry region / nothing with the edge-of-view check, and the minimap pack. Pure tests run anywhere; the ones marked real read the proof game
folder (read only) and skip without it."""
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from todms import minimap, newmap, mapgen                                       # noqa: E402
from todms.mapgen import core                                                   # noqa: E402

PROOF = Path(os.environ.get('TODMS_PROOF', '/no-proof-copy')) / 'game'
HOST = 'submap01_map02_lostoros_downtown.submap'
ROCK = '/data/textures/materials/final_ingame_textures/ter_cliff_face.bmp'
MAP06 = 'data_pc/overdose_the_game/overdose/shared/mainmap_map06_virgillos_farm.map'
DOWNTOWN = 'data_pc/overdose_the_game/overdose/shared/submap01_map02_lostoros_downtown.submap'
ASSETS = dict(textures={ROCK: dict(w=128, h=128, fmt='DXT1', blocks=[DOWNTOWN])},
              models={'/data/models/addons/surround/sur_rock_01.model': dict(blocks=[MAP06], textures=[])})


class Pure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = newmap.load_recipe()
        cls.EX = cls.r.EX

    def test_a_region_is_a_rectangle_or_corners(self):
        self.assertEqual(self.EX.polygon_from_region([5, 4, 1, 2]), [[1.0, 2.0], [5.0, 2.0], [5.0, 4.0], [1.0, 4.0]])
        self.assertEqual(len(self.EX.polygon_from_region([[0, 0], [4, 0], [2, 3]])), 3)
        with self.assertRaises(ValueError):
            self.EX.polygon_from_region([1, 2, 3])
        poly = self.EX.polygon_from_region([0, 0, 10, 10])
        self.assertTrue(self.EX.inside(poly, 5, 5))
        self.assertFalse(self.EX.inside(poly, 11, 5))

    def test_a_region_cut_removes_only_drawn_nodes_and_keeps_big_models_that_reach_in(self):
        # game test (wave 3 proofs): cutting logic nodes together with drawn ones made the game exit while the section loaded
        EX = self.EX
        for t in ('Model', 'SignPost', 'generic_object_effect(Sprite)', 'generic_particle_emitter(Node)'):
            self.assertTrue(EX.is_visual(t), t)
        for t in ('Node', 'Folder', 'Trigger_Condition(NodeLogical)', 'database_traffic_point(NodeSpatial)', 'CollisionBox',
                  'destructable_object_placeholder(HavocPlaceHolder)', 'GEKeyFrame', 'default_global_light', 'SkyBox',
                  'Light'):                                      # lights are not cut by position: with them gone every surface drew black (game test r8-r11)
            self.assertFalse(EX.is_visual(t), t)
        poly = EX.polygon_from_region([0, 0, 10, 10])
        self.assertTrue(EX.reaches(poly, 5, 5, 0))
        self.assertFalse(EX.reaches(poly, 30, 5, 0))
        self.assertFalse(EX.reaches(poly, 30, 5, 19.9))
        self.assertTrue(EX.reaches(poly, 30, 5, 20.1))        # a ground piece 50 m wide placed by its centre 30 m away still covers the region
        self.assertTrue(EX.reaches(poly, 12, 12, 3.0))

    def test_sight_lines_find_unloaded_space_past_the_edge(self):
        poly = self.EX.polygon_from_region([0, 0, 30, 30])
        hits = self.EX.sightlines([(15.0, 1.0, 15.0)], poly, lambda x, z: False, step=6.0)
        self.assertEqual(len(hits), 8)
        self.assertLessEqual(hits[0]['distance'], hits[-1]['distance'])
        self.assertEqual(self.EX.sightlines([(15.0, 1.0, 15.0)], poly, lambda x, z: True), [])        # something is drawn out there

    def test_a_teleport_trigger_is_a_quiet_loader_pair_into_the_maps_own_folders(self):
        m = dict(name='Map11_X', triggers=[dict(id='kill_rim', kind='teleport', teleport_to='SPOT_A', pos=[0, -40, 0], size=[500, 20, 500])])
        ops, rows = self.r.trigger_ops(m, dict(fragment='F', entity='E'), 'MAINMAP_Map11_X', 'SUBMAP01_Map11_X', {'SPOT_A'})
        self.assertEqual([o['name'] for o in ops], ['TRIGGER_MAIN_KILL_RIM', 'TRIGGER_SUB_KILL_RIM'])
        self.assertEqual(ops[0]['child_sets'][0]['set'], dict(TargetName='MAINMAP_Map11_X', name='Action_TRIGGER_MAIN_KILL_RIM', Teleport_to='SPOT_A'))
        self.assertEqual(ops[1]['child_sets'][0]['set']['TargetName'], 'SUBMAP01_Map11_X')
        self.assertLess(ops[0]['child_sets'][1]['set']['sprite_size'][0], 0.1)                  # no beam to see
        self.assertEqual(rows[0]['teleport_to'], 'SPOT_A')
        m['triggers'][0]['teleport_to'] = 'NOWHERE'
        with self.assertRaisesRegex(Exception, 'not a spot'):
            self.r.trigger_ops(m, dict(fragment='F', entity='E'), 'A', 'B', {'SPOT_A'})

    def test_an_end_mission_trigger_is_a_box_that_fails_the_mission(self):
        m = dict(name='Map11_X', triggers=[dict(id='water_a', kind='end_mission', result=0, pos=[1, 2, 3], size=[4, 5, 6])])
        ops, rows = self.r.trigger_ops(m, dict(fragment='F', entity='E'), 'A', 'B', set())
        self.assertEqual(ops[0]['child_sets'][0], dict(type='Trigger_Activate_Mission(NodeLogical)', set=dict(End_Mission_Result=0)))
        self.assertEqual((ops[0]['set']['width'], ops[0]['set']['height'], ops[0]['set']['length']), (4, 5, 6))
        with self.assertRaisesRegex(Exception, 'unknown kind'):
            self.r.trigger_ops(dict(name='M', triggers=[dict(id='x', kind='explode')]), dict(), 'A', 'B', set())

    def test_traffic_routes_become_two_point_road_folders_linked_by_name(self):
        pts = [dict(name='P%d' % i, pos=[float(i) * 10, 0.1, 0.0], next='P%d' % (i + 1) if i < 4 else None) for i in range(5)]
        m = dict(name='M', traffic_routes=[dict(road='main', direction='F', boundradius=4.0, points=pts)])
        ops, rows = self.r.traffic_ops(m, dict(fragment='F', entity='E'))
        self.assertEqual(rows[0]['points'], 6)                                      # an odd route gets one more end point
        self.assertEqual(len(ops), 3)
        subs = [(c['set']['name'], c['set']['Sub_Type'], c['set']['NameOfNextPoint']) for o in ops for c in o['child_sets']]
        self.assertEqual(subs[0], ('P0', 4, 'P1'))                                  # the first point spawns
        self.assertEqual(subs[4], ('P4', 0, 'P4_END'))
        self.assertEqual(subs[-1][1:], (3, ''))                                     # the last point ends the route
        self.assertEqual(ops[1]['pos'], [20.0, 0.1, 0.0])
        self.assertEqual(ops[0]['child_sets'][1]['set']['pos'], [10.0, 0.0, 0.0])    # local to the folder
        self.assertEqual(len({o['name'] for o in ops}), 3)

    def test_shipped_models_become_models_and_placements_of_the_geometry(self):
        m = dict(new_geometry=dict(folder='X', textures=[], models=[dict(name='A', parts=[])], placements=[]),
                 shipped_models=[dict(model='/Models/A/b.model', pos=[1, 2, 3], blocks=['x.map']), dict(model='/Models/A/b.model', pos=[4, 5, 6]),
                                 dict(model='/Models/C/d.model', pos=[7, 8, 9])])
        ng = self.r.shipped_into_geometry(m)
        self.assertEqual([x['name'] for x in ng['models']], ['A', 'SH1', 'SH2'])
        self.assertEqual(ng['models'][1]['shipped'], '/Models/A/b.model')
        self.assertEqual(ng['models'][1]['shipped_blocks'], ['x.map'])
        self.assertEqual([p['model'] for p in ng['placements']], ['SH1', 'SH1', 'SH2'])
        self.assertEqual(len(m['new_geometry']['models']), 1)                       # the recipe is not changed


class Expansion(unittest.TestCase):
    def test_the_asset_index_names_the_donor_blocks(self):
        p = dict(package='T', maps=[dict(name='Map11_Test', source='map10_runawaytrain',
                                         terrain=dict(size=[40, 40], cell=2.0, strokes=[]), ground_paint=dict(palette=['rock']),
                                         scatter=[dict(id='s', rect=[-18, -18, 18, 18], density=0.01, items=[dict(model='/Models/Addons/Surround/sur_rock_01.model')])])])
        m = mapgen.expand(p, assets=ASSETS)['maps'][0]
        tx = [t for t in m['new_geometry']['textures'] if t.get('shipped')]
        self.assertEqual(tx[0]['shipped'], ROCK)
        self.assertEqual(tx[0]['shipped_blocks'], [DOWNTOWN])
        self.assertTrue(m['shipped_models'])
        self.assertEqual(m['shipped_models'][0]['blocks'], [MAP06])

    def test_newmap_expand_passes_the_index_only_to_a_generator_that_takes_it(self):
        import types
        from unittest.mock import patch
        seen = []
        stub = types.ModuleType('todms.mapgen')

        def expand(params, assets=None):
            seen.append(assets)
            return params
        stub.expand = expand
        with patch.dict(sys.modules, {'todms.mapgen': stub}):
            newmap.expand(dict(maps=[dict(name='M')]), assets=ASSETS)
        self.assertEqual(seen, [ASSETS])


class Minimap(unittest.TestCase):
    SAMPLE = dict(name='Map11_Tiny', terrain=dict(size=[20, 20], cell=2.0, strokes=[]),
                  ground_paint=dict(palette=['grass', 'dirt'], default='grass', strokes=[dict(material='dirt', pos=[0, 0], radius=5)]),
                  roads=[dict(id='r', points=[[-18, 0], [0, 4], [18, 0]], width=6, lanes=2)],
                  water=[dict(id='pond', circle=[-10, -12, 5], depth=1.0, rule='reset')],
                  walls=[dict(name='W', pos=[8.0, 1.0, -8.0], size=[6, 2, 1], orient=[0, 0, 0, 1])])

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='mm_')
        cls.info = minimap.build(cls.SAMPLE, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_the_pack_has_the_baker_header_and_a_listed_line(self):
        pack = open(os.path.join(self.dir, self.info['file']), 'rb').read()
        magic = pack[:4]
        ver, x0, z1, texel, tile, border, levels = struct.unpack_from('<IfffIII', pack, 4)
        self.assertEqual((magic, ver, texel, tile, border, levels), (b'MMP1', 1, 0.25, 512, 4, 2))
        self.assertEqual((x0, z1), (self.info['bounds'][0], self.info['bounds'][3]))
        row = minimap.parse_line(self.info['line'])
        self.assertEqual(row['name'], 'map11_tiny')
        self.assertEqual(row['file'], 'map11_tiny.mmp')
        self.assertEqual(row['width'], self.info['width'])
        occ = open(os.path.join(self.dir, self.info['occ'])).read().split('\n')
        self.assertTrue(occ[0].startswith('occ 16.0 '))
        self.assertIn('1', occ[1] + occ[2])

    def test_every_tile_is_a_palette_png_the_dll_can_read(self):
        pack = open(os.path.join(self.dir, self.info['file']), 'rb').read()
        cols, rows, tab = struct.unpack_from('<III', pack, 32)
        seen = 0
        for i in range(cols * rows):
            off, sz = struct.unpack_from('<II', pack, tab + i * 8)
            if not sz:
                continue
            png = pack[off:off + sz]
            self.assertEqual(png.count(b'IDAT'), 1)                                  # the DLL refuses a split picture
            t = minimap.decode_tile(png)
            self.assertEqual(t.shape, (512, 512, 4))
            seen += 1
        self.assertGreater(seen, 0)

    def test_calibration_finds_the_road_and_the_water_where_the_dll_looks(self):
        checks = minimap.calibrate(self.dir, self.info)
        self.assertTrue(checks)
        self.assertEqual([c for c in checks if c['result'] != 'PASS'], [])
        self.assertTrue(any('road r' in c['check'] for c in checks) and any('water pond' in c['check'] for c in checks))

    def test_a_wrong_corner_is_caught(self):
        bad = dict(self.info, bounds=[self.info['bounds'][0] + 40.0] + self.info['bounds'][1:])
        self.assertTrue([c for c in minimap.calibrate(self.dir, bad) if c['result'] == 'FAIL'])

    def test_pixel_of_is_the_dlls_own_formula(self):
        b = self.info['bounds']
        self.assertEqual(minimap.pixel_of(self.info, b[0], b[3]), (0.0, 0.0))
        px, pz = minimap.pixel_of(self.info, b[0] + 10.0, b[3] - 5.0)
        self.assertEqual((px, pz), (40.0, 20.0))

    def test_overlap_with_another_pack_is_named_and_the_index_merges(self):
        self.assertEqual(minimap.overlaps([0, 0, 10, 10], {'a': [5, 5, 20, 20], 'b': [30, 30, 40, 40]}), ['a'])
        self.assertEqual(minimap.overlaps([20000, 20000, 20100, 20100], minimap.SHIPPED_BOUNDS), [])
        self.assertIn('map02_lostoros_downtown', minimap.overlaps(self.info['bounds'], minimap.SHIPPED_BOUNDS))      # the origin is Downtown's ground
        text = minimap.merge_lines([self.info['line']], '# head\nmap01_x 0 0 1 1 2 2 a.mmp\n')
        self.assertIn('map01_x 0 0 1 1 2 2 a.mmp', text)
        self.assertIn('map11_tiny', text)
        again = minimap.merge_lines([self.info['line']], text)
        self.assertEqual(again.count('map11_tiny'), 2)                               # name in the line and in the file name, once each
        self.assertEqual(len([l for l in again.splitlines() if l.startswith('map11_tiny ')]), 1)

    def test_a_map_with_nothing_to_draw_or_too_large_is_refused_plainly(self):
        with self.assertRaisesRegex(minimap.MinimapError, 'nothing to draw'):
            minimap.build(dict(name='Map11_Empty'), self.dir)
        with self.assertRaisesRegex(minimap.MinimapError, 'larger'):
            minimap.build(dict(name='Map11_Big', terrain=dict(size=[600, 600], cell=4.0, strokes=[])), self.dir)

    def test_the_same_map_gives_the_same_pack(self):
        d2 = tempfile.mkdtemp(prefix='mm2_')
        try:
            i2 = minimap.build(self.SAMPLE, d2)
            self.assertEqual(open(os.path.join(d2, i2['file']), 'rb').read(), open(os.path.join(self.dir, self.info['file']), 'rb').read())
        finally:
            shutil.rmtree(d2, ignore_errors=True)


class Real(unittest.TestCase):
    """The builder against the real blocks (read only)."""

    @classmethod
    def setUpClass(cls):
        if not (PROOF / 'blocks.naz').exists():
            raise unittest.SkipTest('needs the read-only proof game')
        from todms.workspace import Workspace
        cls.ws = Workspace()
        cls.ws.set_game(str(PROOF))
        cls.dir = tempfile.mkdtemp(prefix='core2_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, 'dir', ''), ignore_errors=True)

    def build(self, params, label):
        out = os.path.join(self.dir, label)
        os.makedirs(out)
        p = os.path.join(out, 'params.json')
        newmap.write(p, params)
        rep = newmap.run_argv([p, '--out', out], self.ws)
        return rep, out

    def test_look_sky_triggers_traffic_and_the_games_own_pictures_and_models_are_built(self):
        m = dict(name='Map11_Core2TinyMap', source='map10_runawaytrain', arrival=dict(pos=[0.0, 3.0, 0.0], floor='none'),
                 entries=[dict(id='e1', block=HOST, pos=[-237, 2.5, -43.66], size=[12, 6, 2])],
                 terrain=dict(size=[24, 24], cell=2.0, strokes=[]), ground_paint=dict(palette=['rock'], default='rock'),
                 roads=[dict(id='r', points=[[-10, 0], [0, 2], [10, 0]], width=6, lanes=2)],
                 water=[dict(id='pond', circle=[-7, -7, 3], depth=1.0, rule='reset', reset=[0, 0])],
                 edges=[dict(id='rim', kind='invisible', rect=[-12, -12, 12, 12], height=4.0, kill=dict(below=-20, respawn=[0, 0]))],
                 scatter=[dict(id='s', rect=[-11, -11, 11, 11], density=0.02, seed=3, items=[dict(model='/Models/Addons/Surround/sur_rock_01.model')])],
                 look=dict(preset='bright_blue', sky='Skybox_DAWN'),
                 **{'return': dict(pos=[3.0, 4.5, 9.0], size=[4, 4, 2], target_map='MAINMAP_Map02_LosToros_Downtown', target_submap='SUBMAP01_Map02_LosToros_Downtown',
                                   teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill', teleport_block='overdose.main')})
        proj = mapgen.expand(dict(package='T', maps=[m]), assets=ASSETS)
        rep, out = self.build(proj, 'geo')
        bad = [c for c in rep['checks'] if c['result'] == 'FAIL']
        self.assertEqual(rep['result'], 'PASS', bad[:3])
        names = [c['check'] for c in rep['checks'] if c['result'] == 'PASS']
        self.assertTrue(any('read back' in n and 'look' in n for n in names), names)
        self.assertTrue(any('sends the player to' in n for n in names), names)
        self.assertTrue(any('traffic routes linked' in n for n in names), names)
        mm = rep['manifest']['maps'][0]
        self.assertIn('sky set', mm['look_report']['applied'])
        self.assertTrue(any(x.endswith('skybox.model') for x in mm['look_report']['sky_records_added']))
        tex = [t['name'] for t in rep['geometry'][0]['textures']]
        self.assertTrue(any(t.lower().endswith('ter_cliff_face.bmp') for t in tex))      # the game's own picture, not a made one
        self.assertTrue(any(m_.get('shipped') for m_ in rep['geometry'][0]['models']))
        # the sky model is a record of the map block and the clone source's own sky is gone
        sys.path.insert(0, str(ROOT / 'backend' / 'vendor' / 'newmap'))
        r = newmap.load_recipe()
        raw = open(os.path.join(out, 'mainmap_map11_core2tinymap.map'), 'rb').read()
        blk = r.tb.Block(raw, '.map')
        info = bytes(blk.info).lower()
        self.assertIn(b'skybox_dawn/skybox_dawn/skybox.model', info)
        self.assertNotIn(b'reddustsky', info)

    def test_an_extension_that_carries_a_region_keeps_part_of_the_host(self):
        host = dict(block=HOST, enter=dict(pos=[-237, 2.5, -43.66], size=[12, 6, 2]), leave=dict(pos=[-255, 2.5, -43.66], size=[12, 6, 2]))
        ext = dict(name='Plaza', placement='extension', host=host, carry=dict(mode='region', region=[-270, -80, -200, -10]),
                   walls=[dict(name='WALL_E', pos=[-231, 2.7, -43.66], size=[2, 3, 6])])
        rep, out = self.build(dict(package='T', maps=[ext]), 'ext')
        bad = [c for c in rep['checks'] if c['result'] == 'FAIL']
        self.assertEqual(rep['result'], 'PASS', bad[:3])
        sec = rep['manifest']['sections'][0]
        self.assertEqual(sec['carry'], 'region')
        self.assertGreater(sec['carried']['removed'], sec['carried']['kept'] * 0.2)
        self.assertTrue(os.path.getsize(os.path.join(out, 'submap06_map02_lostoros_downtown.submap')) < 0.9 * os.path.getsize(os.path.join(out, HOST)))      # only drawn nodes are cut, so a region saves less than it used to
        warn = [c for c in rep['checks'] if 'edge of view' in c['check']]
        self.assertTrue(warn and warn[0]['result'] in ('PASS', 'WARN'))
        self.assertIn('edge_view', sec)


if __name__ == '__main__':
    unittest.main()
