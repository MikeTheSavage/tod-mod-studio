"""Map generators (todms/mapgen): terrain, ground paint, roads, edges, water, scatter, look, determinism and limit splitting."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import paths, mapgen, ledger, limits, problems                       # noqa: E402
from todms.mapgen import terrain, paint, look, roads, ground, meshkit, core, geoplug, texkinds  # noqa: E402
from todms.mapgen.core import np                                      # noqa: E402

GAME = os.path.join(os.environ.get('TODMS_PROOF', '/no-proof-copy'), 'game')


def recipe(**keys):
    return dict(package='T', maps=[dict(name='Map11_Test', source='map10_runawaytrain', **keys)])


def stats_of(p):
    return mapgen.expand_full(p)['stats']['Map11_Test']


def geo(p):
    return mapgen.expand(p)['maps'][0]['new_geometry']


HILL = dict(size=[40, 40], cell=2.0, strokes=[dict(tool='raise', pos=[0, 0], radius=24, strength=6)])


class Determinism(unittest.TestCase):
    def test_same_input_same_bytes(self):
        p = recipe(terrain=HILL, ground_paint=dict(palette=['dirt', 'grass'], strokes=[dict(material='grass', pos=[10, 10], radius=12)]),
                   roads=[dict(id='a', points=[[-30, -30], [0, 0], [30, 30]])], water=[dict(id='w', circle=[-20, 20, 8])],
                   scatter=[dict(id='s', rect=[-35, -35, 35, 35], density=0.01, seed=3)], look=dict(preset='dawn'))
        a = mapgen.dumps(mapgen.expand(p))
        b = mapgen.dumps(mapgen.expand(copy.deepcopy(p)))
        self.assertEqual(a, b)
        self.assertGreater(len(a), 1000)

    def test_input_is_not_changed(self):
        p = recipe(terrain=HILL)
        before = json.dumps(p, sort_keys=True)
        mapgen.expand(p)
        self.assertEqual(before, json.dumps(p, sort_keys=True))

    def test_expanded_recipe_is_stable_when_expanded_again(self):
        p = mapgen.expand(recipe(terrain=HILL))
        self.assertEqual(mapgen.dumps(p), mapgen.dumps(mapgen.expand(p)))

    def test_map_without_keys_is_untouched(self):
        p = recipe()
        self.assertEqual(mapgen.expand(p), p)


class Terrain(unittest.TestCase):
    def grid(self, **kw):
        t = dict(size=[20, 20], cell=2.0)
        t.update(kw)
        out = core.Out('t')
        return terrain.build(t, out)

    def test_raise_and_lower(self):
        up = self.grid(strokes=[dict(tool='raise', pos=[0, 0], radius=10, strength=3)])
        self.assertAlmostEqual(float(up.at(0, 0)), 3.0, places=1)
        self.assertAlmostEqual(float(up.at(30, 30)), 0.0)
        down = self.grid(strokes=[dict(tool='lower', pos=[0, 0], radius=10, strength=2)])
        self.assertLess(float(down.at(0, 0)), -1.5)

    def test_flatten_and_ramp(self):
        t = self.grid(noise=dict(seed=2, amp=3.0, scale=10), strokes=[dict(tool='flatten', pos=[0, 0], radius=8, strength=1, height=1.0, falloff='flat')])
        self.assertAlmostEqual(float(t.at(1, 1)), 1.0, places=2)
        r = self.grid(strokes=[dict(tool='ramp', pos=[-14, 0], to=[14, 0], radius=5, strength=1, height=0.0, to_height=6.0, falloff='flat')])
        self.assertAlmostEqual(float(r.at(-14, 0)), 0.0, places=1)
        self.assertAlmostEqual(float(r.at(14, 0)), 6.0, places=1)
        self.assertAlmostEqual(float(r.at(0, 0)), 3.0, places=1)

    def test_smooth_reduces_roughness(self):
        base = self.grid(noise=dict(seed=5, amp=4.0, scale=4))
        sm = self.grid(noise=dict(seed=5, amp=4.0, scale=4), strokes=[dict(tool='smooth', pos=[0, 0], radius=40, strength=1, passes=4, falloff='flat')])
        self.assertLess(float(np.abs(np.diff(sm.h, axis=1)).mean()), float(np.abs(np.diff(base.h, axis=1)).mean()))

    def test_unknown_tool_and_size(self):
        with self.assertRaises(core.MapgenError):
            self.grid(strokes=[dict(tool='melt', pos=[0, 0])])
        with self.assertRaises(core.MapgenError):
            self.grid(cell=40.0)

    def test_png16_and_raw_round_trip(self):
        h = np.linspace(-2.0, 9.0, 21 * 31).reshape(21, 31)
        png, lo, hi = terrain.export_png16(h)
        back = terrain.import_png16(png, lo, hi)
        self.assertEqual(back.shape, h.shape)
        self.assertLess(float(np.abs(back - h).max()), (hi - lo) / 65535.0 + 1e-9)
        raw = terrain.export_raw(h)
        self.assertLess(float(np.abs(terrain.import_raw(raw, 30, 20) - h).max()), 1e-5)
        with self.assertRaises(core.MapgenError):
            terrain.import_raw(raw, 29, 20)
        t = terrain.terrain_key_from_png(png, lo, hi, cell=4.0)
        self.assertEqual(terrain.build(t, core.Out('x')).nx, 30)

    def test_png_other_filters_and_bad_files(self):
        import struct, zlib
        w, hgt = 5, 4
        rows = [[(3 * i + 5 * j) % 256 for i in range(w)] for j in range(hgt)]
        raw = b''
        prev = [0] * w
        for j, row in enumerate(rows):
            f = j % 5 if j % 5 < 5 else 0
            f = [1, 2, 3, 4][j % 4]
            out = []
            for i, v in enumerate(row):
                a = row[i - 1] if i else 0
                b = prev[i]
                c = prev[i - 1] if i else 0
                if f == 1:
                    pr = a
                elif f == 2:
                    pr = b
                elif f == 3:
                    pr = (a + b) >> 1
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                out.append((v - pr) & 255)
            raw += bytes([f]) + bytes(out)
            prev = row

        def chunk(tag, data):
            return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, hgt, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
        got = terrain.import_png16(png, 0.0, 255.0)
        self.assertEqual(got.tolist(), [[float(v) for v in r] for r in rows])
        with self.assertRaises(core.MapgenError):
            terrain.import_png16(b'not a png', 0, 1)

    def test_heights_import_in_recipe_and_chunks(self):
        h = np.zeros((11, 11))
        h[5, 5] = 4.0
        p = recipe(terrain=dict(cell=2.0, heights=core.pack_grid(h), chunk=4))
        st = stats_of(p)
        self.assertEqual(st['terrain']['nx'], 10)
        self.assertEqual(st['terrain']['max'], 4.0)
        self.assertEqual(sum(c['triangles'] for c in st['chunks']), 200)


class Chunks(unittest.TestCase):
    def test_counts_per_chunk_and_totals(self):
        st = stats_of(recipe(terrain=dict(size=[48, 48], cell=2.0, chunk=24, noise=dict(seed=1, amp=2.0, scale=12))))
        self.assertEqual(len(st['chunks']), 4)
        for c in st['chunks']:
            self.assertEqual(c['triangles'], 24 * 24 * 2)
            self.assertEqual(c['vertices'], 25 * 25)
        self.assertEqual(st['ground_triangles'], 48 * 48 * 2)
        self.assertLessEqual(st['max_submesh_vertices'], 65535)
        self.assertLessEqual(st['max_hull_vertices'], 255)

    def test_hull_cap_splits_a_chunk(self):
        p = recipe(terrain=dict(size=[24, 24], cell=2.0, chunk=24, noise=dict(seed=1, amp=3.0, scale=6)))
        one = stats_of(p)
        self.assertEqual(len(one['chunks']), 1)
        old = ground.HULL_CAP
        ground.HULL_CAP = 300
        try:
            many = stats_of(p)
        finally:
            ground.HULL_CAP = old
        self.assertGreater(len(many['chunks']), 1)
        self.assertEqual(many['ground_triangles'], one['ground_triangles'])
        for c in many['chunks']:
            self.assertLessEqual

    def test_vertex_cap_reduces_chunk_size(self):
        old = meshkit.VERT_CAP
        ground_cap = ground.VERT_CAP
        meshkit.VERT_CAP = ground.VERT_CAP = 300
        try:
            st = stats_of(recipe(terrain=dict(size=[40, 40], cell=2.0, chunk=40)))
        finally:
            meshkit.VERT_CAP = old
            ground.VERT_CAP = ground_cap
        self.assertGreater(len(st['chunks']), 1)
        self.assertLessEqual(st['max_submesh_vertices'], 300)

    def test_flat_ground_merges_into_few_pieces(self):
        st = stats_of(recipe(terrain=dict(size=[40, 40], cell=2.0)))
        self.assertLessEqual(st['collision_pieces'], 4)

    def test_part_round_trip(self):
        m = meshkit.Mesh()
        m.quad('T', (0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1), n=(0, 1, 0))
        m.hull([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 1), (0, 0, 1)], 'thin', 'Wood')
        meshes, hulls = meshkit.read_part(m.part())
        self.assertEqual(len(meshes[0]['I']), 2)
        self.assertEqual(hulls[0][1:], ('thin', 3))

    def test_hull_vertex_limit(self):
        m = meshkit.Mesh()
        with self.assertRaises(core.MapgenError):
            m.hull(np.zeros((256, 3)))


class Paint(unittest.TestCase):
    def test_palette_cap_comes_from_the_limit(self):
        n = limits.value('G1')
        pal = [dict(id='m%d' % i, kind='sand') for i in range(n + 1)]
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=pal)))
        mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=pal[:n])))

    def test_one_submesh_per_material_and_strokes(self):
        st = stats_of(recipe(terrain=dict(size=[20, 20], cell=2.0), ground_paint=dict(
            palette=['dirt', 'grass', 'asphalt'], strokes=[dict(material='grass', rect=[-20, -20, 0, 0]), dict(material='asphalt', rect=[5, 5, 15, 15])])))
        self.assertEqual(st['ground_materials'], 3)
        self.assertEqual(sorted(st['chunks'][0]['textures']), ['G_asphalt', 'G_dirt', 'G_grass'])

    def test_rock_on_steep_cells_and_surface_layer_is_separate(self):
        p = recipe(terrain=dict(size=[20, 20], cell=2.0, strokes=[dict(tool='raise', pos=[0, 0], radius=10, strength=12)]),
                   ground_paint=dict(palette=['dirt', 'rock'], rock_slope=0.6, surface_strokes=[dict(surface='Grass', rect=[-20, -20, 20, 20])]))
        out = core.Out('t')
        H = terrain.build(p['maps'][0]['terrain'], out)
        pal, tex, surf = paint.build(H, p['maps'][0]['ground_paint'], out)
        self.assertTrue((tex == 1).any() and (tex == 0).any())
        self.assertTrue((surf == core.mat_index('Grass')).all())            # the surface layer ignores the painted material
        self.assertEqual(paint.pack(tex)['shape'], [20, 20])

    def test_surface_follows_the_material_by_default(self):
        out = core.Out('t')
        H = terrain.build(dict(size=[8, 8]), out)
        pal, tex, surf = paint.build(H, dict(palette=['dirt', 'asphalt'], strokes=[dict(material='asphalt', rect=[0, 0, 8, 8])]), out)
        self.assertTrue((surf[4:, 4:] == core.mat_index('Asphalt')).all())
        self.assertTrue((surf[:4, :4] == core.mat_index('Dirt')).all())

    def test_shipped_pictures_are_found_through_the_asset_index(self):
        doc = dict(textures={
            '/data/models/x/ter_grass_lush.bmp': dict(w=128, h=128, fmt='DXT1'),
            '/data/models/x/lod_grass.bmp': dict(w=32, h=32, fmt='DXT1'),
            '/data/models/x/smallgrass02.bmp': dict(w=128, h=64, fmt='RGBA32'),
            '/data/models/x/ter_cliffrock_grey.bmp': dict(w=128, h=128, fmt='DXT1'),
            '/data/models/x/road_dry.bmp': dict(w=128, h=128, fmt='DXT1')})
        self.assertEqual(paint.shipped_match('grass', doc), '/data/models/x/ter_grass_lush.bmp')
        self.assertEqual(paint.shipped_match('rock', doc), '/data/models/x/ter_cliffrock_grey.bmp')
        self.assertEqual(paint.shipped_match('asphalt', doc), '/data/models/x/road_dry.bmp')
        self.assertIsNone(paint.shipped_match('dirt', doc))
        res = mapgen.expand_full(recipe(terrain=HILL, ground_paint=dict(palette=['dirt', 'grass'])), assets=doc)
        tx = {t['name']: t for t in res['params']['maps'][0]['new_geometry']['textures']}
        self.assertEqual(tx['G_grass']['shipped'], '/data/models/x/ter_grass_lush.bmp')
        self.assertNotIn('shipped', tx['G_dirt'])
        self.assertTrue(any('ter_grass_lush' in n for n in res['notes']))
        plain = mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=['dirt', 'grass'])))
        self.assertFalse(any('shipped' in t for t in plain['maps'][0]['new_geometry']['textures']))

    def test_bad_inputs(self):
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=['lava'])))
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=['dirt'], strokes=[dict(material='grass', pos=[0, 0])])))
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(terrain=HILL, ground_paint=dict(palette=['dirt'], surface_strokes=[dict(surface='Lava', pos=[0, 0])])))

    def test_texture_kinds_make_pictures(self):
        for k in ('dirt', 'grass', 'asphalt', 'foliage', 'road_l2'):
            img = texkinds.render(k, 64, 3)
            self.assertEqual(img.shape, (64, 64, 3))
            self.assertTrue(0.0 <= float(img.min()) and float(img.max()) <= 1.0)
        self.assertEqual(texkinds.render('water', 64, 3).shape, (64, 64, 4))
        a = texkinds.render('grass', 64, 3)
        self.assertTrue((a == texkinds.render('grass', 64, 3)).all())


class Roads(unittest.TestCase):
    def road(self, **kw):
        r = dict(id='r', points=[[-40, 0], [0, 0], [40, 0]], width=8, lanes=2)
        r.update(kw)
        return r

    def test_ribbon_kerb_collision_and_texture(self):
        p = recipe(terrain=dict(size=[40, 40], cell=2.0), roads=[self.road()])
        st = stats_of(p)
        rd = st['roads'][0]
        self.assertAlmostEqual(rd['length'], 80.0, delta=0.5)
        self.assertGreater(rd['hulls'], 15)
        g = geo(p)
        self.assertIn('R_Road2L', [t['name'] for t in g['textures']])
        self.assertIn('R_Kerb', [t['name'] for t in g['textures']])
        self.assertEqual([t['kind'] for t in g['textures'] if t['name'] == 'R_Road2L'], ['road_l2'])

    def test_grading_flattens_the_bed_across_the_road(self):
        p = recipe(terrain=dict(size=[40, 40], cell=2.0, strokes=[dict(tool='raise', pos=[0, 0], radius=20, strength=5)]), roads=[self.road(points=[[-30, 0], [30, 0]])])
        out = core.Out('t')
        H = terrain.build(p['maps'][0]['terrain'], out)
        before = float(H.at(0, 3.0))
        roads.build_road(p['maps'][0]['roads'][0], 0, H, out, lambda *a: 'T')
        a, b = float(H.at(0, 0)), float(H.at(0, 3.0))
        self.assertAlmostEqual(a, b, delta=0.05)
        self.assertNotAlmostEqual(before, b, delta=0.2)

    def test_slope_warnings(self):
        gentle = mapgen.expand_full(recipe(terrain=dict(size=[40, 40], cell=2.0), roads=[self.road()]))
        self.assertEqual([n for n in gentle['notes'] if 'climbs' in n], [])
        steep = mapgen.expand_full(recipe(terrain=dict(size=[40, 40], cell=2.0, strokes=[dict(tool='ramp', pos=[-20, 0], to=[20, 0], radius=8, height=0, to_height=9, falloff='flat')]),
                                          roads=[self.road(grade=False)]))
        self.assertTrue(any('cars' in n and 'climbs' in n for n in steep['notes']))
        verysteep = mapgen.expand_full(recipe(roads=[dict(id='cliff', points=[[0, 0, 0], [10, 0, 6], [20, 0, 12]], elevated=True)]))
        self.assertTrue(any('too steep to walk' in n for n in verysteep['notes']))

    def test_elevated_road_has_deck_walls_and_pillars(self):
        p = recipe(terrain=dict(size=[60, 20], cell=2.0), roads=[dict(id='br', elevated=True, width=8, points=[[-50, 0], [-30, 0, 5], [30, 0, 5], [50, 0]])])
        st = stats_of(p)
        self.assertTrue(st['roads'][0]['elevated'])
        g = geo(p)
        part = [m for m in g['models'] if m['name'].startswith('R_br')][0]['parts'][0]
        meshes, hulls = meshkit.read_part(part)
        names = {m['tex'] for m in meshes}
        self.assertIn('R_Concrete', names)
        thin = [h for h in hulls if h[1] == 'thin']
        self.assertGreater(len(thin), 5)                                    # side walls
        self.assertGreater(len(hulls), 40)                                  # deck pieces, walls, pillars
        self.assertEqual(st['roads'][0]['graded_cells'], 0)                 # a bridge leaves the ground alone

    def test_a_third_number_is_the_height_and_the_line_passes_the_points(self):
        road = dict(id='b', elevated=True, width=7, points=[[2.0, 58.0], [34.0, 30.0, 1.8], [58.0, 6.0]])
        xz, s = roads.spline([[p[0], p[1]] for p in road['points']], 2.0)
        for p in road['points']:
            self.assertLess(float(np.hypot(xz[:, 0] - p[0], xz[:, 1] - p[1]).min()), 1.0)
        out = core.Out('t')
        y = roads.profile(road, xz, s, core.Heights(h=None, flat=0.0), out)
        mid = int(np.argmin(np.hypot(xz[:, 0] - 34.0, xz[:, 1] - 30.0)))
        self.assertAlmostEqual(float(y[mid]), 1.8, places=3)
        self.assertAlmostEqual(float(y[0]), 0.0, places=3)                 # an end without a height sits on the ground
        self.assertLessEqual(float(np.abs(np.diff(y) / np.diff(s)).max()), 0.1)

    def test_traffic_route_format(self):
        res = mapgen.expand(recipe(terrain=dict(size=[40, 40], cell=2.0), roads=[self.road()]))
        routes = res['maps'][0]['traffic_routes']
        self.assertEqual(sorted(r['direction'] for r in routes), ['B', 'F'])
        pts = routes[0]['points']
        self.assertTrue(pts[0]['name'].startswith('TRAFFIC_R_F'))
        self.assertEqual(pts[0]['next'], pts[1]['name'])
        self.assertIsNone(pts[-1]['next'])
        one = mapgen.expand(recipe(roads=[self.road(lanes=1)]))['maps'][0]['traffic_routes']
        self.assertEqual(len(one), 1)
        none = mapgen.expand(recipe(roads=[self.road(traffic=False)]))['maps'][0]
        self.assertNotIn('traffic_routes', none)

    def test_bad_roads(self):
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(roads=[dict(id='x', points=[[0, 0]])]))
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(roads=[self.road(width=100)]))

    def test_long_road_splits_into_models(self):
        p = recipe(roads=[self.road(points=[[0, 0], [300, 0], [600, 0]])])
        st = stats_of(p)
        self.assertGreater(len(st['roads'][0]['models']), 1)
        self.assertLessEqual(st['max_submesh_vertices'], 65535)


class Edges(unittest.TestCase):
    SQ = [[-30, -30], [30, -30], [30, 30], [-30, 30]]

    def test_invisible_walls_become_wall_boxes(self):
        m = mapgen.expand(recipe(terrain=dict(size=[40, 40], cell=2.0), edges=[dict(id='rim', kind='invisible', polygon=self.SQ, height=6)]))['maps'][0]
        self.assertGreaterEqual(len(m['walls']), 4 * 3)
        w = m['walls'][0]
        self.assertEqual(sorted(w), ['flags', 'name', 'orient', 'pos', 'size'])
        self.assertTrue(all(0.05 <= s <= 512 for x in m['walls'] for s in x['size']))
        self.assertAlmostEqual(sum(x['size'][0] - 0.2 for x in m['walls']), 240.0, delta=1.0)

    def test_cliff_has_mesh_and_collision(self):
        st = stats_of(recipe(terrain=dict(size=[40, 40], cell=2.0), edges=[dict(id='rim', kind='cliff', rect=[-30, -30, 30, 30])]))
        e = st['edges'][0]
        self.assertAlmostEqual(e['length'], 240.0, delta=0.5)
        self.assertGreater(e['pieces'], 30)
        self.assertGreater(e['triangles'], 100)

    def test_kill_plane_teleports_to_a_spot(self):
        m = mapgen.expand(recipe(edges=[dict(id='rim', kind='invisible', polygon=self.SQ, kill=dict(below=-20, respawn=[0, 0]))]))['maps'][0]
        t = m['triggers'][0]
        self.assertEqual(t['kind'], 'teleport')
        self.assertIn(t['teleport_to'], [s['name'] for s in m['teleports']])
        self.assertLess(t['pos'][1], -20)
        named = mapgen.expand(recipe(edges=[dict(id='rim', kind='invisible', polygon=self.SQ, kill=dict(respawn='SPOT_1'))]))['maps'][0]
        self.assertEqual(named['triggers'][0]['teleport_to'], 'SPOT_1')
        self.assertNotIn('teleports', named)

    def test_bad_kind(self):
        with self.assertRaises(core.MapgenError):
            mapgen.expand(recipe(edges=[dict(kind='lava', rect=[0, 0, 5, 5])]))


class Water(unittest.TestCase):
    def test_basin_is_carved_and_plane_added(self):
        p = recipe(terrain=dict(size=[40, 40], cell=2.0), water=[dict(id='pond', circle=[0, 0, 10], depth=2.5, rule='reset')])
        res = mapgen.expand_full(p)
        st = res['stats']['Map11_Test']
        w = st['water'][0]
        self.assertEqual(w['rule'], 'reset')
        self.assertGreater(w['area'], 250)
        self.assertTrue(any('swimming does not exist' in n for n in res['notes']))
        self.assertTrue(any(m['name'] == 'W_pond' for m in res['params']['maps'][0]['new_geometry']['models']))
        tx = [t for t in res['params']['maps'][0]['new_geometry']['textures'] if t['name'] == 'W_Water'][0]
        self.assertEqual(tx['format'], 'RGBA32')
        out = core.Out('t')
        H = terrain.build(p['maps'][0]['terrain'], out)
        res_w = __import__('todms.mapgen.water', fromlist=['x']).carve(p['maps'][0]['water'][0], 0, H, out)
        self.assertLess(float(H.at(0, 0)), res_w['level'] - 2.0)
        self.assertGreater(float(H.at(12.5, 0)), res_w['level'])

    def test_reset_and_kill_rules(self):
        base = dict(id='pond', circle=[0, 0, 10])
        r = mapgen.expand(recipe(water=[dict(base, rule='reset')]))['maps'][0]
        self.assertTrue(all(t['kind'] == 'teleport' for t in r['triggers']))
        self.assertIn(r['triggers'][0]['teleport_to'], [s['name'] for s in r['teleports']])
        k = mapgen.expand_full(recipe(water=[dict(base, rule='kill')]))
        self.assertTrue(all(t['kind'] == 'end_mission' and t['result'] == 0 for t in k['params']['maps'][0]['triggers']))
        self.assertTrue(any('fail' in n for n in k['notes']))
        n = mapgen.expand(recipe(water=[dict(base, rule='none')]))['maps'][0]
        self.assertNotIn('triggers', n)

    def test_trigger_boxes_cover_the_water(self):
        m = mapgen.expand(recipe(water=[dict(id='pond', rect=[-10, -10, 10, 10], rule='reset')]))['maps'][0]
        area = sum(t['size'][0] * t['size'][2] for t in m['triggers'])
        self.assertGreater(area, 300)
        self.assertLessEqual(len(m['triggers']), 12)


class Scatter(unittest.TestCase):
    def base(self, **kw):
        s = dict(id='s', rect=[-40, -40, 40, 40], density=0.02, seed=4, items=[dict(kind='tree')], min_dist=3.0)
        s.update(kw)
        return recipe(terrain=dict(size=[40, 40], cell=2.0, noise=dict(seed=3, amp=1.0, scale=15)), scatter=[s])

    def test_min_distance_and_count(self):
        m = mapgen.expand(self.base())['maps'][0]
        trees = [p for p in m['new_geometry']['placements'] if p['name'].startswith('SC_')]
        self.assertGreater(len(trees), 20)
        for i, a in enumerate(trees):
            for b in trees[i + 1:]:
                self.assertGreaterEqual(((a['pos'][0] - b['pos'][0]) ** 2 + (a['pos'][2] - b['pos'][2]) ** 2) ** 0.5, 3.0 - 1e-6)

    def test_slope_limit_and_roads_and_water_exclusion(self):
        hill = recipe(terrain=dict(size=[40, 40], cell=2.0, strokes=[dict(tool='raise', pos=[0, 0], radius=20, strength=30)]),
                      scatter=[dict(id='s', rect=[-40, -40, 40, 40], density=0.05, seed=1, slope_max=0.3, items=[dict(kind='rock')])],
                      roads=[dict(id='r', points=[[-40, 30], [40, 30]], width=8)], water=[dict(id='w', circle=[-25, -25, 8], rule='none')])
        res = mapgen.expand(hill)['maps'][0]
        rocks = [p for p in res['new_geometry']['placements'] if p['name'].startswith('SC_')]
        self.assertGreater(len(rocks), 5)
        H = terrain.build(hill['maps'][0]['terrain'], core.Out('t'))
        for p in rocks:
            x, z = p['pos'][0], p['pos'][2]
            self.assertLessEqual(float(H.slope_at(x, z)), 0.31)
            self.assertGreater(abs(z - 30), 4.0 + 2.0 - 1e-6)
            self.assertGreater(((x + 25) ** 2 + (z + 25) ** 2) ** 0.5, 8.0)

    def test_cap_and_report(self):
        res = mapgen.expand_full(self.base(max=10))
        st = res['stats']['Map11_Test']
        self.assertEqual(st['scatter'][0]['instances'], 10)
        self.assertTrue(st['scatter'][0]['capped'])
        self.assertTrue(any('cap of 10' in n for n in res['notes']))
        self.assertEqual(st['generated_instances'], len([p for p in res['params']['maps'][0]['new_geometry']['placements']]))

    def test_trees_carry_trunk_collision_and_bushes_do_not(self):
        m = mapgen.expand(self.base(items=[dict(kind='tree'), dict(kind='bush')]))['maps'][0]
        by = {md['name']: md for md in m['new_geometry']['models'] if md['name'].startswith('S_')}
        tree = [md for n, md in by.items() if '_tree_' in n][0]
        bush = [md for n, md in by.items() if '_bush_' in n][0]
        self.assertTrue(any(p.get('collide') for p in tree['parts'] if p['type'] == 'box'))
        self.assertFalse(any(p.get('collide') for p in bush['parts']))

    def test_shipped_model_items_are_listed_with_solid_hulls(self):
        res = mapgen.expand_full(self.base(items=[dict(model='/Models/Addons/Trees/Palm.model', solid=True, radius=0.3)]))
        m = res['params']['maps'][0]
        self.assertGreater(len(m['shipped_models']), 10)
        self.assertEqual(m['shipped_models'][0]['orient'], [0.0, 0.0, 0.0, 1.0])
        self.assertTrue(any('cannot be scaled' in n for n in res['notes']))
        self.assertTrue(any('models of the game' in n for n in res['notes']))
        flat = res['stats']['Map11_Test']
        self.assertGreater(flat['collision_pieces'], 900)                    # the ground pieces plus one trunk box per instance

    def test_seed_changes_the_picture(self):
        a = [p['pos'] for p in mapgen.expand(self.base(seed=1))['maps'][0]['new_geometry']['placements']]
        b = [p['pos'] for p in mapgen.expand(self.base(seed=2))['maps'][0]['new_geometry']['placements']]
        self.assertNotEqual(a, b)

    def test_bad_item(self):
        with self.assertRaises(core.MapgenError):
            mapgen.expand(self.base(items=[dict(kind='ufo')]))
        with self.assertRaises(core.MapgenError):
            mapgen.expand(self.base(density=9))


class Look(unittest.TestCase):
    def test_presets_and_skies_come_from_the_shipped_files(self):
        self.assertIn('ClearBlueSky', look.skies())
        self.assertGreaterEqual(len(look.presets()), 5)
        p = look.resolve(dict(preset='clear_day'))
        self.assertEqual(p['sky'], 'ClearBlueSky')
        self.assertEqual(p['fog']['far'], 400.0)
        self.assertEqual(len(p['sun']['orient']), 4)

    def test_explicit_values_override_the_preset(self):
        r = look.resolve(dict(preset='dawn', sun=dict(color=[1, 0.5, 0.2], brightness=1.5, azimuth=90, elevation=30), fog=dict(near=50, far=300, color=[0.5, 0.5, 0.6]), sky='RedDustSky'))
        self.assertEqual(r['sun']['color'], [1.0, 0.5, 0.2])
        self.assertEqual(r['fog']['near'], 50.0)
        self.assertEqual(r['sky'], 'RedDustSky')
        self.assertTrue(r['notes'])
        q = r['sun']['orient']
        self.assertAlmostEqual(sum(v * v for v in q), 1.0, places=4)

    def test_bad_values(self):
        for bad in (dict(preset='nope'), dict(sky='Nope'), dict(fog=dict(near=500, far=100)), dict(sun=dict(color=[1, 2]))):
            with self.assertRaises(core.MapgenError):
                look.resolve(bad)

    def test_look_goes_into_the_map_as_lighting(self):
        m = mapgen.expand(recipe(look=dict(preset='jungle_night')))['maps'][0]
        self.assertEqual(m['lighting']['sky'], 'Skybox_NIGHT')
        self.assertNotIn('look', m)
        self.assertNotIn('notes', m['lighting'])

    @unittest.skipUnless(os.path.isdir(GAME), 'proof game folder not on this machine')
    def test_writer_on_a_real_block(self):
        os.environ.setdefault('TODMS_CACHE', os.path.join(os.environ.get('TEMP', '.'), 'mapgen_test_cache'))
        from todms import workspace
        ws = workspace.Workspace()
        ws.set_game(GAME)
        entry = 'data_pc/overdose_the_game/overdose/shared/mainmap_map10_runawaytrain.map'
        BL = ws.block_level(entry)
        docs = {}
        for k, nm in BL.frs:
            docs[nm] = BL.doc(nm)
        lighting = look.resolve(dict(preset='dawn', fog=dict(near=40, far=250, color=[0.2, 0.3, 0.4]), screen=dict(saturation=0.8)))
        rep = look.apply_look(docs, lighting, available_skies=['RedDustSky'])
        self.assertTrue(rep['changed'], rep)
        self.assertTrue(any('sky' in s and 'Skybox_DAWN' in s for s in rep['skipped']), rep)        # Dawn's sky is not in the clone source
        # read every changed fragment back with a fresh reader
        from todct import tools as TT
        k = TT.load()
        found = dict(sun=0, fog=0, gfx=0)
        for nm in rep['changed']:
            d2 = k.fe.FragDoc(docs[nm].payload(), ws.T, nm)
            for n in d2.created_ids():
                t = d2.type_of(n) or ''
                if 'default_global_light' in t and d2.get(n, 'light_type') == 2:
                    self.assertEqual([round(v, 4) for v in d2.get(n, 'light_color_rgb')], [round(v, 4) for v in lighting['sun']['color']])
                    self.assertEqual([round(v, 4) for v in d2.get(n, 'orient')], [round(v, 4) for v in lighting['sun']['orient']])
                    found['sun'] += 1
                elif 'FOG_Controller' in t:
                    self.assertEqual((d2.get(n, 'start'), d2.get(n, 'end')), (40.0, 250.0))
                    found['fog'] += 1
                elif 'default_GFX' in t:
                    self.assertAlmostEqual(d2.get(n, 'default_saturation'), 0.8, places=5)
                    found['gfx'] += 1
        self.assertEqual(found, dict(sun=1, fog=1, gfx=1))
        again = look.apply_look({nm: BL.doc(nm) for nm in rep['changed']}, lighting, available_skies=['RedDustSky'])
        self.assertEqual(again['changed'], [])                                                    # nothing left to change


class Builder(unittest.TestCase):
    def test_plug_builds_a_real_model_record(self):
        paths.setup_tools()
        from todct import tools as TT
        k = TT.load()
        p = recipe(terrain=dict(size=[12, 12], cell=2.0, chunk=12, strokes=[dict(tool='raise', pos=[0, 0], radius=10, strength=2)]),
                   roads=[dict(id='r', points=[[-10, 0], [10, 0]], width=6)], scatter=[dict(id='s', rect=[-10, -10, 10, 10], density=0.02, items=[dict(kind='tree')])])
        res = mapgen.expand_full(p)
        ng = res['params']['maps'][0]['new_geometry']
        import newgeo
        from types import SimpleNamespace
        tex = {t['name']: dict(name='/data/Models/Map11_Test/textures/%s.bmp' % t['name']) for t in ng['textures']}
        models = newgeo.make_models(ng['models'], 'Map11_Test', tex, k.mw, k.tm, [])
        self.assertEqual(len(models), len(ng['models']))
        mg = sum(m['triangles'] for m in models if not m['short'].startswith('S_'))
        self.assertEqual(mg, res['stats']['Map11_Test']['triangles'])               # the builder counted what mapgen reported
        ground_m = [m for m in models if m['short'].startswith('G_')][0]
        self.assertEqual(ground_m['triangles'], 12 * 12 * 2)
        self.assertGreater(ground_m['hulls'], 0)
        self.assertLessEqual(ground_m['bytes'], 2796216)
        tree = [m for m in models if '_tree_' in m['short']][0]
        self.assertGreater(tree['hulls'], 0)

    def test_plug_is_the_only_way_in(self):
        paths.setup_tools()
        from todct import tools as TT
        k = TT.load()
        mapgen.install_builder_plug()
        geoplug.uninstall()
        import newgeo
        tex = dict(T=dict(name='/data/Models/x/textures/T.bmp'))
        try:
            with self.assertRaises(Exception) as cm:
                newgeo.make_models([dict(name='M', parts=[dict(type='mapgen', meshes=[], hulls=None)])], 'x', tex, k.mw, k.tm, [])
            self.assertIn('unknown part type', str(cm.exception))
        finally:
            geoplug.install()


class LedgerRows(unittest.TestCase):
    def test_rows_for_generated_content(self):
        res = mapgen.expand_full(recipe(terrain=dict(size=[40, 40], cell=2.0, chunk=20), ground_paint=dict(palette=['dirt', 'grass'])))
        rows = {r['id']: r for r in ledger.mapgen_rows(res['stats'])}
        self.assertEqual(set(rows), {'M1', 'P6', 'L15', 'L15_index', 'L1', 'G1', 'G2', 'G3'})
        self.assertEqual(rows['G1']['used'], 2)
        self.assertEqual(rows['G2']['used'], 40 * 40 * 2)
        self.assertEqual(rows['G1']['status'], 'ok')
        self.assertEqual(rows['G3']['max'], 2000)
        over = ledger.mapgen_rows({'x': dict(map='x', ground_triangles=500000, ground_materials=3)})
        self.assertEqual({r['id']: r['status'] for r in over}['G2'], 'red')

    def test_problems_list_carries_the_notes_and_red_meters(self):
        res = mapgen.expand_full(recipe(roads=[dict(id='cliff', points=[[0, 0, 0], [10, 0, 6], [20, 0, 12]], elevated=True)]))
        rows = problems.from_mapgen(res)
        self.assertTrue(any(r['source'] == 'mapgen' and 'too steep' in r['title'] for r in rows))
        self.assertTrue(all(r['level'] in ('warn', 'error') and r['jump'] for r in rows))
        big = problems.from_mapgen(dict(notes=[], stats={'x': dict(map='x', ground_triangles=500000)}))
        self.assertTrue(any('Ground triangles per section' in r['title'] and r['level'] == 'warn' for r in big))

    def test_new_limit_rows_exist(self):
        for lid in ('G1', 'G2', 'G3'):
            r = limits.get(lid)
            self.assertTrue(r['confidence'].startswith('INFERRED'))
            self.assertEqual(limits.enforce(lid), 'warn')


if __name__ == '__main__':
    unittest.main()
