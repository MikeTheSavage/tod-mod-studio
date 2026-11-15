"""Print a fragment's entity tree: dumptree.py <block entry or file> <fragment name substring> [maxdepth] [--props]"""
import sys, os, collections
sys.dont_write_bytecode = True
import todblock as tb, todfrag as tf
T = tf.Types()
def load(block):
    if os.path.exists(block):
        return tb.Block(open(block, 'rb').read(), os.path.splitext(block)[1])
    return tb.load_block(tb.Archive(r"C:\GOG Games\Total Overdose\blocks.naz"), block)
def frag_index(b, sub):
    info = bytes(b.info); starts = tb.record_starts(info, b.n)
    hits = [(k, tb.record_name(info, R)) for k, R in enumerate(starts) if tb.u32(info, R) == 4 and sub.lower() in tb.record_name(info, R).lower()]
    return hits
def tree(fr):
    ents = fr.entities()
    info = {}
    for nid, e in ents.items():
        props = {}
        for r in e['sets']:
            props[T.name(r.prop)] = fr.value(r)
        info[nid] = (e['type'], props)
    kids = collections.defaultdict(list)
    for nid, (ty, p) in info.items():
        kids[p.get('parent', 0) or 0].append(nid)
    return info, kids
if __name__ == '__main__':
    b = load(sys.argv[1]); hits = frag_index(b, sys.argv[2])
    k, nm = hits[0]
    fr = tf.Fragment(b.payloads[k], T)
    info, kids = tree(fr)
    maxd = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    showp = '--props' in sys.argv
    def pr(n, d):
        if d > maxd: return
        ty, p = info[n]
        extra = ''
        if showp: extra = ' ' + str({k: v for k, v in p.items() if k not in ('parent', 'name')})[:300]
        print('  ' * d + '%08X %s "%s"%s' % (n, ty, p.get('name'), extra))
        for c in kids.get(n, []): pr(c, d + 1)
    print(nm, len(info), 'entities')
    for r in kids.get(0, []): pr(r, 0)
