"""Print decompiled GOG functions by address from every dump in ref/ (decomp.c, decomp_created.c, decomp_ai*.c,
plus any ref/mdump_*.c this lab produced). Exact entry match first; otherwise the containing function of decomp.c.

  python fn2.py 7FD4B0 7F55E0 ...        print bodies
  python fn2.py --missing 7FD4B0 ...      print the addresses that have no exact entry anywhere
"""
import sys, re, os, glob, pickle, bisect
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.environ.get('TOD_REF', os.path.join(HERE, '..', 'ref'))
IDX = os.path.join(REF, 'fn2.idx')


def files():
    fs = [os.path.join(REF, 'decomp.c')]
    for p in ('decomp_created.c', 'decomp_ai.c', 'decomp_ai2.c'):
        fs.append(os.path.join(REF, p))
    fs += sorted(glob.glob(os.path.join(REF, 'mdump_*.c')))
    return [f for f in fs if os.path.exists(f)]


def build():
    idx = {}
    for fp in files():
        pos = 0
        ent = []
        with open(fp, 'rb') as f:
            for line in f:
                if line.startswith(b'//==== FUNC '):
                    m = re.search(rb'@ ([0-9A-F]{8})', line)
                    ent.append((int(m.group(1), 16), pos))
                pos += len(line)
        ent.append((None, pos))
        for i in range(len(ent) - 1):
            a, s = ent[i]
            e = ent[i + 1][1]
            idx.setdefault(a, (fp, s, e))
    stamp = {fp: os.path.getmtime(fp) for fp in files()}
    pickle.dump((stamp, idx), open(IDX, 'wb'))
    return idx


def load():
    if os.path.exists(IDX):
        stamp, idx = pickle.load(open(IDX, 'rb'))
        if stamp == {fp: os.path.getmtime(fp) for fp in files()}:
            return idx
    return build()


def body(idx, a):
    if a in idx:
        fp, s, e = idx[a]
        with open(fp, 'rb') as f:
            f.seek(s)
            return f.read(e - s).decode('utf-8', 'replace'), True
    main = os.path.join(REF, 'decomp.c')
    keys = sorted(k for k, v in idx.items() if v[0] == main)
    i = bisect.bisect_right(keys, a) - 1
    if i < 0:
        return None, False
    fp, s, e = idx[keys[i]]
    with open(fp, 'rb') as f:
        f.seek(s)
        return '// (containing function)\n' + f.read(e - s).decode('utf-8', 'replace'), False


if __name__ == '__main__':
    idx = load()
    args = sys.argv[1:]
    if args and args[0] == '--missing':
        for x in args[1:]:
            if int(x, 16) not in idx:
                print('%08X' % int(x, 16))
        sys.exit(0)
    for x in args:
        t, exact = body(idx, int(x, 16))
        sys.stdout.write(t if t else '// none %s\n' % x)
