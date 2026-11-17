"""Baked lighting for new geometry: per-vertex colours from the map's own sun, ambient light and shadows.

The original maps get their look from per-vertex colours stored in the block's lighting record (see `lightrec.py`). The same colours
are computed here for a new map's meshes:

  * sun: direction and colour of the map's `look`, N.L, with a shadow ray per vertex against every triangle of the map (`raycast.Tree`)
  * sky: the ambient colour, darkened by the share of the hemisphere above the vertex that is blocked (a few rays of a fixed pattern)
  * the result is clamped to 0..1 and written as the engine's D3DCOLOR (alpha 255)

The result is deterministic: fixed ray patterns rotated by a hash of the vertex position (so shared edges of neighbouring meshes agree),
pure numpy, no thread dependence. Settings are measured against a shipped map (tests: `test_bake.py`, `calibrate()`).
"""
import math
import struct

import numpy as np

from . import paths, raycast
from . import hdblock as _hdblock

QUALITY = {
    # sun rays per vertex, sun cone (radians, half angle), sky rays per vertex, sky ray length (m)
    'draft': dict(sun=1, cone=0.0, sky=4, reach=8.0),
    'normal': dict(sun=3, cone=0.025, sky=8, reach=12.0),
    'high': dict(sun=6, cone=0.03, sky=16, reach=16.0),
}
DEFAULT_QUALITY = 'normal'

# measured against the shipped bakes (bakecal.py, tests/test_bake.py): a shipped vertex is the flat ambient colour plus the sun colour
# times N.L, clamped to 1; shadows from the map's own triangles. Sky occlusion is not in the shipped bakes: it only darkens the ambient
# share here (AO_STRENGTH), so a pit or an alley reads darker than open ground.
GAIN_AMBIENT = 1.0
GAIN_SUN = 1.0
AO_STRENGTH = 0.6
SURFACE_EPS = 0.03       # shadow rays start this far off the surface along the normal (m)
SHADOW_START = 0.5       # surfaces closer than this along the ray are layers of the same ground (roads on terrain), not shadow casters
SHADOW_REACH = 150.0     # shadows are cast over at most this distance (m); long enough for a 90 m shadow of a 50 m tower at 29 degrees
SKY_START = 0.05

# the engine's aim axis of a directional light in the light node's own frame; the direction is rotated by the CONJUGATE of the stored
# orient (the block keeps the inverse of the node's world rotation). Measured: of the six axes and both rotation senses this one predicts
# the brightness of shipped walls best on all four shipped maps with a baked sun (tests/test_bake.py).
SUN_AXIS = (0.0, 0.0, 1.0)


class BakeError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ looks
def rotate(q, v):
    """Rotate vector(s) v by the quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    v = np.asarray(v, np.float64)
    t = 2.0 * np.cross(np.array([x, y, z]), v)
    return v + w * t + np.cross(np.array([x, y, z]), t)


def sun_direction(orient, axis=None):
    """Unit vector the sunlight travels along (from the sun to the ground) for a light node's orient quaternion as it is stored
    in the block (the fragment writer keeps the inverse: world rotation = conjugate)."""
    q = np.asarray(orient, np.float64)
    q = q / (np.linalg.norm(q) or 1.0)
    conj = (-q[0], -q[1], -q[2], q[3])
    d = rotate(conj, np.asarray(axis if axis is not None else SUN_AXIS, np.float64))
    return d / (np.linalg.norm(d) or 1.0)


def colour3(c, k=1.0):
    return np.asarray(c[:3], np.float64) * float(k)


def look_lights(lighting):
    """The map's `lighting` dict (from `mapgen.look.resolve`) -> dict(sun_dir, sun, ambient): the vectors the bake needs.
    sun / ambient are linear rgb multipliers (colour x brightness)."""
    if not lighting:
        raise BakeError('the map has no look to bake with')
    s = lighting.get('sun') or {}
    a = lighting.get('ambient') or {}
    if 'orient' not in s:
        raise BakeError('the sun has no direction')
    return dict(sun_dir=sun_direction(s['orient']),
                sun=colour3(s.get('static_color') or s.get('color') or (1, 1, 1), s.get('brightness', 1.0)),
                ambient=colour3(a.get('static_color') or a.get('color') or (0.4, 0.4, 0.4), a.get('brightness', 0.6)))


# ------------------------------------------------------------------------------------------------ model records
def read_models(raw, ext):
    """Every model record of a block -> {lower name: dict(pivots: [[mesh]])}, mesh = dict(P (n,3), N (n,3), I (m,) uint16, flags).
    Positions and normals are in the model's own space (pivot-local)."""
    from .lightfit import hl
    hl()
    import tod_hd_game as G
    blk = _hdblock.Block(raw, ext)
    info = bytes(blk.info)
    out = {}

    def sp(o, lo, hi):
        v = struct.unpack_from('<I', info, o)[0]
        if v == 0:
            return None
        t = (o + v) & 0xFFFFFFFC
        if not lo <= t < hi:
            raise BakeError('a model pointer leaves its record')
        return t

    for r in blk.records:
        if r['type'] != 3:
            continue
        R, E = r['offset'], r['end']
        pl = sp(R + 0x30, R, E)
        n_piv = struct.unpack_from('<I', info, R + 0x34)[0]
        pivots = []
        for i in range(n_piv):
            P = pl + 0x7C * i
            sl = sp(P + 0x24, R, E)
            meshes = []
            for j in range(struct.unpack_from('<I', info, P + 0x28)[0]):
                S = sl + 0x3C * j
                mb = sp(S, R, E)
                vb, ib = sp(mb + 0x0C, R, E), sp(mb + 0x10, R, E)
                vc, ic = struct.unpack_from('<I', info, vb)[0], struct.unpack_from('<I', info, ib)[0]
                stride = struct.unpack_from('<H', info, vb + 0x14)[0]
                fvf = struct.unpack_from('<I', info, vb + 0x08)[0]
                vd, idd = sp(vb + 0x10, R, E), sp(ib + 0x0C, R, E)
                if vc * stride + vd > E or idd + 2 * ic > E:
                    raise BakeError('a model mesh is inconsistent')
                buf = np.frombuffer(info, np.uint8, vc * stride, vd).reshape(vc, stride) if vc else np.zeros((0, stride), np.uint8)
                P3 = np.ascontiguousarray(buf[:, 0:12]).view('<f4').reshape(vc, 3).astype(np.float64)
                N3 = (np.ascontiguousarray(buf[:, 12:24]).view('<f4').reshape(vc, 3).astype(np.float64)
                      if fvf & 0x10 and stride >= 24 else None)
                idx = np.frombuffer(info, '<u2', ic, idd).astype(np.int64) if ic else np.zeros(0, np.int64)
                is_list = bool(struct.unpack_from('<I', info, ib + 4)[0])
                meshes.append(dict(P=P3, N=N3, I=idx if is_list else strip_to_list(idx), RI=idx.astype(np.uint16), flags=struct.unpack_from('<I', info, S + 0x38)[0], fvf=fvf,
                                   strip=not is_list, raw_indices=len(idx)))
            pivots.append(meshes)
        out[r['name'].lower()] = dict(name=r['name'], pivots=pivots)
    return out


def strip_to_list(idx):
    """Triangle strip indices -> triangle list (flat), degenerate triangles dropped, every second triangle turned back."""
    idx = np.asarray(idx, np.int64)
    if len(idx) < 3:
        return np.zeros(0, np.int64)
    a, b, c = idx[:-2], idx[1:-1], idx[2:]
    odd = (np.arange(len(a)) & 1).astype(bool)
    t = np.stack([np.where(odd, b, a), np.where(odd, a, b), c], 1)
    ok = (a != b) & (b != c) & (a != c)
    return t[ok].reshape(-1)


def face_normals(P, I):
    t = I.reshape(-1, 3)
    a, b, c = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]
    return np.cross(b - a, c - a)


def vertex_normals(P, I):
    """Area-weighted vertex normals from the triangles (used when a mesh carries none)."""
    N = np.zeros_like(P)
    fn = face_normals(P, I)
    for k in range(3):
        np.add.at(N, I.reshape(-1, 3)[:, k], fn)
    n = np.linalg.norm(N, axis=1)
    N[n > 0] /= n[n > 0][:, None]
    return N


# ------------------------------------------------------------------------------------------------ the bake
def _hash_angle(P):
    """A per-position angle in 0..2pi from the position rounded to a millimetre: equal positions get equal rays."""
    q = np.round(np.asarray(P, np.float64) * 1000.0).astype(np.int64)
    h = (q[:, 0] * 73856093) ^ (q[:, 1] * 19349663) ^ (q[:, 2] * 83492791)
    h = (h ^ (h >> 13)) * 1274126177
    h = h ^ (h >> 16)
    return (h & 0xFFFF).astype(np.float64) / 65536.0 * (2.0 * math.pi)


def _frames(N):
    """Two unit tangents for each normal."""
    up = np.where(np.abs(N[:, 1:2]) < 0.9, np.array([[0.0, 1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]))
    t = np.cross(N, up)
    t /= np.maximum(np.linalg.norm(t, axis=1), 1e-12)[:, None]
    return t, np.cross(N, t)


def _cosine_dirs(N, ang, k, n):
    """k-th of n cosine-distributed hemisphere directions around each normal (a fixed spiral, rotated per vertex)."""
    u = (k + 0.5) / n
    r = math.sqrt(u)
    phi = ang + k * 2.399963229728653                      # golden angle
    t, b = _frames(N)
    return (t * (r * np.cos(phi))[:, None] + b * (r * np.sin(phi))[:, None] + N * math.sqrt(1.0 - u))


def _cone_edges(axis, cone):
    """Four directions on the edge of the sun's cone (for the open-ground test)."""
    if cone <= 0.0:
        return []
    t, b = _frames(np.asarray(axis, np.float64)[None, :])
    out = []
    for v in (t[0], -t[0], b[0], -b[0]):
        d = axis + v * cone
        out.append(d / np.linalg.norm(d))
    return out


def bake_vertices(P, N, lights, tree, quality=DEFAULT_QUALITY, progress=None):
    """P, N: (n, 3) world positions and unit normals. -> float (n, 3) colours 0..1 (not yet clamped from above) plus a dict of stats."""
    paths.ensure_cpu_guard()
    q = QUALITY[quality]
    n = len(P)
    P = np.asarray(P, np.float64)
    N = np.asarray(N, np.float64)
    ang = _hash_angle(P)
    sun_to = -np.asarray(lights['sun_dir'], np.float64)
    ndl = np.clip(N @ sun_to, 0.0, 1.0)
    lit = np.zeros(n)
    todo = np.nonzero(ndl > 1e-4)[0]
    origin = P + N * SURFACE_EPS
    if len(todo):
        # most ground is open: a coarse march over the height grid clears those vertices without a single ray (never wrong the other way)
        clear = tree.clear_sun(origin[todo], sun_to, SHADOW_REACH, SHADOW_START)
        for dv in _cone_edges(sun_to, QUALITY[quality]['cone']):
            clear &= tree.clear_sun(origin[todo], dv, SHADOW_REACH, SHADOW_START)
        lit[todo[clear]] = 1.0
        todo = todo[~clear]
        rep_clear = int(clear.sum())
    else:
        rep_clear = 0
    if len(todo):
        nsun = q['sun']
        acc = np.zeros(len(todo))
        for k in range(nsun):
            d = np.tile(sun_to, (len(todo), 1))
            if q['cone'] > 0.0 and nsun > 1:
                t, b = _frames(np.tile(sun_to, (len(todo), 1)))
                phi = ang[todo] + k * 2.399963229728653
                r = q['cone'] * math.sqrt((k + 0.5) / nsun)
                d = d + t * (r * np.cos(phi))[:, None] + b * (r * np.sin(phi))[:, None]
                d /= np.linalg.norm(d, axis=1)[:, None]
            acc += ~tree.occluded(origin[todo], d, SHADOW_REACH, tmin=SHADOW_START)
            if progress:
                progress(0.5 * (k + 1) / nsun)
        lit[todo] = acc / nsun
    open_ = np.zeros(n)
    nsky = q['sky']
    for k in range(nsky):
        d = _cosine_dirs(N, ang, k, nsky)
        open_ += ~tree.occluded(origin, d, q['reach'], tmin=SKY_START)
        if progress:
            progress(0.5 + 0.5 * (k + 1) / nsky)
    open_ /= nsky
    sky = 1.0 - AO_STRENGTH * (1.0 - open_)
    col = (GAIN_AMBIENT * sky)[:, None] * lights['ambient'][None, :] + (GAIN_SUN * ndl * lit)[:, None] * lights['sun'][None, :]
    return col, dict(sun_lit=float(lit.mean()) if n else 0.0, sky_open=float(open_.mean()) if n else 0.0, sun_cleared=rep_clear)


# Output level measured on the baked vertex colours of the shipped city sections (Downtown 0.514 mean luminance, Industrial 0.472; both have a
# floor of 0.249 and 90 % of the vertices at 1.0): a bake of a dense district with plain sun and ambient comes out far darker (0.31), because most
# faces turn away from the sun, so the colours are lifted to the shipped floor and scaled to the shipped mean.
LEVEL_TARGET_MEAN = 0.50
LEVEL_FLOOR = 0.249


def calibrate_level(col, target=LEVEL_TARGET_MEAN, floor=LEVEL_FLOOR):
    """col (n, 3) 0..1 -> (colours, dict(gain, lift, mean_before, mean_after)): every vertex lifted to the shipped floor luminance, then one gain
    (found by bisection, 1 or more) so the mean luminance after the clamp reaches `target`. Hue is kept (the lift is grey)."""
    col = np.asarray(col, np.float64)
    if not len(col):
        return col, dict(gain=1.0, lift=0.0, mean_before=0.0, mean_after=0.0)
    lum = np.clip(col, 0.0, 1.0) @ LUM_W
    before = float(lum.mean())
    c = np.clip(col, 0.0, 1.0)
    lift = np.maximum(0.0, floor - lum)
    c = c + lift[:, None]
    lo, hi = 1.0, 8.0
    mean_at = lambda g: float((np.clip(c * g, 0.0, 1.0) @ LUM_W).mean())      # noqa: E731
    if mean_at(1.0) >= target:
        g = 1.0
    else:
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if mean_at(mid) < target else (lo, mid)
        g = (lo + hi) / 2
    out = np.clip(c * g, 0.0, 1.0)
    return out, dict(gain=round(g, 3), lift=round(float(lift.mean()), 4), mean_before=round(before, 4), mean_after=round(float((out @ LUM_W).mean()), 4))


LUM_W = np.array([0.299, 0.587, 0.114])


def to_d3dcolor(c):
    """float (n, 3) 0..1 -> uint32 0xAARRGGBB with alpha 255."""
    v = np.clip(np.rint(np.asarray(c, np.float64) * 255.0), 0, 255).astype(np.uint32)
    return (np.uint32(0xFF000000) | (v[:, 0] << np.uint32(16)) | (v[:, 1] << np.uint32(8)) | v[:, 2]).astype(np.uint32)


def from_d3dcolor(c):
    c = np.asarray(c, np.uint32)
    return np.stack([(c >> 16) & 255, (c >> 8) & 255, c & 255], 1).astype(np.float64) / 255.0
