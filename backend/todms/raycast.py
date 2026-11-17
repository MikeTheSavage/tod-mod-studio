"""Any-hit ray casting against a triangle soup (numpy). Used by the lighting bake for sun shadows and sky occlusion.

A bounding-volume tree is built by cutting the triangles level by level at the middle of the longest axis of their centres: the leaves hold
`LEAF` consecutive triangles of that order and every level above merges pairs of nodes (a complete binary tree stored level by level, empty
leaves padded with an empty box). Triangles with a long edge are cut first so the boxes stay tight.
Rays are traced in waves: all (ray, node) pairs of one tree level are tested together with the slab test, the surviving pairs go down, at
the leaves every (ray, triangle) pair is tested with the two-sided Moller-Trumbore test. A ray that found a hit leaves the wave at once.
Everything is plain numpy, so the result does not depend on the thread count or on the order of the rays.
"""
import math

import numpy as np

LEAF = 4
EPS = 1e-9


def _spread(v):
    """Interleave the low 10 bits of v with two zero bits between each (Morton code helper)."""
    v = v.astype(np.uint64) & np.uint64(0x3FF)
    v = (v | (v << np.uint64(16))) & np.uint64(0x030000FF)
    v = (v | (v << np.uint64(8))) & np.uint64(0x0300F00F)
    v = (v | (v << np.uint64(4))) & np.uint64(0x030C30C3)
    v = (v | (v << np.uint64(2))) & np.uint64(0x09249249)
    return v


def split_long(t, limit):
    """Cut every triangle whose longest edge passes `limit` in two at that edge's middle, until none does (tight boxes for the tree)."""
    t = np.asarray(t, np.float64).reshape(-1, 3, 3)
    out = []
    for _ in range(12):
        e = np.stack([np.linalg.norm(t[:, 1] - t[:, 0], axis=1), np.linalg.norm(t[:, 2] - t[:, 1], axis=1),
                      np.linalg.norm(t[:, 0] - t[:, 2], axis=1)], 1)
        lo_, hi_ = t.min(1), t.max(1)
        ext = hi_ - lo_
        surf = 2.0 * (ext[:, 0] * ext[:, 1] + ext[:, 1] * ext[:, 2] + ext[:, 0] * ext[:, 2])
        area = 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        slack = surf / np.maximum(2.0 * area, 1e-12)             # 2 for a flat axis-aligned triangle, large for a slanted sliver
        longest = e.max(1)
        big = ((longest > limit) & (slack > 3.0)) | (longest > 8.0 * limit)
        if not big.any():
            break
        out.append(t[~big])
        b, eb = t[big], e[big]
        k = eb.argmax(1)
        i = np.arange(len(b))
        a = b[i, k]                       # edge k runs from vertex k to vertex k+1, the third vertex is k+2
        c = b[i, (k + 1) % 3]
        o = b[i, (k + 2) % 3]
        m = (a + c) * 0.5
        t = np.concatenate([np.stack([a, m, o], 1), np.stack([m, c, o], 1)])
    out.append(t)
    return np.concatenate(out)


class Tree:
    """tris: (n, 3, 3) float array of world-space triangles; triangles with an edge longer than `split` metres are cut first."""

    def __init__(self, tris, split=6.0):
        t = np.asarray(tris, np.float64).reshape(-1, 3, 3)
        if split and len(t):
            t = split_long(t, split)
        self.n = len(t)
        if self.n == 0:
            self.levels = []
            self.tri = np.zeros((0, 3, 3))
            return
        lo = t.min(1)
        hi = t.max(1)
        cen = (lo + hi) * 0.5
        nleaf = (self.n + LEAF - 1) // LEAF
        depth = max(0, int(np.ceil(np.log2(max(nleaf, 1)))))
        width = 1 << depth
        total = width * LEAF
        pad = total - self.n
        big = np.float64(1e30)
        lo = np.concatenate([lo, np.full((pad, 3), big)])
        hi = np.concatenate([hi, np.full((pad, 3), -big)])
        cen = np.concatenate([cen, np.full((pad, 3), np.inf)])
        t = np.concatenate([t, np.zeros((pad, 3, 3))])
        real = np.concatenate([np.ones(self.n, bool), np.zeros(pad, bool)])
        order = np.arange(total)
        # median split level by level: every segment is cut at the middle of its longest centroid axis
        for level in range(depth):
            seg = total >> level
            nseg = 1 << level
            c = cen[order].reshape(nseg, seg, 3)
            r = real[order].reshape(nseg, seg)
            cmin = np.where(r[:, :, None], c, np.inf).min(1)
            cmax = np.where(r[:, :, None], c, -np.inf).max(1)
            axis = np.argmax(np.where(np.isfinite(cmax - cmin), cmax - cmin, 0.0), axis=1)
            key = np.take_along_axis(c, axis[:, None, None].repeat(seg, 1), 2)[:, :, 0]
            perm = np.argsort(key, axis=1, kind='stable')
            order = np.take_along_axis(order.reshape(nseg, seg), perm, 1).reshape(-1)
        t, lo, hi = t[order], lo[order], hi[order]
        self.tri = t
        self.valid = real[order]
        llo = lo.reshape(width, LEAF, 3).min(1)
        lhi = hi.reshape(width, LEAF, 3).max(1)
        levels = [(llo, lhi)]
        while len(levels[-1][0]) > 1:
            a_, b_ = levels[-1]
            levels.append((np.minimum(a_[0::2], a_[1::2]), np.maximum(b_[0::2], b_[1::2])))
        for lo_, hi_ in levels:                                # an empty node (padding) must never pass the slab test: a box at the far point
            empty = (lo_ > hi_).any(1)
            lo_[empty] = 1e30
            hi_[empty] = 1e30
        self.levels = levels[::-1]                           # root first
        # precomputed edges for the triangle test
        self.v0 = self.tri[:, 0]
        self.e1 = self.tri[:, 1] - self.tri[:, 0]
        self.e2 = self.tri[:, 2] - self.tri[:, 0]

    def height_grid(self, cell=None):
        """The coarse 2.5D map used to clear sun rays without the tree: for every ground cell the highest point of any triangle whose box
        (grown by one cell) touches it. -> (x0, z0, cell, nx, nz, heights). Built once."""
        if getattr(self, '_hg', None) is not None:
            return self._hg
        t = self.tri[self.valid]
        lo, hi = t.min(1), t.max(1)
        x0, z0 = float(lo[:, 0].min()), float(lo[:, 2].min())
        ex, ez = float(hi[:, 0].max()) - x0, float(hi[:, 2].max()) - z0
        c = float(cell or max(2.0, max(ex, ez) / 1500.0))
        nx, nz = int(ex / c) + 3, int(ez / c) + 3
        h = np.full(nz * nx, -1e30)
        i0 = np.clip(((lo[:, 0] - x0) / c).astype(np.int64) - 0, 0, nx - 1)
        i1 = np.clip(((hi[:, 0] - x0) / c).astype(np.int64) + 2, 0, nx - 1)
        j0 = np.clip(((lo[:, 2] - z0) / c).astype(np.int64) - 0, 0, nz - 1)
        j1 = np.clip(((hi[:, 2] - z0) / c).astype(np.int64) + 2, 0, nz - 1)
        top = hi[:, 1]
        span = int(max((i1 - i0).max(), (j1 - j0).max())) + 1
        for dj in range(span):
            for di in range(span):
                ok = (i0 + di <= i1) & (j0 + dj <= j1)
                if ok.any():
                    np.maximum.at(h, (j0[ok] + dj) * nx + (i0[ok] + di), top[ok])
        # one more cell of margin on the low side (the box of a triangle starts one cell before its first cell)
        g = h.reshape(nz, nx)
        g2 = g.copy()
        g2[:, 1:] = np.maximum(g2[:, 1:], g[:, :-1])
        g2[1:, :] = np.maximum(g2[1:, :], g[:-1, :])
        g2[1:, 1:] = np.maximum(g2[1:, 1:], g[:-1, :-1])
        g2[:-1, 1:] = np.maximum(g2[:-1, 1:], g[1:, :-1])
        self._hg = (x0, z0, c, nx, nz, g2)
        return self._hg

    def clear_sun(self, origin, direction, reach, start=0.5):
        """-> bool array, True where the ray is certainly free over `reach` metres (marched over the height grid: never True for a ray that a
        triangle blocks). False means 'maybe blocked': ask occluded()."""
        origin = np.asarray(origin, np.float64).reshape(-1, 3)
        d = np.asarray(direction, np.float64).reshape(-1, 3)[0]
        out = np.ones(len(origin), bool)
        if not self.levels or not len(origin):
            return out
        x0, z0, c, nx, nz, g = self.height_grid()
        dh = math.hypot(d[0], d[2])
        step = c * 0.5
        t_step = step / dh if dh > 1e-6 else reach
        n = int(min(reach, 1e6) / t_step) + 1 if dh > 1e-6 else 1
        n = min(n, 4000)
        ts = start + np.arange(n) * t_step
        ts = ts[ts <= reach]
        flat = g.reshape(-1)
        chunk = max(1, 3000000 // max(1, len(ts)))
        for s in range(0, len(origin), chunk):
            o = origin[s:s + chunk]
            px = o[:, 0:1] + ts[None, :] * d[0]
            pz = o[:, 2:3] + ts[None, :] * d[2]
            py = o[:, 1:2] + ts[None, :] * d[1]
            ix = ((px - x0) / c).astype(np.int64)
            iz = ((pz - z0) / c).astype(np.int64)
            inside = (ix >= 0) & (ix < nx) & (iz >= 0) & (iz < nz)
            hh = np.where(inside, flat[np.clip(iz, 0, nz - 1) * nx + np.clip(ix, 0, nx - 1)], -1e30)
            out[s:s + chunk] = ~(hh >= py - 1e-3).any(1)
        return out

    def occluded(self, origin, direction, tmax, tmin=1e-4, chunk=4000):
        """-> bool array: does the ray origin + t * direction (unit direction, tmin < t < tmax) hit any triangle?
        tmax: scalar or one value per ray."""
        origin = np.asarray(origin, np.float64).reshape(-1, 3)
        direction = np.asarray(direction, np.float64).reshape(-1, 3)
        m = len(origin)
        tmax = np.broadcast_to(np.asarray(tmax, np.float64), (m,))
        out = np.zeros(m, bool)
        if not self.levels or m == 0:
            return out
        for s in range(0, m, chunk):
            e = min(m, s + chunk)
            out[s:e] = self._wave(origin[s:e], direction[s:e], tmax[s:e], tmin)
        return out

    def _wave(self, o, d, tmax, tmin):
        m = len(o)
        hit = np.zeros(m, bool)
        with np.errstate(divide='ignore', invalid='ignore'):
            inv = 1.0 / np.where(np.abs(d) < EPS, np.where(d < 0, -EPS, EPS), d)
        ray = np.arange(m)
        node = np.zeros(m, np.int64)
        for depth, (lo, hi) in enumerate(self.levels):
            if not len(ray):
                break
            t0 = (lo[node] - o[ray]) * inv[ray]
            t1 = (hi[node] - o[ray]) * inv[ray]
            tn = np.minimum(t0, t1).max(1)
            tf = np.maximum(t0, t1).min(1)
            ok = (tf >= np.maximum(tn, tmin)) & (tn <= tmax[ray])
            ray, node = ray[ok], node[ok]
            if depth + 1 < len(self.levels):
                ray = np.repeat(ray, 2)
                node = np.repeat(node * 2, 2) + np.tile(np.array([0, 1]), len(ray) // 2)
        if not len(ray):
            return hit
        # leaves: every (ray, triangle) pair
        ray = np.repeat(ray, LEAF)
        tri = np.repeat(node * LEAF, LEAF) + np.tile(np.arange(LEAF), len(ray) // LEAF)
        keep = self.valid[tri]
        ray, tri = ray[keep], tri[keep]
        step = 600000
        for s in range(0, len(ray), step):
            r, t = ray[s:s + step], tri[s:s + step]
            r, t = r[~hit[r]], t[~hit[r]]
            if not len(r):
                continue
            dd, e1, e2 = d[r], self.e1[t], self.e2[t]
            p = np.cross(dd, e2)
            det = (e1 * p).sum(1)
            good = np.abs(det) > 1e-12
            idet = 1.0 / np.where(good, det, 1.0)
            tv = o[r] - self.v0[t]
            u = (tv * p).sum(1) * idet
            q = np.cross(tv, e1)
            v = (dd * q).sum(1) * idet
            tt = (e2 * q).sum(1) * idet
            h = good & (u >= 0) & (v >= 0) & (u + v <= 1) & (tt > tmin) & (tt < tmax[r])
            hit[r[h]] = True
        return hit
