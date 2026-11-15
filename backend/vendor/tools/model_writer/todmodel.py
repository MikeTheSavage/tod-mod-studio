"""TOD (Kapow) ModelAsset codec: decode a MODEL record (asset type 3) of an asset block into a tree and encode it back
byte for byte, in the engine's NativeSerializer allocation order.

Source of the order: ModelAsset serializer FUN_00857960 (GOG TOD.exe) and its helpers, decompiled in
the author's research notes (propcoll/ghidra_scripts/q1-q4.txt, not included):
  record object 0x60 (FUN_0085ae90)
  name string (+0x04, FUN_00851430 -> FUN_0040d0c0: whole words, (strlen+1+3)&~3 bytes)
  +0x20 vector<TextureRef 8 B> (FUN_00916670), then each ref's name string (FUN_00916c00, ref+4)
  +0x30 vector<Pivot 0x7C> (FUN_00858990), then per pivot:
      +0x24 vector<SkinnedMeshBuffer 0x3C> (FUN_00858b30), then per SMB:
          align16 (FUN_0040cc10) + MeshBuffer (FUN_008595c0 -> FUN_00461b60 / FUN_00463270 (flags&2, skinned) /
                                                FUN_0044c4a0 (flags&8)):
              object 0x44 / 0x5C / 0x64, [+0x00 editor Mesh: always null], align16, VertexBuffer 0x28 (FUN_004650e0)
              + vertex bytes (VB+0x0C), align16, IndexBuffer 0x20 (FUN_004609d0) + 2*count bytes, the +0x14 string
              (FUN_0040cf50; inline when its pointer word is 8), skinned: +0x44 96 B per vertex, +0x48 u16 per vertex
              (FUN_00406820); flags&8: +0x44 vector<u16> (FUN_00423490), +0x54 vector<int> (FUN_004237d0)
          SMB +0x08, +0x18, +0x28 vector<int> (FUN_004237d0)
      pivot strings +0x1C, +0x20 (FUN_0040d0c0)
      +0x44 CollisionList (FUN_0085a930 -> FUN_008c5370; todcoll region 'piv')
      +0x34 vector<int>, +0x48 vector<int> (FUN_004237d0)
  +0x40 -> vector object (16 B) of vector<int> elements (FUN_00859e10), then each element's ints
  +0x54 HullList (FUN_0085aba0 ...; todcoll region 'f54')
  +0x58 object 0x6C (FUN_0085a360) + its +0x00 vector<16 B> (FUN_008b4d70) + its +0x5C vector<8 B> (FUN_00916670)
Every allocation advances by (n+3)&~3. Pointers on disk are self-relative (target - field), 0 = null. A vector's pointer
is the write position at the time it was serialized, also when it is empty. Bytes the exporter left uninitialised
(string word tails, pad after odd-sized data, alignment gaps) are kept per node so the round trip is exact; new or
resized data pads with zeros.

The record must be laid out exactly as the engine's measure pass (mode 0) computes it, because the loader advances to
the next record by align16(measured size). This encoder IS that layout, so any edit made through the tree is safe.
"""
import struct
import todcoll as tc

SENT_VEC = 0xBAAFFA00


def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def i32(b, o): return struct.unpack_from('<i', b, o)[0]
def a4(x): return (x + 3) & ~3
def a16(x): return (x + 15) & ~15


def deref(b, fa):
    v = u32(b, fa)
    if v == 0:
        return None
    if v == 0x80000000:
        return fa
    return (fa + (v & ~3)) & 0xFFFFFFFF


class Reader:
    """Allocation-order cursor over a record. take() asserts that the next allocation starts where the serializer
    would put it and returns the pad bytes up to the next 4 boundary; align() returns the gap bytes."""

    def __init__(self, b, pos):
        self.b = b
        self.pos = pos
        self.log = []

    def take(self, off, n, what=''):
        if off != self.pos:
            raise ValueError('allocation order: %s expected at %x, found at %x' % (what, self.pos, off))
        end = off + n
        pend = a4(end)
        self.log.append((off, n, what))
        pad = bytes(self.b[end:pend])
        self.pos = pend
        return pad

    def align(self, m):
        new = (self.pos + m - 1) & ~(m - 1)
        gap = bytes(self.b[self.pos:new])
        self.pos = new
        return gap


class Writer:
    def __init__(self, ptrlog=None):
        self.buf = bytearray()
        self.ptrlog = ptrlog

    @property
    def pos(self):
        return len(self.buf)

    def alloc(self, data, pad=None):
        off = len(self.buf)
        self.buf += data
        need = a4(len(self.buf)) - len(self.buf)
        if need:
            self.buf += pad if (pad is not None and len(pad) == need) else bytes(need)
        return off

    def align(self, m, gap=None):
        need = ((len(self.buf) + m - 1) & ~(m - 1)) - len(self.buf)
        if need:
            self.buf += gap if (gap is not None and len(gap) == need) else bytes(need)

    def ptr(self, field, target):
        """field and target are offsets in this buffer; target None = null."""
        if self.ptrlog is not None:
            self.ptrlog.append((field, target))
        if target is None:
            v = 0
        else:
            v = (target - field) & 0xFFFFFFFF
            if v == 0:
                v = 0x80000000
        struct.pack_into('<I', self.buf, field, v)

    def put(self, off, data):
        self.buf[off:off + len(data)] = data

    def put_u32(self, off, v):
        struct.pack_into('<I', self.buf, off, v & 0xFFFFFFFF)


# ------------------------------------------------------------------------------------------------ small helpers
def rd_cstr_alloc(b, rd, p, what):
    """String allocated by FUN_0040d0c0 / FUN_00916c00: (strlen+1) rounded up to 4, whole words copied."""
    if p is None:
        return None
    e = b.index(b'\0', p)
    s = bytes(b[p:e])
    n = a4(e - p + 1)
    rd.take(p, n, what)
    return dict(s=s, tail=bytes(b[e + 1:p + n]))


def wr_cstr(w, node):
    if node is None:
        return None
    n = a4(len(node['s']) + 1)
    tail = node.get('tail')
    if tail is None or len(tail) != n - len(node['s']) - 1:
        tail = bytes(n - len(node['s']) - 1)
    return w.alloc(node['s'] + b'\0' + tail)


def rd_vec(b, rd, fa, esz, what):
    """Vector {ptr, count, cap, flags} at fa; data esz*count, allocated now (ptr = current position)."""
    n = i32(b, fa + 4)
    p = deref(b, fa)
    hdr = dict(cap=u32(b, fa + 8), flags=u32(b, fa + 12), cnt=n)
    if n > 0:
        pad = rd.take(p, esz * n, what)
        return dict(hdr=hdr, data=bytes(b[p:p + esz * n]), pad=pad)
    if p != rd.pos:
        raise ValueError('empty vector %s points at %x, write position %x' % (what, p if p is not None else -1, rd.pos))
    return dict(hdr=hdr, data=b'', pad=b'')


def wr_vec(w, fa, v, esz):
    """Write vector data now and patch the header at fa (count = len/esz; cap kept when count unchanged)."""
    n = len(v['data']) // esz
    if n:
        p = w.alloc(v['data'], v.get('pad'))
    else:
        p = w.pos
    w.ptr(fa, p)
    cap = v['hdr']['cap'] if v['hdr'].get('cnt') == n else n
    struct.pack_into('<iII', w.buf, fa + 4, n, cap, v['hdr']['flags'])


def new_vec(data=b'', esz=4):
    n = len(data) // esz
    return dict(hdr=dict(cap=n, flags=SENT_VEC, cnt=n), data=data, pad=b'')


# ------------------------------------------------------------------------------------------------ MeshBuffer
MB_BASE, MB_SKIN, MB_F8 = 0x44, 0x5C, 0x64


def mb_kind(flags):
    if flags & 2:
        return 'skin'
    if flags & 8:
        return 'f8'
    return 'base'


def rd_meshbuffer(b, rd, mb):
    flags = u32(b, mb + 4)
    kind = mb_kind(flags)
    size = {'base': MB_BASE, 'skin': MB_SKIN, 'f8': MB_F8}[kind]
    node = dict(kind=kind)
    node['pad_obj'] = rd.take(mb, size, 'MeshBuffer')
    node['raw'] = bytes(b[mb:mb + size])
    if u32(b, mb) != 0:
        raise ValueError('MeshBuffer +0x00 editor mesh present (not supported)')
    node['gap_vb'] = rd.align(16)
    vb = deref(b, mb + 0x0C)
    if vb is None:
        raise ValueError('MeshBuffer without VertexBuffer')
    node['vb_pad_obj'] = rd.take(vb, 0x28, 'VertexBuffer')
    node['vb_raw'] = bytes(b[vb:vb + 0x28])
    vlen = u32(b, vb + 0x0C)
    vd = deref(b, vb + 0x10)
    if vd is None:
        node['vdata'] = None
    else:
        node['vdata_pad'] = rd.take(vd, vlen, 'vertex data')
        node['vdata'] = bytes(b[vd:vd + vlen])
    node['gap_ib'] = rd.align(16)
    ib = deref(b, mb + 0x10)
    if ib is None:
        raise ValueError('MeshBuffer without IndexBuffer')
    node['ib_pad_obj'] = rd.take(ib, 0x20, 'IndexBuffer')
    node['ib_raw'] = bytes(b[ib:ib + 0x20])
    rd.align(4)
    ilen = 2 * u32(b, ib)
    idp = deref(b, ib + 0x0C)
    if idp is None:
        node['idata'] = None
    else:
        node['idata_pad'] = rd.take(idp, ilen, 'index data')
        node['idata'] = bytes(b[idp:idp + ilen])
    # +0x14 String {len, ptr, cap, inline...}
    sl = i32(b, mb + 0x14)
    sp = deref(b, mb + 0x18)
    if sp == mb + 0x20:
        node['str'] = None
    else:
        n = a4(sl + 1)
        rd.take(sp, n, 'MeshBuffer string')
        node['str'] = bytes(b[sp:sp + n])
    if kind == 'skin':
        nv = u32(b, vb)
        for key, off, esz in (('skin', 0x44, 0x60), ('infl', 0x48, 2)):
            p = deref(b, mb + off)
            if p is None:
                node[key] = None
            else:
                node[key + '_pad'] = rd.take(p, esz * nv, key)
                node[key] = bytes(b[p:p + esz * nv])
    elif kind == 'f8':
        node['v44'] = rd_vec(b, rd, mb + 0x44, 2, 'MeshBuffer+0x44 vector<u16>')
        node['v54'] = rd_vec(b, rd, mb + 0x54, 4, 'MeshBuffer+0x54 vector<int>')
    return node


def wr_meshbuffer(w, node):
    size = {'base': MB_BASE, 'skin': MB_SKIN, 'f8': MB_F8}[node['kind']]
    mb = w.alloc(node['raw'], node.get('pad_obj'))
    w.align(16, node.get('gap_vb'))
    vb = w.alloc(node['vb_raw'], node.get('vb_pad_obj'))
    w.ptr(mb + 0x0C, vb)
    if node['vdata'] is None:
        w.ptr(vb + 0x10, None)
    else:
        vd = w.alloc(node['vdata'], node.get('vdata_pad'))
        w.ptr(vb + 0x10, vd)
        w.put_u32(vb + 0x0C, len(node['vdata']))
    w.align(16, node.get('gap_ib'))
    ib = w.alloc(node['ib_raw'], node.get('ib_pad_obj'))
    w.ptr(mb + 0x10, ib)
    w.align(4)
    if node['idata'] is None:
        w.ptr(ib + 0x0C, None)
    else:
        idp = w.alloc(node['idata'], node.get('idata_pad'))
        w.ptr(ib + 0x0C, idp)
        w.put_u32(ib, len(node['idata']) // 2)
    if node['str'] is None:
        w.ptr(mb + 0x18, mb + 0x20)
    else:
        sp = w.alloc(node['str'])
        w.ptr(mb + 0x18, sp)
    if node['kind'] == 'skin':
        for key, off in (('skin', 0x44), ('infl', 0x48)):
            if node[key] is None:
                w.ptr(mb + off, None)
            else:
                p = w.alloc(node[key], node.get(key + '_pad'))
                w.ptr(mb + off, p)
    elif node['kind'] == 'f8':
        wr_vec(w, mb + 0x44, node['v44'], 2)
        wr_vec(w, mb + 0x54, node['v54'], 4)
    return mb


# ------------------------------------------------------------------------------------------------ collision region
def rd_coll(b, rd, lo, kind):
    reg, end = tc.read_region(b, lo, kind)
    rd.take(lo, end - lo, 'collision ' + kind)     # region ends 4-aligned
    return reg


def wr_coll(w, reg):
    base = w.pos
    if w.ptrlog is None:
        data = tc.write_region(reg, base)
    else:                                           # record todcoll's pointer writes too
        orig = tc.Out.put_ptr
        def logged(self, field, target, _log=w.ptrlog):
            _log.append((field, target))
            return orig(self, field, target)
        tc.Out.put_ptr = logged
        try:
            data = tc.write_region(reg, base)
        finally:
            tc.Out.put_ptr = orig
    w.alloc(data)
    return base


# ------------------------------------------------------------------------------------------------ the model
def decode(b, R, E=None):
    """Decode the MODEL record at offset R of buffer b (an info buffer). Returns the tree; checks that the serializer
    order covers the record up to its content end and that the rest up to E (if given) is the align16 tail."""
    if u32(b, R) != 3:
        raise ValueError('not a MODEL record')
    rd = Reader(b, R)
    m = dict(obj_pad=rd.take(R, 0x60, 'ModelAsset'))
    m['raw'] = bytes(b[R:R + 0x60])
    m['name'] = rd_cstr_alloc(b, rd, deref(b, R + 4), 'name')
    # texture references
    m['texrefs'] = rd_vec(b, rd, R + 0x20, 8, 'texref vector')
    tp = deref(b, R + 0x20)
    m['texnames'] = []
    for i in range(i32(b, R + 0x24)):
        e = tp + 8 * i
        if u32(b, e) != 0:
            raise ValueError('texref asset pointer not null')
        m['texnames'].append(rd_cstr_alloc(b, rd, deref(b, e + 4), 'texref name'))
    # pivots
    m['pivvec'] = rd_vec(b, rd, R + 0x30, 0x7C, 'pivot vector')
    pp = deref(b, R + 0x30)
    pivots = []
    for i in range(i32(b, R + 0x34)):
        pv = pp + 0x7C * i
        P = dict(raw=bytes(b[pv:pv + 0x7C]))
        P['smbvec'] = rd_vec(b, rd, pv + 0x24, 0x3C, 'SMB vector')
        sp = deref(b, pv + 0x24)
        smbs = []
        for j in range(i32(b, pv + 0x28)):
            s = sp + 0x3C * j
            S = dict(raw=bytes(b[s:s + 0x3C]))
            if u32(b, s + 4) != 0:
                raise ValueError('SMB editor mesh pointer present')
            mb = deref(b, s)
            if mb is None:
                S['mb'] = None
            else:
                S['gap_mb'] = rd.align(16)
                S['mb'] = rd_meshbuffer(b, rd, mb)
            S['v08'] = rd_vec(b, rd, s + 0x08, 4, 'SMB+0x08')
            S['v18'] = rd_vec(b, rd, s + 0x18, 4, 'SMB+0x18')
            S['v28'] = rd_vec(b, rd, s + 0x28, 4, 'SMB+0x28')
            smbs.append(S)
        P['smbs'] = smbs
        P['name'] = rd_cstr_alloc(b, rd, deref(b, pv + 0x1C), 'pivot name')
        P['name2'] = rd_cstr_alloc(b, rd, deref(b, pv + 0x20), 'pivot string 2')
        c = deref(b, pv + 0x44)
        P['coll'] = None if c is None else rd_coll(b, rd, c, 'piv')
        P['v34'] = rd_vec(b, rd, pv + 0x34, 4, 'pivot+0x34')
        P['v48'] = rd_vec(b, rd, pv + 0x48, 4, 'pivot+0x48')
        pivots.append(P)
    m['pivots'] = pivots
    # +0x40 vector<vector<int>>
    x = deref(b, R + 0x40)
    if x is None:
        m['x40'] = None
    else:
        X = dict(pad=rd.take(x, 16, '+0x40 vector object'), raw=bytes(b[x:x + 16]))
        X['elems'] = rd_vec(b, rd, x, 16, '+0x40 elements')
        ep = deref(b, x)
        X['data'] = [rd_vec(b, rd, ep + 16 * k, 4, '+0x40 element ints') for k in range(i32(b, x + 4))]
        m['x40'] = X
    h = deref(b, R + 0x54)
    m['hulls'] = None if h is None else rd_coll(b, rd, h, 'f54')
    o = deref(b, R + 0x58)
    if o is None:
        m['o58'] = None
    else:
        O = dict(pad=rd.take(o, 0x6C, '+0x58 object'), raw=bytes(b[o:o + 0x6C]))
        O['v00'] = rd_vec(b, rd, o, 16, '+0x58 obj +0x00')
        O['v5c'] = rd_vec(b, rd, o + 0x5C, 8, '+0x58 obj +0x5C')
        m['o58'] = O
    m['content_end'] = rd.pos - R
    if E is not None:
        tail = bytes(b[rd.pos:E])
        if E != a16(rd.pos):
            raise ValueError('record end %x is not align16(content end %x)' % (E, rd.pos))
        m['tail'] = tail
    m['layout'] = [(off - R, n, what) for off, n, what in rd.log]
    return m


def encode(m, ptrlog=None):
    """Encode the tree into record bytes (record start = offset 0, ends padded to 16). ptrlog (a list) receives every
    self-relative pointer the model level writes as (field offset, target offset or None); collision regions are
    written by todcoll and listed by pointer_fields()."""
    w = Writer(ptrlog)
    R = w.alloc(m['raw'], m.get('obj_pad'))
    if m['name'] is None:
        w.ptr(R + 4, None)
    else:
        w.ptr(R + 4, wr_cstr(w, m['name']))
    # texture refs: the vector data is the 8-byte entries; rebuild entries from texnames
    nt = len(m['texnames'])
    ent = bytearray(m['texrefs']['data']) if len(m['texrefs']['data']) == 8 * nt else bytearray(8 * nt)
    tv = dict(m['texrefs'], data=bytes(ent))
    wr_vec(w, R + 0x20, tv, 8)
    tp = w.pos - 8 * nt if nt else None
    if nt:
        tp = R + 0x20 + u32(w.buf, R + 0x20)
    for i, tn in enumerate(m['texnames']):
        w.put_u32(tp + 8 * i, 0)
        w.ptr(tp + 8 * i + 4, wr_cstr(w, tn))
    # pivots
    npv = len(m['pivots'])
    pv_data = b''.join(P['raw'] for P in m['pivots'])
    wr_vec(w, R + 0x30, dict(m['pivvec'], data=pv_data), 0x7C)
    pp = R + 0x30 + u32(w.buf, R + 0x30) if npv else None
    for i, P in enumerate(m['pivots']):
        pv = pp + 0x7C * i
        ns = len(P['smbs'])
        wr_vec(w, pv + 0x24, dict(P['smbvec'], data=b''.join(S['raw'] for S in P['smbs'])), 0x3C)
        sp = pv + 0x24 + u32(w.buf, pv + 0x24) if ns else None
        for j, S in enumerate(P['smbs']):
            s = sp + 0x3C * j
            if S['mb'] is None:
                w.ptr(s, None)
            else:
                w.align(16, S.get('gap_mb'))
                w.ptr(s, wr_meshbuffer(w, S['mb']))
            w.put_u32(s + 4, 0)
            wr_vec(w, s + 0x08, S['v08'], 4)
            wr_vec(w, s + 0x18, S['v18'], 4)
            wr_vec(w, s + 0x28, S['v28'], 4)
        w.ptr(pv + 0x1C, wr_cstr(w, P['name']))
        w.ptr(pv + 0x20, wr_cstr(w, P['name2']))
        w.ptr(pv + 0x44, None if P['coll'] is None else wr_coll(w, P['coll']))
        wr_vec(w, pv + 0x34, P['v34'], 4)
        wr_vec(w, pv + 0x48, P['v48'], 4)
    X = m['x40']
    if X is None:
        w.ptr(R + 0x40, None)
    else:
        x = w.alloc(X['raw'], X.get('pad'))
        w.ptr(R + 0x40, x)
        ne = len(X['data'])
        el = bytearray(X['elems']['data']) if len(X['elems']['data']) == 16 * ne else bytearray(16 * ne)
        wr_vec(w, x, dict(X['elems'], data=bytes(el)), 16)
        ep = x + u32(w.buf, x) if ne else None
        for k, d in enumerate(X['data']):
            wr_vec(w, ep + 16 * k, d, 4)
    w.ptr(R + 0x54, None if m['hulls'] is None else wr_coll(w, m['hulls']))
    O = m['o58']
    if O is None:
        w.ptr(R + 0x58, None)
    else:
        o = w.alloc(O['raw'], O.get('pad'))
        w.ptr(R + 0x58, o)
        wr_vec(w, o, O['v00'], 16)
        wr_vec(w, o + 0x5C, O['v5c'], 8)
    end = w.pos
    tail = m.get('tail')
    need = a16(end) - end
    w.buf += tail if (tail is not None and len(tail) == need) else bytes(need)
    return bytes(w.buf)


def pointer_fields(rec):
    """Every self-relative pointer word of an encoded MODEL record as (field, target or None), record-relative,
    including the ones inside collision regions: the complete list a byte-level patcher would have to fix after
    moving data (an empty vector's pointer is the write position at the time it was written, so it moves too)."""
    m = decode(rec, 0, len(rec))
    log = []
    if encode(m, log) != rec:
        raise ValueError('record does not round-trip')
    return sorted(set(log), key=lambda x: x[0])
