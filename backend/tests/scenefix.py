"""A small synthetic city as a .glb for the large-scene tests: ground, boxes, a duplicated draw, a stray island, a tiling material,
a cut-out picture, the same picture stored twice. Made in code; nothing from any real capture."""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def png(rgb=(200, 120, 50), n=16, alpha=None, seed=0):
    from todct import texture as TX
    rng = np.random.default_rng(seed)
    img = np.clip(np.asarray(rgb, np.float32)[None, None, :] + rng.integers(-20, 20, (n, n, 1)), 0, 255).astype(np.uint8)
    if alpha is not None:
        a = (alpha(n) * 255).astype(np.uint8)[..., None]
        img = np.concatenate([img, a], axis=2)
    return TX.png_bytes(img, alpha=alpha is not None)


def grid_plane(x0, z0, x1, z1, n, y=0.0, uv_scale=1.0):
    xs = np.linspace(x0, x1, n + 1)
    zs = np.linspace(z0, z1, n + 1)
    P = np.array([(x, y, z) for z in zs for x in xs], np.float32)
    UV = np.array([((x - x0) / (x1 - x0) * uv_scale, (z - z0) / (z1 - z0) * uv_scale) for z in zs for x in xs], np.float32)
    T = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            T += [[a, a + n + 1, a + 1], [a + 1, a + n + 1, a + n + 2]]
    N = np.tile(np.array([[0, 1, 0]], np.float32), (len(P), 1))
    return P, N, UV, np.array(T, np.int64)


def box(cx, cz, w, d, h, base=0.0):
    x0, x1, z0, z1, y0, y1 = cx - w / 2, cx + w / 2, cz - d / 2, cz + d / 2, base, base + h
    faces = [((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ((-1, 0, 0), [(x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0)]),
             ((0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
             ((0, 0, 1), [(x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)]),
             ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)])]
    P, N, UV, T = [], [], [], []
    for n, q in faces:
        b = len(P)
        for k, v in enumerate(q):
            P.append(v)
            N.append(n)
            UV.append([(0, 1), (0, 0), (1, 0), (1, 1)][k])
        T += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    return np.array(P, np.float32), np.array(N, np.float32), np.array(UV, np.float32), np.array(T, np.int64)


def write_glb(path, prims, images, materials, zup=False, rotation=None):
    """prims: [dict(P, N, UV, T, material)] in y-up axes. zup: store z-up positions and let the node turn them (a Blender export)."""
    bin_ = bytearray()
    views, acc, meshprims = [], [], []

    def add(arr, comp, typ, target):
        arr = np.ascontiguousarray(arr)
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=arr.nbytes, target=target))
        bin_.extend(arr.tobytes())
        a = dict(bufferView=len(views) - 1, componentType=comp, count=int(arr.shape[0]) if typ != 'SCALAR' else int(arr.size), type=typ)
        if typ == 'VEC3':
            a['min'], a['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        acc.append(a)
        return len(acc) - 1
    for pr in prims:
        P, N = pr['P'].astype(np.float32), pr['N'].astype(np.float32)
        if zup:                                   # file z = up; the node's +90 degrees about x turns it back (x, y, z) -> (x, -z, y)
            P = np.stack([P[:, 0], P[:, 2], -P[:, 1]], 1)
            N = np.stack([N[:, 0], N[:, 2], -N[:, 1]], 1)
        a = dict(POSITION=add(P, 5126, 'VEC3', 34962), NORMAL=add(N, 5126, 'VEC3', 34962), TEXCOORD_0=add(pr['UV'].astype(np.float32), 5126, 'VEC2', 34962))
        meshprims.append(dict(attributes=a, indices=add(pr['T'].astype(np.uint32).reshape(-1), 5125, 'SCALAR', 34963), material=pr['material']))
    img_js = []
    for im in images:
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(im)))
        bin_.extend(im)
        img_js.append(dict(bufferView=len(views) - 1, mimeType='image/png', name='pic%d' % len(img_js)))
    mats = []
    for m in materials:
        d = dict(name=m.get('name', 'mat'), doubleSided=m.get('double', True),
                 pbrMetallicRoughness=dict(baseColorTexture=dict(index=m['image']), metallicFactor=0))
        if m.get('alpha'):
            d['alphaMode'] = m['alpha']
        mats.append(d)
    node = dict(mesh=0, name='scene')
    if zup:
        node['rotation'] = [0.70710678, 0, 0, 0.70710678]
    js = dict(asset=dict(version='2.0'), scene=0, scenes=[dict(nodes=[0])], nodes=[node], meshes=[dict(primitives=meshprims)], materials=mats,
              textures=[dict(source=i) for i in range(len(images))], images=img_js, accessors=acc, bufferViews=views,
              buffers=[dict(byteLength=len(bin_))])
    jb = json.dumps(js).encode()
    jb += b' ' * (-len(jb) % 4)
    bb = bytes(bin_) + b'\0' * (-len(bin_) % 4)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bb)) + struct.pack('<II', len(jb), 0x4E4F534A) + jb +
                struct.pack('<II', len(bb), 0x004E4942) + bb)
    return path


def city(path, zup=False, big=False):
    """A 120 x 120 m block: ground (tiling uv), twelve boxes with four pictures (two of them the same pixels), a cut-out fence, a duplicated
    ground patch, and a tiny island 900 m away. -> dict of what is in it."""
    def cutout(n):
        a = np.ones((n, n), np.float32)
        a[:, ::4] = 0.0
        return a
    pics = [png((90, 90, 95), 32, seed=1),                       # 0 asphalt
            png((190, 120, 80), 16, seed=2),                     # 1 brick
            png((190, 120, 80), 16, seed=2),                     # 2 the same pixels again (a capture repeats pictures)
            png((70, 140, 70), 16, seed=3),                      # 3 grass
            png((200, 200, 210), 16, alpha=cutout, seed=4),      # 4 fence with holes
            png((200, 50, 50), 16, seed=6)]                      # 5 a sign whose uvs sit one whole repeat away from 0..1
    mats = [dict(name='asphalt', image=0), dict(name='brick_a', image=1), dict(name='brick_b', image=2), dict(name='grass', image=3),
            dict(name='fence', image=4, alpha='MASK'), dict(name='sign', image=5)]
    prims = []
    P, N, UV, T = grid_plane(-60, -60, 60, 60, 12 if not big else 40, 0.0, uv_scale=6.0)          # tiling uv: wraps outside 0..1
    prims.append(dict(P=P, N=N, UV=UV, T=T, material=0))
    P2, N2, UV2, T2 = grid_plane(-10, -10, 10, 10, 2, 0.001)                                      # a second draw over the same road (near duplicate)
    prims.append(dict(P=P2, N=N2, UV=UV2, T=T2, material=0))
    prims.append(dict(P=P2.copy(), N=N2.copy(), UV=UV2.copy(), T=T2.copy(), material=0))          # and an exact duplicate
    rng = np.random.default_rng(5)
    k = 0
    for gx in range(-40, 41, 27):
        for gz in range(-40, 41, 27):
            h = 6 + 4 * rng.random()
            P, N, UV, T = box(gx, gz, 10, 10, h)
            prims.append(dict(P=P, N=N, UV=UV, T=T, material=1 + (k % 2) if k < 8 else 3))
            k += 1
    P, N, UV, T = box(20, 50, 12, 0.2, 2.5)                                                       # the fence (cut-out)
    prims.append(dict(P=P, N=N, UV=UV, T=T, material=4))
    P, N, UV, T = box(-30, 52, 6, 0.3, 3, base=0.0)                                               # a sign: uvs shifted by whole repeats
    prims.append(dict(P=P, N=N, UV=UV + np.array([2.0, -1.0], np.float32), T=T, material=5))
    P, N, UV, T = box(900, 900, 3, 3, 3)                                                          # a stray island far away
    prims.append(dict(P=P, N=N, UV=UV, T=T, material=1))
    write_glb(path, prims, pics, mats, zup=zup)
    return dict(prims=len(prims), boxes=k, tris=sum(len(p['T']) for p in prims))
