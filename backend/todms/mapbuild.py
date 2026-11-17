"""mapbuild: what the in-map building tools of the New maps screen ask the backend for (wave 3, worker build).

Everything here is pure (no game, no UI) except `kits`, which reads the asset catalogue. The tools keep their recipe keys in the new-map
recipe exactly as `todms.mapgen` documents them; this module only
  * evaluates one map cheaply for the live view (`field` = the height / paint / surface grids, `preview` = the generated geometry as
    raw arrays plus the numbers, notes and meter rows), cached by the hash of the map's own recipe keys;
  * reads and writes heightmap files;
  * plans sections (`plan_stats`, `simulate`): the per-section numbers, a walk / drive path and the loader check;
  * feeds the ledger and Problems for a new-map project (`rows_for`, `problems_for`, called from ledger.compute / problems.collect).
"""
import base64
import copy
import hashlib
import json
import math

from . import mapgen
from .mapgen import core, terrain, paint
from .mapgen.core import np, Out, MapgenError, Heights
from .mapgen.meshkit import Mesh, read_part

# keys of a map that change the generated result (everything else is ignored by the cache)
KEYS = ('name', 'terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'look', 'blockout')
SURFACES = list(core.MATERIALS)

# a rough guess for the load time (UNPROVEN: no measurement of the game's streaming exists): fixed cost plus a rate per megabyte
LOAD_BASE_S, LOAD_MB_PER_S = 0.8, 25.0
BYTES_PER_TRI, BYTES_PER_INSTANCE = 40.0, 600.0


def _b64(a, dtype):
    return base64.b64encode(np.ascontiguousarray(np.asarray(a, dtype=dtype)).tobytes()).decode('ascii')


def _key(m, extra=''):
    sub = {k: m.get(k) for k in KEYS if m.get(k) is not None}
    return hashlib.sha1((json.dumps(sub, sort_keys=True, default=str) + extra).encode()).hexdigest()


_CACHE = {}


def _cached(key, fn):
    if key in _CACHE:
        return _CACHE[key]
    v = fn()
    if len(_CACHE) > 12:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = v
    return v


# ------------------------------------------------------------------------------------------------ blockout (idea 40)
# the boxes are part of the generators now (todms.mapgen.blockout); this name is kept for callers of the older module
blockout_geometry = mapgen.blockout_mod.geometry


# ------------------------------------------------------------------------------------------------ the live field
def field(m):
    """The height, paint and surface grids of one map as the builder will see them (no meshes). -> dict, packed arrays are base64."""
    def run():
        out = Out(m.get('name') or 'map')
        H = terrain.build(m.get('terrain'), out)
        if H.h is None:
            return dict(terrain=None)
        pal, tex, surf = paint.build(H, m.get('ground_paint'), out)
        return dict(terrain=dict(origin=[H.ox, H.oz], cell=H.cell, nx=H.nx, nz=H.nz, heights=_b64(H.h, '<f4'), paint=_b64(tex, 'u1'), surface=_b64(surf, 'u1'),
                                 min=float(H.h.min()), max=float(H.h.max())),
                    palette=[dict(id=p['id'], kind=p['kind'], surface=p['surface'], surf=int(p['surf'])) for p in pal], surfaces=SURFACES)
    return _cached(_key(m, 'field'), run)


# ------------------------------------------------------------------------------------------------ the preview
def _rock_mesh(p):
    """The faceted boulder of the geometry kit (same recipe as geomkit.add_rock) as a Mesh, for the preview only."""
    rng = np.random.default_rng(int(p.get('seed', 1)))
    t = (1 + 5 ** 0.5) / 2
    V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2),
         (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    V = [np.array(v, dtype=float) / np.linalg.norm(v) for v in V]
    k = {}

    def mid(a, b):
        key = (min(a, b), max(a, b))
        if key not in k:
            m = V[a] + V[b]
            V.append(m / np.linalg.norm(m))
            k[key] = len(V) - 1
        return k[key]
    F2 = []
    for a, b, c in F:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        F2 += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    V = np.array(V) * (0.80 + 0.30 * rng.random(len(V)))[:, None] * np.array([1.0, p.get('squash', 0.7), 1.0]) * p['radius'] + np.array(p['center'], dtype=float)
    m = Mesh()
    for a, b, c in F2:
        m.add(p['tex'], [V[a], V[b], V[c]], [(0, 1, 0)] * 3, [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)])
    return m


def _mesh_arrays(model):
    out = []
    for part in model['parts']:
        if part.get('type') == 'mapgen':
            meshes, _ = read_part(part)
        elif part.get('type') == 'box':                                           # parts of the geometry kit (scatter trees, rocks, bushes, blockout)
            m = Mesh()
            m.box(part['tex'], part['min'], part['max'], part.get('uv', 0.25), collide=False)
            meshes, _ = read_part(m.part())
        elif part.get('type') == 'rock':
            meshes, _ = read_part(_rock_mesh(part).part())
        else:
            continue
        for me in meshes:
            out.append(dict(tex=me['tex'], P=_b64(me['P'], '<f4'), I=_b64(me['I'], '<u4'), n=int(len(me['P']))))
    return out


def _hull_lines(model, cap=400):
    """Collision pieces as edge lists (for the debug overlay): [[x, y, z, x, y, z], ...] in model space."""
    segs = []
    for part in model['parts']:
        if part.get('type') != 'mapgen':
            continue
        _, hulls = read_part(part)
        for pts, _, _ in hulls[:cap]:
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            x0, y0, z0 = lo
            x1, y1, z1 = hi
            for a, b in (((x0, y0, z0), (x1, y0, z0)), ((x0, y0, z1), (x1, y0, z1)), ((x0, y1, z0), (x1, y1, z0)), ((x0, y1, z1), (x1, y1, z1)),
                         ((x0, y0, z0), (x0, y0, z1)), ((x1, y0, z0), (x1, y0, z1)), ((x0, y1, z0), (x0, y1, z1)), ((x1, y1, z0), (x1, y1, z1)),
                         ((x0, y0, z0), (x0, y1, z0)), ((x1, y0, z0), (x1, y1, z0)), ((x0, y0, z1), (x0, y1, z1)), ((x1, y0, z1), (x1, y1, z1))):
                segs.append([round(float(v), 2) for v in (*a, *b)])
    return segs


def preview(m, ground=False, collision=False):
    """Expand one map and return what the view draws: the generated models as raw triangle arrays (the ground chunks only when
    `ground`, the client draws the height grid itself), the numbers, the notes and the meter rows."""
    def run():
        mm, stats, notes = mapgen._expand_map(copy.deepcopy(m))
        ng = mm.get('new_geometry') or {}
        models = {}
        for md in ng.get('models') or []:
            if md['name'].startswith('G_') and not ground:
                continue
            models[md['name']] = dict(meshes=_mesh_arrays(md), hulls=_hull_lines(md) if collision else [])
        res = dict(models=models, placements=[p for p in ng.get('placements') or [] if p['model'] in models],
                   shipped=mm.get('shipped_models') or [], walls=mm.get('walls') or [], triggers=mm.get('triggers') or [],
                   teleports=mm.get('teleports') or [], traffic=mm.get('traffic_routes') or [], lighting=mm.get('lighting'),
                   textures=[dict(name=t['name'], kind=t['kind'], size=t['size'], format=t['format']) for t in ng.get('textures') or []],
                   stats=_slim(stats), notes=notes, rows=rows_from_stats({stats.get('map') or m.get('name') or 'map': stats}, mm))
        return res
    return _cached(_key(m, 'preview%d%d' % (bool(ground), bool(collision))), run)


def _slim(stats):
    s = dict(stats)
    s.pop('chunks', None)
    s.pop('texture_list', None)
    s['chunk_count'] = len(stats.get('chunks') or [])
    s['texture_names'] = [t['name'] for t in stats.get('texture_list') or []]
    s['texture_bytes'] = sum(t['payload'] for t in stats.get('texture_list') or [])
    return s


# ------------------------------------------------------------------------------------------------ meters
def rows_from_stats(stats, mm=None):
    """G1-G3 (mapgen_rows) and the two quadtree rows of the expanded map(s), as ledger rows."""
    from . import ledger
    rows = [r for r in ledger.mapgen_rows(stats) if r['id'] in ('G1', 'G2', 'G3')]
    params = dict(maps=[mm] if mm else [])
    secs = ledger._section_rows(params) if mm else []
    for lid, key in (('Q_main', 'main'), ('Q_aux', 'aux')):
        row = ledger._row_base(lid)
        if not secs:
            rows.append(ledger._fill(row, None, reason='no new map yet'))
            continue
        w = max(secs, key=lambda s: s[key])
        rows.append(ledger._fill(row, round(w[key]), dict(vanilla=0, packages=0, project=round(w[key])),
                                 [dict(label=s['label'], used=round(s[key])) for s in secs], mode='estimate'))
    return rows


def _has_keys(params):
    return any(k in m for m in (params or {}).get('maps', []) for k in KEYS[1:])


def expanded(params):
    """The expanded copy of a project for the meters (None when no map has a generator key or the recipe does not expand yet)."""
    if not _has_keys(params):
        return None
    try:
        key = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
        return _cached('x' + key, lambda: mapgen.expand_full(params))
    except Exception:                                                            # noqa: BLE001  (a half-made recipe is not a crash)
        return None


def rows_for(params):
    """Ledger rows for a new-map project: G1-G3 plus the quadtree rows measured from the EXPANDED recipe. [] when nothing to add."""
    res = expanded(params)
    if not res:
        return []
    return _rows_for_expanded(res)


def _rows_for_expanded(res):
    from . import ledger
    rows = [r for r in ledger.mapgen_rows(res['stats']) if r['id'] in ('G1', 'G2', 'G3')]
    secs = ledger._section_rows(res['params'])
    for lid, key in (('Q_main', 'main'), ('Q_aux', 'aux')):
        if not secs:
            continue
        row = ledger._row_base(lid)
        items = sorted((dict(label=s['label'], used=round(s[key]), jump=dict(screen='newmaps')) for s in secs), key=lambda x: -x['used'])
        rows.append(ledger._fill(row, items[0]['used'], dict(vanilla=0, packages=0, project=items[0]['used']), items, mode='estimate'))
    return rows


def plan_notes(m):
    """What the section planner of one map finds (plain sentences): a section near the quadtree limit, a loader that joins nothing,
    ground no section covers, spots of the walk that are not loaded. The plan is editor data (the builder writes one block per map),
    so these are advice, not build errors."""
    sp = m.get('sections_plan') or {}
    secs = sp.get('sections') or []
    if not secs:
        return []
    out = []
    ids = {x['id'] for x in secs}
    for L in sp.get('loaders') or []:
        if L.get('a') not in ids or L.get('b') not in ids:
            out.append('Planned loader %s joins a section that is not in the plan.' % L.get('id'))
    try:
        sim = simulate(m, secs, sp.get('loaders') or [], sp.get('path') or [])
    except Exception:                                                  # noqa: BLE001
        return out
    for x in secs:
        st = (sim.get('stats') or {}).get(x['id']) or {}
        if st.get('main', 0) > 8500:
            out.append('Planned section %s is near the main quadtree limit (about %d of 10,000).' % (x.get('name') or x['id'], st['main']))
    if sim.get('flags'):
        out.append('The planned walk reaches %d spots that no loaded section covers.' % len(sim['flags']))
    if sim.get('gaps'):
        out.append('%d reachable spots lie in no planned section.' % len(sim['gaps']))
    return out


def problems_for(params):
    """The generator notes and red or amber generator meters, as Problems rows (problems.from_mapgen), plus the section plan's advice."""
    res = expanded(params)
    if not res:
        return []
    from . import problems
    rows = problems.from_mapgen(res)
    for m in (params or {}).get('maps') or []:
        for n in plan_notes(m):
            rows.append(problems._row('warn', 'sections', '%s: %s' % (m.get('name'), n), '', dict(screen='newmaps', area='map', tool='sections')))
    return rows


# ------------------------------------------------------------------------------------------------ heightmap files
def heightmap_export(m, kind='png'):
    out = Out('x')
    H = terrain.build(m.get('terrain'), out)
    if H.h is None:
        raise MapgenError('this map has no terrain yet')
    if kind == 'raw':
        return dict(data=base64.b64encode(terrain.export_raw(H.h)).decode(), nx=H.nx, nz=H.nz, cell=H.cell, origin=[H.ox, H.oz])
    png, lo, hi = terrain.export_png16(H.h)
    return dict(data=base64.b64encode(png).decode(), lo=lo, hi=hi, nx=H.nx, nz=H.nz, cell=H.cell, origin=[H.ox, H.oz])


def heightmap_import(body):
    """-> a ready `terrain` key (the strokes are dropped: the picture becomes the starting grid)."""
    data = base64.b64decode(body['data'])
    cell = float(body.get('cell', 2.0))
    origin = body.get('origin')
    if body.get('kind') == 'raw':
        h = terrain.import_raw(data, int(body['nx']), int(body['nz']))
        t = dict(cell=cell, heights=core.pack_grid(h))
        if origin:
            t['origin'] = list(origin)
        return t
    lo, hi = float(body.get('lo', 0.0)), float(body.get('hi', 20.0))
    return terrain.terrain_key_from_png(data, lo, hi, cell, origin)


# ------------------------------------------------------------------------------------------------ sections (ideas 71-73, 76, 77)
def _inside(rect, x, z):
    return rect[0] <= x <= rect[2] and rect[1] <= z <= rect[3]


def plan_stats(m, plan):
    """Numbers per planned section: {id: dict(cells, triangles, instances, materials, textures, nodes, main, aux, mb, seconds)}.
    plan = [{id, name, rect [x0, z0, x1, z1]}]. Counted from the grids and the generated placements, not a second build."""
    from . import ledger
    f = field(m)
    pv = preview(m)
    t = f.get('terrain')
    out = {}
    pal = {}
    if t:
        nx, nz, cell = t['nx'], t['nz'], t['cell']
        heights = np.frombuffer(base64.b64decode(t['heights']), dtype='<f4').reshape(nz + 1, nx + 1)
        paintg = np.frombuffer(base64.b64decode(t['paint']), dtype='u1').reshape(nz, nx)
        cx = t['origin'][0] + (np.arange(nx) + 0.5) * cell
        cz = t['origin'][1] + (np.arange(nz) + 0.5) * cell
        X, Z = np.meshgrid(cx, cz)
    pts = [(p['pos'][0], p['pos'][2]) for p in pv['placements']] + [(p['pos'][0], p['pos'][2]) for p in pv['shipped']]
    walls = [(w['pos'][0], w['pos'][2]) for w in pv['walls']]
    for sec in plan:
        r = sec['rect']
        d = dict(cells=0, triangles=0, materials=0)
        if t:
            msk = (X >= r[0]) & (X <= r[2]) & (Z >= r[1]) & (Z <= r[3])
            d['cells'] = int(msk.sum())
            d['triangles'] = int(msk.sum()) * 2
            d['materials'] = int(len(set(paintg[msk].tolist()))) if msk.any() else 0
        d['instances'] = sum(1 for p in pts if _inside(r, p[0], p[1])) + sum(1 for p in walls if _inside(r, p[0], p[1]))
        d['textures'] = d['materials']
        d['nodes'] = d['instances']
        d['main'] = round(ledger.DROPPED_POOLS[0] + d['nodes'] * ledger.NODE_MAIN)
        d['aux'] = round(ledger.DROPPED_POOLS[1] + d['nodes'] * ledger.NODE_AUX)
        mb = (d['triangles'] * BYTES_PER_TRI + d['instances'] * BYTES_PER_INSTANCE) / 1048576.0 + d['textures'] * 0.0425
        d['mb'] = round(mb, 2)
        d['seconds'] = round(LOAD_BASE_S + mb / LOAD_MB_PER_S, 1)
        out[sec['id']] = d
    return out


def _seg_cross(a, b, rect):
    """Does the 2-D segment a-b touch the rectangle? (sampled: planner paths are coarse)"""
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 2.0))
    return any(_inside(rect, a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1))


def simulate(m, plan, loaders, path, step=4.0):
    """Walk (or drive) `path` [[x, z], ...] through the planned sections and say which are loaded where.
    loaders: [{id, a, b (section ids), pos [x, y, z], size [w, h, l]}]: a loader box loads BOTH sections it joins while the path is inside it.
    -> dict(samples [{pos, section, loaded [ids]}], flags [{pos, kind, text}], gaps [[x, z]], seconds {id: s}, total_seconds)
    A flag is raised where the path stands in a section that is not loaded (it never passed that section's loader) or in no section at all.
    Ground not covered by any section (a reachable cell) is returned as `gaps` (cell centres, at most 200)."""
    secs = {s['id']: s for s in plan}
    stats = plan_stats(m, plan) if plan else {}
    boxes = {}
    for L in loaders or []:
        sx, sz = (L.get('size') or [12, 6, 2])[0] / 2.0, (L.get('size') or [12, 6, 2])[2] / 2.0
        r = max(sx, sz)
        boxes[L['id']] = (L['pos'][0] - r, L['pos'][2] - r, L['pos'][0] + r, L['pos'][2] + r)
    loaded, samples, flags = set(), [], []
    prev = None
    for p in path or []:
        pts = [p] if prev is None else [[prev[0] + (p[0] - prev[0]) * k / max(1, int(math.hypot(p[0] - prev[0], p[1] - prev[1]) / step)),
                                         prev[1] + (p[1] - prev[1]) * k / max(1, int(math.hypot(p[0] - prev[0], p[1] - prev[1]) / step))]
                                        for k in range(1, max(1, int(math.hypot(p[0] - prev[0], p[1] - prev[1]) / step)) + 1)]
        prev = p
        for q in pts:
            here = next((sid for sid, s in secs.items() if _inside(s['rect'], q[0], q[1])), None)
            for L in loaders or []:
                if _inside(boxes[L['id']], q[0], q[1]):
                    loaded |= {L.get('a'), L.get('b')} - {None}
            if here is None:
                flags.append(dict(pos=[round(q[0], 1), round(q[1], 1)], kind='nowhere', text='This spot is in no section'))
            elif here not in loaded:
                if not loaded:
                    loaded.add(here)                  # the way in: the arrival section is loaded by the entrance
                else:
                    flags.append(dict(pos=[round(q[0], 1), round(q[1], 1)], kind='unloaded', text='This ground is not loaded here', section=here))
                    loaded.add(here)                  # report once, then carry on
            samples.append(dict(pos=[round(q[0], 1), round(q[1], 1)], section=here, loaded=sorted(loaded)))
    gaps = []
    f = field(m).get('terrain')
    if f and plan:
        nx, nz, cell = f['nx'], f['nz'], f['cell']
        h = np.frombuffer(base64.b64decode(f['heights']), dtype='<f4').reshape(nz + 1, nx + 1)
        sl = np.maximum(np.abs(h[:-1, 1:] - h[:-1, :-1]), np.abs(h[1:, :-1] - h[:-1, :-1])) / cell
        for j in range(0, nz, max(1, nz // 40)):
            for i in range(0, nx, max(1, nx // 40)):
                x, z = f['origin'][0] + (i + 0.5) * cell, f['origin'][1] + (j + 0.5) * cell
                if sl[j, i] <= 0.35 and not any(_inside(s['rect'], x, z) for s in plan) and len(gaps) < 200:
                    gaps.append([round(x, 1), round(z, 1)])
    seconds = {sid: d['seconds'] for sid, d in stats.items()}
    visited = [sid for sid in dict.fromkeys(s['section'] for s in samples) if sid]
    return dict(samples=samples[:600], flags=flags[:60], gaps=gaps, seconds=seconds, total_seconds=round(sum(seconds.get(v, 0) for v in visited), 1),
                stats=stats)


# ------------------------------------------------------------------------------------------------ minimap (ideas 78-81, UI only)
def top_down(m, size=256, contrast=1.0):
    """A plain top-down render of the map (height shading + paint colours + roads) as a PNG, used when core's minimap route is not there."""
    import struct
    import zlib
    f = field(m).get('terrain')
    if not f:
        raise MapgenError('this map has no terrain yet')
    nx, nz = f['nx'], f['nz']
    h = np.frombuffer(base64.b64decode(f['heights']), dtype='<f4').reshape(nz + 1, nx + 1).astype(float)
    tex = np.frombuffer(base64.b64decode(f['paint']), dtype='u1').reshape(nz, nx)
    pal = field(m)['palette']
    COL = dict(dirt=(150, 118, 84), sand=(212, 190, 128), asphalt=(70, 72, 78), grass=(92, 140, 70), rock=(120, 120, 124))
    colors = np.array([COL.get(p['id'], COL.get(p['kind'], (140, 140, 140))) for p in pal], dtype=float)
    img = colors[tex]
    gx, gz = np.gradient(h[:-1, :-1])
    shade = np.clip(1.0 + (gx - gz) * 0.35, 0.55, 1.45)[..., None]
    img = np.clip(128 + (img * shade - 128) * float(contrast), 0, 255)
    img = img[::-1]                                                              # north up
    ys = np.minimum(img.shape[0] - 1, (np.arange(size) * img.shape[0] / size).astype(int))
    xs = np.minimum(img.shape[1] - 1, (np.arange(size) * img.shape[1] / size).astype(int))
    img = img[ys][:, xs].astype(np.uint8)
    rows = [b'\x00' + img[j].tobytes() for j in range(size)]

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows), 6))
           + chunk(b'IEND', b''))
    return dict(png=base64.b64encode(png).decode(), size=size, bounds=[f['origin'][0], f['origin'][1], f['origin'][0] + nx * f['cell'], f['origin'][1] + nz * f['cell']])


# ------------------------------------------------------------------------------------------------ look presets for the picker
def look_presets():
    from .mapgen import look
    out = []
    for pid, p in look.presets().items():
        out.append(dict(id=pid, label=p['label'], derived=p['derived'], look=json.loads(json.dumps(p['look'], default=str))))
    return dict(presets=out, skies=sorted(look.skies()))


# ------------------------------------------------------------------------------------------------ kit palettes (ideas 41-43, 114)
# kit id -> (label, maps its pieces are taken from, catalogue categories)
KITS = {'adobe': ('Adobe', ('map08', 'map06'), ('buildings', 'doors', 'props', 'vegetation')),
        'downtown': ('Downtown', ('map02',), ('buildings', 'street', 'signs', 'doors')),
        'industrial': ('Industrial', ('map03', 'map07'), ('crates', 'buildings', 'doors', 'street')),
        'hacienda': ('Hacienda', ('map08',), ('buildings', 'doors', 'interior', 'vegetation', 'props')),
        'harbour': ('Harbour', ('map04',), ('crates', 'buildings', 'street', 'doors'))}


def kits(ws, per_kit=30):
    """Kit palettes built from the shipped pieces in the asset catalogue: {ready, kits: [{id, label, pieces: [{key, name, path, tris, size, uses, cost}]}]}.
    cost = what one placed piece adds (idea 114): one node of the section plus the model's triangles (the catalogue knows them)."""
    from . import catalogue
    doc = catalogue.table(ws)
    if not doc:
        return dict(ready=False, kits=[dict(id=k, label=v[0], pieces=[]) for k, v in KITS.items()])
    keys = [str(m) for m in doc.get('maps') or []]
    out = []
    for kid, (label, maps, cats) in KITS.items():
        mkeys = [k for mp in maps for k in keys if mp in k.lower()][:len(maps)]
        pieces = []
        for r in doc['rows']:
            tris = r.get('triangles') or 0
            dim = max(r.get('size') or [0])
            if r['cat'] not in cats or not tris or tris > 6000 or not 2.0 <= dim <= 40.0 or not any((r.get('maps') or {}).get(k) for k in mkeys):
                continue
            pieces.append(dict(key=r['key'], name=r['label'], path=r['path'], tris=tris, size=r['size'], uses=sum((r.get('maps') or {}).get(k, 0) for k in mkeys),
                               cost=dict(nodes=1, triangles=tris)))
        pieces.sort(key=lambda p: (-p['uses'], p['name']))
        out.append(dict(id=kid, label=label, pieces=pieces[:per_kit]))
    return dict(ready=True, kits=out)
