"""FONT records (type 1): glyph tables straight from a language .main block."""
import struct
def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def sp(b, o):
    v = u32(b, o); return None if v == 0 else o + (v & ~3)
def read_fonts(info, starts):
    out = {}
    for i, R in enumerate(starts):
        if u32(info, R) != 1: continue
        nm = info[sp(info, R + 4):info.index(b'\0', sp(info, R + 4))].decode('latin-1')
        F = sp(info, R + 0x24)
        g = sp(info, F + 0x40); n = u32(info, F + 0x44)
        cell = u32(info, F + 4)
        hs, vs, sx, sy = struct.unpack_from('<4f', info, F + 0x14)
        glyphs = {}
        for k in range(n):
            o = g + 0x20 * k
            ch = struct.unpack_from('<H', info, o)[0]
            xo, yo, adv, u, v, uw = struct.unpack_from('<6f', info, o + 4)
            keep = u32(info, o + 0x1C)
            glyphs[ch] = dict(x_offset=xo, y_offset=yo, advance=adv, u=u, v=v, u_width=uw, keep_color=keep)
        out[nm] = dict(cell=cell, hspacing=hs, vspacing=vs, scale=(sx, sy), glyphs=glyphs)
    return out
