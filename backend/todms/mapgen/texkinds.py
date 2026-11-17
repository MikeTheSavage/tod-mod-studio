"""Procedural texture kinds for the ground, roads and water, added to the builder's own generator table at run time
(the vendored tex_gen.py stays untouched): dirt, grass, asphalt, foliage, water, and road with lane markings for 1 to 4 lanes.

All of them tile, are produced by the same numpy helpers as the shipped kinds, and are deterministic for a seed.
"""
import os
import sys

from . import core
from .core import np

_VENDOR = os.path.join(core.BACKEND, 'vendor', 'newmap')
if _VENDOR not in sys.path:
    sys.path.append(_VENDOR)
import tex_gen as TX  # noqa: E402

# pictures that carry alpha and what the engine does with it: 'cutout' = alpha test (shipped foliage, signs), 'blend' = alpha blend (glass, water)
ALPHA = dict(fence='cutout', glass='blend', water='blend', sea='blend')

ROAD_TILE_M = 8.0            # metres of road along v for one texture repeat


def gen_dirt(n, rng):
    low = TX.fbm(n, 4, 5, rng)
    mid = TX.fbm(n, 12, 3, rng)
    base = TX._mix(np.broadcast_to(TX._col(132, 100, 70), (n, n, 3)), np.broadcast_to(TX._col(96, 72, 50), (n, n, 3)), low)
    img = base * (0.86 + 0.20 * mid[..., None]) * (0.92 + 0.12 * rng.random((n, n))[..., None])
    pebble = (rng.random((n, n)) > 0.992)[..., None]
    return np.where(pebble, img * 1.25, img)


def gen_grass(n, rng):
    low = TX.fbm(n, 4, 5, rng)
    blade = TX.fbm(n, 32, 2, rng)
    base = TX._mix(np.broadcast_to(TX._col(86, 124, 52), (n, n, 3)), np.broadcast_to(TX._col(58, 92, 38), (n, n, 3)), low)
    img = base * (0.82 + 0.30 * blade[..., None]) * (0.92 + 0.12 * rng.random((n, n))[..., None])
    dry = (TX.fbm(n, 6, 3, rng) > 0.62)[..., None]
    return np.where(dry, img * np.array([1.25, 1.1, 0.8]), img)


def gen_asphalt(n, rng):
    low = TX.fbm(n, 6, 4, rng)
    base = TX._mix(np.broadcast_to(TX._col(58, 58, 60), (n, n, 3)), np.broadcast_to(TX._col(40, 40, 42), (n, n, 3)), low)
    grit = rng.random((n, n))
    img = base * (0.84 + 0.30 * grit[..., None])
    crack = TX.fbm(n, 8, 2, rng)
    return np.where((np.abs(crack - 0.5) < 0.012)[..., None], img * 0.55, img)


def gen_foliage(n, rng):
    low = TX.fbm(n, 6, 4, rng)
    leaf = TX.fbm(n, 24, 3, rng)
    base = TX._mix(np.broadcast_to(TX._col(52, 104, 40), (n, n, 3)), np.broadcast_to(TX._col(92, 140, 56), (n, n, 3)), low)
    return base * (0.70 + 0.50 * leaf[..., None])


def gen_water(n, rng):
    """RGBA: blue-green with soft ripples; alpha around 0.55 (the build patches the RGBA32 encoder to keep it)."""
    y, x = np.mgrid[0:n, 0:n] / float(n)
    w = TX.fbm(n, 6, 4, rng)
    rip = 0.5 + 0.5 * np.sin(2 * np.pi * (5 * x + 3 * y + 1.5 * w))
    base = TX._mix(np.broadcast_to(TX._col(34, 92, 118), (n, n, 3)), np.broadcast_to(TX._col(70, 140, 150), (n, n, 3)), rip * 0.6 + w * 0.4)
    a = np.clip(0.50 + 0.12 * rip + 0.08 * w, 0.0, 1.0)
    return np.concatenate([base, a[..., None]], axis=-1)


def gen_sea(n, rng):
    """RGBA: dark blue-green open water that is nearly opaque (alpha about 0.94), for a sea that lies over empty space: a see-through plane over
    the void behind it would only show the pale clear colour."""
    y, x = np.mgrid[0:n, 0:n] / float(n)
    w = TX.fbm(n, 6, 4, rng)
    rip = 0.5 + 0.5 * np.sin(2 * np.pi * (4 * x + 2 * y + 1.5 * w))
    base = TX._mix(np.broadcast_to(TX._col(16, 58, 84), (n, n, 3)), np.broadcast_to(TX._col(34, 96, 120), (n, n, 3)), rip * 0.5 + w * 0.5)
    a = np.clip(0.93 + 0.04 * rip, 0.0, 1.0)
    return np.concatenate([base, a[..., None]], axis=-1)


def gen_fence(n, rng):
    """RGBA, cut-out: a chain-link diamond mesh of thin wire (alpha 0 or 1 only, so the engine's alpha test cuts it out), with a post at the edge."""
    y, x = np.mgrid[0:n, 0:n] / float(n)
    cells = 6.0
    u, v = (x + y) * cells, (x - y) * cells
    du, dv = np.abs(u - np.round(u)), np.abs(v - np.round(v))
    wire = (np.minimum(du, dv) < 0.07)
    post = (x < 0.05) | (x > 0.95)
    a = (wire | post).astype(np.float64)
    grey = np.where(post, 0.38, 0.62 + 0.12 * rng.random((n, n)))
    rgb = np.stack([grey, grey * 1.02, grey * 1.06], axis=-1)
    return np.concatenate([np.clip(rgb, 0, 1), a[..., None]], axis=-1)


def gen_glass(n, rng):
    """RGBA, see-through: a pale blue-grey pane (alpha about 0.3) with a soft streak and a solid frame."""
    y, x = np.mgrid[0:n, 0:n] / float(n)
    streak = np.clip(1.0 - np.abs((x - y * 0.8) - 0.35) * 6.0, 0.0, 1.0) * 0.5
    frame = (x < 0.04) | (x > 0.96) | (y < 0.04) | (y > 0.96)
    base = np.stack([np.full((n, n), 0.62), np.full((n, n), 0.78), np.full((n, n), 0.86)], axis=-1) * (0.92 + 0.08 * rng.random((n, n))[..., None])
    rgb = np.where(frame[..., None], np.array([0.25, 0.27, 0.30]), np.clip(base + streak[..., None] * 0.25, 0, 1))
    a = np.where(frame, 1.0, 0.28 + 0.30 * streak)
    return np.concatenate([rgb, a[..., None]], axis=-1)


def _road(lanes):
    def gen(n, rng):
        """Asphalt with painted lines. u (x) runs across the road once, v (y) along it: dashed centre line (2 lanes), dashed
        lane lines (3 and 4 lanes) and a solid line at each edge."""
        img = gen_asphalt(n, rng).copy()
        x = (np.arange(n) + 0.5) / n
        y = (np.arange(n) + 0.5) / n
        white = np.array([0.88, 0.88, 0.84])
        yellow = np.array([0.90, 0.74, 0.18])

        def vline(cx, half, color, dashed):
            m = np.abs(x - cx) < half
            col = np.broadcast_to(m[None, :], (n, n)).copy()
            if dashed:
                col &= ((y * 2.0) % 1.0 < 0.5)[:, None]
            return col, color
        lines = [vline(0.04, 0.012, white, False), vline(0.96, 0.012, white, False)]
        if lanes == 2:
            lines += [vline(0.5, 0.010, yellow, True)]
        elif lanes >= 3:
            for k in range(1, lanes):
                lines += [vline(k / float(lanes), 0.009, white, True)]
        for m, color in lines:
            img = np.where(m[..., None], img * 0.25 + color * 0.75, img)
        return img
    return gen


def gen_skyline(n, rng):
    """A tower facade seen from far away: slate walls with rows of windows, a part of them lit."""
    low = TX.fbm(n, 4, 3, rng)
    wall = TX._mix(np.broadcast_to(TX._col(92, 104, 122), (n, n, 3)), np.broadcast_to(TX._col(70, 82, 102), (n, n, 3)), low)
    cols = max(2, n // 16)                                   # eight windows across one repeat at 128 px
    cell = n // cols
    yy, xx = np.mgrid[0:n, 0:n]
    fx, fy = (xx % cell) / float(cell), (yy % cell) / float(cell)
    win = (fx > 0.22) & (fx < 0.78) & (fy > 0.25) & (fy < 0.80)
    lit = rng.random((cols, cols)) < 0.30
    on = lit[(yy // cell) % cols, (xx // cell) % cols]
    glass = np.where(on[..., None], np.array([236.0, 204.0, 140.0]), np.array([38.0, 50.0, 72.0]))
    img = np.where(win[..., None], glass, wall * (0.88 + 0.16 * rng.random((n, n))[..., None]))
    return img


KINDS = dict(dirt=gen_dirt, grass=gen_grass, asphalt=gen_asphalt, foliage=gen_foliage, water=gen_water, sea=gen_sea, fence=gen_fence, glass=gen_glass, skyline=gen_skyline,
             road_l1=_road(1), road_l2=_road(2), road_l3=_road(3), road_l4=_road(4))


def road_kind(lanes):
    return 'road_l%d' % max(1, min(4, int(lanes)))


def _rgba32_payload(levels, alpha=None):
    out = bytearray()
    for l in levels:
        px = np.clip(np.rint(l * 255), 0, 255).astype(np.uint8)
        a = px[..., 3:4] if px.shape[-1] == 4 else np.full(px.shape[:2] + (1,), 255, dtype=np.uint8)
        out += np.concatenate([px[..., 2:3], px[..., 1:2], px[..., 0:1], a], axis=-1).tobytes()
    return bytes(out)


_installed = []


def register():
    """Add the kinds to the builder's table (idempotent) and let its RGBA32 encoder keep a fourth channel as alpha."""
    for k, f in KINDS.items():
        TX.KINDS[k] = f
    if not _installed:
        TX.rgba32_payload = _rgba32_payload
        _installed.append(True)
    return sorted(KINDS)


def render(kind, size, seed):
    """The generated picture (float, size x size x 3 or 4), for previews and tests."""
    register()
    return TX.generate(kind, size, seed)
