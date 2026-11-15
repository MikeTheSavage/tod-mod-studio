"""Print decompiled GOG functions from ref/decomp.c by entry address (hex), e.g. fn.py 85D990 863070"""
import sys, re, os, pickle
REF = os.environ.get('TOD_REF', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref'))
idx_path = os.path.join(REF, 'decomp.idx')
src = os.path.join(REF, 'decomp.c')
if os.path.exists(idx_path):
    idx = pickle.load(open(idx_path, 'rb'))
else:
    idx = {}
    with open(src, 'rb') as f:
        pos = 0
        for line in f:
            if line.startswith(b'//==== FUNC '):
                m = re.search(rb'@ ([0-9A-F]{8})', line)
                idx[int(m.group(1), 16)] = pos
            pos += len(line)
    pickle.dump(idx, open(idx_path, 'wb'))
keys = sorted(idx)
import bisect
with open(src, 'rb') as f:
    for a in sys.argv[1:]:
        ad = int(a, 16)
        i = bisect.bisect_right(keys, ad) - 1
        if i < 0: print('none', a); continue
        start = idx[keys[i]]
        end = idx[keys[i + 1]] if i + 1 < len(keys) else None
        f.seek(start)
        data = f.read((end - start) if end else -1)
        sys.stdout.write(data.decode('utf-8', 'replace'))
