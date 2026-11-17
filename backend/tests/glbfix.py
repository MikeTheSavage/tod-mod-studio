"""A tiny textured .glb made in code (tests and proofs): a box (or a crate with a lid) with a PNG texture and UVs, y up, right handed."""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def checker_png(n=64, a=(200, 120, 50), b=(60, 30, 10)):
    from todct import texture as TX
    yy, xx = np.mgrid[0:n, 0:n]
    c = (((yy // 8) + (xx // 8)) % 2)[..., None]
    img = np.where(c, np.array(a, np.uint8), np.array(b, np.uint8)).astype(np.uint8)
    # some detail so the encoder has something to do
    img = np.clip(img.astype(np.int32) + (np.sin(xx * 0.7) * 12).astype(np.int32)[..., None], 0, 255).astype(np.uint8)
    return TX.png_bytes(img)


def box_arrays(size=(1.0, 1.0, 1.0), centre=(0.0, 0.5, 0.0)):
    sx, sy, sz = [s / 2 for s in size]
    cx, cy, cz = centre
    faces = [((1, 0, 0), [(sx, -sy, -sz), (sx, sy, -sz), (sx, sy, sz), (sx, -sy, sz)]),
             ((-1, 0, 0), [(-sx, -sy, sz), (-sx, sy, sz), (-sx, sy, -sz), (-sx, -sy, -sz)]),
             ((0, 1, 0), [(-sx, sy, -sz), (-sx, sy, sz), (sx, sy, sz), (sx, sy, -sz)]),
             ((0, -1, 0), [(-sx, -sy, sz), (-sx, -sy, -sz), (sx, -sy, -sz), (sx, -sy, sz)]),
             ((0, 0, 1), [(sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz), (-sx, -sy, sz)]),
             ((0, 0, -1), [(-sx, -sy, -sz), (-sx, sy, -sz), (sx, sy, -sz), (sx, -sy, -sz)])]
    P, N, T, I = [], [], [], []
    for n, quad in faces:
        b = len(P)
        for k, v in enumerate(quad):
            P.append((v[0] + cx, v[1] + cy, v[2] + cz))
            N.append(n)
            T.append([(0, 1), (0, 0), (1, 0), (1, 1)][k])
        I += [b, b + 1, b + 2, b, b + 2, b + 3]
    return np.array(P, np.float32), np.array(N, np.float32), np.array(T, np.float32), np.array(I, np.uint16)


def write_box_glb(path, size=(1.0, 1.0, 1.0), centre=(0.0, 0.5, 0.0), png=None, extra_boxes=0):
    png = png or checker_png()
    P, N, T, I = box_arrays(size, centre)
    for k in range(extra_boxes):               # more geometry: a stack of boxes (the reduce test)
        p2, n2, t2, i2 = box_arrays((size[0] * 0.8, size[1] * 0.2, size[2] * 0.8), (centre[0], centre[1] + size[1] / 2 + 0.1 * (k + 1), centre[2]))
        I = np.concatenate([I, i2 + len(P)])
        P, N, T = np.concatenate([P, p2]), np.concatenate([N, n2]), np.concatenate([T, t2])
    bin_ = bytearray()
    views = []

    def add(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        v = dict(buffer=0, byteOffset=len(bin_), byteLength=len(data))
        if target:
            v['target'] = target
        views.append(v)
        bin_.extend(data)
        return len(views) - 1
    vp, vn, vt, vi, vimg = add(P.tobytes(), 34962), add(N.tobytes(), 34962), add(T.tobytes(), 34962), add(I.astype(np.uint16).tobytes(), 34963), add(png)
    js = dict(asset=dict(version='2.0'), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0, name='crate')],
              meshes=[dict(name='crate', primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, TEXCOORD_0=2), indices=3, material=0)])],
              materials=[dict(name='wood', pbrMetallicRoughness=dict(baseColorTexture=dict(index=0), metallicFactor=0.0))],
              textures=[dict(source=0)], images=[dict(bufferView=vimg, mimeType='image/png')],
              accessors=[dict(bufferView=vp, componentType=5126, count=len(P), type='VEC3', min=P.min(0).tolist(), max=P.max(0).tolist()),
                         dict(bufferView=vn, componentType=5126, count=len(N), type='VEC3'),
                         dict(bufferView=vt, componentType=5126, count=len(T), type='VEC2'),
                         dict(bufferView=vi, componentType=5123, count=len(I), type='SCALAR')],
              bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    jb = json.dumps(js).encode()
    jb += b' ' * ((4 - len(jb) % 4) % 4)
    bb = bytes(bin_) + b'\0' * ((4 - len(bin_) % 4) % 4)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bb)))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A) + jb)
        f.write(struct.pack('<II', len(bb), 0x004E4942) + bb)
    return path


def barrel_arrays(radius=0.3, height=0.9, seg=32):
    """A barrel: side with a bulge and two lids, y up, right handed, UV u around, v along (0 at the top)."""
    P, N, T, I = [], [], [], []
    rings = 7
    for r in range(rings):
        t = r / (rings - 1)
        y = t * height
        rad = radius * (1.0 + 0.12 * np.sin(np.pi * t))
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            P.append((rad * np.cos(a), y, rad * np.sin(a)))
            N.append((np.cos(a), 0.0, np.sin(a)))
            T.append((s / seg * 2.0, 1.0 - t))
    W = seg + 1
    for r in range(rings - 1):
        for s in range(seg):
            a, b, c, d = r * W + s, r * W + s + 1, (r + 1) * W + s, (r + 1) * W + s + 1
            I += [a, c, b, b, c, d]
    for top in (0, 1):
        y = height if top else 0.0
        rad = radius
        base = len(P)
        P.append((0.0, y, 0.0)); N.append((0.0, 1.0 if top else -1.0, 0.0)); T.append((0.5, 0.5))
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            P.append((rad * np.cos(a), y, rad * np.sin(a))); N.append((0.0, 1.0 if top else -1.0, 0.0))
            T.append((0.5 + 0.5 * np.cos(a), 0.5 + 0.5 * np.sin(a)))
        for s in range(seg):
            I += [base, base + 1 + s + 1, base + 1 + s] if top else [base, base + 1 + s, base + 1 + s + 1]
    return np.array(P, np.float32), np.array(N, np.float32), np.array(T, np.float32), np.array(I, np.uint32)


def barrel_png(n=128):
    from todct import texture as TX
    yy, xx = np.mgrid[0:n, 0:n]
    plank = ((xx // 8) % 2)[..., None]
    wood = np.where(plank, np.array([150, 98, 52]), np.array([128, 80, 40])).astype(np.float64)
    grain = (np.sin(yy * 0.35 + xx * 0.05) * 9)[..., None]
    img = wood + grain
    hoop = ((yy % 64 < 6))[..., None]
    img = np.where(hoop, np.array([70, 70, 76]), img)
    return TX.png_bytes(np.clip(img, 0, 255).astype(np.uint8))


def write_barrel_glb(path, **kw):
    P, N, T, I = barrel_arrays(**kw)
    png = barrel_png()
    bin_ = bytearray()
    views = []

    def add(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        v = dict(buffer=0, byteOffset=len(bin_), byteLength=len(data))
        if target:
            v['target'] = target
        views.append(v)
        bin_.extend(data)
        return len(views) - 1
    vp, vn, vt, vi, vimg = add(P.tobytes(), 34962), add(N.tobytes(), 34962), add(T.tobytes(), 34962), add(I.tobytes(), 34963), add(png)
    js = dict(asset=dict(version='2.0'), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0, name='barrel')],
              meshes=[dict(name='barrel', primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, TEXCOORD_0=2), indices=3, material=0)])],
              materials=[dict(name='wood', pbrMetallicRoughness=dict(baseColorTexture=dict(index=0), metallicFactor=0.0))],
              textures=[dict(source=0)], images=[dict(bufferView=vimg, mimeType='image/png')],
              accessors=[dict(bufferView=vp, componentType=5126, count=len(P), type='VEC3', min=P.min(0).tolist(), max=P.max(0).tolist()),
                         dict(bufferView=vn, componentType=5126, count=len(N), type='VEC3'),
                         dict(bufferView=vt, componentType=5126, count=len(T), type='VEC2'),
                         dict(bufferView=vi, componentType=5125, count=len(I), type='SCALAR')],
              bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    jb = json.dumps(js).encode()
    jb += b' ' * ((4 - len(jb) % 4) % 4)
    bb = bytes(bin_) + b'\0' * ((4 - len(bin_) % 4) % 4)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bb)))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A) + jb)
        f.write(struct.pack('<II', len(bb), 0x004E4942) + bb)
    return path
