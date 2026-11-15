"""Writer round trip: for every MODEL record of every block, describe it semantically (model_writer.spec_from_model),
rebuild it from that description with every computed field DERIVED (bounds rules), and compare with the shipped bytes.

Two comparisons per model:
  exact      the rebuilt record, with the exporter's uninitialised pad bytes copied over, equals the shipped record
  zero-pad   the rebuilt record with zero pads equals the shipped record re-encoded with zero pads
A mismatch is reported with the first differing offset and the allocation it falls in.
"""
import argparse, collections, json, os, sys, copy
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todmodel as tm
import model_writer as mw
from model_roundtrip_strict import strip, coll_strip


def where_in(layout, off):
    for o, n, what in layout:
        if o <= off < ((o + n + 3) & ~3):
            return '%s+0x%x' % (what, off - o)
    return 'gap'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--naz', default=r'C:\GOG Games\Total Overdose\blocks.naz')
    ap.add_argument('--out')
    a = ap.parse_args()
    arch = tb.Archive(a.naz)
    C = collections.Counter(); fails = collections.Counter(); ex = {}
    for name in sorted(n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS):
        try:
            b = tb.Block(arch.read(name), os.path.splitext(name)[1]); info = bytes(b.info)
            st = tb.record_starts(info, b.n)
        except Exception:
            continue
        en = st[1:] + [len(info)]
        for k, R in enumerate(st):
            if tb.u32(info, R) != 3:
                continue
            orig = info[R:en[k]]
            m = tm.decode(info, R, en[k])
            skinned = any(S['mb'] and S['mb']['kind'] == 'skin' for P in m['pivots'] for S in P['smbs'])
            cls = 'skinned' if skinned else 'rigid'
            C['models_' + cls] += 1
            spec = mw.spec_from_model(m)
            for P in spec['pivots']:                     # skinned meshes: rebuild the 96-byte stream from joints/weights
                for me in P['meshes']:
                    if me['kind'] == 'skin':
                        j, w = mw.skin_from_records(me['extra']['skin'], me['extra']['infl'])
                        me['extra']['skin'], me['extra']['infl'] = mw.skin_records(me['vertex_bytes'], j, w)
            if skinned:
                spec['sphere'] = spec['sphere_stored']      # the sphere rule is measured on rigid models only
            tree = mw.build_tree(spec, derive=True)
            t2 = copy.deepcopy(tree)
            mw.transplant_pads(tree, m)
            enc = tm.encode(tree)
            if enc == orig:
                C['exact_' + cls] += 1
            else:
                import struct as _s
                got = _s.unpack_from('<4f', enc, 0x44); want = _s.unpack_from('<4f', orig, 0x44)
                dmax = max(abs(x - y) for x, y in zip(got, want))
                C['sphere_only_mismatch'] += enc[:0x44] + enc[0x54:] == orig[:0x44] + orig[0x54:]
                if dmax > C.get('sphere_maxdiff_e9', 0) / 1e9:
                    C['sphere_maxdiff_e9'] = int(dmax * 1e9)
                spec2 = dict(spec, sphere=spec['sphere_stored'])
                t3 = mw.build_tree(spec2, derive=True)
                mw.transplant_pads(t3, m)
                C['exact_with_stored_sphere_' + cls] += tm.encode(t3) == orig
                d = next((q for q in range(min(len(enc), len(orig))) if enc[q] != orig[q]), None)
                w = where_in(m['layout'], d) if d is not None else 'length %d vs %d' % (len(enc), len(orig))
                key = (cls, w.split('+')[0] + '+' + w.split('+')[1] if '+' in w else w)
                fails[key] += 1
                ex.setdefault(key, [name.split('/')[-1], k, tb.record_name(info, R), w])
            # zero-pad comparison
            s = strip(t2)
            for P in s['pivots']:
                coll_strip(P['coll'])
            coll_strip(s['hulls'])
            so = strip(m)
            for P in so['pivots']:
                coll_strip(P['coll'])
            coll_strip(so['hulls'])
            if tm.encode(s) == tm.encode(so):
                C['zeropad_equal_' + cls] += 1
    rep = dict(counts=dict(C), mismatches={'%s %s' % kk: v for kk, v in fails.items()},
               examples={'%s %s' % kk: v for kk, v in ex.items()})
    print(json.dumps(rep, indent=1))
    if a.out:
        json.dump(rep, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
