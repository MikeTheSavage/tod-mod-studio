"""Round-trip proof over every FRAGMENT asset of every block in the GOG blocks.naz (read only).

Per fragment:
  A  exact parse (every value sized by its property type; no heuristics) and serialize == shipped payload
  B  rechunk with the editor rule (10240-byte chunks, whole records) == shipped payload
  C  every set-property value re-encoded from its decoded value == shipped bytes (string padding masked: the
     original writer leaves stale bytes after a string's NUL, which the engine never reads)
Per block:
  D  block rebuilt from the re-serialized fragment payloads == shipped block bytes (sha256)
Plus statistics (record counts per op, property types used, struct-typed values, nodeId block bits).
"""
import sys, os, json, struct, hashlib, collections, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todfrag as tf

NAZ = r"C:\GOG Games\Total Overdose\blocks.naz"


def main(out_json):
    T = tf.Types()
    a = tb.Archive(NAZ)
    rep = dict(blocks=0, fragments=0, records=0, A_fail=[], B_fail=[], C_fail=[], D_fail=[], empty=0)
    ops = collections.Counter(); types_used = collections.Counter(); struct_vals = collections.Counter()
    blockbits = collections.Counter(); hibytes = collections.Counter(); max_rec = 0
    per_block = {}
    t0 = time.time()
    for name in sorted(a.names):
        ext = os.path.splitext(name)[1].lower()
        if ext not in tb.BLOCK_EXTS:
            continue
        raw = a.read(name)
        b = tb.Block(raw, ext)
        info = bytes(b.info)
        starts = tb.record_starts(info, b.n)
        nb = tb.Block(raw, ext)
        nfr = 0
        bits_here = collections.Counter()
        for k, R in enumerate(starts):
            if tb.u32(info, R) != 4:
                continue
            nfr += 1
            rep['fragments'] += 1
            nm = tb.record_name(info, R)
            p = b.payloads[k]
            try:
                fr = tf.Fragment(p, T)
            except Exception as e:
                rep['A_fail'].append([name, nm, 'parse: %s' % e]); continue
            s = fr.serialize()
            if s != p:
                rep['A_fail'].append([name, nm, 'serialize differs']); continue
            if not fr.chunks:
                rep['empty'] += 1
            recs = fr.records
            fr2 = tf.Fragment(p, T); fr2.rechunk()
            if fr2.serialize() != p:
                rep['B_fail'].append([name, nm, [len(c) for c in fr.chunks], [len(c) for c in fr2.chunks]])
            for r in recs:
                rep['records'] += 1
                ops[r.op] += 1
                max_rec = max(max_rec, r.size())
                bits_here[tf.node_block(r.node)] += 1
                if r.op != tf.SET:
                    if r.op == tf.CREATE:
                        v = tf.decode_value(r.raw, 0, ('string',))
                        if tf.mask_string_padding(r.raw, 0, ('string',)) != tf.encode_string(v):
                            rep['C_fail'].append([name, nm, 'create name']);
                    continue
                hibytes[r.hi] += 1
                ty = T.ptype(r.prop)
                types_used[ty] += 1
                t = T.parse(ty)
                if 'struct' in repr(t):
                    struct_vals[(T.name(r.prop), ty)] += 1
                v = tf.decode_value(r.raw, 0, t)
                enc = tf.encode_value(v, t)
                if enc != tf.mask_string_padding(r.raw, 0, t):
                    if len(rep['C_fail']) < 50:
                        rep['C_fail'].append([name, nm, T.name(r.prop), ty, r.raw.hex()[:80], enc.hex()[:80]])
            nb.payloads[k] = s
        blockbits.update(bits_here)
        per_block[name] = dict(fragments=nfr, nodeid_block_bits=dict(bits_here))
        rb = nb.serialize()
        if rb != raw:
            rep['D_fail'].append(name)
        rep['blocks'] += 1
    rep['ops'] = dict(ops); rep['types_used'] = dict(types_used.most_common())
    rep['struct_values'] = {'%s:%s' % k: v for k, v in struct_vals.items()}
    rep['nodeid_block_bits'] = dict(blockbits); rep['set_record_high_byte'] = dict(hibytes)
    rep['max_record_bytes'] = max_rec
    rep['per_block'] = per_block
    rep['seconds'] = round(time.time() - t0, 1)
    json.dump(rep, open(out_json, 'w'), indent=1)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in rep.items() if k != 'per_block'}, indent=1)[:4000])


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'roundtrip_all.json'))
