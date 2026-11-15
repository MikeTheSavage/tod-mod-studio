"""test_area.py - top view (world X/Z) of the Map02 test spot: Ram's Slot00 spawn, his W-run track from the collision
lab's vanilla run r0, and the collision of the tree instance on that track (shapes at body height, y 1.2..3.2 m) for
vanilla and for each build. Writes one PNG.

  python -I test_area.py OUT.png R0_LOG VANILLA_BLOCK LABEL=BLOCK [LABEL=BLOCK ...]
"""
import os, re, sys
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import todblock as tb
import todmodel as tm
import model_writer as mw

MODEL = 'veg_tree_scruffy_small.model'
INST = ((-226.534, 1.186, -44.745), (0.0, -0.1736, 0.0, 0.9848))     # the instance on the W run (SUBMAP01_Map02_Addons)
SPAWN = (-242.475, -43.654)
X0, X1, Z0, Z1 = -244.0, -222.0, -49.0, -39.5
W, H = 700, 320


def shapes(block):
    b = tb.Block(open(block, 'rb').read(), os.path.splitext(block)[1]); info = bytes(b.info)
    st = tb.record_starts(info, b.n); en = st[1:] + [len(info)]
    k = [k for k, R in enumerate(st) if tb.u32(info, R) == 3 and tb.record_name(info, R).lower().endswith(MODEL)][0]
    m = tm.decode(info, st[k], en[k])
    out = []
    for P in m['pivots']:
        if P['coll']:
            out += [('piv', s) for s in P['coll']['shapes']]
    if m['hulls']:
        out += [('hull', s) for s in m['hulls']['shapes']]
    res = []
    for kind, s in out:
        V = [mw.apply(INST, v) for v in (s['verts'] if s['type'] == 4 else mw.box_corners(s))]
        ys = [v[1] for v in V]
        if max(ys) < 1.4 or min(ys) > 3.2:
            continue
        res.append((kind, hull2d([(v[0], v[2]) for v in V])))
    return res


def hull2d(pts):
    pts = sorted(set((round(x, 4), round(z, 4)) for x, z in pts))
    def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0: hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def track(log):
    pts = []
    for l in open(log):
        mm = re.match(r'(\d+) POS probe=\w+ ra=8BDC71 r=2.000 mask=03 pos ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
        if mm:
            x, z = float(mm.group(2)), float(mm.group(4))
            if X0 <= x <= X1 and Z0 <= z <= Z1:
                pts.append((int(mm.group(1)), x, z))
    # the first W run only: from the first move away from the spawn until the first time stamp gap > 3 s
    run = []
    for p in pts:
        if not run:
            if abs(p[1] - SPAWN[0]) > 0.3:
                run.append(p)
            continue
        if p[0] - run[-1][0] > 3000:
            break
        run.append(p)
    return [SPAWN] + [(x, z) for _, x, z in run]


def panel(title, vanilla, edited, tr):
    im = Image.new('RGB', (W, H + 24), (255, 255, 255))
    d = ImageDraw.Draw(im)
    def P(x, z):  # +X right, +Z up (TOD top view seen from above, left-handed: +Z away)
        return (x - X0) / (X1 - X0) * W, 24 + (Z1 - z) / (Z1 - Z0) * H
    for gx in range(int(X0), int(X1) + 1):
        d.line([P(gx, Z0), P(gx, Z1)], fill=(235, 235, 235) if gx % 5 else (205, 205, 205))
    for gz in range(int(Z0), int(Z1) + 1):
        d.line([P(X0, gz), P(X1, gz)], fill=(235, 235, 235) if gz % 5 else (205, 205, 205))
    for kind, h in vanilla:
        d.polygon([P(*p) for p in h], outline=(150, 150, 150))
    for kind, h in edited:
        d.polygon([P(*p) for p in h], outline=(255, 140, 0) if kind == 'piv' else (0, 170, 210), width=3)
    if len(tr) > 1:
        d.line([P(x, z) for x, z in tr], fill=(200, 0, 0), width=2)
    sx, sz = P(*SPAWN)
    d.ellipse([sx - 5, sz - 5, sx + 5, sz + 5], fill=(0, 0, 0))
    d.text((4, 4), title, fill=(0, 0, 0))
    d.text(P(-243.8, -48.6), 'x %.0f' % X0, fill=(90, 90, 90)); d.text(P(-224.5, -48.6), 'x %.0f' % X1, fill=(90, 90, 90))
    return im


def main():
    out, log, vblock = sys.argv[1:4]
    items = [a.split('=', 1) for a in sys.argv[4:]]
    tr = track(log)
    van = shapes(vblock)
    panels = [panel('vanilla: grey = tree collision at body height, red = Ram W run (r0), dot = spawn', van, [], tr)]
    for label, blk in items:
        panels.append(panel(label + ': orange = per-pivot list, cyan = HullList (grey = vanilla)', van, shapes(blk), tr))
    canvas = Image.new('RGB', (W, len(panels) * (H + 34)), (255, 255, 255))
    for i, p in enumerate(panels):
        canvas.paste(p, (0, i * (H + 34)))
    canvas.save(out)
    print('wrote', out, 'track points', len(tr))


if __name__ == '__main__':
    main()
