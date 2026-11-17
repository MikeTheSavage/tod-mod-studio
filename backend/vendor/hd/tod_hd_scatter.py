"""SurroundGeometry scatter systems (runtime grass/trash/bush instancing) in TOD asset blocks: read their
properties out of the level FRAGMENT payloads and patch the fixed-size ones in place.

Why this exists: the jungle's ground cover is not placed geometry. Two SurroundGeometry entities in
SUBMAP01_Map09_Geometry.fragment ("Cat_01_Grass" and "Cat_02_Dirt") spawn SUR__* models around the player every
frame. Their MaxCount / FarDistance / CloseDistance / Variation / per-model probabilities decide how dense the
undergrowth looks, and they are ordinary entity properties inside the fragment payload, so they can be rewritten
without touching the info buffer, the record table or any size.

Where the values live
  * A FRAGMENT is asset record type 4; its serialized entity graph is the record's PAYLOAD (not the info buffer).
  * The payload is a chain of blocks: [u32 next(self-relative)] [u32 record-stream length] [u32 first record
    (self-relative)] then the record stream. A record is [u32 nodeId] [u32 packed]; packed >> 24 is 0xFF for
    "create node" (payload [u32 wordcount][asciiz padded]), 0xFE for "delete node", anything else for
    "set property", where packed & 0xFFFFFF is the GLOBAL property index and the payload is the value.
    (Format from the TOD Project's tools/tod_fragment_decode.py + docs/subsystem_level_layout.md; this
    module re-implements the walk so it can report the byte offset and word count of every value.)
  * Builtin property values carry no type tag on disk, so a value's length is delimited by scanning forward to
    the next plausible record start (a known nodeId followed by a create/delete marker or a small property index),
    exactly like the reference decoder. Every value this module patches keeps its byte length, so the delimiting
    never changes - and patch_scatter re-decodes the result and refuses if anything but the intended values moved.
  * The engine registers SurroundGeometry's properties in this order (TOD1/SurroundGeometry.cpp Register, binary
    0x8FC070): Category, FarDistance, CloseDistance, MaxCount, Variation, Model1, Properbility1, Model2,
    Properbility2, Model3, Properbility3, Model4, Properbility4, RandomSeed. In every shipped block those are the
    global indices 380..393 (checked on all 22 systems in the game); the module still validates the shape of each
    value it touches and refuses a system whose properties do not typecheck.

What the values do (GOG TOD.exe)
  * Instantiate FUN_008F9380: OverallProbability = sum of the probabilities of the model slots that actually
    loaded; DistanceKoefficient = CloseDistance/FarDistance; the working radius starts at FarDistance. It also
    builds 20 random orientation matrices (class field at +0x84, 20 x 64 B) - the only fixed-size array, and it
    does NOT depend on MaxCount.
  * Render FUN_008FB640: instances are taken from the surrounding terrain samples whose category byte matches,
    each drawn model within the working radius, fading between FarDistanceKoefficient and the working radius.
    At the end of the frame the working radius is scaled down when the drawn count exceeds MaxCount and grown
    again (clamped to FarDistance) when it falls below a fraction of it. MaxCount is therefore a density target
    with a feedback loop, not the size of a buffer: raising it costs draw calls, not memory. Largest value
    shipped: 500 (map07 Cat_03), editor slider max: 200.

API
  list_scatter_systems(data, ext)          -> [system dict] (values + payload offsets + warnings)
  patch_scatter(data, ext, name, values)   -> (new block bytes, report), same-length value patches only,
                                              verified by an independent re-parse and re-decode
  SCATTER_PROPERTIES                       the property table (name -> index, type, range)
"""
import struct

import tod_hd_game as game
from tod_hd_game import GameDataError

__all__ = ["list_scatter_systems", "patch_scatter", "SCATTER_PROPERTIES", "FRAGMENT_TYPE"]

FRAGMENT_TYPE = 4
ENTITY_TYPE = "SurroundGeometry"
NAME_PROPERTY = 15                     # builtin "name" (anchor-validated in tod_fragment_decode)
PROP_INDEX_CEILING = 6100              # the reference decoder's plausibility ceiling for a property index
MAX_MODEL_SLOTS = 4

# name -> (global property index, type, minimum, maximum, editor maximum or None)
SCATTER_PROPERTIES = {
    "Category":       (380, "integer", 0, 13, 13),
    "FarDistance":    (381, "number", 0.0, 1000.0, 30.0),
    "CloseDistance":  (382, "number", 0.0, 1000.0, 30.0),
    "MaxCount":       (383, "integer", 1, 10000, 200),
    "Variation":      (384, "number", 0.0, 1.0, 1.0),
    "Model1":         (385, "string", None, None, None),
    "Properbility1":  (386, "number", 0.0, 1.0, 1.0),
    "Model2":         (387, "string", None, None, None),
    "Properbility2":  (388, "number", 0.0, 1.0, 1.0),
    "Model3":         (389, "string", None, None, None),
    "Properbility3":  (390, "number", 0.0, 1.0, 1.0),
    "Model4":         (391, "string", None, None, None),
    "Properbility4":  (392, "number", 0.0, 1.0, 1.0),
    "RandomSeed":     (393, "number", -1.0, 2147483647.0, None),
}
_BY_INDEX = {v[0]: k for k, v in SCATTER_PROPERTIES.items()}
LARGEST_SHIPPED_MAXCOUNT = 500


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def _cstr(b, o, limit):
    e = b.find(b"\0", o, o + limit)
    if e < 0:
        e = o + limit
    return bytes(b[o:e]).decode("latin-1")


# ------------------------------------------------------------------------------------------------ fragment walk

def _iter_blocks(blob):
    """(first_record_offset, record_stream_end) for every block of the payload chain."""
    size = len(blob)
    if size < 4:
        return
    block = (_u32(blob, 0) + 0) & 0xFFFFFFFF
    seen = set()
    while 0 < block and block + 12 <= size and block not in seen:
        seen.add(block)
        nxt_stored = _u32(blob, block)
        nxt = (nxt_stored + block) & 0xFFFFFFFF
        rec_len = _u32(blob, block + 4)
        first = (_u32(blob, block + 8) + block + 8) & 0xFFFFFFFF
        end = min(first + rec_len, size)
        if first < end:
            yield first, end
        if nxt_stored in (0, 0x80000000) or nxt <= block or nxt + 12 > size:
            break
        block = nxt


def _created_ids(blob):
    ids = set()
    for first, end in _iter_blocks(blob):
        pos = first
        while pos + 8 <= end:
            nid = _u32(blob, pos)
            hi = _u32(blob, pos + 4) >> 24
            if hi == 0xFF:
                ids.add(nid)
                pos += 12 + _u32(blob, pos + 8) * 4
            elif hi == 0xFE:
                pos += 8
            else:
                break
    return ids


def _is_record_start(blob, pos, end, ids):
    if pos + 8 > end:
        return False
    if _u32(blob, pos) not in ids:
        return False
    hi = _u32(blob, pos + 4) >> 24
    if hi in (0xFE, 0xFF):
        return True
    return (_u32(blob, pos + 4) & 0xFFFFFF) < PROP_INDEX_CEILING


def walk_fragment(blob):
    """Every record of a fragment payload with its byte offsets.
    -> (ops, stats); op = {"op": "create"/"delete"/"setprop", "node", "offset" (record start), "value_offset",
    "words", "prop", "type_name"}."""
    ids = _created_ids(blob)
    ops = []
    stats = {"create": 0, "delete": 0, "setprop": 0, "blocks": 0, "resyncs": 0, "skipped_words": 0}
    for first, end in _iter_blocks(blob):
        stats["blocks"] += 1
        pos = first
        while pos + 8 <= end:
            if not _is_record_start(blob, pos, end, ids):
                scan = pos + 4
                while scan + 8 <= end and not _is_record_start(blob, scan, end, ids):
                    scan += 4
                stats["resyncs"] += 1
                stats["skipped_words"] += (scan - pos) // 4
                pos = scan
                continue
            nid, packed = _u32(blob, pos), _u32(blob, pos + 4)
            hi, start = packed >> 24, pos
            pos += 8
            if hi == 0xFF:
                wc = _u32(blob, pos)
                ops.append({"op": "create", "node": nid, "offset": start, "value_offset": pos + 4, "words": wc,
                            "type_name": _cstr(blob, pos + 4, wc * 4)})
                pos += 4 + wc * 4
                stats["create"] += 1
            elif hi == 0xFE:
                ops.append({"op": "delete", "node": nid, "offset": start, "value_offset": pos, "words": 0})
                stats["delete"] += 1
            else:
                vstart = pos
                while pos + 4 <= end and not _is_record_start(blob, pos, end, ids):
                    pos += 4
                ops.append({"op": "setprop", "node": nid, "prop": packed & 0xFFFFFF, "offset": start,
                            "value_offset": vstart, "words": (pos - vstart) // 4})
                stats["setprop"] += 1
    return ops, stats


def _shape(ops):
    """The structure of an op stream, independent of the values it carries."""
    return [(o["op"], o["node"], o.get("prop"), o["offset"], o["value_offset"], o["words"]) for o in ops]


def _decode_value(blob, o, typ):
    off, words = o["value_offset"], o["words"]
    if typ == "integer":
        return _u32(blob, off) if words == 1 else None
    if typ == "number":
        return _f32(blob, off) if words == 1 else None
    if typ == "string":
        if words < 1:
            return None
        n = _u32(blob, off)
        if n + 1 != words or n * 4 + off + 4 > len(blob):
            return None
        return _cstr(blob, off + 4, n * 4)
    return None


# ------------------------------------------------------------------------------------------------ reading

def _systems_in_payload(blob, rec):
    ops, stats = walk_fragment(blob)
    created = {}
    for o in ops:
        if o["op"] == "create":
            created[o["node"]] = o["type_name"]
    nodes = [n for n, t in created.items() if t == ENTITY_TYPE]
    out = []
    for node in nodes:
        props, warn = {}, []
        name = None
        for o in ops:
            if o["op"] != "setprop" or o["node"] != node:
                continue
            if o["prop"] == NAME_PROPERTY:
                name = _decode_value(blob, o, "string")
            pname = _BY_INDEX.get(o["prop"])
            if pname is None:
                continue
            typ = SCATTER_PROPERTIES[pname][1]
            val = _decode_value(blob, o, typ)
            if val is None:
                warn.append("property %s (index %d) does not decode as %s (%d words at payload 0x%x)"
                            % (pname, o["prop"], typ, o["words"], o["value_offset"]))
                continue
            if typ == "string" and not val.startswith("/"):
                warn.append("property %s does not look like a model path: %r" % (pname, val))
            props[pname] = {"index": o["prop"], "type": typ, "value": val, "payload_offset": o["value_offset"],
                            "words": o["words"], "record_offset": o["offset"],
                            "capacity": (o["words"] - 1) * 4 - 1 if typ == "string" else None}
        models = []
        for k in range(1, MAX_MODEL_SLOTS + 1):
            m, p = props.get("Model%d" % k), props.get("Properbility%d" % k)
            if m is None and p is None:
                continue
            models.append({"slot": k, "model": m["value"] if m else None,
                           "probability": p["value"] if p else None,
                           "model_capacity": m["capacity"] if m else None})
        total = sum(m["probability"] or 0.0 for m in models if m["model"])
        out.append({"record_index": rec["index"], "fragment": rec["name"], "node_id": node, "name": name,
                    "properties": props, "models": models, "probability_sum": total,
                    "payload_bytes": len(blob), "fragment_stats": stats, "warnings": warn})
    return out


def list_scatter_systems(data, ext):
    """Every SurroundGeometry entity in every FRAGMENT record of the block, with the decoded property values and
    the payload byte offset of each value. Values are exactly what the engine reads; offsets are only valid for
    these bytes."""
    blk = game.Block(data, ext)
    out = []
    for rec in blk.records:
        if rec["type"] != FRAGMENT_TYPE:
            continue
        out.extend(_systems_in_payload(bytes(blk.payloads[rec["index"]]), rec))
    return out


# ------------------------------------------------------------------------------------------------ patching

def _resolve(systems, name):
    if isinstance(name, int) and not isinstance(name, bool):
        hits = [s for s in systems if s["node_id"] == name]
        if not hits:
            raise GameDataError("no scatter system with node id 0x%x in this block" % name)
        return hits[0]
    key = str(name).strip().lower()
    hits = [s for s in systems if (s["name"] or "").lower() == key]
    if not hits:
        hits = [s for s in systems if ("%s:%s" % (s["fragment"], s["name"])).lower().endswith(key)]
    if not hits:
        raise GameDataError("no scatter system called %r in this block (have: %s)"
                            % (name, ", ".join(repr(s["name"]) for s in systems) or "none"))
    if len(hits) > 1:
        raise GameDataError("scatter system %r is ambiguous (%d systems share the name)" % (name, len(hits)))
    return hits[0]


def _encode(pname, prop, value):
    """-> (bytes of exactly prop['words']*4, normalized value, warnings)"""
    idx, typ, lo, hi, editor = SCATTER_PROPERTIES[pname]
    warn = []
    if typ == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise GameDataError("%s must be an integer, got %r" % (pname, value))
        if not lo <= value <= hi:
            raise GameDataError("%s = %d is outside the supported range %d..%d" % (pname, value, lo, hi))
        if editor is not None and value > editor:
            warn.append("%s = %d is above the editor maximum %d (largest value shipped: %d)"
                        % (pname, value, editor, LARGEST_SHIPPED_MAXCOUNT if pname == "MaxCount" else editor))
        return struct.pack("<I", value & 0xFFFFFFFF), value, warn
    if typ == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GameDataError("%s must be a number, got %r" % (pname, value))
        value = float(value)
        if not lo <= value <= hi:
            raise GameDataError("%s = %r is outside the supported range %r..%r" % (pname, value, lo, hi))
        if editor is not None and value > editor:
            warn.append("%s = %r is above the editor maximum %r" % (pname, value, editor))
        b = struct.pack("<f", value)
        return b, struct.unpack("<f", b)[0], warn
    # string: keep the stored word count, so the record length never changes
    if not isinstance(value, str):
        raise GameDataError("%s must be a string, got %r" % (pname, value))
    cap = (prop["words"] - 1) * 4
    raw = value.encode("latin-1")
    if len(raw) + 1 > cap:
        raise GameDataError("%s: %r needs %d bytes but the stored slot holds %d (a longer string would change the "
                            "record length, which this module never does)" % (pname, value, len(raw) + 1, cap))
    if not value.startswith("/"):
        warn.append("%s = %r does not start with '/' (model paths in fragments do)" % (pname, value))
    return struct.pack("<I", prop["words"] - 1) + raw + b"\0" * (cap - len(raw)), value, warn


def patch_scatter(data, ext, name, values, allow_unshipped=True):
    """Change SurroundGeometry properties in place. `name` is the system's name property (e.g. "Cat_01_Grass"),
    "<fragment>:<name>", or its node id. `values` is {property name: value}; only properties the entity already
    stores can be changed, and every patch keeps the value's byte length (no record, payload, size table, info
    buffer or header field ever moves). Returns (new block bytes, report) or raises GameDataError.

    Unpatchable by design: adding a property the entity does not carry (e.g. a Model3 slot that was never set),
    or a model path longer than the stored slot. Both would change the record stream length, and the fragment's
    block header carries that length, so every following record would have to move.
    """
    if not isinstance(values, dict) or not values:
        raise GameDataError("no property values given")
    unknown = sorted(set(values) - set(SCATTER_PROPERTIES))
    if unknown:
        raise GameDataError("unknown scatter properties %s (known: %s)" % (unknown, sorted(SCATTER_PROPERTIES)))
    blk = game.Block(data, ext)
    systems = list_scatter_systems(data, ext)
    sysd = _resolve(systems, name)
    if sysd["warnings"] and not allow_unshipped:
        raise GameDataError("scatter system %r does not decode cleanly: %s" % (name, sysd["warnings"][0]))

    payload = bytearray(blk.payloads[sysd["record_index"]])
    patches, applied, warnings = [], {}, list(sysd["warnings"])
    for pname, value in sorted(values.items()):
        prop = sysd["properties"].get(pname)
        if prop is None:
            raise GameDataError("%s does not store the property %s; adding one would change the fragment record "
                                "length, which cannot be patched in place"
                                % (sysd["name"] or hex(sysd["node_id"]), pname))
        blob, norm, warn = _encode(pname, prop, value)
        if len(blob) != prop["words"] * 4:
            raise GameDataError("internal: %s encodes to %d bytes, the slot is %d" % (pname, len(blob), prop["words"] * 4))
        off = prop["payload_offset"]
        old = bytes(payload[off:off + len(blob)])
        payload[off:off + len(blob)] = blob
        patches.append((off, len(blob)))
        applied[pname] = {"old": prop["value"], "new": norm, "payload_offset": off, "bytes": len(blob),
                          "changed_bytes": sum(1 for a, b in zip(old, blob) if a != b)}
        warnings += warn
    far = applied.get("FarDistance", {}).get("new", sysd["properties"].get("FarDistance", {}).get("value"))
    close = applied.get("CloseDistance", {}).get("new", sysd["properties"].get("CloseDistance", {}).get("value"))
    if far is not None and close is not None and close > far:
        warnings.append("CloseDistance %r is larger than FarDistance %r (the engine's koefficient becomes > 1)" % (close, far))

    blk.payloads[sysd["record_index"]] = bytes(payload)
    out = blk.serialize()
    report = {"block_ext": ext, "system": sysd["name"], "node_id": sysd["node_id"], "fragment": sysd["fragment"],
              "record_index": sysd["record_index"], "applied": applied, "warnings": warnings,
              "bytes": [len(data), len(out)]}
    report["verification"] = _verify_patch(data, out, ext, sysd, applied, patches)
    return out, report


def _verify_patch(data, out, ext, sysd, applied, patches):
    """Independent re-parse and re-decode: only the patched value bytes may differ, the fragment must decode to
    exactly the same record structure, and every value must read back (the new ones as requested)."""
    old, new = game.Block(data, ext), game.Block(out, ext)
    problems = []
    if (old.prefix, old.timestamp, old.prop_ck, old.cmd_ck, old.max_asset) != \
            (new.prefix, new.timestamp, new.prop_ck, new.cmd_ck, new.max_asset):
        problems.append("block header changed")
    if bytes(old.info) != bytes(new.info):
        problems.append("info buffer changed")
    if old.sizes != new.sizes or len(old.payloads) != len(new.payloads):
        problems.append("payload sizes changed")
    if [(r["type"], r["name"], r["offset"]) for r in old.records] != [(r["type"], r["name"], r["offset"]) for r in new.records]:
        problems.append("record list changed")
    for i, (a, b) in enumerate(zip(old.payloads, new.payloads)):
        if i != sysd["record_index"] and a != b:
            problems.append("payload %d changed" % i)
    op, np_ = bytes(old.payloads[sysd["record_index"]]), bytes(new.payloads[sysd["record_index"]])
    allowed = sorted(patches)
    prev, changed = 0, 0
    for off, ln in allowed:
        if op[prev:off] != np_[prev:off]:
            problems.append("fragment payload changed outside the patched values (0x%x..0x%x)" % (prev, off))
            break
        changed += sum(1 for a, b in zip(op[off:off + ln], np_[off:off + ln]) if a != b)
        prev = max(prev, off + ln)
    if op[prev:] != np_[prev:]:
        problems.append("fragment payload changed after the last patched value")
    old_ops, old_stats = walk_fragment(op)
    new_ops, new_stats = walk_fragment(np_)
    if _shape(old_ops) != _shape(new_ops) or old_stats != new_stats:
        problems.append("the fragment no longer decodes to the same record structure (%s vs %s)" % (old_stats, new_stats))
    else:
        for o, n in zip(old_ops, new_ops):
            if o["op"] == "create" and o["type_name"] != n["type_name"]:
                problems.append("entity type name changed at payload 0x%x" % o["offset"])
                break
        after = [s for s in _systems_in_payload(np_, {"index": sysd["record_index"], "name": sysd["fragment"]})
                 if s["node_id"] == sysd["node_id"]]
        if len(after) != 1:
            problems.append("the patched system is no longer found in the fragment")
        else:
            a = after[0]
            for pname, prop in sysd["properties"].items():
                want = applied[pname]["new"] if pname in applied else prop["value"]
                got = a["properties"].get(pname, {}).get("value")
                if isinstance(want, float):
                    same = isinstance(got, float) and struct.pack("<f", want) == struct.pack("<f", got)
                else:
                    same = got == want
                if not same:
                    problems.append("property %s reads back as %r, expected %r" % (pname, got, want))
                    break
            if a["properties"].keys() != sysd["properties"].keys():
                problems.append("the property set of the system changed")
    if problems:
        raise GameDataError("patch_scatter verification failed: " + "; ".join(problems[:5]))
    return {"changed_bytes": changed, "patched_ranges": len(allowed), "other_payloads_identical": True,
            "info_identical": True, "fragment_records": len(new_ops), "fragment_stats": new_stats}


# ------------------------------------------------------------------------------------------------ density knob

def density_patches(data, ext, factor=1.0, systems=None, far_distance=None, max_count_cap=LARGEST_SHIPPED_MAXCOUNT):
    """Build the patch dict for "more runtime scatter": MaxCount * factor for the named systems (all of them by
    default), clamped to max_count_cap (500 = the largest MaxCount the shipped game uses anywhere, so the engine
    is never asked for more instances than it already handles somewhere), and optionally a new FarDistance so the
    extra grass is actually drawn further out.
    -> {system name: {"MaxCount": int, ...}} ready for tod_hd_vegetation.apply_scatter_patches. Reads only."""
    have = list_scatter_systems(data, ext)
    want = [s for s in have if systems is None or (s["name"] or "").lower() in {str(x).lower() for x in systems}]
    if systems is not None and len(want) != len(set(str(x).lower() for x in systems)):
        raise GameDataError("scatter systems not in this block: %s"
                            % sorted({str(x).lower() for x in systems} - {(s["name"] or "").lower() for s in want}))
    out = {}
    for s in want:
        cur = s["properties"].get("MaxCount", {}).get("value")
        if cur is None:
            continue
        new = max(1, min(int(max_count_cap), int(round(cur * float(factor)))))
        patch = {}
        if new != cur:
            patch["MaxCount"] = new
        if far_distance is not None:
            fd = s["properties"].get("FarDistance", {}).get("value")
            if fd is not None and float(far_distance) != fd:
                patch["FarDistance"] = float(far_distance)
        if patch:
            out[s["name"]] = patch
    return out
