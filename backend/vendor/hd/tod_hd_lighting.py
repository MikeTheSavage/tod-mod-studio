"""Baked-lighting (MESHCOLOR, '.lighting', record type 10) reader and key retargeter for TOD asset blocks.

Why this exists: a placed Model finds its baked lighting through a key that contains each mesh's live vertex
and index counts. When the model rewriter changes those counts, every lookup misses; for single_color_mode
instances the averaged directional light then goes dark. retarget_counts() rewrites the counts inside the keys
of exactly the instances that belong to the rewritten model, so the engine finds the same entries again.
Which instances belong to the model: a (vcount, icount) signature is NOT an identity (ShippingCrate_Pallet and
ADD_Board share (24, 34); the AirVents family shares a 9-vertex fan disc), so retarget_counts(pin=...) restricts the
match to the model's OWN placed instances: pinned_instances(instance_owners(block), model) resolves every UidTable
path to the placed entities of the block's FRAGMENT records that carry its last unique id, and their modelres.

Everything below was decoded from the GOG TOD.exe (Ghidra dumps in work/vegetation_build/lighting/ghidra/out and
work/research/vegetation/model_format/ghidra/dump8*.txt) and is checked against all 28 shipped lighting records.

Record layout (serializer FUN_0085ebf0, size pass = the loader's record walk; cursor relative to the record start)
  +0x00 u32 type 10        +0x04 char* name (FUN_00851430 -> FUN_0040d0c0, a4(strlen+1), right after the header)
  +0x0C 0xBAADF00D         +0x18 0xBA610000  +0x1C 0x18
  +0x20 vector<Entry 24B>  (FUN_0085f6f0: a4(count*24))
  +0x30 vector<UidPath>    (FUN_008b4d70: a4(count*16); then each element's data, FUN_0040d260: a4(n*8))
  +0x40 ptr UidTable       (FUN_00860db0: 16 + a4(count*16) + a4(count*2); then each key's data a4(n*8))
  +0x44 0 (runtime map)    +0x48 ptr KeyTable (FUN_00860db0: 16 + a4(count*16) + a4(count*2))   +0x4C 0 (runtime map)
  Serialization order: header, name, entry array, per entry [align16, colour buffer], +0x30, +0x48, +0x40.
  Record end = align16(size); the loader finds the next record there.
Entry (24 B): +0x00 ptr ColourBuffer or 0, +0x04 D3DCOLOR (single colour; FUN_0085e5d0), +0x08 16-byte copy of
  the key whose value points at this entry (masked fields equal in all 34,789 shipped keys; not read by the
  runtime lookup: the only entry accessors in the class code 0x85E000-0x861500 are FUN_0085e5d0 +4,
  FUN_0085e690 +0, FUN_0085e560 +4). Before EVERY entry the size pass aligns to 16 (FUN_0040cc10), even when +0x00 is 0.
ColourBuffer (FUN_004622f0, fresh sub-context): 0x28 object; +0x04 data pointer into the record's payload
  (stored as payload_offset - field_offset_in_record); +0x10 bits 3..26 = colour count n (engine uses 4 when
  n < 5), payload a4(4*max(n,4)) bytes of D3DCOLOR; +0x14 index count; +0x18 vector<u16> copy of the mesh's
  index list (a4(2*count) bytes in info). Colour buffers are the per-vertex mode; single-colour entries have 0.
KeyTable / UidTable header (16 B): +0 count, +4 u32, +8 self-relative ptr keys, +0x0C self-relative ptr u16 values.
Key (16 B, built by FUN_0085e400): u16 mesh index, u16 pivot index, u16 instance key, bit 16 of u32@+4 = single
  colour flag (the placed Model's flag bit 23), u32@+8 & 0xFFFFF vertex count, u32@+12 & 0xFFFFF index count.
  Order (FUN_0085e470): instance, pivot, mesh, vcount, icount, then flag 0 before 1. Lookup = lower-bound binary
  search FUN_0085f2c0; value = entry index.
Instance key (FUN_0085e7a0): the placed Model builds a path of 8-byte unique ids (FUN_0088f510: its own
  unique id, then those of ancestors that carry one, e.g. the SUBMAP01_Map09_Geometry folder; FUN_008911d0 then
  reverses it, so the path is root first and ends with the entity's (unique_id0, unique_id1)). It is binary-
  searched (FUN_0085fd20, comparator FUN_0085f680 = lexicographic over signed (i32, i32) pairs, then the shorter
  path first) in UidTable; the value is the u16 instance key. The +0x30 array holds the same paths by instance key.
Binding (FUN_00887460 per pivot, pivots in order): for SMB j of pivot p the key is (instance, p, j, VB+0 count,
  IB+0 count, Model+0x6C bit 23); a hit with a colour buffer attaches it; with bit 23 set every hit adds its
  entry colour (x 1/255 per channel, float32) and FUN_00889060 multiplies the sum by 1/(total SMB count of all
  pivots) and truncates x255 into Model+0x78 (the single-colour directional light).
Payload: the colour data of all colour buffers, in entry order, contiguous (== payload size in all 28 records).

Instance ownership (placed entities): a FRAGMENT (record type 4) payload is the level's entity graph (walk:
  tod_hd_scatter.walk_fragment). Every entity stores unique_id0 (#27) and unique_id1 (#28), builtin Node properties;
  a Model stores modelres (#38), the model path ('/Models/...', the model record is '/data/Models/...'). An instanced
  fragment (e.g. BigSpotLight_OnStick.fragment under several placing Nodes) contributes copies with the SAME unique
  id, so one uid can end several UidTable paths (different prefixes = different instance keys) and, where a copy
  overrides modelres, name several models under ONE instance key (4 of the 8,311 shipped instances: farm submap01
  #289 ADD_TelepoleLamp/ADD_TelepolePlainLamp, meat factory submap01 #26 and submap02 #296 (two Vehicle.model
  resources), industrial submap03 #40 ADDJumpWood/ADDJumpWoodKick). Checked on all 28 blocks with lighting
  (work/research/pinned_retarget/t0_owners.json): 8,307 instances resolve to exactly one model, those 4 to two, none
  to no entity; against the RE level dumps 7,390 agree, 0 disagree, 84 sit in shared script fragments the dumps lack.

API
  lighting_records(data, ext)                  every MESHCOLOR record, parsed exactly (keys, entries, uid tables, checks)
  retarget_counts(data, ext, signature, new_counts, pivot=0, colour_policy=None, ..., pin=None) -> (new_bytes, report)
  instance_owners(data, ext)                   every lighting instance -> the model(s) its placed entities reference
  pinned_instances(owners, model)              a model's own / shared / foreign / unresolved instances (the pin)
  model_mesh_counts / model_mesh_geometry      live counts (and positions/indices) of a model record
  engine_lookup / instance_key / simulate_binding   the engine's lookups, step by step, for verification
  relayout_record(rec, payload, regen)          size-pass re-layout (identity on all 28 shipped records)
"""
import bisect
import functools
import struct

import tod_hd_game as game
import tod_hd_scatter as scatter
from tod_hd_game import GameDataError

LIGHTING_TYPE = 10
HEADER = 0x50
ENTRY = 24
KEY = 16
COLOUR_BUFFER = 0x28
COUNT_MASK = 0xFFFFF
SINGLE_BIT = 0x10000
SENTINEL = 0xBAADF00D
NULL_TAG = 0x80000000


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def _a4(x):
    return (x + 3) & ~3


def _a16(x):
    return (x + 15) & ~15


def _f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


# ------------------------------------------------------------------------------------------------ engine rules

def key_words(key_bytes):
    return struct.unpack("<4I", key_bytes)


def key_less(a, b):
    """FUN_0085e470: True when key a sorts before key b. a, b = 4 u32 words."""
    ai, bi = a[1] & 0xFFFF, b[1] & 0xFFFF
    if ai != bi:
        return ai < bi
    ap, bp = (a[0] >> 16) & 0xFFFF, (b[0] >> 16) & 0xFFFF
    if ap != bp:
        return ap < bp
    am, bm = a[0] & 0xFFFF, b[0] & 0xFFFF
    if am != bm:
        return am < bm
    av, bv = a[2] & COUNT_MASK, b[2] & COUNT_MASK
    if av != bv:
        return av < bv
    ac, bc = a[3] & COUNT_MASK, b[3] & COUNT_MASK
    if ac != bc:
        return ac < bc
    return (a[1] & SINGLE_BIT) == 0 and (b[1] & SINGLE_BIT) != 0


def build_key(instance, pivot, mesh, vcount, icount, single, fill=(0, 0, 0, 0)):
    """FUN_0085e400: u16 mesh, u16 pivot, u16 instance, bit 16 flag, 20-bit counts; the remaining bits keep
    whatever the (uninitialised stack) buffer held, which the comparator never looks at."""
    w0 = ((pivot & 0xFFFF) << 16) | (mesh & 0xFFFF)
    w1 = (fill[1] & 0xFFFE0000) | (instance & 0xFFFF) | (SINGLE_BIT if single else 0)
    w2 = (fill[2] & 0xFFF00000) | (vcount & COUNT_MASK)
    w3 = (fill[3] & 0xFFF00000) | (icount & COUNT_MASK)
    return (w0, w1, w2, w3)


def engine_search(keys, search):
    """FUN_0085f2c0 step by step: returns the index whose value the engine reads, or None (miss)."""
    n = len(keys)
    lo, hi = 0, n
    if n:
        while True:
            mid = (hi - lo) // 2 + lo
            if key_less(keys[mid], search):
                lo = mid + 1
            else:
                hi = mid
            if lo == hi:
                break
    if hi < n and not key_less(search, keys[hi]):
        return hi
    return None


def uid_less(a, b):
    """FUN_0085f680 with FUN_0040fed0: lexicographic over (i32, i32) pairs, then the shorter path first."""
    for x, y in zip(a, b):
        if x[0] != y[0]:
            return x[0] < y[0]
        if x[1] != y[1]:
            return x[1] < y[1]
    return len(a) < len(b)


def engine_uid_search(paths, search):
    """FUN_0085fd20: lower-bound binary search over the UidTable keys; index or None."""
    n = len(paths)
    lo, hi = 0, n
    if n:
        while True:
            mid = (hi - lo) // 2 + lo
            if uid_less(paths[mid], search):
                lo = mid + 1
            else:
                hi = mid
            if lo == hi:
                break
    if hi < n and not uid_less(search, paths[hi]):
        return hi
    return None


# ------------------------------------------------------------------------------------------------ reader

class _Rec:
    """Exact size-pass replay of one lighting record; every pointer is checked against the emulated cursor.
    It also records the allocation sequence (kind, start, size) and every pointer field (field, target
    allocation), which is what relayout_record() needs to lay the record out again with other sizes."""

    def __init__(self, info, R, end, payload_len, index, name):
        self.info, self.R, self.end, self.index, self.name = info, R, end, index, name
        self.problems = []
        self.cur = R
        self.data = 0
        self.allocs = []          # {"kind", "start", "size", "entry"}; kind "align16" marks the per-entry alignment
        self.ptrs = []            # (field address, index of the allocation it points at)
        self.dptrs = []           # (field address, entry index) data pointers into the payload
        self._parse(payload_len)

    def fail(self, msg):
        raise GameDataError("lighting record %d (%s) at 0x%x: %s" % (self.index, self.name, self.R, msg))

    def ptr(self, field, what):
        v = _u32(self.info, field)
        if v == 0:
            return None
        if v & 3:
            self.fail("%s pointer at +0x%x has tag bits 0x%x" % (what, field - self.R, v & 3))
        t = field if v == NULL_TAG else (field + v) & 0xFFFFFFFF
        return t

    def expect(self, field, what):
        """The pointer must address the allocation the size pass creates next."""
        t = self.ptr(field, what)
        if t != self.cur:
            self.fail("%s pointer at +0x%x -> %s, size pass puts it at +0x%x" % (
                what, field - self.R, "null" if t is None else "+0x%x" % (t - self.R), self.cur - self.R))
        self.ptrs.append((field, len(self.allocs)))
        return t

    def alloc(self, kind, size, what, entry=None):
        if not (self.R <= self.cur and self.cur + size <= self.end):
            self.fail("%s (+0x%x, %d bytes) is outside the record" % (what, self.cur - self.R, size))
        self.allocs.append({"kind": kind, "start": self.cur, "size": size, "entry": entry})
        self.cur += size

    def vector(self, field, elem, kind, what, entry=None):
        cnt, cap = _u32(self.info, field + 4), _u32(self.info, field + 8)
        if cnt >= 0x1000000:
            self.fail("%s count %d" % (what, cnt))
        t = self.expect(field, what)
        self.alloc(kind, _a4(cnt * elem), what, entry)
        if cap != cnt:
            self.problems.append("%s capacity %d != count %d" % (what, cap, cnt))
        return t, cnt

    def table(self, field, kind, what):
        if _u32(self.info, field) == 0:
            return None, 0, None, None
        t = self.expect(field, what)
        self.alloc(kind + "_header", 16, what)
        n = _u32(self.info, t)
        if n >= 0x1000000:
            self.fail("%s count %d" % (what, n))
        kp = self.expect(t + 8, what + " keys")
        self.alloc(kind + "_keys", _a4(n * 16), what + " keys")
        vp = self.expect(t + 12, what + " values")
        self.alloc(kind + "_values", _a4(n * 2), what + " values")
        return t, n, kp, vp

    def _parse(self, payload_len):
        info, R = self.info, self.R
        if self.end - R < HEADER:
            self.fail("shorter than the 0x50 header")
        if _u32(info, R) != LIGHTING_TYPE or _u32(info, R + 0x0C) != SENTINEL:
            self.fail("not a type-10 record")
        self.alloc("header", HEADER, "header")                                   # FUN_0085ae90(0x50)
        np_ = self.expect(R + 4, "name")                                         # FUN_00851430 -> FUN_0040d0c0
        nm = game.cstring(info, np_)
        self.alloc("name", _a4(len(nm) + 1), "name")
        self.header_words = struct.unpack_from("<20I", info, R)

        # +0x20 entries (FUN_0085f6f0) and, per entry, align16 + colour buffer (FUN_00860b40 -> FUN_004622f0)
        self.entries_off, n_entries = self.vector(R + 0x20, ENTRY, "entries", "entry array")
        self.entries = []
        for i in range(n_entries):
            self.allocs.append({"kind": "align16", "start": None, "size": 0, "entry": i})
            self.cur = R + _a4(_a16(self.cur - R))
            E = self.entries_off + ENTRY * i
            e = {"index": i, "offset": E, "colour": _u32(info, E + 4), "key_copy": struct.unpack_from("<4I", info, E + 8),
                 "buffer": None}
            if _u32(info, E) & 0xFFFFFFFC:
                obj = self.expect(E, "colour buffer %d" % i)
                self.alloc("colour_buffer", COLOUR_BUFFER, "colour buffer %d" % i, i)
                bits = _u32(info, obj + 0x10)
                ncol = (bits >> 3) & 0xFFFFFF
                nstore = 4 if ncol < 5 else ncol
                dv = _u32(info, obj + 4)
                dt = ((obj + 4 - R) + dv) & 0xFFFFFFFF
                if dv & 3 or dt != self.data:
                    self.fail("colour buffer %d data pointer -> 0x%x, size pass puts it at payload 0x%x" % (i, dt, self.data))
                self.dptrs.append((obj + 4, i))
                data_off = self.data
                self.data += _a4(4 * nstore)
                icnt_field = _u32(info, obj + 0x14)
                ivec, icnt = self.vector(obj + 0x18, 2, "index_copy", "colour buffer %d index copy" % i, i)
                if icnt != icnt_field:
                    self.problems.append("colour buffer %d: +0x14 %d != index copy count %d" % (i, icnt_field, icnt))
                e["buffer"] = {"offset": obj, "count": ncol, "stored_colours": nstore, "bits": bits,
                               "data_offset": data_off, "data_size": _a4(4 * nstore),
                               "index_count": icnt_field, "index_copy_offset": ivec, "index_copy_count": icnt}
            self.entries.append(e)

        # +0x30 unique-id paths (index = instance key): FUN_008b4d70, then FUN_0040d260 per element
        self.paths_off, n_paths = self.vector(R + 0x30, 16, "paths", "uid path array")
        self.paths = []
        for j in range(n_paths):
            po, pc = self.vector(self.paths_off + 16 * j, 8, "path_data", "uid path %d" % j)
            self.paths.append(tuple(struct.unpack_from("<ii", info, po + 8 * k) for k in range(pc)))

        # +0x48 key table (FUN_00860db0)
        self.kt_off, n_keys, self.keys_off, self.values_off = self.table(R + 0x48, "key_table", "key table")
        if self.kt_off is None:
            self.fail("key table pointer is null")
        self.keys = [struct.unpack_from("<4I", info, self.keys_off + 16 * k) for k in range(n_keys)]
        self.values = list(struct.unpack_from("<%dH" % n_keys, info, self.values_off)) if n_keys else []

        # +0x40 unique-id table (FUN_00860db0, then FUN_0040d260 per key)
        self.ut_off, n_uid, ukeys, uvals = self.table(R + 0x40, "uid_table", "uid table")
        if self.ut_off is None:
            self.fail("uid table pointer is null (the serializer dereferences it)")
        self.uid_keys = []
        for k in range(n_uid):
            po, pc = self.vector(ukeys + 16 * k, 8, "uid_data", "uid key %d" % k)
            self.uid_keys.append(tuple(struct.unpack_from("<ii", info, po + 8 * m) for m in range(pc)))
        self.uid_values = list(struct.unpack_from("<%dH" % n_uid, info, uvals)) if n_uid else []
        self.uid_keys_off, self.uid_values_off = ukeys, uvals

        self.size = self.cur - R
        if R + _a16(self.size) != self.end:
            self.fail("exact size 0x%x aligns to 0x%x but the next record starts at +0x%x" % (
                self.size, _a16(self.size), self.end - R))
        if self.data != payload_len:
            self.fail("colour data %d bytes but the payload is %d bytes" % (self.data, payload_len))
        self.checks = self._semantic_checks()

    def _semantic_checks(self):
        c = {}
        c["keys_sorted_strict"] = all(key_less(self.keys[k], self.keys[k + 1]) for k in range(len(self.keys) - 1))
        c["values_index_entries"] = all(v < len(self.entries) for v in self.values)
        c["binary_search_finds_every_key"] = all(
            engine_search(self.keys, kw) is not None and self.values[engine_search(self.keys, kw)] == self.values[k]
            for k, kw in enumerate(self.keys))
        c["uid_keys_sorted_strict"] = all(uid_less(self.uid_keys[k], self.uid_keys[k + 1]) for k in range(len(self.uid_keys) - 1))
        c["uid_values_index_paths"] = all(v < len(self.paths) and self.paths[v] == self.uid_keys[k]
                                          for k, v in enumerate(self.uid_values))
        c["uid_values_are_permutation_of_paths"] = sorted(self.uid_values) == list(range(len(self.paths)))
        c["key_instances_have_uid_path"] = all((w[1] & 0xFFFF) < len(self.paths) for w in self.keys)
        mode_ok = True
        for kw, v in zip(self.keys, self.values):
            e = self.entries[v]
            single = bool(kw[1] & SINGLE_BIT)
            if single == (e["buffer"] is not None):
                mode_ok = False
            if e["buffer"] is not None and e["buffer"]["count"] != kw[2] & COUNT_MASK:
                mode_ok = False
        c["entry_mode_matches_key_flag_and_vcount"] = mode_ok
        c["colour_buffer_index_count_matches_key_icount"] = all(
            self.entries[v]["buffer"] is None or self.entries[v]["buffer"]["index_count"] == kw[3] & COUNT_MASK
            for kw, v in zip(self.keys, self.values))
        c["entry_key_copy_matches_key"] = all(
            _masked(self.entries[v]["key_copy"]) == _masked(kw) for kw, v in zip(self.keys, self.values))
        c["each_entry_referenced_once"] = sorted(self.values) == list(range(len(self.entries)))
        return c


def _masked(w):
    return (w[0] & 0xFFFFFFFF, w[1] & 0x1FFFF, w[2] & COUNT_MASK, w[3] & COUNT_MASK)


def _key_dict(k, w, v, offset):
    return {"position": k, "offset": offset, "mesh": w[0] & 0xFFFF, "pivot": (w[0] >> 16) & 0xFFFF,
            "instance": w[1] & 0xFFFF, "single": bool(w[1] & SINGLE_BIT),
            "vcount": w[2] & COUNT_MASK, "icount": w[3] & COUNT_MASK, "value": v, "words": w}


def _parse_block(blk):
    out = []
    for r in blk.records:
        if r["type"] != LIGHTING_TYPE:
            continue
        out.append(_Rec(blk.info, r["offset"], r["end"], blk.sizes[r["index"]], r["index"], r["name"]))
    return out


def lighting_records(data, ext):
    """Parse every MESHCOLOR record of a block from scratch (offsets are only valid for these bytes)."""
    blk = game.Block(data, ext)
    res = []
    for rec in _parse_block(blk):
        res.append(_record_dict(rec, blk))
    return res


def _record_dict(rec, blk):
    return {
        "index": rec.index, "offset": rec.R, "end": rec.end, "size": rec.size, "name": rec.name,
        "payload_size": blk.sizes[rec.index],
        "key_table_offset": rec.kt_off, "keys_offset": rec.keys_off, "values_offset": rec.values_off,
        "keys": [_key_dict(k, w, v, rec.keys_off + 16 * k) for k, (w, v) in enumerate(zip(rec.keys, rec.values))],
        "entries": [{"index": e["index"], "offset": e["offset"],
                     "mode": "vertex" if e["buffer"] else "single", "colour": e["colour"],
                     "key_copy": _key_dict(None, e["key_copy"], None, e["offset"] + 8), "buffer": e["buffer"]}
                    for e in rec.entries],
        "instances": [{"instance": v, "uid_path": rec.uid_keys[k]} for k, v in enumerate(rec.uid_values)],
        "uid_paths": list(rec.paths),
        "checks": dict(rec.checks), "problems": list(rec.problems),
    }


# ------------------------------------------------------------------------------------------------ engine simulation

def engine_lookup(record, instance, pivot, mesh, vcount, icount, single):
    """FUN_0085e6b0 on a lighting_records() dict: entry index or -1."""
    keys = [k["words"] for k in record["keys"]]
    pos = engine_search(keys, build_key(instance, pivot, mesh, vcount, icount, single))
    return -1 if pos is None else record["keys"][pos]["value"]


def instance_key(record, uid_path):
    """FUN_0085e7a0: u16 instance key for a Model whose FUN_0088f510 path is uid_path, or -1."""
    paths = [i["uid_path"] for i in record["instances"]]
    pos = engine_uid_search(paths, tuple(tuple(x) for x in uid_path))
    return -1 if pos is None else record["instances"][pos]["instance"]


def simulate_binding(record, instance, pivots, single, smb_flags=None):
    """FUN_00887460 for every pivot + the FUN_00889060 average.
    pivots: list (pivot order) of lists (SMB order) of (vcount, icount); smb_flags: same shape (u32) or None.
    Returns {"lookups": [(pivot, mesh, entry)], "colour_buffers": [...], "sum": [4 float32], "argb": int|None}."""
    ents = record["entries"]
    keys = [k["words"] for k in record["keys"]]
    total_smbs = sum(len(p) for p in pivots if len(p) > 0)
    unlit_model = False
    if smb_flags:
        for p in smb_flags:
            if p:
                unlit_model = bool((p[0] >> 21) & 1)          # FUN_00855e20
                break
    acc = [0.0, 0.0, 0.0, 0.0]
    k255 = _f32(struct.unpack("<f", bytes.fromhex("8180803b"))[0])   # DAT_009b38e8
    lookups, bufs = [], []
    for p, meshes in enumerate(pivots):
        for j, (vc, ic) in enumerate(meshes):
            skip = unlit_model or (smb_flags is not None and (smb_flags[p][j] >> 22) & 1)
            pos = None if skip else engine_search(keys, build_key(instance, p, j, vc, ic, single))
            e = -1 if pos is None else record["keys"][pos]["value"]
            lookups.append((p, j, e))
            if e != -1 and ents[e]["buffer"] is not None:
                bufs.append((p, j, e))
            if single and e != -1:
                c = ents[e]["colour"]
                for ch in range(4):
                    acc[ch] = _f32(acc[ch] + _f32(float((c >> (8 * ch)) & 0xFF) * k255))
    argb = None
    if single and total_smbs:
        inv = _f32(1.0 / float(total_smbs))
        packed = 0
        for ch in (3, 2, 1, 0):
            packed = (packed << 8) | int(_f32(_f32(inv * acc[ch]) * 255.0))
        argb = packed & 0xFFFFFFFF
    return {"lookups": lookups, "colour_buffers": bufs, "sum": acc, "argb": argb}


# ------------------------------------------------------------------------------------------------ model data

def _model_walk(blk, name_part, geometry):
    info = blk.info
    out = []

    def sp(o, lo, hi):
        v = _u32(info, o)
        if v == 0:
            return None
        t = (o + v) & 0xFFFFFFFC
        if not lo <= t < hi:
            raise GameDataError("model pointer at 0x%x leaves its record" % o)
        return t

    for r in blk.records:
        if r["type"] != 3 or name_part.lower() not in r["name"].lower():
            continue
        R, E = r["offset"], r["end"]
        pl = sp(R + 0x30, R, E)
        pivots, flags, geo = [], [], []
        for i in range(_u32(info, R + 0x34)):
            P = pl + 0x7C * i
            sl = sp(P + 0x24, R, E)
            meshes, fl, gm = [], [], []
            for j in range(_u32(info, P + 0x28)):
                S = sl + 0x3C * j
                mb = sp(S, R, E)
                vb, ib = sp(mb + 0x0C, R, E), sp(mb + 0x10, R, E)
                vc, ic = _u32(info, vb), _u32(info, ib)
                meshes.append((vc, ic))
                fl.append(_u32(info, S + 0x38))
                if geometry:
                    stride = struct.unpack_from("<H", info, vb + 0x14)[0]
                    vd, idd = sp(vb + 0x10, R, E), sp(ib + 0x0C, R, E)
                    if _u32(info, vb + 0x0C) != vc * stride or vd + vc * stride > E or idd + 2 * ic > E:
                        raise GameDataError("%s pivot %d mesh %d: vertex/index data inconsistent" % (r["name"], i, j))
                    gm.append({"stride": stride, "fvf": _u32(info, vb + 0x08),
                               "positions": [struct.unpack_from("<3f", info, vd + stride * v) for v in range(vc)],
                               "indices": list(struct.unpack_from("<%dH" % ic, info, idd)) if ic else []})
            pivots.append(meshes)
            flags.append(fl)
            geo.append(gm)
        d = {"index": r["index"], "offset": R, "name": r["name"], "pivots": pivots, "smb_flags": flags}
        if geometry:
            d["geometry"] = geo
        out.append(d)
    return out


def model_mesh_counts(data, ext, name_part):
    """Live (vcount, icount) and SMB flags per pivot/SMB for every MODEL record whose name contains name_part.
    Follows only self-relative pointers (ModelAsset+0x30 pivots, pivot+0x24 SMBs, SMB+0 MeshBuffer, MB+0x0C VB,
    MB+0x10 IB) with range checks, so it works on rebuilt blocks too."""
    return _model_walk(game.Block(data, ext), name_part, False)


def model_mesh_geometry(data, ext, name_part):
    """model_mesh_counts plus per mesh {"stride", "fvf", "positions" [(x,y,z)], "indices" [u16]} (pivot-local)."""
    return _model_walk(game.Block(data, ext), name_part, True)


# ------------------------------------------------------------------------------------------------ record layout

_FILL = b"\x0d\xf0\xad\xba"          # 0xBAADF00D, the fill the shipped gaps carry


def _fill(n):
    return (_FILL * (n // 4 + 1))[:n]


def relayout_record(rec, payload, regen=None):
    """Lay one parsed lighting record out again with the engine's size pass.
    regen: {entry index: (colours [u32], indices [u16])} replaces that entry's colour buffer contents (the entry
    must already own a colour buffer). Returns (record bytes padded to 16, payload bytes). With regen empty the
    result is byte-identical to the shipped record and payload (checked for all 28 by the test suite)."""
    regen = regen or {}
    info, R = rec.info, rec.R
    for e in regen:
        if rec.entries[e]["buffer"] is None:
            raise GameDataError("entry %d has no colour buffer to regenerate" % e)
    old_start, new_start, sizes = [], [], []
    cur, data = 0, 0
    new_data = {}
    for a in rec.allocs:
        if a["kind"] == "align16":
            cur = _a4(_a16(cur))
            old_start.append(None)
            new_start.append(None)
            sizes.append(0)
            continue
        size = a["size"]
        if a["kind"] == "index_copy" and a["entry"] in regen:
            size = _a4(2 * len(regen[a["entry"]][1]))
        if a["kind"] == "colour_buffer":
            e = a["entry"]
            n = len(regen[e][0]) if e in regen else rec.entries[e]["buffer"]["count"]
            new_data[e] = (data, _a4(4 * (4 if n < 5 else n)))
            data += new_data[e][1]
        old_start.append(a["start"] - R)
        new_start.append(cur)
        sizes.append(size)
        cur += size
    new_size = cur
    out = bytearray(_a16(new_size))
    old_rec = bytes(info[R:rec.end])

    # contents and gaps, allocation by allocation (gaps keep their shipped bytes when their length is unchanged)
    real = [k for k, a in enumerate(rec.allocs) if a["kind"] != "align16"]
    prev_old_end, prev_new_end = 0, 0
    for k in real:
        a = rec.allocs[k]
        og, ng = old_start[k] - prev_old_end, new_start[k] - prev_new_end
        out[prev_new_end:new_start[k]] = old_rec[prev_old_end:old_start[k]] if og == ng else _fill(ng)
        if a["kind"] == "index_copy" and a["entry"] in regen:
            idx = regen[a["entry"]][1]
            blob = struct.pack("<%dH" % len(idx), *idx) if idx else b""
            blob += _fill(sizes[k] - len(blob))
            out[new_start[k]:new_start[k] + sizes[k]] = blob
        else:
            out[new_start[k]:new_start[k] + sizes[k]] = old_rec[old_start[k]:old_start[k] + a["size"]]
        prev_old_end, prev_new_end = old_start[k] + a["size"], new_start[k] + sizes[k]
    og, ng = len(old_rec) - prev_old_end, len(out) - prev_new_end
    out[prev_new_end:] = old_rec[prev_old_end:] if og == ng else _fill(ng)

    # colour-buffer object fields of regenerated entries
    for k in real:
        a = rec.allocs[k]
        if a["kind"] == "colour_buffer" and a["entry"] in regen:
            cols, idx = regen[a["entry"]]
            o = new_start[k]
            bits = _u32(out, o + 0x10)
            struct.pack_into("<I", out, o + 0x10, (bits & ~(0xFFFFFF << 3) & 0xFFFFFFFF) | (len(cols) << 3))
            struct.pack_into("<III", out, o + 0x14, len(idx), 0, len(idx))
            struct.pack_into("<I", out, o + 0x20, len(idx))

    # pointers: every recorded field gets target_new - field_new
    starts = sorted((old_start[k], rec.allocs[k]["size"], k) for k in real if rec.allocs[k]["size"] > 0)
    keys_ = [s_[0] for s_ in starts]

    def new_addr(old_abs):
        rel = old_abs - R
        p = bisect.bisect_right(keys_, rel) - 1
        s0, sz, k = starts[p]
        if not s0 <= rel < s0 + sz:
            raise GameDataError("pointer field +0x%x is not inside an allocation" % rel)
        return new_start[k] + (rel - s0)

    for field, target in rec.ptrs:
        f = new_addr(field)
        v = (new_start[target] - f) & 0xFFFFFFFF
        struct.pack_into("<I", out, f, NULL_TAG if v == 0 else v)
    for field, e in rec.dptrs:
        f = new_addr(field)
        struct.pack_into("<I", out, f, (new_data[e][0] - f) & 0xFFFFFFFF)

    # payload
    pay = bytearray(data)
    for e, (off, size) in new_data.items():
        if e in regen:
            cols = list(regen[e][0])
            blob = struct.pack("<%dI" % len(cols), *[c & 0xFFFFFFFF for c in cols]) if cols else b""
            pay[off:off + size] = blob + bytes(size - len(blob))
        else:
            b = rec.entries[e]["buffer"]
            pay[off:off + size] = payload[b["data_offset"]:b["data_offset"] + b["data_size"]]
    return bytes(out), bytes(pay)


def nearest_vertex_map(old_positions, new_positions):
    """For every new vertex, the index of the nearest old vertex (squared distance, lowest index on ties)."""
    if not old_positions:
        raise GameDataError("nearest colour policy needs at least one old vertex")
    ox = [p[0] for p in old_positions]
    oy = [p[1] for p in old_positions]
    oz = [p[2] for p in old_positions]
    rng = range(len(old_positions))
    out = []
    for x, y, z in new_positions:
        best, bi = None, 0
        for i in rng:
            dx, dy, dz = ox[i] - x, oy[i] - y, oz[i] - z
            d = dx * dx + dy * dy + dz * dz
            if best is None or d < best:
                best, bi = d, i
        out.append(bi)
    return out


# ------------------------------------------------------------------------------------------------ instance ownership

FRAGMENT_TYPE = 4
PROP_UNIQUE_ID0, PROP_UNIQUE_ID1, PROP_MODELRES = 27, 28, 38     # builtin Node, Node, Model property indices
UNDECODABLE = "<undecodable modelres>"


def model_key(path):
    """A model path as the engine's (case-insensitive) file lookup sees it: '/' separators, lower case, no '/data'
    root. Model records are named '/data/Models/...', a placed entity's modelres is '/Models/...'."""
    p = str(path or "").replace("\\", "/").lower()
    return p[5:] if p.startswith("/data/") else p


def _fragment_string(blob, op):
    """A string property value: [u32 n][n words of asciiz]; None unless the walked value is exactly that."""
    off, words = op["value_offset"], op["words"]
    if words < 1 or off + 4 * words > len(blob):
        return None
    n = _u32(blob, off)
    if n + 1 != words:
        return None
    raw = bytes(blob[off + 4:off + 4 + 4 * n])
    end = raw.find(b"\0")
    return raw[:end if end >= 0 else len(raw)].decode("latin-1")


def placed_models_by_uid(data, ext):
    """-> ({(unique_id0, unique_id1) as signed i32: set of model_key(modelres)}, stats) over every entity of every
    FRAGMENT record of the block that stores a modelres. The last value set wins, as when the engine replays the
    stream; entities are keyed per fragment (node ids repeat across fragments)."""
    blk = game.Block(data, ext)
    by_uid = {}
    stats = {"fragments": 0, "entities": 0, "models": 0, "models_without_uid": 0, "undecodable_values": 0}
    for r in blk.records:
        if r["type"] != FRAGMENT_TYPE:
            continue
        stats["fragments"] += 1
        blob = bytes(blk.payloads[r["index"]])
        ops, _ = scatter.walk_fragment(blob)
        ents = {}
        for o in ops:
            if o["op"] == "create":
                ents.setdefault(o["node"], {})
            elif o["op"] == "setprop" and o["prop"] in (PROP_UNIQUE_ID0, PROP_UNIQUE_ID1, PROP_MODELRES):
                e = ents.setdefault(o["node"], {})
                if o["prop"] == PROP_MODELRES:
                    v = _fragment_string(blob, o)
                elif o["words"] == 1:
                    v = _i32(blob, o["value_offset"])
                else:
                    v = None
                if v is None:
                    stats["undecodable_values"] += 1
                    e.pop(o["prop"], None)
                    e.setdefault("bad", set()).add(o["prop"])
                else:
                    e[o["prop"]] = v
                    e.get("bad", set()).discard(o["prop"])
        stats["entities"] += len(ents)
        for e in ents.values():
            bad_model = PROP_MODELRES in e.get("bad", ())
            if PROP_MODELRES not in e and not bad_model:
                continue
            stats["models"] += 1
            if PROP_UNIQUE_ID0 not in e or PROP_UNIQUE_ID1 not in e:
                stats["models_without_uid"] += 1
                continue
            # an undecodable modelres poisons its uid: the instance can then never count as one model's own
            by_uid.setdefault((e[PROP_UNIQUE_ID0], e[PROP_UNIQUE_ID1]), set()).add(
                UNDECODABLE if bad_model else model_key(e[PROP_MODELRES]))
    return by_uid, stats


def instance_owners(data, ext):
    """Every baked-lighting instance of the block -> the model(s) of the placed entities it belongs to.
    FUN_0085e7a0 looks a placed Model's UidTable path up to get its instance key, and that path ENDS with the
    entity's own (unique_id0, unique_id1) (FUN_0088f510 / FUN_008911d0); so the owners of an instance are the
    modelres of every entity in the block's fragments that carries the path's last uid. The UidTable is read
    exactly as instance_key() reads it.
    -> {"records": {lighting record index: {instance key: tuple(sorted model keys)}}, "stats": {...}};
    an empty tuple means no placed entity with a modelres carries that uid (unresolved)."""
    recs = lighting_records(data, ext)
    out = {"records": {}, "stats": {"lighting_records": len(recs), "instances": 0, "one_model": 0,
                                     "several_models": 0, "unresolved": 0}}
    if not recs:
        return out
    by_uid, st = placed_models_by_uid(data, ext)
    out["stats"].update(st)
    for rec in recs:
        per = {}
        paths = [i["uid_path"] for i in rec["instances"]]
        for k, i in enumerate(rec["instances"]):
            path = i["uid_path"]
            models = tuple(sorted(by_uid.get(tuple(path[-1]), ()))) if path else ()
            if engine_uid_search(paths, path) != k:          # instance_key(): the engine's own lookup of this path
                raise GameDataError("lighting record %s: the UidTable lookup of instance %d's own path does not find it"
                                    % (rec["name"], i["instance"]))
            per[i["instance"]] = models
            out["stats"]["instances"] += 1
            out["stats"]["one_model" if len(models) == 1 else ("unresolved" if not models else "several_models")] += 1
        out["records"][rec["index"]] = per
    return out


def pinned_instances(owners, model):
    """The pin for retarget_counts: `model`'s own placed instances, from instance_owners(). Per lighting record:
      own         every entity carrying the instance's uid references this model - the only instances it may touch
      shared      this model AND another one (an instanced fragment whose copies override modelres share one key)
      foreign     other models only: a sibling that merely shares the mesh-count signature - never touched
      unresolved  no placed entity of this block with a modelres carries the uid
    -> {"model": model_key, "records": {record index: {"own": [..], "shared": {i: [..]}, "foreign": {i: [..]},
        "unresolved": [..]}}, "own": total own count}"""
    mk = model_key(model)
    res = {"model": mk, "records": {}, "own": 0}
    for idx, per in owners["records"].items():
        r = {"own": [], "shared": {}, "foreign": {}, "unresolved": []}
        for inst, models in sorted(per.items()):
            if not models:
                r["unresolved"].append(inst)
            elif mk not in models:
                r["foreign"][inst] = list(models)
            elif len(models) == 1:
                r["own"].append(inst)
            else:
                r["shared"][inst] = list(models)
        res["records"][idx] = r
        res["own"] += len(r["own"])
    return res


# ------------------------------------------------------------------------------------------------ retarget

def match_instances(rec_or_dict, signature, pivot=0, allow_extra_keys=False):
    """Instance keys whose keys on `pivot` carry every (mesh -> (vcount, icount)) of the signature.
    Returns (matched, partial, superset). Unless allow_extra_keys, a matching instance with any other key
    (another pivot or mesh index) is put in superset and not matched."""
    if isinstance(rec_or_dict, dict):
        keys = [k["words"] for k in rec_or_dict["keys"]]
    else:
        keys = rec_or_dict.keys
    groups = {}
    for k, w in enumerate(keys):
        groups.setdefault(w[1] & 0xFFFF, []).append(k)
    matched, partial, superset = [], [], []
    for inst, ks in sorted(groups.items()):
        have = {}
        for k in ks:
            w = keys[k]
            have.setdefault(((w[0] >> 16) & 0xFFFF, w[0] & 0xFFFF), []).append((w[2] & COUNT_MASK, w[3] & COUNT_MASK))
        hits = sum(1 for m, cnt in signature.items() if cnt in have.get((pivot, m), []))
        if hits == 0:
            continue
        if hits < len(signature):
            partial.append(inst)
            continue
        if len(ks) != len(signature) and not allow_extra_keys:
            superset.append(inst)
            continue
        matched.append(inst)
    return matched, partial, superset


def _check_order(keys, values):
    strict = all(key_less(keys[k], keys[k + 1]) for k in range(len(keys) - 1))
    found = True
    for k, kw in enumerate(keys):
        pos = engine_search(keys, kw)
        if pos is None or values[pos] != values[k]:
            found = False
            break
    return strict, found


def resort_keys(keys, values):
    """Sort (key, value) pairs together in comparator order; refuse keys that compare equal."""
    order = sorted(range(len(keys)), key=functools.cmp_to_key(
        lambda a, b: -1 if key_less(keys[a], keys[b]) else (1 if key_less(keys[b], keys[a]) else 0)))
    nk, nv = [keys[i] for i in order], [values[i] for i in order]
    for k in range(len(nk) - 1):
        if not key_less(nk[k], nk[k + 1]):
            raise GameDataError("two lighting keys compare equal after retargeting (%r / %r)" % (nk[k], nk[k + 1]))
    return nk, nv


def _pin_filter(rec, pin, pivot, matched, partial, superset, rrep):
    """retarget_counts(pin=...): keep the model's own instances of this record (see retarget_counts)."""
    pr = pin["records"].get(rec.index)
    listed = set() if pr is None else (set(pr["own"]) | set(pr["shared"]) | set(pr["foreign"]) | set(pr["unresolved"]))
    if pr is None or listed != set(rec.uid_values):
        raise GameDataError("the pin for %s does not describe lighting record %d (%s): it was resolved from other bytes"
                            % (pin.get("model"), rec.index, rec.name))
    own, unresolved = set(pr["own"]), set(pr["unresolved"])
    bad = [i for i in matched if i in pr["shared"] or i in unresolved]
    if bad:
        raise GameDataError(
            "pivot %d: lighting instance(s) %s carry this signature but cannot be proven to be %s's own (%s); "
            "refusing to rewrite them. Geometry 'lighting': {'pin': false} falls back to the signature alone."
            % (pivot, bad[:8], pin.get("model"), "; ".join(
                "%d: %s" % (i, "shared with " + ", ".join(m for m in pr["shared"][i] if m != pin.get("model"))
                            if i in pr["shared"] else "no placed entity of this block carries its unique id")
                for i in bad[:4])))
    skipped = [i for i in matched if i not in own]
    rrep["instances_signature_matched"] = list(matched)
    rrep["instances_skipped_foreign"] = skipped
    rrep["instances_skipped_owners"] = {i: pr["foreign"][i] for i in skipped}
    rrep["pinned_own_instances"] = len(own)
    matched = [i for i in matched if i in own]
    partial = [i for i in partial if i in own]
    superset = [i for i in superset if i in own]
    rrep["instances_matched"], rrep["instances_partial_signature"], rrep["instances_with_extra_keys"] = matched, partial, superset
    return matched, partial, superset


def _pin_expected(pin, pivot, want, report):
    """retarget_counts(pin=..., expect_instances=...): split the reference's list into own and foreign instances.
    Instance ids are compared across the block's lighting records, as the unpinned check does (every shipped block
    has at most one lighting record)."""
    own, foreign = set(), set()
    for pr in pin["records"].values():
        own |= set(pr["own"])
        foreign |= set(pr["foreign"])
    odd = [i for i in want if i not in own and i not in foreign]
    if odd:
        raise GameDataError("pivot %d: the reference lists lighting instance(s) %s that are neither %s's own placements "
                            "nor another model's in this block; refusing" % (pivot, odd[:8], pin.get("model")))
    report["instances_expected_foreign"] = sorted(i for i in want if i in foreign)
    return [i for i in want if i in own]


_TABLE_CHECKS = ("keys_sorted_strict", "values_index_entries", "binary_search_finds_every_key", "each_entry_referenced_once",
                 "entry_mode_matches_key_flag_and_vcount", "colour_buffer_index_count_matches_key_icount",
                 "uid_keys_sorted_strict", "uid_values_index_paths", "uid_values_are_permutation_of_paths",
                 "key_instances_have_uid_path")


def retarget_counts(data, ext, signature, new_counts, pivot=0, colour_policy=None, allow_extra_keys=False,
                    patch_entry_copies=True, old_positions=None, new_positions=None, new_indices=None,
                    require_match=False, expect_instances=None, pin=None):
    """Keep baked lighting attached to a model whose mesh counts changed.

    signature  {mesh_index: (old_vcount, old_icount)} on `pivot` - an instance is matched only when its keys carry
               every pair (and, unless allow_extra_keys, no other key)
    new_counts {mesh_index: (new_vcount, new_icount)} for the meshes whose counts change
    require_match  True: raise GameDataError when no instance in the block matches the signature (the caller
               believes the model has baked instances here); False (default): return the block unchanged
    expect_instances  the exact instance ids this retarget is allowed to touch (from the reference dump, where
               they were resolved through the level's unique_id -> modelres and proven to belong to this model).
               A mesh-count signature is NOT an identity: StandardDoor_A_MultiMaterial's pivot 0 carries the same
               (48, 70) counts as the whole jungle_bananatree, so a signature match alone can rewrite - and black
               out - another model's baked lighting. Any difference raises before a byte is written.
    pin        None: the signature is matched against every instance of the block (the behaviour before 2026-09-19).
               pinned_instances(instance_owners(block), model) of the model being retargeted (the block's input
               bytes; fragments and UidTables never change here): only its OWN placed instances can match, so a
               sibling model whose keys carry the same signature is never touched (its instances are skipped and
               listed as instances_skipped_foreign). A signature match on a shared or unresolved instance raises
               (whose lighting it is cannot be proven). With expect_instances, the reference list is first split
               into own (must equal the pinned match exactly) and foreign (skipped); an id that is neither raises.
               When every signature-matched instance is the model's own, the result is byte-identical to pin=None.
    Returns (new_bytes, report). The block is always parsed fresh, so it may already be rebuilt by the model rewriter.

      * matched single-colour keys: only the 20-bit count fields change, in place (same length); if that ever
        broke the comparator order the table is re-sorted with its u16 values and every key is re-found with the
        engine's binary search
      * patch_entry_copies: the same count fields are updated in the key copy at entry+0x08 (shipped invariant:
        entry key copy == its table key in 34,789 of 34,789 keys; the runtime lookup never reads it)
      * matched per-vertex keys (colour buffer of vcount colours + icount index copy): refused (GameDataError)
        unless colour_policy='nearest', which needs old_positions / new_positions {mesh: [(x,y,z)]} and new_indices
        {mesh: [u16]} (pivot-local, from the model record) and rebuilds each such colour buffer: colour of every new
        vertex = colour of the nearest old vertex, index copy = new index list. The lighting record and its payload
        grow, so every later record shifts (records stay 16-aligned) and the block's S (and maybe M) change.
    """
    if colour_policy not in (None, "nearest"):
        raise GameDataError("unknown colour_policy %r" % (colour_policy,))
    signature = {int(m): (int(v), int(i)) for m, (v, i) in signature.items()}
    new_counts = {int(m): (int(v), int(i)) for m, (v, i) in new_counts.items()}
    if not signature:
        raise GameDataError("empty signature")
    if not set(new_counts) <= set(signature):
        raise GameDataError("new_counts names meshes %s that are not in the signature" % sorted(set(new_counts) - set(signature)))
    for m, (v, i) in list(signature.items()) + list(new_counts.items()):
        if not (0 <= m <= 0xFFFF and 0 <= v <= COUNT_MASK and 0 <= i <= COUNT_MASK):
            raise GameDataError("mesh %d counts (%d, %d) do not fit the key fields" % (m, v, i))
    if not 0 <= pivot <= 0xFFFF:
        raise GameDataError("pivot %d does not fit the key field" % pivot)

    old_blk = game.Block(data, ext)
    old_recs = _parse_block(old_blk)
    report = {"lighting_records": len(old_recs), "records": [], "keys_patched": 0, "instances_matched": 0,
              "entries_regenerated": 0, "record_growth_bytes": 0, "payload_growth_bytes": 0,
              "S_before": len(old_blk.info), "M_before": old_blk.max_asset}
    plans = []
    maps = {}
    for rec in old_recs:
        matched, partial, superset = match_instances(rec, signature, pivot, allow_extra_keys)
        rrep = {"index": rec.index, "name": rec.name, "offset": rec.R, "keys": len(rec.keys),
                "instances_matched": matched, "instances_partial_signature": partial,
                "instances_with_extra_keys": superset, "patched": [], "regenerated": [], "resorted": False}
        if pin is not None:
            matched, partial, superset = _pin_filter(rec, pin, pivot, matched, partial, superset, rrep)
        report["records"].append(rrep)
        mset = set(matched)
        modes = {}
        patches, regen = {}, {}
        for k, w in enumerate(rec.keys):
            inst = w[1] & 0xFFFF
            if inst not in mset:
                continue
            modes.setdefault(inst, set()).add("single" if w[1] & SINGLE_BIT else "vertex")
            p, m = (w[0] >> 16) & 0xFFFF, w[0] & 0xFFFF
            if p != pivot or m not in new_counts or (w[2] & COUNT_MASK, w[3] & COUNT_MASK) != signature[m]:
                continue
            nv, ni = new_counts[m]
            if (nv, ni) == signature[m]:
                continue
            e = rec.entries[rec.values[k]]
            if patch_entry_copies and _masked(e["key_copy"]) != _masked(w):
                raise GameDataError("entry %d key copy does not match its table key; refusing to guess" % e["index"])
            if e["buffer"] is not None:
                if colour_policy is None:
                    raise GameDataError(
                        "instance %d mesh %d uses a per-vertex colour buffer (%d colours, %d-index copy, entry %d) "
                        "whose size depends on the old counts; pass colour_policy='nearest' with old/new positions "
                        "and new indices to regenerate it" % (inst, m, e["buffer"]["count"], e["buffer"]["index_count"], e["index"]))
                ov, oi = signature[m]
                for label, src, n in (("old_positions", old_positions, ov), ("new_positions", new_positions, nv), ("new_indices", new_indices, ni)):
                    if not src or m not in src or len(src[m]) != n:
                        raise GameDataError("colour_policy 'nearest': %s[%d] must hold exactly %d items" % (label, m, n))
                if any(not 0 <= x < nv for x in new_indices[m]):
                    raise GameDataError("colour_policy 'nearest': new_indices[%d] addresses a vertex >= %d" % (m, nv))
                if e["buffer"]["count"] != ov:
                    raise GameDataError("entry %d holds %d colours, the signature says %d vertices" % (e["index"], e["buffer"]["count"], ov))
                if m not in maps:
                    maps[m] = nearest_vertex_map(old_positions[m], new_positions[m])
                b = e["buffer"]
                pay = old_blk.payloads[rec.index]
                old_cols = struct.unpack_from("<%dI" % b["count"], pay, b["data_offset"]) if b["count"] else ()
                regen[e["index"]] = ([old_cols[i] for i in maps[m]], [int(x) for x in new_indices[m]])
                rrep["regenerated"].append({"entry": e["index"], "instance": inst, "mesh": m, "old": signature[m], "new": (nv, ni)})
            patches[k] = (nv, ni)
            rrep["patched"].append({"position": k, "instance": inst, "pivot": p, "mesh": m, "single": bool(w[1] & SINGLE_BIT),
                                    "entry": rec.values[k], "old": signature[m], "new": (nv, ni)})
        rrep["instance_modes"] = {i: sorted(s) for i, s in sorted(modes.items())}
        rrep["entry_copies_patched"] = len(patches) if patch_entry_copies else 0
        if patches:
            plans.append((rec, patches, regen))
        report["keys_patched"] += len(patches)
        report["instances_matched"] += len(matched)
        report["entries_regenerated"] += len(regen)

    if pin is not None:
        report["pin"] = {"model": pin.get("model"), "own_instances": pin.get("own"),
                         "skipped_foreign": sum(len(r.get("instances_skipped_foreign", ())) for r in report["records"])}
    if require_match and not report["instances_matched"]:
        raise GameDataError("no %sinstance in this block carries the signature %s on pivot %d (%d lighting record(s), "
                            "%d keys): require_match=True" % ("OWN " if pin is not None else "", sorted(signature.items()),
                                                              pivot, len(old_recs), sum(len(r.keys) for r in old_recs)))
    if expect_instances is not None:
        want = sorted(int(i) for i in expect_instances)
        got = sorted(i for r in report["records"] for i in r["instances_matched"])
        if pin is not None:
            want = _pin_expected(pin, pivot, want, report)
        report["instances_expected"] = want
        report["instances_match_expected"] = (got == want)
        if got != want:
            extra = sorted(set(got) - set(want))
            miss = sorted(set(want) - set(got))
            raise GameDataError("the instances matched on pivot %d are not the ones the reference verified: "
                                "%d matched, %d expected; %d unexpected %s, %d missing %s. Another model's baked "
                                "lighting would be rewritten (or this model's placements changed)."
                                % (pivot, len(got), len(want), len(extra), extra[:8], len(miss), miss[:8]))
    if not plans:
        report["changed_bytes"] = 0
        report["S_after"], report["M_after"] = report["S_before"], report["M_before"]
        return bytes(data), report

    # 1) colour-buffer regeneration: re-lay the record out (last record first so earlier offsets stay valid)
    info = bytearray(old_blk.info)
    payloads = list(old_blk.payloads)
    shifts = []                      # (old record start, old record end, growth)
    for rec, patches, regen in sorted(plans, key=lambda t: -t[0].R):
        if not regen:
            continue
        new_rec, new_pay = relayout_record(rec, old_blk.payloads[rec.index], regen)
        growth = len(new_rec) - (rec.end - rec.R)
        info[rec.R:rec.end] = new_rec
        payloads[rec.index] = new_pay
        shifts.append((rec.R, rec.end, growth))
        report["record_growth_bytes"] += growth
        report["payload_growth_bytes"] += len(new_pay) - len(old_blk.payloads[rec.index])
    stage = old_blk
    if shifts:
        stage = game.Block(data, ext)
        stage.info = info
        stage.payloads = payloads
        stage = game.Block(stage.serialize(), ext)
    stage_recs = {r.index: r for r in _parse_block(stage)}

    # 2) key patches on the freshly parsed (possibly re-laid-out) records
    info = bytearray(stage.info)
    touched = []
    for rec, patches, regen in plans:
        nr = stage_recs[rec.index]
        rrep = [x for x in report["records"] if x["index"] == rec.index][0]
        keys, values = list(nr.keys), list(nr.values)
        if keys != [tuple(w) for w in rec.keys] and not regen:
            raise GameDataError("key table changed between parse passes")
        for k, (nv, ni) in patches.items():
            w = keys[k]
            keys[k] = (w[0], w[1], (w[2] & 0xFFF00000) | nv, (w[3] & 0xFFF00000) | ni)
            if patch_entry_copies:
                e = nr.entries[values[k]]
                c = e["key_copy"]
                o = e["offset"] + 8
                info[o + 8:o + 16] = struct.pack("<2I", (c[2] & 0xFFF00000) | nv, (c[3] & 0xFFF00000) | ni)
                touched.append((o + 8, o + 16))
        strict, found = _check_order(keys, values)
        if not (strict and found):
            keys, values = resort_keys(keys, values)
            rrep["resorted"] = True
            strict, found = _check_order(keys, values)
            if not (strict and found):
                raise GameDataError("re-sorted key table still fails the engine binary search")
        rrep["order_strict_after"], rrep["binary_search_finds_every_key_after"] = strict, found
        if rrep["resorted"]:
            lo, hi = nr.keys_off, nr.keys_off + 16 * len(keys)
            info[lo:hi] = b"".join(struct.pack("<4I", *w) for w in keys)
            touched.append((lo, hi))
            if values:
                info[nr.values_off:nr.values_off + 2 * len(values)] = struct.pack("<%dH" % len(values), *values)
                touched.append((nr.values_off, nr.values_off + 2 * len(values)))
        else:
            for k in patches:
                o = nr.keys_off + 16 * k
                info[o + 8:o + 16] = struct.pack("<2I", keys[k][2], keys[k][3])
                touched.append((o + 8, o + 16))
    stage.info = info
    out = stage.serialize()
    report["changed_bytes"] = _verify_retarget(data, out, ext, plans, shifts, stage, touched, patch_entry_copies)
    chk = game.Block(out, ext)
    report["S_after"], report["M_after"] = len(chk.info), chk.max_asset
    report["entry_copies_patched"] = sum(r.get("entry_copies_patched", 0) for r in report["records"])
    report["bytes"] = len(out)
    return out, report


def _verify_retarget(data, out, ext, plans, shifts, stage, touched, patch_entry_copies):
    """Independent re-parse of the result against the input. Raises GameDataError listing what is wrong."""
    old, chk = game.Block(data, ext), game.Block(out, ext)
    problems = []
    if (chk.prefix, chk.timestamp, chk.prop_ck, chk.cmd_ck, len(chk.payloads)) != (old.prefix, old.timestamp, old.prop_ck, old.cmd_ck, len(old.payloads)):
        problems.append("block prefix, timestamp, checksums or resource count changed")
    if chk.max_asset > game.LOAD_BUFFER_CAP and chk.max_asset > old.max_asset:
        problems.append("maximumAssetSize %d over the %d-byte load buffer" % (chk.max_asset, game.LOAD_BUFFER_CAP))
    if [(r["type"], r["name"]) for r in chk.records] != [(r["type"], r["name"]) for r in old.records]:
        problems.append("record list changed")
    planned = {rec.index: (rec, patches, regen) for rec, patches, regen in plans}
    grow = {R: g for R, _, g in shifts}
    shift = 0
    for ro, rn in zip(old.records, chk.records):
        if rn["offset"] != ro["offset"] + shift:
            problems.append("record %d starts at 0x%x, expected 0x%x" % (ro["index"], rn["offset"], ro["offset"] + shift))
            break
        if ro["index"] not in planned:
            if old.info[ro["offset"]:ro["end"]] != chk.info[rn["offset"]:rn["end"]]:
                problems.append("record %d (%s) bytes changed" % (ro["index"], ro["name"]))
            if old.payloads[ro["index"]] != chk.payloads[rn["index"]]:
                problems.append("payload %d changed" % ro["index"])
        shift += grow.get(ro["offset"], 0)
    if len(chk.info) != len(old.info) + shift:
        problems.append("info size %d != %d + growth %d" % (len(chk.info), len(old.info), shift))

    new_recs = {r.index: r for r in _parse_block(chk)}
    old_recs = {r.index: r for r in _parse_block(old)}
    changed = 0
    for idx, (rec, patches, regen) in planned.items():
        o, n = old_recs[idx], new_recs[idx]
        failed = [c for c in _TABLE_CHECKS if not n.checks[c]]
        if patch_entry_copies:
            failed += [] if n.checks["entry_key_copy_matches_key"] else ["entry_key_copy_matches_key"]
        if failed:
            problems.append("record %d fails %s" % (idx, failed))
        if n.uid_keys != o.uid_keys or n.uid_values != o.uid_values or n.paths != o.paths:
            problems.append("record %d: uid tables changed" % idx)
        if len(n.keys) != len(o.keys) or len(n.entries) != len(o.entries):
            problems.append("record %d: key or entry count changed" % idx)
            continue
        if sorted(n.values) != sorted(o.values):
            problems.append("record %d: the multiset of key values changed" % idx)
        if n.header_words[:8] != o.header_words[:8] or n.header_words[9:12] != o.header_words[9:12] or \
                n.header_words[13:16] != o.header_words[13:16] or (n.header_words[17], n.header_words[19]) != (o.header_words[17], o.header_words[19]):
            problems.append("record %d: header fields other than pointers changed" % idx)
        # Key comparison is ORDER-INDEPENDENT: the retarget may re-sort the table (keys and their u16 values move
        # together), so the table is checked as a key -> value mapping, plus the engine's own binary search below.
        want_map, have_map, dup = {}, {}, []
        for k, wo in enumerate(o.keys):
            w = wo if k not in patches else (wo[0], wo[1], (wo[2] & 0xFFF00000) | patches[k][0], (wo[3] & 0xFFF00000) | patches[k][1])
            if w in want_map:
                dup.append("expected key %r occurs twice" % (w,))
            want_map[w] = o.values[k]
        for w, v in zip(n.keys, n.values):
            if w in have_map:
                dup.append("written key %r occurs twice" % (w,))
            have_map[w] = v
        if dup:
            problems.append("record %d: %s" % (idx, dup[0]))
        if have_map != want_map:
            missing = [w for w in want_map if w not in have_map]
            extra = [w for w in have_map if w not in want_map]
            wrong = [w for w in want_map if w in have_map and have_map[w] != want_map[w]]
            problems.append("record %d: key table is not the expected mapping (%d missing, %d unexpected, %d with a "
                            "different value; first: %r)" % (idx, len(missing), len(extra), len(wrong),
                                                             (missing or extra or wrong)[0]))
        else:
            # every expected key must be reachable through the engine's own lower-bound search
            for w, v in want_map.items():
                pos = engine_search(n.keys, w)
                if pos is None or n.values[pos] != v:
                    problems.append("record %d: the engine search does not find key %r (entry %d) after retargeting"
                                    % (idx, w, v))
                    break
        patched_entries = {o.values[k]: patches[k] for k in patches}
        opay, npay = old.payloads[idx], chk.payloads[idx]
        for eo, en in zip(o.entries, n.entries):
            i = eo["index"]
            wc = eo["key_copy"]
            if patch_entry_copies and i in patched_entries:
                nv, ni = patched_entries[i]
                wc = (wc[0], wc[1], (wc[2] & 0xFFF00000) | nv, (wc[3] & 0xFFF00000) | ni)
            if en["key_copy"] != wc or en["colour"] != eo["colour"] or (en["buffer"] is None) != (eo["buffer"] is None):
                problems.append("record %d entry %d changed beyond its key copy counts" % (idx, i))
                break
            if eo["buffer"] is None:
                continue
            bo, bn = eo["buffer"], en["buffer"]
            ocp = bytes(old.info[bo["index_copy_offset"]:bo["index_copy_offset"] + 2 * bo["index_copy_count"]])
            ncp = bytes(chk.info[bn["index_copy_offset"]:bn["index_copy_offset"] + 2 * bn["index_copy_count"]])
            ocol = opay[bo["data_offset"]:bo["data_offset"] + bo["data_size"]]
            ncol = npay[bn["data_offset"]:bn["data_offset"] + bn["data_size"]]
            ohdr = bytes(old.info[bo["offset"]:bo["offset"] + COLOUR_BUFFER])
            nhdr = bytes(chk.info[bn["offset"]:bn["offset"] + COLOUR_BUFFER])
            if i in regen:
                cols, idxs = regen[i]
                exp_col = struct.pack("<%dI" % len(cols), *cols) if cols else b""
                if bn["count"] != len(cols) or bn["index_count"] != len(idxs) or ncp != (struct.pack("<%dH" % len(idxs), *idxs) if idxs else b"") \
                        or ncol[:len(exp_col)] != exp_col or (bn["bits"] & 0xF8000007) != (bo["bits"] & 0xF8000007) \
                        or nhdr[:4] != ohdr[:4] or nhdr[8:16] != ohdr[8:16] or nhdr[0x24:] != ohdr[0x24:]:
                    problems.append("record %d entry %d: regenerated colour buffer does not read back" % (idx, i))
                    break
            elif (bn["count"], bn["bits"], bn["index_count"], ncp, ncol) != (bo["count"], bo["bits"], bo["index_count"], ocp, ocol) \
                    or nhdr[:4] != ohdr[:4] or nhdr[8:0x18] != ohdr[8:0x18] or nhdr[0x1C:] != ohdr[0x1C:]:
                problems.append("record %d entry %d: untouched colour buffer changed" % (idx, i))
                break
        for k, (nv, ni) in patches.items():
            w = o.keys[k]
            inst, piv, mesh, single = w[1] & 0xFFFF, (w[0] >> 16) & 0xFFFF, w[0] & 0xFFFF, bool(w[1] & SINGLE_BIT)
            hit = engine_search(n.keys, build_key(inst, piv, mesh, nv, ni, single))
            if hit is None or n.values[hit] != o.values[k]:
                problems.append("record %d: instance %d mesh %d new counts miss entry %d" % (idx, inst, mesh, o.values[k]))
                break
            e = n.entries[o.values[k]]
            if e["buffer"] is not None and e["buffer"]["count"] != nv:
                problems.append("record %d: entry %d colour count %d != new vcount %d" % (idx, e["index"], e["buffer"]["count"], nv))
            if (w[2] & COUNT_MASK, w[3] & COUNT_MASK) != (nv, ni) and engine_search(n.keys, build_key(inst, piv, mesh, w[2], w[3], single)) is not None:
                problems.append("record %d: instance %d mesh %d old counts still hit" % (idx, inst, mesh))
                break
    if not shifts:
        # in place: every changed byte must lie inside a patched range
        prev = 0
        for lo, hi in sorted(touched):
            if old.info[prev:lo] != chk.info[prev:lo]:
                problems.append("info bytes changed outside the patched count fields (0x%x..0x%x)" % (prev, lo))
                break
            changed += sum(1 for a, b in zip(old.info[lo:hi], chk.info[lo:hi]) if a != b)
            prev = max(prev, hi)
        if old.info[prev:] != chk.info[prev:] or old.payloads != chk.payloads or len(old.info) != len(chk.info):
            problems.append("bytes changed after the last patched count field, or payloads/S changed")
    else:
        changed = None
    if problems:
        raise GameDataError("retarget verification failed: " + "; ".join(problems[:6]))
    return changed
