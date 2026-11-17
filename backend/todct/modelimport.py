"""Model importer core: a textured mesh file (todct.meshtex) -> everything a TOD model record needs.

  transform   axes, handedness, turn, scale, origin  (one function: the preview and the build both use it)
  reduce      vertex clustering toward a triangle target (keeps texture seams: vertices merge only when both position and
              texture coordinate are close)
  bake        game-space sub-mesh groups (one per texture), the textures as TOD payloads, the collision pieces, the numbers
              the ledger and the checks need
  glb         a textured .glb of the baked result in the editor's view axes (the preview shows what was encoded)

Game axes: left-handed, y up, metres. A glTF/OBJ file is right-handed y up, so the default is to negate z ('mirror': 'z'); a
Z-up file is turned first ('up': 'z'). Everything is a parameter of the import; nothing is guessed after the fact.
"""
import hashlib
import io
import json
import math
import struct

import numpy as np

from . import texture as TX
from . import meshtex as MT

DEFAULTS = dict(up='y', mirror='z', yaw=0.0, scale=1.0, origin='bottom', reduce=1.0, max_tex=512, tex_format='auto',
                double_sided=True, collision=dict(mode='hull', material='Stone', max_pieces=24), keep_collision=True)
MAX_MESH_VERTS = 60000            # M1 is 65,535; split sub-meshes above this
SLOT_LIMIT_NOTE = 48              # shipped maximum textures per model (M3)
REFERENCE_FIGURE_M = 1.8          # the player's height, used by the scale tool's reference


class ImportError_(ValueError):
    pass


def params_of(p):
    q = json.loads(json.dumps(DEFAULTS))
    for k, v in (p or {}).items():
        if k == 'collision' and isinstance(v, dict):
            q['collision'].update(v)
        else:
            q[k] = v
    return q


# ---------------------------------------------------------------------------------------------- transform
def axis_matrix(params):
    A = np.eye(3)
    if params['up'] == 'z':
        A = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64) @ A
    elif params['up'] == '-y':
        A = np.diag([1.0, -1.0, 1.0]) @ A
    a = math.radians(float(params.get('yaw') or 0.0))
    c, s = math.cos(a), math.sin(a)
    A = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float64) @ A
    mir = params.get('mirror')
    if mir == 'z':
        A = np.diag([1.0, 1.0, -1.0]) @ A
    elif mir == 'x':
        A = np.diag([-1.0, 1.0, 1.0]) @ A
    return A


def transform(scene, params, ref=None):
    """-> list of MT.Part in game space (copies). ref: (min, max) of the model being replaced, for origin 'match'."""
    p = params_of(params)
    A = axis_matrix(p)
    s = float(p['scale'])
    parts = []
    for part in scene.parts:
        q = part.copy()
        q.P = ((part.P.astype(np.float64) @ A.T) * s).astype(np.float32)
        if part.N is not None:
            n = part.N.astype(np.float64) @ A.T
            q.N = (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)).astype(np.float32)
        parts.append(q)
    if not parts:
        raise ImportError_('nothing to import')
    allp = np.concatenate([q.P for q in parts]).astype(np.float64)
    mn, mx = allp.min(0), allp.max(0)
    o = p['origin']
    if o == 'bottom':
        shift = np.array([-(mn[0] + mx[0]) / 2, -mn[1], -(mn[2] + mx[2]) / 2])
    elif o == 'center':
        shift = -(mn + mx) / 2
    elif o == 'match' and ref is not None:
        rmn, rmx = np.asarray(ref[0], float), np.asarray(ref[1], float)
        shift = np.array([(rmn[0] + rmx[0]) / 2 - (mn[0] + mx[0]) / 2, rmn[1] - mn[1], (rmn[2] + rmx[2]) / 2 - (mn[2] + mx[2]) / 2])
    else:
        shift = np.zeros(3)
    for q in parts:
        q.P = (q.P.astype(np.float64) + shift).astype(np.float32)
        if q.N is None:
            q.N = MT.smooth_normals(q.P, q.tris)
    return parts


def bbox(parts):
    allp = np.concatenate([q.P for q in parts]).astype(np.float64)
    return allp.min(0), allp.max(0)


# ---------------------------------------------------------------------------------------------- reduce
def _cluster(part, cell, uv_cell=None):
    P = part.P.astype(np.float64)
    lo = P.min(0)
    if part.UV is not None:                      # texture cells follow the position cells, so only a real seam keeps two vertices apart
        uvd = float(np.linalg.norm(part.UV.max(0) - part.UV.min(0))) or 1.0
        pd = float(np.linalg.norm(P.max(0) - lo)) or 1.0
        uv_cell = cell * uvd / pd
    k = np.floor((P - lo) / cell).astype(np.int64)
    cols = [k[:, 0], k[:, 1], k[:, 2]]
    if part.UV is not None:
        u = np.floor(part.UV.astype(np.float64) / uv_cell).astype(np.int64)
        cols += [u[:, 0], u[:, 1]]
    key = np.stack(cols, 1)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    n = len(counts)
    out = np.zeros((n, 3))
    np.add.at(out, inv, P)
    out /= counts[:, None]
    N = None
    if part.N is not None:
        N = np.zeros((n, 3))
        np.add.at(N, inv, part.N.astype(np.float64))
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    UV = None
    if part.UV is not None:
        UV = np.zeros((n, 2))
        np.add.at(UV, inv, part.UV.astype(np.float64))
        UV /= counts[:, None]
    t = inv[part.tris]
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    t = t[ok]
    if len(t):
        srt = np.sort(t, axis=1)
        _, first = np.unique(srt, axis=0, return_index=True)
        t = t[np.sort(first)]
    q = MT.Part(part.name, out.astype(np.float32), None if N is None else N.astype(np.float32),
                None if UV is None else UV.astype(np.float32), t.astype(np.int64), dict(part.mat))
    return q


def reduce_parts(parts, ratio):
    """Vertex clustering toward `ratio` of the triangles (a ratio of 1 or more changes nothing)."""
    if ratio >= 0.999:
        return parts
    total = sum(len(p.tris) for p in parts)
    target = max(12, int(total * ratio))
    mn, mx = bbox(parts)
    diag = float(np.linalg.norm(mx - mn)) or 1.0
    lo, hi = diag / 8192.0, diag / 2.0
    best = None
    for _ in range(14):
        mid = math.sqrt(lo * hi)
        red = [_cluster(p, mid) for p in parts]
        n = sum(len(p.tris) for p in red)
        if n > target:
            lo = mid
        else:
            hi = mid
            best = red
    if best is None:
        best = [_cluster(p, hi) for p in parts]
    return [p for p in best if len(p.tris)]


# ---------------------------------------------------------------------------------------------- slots and textures
def _slot_key(part):
    m = part.mat
    if m.get('image') is not None:
        return ('img', m['image'], m['alpha'], round(float(m.get('cutoff', 0.5)), 3), tuple(round(c, 3) for c in m['color'][:3]))
    return ('col', tuple(round(c, 3) for c in m['color']), m['alpha'])


def _chunk(P, N, UV, tris, limit=MAX_MESH_VERTS):
    if len(P) <= limit:
        return [(P, N, UV, tris)]
    out = []
    for s in range(0, len(tris), 20000):
        t = tris[s:s + 20000]
        used, inv = np.unique(t.reshape(-1), return_inverse=True)
        out.append((P[used], N[used], UV[used], inv.reshape(-1, 3).astype(np.int64)))
    return out


def _texture_image(scene, key, params):
    """float RGBA for a slot (before sizing)."""
    if key[0] == 'img':
        data = scene.images[key[1]]['data']
        img = TX.read_image(data)
        col = np.asarray(key[4] + (1.0,), np.float32)
        if not np.allclose(col[:3], 1.0, atol=0.01):
            img = img.copy()
            img[..., :3] = np.clip(img[..., :3] * col[:3], 0, 1)
        return img
    c = np.asarray(key[1], np.float32)
    return np.broadcast_to(c, (4, 4, 4)).copy()


def _choose_format(img, alpha_kind, params):
    f = params['tex_format']
    if f in ('DXT1', 'RGBA32'):
        return f
    if alpha_kind == 'blend' and TX.has_alpha(img, 0.95):
        return 'RGBA32'
    return 'DXT1'


def slot_texture(scene, key, params, ov=None):
    """-> dict(img (pow2, edited), fmt, alpha_cut, w, h, source (w, h)) for one slot."""
    ov = ov or {}
    img = _texture_image(scene, key, params)
    sw, sh = img.shape[1], img.shape[0]
    alpha_kind = key[2] if key[0] == 'img' else key[2]
    if alpha_kind == 'opaque':
        img = img.copy()
        img[..., 3] = 1.0
    fmt = ov.get('fmt') or _choose_format(img, alpha_kind, params)
    cut = float(key[3]) if key[0] == 'img' and alpha_kind == 'mask' else 0.5
    maxdim = int(ov.get('max') or params['max_tex'])
    w, h = TX.pow2_near(sw), TX.pow2_near(sh)
    while max(w, h) > maxdim:
        w, h = max(w // 2, 1), max(h // 2, 1)
    if fmt == 'DXT1':
        w, h = max(w, 4), max(h, 4)
    w, h = TX.fit_for_cap(fmt, w, h)
    img = TX.resize(img, w, h) if (w, h) != (sw, sh) else img
    if fmt == 'DXT1' and alpha_kind == 'blend':
        img = img.copy()
        img[..., 3] = (img[..., 3] >= 0.5).astype(np.float32)
    return dict(img=img, fmt=fmt, alpha_cut=cut, w=w, h=h, source=(sw, sh), alpha=alpha_kind)


# ---------------------------------------------------------------------------------------------- bake
class Baked:
    """Everything a model record needs, in game space."""

    def __init__(self):
        self.groups = []         # dict(tex=int, P, N, UV, tris)   tris oriented the render way
        self.textures = []       # dict(key, fmt, w, h, levels, payload, alpha, preview(float RGBA of level 0 decoded), psnr)
        self.collision = []      # pieces (todct.collision piece json, model space)
        self.warnings = []
        self.stats = {}


def bake(scene, params, ref=None, with_payload=True, progress=None):
    p = params_of(params)
    parts = transform(scene, p, ref)
    n0 = sum(len(q.tris) for q in parts)
    parts = reduce_parts(parts, float(p['reduce']))
    parts = [q for q in parts if len(q.tris)]
    if not parts:
        raise ImportError_('nothing is left after the reduction')
    out = Baked()
    keys, slots = [], {}
    for q in parts:
        k = _slot_key(q)
        if k not in slots:
            slots[k] = []
            keys.append(k)
        slots[k].append(q)
    for ti, k in enumerate(keys):
        Ps, Ns, UVs, Ts, base = [], [], [], [], 0
        dbl = []
        for q in slots[k]:
            uv = q.UV if q.UV is not None else np.zeros((len(q.P), 2), np.float32)
            Ps.append(q.P)
            Ns.append(q.N)
            UVs.append(uv)
            Ts.append(q.tris + base)
            dbl.append(bool(q.mat.get('double_sided')))
            base += len(q.P)
        P, N, UV, T = np.concatenate(Ps), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Ts)
        if p['double_sided'] and k[2] != 'opaque' and any(dbl):
            m = len(P)
            P, N, UV = np.concatenate([P, P]), np.concatenate([N, -N]), np.concatenate([UV, UV])
            T = np.concatenate([T, T[:, [0, 2, 1]] + m])
        T = _orient(P, N, T)
        for (cp, cn, cu, ct) in _chunk(P, N, UV, T):
            out.groups.append(dict(tex=ti, P=cp, N=cn, UV=cu, tris=ct))
    tex_ov = (p.get('textures') or {})
    for ti, k in enumerate(keys):
        if progress:
            progress('texture %d / %d' % (ti + 1, len(keys)), ti, len(keys))
        ov = tex_ov.get(str(ti)) or {}
        st = slot_texture(scene, k, p, ov)
        rec = dict(key=list(k), fmt=st['fmt'], w=st['w'], h=st['h'], levels=TX.full_chain(st['w'], st['h']), alpha=st['alpha'],
                   source=list(st['source']), payload_bytes=TX.payload_size(st['fmt'], st['w'], st['h'], TX.full_chain(st['w'], st['h'])))
        if with_payload:
            pay, lv = TX.encode(st['img'], st['fmt'], st['alpha_cut'])
            dec = TX.decode_payload(pay, st['fmt'], st['w'], st['h'])
            rec.update(payload=pay, levels=lv, preview=dec, psnr=TX.psnr(st['img'], dec))
        out.textures.append(rec)
    allv = sum(len(g['P']) for g in out.groups)
    allt = sum(len(g['tris']) for g in out.groups)
    mn, mx = bbox(parts)
    ext = (mx - mn)
    out.stats = dict(vertices=int(allv), triangles=int(allt), triangles_in=int(n0), textures=len(out.textures),
                     max_mesh_vertices=int(max(len(g['P']) for g in out.groups)), submeshes=len(out.groups),
                     size=[round(float(x), 4) for x in ext], min=[round(float(x), 4) for x in mn], max=[round(float(x), 4) for x in mx],
                     texture_bytes=int(sum(t['payload_bytes'] for t in out.textures)),
                     largest_texture=int(max(t['payload_bytes'] for t in out.textures)),
                     record_bytes=int(allv * 32 + allt * 6))
    if len(out.textures) > SLOT_LIMIT_NOTE:
        out.warnings.append('%d textures: the largest shipped model holds %d' % (len(out.textures), SLOT_LIMIT_NOTE))
    cm = p['collision']
    if cm.get('mode') not in (None, 'none') and p.get('collision_build', True):
        out.collision = collision_pieces(parts, cm, out.warnings)
    return out


def _orient(P, N, T):
    """Shipped render triangles are wound against their normals (model_writer.orient_render); done here in numpy."""
    a, b, c = P[T[:, 0]].astype(np.float64), P[T[:, 1]].astype(np.float64), P[T[:, 2]].astype(np.float64)
    n = np.cross(b - a, c - a)
    vn = N[T[:, 0]].astype(np.float64) + N[T[:, 1]] + N[T[:, 2]]
    flip = (n * vn).sum(1) > 0
    T = T.copy()
    T[flip] = T[flip][:, [0, 2, 1]]
    keep = np.linalg.norm(n, axis=1) > 1e-14
    return T[keep]


def collision_pieces(parts, cm, warnings):
    """Convex pieces of the visible geometry (model space = game space here). mode: hull | solid | surface | box."""
    from . import collision as CO, geom
    mode = cm.get('mode') or 'hull'
    V, F, base = [], [], 0
    for q in parts:
        V.append(q.P.astype(np.float64))
        F += (q.tris + base).tolist()
        base += len(q.P)
    V = np.concatenate(V)
    mat = cm.get('material') or 'Stone'
    if mode == 'box':
        mn, mx = V.min(0), V.max(0)
        Vb, Fb = _box(mn, mx)
        return [CO.piece_json(Vb, Fb, mat)]
    log = []
    kw = {}
    if cm.get('max_pieces'):
        kw['max_pieces'] = int(cm['max_pieces'])
    try:
        pieces = CO.pieces_from_mesh(V, F, method=mode, material=mat, log=log, **kw)
    except Exception as e:                                   # noqa: BLE001
        warnings.append('collision: %s' % e)
        return []
    if not pieces:
        warnings.append('collision: no pieces came out of this mesh')
    return pieces


def _box(mn, mx):
    x0, y0, z0 = mn
    x1, y1, z1 = mx
    V = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3], [1, 2, 6, 5]]
    return V, F


# ---------------------------------------------------------------------------------------------- the model record's spec
ALPHA_BITS = {'mask': 0x40, 'cutout': 0x40, 'blend': 0x20}      # shipped meshes: cut-out foliage and signs 0x40, glass and glow 0x20
SMB_BASE = 0xBA1BC000


def smb_flags(alpha=None):
    """The submesh flags the engine's shipped meshes carry for a picture of this alpha kind ('opaque', 'mask'/'cutout', 'blend')."""
    return SMB_BASE | ALPHA_BITS.get(alpha or 'opaque', 0)


def mesh_dict(mw, g, texref, alpha=None):
    """A model_writer mesh from one baked group (alpha: the kind of its picture, which sets the cut-out / see-through flag)."""
    P = [tuple(float(x) for x in v) for v in g['P']]
    N = [tuple(float(x) for x in v) for v in g['N']]
    UV = [tuple(float(x) for x in v) for v in g['UV']]
    T = [tuple(int(x) for x in t) for t in g['tris']]
    return mw.mesh_from_triangles(P, N, UV, T, texrefs=[texref], smb_flags=smb_flags(alpha), mb_flags=0xBAADE000)


def hull_shapes(mw, pieces, pivot=0, aux=''):
    from . import surfaces
    out = []
    for i, pc in enumerate(pieces):
        V = [tuple(v) for v in pc['verts']]
        sh = mw.hull_shape(V, [list(f) for f in pc['faces']], pivot=pivot, surf=surfaces.parse_word(pc.get('surface', surfaces.DEFAULT_WORD)),
                           facemat=surfaces.material_index(pc.get('material', 'Stone')), aux_name=aux[:60])
        out.append(sh)
    return out


# ---------------------------------------------------------------------------------------------- preview glb
def _pad4(b, fill=b' '):
    return b + fill * ((4 - len(b) % 4) % 4)


def preview_glb(baked, with_textures=True, tint=None):
    """The baked model as a .glb in glTF axes (z negated: the editor places game models at (x, y, -z)); textures are the decoded payloads."""
    bin_ = bytearray()
    views, acc, imgs, texs, mats, meshes, nodes = [], [], [], [], [], [], []

    def add_view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), **({'target': target} if target else {})))
        bin_.extend(data)
        return len(views) - 1

    def add_acc(arr, comp, typ, target, mm=False):
        arr = np.ascontiguousarray(arr)
        v = add_view(arr.tobytes(), target)
        a = dict(bufferView=v, componentType=comp, count=int(arr.shape[0]) if typ != 'SCALAR' else int(arr.size), type=typ)
        if mm:
            a['min'], a['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        acc.append(a)
        return len(acc) - 1
    tex_of = {}
    for i, t in enumerate(baked.textures):
        if with_textures and 'preview' in t:
            png = TX.png_bytes(t['preview'])
            v = add_view(png)
            imgs.append(dict(bufferView=v, mimeType='image/png'))
            texs.append(dict(source=len(imgs) - 1, sampler=0))
            tex_of[i] = len(texs) - 1
    for i, t in enumerate(baked.textures):
        m = dict(name='tex%d' % i, doubleSided=True, pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=1.0))
        if i in tex_of:
            m['pbrMetallicRoughness']['baseColorTexture'] = dict(index=tex_of[i])
        if t['alpha'] != 'opaque':
            m['alphaMode'] = 'MASK' if t['fmt'] == 'DXT1' else 'BLEND'
            m['alphaCutoff'] = 0.5
        mats.append(m)
    for gi, g in enumerate(baked.groups):
        V = g['P'].astype(np.float32) * np.array([1, 1, -1], np.float32)
        Nn = g['N'].astype(np.float32) * np.array([1, 1, -1], np.float32)
        UV = g['UV'].astype(np.float32)
        pa = add_acc(V, 5126, 'VEC3', 34962, True)
        na = add_acc(Nn, 5126, 'VEC3', 34962)
        ua = add_acc(UV, 5126, 'VEC2', 34962)
        ia = add_acc(g['tris'].astype(np.uint32).reshape(-1), 5125, 'SCALAR', 34963)
        meshes.append(dict(name='m%d' % gi, primitives=[dict(attributes=dict(POSITION=pa, NORMAL=na, TEXCOORD_0=ua), indices=ia, material=g['tex'])]))
        nodes.append(dict(mesh=len(meshes) - 1, name='m%d' % gi))
    # the editor's mesh loader looks for a node called 'render' (as in the game's own model files)
    nodes.append(dict(name='render', children=list(range(len(nodes)))))
    js = dict(asset=dict(version='2.0', generator='todms'), scene=0, scenes=[dict(nodes=[len(nodes) - 1])], nodes=nodes, meshes=meshes,
              materials=mats, accessors=acc, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    if imgs:
        js['images'], js['textures'] = imgs, texs
        js['samplers'] = [dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)]
    jb = _pad4(json.dumps(js, separators=(',', ':')).encode('utf-8'))
    bb = _pad4(bytes(bin_), b'\0')
    return struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bb)) + struct.pack('<II', len(jb), 0x4E4F534A) + jb + \
        struct.pack('<II', len(bb), 0x004E4942) + bb


# ---------------------------------------------------------------------------------------------- scene blobs
def scene_to_bytes(scene):
    arrs, meta = {}, dict(source=scene.source, parts=[], images=[])
    for i, p in enumerate(scene.parts):
        arrs['P%d' % i] = p.P.astype(np.float32)
        arrs['T%d' % i] = p.tris.astype(np.int32)
        if p.N is not None:
            arrs['N%d' % i] = p.N.astype(np.float32)
        if p.UV is not None:
            arrs['U%d' % i] = p.UV.astype(np.float32)
        meta['parts'].append(dict(name=p.name, mat=p.mat))
    for i, im in enumerate(scene.images):
        arrs['I%d' % i] = np.frombuffer(im['data'], np.uint8)
        meta['images'].append(dict(name=im['name']))
    arrs['meta'] = np.frombuffer(json.dumps(meta).encode('utf-8'), np.uint8)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrs)
    return buf.getvalue()


def scene_from_bytes(data):
    z = np.load(io.BytesIO(data))
    meta = json.loads(bytes(z['meta']).decode('utf-8'))
    parts = []
    for i, pm in enumerate(meta['parts']):
        parts.append(MT.Part(pm['name'], z['P%d' % i], z['N%d' % i] if 'N%d' % i in z else None, z['U%d' % i] if 'U%d' % i in z else None,
                             z['T%d' % i].astype(np.int64), pm['mat']))
    images = [dict(name=im['name'], data=bytes(z['I%d' % i])) for i, im in enumerate(meta['images'])]
    return MT.Scene(parts, images, meta['source'])


def sha_of(data):
    return hashlib.sha256(data).hexdigest()[:32]
