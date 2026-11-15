"""Round trip: decode every collision region of every block in blocks.naz and re-encode it; compare bytes.
Read-only on the archive. Writes ../out/roundtrip.json."""
import sys, os, collections, hashlib, json
sys.path.insert(0, os.path.dirname(__file__))
import todblock as tb, todcoll as tc

NAZ = os.environ.get("TOD_NAZ", r"C:\GOG Games\Total Overdose\blocks.naz")


def regions_of_model(info, R):
    regs = []
    pp = tc.deref(info, R + 0x30)
    for i in range(tc.i32(info, R + 0x34)):
        c = tc.deref(info, pp + i * 0x7C + 0x44)
        if c is not None:
            regs.append(('piv', c, i))
    f = tc.deref(info, R + 0x54)
    if f is not None:
        regs.append(('f54', f, -1))
    return regs


def main():
    arch = tb.Archive(NAZ)
    C = collections.Counter(); fails = []
    H = hashlib.sha256()
    for name in sorted(n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS):
        try:
            b = tb.Block(arch.read(name), os.path.splitext(name)[1]); info = bytes(b.info)
            starts = tb.record_starts(info, b.n)
        except Exception:
            C['block_unreadable'] += 1
            continue
        C['blocks'] += 1
        for k, R in enumerate(starts):
            if tc.u32(info, R) != 3:
                continue
            C['models'] += 1
            for kind, lo, i in regions_of_model(info, R):
                C['regions_' + kind] += 1
                enc = end = None; err = ''
                try:
                    reg, end = tc.read_region(info, lo, kind)
                    enc = tc.write_region(reg, lo)
                    ok = enc == info[lo:end]
                    C['shapes'] += len(reg['shapes'])
                    C['bytes'] += end - lo
                except Exception as e:
                    ok = False; err = repr(e)
                if ok:
                    C['ok_' + kind] += 1
                    H.update(info[lo:end])
                else:
                    C['FAIL_' + kind] += 1
                    if len(fails) < 20:
                        if enc is not None:
                            orig = info[lo:end]
                            d = next((q for q in range(min(len(enc), len(orig))) if enc[q] != orig[q]), None)
                            fails.append([name.split('/')[-1], k, kind, i, 'len', len(enc), len(orig), 'firstdiff', d])
                        else:
                            fails.append([name.split('/')[-1], k, kind, i, err])
    print(dict(C))
    print('sha256 of all region bytes', H.hexdigest())
    for f in fails:
        print(f)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'roundtrip.json')
    json.dump(dict(counts=dict(C), sha256=H.hexdigest(), fails=fails), open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
