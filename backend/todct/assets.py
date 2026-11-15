"""Asset replacement manager core: the table that maps each TOD model to an Unreal asset.

Identity is the bridge's (TODBridgeLink TodbAssetTable): the STEM KEY of the model's resource path,
  "data_" + path without "/data", without ".model", "/" -> "_", lower case
  (/data/Models/Addons/AirVents/AirVent_Doubble.model -> data_models_addons_airvents_airvent_doubble),
optionally "<stem>#ts<N>" for a character drawn with texture set N and "<stem>#p<N>" for the mesh of pivot N (MC's
per-pivot import). The bridge resolves a drawn model through Config/TODBridge/asset_table.json (the imported
originals), asset_overrides.json (replacements, which win) and asset_overrides_todhd.json (the TOD HD agent's rows,
which win over both; this module only reads that file). This module never changes asset_table.json; it MERGES assignments into asset_overrides.json (rows it does
not own, comments and extra fields such as "note" are kept) and keeps the manager's own state (markers, notes) in
Config/TODBridge/asset_manager.json.

Files:
  asset_census.json      per TOD model: maps and placement counts, kind, render size, collision kind (built from
                         the game's blocks by `census`, cached)
  asset_manager.json     {"kind": "todct-asset-manager", "rows": {stem: {"marker": "visual_only"|"needs_collision"|"",
                          "note": ""}}}
  asset_candidates.json  THE HOOK for a later matcher (vector search): {"kind": "todct-asset-candidates", "version": 1,
                          "generated_by": "...", "rows": {stem: [{"ue": "/Game/...", "score": 0..1, "source": "...",
                          "note": "..."}]}}. The manager shows them per row and can accept the best ones in bulk.
                          `name_candidates` writes a simple one (name tokens + size) so the hook is exercised now.
"""
import collections
import json
import math
import os
import re
import struct
import time
import zlib

import numpy as np

from . import tools

MARKERS = ('', 'visual_only', 'needs_collision')
MARKER_TEXT = {'': '', 'visual_only': 'visual only (game collision stays)',
               'needs_collision': 'needs collision change (run the collision generator)'}


def stem_key(path):
    """TodbAssetTable stem key (TODBridgeLinkModule.cpp AssetStemKey)."""
    p = (path or '').replace('\\', '/').lower()
    if p.startswith('/data/'):
        p = p[5:]
    elif p.startswith('data/'):
        p = p[4:]
    if not p.startswith('/'):
        p = '/' + p
    p = p[1:]
    if p.endswith('.model'):
        p = p[:-6]
    return 'data_' + p.replace('/', '_')


# ---------------------------------------------------------------------------------------------- JSON files
def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + '.part'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=2)
        f.write('\n')
    os.replace(tmp, path)


class Config:
    """The bridge config folder (Unreal project Config/TODBridge) or any copy of it."""

    def __init__(self, folder):
        self.folder = folder
        self.table_path = os.path.join(folder, 'asset_table.json')
        self.overrides_path = os.path.join(folder, 'asset_overrides.json')
        self.state_path = os.path.join(folder, 'asset_manager.json')
        self.candidates_path = os.path.join(folder, 'asset_candidates.json')
        self.census_path = os.path.join(folder, 'asset_census.json')
        self.todhd_path = os.path.join(folder, 'asset_overrides_todhd.json')

    def table(self):
        return _load(self.table_path, {}).get('assets', {})

    def overrides_doc(self):
        return _load(self.overrides_path, {'comment': 'HD replacements: key = stem key of the TOD asset (data_ + path '
                                           'without .model, \'/\' -> \'_\', lower case), value = the UE asset. Entries '
                                           'here win over asset_table.json.', 'assets': {}})

    def todhd(self):
        return _load(self.todhd_path, {}).get('assets', {})

    def state(self):
        return _load(self.state_path, {'kind': 'todct-asset-manager', 'version': 1, 'rows': {}})

    def candidates(self):
        return _load(self.candidates_path, {'kind': 'todct-asset-candidates', 'version': 1, 'rows': {}})

    def census(self):
        return _load(self.census_path, None)


# ---------------------------------------------------------------------------------------------- census
def model_summary(K, info, R, E):
    """Kind, render AABB size (model space, metres) and collision kind of one MODEL record."""
    m = K.tm.decode(info, R, E)
    spec = K.mw.spec_from_model(m)
    skinned = any(me['kind'] == 'skin' for P in spec['pivots'] for me in P['meshes'])
    PW = K.mw.pivot_world(spec['pivots'])
    pts = []
    tris = 0
    for i, P in enumerate(spec['pivots']):
        for me in P['meshes']:
            V = K.mw.vertex_positions(me)
            pts += [K.mw.apply(PW[i], v) for v in V[::max(1, len(V) // 400)]]
            tris += len(me['indices']) // 3 if me['prim'] == 'list' else max(0, len(me['indices']) - 2)
    if pts:
        A = np.asarray(pts)
        mn, mx = A.min(0), A.max(0)
    else:
        mn = mx = np.zeros(3)
    coll = 'hulls' if m['hulls'] else ('pivot' if any(P['coll'] for P in m['pivots']) else 'none')
    nshapes = (len(m['hulls']['shapes']) if m['hulls'] else 0) + sum(len(P['coll']['shapes']) for P in m['pivots'] if P['coll'])
    return dict(kind='skeletal' if skinned else 'static', size=(mx - mn).round(3).tolist(), min=mn.round(3).tolist(),
                max=mx.round(3).tolist(), triangles=int(tris), collision=coll, collision_shapes=nshapes,
                pivots=len(spec['pivots']))


def census(read, names, progress=None):
    """Every model record of the shared map/submap/mission blocks and overdose.main: where it is, how often each map
    places it. names: archive entry names; read(entry) -> raw. Returns the census dict (JSON)."""
    from . import collision as CO
    K = tools.load()
    rows = {}
    maps = set()
    for n in names:
        if '/shared/' in n.lower() and n.lower().endswith(('.map', '.submap')):
            try:
                maps.add(CO.map_key_of(n))
            except CO.CollisionError:
                pass                                  # startmap.map and other non-level blocks
    maps = sorted(maps)
    blocks = [n for n in names if '/shared/' in n.lower() and n.lower().endswith(('.map', '.submap', '.mission', '.main'))
              and not n.lower().split('/')[-1].startswith(('mainmenu',))]
    t0 = time.time()
    for bi, e in enumerate(sorted(blocks)):
        if progress:
            progress('models of %s' % e.split('/')[-1], bi, len(blocks))
        raw = read(e)
        b = K.tb.Block(raw, os.path.splitext(e)[1])
        info = bytes(b.info)
        starts = K.tb.record_starts(info, b.n)
        ends = starts[1:] + [len(info)]
        for k, R in enumerate(starts):
            if K.tb.u32(info, R) != 3:
                continue
            nm = K.tb.record_name(info, R)
            key = stem_key(nm)
            r = rows.get(key)
            if r is None:
                try:
                    s = model_summary(K, info, R, ends[k])
                except Exception as ex:          # noqa: BLE001  (an unreadable record still gets a row)
                    s = dict(kind='static', size=[0, 0, 0], error=str(ex))
                r = rows[key] = dict(key=key, path=nm, name=nm.replace('\\', '/').split('/')[-1].rsplit('.', 1)[0],
                                     blocks=[], maps={}, uses=0, **s)
            r['blocks'].append(e.split('/')[-1])
    for mi, mk in enumerate(maps):
        if progress:
            progress('placements in %s' % mk, mi, len(maps))
        ents = CO.map_entries(names, mk)
        ctx = CO.MapContext(mk, ents, read)
        for nm, pls in ctx.placements.items():
            key = stem_key(nm)
            n = sum(p[3] for p in pls)
            if key not in rows or n == 0:
                continue
            rows[key]['maps'][mk] = rows[key]['maps'].get(mk, 0) + n
            rows[key]['uses'] += n
    return dict(kind='todct-asset-census', version=1, built=time.strftime('%Y-%m-%d %H:%M:%S'), seconds=round(time.time() - t0, 1),
                maps=maps, rows=rows)


# ---------------------------------------------------------------------------------------------- the table
def rows(cfg, census_doc=None):
    """Merged manager rows (JSON-able), sorted by uses."""
    cen = census_doc or cfg.census() or dict(rows={}, maps=[])
    table = cfg.table()
    ov = cfg.overrides_doc().get('assets', {})
    hd = cfg.todhd()
    st = cfg.state().get('rows', {})
    cand = cfg.candidates().get('rows', {})
    keys = set(cen['rows']) | {k.split('#')[0] for k in table} | {k.split('#')[0] for k in ov} | {k.split('#')[0] for k in hd}
    out = []
    for k in keys:
        c = cen['rows'].get(k, {})
        t = table.get(k, {})
        o = ov.get(k, {})
        s = st.get(k, {})
        out.append(dict(key=k, name=c.get('name') or (t.get('path') or o.get('path') or k).split('/')[-1].replace('.model', ''),
                        path=c.get('path') or t.get('path') or o.get('path'), kind=c.get('kind') or t.get('kind') or o.get('kind') or 'static',
                        maps=c.get('maps', {}), uses=c.get('uses', 0), size=c.get('size'), collision=c.get('collision'),
                        collision_shapes=c.get('collision_shapes'), triangles=c.get('triangles'),
                        ue_original=t.get('ue'), ue_assigned=o.get('ue'), assigned_note=o.get('note'),
                        assigned_by=o.get('assigned_by'), ue_hd=(hd.get(k) or {}).get('ue'),
                        ue_effective=(hd.get(k) or {}).get('ue') or o.get('ue') or t.get('ue'),
                        marker=s.get('marker', o.get('collision', '')), note=s.get('note', ''),
                        candidates=cand.get(k, []),
                        variants=sorted(set(x for x in list(table) + list(ov) + list(hd) if x.startswith(k + '#')))))
    out.sort(key=lambda r: (-r['uses'], r['name'].lower()))
    return out


def filter_rows(rs, map_key=None, min_uses=0, text='', only=None):
    """only: None | 'assigned' | 'unassigned' | 'visual_only' | 'needs_collision' | 'imported' | 'with_candidates'."""
    t = (text or '').lower()
    out = []
    for r in rs:
        if map_key and not r['maps'].get(map_key):
            continue
        if (r['maps'].get(map_key, 0) if map_key else r['uses']) < (min_uses or 0):
            continue
        if t and t not in (r['name'] + ' ' + (r['path'] or '') + ' ' + (r['ue_assigned'] or '')).lower():
            continue
        if only == 'todhd' and not r.get('ue_hd'):
            continue
        if only == 'assigned' and not r['ue_assigned']:
            continue
        if only == 'unassigned' and r['ue_assigned']:
            continue
        if only in ('visual_only', 'needs_collision') and r['marker'] != only:
            continue
        if only == 'imported' and not r['ue_original']:
            continue
        if only == 'with_candidates' and not r['candidates']:
            continue
        out.append(r)
    return out


def suggest_marker(tod_size, ue_size_m, tol_rel=0.12, tol_abs=0.3):
    """'visual_only' when the replacement's bounds match the TOD model's within 12 % / 0.3 m per axis (the game's
    collision still fits it), else 'needs_collision'. Sizes in metres, TOD axes (x, y up, z)."""
    if not tod_size or not ue_size_m:
        return ''
    for a, b in zip(tod_size, ue_size_m):
        if abs(a - b) > max(tol_abs, tol_rel * max(abs(a), abs(b))):
            return 'needs_collision'
    return 'visual_only'


def ue_size_to_tod(size_cm):
    """UE bounds box size (cm, X Y Z) -> TOD axes metres (x, y up, z): (X, Z, Y) / 100."""
    return [size_cm[0] / 100.0, size_cm[2] / 100.0, size_cm[1] / 100.0]


def assign(cfg, assignments, by='asset manager'):
    """assignments: [{"key", "ue" (None/'' = clear), "kind" (static|skeletal), "path", "marker", "note",
    "ue_size_cm"}]. Merges into asset_overrides.json (other rows untouched) and asset_manager.json. Returns a report."""
    doc = cfg.overrides_doc()
    ov = doc.setdefault('assets', {})
    st = cfg.state()
    srows = st.setdefault('rows', {})
    cen = (cfg.census() or {}).get('rows', {})
    changed, cleared, marked = [], [], []
    for a in assignments:
        k = a['key']
        if not re.match(r'^data_[a-z0-9_./-]+(#(ts|p)\d+)?$', k):
            raise ValueError('not a stem key: %r' % k)
        if 'ue' in a:
            if a['ue']:
                if not a['ue'].startswith('/'):
                    raise ValueError('%s: UE asset path must start with / (got %r)' % (k, a['ue']))
                row = dict(ov.get(k, {}))
                row.update(ue=a['ue'], kind=a.get('kind') or row.get('kind') or (cen.get(k.split('#')[0], {}).get('kind')) or 'static',
                           path=a.get('path') or row.get('path') or re.sub(r'^/data(?=/)', '', cen.get(k.split('#')[0], {}).get('path') or '', flags=re.I) or None)
                if row['path'] is None:
                    row.pop('path')
                row['assigned_by'] = by
                if a.get('ue_size_cm') and cen.get(k, {}).get('size'):
                    row['suggested'] = suggest_marker(cen[k]['size'], ue_size_to_tod(a['ue_size_cm']))
                    if 'marker' not in a and not srows.get(k, {}).get('marker'):
                        a = dict(a, marker=row['suggested'])          # the size check sets the first marker
                ov[k] = row
                changed.append(k)
            elif k in ov and ov[k].get('assigned_by'):
                del ov[k]                         # only rows this manager made are removed; hand-made rows stay
                cleared.append(k)
        if 'marker' in a or 'note' in a:
            s = srows.setdefault(k, {})
            if 'marker' in a:
                if a['marker'] not in MARKERS:
                    raise ValueError('%s: marker %r (one of %s)' % (k, a['marker'], MARKERS))
                s['marker'] = a['marker']
                if k in ov:
                    if a['marker']:
                        ov[k]['collision'] = a['marker']
                    else:
                        ov[k].pop('collision', None)
                marked.append(k)
            if 'note' in a:
                s['note'] = a['note']
    _save(cfg.overrides_path, doc)
    _save(cfg.state_path, st)
    return dict(assigned=changed, cleared=cleared, marked=marked, overrides=len(ov), file=cfg.overrides_path)


def accept_candidates(cfg, keys, min_score=0.0):
    cand = cfg.candidates().get('rows', {})
    a = []
    for k in keys:
        c = sorted(cand.get(k, []), key=lambda x: -x.get('score', 0))
        if c and c[0].get('score', 0) >= min_score:
            a.append(dict(key=k, ue=c[0]['ue'], kind=c[0].get('kind'), ue_size_cm=c[0].get('size_cm')))
    return assign(cfg, a, by='candidate (%s)' % ((cfg.candidates().get('generated_by')) or 'matcher'))


# ---------------------------------------------------------------------------------------------- candidates hook
STOP = {'sm', 'mesh', 'model', 'models', 'static', 'staticmeshes', 'textured', 'veg', 'bui', 'ter', 'data', 'addons',
        'game', 'jungle', 'vegetation', 'downtown', 'lostoros', 'industrial', 'harbour', 'farm', 'hacienda', 'props'}


def tokens(s):
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s or '')
    return {t for t in re.split(r'[^a-z0-9]+', s.lower()) if len(t) > 1 and not t.isdigit() and not re.match(r'^map\d+$', t)} - STOP


def name_candidates(cfg, ue_assets, rows_=None, top=5, exclude_roots=('/Game/K/',), min_score=0.2):
    """The built-in matcher (fills the hook until the vector search exists): ue_assets = [{"ue": path, "name": .,
    "size_cm": [x,y,z], "kind": "static"}] (the editor scans its asset registry). Score = name-token overlap
    (Jaccard) * 0.7 + size similarity * 0.3. Writes asset_candidates.json; returns the doc."""
    rs = rows_ or rows(cfg)
    pool = [u for u in ue_assets if not any(u['ue'].startswith(r) for r in exclude_roots)]
    ptok = [(u, tokens(u.get('name') or u['ue'].split('/')[-1].split('.')[0])) for u in pool]
    out = {}
    for r in rs:
        tt = tokens(r['name']) | tokens((r['path'] or '').replace('/', ' '))
        if not tt:
            continue
        sc = []
        for u, ut in ptok:
            if not ut or u.get('kind', 'static') != r['kind']:
                continue
            j = len(tt & ut) / len(tt | ut)
            if j <= 0:
                continue
            size = 0.0
            if r.get('size') and u.get('size_cm'):
                a = np.asarray(r['size']) + 0.1
                b = np.asarray(ue_size_to_tod(u['size_cm'])) + 0.1
                size = float(np.exp(-np.mean(np.abs(np.log(a / b)))))
            sc.append(dict(ue=u['ue'], score=round(0.7 * j + 0.3 * size, 4), source='name-match',
                           kind=u.get('kind', 'static'), size_cm=u.get('size_cm'),
                           note='tokens %s' % sorted(tt & ut)))
        sc = [x for x in sc if x['score'] >= min_score]
        sc.sort(key=lambda x: -x['score'])
        if sc:
            out[r['key']] = sc[:top]
    doc = dict(kind='todct-asset-candidates', version=1, generated_by='todct name-match', generated=time.strftime('%Y-%m-%d %H:%M:%S'),
               pool=len(pool), rows=out)
    _save(cfg.candidates_path, doc)
    return doc


# ---------------------------------------------------------------------------------------------- thumbnails
def png_bytes(rgb):
    """rgb (h, w, 3) uint8 -> PNG (no PIL: the packaged Mod Studio has none)."""
    h, w, _ = rgb.shape
    raw = b''.join(b'\x00' + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')


def model_triangles(K, info, R, E):
    m = K.tm.decode(info, R, E)
    spec = K.mw.spec_from_model(m)
    PW = K.mw.pivot_world(spec['pivots'])
    Vs, Fs, base = [], [], 0
    for i, P in enumerate(spec['pivots']):
        for me in P['meshes']:
            if me['smb_flags'] & 1:                  # the second, lower-detail copy (LOD1) of a mesh
                continue
            V = [K.mw.apply(PW[i], v) for v in K.mw.vertex_positions(me)]
            idx = me['indices']
            if me['prim'] == 'list':
                T = [idx[j:j + 3] for j in range(0, len(idx) - 2, 3)]
            else:
                T = [(idx[j], idx[j + 1], idx[j + 2]) if j % 2 == 0 else (idx[j + 1], idx[j], idx[j + 2]) for j in range(len(idx) - 2)]
            T = [t for t in T if len(set(t)) == 3]
            Vs += V
            Fs += [[a + base, b + base, c + base] for a, b, c in T]
            base += len(V)
    return np.asarray(Vs, dtype=np.float64).reshape(-1, 3), Fs


def render_thumb(V, F, size=128, colour=(0.78, 0.74, 0.66)):
    """Software z-buffer render, 3/4 view from the front-left above, Lambert shading. -> (size, size, 3) uint8."""
    img = np.full((size, size, 3), 40, dtype=np.uint8)
    if len(F) == 0:
        return img
    V = np.asarray(V, dtype=np.float64)
    c = (V.min(0) + V.max(0)) / 2
    yaw, pitch = math.radians(35), math.radians(25)
    Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    P = (V - c) @ (Rx @ Ry).T
    P[:, 2] *= -1                                  # TOD left-handed: look along +z
    ext = max(np.ptp(P[:, 0]), np.ptp(P[:, 1]), 1e-3)
    s = (size * 0.86) / ext
    X = P[:, 0] * s + size / 2
    Y = size / 2 - P[:, 1] * s
    Z = P[:, 2]
    zb = np.full((size, size), np.inf)
    light = np.array([0.4, 0.8, -0.45])
    light /= np.linalg.norm(light)
    F = np.asarray(F, dtype=np.int64)
    a, b, cc = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    N = np.cross(b - a, cc - a)
    ln = np.linalg.norm(N, axis=1)
    ok = ln > 0
    N[ok] /= ln[ok][:, None]
    shade = 0.35 + 0.65 * np.abs(N @ light)
    order = np.argsort(-np.maximum(np.maximum(Z[F[:, 0]], Z[F[:, 1]]), Z[F[:, 2]]))
    col = np.asarray(colour)
    for t in order[:60000]:
        i, j, k = F[t]
        x0, y0, x1, y1, x2, y2 = X[i], Y[i], X[j], Y[j], X[k], Y[k]
        mnx, mxx = int(max(0, math.floor(min(x0, x1, x2)))), int(min(size - 1, math.ceil(max(x0, x1, x2))))
        mny, mxy = int(max(0, math.floor(min(y0, y1, y2)))), int(min(size - 1, math.ceil(max(y0, y1, y2))))
        if mnx > mxx or mny > mxy:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(mnx, mxx + 1) + 0.5, np.arange(mny, mxy + 1) + 0.5)
        w0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / den
        w1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / den
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m.any():
            continue
        z = w0 * Z[i] + w1 * Z[j] + w2 * Z[k]
        sub = zb[mny:mxy + 1, mnx:mxx + 1]
        m &= z < sub
        sub[m] = z[m]
        img[mny:mxy + 1, mnx:mxx + 1][m] = (col * shade[t] * 255).clip(0, 255).astype(np.uint8)
    return img


def thumbnail(read, block_entry, model_path, out_png, size=128):
    """Render one TOD model (from the block that holds its record) to a PNG; cached by file."""
    if os.path.exists(out_png):
        return out_png
    K = tools.load()
    raw = read(block_entry)
    b = K.tb.Block(raw, os.path.splitext(block_entry)[1])
    info = bytes(b.info)
    starts = K.tb.record_starts(info, b.n)
    ends = starts[1:] + [len(info)]
    k = K.me.find_model(info, starts, model_path)
    V, F = model_triangles(K, info, starts[k], ends[k])
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with open(out_png + '.part', 'wb') as f:
        f.write(png_bytes(render_thumb(V, F, size)))
    os.replace(out_png + '.part', out_png)
    return out_png
