"""Reader for the PSP game's vehicle models (read only): the user's own game data in, the importer's part list out.

Every vehicle model is a record of a data block (type 3): a table of texture paths, a list of parts (88 bytes each: position,
rotation, name, parent, a pointer to its mesh records) and quantised GE vertex buffers kept in the block's second segment. Nothing
of the game is stored by Mod Studio: this module only decodes what the user points it to and hands over textured parts.

Public API
  resolve(path)                  the archive file for a folder or file the user named, or None
  list_vehicles(path)            [{id, name, block, model}] (cached next to the archive's size and date)
  read_vehicle(path, vid)        Vehicle (parts with transforms, meshes, texture images)
  vehicle_scene(v)               todct.meshtex.Scene: assembled body + wheels, ready for the importer
"""
import io
import json
import os
import re
import struct
import zlib

import numpy as np

from . import meshtex as MT
from .cccfmt import extract_textures as ET
from .cccfmt import naz as NAZ
from .cccfmt import props as PROPS


class CccError(ValueError):
    pass


PIVOT_STRIDE = 0x58
# readable names of the vehicle folders (the game's own folder names, spaced)
_NICE = {'pickup4x4': 'Pickup 4x4', 'pickuptruck': 'Pickup truck', 'pickuptruck_mamma': 'Mamma pickup truck', 'bigtruck_flatnose': 'Big truck',
         'elcamino_lostorosrose': 'El Camino', 'golfcar': 'Golf car', 'forklift': 'Forklift', 'tractor': 'Tractor', 'tank': 'Tank',
         'harrier': 'Harrier', 'huey': 'Huey', 'marcoshelicopter': 'Marcos helicopter', 'speedboat_scarab': 'Speed boat'}


def nice_name(folder):
    k = folder.lower()
    if k in _NICE:
        return _NICE[k]
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])|_+', ' ', folder).strip().capitalize()


def resolve(path):
    """assets00.naz for a file, a game folder, or a folder that holds it somewhere below (three levels)."""
    if not path:
        return None
    path = os.path.normpath(path)
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        return None
    for root, dirs, files in os.walk(path):
        depth = root[len(path):].count(os.sep)
        if depth > 4:
            dirs[:] = []
            continue
        for f in files:
            if f.lower() == 'assets00.naz':
                return os.path.join(root, f)
    return None


class Archive:
    def __init__(self, path):
        self.path = path
        try:
            self.f = open(path, 'rb')
            self.entries = {e.name: e for e in NAZ.read_directory(self.f)}
        except (OSError, NAZ.NazError, struct.error) as e:
            raise CccError('not a game archive: %s' % e)

    def read(self, name):
        e = self.entries[name]
        self.f.seek(e.data_offset)
        return self.f.read(e.size)

    def blocks(self):
        return sorted(n for n in self.entries if n.lower().endswith(('.map', '.main')))

    def block(self, name):
        return ET.Block(self.read(name), name.lower().endswith('.map'))

    def close(self):
        self.f.close()


_VEH = re.compile(r'^/data/models/vehicles/([^/]+)/vehicle\.model$', re.I)


def list_vehicles(path, cache_dir=None):
    """[{id, name, folder, block, model}]: one entry per vehicle folder (the first block that holds it)."""
    ap = resolve(path)
    if not ap:
        return []
    st = os.stat(ap)
    ck = None
    if cache_dir:
        ck = os.path.join(cache_dir, 'ccc_vehicles.json')
        try:
            with open(ck, 'r', encoding='utf-8') as f:
                c = json.load(f)
            if c.get('size') == st.st_size and c.get('mtime') == int(st.st_mtime) and c.get('path') == ap:
                return c['vehicles']
        except (OSError, ValueError):
            pass
    A = Archive(ap)
    out, seen = [], set()
    try:
        for bn in A.blocks():
            low = bn.lower()
            if not (low.endswith('.main') or '/shared/' in low.replace('\\', '/')):
                continue
            try:
                B = A.block(bn)
            except (PROPS.BlockError, struct.error):
                continue
            for r in B.records:
                m = _VEH.match(r.name)
                if r.type == 3 and m and m.group(1).lower() not in seen:
                    seen.add(m.group(1).lower())
                    out.append(dict(id=m.group(1), name=nice_name(m.group(1)), folder=m.group(1), block=bn, model=r.name))
    finally:
        A.close()
    out.sort(key=lambda v: v['name'].lower())
    if ck:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(ck, 'w', encoding='utf-8') as f:
                json.dump(dict(size=st.st_size, mtime=int(st.st_mtime), path=ap, vehicles=out), f)
        except OSError:
            pass
    return out


# ---------------------------------------------------------------------------------------------- the model record
def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def _f32(b, o, n):
    return struct.unpack_from('<%df' % n, b, o)


def _target(b, o):
    """Self-relative pointer at o: the flag bits are the low two."""
    return o + (_u32(b, o) & ~3)


def _cstr(b, o):
    e = b.find(b'\0', o)
    return b[o:e].decode('latin-1') if e > o else ''


def vtype_size(vt):
    """Size and field offsets of one GE vertex (VTYPE walk): -> (stride, tc_off, nm_off, ps_off)."""
    tc, col, nm, ps = vt & 3, (vt >> 2) & 7, (vt >> 5) & 3, (vt >> 7) & 3
    wt, wc = (vt >> 9) & 3, ((vt >> 14) & 7) + 1
    sz, al = 0, 1
    offs = {}

    def add(key, size, a):
        nonlocal sz, al
        sz = (sz + a - 1) // a * a
        offs[key] = sz
        sz += size
        al = max(al, a)
    if wt:
        add('w', {1: 1, 2: 2, 3: 4}[wt] * wc, {1: 1, 2: 2, 3: 4}[wt])
    if tc:
        add('tc', {1: 2, 2: 4, 3: 8}[tc], {1: 1, 2: 2, 3: 4}[tc])
    if col:
        add('col', {4: 2, 5: 2, 6: 2, 7: 4}.get(col, 0), {4: 2, 5: 2, 6: 2, 7: 4}.get(col, 1))
    if nm:
        add('nm', {1: 3, 2: 6, 3: 12}[nm], {1: 1, 2: 2, 3: 4}[nm])
    if ps:
        add('ps', {1: 3, 2: 6, 3: 12}[ps], {1: 1, 2: 2, 3: 4}[ps])
    return (sz + al - 1) // al * al, offs


def _mesh_header(b, t, seg):
    """The mesh buffer header at t (16 bytes), or None when it is not one."""
    if t < 0 or t + 16 > len(b):
        return None
    w0, vt, sc, ptr = struct.unpack_from('<IIfI', b, t)
    cnt, nb = w0 & 0xFFFF, w0 >> 23
    if not (0 < cnt < 20000 and 1 <= nb < 64 and vt < 0x1000000 and (vt >> 7) & 3 and 0.0001 < abs(sc) < 1e4):
        return None
    if ptr + 28 * nb + 40 > len(seg):
        return None
    if struct.unpack_from('<H', seg, ptr + 28 * nb - 4)[0] != cnt:
        return None
    return dict(at=t, cnt=cnt, nb=nb, vt=vt, scale=sc, ptr=ptr)


def decode_mesh(h, seg):
    """-> P (n,3) float32, N (n,3) float32 or None, UV (n,2) float32 or None, triangles (m,3) int64 (batches are strips)."""
    cnt, nb, vt, sc, ptr = h['cnt'], h['nb'], h['vt'], h['scale'], h['ptr']
    stride, offs = vtype_size(vt)
    base = ptr + 28 * nb + 40
    raw = np.frombuffer(seg, np.uint8, cnt * stride, base).reshape(cnt, stride)

    def field(key, kind, n):
        o = offs[key]
        sz = {'i1': 1, 'u1': 1, 'i2': 2, 'u2': 2, 'f4': 4}[kind] * n
        dt = {'i1': '<i1', 'u1': '<u1', 'i2': '<i2', 'u2': '<u2', 'f4': '<f4'}[kind]
        return np.ascontiguousarray(raw[:, o:o + sz]).view(dt).reshape(cnt, n).astype(np.float64)
    pk = {1: 'i1', 2: 'i2', 3: 'f4'}[(vt >> 7) & 3]
    P = field('ps', pk, 3)
    P = P / {'i1': 127.0, 'i2': 32767.0, 'f4': 1.0}[pk]           # -1..1 across the part's own box (the part's size scales it)
    N = None
    if (vt >> 5) & 3:
        nk = {1: 'i1', 2: 'i2', 3: 'f4'}[(vt >> 5) & 3]
        N = field('nm', nk, 3) / {'i1': 127.0, 'i2': 32767.0, 'f4': 1.0}[nk]
        ln = np.linalg.norm(N, axis=1, keepdims=True)
        N = (N / np.maximum(ln, 1e-9)).astype(np.float32)
    UV = None
    if vt & 3:
        uk = {1: 'u1', 2: 'u2', 3: 'f4'}[vt & 3]
        UV = (field('tc', uk, 2) / {'u1': 128.0, 'u2': 32768.0, 'f4': 1.0}[uk] * sc).astype(np.float32)      # the header float is the texture scale (the GE's UV scale)
    ends = [struct.unpack_from('<H', seg, ptr + 28 * k + 24)[0] for k in range(nb)]
    T, s = [], 0
    for e in ends:
        e = min(e, cnt)
        for i in range(s, e - 2):
            T.append((i, i + 1, i + 2) if (i - s) % 2 == 0 else (i + 1, i, i + 2))
        s = e
    T = np.asarray(T, np.int64).reshape(-1, 3)
    if len(T):                                              # strips are stitched with repeated vertices
        keep = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])
        a, b_, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        keep &= np.linalg.norm(np.cross(b_ - a, c - a), axis=1) > 1e-12
        T = T[keep]
    return P.astype(np.float32), N, UV, T


def quat_matrix(q):
    """Rotation matrix of a stored part quaternion (x, y, z, w). The engine stores the conjugate (its parts turn the other way round
    than the textbook matrix): the same convention as the TOD model reader (model_writer.pivot_world), found on the six vehicles both
    games have, whose part positions and rotations are identical."""
    x, y, z, w = q
    x, y, z = -x, -y, -z
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                     [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                     [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])


class Vehicle:
    def __init__(self):
        self.name = ''
        self.pivots = []          # dict(i, name, parent, pos, quat, meshes=[dict(P,N,UV,tris,tex,flags)])
        self.textures = []        # path strings
        self.images = {}          # texture index -> (w, h, rgba bytes)
        self.has_alpha = {}       # texture index -> True when the picture has see-through texels
        self.world = []

    def world_matrices(self):
        """Model-space matrix of every part: the parent's matrix times (position, rotation). The part's size and centre (see parse_model)
        act on its own meshes only, never on its children."""
        W = []
        for p in self.pivots:
            M = np.eye(4)
            M[:3, :3] = quat_matrix(p['quat'])
            M[:3, 3] = p['pos']
            W.append(W[p['parent']] @ M if p['parent'] >= 0 else M)
        return W


def parse_model(b, seg):
    """The model record bytes and its block's segment -> Vehicle (without images)."""
    v = Vehicle()
    pc = _u32(b, 0x34)
    if not 0 < pc < 400:
        raise CccError('not a vehicle model')
    pstart = _target(b, 0x30)
    v.textures = [m.group().decode('latin-1') for m in re.finditer(rb'/data/[ -~]{4,}?\.bmp', b[:pstart], re.I)]
    for i in range(pc):
        o = pstart + i * PIVOT_STRIDE
        pos, q = _f32(b, o, 3), _f32(b, o + 12, 4)
        try:
            name = _cstr(b, _target(b, o + 0x1c))
        except (struct.error, ValueError):
            name = 'part%d' % i
        parent = struct.unpack_from('<i', b, o + 0x38)[0]
        meshes = []
        t = _target(b, o + 0x24)
        while t + 0x3c <= len(b):
            mt = _target(b, t)
            h = _mesh_header(b, mt, seg)
            if h is None:
                break
            P, N, UV, T = decode_mesh(h, seg)
            tex = _u32(b, mt + 0x10)
            meshes.append(dict(P=P, N=N, UV=UV, tris=T, tex=tex, hscale=h['scale'], vt=h['vt'], flags=_u32(b, t + 0x14), lod=bool(_u32(b, t + 0x38) & 1)))
            t += 0x3c
        v.pivots.append(dict(i=i, name=name, parent=parent if 0 <= parent < i else -1, pos=pos, quat=q, scale=_f32(b, o + 0x40, 3), centre=_f32(b, o + 0x4c, 3), meshes=meshes))
    v.world = v.world_matrices()
    return v


def read_vehicle(path, vid, cache=None):
    ap = resolve(path)
    if not ap:
        raise CccError('no game data set')
    veh = next((x for x in list_vehicles(path, cache) if x['id'].lower() == str(vid).lower()), None)
    if veh is None:
        raise CccError('unknown vehicle %s' % vid)
    A = Archive(ap)
    try:
        B = A.block(veh['block'])
        r = next(r for r in B.records if r.name == veh['model'] and r.type == 3)
        v = parse_model(bytes(B.memory[r.start:r.limit]), B.segment)
        v.name, v.folder = veh['name'], veh['folder']
        v.images, v.has_alpha = _load_images(A, B, veh['block'], v.textures)
    finally:
        A.close()
    return v


def _load_images(A, B, block_name, paths):
    """texture index -> (w, h, RGBA bytes) for every referenced path found in the model's block or the main block."""
    want = {p.lower(): i for i, p in enumerate(paths)}
    found, alpha = {}, {}
    problems = []
    blocks = [(block_name, B)]
    for bn in A.blocks():
        if bn.lower().endswith('.main') and bn != block_name:
            try:
                blocks.append((bn, A.block(bn)))
            except (PROPS.BlockError, struct.error):
                pass
    for bn, blk in blocks:
        if len(found) == len(want):
            break
        for tex in blk.textures(ET.container_name(bn), problems)[0]:
            i = want.get(tex.name.lower())
            if i is not None and i not in found:
                try:
                    w, h, px = tex.rgba()
                    found[i] = (w, h, bytes(px) if not isinstance(px, bytes) else px)
                    alpha[i] = bool((np.frombuffer(found[i][2], np.uint8)[3::4] < 250).any())
                except Exception:               # a texture this reader cannot decode stays a flat colour
                    pass
    return found, alpha


# ---------------------------------------------------------------------------------------------- scene for the importer
def png_bytes(w, h, rgba):
    raw = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')


_SKIP_TEX = ('wreck', 'lod_', 'shadow', 'blob')
_SKIP_PIVOT = ('physics', 'shadow')


def usable(v, mesh):
    """Drop the far-view copies (bit 0 of the mesh record's last flag word: the same bit TOD keeps in its sub-mesh flags), the damaged
    copies (their texture says so) and flat helper quads."""
    t = v.textures[mesh['tex']].lower() if mesh['tex'] < len(v.textures) else ''
    return not mesh.get('lod') and not any(k in t for k in _SKIP_TEX) and len(mesh['tris']) > 0


def _wheel_groups(parts):
    g = {}
    for q in parts:
        n = (getattr(q, 'pivot', None) or q.mat.get('pivot') or '')
        if n.lower().startswith('wheel_'):
            g.setdefault(n.lower(), []).append(q.P.astype(np.float64))
    out = {}
    for n, a in g.items():
        A = np.concatenate(a)
        mn, mx = A.min(0), A.max(0)
        out[n] = ((mn + mx) / 2, (mx[1] - mn[1] + mx[2] - mn[2]) / 4)
    return out


def _min_gap(A, B, step=2000):
    """Smallest distance between two vertex clouds (a few thousand points each at most)."""
    if len(A) > step:
        A = A[::len(A) // step + 1]
    if len(B) > step:
        B = B[::len(B) // step + 1]
    best = 1e9
    for i in range(0, len(A), 256):
        d = np.linalg.norm(A[i:i + 256, None, :] - B[None, :, :], axis=2)
        best = min(best, float(d.min()))
    return best


def check_vehicle(parts, tol=0.05, gap=0.4):
    """Physical checks on an assembled vehicle (game space, y up). -> short warnings; an empty list means it is sound:
    the wheels touch one ground, left and right wheels mirror each other, the chassis stays above that ground, and no part hangs
    detached from the rest."""
    out = []
    wheels = _wheel_groups(parts)
    if wheels:
        floor = [c[1] - r for c, r in wheels.values()]
        ground = float(np.mean(floor))
        if max(floor) - min(floor) > tol:
            out.append('The wheels do not touch one ground (%.2f m apart)' % (max(floor) - min(floor)))
        left = [(c, r) for c, r in wheels.values() if c[0] < -1e-3]
        right = [(c, r) for c, r in wheels.values() if c[0] > 1e-3]
        bad = 0
        for c, r in left:
            if not right:
                break
            m = min(right, key=lambda w: abs(w[0][2] - c[2]))
            if abs(m[0][0] + c[0]) > tol or abs(m[0][1] - c[1]) > tol or abs(m[0][2] - c[2]) > tol or abs(m[1] - r) > tol:
                bad += 1
        if bad or len(left) != len(right):
            out.append('Left and right wheels do not mirror each other')
        low = [q.P[:, 1].min() for q in parts if not (q.mat.get('pivot') or '').lower().startswith('wheel_')]
        if low and min(low) < ground - 0.10:
            out.append('The body reaches %.2f m below the ground the wheels stand on' % (ground - min(low)))
    groups = {}
    for q in parts:
        groups.setdefault((q.mat.get('pivot') or '').lower(), []).append(q.P.astype(np.float64))
    names = list(groups)
    pts = {n: np.concatenate(groups[n]) for n in names}
    lopsided = []
    for n in names:                                                         # a left part and its right twin are mirror images
        m = n.replace('left', 'right')
        if 'left' in n and m in pts and not n.startswith('wheel_'):
            a, b = pts[n], pts[m]
            err = max(abs(a[:, 0].min() + b[:, 0].max()), abs(a[:, 0].max() + b[:, 0].min()), abs(a[:, 1].min() - b[:, 1].min()),
                      abs(a[:, 1].max() - b[:, 1].max()), abs(a[:, 2].min() - b[:, 2].min()), abs(a[:, 2].max() - b[:, 2].max()))
            if err > 2 * tol:
                lopsided.append(n)
    if lopsided:
        out.append('%d left part%s not mirrored by the right one' % (len(lopsided), ' is' if len(lopsided) == 1 else 's are'))
    seen = {names[0]} if names else set()
    todo = [names[0]] if names else []
    while todo:
        a = todo.pop()
        for b in names:
            if b not in seen and _min_gap(pts[a], pts[b]) <= gap:
                seen.add(b)
                todo.append(b)
    loose = [n for n in names if n not in seen]
    if loose:
        out.append('%d part%s hang%s detached from the rest' % (len(loose), '' if len(loose) == 1 else 's', 's' if len(loose) == 1 else ''))
    return out


def vehicle_scene(v, keep=None):
    """Assembled meshes in the PSP game's axes (the same metres): a todct.meshtex.Scene whose parts are named after their pivots.
    keep(pivot) -> bool may drop pivots."""
    images, img_of, parts = [], {}, []
    for p in v.pivots:
        if not p['meshes'] or not p['name'] or p['name'].lower().startswith(_SKIP_PIVOT) or (keep and not keep(p)):
            continue
        M = v.world[p['i']]
        R = M[:3, :3]
        for mi, me in enumerate(p['meshes']):
            if not usable(v, me):
                continue
            S = np.asarray(p['scale'], np.float64)           # the meshes are stored in a unit box (-1..1): half the part's size scales them
            C = np.asarray(p['centre'], np.float64)          # ... and the box centre (in the part's own frame) moves them
            P = ((me['P'].astype(np.float64) * S * 0.5 + C) @ R.T + M[:3, 3]).astype(np.float32)
            N = None
            if me['N'] is not None:
                N = (me['N'].astype(np.float64) / S) @ R.T
                N = (N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)).astype(np.float32)
            tris = me['tris']
            if np.linalg.det(R) * np.prod(S) < 0:
                tris = tris[:, [0, 2, 1]]
            mat = MT.default_material('tex%d' % me['tex'])
            mat['pivot'] = p['name']
            mat['origin'] = [float(x) for x in M[:3, 3]]
            im = v.images.get(me['tex'])
            if im is not None:
                if me['tex'] not in img_of:
                    images.append(dict(name=os.path.basename(v.textures[me['tex']]), data=png_bytes(*im)))
                    img_of[me['tex']] = len(images) - 1
                mat.update(image=img_of[me['tex']], color=[1, 1, 1, 1], name=os.path.basename(v.textures[me['tex']]))
                if v.has_alpha.get(me['tex']):
                    mat['alpha'] = 'blend'
            part = MT.Part('%s#%d' % (p['name'], mi), P, N, me['UV'], tris, mat)
            part.pivot = p['name']
            parts.append(part)
    if not parts:
        raise CccError('nothing to import')
    return MT.Scene(parts, images, 'ccc:%s' % getattr(v, 'folder', v.name), warnings=check_vehicle(parts))
