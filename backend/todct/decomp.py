"""Convex decomposition of a triangle mesh into TOD collision pieces (VertexCloud shapes: convex, <= 255 vertices).

Methods (all deterministic: the same mesh gives the same pieces every time):
  'solid'    approximate convex decomposition of a closed mesh (VHACD-like, written here): the mesh is voxelised
             (ray parity fill), the voxel set is split recursively by axis planes of the mesh's own frame, each time
             at the plane that minimises the summed hull volume of the two halves, until every part is convex within
             `concavity` (wasted hull volume / hull volume) or `max_pieces` is reached. Each final part becomes the
             exact convex hull of the mesh clipped to the part's box. Good for walls with openings, steps, ruins.
  'surface'  the shipped exporter's way (docs/subsystem_collision.md 3.3): triangles grouped into flat (within
             `angle_deg`) convex patches, each patch one flat shape. Exact for any mesh, also open ones (terrain,
             ramps without a bottom). Used automatically when 'solid' finds the mesh is not closed.
  'hull'     the convex hull of the whole mesh as one piece (crates, rocks, anything convex).
Every piece goes through geom.capped_hull (<= 255 vertices, <= 4095 index entries).
"""
import math

import numpy as np

from . import geom

CUT_GAP = 1e-4          # m between neighbouring solid parts
DEFAULTS = dict(method='solid', concavity=0.04, max_pieces=24, resolution=40, angle_deg=2.0, thickness=0.0,
                min_part_voxels=2)


class DecompError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- mesh checks
def closed_mesh(V, F):
    """Every edge used exactly twice (with opposite directions in a consistently wound mesh, but either is accepted)."""
    from collections import Counter
    c = Counter()
    for t in F:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            c[(min(a, b), max(a, b))] += 1
    return len(c) > 0 and all(v == 2 for v in c.values())


def weld(V, F, tol=1e-5):
    """Merge coincident vertices (glTF splits them per normal/uv) so edges can be matched."""
    V = np.asarray(V, dtype=np.float64)
    key = np.round(V / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    F2 = [[int(inv[i]) for i in t] for t in F]
    F2 = [t for t in F2 if len(set(t)) == 3]
    return V[first], F2


# ---------------------------------------------------------------------------------------------- voxels
def voxelize(V, F, res):
    """Solid occupancy grid by ray parity along +Z through voxel column centres. Returns (occ bool [nx,ny,nz],
    origin, size, ok) with ok False when the parity test sees an open mesh."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    mn, mx = V.min(0), V.max(0)
    ext = mx - mn
    h = float(max(ext.max() / res, 1e-3))
    n = np.maximum(1, np.ceil(ext / h - 1e-9).astype(int))
    origin = mn
    occ = np.zeros(tuple(n), dtype=bool)
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    bad = 0
    total = 0
    xs = origin[0] + (np.arange(n[0]) + 0.5) * h
    ys = origin[1] + (np.arange(n[1]) + 0.5) * h
    # tiny deterministic offset avoids rays through shared edges / vertices
    xs = xs + h * 1.234e-4
    ys = ys + h * 2.345e-4
    tri_minx = np.minimum(np.minimum(A[:, 0], B[:, 0]), C[:, 0]); tri_maxx = np.maximum(np.maximum(A[:, 0], B[:, 0]), C[:, 0])
    tri_miny = np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1]); tri_maxy = np.maximum(np.maximum(A[:, 1], B[:, 1]), C[:, 1])
    zc = origin[2] + (np.arange(n[2]) + 0.5) * h
    for i, x in enumerate(xs):
        selx = (tri_minx <= x) & (tri_maxx >= x)
        if not selx.any():
            continue
        Ai, Bi, Ci = A[selx], B[selx], C[selx]
        miny, maxy = tri_miny[selx], tri_maxy[selx]
        for j, y in enumerate(ys):
            s = (miny <= y) & (maxy >= y)
            if not s.any():
                continue
            a, b, c = Ai[s], Bi[s], Ci[s]
            # barycentric in XY
            v0 = b[:, :2] - a[:, :2]; v1 = c[:, :2] - a[:, :2]; v2 = np.array([x, y]) - a[:, :2]
            den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
            ok = np.abs(den) > 1e-14
            if not ok.any():
                continue
            den = np.where(ok, den, 1.0)
            u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
            w = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
            hit = ok & (u >= 0) & (w >= 0) & (u + w <= 1)
            if not hit.any():
                continue
            z = (a[hit, 2] + u[hit] * (b[hit, 2] - a[hit, 2]) + w[hit] * (c[hit, 2] - a[hit, 2]))
            z = np.sort(z)
            total += 1
            if len(z) % 2:
                bad += 1
                z = z[:-1]
            for k in range(0, len(z), 2):
                occ[i, j, (zc >= z[k]) & (zc <= z[k + 1])] = True
    ok = total > 0 and bad <= max(1, total // 50) and occ.any()
    return occ, origin, h, ok


def _region_index(lo, hi, origin, h, shape):
    """Voxel index ranges whose centres lie in [lo, hi)."""
    i0 = np.clip(np.ceil((np.asarray(lo) - origin) / h - 0.5 - 1e-9), 0, shape).astype(int)
    i1 = np.clip(np.ceil((np.asarray(hi) - origin) / h - 0.5 - 1e-9), 0, shape).astype(int)
    return i0, i1


def _measure(occ, lo, hi, origin, h):
    """Waste of a region measured on the voxel grid: grid centres inside the hull of the region's occupied centres
    minus the occupied ones (0 for any convex solid, whatever its orientation to the grid)."""
    i0, i1 = _region_index(lo, hi, origin, h, np.array(occ.shape))
    sub = occ[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
    n = int(sub.sum())
    if n < 4:
        return dict(lo=lo, hi=hi, n=n, inside=n, waste=0, conc=0.0)
    idx = np.argwhere(sub)
    C = origin + (idx + i0 + 0.5) * h
    Q = geom.extreme_points(C, 64)
    try:
        V, tris = geom.convex_hull(Q)
    except geom.HullError:
        return dict(lo=lo, hi=hi, n=n, inside=n, waste=0, conc=0.0)
    if len(tris) < 4:
        return dict(lo=lo, hi=hi, n=n, inside=n, waste=0, conc=0.0)
    gi = np.stack(np.meshgrid(*[np.arange(a, b) for a, b in zip(i0, i1)], indexing='ij'), -1).reshape(-1, 3)
    G = origin + (gi + 0.5) * h
    N = np.array([np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]]) for t in tris])
    N /= np.linalg.norm(N, axis=1)[:, None]
    D = np.array([N[k] @ V[t[0]] for k, t in enumerate(tris)])
    inside = int(np.sum(np.all(G @ N.T - D <= h * 1e-3, axis=1)))
    inside = max(inside, n)
    return dict(lo=lo, hi=hi, n=n, inside=inside, waste=inside - n, conc=(inside - n) / inside)


def split_voxels(occ, origin, h, V, concavity, max_pieces, min_part_voxels=2, max_cands=40):
    """Recursive splitting by axis planes. Candidate planes are the mesh's own vertex coordinates (so cuts land on
    door jambs, lintels, steps); a region is scored on the voxel grid. Returns [(lo, hi)] in metres."""
    V = np.asarray(V)
    vmin, vmax = V.min(0), V.max(0)
    coords = [np.unique(np.round(V[:, ax], 5)) for ax in range(3)]
    parts = [_measure(occ, vmin.copy(), vmax.copy(), origin, h)]
    while len(parts) < max_pieces:
        cand = [i for i, p in enumerate(parts) if p['conc'] > concavity and p['n'] >= 2 * min_part_voxels]
        if not cand:
            break
        wi = max(cand, key=lambda i: (parts[i]['waste'], -i))
        worst = parts[wi]
        best = None
        for ax in range(3):
            lo, hi = worst['lo'][ax], worst['hi'][ax]
            cs = coords[ax][(coords[ax] > lo + h * 0.5) & (coords[ax] < hi - h * 0.5)]
            if len(cs) == 0:
                k0 = int(np.ceil((lo - origin[ax]) / h)); k1 = int(np.floor((hi - origin[ax]) / h))
                cs = origin[ax] + np.arange(k0 + 1, k1) * h
            if len(cs) > max_cands:
                cs = cs[np.linspace(0, len(cs) - 1, max_cands).round().astype(int)]
            for c in cs:
                alo, ahi = worst['lo'].copy(), worst['hi'].copy(); ahi[ax] = c
                blo, bhi = worst['lo'].copy(), worst['hi'].copy(); blo[ax] = c
                ma, mb = _measure(occ, alo, ahi, origin, h), _measure(occ, blo, bhi, origin, h)
                if ma['n'] < min_part_voxels or mb['n'] < min_part_voxels:
                    continue
                key = (ma['waste'] + mb['waste'], ax, float(c))
                if best is None or key < best[0]:
                    best = (key, ma, mb)
        if best is None or best[0][0] >= worst['waste']:
            worst['conc'] = 0.0                  # no split helps: accept as is
            continue
        parts[wi:wi + 1] = [best[1], best[2]]
    return [(p['lo'], p['hi']) for p in parts if p['n'] > 0]


# ---------------------------------------------------------------------------------------------- clipping
def clip_mesh_to_box(V, F, bmin, bmax):
    """Points of the mesh surface inside the box (Sutherland-Hodgman per triangle)."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    T = V[F]                                            # (n, 3, 3)
    tmin, tmax = T.min(1), T.max(1)
    touch = np.all(tmax >= bmin - 1e-9, axis=1) & np.all(tmin <= bmax + 1e-9, axis=1)
    inside = np.all(tmin >= bmin - 1e-9, axis=1) & np.all(tmax <= bmax + 1e-9, axis=1)
    pts = [T[inside].reshape(-1, 3)]
    for tri in T[touch & ~inside]:
        poly = [tuple(p) for p in tri]
        for ax in range(3):
            for sgn, lim in ((1, bmin[ax]), (-1, bmax[ax])):
                if not poly:
                    break
                out = []
                for k in range(len(poly)):
                    p, q = poly[k - 1], poly[k]
                    dp, dq = sgn * (p[ax] - lim), sgn * (q[ax] - lim)
                    if dq >= 0:
                        if dp < 0:
                            t = dp / (dp - dq)
                            out.append(tuple(p[i] + t * (q[i] - p[i]) for i in range(3)))
                        out.append(q)
                    elif dp >= 0:
                        t = dp / (dp - dq)
                        out.append(tuple(p[i] + t * (q[i] - p[i]) for i in range(3)))
                poly = out
        if poly:
            pts.append(np.array(poly))
    P = np.concatenate([p for p in pts if len(p)]) if any(len(p) for p in pts) else np.empty((0, 3))
    return P


# ---------------------------------------------------------------------------------------------- surface patches
def surface_patches(V, F, angle_deg=2.0, max_verts=255):
    """Greedy region growing over shared edges: a triangle joins a patch when its normal is within angle_deg of the
    patch normal, the patch stays convex (2D hull area = summed triangle area) and <= max_verts vertices."""
    V = np.asarray(V, dtype=np.float64)
    F = [list(t) for t in F]
    N, area = [], []
    for t in F:
        n = np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]])
        a = np.linalg.norm(n)
        N.append(n / a if a else n)
        area.append(a / 2)
    edges = {}
    for i, t in enumerate(F):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edges.setdefault((min(a, b), max(a, b)), []).append(i)
    nbr = [[] for _ in F]
    for tl in edges.values():
        for i in tl:
            nbr[i] += [j for j in tl if j != i]
    cos_tol = math.cos(math.radians(angle_deg))
    done = [False] * len(F)
    patches = []
    order = sorted(range(len(F)), key=lambda i: -area[i])
    for seed in order:
        if done[seed] or area[seed] <= 0:
            done[seed] = True
            continue
        P = [seed]
        done[seed] = True
        n0 = N[seed]
        verts = set(F[seed])
        parea = area[seed]
        front = list(nbr[seed])
        while front:
            j = front.pop(0)
            if done[j] or area[j] <= 0 or float(N[j] @ n0) < cos_tol:
                continue
            nv = verts | set(F[j])
            if len(nv) > max_verts:
                continue
            pts = V[sorted(nv)]
            u, v = geom.plane_basis(n0)
            Q = [(p @ u, p @ v) for p in pts]
            hidx = geom.hull2d(Q)
            ha = 0.0
            for k in range(len(hidx)):
                x1, y1 = Q[hidx[k - 1]]; x2, y2 = Q[hidx[k]]
                ha += x1 * y2 - x2 * y1
            ha = abs(ha) / 2
            proj = parea + area[j] * abs(float(N[j] @ n0))
            if ha > proj * 1.002 + 1e-9:
                continue
            P.append(j)
            done[j] = True
            verts = nv
            parea += area[j] * abs(float(N[j] @ n0))
            front += [x for x in nbr[j] if not done[x]]
        patches.append((P, n0))
    return patches


# ---------------------------------------------------------------------------------------------- front door
def components(V, F):
    """Connected parts of a welded mesh (triangles sharing a vertex) -> [(V_part, F_part)], biggest first."""
    parent = list(range(len(V)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for t in F:
        r = find(t[0])
        for x in t[1:]:
            q = find(x)
            if q != r:
                parent[q] = r
    groups = {}
    for t in F:
        groups.setdefault(find(t[0]), []).append(t)
    out = []
    for tris in groups.values():
        ids = sorted({i for t in tris for i in t})
        remap = {o: k for k, o in enumerate(ids)}
        out.append((np.asarray(V)[ids], [[remap[i] for i in t] for t in tris]))
    out.sort(key=lambda c: (-len(c[1]), c[0].min(0).tolist()))
    return out


def decompose(V, F, method='solid', concavity=0.04, max_pieces=24, resolution=40, angle_deg=2.0, thickness=0.0,
              min_part_voxels=2, max_verts=255, log=None):
    """V (n,3), F triangles, in the frame where axis splits make sense (the mesh's own frame, scaled to metres).
    Disconnected parts (a wall and a ramp in one file) are decomposed one by one.
    Returns a list of pieces: dict(verts (m,3) ndarray, faces [polygons], info)."""
    log = log if log is not None else []
    V, F = weld(V, F)
    if len(F) == 0:
        raise DecompError('the mesh has no triangles')
    comps = components(V, F)
    if len(comps) > 1:
        log.append('%d separate parts' % len(comps))
        out = []
        for Vc, Fc in comps:
            out += _decompose_one(Vc, Fc, method, concavity, max_pieces, resolution, angle_deg, thickness,
                                  min_part_voxels, max_verts, log)
        return out
    return _decompose_one(V, F, method, concavity, max_pieces, resolution, angle_deg, thickness, min_part_voxels,
                          max_verts, log)


def _decompose_one(V, F, method, concavity, max_pieces, resolution, angle_deg, thickness, min_part_voxels, max_verts, log):
    pieces = []
    if method == 'hull':
        Vh, polys, info = geom.capped_hull(V, max_verts)
        return [dict(verts=Vh, faces=polys, info=info)]
    if method == 'solid':
        if not closed_mesh(V, F):
            log.append('solid: the mesh is not closed (open edges), using surface patches instead')
            method = 'surface'
        else:
            occ, origin, h, ok = voxelize(V, F, resolution)
            if not ok:
                log.append('solid: voxel fill failed (open or self-intersecting mesh), using surface patches instead')
                method = 'surface'
            else:
                regions = split_voxels(occ, origin, h, V, concavity, max_pieces, min_part_voxels)
                log.append('solid: %d voxels of %.3f m, %d parts' % (int(occ.sum()), h, len(regions)))
                vmin, vmax = V.min(0), V.max(0)
                for lo, hi in regions:
                    # exterior faces reach past the mesh; cut faces move in by CUT_GAP so geometry lying ON a cut
                    # plane (a door jamb under a lintel) is not pulled into the neighbouring part
                    lo = np.where(lo <= vmin + 1e-9, vmin - 1e-6, lo + CUT_GAP)
                    hi = np.where(hi >= vmax - 1e-9, vmax + 1e-6, hi - CUT_GAP)
                    P = clip_mesh_to_box(V, F, lo, hi)
                    if len(P) < 4:
                        continue
                    try:
                        Vh, polys, info = geom.capped_hull(P, max_verts)
                    except geom.HullError:
                        continue
                    info['box'] = [lo.tolist(), hi.tolist()]
                    pieces.append(dict(verts=Vh, faces=polys, info=info))
                return pieces
    if method == 'surface':
        for tris, n in surface_patches(V, F, angle_deg, max_verts):
            ids = sorted({i for t in tris for i in F[t]})
            P = V[ids]
            if thickness > 0:
                P = np.concatenate([P, P - n * thickness])
                Vh, polys, info = geom.capped_hull(P, max_verts)
            else:
                try:
                    Vh, polys = geom.flat_hull(P, normal=n)
                except geom.HullError:
                    continue
                info = dict(input_points=len(P), hull_verts=len(Vh), reduced=False, verts=len(Vh), faces=1,
                            entries=len(Vh) + 1, flat=True)
                if len(Vh) > max_verts:
                    Vh, polys, info = geom.capped_hull(np.concatenate([P, P - n * 0.01]), max_verts)
            info['triangles'] = len(tris)
            pieces.append(dict(verts=Vh, faces=polys, info=info))
        log.append('surface: %d triangles -> %d flat convex patches' % (len(F), len(pieces)))
        return pieces
    raise DecompError('unknown method %r' % method)


def pieces_from_point_sets(sets, max_verts=255):
    """One capped convex hull per point set (points already in world space)."""
    out = []
    for P in sets:
        P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
        if len(P) < 3:
            continue
        Vh, polys, info = geom.capped_hull(P, max_verts)
        out.append(dict(verts=Vh, faces=polys, info=info))
    return out
