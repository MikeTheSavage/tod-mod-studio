"""Which entity instantiates which fragment ('fragment' property, index 9): fragrefs.py <block> [<block> ...]"""
import sys, os
sys.dont_write_bytecode = True
import todblock as tb, todfrag as tf
from dumptree import load, T, tree
FRAG = T.index('fragment')
for blk in sys.argv[1:]:
    b = load(blk); info = bytes(b.info); starts = tb.record_starts(info, b.n)
    names = {}
    for k, R in enumerate(starts):
        if tb.u32(info, R) != 4: continue
        nm = tb.record_name(info, R)
        fr = tf.Fragment(b.payloads[k], T)
        inf, kids = tree(fr)
        for nid, (ty, p) in inf.items():
            v = p.get('fragment')
            if v:
                print('%s :: %08X %s "%s" pos=%s orient=%s -> %s' % (nm.split('/')[-1], nid, ty, p.get('name'), p.get('pos'), p.get('orient'), v))
