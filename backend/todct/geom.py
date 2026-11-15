"""Geometry for the collision generator: 3D convex hull (quickhull), hull simplification to the VertexCloud limits,
coplanar face merging, transforms. numpy only (the packaged Mod Studio has no scipy).

Conventions: points are (n, 3) float64 arrays; a hull is (verts (m, 3), faces [list of vertex index lists]) with
faces wound so that cross(v1 - v0, v2 - v0) points OUT of the solid (the collision format's convention,
docs/subsystem_collision.md 3.3). A flat point set gives one polygon face (a "flat" hull, like the shipped single
triangles and coplanar patches).
"""
import math

import numpy as np

EPS_REL = 1e-9


class HullError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- small helpers
def unique_points(P, tol=1e-6):
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    if len(P) == 0:
        return P
    key = np.round(P / tol).astype(np.int64)
    _, idx = np.unique(key, axis=0, return_index=True)
    return P[np.sort(idx)]


def _scale_eps(P):
    ext = float(np.max(np.ptp(P, axis=0))) if len(P) else 1.0
    return max(ext, 1e-3) * 1e-7


def plane_of(points):
    """Best-fit plane (centroid, unit normal) and the largest distance of a point from it."""
    P = np.asarray(points, dtype=np.float64)
    c = P.mean(axis=0)
    _, s, vt = np.linalg.svd(P - c, full_matrices=False)
    n = vt[-1]
    return c, n / (np.linalg.norm(n) or 1.0), float(np.max(np.abs((P - c) @ n))) if len(P) else 0.0


def hull2d(Q):
    """Andrew's monotone chain; Q (n, 2) -> indices of the hull in counter-clockwise order."""
    order = sorted(range(len(Q)), key=lambda i: (Q[i][0], Q[i][1]))
    if len(order) <= 2:
        return order

    def cross(o, a, b):
        return (Q[a][0] - Q[o][0]) * (Q[b][1] - Q[o][1]) - (Q[a][1] - Q[o][1]) * (Q[b][0] - Q[o][0])
    lo, hi = [], []
    for i in order:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], i) <= 0:
            lo.pop()
        lo.append(i)
    for i in reversed(order):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], i) <= 0:
            hi.pop()
        hi.append(i)
    return lo[:-1] + hi[:-1]


def plane_basis(n):
    n = np.asarray(n, dtype=np.float64)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def flat_hull(P, normal=None):
    """Convex polygon of an (almost) coplanar point set -> (verts, [polygon]) with the polygon's normal along
    `normal` when given (else the fitted plane normal)."""
    c, n, _ = plane_of(P)
    if normal is not None and np.dot(n, normal) < 0:
        n = -n
    u, v = plane_basis(n)
    Q = [((p - c) @ u, (p - c) @ v) for p in P]
    idx = hull2d(Q)
    if len(idx) < 3:
        raise HullError('degenerate (collinear) point set')
    V = P[idx]
    poly = list(range(len(idx)))                       # counter-clockwise about n => normal along n
    a, b, cc = V[0], V[1], V[2]
    if np.dot(np.cross(b - a, cc - a), n) < 0:
        poly.reverse()
    return V, [poly]


# ---------------------------------------------------------------------------------------------- quickhull
def convex_hull(points, tol=None):
    """3D convex hull. Returns (verts (m, 3), triangles [[i, j, k], ...]) outward wound. Flat input -> one polygon."""
    P = unique_points(points)
    if len(P) < 3:
        raise HullError('need at least 3 distinct points (got %d)' % len(P))
    eps = tol if tol is not None else _scale_eps(P)
    c, n, dev = plane_of(P)
    ext = float(np.max(np.ptp(P, axis=0)))
    if dev <= max(eps * 10, ext * 1e-6) or len(P) == 3:
        return flat_hull(P)
    # initial simplex
    i0 = int(np.argmin(P[:, 0])); i1 = int(np.argmax(P[:, 0]))
    if i0 == i1:
        i1 = int(np.argmax(np.linalg.norm(P - P[i0], axis=1)))
    d = P[i1] - P[i0]
    d /= np.linalg.norm(d)
    w = P - P[i0]
    dl = np.linalg.norm(w - np.outer(w @ d, d), axis=1)
    i2 = int(np.argmax(dl))
    nrm = np.cross(P[i1] - P[i0], P[i2] - P[i0])
    nrm /= np.linalg.norm(nrm)
    dp = (P - P[i0]) @ nrm
    i3 = int(np.argmax(np.abs(dp)))
    if abs(dp[i3]) <= eps:
        return flat_hull(P)
    simplex = [i0, i1, i2, i3]
    centre = P[simplex].mean(axis=0)

    faces = {}          # fid -> dict(v=(a,b,c), n, d, out=np.array of point idx)
    emap = {}           # directed edge (a, b) -> fid of the face that has it
    next_id = [0]

    def make_face(a, b, cc):
        nn = np.cross(P[b] - P[a], P[cc] - P[a])
        ln = np.linalg.norm(nn)
        nn = nn / ln if ln else np.zeros(3)
        dd = float(nn @ P[a])
        if nn @ centre - dd > 0:                       # must face away from the interior point
            b, cc = cc, b
            nn, dd = -nn, -dd
        fid = next_id[0]
        next_id[0] += 1
        faces[fid] = dict(v=(a, b, cc), n=nn, d=dd, out=np.empty(0, dtype=np.int64))
        for e in ((a, b), (b, cc), (cc, a)):
            emap[e] = fid
        return fid

    def drop_face(fid):
        a, b, cc = faces[fid]['v']
        for e in ((a, b), (b, cc), (cc, a)):
            if emap.get(e) == fid:
                del emap[e]
        del faces[fid]

    for tri in ((i0, i1, i2), (i0, i1, i3), (i0, i2, i3), (i1, i2, i3)):
        make_face(*tri)
    rest = np.array([i for i in range(len(P)) if i not in simplex], dtype=np.int64)

    def assign(cands, fids):
        if len(cands) == 0:
            return
        remaining = cands
        for fid in fids:
            f = faces[fid]
            dist = P[remaining] @ f['n'] - f['d']
            m = dist > eps
            f['out'] = remaining[m]
            remaining = remaining[~m]
            if len(remaining) == 0:
                break

    assign(rest, list(faces.keys()))
    pending = [k for k, f in faces.items() if len(f['out'])]
    guard = 0
    while pending:
        guard += 1
        if guard > 200000:
            raise HullError('quickhull did not converge')
        fid = pending.pop()
        if fid not in faces or not len(faces[fid]['out']):
            continue
        f = faces[fid]
        dist = P[f['out']] @ f['n'] - f['d']
        p = int(f['out'][int(np.argmax(dist))])
        pp = P[p]
        # visible faces: flood from fid across shared edges
        visible, stack, seen = [], [fid], {fid}
        while stack:
            k = stack.pop()
            g = faces[k]
            if k != fid and pp @ g['n'] - g['d'] <= eps:
                continue
            visible.append(k)
            a, b, cc = g['v']
            for e in ((b, a), (cc, b), (a, cc)):
                nb = emap.get(e)
                if nb is not None and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        vis = set(visible)
        horizon = []
        for k in visible:
            a, b, cc = faces[k]['v']
            for e in ((a, b), (b, cc), (cc, a)):
                if emap.get((e[1], e[0])) not in vis:
                    horizon.append(e)
        pts = np.unique(np.concatenate([faces[k]['out'] for k in visible]))
        pts = pts[pts != p]
        for k in visible:
            drop_face(k)
        new = [make_face(a, b, p) for a, b in horizon]
        assign(pts, new)
        pending += [k for k in new if len(faces[k]['out'])]
    used = sorted({i for f in faces.values() for i in f['v']})
    remap = {o: k for k, o in enumerate(used)}
    V = P[used]
    tris = [[remap[i] for i in f['v']] for f in faces.values()]
    return V, tris


def merge_coplanar(V, tris, cos_tol=1.0 - 1e-9, dist_tol=None):
    """Merge coplanar triangles of a convex hull into convex polygons (vertex order around the face, outward)."""
    V = np.asarray(V)
    if len(tris) == 1 and len(tris[0]) > 3:
        return [list(tris[0])]
    dist_tol = dist_tol if dist_tol is not None else _scale_eps(V) * 100
    groups = []
    for t in tris:
        a, b, c = V[t[0]], V[t[1]], V[t[2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        n = n / ln if ln else n
        d = float(n @ a)
        for g in groups:
            if g['n'] @ n >= cos_tol and abs(g['d'] - d) <= dist_tol:
                g['t'].append(t)
                break
        else:
            groups.append(dict(n=n, d=d, t=[t]))
    polys = []
    for g in groups:
        ids = sorted({i for t in g['t'] for i in t})
        if len(ids) == 3:
            polys.append(list(g['t'][0]))
            continue
        P = V[ids]
        c = P.mean(axis=0)
        u, v = plane_basis(g['n'])
        ang = [math.atan2((p - c) @ v, (p - c) @ u) for p in P]
        order = [ids[i] for i in sorted(range(len(ids)), key=lambda i: ang[i])]
        # drop vertices that are collinear inside an edge (keep it a strict polygon)
        poly = []
        for k in range(len(order)):
            a, b, cc = V[order[k - 1]], V[order[k]], V[order[(k + 1) % len(order)]]
            if np.linalg.norm(np.cross(b - a, cc - b)) > dist_tol * 0.01:
                poly.append(order[k])
        if len(poly) < 3:
            poly = order
        a, b, cc = V[poly[0]], V[poly[1]], V[poly[2]]
        if np.cross(b - a, cc - a) @ g['n'] < 0:
            poly.reverse()
        polys.append(poly)
    return polys


def hull_volume(V, faces):
    """Volume of a closed convex polyhedron (0 for a flat one)."""
    V = np.asarray(V)
    if len(faces) < 4:
        return 0.0
    c = V.mean(axis=0)
    vol = 0.0
    for f in faces:
        for k in range(1, len(f) - 1):
            a, b, d = V[f[0]] - c, V[f[k]] - c, V[f[k + 1]] - c
            vol += abs(np.dot(a, np.cross(b, d))) / 6.0
    return vol


def fibonacci_dirs(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)


def extreme_points(P, ndirs=64):
    """Extreme points of P along ndirs directions (+ the 6 axis directions): a small set whose hull approximates
    the hull of P from inside."""
    P = np.asarray(P, dtype=np.float64)
    D = np.concatenate([fibonacci_dirs(ndirs), np.eye(3), -np.eye(3)])
    idx = np.unique(np.argmax(P @ D.T, axis=0))
    return P[idx]


def capped_hull(points, max_verts=255, max_entries=4095):
    """Convex hull with at most max_verts vertices and an index stream of at most max_entries entries (the
    VertexCloud limits). Larger hulls are reduced to the extreme points along more and more directions (an inner
    approximation that keeps every extreme point of the shape along those directions).
    Returns (verts, polygons, info)."""
    P = unique_points(points)
    n_in = len(P)
    if n_in > 1500:                                   # pre-reduce big clouds to their extreme points (fast, inner)
        P = np.concatenate([extreme_points(P[k:k + 20000], 512) for k in range(0, len(P), 20000)])
        P = extreme_points(P, 1024)
    V, tris = convex_hull(P)
    info = dict(input_points=int(n_in), hull_verts=int(len(V)), reduced=n_in > 1500)
    nd = 2 * max_verts
    while True:
        polys = merge_coplanar(V, tris)
        entries = sum(len(p) + 1 for p in polys)
        if len(V) <= max_verts and entries <= max_entries:
            info.update(verts=int(len(V)), faces=len(polys), entries=entries)
            return V, polys, info
        info['reduced'] = True
        nd = max(8, int(nd * 0.8))
        V, tris = convex_hull(extreme_points(V, nd))


# ---------------------------------------------------------------------------------------------- transforms
def quat_to_mat(q):
    x, y, z, w = [float(c) for c in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def qrot(q, v):
    return quat_to_mat(q) @ np.asarray(v, dtype=np.float64)


def apply_trs(P, pos=(0, 0, 0), quat=(0, 0, 0, 1), scale=(1, 1, 1)):
    """world = R(quat) * (scale * p) + pos  (row-vector points)."""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3) * np.asarray(scale, dtype=np.float64)
    return P @ quat_to_mat(quat).T + np.asarray(pos, dtype=np.float64)


def inverse_trs_points(P, pos, quat):
    """Points from world into the frame (pos, quat) (no scale): R^T (p - pos)."""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3) - np.asarray(pos, dtype=np.float64)
    return P @ quat_to_mat(quat)


def is_convex_hull_of(V, faces, P, tol=1e-4):
    """True when every point of P lies inside (or on) the convex polyhedron (V, faces) within tol metres."""
    V = np.asarray(V)
    P = np.asarray(P).reshape(-1, 3)
    if len(faces) < 4:
        c, n, _ = plane_of(V)
        return bool(np.all(np.abs((P - c) @ n) <= tol))
    for f in faces:
        a, b, c = V[f[0]], V[f[1]], V[f[2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln == 0:
            continue
        n /= ln
        if np.max((P - a) @ n) > tol:
            return False
    return True
