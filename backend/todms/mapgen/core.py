"""Shared pieces of the map generators: the numpy guard, seeded random numbers, compact array encoding, the height grid and
the collector every generator writes into (textures, models, placements, walls, teleports, triggers, stats, notes).

Everything here is deterministic: the same input gives the same bytes (seeds come from a hash of the input, never from the clock).
"""
import base64
import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))


def _guard():
    """Keep numpy off the faulty CPU cores (cpu_guard.py): the vendored copy is the same file as the lab one."""
    p = os.path.join(BACKEND, 'vendor', 'newmap')
    if p not in sys.path:
        sys.path.append(p)
    try:
        import cpu_guard  # noqa: F401
    except Exception:                                                    # noqa: BLE001
        pass


_guard()
import numpy as np  # noqa: E402

IDENT = [0.0, 0.0, 0.0, 1.0]

# face materials (the engine's facecoll list, same order as geomkit.MATERIALS) and the two surface words the builder writes
MATERIALS = ["AllRound", "Metal", "Concrete", "Wood", "Dirt", "Stone", "Glass", "Bush", "Wirefence", "Grass", "Asphalt",
             "Water", "Cloth", "SolidGlass"]
SURF_SOLID = 0x02007C00        # solid, bullet-proof, opaque, camera-blocking: the default of every shipped hull
SURF_THIN = 0x02007400         # as solid but not bullet-proof (shipped thin parts: railings, fences)
SURF_WORDS = {'solid': SURF_SOLID, 'thin': SURF_THIN}


class MapgenError(ValueError):
    """A bad high-level key: the message is a plain sentence for the user."""


def mat_index(name):
    for i, n in enumerate(MATERIALS):
        if n.lower() == str(name).lower():
            return i
    raise MapgenError('unknown surface type %r (%s)' % (name, ', '.join(MATERIALS)))


# ------------------------------------------------------------------------------------------------ random numbers
def seed_of(*parts):
    """A stable 63-bit seed from any strings and numbers (so a map's seed never depends on the order generators run)."""
    h = hashlib.sha256('|'.join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], 'little') >> 1


def rng(*parts):
    return np.random.default_rng(seed_of(*parts))


# ------------------------------------------------------------------------------------------------ compact arrays
def enc(a, dtype='<f4'):
    return base64.b64encode(np.ascontiguousarray(np.asarray(a, dtype=dtype)).tobytes()).decode('ascii')


def dec(s, dtype='<f4', shape=None):
    a = np.frombuffer(base64.b64decode(s), dtype=dtype)
    return a.reshape(shape) if shape is not None else a


def pack_grid(a, dtype='<f4'):
    a = np.asarray(a)
    return dict(enc=np.dtype(dtype).str, shape=list(a.shape), data=enc(a, dtype))


def unpack_grid(g, dtype=None):
    """Accept a packed grid {enc, shape, data}, a nested list, or None."""
    if g is None:
        return None
    if isinstance(g, dict):
        a = dec(g['data'], g.get('enc', '<f4'), tuple(g['shape']))
        return a.astype(dtype) if dtype else a.copy()
    return np.asarray(g, dtype=dtype or float)


# ------------------------------------------------------------------------------------------------ geometry helpers
def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def in_polygon(px, pz, poly):
    """Even-odd test of arrays px, pz against polygon [[x, z], ...] (vectorised)."""
    px = np.asarray(px, dtype=float)
    pz = np.asarray(pz, dtype=float)
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if zi != zj:
            cond = ((zi > pz) != (zj > pz)) & (px < (xj - xi) * (pz - zi) / (zj - zi) + xi)
            inside ^= cond
        j = i
    return inside


def polygon_area(poly):
    a = 0.0
    for i in range(len(poly)):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % len(poly)]
        a += x0 * z1 - x1 * z0
    return abs(a) / 2.0


def polygon_of(spec, what='area'):
    """A polygon [[x, z], ...] from {polygon: [...]} | {rect: [x0, z0, x1, z1]} | {circle: [x, z, r]}."""
    if spec.get('polygon'):
        p = [[float(a), float(b)] for a, b in spec['polygon']]
        if len(p) < 3:
            raise MapgenError('%s needs at least 3 corners' % what)
        return p
    if spec.get('rect'):
        x0, z0, x1, z1 = [float(v) for v in spec['rect']]
        return [[min(x0, x1), min(z0, z1)], [max(x0, x1), min(z0, z1)], [max(x0, x1), max(z0, z1)], [min(x0, x1), max(z0, z1)]]
    if spec.get('circle'):
        cx, cz, r = [float(v) for v in spec['circle']]
        return [[round(cx + r * math.cos(2 * math.pi * k / 24), 4), round(cz + r * math.sin(2 * math.pi * k / 24), 4)] for k in range(24)]
    raise MapgenError('%s needs a polygon, a rect or a circle' % what)


def yaw_quat(yaw):
    """Quaternion (x, y, z, w) of a turn about +y (radians)."""
    return [0.0, round(math.sin(yaw / 2.0), 6), 0.0, round(math.cos(yaw / 2.0), 6)]


# ------------------------------------------------------------------------------------------------ the height grid
class Heights:
    """Regular height grid: h[j, i] at (ox + i * cell, oz + j * cell). Without terrain: a flat plane at `flat`."""

    def __init__(self, ox=0.0, oz=0.0, cell=2.0, h=None, flat=0.0):
        self.ox, self.oz, self.cell = float(ox), float(oz), float(cell)
        self.h = h
        self.flat = float(flat)

    @property
    def nz(self):
        return self.h.shape[0] - 1

    @property
    def nx(self):
        return self.h.shape[1] - 1

    def xs(self):
        return self.ox + np.arange(self.nx + 1) * self.cell

    def zs(self):
        return self.oz + np.arange(self.nz + 1) * self.cell

    def mesh(self):
        return np.meshgrid(self.xs(), self.zs())

    def at(self, x, z):
        """Bilinear height at world (x, z); outside the grid the nearest edge value."""
        x = np.asarray(x, dtype=float)
        z = np.asarray(z, dtype=float)
        if self.h is None:
            return np.full(np.broadcast(x, z).shape, self.flat)
        fx = np.clip((x - self.ox) / self.cell, 0, self.nx)
        fz = np.clip((z - self.oz) / self.cell, 0, self.nz)
        i0 = np.minimum(np.floor(fx).astype(int), self.nx - 1)
        j0 = np.minimum(np.floor(fz).astype(int), self.nz - 1)
        tx, tz = fx - i0, fz - j0
        h = self.h
        return (h[j0, i0] * (1 - tx) * (1 - tz) + h[j0, i0 + 1] * tx * (1 - tz) + h[j0 + 1, i0] * (1 - tx) * tz
                + h[j0 + 1, i0 + 1] * tx * tz)

    def inside(self, x, z):
        x = np.asarray(x, dtype=float)
        z = np.asarray(z, dtype=float)
        if self.h is None:
            return np.ones(np.broadcast(x, z).shape, dtype=bool)
        return ((x >= self.ox) & (x <= self.ox + self.nx * self.cell) & (z >= self.oz) & (z <= self.oz + self.nz * self.cell))

    def slope_at(self, x, z):
        """Rise over run at world (x, z)."""
        d = self.cell * 0.5
        gx = (self.at(x + d, z) - self.at(x - d, z)) / (2 * d)
        gz = (self.at(x, z + d) - self.at(x, z - d)) / (2 * d)
        return np.sqrt(gx * gx + gz * gz)


# ------------------------------------------------------------------------------------------------ the collector
class Out:
    """What the generators of one map produce, before it is written into the recipe."""

    def __init__(self, name):
        self.name = name
        self.textures = {}        # name -> dict(name, kind, size, format, seed)
        self.models = []          # dict(name, parts=[...])
        self.placements = []      # dict(model, pos, name)
        self.walls = []
        self.teleports = []
        self.triggers = []
        self.collision_sets = []
        self.traffic = []         # seed traffic routes
        self.shipped_models = []  # placements of shipped models (the builder cannot copy their records into a new map yet)
        self.notes = []
        self.stats = dict(sections=[], chunks=[], textures=[], instances={}, roads=[], water=[], edges=[], limits={})
        self.model_names = set()

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def texture(self, name, kind, size=256, fmt='DXT1', seed=1, alpha=None):
        t = dict(name=name, kind=kind, size=int(size), format=fmt, seed=int(seed))
        if alpha is None and fmt == 'RGBA32':
            from .texkinds import ALPHA
            alpha = ALPHA.get(kind)
        if alpha:
            t['alpha'] = alpha                      # 'cutout' | 'blend': sets the alpha-test / alpha-blend flag of the meshes that use it
        old = self.textures.get(name)
        if old and old != t:
            raise MapgenError('texture name %s is used twice with different settings' % name)
        self.textures[name] = t
        return name

    def model(self, name, parts):
        if name in self.model_names:
            raise MapgenError('model name %s is used twice' % name)
        self.model_names.add(name)
        self.models.append(dict(name=name, parts=parts))

    def place(self, model, pos, name=None):
        pl = dict(model=model, pos=[round(float(v), 4) for v in pos])
        if name:
            pl['name'] = name
        self.placements.append(pl)
