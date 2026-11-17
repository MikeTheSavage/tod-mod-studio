"""Proof of the core2 writers (no game is launched): the geo sample map built with the sky and look, the triggers, the traffic routes,
the game's own ground pictures and models, then read back from the written blocks.

  python scripts/proof_core2.py GAME_FOLDER WORK_DIR [--ext]

GAME_FOLDER is only read (set TODMS_CACHE / TODMS_HOME to your own copies). --ext also builds the extension sections (carry region, nothing).
"""
import copy
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)

game, work = sys.argv[1], sys.argv[2]
EXT = '--ext' in sys.argv
os.makedirs(work, exist_ok=True)
os.environ.setdefault('TODMS_HOME', os.path.join(work, 'home'))
os.environ.setdefault('TODMS_CACHE', os.path.join(work, 'cache'))

from todms import paths, mapgen, newmap, workspace, assetindex          # noqa: E402
from todms.mapgen import terrain, core                                   # noqa: E402

paths.ensure_cpu_guard()
paths.setup_tools()
log = []


def say(*a):
    s = ' '.join(str(x) for x in a)
    log.append(s)
    print(s, flush=True)


SAMPLE = dict(
    terrain=dict(cell=2.0, size=[60, 60], noise=dict(seed=7, amp=0.7, scale=26), chunk=24, strokes=[
        dict(tool='raise', pos=[-18, -14], radius=34, strength=10.0),
        dict(tool='smooth', pos=[-18, -14], radius=36, strength=1.0, passes=2),
        dict(tool='raise', pos=[34, 30], radius=22, strength=-5.0)]),
    ground_paint=dict(palette=['dirt', 'sand', 'grass', 'rock'], default='grass', rock_slope=0.55, strokes=[
        dict(material='dirt', pos=[-18, -14], radius=14), dict(material='sand', pos=[34, 30], radius=24)]),
    roads=[dict(id='main', points=[[-58, -44], [-34, -22], [-8, -18], [12, -4], [30, -2], [58, -8]], width=8, lanes=2),
           dict(id='bridge', elevated=True, width=7, points=[[2, 58], [34, 30, 1.8], [58, 6]],
                deck=dict(thickness=0.8, wall=1.0, pillar_every=10))],
    water=[dict(id='pond', circle=[34, 30, 16], depth=2.4, rule='reset', reset=[0, 0])],
    edges=[dict(id='rim', kind='cliff', rect=[-60, -60, 60, 60], height=7.0, kill=dict(below=-30, respawn=[0, 20]))],
    scatter=[dict(id='trees', rect=[-58, -58, 58, 58], density=0.012, seed=5, slope_max=0.45, min_dist=4.0, avoid_roads=3.0,
                  items=[dict(kind='tree', weight=3), dict(kind='bush', weight=2)]),
             dict(id='rocks', rect=[-58, -58, 58, 58], density=0.004, seed=9, slope_max=0.9, items=[dict(kind='rock')]),
             dict(id='shipped', rect=[-58, -58, 58, 58], density=0.0015, seed=3, slope_max=0.5, min_dist=6.0, avoid_roads=3.0,
                  items=[dict(model='/Models/Addons/Surround/sur_rock_01.model', weight=2),
                         dict(model='/Models/Addons/Map02_LosToros_Downtown/Crates/crate_wooden.model', weight=1, solid=True, radius=0.6, height=1.2)])],
    look=dict(preset='bright_blue', sky='Skybox_DAWN', fog=dict(near=80, far=420)))


def sample_recipe(y):
    return dict(package='Core2Proof', maps=[dict(
        name='Map11_GeoGenProofs', source='map10_runawaytrain',
        arrival=dict(pos=[-50.0, y, -50.0], orient=[0, 0, 0, 1], floor='none'),
        entries=[dict(id='e1', block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66], size=[12, 6, 2],
                      parent=dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'))],
        teleports=[dict(name='SPOT_1', pos=[-48.0, y, -46.0], orient=[0, 0, 0, 1])],
        **{'return': dict(pos=[-52.0, y + 1.5, -52.0], size=[6, 6, 2], orient=[0, 0, 0, 1], target_map='MAINMAP_Map02_LosToros_Downtown',
                          target_submap='SUBMAP01_Map02_LosToros_Downtown', teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill',
                          teleport_block='overdose.main')},
        **SAMPLE)])


def ext_recipe():
    host = dict(block='submap01_map02_lostoros_downtown.submap', enter=dict(pos=[-237, 2.5, -43.66], size=[12, 6, 2]),
                leave=dict(pos=[-255, 2.5, -43.66], size=[12, 6, 2]))
    host2 = dict(block='submap01_map02_lostoros_downtown.submap', enter=dict(pos=[-237, 2.5, -70.0], size=[12, 6, 2]),
                 leave=dict(pos=[-255, 2.5, -70.0], size=[12, 6, 2]))
    return dict(package='Core2Ext', maps=[
        dict(name='Plaza', placement='extension', host=host, carry=dict(mode='region', region=[-300, -120, -150, 40]),
             walls=[dict(name='WALL_E', pos=[-231, 2.7, -43.66], size=[2, 3, 6])]),
        dict(name='Void', placement='extension', host=host2, carry=dict(mode='nothing'))])


def run(recipe, out, label):
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    pj = os.path.join(out, 'params.json')
    newmap.write(pj, recipe)
    t0 = time.time()
    rep = newmap.run_argv([pj, '--out', out], ws)
    say('%s: build %.1f s: result %s' % (label, time.time() - t0, rep.get('result')))
    for c in rep.get('checks', []):
        if c.get('result') != 'PASS':
            say('  %-5s %s %s' % (c.get('result'), c.get('check'), str(c.get('evidence', ''))[:200]))
    json.dump(rep, open(os.path.join(work, label + '_report.json'), 'w'), indent=1, default=str)
    return rep


ws = workspace.Workspace()
ws.set_game(game)
doc = assetindex.load(ws)
if not doc:
    assetindex.build(ws)
    doc = assetindex.load(ws)
H = terrain.build(SAMPLE['terrain'], core.Out('t'))
y = float(H.at(-50, -50)) + 1.5
res = mapgen.expand_full(sample_recipe(y), assets=doc)
m = res['params']['maps'][0]
say('expanded: triggers %d, traffic routes %d, shipped models %d, shipped textures %s' % (
    len(m.get('triggers') or []), len(m.get('traffic_routes') or []), len(m.get('shipped_models') or []),
    [t['name'] for t in m['new_geometry']['textures'] if t.get('shipped')]))
rep = run(res['params'], os.path.join(work, 'geo'), 'geo') if '--skipgeo' not in sys.argv else {}
man = rep.get('manifest') or {}
for mm in man.get('maps', []):
    say('look:', json.dumps(mm.get('look_report')))
    say('triggers:', [(t['id'], t['kind']) for t in mm.get('triggers', [])])
    say('traffic:', mm.get('traffic'))
if EXT:
    rep2 = run(ext_recipe(), os.path.join(work, 'ext'), 'ext')
    for s in (rep2.get('manifest') or {}).get('sections', []):
        say('section', s['name'], s['carry'], str(s.get('carried'))[:200], str(s.get('edge_view'))[:300])
with open(os.path.join(work, 'proof.log'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(log) + '\n')
