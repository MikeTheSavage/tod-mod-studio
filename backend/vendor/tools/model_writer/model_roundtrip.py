"""Round trip every MODEL record of every block in blocks.naz through todmodel.decode/encode (read-only on the archive).

  python model_roundtrip.py [--naz PATH] [--limit N] [--out report.json]
"""
import argparse, collections, hashlib, json, os, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todmodel as tm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--naz', default=r'C:\GOG Games\Total Overdose\blocks.naz')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    t0 = time.time()
    arch = tb.Archive(a.naz)
    C = collections.Counter(); fails = []; H = hashlib.sha256()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS)
    if a.limit:
        names = names[:a.limit]
    for name in names:
        try:
            b = tb.Block(arch.read(name), os.path.splitext(name)[1]); info = bytes(b.info)
            st = tb.record_starts(info, b.n)
        except Exception:
            C['block_unreadable'] += 1
            continue
        C['blocks'] += 1
        en = st[1:] + [len(info)]
        for k, R in enumerate(st):
            if tb.u32(info, R) != 3:
                continue
            C['models'] += 1
            try:
                m = tm.decode(info, R, en[k])
                enc = tm.encode(m)
                ok = enc == info[R:en[k]]
            except Exception as e:
                ok = False; enc = None; err = repr(e)
            if ok:
                C['identical'] += 1
                C['bytes'] += en[k] - R
                H.update(enc)
                C['pivots'] += len(m['pivots'])
                C['smbs'] += sum(len(P['smbs']) for P in m['pivots'])
                C['pivot_colllists'] += sum(1 for P in m['pivots'] if P['coll'] is not None)
                C['hulllists'] += m['hulls'] is not None
                for P in m['pivots']:
                    for S in P['smbs']:
                        if S['mb'] is not None:
                            C['mb_' + S['mb']['kind']] += 1
            else:
                C['FAIL'] += 1
                if len(fails) < 30:
                    if enc is not None:
                        orig = info[R:en[k]]
                        d = next((q for q in range(min(len(enc), len(orig))) if enc[q] != orig[q]), None)
                        fails.append([name.split('/')[-1], k, tb.record_name(info, R), 'len', len(enc), len(orig),
                                      'firstdiff', hex(d) if d is not None else None])
                    else:
                        fails.append([name.split('/')[-1], k, tb.record_name(info, R), err])
    rep = dict(counts=dict(C), sha256_all_model_records=H.hexdigest(), fails=fails, seconds=round(time.time() - t0, 1))
    print(json.dumps(rep, indent=1))
    if a.out:
        json.dump(rep, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
