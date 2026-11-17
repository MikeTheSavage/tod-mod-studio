"""Ground paint: which material each terrain cell shows, and (a separate layer) which surface type it feels like.

Recipe key `ground_paint` (all optional):
  {"palette": ["dirt", "grass", ...],     ids of PALETTE (or {"id", "kind", "surface", "size", "seed"} for your own); at most the
                                          limit G1 per section; default ["dirt"]
   "default": "dirt",                      material of every cell no stroke covers
   "cells": null,                          packed grid {enc, shape, data} of palette indices per cell (nz x nx), the painted base
   "strokes": [{"material": "grass", "pos": [x, z], "radius": 8} | {"material": "sand", "rect": [x0, z0, x1, z1]} |
               {"material": "dirt", "polygon": [[x, z], ...]}],            replayed in order over `cells`
   "rock_slope": null,                     cells steeper than this rise/run take the palette's rock (when it has one)
   "surface_strokes": [{"surface": "Asphalt", "pos": [x, z], "radius": 5}],   the surface layer: footsteps, grip, impacts. It starts
                                          as each material's own surface and is changed by these strokes only
   "surface_cells": null}                  packed grid of surface indices per cell (into core.MATERIALS), under the strokes
One texture shows per sub-mesh, so cells of one material share one mesh and edges between materials are hard (no blend).
"""
from .core import np, MapgenError, MATERIALS, in_polygon, pack_grid, unpack_grid, mat_index

# id -> (texture kind, default surface type, texture size)
PALETTE = {
    'dirt': ('dirt', 'Dirt', 256),
    'sand': ('sand', 'Dirt', 256),
    'asphalt': ('asphalt', 'Asphalt', 256),
    'grass': ('grass', 'Grass', 256),
    'rock': ('cliff', 'Stone', 256),
}
SHIPPED_WORDS = {'dirt': ['dirt', 'mud', 'soil', 'ground'], 'sand': ['sand', 'desert'], 'asphalt': ['asphalt', 'road'],
                 'grass': ['grass', 'lawn'], 'rock': ['rock', 'cliff', 'stone']}


PREFER = ('ter_', 'floor_', 'road', 'grass_', 'surround')
AVOID = ('lod_', 'decal', 'overlay', 'to_', 'wheel', 'bike', 'panel', 'frame', 'window', 'sign', 'detail')


def shipped_match(pid, doc):
    """The shipped ground texture that looks most like a palette material, found through the asset index (`doc` =
    assetindex.load(ws)): -> its path or None. Terrain pictures (ter_*) of 128 px and up are preferred; level-of-detail pictures,
    decals and overlays are not offered."""
    words = SHIPPED_WORDS.get(pid)
    if not doc or not words:
        return None
    best, best_score = None, 0
    for path in sorted(doc.get('textures') or {}):
        t = doc['textures'][path]
        base = path.split('/')[-1]
        if not any(w in base for w in words) or any(a in base for a in AVOID) or t.get('fmt') != 'DXT1' or min(t.get('w', 0), t.get('h', 0)) < 64:
            continue
        score = 10 + (5 if base.startswith('ter_') else 0) + (2 if t.get('w') == t.get('h') else 0) + (2 if t.get('w', 0) >= 128 else 0)             + sum(1 for p in PREFER if base.startswith(p))
        if score > best_score:
            best, best_score = path, score
    return best


def max_materials():
    from .. import limits
    return int(limits.value('G1'))


def resolve_palette(gp, out, assets=None):
    """-> list of dict(id, tex (texture name), kind, surface (face material index), size, seed). Registers the textures."""
    raw = (gp or {}).get('palette') or ['dirt']
    cap = max_materials()
    if len(raw) > cap:
        raise MapgenError('a section can paint with at most %d materials (this one has %d)' % (cap, len(raw)))
    pal = []
    for k, e in enumerate(raw):
        if isinstance(e, str):
            if e not in PALETTE:
                raise MapgenError('unknown ground material %r (%s)' % (e, ', '.join(PALETTE)))
            kind, surf, size = PALETTE[e]
            e = dict(id=e, kind=kind, surface=surf, size=size)
        else:
            e = dict(e)
            base = PALETTE.get(e.get('id'))
            e.setdefault('kind', base[0] if base else 'dirt')
            e.setdefault('surface', base[1] if base else 'Dirt')
            e.setdefault('size', base[2] if base else 256)
        if not e.get('id'):
            raise MapgenError('a palette entry needs an id')
        if any(p['id'] == e['id'] for p in pal):
            raise MapgenError('palette material %s is listed twice' % e['id'])
        e['seed'] = int(e.get('seed', 1 + k))
        e['tex'] = out.texture('G_' + e['id'], e['kind'], e['size'], 'DXT1', e['seed'])
        if assets:
            e['shipped'] = e.get('shipped') or shipped_match(e['id'], assets)
            if e['shipped']:
                out.textures[e['tex']]['shipped'] = e['shipped']
                blocks = ((assets.get('textures') or {}).get(e['shipped'].lower()) or {}).get('blocks') or []
                if blocks:
                    out.textures[e['tex']]['shipped_blocks'] = list(blocks[:3])
                out.note('Ground material %s shows the game picture %s.' % (e['id'], e['shipped'].split('/')[-1]))
        e['surf'] = mat_index(e['surface'])
        pal.append(e)
    return pal


def _stroke_mask(H, s):
    """Boolean (nz, nx) mask of the cells whose centre a stroke covers."""
    xs = H.ox + (np.arange(H.nx) + 0.5) * H.cell
    zs = H.oz + (np.arange(H.nz) + 0.5) * H.cell
    X, Z = np.meshgrid(xs, zs)
    if s.get('rect'):
        x0, z0, x1, z1 = [float(v) for v in s['rect']]
        return (X >= min(x0, x1)) & (X <= max(x0, x1)) & (Z >= min(z0, z1)) & (Z <= max(z0, z1))
    if s.get('polygon'):
        return in_polygon(X, Z, [[float(a), float(b)] for a, b in s['polygon']])
    px, pz = [float(v) for v in s['pos']]
    r = float(s.get('radius', 6.0))
    return np.hypot(X - px, Z - pz) <= r


def build(H, gp, out, assets=None):
    """-> (palette, tex (nz, nx) palette indices, surf (nz, nx) face-material indices)."""
    gp = gp or {}
    pal = resolve_palette(gp, out, assets)
    ids = [p['id'] for p in pal]
    default = gp.get('default', ids[0])
    if default not in ids:
        raise MapgenError('the default ground material %r is not in the palette' % default)
    shape = (H.nz, H.nx)
    cells = unpack_grid(gp.get('cells'), np.int64)
    tex = np.full(shape, ids.index(default), dtype=np.int64)
    if cells is not None:
        if cells.shape != shape:
            raise MapgenError('painted cells are %s but the terrain has %d x %d cells' % ('x'.join(str(v) for v in cells.shape[::-1]), H.nx, H.nz))
        if cells.size and (cells.min() < 0 or cells.max() >= len(pal)):
            raise MapgenError('painted cells use a palette entry that does not exist')
        tex = cells.copy()
    for s in gp.get('strokes') or []:
        m = s.get('material')
        if m not in ids:
            raise MapgenError('stroke uses %r, which is not in the palette' % m)
        tex[_stroke_mask(H, s)] = ids.index(m)
    if gp.get('rock_slope') is not None:
        if 'rock' not in ids:
            out.note('rock_slope is set but the palette has no rock: steep cells keep their material')
        else:
            h = H.h
            sx = np.maximum(np.abs(h[:-1, 1:] - h[:-1, :-1]), np.abs(h[1:, 1:] - h[1:, :-1])) / H.cell
            sz = np.maximum(np.abs(h[1:, :-1] - h[:-1, :-1]), np.abs(h[1:, 1:] - h[:-1, 1:])) / H.cell
            tex[np.maximum(sx, sz) > float(gp['rock_slope'])] = ids.index('rock')
    own = np.array([p['surf'] for p in pal], dtype=np.int64)
    surf = own[tex]
    sc = unpack_grid(gp.get('surface_cells'), np.int64)
    if sc is not None:
        if sc.shape != shape:
            raise MapgenError('surface cells do not match the terrain size')
        surf = np.where(sc >= 0, sc, surf)
    for s in gp.get('surface_strokes') or []:
        surf[_stroke_mask(H, s)] = mat_index(s['surface'])
    return pal, tex, surf


def pack(tex):
    return pack_grid(tex, '<u1')
