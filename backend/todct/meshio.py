"""Mesh files for the collision generator: read glTF 2.0 (.glb / .gltf with embedded or side-car buffers) and
Wavefront OBJ into one triangle soup with the node transforms applied; write simple .glb files (collision layer
pictures, the proof geometry). numpy only.

Axes: a glTF/OBJ file is right-handed y-up (metres). TOD is left-handed y-up; the project's exporters map between
them by negating z (docs/subsystem_collision.md 6). `to_game_axes` does that (and flips the winding so outward
faces stay outward).
"""
import base64
import json
import math
import os
import struct

import numpy as np

from . import geom

COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class MeshError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- glTF read
def _load_gltf(path):
    with open(path, 'rb') as f:
        data = f.read()
    bin_chunk = None
    if data[:4] == b'glTF':
        _, ver, total = struct.unpack_from('<III', data, 0)
        off = 12
        js = None
        while off < total:
            ln, typ = struct.unpack_from('<II', data, off)
            chunk = data[off + 8: off + 8 + ln]
            if typ == 0x4E4F534A:
                js = json.loads(chunk.decode('utf-8'))
            elif typ == 0x004E4942:
                bin_chunk = chunk
            off += 8 + ln
        if js is None:
            raise MeshError('%s: no JSON chunk' % path)
    else:
        js = json.loads(data.decode('utf-8'))
    buffers = []
    for i, b in enumerate(js.get('buffers', [])):
        uri = b.get('uri')
        if uri is None:
            buffers.append(bin_chunk)
        elif uri.startswith('data:'):
            buffers.append(base64.b64decode(uri.split(',', 1)[1]))
        else:
            with open(os.path.join(os.path.dirname(path), uri), 'rb') as f:
                buffers.append(f.read())
    return js, buffers


def _accessor(js, buffers, i):
    a = js['accessors'][i]
    bv = js['bufferViews'][a['bufferView']]
    buf = buffers[bv['buffer']]
    dt = np.dtype(COMP[a['componentType']])
    nc = NCOMP[a['type']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride')
    cnt = a['count']
    if stride and stride != dt.itemsize * nc:
        rows = [np.frombuffer(buf, dtype=dt, count=nc, offset=off + k * stride) for k in range(cnt)]
        arr = np.array(rows)
    else:
        arr = np.frombuffer(buf, dtype=dt, count=cnt * nc, offset=off).reshape(cnt, nc)
    if a.get('normalized'):
        arr = arr.astype(np.float64) / np.iinfo(dt).max
    return arr


def _node_matrix(n):
    if 'matrix' in n:
        return np.array(n['matrix'], dtype=np.float64).reshape(4, 4).T
    M = np.eye(4)
    s = np.array(n.get('scale', [1, 1, 1]), dtype=np.float64)
    R = geom.quat_to_mat(n.get('rotation', [0, 0, 0, 1]))
    M[:3, :3] = R * s
    M[:3, 3] = n.get('translation', [0, 0, 0])
    return M


def read_gltf(path, mesh_name=None):
    """-> (V (n,3) float64, F list of [i,j,k], parts [dict(name, tris)]) in the file's axes, node transforms applied.
    mesh_name: only meshes/nodes whose name contains it (case-insensitive)."""
    js, buffers = _load_gltf(path)
    Vs, Fs, parts = [], [], []
    base = [0]

    def emit(mi, M, nname):
        m = js['meshes'][mi]
        nm = m.get('name') or nname or 'mesh%d' % mi
        if mesh_name and mesh_name.lower() not in (nm.lower() + ' ' + (nname or '').lower()):
            return
        ntri = 0
        for p in m.get('primitives', []):
            if p.get('mode', 4) != 4:
                continue
            P = _accessor(js, buffers, p['attributes']['POSITION']).astype(np.float64)
            P = (np.c_[P, np.ones(len(P))] @ M.T)[:, :3]
            if 'indices' in p:
                idx = _accessor(js, buffers, p['indices']).reshape(-1).astype(np.int64)
            else:
                idx = np.arange(len(P))
            tri = idx.reshape(-1, 3) + base[0]
            if np.linalg.det(M[:3, :3]) < 0:
                tri = tri[:, [0, 2, 1]]
            Vs.append(P)
            Fs.extend(tri.tolist())
            base[0] += len(P)
            ntri += len(tri)
        parts.append(dict(name=nm, triangles=ntri))

    def walk(ni, parent):
        n = js['nodes'][ni]
        M = parent @ _node_matrix(n)
        if 'mesh' in n:
            emit(n['mesh'], M, n.get('name'))
        for c in n.get('children', []):
            walk(c, M)
    scene = js.get('scenes', [{}])[js.get('scene', 0)] if js.get('scenes') else None
    if scene and scene.get('nodes') is not None:
        for ni in scene['nodes']:
            walk(ni, np.eye(4))
    else:
        for mi in range(len(js.get('meshes', []))):
            emit(mi, np.eye(4), None)
    if not Vs:
        raise MeshError('%s: no triangle meshes%s' % (path, (' named %s' % mesh_name) if mesh_name else ''))
    return np.concatenate(Vs), Fs, parts


# ---------------------------------------------------------------------------------------------- OBJ read
def read_obj(path):
    V, F = [], []
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()
    for line in lines:
        s = line.split()
        if not s:
            continue
        if s[0] == 'v':
            V.append([float(x) for x in s[1:4]])
        elif s[0] == 'f':
            idx = []
            for w in s[1:]:
                i = int(w.split('/')[0])
                idx.append(i - 1 if i > 0 else len(V) + i)
            for k in range(1, len(idx) - 1):
                F.append([idx[0], idx[k], idx[k + 1]])
    if not F:
        raise MeshError('%s: no faces' % path)
    return np.array(V, dtype=np.float64), F, [dict(name=os.path.basename(path), triangles=len(F))]


def read_mesh(path, mesh_name=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.glb', '.gltf'):
        return read_gltf(path, mesh_name)
    if ext == '.obj':
        return read_obj(path)
    raise MeshError('unsupported mesh file %s (use .glb, .gltf or .obj)' % path)


def to_game_axes(V, F):
    """glTF/OBJ (right-handed y-up) -> TOD (left-handed y-up): z negated, winding flipped."""
    V = np.asarray(V, dtype=np.float64).copy()
    V[:, 2] *= -1
    return V, [[t[0], t[2], t[1]] for t in F]


# ---------------------------------------------------------------------------------------------- glb write
def write_glb(path, meshes, extras=None):
    """meshes: [dict(name, verts (n,3), tris [[i,j,k]], color (r,g,b,a) 0..1 optional)] in glTF axes."""
    bin_ = bytearray()
    acc, views, gmeshes, nodes, mats = [], [], [], [], []

    def add(arr, comp, typ, target=None, mnmx=False):
        arr = np.ascontiguousarray(arr)
        while len(bin_) % 4:
            bin_.append(0)
        off = len(bin_)
        bin_.extend(arr.tobytes())
        v = dict(buffer=0, byteOffset=off, byteLength=arr.nbytes)
        if target:
            v['target'] = target
        views.append(v)
        a = dict(bufferView=len(views) - 1, componentType=comp, count=int(arr.shape[0]) if typ != 'SCALAR' else int(arr.size), type=typ)
        if mnmx:
            a['min'] = arr.min(0).tolist()
            a['max'] = arr.max(0).tolist()
        acc.append(a)
        return len(acc) - 1
    for m in meshes:
        V = np.asarray(m['verts'], dtype=np.float32).reshape(-1, 3)
        T = np.asarray(m['tris'], dtype=np.uint32).reshape(-1)
        if len(V) == 0 or len(T) == 0:
            continue
        pa = add(V, 5126, 'VEC3', 34962, True)
        ia = add(T, 5125, 'SCALAR', 34963)
        col = m.get('color', (0.8, 0.8, 0.8, 1.0))
        mats.append(dict(name=m.get('name', 'm') + '_mat', doubleSided=True,
                         pbrMetallicRoughness=dict(baseColorFactor=list(col), metallicFactor=0.0, roughnessFactor=0.9),
                         alphaMode='BLEND' if col[3] < 1 else 'OPAQUE'))
        gmeshes.append(dict(name=m.get('name', 'mesh'), primitives=[dict(attributes=dict(POSITION=pa), indices=ia,
                                                                          material=len(mats) - 1)]))
        nodes.append(dict(name=m.get('name', 'mesh'), mesh=len(gmeshes) - 1))
    js = dict(asset=dict(version='2.0', generator='todct'), scene=0, scenes=[dict(nodes=list(range(len(nodes))))],
              nodes=nodes, meshes=gmeshes, materials=mats, accessors=acc, bufferViews=views,
              buffers=[dict(byteLength=len(bin_))])
    if extras:
        js['extras'] = extras
    jb = json.dumps(js, separators=(',', ':')).encode('utf-8')
    while len(jb) % 4:
        jb += b' '
    while len(bin_) % 4:
        bin_.append(0)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bin_)))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A))
        f.write(jb)
        f.write(struct.pack('<II', len(bin_), 0x004E4942))
        f.write(bytes(bin_))
    return path


def polys_to_tris(faces):
    out = []
    for f in faces:
        for k in range(1, len(f) - 1):
            out.append([f[0], f[k], f[k + 1]])
    return out


# ---------------------------------------------------------------------------------------------- simple solids
def box(mn, mx):
    """Closed box, outward winding in a right-handed frame."""
    x0, y0, z0 = mn
    x1, y1, z1 = mx
    V = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=np.float64)
    F = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]]
    return V, F


def concat(*meshes):
    Vs, Fs, base = [], [], 0
    for V, F in meshes:
        Vs.append(np.asarray(V, dtype=np.float64))
        Fs += [[a + base, b + base, c + base] for a, b, c in F]
        base += len(V)
    return np.concatenate(Vs), Fs


def extrude_polygon(poly2d, y0, y1):
    """Prism: polygon in the XZ plane (counter-clockwise seen from +Y), extruded from y0 to y1. Closed, outward."""
    n = len(poly2d)
    V = [[x, y0, z] for x, z in poly2d] + [[x, y1, z] for x, z in poly2d]
    F = []
    for k in range(1, n - 1):
        F.append([0, k + 1, k])                    # bottom (normal -Y)
        F.append([n, n + k, n + k + 1])            # top (normal +Y)
    for k in range(n):
        a, b = k, (k + 1) % n
        F.append([a, b, n + b])
        F.append([a, n + b, n + a])
    V = np.array(V, dtype=np.float64)
    # fix the orientation against the centroid (works for convex prisms)
    c = V.mean(0)
    out = []
    for t in F:
        nrm = np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]])
        out.append(t if nrm @ (V[t[0]] - c) >= 0 else [t[0], t[2], t[1]])
    return V, out


def ruin_wall_with_doorway(width=6.0, height=3.2, depth=0.8, door_w=1.4, door_h=2.2, step_w=2.4, step_d=1.6):
    """Proof geometry (right-handed y-up, metres, base at y=0, centred on x): a Mayan-style ruin wall block with a
    doorway (left pier, right pier, lintel as ONE closed mesh with a hole) plus a ramp of stone in front of it.
    The wall is a single closed non-convex mesh: the decomposition has to find the doorway."""
    hw, hd = width / 2, depth / 2
    dw = door_w / 2
    # outline of the wall seen from the front (x, y), with the doorway cut from the bottom, as a closed polygon
    outline = [(-hw, 0), (-dw, 0), (-dw, door_h), (dw, door_h), (dw, 0), (hw, 0), (hw, height), (-hw, height)]
    V, F = _extrude_outline_z(outline, -hd, hd)
    # ramp: wedge in front of the wall (towards +z), rising from 0 to 0.9 m
    rz0, rz1 = hd + 0.2, hd + 0.2 + step_d * 2
    rx = step_w / 2 + 1.6
    ramp = np.array([[rx - step_w, 0, rz1], [rx, 0, rz1], [rx, 0, rz0], [rx - step_w, 0, rz0],
                     [rx - step_w, 0.9, rz0], [rx, 0.9, rz0]], dtype=np.float64)
    RF = [[0, 2, 1], [0, 3, 2],            # bottom
          [3, 4, 5], [3, 5, 2],            # back (vertical, at rz0)
          [0, 1, 5], [0, 5, 4],            # slope
          [0, 4, 3], [1, 2, 5]]            # sides
    c = ramp.mean(0)
    RF = [t if np.cross(ramp[t[1]] - ramp[t[0]], ramp[t[2]] - ramp[t[0]]) @ (ramp[t[0]] - c) >= 0 else [t[0], t[2], t[1]] for t in RF]
    return dict(wall=(V, F), ramp=(ramp, RF))


def _extrude_outline_z(outline, z0, z1):
    """Closed prism from a simple polygon in the XY plane extruded along Z (ear-clipped caps). Outward winding."""
    pts = list(outline)
    n = len(pts)
    area = sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(n)) / 2
    if area < 0:
        pts.reverse()
    tris = _ear_clip(pts)
    V = [[x, y, z0] for x, y in pts] + [[x, y, z1] for x, y in pts]
    F = []
    for a, b, c in tris:
        F.append([a, c, b])                # back cap (z0), normal -Z
        F.append([n + a, n + b, n + c])    # front cap (z1), normal +Z
    for k in range(n):
        a, b = k, (k + 1) % n
        F.append([a, b, n + b])
        F.append([a, n + b, n + a])
    return np.array(V, dtype=np.float64), F


def _ear_clip(pts):
    idx = list(range(len(pts)))
    out = []

    def convex(a, b, c):
        return (pts[b][0] - pts[a][0]) * (pts[c][1] - pts[a][1]) - (pts[b][1] - pts[a][1]) * (pts[c][0] - pts[a][0]) > 1e-12

    def inside(p, a, b, c):
        def s(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        d1, d2, d3 = s(p, pts[a], pts[b]), s(p, pts[b], pts[c]), s(p, pts[c], pts[a])
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if not convex(a, b, c):
                continue
            if any(inside(pts[o], a, b, c) for o in idx if o not in (a, b, c)):
                continue
            out.append((a, b, c))
            idx.pop(k)
            break
    out.append(tuple(idx))
    return out
