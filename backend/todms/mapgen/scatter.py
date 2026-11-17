"""Scatter: seeded placement of trees, rocks and bushes inside an area, with density, a slope limit and exclusion of roads and water.

Recipe key `scatter` (a list):
  {"id": "palms", "polygon": [[x, z], ...] | "rect": [x0, z0, x1, z1] | "circle": [x, z, r],
   "items": [{"kind": "tree" | "rock" | "bush", "weight": 1.0}                        a generated model (rocks and trunks are solid)
             {"model": "/Models/...", "weight": 1.0, "solid": false, "radius": 0.4}], a shipped model (see the notes)
   "density": 0.01,            instances per square metre
   "seed": 1,
   "slope_max": 0.5,           steepest ground (rise / run) that takes an instance
   "min_dist": 2.5,            metres between instances
   "avoid_roads": 2.0,         metres kept clear beside a road
   "avoid_water": 1.0,         metres kept clear around water
   "variants": 3,              generated shapes per kind (different seeds; there is no turning or scaling of a placed model)
   "max": 2000}                cap per area
Generated kinds are built from the kit shapes, so they work in a new map today. A shipped model needs its record copied into the new
map's block, which the map builder does not do yet: those instances are listed under `shipped_models` and counted, and a `solid` one
also gets a small box hull in the ground chunk it stands in.
"""
import math

from .core import np, MapgenError, polygon_of, in_polygon, rng

KINDS = ('tree', 'rock', 'bush')
SIZES = dict(tree=(1.2, 4.5), rock=(0.7, 1.8), bush=(0.6, 1.2))


def variant_model(kind, v, tex):
    """Native kit parts of one generated model (origin at its base). tex: dict kind -> texture name."""
    r = rng('scatter-variant', kind, v)
    if kind == 'tree':
        h = 3.2 + float(r.random()) * 1.4
        w = 0.22 + float(r.random()) * 0.08
        rad = 1.5 + float(r.random()) * 0.6
        parts = [dict(type='box', min=[-w, -0.3, -w], max=[w, h, w], tex=tex['bark'], uv=0.6, collide=True, material='Wood'),
                 dict(type='rock', center=[0.0, h + 0.4, 0.0], radius=rad, squash=0.75, seed=10 + v, tex=tex['leaf'], uv=0.4, collide=False),
                 dict(type='rock', center=[0.5 * rad, h - 0.3, 0.2 * rad], radius=rad * 0.7, squash=0.7, seed=20 + v, tex=tex['leaf'], uv=0.4, collide=False)]
        return parts, dict(solid=True, radius=w)
    if kind == 'rock':
        rad = 0.9 + float(r.random()) * 0.7
        return [dict(type='rock', center=[0.0, rad * 0.35, 0.0], radius=rad, squash=0.65, seed=30 + v, tex=tex['rock'], uv=0.35, collide=True,
                     material='Stone')], dict(solid=True, radius=rad)
    rad = 0.7 + float(r.random()) * 0.4
    return [dict(type='rock', center=[0.0, rad * 0.45, 0.0], radius=rad, squash=0.8, seed=40 + v, tex=tex['leaf'], uv=0.4, collide=False)], \
        dict(solid=False, radius=rad)


def _dist_polylines(x, z, lines):
    """Distance minus half width to the nearest road centre line (arrays x, z)."""
    best = np.full(x.shape, np.inf)
    for xz, half in lines:
        for i in range(len(xz) - 1):
            a, b = xz[i], xz[i + 1]
            d = b - a
            L2 = float(d @ d)
            t = np.clip(((x - a[0]) * d[0] + (z - a[1]) * d[1]) / max(L2, 1e-12), 0.0, 1.0)
            best = np.minimum(best, np.hypot(x - (a[0] + t * d[0]), z - (a[1] + t * d[1])) - half)
    return best


def _water_blocked(x, z, waters, margin):
    from .water import _dist_to_polygon
    bad = np.zeros(x.shape, dtype=bool)
    for w in waters:
        bad |= in_polygon(x, z, w['poly']) | (_dist_to_polygon(x, z, w['poly']) <= margin)
    return bad


def candidates(area, spec, sid, H, roads, waters):
    poly = polygon_of(spec, 'scatter %s' % sid)
    xs, zs = [p[0] for p in poly], [p[1] for p in poly]
    dens = float(spec.get('density', 0.01))
    if not 0 < dens <= 2.0:
        raise MapgenError('scatter %s: density must be between 0 and 2 per square metre' % sid)
    r = rng('scatter', sid, spec.get('seed', 1))
    spacing = 1.0 / math.sqrt(dens)
    gx = np.arange(min(xs), max(xs) + spacing, spacing)
    gz = np.arange(min(zs), max(zs) + spacing, spacing)
    GX, GZ = np.meshgrid(gx, gz)
    jit = r.random(GX.shape + (2,)) - 0.5
    X = GX + jit[..., 0] * spacing
    Z = GZ + jit[..., 1] * spacing
    X, Z = X.ravel(), Z.ravel()
    ok = in_polygon(X, Z, poly)
    X, Z = X[ok], Z[ok]
    return X, Z, r


def place(spec, k, H, out, roads, waters, kit_tex_for, extras):
    """Build one scatter area. -> stats dict. Adds models/placements to `out` and solid hull sets of shipped instances to `extras`."""
    sid = str(spec.get('id') or 'scatter%d' % (k + 1))
    items = spec.get('items') or [dict(kind='tree')]
    for it in items:
        if not it.get('model') and it.get('kind') not in KINDS:
            raise MapgenError('scatter %s: an item is a kind (%s) or a model path' % (sid, ', '.join(KINDS)))
    X, Z, r = candidates(None, spec, sid, H, roads, waters)
    keep = np.ones(X.shape, dtype=bool)
    slope_max = float(spec.get('slope_max', 0.5))
    if H.h is not None:
        keep &= H.slope_at(X, Z) <= slope_max
        keep &= H.inside(X, Z)
    if roads:
        keep &= _dist_polylines(X, Z, roads) > float(spec.get('avoid_roads', 2.0))
    if waters:
        keep &= ~_water_blocked(X, Z, waters, float(spec.get('avoid_water', 1.0)))
    X, Z = X[keep], Z[keep]
    # thin to the minimum distance, in a stable order
    md = float(spec.get('min_dist', 2.5))
    order = np.lexsort((Z, X))
    X, Z = X[order], Z[order]
    cell = max(md, 0.5)
    taken, sel = {}, []
    for x, z in zip(X, Z):
        cx, cz = int(x // cell), int(z // cell)
        if any((cx + a, cz + b) in taken and math.hypot(taken[(cx + a, cz + b)][0] - x, taken[(cx + a, cz + b)][1] - z) < md
               for a in (-1, 0, 1) for b in (-1, 0, 1)):
            continue
        taken[(cx, cz)] = (float(x), float(z))
        sel.append((float(x), float(z)))
    cap = int(spec.get('max', 2000))
    capped = len(sel) > cap
    if capped:
        pick = np.sort(r.permutation(len(sel))[:cap])
        sel = [sel[int(i)] for i in pick]
        out.note('Scatter %s would place %d instances; the cap of %d keeps a seeded subset.' % (sid, len(taken), cap))
    weights = np.array([float(it.get('weight', 1.0)) for it in items])
    weights = weights / weights.sum()
    nvar = max(1, int(spec.get('variants', 3)))
    made = {}
    counts = {}
    shipped = 0
    for (x, z) in sel:
        it = items[int(r.choice(len(items), p=weights))]
        y = float(H.at(x, z))
        if it.get('model'):
            out.shipped_models.append(dict(model=it['model'], pos=[round(x, 3), round(y, 3), round(z, 3)], orient=[0.0, 0.0, 0.0, 1.0]))
            if it.get('solid'):
                rr = float(it.get('radius', 0.4))
                hh = float(it.get('height', 3.0))
                pts = [(x + a * rr, y + b * hh - 0.3, z + c * rr) for a in (-1, 1) for b in (0, 1) for c in (-1, 1)]
                extras.append((x, z, [pts], 'Wood'))
            shipped += 1
            counts[it['model']] = counts.get(it['model'], 0) + 1
            continue
        kind = it['kind']
        v = int(r.integers(0, nvar))
        mname = 'S_%s_%s_%d' % (sid, kind, v)
        if mname not in made:
            parts, _ = variant_model(kind, v, kit_tex_for())
            out.model(mname, parts)
            made[mname] = True
        out.place(mname, [x, y, z], name='SC_%s_%d' % (sid.upper(), len(out.placements)))
        counts[kind] = counts.get(kind, 0) + 1
    if shipped:
        out.note('Scatter %s places %d models of the game; the builder copies each model and its pictures into the map.' % (sid, shipped))
    if any(it.get('model') for it in items):
        out.note('Placed shipped models cannot be scaled (the game has no scale on models) and a new-geometry map cannot turn them; '
                 'generated kinds use several shapes instead.')
    return dict(id=sid, instances=len(sel), generated=len(sel) - shipped, shipped=shipped, counts=counts, capped=capped)
