"""Writes backend/data/world_bounds.json: for every shipped map block and section, the box its objects lie in and a coarse occupancy grid.
The atlas draws these as stand-ins for the shipped maps (no meshes). Read-only on the game; the cache and home copies come from TODMS_CACHE / TODMS_HOME.

  python -I scripts/world_bounds.py GAME_FOLDER
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)
from todms import paths, workspace   # noqa: E402

paths.ensure_cpu_guard()
paths.setup_tools()
ws = workspace.Workspace()
ws.set_game(sys.argv[1])
CELL = 40.0
out = {}
for m in ws.catalog['maps']:
    for kind, entry, title in [('map', m['map_block'], m['title'])] + [('section', s['entry'], s['title']) for s in m['sections']]:
        L = ws.level_json(entry)
        pts = [e['pos'] for e in L['entities'] if e.get('pos') and e.get('cat') != 'logic' and all(abs(c) < 5000 for c in e['pos']) and (abs(e['pos'][0]) > 1e-3 or abs(e['pos'][2]) > 1e-3)]
        if len(pts) < 5:
            pts = [e['pos'] for e in L['entities'] if e.get('pos') and all(abs(c) < 5000 for c in e['pos']) and (abs(e['pos'][0]) > 1e-3 or abs(e['pos'][2]) > 1e-3)]
        if not pts:
            continue
        xs = sorted(p[0] for p in pts)
        zs = sorted(p[2] for p in pts)
        lo, hi = int(len(pts) * 0.01), max(int(len(pts) * 0.99) - 1, 0)
        box = [round(xs[lo]), round(zs[lo]), round(xs[hi]), round(zs[hi])]
        cells = {}
        for p in pts:
            if box[0] <= p[0] <= box[2] and box[1] <= p[2] <= box[3]:
                k = (int((p[0] - box[0]) // CELL), int((p[2] - box[1]) // CELL))
                cells[k] = cells.get(k, 0) + 1
        out[entry.split('/')[-1].lower()] = dict(map=m['id'], kind=kind, title=title, box=box, cell=CELL, n=len(pts),
                                                 cells=[[k[0], k[1], v] for k, v in sorted(cells.items())])
        print(entry.split('/')[-1], box, len(cells), flush=True)
dest = os.path.join(ROOT, 'backend', 'data', 'world_bounds.json')
json.dump(out, open(dest, 'w'), separators=(',', ':'))
print('wrote', dest, os.path.getsize(dest))
