"""Writer for the engine's baked-lighting record (MESHCOLOR, record type 10) of a NEW map block.

The reader and the key rules live in TOD HD's `tod_hd_lighting.py` (vendored unchanged, `vendor/hd`); this module lays a whole record out
again from a description, by the same size pass the engine's loader replays (every allocation 4-aligned, every entry 16-aligned, the
record padded to 16 bytes). Nothing is copied from a shipped record except the constant words of the structures.

  record  = header (0x50) | name | entry array | per entry: [align 16] colour buffer object (0x28) + index copy | uid path array + data |
            key table (header, keys, values) | uid table (header, keys, values, per key data)
  payload = the colour data of all colour buffers in entry order (4 bytes per colour, at least 4 colours per buffer)

Description of a record: instances = [{path: ((uid0, uid1), ...), meshes: [mesh, ...]}] where a mesh is either
  per-vertex   {pivot, mesh, colours [u32 D3DCOLOR], indices [u16]}                    an entry with a colour buffer, or
  single       {pivot, mesh, single: u32 D3DCOLOR, vcount, icount}                      an entry with no buffer: one colour for the mesh
               (the placed Model's single-colour flag is on and the key carries the mesh's vertex and index counts; a shipped record holds both).
The instance key of the engine is the position of the path in the sorted uid table. Entries are written in key order.
"""
import functools
import struct

import numpy as np

from . import lightfit
from . import hdblock as _hdblock

TYPE = 10
FILL = 0xBAADF00D
FILL_A = 0xBAAFFA00
FILL_T = 0xBAAC0040
TAG = 0x80000000
BUFFER_BITS = 0xB8000004            # low bits 4, bits 3..26 = colour count, the rest as the shipped buffers carry it
MAX_INSTANCES = 0xFFFF


class RecordError(Exception):
    pass


def a4(x):
    return (x + 3) & ~3


def a16(x):
    return (x + 15) & ~15


@functools.lru_cache(maxsize=1)
def HL():
    return lightfit.hl()


def _uid_cmp_key(path):
    """The engine's order of unique-id paths: lexicographic over signed (i32, i32) pairs, the shorter path first."""
    return tuple((int(a), int(b)) for a, b in path)


def build(name, instances, single=False):
    """-> (record bytes padded to 16, payload bytes, summary dict). Raises RecordError for a description the engine cannot read."""
    hl = HL()
    if not instances:
        raise RecordError('no instances')
    if len(instances) > MAX_INSTANCES:
        raise RecordError('%d instances; a record holds at most %d' % (len(instances), MAX_INSTANCES))
    inst = sorted(instances, key=lambda i: _uid_cmp_key(i['path']))
    paths = [tuple((int(a), int(b)) for a, b in i['path']) for i in inst]
    if len(set(paths)) != len(paths):
        raise RecordError('two instances share one unique-id path')
    keys = []                      # (key words, entry description)
    for ik, i in enumerate(inst):
        seen = set()
        for m in i['meshes']:
            ident = (int(m['pivot']), int(m['mesh']))
            if ident in seen:
                raise RecordError('mesh %s of an instance is listed twice' % (ident,))
            seen.add(ident)
            if m.get('single') is not None:
                nv, ni = int(m['vcount']), int(m['icount'])
                if not (0 < nv <= 0xFFFFF) or not (0 <= ni <= 0xFFFFF):
                    raise RecordError('a mesh has %d vertices and %d indices' % (nv, ni))
                words = hl.build_key(ik, ident[0], ident[1], nv, ni, True)
                keys.append((words, None, None, int(m['single']) & 0xFFFFFFFF))
                continue
            col = np.asarray(m['colours'], np.uint32)
            idx = np.asarray(m['indices'], np.uint16)
            if not len(col) or len(col) > 0xFFFFF or len(idx) > 0xFFFFF:
                raise RecordError('a mesh has %d vertices and %d indices' % (len(col), len(idx)))
            words = hl.build_key(ik, ident[0], ident[1], len(col), len(idx), single)
            keys.append((words, col, idx, None))
    keys.sort(key=functools.cmp_to_key(lambda a, b: -1 if hl.key_less(a[0], b[0]) else (1 if hl.key_less(b[0], a[0]) else 0)))
    for k in range(len(keys) - 1):
        if not hl.key_less(keys[k][0], keys[k + 1][0]):
            raise RecordError('two meshes of one instance have the same key')
    n_entries = len(keys)
    nm = name.encode('latin-1') + b'\0'

    # ---- layout (the size pass), offsets relative to the record start
    cur = 0x50
    name_off, cur = cur, cur + a4(len(nm))
    entries_off, cur = cur, cur + a4(24 * n_entries)
    buf_off, idx_off, data_off = [], [], []
    data = 0
    for _, col, idx, sc in keys:
        cur = a16(cur)                                        # the size pass aligns before every entry, buffer or not
        if col is None:
            buf_off.append(None)
            idx_off.append(None)
            data_off.append(None)
            continue
        buf_off.append(cur)
        cur += 0x28
        idx_off.append(cur)
        cur += a4(2 * len(idx))
        data_off.append(data)
        data += a4(4 * max(len(col), 4))
    paths_off, cur = cur, cur + a4(16 * len(paths))
    path_data = []
    for p in paths:
        path_data.append(cur)
        cur += a4(8 * len(p))
    kt_off, cur = cur, cur + 16
    kt_keys, cur = cur, cur + a4(16 * n_entries)
    kt_vals, cur = cur, cur + a4(2 * n_entries)
    ut_off, cur = cur, cur + 16
    ut_keys, cur = cur, cur + a4(16 * len(paths))
    ut_vals, cur = cur, cur + a4(2 * len(paths))
    ut_data = []
    for p in paths:
        ut_data.append(cur)
        cur += a4(8 * len(p))
    size = cur
    out = bytearray(a16(size))
    for o in range(0, len(out) - 3, 4):                        # the gaps carry the engine's fill word
        struct.pack_into('<I', out, o, FILL)

    def rel(field, target):
        v = (target - field) & 0xFFFFFFFF
        return TAG if v == 0 else v

    def put(o, *w):
        struct.pack_into('<%dI' % len(w), out, o, *w)

    put(0, TYPE, rel(4, name_off), 0, FILL, 0, 0, 0xBA610000, 0x18,
        rel(0x20, entries_off), n_entries, n_entries, FILL_A,
        rel(0x30, paths_off), len(paths), len(paths), FILL_A,
        rel(0x40, ut_off), 0, rel(0x48, kt_off), 0)
    out[name_off:name_off + len(nm)] = nm
    out[name_off + len(nm):name_off + a4(len(nm))] = bytes(a4(len(nm)) - len(nm))
    payload = bytearray(data)
    for e, (w, col, idx, sc) in enumerate(keys):
        eo = entries_off + 24 * e
        if col is None:
            put(eo, 0, sc, *w)
            continue
        put(eo, rel(eo, buf_off[e]), 0xFFFFFFFF, *w)
        bo = buf_off[e]
        put(bo, 0, 0, FILL, 0, BUFFER_BITS | (len(col) << 3), len(idx), rel(bo + 0x18, idx_off[e]), len(idx), len(idx), FILL_A)
        if len(idx):
            out[idx_off[e]:idx_off[e] + 2 * len(idx)] = struct.pack('<%dH' % len(idx), *idx.tolist())
        payload[data_off[e]:data_off[e] + 4 * len(col)] = struct.pack('<%dI' % len(col), *[int(c) for c in col])
    for j, p in enumerate(paths):
        po = paths_off + 16 * j
        put(po, rel(po, path_data[j]), len(p), len(p), FILL_A)
        for k, (a, b) in enumerate(p):
            struct.pack_into('<ii', out, path_data[j] + 8 * k, a, b)
    put(kt_off, n_entries, FILL_T, rel(kt_off + 8, kt_keys), rel(kt_off + 12, kt_vals))
    for e, (w, col, idx, sc) in enumerate(keys):
        struct.pack_into('<4I', out, kt_keys + 16 * e, *w)
        struct.pack_into('<H', out, kt_vals + 2 * e, e)
    put(ut_off, len(paths), FILL_T, rel(ut_off + 8, ut_keys), rel(ut_off + 12, ut_vals))
    for j, p in enumerate(paths):
        uo = ut_keys + 16 * j
        put(uo, rel(uo, ut_data[j]), len(p), len(p), FILL_A)
        for k, (a, b) in enumerate(p):
            struct.pack_into('<ii', out, ut_data[j] + 8 * k, a, b)
        struct.pack_into('<H', out, ut_vals + 2 * j, j)
    # the entries' key copies: the engine never reads them; they hold the key words (masked fields equal, as in every shipped entry)
    # colour buffer data pointers: stored as payload offset minus the field's own offset in the record (cursor relative, see HD)
    for e in range(n_entries):
        bo = buf_off[e]
        if bo is None:
            continue
        struct.pack_into('<I', out, bo + 4, (data_off[e] - (bo + 4)) & 0xFFFFFFFF)
    summary = dict(entries=n_entries, instances=len(paths), info_bytes=len(out), payload_bytes=len(payload),
                   vertices=sum(len(c) for _, c, _, _ in keys if c is not None), indices=sum(len(i) for _, _, i, _ in keys if i is not None),
                   single_entries=sum(1 for k in keys if k[1] is None))
    return bytes(out), bytes(payload), summary


# ------------------------------------------------------------------------------------------------ read back
def read(raw, ext, name=None):
    """Every lighting record of a block (HD's strict reader) -> list of parsed records; raises when one is bad."""
    hl = HL()
    import tod_hd_game as G
    blk = _hdblock.Block(raw, ext)
    recs = hl._parse_block(blk)
    for r in recs:
        bad = [c for c, ok in r.checks.items() if not ok]
        if bad or r.problems:
            raise RecordError('lighting record %s fails %s' % (r.name, bad or r.problems[0]))
    return [r for r in recs if name is None or r.name == name], blk


def describe(rec, blk):
    """A parsed record -> the description build() takes (colours and index copies read back)."""
    pay = blk.payloads[rec.index]
    uid_of = {v: rec.uid_keys[n] for n, v in enumerate(rec.uid_values)}
    by_inst = {}
    for k, w in enumerate(rec.keys):
        e = rec.entries[rec.values[k]]
        b = e['buffer']
        if b is None:                                    # a single-colour entry: one colour and the counts of its key
            by_inst.setdefault(w[1] & 0xFFFF, []).append(dict(pivot=(w[0] >> 16) & 0xFFFF, mesh=w[0] & 0xFFFF, single=int(e['colour']),
                                                              vcount=w[2] & 0xFFFFF, icount=w[3] & 0xFFFFF))
            continue
        col = np.frombuffer(pay, '<u4', b['count'], b['data_offset']).copy()
        idx = np.frombuffer(bytes(rec.info[b['index_copy_offset']:b['index_copy_offset'] + 2 * b['index_copy_count']]), '<u2').copy()
        by_inst.setdefault(w[1] & 0xFFFF, []).append(dict(pivot=(w[0] >> 16) & 0xFFFF, mesh=w[0] & 0xFFFF, colours=col, indices=idx))
    return [dict(path=uid_of[i], meshes=ms) for i, ms in sorted(by_inst.items())]
