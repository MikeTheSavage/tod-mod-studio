"""Stricter round trip: rebuild every shape from its semantic fields only (no kept object bytes, no kept aux bytes,
zero padding, no kept stream bits). Counts regions that are still byte-identical; the rest differ only where the
original exporter left uninitialised bytes (listed by kind)."""
import sys, os, collections, struct
sys.path.insert(0, os.path.dirname(__file__))
import todblock as tb, todcoll as tc
from roundtrip import regions_of_model, NAZ

def semantic(reg):
    for s in reg['shapes']:
        if s['type'] != 4:
            continue
        keep = bytearray(tc.new_hull_obj(s['sphere'], s['extrude'], s['flags20'], s['surf']))
        struct.pack_into('<I', keep, 0x28, s['x28'])
        struct.pack_into('<II', keep, 0x44, *s['facemat_hdr'])
        s['obj_keep'] = bytes(keep)
        s['pads'] = {}
        s.pop('stream_raw', None)
        if s.get('aux'):
            a = bytearray(tc.AUX_TEMPLATE)
            s['aux']['raw'] = bytes(a)
    return reg

arch = tb.Archive(NAZ)
C = collections.Counter()
for name in sorted(n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS):
    try:
        b = tb.Block(arch.read(name), os.path.splitext(name)[1]); info = bytes(b.info); starts = tb.record_starts(info, b.n)
    except Exception:
        continue
    for k, R in enumerate(starts):
        if tc.u32(info, R) != 3:
            continue
        for kind, lo, i in regions_of_model(info, R):
            reg, end = tc.read_region(info, lo, kind)
            garbage = any(any(x for x in p) for s in reg['shapes'] if s['type'] == 4 for p in s['pads'].values()) or \
                any(s['type'] == 4 and s['stream_raw'] != tc.encode_faces(s['faces'], s['bits'])[0] for s in reg['shapes'])
            enc = tc.write_region(semantic(reg), lo)
            same = enc == info[lo:end]
            C[('identical' if same else 'differs', 'has_uninit_bytes' if garbage else 'clean')] += 1
for k, v in sorted(C.items()):
    print(k, v)
