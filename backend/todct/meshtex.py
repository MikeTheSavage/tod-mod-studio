"""Textured mesh reader for the model importer: glTF 2.0 (.glb / .gltf) and Wavefront OBJ (+ .mtl) into parts that keep
positions, normals, texture coordinates and the colour texture of each material.

Everything stays in the FILE's axes (right-handed, y up, metres for glTF; OBJ is taken the same way). The importer's
transform (axes, handedness, scale, origin) is applied afterwards, so the preview and the build use one function.
Texture coordinates leave this module in the D3D convention (v down), the one the game's textures use.
"""
import math
import os
import re

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
    def __init__(self, parts, images, source, warnings=None):
        self.parts, self.images, self.source = parts, images, source
        self.warnings = list(warnings or [])          # short plain lines: what was ignored or fell back

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


# ---------------------------------------------------------------------------------------------- shared helpers
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.tif', '.tiff', '.webp')


def _decodable(data):
    from . import texture as TX
    try:
        TX.read_image(data)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def _warn_once(lst, text):
    if text not in lst:
        lst.append(text)


def _finite_parts(parts, warnings):
    """Drop triangles that point outside their vertices or at non-finite points; a part with nothing left goes."""
    out = []
    for p in parts:
        ok = np.isfinite(p.P).all(1)
        good = (p.tris >= 0).all(1) & (p.tris < len(p.P)).all(1)
        if not good.all():
            _warn_once(warnings, 'some faces point at missing points and were skipped')
            p.tris = p.tris[good]
        if not ok.all():
            _warn_once(warnings, 'some points are not numbers and their faces were skipped')
            p.tris = p.tris[ok[p.tris].all(1)] if len(p.tris) else p.tris
            p.P = np.nan_to_num(p.P)
        if len(p.tris):
            if p.N is not None and (len(p.N) != len(p.P) or not np.isfinite(p.N).all()):
                p.N = None
            if p.UV is not None and (len(p.UV) != len(p.P) or not np.isfinite(p.UV).all()):
                p.UV = None
            out.append(p)
    return out


# ---------------------------------------------------------------------------------------------- glTF
KNOWN_EXT = ('KHR_', 'EXT_texture_webp', 'EXT_mesh_gpu_instancing')


def _image_bytes(js, buffers, i, base):
    im = js['images'][i]
    if 'bufferView' in im:
        bv = js['bufferViews'][im['bufferView']]
        o = bv.get('byteOffset', 0)
        b = buffers[bv['buffer']]
        return None if b is None else b[o:o + bv['byteLength']]
    uri = im.get('uri') or ''
    if uri.startswith('data:'):
        import base64
        try:
            return base64.b64decode(uri.split(',', 1)[1])
        except Exception:                                   # noqa: BLE001
            return None
    from urllib.parse import unquote
    for cand in (unquote(uri), uri):
        cand = cand.replace('\\', '/')
        for p in (os.path.join(base, cand), os.path.join(base, os.path.basename(cand))):
            if os.path.isfile(p):
                with open(p, 'rb') as f:
                    return f.read()
    return None


def _uv_matrix(info):
    """KHR_texture_transform of a texture reference -> 3x3 matrix or None."""
    t = (info.get('extensions') or {}).get('KHR_texture_transform')
    if not t:
        return None
    off = t.get('offset', [0, 0])
    r = float(t.get('rotation', 0.0))
    sc = t.get('scale', [1, 1])
    T = np.array([[1, 0, off[0]], [0, 1, off[1]], [0, 0, 1]], np.float64)
    R = np.array([[math.cos(r), math.sin(r), 0], [-math.sin(r), math.cos(r), 0], [0, 0, 1]], np.float64)
    S = np.array([[sc[0], 0, 0], [0, sc[1], 0], [0, 0, 1]], np.float64)
    return T @ R @ S


def read_gltf(path):
    js, buffers = meshio._load_gltf(path)
    base = os.path.dirname(os.path.abspath(path))
    images, img_of_tex, warnings = [], {}, []
    nodes, texs, mats, meshes = js.get('nodes', []), js.get('textures', []), js.get('materials', []), js.get('meshes', [])
    for e in js.get('extensionsRequired') or []:
        if not str(e).startswith(KNOWN_EXT):
            _warn_once(warnings, 'some features of the file are not supported and were ignored')

    def image_for_texture(ti):
        if ti is None or not (0 <= ti < len(texs)):
            return None
        src = texs[ti].get('source')
        if src is None:
            for ext in (texs[ti].get('extensions') or {}).values():
                if isinstance(ext, dict):
                    src = ext.get('source', src)
        if src is None or not (0 <= src < len(js.get('images', []))):
            return None
        if src not in img_of_tex:
            data = _image_bytes(js, buffers, src, base)
            if data is None:
                _warn_once(warnings, 'a texture file is missing; its material colour is used')
                img_of_tex[src] = None
            elif not _decodable(data):
                _warn_once(warnings, 'a texture could not be read; its material colour is used')
                img_of_tex[src] = None
            else:
                images.append(dict(name=js['images'][src].get('name') or ('image%d' % src), data=data))
                img_of_tex[src] = len(images) - 1
        return img_of_tex[src]

    mat_cache = {}

    def material(mi):
        """-> (material dict, texture reference of the colour texture or {})"""
        if mi is None or not (0 <= mi < len(mats)):
            return default_material(), {}
        if mi in mat_cache:
            return mat_cache[mi]
        m = mats[mi]
        pbr = m.get('pbrMetallicRoughness') or {}
        sg = (m.get('extensions') or {}).get('KHR_materials_pbrSpecularGlossiness') or {}
        col = list(pbr.get('baseColorFactor') or sg.get('diffuseFactor') or [1, 1, 1, 1])
        col = (col + [1.0] * 4)[:4]
        ref = pbr.get('baseColorTexture') or sg.get('diffuseTexture') or {}
        r = default_material(m.get('name') or 'material%d' % mi)
        r.update(color=[float(x) for x in col], image=image_for_texture(ref.get('index')),
                 alpha={'OPAQUE': 'opaque', 'MASK': 'mask', 'BLEND': 'blend'}.get(m.get('alphaMode', 'OPAQUE'), 'opaque'),
                 cutoff=float(m.get('alphaCutoff', 0.5)), double_sided=bool(m.get('doubleSided')))
        mat_cache[mi] = (r, ref)
        return mat_cache[mi]

    parts = []
    skipped = [0]

    def emit(mi, M, nname, skinned):
        if not (0 <= mi < len(meshes)):
            return
        mesh = meshes[mi]
        nm = mesh.get('name') or nname or 'mesh%d' % mi
        if skinned:                                          # a skinned mesh sits where its joints put it, not where its node is
            M = np.eye(4)
        R = M[:3, :3]
        try:
            NM = np.linalg.inv(R).T
        except np.linalg.LinAlgError:
            NM = np.eye(3)
        flip = np.linalg.det(R) < 0
        prims = mesh.get('primitives', [])
        for pi, p in enumerate(prims):
            mode = p.get('mode', 4)
            at = p.get('attributes') or {}
            if mode not in (4, 5, 6):
                skipped[0] += 1
                continue
            if 'POSITION' not in at:
                continue
            P = meshio._accessor(js, buffers, at['POSITION']).astype(np.float64)
            if P.ndim != 2 or P.shape[1] != 3:
                raise meshio.MeshError('the file is damaged')
            P = (np.c_[P, np.ones(len(P))] @ M.T)[:, :3]
            N = None
            if 'NORMAL' in at:
                N = meshio._accessor(js, buffers, at['NORMAL']).astype(np.float64) @ NM.T
                ln = np.linalg.norm(N, axis=1, keepdims=True)
                N = (N / np.maximum(ln, 1e-12)).astype(np.float32)
            UV = None
            mat, ref = material(p.get('material'))
            tc = 'TEXCOORD_%d' % int(ref.get('texCoord', 0) or 0)
            xf = _uv_matrix(ref)
            tt = (ref.get('extensions') or {}).get('KHR_texture_transform') or {}
            if tt.get('texCoord') is not None:
                tc = 'TEXCOORD_%d' % int(tt['texCoord'])
            if tc not in at and 'TEXCOORD_0' in at:
                tc = 'TEXCOORD_0'
            if tc in at:
                UV = meshio._accessor(js, buffers, at[tc]).astype(np.float64)[:, :2]
                if xf is not None:
                    UV = (np.c_[UV, np.ones(len(UV))] @ xf.T)[:, :2]
                UV = UV.astype(np.float32)
            if 'indices' in p:
                idx = meshio._accessor(js, buffers, p['indices']).reshape(-1).astype(np.int64)
            else:
                idx = np.arange(len(P))
            if mode == 4:
                tris = idx[:len(idx) // 3 * 3].reshape(-1, 3)
            elif mode == 5:
                k = np.arange(max(len(idx) - 2, 0))
                even = (k % 2 == 0)
                tris = np.c_[idx[k], np.where(even, idx[k + 1], idx[k + 2]), np.where(even, idx[k + 2], idx[k + 1])] if len(k) else np.zeros((0, 3), np.int64)
            else:
                k = np.arange(1, max(len(idx) - 1, 1))
                tris = np.c_[np.full(len(k), idx[0]), idx[k], idx[k + 1]] if len(idx) > 2 else np.zeros((0, 3), np.int64)
            if flip:
                tris = tris[:, [0, 2, 1]]
            parts.append(Part('%s_%d' % (nm, pi) if len(prims) > 1 else nm, P.astype(np.float32), N, UV, tris, dict(mat)))

    def walk(ni, parent, depth=0):
        if not (0 <= ni < len(nodes)) or depth > 64:
            return
        n = nodes[ni]
        M = parent @ meshio._node_matrix(n)
        if 'mesh' in n:
            emit(n['mesh'], M, n.get('name'), 'skin' in n)
        for c in n.get('children', []):
            walk(c, M, depth + 1)
    sc = js.get('scenes') or []
    si = js.get('scene', 0)
    scene = sc[si] if sc and 0 <= si < len(sc) else (sc[0] if sc else None)
    if scene and scene.get('nodes') is not None:
        for ni in scene['nodes']:
            walk(ni, np.eye(4))
    else:
        for mi in range(len(meshes)):
            emit(mi, np.eye(4), None, False)
    if skipped[0]:
        _warn_once(warnings, 'lines and points in the file were skipped')
    parts = _finite_parts(parts, warnings)
    if not parts:
        raise MeshTexError('the file holds no triangle meshes')
    return Scene(parts, images, os.path.basename(path), warnings)


# ---------------------------------------------------------------------------------------------- OBJ
def _find_file(name, dirs):
    """A texture named by a file's own text: tolerate backslashes, quotes, Blender's // prefix, absolute paths of another
    machine, another case and another picture extension. -> path or None."""
    n = name.strip().strip('"').replace('\\', '/')
    if n.startswith('//'):
        n = n[2:]
    if not n:
        return None
    cands = [n] if (os.path.isabs(n) or re.match(r'^[A-Za-z]:/', n)) else []
    cands += [os.path.join(d, n) for d in dirs]
    cands += [os.path.join(d, os.path.basename(n)) for d in dirs]
    for c in cands:
        if os.path.isfile(c):
            return c
    stem = os.path.splitext(os.path.basename(n))[0].lower()
    want = os.path.basename(n).lower()
    for d in dirs:
        for depth, (root, subs, files) in enumerate(os.walk(d)):
            if depth > 2:
                break
            low = {f.lower(): f for f in files}
            if want in low:
                return os.path.join(root, low[want])
            for f in files:
                if os.path.splitext(f)[0].lower() == stem and f.lower().endswith(IMAGE_EXT):
                    return os.path.join(root, f)
    return None


_OPT_ARGS = {'-blendu': 1, '-blendv': 1, '-cc': 1, '-clamp': 1, '-imfchan': 1, '-mm': 2, '-o': 3, '-s': 3, '-t': 3, '-texres': 1, '-bm': 1, '-type': 1}


def _map_name(v):
    """The file of a `map_*` line: options (-s 1 1 1 -o 0 0 0 ...) come first, the file name (which may hold spaces) is the rest."""
    t = v.split()
    i = 0
    while i < len(t) and t[i].startswith('-') and t[i].lower() in _OPT_ARGS:
        i += 1 + _OPT_ARGS[t[i].lower()]
    rest = ' '.join(t[i:])
    if not rest and t:
        rest = t[-1]
    return rest.strip().strip('"')


def _floats(v, n):
    out = []
    for x in v.split()[:n]:
        try:
            out.append(float(x))
        except ValueError:
            return None
    return out


def _read_mtl(path):
    mats, cur = {}, None
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8-sig', errors='replace') as f:
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
                c = _floats(v, 3)
                if c:
                    cur['color'][:3] = (c * 3)[:3] if len(c) == 1 else (c + [0.0, 0.0])[:3]
            elif k == 'd':
                c = _floats(v.split()[-1], 1)
                if c:
                    cur['d'] = c[0]
            elif k == 'tr':
                c = _floats(v, 1)
                if c:
                    cur['d'] = 1.0 - c[0]
            elif k == 'map_kd':
                cur['map'] = _map_name(v) or None
    return mats


def read_obj(path):
    base = os.path.dirname(os.path.abspath(path))
    V, VT, VN = [], [], []
    groups = {}          # material name -> dict(corners {key: index}, P, N, UV, tris)
    order = []
    cur_mat = None
    mtl, warnings, mtl_dirs, mtllib_seen = {}, [], [base], False
    bad = [0]

    def grp(m):
        if m not in groups:
            groups[m] = dict(map={}, P=[], N=[], UV=[], tris=[], hasN=False, hasUV=False)
            order.append(m)
        return groups[m]

    def load_mtl(text):
        for cand in [text] + text.split():
            c = cand.strip().strip('"').replace('\\', '/')
            fn = os.path.join(base, c)
            if not os.path.isfile(fn):
                fn = os.path.join(base, os.path.basename(c))
            r = _read_mtl(fn)
            if r is not None:
                mtl.update(r)
                if os.path.dirname(fn) not in mtl_dirs:
                    mtl_dirs.append(os.path.dirname(fn))
                return True
        return False
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            s = line.split()
            if not s:
                continue
            k = s[0]
            try:
                if k == 'v':
                    if len(s) < 4:
                        raise ValueError
                    V.append([float(x) for x in s[1:4]])
                elif k == 'vt':
                    VT.append([float(s[1]), 1.0 - float(s[2]) if len(s) > 2 else 0.0])
                elif k == 'vn':
                    VN.append([float(x) for x in s[1:4]])
                elif k == 'mtllib':
                    mtllib_seen = True
                    rest = line.split(None, 1)[1].strip() if len(s) > 1 else ''
                    if rest and not load_mtl(rest):
                        _warn_once(warnings, 'the material file is missing; plain colours are used')
                elif k == 'usemtl':
                    nm = line.split(None, 1)[1].strip() if len(s) > 1 else ''
                    cur_mat = None if nm.lower() in ('', '(null)', 'none', 'null') else nm
                elif k == 'f':
                    ids = []
                    g = grp(cur_mat)
                    ok = True
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
                        if not (0 <= vi < len(V)) or ti >= len(VT) or ni >= len(VN) or ti < -1 or ni < -1:
                            ok = False
                            break
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
                    if not ok:
                        bad[0] += 1
                        continue
                    for q in range(1, len(ids) - 1):
                        g['tris'].append([ids[0], ids[q], ids[q + 1]])
            except (ValueError, IndexError):
                bad[0] += 1
    if bad[0]:
        _warn_once(warnings, 'some lines of the file could not be read and were skipped')
    if not mtllib_seen:                                       # a .mtl of the same name next to the file
        load_mtl(os.path.splitext(os.path.basename(path))[0] + '.mtl')
    if not order or not any(groups[m]['tris'] for m in order):
        raise MeshTexError('the file holds no faces')
    low = {k.lower(): k for k in mtl}
    images, img_of, parts = [], {}, []
    for m in order:
        g = groups[m]
        if not g['tris']:
            continue
        mat = default_material(m or 'material')
        info = mtl.get(m or '') or mtl.get(low.get((m or '').lower(), ''))
        if info:
            mat['color'] = list(info['color'][:3]) + [info['d']]
            if info['d'] < 0.999:
                mat['alpha'] = 'blend'
            if info['map']:
                fn = _find_file(info['map'], mtl_dirs)
                if fn not in img_of:
                    data = None
                    if fn is not None:
                        with open(fn, 'rb') as f:
                            data = f.read()
                    if fn is None:
                        _warn_once(warnings, 'a texture file is missing; its material colour is used')
                        img_of[fn] = None
                    elif not _decodable(data):
                        _warn_once(warnings, 'a texture could not be read; its material colour is used')
                        img_of[fn] = None
                    else:
                        images.append(dict(name=os.path.basename(fn), data=data))
                        img_of[fn] = len(images) - 1
                mat['image'] = img_of[fn]
        P = np.asarray(g['P'], np.float32)
        tris = np.asarray(g['tris'], np.int64)
        N = np.asarray(g['N'], np.float32) if g['hasN'] else None
        if N is not None and (np.linalg.norm(N, axis=1) < 0.5).any():
            fix = smooth_normals(P, tris)
            badn = np.linalg.norm(N, axis=1) < 0.5
            N[badn] = fix[badn]
        UV = np.asarray(g['UV'], np.float32) if g['hasUV'] else None
        parts.append(Part(m or os.path.splitext(os.path.basename(path))[0], P, N, UV, tris, mat))
    parts = _finite_parts(parts, warnings)
    if not parts:
        raise MeshTexError('the file holds no faces')
    return Scene(parts, images, os.path.basename(path), warnings)


def read(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.glb', '.gltf'):
        try:
            return read_gltf(path)
        except (meshio.MeshError, MeshTexError) as e:
            raise MeshTexError(str(e))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, OverflowError):
            raise MeshTexError('the file is damaged or not a valid glTF file')
    if ext == '.obj':
        try:
            return read_obj(path)
        except MeshTexError:
            raise
        except OSError:
            raise MeshTexError('the file could not be opened')
        except (KeyError, IndexError, TypeError, ValueError, MemoryError):
            raise MeshTexError('the file is damaged or not a valid OBJ file')
    raise MeshTexError('use a .glb, .gltf or .obj file')
