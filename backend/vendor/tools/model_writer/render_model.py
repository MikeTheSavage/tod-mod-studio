"""render_model.py - proof pictures of a model before/after an edit: render geometry (flat shaded, numpy z-buffer)
with the collision shapes drawn as coloured wireframes (per-pivot lists orange, HullList cyan, OrientedBoxes red).

  python -I render_model.py OUT.png MODELNAME BLOCK_BEFORE BLOCK_AFTER [--title "..."] [--size 520]

Two rows (before, after), three views each: 3/4 perspective, side (looking +Z), top (looking down). Model space,
TOD axes (left-handed, y up; the views mirror nothing: +X is to the right in the side and top views).
"""
import argparse, math, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import todblock as tb
import todmodel as tm
import model_writer as mw


def load(block, name):
    b = tb.Block(open(block, 'rb').read(), os.path.splitext(block)[1])
    info = bytes(b.info)
    st = tb.record_starts(info, b.n); en = st[1:] + [len(info)]
    for k, R in enumerate(st):
        if tb.u32(info, R) == 3 and tb.record_name(info, R).lower().endswith(name.lower()):
            return tm.decode(info, R, en[k])
    raise SystemExit('model not found in ' + block)


def geometry(m):
    spec = mw.spec_from_model(m)
    PW = mw.pivot_world(spec['pivots'])
    tris = []
    for i, P in enumerate(spec['pivots']):
        for me in P['meshes']:
            V = [mw.apply(PW[i], v) for v in mw.vertex_positions(me)]
            for a, b, c in mw.triangles_of(me):
                tris.append((V[a], V[b], V[c]))
    edges = []
    def shape_edges(s, T, col):
        if s['type'] == 4:
            V = [mw.apply(T, v) for v in s['verts']]
            for f in s['faces']:
                for q in range(len(f)):
                    edges.append((V[f[q]], V[f[(q + 1) % len(f)]], col))
        else:
            C = [mw.apply(T, v) for v in mw.box_corners(s)]
            for a in range(8):
                for b in range(a + 1, 8):
                    if bin(a ^ b).count('1') == 1:
                        edges.append((C[a], C[b], (230, 40, 40)))
    for i, P in enumerate(m['pivots']):
        if P['coll']:
            for s in P['coll']['shapes']:
                shape_edges(s, PW[i], (255, 140, 0))
    if m['hulls']:
        for s in m['hulls']['shapes']:
            shape_edges(s, ((0, 0, 0), (0, 0, 0, 1)), (0, 200, 230))
    sph = struct.unpack_from('<4f', m['raw'], 0x44)
    return tris, edges, sph


def view_matrix(kind, centre, radius):
    c = np.array(centre)
    if kind == 'persp':
        d = np.array([-0.55, 0.45, -0.70]); d /= np.linalg.norm(d)
        eye = c + d * radius * 2.6
        f = c - eye; f /= np.linalg.norm(f)
    elif kind == 'side':
        eye = c + np.array([0, 0, -radius * 3]); f = np.array([0, 0, 1.0])
    else:
        eye = c + np.array([0, radius * 3, 0]); f = np.array([0, -1.0, 0])
    up = np.array([0, 1.0, 0]) if kind != 'top' else np.array([0, 0, 1.0])
    # TOD is left-handed: right = up x forward
    r = np.cross(up, f); r /= np.linalg.norm(r)
    u = np.cross(f, r)
    return eye, r, u, f


def render(tris, edges, kind, centre, radius, W):
    eye, r, u, f = view_matrix(kind, centre, radius)
    img = np.full((W, W, 3), 245, np.uint8)
    zb = np.full((W, W), np.inf)
    persp = kind == 'persp'
    scale = W / (2.3 * radius)
    fl = W * 0.5 / math.tan(math.radians(22))

    def proj(p):
        d = np.asarray(p) - eye
        x, y, z = d @ r, d @ u, d @ f
        if persp:
            return W / 2 + fl * x / z, W / 2 - fl * y / z, z
        return W / 2 + x * scale, W / 2 - y * scale, z
    light = np.array([0.4, 0.8, -0.45]); light /= np.linalg.norm(light)
    for A, B, C in tris:
        a, b, c = proj(A), proj(B), proj(C)
        n = np.cross(np.subtract(B, A), np.subtract(C, A))
        ln = np.linalg.norm(n)
        if ln == 0:
            continue
        shade = 0.35 + 0.65 * abs(n @ light) / ln
        col = np.array([150, 160, 150]) * shade
        xs = [a[0], b[0], c[0]]; ys = [a[1], b[1], c[1]]
        x0, x1 = max(int(min(xs)), 0), min(int(max(xs)) + 1, W - 1)
        y0, y1 = max(int(min(ys)), 0), min(int(max(ys)) + 1, W - 1)
        if x0 > x1 or y0 > y1:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-9:
            continue
        w0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
        w1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        z = w0 * a[2] + w1 * b[2] + w2 * c[2]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (z < sub)
        sub[upd] = z[upd]
        img[y0:y1 + 1, x0:x1 + 1][upd] = col.astype(np.uint8)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    for A, B, col in edges:
        a, b = proj(A), proj(B)
        if persp and (a[2] <= 0 or b[2] <= 0):
            continue
        dr.line([(a[0], a[1]), (b[0], b[1])], fill=col, width=2)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('model'); ap.add_argument('before'); ap.add_argument('after')
    ap.add_argument('--title', default='')
    ap.add_argument('--size', type=int, default=420)
    a = ap.parse_args()
    rows = []
    sets = [('before', load(a.before, a.model)), ('after', load(a.after, a.model))]
    geo = [geometry(m) for _, m in sets]
    # common framing: the larger of the two model spheres
    sph = max((g[2] for g in geo), key=lambda s: s[3])
    centre, radius = sph[:3], max(sph[3], 0.5)
    W = a.size
    canvas = Image.new('RGB', (3 * W + 40, 2 * W + 90), (255, 255, 255))
    dr = ImageDraw.Draw(canvas)
    dr.text((10, 8), a.title or a.model, fill=(0, 0, 0))
    dr.text((10, 24), 'grey: render geometry   orange: per-pivot CollisionList (pivot+0x44)   cyan: HullList (+0x54)   '
                      'red: OrientedBox', fill=(60, 60, 60))
    for row, ((label, m), (tris, edges, s)) in enumerate(zip(sets, geo)):
        y = 50 + row * (W + 20)
        dr.text((10, y - 12), '%s: %d triangles, %d collision edges, model sphere r=%.2f' % (label, len(tris), len(edges), s[3]),
                fill=(0, 0, 0))
        for col, kind in enumerate(('persp', 'side', 'top')):
            im = render(tris, edges, kind, centre, radius, W)
            canvas.paste(im, (10 + col * (W + 10), y))
    canvas.save(a.out)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
