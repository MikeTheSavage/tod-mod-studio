"""List entities whose create type matches a substring: find_ents.py <block> <type substring> [--props]"""
import sys, os, collections
sys.dont_write_bytecode = True
import todblock as tb, todfrag as tf
from dumptree import load, T
b = load(sys.argv[1]); info = bytes(b.info); starts = tb.record_starts(info, b.n)
sub = sys.argv[2].lower(); showp = '--props' in sys.argv
cnt = collections.Counter()
for k, R in enumerate(starts):
    if tb.u32(info, R) != 4: continue
    nm = tb.record_name(info, R)
    fr = tf.Fragment(b.payloads[k], T)
    for nid, e in fr.entities().items():
        if e['type'] and sub in e['type'].lower():
            p = {T.name(r.prop): fr.value(r) for r in e['sets']}
            cnt[(nm.split('/')[-1], e['type'])] += 1
            if showp:
                keep = {kk: v for kk, v in p.items() if kk in ('name', 'pos', 'orient', 'parent', 'width', 'height', 'length', 'CollisionFlags', 'flags', 'touchmask', 'dynamicmask', 'usermask')}
                print(nm.split('/')[-1], hex(nid), e['type'], keep)
for k, v in cnt.most_common(): print(v, k)
