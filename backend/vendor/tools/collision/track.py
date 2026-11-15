"""track.py LOG T0 T1 [mask] - positions of mode-0 probes moving between ticks T0..T1 (player: r=2.000 mask=03)."""
import re, sys, collections
L = open(sys.argv[1]).read().splitlines()
t0, t1 = int(sys.argv[2]), int(sys.argv[3]); want = sys.argv[4] if len(sys.argv) > 4 else None
pos = collections.defaultdict(list)
for l in L:
    m = re.match(r'(\d+) POS probe=(\w+) ra=(\w+) r=([\d.-]+) mask=(\w+) pos ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
    if m and t0 <= int(m.group(1)) <= t1 and (want is None or m.group(5) == want):
        pos[(m.group(2), m.group(4), m.group(5))].append((int(m.group(1)), float(m.group(6)), float(m.group(7)), float(m.group(8))))
for k, v in sorted(pos.items(), key=lambda kv: -len(kv[1])):
    net = ((v[-1][1]-v[0][1])**2 + (v[-1][3]-v[0][3])**2) ** 0.5
    if net < 0.5: continue
    print(k, 'n', len(v), 'net %.2f' % net)
    for x in v[::max(1, len(v)//15)] + [v[-1]]:
        print('   %d %.3f %.3f %.3f' % x)
