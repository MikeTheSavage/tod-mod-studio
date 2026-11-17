"""Numpy steps of the large-scene import: region cut, clean-up, atlas packing, chunk planning and collision pieces.

Everything here is deterministic (sorted keys, stable orders, no clock, no random numbers) and works on plain arrays:

  Soup        triangles of the cut region: positions, normals, texture coordinates, one material class per vertex, triangle indices
  select      the triangles of a polygon (centroid test; `whole` keeps every triangle of any primitive the polygon touches)
  clean       degenerate, exact and near duplicate triangles, stray islands, vertex weld; returns what it removed
  Atlas       power-of-two squares packed into pages (buddy blocks), with the uv remap of each tile
  plan_cells  the spatial split of a section into objects that respect vertex, byte and texture budgets
  collision   convex slabs of the visible geometry (one thin hull per near-flat patch), within a piece budget

Game axes are produced by the caller (`todct.modelimport.axis_matrix`); nothing in this module knows about glTF.
"""
import hashlib

import numpy as np

try:                                                    # cpu_guard can keep numpy work off chosen CPU cores
    import sys as _sys
    _p = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))), 'vendor', 'newmap')
    if _p not in _sys.path:
        _sys.path.append(_p)
    import cpu_guard                                    # noqa: F401
except Exception:                                       # noqa: BLE001
    pass

KEY_BITS = 21
KEY_MAX = 1 << KEY_BITS


class Soup:
    """One region of triangles. VM = material class of each vertex (a vertex belongs to one primitive, so to one class)."""

    def __init__(self, P, N, UV, VM, T):
        self.P, self.N, self.UV, self.VM, self.T = P, N, UV, VM, T

    @property
    def tris(self):
        return int(len(self.T))

    def tri_class(self):
        return self.VM[self.T[:, 0]]

    def subset(self, keep):
        """Triangles `keep` (bool mask or index array), vertices compacted."""
        T = self.T[keep]
        used, inv = np.unique(T.reshape(-1), return_inverse=True)
        return Soup(self.P[used], self.N[used], self.UV[used], self.VM[used], inv.reshape(-1, 3).astype(np.int64))

    def digest(self):
        h = hashlib.sha1()
        for a in (self.P, self.N, self.UV, self.VM, self.T):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- geometry helpers
def point_in_polygon(xz, poly):
    """Even-odd test of (n, 2) points against a polygon (k, 2); boundary points are not decided."""
    poly = np.asarray(poly, np.float64)
    x, z = xz[:, 0], xz[:, 1]
    inside = np.zeros(len(xz), bool)
    k = len(poly)
    j = k - 1
    for i in range(k):
        xi, zi, xj, zj = poly[i, 0], poly[i, 1], poly[j, 0], poly[j, 1]
        cond = (zi > z) != (zj > z)
        with np.errstate(divide='ignore', invalid='ignore'):
            xint = (xj - xi) * (z - zi) / (zj - zi) + xi
        inside ^= cond & (x < xint)
        j = i
    return inside


def tri_normals_area(P, T):
    a, b, c = P[T[:, 0]].astype(np.float64), P[T[:, 1]].astype(np.float64), P[T[:, 2]].astype(np.float64)
    n = np.cross(b - a, c - a)
    ar = np.linalg.norm(n, axis=1)
    return n / np.maximum(ar, 1e-30)[:, None], ar * 0.5


def _quant_ids(P, tol):
    """Welded position id per vertex (0..K-1, ordered by first occurrence of the sorted key) at tolerance `tol`."""
    P = np.asarray(P, np.float64)
    lo = P.min(0)
    k = np.rint((P - lo) / tol).astype(np.int64)
    if k.max() >= KEY_MAX:
        tol = float((P.max(0) - lo).max()) / (KEY_MAX - 2)
        k = np.rint((P - lo) / tol).astype(np.int64)
    key = (k[:, 0] << (2 * KEY_BITS)) | (k[:, 1] << KEY_BITS) | k[:, 2]
    uniq, inv = np.unique(key, return_inverse=True)
    return inv.reshape(-1).astype(np.int64), len(uniq)


def _tri_keys(ids, T, extra=None):
    """One sortable key per triangle from its sorted corner ids (and an optional extra class id)."""
    c = np.sort(ids[T], axis=1)
    big = int(ids.max()) + 1 if len(ids) else 1
    if extra is None and big < KEY_MAX:
        return (c[:, 0] << (2 * KEY_BITS)) | (c[:, 1] << KEY_BITS) | c[:, 2], None
    cols = [c[:, 0], c[:, 1], c[:, 2]] + ([extra] if extra is not None else [])
    arr = np.stack(cols, 1)
    _, inv = np.unique(arr, axis=0, return_inverse=True)
    return inv.reshape(-1).astype(np.int64), None


def _keep_last(keys):
    """Mask keeping the LAST triangle of each key (a later draw covers an earlier one)."""
    rev = keys[::-1]
    _, first = np.unique(rev, return_index=True)
    keep = np.zeros(len(keys), bool)
    keep[len(keys) - 1 - first] = True
    return keep


def components(vid, T, n_ids):
    """Connected components of the triangle graph over welded vertex ids; -> component id per welded id (roots), count."""
    a, b, c = vid[T[:, 0]], vid[T[:, 1]], vid[T[:, 2]]
    ea = np.concatenate([a, b, c])
    eb = np.concatenate([b, c, a])
    ok = ea != eb
    ea, eb = ea[ok], eb[ok]
    parent = np.arange(n_ids, dtype=np.int64)
    for _ in range(64):
        pa, pb = parent[ea], parent[eb]
        m = pa != pb
        if not m.any():
            break
        lo, hi = np.minimum(pa[m], pb[m]), np.maximum(pa[m], pb[m])
        np.minimum.at(parent, hi, lo)
        while True:
            pp = parent[parent]
            if (pp == parent).all():
                break
            parent = pp
    return parent


# ---------------------------------------------------------------------------------------------- clean
CLEAN_DEFAULTS = dict(weld_mm=2.0, near_mm=40.0, drop_degenerate=True, drop_exact=True, drop_near=True, strays=True,
                      anchor_tris=200, far_m=60.0, tiny_tris=2, tiny_size_m=0.4, weld_vertices=True)


def clean(soup, params=None):
    """-> (Soup, report). report: counts of what each step removed (triangles) and the vertex weld."""
    p = dict(CLEAN_DEFAULTS)
    p.update(params or {})
    rep = dict(triangles_in=soup.tris, vertices_in=int(len(soup.P)))
    T = soup.T
    P = soup.P
    if soup.tris == 0:
        rep.update(degenerate=0, exact=0, near=0, tiny=0, far=0, triangles_out=0, vertices_out=0, vertices_welded=0, islands=0)
        return soup, rep
    fine = max(float(p['weld_mm']) / 1000.0, 1e-6)
    vid, nid = _quant_ids(P, fine)
    keep = np.ones(len(T), bool)
    # degenerate: two corners welded together, or no area
    _, area = tri_normals_area(P, T)
    deg = (vid[T[:, 0]] == vid[T[:, 1]]) | (vid[T[:, 1]] == vid[T[:, 2]]) | (vid[T[:, 0]] == vid[T[:, 2]]) | (area < 1e-9)
    rep['degenerate'] = int(deg.sum()) if p['drop_degenerate'] else 0
    if p['drop_degenerate']:
        keep &= ~deg
    # exact duplicates: the same three welded positions and the same material class
    cls = soup.tri_class().astype(np.int64)
    if p['drop_exact']:
        idx = np.nonzero(keep)[0]
        k, _ = _tri_keys(vid, T[idx], cls[idx])
        kk = _keep_last(k)
        rep['exact'] = int((~kk).sum())
        keep[idx[~kk]] = False
    else:
        rep['exact'] = 0
    # near duplicates (overlapping capture draws, any material): the same corners at a coarse tolerance
    if p['drop_near']:
        idx = np.nonzero(keep)[0]
        cvid, _ = _quant_ids(P, max(float(p['near_mm']) / 1000.0, fine))
        k, _ = _tri_keys(cvid, T[idx])
        d2 = (cvid[T[idx, 0]] == cvid[T[idx, 1]]) | (cvid[T[idx, 1]] == cvid[T[idx, 2]]) | (cvid[T[idx, 0]] == cvid[T[idx, 2]])
        kk = _keep_last(k)
        kk |= d2                                         # a triangle that collapses at the coarse tolerance is not a duplicate of anything
        rep['near'] = int((~kk).sum())
        keep[idx[~kk]] = False
    else:
        rep['near'] = 0
    soup = soup.subset(keep)
    T, P = soup.T, soup.P
    rep['tiny'] = rep['far'] = rep['islands'] = rep['tiny_islands'] = rep['far_islands'] = 0
    if p['strays'] and soup.tris:
        vid, nid = _quant_ids(P, fine)
        root = components(vid, T, nid)
        tc = root[vid[T[:, 0]]]
        comps, cinv, ctris = np.unique(tc, return_inverse=True, return_counts=True)
        cinv = cinv.reshape(-1)
        rep['islands'] = int(len(comps))
        cen = (P[T[:, 0]].astype(np.float64) + P[T[:, 1]] + P[T[:, 2]]) / 3.0
        # component boxes
        lo = np.full((len(comps), 3), np.inf)
        hi = np.full((len(comps), 3), -np.inf)
        order = np.argsort(cinv, kind='stable')
        bounds = np.concatenate([[0], np.cumsum(ctris)])
        cs = cen[order]
        for ax in range(3):
            lo[:, ax] = np.minimum.reduceat(cs[:, ax], bounds[:-1])
            hi[:, ax] = np.maximum.reduceat(cs[:, ax], bounds[:-1])
        size = np.linalg.norm(hi - lo, axis=1)
        mid = (lo + hi) / 2
        drop = np.zeros(len(comps), bool)
        tiny = (ctris <= int(p['tiny_tris'])) & (size < float(p['tiny_size_m']))
        drop |= tiny
        anchor = ctris >= int(p['anchor_tris'])
        far_drop = np.zeros(len(comps), bool)
        if anchor.any():
            cell = max(float(p['far_m']), 1.0)
            ac = cen[anchor[cinv]]
            occ = set(map(tuple, np.unique(np.floor(ac / cell).astype(np.int64), axis=0).tolist()))
            cand = np.nonzero(~anchor & ~tiny)[0]
            cc = np.floor(mid[cand] / cell).astype(np.int64)
            for i, c in zip(cand, cc):
                near = False
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            if (c[0] + dx, c[1] + dy, c[2] + dz) in occ:
                                near = True
                                break
                        if near:
                            break
                    if near:
                        break
                if not near:
                    far_drop[i] = True
        drop |= far_drop
        rep['tiny_islands'], rep['far_islands'] = int(tiny.sum()), int(far_drop.sum())
        rep['tiny'] = int(ctris[tiny].sum())
        rep['far'] = int(ctris[far_drop].sum())
        if drop.any():
            soup = soup.subset(~drop[cinv])
    # vertex weld: position, texture coordinate, normal and material class
    n0 = len(soup.P)
    if p['weld_vertices'] and soup.tris:
        soup = weld_vertices(soup, fine)
    rep.update(triangles_out=soup.tris, vertices_out=int(len(soup.P)), vertices_welded=int(n0 - len(soup.P)))
    return soup, rep


def weld_vertices(soup, tol=0.002):
    P = soup.P.astype(np.float64)
    lo = P.min(0)
    k = np.rint((P - lo) / max(tol, 1e-6)).astype(np.int64)
    if k.max() >= KEY_MAX:
        k = np.rint((P - lo) / (float((P.max(0) - lo).max()) / (KEY_MAX - 2))).astype(np.int64)
    k1 = (k[:, 0] << (2 * KEY_BITS)) | (k[:, 1] << KEY_BITS) | k[:, 2]
    uv = np.rint(soup.UV.astype(np.float64) * 1024.0).astype(np.int64) & 0xFFFFF
    q = np.rint((soup.N.astype(np.float64) + 1.0) * 31.5).astype(np.int64) & 63
    k2 = (uv[:, 0] << 40) | (uv[:, 1] << 20) | (soup.VM.astype(np.int64) & 0xFFFFF)
    k3 = (q[:, 0] << 12) | (q[:, 1] << 6) | q[:, 2]
    order = np.lexsort((k3, k2, k1))
    s1, s2, s3 = k1[order], k2[order], k3[order]
    new = np.ones(len(order), bool)
    new[1:] = (s1[1:] != s1[:-1]) | (s2[1:] != s2[:-1]) | (s3[1:] != s3[:-1])
    grp = np.cumsum(new) - 1
    first = order[new]
    remap = np.empty(len(order), np.int64)
    remap[order] = grp
    T = remap[soup.T]
    ok = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])
    return Soup(soup.P[first], soup.N[first], soup.UV[first], soup.VM[first], T[ok])


# ---------------------------------------------------------------------------------------------- texture classes
def classify_alpha(alpha, material_alpha='blend'):
    """From the alpha channel of a picture (floats 0..1): 'opaque' | 'cutout' | 'blend'.
    A material that says opaque stays opaque (a capture often carries a junk alpha channel)."""
    a = np.asarray(alpha, np.float32)
    if material_alpha == 'opaque' or a.size == 0 or float(a.min()) >= 0.98:
        return 'opaque'
    hard = ((a <= 0.04) | (a >= 0.96)).mean()
    if float((a <= 0.04).mean()) < 0.003:
        return 'opaque'
    return 'cutout' if hard >= 0.93 else 'blend'


# ---------------------------------------------------------------------------------------------- atlas
class Atlas:
    """Power-of-two square tiles in square pages (buddy blocks). add() returns (page, x, y); pages grow on demand."""

    def __init__(self, page=1024):
        self.page = page
        self.free = []                                   # per page: {size: [(x, y)]}

    def _new_page(self):
        self.free.append({self.page: [(0, 0)]})
        return len(self.free) - 1

    def add(self, size):
        if size > self.page:
            raise ValueError('a tile is larger than the page')
        for pg, fr in enumerate(self.free):
            r = self._take(fr, size)
            if r:
                return (pg,) + r
        pg = self._new_page()
        return (pg,) + self._take(self.free[pg], size)

    def _take(self, fr, size):
        s = size
        while s <= self.page and not fr.get(s):
            s *= 2
        if s > self.page:
            return None
        fr[s].sort()
        x, y = fr[s].pop(0)
        while s > size:
            s //= 2
            fr.setdefault(s, []).extend([(x + s, y), (x, y + s), (x + s, y + s)])
        return x, y


def pack_tiles(tiles, page=1024):
    """tiles: [(key, size)] (sizes powers of two). -> ({key: (page, x, y)}, pages). Largest first, then key order."""
    at = Atlas(page)
    out = {}
    for key, size in sorted(tiles, key=lambda t: (-t[1], str(t[0]))):
        out[key] = at.add(size)
    return out, len(at.free)


# ---------------------------------------------------------------------------------------------- chunk planning
def plan_cells(cx, cz, idx, stat, limits, box=None, min_cell=6.0, depth=0):
    """Split the triangles `idx` (centroids cx, cz) of one section into cells that satisfy `limits`.
    stat(idx) -> dict(verts_max, bytes, textures). limits: dict(verts, bytes, textures). A cell is final when it passes, cannot be split
    (smaller than min_cell, or all centroids equal) or has one triangle. Returns a list of index arrays, in a fixed order."""
    if box is None:
        box = (float(cx[idx].min()), float(cz[idx].min()), float(cx[idx].max()), float(cz[idx].max()))
    s = stat(idx)
    ok = s['verts_max'] <= limits['verts'] and s['bytes'] <= limits['bytes']
    tex_ok = s['textures'] <= limits.get('textures', 1 << 30)
    w, h = box[2] - box[0], box[3] - box[1]
    if (ok and tex_ok) or len(idx) <= 1 or (max(w, h) <= min_cell and ok) or depth > 24:
        if ok or len(idx) <= 1:
            return [idx]
        # cannot be split by position: cut the triangle list itself (still deterministic)
        n = int(np.ceil(max(s['verts_max'] / float(limits['verts']), s['bytes'] / float(limits['bytes']), 2.0)))
        return [part for part in np.array_split(idx, n) if len(part)]
    mx, mz = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    if w >= h:
        sel = cx[idx] < mx
        halves = [(idx[sel], (box[0], box[1], mx, box[3])), (idx[~sel], (mx, box[1], box[2], box[3]))]
    else:
        sel = cz[idx] < mz
        halves = [(idx[sel], (box[0], box[1], box[2], mz)), (idx[~sel], (box[0], mz, box[2], box[3]))]
    if any(len(h_[0]) == 0 for h_ in halves):            # all centroids on one side of the mid line: shrink to their own box
        part = [h_ for h_ in halves if len(h_[0])][0][0]
        if max(w, h) <= min_cell * 0.5 or len(part) == len(idx) and (cx[idx].max() == cx[idx].min() and cz[idx].max() == cz[idx].min()):
            n = int(np.ceil(max(s['verts_max'] / float(limits['verts']), s['bytes'] / float(limits['bytes']), 1.0)))
            return [pp for pp in np.array_split(idx, max(n, 1)) if len(pp)]
        nb = (float(cx[part].min()), float(cz[part].min()), float(cx[part].max()), float(cz[part].max()))
        return plan_cells(cx, cz, part, stat, limits, nb, min_cell, depth + 1)
    out = []
    for part, b in halves:
        out += plan_cells(cx, cz, part, stat, limits, b, min_cell, depth + 1)
    return out


# ---------------------------------------------------------------------------------------------- collision
def _hull2d(pts):
    pts = np.unique(np.round(pts, 5), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    lower = half(pts)
    upper = half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _cap_hull(h, n):
    """At most n vertices of a convex polygon: keep the n corners that carry the most area (stable by index)."""
    if len(h) <= n:
        return h
    keep = np.round(np.linspace(0, len(h), n, endpoint=False)).astype(int)
    return h[np.unique(keep)]


COLLISION_DEFAULTS = dict(cell_m=5.0, flat_deg=18.0, flat_tol_m=0.25, thickness_m=0.4, min_area_m2=0.02, skip_size_m=1.0, max_pieces=2000,
                          max_verts=96, flush=True, stack_tol_m=0.6, stack_cover=0.9)


def collision(P, T, tri_ok, tri_surface, params=None, log=None, N=None):
    """Convex slab pieces of the triangles `tri_ok` (bool mask) of one chunk.
    -> list of dict(points (k, 3) float64, surface int, area, tris). tri_surface: per-triangle surface class index (any int).
    Near-flat patches (the normals within flat_deg, all corners within flat_tol_m of the patch plane, one grid cell) become one slab
    of thickness_m; a patch that is not flat is split in half until it is. If the count passes max_pieces the cell grows by 50 %.
    N (per-vertex normals, optional) says which way a surface faces: with `flush` the slab hangs behind that face, so its front face is the drawn
    surface (a slab centred on the surface would put the player half a thickness above the floor)."""
    p = dict(COLLISION_DEFAULTS)
    p.update(params or {})
    n, area = tri_normals_area(P, T)
    cen = (P[T[:, 0]].astype(np.float64) + P[T[:, 1]] + P[T[:, 2]]) / 3.0
    sel = np.nonzero(tri_ok & (area >= float(p['min_area_m2'])))[0]
    if len(sel) == 0:
        return []
    cell = float(p['cell_m'])
    # direction buckets: cube-sphere cells of 2 * flat_deg
    step = max(np.sin(np.radians(float(p['flat_deg']))), 0.05)
    for attempt in range(8):
        key_n = np.rint(n[sel] / step).astype(np.int64)
        key_c = np.floor(cen[sel] / cell).astype(np.int64)
        key = np.concatenate([key_n, key_c], axis=1)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        groups = np.argsort(inv, kind='stable')
        bounds = np.concatenate([[0], np.cumsum(np.bincount(inv))])
        pieces = []
        work = [groups[bounds[g]:bounds[g + 1]] for g in range(len(bounds) - 2, -1, -1)]
        while work:
            pos = work.pop()
            ids = sel[pos]
            pc = _slab(P, T, n, area, ids, tri_surface, p, N)
            if pc is None:                               # not flat enough: split along the longer axis of the group
                ctr = cen[ids]
                ext = ctr.max(0) - ctr.min(0)
                ax = int(np.argmax(ext))
                m = ctr[:, ax] < (ctr[:, ax].min() + ctr[:, ax].max()) / 2
                if ext[ax] < 0.5 or len(ids) < 2 or m.all() or (~m).all():
                    pc = _slab(P, T, n, area, ids, tri_surface, dict(p, flat_tol_m=1e9), N)
                else:
                    work.append(pos[~m])
                    work.append(pos[m])
                    continue
            if pc:
                pieces.append(pc)
        if len(pieces) <= int(p['max_pieces']):
            break
        cell *= 1.5
        if log is not None:
            log.append('collision: %d pieces, cell grown to %.1f m' % (len(pieces), cell))
    return pieces


def thin_stacks(pieces, tol_m=0.6, cover=0.9, cell_m=0.5):
    """Drop floor slabs that only repeat another floor slab. The source layers coplanar surfaces (a road over its terrain, double-sided
    duplicates, neighbouring chunks that both cover a street), and the engine darkens the player's blob shadow once per collision face under
    it, so every extra layer makes it blacker. A slab whose top is at least `cover` covered (on a cell_m grid) by the tops of slabs already
    kept, within tol_m in height, adds nothing to the floor and is dropped. Highest first, so the topmost layer stays.
    pieces: dicts with `points` in one common frame (top face = first half of the points, as _slab writes them).
    -> (kept pieces in the original order, dropped count). Slabs that are not floors (walls) are always kept."""
    if tol_m <= 0:
        return list(pieces), 0
    info = []
    for i, pc in enumerate(pieces):
        P = np.asarray(pc['points'], np.float64)
        k = len(P) // 2
        top, bot = P[:k], P[k:]
        nn = top.mean(0) - bot.mean(0)
        ln = np.linalg.norm(nn)
        if k >= 3 and ln > 1e-9 and abs(nn[1]) / ln > 0.5:           # a duplicate wound the other way has its two faces swapped
            if nn[1] < 0:
                top = bot
            info.append((float(top[:, 1].mean()), i, top))
    info.sort(key=lambda t: -t[0])
    seen = {}
    drop = set()
    for ym, i, top in info:
        lo, hi = top[:, [0, 2]].min(0), top[:, [0, 2]].max(0)
        gx = np.arange(np.floor(lo[0] / cell_m), np.floor(hi[0] / cell_m) + 1)
        gz = np.arange(np.floor(lo[1] / cell_m), np.floor(hi[1] / cell_m) + 1)
        X, Z = np.meshgrid((gx + 0.5) * cell_m, (gz + 0.5) * cell_m, indexing='ij')
        X, Z = X.ravel(), Z.ravel()
        inside = np.ones(len(X), bool)
        c2 = top[:, [0, 2]]
        cen = c2.mean(0)
        order = np.argsort(np.arctan2(c2[:, 1] - cen[1], c2[:, 0] - cen[0]))
        r = c2[order]
        for a in range(len(r)):
            b = (a + 1) % len(r)
            cr = (r[b][0] - r[a][0]) * (Z - r[a][1]) - (r[b][1] - r[a][1]) * (X - r[a][0])
            inside &= cr >= -1e-9
        if not inside.any():                              # smaller than a cell: sample its middle
            X, Z, inside = np.array([cen[0]]), np.array([cen[1]]), np.array([True])
        cells = [(int(np.floor(x / cell_m)), int(np.floor(z / cell_m))) for x, z in zip(X[inside], Z[inside])]
        hit = sum(1 for c in cells if any(abs(y - ym) <= tol_m for y in seen.get(c, ())))
        if hit >= cover * len(cells):
            drop.add(i)
            continue
        for c in cells:
            seen.setdefault(c, []).append(ym)
    return [pc for i, pc in enumerate(pieces) if i not in drop], len(drop)


def _slab(P, T, n, area, ids, tri_surface, p, N=None):
    pts = P[T[ids].reshape(-1)].astype(np.float64)
    w = np.repeat(area[ids], 3)
    nn = (n[ids] * area[ids][:, None]).sum(0)
    ln = np.linalg.norm(nn)
    if ln < 1e-12:
        return None
    nn /= ln
    d = pts @ nn
    d0 = float((d * w).sum() / w.sum())
    if float(np.abs(d - d0).max()) > float(p['flat_tol_m']):
        return None
    u = np.cross(nn, [0.0, 1.0, 0.0] if abs(nn[1]) < 0.9 else [1.0, 0.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(nn, u)
    q = np.stack([pts @ u, pts @ v], 1)
    h = _cap_hull(_hull2d(q), int(p['max_verts']) // 2)
    if len(h) < 3:
        return None
    half = float(p['thickness_m']) / 2.0
    # flush: the slab hangs BEHIND the surface (its front face is the surface), so the player stands on the drawn floor instead of half a
    # thickness above it. (The blob shadow's darkness is not decided here: it darkens once per collision face under the player, and
    # the hull builder keeps one face per plane, see hullclean.py.)
    out = nn
    if N is not None:
        vn = np.asarray(N)[T[ids].reshape(-1)].astype(np.float64).mean(0)
        if float(np.linalg.norm(vn)) > 1e-6 and float(vn @ nn) < 0:
            out = -nn
    origin = nn * d0 - (out * half if p.get('flush', True) else 0.0)
    top = origin + h[:, 0:1] * u + h[:, 1:2] * v + nn * half
    bot = origin + h[:, 0:1] * u + h[:, 1:2] * v - nn * half
    surf = np.bincount(np.asarray(tri_surface)[ids].astype(np.int64), weights=area[ids])
    return dict(points=np.concatenate([top, bot]), surface=int(np.argmax(surf)), area=float(area[ids].sum()), tris=int(len(ids)))
