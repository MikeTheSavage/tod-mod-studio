"""Proof of the map generators (no game is launched).

  python scripts/proof_mapgen.py GAME_FOLDER WORK_DIR [--full]

Builds a small sample (a 120 x 120 m terrain with a hill, a road over it, a bridge over a pond, scatter, a sky preset), expands it
with todms.mapgen, writes the expanded recipe, the stats and the notes, renders the result to a .glb, takes three headless
screenshots of it and runs the expanded recipe through the map builder in check-only mode (and with --full: a real build into WORK_DIR).
GAME_FOLDER is only read (a private copy of the data cache and home is used: set TODMS_CACHE / TODMS_HOME to your own copies).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)

game, work = sys.argv[1], sys.argv[2]
FULL = '--full' in sys.argv
os.makedirs(work, exist_ok=True)
shots = os.path.join(work, 'shots')
os.makedirs(shots, exist_ok=True)
os.environ.setdefault('TODMS_HOME', os.path.join(work, 'home'))
os.environ.setdefault('TODMS_CACHE', os.path.join(work, 'cache'))
os.environ.setdefault('TODMS_SAVES', os.path.join(work, 'saves'))

import numpy as np                                                    # noqa: E402
from todms import paths, mapgen, newmap, workspace, assetindex        # noqa: E402
from todms.mapgen import terrain, core, texkinds                      # noqa: E402
from todms.mapgen.meshkit import read_part                            # noqa: E402

paths.ensure_cpu_guard()
paths.setup_tools()
log = []


def say(*a):
    s = ' '.join(str(x) for x in a)
    log.append(s)
    print(s, flush=True)


# ------------------------------------------------------------------------------------------------ the sample
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
             dict(id='rocks', rect=[-58, -58, 58, 58], density=0.004, seed=9, slope_max=0.9, items=[dict(kind='rock')])],
    look=dict(preset='clear_day', fog=dict(near=80, far=420)))


def sample_recipe(arrival_y):
    return dict(package='GeoProof', maps=[dict(
        name='Map11_GeoGenProofs', source='map10_runawaytrain',
        arrival=dict(pos=[-50.0, arrival_y, -50.0], orient=[0, 0, 0, 1], floor='none'),
        entry=dict(block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66],
                   parent=dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'),
                   size=[12, 6, 2], orient=[0, .70710678, 0, .70710678]),
        teleports=[dict(name='SPOT_1', pos=[-48.0, arrival_y, -46.0], orient=[0, 0, 0, 1])],
        **{'return': dict(pos=[-52.0, arrival_y + 1.5, -52.0], size=[6, 6, 2], orient=[0, 0, 0, 1], target_map='MAINMAP_Map02_LosToros_Downtown',
                          target_submap='SUBMAP01_Map02_LosToros_Downtown', teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill',
                          teleport_block='overdose.main')},
        **SAMPLE)])


# ------------------------------------------------------------------------------------------------ the picture
def build_glb(expanded, path):
    """World-space textured glb of every placed model of the expanded map (generated and kit parts)."""
    sys.path.append(os.path.join(ROOT, 'backend', 'vendor', 'newmap'))
    import geomkit as GK
    from todms.mapgen import geoplug
    from todct import modelimport
    ng = expanded['maps'][0]['new_geometry']
    texs = {t['name']: t for t in ng['textures']}
    order = list(texs)
    previews = []
    for n in order:
        t = texs[n]
        img = texkinds.render(t['kind'], min(int(t['size']), 128), t['seed'])
        previews.append(dict(preview=img, alpha='blend' if img.shape[2] == 4 else 'opaque', fmt=t['format']))
    models = {m['name']: m for m in ng['models']}
    acc = {n: dict(P=[], N=[], UV=[], tris=[], n=0) for n in order}
    for pl in ng['placements']:
        md = models[pl['model']]
        mb = GK.ModelBuilder(md['name'])
        for p in md['parts']:
            if p['type'] == 'mapgen':
                geoplug.pour(mb, p)
            elif p['type'] == 'box':
                mb.add_box(p['min'], p['max'], p['tex'], p.get('uv', 0.25), (), False)
            elif p['type'] == 'rock':
                mb.add_rock(p['center'], p['radius'], p['tex'], p.get('uv', 0.2), p.get('squash', 0.7), p.get('seed', 1), False)
        off = np.array(pl['pos'], dtype=float)
        for tex, g in mb.groups.items():
            a = acc[tex]
            a['P'].append(np.array(g.P) + off)
            a['N'].append(np.array(g.N))
            a['UV'].append(np.array(g.T))
            a['tris'].append(np.array(g.tris, dtype=np.int64) + a['n'])
            a['n'] += len(g.P)
    groups = []
    for ti, n in enumerate(order):
        a = acc[n]
        if not a['n']:
            continue
        groups.append(dict(P=np.concatenate(a['P']), N=np.concatenate(a['N']), UV=np.concatenate(a['UV']), tris=np.concatenate(a['tris']), tex=ti))
    baked = SimpleNamespace(textures=previews, groups=groups)
    data = modelimport.preview_glb(baked)
    with open(path, 'wb') as f:
        f.write(data)
    return len(data)


VIEWER = """<!doctype html><meta charset=utf-8><title>geo</title>
<style>html,body{margin:0;background:#9fc4e8;overflow:hidden}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"./three.module.js"}}</script>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from './jsm/loaders/GLTFLoader.js';
const q = new URLSearchParams(location.search);
const eye = (q.get('eye')||'0,60,-90').split(',').map(Number), tgt = (q.get('at')||'0,0,0').split(',').map(Number);
const r = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
r.setSize(innerWidth, innerHeight); document.body.appendChild(r.domElement);
const sc = new THREE.Scene(); sc.background = new THREE.Color(0x9fc4e8); sc.fog = new THREE.Fog(0x9fc4e8, 160, 420);
sc.add(new THREE.HemisphereLight(0xdfeaff, 0x6b5a45, 1.15));
const sun = new THREE.DirectionalLight(0xfff1d6, 2.2); sun.position.set(-60, 90, -40); sc.add(sun);
const cam = new THREE.PerspectiveCamera(Number(q.get('fov')||50), innerWidth/innerHeight, 0.3, 900);
// game coordinates in the page url (x, y, z) -> the glb has z negated
cam.position.set(eye[0], eye[1], -eye[2]); cam.lookAt(tgt[0], tgt[1], -tgt[2]);
new GLTFLoader().load('map.glb', g => {
  g.scene.traverse(o => { if (o.isMesh) { o.material.metalness = 0; o.material.roughness = 1; o.material.side = THREE.DoubleSide;
     if (o.material.map) { o.material.map.colorSpace = THREE.SRGBColorSpace; o.material.map.anisotropy = 4; } } });
  sc.add(g.scene); r.render(sc, cam); document.title = 'ready';
}, undefined, e => { document.title = 'error ' + e; });
</script>"""


def shoot(port, name, eye, at, size=(1600, 960), fov=50):
    out = os.path.join(shots, name + '.png')
    if os.path.exists(out):
        os.remove(out)
    url = 'http://127.0.0.1:%d/index.html?eye=%s&at=%s&fov=%d' % (port, ','.join(str(v) for v in eye), ','.join(str(v) for v in at), fov)
    cmd = [r'C:\Program Files\Google\Chrome\Application\chrome.exe', '--headless=new', '--disable-gpu', '--hide-scrollbars',
           '--window-size=%d,%d' % size, '--virtual-time-budget=12000', '--user-data-dir=' + os.path.join(work, 'chr'),
           '--screenshot=' + out, url]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    ok = os.path.exists(out) and os.path.getsize(out) > 2000
    say('shot', out, 'ok' if ok else 'MISSING')
    return out


def screenshots(glb):
    page = os.path.join(work, 'page')
    os.makedirs(os.path.join(page, 'jsm', 'loaders'), exist_ok=True)
    os.makedirs(os.path.join(page, 'jsm', 'utils'), exist_ok=True)
    nm = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend', 'node_modules', 'three')
    shutil.copy(os.path.join(nm, 'build', 'three.module.js'), page)
    shutil.copy(os.path.join(nm, 'examples', 'jsm', 'loaders', 'GLTFLoader.js'), os.path.join(page, 'jsm', 'loaders'))
    shutil.copy(os.path.join(nm, 'examples', 'jsm', 'utils', 'BufferGeometryUtils.js'), os.path.join(page, 'jsm', 'utils'))
    shutil.copy(glb, os.path.join(page, 'map.glb'))
    with open(os.path.join(page, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(VIEWER)

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=page, **k)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        shoot(port, 'geo_overview', (-95, 70, -120), (0, 0, 0))
        shoot(port, 'geo_bridge', (46, 14, 62), (30, 3, 24), fov=60)
        shoot(port, 'geo_road_hill', (-70, 22, -30), (-10, 4, -15), fov=60)
        shoot(port, 'geo_overview_small', (-95, 70, -120), (0, 0, 0), size=(1100, 700))
    finally:
        srv.shutdown()


# ------------------------------------------------------------------------------------------------ run
ws = workspace.Workspace()
ws.set_game(game)
doc = assetindex.load(ws)
if not doc:
    assetindex.build(ws)
    doc = assetindex.load(ws)
H = terrain.build(SAMPLE['terrain'], core.Out('t'))
ay = float(H.at(-50, -50)) + 1.5
recipe = sample_recipe(ay)
recipe['maps'][0]['blockout'] = [        # a cut-out fence and a see-through pane next to the arrival, for the alpha flags and the shadows
    dict(id='fence', pos=[-44.0, float(H.at(-44, -52)), -52.0], size=[10.0, 2.0, 0.12], yaw=0, material='fence'),
    dict(id='glass', pos=[-45.0, float(H.at(-45, -44)), -44.0], size=[4.0, 2.4, 0.08], yaw=0, material='glass'),
    dict(id='wall', pos=[-52.0, float(H.at(-52, -40)), -40.0], size=[1.0, 3.0, 6.0], yaw=0)]
t0 = time.time()
res = mapgen.expand_full(recipe, assets=doc)
say('expand %.2f s' % (time.time() - t0))
again = mapgen.dumps(mapgen.expand(recipe, assets=doc))
say('deterministic:', again == mapgen.dumps(res['params']), 'bytes', len(again))
st = res['stats']['Map11_GeoGenProofs']
with open(os.path.join(work, 'expanded.json'), 'w', encoding='utf-8') as f:
    json.dump(res['params'], f, indent=1)
with open(os.path.join(work, 'stats.json'), 'w', encoding='utf-8') as f:
    json.dump(st, f, indent=1)
with open(os.path.join(work, 'notes.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(res['notes']) + '\n')
say('stats: triangles %d (ground %d), vertices %d, textures %d, collision pieces %d, instances %d, nodes %d' % (
    st['triangles'], st['ground_triangles'], st['vertices'], st['textures'], st['collision_pieces'], st['instances'], st['nodes_added']))
say('largest sub-mesh %d vertices, largest hull %d vertices, largest texture %d bytes, steep ground %.1f%%' % (
    st['max_submesh_vertices'], st['max_hull_vertices'], st['largest_texture'], st['steep_percent']))
for c in st['chunks']:
    say('  chunk %-10s cells %s tris %5d verts %5d submeshes %d hulls %4d' % (c['model'], c['cells'], c['triangles'], c['vertices'], c['submeshes'], c['hulls']))
for r in st['roads']:
    say('  road', r['id'], 'length', r['length'], 'max slope %.0f%%' % (r['max_slope'] * 100), 'hulls', r['hulls'], 'elevated', r['elevated'])
for w in st['water']:
    say('  water', w)
for e in st['edges']:
    say('  edge', e)
for s in st['scatter']:
    say('  scatter', s)
for n in res['notes']:
    say('note:', n)
rows = __import__('todms.ledger', fromlist=['x']).mapgen_rows(res['stats'])
for r in rows:
    say('  ledger %-9s used %-8s of %-8s %s' % (r['id'], r['used'], r['max'], r['status']))

glb = os.path.join(work, 'map.glb')
say('glb bytes', build_glb(res['params'], glb))
screenshots(glb)

# ------------------------------------------------------------------------------------------------ the builder
out = os.path.join(work, 'check')
shutil.rmtree(out, ignore_errors=True)
os.makedirs(out)
pj = os.path.join(out, 'params.json')
newmap.write(pj, res['params'])
t0 = time.time()
rep = newmap.run_argv([pj, '--out', out, '--check-only'], ws)
say('builder check-only %.1f s: result %s' % (time.time() - t0, rep.get('result')))
for c in rep.get('checks', []):
    say('  %-5s %s %s' % (c.get('result'), c.get('check'), str(c.get('evidence', ''))[:140]))
json.dump(rep, open(os.path.join(work, 'check_report.json'), 'w'), indent=1, default=str)
if FULL:
    out2 = os.path.join(work, 'build')
    shutil.rmtree(out2, ignore_errors=True)
    os.makedirs(out2)
    pj2 = os.path.join(out2, 'params.json')
    newmap.write(pj2, res['params'])
    t0 = time.time()
    rep2 = newmap.run_argv([pj2, '--out', out2], ws)
    say('builder full build %.1f s: result %s' % (time.time() - t0, rep2.get('result')))
    for c in rep2.get('checks', []):
        say('  %-5s %s %s' % (c.get('result'), c.get('check'), str(c.get('evidence', ''))[:160]))
    json.dump(rep2, open(os.path.join(work, 'build_report.json'), 'w'), indent=1, default=str)
    for g in rep2.get('geometry') or []:
        bk = dict(g.get('bake') or {})
        bk.pop('nodes', None)
        say('bake:', json.dumps(bk, default=str)[:600])
with open(os.path.join(work, 'proof.log'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(log) + '\n')
