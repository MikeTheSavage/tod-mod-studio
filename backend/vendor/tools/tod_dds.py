#!/usr/bin/env python3
"""Minimal DXT1/DXT3/DXT5 .dds decoder -> RGBA bytes, plus a PNG writer. No external deps.
TOD character/world textures are DXT1 (and a few DXT5). Used to embed real textures into the
glTF previews."""
import struct, zlib

def _rgb565(c):
    r = (c >> 11) & 0x1f; g = (c >> 5) & 0x3f; b = c & 0x1f
    return ((r * 527 + 23) >> 6, (g * 259 + 33) >> 6, (b * 527 + 23) >> 6)

def decode_dds(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'DDS ', 'not a DDS'
    h = struct.unpack_from('<I', d, 12)[0]   # dwHeight
    w = struct.unpack_from('<I', d, 16)[0]   # dwWidth
    fourcc = d[84:88]
    off = 128
    px = bytearray(w * h * 4)
    def putblock(bx, by, colors, cidx, alphas=None):
        for py in range(4):
            for pxl in range(4):
                x = bx * 4 + pxl; y = by * 4 + py
                if x >= w or y >= h: continue
                ci = (cidx >> (2 * (py * 4 + pxl))) & 3
                r, g, b = colors[ci]
                a = 255 if alphas is None else alphas[py * 4 + pxl]
                o = (y * w + x) * 4
                px[o] = r; px[o+1] = g; px[o+2] = b; px[o+3] = a
    blocks_x = (w + 3) // 4; blocks_y = (h + 3) // 4
    if fourcc == b'DXT1':
        for by in range(blocks_y):
            for bx in range(blocks_x):
                c0, c1, idx = struct.unpack_from('<HHI', d, off); off += 8
                a, b = _rgb565(c0), _rgb565(c1)
                if c0 > c1:
                    c2 = tuple((2*a[k]+b[k])//3 for k in range(3))
                    c3 = tuple((a[k]+2*b[k])//3 for k in range(3))
                else:
                    c2 = tuple((a[k]+b[k])//2 for k in range(3)); c3 = (0, 0, 0)
                putblock(bx, by, [a, b, c2, c3], idx)
    elif fourcc in (b'DXT3', b'DXT5'):
        for by in range(blocks_y):
            for bx in range(blocks_x):
                ablock = d[off:off+8]; off += 8
                c0, c1, idx = struct.unpack_from('<HHI', d, off); off += 8
                a, b = _rgb565(c0), _rgb565(c1)
                c2 = tuple((2*a[k]+b[k])//3 for k in range(3))
                c3 = tuple((a[k]+2*b[k])//3 for k in range(3))
                if fourcc == b'DXT3':
                    bits = int.from_bytes(ablock, 'little')
                    alphas = [((bits >> (4*i)) & 0xf) * 17 for i in range(16)]
                else:
                    a0, a1 = ablock[0], ablock[1]
                    abits = int.from_bytes(ablock[2:], 'little')
                    al = [a0, a1]
                    if a0 > a1:
                        for i in range(1, 7): al.append(((7-i)*a0 + i*a1)//7)
                    else:
                        for i in range(1, 5): al.append(((5-i)*a0 + i*a1)//5)
                        al += [0, 255]
                    alphas = [al[(abits >> (3*i)) & 7] for i in range(16)]
                putblock(bx, by, [a, b, c2, c3], idx, alphas)
    elif fourcc in (b'\x00\x00\x00\x00', b'DX10') or struct.unpack_from('<I', d, 80)[0] & 0x40:
        # uncompressed RGB/RGBA: read masks and reorder to RGBA
        bpp = struct.unpack_from('<I', d, 88)[0] or 32
        rm, gm, bm, am = struct.unpack_from('<IIII', d, 92)
        def shift(mask):
            if not mask: return None
            s = 0
            while not (mask >> s) & 1: s += 1
            return s
        sr, sg, sb, sa = shift(rm), shift(gm), shift(bm), shift(am)
        bypp = bpp // 8
        for y in range(h):
            for x in range(w):
                o = off + (y*w + x) * bypp
                v = int.from_bytes(d[o:o+bypp], 'little')
                po = (y*w + x) * 4
                px[po] = (v & rm) >> sr if sr is not None else 0
                px[po+1] = (v & gm) >> sg if sg is not None else 0
                px[po+2] = (v & bm) >> sb if sb is not None else 0
                px[po+3] = (v & am) >> sa if sa is not None else 255
    else:
        raise ValueError('unsupported fourcc %r' % fourcc)
    return w, h, bytes(px)

def rgba_to_png(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0); raw += rgba[y*w*4:(y+1)*w*4]
    def chunk(t, dat): return struct.pack('>I', len(dat)) + t + dat + struct.pack('>I', zlib.crc32(t+dat) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))

def dds_to_png_bytes(path):
    w, h, rgba = decode_dds(path)
    return rgba_to_png(w, h, rgba)

def has_transparency(rgba):
    """True if the texture has genuinely transparent texels (alpha well below opaque). Used to set
    glTF alphaMode=MASK so sign/decal/effect cards don't render as opaque gray quads in UE."""
    mn = 255
    for i in range(3, len(rgba), 4 * 5):   # sample alpha every 5th texel
        if rgba[i] < mn:
            mn = rgba[i]
            if mn < 16:
                return True
    return mn < 200

def dds_to_png_and_alpha(path):
    """-> (png_bytes, has_transparency). Single decode reused for both."""
    w, h, rgba = decode_dds(path)
    return rgba_to_png(w, h, rgba), has_transparency(rgba)

if __name__ == '__main__':
    import sys
    w, h, rgba = decode_dds(sys.argv[1])
    open(sys.argv[2], 'wb').write(rgba_to_png(w, h, rgba))
    print('wrote %s  (%dx%d)' % (sys.argv[2], w, h))
