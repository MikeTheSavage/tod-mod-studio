"""The ground surface: chunk meshes of the height grid (one sub-mesh per painted material, smooth shared normals, seamless uv) and
their convex collision pieces (merged rectangles on planes, one hull for a gently twisted cell, two prisms otherwise).

A chunk is one generated model placed once. Limits split it: more than G3 collision pieces, or more than the sub-mesh vertex cap,
cut the chunk in four (repeatedly). Triangle and vertex counts are reported per chunk.
"""
from .core import np, MapgenError
from .meshkit import Mesh, VERT_CAP

HULL_CAP = 2000
TWIST_ONE_HULL = 0.04       # a cell whose four heights miss a plane by less than this (m) gets one hull instead of two prisms
PLANE_EPS = 1e-4


def normals(H):
    """Smooth vertex normals of the whole grid (nz + 1, nx + 1, 3)."""
    h = H.h
    p = np.pad(h, 1, mode='edge')
    dx = (p[1:-1, 2:] - p[1:-1, :-2]) / (2 * H.cell)
    dz = (p[2:, 1:-1] - p[:-2, 1:-1]) / (2 * H.cell)
    n = np.stack([-dx, np.ones_like(h), -dz], axis=-1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def cell_mesh(H, N, i0, i1, j0, j1, tex_idx, pal, uv, origin, mesh):
    """Add the cells [i0, i1) x [j0, j1) to `mesh` (model space: world minus origin in x and z)."""
    sub = tex_idx[j0:j1, i0:i1]
    for pi in sorted(set(int(v) for v in np.unique(sub))):
        jj, ii = np.nonzero(sub == pi)
        jj, ii = jj + j0, ii + i0
        pts = np.unique(np.concatenate([jj * (H.nx + 1) + ii, jj * (H.nx + 1) + ii + 1, (jj + 1) * (H.nx + 1) + ii,
                                        (jj + 1) * (H.nx + 1) + ii + 1]))
        pz, px = np.divmod(pts, H.nx + 1)
        remap = {int(g): k for k, g in enumerate(pts)}
        lut = np.full((H.nz + 1) * (H.nx + 1), -1, dtype=np.int64)
        lut[pts] = np.arange(len(pts))
        wx = H.ox + px * H.cell
        wz = H.oz + pz * H.cell
        P = np.stack([wx - origin[0], H.h[pz, px], wz - origin[1]], axis=-1)
        Nn = N[pz, px]
        T = np.stack([wx * uv, wz * uv], axis=-1)
        a = lut[jj * (H.nx + 1) + ii]
        b = lut[jj * (H.nx + 1) + ii + 1]
        c = lut[(jj + 1) * (H.nx + 1) + ii + 1]
        d = lut[(jj + 1) * (H.nx + 1) + ii]
        h00, h10, h11, h01 = H.h[jj, ii], H.h[jj, ii + 1], H.h[jj + 1, ii + 1], H.h[jj + 1, ii]
        short_ac = np.abs(h00 - h11) <= np.abs(h10 - h01)           # split along the shorter diagonal
        t1 = np.where(short_ac[:, None], np.stack([a, b, c], 1), np.stack([a, b, d], 1))
        t2 = np.where(short_ac[:, None], np.stack([a, c, d], 1), np.stack([b, c, d], 1))
        mesh.add(pal[pi]['tex'], P, Nn, T, np.concatenate([t1, t2]))
        del remap


def _runs(cells, key):
    """Greedy rectangles over a dict {(i, j): value}: cells of equal value merge. -> [(i0, j0, i1, j1 inclusive, value)]."""
    done = set()
    out = []
    for (i, j) in sorted(cells, key=lambda k: (k[1], k[0])):
        if (i, j) in done:
            continue
        v = cells[(i, j)]
        ie = i
        while (ie + 1, j) in cells and (ie + 1, j) not in done and cells[(ie + 1, j)] == v:
            ie += 1
        je = j
        while all((k, je + 1) in cells and (k, je + 1) not in done and cells[(k, je + 1)] == v for k in range(i, ie + 1)):
            je += 1
        for jj in range(j, je + 1):
            for ii in range(i, ie + 1):
                done.add((ii, jj))
        out.append((i, j, ie, je, v))
    return out


def cell_hulls(H, i0, i1, j0, j1, surf, th, origin, mesh):
    """Collision pieces for the cells [i0, i1) x [j0, j1); `surf` is the (nz, nx) face-material grid."""
    h = H.h
    sub = (slice(j0, j1), slice(i0, i1))
    h00, h10 = h[j0:j1, i0:i1], h[j0:j1, i0 + 1:i1 + 1]
    h01, h11 = h[j0 + 1:j1 + 1, i0:i1], h[j0 + 1:j1 + 1, i0 + 1:i1 + 1]
    twist = h00 + h11 - h01 - h10
    gx = (h10 - h00) / H.cell                            # plane through the cell when it is exactly planar
    gz = (h01 - h00) / H.cell
    planar = np.abs(twist) < PLANE_EPS
    mat = ''
    del sub, mat
    plane_cells = {}
    odd = []
    S = surf[j0:j1, i0:i1]
    for j in range(j1 - j0):
        for i in range(i1 - i0):
            s = int(S[j, i])
            if planar[j, i]:
                wx0 = H.ox + (i0 + i) * H.cell
                wz0 = H.oz + (j0 + j) * H.cell
                c0 = h00[j, i] - gx[j, i] * wx0 - gz[j, i] * wz0
                plane_cells[(i0 + i, j0 + j)] = (s, round(float(gx[j, i]), 4), round(float(gz[j, i]), 4), round(float(c0), 3))
            else:
                odd.append((i0 + i, j0 + j, s, float(twist[j, i])))
    ox, oz = origin
    for (a0, b0, a1, b1, (s, ax, az, c0)) in _runs(plane_cells, None):
        x0, x1 = H.ox + a0 * H.cell, H.ox + (a1 + 1) * H.cell
        z0, z1 = H.oz + b0 * H.cell, H.oz + (b1 + 1) * H.cell
        top = [(x, ax * x + az * z + c0, z) for x in (x0, x1) for z in (z0, z1)]
        pts = [(x - ox, y, z - oz) for x, y, z in top] + [(x - ox, y - th, z - oz) for x, y, z in top]
        mesh.hull(pts, 'solid', _MAT[s])
    for (i, j, s, tw) in odd:
        x0, x1 = H.ox + i * H.cell, H.ox + (i + 1) * H.cell
        z0, z1 = H.oz + j * H.cell, H.oz + (j + 1) * H.cell
        q = [(x0, h[j, i], z0), (x1, h[j, i + 1], z0), (x1, h[j + 1, i + 1], z1), (x0, h[j + 1, i], z1)]
        if abs(tw) < TWIST_ONE_HULL:
            tops = [q[0], q[1], q[3], q[2]]
            pts = [(x - ox, y, z - oz) for x, y, z in tops] + [(x - ox, y - th, z - oz) for x, y, z in tops]
            mesh.hull(pts, 'solid', _MAT[s])
        else:
            if abs(q[0][1] - q[2][1]) <= abs(q[1][1] - q[3][1]):
                tris = [(0, 1, 2), (0, 2, 3)]
            else:
                tris = [(0, 1, 3), (1, 2, 3)]
            for t in tris:
                tp = [q[k] for k in t]
                pts = [(x - ox, y, z - oz) for x, y, z in tp] + [(x - ox, y - th, z - oz) for x, y, z in tp]
                mesh.hull(pts, 'solid', _MAT[s])


def _mat_names():
    from .core import MATERIALS
    return MATERIALS


_MAT = _mat_names()


def chunk_ranges(nx, nz, cs):
    return [(i, min(i + cs, nx), j, min(j + cs, nz)) for j in range(0, nz, cs) for i in range(0, nx, cs)]


def build_chunks(H, tex_idx, surf, pal, uv, th, cs, extra, out, prefix='G'):
    """Chunk models of the whole grid. `extra`: list of (x, z, [hull point sets in world space], material) added to the chunk that
    contains (x, z). Registers the models and placements in `out`; returns the per-chunk stats."""
    N = normals(H)
    stats = []
    cs = max(2, int(cs))
    while (cs + 1) * (cs + 1) > VERT_CAP:
        cs //= 2
    todo = chunk_ranges(H.nx, H.nz, cs)
    final = []
    while todo:
        i0, i1, j0, j1 = todo.pop(0)
        origin = (H.ox + i0 * H.cell, H.oz + j0 * H.cell)
        mesh = Mesh()
        cell_mesh(H, N, i0, i1, j0, j1, tex_idx, pal, uv, origin, mesh)
        cell_hulls(H, i0, i1, j0, j1, surf, th, origin, mesh)
        x0, x1 = H.ox + i0 * H.cell, H.ox + i1 * H.cell
        z0, z1 = H.oz + j0 * H.cell, H.oz + j1 * H.cell
        last_i, last_j = i1 == H.nx, j1 == H.nz
        for (ex, ez, sets, mat) in extra:
            if x0 <= ex < x1 + (1e-9 if last_i else 0) and z0 <= ez < z1 + (1e-9 if last_j else 0):
                for pts in sets:
                    mesh.hull([(p[0] - origin[0], p[1], p[2] - origin[1]) for p in pts], 'solid', mat)
        if len(mesh.hulls) > HULL_CAP and (i1 - i0 > 1 or j1 - j0 > 1):
            im, jm = (i0 + i1) // 2 if i1 - i0 > 1 else i1, (j0 + j1) // 2 if j1 - j0 > 1 else j1
            parts = [(i0, im, j0, jm), (im, i1, j0, jm), (i0, im, jm, j1), (im, i1, jm, j1)]
            todo = [p for p in parts if p[1] > p[0] and p[3] > p[2]] + todo
            continue
        final.append((i0, i1, j0, j1, origin, mesh))
    for i0, i1, j0, j1, origin, mesh in final:
        name = '%s_%d_%d' % (prefix, i0, j0)
        out.model(name, [mesh.part()])
        out.place(name, [origin[0], 0.0, origin[1]], name='GROUND_%d_%d' % (i0, j0))
        c = mesh.counts()
        stats.append(dict(model=name, cells=[i0, j0, i1, j1], triangles=c['triangles'], vertices=c['vertices'], submeshes=len(c['textures']),
                          max_submesh=c['max_submesh'], hulls=c['hulls'], max_hull_vertices=c['max_hull_vertices'], textures=c['textures']))
    return stats
