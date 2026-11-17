"""The in-map building tools' backend (todms.mapbuild): live field and preview, heightmap files, blockout, section planner, minimap, meters."""
import base64
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from todms import mapbuild, mapgen, server, ledger, problems          # noqa: E402

MAP = dict(name='Test_Map', terrain=dict(cell=2.0, size=[40, 40], strokes=[dict(tool='raise', pos=[0, 0], radius=16, strength=6)]),
           ground_paint=dict(palette=['grass', 'dirt'], default='grass', strokes=[dict(material='dirt', pos=[10, 10], radius=8)],
                             surface_strokes=[dict(surface='Stone', pos=[-10, -10], radius=6)]),
           roads=[dict(id='main', points=[[-30, -10], [0, 0, 6], [30, 10]], width=8, elevated=True)],
           scatter=[dict(id='trees', circle=[-20, 20, 14], items=[dict(kind='tree', weight=2), dict(kind='rock', weight=1)], density=0.01, seed=2)],
           water=[dict(id='pond', circle=[20, -20, 8], depth=2)],
           edges=[dict(id='rim', kind='invisible', rect=[-38, -38, 38, 38], height=5, kill=dict(below=-20, respawn=[0, 0]))],
           look=dict(preset='clear_day'),
           blockout=[dict(id='b1', pos=[5, 2, 25], size=[6, 4, 6], yaw=30), dict(id='b2', pos=[15, 2, 25], size=[4, 3, 4], piece=dict(model='/data/Models/x.model', name='Hut'))])


class TestField(unittest.TestCase):
    def test_field_grids(self):
        f = mapbuild.field(MAP)
        t = f['terrain']
        self.assertEqual((t['nx'], t['nz']), (40, 40))
        self.assertEqual(len(base64.b64decode(t['heights'])), 41 * 41 * 4)
        self.assertEqual(len(base64.b64decode(t['paint'])), 40 * 40)
        self.assertEqual([p['id'] for p in f['palette']], ['grass', 'dirt'])
        self.assertGreater(t['max'], 5.0)

    def test_no_terrain(self):
        self.assertIsNone(mapbuild.field(dict(name='x'))['terrain'])

    def test_cached_by_recipe_keys(self):
        a = mapbuild.field(MAP)
        m2 = copy.deepcopy(MAP)
        m2['arrival'] = dict(pos=[1, 2, 3])                       # a key the generators do not read
        self.assertIs(mapbuild.field(m2), a)
        m3 = copy.deepcopy(MAP)
        m3['terrain']['strokes'].append(dict(tool='lower', pos=[0, 0], radius=4, strength=1))
        self.assertIsNot(mapbuild.field(m3), a)


class TestPreview(unittest.TestCase):
    def test_preview_has_geometry_numbers_and_rows(self):
        p = mapbuild.preview(MAP)
        self.assertTrue(any(n.startswith('R_main') for n in p['models']), list(p['models']))
        self.assertFalse(any(n.startswith('G_') for n in p['models']), 'the ground is drawn from the grid, not sent')
        self.assertTrue(p['placements'])
        self.assertIn('stats', p)
        ids = [r['id'] for r in p['rows']]
        for lid in ('G1', 'G2', 'G3', 'Q_main', 'Q_aux'):
            self.assertIn(lid, ids)
        g2 = next(r for r in p['rows'] if r['id'] == 'G2')
        self.assertEqual(g2['used'], p['stats']['ground_triangles'])
        self.assertTrue(p['traffic'] and p['triggers'] and p['walls'])

    def test_scatter_kit_parts_become_triangles(self):
        p = mapbuild.preview(MAP)
        trees = [n for n in p['models'] if n.startswith('S_trees')]
        self.assertTrue(trees)
        for n in trees:
            self.assertTrue(p['models'][n]['meshes'], n)
            me = p['models'][n]['meshes'][0]
            self.assertGreater(me['n'], 3)
            self.assertEqual(len(base64.b64decode(me['P'])), me['n'] * 12)

    def test_ground_on_request(self):
        p = mapbuild.preview(MAP, ground=True)
        self.assertTrue(any(n.startswith('G_') for n in p['models']))

    def test_collision_lines(self):
        p = mapbuild.preview(MAP, collision=True)
        self.assertTrue(any(m['hulls'] for m in p['models'].values()))

    def test_bad_recipe_is_a_plain_error(self):
        bad = copy.deepcopy(MAP)
        bad['ground_paint']['strokes'] = [dict(material='lava', pos=[0, 0], radius=3)]
        with self.assertRaises(mapgen.MapgenError):
            mapbuild.preview(bad)

    def test_deterministic(self):
        a = mapbuild.preview(copy.deepcopy(MAP))
        mapbuild._CACHE.clear()
        b = mapbuild.preview(copy.deepcopy(MAP))
        self.assertEqual(json.dumps(a['models'], sort_keys=True), json.dumps(b['models'], sort_keys=True))


class TestBlockout(unittest.TestCase):
    def test_boxes_expand_into_the_builders_shapes(self):
        res = mapgen.expand_full(dict(maps=[copy.deepcopy(MAP)]))
        mm = res['params']['maps'][0]
        ng = mm['new_geometry']
        self.assertIn('BLOCKOUT', [m['name'] for m in ng['models']])
        self.assertIn('B_Grey', [t['name'] for t in ng['textures']])
        self.assertTrue(any(p['model'] == 'BLOCKOUT' for p in ng['placements']))
        self.assertNotIn('blockout', mm)
        sw = [s for s in mm['shipped_models'] if s.get('blockout') == 'b2']
        self.assertEqual(len(sw), 1)
        self.assertEqual(res['stats']['Gen']['blockout'] if 'Gen' in res['stats'] else list(res['stats'].values())[0]['blockout'], dict(boxes=1, pieces=1))

    def test_a_map_with_only_boxes_is_expanded(self):
        m = dict(name='Only_Boxes', blockout=[dict(id='b', pos=[0, 0, 0], size=[4, 3, 4])])
        self.assertTrue(mapgen.has_mapgen(dict(maps=[m])))
        res = mapgen.expand_full(dict(maps=[m]))
        self.assertEqual(res['stats']['Only_Boxes']['blockout']['boxes'], 1)


class TestFiles(unittest.TestCase):
    def test_png16_round_trip(self):
        e = mapbuild.heightmap_export(MAP, 'png')
        self.assertEqual(base64.b64decode(e['data'])[:8], b'\x89PNG\r\n\x1a\n')
        t = mapbuild.heightmap_import(dict(data=e['data'], kind='png', lo=e['lo'], hi=e['hi'], cell=2.0))
        a = mapbuild.field(MAP)['terrain']
        b = mapbuild.field(dict(name='x', terrain=t))['terrain']
        ha = base64.b64decode(a['heights'])
        hb = base64.b64decode(b['heights'])
        import struct
        va = struct.unpack('<%df' % (len(ha) // 4), ha)
        vb = struct.unpack('<%df' % (len(hb) // 4), hb)
        self.assertLess(max(abs(x - y) for x, y in zip(va, vb)), (e['hi'] - e['lo']) / 60000.0 + 1e-4)

    def test_raw_round_trip(self):
        e = mapbuild.heightmap_export(MAP, 'raw')
        t = mapbuild.heightmap_import(dict(data=e['data'], kind='raw', nx=e['nx'], nz=e['nz'], cell=2.0))
        self.assertEqual(mapbuild.field(dict(name='x', terrain=t))['terrain']['heights'], mapbuild.field(MAP)['terrain']['heights'])

    def test_minimap_is_a_png_with_bounds(self):
        r = mapbuild.top_down(MAP, 128)
        self.assertEqual(base64.b64decode(r['png'])[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(r['bounds'], [-40.0, -40.0, 40.0, 40.0])


class TestPlanner(unittest.TestCase):
    PLAN = [dict(id='a', rect=[-40, -40, 0, 40]), dict(id='b', rect=[0, -40, 40, 40])]

    def test_section_numbers(self):
        s = mapbuild.plan_stats(MAP, self.PLAN)
        self.assertEqual(set(s), {'a', 'b'})
        self.assertEqual(s['a']['cells'] + s['b']['cells'], 40 * 40)
        self.assertGreater(s['a']['seconds'], 0)
        self.assertGreater(s['a']['instances'] + s['b']['instances'], 0)

    def test_walk_through_a_loader_is_loaded(self):
        sim = mapbuild.simulate(MAP, self.PLAN, [dict(id='L', a='a', b='b', pos=[0, 0, 0], size=[4, 6, 12])], [[-30, 0], [30, 0]])
        self.assertEqual(sim['flags'], [])
        self.assertGreater(sim['total_seconds'], 0)

    def test_walk_without_a_loader_is_flagged(self):
        sim = mapbuild.simulate(MAP, self.PLAN, [], [[-30, 0], [30, 0]])
        self.assertTrue(sim['flags'])
        self.assertEqual(sim['flags'][0]['kind'], 'unloaded')

    def test_ground_in_no_section_is_reported(self):
        sim = mapbuild.simulate(MAP, [dict(id='a', rect=[-40, -40, 0, 40])], [], [[-30, 0]])
        self.assertTrue(sim['gaps'])


class TestFeeds(unittest.TestCase):
    def test_ledger_rows_and_problems_for_a_project(self):
        params = dict(package='P', maps=[copy.deepcopy(MAP)])
        rows = {r['id']: r for r in mapbuild.rows_for(params)}
        self.assertEqual(rows['G2']['used'], mapbuild.preview(MAP)['stats']['ground_triangles'])
        self.assertIn('Q_main', rows)
        self.assertTrue(any(p['level'] == 'warn' for p in mapbuild.problems_for(params)))

    def test_a_map_without_generator_keys_adds_nothing(self):
        self.assertEqual(mapbuild.rows_for(dict(maps=[dict(name='x')])), [])
        self.assertEqual(mapbuild.problems_for(dict(maps=[dict(name='x')])), [])

    def test_a_broken_recipe_does_not_crash_the_meters(self):
        bad = copy.deepcopy(MAP)
        bad['ground_paint']['strokes'] = [dict(material='lava', pos=[0, 0], radius=3)]
        self.assertEqual(mapbuild.rows_for(dict(maps=[bad])), [])

    def test_ledger_compute_uses_the_expanded_recipe(self):
        class W:
            game = None
        rows = {r['id']: r for r in ledger.compute(W(), 'newmap', dict(package='P', maps=[copy.deepcopy(MAP)]))['rows']}
        self.assertEqual(rows['G2']['status'], 'ok')
        self.assertGreater(rows['G2']['used'], 0)
        self.assertEqual(rows['G1']['used'], 2)

    def test_routes_are_registered(self):
        for p in ('/api/mapbuild/field', '/api/mapbuild/preview', '/api/mapbuild/heightmap', '/api/mapbuild/plan', '/api/mapbuild/topdown'):
            self.assertIn(p, server.POST)
        self.assertIn('/api/mapbuild/looks', server.GET)
        self.assertIn('/api/mapbuild/kits', server.GET)

    def test_look_presets_for_the_picker(self):
        r = mapbuild.look_presets()
        self.assertIn('clear_day', [p['id'] for p in r['presets']])
        self.assertIn('ClearBlueSky', r['skies'])


class TestKits(unittest.TestCase):
    ROWS = [dict(key='a', label='Adobe Wall', path='/x/a.model', cat='buildings', triangles=300, size=[4, 3, 0.4], maps={'MAINMAP_Map08_Hacienda.map': 9}),
            dict(key='b', label='Huge Thing', path='/x/b.model', cat='buildings', triangles=90000, size=[40, 30, 40], maps={'MAINMAP_Map08_Hacienda.map': 99}),
            dict(key='c', label='Crate', path='/x/c.model', cat='crates', triangles=12, size=[2, 2, 2], maps={'MAINMAP_Map03_Industrial.map': 5}),
            dict(key='d', label='Pebble', path='/x/d.model', cat='crates', triangles=12, size=[0.3, 0.3, 0.3], maps={'MAINMAP_Map03_Industrial.map': 50})]

    def test_kits_from_the_catalogue(self):
        from todms import catalogue
        old = catalogue.table
        catalogue.table = lambda ws=None: dict(rows=self.ROWS, maps=['MAINMAP_Map08_Hacienda.map', 'MAINMAP_Map03_Industrial.map'])
        try:
            r = mapbuild.kits(None)
        finally:
            catalogue.table = old
        self.assertTrue(r['ready'])
        ad = next(k for k in r['kits'] if k['id'] == 'adobe')
        self.assertEqual([p['key'] for p in ad['pieces']], ['a'])                  # the 90,000-triangle piece is left out
        self.assertEqual(ad['pieces'][0]['cost'], dict(nodes=1, triangles=300))
        self.assertEqual([p['key'] for p in next(k for k in r['kits'] if k['id'] == 'industrial')['pieces']], ['c'])      # a pebble is clutter, not a piece

    def test_not_ready_before_the_scan(self):
        from todms import catalogue
        old = catalogue.table
        catalogue.table = lambda ws=None: None
        try:
            r = mapbuild.kits(None)
        finally:
            catalogue.table = old
        self.assertFalse(r['ready'])
        self.assertEqual([k['id'] for k in r['kits']], ['adobe', 'downtown', 'industrial', 'hacienda', 'harbour'])


if __name__ == '__main__':
    unittest.main()


class TestBlockoutInMapgen(unittest.TestCase):
    """The grey boxes are a supported mapgen key now (todms.mapgen.blockout), not a wrapper of mapbuild."""
    BO = dict(name='Bo_Map', blockout=[dict(id='b1', pos=[5, 2, 25], size=[6, 4, 6], yaw=30),
                                       dict(id='p1', pos=[15, 2, 25], size=[4, 3, 4], yaw=90, piece=dict(model='/data/Models/x.model', name='Hut')),
                                       dict(id='p2', pos=[25, 2, 25], size=[4, 3, 4], piece=dict(model='/data/Models/x.model', name='Hut'))])

    def test_it_is_a_high_key_without_importing_mapbuild(self):
        self.assertIn('blockout', mapgen.HIGH_KEYS)
        self.assertTrue(mapgen.has_mapgen(dict(maps=[self.BO])))

    def test_boxes_count_in_the_numbers(self):
        st = mapgen.expand_full(dict(maps=[copy.deepcopy(self.BO)]))['stats']['Bo_Map']
        self.assertEqual(st['blockout'], dict(boxes=1, pieces=2))
        self.assertEqual(st['models'], 1)
        self.assertGreaterEqual(st['collision_pieces'], 1)
        self.assertEqual(st['nodes_added'], 1 + 2)                                  # the box model and two shipped pieces

    def test_pieces_reach_the_builder_through_shipped_models(self):
        assets = dict(models={'/data/models/x.model': dict(blocks=['b.map'], textures=[])})
        res = mapgen.expand_full(dict(maps=[copy.deepcopy(self.BO)]), assets)
        mm = res['params']['maps'][0]
        self.assertEqual([s['blockout'] for s in mm['shipped_models']], ['p1', 'p2'])
        self.assertEqual(mm['shipped_models'][0]['blocks'], ['b.map'])
        self.assertTrue(any('turned' in n for n in res['notes']))                   # one piece is turned, the builder cannot turn it
        from todms.newmap_recipe import make_new_map as R
        ng = R.shipped_into_geometry(mm)
        self.assertEqual([m['name'] for m in ng['models']], ['BLOCKOUT', 'SH1'])
        self.assertEqual(len([p for p in ng['placements'] if p['model'] == 'SH1']), 2)

    def test_same_input_same_output(self):
        a = mapgen.dumps(mapgen.expand(dict(maps=[copy.deepcopy(self.BO)])))
        b = mapgen.dumps(mapgen.expand(dict(maps=[copy.deepcopy(self.BO)])))
        self.assertEqual(a, b)


class TestPlanAndJumps(unittest.TestCase):
    def _map(self):
        m = copy.deepcopy(MAP)
        m['sections_plan'] = dict(sections=[dict(id='a', name='West', rect=[-40, -40, 0, 40]), dict(id='b', name='East', rect=[0, -40, 40, 40])],
                                  loaders=[dict(id='l1', a='a', b='zzz', pos=[0, 0, 0], size=[12, 6, 2])], path=[[-30, 0], [30, 0]])
        return m

    def test_the_plan_gives_advice_in_plain_sentences(self):
        notes = mapbuild.plan_notes(self._map())
        self.assertTrue(any('joins a section that is not in the plan' in n for n in notes))
        self.assertTrue(any('no loaded section covers' in n for n in notes))        # the loader is broken, so East is never loaded on the walk

    def test_problems_carry_the_area_and_the_tool(self):
        rows = mapbuild.problems_for(dict(maps=[self._map()]))
        plan = [r for r in rows if r['source'] == 'sections']
        self.assertTrue(plan)
        self.assertEqual(plan[0]['jump'], dict(screen='newmaps', area='map', tool='sections'))

    def test_every_problem_of_a_new_map_says_where_it_is_fixed(self):
        from todms import problems
        for text, area, tool in (('Ground triangles: 100,000 of 90,000', 'map', 'terrain'), ('section X: edge of view: 12 sight lines', 'atlas', None),
                                 ('The arrival lies outside the map ground', 'entrances', None), ('minimap area of X', 'map', 'minimap'),
                                 ('The look is too dark', 'map', 'look'), ('Aux quadtree: 9,000 of 12,200', 'map', 'scatter')):
            j = problems.newmap_jump(text)
            self.assertEqual((j.get('area'), j.get('tool')), (area, tool), text)
        res = mapgen.expand_full(dict(maps=[copy.deepcopy(TestBlockoutInMapgen.BO)]))
        for r in problems.from_mapgen(res):
            self.assertIn('area', r['jump'], r['title'])


class TestMinimapPreview(unittest.TestCase):
    def test_the_picture_reads_back_at_the_dot(self):
        from todms import minimap
        r = minimap.preview(MAP, None, 256, [0, 0])
        self.assertEqual(base64.b64decode(r['png'])[1:4], b'PNG')
        self.assertEqual(r['bounds'][0], -64.0)
        self.assertTrue(r['at']['inside'])
        self.assertEqual(r['at']['pixel'], [256.0, 256.0])                           # (x - x0) / 0.25 as the DLL computes it
        out = minimap.preview(MAP, None, 256, [500, 500])
        self.assertFalse(out['at']['inside'])

    def test_a_map_with_nothing_to_draw_is_refused_plainly(self):
        from todms import minimap
        with self.assertRaises(minimap.MinimapError):
            minimap.preview(dict(name='Empty'))
