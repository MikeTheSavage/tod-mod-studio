"""analyze.py - numbers for one test session (runseq.sh) from the collwatch log and the todrun step ticks.

  python analyze.py RUN_LABEL            (reads logs/<label>_collwatch.log and the 'todrun: hold' lines of ACTION_LOG.md)

Prints, per test:
  A wall     Ram's x when W has been held 10 s (vanilla: stopped at the Farmacia shop front, x ~ -198.8)
  B box      Ram's x after D 0.8 s + W 4 s (vanilla: runs on to the street; modded: held at the block's face x -232)
  bullets    the bullet segment tests (IsLineColliding called from 0x8C95A9, mask 03): hits and hits on our shapes
  C camera   camera distance behind Ram (start of the lens-flare ray = camera position) at the end of the camera test
  queries    per-mask counts of GetClosestNode / IsLineColliding results that were one of our added shapes
"""
import re, sys, os, collections
LAB = os.environ.get('TOD_COLL_LAB', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lab'))   # lab: logs/ and ACTION_LOG.md
label = sys.argv[1]
log = open(os.path.join(LAB, 'logs', label + '_collwatch.log')).read().splitlines()
steps = []
for l in open(os.path.join(LAB, 'ACTION_LOG.md'), encoding='utf-8'):
    m = re.search(r'todrun: hold (\w+) ([\d.]+)s ticks (\d+)\.\.(\d+) cap .*/caps/%s/(\w+)' % re.escape(label), l)
    if m:
        steps.append(dict(key=m.group(1), t0=int(m.group(3)), t1=int(m.group(4)), name=m.group(5)))
S = {s['name']: s for s in steps}

player = []      # (t, x, y, z)
cam = []         # (t, x, y, z)
prev_to = None
for l in log:
    m = re.match(r'(\d+) POS probe=\w+ ra=\w+ r=2\.000 mask=03 pos ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
    if m:
        player.append(tuple([int(m.group(1))] + [float(x) for x in m.groups()[1:]])); continue
    m = re.match(r'(\d+) LINE ra=8E4EBA probe=\w+ mask=04 from ([-\d.]+) ([-\d.]+) ([-\d.]+) to ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
    if m:
        fr = tuple(float(x) for x in m.groups()[1:4]); to = tuple(float(x) for x in m.groups()[4:7])
        chained = prev_to is not None and all(abs(a - b) < 1e-3 for a, b in zip(fr, prev_to))
        prev_to = to
        if not chained:
            cam.append((int(m.group(1)),) + fr)


def at(seq, t):
    best = None
    for r in seq:
        if r[0] <= t:
            best = r
        else:
            break
    return best


def fmt(p):
    return '(%.3f, %.3f, %.3f)' % p[1:4] if p else '?'


print('run', label)
if 'a_wall' in S:
    s = S['a_wall']; p0 = at(player, s['t0'] + 50); p1 = at(player, S['a_still']['t1'] if 'a_still' in S else s['t1'] + 1000)
    print('A wall : start %s  end %s   (Farmacia front face at x = -198.32)' % (fmt(p0), fmt(p1)))
if 'b1_box' in S:
    s = S['b1_box']; p0 = at(player, s['t0'] + 50); p1 = at(player, s['t1'] + 500)
    print('B box  : start %s  end %s   (invisible block face at x = -232.00, z -49.3..-46.3)' % (fmt(p0), fmt(p1)))
if 'b2_shoot' in S:
    s = S['b2_shoot']
    segs = [l for l in log if ' LINE ra=8C95A9 ' in l and s['t0'] - 100 <= int(l.split()[0]) <= s['t1'] + 1500]
    hits = [l for l in segs if 'hit=1' in l]; ours = [l for l in segs if re.search(r'ours=\d', l)]
    print('bullets: %d segment tests, %d hits, %d on our shapes; first hit: %s' % (len(segs), len(hits), len(ours), hits[0][:160] if hits else '-'))
if 'c4_still' in S:
    s = S['c4_still']; t = s['t1']
    c = at(cam, t); p = at(player, t)
    if c and p:
        d = ((c[1] - p[1]) ** 2 + (c[3] - p[3]) ** 2) ** 0.5
        print('C cam  : Ram %s camera %s  horizontal %.2f m behind, %.2f m above his feet' % (fmt(p), fmt(c), d, c[2] - p[2]))
    for name in ('c1_side', 'c2_past'):
        if name in S:
            c = at(cam, S[name]['t0']); p = at(player, S[name]['t0'])
            if c and p:
                print('         before %s: %.2f m behind, %.2f m above' % (name, ((c[1]-p[1])**2 + (c[3]-p[3])**2) ** 0.5, c[2] - p[2]))
tot_close = collections.Counter(); tot_line = collections.Counter()
for l in log:
    if ' SUM ' not in l:
        continue
    a, b = l.split('| line by mask:')
    for m in re.finditer(r'm(\w\w)=(\d+)/(\d+)/(\d+)', a):
        tot_close[m.group(1)] += int(m.group(4))
    for m in re.finditer(r'm(\w\w)=(\d+)/(\d+)/(\d+)', b):
        tot_line[m.group(1)] += int(m.group(4))
print('results that were our shapes, by probe mask (Solid 01 BulletProof 02 Opaque 04 CameraBlock 08 NavBlock 20 Physics 40):')
print('  GetClosestNode :', dict(tot_close))
print('  IsLineColliding:', dict(tot_line))
first = {}
for l in log:
    m = re.match(r'(\d+) (CLOSE|LINE) ra=(\w+) probe=\w+ mask=(\w+).*ours=(\d)', l)
    if m:
        first.setdefault((m.group(2), m.group(3), m.group(4), m.group(5)), l[:200])
for k, v in sorted(first.items()):
    print('  first', k, '->', v)
