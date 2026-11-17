"""Water: a basin carved into the terrain, a translucent plane at the water level, and a rule for falling in.

Recipe key `water` (a list):
  {"id": "pond", "polygon": [[x, z], ...] | "rect": [x0, z0, x1, z1] | "circle": [x, z, r],
   "level": null,            water surface height; null = the lowest ground under the area plus `depth` (a fresh basin)
   "depth": 2.0,             how far the bottom of the basin lies below the surface
   "bank": 5.0,              metres over which the basin blends into the terrain
   "rule": "reset" | "kill" | "none",
   "reset": "SPOT" | [x, z] | null,       where `reset` puts the player (null = just outside the shore)
   "cell": 2.0,             size of the quads of the water plane
   "opaque": false}          true: dark, nearly opaque open water (a sea over empty space) instead of the see-through pond picture
The game has no water system and no swimming: the plane is a see-through picture, `reset` is a teleport trigger over the water, and
`kill` is the shipped behaviour of a mission that fails when the player falls in (it only acts while such a mission runs).
"""
import math

from .core import np, MapgenError, polygon_of, smoothstep, in_polygon
from .meshkit import Mesh
from . import ground as G


def _dist_to_polygon(X, Z, poly):
    best = np.full(X.shape, np.inf)
    n = len(poly)
    for i in range(n):
        a = np.array(poly[i], dtype=float)
        b = np.array(poly[(i + 1) % n], dtype=float)
        d = b - a
        L2 = float(d @ d)
        t = np.clip(((X - a[0]) * d[0] + (Z - a[1]) * d[1]) / max(L2, 1e-12), 0.0, 1.0)
        best = np.minimum(best, np.hypot(X - (a[0] + t * d[0]), Z - (a[1] + t * d[1])))
    return best


def carve(w, k, H, out):
    """Dig the basin into the height grid and fix the level. Returns the resolved description of the water body."""
    wid = str(w.get('id') or 'water%d' % (k + 1))
    poly = polygon_of(w, 'water %s' % wid)
    depth = float(w.get('depth', 2.0))
    bank = max(float(w.get('bank', 5.0)), 0.5)
    level = w.get('level')
    if H.h is not None:
        X, Z = H.mesh()
        inside = in_polygon(X, Z, poly)
        if level is None:
            level = float(H.h[inside].min()) + depth if inside.any() else float(H.h.mean())
        level = float(level)
        dist = _dist_to_polygon(X, Z, poly)
        deep = level - depth * smoothstep(dist / bank)
        shore = level + 0.5 * (1.0 - smoothstep(dist / bank))
        h = H.h
        H.h = np.where(inside, np.minimum(h, deep), np.where(dist <= bank, np.maximum(h, shore), h))
    else:
        level = float(level if level is not None else H.flat)
    return dict(id=wid, poly=poly, level=level, depth=depth, bank=bank, spec=w)


def build(res, H, out, tex_for):
    """The water plane model and the rule trigger(s) of a carved body."""
    from .edges import _spot
    wid, poly, level, w = res['id'], res['poly'], res['level'], res['spec']
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    cell = float(w.get('cell', 2.0))
    x0, x1 = min(xs) - 2.0, max(xs) + 2.0
    z0, z1 = min(zs) - 2.0, max(zs) + 2.0
    nx = max(1, int(math.ceil((x1 - x0) / cell)))
    nz = max(1, int(math.ceil((z1 - z0) / cell)))
    gx = x0 + np.arange(nx + 1) * cell
    gz = z0 + np.arange(nz + 1) * cell
    GX, GZ = np.meshgrid(gx, gz)
    near = _dist_to_polygon(GX, GZ, poly) <= 1.5
    pin = in_polygon(GX, GZ, poly)
    keep = near | pin
    cc = (keep[:-1, :-1] | keep[:-1, 1:] | keep[1:, :-1] | keep[1:, 1:])
    cc &= (in_polygon(0.5 * (GX[:-1, :-1] + GX[1:, 1:]), 0.5 * (GZ[:-1, :-1] + GZ[1:, 1:]), poly)
           | (_dist_to_polygon(0.5 * (GX[:-1, :-1] + GX[1:, 1:]), 0.5 * (GZ[:-1, :-1] + GZ[1:, 1:]), poly) <= 1.5))
    jj, ii = np.nonzero(cc)
    if not len(ii):
        raise MapgenError('water %s is smaller than one cell of its plane' % wid)
    ids = np.unique(np.concatenate([jj * (nx + 1) + ii, jj * (nx + 1) + ii + 1, (jj + 1) * (nx + 1) + ii, (jj + 1) * (nx + 1) + ii + 1]))
    lut = np.full((nx + 1) * (nz + 1), -1, dtype=np.int64)
    lut[ids] = np.arange(len(ids))
    pz, px = np.divmod(ids, nx + 1)
    ox, oz = float(x0), float(z0)
    P = np.stack([gx[px] - ox, np.full(len(ids), level), gz[pz] - oz], axis=-1)
    T = np.stack([gx[px] * 0.08, gz[pz] * 0.08], axis=-1)
    a, b, c, d = lut[jj * (nx + 1) + ii], lut[jj * (nx + 1) + ii + 1], lut[(jj + 1) * (nx + 1) + ii + 1], lut[(jj + 1) * (nx + 1) + ii]
    mesh = Mesh()
    mesh.add(tex_for('sea' if w.get('opaque') else 'water', 0), P, np.tile([0.0, 1.0, 0.0], (len(P), 1)), T, np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)]))
    name = 'W_%s' % wid
    out.model(name, [mesh.part()])
    out.place(name, [ox, 0.0, oz], name='WATER_%s' % wid.upper())
    rule = w.get('rule', 'reset')
    info = dict(id=wid, level=round(level, 3), depth=res['depth'], area=round(float(cc.sum()) * cell * cell, 1), rule=rule,
                triangles=mesh.counts()['triangles'], vertices=mesh.counts()['vertices'])
    out.note('Water %s is a see-through plane: swimming does not exist in the game, so the player wades on the basin floor unless a rule moves him.' % wid)
    if rule in ('reset', 'kill'):
        boxes = _boxes(poly, H, level, res['depth'])
        spot = None
        if rule == 'reset':
            spot = _spot(w.get('reset'), 'WATER_%s_SHORE' % wid.upper(), _shore_point(poly), H, out)
        for n, (bx0, bz0, bx1, bz1) in enumerate(boxes):
            t = dict(id='water_%s_%d' % (wid, n), kind='teleport' if rule == 'reset' else 'end_mission', reason='water',
                     pos=[round((bx0 + bx1) / 2.0, 3), round(level - res['depth'] / 2.0 + 0.2, 3), round((bz0 + bz1) / 2.0, 3)],
                     size=[round(bx1 - bx0, 3), round(res['depth'] + 0.8, 3), round(bz1 - bz0, 3)], orient=[0.0, 0.0, 0.0, 1.0])
            if rule == 'reset':
                t['teleport_to'] = spot
            else:
                t['result'] = 0
            out.triggers.append(t)
        if rule == 'kill':
            out.note('Water %s ends a mission as failed when the player enters it (the shipped behaviour); outside a mission nothing happens.' % wid)
        info['triggers'] = len(boxes)
    out.stats['water'].append(info)
    return info


def _shore_point(poly):
    """A point just outside the polygon, east of its bounding box: [[x, z] ...] shaped like a polygon so edges._spot can average it."""
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    x, z = max(xs) + 3.0, (max(zs) + min(zs)) / 2.0
    return [[x, z], [x, z], [x, z]]


def _boxes(poly, H, level, depth):
    """A few axis boxes (x0, z0, x1, z1) covering the cells whose centre lies in the polygon (at most 12, merged)."""
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    step = max((max(xs) - min(xs)), (max(zs) - min(zs))) / 24.0
    step = max(step, 1.0)
    nx = int(math.ceil((max(xs) - min(xs)) / step))
    nz = int(math.ceil((max(zs) - min(zs)) / step))
    cells = {}
    for j in range(nz):
        for i in range(nx):
            cx, cz = min(xs) + (i + 0.5) * step, min(zs) + (j + 0.5) * step
            if in_polygon(np.array([cx]), np.array([cz]), poly)[0]:
                cells[(i, j)] = 1
    runs = G._runs(cells, None)
    while len(runs) > 12:
        runs = sorted(runs, key=lambda r: (r[2] - r[0] + 1) * (r[3] - r[1] + 1))[1:]       # drop the smallest slivers
    return [(min(xs) + a * step, min(zs) + b * step, min(xs) + (c + 1) * step, min(zs) + (d + 1) * step) for a, b, c, d, _ in runs]
