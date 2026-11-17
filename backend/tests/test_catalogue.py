"""The asset catalogue: the category rules (one table), the row filter, the rows and where-used API on a small synthetic census,
and the detail of a real model on the proof copy (skipped when the proof game is absent).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
PROOF = os.environ.get('TODMS_PROOF', '/no-proof-copy')
HAVE_GAME = os.path.isdir(os.path.join(PROOF, 'game'))

BLOCK = 'data_pc/overdose_the_game/overdose/shared/'
M9 = BLOCK + 'mainmap_map09_jungle.map'
S9 = BLOCK + 'submap01_map09_jungle_temple.submap'
MS = BLOCK + 'mm092_escapejungle.mission'


def row(path, **kw):
    from todct import assets
    d = dict(key=assets.stem_key(path), path=path, name=path.split('/')[-1][:-6], kind='static', maps={}, uses=0, size=[1, 1, 1],
             collision='none', collision_shapes=0, triangles=100, pivots=1, sections={}, blocks=['a.map'])
    d.update(kw)
    return d


CENSUS = dict(kind='todct-asset-census', version=2, built='t', seconds=1, maps=['map09_jungle', 'map02_lostoros_downtown'], rows={
    r['key']: r for r in [
        row('/data/characters/ram/ram.model', kind='skeletal', size=[0.9, 1.8, 0.4], triangles=4000, pivots=50),
        row('/data/models/vehicles/pickuptruck/vehicle.model', size=[2.6, 2.1, 6.4], triangles=4600, maps={'map09_jungle': 3},
            uses=3, sections={M9: 1, S9: 2}),
        row('/data/models/addons/vegetation/plants/veg_bush_flower_red.model', size=[0.8, 0.7, 0.8], triangles=40,
            maps={'map09_jungle': 20, 'map02_lostoros_downtown': 5}, uses=25, sections={S9: 20, BLOCK + 'mainmap_map02_lostoros_downtown.map': 5}),
        row('/data/models/addons/commercialsigns/sign_botica.model', size=[2, 1, 0.1], triangles=12, maps={'map02_lostoros_downtown': 9}, uses=9),
        row('/data/models/map09_jungle/terrain/chunks/chunk_03/textured/bui_mayatemple.model', size=[60, 30, 60], triangles=24000),
    ]})
INDEX = dict(version=2, game='', textures={'/t/a.bmp': dict(name='/t/a.bmp', w=128, h=64, fmt='DXT1', size=5000, users=['x'], hd=[], blocks=['a'])},
             models={'/data/models/vehicles/pickuptruck/vehicle.model': dict(name='x', textures=['/t/a.bmp', '/t/a.bmp'], blocks=['a'], hd=[])})


class FakeWs:
    catalog = dict(maps=[dict(id='map09', title='Map09 Jungle', map_block=M9, sections=[dict(entry=S9, title='Section 01 Temple')],
                              missions=[dict(entry=MS, title='Escape')]),
                         dict(id='map02', title='Map02 Downtown', map_block=BLOCK + 'mainmap_map02_lostoros_downtown.map', sections=[], missions=[])])


class TestCategoryRules(unittest.TestCase):
    def cat(self, p):
        from todct import modelcat
        return modelcat.category(p)

    def test_known_models(self):
        c = self.cat
        self.assertEqual(c('/data/characters/ram/ram.model'), 'characters')
        self.assertEqual(c('/data/animals/chicken/chicken.model'), 'animals')
        self.assertEqual(c('/data/models/vehicles/pickuptruck/vehicle.model'), 'vehicles')
        self.assertEqual(c('/data/models/vehicles/pickup4x4/vehicle.model'), 'vehicles')         # "pickup" in the path is not a pickup item
        self.assertEqual(c('/data/models/collectables/goodies/pickup_oneshot_armour.model'), 'pickups')
        self.assertEqual(c('/data/models/collectables/weapons/weapon_gun_light/weapon_gun_light.model'), 'weapons')
        self.assertEqual(c('/data/models/addons/vegetation/trees/veg_tree_scruffy_large.model'), 'vegetation')
        self.assertEqual(c('/data/models/map09_jungle/terrain/terrainandroads/ter_chunk_01.model'), 'terrain')
        self.assertEqual(c('/data/textures/skybox/sky/cloudsky/skybox.model'), 'terrain')
        self.assertEqual(c('/data/models/addons/commercialsigns/sign_botica.model'), 'signs')
        self.assertEqual(c('/data/models/map09_jungle/terrain/chunks/chunk_03/textured/bui_mayatemple.model'), 'buildings')
        self.assertEqual(c('/data/models/addons/shippingcrates/shippingcrate_wood_small.model'), 'crates')
        self.assertEqual(c('/data/models/addons/havocobjects/explosivebarrels/red_barrel.model'), 'destructibles')
        self.assertEqual(c('/data/models/addons/doorsglobal/chainlinkdoor/chainlinkdoor.model'), 'doors')
        self.assertEqual(c('/data/models/addons/office/add_officedesk_big.model'), 'interior')
        self.assertEqual(c('/data/models/addons/hydrant/add_hydrant.model'), 'street')
        self.assertEqual(c('/data/models/props/effect/cone_marker_red_small.model'), 'effects')

    def test_word_traps(self):
        c = self.cat
        self.assertEqual(c('/data/models/map03_lostoros_industrial/addons/junkyardaddons/crushedcarpile_01.model'), 'crates')      # "shed" inside "crushed"
        self.assertNotEqual(c('/data/models/map03_lostoros_industrial/addons/junkyardaddons/crushedcarpile_01.model'), 'buildings')
        self.assertEqual(c('/data/models/addons/surroundgeometry/trash/trash_soda_red.model'), 'props')                              # litter is not a plant

    def test_every_path_gets_one_known_category(self):
        from todct import modelcat as MC
        ids = {i for i, _, _ in MC.RULES}
        for p in ('/data/x.model', '', '\\data\\Models\\Addons\\Zzz\\Q.model', 'models/addons/unknown/thing'):
            self.assertIn(MC.category(p), ids)
        self.assertEqual(MC.category('/DATA/Characters/Ram/Ram.MODEL'), 'characters')            # case does not matter

    def test_table_has_unique_ids_and_labels(self):
        from todct import modelcat as MC
        t = MC.table()
        self.assertEqual(len({x['id'] for x in t}), len(t))
        self.assertTrue(all(x['label'] for x in t))
        self.assertEqual(t[-1]['id'], 'props')                                                   # the catch-all is last
        self.assertEqual(MC.FALLBACK, 'props')

    def test_labels_and_area(self):
        from todct import modelcat as MC
        self.assertEqual(MC.label('/data/models/vehicles/sedan_modernstandard/vehicle.model'), 'Sedan Modernstandard')
        self.assertEqual(MC.label('/data/models/addons/hydrant/add_hydrant.model'), 'Hydrant')
        self.assertEqual(MC.area('/data/models/addons/map09_jungle/templeelevator/templeelvator.model'), 'map09_jungle')
        self.assertEqual(MC.area('/data/models/addons/hydrant/add_hydrant.model'), '')

    def test_census_models_all_land_somewhere(self):
        """Against the real census of the proof copy, when it has been built: no model without a category, no category swallowing most."""
        p = os.path.join(PROOF, 'cache', 'assets', 'asset_census.json')
        if not os.path.exists(p):
            self.skipTest('no census')
        from todct import modelcat as MC
        rows = json.load(open(p, encoding='utf-8'))['rows']
        n = {}
        for r in rows.values():
            n[MC.category(r['path'])] = n.get(MC.category(r['path']), 0) + 1
        self.assertEqual(sum(n.values()), len(rows))
        self.assertLess(max(n.values()), len(rows) * 0.25)
        for need in ('characters', 'vehicles', 'weapons', 'pickups', 'vegetation', 'buildings', 'props'):
            self.assertGreater(n.get(need, 0), 0, need)


class TestRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.tmp, 'home'), TODMS_CACHE=os.path.join(self.tmp, 'cache'))
        self.env.start()
        from todms import catalogue
        self.C = catalogue
        catalogue._MEMO.clear()
        from todms import assetindex
        assetindex._CACHE.clear()
        d = os.path.join(self.tmp, 'cache', 'assets')
        os.makedirs(d)
        json.dump(CENSUS, open(os.path.join(d, 'asset_census.json'), 'w'))
        json.dump(INDEX, open(os.path.join(d, 'asset_index.json'), 'w'))

    def tearDown(self):
        self.env.stop()
        self.C._MEMO.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def keys(self, q):
        return [r['name'] for r in self.C.rows(FakeWs(), q)['rows']]

    def test_not_ready_without_a_census(self):
        os.remove(os.path.join(self.tmp, 'cache', 'assets', 'asset_census.json'))
        self.C._MEMO.clear()
        r = self.C.rows(FakeWs(), {})
        self.assertFalse(r['ready'])
        self.assertEqual(r['rows'], [])
        self.assertTrue(r['cats'])

    def test_old_census_needs_a_rescan(self):
        p = os.path.join(self.tmp, 'cache', 'assets', 'asset_census.json')
        d = json.load(open(p))
        d['version'] = 1
        json.dump(d, open(p, 'w'))
        self.C._MEMO.clear()
        self.assertFalse(self.C.rows(FakeWs(), {})['ready'])

    def test_all_rows_and_category_counts(self):
        r = self.C.rows(FakeWs(), {})
        self.assertTrue(r['ready'])
        self.assertEqual((r['count'], r['total']), (5, 5))
        cnt = {c['id']: c['count'] for c in r['cats']}
        self.assertEqual(cnt['vehicles'], 1)
        self.assertEqual(cnt['characters'], 1)
        self.assertEqual(sum(cnt.values()), 5)
        self.assertEqual(r['rows'][0]['name'], 'Bush Flower Red')            # most placed first
        self.assertEqual(r['rows'][0]['path'], '/data/models/addons/vegetation/plants/veg_bush_flower_red.model')

    def test_category_filter_keeps_other_counts(self):
        r = self.C.rows(FakeWs(), {'cat': 'vehicles'})
        self.assertEqual([x['name'] for x in r['rows']], ['Pickuptruck'])
        self.assertEqual({c['id']: c['count'] for c in r['cats']}['vegetation'], 1)          # counts ignore the chosen category

    def test_map_and_min_uses(self):
        self.assertEqual(sorted(self.keys({'map': 'map02_lostoros_downtown'})), ['Bush Flower Red', 'Sign Botica'])
        self.assertEqual(self.keys({'map': 'map02_lostoros_downtown', 'min_uses': 6}), ['Sign Botica'])
        self.assertEqual(self.keys({'min_uses': 10}), ['Bush Flower Red'])
        self.assertEqual(sorted(self.keys({'unused': True})), ['Bui Mayatemple', 'Ram'])

    def test_size_bands_and_triangles(self):
        self.assertEqual(self.keys({'band': 'huge'}), ['Bui Mayatemple'])
        self.assertEqual(sorted(self.keys({'band': 'small'})), ['Bush Flower Red', 'Ram'])
        self.assertEqual(sorted(self.keys({'size_min': 2, 'size_max': 8})), ['Pickuptruck', 'Sign Botica'])
        self.assertEqual(self.keys({'tris_min': 4000, 'tris_max': 5000, 'sort': 'tris'}), ['Pickuptruck', 'Ram'])
        self.assertEqual(self.keys({'tris_max': 50, 'sort': 'tris'}), ['Bush Flower Red', 'Sign Botica'])

    def test_text_search_and_kind(self):
        self.assertEqual(self.keys({'q': 'flower red'}), ['Bush Flower Red'])
        self.assertEqual(self.keys({'q': 'plants/veg'}), ['Bush Flower Red'])            # the path counts too
        self.assertEqual(self.keys({'kind': 'skeletal'}), ['Ram'])
        self.assertEqual(self.keys({'q': 'zzzz'}), [])

    def test_sorting(self):
        self.assertEqual(self.keys({'sort': 'name'})[0], 'Bui Mayatemple')
        self.assertEqual(self.keys({'sort': 'size'})[0], 'Bui Mayatemple')
        self.assertEqual(self.keys({'sort': 'textures'})[0], 'Pickuptruck')                   # the only one with a texture list

    def test_textures_counted_once(self):
        r = {x['name']: x for x in self.C.rows(FakeWs(), {})['rows']}
        self.assertEqual(r['Pickuptruck']['tex'], 1)                                          # the same texture listed twice
        self.assertIsNone(r['Ram']['tex'])                                                    # not in the index

    def test_where_used(self):
        doc = self.C.table()
        w = self.C.where_used(FakeWs(), doc['by_key']['data_models_addons_vegetation_plants_veg_bush_flower_red'])
        self.assertEqual([(x['map'], x['kind'], x['count']) for x in w], [('map09', 'section', 20), ('map02', 'map', 5)])
        self.assertEqual(w[0]['section'], S9)
        self.assertIsNone(w[1]['section'])
        w = self.C.where_used(FakeWs(), doc['by_key']['data_models_vehicles_pickuptruck_vehicle'])
        self.assertEqual([(x['kind'], x['count']) for x in w], [('section', 2), ('map', 1)])
        self.assertEqual(self.C.where_used(FakeWs(), doc['by_key']['data_characters_ram_ram']), [])

    def test_unknown_block_still_listed(self):
        w = self.C.where_used(FakeWs(), dict(sections={BLOCK + 'weird.submap': 4}))
        self.assertEqual(w[0]['kind'], 'block')
        self.assertIsNone(w[0]['map'])

    def test_cards_are_kept_and_reported(self):
        key = 'data_models_vehicles_pickuptruck_vehicle'
        png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=='
        self.assertTrue(self.C.save_card(key, png)['ok'])
        self.assertTrue(next(x for x in self.C.rows(FakeWs(), {})['rows'] if x['key'] == key)['card'])
        with self.assertRaises(KeyError):
            self.C.save_card('nope', png)
        with self.assertRaises(ValueError):
            self.C.save_card(key, 'data:text/html;base64,AAAA')
        with self.assertRaises(ValueError):
            self.C.save_card(key, 'data:image/png;base64,' + 'AAAA' * 10)                   # not a PNG


@unittest.skipUnless(HAVE_GAME, 'proof game not available')
class TestDetailOnTheGame(unittest.TestCase):
    """One small prop through the real extraction: its glb, textures and where-used, built in a private cache."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.env = patch.dict(os.environ, TODMS_HOME=os.path.join(cls.tmp, 'home'), TODMS_CACHE=os.path.join(cls.tmp, 'cache'))
        cls.env.start()
        from todms import paths, workspace, catalogue
        paths.setup_tools()
        cls.C = catalogue
        catalogue._MEMO.clear()
        cls.ws = workspace.Workspace()
        cls.ws.set_game(os.path.join(PROOF, 'game'))
        d = os.path.join(cls.tmp, 'cache', 'assets')
        os.makedirs(d, exist_ok=True)
        c = json.load(open(os.path.join(PROOF, 'cache', 'assets', 'asset_census.json'), encoding='utf-8'))
        c['version'] = 2
        key = 'data_models_addons_weaponammocrate_weaponammocratewoodopen'
        c['rows'][key]['sections'] = {}
        json.dump(c, open(os.path.join(d, 'asset_census.json'), 'w'))
        cls.key = key

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.C._MEMO.clear()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detail_has_mesh_textures_and_pivots(self):
        d = self.C.detail(self.ws, self.key)
        self.assertEqual(d['cat'], 'crates')
        self.assertTrue(d['rec']['url'].endswith('.glb'))
        self.assertGreater(d['rec']['tris'], 10)
        self.assertEqual(d['textures'], [])                         # no asset index in this private cache: the list is empty, not an error
        self.assertGreaterEqual(len(d['pivots']), 1)
        for p in d['pivots']:
            self.assertEqual(len(p['pos']), 3)
        f = os.path.join(self.tmp, 'cache', *d['rec']['url'][len('/cache/'):].split('/'))
        self.assertTrue(os.path.exists(f))
        raw = open(f, 'rb').read(12)
        self.assertEqual(raw[:4], b'glTF')

    def test_unknown_key(self):
        with self.assertRaises(KeyError):
            self.C.detail(self.ws, 'data_nothing')

    def test_clips_of_the_player(self):
        from todms import clips
        row = self.C.row_of(self.ws, 'data_characters_ram_ram')
        a = clips.available(self.ws, row)
        self.assertTrue(a['rigged'])
        self.assertGreater(len(a['clips']), 300)                         # the whole humanoid set fits the player
        run = next(c for c in a['clips'] if c['name'] == 'ram_run')
        self.assertTrue(run['own'])
        self.assertTrue(run['loop'])
        self.assertGreater(run['frames'], 10)
        self.assertAlmostEqual(run['seconds'], run['frames'] / 25.0, places=1)
        self.assertTrue(a['clips'][0]['own'])                            # his own clips come first
        c = clips.clip(self.ws, row, 'ram_run')
        n = len(c['rot'])
        self.assertEqual(n, 50)
        self.assertEqual(len(c['pos']), n)
        moving = [r for r, st in zip(c['rot'], c['rot_static']) if r and not st]
        self.assertGreater(len(moving), 20)
        self.assertEqual(len(moving[0]), 4 * c['frames'])
        for q in zip(*[iter(moving[0])] * 4):                             # unit quaternions (x, y, z, w)
            self.assertAlmostEqual(sum(v * v for v in q), 1.0, places=2)
        with self.assertRaises(KeyError):
            clips.clip(self.ws, row, 'no_such_clip')

    def test_skin_of_the_player(self):
        from todms import clips
        s = clips.skin(self.ws, self.C.row_of(self.ws, 'data_characters_ram_ram'))
        self.assertEqual(len(s['pivots']), 50)
        names = {p['name'] for p in s['pivots']}
        self.assertTrue({'Pelvis', 'Head', 'L Thigh', 'R Forearm'} <= names)
        for p in s['pivots']:
            self.assertTrue(-1 <= p['parent'] < 50)
        self.assertEqual(len(s['meshes']), 4)
        for m in s['meshes']:
            nv = len(m['pos']) // 3
            self.assertEqual(len(m['nrm']), nv * 3)
            self.assertEqual(len(m['uv']), nv * 2)
            self.assertTrue(m['skinned'])
            self.assertEqual(len(m['joints']), nv * 4)
            self.assertLess(max(m['idx']), nv)
            self.assertLess(max(m['joints']), 50)
            self.assertEqual(len(m['idx']) % 3, 0)

    def test_things_without_a_rig_have_no_clips(self):
        from todms import clips
        a = clips.available(self.ws, self.C.row_of(self.ws, self.key))
        self.assertEqual(a, dict(clips=[], rigged=False))
        a = clips.available(self.ws, self.C.row_of(self.ws, 'data_animals_chicken_chicken'))
        self.assertTrue(a['rigged'])
        self.assertGreaterEqual(len([c for c in a['clips'] if c['own']]), 10)               # the chicken's own clips

    def test_fits_rule(self):
        from todms import clips
        names = ['pelvis', 'spine', 'head', 'l thigh', 'r thigh']
        self.assertTrue(clips.fits(dict(chans=['Pelvis', 'Spine', 'Head', 'L Thigh', 'R Thigh', 'Extra']), names))
        self.assertFalse(clips.fits(dict(chans=['Pelvis', 'Spine']), names))
        self.assertFalse(clips.fits(dict(chans=['Pelvis']), []))


if __name__ == '__main__':
    unittest.main()
