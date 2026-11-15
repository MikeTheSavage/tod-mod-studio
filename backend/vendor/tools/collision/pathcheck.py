"""pathcheck.py X0 Z0 X1 Z1 CLEAR BLOCKS... - collision shapes (static + per-pivot + boxes) whose XZ AABB comes
within CLEAR of the segment and that reach 0.3..2.0 m above the local ground (rough: y range overlaps -0.5..3.5)."""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import near
x0, z0, x1, z1, clear = map(float, sys.argv[1:6]); paths = sys.argv[6:]
def segdist(px, pz, mn, mx):
    best = 1e9
    for i in range(201):
        t = i / 200; x = x0 + (x1 - x0) * t; z = z0 + (z1 - z0) * t
        dx = max(mn[0] - x, 0, x - mx[0]); dz = max(mn[2] - z, 0, z - mx[2])
        best = min(best, math.hypot(dx, dz))
    return best
for h in near.hulls_world(paths):
    W = h['world']
    mn = [min(v[i] for v in W) for i in range(3)]; mx = [max(v[i] for v in W) for i in range(3)]
    if mx[1] - mn[1] < 0.25 or mn[1] > 3.5 or mx[1] < 0.3: continue      # flat ground pieces and high stuff skipped
    d = segdist(0, 0, mn, mx)
    if d <= clear:
        print('%5.2f %-40s %8s x %8.2f..%8.2f y %6.2f..%6.2f z %8.2f..%8.2f' % (d, h['model'].split('/')[-1][:40], h['index'], mn[0], mx[0], mn[1], mx[1], mn[2], mx[2]))
