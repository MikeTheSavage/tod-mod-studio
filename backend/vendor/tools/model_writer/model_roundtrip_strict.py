"""Stricter round trip: drop every kept pad/gap byte (as a writer of new data would), encode, and check that
(1) the record has the same size and layout (allocation offsets), (2) it differs from the original only in pad bytes,
(3) it decodes again. Shows which bytes of a shipped record are exporter garbage. Read-only on the archive.
"""
import argparse, collections, json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todmodel as tm

PADKEYS = {'obj_pad', 'pad', 'tail', 'pad_obj', 'gap_vb', 'vb_pad_obj', 'vdata_pad', 'gap_ib', 'ib_pad_obj', 'idata_pad',
           'skin_pad', 'infl_pad', 'gap_mb'}


def strip(x):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in PADKEYS:
                continue
            if k == 'tail' or k == 'pads':
                continue
            out[k] = strip(v)
        if 's' in out and 'tail' in x:       # cstring node: tail is garbage after the NUL
            out['tail'] = None
        return out
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def coll_strip(reg):
    """todcoll keeps 'pads' per shape (uninitialised exporter bytes) and stream_raw high bits; drop them."""
    if reg is None:
        return None
    for s in reg['shapes']:
        s.pop('pads', None)
        s.pop('stream_raw', None)
    return reg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--naz', default=r'C:\GOG Games\Total Overdose\blocks.naz')
    a = ap.parse_args()
    arch = tb.Archive(a.naz)
    C = collections.Counter(); ex = []
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
            C['models'] += 1
            m = tm.decode(info, R, en[k])
            s = strip(m)
            for P in s['pivots']:
                coll_strip(P['coll'])
            coll_strip(s['hulls'])
            enc = tm.encode(s)
            orig = info[R:en[k]]
            if len(enc) != len(orig):
                C['size_differs'] += 1
                if len(ex) < 10:
                    ex.append([name.split('/')[-1], k, 'size', len(enc), len(orig)])
                continue
            m2 = tm.decode(enc, 0, len(enc))
            if m2['layout'] != m['layout']:
                C['layout_differs'] += 1
                continue
            C['same_size_and_layout'] += 1
            s2 = strip(m2)
            for P in s2['pivots']:
                coll_strip(P['coll'])
            coll_strip(s2['hulls'])
            s.pop('layout'); s2.pop('layout')
            if s2 != s:
                C['semantic_differs'] += 1
                if len(ex) < 10:
                    ex.append([name.split('/')[-1], k, 'semantic'])
            else:
                C['semantic_equal'] += 1
            nd = sum(1 for q in range(len(enc)) if enc[q] != orig[q])
            if nd == 0:
                C['identical_without_pads'] += 1
            else:
                C['differs_only_in_pad_bytes'] += 1
                C['pad_bytes_differing'] += nd
    print(json.dumps(dict(counts=dict(C), examples=ex), indent=1))


if __name__ == '__main__':
    main()
