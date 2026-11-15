"""geomkit.py - turn a small JSON description of a static model (parts + textures) into a model_writer spec with its
HullList. Everything is in the MODEL's own space (TOD axes, y up, metres); placements put it into the world.

A model description (the "models" entries of new_geometry in make_new_map.py):
  {"name": "AdobeHouse",
   "parts": [ {"type": "box",   "min": [x,y,z], "max": [x,y,z], "tex": "Adobe", "uv": 0.33,        uv = texture repeats per metre
                                 "faces": "all" | "-y" | "+y+z..." (axis faces to build, default all),
                                 "collide": true, "material": "Concrete", "surface": "solid"},
              {"type": "wedge", "min": [..], "max": [..], "rise": "+z", "tex": "Concrete", "uv": 0.25, "collide": true},
              {"type": "rock",  "center": [x,y,z], "radius": 1.5, "squash": 0.7, "seed": 3, "tex": "Cliff", "uv": 0.2},
              {"type": "heightfield", "xs": [...], "zs": [...], "heights": [[...] per z row, each len(xs)],
               "tex": "Sand", "steep_tex": "Cliff", "steep": 1.2 (slope limit, rise/run), "uv": 0.125,
               "collide": {"box": [x0, z0, x1, z1] (cells inside only), "thickness": 1.5}, "material": "Dirt"} ]}
Textures are named, the model's texture list is the set used (in first-use order). One submesh per texture.
Collision: every part with "collide" adds convex pieces to the model's HullList (model space): boxes and wedges one hull
each, a rock its convex hull, a heightfield one slab per rectangle of flat cells and two prisms per other cell.
"""
import math
import os
import struct
import sys

import numpy as np
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import cpu_guard  # noqa: E402,F401  (keeps numpy off the faulty CPU cores, see cpu_guard.py)

SURFACES = {'solid': 0x02007C00, 'thin': 0x02007400}
MATERIALS = ["AllRound", "Metal", "Concrete", "Wood", "Dirt", "Stone", "Glass", "Bush", "Wirefence", "Grass", "Asphalt",
             "Water", "Cloth", "SolidGlass"]


def mat_index(m):
    if m is None or m == 'none':
        return 0xFF
    if isinstance(m, int):
        return m
    for i, n in enumerate(MATERIALS):
        if n.lower() == str(m).lower():
            return i
    raise ValueError('unknown face material %r' % m)


def surf_word(s):
    if s is None:
        return SURFACES['solid']
    if isinstance(s, str) and s in SURFACES:
        return SURFACES[s]
    return int(s, 16) if isinstance(s, str) else int(s)


class Group:
    def __init__(self):
        self.P, self.N, self.T, self.tris = [], [], [], []

    def quad(self, pts, n, uvs):
        b = len(self.P)
        for p, t in zip(pts, uvs):
            self.P.append(tuple(float(c) for c in p)); self.N.append(tuple(float(c) for c in n)); self.T.append(tuple(t))
        self.tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]

    def tri(self, pts, nrm, uvs):
        b = len(self.P)
        for p, n, t in zip(pts, nrm, uvs):
            self.P.append(tuple(float(c) for c in p)); self.N.append(tuple(float(c) for c in n)); self.T.append(tuple(t))
        self.tris.append((b, b + 1, b + 2))


class ModelBuilder:
    def __init__(self, name):
        self.name = name
        self.groups = {}              # texture name -> Group (insertion order = texture list order)
        self.hulls = []               # (verts, surf word, material index)

    def group(self, tex):
        if tex not in self.groups:
            self.groups[tex] = Group()
        return self.groups[tex]

    # ------------------------------------------------------------------ parts
    def add_box(self, mn, mx, tex, uv=0.25, skip=(), collide=True, material=None, surface=None, uv_off=(0.0, 0.0)):
        x0, y0, z0 = mn; x1, y1, z1 = mx
        g = self.group(tex)
        ou, ov = uv_off
        F = [('+x', (1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ('-x', (-1, 0, 0), [(x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0)]),
             ('+y', (0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
             ('-y', (0, -1, 0), [(x0, y0, z1), (x0, y0, z0), (x1, y0, z0), (x1, y0, z1)]),
             ('+z', (0, 0, 1), [(x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)]),
             ('-z', (0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)])]
        for key, n, quad in F:
            if key in skip:
                continue
            uvs = []
            for v in quad:
                if n[1] != 0:
                    uvs.append(((v[0] + ou) * uv, (v[2] + ov) * uv))
                elif n[0] != 0:
                    uvs.append(((v[2] + ou) * uv, (-v[1] + ov) * uv))
                else:
                    uvs.append(((v[0] + ou) * uv, (-v[1] + ov) * uv))
            g.quad(quad, n, uvs)
        if collide:
            pts = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
            self.hulls.append((pts, surf_word(surface), mat_index(material)))

    def add_wedge(self, mn, mx, rise, tex, uv=0.25, collide=True, material=None, surface=None):
        """A ramp: the box [mn, mx] cut by a plane; `rise` names the HIGH side (+x, -x, +z, -z)."""
        x0, y0, z0 = mn; x1, y1, z1 = mx
        ax = rise[1]
        hi_pos = rise[0] == '+'
        # parametrise along the rise axis: t in [0,1] from low to high edge; height above y0 = t * (y1 - y0)
        if ax == 'z':
            lo_e, hi_e = (z0, z1) if hi_pos else (z1, z0)
            def P(a, y, c):                       # a = along-axis coordinate, c = cross coordinate (x)
                return (c, y, a)
            c0, c1 = x0, x1
        else:
            lo_e, hi_e = (x0, x1) if hi_pos else (x1, x0)
            def P(a, y, c):
                return (a, y, c)
            c0, c1 = z0, z1
        g = self.group(tex)
        run = abs(hi_e - lo_e); rise_h = y1 - y0
        slope_n = np.array([0.0, run, -rise_h if hi_pos else -rise_h])
        # top (slanted) quad normal: points up and away from the high side
        def unit(v):
            v = np.asarray(v, dtype=float); return v / np.linalg.norm(v)
        if ax == 'z':
            n_top = unit((0, run, -rise_h if hi_pos else rise_h))
        else:
            n_top = unit((-rise_h if hi_pos else rise_h, run, 0))
        top = [P(lo_e, y0, c0), P(lo_e, y0, c1), P(hi_e, y1, c1), P(hi_e, y1, c0)]
        g.quad(top, n_top, [(p[0] * uv, p[2] * uv) for p in top])
        # high end wall (vertical, at hi_e)
        hw = [P(hi_e, y0, c0), P(hi_e, y1, c0), P(hi_e, y1, c1), P(hi_e, y0, c1)]
        n_hi = (0, 0, 1 if hi_pos else -1) if ax == 'z' else (1 if hi_pos else -1, 0, 0)
        g.quad(hw, n_hi, [((p[0] if ax == 'z' else p[2]) * uv, -p[1] * uv) for p in hw])
        # bottom
        bt = [P(lo_e, y0, c0), P(hi_e, y0, c0), P(hi_e, y0, c1), P(lo_e, y0, c1)]
        g.quad(bt, (0, -1, 0), [(p[0] * uv, p[2] * uv) for p in bt])
        # two triangular sides (cross = c0 side and c1 side)
        for c, sgn in ((c0, -1), (c1, 1)):
            tri = [P(lo_e, y0, c), P(hi_e, y0, c), P(hi_e, y1, c)]
            n = (sgn, 0, 0) if ax == 'z' else (0, 0, sgn)
            g.tri(tri, [n] * 3, [((p[2] if ax == 'z' else p[0]) * uv, -p[1] * uv) for p in tri])
        if collide:
            pts = [P(lo_e, y0, c0), P(lo_e, y0, c1), P(hi_e, y0, c0), P(hi_e, y0, c1), P(hi_e, y1, c0), P(hi_e, y1, c1)]
            self.hulls.append((pts, surf_word(surface), mat_index(material)))

    def add_rock(self, center, radius, tex, uv=0.2, squash=0.7, seed=1, collide=True, material='Stone', surface=None):
        """A faceted boulder: a subdivided icosahedron pushed around by noise (convex enough: collision = convex hull)."""
        rng = np.random.default_rng(seed)
        t = (1 + 5 ** 0.5) / 2
        V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1),
             (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
        F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
             (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]
        V = [np.array(v, dtype=float) / np.linalg.norm(v) for v in V]
        k = {}
        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in k:
                m = V[a] + V[b]
                V.append(m / np.linalg.norm(m)); k[key] = len(V) - 1
            return k[key]
        F2 = []
        for a, b, c in F:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            F2 += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        V = np.array(V)
        bump = 0.80 + 0.30 * rng.random(len(V))
        V = V * bump[:, None]
        V = V * np.array([1.0, squash, 1.0]) * radius
        cen = np.array(center, dtype=float)
        V = V + cen
        g = self.group(tex)
        # flat shaded
        for a, b, c in F2:
            A, B, C = V[a], V[b], V[c]
            n = np.cross(B - A, C - A)
            n = n / (np.linalg.norm(n) + 1e-12)
            if np.dot(n, (A + B + C) / 3 - cen) < 0:
                n = -n
            uvs = [((p[0] + p[2]) * uv, (p[1] + p[0] * 0.5) * uv) for p in (A, B, C)]
            g.tri([A, B, C], [n, n, n], uvs)
        if collide:
            pts = [tuple(p) for p in V]
            self.hulls.append((pts, surf_word(surface), mat_index(material)))

    def add_heightfield(self, xs, zs, heights, tex, steep_tex=None, steep=1.2, uv=0.125, collide=None, material='Dirt',
                        surface=None):
        xs, zs = list(xs), list(zs)
        H = np.asarray(heights, dtype=float)
        if H.shape != (len(zs), len(xs)):
            raise ValueError('heights must be len(zs) x len(xs)')
        # smooth vertex normals from the height field
        N = np.zeros(H.shape + (3,))
        for j in range(len(zs)):
            for i in range(len(xs)):
                i0, i1 = max(i - 1, 0), min(i + 1, len(xs) - 1)
                j0, j1 = max(j - 1, 0), min(j + 1, len(zs) - 1)
                dhdx = (H[j, i1] - H[j, i0]) / (xs[i1] - xs[i0])
                dhdz = (H[j1, i] - H[j0, i]) / (zs[j1] - zs[j0])
                n = np.array([-dhdx, 1.0, -dhdz])
                N[j, i] = n / np.linalg.norm(n)
        for j in range(len(zs) - 1):
            for i in range(len(xs) - 1):
                cx = [H[j, i], H[j, i + 1], H[j + 1, i + 1], H[j + 1, i]]
                dx, dz = xs[i + 1] - xs[i], zs[j + 1] - zs[j]
                sl = max(abs(cx[1] - cx[0]) / dx, abs(cx[2] - cx[3]) / dx, abs(cx[3] - cx[0]) / dz, abs(cx[2] - cx[1]) / dz)
                g = self.group(steep_tex if (steep_tex and sl > steep) else tex)
                q = [(xs[i], H[j, i], zs[j]), (xs[i + 1], H[j, i + 1], zs[j]), (xs[i + 1], H[j + 1, i + 1], zs[j + 1]),
                     (xs[i], H[j + 1, i], zs[j + 1])]
                nn = [N[j, i], N[j, i + 1], N[j + 1, i + 1], N[j + 1, i]]
                if steep_tex and sl > steep:
                    uvs = [((p[0] + p[2]) * uv, p[1] * uv * 0.6) for p in q]
                else:
                    uvs = [(p[0] * uv, p[2] * uv) for p in q]
                b = len(g.P)
                for p, n, t in zip(q, nn, uvs):
                    g.P.append(tuple(float(c) for c in p)); g.N.append(tuple(float(c) for c in n)); g.T.append(t)
                # split along the shorter diagonal
                d1 = abs(q[0][1] - q[2][1]); d2 = abs(q[1][1] - q[3][1])
                if d1 <= d2:
                    g.tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
                else:
                    g.tris += [(b, b + 1, b + 3), (b + 1, b + 2, b + 3)]
        if collide:
            self._heightfield_collision(xs, zs, H, collide, material, surface)

    def _heightfield_collision(self, xs, zs, H, c, material, surface):
        x0, z0, x1, z1 = c.get('box', [xs[0], zs[0], xs[-1], zs[-1]])
        th = float(c.get('thickness', 1.5))
        sw, mi = surf_word(surface), mat_index(material)
        cells = {}
        for j in range(len(zs) - 1):
            for i in range(len(xs) - 1):
                if xs[i] < x0 - 1e-6 or xs[i + 1] > x1 + 1e-6 or zs[j] < z0 - 1e-6 or zs[j + 1] > z1 + 1e-6:
                    continue
                cx = [H[j, i], H[j, i + 1], H[j + 1, i + 1], H[j + 1, i]]
                cells[(i, j)] = cx
        done = set()
        # flat cells (all four heights equal): merge rows into rectangles, then rectangles of equal x-extent downwards
        flat = {k: v[0] for k, v in cells.items() if max(v) - min(v) < 1e-9}
        runs = []
        for (i, j) in sorted(flat, key=lambda k: (k[1], k[0])):
            if (i, j) in done:
                continue
            h = flat[(i, j)]
            ie = i
            while (ie + 1, j) in flat and (ie + 1, j) not in done and abs(flat[(ie + 1, j)] - h) < 1e-9:
                ie += 1
            je = j
            while all((k, je + 1) in flat and (k, je + 1) not in done and abs(flat[(k, je + 1)] - h) < 1e-9
                      for k in range(i, ie + 1)):
                je += 1
            for jj in range(j, je + 1):
                for ii in range(i, ie + 1):
                    done.add((ii, jj))
            runs.append((xs[i], zs[j], xs[ie + 1], zs[je + 1], h))
        for (a0, b0, a1, b1, h) in runs:
            pts = [(x, y, z) for x in (a0, a1) for y in (h, h - th) for z in (b0, b1)]
            self.hulls.append((pts, sw, mi))
        for (i, j), cx in cells.items():
            if (i, j) in done:
                continue
            q = [(xs[i], cx[0], zs[j]), (xs[i + 1], cx[1], zs[j]), (xs[i + 1], cx[2], zs[j + 1]), (xs[i], cx[3], zs[j + 1])]
            d1 = abs(q[0][1] - q[2][1]); d2 = abs(q[1][1] - q[3][1])
            tris = [(0, 1, 2), (0, 2, 3)] if d1 <= d2 else [(0, 1, 3), (1, 2, 3)]
            for t in tris:
                top = [q[k] for k in t]
                pts = top + [(p[0], p[1] - th, p[2]) for p in top]
                self.hulls.append((pts, sw, mi))

    # ------------------------------------------------------------------ output
    def textures(self):
        return list(self.groups)


def hull_of(mw, pts):
    """Convex hull (verts, triangle faces): model_writer's gift wrapping for small sets, the collision generator's
    quickhull (todct.geom) for larger ones. One code path, so TOD Mod Studio's exe (no scipy) writes the same bytes."""
    if len(pts) <= 24:
        return mw.convex_hull(pts)
    from todct import geom as _G
    V, F = _G.convex_hull(np.asarray(pts, dtype=float))
    return [tuple(float(c) for c in v) for v in V], [[int(i) for i in f] for f in F]


def build_spec(mb, mw, tex_names, flags=None):
    """model_writer spec for a ModelBuilder. tex_names: texture name -> full engine texture name (/data/...bmp)."""
    texs = mb.textures()
    meshes = []
    for ti, t in enumerate(texs):
        g = mb.groups[t]
        if len(g.P) > 60000:
            raise ValueError('%s: submesh %s has %d vertices (limit 65,536)' % (mb.name, t, len(g.P)))
        m = mw.mesh_from_triangles(g.P, g.N, g.T, g.tris, texrefs=[ti], smb_flags=0xBA1BC000, mb_flags=0xBAADE000)
        meshes.append(m)
    shapes = []
    for k, (pts, sw, mi) in enumerate(mb.hulls):
        V, F = hull_of(mw, pts)
        shapes.append(mw.hull_shape(V, F, pivot=0, surf=sw, facemat=mi, aux_name=mb.name.split('/')[-1] + '.model'))
    spec = dict(name=mb.name, textures=[tex_names[t] for t in texs],
                pivots=[dict(name=None, name2=None, pos=(0.0, 0.0, 0.0), quat=(0.0, 0.0, 0.0, 1.0), parent=-1, w5c=-1,
                             w60=1, box=None, meshes=meshes, collision=None, v34=[], v48=[])],
                hulls=shapes if shapes else None, x40=None, sphere=None, cover_collision=True)
    return spec
