"""Export one map's collision (and its render geometry, for checking) as glTF.

  python export_map.py OUTDIR BLOCK [BLOCK ...]      (first the .map, then its .submap files, optionally overdose.main)

Placement: every Model entity of every level fragment (prefab definitions under /data/scripts/fragments are skipped),
world = parent * local up the fragment-local parent chain, stored quaternions conjugated (project convention, see
tools/ue/kapow_populate_v2.py). Model pivots use the parent index at pivot+0x58, also conjugated.
Collision sources:
  - model+0x54 HullList (static collision, model space)
  - pivot+0x44 CollisionList (per pivot, pivot-local space): VertexCloud hulls and OrientedBoxes
  - CollisionBox entities (authored boxes; width=#241 height=#69 length=#242 flags=#71, centred on the node)
glTF: TOD is left-handed y-up; we negate Z only (as the project's other glb exporters) and keep the index order.
Writes OUTDIR/<name>_render.glb, <name>_collision.glb, <name>_collision_stats.json.
"""
import sys, os, json, math, struct, collections
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
import todblock as tb, todcoll as tc
import tod_model_extract as me
import tod_fragment_decode as fd
import tod_block_fragment_recover as rec

# ---------------------------------------------------------------- math
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
def compose(A, B):          # A then local B: world = A * B ; transforms are (pos, quat)
    return (tuple(a + r for a, r in zip(A[0], qrot(A[1], B[0]))), qmul(A[1], B[1]))
def apply(T, v):
    r = qrot(T[1], v)
    return (r[0] + T[0][0], r[1] + T[0][1], r[2] + T[0][2])
IDENT = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))

# ---------------------------------------------------------------- blocks and models
class BlockSet:
    def __init__(self, paths):
        self.blocks = []
        self.models = {}            # normalized name -> (bi, R)
        for bi, p in enumerate(paths):
            b = tb.Block(open(p, 'rb').read(), os.path.splitext(p)[1])
            info = bytes(b.info)
            starts = tb.record_starts(info, b.n)
            self.blocks.append(dict(path=p, info=info, starts=starts))
            for R in starts:
                if tc.u32(info, R) == 3:
                    self.models.setdefault(norm(tb.record_name(info, R)), (bi, R))

def norm(s):
    s = s.lower().replace('\\', '/')
    return s[6:] if s.startswith('/data/') else s.lstrip('/')

def pivot_world(info, R):
    pp = tc.deref(info, R + 0x30); n = tc.i32(info, R + 0x34)
    loc = []
    for i in range(n):
        pv = pp + i * 0x7C
        pos = struct.unpack_from('<3f', info, pv); q = struct.unpack_from('<4f', info, pv + 12)
        loc.append(((pos), qconj(qnorm(q)), tc.i32(info, pv + 0x58)))
    out = [None] * n
    def get(i, d=0):
        if out[i] is None:
            p, q, par = loc[i]
            out[i] = compose(get(par, d + 1), (p, q)) if (0 <= par < n and par != i and d < 64) else (p, q)
        return out[i]
    for i in range(n):
        get(i)
    return out

def model_collision(info, R):
    """-> list of (space, pivot, shape dict) ; space 'model' (HullList) or 'pivot' (CollisionList)."""
    res = []
    pp = tc.deref(info, R + 0x30)
    for i in range(tc.i32(info, R + 0x34)):
        c = tc.deref(info, pp + i * 0x7C + 0x44)
        if c is None:
            continue
        reg, _ = tc.read_region(info, c, 'piv')
        res += [('pivot', i, s) for s in reg['shapes']]
    f = tc.deref(info, R + 0x54)
    if f is not None:
        reg, _ = tc.read_region(info, f, 'f54')
        res += [('model', s['lowbyte'] & 0x7F, s) for s in reg['shapes']]
    return res

def box_corners_tris(size, center, quat):
    hx, hy, hz = (size[0] * 0.5, size[1] * 0.5, size[2] * 0.5)
    q = qconj(qnorm(quat)) if any(quat) else (0, 0, 0, 1)
    vs = [apply((center, q), (sx * hx, sy * hy, sz * hz)) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, c, d in faces:
        tris += [(a, b, c), (a, c, d)]
    return vs, tris

# surface classes (colour key in the picture)
def surf_class(w):
    f = tc.surf_flags_byte(w)
    if f & 1 and f & 2: return 'solid_bulletproof'
    if f & 1: return 'solid_thin'
    if f & 0x0E: return 'nonsolid_blocker'
    if f & 0x40: return 'physics_only'
    return 'other'
CLASS_COLOR = {'solid_bulletproof': (1.0, 0.45, 0.05), 'solid_thin': (1.0, 0.9, 0.1), 'nonsolid_blocker': (0.1, 0.8, 1.0),
               'physics_only': (0.6, 0.6, 0.6), 'other': (1, 0, 1),
               'box_solid': (0.9, 0.05, 0.05), 'box_navblock': (0.6, 0.2, 1.0), 'box_other': (0.3, 0.3, 1.0)}

# ---------------------------------------------------------------- glTF writer
class Mesh:
    def __init__(self):
        self.pos = []; self.col = []; self.idx = []
    def add(self, verts, tris, color=None):
        base = len(self.pos)
        for v in verts:
            self.pos.append((v[0], v[1], -v[2]))          # TOD left-handed -> glTF: negate Z only
            if color is not None:
                self.col.append(color)
        for t in tris:
            self.idx += [base + t[0], base + t[1], base + t[2]]

def write_glb(path, meshes, extras=None):
    bin_ = bytearray(); views = []; accs = []; gmeshes = []; nodes = []
    def view(data, target):
        while len(bin_) % 4: bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), target=target)); bin_.extend(data)
        return len(views) - 1
    for name, m in meshes:
        if not m.idx:
            continue
        pdata = b''.join(struct.pack('<3f', *p) for p in m.pos)
        mn = [min(p[i] for p in m.pos) for i in range(3)]; mx = [max(p[i] for p in m.pos) for i in range(3)]
        accs.append(dict(bufferView=view(pdata, 34962), componentType=5126, count=len(m.pos), type='VEC3', min=mn, max=mx))
        attrs = dict(POSITION=len(accs) - 1)
        if m.col:
            cdata = b''.join(struct.pack('<3f', *c) for c in m.col)
            accs.append(dict(bufferView=view(cdata, 34962), componentType=5126, count=len(m.col), type='VEC3'))
            attrs['COLOR_0'] = len(accs) - 1
        big = max(m.idx) > 65535
        idata = struct.pack('<%d%s' % (len(m.idx), 'I' if big else 'H'), *m.idx)
        accs.append(dict(bufferView=view(idata, 34963), componentType=5125 if big else 5123, count=len(m.idx), type='SCALAR'))
        gmeshes.append(dict(name=name, primitives=[dict(attributes=attrs, indices=len(accs) - 1, mode=4)]))
        nodes.append(dict(name=name, mesh=len(gmeshes) - 1))
    gl = dict(asset=dict(version='2.0', generator='collision_lab export_map.py'), scene=0,
              scenes=[dict(nodes=list(range(len(nodes))))], nodes=nodes, meshes=gmeshes, accessors=accs,
              bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    if extras:
        gl['extras'] = extras
    js = json.dumps(gl, separators=(',', ':')).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    while len(bin_) % 4: bin_.append(0)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(bin_), 0x004E4942)); f.write(bin_)

# ---------------------------------------------------------------- level entities
def level_entities(block_paths):
    ents = []
    for p in block_paths:
        if not p.lower().endswith(('.map', '.submap', '.mission')):
            continue
        for r in rec.assets(Path(p)):
            if r['type'] != 4 or r['name'].lower().startswith('/data/scripts/fragments/'):
                continue
            ops, st = fd.decode_fragment(r['payload'], {})
            raw = {}
            for op in ops:
                if op['op'] == 'setprop':
                    raw.setdefault(op['nodeId'], {})[op['propIndex']] = op['value']
            es = fd.build_entities(ops)
            byid = {e['nodeId']: e for e in es}
            memo = {}
            def world(nid, d=0):
                if nid in memo: return memo[nid]
                e = byid.get(nid)
                if e is None or d > 80: return IDENT
                pr = raw.get(nid, {})
                lp = tuple(pr.get(12) if isinstance(pr.get(12), list) else (0.0, 0.0, 0.0))
                lq = pr.get(13) if isinstance(pr.get(13), list) and len(pr.get(13)) == 4 else (0.0, 0.0, 0.0, 1.0)
                lq = qconj(qnorm(lq))
                par = pr.get(7)
                pid = par.get('i') if isinstance(par, dict) else None
                memo[nid] = IDENT
                w = compose(world(pid, d + 1), (lp, lq)) if (pid and pid in byid and pid != nid) else (lp, lq)
                memo[nid] = w
                return w
            for e in es:
                pr = raw.get(e['nodeId'], {})
                ents.append(dict(block=p, fragment=r['name'], nodeId=e['nodeId'], type=e['type'] or '',
                                 name=(pr.get(15) or {}).get('str') if isinstance(pr.get(15), dict) else None,
                                 raw=pr, world=world(e['nodeId'])))
    return ents

def main():
    out = sys.argv[1]; paths = sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    stem = Path(paths[0]).stem
    BS = BlockSet(paths)
    ents = level_entities(paths)
    render = Mesh()
    coll = collections.defaultdict(Mesh)
    stats = collections.Counter(); missing = collections.Counter()
    model_cache = {}
    for e in ents:
        typ = e['type']
        if typ == 'Model' or typ.endswith('(Model)'):
            ref = e['raw'].get(38)
            ref = ref.get('str') if isinstance(ref, dict) else None
            if not ref or not ref.lower().endswith('.model'):
                continue
            key = norm(ref)
            if key not in BS.models:
                missing[key] += 1
                continue
            bi, R = BS.models[key]
            info = BS.blocks[bi]['info']
            if key not in model_cache:
                m = me.extract_model(info, R, ref)
                model_cache[key] = (m, pivot_world(info, R), model_collision(info, R))
            m, PW, shapes = model_cache[key]
            T = e['world']
            stats['models_placed'] += 1
            if m:
                for mesh in m['meshes']:
                    if mesh['source_lod'] != 0:
                        continue
                    M = compose(T, PW[mesh['pivot']])
                    verts = [apply(M, v[0]) for v in mesh['verts']]
                    idx = mesh['indices'] if mesh['isTriangles'] else me.g.strip_to_tris(mesh['indices'])
                    tris = [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
                    render.add(verts, tris)
                    stats['render_tris'] += len(tris)
            for space, pi, s in shapes:
                M = T if space == 'model' else compose(T, PW[pi])
                grp = 'static_hulls' if space == 'model' else 'pivot_hulls'
                if s['type'] == 4:
                    verts = [apply(M, v) for v in s['verts']]
                    tris = [(f[0], f[k], f[k + 1]) for f in s['faces'] for k in range(1, len(f) - 1)]
                    cls = surf_class(s['surf'])
                    coll[grp + '__' + cls].add(verts, tris, CLASS_COLOR[cls])
                    stats[grp] += 1; stats[grp + '_tris'] += len(tris); stats['class_' + cls] += 1
                else:
                    vs, tris = box_corners_tris(s['size'], s['center'], s['quat'])
                    cls = surf_class(s['surf'])
                    coll['pivot_boxes__' + cls].add([apply(M, v) for v in vs], tris, CLASS_COLOR[cls])
                    stats['pivot_boxes'] += 1
        elif typ == 'CollisionBox':
            r = e['raw']
            def num(k):
                v = r.get(k); return v.get('f') if isinstance(v, dict) else None
            w, h, l = num(241), num(69), num(242)
            fl = r.get(71); fl = fl.get('i') if isinstance(fl, dict) else 0
            if None in (w, h, l):
                stats['collisionbox_incomplete'] += 1
                continue
            vs, tris = box_corners_tris((w, h, l), (0, 0, 0), (0, 0, 0, 1))
            cls = 'box_solid' if fl & 1 else ('box_navblock' if fl & 32 else 'box_other')
            coll['collisionbox_entities__' + cls].add([apply(e['world'], v) for v in vs], tris, CLASS_COLOR[cls])
            stats['collisionbox_' + cls] += 1
    write_glb(os.path.join(out, stem + '_render.glb'), [('render_lod0', render)])
    meshes = sorted(coll.items())
    write_glb(os.path.join(out, stem + '_collision.glb'), meshes,
              extras=dict(colors={k: v for k, v in CLASS_COLOR.items()}, source=paths))
    st = dict(stats=dict(stats), missing_models=dict(missing), meshes={k: len(m.idx) // 3 for k, m in meshes})
    json.dump(st, open(os.path.join(out, stem + '_collision_stats.json'), 'w'), indent=1)
    print(json.dumps(st, indent=1))

if __name__ == '__main__':
    main()
