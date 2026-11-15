"""Software render (numpy z-buffer) of a render glb and a collision glb for an overlay check.

  python render_overlay.py RENDER.glb COLLISION.glb OUT.png  --view top|persp  [--eye x y z --at x y z --fov deg]
         [--crop xmin xmax zmin zmax]  [--size W H]

Coordinates are glTF (y up, the exporters negated TOD's Z). Panels: render only | collision only | overlay
(render shading + collision colour at 55 % where the collision surface is within 'tol' of the visible render surface
or in front of it, plus collision edges)."""
import sys, json, struct, argparse, math
import numpy as np
from PIL import Image, ImageDraw


def read_glb(path):
    d = open(path, 'rb').read()
    jl, = struct.unpack_from('<I', d, 12)
    js = json.loads(d[20:20 + jl])
    bin_ = d[20 + jl + 8:]
    def acc(i):
        a = js['accessors'][i]; v = js['bufferViews'][a['bufferView']]
        comp = {5126: ('f', 4), 5123: ('H', 2), 5125: ('I', 4)}[a['componentType']]
        n = {'SCALAR': 1, 'VEC3': 3}[a['type']]
        arr = np.frombuffer(bin_, dtype=np.dtype('<' + comp[0]), count=a['count'] * n, offset=v['byteOffset'])
        return arr.reshape(-1, n) if n > 1 else arr
    out = []
    for node in js['nodes']:
        m = js['meshes'][node['mesh']]
        for p in m['primitives']:
            pos = acc(p['attributes']['POSITION']).astype(np.float64)
            col = acc(p['attributes']['COLOR_0']).astype(np.float64) if 'COLOR_0' in p['attributes'] else None
            idx = acc(p['indices']).astype(np.int64).reshape(-1, 3)
            out.append((m['name'], pos, col, idx))
    return out


def look_at(eye, at, up=(0, 1, 0)):
    eye = np.array(eye, float); at = np.array(at, float); up = np.array(up, float)
    f = at - eye; f /= np.linalg.norm(f)
    r = np.cross(f, up); r /= np.linalg.norm(r)
    u = np.cross(r, f)
    M = np.eye(4); M[0, :3] = r; M[1, :3] = u; M[2, :3] = -f
    M[:3, 3] = -M[:3, :3] @ eye
    return M


class Cam:
    def __init__(self, W, H, view, ortho=None, fov=50.0, near=0.5):
        self.W, self.H, self.V, self.ortho, self.fov, self.near = W, H, view, ortho, fov, near

    def project(self, P):
        """P (N,3) world -> (N,3) screen x,y and depth (positive distance)."""
        Q = np.c_[P, np.ones(len(P))] @ self.V.T
        z = -Q[:, 2]
        if self.ortho:
            x0, x1, y0, y1 = self.ortho
            sx = (Q[:, 0] - x0) / (x1 - x0) * self.W
            sy = (y1 - Q[:, 1]) / (y1 - y0) * self.H
        else:
            f = 0.5 * self.H / math.tan(math.radians(self.fov) * 0.5)
            zz = np.maximum(z, 1e-6)
            sx = self.W * 0.5 + f * Q[:, 0] / zz
            sy = self.H * 0.5 - f * Q[:, 1] / zz
        return np.c_[sx, sy, z]


def raster(cam, tris, ids):
    """tris (T,3,3) world. Returns depth (H,W) and id (H,W) (-1 = none)."""
    W, H = cam.W, cam.H
    depth = np.full((H, W), np.inf); idb = np.full((H, W), -1, np.int64)
    S = cam.project(tris.reshape(-1, 3)).reshape(-1, 3, 3)
    keep = (S[:, :, 2] > cam.near).all(1)
    xs, ys = S[:, :, 0], S[:, :, 1]
    keep &= (xs.max(1) >= 0) & (xs.min(1) < W) & (ys.max(1) >= 0) & (ys.min(1) < H)
    for t in np.nonzero(keep)[0]:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = S[t]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        bx0 = max(int(math.floor(min(x0, x1, x2))), 0); bx1 = min(int(math.ceil(max(x0, x1, x2))), W - 1)
        by0 = max(int(math.floor(min(y0, y1, y2))), 0); by1 = min(int(math.ceil(max(y0, y1, y2))), H - 1)
        if bx1 < bx0 or by1 < by0:
            continue
        px, py = np.meshgrid(np.arange(bx0, bx1 + 1) + 0.5, np.arange(by0, by1 + 1) + 0.5)
        w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
        w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not m.any():
            continue
        if cam.ortho:
            z = w0 * z0 + w1 * z1 + w2 * z2
        else:
            z = 1.0 / (w0 / z0 + w1 / z1 + w2 / z2)
        sub = depth[by0:by1 + 1, bx0:bx1 + 1]
        upd = m & (z < sub)
        sub[upd] = z[upd]
        idb[by0:by1 + 1, bx0:bx1 + 1][upd] = ids[t]
    return depth, idb


def shade(tris, light=(0.4, 0.8, 0.3)):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    L = np.array(light, float); L /= np.linalg.norm(L)
    return 0.35 + 0.65 * np.abs(n @ L)


def gather(meshes):
    T = []; C = []
    for name, pos, col, idx in meshes:
        T.append(pos[idx])
        C.append(col[idx[:, 0]] if col is not None else np.full((len(idx), 3), 0.8))
    return (np.concatenate(T), np.concatenate(C)) if T else (np.zeros((0, 3, 3)), np.zeros((0, 3)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('render'); ap.add_argument('collision'); ap.add_argument('out')
    ap.add_argument('--view', default='top')
    ap.add_argument('--eye', type=float, nargs=3); ap.add_argument('--at', type=float, nargs=3)
    ap.add_argument('--fov', type=float, default=55)
    ap.add_argument('--crop', type=float, nargs=4)
    ap.add_argument('--size', type=int, nargs=2, default=(900, 900))
    ap.add_argument('--tol', type=float, default=0.15)
    ap.add_argument('--title', default='')
    a = ap.parse_args()
    RT, RC = gather(read_glb(a.render))
    CT, CC = gather(read_glb(a.collision))
    W, H = a.size
    if a.view == 'top':
        allp = np.concatenate([RT.reshape(-1, 3), CT.reshape(-1, 3)])
        if a.crop:
            x0, x1, z0, z1 = a.crop
        else:
            x0, x1 = allp[:, 0].min(), allp[:, 0].max(); z0, z1 = allp[:, 2].min(), allp[:, 2].max()
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2; half = max(x1 - x0, z1 - z0) / 2 * 1.02
        top = allp[:, 1].max() + 50
        V = look_at((cx, top, cz), (cx, top - 1, cz), up=(0, 0, -1))
        cam = Cam(W, H, V, ortho=(-half, half, -half, half))
    else:
        cam = Cam(W, H, look_at(a.eye, a.at), fov=a.fov)
    rd, rid = raster(cam, RT, np.arange(len(RT)))
    cd, cid = raster(cam, CT, np.arange(len(CT)))
    rs = shade(RT) if len(RT) else np.zeros(0)
    cs = shade(CT) if len(CT) else np.zeros(0)
    bg = np.array([0.08, 0.09, 0.11])
    img_r = np.tile(bg, (H, W, 1)); img_c = img_r.copy()
    m = rid >= 0
    img_r[m] = (np.array([0.85, 0.85, 0.82]) * rs[rid[m]][:, None])
    mc = cid >= 0
    img_c[mc] = CC[cid[mc]] * cs[cid[mc]][:, None]
    over = img_r.copy()
    if a.view == 'top':
        vis = mc
    else:
        vis = mc & (cd <= rd + a.tol * np.maximum(1, cd / 20))
    over[vis] = 0.45 * over[vis] + 0.55 * CC[cid[vis]]
    panels = [(img_r, 'render geometry (LOD0)'), (img_c, 'collision'), (over, 'overlay')]
    out = Image.new('RGB', (W * 3 + 20, H + 34), (20, 22, 26))
    dr = ImageDraw.Draw(out)
    for k, (im, label) in enumerate(panels):
        out.paste(Image.fromarray((np.clip(im, 0, 1) * 255).astype(np.uint8)), (k * (W + 10), 34))
        dr.text((k * (W + 10) + 6, 10), label, fill=(230, 230, 230))
    if a.title:
        dr.text((W * 3 + 20 - 8 * len(a.title) - 6, 10), a.title, fill=(200, 200, 120))
    # collision edges on the overlay panel
    ov = ImageDraw.Draw(out)
    S = cam.project(CT.reshape(-1, 3)).reshape(-1, 3, 3)
    ok = (S[:, :, 2] > cam.near).all(1)
    for t in np.nonzero(ok)[0][:400000]:
        p = S[t]
        if a.view != 'top':
            cxp, cyp = int(p[:, 0].mean()), int(p[:, 1].mean())
            if not (0 <= cxp < W and 0 <= cyp < H) or cid[cyp, cxp] != t:
                continue
        pts = [(2 * (W + 10) + float(q[0]), 34 + float(q[1])) for q in p] + [(2 * (W + 10) + float(p[0][0]), 34 + float(p[0][1]))]
        if all(0 <= q[0] - 2 * (W + 10) < W and 0 <= q[1] - 34 < H for q in pts):
            col = tuple(int(255 * min(1, c * 0.6)) for c in CC[t])
            ov.line(pts, fill=col, width=1)
    out.save(a.out)
    stats = dict(render_px=int(m.sum()), collision_px=int(mc.sum()), overlay_px=int(vis.sum()))
    if a.view != 'top':
        both = m & mc
        dz = np.abs(cd[both] - rd[both])
        stats['coincident_px_within_tol'] = int((dz <= a.tol * np.maximum(1, cd[both] / 20)).sum())
        stats['both_px'] = int(both.sum())
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
