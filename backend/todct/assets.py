"""Model catalogue core: every TOD model of the player's game with the maps that place it, use counts, render size,
game collision and a thumbnail drawn from the game's own mesh.

Identity is the STEM KEY of the model's resource path,
  "data_" + path without "/data", without ".model", "/" -> "_", lower case
  (/data/Models/Addons/AirVents/AirVent_Doubble.model -> data_models_addons_airvents_airvent_doubble).

Files (in the cache folder):
  asset_census.json      per TOD model: maps and placement counts, kind, render size, collision kind (built from
                         the game's blocks by `census`, cached)
"""
import json
import math
import os
import struct
import time
import zlib

import numpy as np

from . import tools


def stem_key(path):
    """The stem key of a model path."""
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
    """The cache folder that holds the census."""

    def __init__(self, folder):
        self.folder = folder
        self.census_path = os.path.join(folder, 'asset_census.json')

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
            sec = rows[key].setdefault('sections', {})
            for p in pls:
                sec[p[0]] = sec.get(p[0], 0) + p[3]
    return dict(kind='todct-asset-census', version=2, built=time.strftime('%Y-%m-%d %H:%M:%S'), seconds=round(time.time() - t0, 1),
                maps=maps, rows=rows)


# ---------------------------------------------------------------------------------------------- the table
def rows(cfg, census_doc=None):
    """Catalogue rows (JSON-able), sorted by uses."""
    cen = census_doc or cfg.census() or dict(rows={}, maps=[])
    out = []
    for k, c in cen['rows'].items():
        out.append(dict(key=k, name=c.get('name') or k, path=c.get('path'), kind=c.get('kind') or 'static',
                        maps=c.get('maps', {}), uses=c.get('uses', 0), size=c.get('size'), collision=c.get('collision'),
                        collision_shapes=c.get('collision_shapes'), triangles=c.get('triangles'), pivots=c.get('pivots'),
                        sections=c.get('sections', {}), blocks=c.get('blocks', [])))
    out.sort(key=lambda r: (-r['uses'], r['name'].lower()))
    return out


def filter_rows(rs, map_key=None, min_uses=0, text=''):
    t = (text or '').lower()
    out = []
    for r in rs:
        if map_key and not r['maps'].get(map_key):
            continue
        if (r['maps'].get(map_key, 0) if map_key else r['uses']) < (min_uses or 0):
            continue
        if t and t not in (r['name'] + ' ' + (r['path'] or '')).lower():
            continue
        out.append(r)
    return out


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
