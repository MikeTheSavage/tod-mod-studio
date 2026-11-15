"""TOD (Kapow) model writer: build a MODEL record from a semantic description (spec), deriving every computed field the
way the original exporter did. Works on top of todmodel (layout/pointers) and todcoll (collision shapes).

spec (Python dict; the CLI builds it from JSON + OBJ files):
  name        '/data/Models/.../X.model'   (the record name; keep an existing name to replace that model in place)
  textures    ['/data/textures/.../a.bmp', ...]   texture reference list (names must exist as TEXTURE assets in a
              loaded block)
  header      {'w18': 0xBA610000, 'w1c': 0x18, 'w5c': 0xBAADF020}     opaque words (defaults = the common values)
  sphere      None = derive (exporter rule), or (cx, cy, cz, r)
  cover_collision  True: grow the model sphere so it also encloses every collision vertex (the engine registers
              collision by this sphere, see docs/subsystem_collision.md 11.4); False = exporter rule only (rebuilds)
  pivots      [{name, name2, pos, quat (x,y,z,w as stored), parent, w5c (-1), w60 (1 mesh / 2 none),
                box: None = derive | (sx,sy,sz,cx,cy,cz),
                meshes: [{texrefs [i..], smb_flags 0xBA1BC000, mb_flags 0xBAADE000, kind 'base',
                          vb: {fvf 0x112, stride 32, decl 6, w16 0xBA01, w1c 0}, vertex_bytes (stride*n bytes),
                          indices [u16..], prim 'strip'|'list', ib: {w10 0xBAADF00D, w18 0},
                          v18 [], v28 [], extra: {...} (skinned / flags&8 payloads, kept verbatim)}],
                collision: None | {'flags': (a, b) or None (derive), 'shapes': [todcoll shape dicts]},
                v34 [], v48 []}]
  hulls       None | [todcoll shape dicts]     (model +0x54 HullList, model space)
  x40         None | list of int lists (characters only)
  o58         None = the common 0x6C template | raw bytes (pointer/count words are rewritten)

Derived fields (rules measured on all shipped models, see docs/subsystem_model_writer.md):
  MeshBuffer +0x24 centre = AABB centre of its vertex positions, +0x34 half extents, +0x30 radius = |half|  (12,035/12,035)
  pivot +0x64 size = max(0.5, 2*half) per axis and +0x70 centre of the AABB of that pivot's own vertices; a pivot
      without meshes: size 0.5, centre 0 (5,550/5,550)
  model +0x44 centre = AABB centre of all render vertices in model space (pivot chain, conjugated quaternions),
      +0x50 radius = max distance from it to a render vertex; collision is not included (1,299/1,299 rigid models)
"""
import math
import struct
import numpy as np
import todmodel as tm
import todcoll as tc

SENT_VEC = 0xBAAFFA00
F32 = np.float32


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


# ------------------------------------------------------------------------------------------------ quaternions
def qconj(q): return (-q[0], -q[1], -q[2], q[3])


def qnorm(q):
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return tuple(x / n for x in q)


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz)


def qrot(q, v):
    x, y, z, w = q; vx, vy, vz = v
    tx = 2*(y*vz - z*vy); ty = 2*(z*vx - x*vz); tz = 2*(x*vy - y*vx)
    return (vx+w*tx+(y*tz-z*ty), vy+w*ty+(z*tx-x*tz), vz+w*tz+(x*ty-y*tx))


def compose(A, B):
    return (tuple(a + r for a, r in zip(A[0], qrot(A[1], B[0]))), qmul(A[1], B[1]))


def apply(T, v):
    r = qrot(T[1], v)
    return (r[0] + T[0][0], r[1] + T[0][1], r[2] + T[0][2])


def pivot_world(pivots):
    """Model-space transform of every pivot: parent chain, stored quaternion conjugated (project convention, verified
    by the model-sphere rule on 736 multi-pivot models)."""
    loc = [(tuple(P['pos']), qconj(tuple(P['quat'])), P['parent']) for P in pivots]
    out = [None] * len(loc)

    def get(i, d=0):
        if out[i] is None:
            p, q, par = loc[i]
            out[i] = compose(get(par, d + 1), (p, q)) if (0 <= par < len(loc) and par != i and d < 64) else (p, q)
        return out[i]
    for i in range(len(loc)):
        get(i)
    return out


# ------------------------------------------------------------------------------------------------ templates
def default_o58():
    b = bytearray(0x6C)
    struct.pack_into('<IiiI', b, 0, 0, 0, 0, SENT_VEC)
    struct.pack_into('<I', b, 0x10, 0xBAADF000)
    struct.pack_into('<f', b, 0x30, 1.0)
    struct.pack_into('<I', b, 0x34, 0xBAADF000)
    struct.pack_into('<f', b, 0x54, 1.0)
    struct.pack_into('<I', b, 0x58, 0xBAADF001)
    struct.pack_into('<IiiI', b, 0x5C, 0, 0, 0, SENT_VEC)
    return bytes(b)


DEFAULT_HEADER = dict(w18=0xBA610000, w1c=0x18, w5c=0xBAADF020)
DEFAULT_VB = dict(fvf=0x112, stride=32, decl=6, w16=0xBA01, w1c=0)
DEFAULT_IB = dict(w10=0xBAADF00D, w18=0)


# ------------------------------------------------------------------------------------------------ mesh helpers
def vertex_positions(mesh):
    st = mesh['vb']['stride']
    vb = mesh['vertex_bytes']
    return [struct.unpack_from('<3f', vb, i * st) for i in range(len(vb) // st)]


def mesh_from_triangles(positions, normals, uvs, tris, **kw):
    """Triangle list mesh with FVF 0x112 (pos, normal, uv; stride 32, declaration 6)."""
    tris = orient_render(positions, normals, tris)
    vb = b''.join(struct.pack('<8f', *p, *n, *t) for p, n, t in zip(positions, normals, uvs))
    idx = [i for t in tris for i in t]
    if max(idx) >= 65536:
        raise ValueError('more than 65,536 vertices in one submesh')
    m = dict(texrefs=kw.get('texrefs', [0]), smb_flags=kw.get('smb_flags', 0xBA1BC000), mb_flags=kw.get('mb_flags', 0xBAADE000),
             kind='base', vb=dict(DEFAULT_VB), vertex_bytes=vb, indices=idx, prim='list', ib=dict(DEFAULT_IB),
             v18=[], v28=[], extra={})
    return m


BAAD = struct.pack('<I', 0xBAADF00D)


def skin_records(vertex_bytes, joints, weights):
    """Smooth-skin stream of a 'skin' MeshBuffer (FUN_00463270: +0x44 = 96 B per vertex, +0x48 = u16 count per vertex).
    Record = the 32-byte vertex (pos, normal, uv) + 4 int32 bone indices (model pivot indices, < 64) at +0x20 +
    4 float weights at +0x40; unused slots and +0x30/+0x50 hold 0xBAADF00D (857 of 857 shipped skinned meshes,
    269,373 vertices, rebuild bit-exact this way). joints/weights: per vertex lists of 1..4 entries."""
    out = bytearray(); cnt = bytearray()
    for v, (bj, bw) in enumerate(zip(joints, weights)):
        if not 1 <= len(bj) == len(bw) <= 4:
            raise ValueError('vertex %d: 1..4 influences needed' % v)
        if max(bj) >= 64:
            raise ValueError('bone index %d >= 64 (models hold up to 64 bones)' % max(bj))
        out += vertex_bytes[32 * v:32 * v + 32]
        out += b''.join(struct.pack('<i', j) for j in bj) + BAAD * (4 - len(bj))
        out += BAAD * 4
        out += b''.join(struct.pack('<f', w) for w in bw) + BAAD * (4 - len(bw))
        out += BAAD * 4
        cnt += struct.pack('<H', len(bj))
    return bytes(out), bytes(cnt)


def skin_from_records(skin, infl):
    n = len(infl) // 2
    joints, weights = [], []
    for v in range(n):
        c = struct.unpack_from('<H', infl, 2 * v)[0]
        joints.append(list(struct.unpack_from('<%di' % c, skin, 96 * v + 0x20)))
        weights.append(list(struct.unpack_from('<%df' % c, skin, 96 * v + 0x40)))
    return joints, weights


def skinned_mesh(positions, normals, uvs, tris, joints, weights, **kw):
    """A smooth-skinned submesh (characters): VB FVF 0x112 stride 32 with the bind-pose vertices (the engine CPU-skins
    them every frame into the same dynamic buffer, VB +0x1C = 1, IB +0x18 = 1), MeshBuffer flags 0xBAADE002."""
    m = mesh_from_triangles(positions, normals, uvs, tris, **kw)
    m['kind'] = 'skin'
    m['mb_flags'] = kw.get('mb_flags', 0xBAADE002)
    m['vb']['w1c'] = 1
    m['ib']['w18'] = 1
    sk, ct = skin_records(m['vertex_bytes'], joints, weights)
    m['extra'] = dict(skin=sk, infl=ct, tail=bytes(8) + BAAD * 4)
    return m


def orient_render(positions, normals, tris):
    """Shipped render triangles are wound so that cross(v1-v0, v2-v0) points AGAINST the vertex normals (80,901 of
    81,000 triangles in submap01 Map02: D3D's default clockwise front face in TOD's left-handed space). Flip every
    triangle whose winding disagrees with its normals."""
    out = []
    for a, b, c in tris:
        A, B, C = positions[a], positions[b], positions[c]
        u = [B[i] - A[i] for i in range(3)]; v = [C[i] - A[i] for i in range(3)]
        n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        vn = [normals[a][i] + normals[b][i] + normals[c][i] for i in range(3)]
        out.append((a, c, b) if sum(n[i] * vn[i] for i in range(3)) > 0 else (a, b, c))
    return out


def box_mesh(mn, mx, uv_scale=1.0):
    """A closed box: 24 vertices with flat outward normals, 12 triangles (render winding, see orient_render).
    Texture coordinates are the face's in-plane coordinates in metres * uv_scale (the texture repeats)."""
    x0, y0, z0 = mn; x1, y1, z1 = mx
    faces = [((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ((-1, 0, 0), [(x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0)]),
             ((0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
             ((0, -1, 0), [(x0, y0, z1), (x0, y0, z0), (x1, y0, z0), (x1, y0, z1)]),
             ((0, 0, 1), [(x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)]),
             ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)])]
    P, N, T, tris = [], [], [], []
    for n, quad in faces:
        b = len(P)
        for v in quad:
            P.append(v); N.append(n)
            if n[1] != 0:                       # top / bottom: u = x, v = z
                T.append((v[0] * uv_scale, v[2] * uv_scale))
            elif n[0] != 0:                     # +-X sides: u = z, v = -y (texture upright)
                T.append((v[2] * uv_scale, -v[1] * uv_scale))
            else:                               # +-Z sides: u = x, v = -y
                T.append((v[0] * uv_scale, -v[1] * uv_scale))
        tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return P, N, T, orient_render(P, N, tris)


def load_obj(path, scale=1.0, flip_z=False):
    """Minimal OBJ reader: v / vt / vn / f (triangulated as fans). Returns positions, normals, uvs, triangles with one
    vertex per (v, vt, vn) corner combination. flip_z converts a right-handed y-up export (glTF/Blender) to TOD's
    left-handed y-up (negate Z and reverse the winding)."""
    V, VT, VN = [], [], []
    corners = {}
    P, N, T, tris = [], [], [], []
    for line in open(path, encoding='latin-1'):
        s = line.split()
        if not s:
            continue
        if s[0] == 'v':
            x, y, z = (float(c) * scale for c in s[1:4]); V.append((x, y, -z if flip_z else z))
        elif s[0] == 'vt':
            VT.append((float(s[1]), 1.0 - float(s[2])))
        elif s[0] == 'vn':
            x, y, z = (float(c) for c in s[1:4]); VN.append((x, y, -z if flip_z else z))
        elif s[0] == 'f':
            ids = []
            for c in s[1:]:
                parts = (c.split('/') + ['', ''])[:3]
                key = tuple(int(p) if p else 0 for p in parts)
                if key not in corners:
                    vi, ti, ni = key
                    corners[key] = len(P)
                    P.append(V[vi - 1 if vi > 0 else vi])
                    T.append(VT[ti - 1 if ti > 0 else ti] if ti else (0.0, 0.0))
                    N.append(VN[ni - 1 if ni > 0 else ni] if ni else (0.0, 1.0, 0.0))
                ids.append(corners[key])
            for k in range(1, len(ids) - 1):
                t = (ids[0], ids[k], ids[k + 1])
                tris.append((t[0], t[2], t[1]) if flip_z else t)
    return P, N, T, tris


def triangles_of(mesh):
    idx = mesh['indices']
    if mesh['prim'] == 'list':
        return [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
    out = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue
        out.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return out


# ------------------------------------------------------------------------------------------------ collision helpers
BOX_TRIS = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2),
            (1, 3, 7), (1, 7, 5)]
AUX_TEMPLATE = tc.AUX_TEMPLATE


def _outward(verts, faces):
    cen = [sum(v[i] for v in verts) / len(verts) for i in range(3)]
    for f in faces:
        a, b, c = (verts[i] for i in f[:3])
        n = [(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]), (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),
             (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])]
        if sum(n[i] * (a[i] - cen[i]) for i in range(3)) < 0:
            f.reverse()
    return faces


def hull_shape(verts, faces, pivot=0, surf=0x02007C00, facemat=0xFF, flags20=0xB8FFFFFF, aux_name='', wrapper=True):
    """A VertexCloud shape (todcoll dict). faces: polygons (lists of vertex indices), oriented outward here.
    Collision uses only the vertices (support function); faces serve the material lookup and decals."""
    verts = [tuple(f32(c) for c in v) for v in verts]
    if len(verts) > 255:
        raise ValueError('a VertexCloud holds at most 255 vertices')
    faces = _outward(verts, [list(f) for f in faces])
    bits = max(1, len(verts).bit_length())
    entries = sum(len(f) + 1 for f in faces)
    if entries > 4095:
        raise ValueError('index stream longer than 4095 entries')
    s = dict(type=4, sphere=(0.0, 0.0, 0.0, -1.0), extrude=(0.0, 0.0, 0.0), flags20=flags20, surf=surf, x28=0,
             lowbyte=pivot & 0x7F, bits=bits, verts=verts, faces=faces, facemat=[facemat] * len(faces),
             u16list=None, facesurf=None, aux=dict(raw=AUX_TEMPLATE, name=aux_name))
    if wrapper:
        s['wrapper_tail'] = bytes(24)
    return s


def box_shape(mn, mx, **kw):
    verts = [(x, y, z) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    return hull_shape(verts, [list(t) for t in BOX_TRIS], **kw)


def convex_hull(points, eps=1e-6):
    """Small 3D convex hull (gift-wrapping over all point triples; fine for <= ~100 points). Returns (verts, tris)."""
    pts = []
    for p in points:
        if all(math.dist(p, q) > 1e-5 for q in pts):
            pts.append(tuple(p))
    n = len(pts)
    if n < 4:
        raise ValueError('need 4 distinct points')
    tris = set()
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = pts[i], pts[j], pts[k]
                nrm = [(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]), (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),
                       (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])]
                ln = math.sqrt(sum(x * x for x in nrm))
                if ln < eps:
                    continue
                side = [sum(nrm[q] * (pts[m][q] - a[q]) for q in range(3)) / ln for m in range(n)]
                if all(s <= eps for s in side):
                    tris.add((i, j, k))
                elif all(s >= -eps for s in side):
                    tris.add((i, k, j))
    used = sorted({i for t in tris for i in t})
    remap = {o: k for k, o in enumerate(used)}
    return [pts[i] for i in used], [[remap[i] for i in t] for t in tris]


# ------------------------------------------------------------------------------------------------ bounds rules
def aabb(P):
    mn = [min(v[i] for v in P) for i in range(3)]; mx = [max(v[i] for v in P) for i in range(3)]
    return mn, mx


def mesh_bounds(P):
    """MeshBuffer +0x24 centre, +0x30 radius, +0x34 half extents, in float32 exactly as the exporter computed them:
    c = (mn + mx) * 0.5, h = (mx - mn) * 0.5, r = sqrt((hx*hx + hz*hz) + hy*hy)   (20,920 of 20,920 bit-exact)."""
    V = np.asarray(P, dtype=F32)
    mn = V.min(0); mx = V.max(0)
    c = (mn + mx) * F32(0.5)
    h = (mx - mn) * F32(0.5)
    r = len_xzy(h)
    return [float(x) for x in c], float(r), [float(x) for x in h]


def len_xzy(d):
    """|d| in float32 with the exporter's summation order (x*x + z*z) + y*y."""
    d = np.asarray(d, dtype=F32)
    return F32(np.sqrt(F32(F32(F32(d[0] * d[0]) + F32(d[2] * d[2])) + F32(d[1] * d[1]))))


def pivot_box(P):
    V = np.asarray(P, dtype=F32)
    mn = V.min(0); mx = V.max(0)
    size = np.maximum(mx - mn, F32(0.5))
    c = (mn + mx) * F32(0.5)
    return tuple(float(x) for x in size) + tuple(float(x) for x in c)


def model_sphere(spec):
    """Model +0x44 centre = mn + (mx - mn) * 0.5 over all render vertices in model space, +0x50 radius = the largest
    len_xzy(v - c); float32 (bit-exact on 1,137 of 1,137 single-pivot rigid models; see writer_roundtrip)."""
    PW = pivot_world(spec['pivots'])
    V = []
    for i, P in enumerate(spec['pivots']):
        ident = tuple(PW[i][0]) == (0.0, 0.0, 0.0) and tuple(PW[i][1]) in ((0.0, 0.0, 0.0, 1.0), (-0.0, -0.0, -0.0, 1.0))
        for mesh in P['meshes']:
            V += vertex_positions(mesh) if ident else [apply(PW[i], v) for v in vertex_positions(mesh)]
    if not V:
        return None
    V = np.asarray(V, dtype=F32)
    mn = V.min(0); mx = V.max(0)
    c = mn + (mx - mn) * F32(0.5)
    d = V - c
    r2 = F32(F32(d[:, 0] * d[:, 0]) + F32(d[:, 2] * d[:, 2])) + F32(d[:, 1] * d[:, 1])
    r = np.sqrt(r2.astype(F32)).max()
    return [float(x) for x in c], float(F32(r))


def collision_points_model_space(spec):
    PW = pivot_world(spec['pivots'])
    pts = []
    for i, P in enumerate(spec['pivots']):
        if P.get('collision'):
            for s in P['collision']['shapes']:
                if s['type'] == 4:
                    pts += [apply(PW[i], v) for v in s['verts']]
                else:
                    pts += [apply(PW[i], v) for v in box_corners(s)]
    for s in spec.get('hulls') or []:
        if s['type'] == 4:
            pts += list(s['verts'])
        else:
            pts += box_corners(s)
    return pts


def box_corners(s):
    hx, hy, hz = (x * 0.5 for x in s['size'])
    q = s['quat']; c = s['center']
    return [tuple(a + b for a, b in zip(qrot(q, (x, y, z)), c)) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]


def list_flags(shapes):
    """CollisionList +0x10/+0x11: OR and AND of the shapes' collision flag bytes (4,331 of 4,946 shipped lists; the
    rest carry authored values, kept by spec['flags'])."""
    fl = [tc.surf_flags_byte(s['surf']) for s in shapes]
    o = 0; a = 0xFF
    for x in fl:
        o |= x; a &= x
    return o, (a if fl else 0)


# ------------------------------------------------------------------------------------------------ spec <-> tree
def spec_from_model(m):
    """Semantic description of a decoded model (todmodel.decode)."""
    r = m['raw']
    spec = dict(name=m['name']['s'].decode('latin-1'),
                textures=[t['s'].decode('latin-1') for t in m['texnames']],
                header=dict(w18=struct.unpack_from('<I', r, 0x18)[0], w1c=struct.unpack_from('<I', r, 0x1C)[0],
                            w5c=struct.unpack_from('<I', r, 0x5C)[0]),
                sphere_stored=struct.unpack_from('<4f', r, 0x44), pivots=[], hulls=None, x40=None,
                o58=m['o58']['raw'], o58_v00=m['o58']['v00']['data'], o58_v5c=m['o58']['v5c']['data'])
    for P in m['pivots']:
        pr = P['raw']
        pd = dict(name=P['name']['s'].decode('latin-1') if P['name'] else None,
                  name2=P['name2']['s'].decode('latin-1') if P['name2'] else None,
                  pos=struct.unpack_from('<3f', pr, 0), quat=struct.unpack_from('<4f', pr, 12),
                  parent=struct.unpack_from('<i', pr, 0x58)[0], w5c=struct.unpack_from('<i', pr, 0x5C)[0],
                  w60=struct.unpack_from('<i', pr, 0x60)[0],
                  box_stored=struct.unpack_from('<6f', pr, 0x64), meshes=[],
                  collision=None if P['coll'] is None else dict(flags=(P['coll']['hdr']['w10'] & 0xFF,
                                                                      (P['coll']['hdr']['w10'] >> 8) & 0xFF),
                                                               w10_hi=P['coll']['hdr']['w10'] >> 16,
                                                               shapes=P['coll']['shapes']),
                  v34=list(struct.unpack('<%di' % (len(P['v34']['data']) // 4), P['v34']['data'])),
                  v48=list(struct.unpack('<%di' % (len(P['v48']['data']) // 4), P['v48']['data'])))
        for S in P['smbs']:
            M = S['mb']
            if M is None:
                raise ValueError('submesh without MeshBuffer')
            vb, ib = M['vb_raw'], M['ib_raw']
            mesh = dict(texrefs=list(struct.unpack('<%di' % (len(S['v08']['data']) // 4), S['v08']['data'])),
                        smb_flags=struct.unpack_from('<I', S['raw'], 0x38)[0],
                        mb_flags=struct.unpack_from('<I', M['raw'], 4)[0], kind=M['kind'],
                        vb=dict(fvf=struct.unpack_from('<I', vb, 8)[0], stride=struct.unpack_from('<H', vb, 0x14)[0],
                                w16=struct.unpack_from('<H', vb, 0x16)[0], decl=struct.unpack_from('<I', vb, 0x18)[0],
                                w1c=struct.unpack_from('<I', vb, 0x1C)[0]),
                        vertex_bytes=M['vdata'],
                        indices=list(struct.unpack('<%dH' % (len(M['idata']) // 2), M['idata'])),
                        prim='list' if struct.unpack_from('<I', ib, 4)[0] else 'strip',
                        ib=dict(w10=struct.unpack_from('<I', ib, 0x10)[0], w18=struct.unpack_from('<I', ib, 0x18)[0]),
                        v18=list(struct.unpack('<%di' % (len(S['v18']['data']) // 4), S['v18']['data'])),
                        v28=list(struct.unpack('<%di' % (len(S['v28']['data']) // 4), S['v28']['data'])),
                        extra={}, bounds_stored=struct.unpack_from('<7f', M['raw'], 0x24))
            if M['kind'] == 'skin':
                mesh['extra'] = dict(skin=M['skin'], infl=M['infl'], tail=M['raw'][0x44:0x5C])
            elif M['kind'] == 'f8':
                mesh['extra'] = dict(v44=M['v44']['data'], v54=M['v54']['data'], tail=M['raw'][0x44:0x64])
            if M['str'] is not None:
                mesh['extra']['str'] = M['str']; mesh['extra']['strlen'] = struct.unpack_from('<i', M['raw'], 0x14)[0]
            pd['meshes'].append(mesh)
        spec['pivots'].append(pd)
    if m['hulls'] is not None:
        spec['hulls'] = m['hulls']['shapes']
        spec['hulls_w10'] = m['hulls']['hdr']['w10']
    if m['x40'] is not None:
        spec['x40'] = [list(struct.unpack('<%di' % (len(d['data']) // 4), d['data'])) for d in m['x40']['data']]
        spec['x40_raw'] = m['x40']['raw']
    return spec


def _vec(ints=(), esz=4, fmt='<i'):
    data = b''.join(struct.pack(fmt, x) for x in ints) if not isinstance(ints, (bytes, bytearray)) else bytes(ints)
    return tm.new_vec(data, esz)


def _cstr(s):
    return None if s is None else dict(s=s.encode('latin-1'), tail=None)


def build_tree(spec, derive=True):
    """spec -> todmodel tree (encode with todmodel.encode). derive=False keeps stored bounds (for checks)."""
    hdr = dict(DEFAULT_HEADER, **spec.get('header', {}))
    raw = bytearray(0x60)
    struct.pack_into('<I', raw, 0, 3)
    struct.pack_into('<I', raw, 0x0C, 0xBAADF00D)
    struct.pack_into('<II', raw, 0x18, hdr['w18'], hdr['w1c'])
    struct.pack_into('<I', raw, 0x5C, hdr['w5c'])
    nt = len(spec['textures'])
    struct.pack_into('<IiiI', raw, 0x20, 0, nt, nt, SENT_VEC)
    npv = len(spec['pivots'])
    struct.pack_into('<IiiI', raw, 0x30, 0, npv, npv, SENT_VEC)
    # model sphere
    sph = spec.get('sphere')
    if sph is None and derive:
        ms = model_sphere(spec)
        if ms is not None:
            c, r = ms
            sph = (c[0], c[1], c[2], r)
    if sph is None:
        sph = spec.get('sphere_stored', (0.0, 0.0, 0.0, 0.5))
    if spec.get('cover_collision'):
        cpts = collision_points_model_space(spec)
        if cpts:
            need = max(math.dist(sph[:3], p) for p in cpts)
            if need > sph[3]:
                sph = (sph[0], sph[1], sph[2], f32(need + 0.5))
    struct.pack_into('<4f', raw, 0x44, *sph)
    m = dict(raw=bytes(raw), name=_cstr(spec['name']),
             texrefs=tm.new_vec(bytes(8 * nt), 8), texnames=[_cstr(t) for t in spec['textures']],
             pivvec=tm.new_vec(bytes(0x7C * npv), 0x7C), pivots=[])
    for P in spec['pivots']:
        pr = bytearray(0x7C)
        struct.pack_into('<3f', pr, 0, *P['pos'])
        struct.pack_into('<4f', pr, 12, *P['quat'])
        nm = len(P['meshes'])
        struct.pack_into('<IiiI', pr, 0x24, 0, nm, nm, SENT_VEC)
        struct.pack_into('<IiiI', pr, 0x34, 0, 0, 0, SENT_VEC)
        struct.pack_into('<IiiI', pr, 0x48, 0, 0, 0, SENT_VEC)
        struct.pack_into('<iii', pr, 0x58, P['parent'], P.get('w5c', -1), P.get('w60', 1 if nm else 2))
        box = P.get('box')
        if box is None and derive:
            pts = [v for mesh in P['meshes'] for v in vertex_positions(mesh)]
            box = pivot_box(pts) if pts else (0.5, 0.5, 0.5, 0.0, 0.0, 0.0)
        if box is None:
            box = P['box_stored']
        struct.pack_into('<6f', pr, 0x64, *box)
        smbs = []
        for mesh in P['meshes']:
            smbs.append(build_smb(mesh, derive))
        coll = None
        if P.get('collision'):
            C = P['collision']
            fl = C.get('flags') or list_flags(C['shapes'])
            w10 = fl[0] | (fl[1] << 8) | (C.get('w10_hi', 0xBAAC) << 16)
            n = len(C['shapes'])
            coll = dict(kind='piv', hdr=dict(vec=dict(cnt=n, cap=n, flags=SENT_VEC), w10=w10), shapes=C['shapes'])
        m['pivots'].append(dict(raw=bytes(pr), smbvec=tm.new_vec(bytes(0x3C * nm), 0x3C), smbs=smbs,
                                name=_cstr(P.get('name')), name2=_cstr(P.get('name2')), coll=coll,
                                v34=_vec(P.get('v34', [])), v48=_vec(P.get('v48', []))))
    X = spec.get('x40')
    if X is None:
        m['x40'] = None
    else:
        xr = bytearray(spec.get('x40_raw') or struct.pack('<IiiI', 0, 0, 0, SENT_VEC))
        struct.pack_into('<ii', xr, 4, len(X), len(X))
        el = bytearray()
        for d in X:
            el += struct.pack('<IiiI', 0, len(d), len(d), SENT_VEC)
        m['x40'] = dict(raw=bytes(xr), elems=tm.new_vec(bytes(el), 16), data=[_vec(d) for d in X])
    H = spec.get('hulls')
    if H is None:
        m['hulls'] = None
    else:
        m['hulls'] = dict(kind='f54', hdr=dict(vec=dict(cnt=len(H), cap=len(H), flags=SENT_VEC), w10=spec.get('hulls_w10', 0)),
                          shapes=H)
    o58 = bytearray(spec.get('o58') or default_o58())
    v00 = spec.get('o58_v00', b''); v5c = spec.get('o58_v5c', b'')
    struct.pack_into('<ii', o58, 4, len(v00) // 16, len(v00) // 16)
    struct.pack_into('<ii', o58, 0x60, len(v5c) // 8, len(v5c) // 8)
    m['o58'] = dict(raw=bytes(o58), v00=tm.new_vec(v00, 16), v5c=tm.new_vec(v5c, 8))
    return m


def build_smb(mesh, derive=True):
    sr = bytearray(0x3C)
    struct.pack_into('<I', sr, 0x38, mesh['smb_flags'])
    for o in (0x08, 0x18, 0x28):
        struct.pack_into('<IiiI', sr, o, 0, 0, 0, SENT_VEC)
    kind = mesh.get('kind', 'base')
    size = {'base': tm.MB_BASE, 'skin': tm.MB_SKIN, 'f8': tm.MB_F8}[kind]
    mr = bytearray(size)
    struct.pack_into('<IIIII', mr, 0, 0, mesh['mb_flags'], 0xBAADF00D, 0, 0)
    ex = mesh.get('extra') or {}
    struct.pack_into('<iII', mr, 0x14, ex.get('strlen', 0), 8, 0x80000000)
    struct.pack_into('<I', mr, 0x20, 0xBAADF000)
    st = mesh['vb']['stride']
    nv = len(mesh['vertex_bytes']) // st
    if derive and nv:
        c, r, h = mesh_bounds(vertex_positions(mesh))
        struct.pack_into('<3ff3fI', mr, 0x24, *c, r, *h, 0)
    else:
        struct.pack_into('<7fI', mr, 0x24, *mesh['bounds_stored'], 0)
    if kind in ('skin', 'f8') and 'tail' in ex:
        mr[0x44:size] = ex['tail']
    vb = bytearray(0x28)
    v = mesh['vb']
    struct.pack_into('<IIIII', vb, 0, nv, 0, v['fvf'], len(mesh['vertex_bytes']), 0)
    struct.pack_into('<HHII', vb, 0x14, st, v['w16'], v['decl'], v['w1c'])
    ib = bytearray(0x20)
    n = len(mesh['indices'])
    struct.pack_into('<IIIII', ib, 0, n, 1 if mesh['prim'] == 'list' else 0, 4 if mesh['prim'] == 'list' else 5, 0,
                     mesh['ib']['w10'])
    struct.pack_into('<I', ib, 0x18, mesh['ib']['w18'])
    M = dict(kind=kind, raw=bytes(mr), vb_raw=bytes(vb), vdata=mesh['vertex_bytes'], ib_raw=bytes(ib),
             idata=struct.pack('<%dH' % n, *mesh['indices']), str=ex.get('str'))
    if kind == 'skin':
        M['skin'] = ex['skin']; M['infl'] = ex['infl']
    elif kind == 'f8':
        M['v44'] = tm.new_vec(ex['v44'], 2); M['v54'] = tm.new_vec(ex['v54'], 4)
    return dict(raw=bytes(sr), mb=M, v08=_vec(mesh['texrefs']), v18=_vec(mesh.get('v18', [])), v28=_vec(mesh.get('v28', [])))


def transplant_pads(new, old):
    """Copy the exporter's uninitialised pad bytes (and cstring tails) from an original tree into a structurally equal
    new tree, so a rebuild can be compared byte for byte. Only keys that hold pads are copied."""
    PAD = {'obj_pad', 'pad', 'tail', 'pad_obj', 'gap_vb', 'vb_pad_obj', 'vdata_pad', 'gap_ib', 'ib_pad_obj',
           'idata_pad', 'skin_pad', 'infl_pad', 'gap_mb', 'pads', 'stream_raw', 'obj_keep', 'facemat_emptyptr'}
    if isinstance(new, dict) and isinstance(old, dict):
        for k, v in old.items():
            if k in PAD:
                new[k] = v
            elif k in new:
                transplant_pads(new[k], v)
    elif isinstance(new, list) and isinstance(old, list):
        for a, b in zip(new, old):
            transplant_pads(a, b)


def build_record(spec, derive=True):
    return tm.encode(build_tree(spec, derive))
