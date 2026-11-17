"""Texture toolkit of Mod Studio: read an image, edit it, encode it as a TOD texture payload (DXT1 or A8R8G8B8), decode a
payload back. numpy only (no PIL in the packaged app); PIL is used for reading when it happens to be installed.

Images are float32 RGBA arrays (h, w, 4), straight (not premultiplied) alpha, values 0..1.

Encoders
  DXT1     per 4x4 block: principal-axis endpoints refined by least squares, compared with the plain bounding-box endpoints,
           the lower error wins. A block that holds a transparent texel (alpha below the cut) uses the 3-colour mode
           with the 1-bit transparent index (the shape shipped cut-out foliage uses).
  RGBA32   B, G, R, A bytes (D3DFMT_A8R8G8B8).
Mip chains are box filtered on premultiplied colour down to 1x1 (the full chain: the engine's mip mode 1).
"""
import colorsys  # noqa: F401  (kept for readers of the hue code below)
import io
import math
import os
import struct
import zlib

import numpy as np

FMT = ('DXT1', 'RGBA32')
ALPHA_MODES = ('keep', 'opaque', 'threshold')
MAX_DIM = 4096
TEXTURE_CAP = 1351384            # P6: per-texture payload policy
LOAD_BUFFER_CAP = 2796216        # P5: the largest payload proven in a block


class TextureError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- sizes
def is_pow2(n):
    return n > 0 and n & (n - 1) == 0


def full_chain(w, h):
    return max(w, h).bit_length()


def level_size(fmt, w, h, level):
    ww, hh = max(w >> level, 1), max(h >> level, 1)
    if fmt == 'DXT1':
        return 8 * max(ww // 4, 1) * max(hh // 4, 1)
    return ww * hh * 4


def payload_size(fmt, w, h, levels):
    return (sum(level_size(fmt, w, h, L) for L in range(levels)) + 3) & ~3


def max_dim_for_cap(fmt, cap=TEXTURE_CAP):
    """The largest square power-of-two side whose full-chain payload stays within the cap."""
    s = 4
    while s * 2 <= MAX_DIM and payload_size(fmt, s * 2, s * 2, full_chain(s * 2, s * 2)) <= cap:
        s *= 2
    return s


def fit_for_cap(fmt, w, h, cap=TEXTURE_CAP):
    """Halve both sides until the full chain fits the cap; returns (w, h)."""
    while payload_size(fmt, w, h, full_chain(w, h)) > cap and max(w, h) > 4:
        w, h = max(w // 2, 1), max(h // 2, 1)
    return w, h


# ---------------------------------------------------------------------------------------------- PNG
def png_bytes(img, alpha=None):
    """float RGBA (h, w, 4) or uint8 (h, w, 3|4) -> PNG bytes. alpha None: written when any texel is not opaque."""
    a = np.asarray(img)
    if a.dtype != np.uint8:
        a = np.clip(np.rint(a * 255.0), 0, 255).astype(np.uint8)
    h, w = a.shape[:2]
    if a.shape[2] == 3:
        a = np.concatenate([a, np.full((h, w, 1), 255, np.uint8)], axis=2)
    use_alpha = bool((a[..., 3] < 255).any()) if alpha is None else alpha
    ch = a if use_alpha else a[..., :3]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), ch.reshape(h, -1)], axis=1).tobytes()

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6 if use_alpha else 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))


def read_png(data):
    """Pure python/numpy PNG reader (non-interlaced; depths 1-16; all colour types) -> float RGBA."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise TextureError('not a PNG')
    pos, idat, plte, trns, hdr = 8, [], None, None, None
    while pos < len(data):
        n, t = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if t == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', body)
        elif t == b'PLTE':
            plte = np.frombuffer(body, np.uint8).reshape(-1, 3)
        elif t == b'tRNS':
            trns = np.frombuffer(body, np.uint8)
        elif t == b'IDAT':
            idat.append(body)
        elif t == b'IEND':
            break
    w, h, depth, ctype, _, _, interlace = hdr
    if interlace:
        raise TextureError('interlaced PNG files are not supported: save it without interlacing')
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = depth * nch
    bpp = max(1, bits // 8)
    stride = (w * bits + 7) // 8
    raw = np.frombuffer(zlib.decompress(b''.join(idat)), np.uint8).reshape(h, stride + 1)
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.uint8)
    for y in range(h):
        f = raw[y, 0]
        line = raw[y, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 1:
            cur = line.copy()
            if stride % bpp == 0:
                cur = np.cumsum(cur.reshape(-1, bpp), axis=0).reshape(-1) & 255
            else:
                for i in range(bpp, stride):
                    cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif f == 2:
            cur = (line + prev) & 255
        elif f == 3:
            cur = line.copy()
            pv = prev.astype(np.int32)
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + pv[i]) >> 1)) & 255
        elif f == 4:
            cur = line.copy()
            pv = prev.astype(np.int32)
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                c = pv[i - bpp] if i >= bpp else 0
                b = pv[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 255
        else:
            raise TextureError('bad PNG filter')
        out[y] = cur.astype(np.uint8)
        prev = out[y]
    if depth == 8:
        px = out.reshape(h, w, nch).astype(np.float32)
        if ctype != 3:
            px = px / 255.0
    elif depth == 16:
        px = (out.reshape(h, w, nch, 2).astype(np.uint32) @ np.array([256, 1], np.uint32)).astype(np.float32) / 65535.0
    else:
        bitsarr = np.unpackbits(out, axis=1)
        if depth == 8 // 8:                                  # 1 bit
            idx = bitsarr[:, :w * nch]
        else:
            g = bitsarr[:, :w * depth * nch].reshape(h, w * nch, depth)
            idx = (g * (1 << np.arange(depth - 1, -1, -1))).sum(-1)
        px = idx.reshape(h, w, nch).astype(np.float32)
        if ctype != 3:
            px = px / float((1 << depth) - 1)
    if ctype == 0:
        rgba = np.concatenate([np.repeat(px, 3, 2), np.ones((h, w, 1), np.float32)], 2)
    elif ctype == 4:
        rgba = np.concatenate([np.repeat(px[..., :1], 3, 2), px[..., 1:2]], 2)
    elif ctype == 2:
        rgba = np.concatenate([px, np.ones((h, w, 1), np.float32)], 2)
    elif ctype == 6:
        rgba = px
    else:
        if plte is None:
            raise TextureError('PNG palette missing')
        ix = px[..., 0].astype(np.int32)
        col = plte.astype(np.float32)[np.clip(ix, 0, len(plte) - 1)] / 255.0
        al = np.ones((h, w, 1), np.float32)
        if trns is not None:
            tr = np.full(256, 255, np.uint8)
            tr[:len(trns)] = trns
            al = (tr[ix].astype(np.float32) / 255.0)[..., None]
        rgba = np.concatenate([col, al], 2)
    return np.ascontiguousarray(rgba, dtype=np.float32)


# ---------------------------------------------------------------------------------------------- other readers
def read_bmp(data):
    off = struct.unpack_from('<I', data, 10)[0]
    hs, w, h, planes, bpp, comp = struct.unpack_from('<IiiHHI', data, 14)
    if comp not in (0, 3) or bpp not in (24, 32):
        raise TextureError('only uncompressed 24 and 32 bit BMP files are read')
    top_down = h < 0
    h = abs(h)
    bypp = bpp // 8
    stride = (w * bypp + 3) & ~3
    a = np.frombuffer(data, np.uint8, count=stride * h, offset=off).reshape(h, stride)[:, :w * bypp].reshape(h, w, bypp)
    if not top_down:
        a = a[::-1]
    rgb = a[..., [2, 1, 0]].astype(np.float32) / 255.0
    al = a[..., 3:4].astype(np.float32) / 255.0 if bypp == 4 else np.ones((h, w, 1), np.float32)
    if bypp == 4 and not (al < 1).any() and (a[..., 3] == 0).all():
        al = np.ones((h, w, 1), np.float32)
    return np.concatenate([rgb, al], 2)


def read_tga(data):
    idl, cmt, typ = data[0], data[1], data[2]
    w, h = struct.unpack_from('<HH', data, 12)
    bpp, desc = data[16], data[17]
    if cmt or typ not in (2, 10) or bpp not in (24, 32):
        raise TextureError('only true-colour TGA files are read')
    off = 18 + idl
    bypp = bpp // 8
    if typ == 2:
        a = np.frombuffer(data, np.uint8, count=w * h * bypp, offset=off).reshape(h, w, bypp)
    else:
        out = bytearray()
        p = off
        while len(out) < w * h * bypp:
            c = data[p]
            p += 1
            n = (c & 127) + 1
            if c & 128:
                out += data[p:p + bypp] * n
                p += bypp
            else:
                out += data[p:p + n * bypp]
                p += n * bypp
        a = np.frombuffer(bytes(out[:w * h * bypp]), np.uint8).reshape(h, w, bypp)
    if not desc & 0x20:
        a = a[::-1]
    rgb = a[..., [2, 1, 0]].astype(np.float32) / 255.0
    al = a[..., 3:4].astype(np.float32) / 255.0 if bypp == 4 else np.ones((h, w, 1), np.float32)
    return np.concatenate([rgb, al], 2)


def read_dds(data):
    h, w = struct.unpack_from('<II', data, 12)
    four = data[84:88]
    body = data[128:]
    if four == b'DXT1':
        return decode_payload(body, 'DXT1', w, h)
    if struct.unpack_from('<I', data, 88)[0] == 32:
        a = np.frombuffer(body, np.uint8, count=w * h * 4).reshape(h, w, 4)
        return (a[..., [2, 1, 0, 3]].astype(np.float32) / 255.0)
    raise TextureError('only DXT1 and 32 bit DDS files are read')


def read_image(src):
    """path or bytes -> float RGBA. PNG, BMP, TGA, DDS always; JPEG and the rest through PIL when it is there, else the built-in
    baseline JPEG reader."""
    if isinstance(src, (str, os.PathLike)):
        with open(src, 'rb') as f:
            data = f.read()
    else:
        data = bytes(src)
    head = data[:12]
    try:
        if head[:2] == b'BM':
            return read_bmp(data)
        if head[:4] == b'DDS ':
            return read_dds(data)
        pil = _pil_read(data)
        if pil is not None:
            return pil
        if head[:8] == b'\x89PNG\r\n\x1a\n':
            return read_png(data)
        if head[:2] == b'\xff\xd8':
            from . import jpeg
            return jpeg.decode(data)
        if data[2:3] in (b'\x02', b'\x0a') and data[1:2] in (b'\x00',):
            return read_tga(data)
    except TextureError:
        raise
    except Exception as e:                                   # noqa: BLE001
        raise TextureError('the image could not be read: %s' % e)
    raise TextureError('unsupported image file (use PNG, JPEG, BMP, TGA or DDS)')


def _pil_read(data):
    try:
        from PIL import Image
    except Exception:                                        # noqa: BLE001
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert('RGBA')
        return np.asarray(im, dtype=np.float32) / 255.0
    except Exception:                                        # noqa: BLE001
        return None


# ---------------------------------------------------------------------------------------------- resample
def _weights(n_in, n_out):
    """(n_out, n_in) area weights (box filter on the exact overlap); linear interpolation when enlarging."""
    if n_out == n_in:
        return np.eye(n_in, dtype=np.float32)
    if n_out < n_in:
        s = n_in / n_out
        W = np.zeros((n_out, n_in), np.float32)
        for o in range(n_out):
            a, b = o * s, (o + 1) * s
            i0, i1 = int(math.floor(a)), min(int(math.ceil(b)), n_in)
            for i in range(i0, i1):
                W[o, i] = min(b, i + 1) - max(a, i)
        return W / W.sum(1, keepdims=True)
    W = np.zeros((n_out, n_in), np.float32)
    s = n_in / n_out
    for o in range(n_out):
        x = (o + 0.5) * s - 0.5
        i0 = int(math.floor(x))
        f = x - i0
        a, b = min(max(i0, 0), n_in - 1), min(max(i0 + 1, 0), n_in - 1)
        W[o, a] += 1 - f
        W[o, b] += f
    return W


def resize(img, w, h):
    """Resample to (w, h) on premultiplied colour so transparent texels do not bleed their colour."""
    ih, iw = img.shape[:2]
    if (iw, ih) == (w, h):
        return img
    a = img[..., 3:4]
    pm = np.concatenate([img[..., :3] * a, a], 2)
    Wx, Wy = _weights(iw, w), _weights(ih, h)
    t = np.einsum('ox,yxc->yoc', Wx, pm, optimize=True)
    t = np.einsum('py,yoc->poc', Wy, t, optimize=True)
    al = t[..., 3:4]
    rgb = np.where(al > 1e-6, t[..., :3] / np.maximum(al, 1e-6), 0.0)
    return np.clip(np.concatenate([rgb, al], 2), 0, 1).astype(np.float32)


def crop(img, x, y, w, h):
    ih, iw = img.shape[:2]
    x, y = max(0, min(int(x), iw - 1)), max(0, min(int(y), ih - 1))
    w, h = max(1, min(int(w), iw - x)), max(1, min(int(h), ih - y))
    return img[y:y + h, x:x + w]


def pow2_floor(n):
    return 1 << (max(int(n), 1).bit_length() - 1)


def pow2_near(n):
    lo = pow2_floor(n)
    return lo * 2 if n - lo > lo * 2 - n else lo


# ---------------------------------------------------------------------------------------------- edits
def hue_rotate(rgb, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    to_yiq = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]], np.float32)
    rot = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)
    M = np.linalg.inv(to_yiq) @ rot @ to_yiq
    return rgb @ M.T.astype(np.float32)


def apply_edits(img, e):
    """e: {hue (deg), brightness (-1..1), contrast (-1..1), saturation (-1..1), tint [r,g,b] 0..255 + tint_amount 0..1,
    alpha: keep|opaque|threshold, alpha_cut 0..1}. -> new float RGBA."""
    e = e or {}
    out = img.copy()
    rgb = out[..., :3]
    if e.get('hue'):
        rgb = hue_rotate(rgb, float(e['hue']))
    sat = float(e.get('saturation') or 0)
    if sat:
        g = (rgb * np.array([0.299, 0.587, 0.114], np.float32)).sum(-1, keepdims=True)
        rgb = g + (rgb - g) * (1.0 + sat)
    ct = float(e.get('contrast') or 0)
    if ct:
        rgb = (rgb - 0.5) * (1.0 + ct) + 0.5
    br = float(e.get('brightness') or 0)
    if br:
        rgb = rgb + br
    t = e.get('tint')
    amt = float(e.get('tint_amount') or 0)
    if t and amt:
        tc = np.asarray(t, np.float32) / 255.0
        rgb = rgb * (1 - amt) + rgb * tc * amt * 1.0 + 0.0
    out[..., :3] = np.clip(rgb, 0, 1)
    mode = e.get('alpha') or 'keep'
    if mode == 'opaque':
        out[..., 3] = 1.0
    elif mode == 'threshold':
        out[..., 3] = (out[..., 3] >= float(e.get('alpha_cut', 0.5))).astype(np.float32)
    return out


def has_alpha(img, cut=0.98):
    return bool((img[..., 3] < cut).any())


# ---------------------------------------------------------------------------------------------- mips
def mip_chain(img):
    """Full chain down to 1x1, premultiplied box filter. Level 0 is the image itself."""
    out = [img]
    cur = img
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        a = cur[..., 3:4]
        pm = np.concatenate([cur[..., :3] * a, a], 2)
        h, w = pm.shape[:2]
        if h > 1 and w > 1:
            pm = (pm[0::2, 0::2] + pm[1::2, 0::2] + pm[0::2, 1::2] + pm[1::2, 1::2]) * 0.25
        elif w > 1:
            pm = (pm[:, 0::2] + pm[:, 1::2]) * 0.5
        else:
            pm = (pm[0::2] + pm[1::2]) * 0.5
        al = pm[..., 3:4]
        rgb = np.where(al > 1e-6, pm[..., :3] / np.maximum(al, 1e-6), 0.0)
        cur = np.concatenate([rgb, al], 2).astype(np.float32)
        out.append(cur)
    return out


# ---------------------------------------------------------------------------------------------- DXT1
def _to565(c):
    r = np.clip(np.rint(c[..., 0] * 31), 0, 31).astype(np.uint16)
    g = np.clip(np.rint(c[..., 1] * 63), 0, 63).astype(np.uint16)
    b = np.clip(np.rint(c[..., 2] * 31), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _from565(v):
    v = v.astype(np.uint32)
    r = ((v >> 11) & 31) / 31.0
    g = ((v >> 5) & 63) / 63.0
    b = (v & 31) / 31.0
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def _palette4(p0, p1):
    return np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)


def _assign(blocks, pal):
    d = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1)
    err = np.take_along_axis(d, idx[..., None], -1)[..., 0].sum(1)
    return idx.astype(np.uint32), err


def _order4(e0, e1):
    """565 endpoint pair -> c0 > c1 (four-colour mode); equal pairs are nudged apart."""
    c0, c1 = _to565(e0), _to565(e1)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1
    c0 = np.where(eq & (c0 < 0xFFFF), c0 + 1, c0)
    c1 = np.where(eq & (c0 == 0xFFFF) & (c1 > 0), c1 - 1, c1)
    return c0.astype(np.uint16), c1.astype(np.uint16)


def _candidate(blocks, e0, e1):
    c0, c1 = _order4(e0, e1)
    pal = _palette4(_from565(c0), _from565(c1))
    idx, err = _assign(blocks, pal)
    return c0, c1, idx, err


def _refine(blocks, idx):
    """Least squares endpoints for fixed indices: x_i ~ a_i c0 + (1 - a_i) c1."""
    a = np.array([1.0, 0.0, 2 / 3, 1 / 3], np.float32)[idx]
    b = 1 - a
    aa, bb, ab = (a * a).sum(1), (b * b).sum(1), (a * b).sum(1)
    det = aa * bb - ab * ab
    ok = np.abs(det) > 1e-6
    ax = np.einsum('ni,nic->nc', a, blocks)
    bx = np.einsum('ni,nic->nc', b, blocks)
    d = np.where(ok, det, 1.0)[:, None]
    e0 = (bb[:, None] * ax - ab[:, None] * bx) / d
    e1 = (aa[:, None] * bx - ab[:, None] * ax) / d
    return np.clip(e0, 0, 1), np.clip(e1, 0, 1), ok


def _principal(blocks):
    mean = blocks.mean(1)
    cen = blocks - mean[:, None, :]
    cov = np.einsum('nij,nik->njk', cen, cen)
    v = blocks.max(1) - blocks.min(1)
    v = v + 1e-4
    for _ in range(4):
        v = np.einsum('njk,nk->nj', cov, v)
        nv = np.linalg.norm(v, axis=1, keepdims=True)
        v = np.where(nv > 1e-9, v / np.maximum(nv, 1e-9), np.array([1.0, 1.0, 1.0], np.float32))
    proj = np.einsum('nic,nc->ni', cen, v)
    lo = mean + v * proj.min(1)[:, None]
    hi = mean + v * proj.max(1)[:, None]
    return np.clip(lo, 0, 1), np.clip(hi, 0, 1)


def _encode_opaque(blocks):
    """blocks (n, 16, 3) float -> (c0, c1, idx (n,16), err)."""
    mn, mx = blocks.min(1), blocks.max(1)
    inset = (mx - mn) / 16.0
    best = _candidate(blocks, mx - inset, mn + inset)
    lo, hi = _principal(blocks)
    for cand in (_candidate(blocks, hi, lo),):
        better = cand[3] < best[3]
        best = tuple(np.where(better[:, None] if x.ndim == 2 else better, c, x) for c, x in zip(cand, best))
    for _ in range(2):
        e0, e1, ok = _refine(blocks, best[2])
        cand = _candidate(blocks, e0, e1)
        better = (cand[3] < best[3]) & ok
        best = tuple(np.where(better[:, None] if x.ndim == 2 else better, c, x) for c, x in zip(cand, best))
    return best


def _encode_punch(blocks, opaque):
    """Blocks with transparent texels: 3-colour mode (c0 <= c1), index 3 = transparent. opaque (n, 16) bool."""
    n = len(blocks)
    w = opaque[..., None].astype(np.float32)
    cnt = np.maximum(w.sum(1), 1.0)
    mean = (blocks * w).sum(1) / cnt
    big = np.where(opaque[..., None], blocks, mean[:, None, :])
    lo, hi = _principal(big)
    mn, mx = big.min(1), big.max(1)
    lo = np.where((opaque.sum(1) > 1)[:, None], lo, mean)
    hi = np.where((opaque.sum(1) > 1)[:, None], hi, mean)
    c0, c1 = _to565(lo), _to565(hi)
    swap = c0 > c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)          # c0 <= c1 selects the 3-colour mode
    p0, p1 = _from565(c0), _from565(c1)
    pal = np.stack([p0, p1, (p0 + p1) / 2], axis=1)
    d = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1).astype(np.uint32)
    idx = np.where(opaque, idx, 3).astype(np.uint32)
    return c0.astype(np.uint16), c1.astype(np.uint16), idx


def dxt1_level(img, alpha_cut=0.5, chunk=65536):
    """One mip level (float RGBA) -> DXT1 bytes (8 B per 4x4 block; sides under 4 are padded by edge replication)."""
    h, w = img.shape[:2]
    H, W = max(h, 4), max(w, 4)
    if (H, W) != (h, w):
        img = np.pad(img, ((0, H - h), (0, W - w), (0, 0)), mode='edge')
    bh, bw = H // 4, W // 4
    rgb = img[..., :3].reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 3)
    al = img[..., 3].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh * bw, 16)
    out = np.zeros(bh * bw, dtype=[('c0', '<u2'), ('c1', '<u2'), ('b', '<u4')])
    for s in range(0, len(rgb), chunk):
        blk, a = rgb[s:s + chunk].astype(np.float32), al[s:s + chunk]
        opaque = a >= alpha_cut
        punch = ~opaque.all(1)
        c0, c1, idx, _ = _encode_opaque(blk)
        if punch.any():
            p0, p1, pidx = _encode_punch(blk[punch], opaque[punch])
            c0, c1, idx = c0.copy(), c1.copy(), idx.copy()
            c0[punch], c1[punch], idx[punch] = p0, p1, pidx
        bits = np.zeros(len(idx), dtype=np.uint32)
        for i in range(16):
            bits |= idx[:, i].astype(np.uint32) << (2 * i)
        out['c0'][s:s + chunk], out['c1'][s:s + chunk], out['b'][s:s + chunk] = c0, c1, bits
    return out.tobytes()


def dxt1_decode_level(data, w, h):
    """DXT1 -> float RGBA (the 1-bit transparent index gives alpha 0)."""
    H, W = max(h, 4), max(w, 4)
    n = (H // 4) * (W // 4)
    a = np.frombuffer(data[:8 * n], dtype=[('c0', '<u2'), ('c1', '<u2'), ('b', '<u4')])
    p0, p1 = _from565(a['c0']), _from565(a['c1'])
    four = (a['c0'] > a['c1'])[:, None]
    pal = np.stack([p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0.0)], axis=1)
    px = np.zeros((n, 16, 4), np.float32)
    for i in range(16):
        k = ((a['b'] >> (2 * i)) & 3).astype(np.int64)
        px[:, i, :3] = pal[np.arange(n), k]
        px[:, i, 3] = np.where((k == 3) & ~four[:, 0], 0.0, 1.0)
    img = px.reshape(H // 4, W // 4, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(H, W, 4)
    return img[:h, :w]


def rgba32_level(img):
    px = np.clip(np.rint(img * 255), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(px[..., [2, 1, 0, 3]]).tobytes()


def rgba32_decode_level(data, w, h):
    a = np.frombuffer(data[:w * h * 4], np.uint8).reshape(h, w, 4)
    return a[..., [2, 1, 0, 3]].astype(np.float32) / 255.0


# ---------------------------------------------------------------------------------------------- payloads
def encode(img, fmt, alpha_cut=0.5, mips=True):
    """float RGBA with power-of-two sides -> (payload bytes, levels)."""
    h, w = img.shape[:2]
    if not (is_pow2(w) and is_pow2(h)):
        raise TextureError('texture sides must be powers of two (%dx%d)' % (w, h))
    if fmt == 'DXT1' and (w < 4 or h < 4):
        raise TextureError('DXT1 needs at least 4x4')
    chain = mip_chain(img) if mips else [img]
    if fmt == 'DXT1':
        pay = b''.join(dxt1_level(l, alpha_cut) for l in chain)
    elif fmt == 'RGBA32':
        pay = b''.join(rgba32_level(l) for l in chain)
    else:
        raise TextureError('format must be DXT1 or RGBA32')
    want = payload_size(fmt, w, h, len(chain))
    if len(pay) != want:
        raise TextureError('payload is %d bytes, the engine will copy %d' % (len(pay), want))
    return pay, len(chain)


def decode_payload(payload, fmt, w, h, level=0):
    off = sum(level_size(fmt, w, h, L) for L in range(level))
    ww, hh = max(w >> level, 1), max(h >> level, 1)
    if fmt == 'DXT1':
        return dxt1_decode_level(payload[off:], ww, hh)
    return rgba32_decode_level(payload[off:], ww, hh)


def psnr(a, b):
    d = float(((a[..., :3] - b[..., :3]) ** 2).mean())
    return 99.0 if d < 1e-12 else round(10 * math.log10(1.0 / d), 2)


def checker_under(img, size=8):
    """Preview helper: composite over a light/dark checker so transparency shows."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    c = (((yy // size) + (xx // size)) % 2).astype(np.float32) * 0.25 + 0.4
    a = img[..., 3:4]
    return np.concatenate([img[..., :3] * a + c[..., None] * (1 - a), np.ones((h, w, 1), np.float32)], 2)
