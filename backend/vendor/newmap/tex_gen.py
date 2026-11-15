"""tex_gen.py - procedural, tileable textures in the engine's own formats (DXT1 / RGBA32) and the TEXTURE asset record.

Nothing here is copied from the game or downloaded: every pixel comes from numpy noise.

  generate(kind, size, seed)            -> float RGB array (size, size, 3) in 0..1, tileable
  KINDS                                 sand, adobe, wood, metal, concrete, plaster, roof
  mip_chain(rgb)                        -> list of arrays down to 1x1 (box filter)
  dxt1_payload(levels) / rgba32_payload(levels)   engine payload bytes (all levels concatenated)
  texture_record(name, w, h, fmt, template_info, template_rec_offset)    -> TEXTURE record bytes (INFO part)
  build_texture(name, kind, size, fmt, seed, template_block)             -> (record bytes, payload bytes, preview rgb8)

Record layout (checked on all 166 textures of Map10's map block):
  obj 0x30 | name (4-aligned, NUL) | pad to 16 | GfxTexture 0x2C | TextureInfo 0x54 | pad to 16
  obj +0x04 -> name, +0x20 -> TextureInfo, +0x28 -> GfxTexture; GfxTexture +0x08 -> the record start
  GfxTexture: +0x0C/+0x10 resolution, +0x14/+0x18 surface w/h, +0x1C format (1 A8R8G8B8, 7 DXT1), +0x20 descriptor,
  +0x24 levels word (0xBAADF000 | levels << 1 | compressed), +0x28 mip mode (1 = full chain)
Payload = every mip level, each level `size_for_level` bytes (Texture::GetSizeForLevel 0x4633D0), a block's payload for
the texture record (one buffer per asset).
"""
import struct
import numpy as np
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import cpu_guard  # noqa: E402,F401  (keeps numpy off the faulty CPU cores, see cpu_guard.py)

FMT_A8R8G8B8, FMT_DXT1 = 1, 7
FMT = {'RGBA32': FMT_A8R8G8B8, 'DXT1': FMT_DXT1}
DESCRIPTOR = {FMT_A8R8G8B8: 2132104, FMT_DXT1: 262144}
MAX_PAYLOAD = 1_351_384          # largest shipped maximumAssetSize (TOD HD's per-texture cap)


def a4(x):
    return (x + 3) & ~3


def a16(x):
    return (x + 15) & ~15


# ---------------------------------------------------------------------------------------------- noise
def _periodic(n, cells, rng):
    """Smooth periodic value noise: n x n, `cells` random lattice points per side (wraps)."""
    g = rng.random((cells, cells))
    idx = np.arange(n, dtype=np.float64) * (float(cells) / n)      # 2b: int*int/int is miscomputed in SOME numpy 2.5.3 processes here (NOTES_2b.md)
    i0 = np.floor(idx).astype(int)
    f = idx - i0
    f = f * f * (3 - 2 * f)
    i1 = (i0 + 1) % cells
    a = g[i0][:, i0] * (1 - f)[None, :] * (1 - f)[:, None]
    b = g[i0][:, i1] * f[None, :] * (1 - f)[:, None]
    c = g[i1][:, i0] * (1 - f)[None, :] * f[:, None]
    d = g[i1][:, i1] * f[None, :] * f[:, None]
    return a + b + c + d


def fbm(n, base, octaves, rng, gain=0.5):
    out = np.zeros((n, n))
    amp, tot = 1.0, 0.0
    cells = base
    for _ in range(octaves):
        out += amp * _periodic(n, min(cells, n), rng)
        tot += amp
        amp *= gain
        cells *= 2
    return out / tot


def _mix(a, b, t):
    return a + (b - a) * t[..., None]


def _col(r, g, b):
    return np.array([r, g, b], dtype=np.float64) / 255.0


def _grid(n):
    y, x = np.mgrid[0:n, 0:n]
    return x / n, y / n


# ---------------------------------------------------------------------------------------------- generators
def gen_sand(n, rng):
    x, y = _grid(n)
    low = fbm(n, 4, 4, rng)
    grain = rng.random((n, n))
    rip = 0.5 + 0.5 * np.sin(2 * np.pi * (6 * y + 2.5 * fbm(n, 4, 3, rng)))      # wind ripples (period 1/6, tiles)
    base = _mix(np.broadcast_to(_col(214, 183, 128), (n, n, 3)), np.broadcast_to(_col(176, 140, 92), (n, n, 3)), low)
    img = base * (0.90 + 0.12 * grain[..., None]) * (0.93 + 0.10 * rip[..., None])
    spk = (rng.random((n, n)) > 0.985)[..., None]
    img = np.where(spk, img * 0.72, img)
    return img


def gen_adobe(n, rng):
    x, y = _grid(n)
    patch = fbm(n, 3, 5, rng)
    base = _mix(np.broadcast_to(_col(196, 146, 104), (n, n, 3)), np.broadcast_to(_col(158, 112, 78), (n, n, 3)), patch)
    grain = rng.random((n, n))
    img = base * (0.92 + 0.14 * grain[..., None])
    # mud-brick courses: 4 courses per tile, offset joints, thin dark mortar lines
    rows = 4
    ry = (y * rows) % 1.0
    row = np.floor(y * rows).astype(int)
    cols = 2
    rx = ((x * cols) + 0.5 * (row % 2)) % 1.0
    mortar = ((ry < 0.04) | (ry > 0.965) | (rx < 0.02) | (rx > 0.985)).astype(float)
    img = img * (1 - 0.28 * mortar[..., None])
    # hair cracks
    cr = np.abs(fbm(n, 6, 3, rng) - 0.5) < 0.0025
    img = np.where(cr[..., None], img * 0.62, img)
    return img


def gen_wood(n, rng):
    x, y = _grid(n)
    planks = 4
    px = (x * planks) % 1.0
    pid = np.floor(x * planks).astype(int)
    tint = rng.random(planks)[pid]
    warp = fbm(n, 3, 3, rng)
    gr = 0.5 + 0.5 * np.sin(2 * np.pi * (10 * px + 5 * warp + 3 * fbm(n, 2, 2, rng)))
    long_noise = fbm(n, 2, 4, rng)
    base = _mix(np.broadcast_to(_col(150, 104, 62), (n, n, 3)), np.broadcast_to(_col(105, 70, 40), (n, n, 3)), tint * 0.6 + 0.4 * gr)
    img = base * (0.85 + 0.25 * long_noise[..., None])
    gap = (px < 0.035) | (px > 0.975)
    img = np.where(gap[..., None], _col(38, 26, 16), img)
    # nail rows
    nail = (((y * 8) % 1.0) < 0.05) & (px > 0.45) & (px < 0.55)
    img = np.where(nail[..., None], _col(60, 52, 48), img)
    return img


def gen_metal(n, rng):
    x, y = _grid(n)
    rib = 0.5 + 0.5 * np.sin(2 * np.pi * 8 * x)                                  # corrugation
    base = np.broadcast_to(_col(122, 134, 140), (n, n, 3)) * (0.62 + 0.38 * rib[..., None])
    rust = fbm(n, 4, 5, rng)
    rust_mask = np.clip((rust - 0.52) * 5.0, 0, 1) * (0.5 + 0.5 * fbm(n, 8, 3, rng))
    rust_col = _mix(np.broadcast_to(_col(150, 82, 38), (n, n, 3)), np.broadcast_to(_col(104, 52, 28), (n, n, 3)), fbm(n, 8, 3, rng))
    img = _mix(base, rust_col * (0.7 + 0.3 * rib[..., None]), rust_mask)
    img = img * (0.94 + 0.10 * rng.random((n, n))[..., None])
    return img


def gen_concrete(n, rng):
    low = fbm(n, 3, 5, rng)
    base = _mix(np.broadcast_to(_col(160, 158, 150), (n, n, 3)), np.broadcast_to(_col(118, 116, 110), (n, n, 3)), low)
    img = base * (0.90 + 0.16 * rng.random((n, n))[..., None])
    x, y = _grid(n)
    joint = (np.abs(((x * 2) % 1.0) - 0.0) < 0.012) | (((x * 2) % 1.0) > 0.988) | (((y * 2) % 1.0) < 0.012) | (((y * 2) % 1.0) > 0.988)
    img = np.where(joint[..., None], img * 0.55, img)
    stain = np.clip((fbm(n, 5, 4, rng) - 0.55) * 4, 0, 1)
    return img * (1 - 0.25 * stain[..., None])


def gen_plaster(n, rng):
    """Whitewashed plaster for the compound's inner walls (lighter than adobe)."""
    low = fbm(n, 3, 5, rng)
    base = _mix(np.broadcast_to(_col(226, 214, 190), (n, n, 3)), np.broadcast_to(_col(196, 180, 152), (n, n, 3)), low)
    img = base * (0.94 + 0.10 * rng.random((n, n))[..., None])
    dirt = np.clip((fbm(n, 4, 5, rng) - 0.5) * 3, 0, 1)
    return img * (1 - 0.30 * dirt[..., None])


def gen_roof(n, rng):
    x, y = _grid(n)
    rows = 8
    ry = (y * rows) % 1.0
    tile = 0.55 + 0.45 * np.sin(np.pi * ry) ** 0.7
    tint = fbm(n, 4, 3, rng)
    base = _mix(np.broadcast_to(_col(168, 84, 56), (n, n, 3)), np.broadcast_to(_col(120, 56, 38), (n, n, 3)), tint)
    img = base * tile[..., None] * (0.92 + 0.12 * rng.random((n, n))[..., None])
    return img


def gen_cliff(n, rng):
    """Sandstone strata for the mesa's cliff faces and boulders."""
    x, y = _grid(n)
    warp = fbm(n, 4, 4, rng)
    band = 0.5 + 0.5 * np.sin(2 * np.pi * (7 * y + 0.45 * warp))
    band2 = 0.5 + 0.5 * np.sin(2 * np.pi * (19 * y + 0.9 * warp + 0.3))
    base = _mix(np.broadcast_to(_col(182, 112, 72), (n, n, 3)), np.broadcast_to(_col(140, 84, 56), (n, n, 3)), band)
    base = _mix(base, np.broadcast_to(_col(208, 160, 112), (n, n, 3)), band2 * 0.35)
    streak = fbm(n, 12, 3, rng)
    img = base * (0.84 + 0.22 * streak[..., None]) * (0.92 + 0.10 * rng.random((n, n))[..., None])
    return img


KINDS = dict(cliff=gen_cliff, sand=gen_sand, adobe=gen_adobe, wood=gen_wood, metal=gen_metal, concrete=gen_concrete, plaster=gen_plaster,
             roof=gen_roof)


def generate(kind, size, seed=1):
    if kind not in KINDS:
        raise ValueError('unknown texture kind %r (%s)' % (kind, ', '.join(KINDS)))
    rng = np.random.default_rng(seed)
    return np.clip(KINDS[kind](size, rng), 0.0, 1.0)


# ---------------------------------------------------------------------------------------------- mips and encoders
def mip_chain(rgb):
    out = [rgb]
    cur = rgb
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = cur.shape[:2]
        if h > 1 and w > 1:
            cur = (cur[0::2, 0::2] + cur[1::2, 0::2] + cur[0::2, 1::2] + cur[1::2, 1::2]) * 0.25
        elif w > 1:
            cur = (cur[:, 0::2] + cur[:, 1::2]) * 0.5
        else:
            cur = (cur[0::2] + cur[1::2]) * 0.5
        out.append(cur)
    return out


def _to565(c):
    r = np.clip(np.rint(c[..., 0] * 31), 0, 31).astype(np.uint16)
    g = np.clip(np.rint(c[..., 1] * 63), 0, 63).astype(np.uint16)
    b = np.clip(np.rint(c[..., 2] * 31), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _from565(v):
    r = ((v >> 11) & 31) / 31.0
    g = ((v >> 5) & 63) / 63.0
    b = (v & 31) / 31.0
    return np.stack([r, g, b], axis=-1)


def dxt1_level(rgb):
    """One mip level -> DXT1 bytes (8 bytes per 4x4 block; images smaller than 4 are padded by edge replication)."""
    h, w = rgb.shape[:2]
    H, W = max(h, 4), max(w, 4)
    if (H, W) != (h, w):
        rgb = np.pad(rgb, ((0, H - h), (0, W - w), (0, 0)), mode='edge')
    bh, bw = H // 4, W // 4
    blocks = rgb.reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 3)
    mn, mx = blocks.min(1), blocks.max(1)
    inset = (mx - mn) / 16.0
    mn, mx = mn + inset, mx - inset
    c0 = _to565(mx)
    c1 = _to565(mn)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1                                              # solid block: force the 4-colour mode with c0 > c1
    c0 = np.where(eq & (c0 < 0xFFFF), c0 + 1, c0)
    p0, p1 = _from565(c0), _from565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)           # (n, 4, 3)
    d = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)                   # (n, 16, 4)
    idx = d.argmin(-1).astype(np.uint32)
    bits = np.zeros(len(idx), dtype=np.uint32)
    for i in range(16):
        bits |= idx[:, i] << (2 * i)
    out = np.zeros(len(idx), dtype=[('c0', '<u2'), ('c1', '<u2'), ('b', '<u4')])
    out['c0'], out['c1'], out['b'] = c0, c1, bits
    return out.tobytes()


def dxt1_decode_level(data, w, h):
    """Decoder for the self-check (and previews)."""
    H, W = max(h, 4), max(w, 4)
    n = (H // 4) * (W // 4)
    a = np.frombuffer(data[:8 * n], dtype=[('c0', '<u2'), ('c1', '<u2'), ('b', '<u4')])
    p0, p1 = _from565(a['c0'].astype(np.uint16)), _from565(a['c1'].astype(np.uint16))
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)
    px = np.zeros((n, 16, 3))
    for i in range(16):
        k = (a['b'] >> (2 * i)) & 3
        px[:, i] = pal[np.arange(n), k]
    img = px.reshape(H // 4, W // 4, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(H, W, 3)
    return img[:h, :w]


def dxt1_payload(levels):
    return b''.join(dxt1_level(l) for l in levels)


def rgba32_payload(levels, alpha=None):
    out = bytearray()
    for l in levels:
        px = np.clip(np.rint(l * 255), 0, 255).astype(np.uint8)
        a = np.full(px.shape[:2] + (1,), 255, dtype=np.uint8)
        bgra = np.concatenate([px[..., 2:3], px[..., 1:2], px[..., 0:1], a], axis=-1)      # A8R8G8B8 = B,G,R,A bytes
        out += bgra.tobytes()
    return bytes(out)


def size_for_level(w, h, level, compressed, bpp):
    """Texture::GetSizeForLevel @0x4633D0."""
    ww, hh = max(w >> level, 1), max(h >> level, 1)
    if compressed:
        return 8 * max(ww // 4, 1) * max(hh // 4, 1)
    return ((bpp & 0x3F) * hh * ww) >> 3


def payload_size(fmt, w, h, levels):
    comp = FMT[fmt] == FMT_DXT1
    return a4(sum(size_for_level(w, h, L, comp, 4 if comp else 32) for L in range(levels)))


# ---------------------------------------------------------------------------------------------- the record
def texture_record(name, w, h, fmt, levels, tmpl):
    """TEXTURE record bytes. tmpl: raw bytes of a shipped record of the SAME format (its GfxTexture and TextureInfo are
    copied and patched). Verified layout: see the module docstring."""
    code = FMT[fmt]
    nb = name.encode('latin-1') + b'\0'
    G = a16(0x30 + a4(len(nb)))
    T = G + 0x2C
    end = T + 0x54
    # template parts
    tT = struct.unpack_from('<i', tmpl, 0x20)[0] + 0x20
    tG = struct.unpack_from('<i', tmpl, 0x28)[0] + 0x28
    if tG + 0x2C > tT or tT + 0x54 > len(tmpl):
        raise ValueError('unexpected template layout')
    gfx = bytearray(tmpl[tG:tG + 0x2C])
    ti = bytearray(tmpl[tT:tT + 0x54])
    if struct.unpack_from('<i', gfx, 0x1C)[0] != code:
        raise ValueError('template format differs from %s' % fmt)
    rec = bytearray(a16(end))
    rec[0:0x30] = tmpl[0:0x30]
    struct.pack_into('<i', rec, 0x04, 0x30 - 0x04)
    struct.pack_into('<i', rec, 0x20, T - 0x20)
    struct.pack_into('<i', rec, 0x28, G - 0x28)
    rec[0x30:0x30 + len(nb)] = nb
    lw = struct.unpack_from('<I', gfx, 0x24)[0]
    lw = (lw & ~0x1FF) | (levels << 1) | (1 if code == FMT_DXT1 else 0)
    struct.pack_into('<II', gfx, 0x0C, w, h)
    struct.pack_into('<II', gfx, 0x14, w, h)
    struct.pack_into('<I', gfx, 0x24, lw)
    struct.pack_into('<I', gfx, 0x28, 1 if levels > 1 else 0)
    struct.pack_into("<i", gfx, 0x08, -(G + 8))           # surface bits -> the record start
    for o in (0x34, 0x3C, 0x44, 0x4C):                       # TextureInfo repeats (w, h) pairs from +0x34
        struct.pack_into('<II', ti, o, w, h)
    rec[G:G + 0x2C] = gfx
    rec[T:T + 0x54] = ti
    return bytes(rec)


def full_chain(w, h):
    return max(w, h).bit_length()


def build_texture(name, kind_or_rgb, size, fmt, seed, templates):
    """-> (record bytes, payload bytes, preview uint8 array). templates: {'DXT1': rec bytes, 'RGBA32': rec bytes}."""
    rgb = generate(kind_or_rgb, size, seed) if isinstance(kind_or_rgb, str) else kind_or_rgb
    h, w = rgb.shape[:2]
    if w & (w - 1) or h & (h - 1):
        raise ValueError('texture size must be a power of two')
    if fmt == 'DXT1' and (w < 4 or h < 4):
        raise ValueError('DXT1 needs at least 4x4')
    levels = mip_chain(rgb)
    payload = dxt1_payload(levels) if fmt == 'DXT1' else rgba32_payload(levels)
    want = payload_size(fmt, w, h, len(levels))
    if len(payload) != want:
        raise ValueError('%s: payload %d bytes, the engine will copy %d' % (name, len(payload), want))
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('%s: %d bytes is over the %d byte cap' % (name, len(payload), MAX_PAYLOAD))
    rec = texture_record(name, w, h, fmt, full_chain(w, h), templates[fmt])
    prev = np.clip(np.rint((dxt1_decode_level(dxt1_level(rgb), w, h) if fmt == 'DXT1' else rgb) * 255), 0, 255).astype(np.uint8)
    return rec, payload, prev


def find_templates(info, starts, n):
    """Pick one shipped DXT1 and one RGBA32 record (as bytes) out of a block's INFO."""
    out = {}
    ends = list(starts[1:]) + [len(info)]
    for R, E in zip(starts, ends):
        if struct.unpack_from('<I', info, R)[0] != 0:
            continue
        G = R + 0x28 + struct.unpack_from('<i', info, R + 0x28)[0]
        code = struct.unpack_from('<i', info, G + 0x1C)[0]
        key = {FMT_A8R8G8B8: 'RGBA32', FMT_DXT1: 'DXT1'}.get(code)
        T = R + 0x20 + struct.unpack_from('<i', info, R + 0x20)[0]
        usual = struct.unpack_from('<3I', info, T + 0x28) == (4, 0x20, 0xBAADF145)       # the common TextureInfo header
        if key and key not in out and usual:
            out[key] = bytes(info[R:E])
    if set(out) != {'DXT1', 'RGBA32'}:
        raise ValueError('block has no DXT1 + RGBA32 texture to use as a template')
    return out
