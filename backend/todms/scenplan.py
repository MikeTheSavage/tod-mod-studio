"""The plan of a scene: a top-down picture of where its streets, open ground, buildings and water are.

A scene map has no terrain, roads or trees in the generator's sense, so the minimap writer and the mission placement view had nothing to draw
from. The plan is made once, when the scene is sent, from the cleaned triangles, and kept beside the project (`plan.png`, one byte per cell,
north up like the minimap: row 0 is the largest z). Both pictures then read it without the source file.

  cell classes   0 nothing   1 open ground (a floor at street level: pavement, plaza, yard)   2 road (a floor at street level whose
                 picture reads as asphalt)   3 building (roofs or a floor well above the street, with no street-level floor under them)
                 4 water (the sea bodies of the map)
  make(...)      -> dict(grid, x0, z1, cell)
  save / load    the plan as an 8-bit palette PNG (index = class), the geometry in a small dict kept in the project's scene summary
  sdf(grid, k)   signed distance (metres, negative inside) of one class, for edges that are finer than a cell
"""
import io
import struct
import zlib

import numpy as np

NONE, GROUND, ROAD, BUILDING, WATER = 0, 1, 2, 3, 4
NAMES = {NONE: 'nothing', GROUND: 'ground', ROAD: 'road', BUILDING: 'building', WATER: 'water'}
# the colours of the editor's picture (class -> RGBA); the minimap draws its own inks
VIEW_COLOURS = {GROUND: (108, 116, 128, 235), ROAD: (62, 68, 82, 245), BUILDING: (168, 176, 190, 245), WATER: (58, 108, 150, 235)}
MAX_SIDE = 720                  # cells along the longer side
STREET_LOW = -4.0               # metres from the street level: a floor in [low, high] is the street (steps and kerbs of a double scale included)
STREET_HIGH = 3.0
ROOF = 4.0                      # a surface this far above the street is a roof
STEP_LIMIT = 1.5                # the highest step the player climbs, in metres (measured in game on stairs made by the scene import: 1.55 m yes, 1.6 m no)
LEDGE_MAX = 4.0                 # a jump of the walk surface above the limit and up to this is a ledge; taller is a wall


def _up_samples(P, T, ny_min, density, rng, cap=20000):
    A, B, C = P[T[:, 0]].astype(np.float64), P[T[:, 1]].astype(np.float64), P[T[:, 2]].astype(np.float64)
    nn = np.cross(B - A, C - A)
    ln = np.linalg.norm(nn, axis=1)
    ny = np.abs(nn[:, 1]) / np.maximum(ln, 1e-12)               # a scene draws its faces both ways round: up or down makes no difference here
    ok = (ny > ny_min) & (ln > 1e-12)
    ids = np.nonzero(ok)[0]
    area = ln[ids] / 2.0
    cnt = np.clip(np.ceil(area * density).astype(np.int64), 1, cap)
    idx = np.repeat(np.arange(len(ids)), cnt)
    u = rng.random(len(idx))
    v = rng.random(len(idx))
    f = u + v > 1.0
    u[f], v[f] = 1.0 - u[f], 1.0 - v[f]
    a, b, c = A[ids][idx], B[ids][idx], C[ids][idx]
    Q = a + (b - a) * u[:, None] + (c - a) * v[:, None]
    return Q, ids[idx], ny[ids][idx]


def make(P, T, road_tri, ground_y, water=(), cell=None, max_side=MAX_SIDE, low=STREET_LOW, high=STREET_HIGH, roof=ROOF, seed=1):
    """P (n, 3) and T (m, 3) the cleaned triangles; road_tri (m,) bool: the triangle's picture reads as asphalt; ground_y: the street level;
    water: rects [x0, z0, x1, z1]. -> dict(grid (h, w) uint8, x0, z1, cell) or None when there is nothing to draw."""
    P = np.asarray(P)
    T = np.asarray(T)
    if len(T) == 0:
        return None
    lo, hi = P.min(0), P.max(0)
    ext = max(hi[0] - lo[0], hi[2] - lo[2], 1.0)
    cell = float(cell) if cell else max(0.5, float(np.ceil(ext / max_side * 4.0) / 4.0))
    x0, z1 = float(lo[0]) - cell, float(hi[2]) + cell
    w = int(np.ceil((hi[0] + cell - x0) / cell)) + 1
    h = int(np.ceil((z1 - (lo[2] - cell)) / cell)) + 1
    rng = np.random.default_rng(seed)
    road_tri = np.asarray(road_tri, bool)
    Q, tid, ny = _up_samples(P, T, 0.3, 3.0 / (cell * cell), rng)
    ix = np.clip(((Q[:, 0] - x0) / cell).astype(np.int64), 0, w - 1)
    iz = np.clip(((z1 - Q[:, 2]) / cell).astype(np.int64), 0, h - 1)
    flat = (ny > 0.85) & (Q[:, 1] >= ground_y + low) & (Q[:, 1] <= ground_y + high)
    tall = Q[:, 1] > ground_y + roof
    street = np.zeros((h, w), np.int32)
    asph = np.zeros((h, w), np.int32)
    high_ = np.zeros((h, w), bool)
    np.add.at(street, (iz[flat], ix[flat]), 1)
    np.add.at(asph, (iz[flat & road_tri[tid]], ix[flat & road_tri[tid]]), 1)
    high_[iz[tall], ix[tall]] = True
    grid = np.zeros((h, w), np.uint8)
    some = street > 0
    grid[some] = GROUND
    grid[high_ & ~some] = BUILDING                           # a roof high above a cell with no street-level floor: a building (a deck or an arcade over a street leaves the street)
    grid[some & (asph * 10 >= street * 3)] = ROAD            # a road over its ground (coplanar layers) still reads as road, also under a deck or an arcade
    # a floor above the street level that is not a roof (a terrace, a bridge deck): a block when nothing else is there
    mid = (Q[:, 1] > ground_y + high) & (Q[:, 1] <= ground_y + roof) & (ny > 0.85)
    m2 = np.zeros((h, w), bool)
    m2[iz[mid], ix[mid]] = True
    grid[m2 & (grid == NONE)] = BUILDING
    # below the street (a quay, steps down to the water): open ground
    under = (Q[:, 1] < ground_y + low) & (ny > 0.85)
    m3 = np.zeros((h, w), bool)
    m3[iz[under], ix[under]] = True
    grid[m3 & (grid == NONE)] = GROUND
    grid = _smooth(_close(grid))
    for r in water or ():
        c0 = max(0, int((r[0] - x0) / cell))
        c1 = min(w, int(np.ceil((r[2] - x0) / cell)))
        r0 = max(0, int((z1 - r[3]) / cell))
        r1 = min(h, int(np.ceil((z1 - r[1]) / cell)))
        if c1 > c0 and r1 > r0:
            seg = grid[r0:r1, c0:c1]
            seg[seg == NONE] = WATER
    if not grid.any():
        return None
    out = dict(grid=grid, x0=x0, z1=z1, cell=cell)
    # the heights of the buildings above the street (the biggest first), for the skyline that is drawn past the edge
    roof_y = np.full((h, w), -np.inf)
    np.maximum.at(roof_y, (iz[tall], ix[tall]), Q[tall, 1])
    try:
        from scipy import ndimage as ndi
        lab, n = ndi.label(grid == BUILDING)
        if n:
            top = np.asarray(ndi.maximum(np.where(np.isfinite(roof_y), roof_y, ground_y), lab, np.arange(1, n + 1))) - ground_y
            size = np.asarray(ndi.sum(np.ones_like(lab), lab, np.arange(1, n + 1)))
            order = np.argsort(-size)[:80]
            out['heights'] = [round(float(top[i]), 1) for i in order if top[i] > roof * 0.5]
    except ImportError:
        pass
    out['steps'] = step_report(Q, ny, ground_y, ix, iz, flat, h, w, cell, x0, z1, low, high)
    return out


def step_report(Q, ny, ground_y, ix, iz, flat, h, w, cell, x0, z1, low, high):
    """Places where the walk surface jumps by more than the player climbs (STEP_LIMIT) but by less than a wall (LEDGE_MAX): kerbs, plinths and
    stairs that are too tall for him. The walk surface of a cell is its highest flat floor in the street band. A ledge is two cells (one or two
    apart) at different heights; neighbouring ledge cells join into one place. -> dict(limit, count, highest, places [[x, z, height], ...] (the
    tallest first, at most 8))."""
    from scipy import ndimage as ndi
    top = np.full((h, w), -np.inf)
    np.maximum.at(top, (iz[flat], ix[flat]), Q[flat, 1])
    have = np.isfinite(top)
    ledge = np.zeros((h, w), bool)
    jump = np.zeros((h, w), np.float32)
    for dz, dx in ((0, 1), (1, 0), (0, 2), (2, 0)):
        a = top[:h - dz, :w - dx]
        b = top[dz:, dx:]
        ok = np.isfinite(a) & np.isfinite(b)
        d = np.where(ok, np.abs(a - b), 0.0)
        m = ok & (d > STEP_LIMIT) & (d < LEDGE_MAX)
        ledge[:h - dz, :w - dx] |= m
        jump[:h - dz, :w - dx] = np.maximum(jump[:h - dz, :w - dx], np.where(m, d, 0.0))
    lab, n = ndi.label(ledge, structure=np.ones((3, 3), int))
    places = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < 2:                                          # a single cell is a sliver, not a place
            continue
        j = float(jump[ys, xs].max())
        places.append((j, float(x0 + (xs.mean() + 0.5) * cell), float(z1 - (ys.mean() + 0.5) * cell)))
    places.sort(reverse=True)
    return dict(limit=STEP_LIMIT, count=len(places), highest=round(places[0][0], 2) if places else 0.0,
                places=[[round(x, 1), round(z, 1), round(j, 2)] for j, x, z in places[:8]])


def _smooth(grid, size=5):
    """Road and open ground flicker where the source's pictures alternate (a lane mark, a patch of a second picture): each street cell takes the
    majority of the street cells around it (a size x size window)."""
    try:
        from scipy import ndimage as ndi
    except ImportError:
        return grid
    st = (grid == GROUND) | (grid == ROAD)
    road = (grid == ROAD).astype(np.float32)
    num = ndi.uniform_filter(road * st, size=size)
    den = ndi.uniform_filter(st.astype(np.float32), size=size)
    out = grid.copy()
    isroad = num >= 0.5 * np.maximum(den, 1e-6)
    out[st & isroad] = ROAD
    out[st & ~isroad] = GROUND
    return out


def _close(grid):
    """Fill one-cell holes: a nothing cell with a class on both sides (left and right, or above and below) takes the left or upper class."""
    g = grid.copy()
    for ax in (1, 0):
        a = np.roll(g, 1, ax)
        b = np.roll(g, -1, ax)
        hole = (g == NONE) & (a != NONE) & (a == b)
        g[hole] = a[hole]
    return g


# ---------------------------------------------------------------------------------------------- the file
def _chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def to_png(grid, colours=None):
    """The plan as an 8-bit palette PNG: index = class. Class 0 is transparent. `colours` (class -> RGBA) makes it a picture for the editor."""
    cols = colours or VIEW_COLOURS
    pal = bytearray(256 * 3)
    al = bytearray([0]) + bytearray(4)
    for k, c in cols.items():
        pal[3 * k:3 * k + 3] = bytes(c[:3])
        al[k] = c[3] if len(c) > 3 else 255
    h, w = grid.shape
    raw = b''.join(b'\0' + grid[r].tobytes() for r in range(h))
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 3, 0, 0, 0)) + _chunk(b'PLTE', bytes(pal[:15]))
            + _chunk(b'tRNS', bytes(al)) + _chunk(b'IDAT', zlib.compress(raw, 9)) + _chunk(b'IEND', b''))


def from_png(data):
    """The class grid of a plan file (the palette index of every pixel). -> (h, w) uint8"""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    return np.asarray(im, dtype=np.uint8).copy()


def info_of(plan, file='plan.png'):
    """What the scene summary keeps to find the picture again."""
    g = plan['grid']
    d = dict(file=file, x0=round(float(plan['x0']), 3), z1=round(float(plan['z1']), 3), cell=float(plan['cell']), w=int(g.shape[1]), h=int(g.shape[0]),
             cells={NAMES[k]: int((g == k).sum()) for k in NAMES if k})
    if plan.get('heights'):
        d['heights'] = list(plan['heights'])
    if plan.get('steps') is not None:
        d['steps'] = plan['steps']
    return d


def write(folder, plan, file='plan.png'):
    import os
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, file), 'wb') as f:
        f.write(to_png(plan['grid']))
    return info_of(plan, file)


def read(folder, info):
    """-> dict(grid, x0, z1, cell) from a project folder and the summary's plan info, or None when the file is not there (or does not fit)."""
    import os
    try:
        with open(os.path.join(folder, info['file']), 'rb') as f:
            g = from_png(f.read())
    except (OSError, KeyError, ValueError):
        return None
    if g.ndim != 2 or g.shape != (info['h'], info['w']):
        return None
    return dict(grid=g, x0=float(info['x0']), z1=float(info['z1']), cell=float(info['cell']))


def bounds(plan):
    g = plan['grid']
    c = plan['cell']
    ys, xs = np.nonzero(g)
    if not len(xs):
        return None
    return [plan['x0'] + xs.min() * c, plan['z1'] - (ys.max() + 1) * c, plan['x0'] + (xs.max() + 1) * c, plan['z1'] - ys.min() * c]


# ---------------------------------------------------------------------------------------------- sampling
def sdf(grid, cls, cell):
    """Signed distance in metres to the edge of the cells of class `cls` (negative inside), at the cell centres."""
    from scipy import ndimage as ndi
    m = np.isin(grid, cls) if isinstance(cls, (tuple, list, set)) else grid == cls
    if not m.any():
        return np.full(grid.shape, 1e3, np.float32)
    out = ndi.distance_transform_edt(~m) - 0.5
    ins = ndi.distance_transform_edt(m) - 0.5
    return ((out - ins) * cell).astype(np.float32)


def bilinear(field, plan, X, Z, outside=1e3):
    """The field (one value per cell centre) at world positions X, Z; `outside` beyond the plan. Inside it the border cells carry on to the edge."""
    c = plan['cell']
    h, w = field.shape
    fx = (X - plan['x0']) / c - 0.5
    fz = (plan['z1'] - Z) / c - 0.5
    inside = (fx > -0.5) & (fx < w - 0.5) & (fz > -0.5) & (fz < h - 0.5)
    x0 = np.floor(fx).astype(np.int64)
    z0 = np.floor(fz).astype(np.int64)
    tx, tz = fx - x0, fz - z0
    out = np.zeros(X.shape, np.float32)
    for dz, wz in ((0, 1.0 - tz), (1, tz)):
        for dx, wx in ((0, 1.0 - tx), (1, tx)):
            v = field[np.clip(z0 + dz, 0, h - 1), np.clip(x0 + dx, 0, w - 1)]
            out += (wz * wx * v).astype(np.float32)
    return np.where(inside, out, np.float32(outside)).astype(np.float32)


def at(plan, x, z):
    """The class at a world position."""
    c = plan['cell']
    ix = int((x - plan['x0']) // c)
    iz = int((plan['z1'] - z) // c)
    g = plan['grid']
    if 0 <= ix < g.shape[1] and 0 <= iz < g.shape[0]:
        return int(g[iz, ix])
    return NONE


def view(folder, info):
    """The plan as a picture for the editor: dict(png base64, rect [x0, z0, x1, z1] it covers, cell). None when the file is not there."""
    import base64
    plan = read(folder, info)
    if plan is None:
        return None
    g = plan['grid']
    c = plan['cell']
    return dict(png=base64.b64encode(to_png(g)).decode('ascii'), cell=c,
                rect=[round(plan['x0'], 3), round(plan['z1'] - g.shape[0] * c, 3), round(plan['x0'] + g.shape[1] * c, 3), round(plan['z1'], 3)])
