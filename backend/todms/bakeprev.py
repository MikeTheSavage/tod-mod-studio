"""The look of the baked lighting before the map is built: the same bake (`bake.py`) over the map's generated geometry, answered as colours
the view can paint on its meshes ("before / after" in the Look tool).

  POST /api/mapbuild/bake {map, quality}
    -> {quality, seconds, vertices, triangles, sun_lit, mean, ground: {nx, nz, rgb}|null, meshes: {placement key: [rgb per mesh]}}

rgb values are base64 of uint8 triples, one per vertex of the mesh as the preview draws it (the same order as /api/mapbuild/preview). The
ground is answered per point of the height grid (the view draws its own terrain from that grid). Placement key: `model@x,y,z` (4 decimals).
"""
import copy
import base64
import time

import numpy as np

from . import bake, bakestep, mapbuild, mapgen, raycast
from .mapgen.core import MapgenError
from .mapgen.meshkit import Mesh, read_part

VERTEX_CAP = 600000


def _meshes(model):
    """The meshes of a model as the preview draws them: dict(tex, P (n,3), N (n,3), I (m,3))."""
    out = []
    for part in model['parts']:
        if part.get('type') == 'mapgen':
            ms, _ = read_part(part)
        elif part.get('type') == 'box':
            m = Mesh()
            m.box(part['tex'], part['min'], part['max'], part.get('uv', 0.25), collide=False)
            ms, _ = read_part(m.part())
        elif part.get('type') == 'rock':
            ms, _ = read_part(mapbuild._rock_mesh(part).part())
            for me in ms:                                  # the preview mesh carries no true normals: from the triangles, turned away from the middle
                P = np.asarray(me['P'], np.float64)
                N = bake.vertex_normals(P, np.asarray(me['I'], np.int64).reshape(-1))
                out_ = (N * (P - P.mean(0))).sum(1) < 0
                N[out_] *= -1.0
                me['N'] = N
        else:
            continue
        out += ms
    return out


def key_of(model, pos):
    return '%s@%.4f,%.4f,%.4f' % ((model,) + tuple(float(v) + 0.0 or 0.0 for v in pos))


def _b64(rgb):
    return base64.b64encode(np.ascontiguousarray(np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)).tobytes()).decode('ascii')


def preview(m, quality='draft'):
    if quality not in bake.QUALITY:
        raise MapgenError('unknown bake quality %r' % quality)

    def run():
        t0 = time.time()
        mm, stats, notes = mapgen._expand_map(copy.deepcopy(m))
        ng = mm.get('new_geometry') or {}
        models = {md['name']: _meshes(md) for md in ng.get('models') or []}
        places = [p for p in ng.get('placements') or [] if p['model'] in models]
        if not places:
            raise MapgenError('there is nothing to bake yet')
        lights = bake.look_lights(mm.get('lighting') or bakestep.default_lighting())
        chunks, spans, tri_chunks = [], [], []
        start = 0
        for p in places:
            pos = np.asarray(p['pos'], np.float64)
            sp = []
            for me in models[p['model']]:
                P = np.asarray(me['P'], np.float64) + pos
                N = np.asarray(me['N'], np.float64)
                I = np.asarray(me['I'], np.int64).reshape(-1, 3)
                chunks.append((P, N))
                tri_chunks.append(P[I])
                sp.append((start, start + len(P)))
                start += len(P)
            spans.append(sp)
        if start > VERTEX_CAP:
            raise MapgenError('the map has %d vertices; the preview bakes up to %d' % (start, VERTEX_CAP))
        P = np.concatenate([c[0] for c in chunks])
        N = np.concatenate([c[1] for c in chunks])
        tree = raycast.Tree(np.concatenate(tri_chunks))
        col, st = bake.bake_vertices(P, N, lights, tree, quality)
        col = np.clip(col, 0.0, 1.0)
        res = dict(quality=quality, vertices=int(start), triangles=int(sum(len(t) for t in tri_chunks)), sun_lit=round(st['sun_lit'], 3),
                   mean=round(float((col @ np.array([0.299, 0.587, 0.114])).mean()), 3), meshes={}, ground=None)
        ter = stats.get('terrain')
        gx, gz, gv = [], [], []
        for p, sp in zip(places, spans):
            if p['model'].startswith('G_') and ter:
                for s, e in sp:
                    gx.append(P[s:e, 0]), gz.append(P[s:e, 2]), gv.append(col[s:e])
                continue
            res['meshes'][key_of(p['model'], p['pos'])] = [_b64(col[s:e]) for s, e in sp]
        if gx and ter:
            cell = float(ter['cell'])
            ox, oz = float(ter['origin'][0]), float(ter['origin'][1])
            x, z, v = np.concatenate(gx), np.concatenate(gz), np.concatenate(gv)
            i = np.rint((x - ox) / cell).astype(np.int64)
            j = np.rint((z - oz) / cell).astype(np.int64)
            ni, nj = int(i.max()) + 1, int(j.max()) + 1
            grid = np.ones((nj, ni, 3))
            grid[j, i] = v
            res['ground'] = dict(nx=ni, nz=nj, rgb=_b64(grid.reshape(-1, 3)))
        res['seconds'] = round(time.time() - t0, 2)
        return res
    return mapbuild._cached(mapbuild._key(m, 'bake' + quality), run)
