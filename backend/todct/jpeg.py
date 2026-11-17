"""A small baseline JPEG reader (numpy + python), used when PIL is not installed (the packaged app has none).

Sequential Huffman JPEG, 8 bit, 1 or 3 components, any sampling factors, restart markers. Progressive and arithmetic-coded files are
refused with a plain message (save the picture as PNG or as a baseline JPEG). Chroma is enlarged by repetition.
"""
import struct

import numpy as np

from .texture import TextureError

ZZ = np.array([0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
               35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63])


def _dct_matrix():
    m = np.zeros((8, 8))
    for k in range(8):
        for n in range(8):
            m[k, n] = (np.sqrt(1 / 8) if k == 0 else np.sqrt(2 / 8)) * np.cos((2 * n + 1) * k * np.pi / 16)
    return m


C = _dct_matrix()


class Huff:
    def __init__(self, counts, symbols):
        self.lookup = {}
        code, k = 0, 0
        self.fast = [None] * 512                              # 9-bit prefix -> (length, symbol)
        for ln in range(1, 17):
            for _ in range(counts[ln - 1]):
                sym = symbols[k]
                k += 1
                self.lookup[(ln, code)] = sym
                if ln <= 9:
                    lo = code << (9 - ln)
                    for x in range(lo, lo + (1 << (9 - ln))):
                        self.fast[x] = (ln, sym)
                code += 1
            code <<= 1


class Bits:
    def __init__(self, data):
        self.d, self.p, self.buf, self.n = data, 0, 0, 0

    def fill(self, need):
        while self.n < need:
            b = self.d[self.p] if self.p < len(self.d) else 0
            self.p += 1
            self.buf = ((self.buf << 8) | b) & 0xFFFFFFFFFFFF
            self.n += 8

    def get(self, k):
        if k == 0:
            return 0
        self.fill(k)
        self.n -= k
        return (self.buf >> self.n) & ((1 << k) - 1)

    def huff(self, h):
        self.fill(16)
        peek = (self.buf >> (self.n - 9)) & 511
        e = h.fast[peek]
        if e is not None:
            self.n -= e[0]
            return e[1]
        code = 0
        for ln in range(1, 17):
            code = (self.buf >> (self.n - ln)) & ((1 << ln) - 1)
            s = h.lookup.get((ln, code))
            if s is not None:
                self.n -= ln
                return s
        raise TextureError('damaged JPEG data')


def _ext(v, s):
    return v if v >= (1 << (s - 1)) else v - (1 << s) + 1


def decode(data):
    if data[:2] != b'\xff\xd8':
        raise TextureError('not a JPEG')
    pos = 2
    qt, hdc, hac, comps, restart = {}, {}, {}, [], 0
    size = None
    scans = []
    while pos < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        m = data[pos + 1]
        pos += 2
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7 or m == 0xFF:
            if m == 0xFF:
                pos -= 1
            continue
        if m == 0xD9:
            break
        ln = struct.unpack_from('>H', data, pos)[0]
        seg = data[pos + 2:pos + ln]
        if m == 0xDB:
            i = 0
            while i < len(seg):
                pq, tq = seg[i] >> 4, seg[i] & 15
                i += 1
                if pq:
                    t = np.frombuffer(seg[i:i + 128], '>u2').astype(np.float32)
                    i += 128
                else:
                    t = np.frombuffer(seg[i:i + 64], np.uint8).astype(np.float32)
                    i += 64
                qt[tq] = t
        elif m in (0xC0, 0xC1):
            if seg[0] != 8:
                raise TextureError('only 8 bit JPEG files are read')
            h, w, n = struct.unpack_from('>HHB', seg, 1)
            size = (w, h)
            comps = []
            for k in range(n):
                cid, hv, tq = seg[6 + 3 * k], seg[7 + 3 * k], seg[8 + 3 * k]
                comps.append(dict(id=cid, h=hv >> 4, v=hv & 15, tq=tq))
        elif m in (0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise TextureError('this JPEG is progressive or arithmetic coded: save it as PNG or as a baseline JPEG')
        elif m == 0xC4:
            i = 0
            while i < len(seg):
                tc, th = seg[i] >> 4, seg[i] & 15
                counts = list(seg[i + 1:i + 17])
                tot = sum(counts)
                syms = list(seg[i + 17:i + 17 + tot])
                i += 17 + tot
                (hac if tc else hdc)[th] = Huff(counts, syms)
        elif m == 0xDD:
            restart = struct.unpack_from('>H', seg, 0)[0]
        elif m == 0xDA:
            ns = seg[0]
            sel = []
            for k in range(ns):
                cid, t = seg[1 + 2 * k], seg[2 + 2 * k]
                sel.append((cid, t >> 4, t & 15))
            # entropy data runs to the next marker that is not RST or a stuffed 0xFF
            j = pos + ln
            e = j
            while True:
                e = data.find(b'\xff', e)
                if e < 0 or e + 1 >= len(data):
                    e = len(data)
                    break
                nx = data[e + 1]
                if nx == 0 or 0xD0 <= nx <= 0xD7:
                    e += 2
                    continue
                break
            scans.append((sel, data[j:e], restart))
            pos = e
            continue
        pos += ln
    if size is None or not scans:
        raise TextureError('the JPEG has no picture data')
    if len(comps) not in (1, 3):
        raise TextureError('only grey and colour JPEG files are read')
    W, H = size
    hmax, vmax = max(c['h'] for c in comps), max(c['v'] for c in comps)
    mcux, mcuy = -(-W // (8 * hmax)), -(-H // (8 * vmax))
    for c in comps:
        c['bx'], c['by'] = mcux * c['h'], mcuy * c['v']
        c['blocks'] = np.zeros((c['by'] * c['bx'], 64), np.float32)
    for sel, raw, rst in scans:
        _scan(comps, sel, raw, rst, hdc, hac, qt, mcux, mcuy, (W, H, hmax, vmax))
    planes = []
    for c in comps:
        blk = c['blocks'].reshape(-1, 8, 8)
        px = np.einsum('ki,nkl,lj->nij', C, blk, C, optimize=True)
        px = px.reshape(c['by'], c['bx'], 8, 8).transpose(0, 2, 1, 3).reshape(c['by'] * 8, c['bx'] * 8) + 128.0
        fy, fx = vmax // c['v'], hmax // c['h']
        if fy > 1 or fx > 1:
            px = np.repeat(np.repeat(px, fy, 0), fx, 1)
        planes.append(px[:H, :W])
    if len(planes) == 1:
        g = np.clip(planes[0], 0, 255) / 255.0
        rgb = np.stack([g, g, g], -1)
    else:
        Y, Cb, Cr = planes[0], planes[1] - 128.0, planes[2] - 128.0
        rgb = np.stack([Y + 1.402 * Cr, Y - 0.344136 * Cb - 0.714136 * Cr, Y + 1.772 * Cb], -1)
        rgb = np.clip(rgb, 0, 255) / 255.0
    return np.concatenate([rgb, np.ones(rgb.shape[:2] + (1,))], -1).astype(np.float32)


def _scan(comps, sel, raw, restart, hdc, hac, qt, mcux, mcuy, dims):
    by_id = {c['id']: c for c in comps}
    cs = [(by_id[cid], hdc[td], hac[ta]) for cid, td, ta in sel]
    segs = []
    cur = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0xFF and i + 1 < len(raw):
            n = raw[i + 1]
            if n == 0:
                cur.append(0xFF)
                i += 2
                continue
            if 0xD0 <= n <= 0xD7:
                segs.append(bytes(cur))
                cur = bytearray()
                i += 2
                continue
        cur.append(b)
        i += 1
    segs.append(bytes(cur))
    single = len(cs) == 1
    if single:
        c = cs[0][0]
        W, H, hmax, vmax = dims
        cw = -(-(-(-W * c['h'] // hmax)) // 8)             # blocks across / down of this component alone
        ch = -(-(-(-H * c['v'] // vmax)) // 8)
        n_mcu = cw * ch
    else:
        n_mcu = mcux * mcuy
    pred = {id(c): 0 for c, _, _ in cs}
    si = 0
    bits = Bits(segs[0])
    zz = ZZ
    for m in range(n_mcu):
        if restart and m and m % restart == 0:
            si += 1
            bits = Bits(segs[si] if si < len(segs) else b'')
            for k in pred:
                pred[k] = 0
        if single:
            c, hd, ha = cs[0]
            _block(bits, c, (m // cw) * c['bx'] + m % cw, hd, ha, pred, qt, zz)
        else:
            mx, my = m % mcux, m // mcux
            for c, hd, ha in cs:
                for v in range(c['v']):
                    for h in range(c['h']):
                        _block(bits, c, (my * c['v'] + v) * c['bx'] + mx * c['h'] + h, hd, ha, pred, qt, zz)


def _block(bits, c, idx, hd, ha, pred, qt, zz):
    q = qt[c['tq']]
    t = bits.huff(hd)
    d = _ext(bits.get(t), t) if t else 0
    pred[id(c)] += d
    out = c['blocks'][idx]
    out[0] = pred[id(c)] * q[0]
    k = 1
    while k < 64:
        rs = bits.huff(ha)
        r, s = rs >> 4, rs & 15
        if s == 0:
            if r == 15:
                k += 16
                continue
            break
        k += r
        if k > 63:
            break
        out[zz[k]] = _ext(bits.get(s), s) * q[k]
        k += 1
