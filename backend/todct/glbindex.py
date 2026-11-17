"""Streaming glTF/glb index for scenes too big to load at once (a captured city: millions of triangles, thousands of materials,
thousands of embedded pictures).

Nothing is decoded when the file is opened: the JSON is read, the binary part is memory-mapped, and every mesh primitive becomes one
row (name, material, vertex and triangle counts, the world box of its accessor min/max). Geometry is read per primitive on demand
(`positions`, `triangles`, `attributes`), pictures are returned as their stored bytes (`image_bytes`) and decoded by the caller only
for the pictures it needs.

Positions are returned in the file's world axes (node transforms applied, right-handed, y up for a normal glTF); the importer's own
axis step (`todct.modelimport.axis_matrix`) turns them into game axes afterwards.
"""
import base64
import json
import math
import os
import struct

import numpy as np

from . import meshio

COMP = meshio.COMP
NCOMP = meshio.NCOMP


class GlbError(ValueError):
    pass


def _read_json_chunk(path):
    with open(path, 'rb') as f:
        head = f.read(12)
        if head[:4] != b'glTF':
            f.seek(0)
            return json.loads(f.read().decode('utf-8')), None, None
        pos = 12
        total = struct.unpack_from('<I', head, 8)[0]
        js, bin_off, bin_len = None, None, None
        while pos < total:
            f.seek(pos)
            ln, typ = struct.unpack('<II', f.read(8))
            if typ == 0x4E4F534A:
                js = json.loads(f.read(ln).decode('utf-8'))
            elif typ == 0x004E4942:
                bin_off, bin_len = pos + 8, ln
            pos += 8 + ln
    if js is None:
        raise GlbError('no JSON chunk')
    return js, bin_off, bin_len


class GlbIndex:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.js, bo, bl = _read_json_chunk(path)
        js = self.js
        self.buffers = []
        base = os.path.dirname(self.path)
        for i, b in enumerate(js.get('buffers', [])):
            uri = b.get('uri')
            if uri is None:
                if bo is None:
                    raise GlbError('binary buffer missing')
                self.buffers.append(np.memmap(self.path, dtype=np.uint8, mode='r', offset=bo, shape=(bl,)))
            elif uri.startswith('data:'):
                self.buffers.append(np.frombuffer(base64.b64decode(uri.split(',', 1)[1]), dtype=np.uint8))
            else:
                from urllib.parse import unquote
                self.buffers.append(np.memmap(os.path.join(base, unquote(uri)), dtype=np.uint8, mode='r'))
        self.prims = []
        self._walk()
        if not self.prims:
            raise GlbError('the file holds no triangle meshes')
        self.node_rotation = self._detect_rotation()

    # ------------------------------------------------------------------------------------------ accessors
    def accessor(self, i):
        a = self.js['accessors'][i]
        bv = self.js['bufferViews'][a['bufferView']]
        dt = np.dtype(COMP[a['componentType']])
        nc = NCOMP[a['type']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = bv.get('byteStride') or dt.itemsize * nc
        buf = self.buffers[bv['buffer']]
        arr = np.ndarray(shape=(a['count'], nc), dtype=dt, buffer=buf, offset=off, strides=(stride, dt.itemsize))
        if a.get('normalized'):
            return arr.astype(np.float32) / float(np.iinfo(dt).max)
        return arr

    # ------------------------------------------------------------------------------------------ the primitive table
    def _walk(self):
        js = self.js
        mats = js.get('materials', [])

        def emit(mi, M, nname):
            mesh = js['meshes'][mi]
            R = M[:3, :3]
            flip = bool(np.linalg.det(R) < 0)
            for pi, p in enumerate(mesh.get('primitives', [])):
                if p.get('mode', 4) != 4 or 'POSITION' not in p['attributes']:
                    continue
                a = js['accessors'][p['attributes']['POSITION']]
                if 'min' in a and 'max' in a:
                    lo, hi = np.asarray(a['min'], np.float64)[:3], np.asarray(a['max'], np.float64)[:3]
                else:
                    P = self.accessor(p['attributes']['POSITION']).astype(np.float64)
                    lo, hi = P.min(0), P.max(0)
                corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ M.T
                n_idx = js['accessors'][p['indices']]['count'] if 'indices' in p else a['count']
                mat = p.get('material')
                self.prims.append(dict(
                    mesh=mi, prim=pi, name=(mesh.get('name') or nname or 'mesh%d' % mi) + ('_%d' % pi if len(mesh['primitives']) > 1 else ''),
                    material=mat if (mat is not None and mat < len(mats)) else None, verts=int(a['count']), tris=int(n_idx // 3),
                    lo=corners[:, :3].min(0), hi=corners[:, :3].max(0), M=M, flip=flip, attrs=p['attributes'], indices=p.get('indices'),
                    texcoord=self._texcoord_set(p)))

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

    def _texcoord_set(self, p):
        mi = p.get('material')
        if mi is None or mi >= len(self.js.get('materials', [])):
            return 0
        m = self.js['materials'][mi]
        pbr = m.get('pbrMetallicRoughness') or {}
        sg = (m.get('extensions') or {}).get('KHR_materials_pbrSpecularGlossiness') or {}
        return int((pbr.get('baseColorTexture') or sg.get('diffuseTexture') or {}).get('texCoord') or 0)

    def _detect_rotation(self):
        """The turn the file's nodes apply (degrees about x, y, z of the first primitive), 0 when none."""
        M = self.prims[0]['M'][:3, :3]
        s = np.linalg.norm(M, axis=0)
        R = M / np.maximum(s, 1e-12)
        sy = math.hypot(R[0, 0], R[1, 0])
        if sy > 1e-6:
            x, y, z = math.atan2(R[2, 1], R[2, 2]), math.atan2(-R[2, 0], sy), math.atan2(R[1, 0], R[0, 0])
        else:
            x, y, z = math.atan2(-R[1, 2], R[1, 1]), math.atan2(-R[2, 0], sy), 0.0
        return [round(math.degrees(v), 2) for v in (x, y, z)]

    # ------------------------------------------------------------------------------------------ materials and pictures
    def materials(self):
        """-> list of dict(name, image, color, alpha, cutoff, double_sided) in the file's material order."""
        js = self.js
        out = []
        for mi, m in enumerate(js.get('materials', [])):
            pbr = m.get('pbrMetallicRoughness') or {}
            sg = (m.get('extensions') or {}).get('KHR_materials_pbrSpecularGlossiness') or {}
            tex = (pbr.get('baseColorTexture') or sg.get('diffuseTexture') or {}).get('index')
            src = None
            if tex is not None and tex < len(js.get('textures', [])):
                t = js['textures'][tex]
                src = t.get('source')
                if src is None:
                    for ext in (t.get('extensions') or {}).values():
                        src = ext.get('source', src)
            out.append(dict(name=m.get('name') or 'material%d' % mi, image=src,
                            color=[float(x) for x in (pbr.get('baseColorFactor') or sg.get('diffuseFactor') or [1, 1, 1, 1])],
                            alpha={'OPAQUE': 'opaque', 'MASK': 'mask', 'BLEND': 'blend'}[m.get('alphaMode', 'OPAQUE')],
                            cutoff=float(m.get('alphaCutoff', 0.5)), double_sided=bool(m.get('doubleSided'))))
        return out

    def image_count(self):
        return len(self.js.get('images', []))

    def image_name(self, i):
        return self.js['images'][i].get('name') or 'image%d' % i

    def image_bytes(self, i):
        im = self.js['images'][i]
        if 'bufferView' in im:
            bv = self.js['bufferViews'][im['bufferView']]
            o = bv.get('byteOffset', 0)
            return bytes(self.buffers[bv['buffer']][o:o + bv['byteLength']])
        uri = im.get('uri') or ''
        if uri.startswith('data:'):
            return base64.b64decode(uri.split(',', 1)[1])
        from urllib.parse import unquote
        p = os.path.join(os.path.dirname(self.path), unquote(uri))
        if os.path.exists(p):
            with open(p, 'rb') as f:
                return f.read()
        return None

    # ------------------------------------------------------------------------------------------ geometry
    def positions(self, k):
        """World positions of primitive k (float32, node matrix applied)."""
        pr = self.prims[k]
        P = self.accessor(pr['attrs']['POSITION']).astype(np.float64)
        M = pr['M']
        if not np.allclose(M, np.eye(4)):
            P = P @ M[:3, :3].T + M[:3, 3]
        return P.astype(np.float32)

    def triangles(self, k):
        pr = self.prims[k]
        if pr['indices'] is not None:
            idx = np.asarray(self.accessor(pr['indices'])).reshape(-1).astype(np.int64)
        else:
            idx = np.arange(pr['verts'], dtype=np.int64)
        t = idx[:len(idx) // 3 * 3].reshape(-1, 3)
        return t[:, [0, 2, 1]] if pr['flip'] else t

    def normals(self, k):
        pr = self.prims[k]
        if 'NORMAL' not in pr['attrs']:
            return None
        N = self.accessor(pr['attrs']['NORMAL']).astype(np.float64)
        M = pr['M']
        R = M[:3, :3]
        try:
            NM = np.linalg.inv(R).T
        except np.linalg.LinAlgError:
            NM = np.eye(3)
        N = N @ NM.T
        return (N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)).astype(np.float32)

    def uvs(self, k):
        pr = self.prims[k]
        key = 'TEXCOORD_%d' % pr['texcoord']
        if key not in pr['attrs']:
            return None
        return np.asarray(self.accessor(pr['attrs'][key])).astype(np.float32)

    def close(self):
        for b in self.buffers:
            m = getattr(b, '_mmap', None)
            if m is not None:
                try:
                    m.close()
                except Exception:                            # noqa: BLE001
                    pass
        self.buffers = []
