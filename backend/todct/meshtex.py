"""Textured mesh reader for the model importer: glTF 2.0 (.glb / .gltf) and Wavefront OBJ (+ .mtl) into parts that keep
positions, normals, texture coordinates and the colour texture of each material.

Everything stays in the FILE's axes (right-handed, y up, metres for glTF; OBJ is taken the same way). The importer's
transform (axes, handedness, scale, origin) is applied afterwards, so the preview and the build use one function.
Texture coordinates leave this module in the D3D convention (v down), the one the game's textures use.
"""
import math
import os

import numpy as np

from . import meshio


class MeshTexError(ValueError):
    pass


class Part:
    def __init__(self, name, P, N, UV, tris, mat):
        self.name, self.P, self.N, self.UV, self.tris, self.mat = name, P, N, UV, tris, mat

    def copy(self):
        return Part(self.name, self.P.copy(), None if self.N is None else self.N.copy(), None if self.UV is None else self.UV.copy(),
                    self.tris.copy(), dict(self.mat))


class Scene:
    def __init__(self, parts, images, source):
        self.parts, self.images, self.source = parts, images, source

    def stats(self):
        P = np.concatenate([p.P for p in self.parts]) if self.parts else np.zeros((0, 3))
        return dict(parts=len(self.parts), vertices=int(sum(len(p.P) for p in self.parts)),
                    triangles=int(sum(len(p.tris) for p in self.parts)),
                    min=P.min(0).round(4).tolist() if len(P) else [0, 0, 0], max=P.max(0).round(4).tolist() if len(P) else [0, 0, 0])


def default_material(name='material'):
    return dict(name=name, color=[0.8, 0.8, 0.8, 1.0], image=None, alpha='opaque', cutoff=0.5, double_sided=False)


def smooth_normals(P, tris):
    N = np.zeros_like(P, dtype=np.float64)
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(N, tris[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return (N / np.maximum(ln, 1e-12)).astype(np.float32)


# ---------------------------------------------------------------------------------------------- glTF
def _image_bytes(js, buffers, i, base):
    im = js['images'][i]
    if 'bufferView' in im:
        bv = js['bufferViews'][im['bufferView']]
        o = bv.get('byteOffset', 0)
        return buffers[bv['buffer']][o:o + bv['byteLength']]
    uri = im.get('uri') or ''
    if uri.startswith('data:'):
        import base64
        return base64.b64decode(uri.split(',', 1)[1])
    from urllib.parse import unquote
    p = os.path.join(base, unquote(uri))
    if os.path.exists(p):
        with open(p, 'rb') as f:
            return f.read()
    return None


def read_gltf(path):
    js, buffers = meshio._load_gltf(path)
    base = os.path.dirname(os.path.abspath(path))
    images, img_of_tex = [], {}

    def image_for_texture(ti):
        if ti is None or ti >= len(js.get('textures', [])):
            return None
        src = js['textures'][ti].get('source')
        if src is None:
            for ext in (js['textures'][ti].get('extensions') or {}).values():
                src = ext.get('source', src)
        if src is None:
            return None
        if src not in img_of_tex:
            data = _image_bytes(js, buffers, src, base)
            if data is None:
                img_of_tex[src] = None
            else:
                images.append(dict(name=js['images'][src].get('name') or ('image%d' % src), data=data))
                img_of_tex[src] = len(images) - 1
        return img_of_tex[src]

    def material(mi):
        if mi is None or mi >= len(js.get('materials', [])):
            return default_material()
        m = js['materials'][mi]
        pbr = m.get('pbrMetallicRoughness') or {}
        sg = (m.get('extensions') or {}).get('KHR_materials_pbrSpecularGlossiness') or {}
        col = list(pbr.get('baseColorFactor') or sg.get('diffuseFactor') or [1, 1, 1, 1])
        tex = (pbr.get('baseColorTexture') or sg.get('diffuseTexture') or {}).get('index')
        r = default_material(m.get('name') or 'material%d' % mi)
        r.update(color=[float(x) for x in col], image=image_for_texture(tex), alpha={'OPAQUE': 'opaque', 'MASK': 'mask', 'BLEND': 'blend'}[
            m.get('alphaMode', 'OPAQUE')], cutoff=float(m.get('alphaCutoff', 0.5)), double_sided=bool(m.get('doubleSided')))
        return r

    parts = []

    def emit(mi, M, nname):
        mesh = js['meshes'][mi]
        nm = mesh.get('name') or nname or 'mesh%d' % mi
        R = M[:3, :3]
        try:
            NM = np.linalg.inv(R).T
        except np.linalg.LinAlgError:
            NM = np.eye(3)
        flip = np.linalg.det(R) < 0
        for pi, p in enumerate(mesh.get('primitives', [])):
            if p.get('mode', 4) != 4 or 'POSITION' not in p['attributes']:
                continue
            P = meshio._accessor(js, buffers, p['attributes']['POSITION']).astype(np.float64)
            P = (np.c_[P, np.ones(len(P))] @ M.T)[:, :3]
            N = None
            if 'NORMAL' in p['attributes']:
                N = meshio._accessor(js, buffers, p['attributes']['NORMAL']).astype(np.float64) @ NM.T
                ln = np.linalg.norm(N, axis=1, keepdims=True)
                N = (N / np.maximum(ln, 1e-12)).astype(np.float32)
            UV = None
            mat = material(p.get('material'))
            tc = 'TEXCOORD_0'
            bct = ((js['materials'][p['material']].get('pbrMetallicRoughness') or {}).get('baseColorTexture') or {}) \
                if p.get('material') is not None and p['material'] < len(js.get('materials', [])) else {}
            if bct.get('texCoord'):
                tc = 'TEXCOORD_%d' % bct['texCoord']
            if tc in p['attributes']:
                UV = meshio._accessor(js, buffers, p['attributes'][tc]).astype(np.float32)
            if 'indices' in p:
                idx = meshio._accessor(js, buffers, p['indices']).reshape(-1).astype(np.int64)
            else:
                idx = np.arange(len(P))
            tris = idx[:len(idx) // 3 * 3].reshape(-1, 3)
            if flip:
                tris = tris[:, [0, 2, 1]]
            parts.append(Part('%s_%d' % (nm, pi) if len(mesh['primitives']) > 1 else nm, P.astype(np.float32), N, UV, tris, mat))

    def walk(ni, parent):
        n = js['nodes'][ni]
        M = parent @ meshio._node_matrix(n)
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
    if not parts:
        raise MeshTexError('the file holds no triangle meshes')
    return Scene(parts, images, os.path.basename(path))


# ---------------------------------------------------------------------------------------------- OBJ
def _read_mtl(path):
    mats, cur = {}, None
    if not os.path.exists(path):
        return mats
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            s = line.strip().split(None, 1)
            if len(s) < 2:
                continue
            k, v = s[0].lower(), s[1].strip()
            if k == 'newmtl':
                cur = mats[v] = dict(color=[0.8, 0.8, 0.8, 1.0], map=None, d=1.0)
            elif cur is None:
                continue
            elif k == 'kd':
                c = [float(x) for x in v.split()[:3]]
                cur['color'][:3] = c
            elif k == 'd':
                cur['d'] = float(v.split()[0])
            elif k == 'tr':
                cur['d'] = 1.0 - float(v.split()[0])
            elif k == 'map_kd':
                parts = v.split()
                cur['map'] = parts[-1] if parts else None
    return mats


def read_obj(path):
    base = os.path.dirname(os.path.abspath(path))
    V, VT, VN = [], [], []
    groups = {}          # material name -> dict(corners {key: index}, P, N, UV, tris)
    order = []
    cur_mat = None
    mtl = {}

    def grp(m):
        if m not in groups:
            groups[m] = dict(map={}, P=[], N=[], UV=[], tris=[], hasN=False, hasUV=False)
            order.append(m)
        return groups[m]
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            s = line.split()
            if not s:
                continue
            k = s[0]
            if k == 'v':
                V.append([float(x) for x in s[1:4]])
            elif k == 'vt':
                VT.append([float(s[1]), 1.0 - float(s[2]) if len(s) > 2 else 0.0])
            elif k == 'vn':
                VN.append([float(x) for x in s[1:4]])
            elif k == 'mtllib':
                for nme in line.split(None, 1)[1].strip().split():
                    mtl.update(_read_mtl(os.path.join(base, nme)))
            elif k == 'usemtl':
                cur_mat = line.split(None, 1)[1].strip()
            elif k == 'f':
                g = grp(cur_mat)
                ids = []
                for w in s[1:]:
                    p = w.split('/')
                    vi = int(p[0])
                    vi = vi - 1 if vi > 0 else len(V) + vi
                    ti = ni = -1
                    if len(p) > 1 and p[1]:
                        t = int(p[1])
                        ti = t - 1 if t > 0 else len(VT) + t
                    if len(p) > 2 and p[2]:
                        n = int(p[2])
                        ni = n - 1 if n > 0 else len(VN) + n
                    key = (vi, ti, ni)
                    j = g['map'].get(key)
                    if j is None:
                        j = g['map'][key] = len(g['P'])
                        g['P'].append(V[vi])
                        g['UV'].append(VT[ti] if ti >= 0 else [0.0, 0.0])
                        g['N'].append(VN[ni] if ni >= 0 else [0.0, 0.0, 0.0])
                        g['hasUV'] |= ti >= 0
                        g['hasN'] |= ni >= 0
                    ids.append(j)
                for q in range(1, len(ids) - 1):
                    g['tris'].append([ids[0], ids[q], ids[q + 1]])
    if not order or not any(groups[m]['tris'] for m in order):
        raise MeshTexError('the file holds no faces')
    images, img_of, parts = [], {}, []
    for m in order:
        g = groups[m]
        if not g['tris']:
            continue
        mat = default_material(m or 'material')
        info = mtl.get(m or '')
        if info:
            mat['color'] = list(info['color']) + [info['d']]
            if info['d'] < 0.999:
                mat['alpha'] = 'blend'
            if info['map']:
                fn = os.path.join(base, info['map'].replace('\\', '/'))
                if fn not in img_of:
                    if os.path.exists(fn):
                        with open(fn, 'rb') as f:
                            images.append(dict(name=os.path.basename(fn), data=f.read()))
                        img_of[fn] = len(images) - 1
                    else:
                        img_of[fn] = None
                mat['image'] = img_of[fn]
        P = np.asarray(g['P'], np.float32)
        tris = np.asarray(g['tris'], np.int64)
        N = np.asarray(g['N'], np.float32) if g['hasN'] else None
        if N is not None and (np.linalg.norm(N, axis=1) < 0.5).any():
            fix = smooth_normals(P, tris)
            bad = np.linalg.norm(N, axis=1) < 0.5
            N[bad] = fix[bad]
        UV = np.asarray(g['UV'], np.float32) if g['hasUV'] else None
        parts.append(Part(m or os.path.splitext(os.path.basename(path))[0], P, N, UV, tris, mat))
    return Scene(parts, images, os.path.basename(path))


def read(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.glb', '.gltf'):
        return read_gltf(path)
    if ext == '.obj':
        return read_obj(path)
    raise MeshTexError('use a .glb, .gltf or .obj file')
