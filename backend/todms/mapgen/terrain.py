"""Terrain: a height grid per map, edited by replayable brush strokes, imported from and exported to heightmap files.

Recipe key `terrain` (all optional, shown with defaults):
  {"cell": 2.0,                       metres per grid cell (0.5 to 16)
   "size": [60, 60],                  cells along x and z (the grid has size + 1 points per side)
   "origin": null,                    [x, z] of the south-west corner; null centres the grid on the origin
   "base": 0.0,                       height of a fresh grid
   "heights": null,                   a packed grid {enc, shape, data} or nested rows (nz + 1 rows of nx + 1): replaces base and noise
   "noise": null,                     {"seed": 1, "amp": 2.0, "scale": 40.0, "octaves": 3}: gentle rolling ground under the strokes
   "strokes": [],                     replayed in order: {"tool": "raise" | "lower" | "smooth" | "flatten" | "ramp",
                                        "pos": [x, z], "radius": 10, "strength": 1.0, "falloff": "smooth" | "linear" | "flat",
                                        "height": h (flatten target, ramp start), "to": [x, z], "to_height": h (ramp end),
                                        "passes": 2 (smooth)}
   "chunk": 24,                       cells per chunk side (a chunk is one placed model; split further to fit the limits)
   "uv": 0.125,                       texture repeats per metre
   "thickness": 1.5}                  depth of the collision slabs under the surface
The strokes stay in the recipe so an editor can replay and undo them; `heights` is only the starting point.
"""
import io
import struct
import zlib

from .core import np, Heights, MapgenError, smoothstep, pack_grid, unpack_grid, rng

MAX_CELLS = 1_000_000


# ------------------------------------------------------------------------------------------------ noise
def value_noise(nz, nx, scale_cells, octaves, r):
    """Smooth value noise on an (nz, nx) grid, features about `scale_cells` wide. Deterministic for the generator state."""
    out = np.zeros((nz, nx))
    amp, tot, sc = 1.0, 0.0, max(float(scale_cells), 1.0)
    for _ in range(max(1, int(octaves))):
        gz, gx = int(nz / sc) + 3, int(nx / sc) + 3
        lat = r.random((gz, gx))
        z = np.arange(nz) / sc
        x = np.arange(nx) / sc
        z0, x0 = np.floor(z).astype(int), np.floor(x).astype(int)
        fz, fx = smoothstep(z - z0)[:, None], smoothstep(x - x0)[None, :]
        a = lat[z0][:, x0]
        b = lat[z0][:, x0 + 1]
        c = lat[z0 + 1][:, x0]
        d = lat[z0 + 1][:, x0 + 1]
        out += amp * (a * (1 - fx) * (1 - fz) + b * fx * (1 - fz) + c * (1 - fx) * fz + d * fx * fz)
        tot += amp
        amp *= 0.5
        sc = max(sc / 2.0, 1.0)
    return out / tot


# ------------------------------------------------------------------------------------------------ strokes
def falloff(d, radius, kind):
    t = d / max(radius, 1e-6)
    if kind == 'flat':
        return (t <= 1.0).astype(float)
    if kind == 'linear':
        return np.clip(1.0 - t, 0.0, 1.0)
    return 1.0 - smoothstep(t)


def _blur(h):
    p = np.pad(h, 1, mode='edge')
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0


TOOLS = ('raise', 'lower', 'smooth', 'flatten', 'ramp')


def apply_stroke(H, s):
    tool = s.get('tool')
    if tool not in TOOLS:
        raise MapgenError('unknown terrain tool %r (%s)' % (tool, ', '.join(TOOLS)))
    px, pz = [float(v) for v in s['pos']]
    radius = float(s.get('radius', 10.0))
    if radius <= 0:
        raise MapgenError('a stroke needs a radius above zero')
    strength = float(s.get('strength', 1.0))
    kind = s.get('falloff', 'smooth')
    X, Z = H.mesh()
    if tool == 'ramp':
        qx, qz = [float(v) for v in s.get('to', [px + radius, pz])]
        dx, dz = qx - px, qz - pz
        L = max((dx * dx + dz * dz) ** 0.5, 1e-6)
        ux, uz = dx / L, dz / L
        along = (X - px) * ux + (Z - pz) * uz
        lat = np.abs((X - px) * -uz + (Z - pz) * ux)
        beyond = np.maximum(np.maximum(-along, along - L), 0.0)
        w = falloff(np.hypot(lat, beyond), radius, kind)
        h0 = float(s['height']) if s.get('height') is not None else float(H.at(px, pz))
        h1 = float(s['to_height']) if s.get('to_height') is not None else float(H.at(qx, qz))
        target = h0 + (h1 - h0) * np.clip(along / L, 0.0, 1.0)
        H.h += (target - H.h) * w * min(1.0, abs(strength))
        return
    w = falloff(np.hypot(X - px, Z - pz), radius, kind)
    if tool == 'raise':
        H.h += strength * w
    elif tool == 'lower':
        H.h -= strength * w
    elif tool == 'flatten':
        target = float(s['height']) if s.get('height') is not None else float(H.at(px, pz))
        H.h += (target - H.h) * w * min(1.0, abs(strength))
    elif tool == 'smooth':
        k = w * min(1.0, abs(strength))
        for _ in range(int(s.get('passes', 2))):
            H.h = H.h * (1 - k) + _blur(H.h) * k


# ------------------------------------------------------------------------------------------------ the grid
def build(t, out):
    """The Heights of a `terrain` key (or a flat plane when the map has none)."""
    if not t:
        return Heights(h=None)
    cell = float(t.get('cell', 2.0))
    if not 0.5 <= cell <= 16.0:
        raise MapgenError('terrain cell size must be between 0.5 and 16 metres')
    given = unpack_grid(t.get('heights'), float)
    if given is not None:
        if given.ndim != 2 or min(given.shape) < 2:
            raise MapgenError('terrain heights must be a grid of at least 2 x 2 points')
        nz, nx = given.shape[0] - 1, given.shape[1] - 1
    else:
        nx, nz = [int(v) for v in t.get('size', [60, 60])]
        if nx < 1 or nz < 1:
            raise MapgenError('terrain size must be at least 1 cell each way')
    if (nx + 1) * (nz + 1) > MAX_CELLS:
        raise MapgenError('terrain of %d x %d cells is too large (at most about %d points)' % (nx, nz, MAX_CELLS))
    org = t.get('origin')
    ox, oz = (float(org[0]), float(org[1])) if org else (-nx * cell / 2.0, -nz * cell / 2.0)
    if given is not None:
        h = given.copy()
    else:
        h = np.full((nz + 1, nx + 1), float(t.get('base', 0.0)))
        nz_ = t.get('noise')
        if nz_:
            r = rng('terrain-noise', nz_.get('seed', 1))
            h += float(nz_.get('amp', 2.0)) * (value_noise(nz + 1, nx + 1, float(nz_.get('scale', 40.0)) / cell, nz_.get('octaves', 3), r) - 0.5) * 2.0
    H = Heights(ox, oz, cell, h)
    for s in t.get('strokes') or []:
        apply_stroke(H, s)
    return H


# ------------------------------------------------------------------------------------------------ heightmap files
def export_raw(h):
    """Rows of little-endian float32 (z rows from the south edge, x along each row)."""
    return np.ascontiguousarray(np.asarray(h, dtype='<f4')).tobytes()


def import_raw(data, nx, nz):
    a = np.frombuffer(data, dtype='<f4')
    if a.size != (nx + 1) * (nz + 1):
        raise MapgenError('the raw file holds %d values; a %d x %d cell grid needs %d' % (a.size, nx, nz, (nx + 1) * (nz + 1)))
    return a.reshape(nz + 1, nx + 1).astype(float)


def _chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def export_png16(h, lo=None, hi=None):
    """A 16-bit greyscale PNG of the grid. Returns (bytes, lo, hi): the heights are lo at value 0 and hi at 65535."""
    h = np.asarray(h, dtype=float)
    lo = float(h.min()) if lo is None else float(lo)
    hi = float(h.max()) if hi is None else float(hi)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    v = np.clip(np.rint((h - lo) / (hi - lo) * 65535.0), 0, 65535).astype('>u2')
    rows = b''.join(b'\x00' + v[j].tobytes() for j in range(v.shape[0]))
    png = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', v.shape[1], v.shape[0], 16, 0, 0, 0, 0))
           + _chunk(b'IDAT', zlib.compress(rows, 6)) + _chunk(b'IEND', b''))
    return png, lo, hi


def import_png16(data, lo=0.0, hi=1.0):
    """Heights from a greyscale (8 or 16 bit; colour pictures use the red channel) PNG: 0 -> lo, full scale -> hi."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise MapgenError('this is not a PNG file')
    pos, idat, ihdr = 8, b'', None
    while pos + 8 <= len(data):
        n, tag = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if tag == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif tag == b'IDAT':
            idat += body
        pos += 12 + n
    if ihdr is None:
        raise MapgenError('the PNG has no header')
    w, hgt, depth, ctype, _, _, inter = ihdr
    if inter:
        raise MapgenError('interlaced PNG files are not supported: save it without interlacing')
    if depth not in (8, 16) or ctype not in (0, 2, 4, 6):
        raise MapgenError('use a greyscale PNG with 8 or 16 bits per pixel')
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bpp = ch * depth // 8
    stride = w * bpp
    raw = zlib.decompress(idat)
    if len(raw) != (stride + 1) * hgt:
        raise MapgenError('the PNG data has the wrong size')
    img = np.zeros((hgt, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    o = 0
    for j in range(hgt):
        f = raw[o]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=o + 1).astype(np.int32)
        o += stride + 1
        if f == 0:
            cur = line
        elif f == 1:
            cur = line.copy()
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif f == 2:
            cur = (line + prev) & 255
        elif f == 3:
            cur = line.copy()
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            cur = line.copy()
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 255
        else:
            raise MapgenError('the PNG uses an unknown filter')
        img[j] = cur
        prev = cur
    px = img.reshape(hgt, w, ch, depth // 8)
    if depth == 16:
        v = (px[:, :, 0, 0].astype(np.uint32) << 8 | px[:, :, 0, 1]).astype(float) / 65535.0
    else:
        v = px[:, :, 0, 0].astype(float) / 255.0
    return lo + v * (hi - lo)


def terrain_key_from_png(data, lo, hi, cell=2.0, origin=None):
    """A ready `terrain` key from a heightmap picture (the grid shape is the picture's size)."""
    h = import_png16(data, lo, hi)
    t = dict(cell=cell, heights=pack_grid(h))
    if origin:
        t['origin'] = list(origin)
    return t
