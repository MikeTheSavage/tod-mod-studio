"""Small synthetic mesh files in the shapes real exporters write (Blender 2.79 OBJ, 2.93 / 4.x / 5.x glTF), plus the odd ones.
Used by test_import_formats.py and by the corpus builder of the importer."""
import base64
import json
import os
import struct

import numpy as np

QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
CUBE_V = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_F = [(1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 8, 4), (5, 1, 4, 8)]


def png(w=8, h=8, rgb=(200, 50, 20)):
    from todct import texture as TX
    a = np.zeros((h, w, 4), np.float32)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3] = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0
    a[::2, ::2, :3] = 0.1
    return TX.png_bytes(a)


def write(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
    return path


# ------------------------------------------------------------------------------------------------ OBJ (Blender 2.79 exporter)
def obj_279(d, name='cube279', tex_line='map_Kd C:\\Users\\gone\\Desktop\\tex.png', usemtl='Material', tex_in=None, crlf=False, extra=''):
    """The text Blender 2.79's OBJ exporter writes: header, mtllib, o, v, vt, vn, usemtl, s off, f v/vt/vn."""
    L = ["# Blender v2.79 (sub 0) OBJ File: 'untitled.blend'", '# www.blender.org', 'mtllib %s.mtl' % name, 'o Cube']
    L += ['v %f %f %f' % v for v in CUBE_V]
    L += ['vt 0.000100 0.000100', 'vt 0.999900 0.000100', 'vt 0.999900 0.999900', 'vt 0.000100 0.999900']
    L += ['vn 0.0000 0.0000 -1.0000']
    if usemtl is not None:
        L.append('usemtl ' + usemtl)
    L.append('s off')
    for f in CUBE_F:
        L.append('f ' + ' '.join('%d/%d/1' % (v, i + 1) for i, v in enumerate(f)))
    L.append(extra)
    nl = '\r\n' if crlf else '\n'
    write(os.path.join(d, name + '.obj'), nl.join(L) + nl)
    M = ['# Blender MTL File: \'None\'', '# Material Count: 1', '', 'newmtl Material', 'Ns 96.078431', 'Ka 1.000000 1.000000 1.000000',
         'Kd 0.640000 0.640000 0.640000', 'Ks 0.500000 0.500000 0.500000', 'Ke 0.000000 0.000000 0.000000', 'Ni 1.000000', 'd 1.000000', 'illum 2']
    if tex_line:
        M.append(tex_line)
    write(os.path.join(d, name + '.mtl'), nl.join(M) + nl)
    if tex_in:
        write(os.path.join(d, tex_in), png())
    return os.path.join(d, name + '.obj')


def obj_text(d, text, name='x', mtl=None):
    write(os.path.join(d, name + '.obj'), text)
    if mtl is not None:
        write(os.path.join(d, name + '.mtl'), mtl)
    return os.path.join(d, name + '.obj')


# ------------------------------------------------------------------------------------------------ glTF builder
class G:
    """A glTF 2.0 document under construction. Buffer 0 is binary; `finish_*` writes it as .glb, .gltf + .bin, or embedded."""

    def __init__(self, generator='Khronos glTF Blender I/O v1.7.33'):
        self.js = dict(asset=dict(version='2.0', generator=generator), scene=0, scenes=[dict(nodes=[])], nodes=[], meshes=[], accessors=[],
                       bufferViews=[], buffers=[dict(byteLength=0)])
        self.bin = bytearray()

    def view(self, data, stride=None, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = dict(buffer=0, byteOffset=len(self.bin), byteLength=len(data))
        if stride:
            bv['byteStride'] = stride
        if target:
            bv['target'] = target
        self.bin += data
        self.js['bufferViews'].append(bv)
        return len(self.js['bufferViews']) - 1

    def acc(self, arr, ctype, typ, normalized=False, stride_pad=0, **kw):
        arr = np.asarray(arr)
        dt = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32, 5120: np.int8, 5122: np.int16}[ctype]
        arr = arr.astype(dt)
        n = arr.shape[0]
        nc = 1 if arr.ndim == 1 else arr.shape[1]
        if stride_pad:
            rows = b''.join(arr[i].tobytes() + b'\0' * stride_pad for i in range(n))
            bv = self.view(rows, stride=nc * arr.itemsize + stride_pad)
        else:
            bv = self.view(arr.tobytes())
        a = dict(bufferView=bv, componentType=ctype, count=n, type=typ)
        if normalized:
            a['normalized'] = True
        if typ in ('VEC3',) and ctype == 5126:
            a['min'], a['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        a.update(kw)
        self.js['accessors'].append(a)
        return len(self.js['accessors']) - 1

    def prim(self, P, tris=None, uv=None, normals=True, material=None, index_type=5123, mode=4, uv1=None, extra_attr=None):
        P = np.asarray(P, np.float32)
        at = dict(POSITION=self.acc(P, 5126, 'VEC3'))
        if normals:
            at['NORMAL'] = self.acc(np.tile([0, 0, 1], (len(P), 1)), 5126, 'VEC3')
        if uv is not None:
            at['TEXCOORD_0'] = self.acc(uv, 5126, 'VEC2')
        if uv1 is not None:
            at['TEXCOORD_1'] = self.acc(uv1, 5126, 'VEC2')
        at.update(extra_attr or {})
        p = dict(attributes=at, mode=mode)
        if tris is not None:
            p['indices'] = self.acc(np.asarray(tris).reshape(-1), index_type, 'SCALAR')
        if material is not None:
            p['material'] = material
        return p

    def mesh(self, prims, name='Mesh', node=True, **nodekw):
        self.js['meshes'].append(dict(name=name, primitives=prims))
        if node:
            self.js['nodes'].append(dict(name=name, mesh=len(self.js['meshes']) - 1, **nodekw))
            self.js['scenes'][0]['nodes'].append(len(self.js['nodes']) - 1)

    def image_view(self, data, mime='image/png'):
        bv = self.view(data)
        self.js.setdefault('images', []).append(dict(bufferView=bv, mimeType=mime))
        self.js.setdefault('textures', []).append(dict(source=len(self.js['images']) - 1))
        return len(self.js['textures']) - 1

    def image_uri(self, uri):
        self.js.setdefault('images', []).append(dict(uri=uri))
        self.js.setdefault('textures', []).append(dict(source=len(self.js['images']) - 1))
        return len(self.js['textures']) - 1

    def material(self, tex=None, color=None, **kw):
        pbr = {}
        if tex is not None:
            pbr['baseColorTexture'] = tex if isinstance(tex, dict) else dict(index=tex)
        if color:
            pbr['baseColorFactor'] = color
        pbr.update(metallicFactor=0.0, roughnessFactor=0.5)
        self.js.setdefault('materials', []).append(dict(name='Material', pbrMetallicRoughness=pbr, **kw))
        return len(self.js['materials']) - 1

    def _json(self):
        js = json.loads(json.dumps(self.js))
        js['buffers'][0]['byteLength'] = len(self.bin)
        return js

    def glb(self, path, pad=b' '):
        js = json.dumps(self._json()).encode()
        js += pad * (-len(js) % 4)
        b = bytes(self.bin) + b'\0' * (-len(self.bin) % 4)
        data = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(b))
        data += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(b), 0x004E4942) + b
        return write(path, data)

    def gltf(self, path, binname=None, bom=False, embedded=False):
        js = self._json()
        if embedded:
            js['buffers'][0]['uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(bytes(self.bin)).decode()
        else:
            binname = binname or os.path.splitext(os.path.basename(path))[0] + '.bin'
            js['buffers'][0]['uri'] = binname.replace(' ', '%20')
            write(os.path.join(os.path.dirname(path), binname), bytes(self.bin))
        text = json.dumps(js, indent=2)
        return write(path, (b'\xef\xbb\xbf' if bom else b'') + text.encode())


def quad_prim(g, **kw):
    return g.prim(QUAD, [0, 1, 2, 0, 2, 3], uv=[(0, 1), (1, 1), (1, 0), (0, 0)], **kw)
