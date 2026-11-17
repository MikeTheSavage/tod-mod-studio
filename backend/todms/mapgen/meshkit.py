"""Mesh and hull accumulation for the generated models, and the compact 'mapgen' part they are written as.

A generated model is one `parts` entry {"type": "mapgen", ...}: per texture one triangle mesh (positions, normals, uvs, indices as
little-endian base64 arrays) plus a list of convex collision pieces (points, surface word index, face material). The vendored
geometry kit knows the four shipped part types only; `geoplug.install()` teaches the builder this one (an old builder refuses
the unknown type instead of building an empty model).
"""
import numpy as np

from .core import enc, dec, mat_index, SURF_WORDS, MapgenError

VERT_CAP = 60000        # the builder's own cap per sub-mesh (the engine's is 65,535: M1)
HULL_VERT_CAP = 255     # L15
HULL_INDEX_CAP = 4095   # L15_index


class Mesh:
    """Triangle meshes grouped by texture name, plus convex collision pieces, in the model's own space."""

    def __init__(self):
        self.groups = {}     # tex -> dict(P=[arrays], N=[], T=[], I=[], n=0)
        self.hulls = []      # (points (k, 3), surface 0|1, material index)

    # -------------------------------------------------------------------------------- triangles
    def add(self, tex, P, N, T, tris):
        g = self.groups.setdefault(tex, dict(P=[], N=[], T=[], I=[], n=0))
        P = np.asarray(P, dtype=float).reshape(-1, 3)
        g['P'].append(P)
        g['N'].append(np.asarray(N, dtype=float).reshape(-1, 3))
        g['T'].append(np.asarray(T, dtype=float).reshape(-1, 2))
        g['I'].append(np.asarray(tris, dtype=np.int64).reshape(-1, 3) + g['n'])
        g['n'] += len(P)

    def quad(self, tex, a, b, c, d, n=None, uv=None):
        """A quad a-b-c-d (any winding: the builder winds against the normal). Normal from the corners unless given."""
        a, b, c, d = [np.asarray(v, dtype=float) for v in (a, b, c, d)]
        if n is None:
            n = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(n))
            n = n / ln if ln > 1e-12 else np.array([0.0, 1.0, 0.0])
        if uv is None:
            uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.add(tex, [a, b, c, d], [n] * 4, uv, [(0, 1, 2), (0, 2, 3)])

    def box(self, tex, mn, mx, uv=0.25, skip=(), collide=True, material='Concrete', surface='solid'):
        """An axis box with flat outward normals and metre-scaled uvs."""
        x0, y0, z0 = mn
        x1, y1, z1 = mx
        F = [('+x', (1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ('-x', (-1, 0, 0), [(x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0)]),
             ('+y', (0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
             ('-y', (0, -1, 0), [(x0, y0, z1), (x0, y0, z0), (x1, y0, z0), (x1, y0, z1)]),
             ('+z', (0, 0, 1), [(x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)]),
             ('-z', (0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)])]
        for key, n, q in F:
            if key in skip:
                continue
            uvs = []
            for v in q:
                if n[1]:
                    uvs.append((v[0] * uv, v[2] * uv))
                elif n[0]:
                    uvs.append((v[2] * uv, -v[1] * uv))
                else:
                    uvs.append((v[0] * uv, -v[1] * uv))
            self.add(tex, q, [n] * 4, uvs, [(0, 1, 2), (0, 2, 3)])
        if collide:
            self.hull([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], surface, material)

    def hull(self, pts, surface='solid', material='Dirt'):
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        if len(pts) > HULL_VERT_CAP:
            raise MapgenError('a collision piece has %d vertices (the limit is %d)' % (len(pts), HULL_VERT_CAP))
        self.hulls.append((pts, 1 if surface == 'thin' else 0, mat_index(material)))

    # -------------------------------------------------------------------------------- numbers
    def counts(self):
        """-> vertices, triangles, largest sub-mesh vertex count, hulls, largest hull vertex count."""
        v = sum(g['n'] for g in self.groups.values())
        t = sum(sum(len(i) for i in g['I']) for g in self.groups.values())
        big = max([g['n'] for g in self.groups.values()] + [0])
        hv = max([len(h[0]) for h in self.hulls] + [0])
        return dict(vertices=v, triangles=t, max_submesh=big, hulls=len(self.hulls), max_hull_vertices=hv, textures=list(self.groups))

    def empty(self):
        return not self.groups and not self.hulls

    # -------------------------------------------------------------------------------- the part
    def part(self):
        meshes = []
        for tex, g in self.groups.items():
            P = np.concatenate(g['P'])
            if len(P) > VERT_CAP:
                raise MapgenError('a generated sub-mesh has %d vertices (the cap is %d)' % (len(P), VERT_CAP))
            meshes.append(dict(tex=tex, n=int(len(P)), P=enc(P), N=enc(np.concatenate(g['N'])), T=enc(np.concatenate(g['T'])),
                               I=enc(np.concatenate(g['I']), '<u2')))
        hulls = None
        if self.hulls:
            hulls = dict(n=len(self.hulls), counts=enc([len(h[0]) for h in self.hulls], '<u1'),
                         pts=enc(np.concatenate([h[0] for h in self.hulls])), surf=enc([h[1] for h in self.hulls], '<u1'),
                         mat=enc([h[2] for h in self.hulls], '<u1'))
        return dict(type='mapgen', meshes=meshes, hulls=hulls)


def read_part(part):
    """The inverse of Mesh.part(): -> list of dict(tex, P, N, T, I) and list of (points, surface word name, material index)."""
    if part.get('ref'):                                  # a part kept in the asset store (large scenes): zlib JSON of the same part
        import json
        import zlib
        from .. import assetstore
        part = json.loads(zlib.decompress(assetstore.get(part['ref'])).decode('utf-8'))
    meshes = []
    for m in part.get('meshes', []):
        n = m['n']
        meshes.append(dict(tex=m['tex'], P=dec(m['P']).reshape(n, 3), N=dec(m['N']).reshape(n, 3), T=dec(m['T']).reshape(n, 2),
                           I=dec(m['I'], '<u2').reshape(-1, 3)))
    hulls = []
    h = part.get('hulls')
    if h:
        counts = dec(h['counts'], '<u1')
        pts = dec(h['pts']).reshape(-1, 3)
        surf = dec(h['surf'], '<u1')
        mat = dec(h['mat'], '<u1')
        o = 0
        for k in range(h['n']):
            c = int(counts[k])
            hulls.append((pts[o:o + c].astype(float), 'thin' if surf[k] else 'solid', int(mat[k])))
            o += c
    return meshes, hulls


def surface_word(name):
    return SURF_WORDS[name]
