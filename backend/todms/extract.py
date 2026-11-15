"""Mesh, texture and collision extraction into the local cache (from the user's own blocks).

Per model: one glb with two meshes,
  'render'    LOD0 render geometry (tools/tod_model_extract + tod_static_textured's pivot bake and LOD rule),
              materials carry extras.tod_texture = the texture asset name; the texture itself is served as a .dds
              (no decode, the viewer's GPU reads DXT directly)
  'collision' the model's collision hulls and boxes in model space (tools/collision/export_map: HullList +0x54 and
              the per-pivot lists +0x44), vertex-coloured by surface class
Handedness: TOD is left-handed y-up; the glb negates Z (positions and normals) and keeps the D3D index order, like
every exporter of the project. The viewer places a model at (x, y, -z) with quaternion (-qx, -qy, qz, qw).
"""
import json
import os
import struct

import tod_model_extract as me      # top-level vendored copy first (collision/proj holds an older one)
import tod_model_to_gltf as mg
import tod_static_textured as st
import tod_texture_extract as tx
import todblock as tb
import todcoll as tc
import sys as _sys
_before = list(_sys.path)
import export_map as ex
_sys.path[:] = [p for p in _sys.path if p in _before]     # export_map pushes collision/proj first

TEXTURE, MODEL = 0, 3
FORMATS = tx.FORMATS


class BlockAssets:
    """Model and texture records of one block, by lower-case asset name."""

    def __init__(self, raw, ext):
        self.b = tb.Block(raw, ext)
        self.info = bytes(self.b.info)
        self.starts = tb.record_starts(self.info, self.b.n)
        self.models, self.textures = {}, {}
        for k, R in enumerate(self.starts):
            t = tb.u32(self.info, R)
            if t == MODEL:
                self.models.setdefault(tb.record_name(self.info, R).lower(), (k, R))
            elif t == TEXTURE:
                self.textures.setdefault(tb.record_name(self.info, R).lower(), (k, R))

    # ------------------------------------------------------------------ textures
    def texture_dds(self, name):
        """-> (dds bytes, meta) or None. Formats the viewer cannot read natively are converted to A8R8G8B8."""
        hit = self.textures.get(name.lower())
        if hit is None:
            return None
        k, R = hit
        info = self.info
        gfx = tx.ptr(info, R + 0x28)
        if gfx is None or gfx + 0x29 > len(info):
            return None
        w, h = tb.u32(info, gfx + 0x14), tb.u32(info, gfx + 0x18)
        fmt = struct.unpack_from('<i', info, gfx + 0x1C)[0]
        mips = info[gfx + 0x28]
        data = self.b.payloads[k]
        if not (0 < w <= 8192 and 0 < h <= 8192 and 0 <= fmt < len(FORMATS) and data):
            return None
        meta = dict(w=w, h=h, fmt=FORMATS[fmt], alpha=False)
        if fmt in (7, 9, 11):                          # DXT1, DXT3, DXT5
            if fmt == 7:
                meta['alpha'] = dxt1_has_alpha(data, w, h)
            else:
                meta['alpha'] = True
            return tx.dds_header(w, h, fmt, max(1, mips), len(data)) + data, meta
        if fmt == 1:                                   # A8R8G8B8
            meta['alpha'] = True
            return tx.dds_header(w, h, 1, max(1, mips), len(data)) + data, meta
        rgba = convert_to_argb(data, w, h, fmt)
        if rgba is None:
            return None
        meta['alpha'] = fmt in (3, 4)
        return tx.dds_header(w, h, 1, 1, len(rgba)) + rgba, meta

    # ------------------------------------------------------------------ models
    def model_glb(self, name):
        hit = self.models.get(name.lower())
        if hit is None:
            return None
        k, R = hit
        return model_glb(self.info, R, name)


def dxt1_has_alpha(data, w, h):
    """True if any DXT1 block of the top mip uses the 1-bit transparent colour (c0 <= c1 and an index of 3)."""
    nb = max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
    n = min(nb, len(data) // 8)
    for i in range(n):
        c0, c1, bits = struct.unpack_from('<HHI', data, i * 8)
        if c0 <= c1:
            b = bits
            for _ in range(16):
                if b & 3 == 3:
                    return True
                b >>= 2
    return False


def convert_to_argb(data, w, h, fmt):
    n = w * h
    out = bytearray(n * 4)
    if fmt == 2 and len(data) >= n * 2:            # R5G6B5
        for i, (v,) in enumerate(struct.iter_unpack('<H', data[:n * 2])):
            out[i * 4:i * 4 + 4] = bytes((((v & 31) * 255) // 31, (((v >> 5) & 63) * 255) // 63,
                                          ((v >> 11) * 255) // 31, 255))
        return bytes(out)
    if fmt == 3 and len(data) >= n * 2:            # A1R5G5B5
        for i, (v,) in enumerate(struct.iter_unpack('<H', data[:n * 2])):
            out[i * 4:i * 4 + 4] = bytes((((v & 31) * 255) // 31, (((v >> 5) & 31) * 255) // 31,
                                          (((v >> 10) & 31) * 255) // 31, 255 if v & 0x8000 else 0))
        return bytes(out)
    if fmt == 4 and len(data) >= n * 2:            # A4R4G4B4
        for i, (v,) in enumerate(struct.iter_unpack('<H', data[:n * 2])):
            out[i * 4:i * 4 + 4] = bytes(((v & 15) * 17, ((v >> 4) & 15) * 17, ((v >> 8) & 15) * 17,
                                          ((v >> 12) & 15) * 17))
        return bytes(out)
    if fmt == 0 and len(data) >= n * 3:            # R8G8B8 (B, G, R in memory)
        for i in range(n):
            out[i * 4:i * 4 + 4] = data[i * 3:i * 3 + 3] + b'\xff'
        return bytes(out)
    return None


# ---------------------------------------------------------------------- glb
class _Glb:
    def __init__(self):
        self.blob = bytearray()
        self.bv, self.acc, self.materials, self.meshes, self.nodes = [], [], [], [], []

    def _pack(self, data):
        while len(self.blob) % 4:
            self.blob.append(0)
        o = len(self.blob)
        self.blob.extend(data)
        self.bv.append({'buffer': 0, 'byteOffset': o, 'byteLength': len(data)})
        return len(self.bv) - 1

    def acc_add(self, data, comp, typ, count, mn=None, mx=None):
        a = {'bufferView': self._pack(data), 'componentType': comp, 'count': count, 'type': typ}
        if mn is not None:
            a['min'], a['max'] = mn, mx
        self.acc.append(a)
        return len(self.acc) - 1

    def prim(self, pos, idx, nrm=None, uv=None, col=None, material=None, extras=None):
        pmin = [min(p[i] for p in pos) for i in range(3)]
        pmax = [max(p[i] for p in pos) for i in range(3)]
        attrs = {'POSITION': self.acc_add(struct.pack('<%df' % (len(pos) * 3), *[c for p in pos for c in p]),
                                          5126, 'VEC3', len(pos), pmin, pmax)}
        if nrm:
            attrs['NORMAL'] = self.acc_add(struct.pack('<%df' % (len(nrm) * 3), *[c for n in nrm for c in n]),
                                           5126, 'VEC3', len(nrm))
        if uv:
            attrs['TEXCOORD_0'] = self.acc_add(struct.pack('<%df' % (len(uv) * 2), *[c for u in uv for c in u]),
                                               5126, 'VEC2', len(uv))
        if col:
            attrs['COLOR_0'] = self.acc_add(struct.pack('<%df' % (len(col) * 3), *[c for v in col for c in v]),
                                            5126, 'VEC3', len(col))
        big = max(idx) > 65535
        ia = self.acc_add(struct.pack('<%d%s' % (len(idx), 'I' if big else 'H'), *idx),
                          5125 if big else 5123, 'SCALAR', len(idx))
        p = {'attributes': attrs, 'indices': ia, 'mode': 4}
        if material is not None:
            p['material'] = material
        if extras:
            p['extras'] = extras
        return p

    def mesh(self, name, prims):
        if not prims:
            return
        self.meshes.append({'name': name, 'primitives': prims})
        self.nodes.append({'name': name, 'mesh': len(self.meshes) - 1})

    def bytes(self, extras=None):
        g = {'asset': {'version': '2.0', 'generator': 'TOD Mod Studio'}, 'scene': 0,
             'scenes': [{'nodes': list(range(len(self.nodes)))}], 'nodes': self.nodes, 'meshes': self.meshes,
             'accessors': self.acc, 'bufferViews': self.bv, 'buffers': [{'byteLength': len(self.blob)}]}
        if self.materials:
            g['materials'] = self.materials
        if extras:
            g['extras'] = extras
        j = json.dumps(g, separators=(',', ':')).encode('utf-8')
        while len(j) % 4:
            j += b' '
        b = bytes(self.blob) + b'\0' * ((4 - len(self.blob) % 4) % 4)
        return (b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + 8 + len(b)) + struct.pack('<I', len(j)) + b'JSON' +
                j + struct.pack('<I', len(b)) + b'BIN\x00' + b)


def model_glb(info, R, name):
    """-> (glb bytes, meta) for a model record."""
    g = _Glb()
    meta = dict(name=name, render_tris=0, coll_tris=0, textures=[])
    try:
        model = me.extract_model(info, R, name)
    except Exception as e:                      # damaged or unusual record: no render mesh
        model = None
        meta['error'] = str(e)[:200]
    prims = []
    if model and model['meshes']:
        st.bake_pivots(model, info, R)
        try:
            meshes = st.select_source_lod(model['meshes'], 0)
        except ValueError:
            meshes = model['meshes']
        mat_of = {}
        for mi, m in enumerate(meshes):
            if not m['verts']:
                continue
            idx = m['indices'] if m['isTriangles'] else st.me_strip(m['indices'])
            idx = idx[:len(idx) - len(idx) % 3]
            if not idx:
                continue
            pos = [(v[0][0], v[0][1], -v[0][2]) for v in m['verts']]
            nrm = [(v[3][0], v[3][1], -v[3][2]) for v in m['verts']]
            uv = [v[1] for v in m['verts']]
            ti = m.get('texidx', -1)
            if not (0 <= ti < len(model['textures'])):
                ti = mi if mi < len(model['textures']) else 0
            ref = model['textures'][ti] if model['textures'] else None
            if ref not in mat_of:
                mat = {'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 1.0}, 'doubleSided': True}
                if ref:
                    mat['extras'] = {'tod_texture': ref.lower()}
                    meta['textures'].append(ref.lower())
                g.materials.append(mat)
                mat_of[ref] = len(g.materials) - 1
            prims.append(g.prim(pos, idx, nrm, uv, material=mat_of[ref]))
            meta['render_tris'] += len(idx) // 3
    g.mesh('render', prims)
    # collision
    cpos, ccol, cidx = [], [], []
    try:
        PW = ex.pivot_world(info, R)
        shapes = ex.model_collision(info, R)
    except Exception:
        shapes, PW = [], []
    for space, pi, s in shapes:
        M = ex.IDENT if space == 'model' else (PW[pi] if 0 <= pi < len(PW) else ex.IDENT)
        cls = ex.surf_class(s['surf'])
        colr = ex.CLASS_COLOR[cls]
        if s['type'] == 4:
            verts = [ex.apply(M, v) for v in s['verts']]
            tris = [(f[0], f[k], f[k + 1]) for f in s['faces'] for k in range(1, len(f) - 1)]
        else:
            vs, tris = ex.box_corners_tris(s['size'], s['center'], s['quat'])
            verts = [ex.apply(M, v) for v in vs]
        base = len(cpos)
        for v in verts:
            cpos.append((v[0], v[1], -v[2]))
            ccol.append(colr)
        for t in tris:
            cidx += [base + t[0], base + t[1], base + t[2]]
    if cidx:
        g.mesh('collision', [g.prim(cpos, cidx, col=ccol)])
        meta['coll_tris'] = len(cidx) // 3
    meta['hulls'] = len(shapes)
    bound = None
    try:
        bound = list(struct.unpack_from('<4f', info, R + 0x44))
    except struct.error:
        pass
    meta['bound'] = bound
    if not g.meshes:
        return None, meta
    return g.bytes(extras=dict(tod_model=name)), meta
