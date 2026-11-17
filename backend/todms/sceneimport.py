"""Large-scene import: a captured or downloaded city (one glb, millions of triangles, thousands of materials) cut down to map pieces.

A session keeps the streamed file open (`todct.glbindex`) and walks the stages, each one cached by the parameters it depends on:

  open      the file: counts, the turn its nodes apply, a guess for the up axis, materials grouped into classes
  overview  a top view raster of the whole scene (every vertex binned once)
  select    the triangles of a polygon, in game axes at the chosen scale, moved so the region sits at `place` (a map coordinate)
  clean     duplicates, stray islands, vertex weld (todct.scenekit.clean)
  textures  pictures deduplicated by pixel hash, sized, atlased where the uvs allow it, stored in the asset store
  chunks    sections (grid) -> objects (spatial split by budgets) -> meshes, with triangle reduction only where a budget needs it
  collision convex slabs per object from the visible geometry
  send      recipe data: a new-map project (or an extension section's data) with one model per object and one placement each

The recipe keeps no geometry: every model part is {"type": "mapgen", "ref": sha} and the blob lives in the asset store (like the
imported models), so a project stays a few hundred kilobytes. The builder reads it through `mapgen.meshkit.read_part`.
"""
import collections
import hashlib
import io
import json
import math
import os
import struct
import threading
import time
import uuid
import zlib

import numpy as np

from todct import glbindex, scenekit as SK, modelimport as MI, texture as TX
from . import assetstore, limits, paths, scenplan

MAX_POS_CACHE = 4000000          # vertices of primitives kept in memory per session
REF_KIND = 'scene:'
LOCK = threading.RLock()
SESSIONS = {}


class SceneError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- parameters
DEFAULTS = dict(
    up='y', mirror='z', yaw=0.0, scale=1.0,
    region=dict(polygon=None, mode='clip'),
    clean=dict(SK.CLEAN_DEFAULTS),
    textures=dict(max_tex=256, atlas=True, atlas_max_px=64, budget_mb=64.0, alpha={}),
    sections=dict(section_m=128.0, object_verts=40000, object_bytes=2000000, object_textures=48, min_cell=6.0, section_tris=None,
                  reduce=True, double_sided=True),
    collision=dict(enabled=True, default='Concrete', surface={}, **SK.COLLISION_DEFAULTS),
    place=[0.0, 0.0, 0.0], name='Scene')


def merged(p):
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (p or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def _h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def axes_matrix(p):
    return MI.axis_matrix(dict(up=p['up'], yaw=p.get('yaw') or 0.0, mirror=p.get('mirror')))


# ---------------------------------------------------------------------------------------------- session
class Session:
    def __init__(self, sid, path):
        self.sid, self.path = sid, os.path.abspath(path)
        self.index = glbindex.GlbIndex(path)
        mats = self.index.materials()
        self.classes, self.prim_class = [], []
        by_key = {}
        for pr in self.index.prims:
            m = mats[pr['material']] if pr['material'] is not None else dict(name='default', image=None, color=[0.8, 0.8, 0.8, 1.0], alpha='opaque',
                                                                             double_sided=False, cutoff=0.5)
            key = (m['image'], tuple(round(float(c), 3) for c in m['color'][:3]), m['alpha'], bool(m['double_sided']))
            if key not in by_key:
                by_key[key] = len(self.classes)
                self.classes.append(dict(id=len(self.classes), name=m['name'], image=m['image'], color=[float(c) for c in m['color'][:3]],
                                         alpha=m['alpha'], double=bool(m['double_sided']), cutoff=m['cutoff']))
            self.prim_class.append(by_key[key])
        self.pos_cache = collections.OrderedDict()
        self.pos_verts = 0
        self.stage = {}
        self.img_info = {}
        self.overview_cache = {}
        self.file_key = _h([self.path, os.path.getsize(self.path), int(os.path.getmtime(self.path))])
        self._load_img_cache()

    # --- disk cache of picture facts (pixel hash, size, alpha class numbers): decoding 2,000 pictures is the slowest read of the file
    def _img_cache_path(self):
        d = os.path.join(paths.cache_dir(), 'scene')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, self.file_key + '_img.json')

    def _load_img_cache(self):
        try:
            with open(self._img_cache_path(), encoding='utf-8') as f:
                self.img_info = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.img_info = {}

    def save_img_cache(self):
        try:
            with open(self._img_cache_path() + '.part', 'w', encoding='utf-8') as f:
                json.dump({str(k): v for k, v in self.img_info.items()}, f)
            os.replace(self._img_cache_path() + '.part', self._img_cache_path())
        except OSError:
            pass

    def info(self, src):
        """Facts of picture `src` (decoded once): hash of the pixels, size, alpha numbers and the mean colour."""
        if src in self.img_info and 'p99' in self.img_info[src] and 'amean' in self.img_info[src]:           # older cached records lack the highlight percentile: read the picture again
            return self.img_info[src]
        data = self.index.image_bytes(src)
        rec = None
        if data:
            try:
                img = TX.read_image(data)
                u8 = np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8)
                a = img[..., 3]
                rec = dict(hash=hashlib.sha1(u8.tobytes() + struct.pack('<II', img.shape[1], img.shape[0])).hexdigest()[:20],
                           w=int(img.shape[1]), h=int(img.shape[0]), amin=float(a.min()), amean=float(a.mean()), clear=float((a <= 0.04).mean()),
                           hard=float(((a <= 0.04) | (a >= 0.96)).mean()), mean=[round(float(x), 4) for x in img[..., :3].reshape(-1, 3).mean(0)],
                           alpha=SK.classify_alpha(a, 'blend'),
                           p99=float(np.percentile(u8[..., :3].reshape(-1, 3).astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32), 99) / 255.0))
            except Exception:                                          # noqa: BLE001
                rec = None
        if rec is None:
            rec = dict(hash='x%d' % src, w=4, h=4, amin=1.0, amean=1.0, clear=0.0, hard=1.0, mean=[0.5, 0.5, 0.5], alpha='opaque', bad=True, p99=0.5)
        self.img_info[src] = rec
        return rec

    # --- positions in game axes (cached per primitive)
    def game_pos(self, k, A, scale):
        key = (k, A.tobytes(), float(scale))
        v = self.pos_cache.get(key)
        if v is not None:
            self.pos_cache.move_to_end(key)
            return v
        P = self.index.positions(k).astype(np.float64)
        P = ((P @ A.T) * float(scale)).astype(np.float32)
        self.pos_cache[key] = P
        self.pos_verts += len(P)
        while self.pos_verts > MAX_POS_CACHE and len(self.pos_cache) > 1:
            _, old = self.pos_cache.popitem(last=False)
            self.pos_verts -= len(old)
        return P

    def prim_box(self, A, scale):
        """(n, 2, 3) boxes of the primitives in game axes."""
        out = np.empty((len(self.index.prims), 2, 3))
        for k, pr in enumerate(self.index.prims):
            c = np.array([[x, y, z] for x in (pr['lo'][0], pr['hi'][0]) for y in (pr['lo'][1], pr['hi'][1]) for z in (pr['lo'][2], pr['hi'][2])])
            g = (c @ A.T) * float(scale)
            out[k, 0], out[k, 1] = g.min(0), g.max(0)
        return out

    def close(self):
        self.index.close()


def get(sid):
    s = SESSIONS.get(sid)
    if s is None:
        raise SceneError('open the file again: this scene is no longer loaded')
    return s


# ---------------------------------------------------------------------------------------------- open
def open_scene(path, progress=None):
    if not os.path.isfile(path):
        raise SceneError('that file does not exist')
    if os.path.splitext(path)[1].lower() not in ('.glb', '.gltf'):
        raise SceneError('a large scene is a .glb or .gltf file')
    t0 = time.time()
    if progress:
        progress('Reading the file', 0, 1)
    try:
        sess = Session(uuid.uuid4().hex[:10], path)
    except (glbindex.GlbError, KeyError, ValueError) as e:
        raise SceneError('the file could not be read: %s' % e)
    with LOCK:
        for old in list(SESSIONS):
            if SESSIONS[old].path == sess.path:
                SESSIONS.pop(old).close()
        SESSIONS[sess.sid] = sess
    ix = sess.index
    lo = np.min([p['lo'] for p in ix.prims], axis=0)
    hi = np.max([p['hi'] for p in ix.prims], axis=0)
    guess = guess_up(sess)
    return dict(sid=sess.sid, file=os.path.basename(path), size=os.path.getsize(path), prims=len(ix.prims), vertices=int(sum(p['verts'] for p in ix.prims)),
                triangles=int(sum(p['tris'] for p in ix.prims)), materials=len(sess.classes), images=ix.image_count(),
                extent=[round(float(x), 3) for x in hi - lo], min=[round(float(x), 3) for x in lo], max=[round(float(x), 3) for x in hi],
                node_rotation=ix.node_rotation, up_guess=guess, seconds=round(time.time() - t0, 2))


def guess_up(sess, sample=300):
    """What the axes look like: 'turned' when the file's own node turns a Z-up scene, plus the share of normals that point up in file
    axes (a flipped scene reads below one half). Cheap: the normals of up to `sample` primitives, evenly spread."""
    ix = sess.index
    n = len(ix.prims)
    pick = np.unique(np.linspace(0, n - 1, min(sample, n)).astype(int))
    up = down = 0
    for k in pick:
        N = ix.normals(int(k))
        if N is None:
            continue
        up += int((N[:, 1] > 0.9).sum())
        down += int((N[:, 1] < -0.9).sum())
    rot = ix.node_rotation
    turned = abs(rot[0]) > 45 or abs(rot[2]) > 45
    ext = np.max([p['hi'] for p in ix.prims], axis=0) - np.min([p['lo'] for p in ix.prims], axis=0)
    flat = int(np.argmin(ext))
    share = up / float(max(up + down, 1))
    suggest = 'y'
    if flat != 1 and not turned:
        suggest = 'z' if flat == 2 else 'y'
    return dict(turned=bool(turned), rotation=rot, up_share=round(share, 3), flat_axis='xyz'[flat], suggest_up=suggest, flipped=bool(share < 0.4 and (up + down) > 100))


# ---------------------------------------------------------------------------------------------- overview (top view)
def _colorize(cnt, hmax, hmin, hmax_all):
    h = np.where(cnt > 0, (hmax - hmin) / max(hmax_all - hmin, 1e-6), 0.0)
    h = np.clip(h, 0, 1)
    stops = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    cols = np.array([[0.10, 0.20, 0.38], [0.14, 0.45, 0.50], [0.45, 0.70, 0.42], [0.88, 0.80, 0.40], [0.98, 0.95, 0.88]])
    img = np.zeros(h.shape + (4,), np.float32)
    for c in range(3):
        img[..., c] = np.interp(h, stops, cols[:, c])
    dens = np.clip(np.log1p(cnt) / np.log1p(max(float(cnt.max()), 2.0)), 0, 1)
    img[..., :3] *= (0.72 + 0.28 * dens)[..., None]
    img[..., 3] = (cnt > 0).astype(np.float32)
    return img


def overview(sid, params=None, progress=None, size=640):
    """The whole scene from above in game axes at scale 1: -> dict(png (data url), min, max (x, z), cell, size)."""
    sess = get(sid)
    p = merged(params)
    A = axes_matrix(p)
    key = (A.tobytes(), size)
    if key in sess.overview_cache:
        return sess.overview_cache[key]
    boxes = sess.prim_box(A, 1.0)
    lo, hi = boxes[:, 0].min(0), boxes[:, 1].max(0)
    cell = max((hi[0] - lo[0]), (hi[2] - lo[2])) / float(size)
    nx = int((hi[0] - lo[0]) / cell) + 1
    nz = int((hi[2] - lo[2]) / cell) + 1
    flat, ys = [], []
    n = len(sess.index.prims)
    for k in range(n):
        if progress and k % 200 == 0:
            progress('Top view', k, n)
        P = sess.index.positions(k).astype(np.float64) @ A.T
        T = sess.index.triangles(k)
        # vertices and triangle centres: a big flat triangle leaves no holes
        C = (P[T[:, 0]] + P[T[:, 1]] + P[T[:, 2]]) / 3.0
        Q = np.concatenate([P, C])
        ix = ((Q[:, 0] - lo[0]) / cell).astype(np.int64).clip(0, nx - 1)
        iz = ((hi[2] - Q[:, 2]) / cell).astype(np.int64).clip(0, nz - 1)
        flat.append((iz * nx + ix).astype(np.int32))
        ys.append(Q[:, 1].astype(np.float32))
    flat = np.concatenate(flat)
    ys = np.concatenate(ys)
    cnt = np.bincount(flat, minlength=nx * nz).astype(np.float32)
    order = np.argsort(ys, kind='stable')
    hmax = np.full(nx * nz, -1e9, np.float32)
    hmax[flat[order]] = ys[order]                                      # the last write of a cell is the highest point
    cnt = cnt.reshape(nz, nx)
    hmax = hmax.reshape(nz, nx)
    # close one-cell holes: a cell takes the best of its eight neighbours when it is empty
    pad_c = np.pad(cnt, 1)
    pad_h = np.pad(hmax, 1, constant_values=-1e9)
    best_h = np.full_like(hmax, -1e9)
    near = np.zeros_like(cnt)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                sh_h = pad_h[1 + dy:1 + dy + nz, 1 + dx:1 + dx + nx]
                best_h = np.maximum(best_h, sh_h)
                near += (pad_c[1 + dy:1 + dy + nz, 1 + dx:1 + dx + nx] > 0)
    fill = (cnt == 0) & (near >= 3)
    hmax = np.where(fill, best_h, hmax)
    cnt = np.where(fill, 1.0, cnt)
    hv = hmax[cnt > 0]
    hmin, hhi = float(np.percentile(hv, 1)), float(np.percentile(hv, 99.5))
    img = _colorize(cnt, np.where(cnt > 0, hmax, hmin), hmin, hhi)
    import base64
    png = 'data:image/png;base64,' + base64.b64encode(TX.png_bytes(img, alpha=True)).decode('ascii')
    res = dict(png=png, min=[float(lo[0]), float(lo[2])], max=[float(lo[0] + nx * cell), float(hi[2])], cell=float(cell), width=nx, height=nz,
               y=[hmin, hhi], bytes=len(png))
    sess.overview_cache[key] = res
    return res


# ---------------------------------------------------------------------------------------------- region: counts and selection
def _poly(p):
    poly = (p.get('region') or {}).get('polygon')
    if not poly or len(poly) < 3:
        raise SceneError('draw the region first')
    return np.asarray(poly, np.float64).reshape(-1, 2)


def _candidates(sess, A, scale, poly):
    boxes = sess.prim_box(A, scale)
    lo, hi = poly.min(0), poly.max(0)
    ok = (boxes[:, 1, 0] >= lo[0]) & (boxes[:, 0, 0] <= hi[0]) & (boxes[:, 1, 2] >= lo[1]) & (boxes[:, 0, 2] <= hi[1])
    return np.nonzero(ok)[0]


def _tri_centroids_xz(P, T):
    c = (P[T[:, 0]].astype(np.float64) + P[T[:, 1]] + P[T[:, 2]]) / 3.0
    return c[:, [0, 2]]


def count_region(sid, params):
    """Live numbers of a region: triangles, primitives, material classes, distinct pictures (by position in the file)."""
    sess = get(sid)
    p = merged(params)
    A, s = axes_matrix(p), float(p['scale'])
    poly = _poly(p)
    whole = (p['region'].get('mode') == 'whole')
    prims = tris = verts = 0
    classes, images = set(), set()
    for k in _candidates(sess, A, s, poly):
        P = sess.game_pos(int(k), A, s)
        T = sess.index.triangles(int(k))
        ins = SK.point_in_polygon(_tri_centroids_xz(P, T), poly)
        if not ins.any():
            continue
        n = int(len(T)) if whole else int(ins.sum())
        prims += 1
        tris += n
        verts += min(len(P), n * 3)
        cl = sess.prim_class[int(k)]
        classes.add(cl)
        if sess.classes[cl]['image'] is not None:
            images.add(sess.classes[cl]['image'])
    return dict(triangles=tris, primitives=prims, materials=len(classes), textures=len(images), vertices_max=verts)


def select(sess, p, progress=None):
    """-> dict(soup, stats). Game axes at scale, shifted so the region's centre / lowest point lands on `place`."""
    A, s = axes_matrix(p), float(p['scale'])
    poly = _poly(p)
    whole = (p['region'].get('mode') == 'whole')
    Ps, Ns, UVs, VMs, Ts = [], [], [], [], []
    base = 0
    cands = _candidates(sess, A, s, poly)
    prims = 0
    for n_, k in enumerate(cands):
        k = int(k)
        if progress and n_ % 50 == 0:
            progress('Cutting the region', n_, len(cands))
        P = sess.game_pos(k, A, s)
        T = sess.index.triangles(k)
        ins = SK.point_in_polygon(_tri_centroids_xz(P, T), poly)
        if not ins.any():
            continue
        if not whole:
            T = T[ins]
        used, inv = np.unique(T.reshape(-1), return_inverse=True)
        N = sess.index.normals(k)
        if N is None:
            Nu = None
        else:
            Nu = (N[used].astype(np.float64) @ A.T)
            Nu = (Nu / np.maximum(np.linalg.norm(Nu, axis=1, keepdims=True), 1e-12)).astype(np.float32)
        Pu = P[used]
        if Nu is None:
            Nu = SK.tri_normals_area(Pu, inv.reshape(-1, 3))[0].mean(0)[None, :].repeat(len(Pu), 0).astype(np.float32)
        UV = sess.index.uvs(k)
        UVu = UV[used] if UV is not None else np.zeros((len(used), 2), np.float32)
        Ps.append(Pu)
        Ns.append(Nu)
        UVs.append(UVu)
        VMs.append(np.full(len(used), sess.prim_class[k], np.int32))
        Ts.append(inv.reshape(-1, 3).astype(np.int64) + base)
        base += len(used)
        prims += 1
    if not Ps:
        raise SceneError('no triangles inside the region')
    soup = SK.Soup(np.concatenate(Ps), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(VMs), np.concatenate(Ts))
    lo, hi = soup.P.min(0), soup.P.max(0)
    place = np.asarray(p.get('place') or [0, 0, 0], np.float64)
    shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]) + place
    soup.P = (soup.P.astype(np.float64) + shift).astype(np.float32)
    st = dict(triangles=soup.tris, vertices=int(len(soup.P)), primitives=prims, size=[round(float(x), 2) for x in hi - lo],
              shift=[round(float(x), 4) for x in shift], classes=int(len(np.unique(soup.VM))))
    return dict(soup=soup, stats=st)


# ---------------------------------------------------------------------------------------------- stage runner (cached)
def _stage(sess, name, key, fn):
    with LOCK:
        cur = sess.stage.get(name)
        if cur and cur[0] == key:
            return cur[1]
    res = fn()
    with LOCK:
        sess.stage[name] = (key, res)
        for later in STAGE_ORDER[STAGE_ORDER.index(name) + 1:]:
            sess.stage.pop(later, None)
    return res


STAGE_ORDER = ['select', 'clean', 'textures', 'chunks', 'collision']


def _key_select(p):
    return _h([p['up'], p['mirror'], p['yaw'], p['scale'], p['region'], p['place']])


def run_select(sess, p, progress=None):
    return _stage(sess, 'select', _key_select(p), lambda: select(sess, p, progress))


def run_clean(sess, p, progress=None):
    sel = run_select(sess, p, progress)
    key = _h([_key_select(p), p['clean']])

    def go():
        if progress:
            progress('Cleaning', 0, 1)
        soup, rep = SK.clean(sel['soup'], p['clean'])
        rep['classes'] = int(len(np.unique(soup.VM))) if soup.tris else 0
        return dict(soup=soup, report=rep)
    return _stage(sess, 'clean', key, go)


def _tri_centres(soup):
    return (soup.P[soup.T[:, 0]].astype(np.float64) + soup.P[soup.T[:, 1]] + soup.P[soup.T[:, 2]]) / 3.0


# ---------------------------------------------------------------------------------------------- textures
def _face_surface(mean):
    r, g, b = mean
    mx, mn = max(mean), min(mean)
    if g > r * 1.08 and g > b * 1.08:
        return 'Grass'
    if mx < 0.38 and mx - mn < 0.1:
        return 'Asphalt'
    if r > g > b and r - b > 0.12:
        return 'Dirt'
    return 'Concrete'


SHOULDER_KNEE = 0.70


def shoulder(v, knee=SHOULDER_KNEE):
    """Soft highlight roll-off: linear up to `knee`, then an exponential approach to 1 (slope 1 at the knee, strictly rising, never flat),
    so a picture that is brightened keeps the detail of its light parts instead of clipping to white."""
    v = np.asarray(v, np.float32)
    k = float(knee)
    over = np.maximum(v - k, 0.0)
    return np.where(v <= k, v, k + (1.0 - k) * (1.0 - np.exp(-over / (1.0 - k)))).astype(np.float32)


GLASS_ALPHA = 0.55          # the most opaque a glass pane is drawn (the picture's own alpha scales it)


def is_glass(inf, material_alpha, vertical, tint):
    """A picture that is glass: see-through all over (hardly a hole, but its alpha sits clearly below 1), on mostly upright surfaces, with a
    blue-green tint. The capture says every material is opaque, so only the picture's own alpha, its colour and where it hangs tell glass
    from a decal or a shadow on the ground."""
    if inf.get('bad') or inf['clear'] >= 0.05 or inf['amin'] <= 0.04:
        return False
    amean = float(inf.get('amean', 1.0))
    if amean > 0.95:
        return False
    if vertical < 0.5:
        return False
    r, g, b = tint
    return bool(b >= r + 0.02 and b >= g - 0.02 or material_alpha == 'blend')


def class_vertical(soup):
    """Area-weighted share of upright surface (1 = wall, 0 = floor) for each material class -> {class: share}."""
    P, T = soup.P, soup.T
    if not len(T):
        return {}
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    ar = np.linalg.norm(n, axis=1)
    up = np.abs(n[:, 1]) / np.maximum(ar, 1e-12)
    cl = soup.tri_class().astype(np.int64)
    a = np.bincount(cl, weights=ar)
    v = np.bincount(cl, weights=ar * (1.0 - up))
    return {int(c): float(v[c] / a[c]) for c in np.unique(cl) if a[c] > 0}


def _square_rgba(img, size, color, kind, gain=1.0, glass=None):
    """Picture -> (size, size, 4) float: colour factor applied, then the exposure gain through the highlight shoulder, alpha by kind
    (opaque 1, cutout 0/1, blend as is)."""
    if not np.allclose(color, 1.0, atol=0.01):
        img = img.copy()
        img[..., :3] = np.clip(img[..., :3] * np.asarray(color, np.float32), 0, 1)
    if abs(float(gain) - 1.0) > 1e-3:
        img = img.copy()
        img[..., :3] = shoulder(img[..., :3] * np.float32(gain))
    if kind == 'opaque':
        img = img.copy()
        img[..., 3] = 1.0
    elif kind == 'cutout':
        img = img.copy()
        img[..., 3] = (img[..., 3] >= 0.5).astype(np.float32)
    elif kind == 'blend' and glass:
        img = img.copy()
        img[..., 3] = np.clip(img[..., 3] * np.float32(glass), 0.12, 1.0)
    if img.shape[0] != size or img.shape[1] != size:
        img = TX.resize(img, size, size)
        if kind == 'cutout':
            img[..., 3] = (img[..., 3] >= 0.5).astype(np.float32)
    return img


def GLASS_A(tp):
    return float(tp.get('glass_alpha', GLASS_ALPHA))


def _flat_image(color, kind):
    a = 1.0 if kind == 'opaque' else 1.0
    img = np.empty((4, 4, 4), np.float32)
    img[..., :3] = np.asarray(color, np.float32)
    img[..., 3] = a
    return img


def build_textures(sess, p, soup, progress=None):
    tp = p['textures']
    used = np.unique(soup.VM)
    # 1. per class: facts of its picture, alpha kind
    cls = {}
    vert = class_vertical(soup)
    glass_on = tp.get('glass', True)
    for c in used.tolist():
        k = sess.classes[c]
        glass = False
        if k['image'] is not None:
            inf = sess.info(k['image'])
            # a frame capture says every material is opaque even where the game drew it alpha tested (trees, fences, wires): a picture with
            # real see-through pixels (1 % or more fully clear) is judged from its pixels; a material that says opaque only wins when the
            # picture hardly has any
            if inf['clear'] < 0.003 or inf['amin'] >= 0.98 or (k['alpha'] == 'opaque' and inf['clear'] < 0.01):
                kind = 'opaque'
            else:
                kind = 'cutout' if inf['hard'] >= 0.93 else 'blend'
            if kind == 'opaque' and glass_on and is_glass(inf, k['alpha'], vert.get(c, 0.0), inf['mean']):
                kind, glass = 'blend', True
            ov = (tp.get('alpha') or {}).get(str(c))
            if ov in ('opaque', 'cutout', 'blend', 'glass'):
                glass = ov == 'glass'
                kind = 'blend' if glass else ov
            cls[c] = dict(hash=inf['hash'], w=inf['w'], h=inf['h'], mean=inf['mean'], kind=kind, bad=bool(inf.get('bad')), glass=glass)
        else:
            cls[c] = dict(hash='c' + _h(k['color']), w=4, h=4, mean=k['color'], kind='opaque', bad=False, glass=False)
    if progress:
        progress('Pictures', 0, 1)
    # 2. slots: the same pixels, colour factor and alpha kind are one picture
    slot_of, slots = {}, []
    for c in sorted(cls):
        k = sess.classes[c]
        key = (cls[c]['hash'], tuple(round(x, 2) for x in k['color']), cls[c]['kind'], cls[c]['glass'])
        if key not in slot_of:
            slot_of[key] = len(slots)
            slots.append(dict(key=key, classes=[], image=k['image'], color=k['color'], kind=cls[c]['kind'], glass=cls[c]['glass'], w=cls[c]['w'], h=cls[c]['h'],
                              mean=cls[c]['mean'], uv_lo=np.array([1e9, 1e9]), uv_hi=np.array([-1e9, -1e9])))
        slots[slot_of[key]]['classes'].append(c)
    class_slot = {c: i for i, s in enumerate(slots) for c in s['classes']}
    # 3. uv range of each class. A class whose uvs sit in one whole-number cell (0..1 shifted by whole repeats) is moved into 0..1:
    #    the repeat wrap makes that identical. A class that spans more than one repeat tiles; its picture is never atlased.
    vm = soup.VM
    eps = 1e-3
    class_off = {}
    for c in used.tolist():
        m = vm == c
        uv = soup.UV[m].astype(np.float64)
        s = slots[class_slot[c]]
        class_off[c] = np.zeros(2)
        if len(uv):
            lo, hi = uv.min(0), uv.max(0)
            off = np.floor(lo + eps)
            if ((hi - off) <= 1 + eps).all():
                class_off[c] = off
                lo, hi = lo - off, hi - off
            s['uv_lo'] = np.minimum(s['uv_lo'], lo)
            s['uv_hi'] = np.maximum(s['uv_hi'], hi)
    for s in slots:
        s['wraps'] = bool((s['uv_lo'] < -eps).any() or (s['uv_hi'] > 1 + eps).any()) if s['image'] is not None else False
        fmt = 'DXT1' if s['kind'] == 'opaque' else 'RGBA32'
        s['format'] = fmt
        side = TX.pow2_near(max(s['w'], s['h']))
        side = min(side, int(tp['max_tex']))
        side = max(side, 4)
        side = TX.fit_for_cap(fmt, side, side)[0]
        s['size'] = side
    # 3b. exposure: the pictures of a frame capture are darker than the game's own (the capture has not been through the game's lighting),
    #     so every picture gets one gain that brings the triangle-weighted mean brightness to `exposure_mean` (never darker, at most 2.5 x)
    cnt = np.bincount(soup.VM.astype(np.int64), minlength=max(cls) + 1).astype(np.float64)
    wsum = sum(cnt[c] for c in cls) or 1.0
    mean_l = sum(cnt[c] * float(np.dot(cls[c]['mean'], (0.299, 0.587, 0.114))) for c in cls) / wsum
    gain = tp.get('exposure')
    peak_l = None
    if gain is None:
        gain = float(np.clip(float(tp.get('exposure_mean', 0.55)) / max(mean_l, 1e-3), 1.0, 2.5))
        # the brightest pictures must keep their detail: the triangle-weighted 99th percentile of the picture highlights may not go
        # past `exposure_peak` before the shoulder (a soft roll-off takes it from there), so a light-grey pavement is not blown out
        hl = sorted((float(sess.info(sess.classes[c]['image'])['p99'] if sess.classes[c]['image'] is not None else
                           float(np.dot(sess.classes[c]['color'], (0.299, 0.587, 0.114)))), float(cnt[c])) for c in cls)
        acc, peak_l = 0.0, hl[-1][0]
        for v, w_ in hl:
            acc += w_
            if acc >= 0.99 * wsum:
                peak_l = v
                break
        gain = float(np.clip(min(gain, float(tp.get('exposure_peak', 1.3)) / max(peak_l, 1e-3)), 1.0, 2.5))
    gain = float(gain)
    for sl in slots:
        sl['gain'] = gain
    # 4. the budget drives the sizes: halve the biggest pictures until the whole set fits
    budget = int(float(tp['budget_mb']) * 1048576)

    def total_bytes():
        t = 0
        for s in slots:
            t += TX.payload_size(s['format'], s['size'], s['size'], TX.full_chain(s['size'], s['size']))
        return t
    shrunk = 0
    while total_bytes() > budget:
        big = max(slots, key=lambda s: (TX.payload_size(s['format'], s['size'], s['size'], TX.full_chain(s['size'], s['size'])), -slots.index(s)))
        if big['size'] <= 8:
            break
        big['size'] //= 2
        shrunk += 1
    # 5. atlas: small, non-wrapping pictures of one format share pages; tiles keep their power-of-two sizes
    textures, class_tex = [], {}
    atlas_slots = {}
    if tp.get('atlas'):
        for akind in ('opaque', 'cutout', 'blend'):                  # alpha pictures never share a page with opaque ones, nor cut-out with see-through
            fmt = 'DXT1' if akind == 'opaque' else 'RGBA32'
            cand = [(i, s['size']) for i, s in enumerate(slots) if s['kind'] == akind and not s['wraps'] and s['image'] is not None
                    and s['size'] <= int(tp['atlas_max_px'])]
            if len(cand) >= 2:
                top = min(1024, TX.max_dim_for_cap(fmt))
                need = sum(sz * sz for _, sz in cand) * 1.35
                page = 8
                while page < top and (page * page < need or page < max(sz for _, sz in cand)):
                    page *= 2
                # nearby pictures share a page: order by the first triangle that uses a class of the slot
                first = {}
                tc = soup.VM[soup.T[:, 0]]
                for i, _ in cand:
                    m = np.isin(tc, slots[i]['classes'])
                    first[i] = int(np.argmax(m)) if m.any() else 0
                ordered = sorted(cand, key=lambda t: (first[t[0]], t[0]))
                tiles = [((i), sz) for i, sz in ordered]
                place, npages = SK.pack_tiles(tiles, page)
                if npages and npages < len(cand):
                    atlas_slots[akind] = dict(page=page, place=place, pages=npages)
    atlased = {i for a in atlas_slots.values() for i in a['place']}
    # 6. pixels: own pictures first
    sizes_out = 0
    for si, s in enumerate(slots):
        if progress and si % 25 == 0:
            progress('Pictures', si, len(slots))
        if si in atlased:
            continue
        img = TX.read_image(sess.index.image_bytes(s['image'])) if s['image'] is not None and not sess.info(s['image']).get('bad') else _flat_image(s['color'], s['kind'])
        side = s['size']
        pic = _square_rgba(img, side, s['color'] if s['image'] is not None else (1, 1, 1), s['kind'], s.get('gain', 1.0), GLASS_A(tp) if s.get('glass') else None)
        png = TX.png_bytes(pic, alpha=(s['kind'] != 'opaque'))
        sha = assetstore.put(png)
        name = 'Sc' + sha[:10]
        if name not in {t['name'] for t in textures}:
            textures.append(_tex_entry(name, sha, side, s['format'], s['kind'], False))
        for c in s['classes']:
            class_tex[c] = dict(name=name, xf=[1.0, 1.0, 0.0, 0.0])
    # 7. the atlas pages
    pages_info = []
    for akind, a in atlas_slots.items():
        fmt = 'DXT1' if akind == 'opaque' else 'RGBA32'
        page = a['page']
        pages = [np.zeros((page, page, 4), np.float32) for _ in range(a['pages'])]
        has = [np.zeros((page, page), bool) for _ in range(a['pages'])]
        for pg in pages:
            pg[..., :3] = 0.5
            pg[..., 3] = 1.0 if fmt == 'DXT1' else 0.0
        for i, (pgi, x, y) in sorted(a['place'].items(), key=lambda t: t[0]):
            s = slots[i]
            img = TX.read_image(sess.index.image_bytes(s['image']))
            pic = _square_rgba(img, s['size'], s['color'], s['kind'], s.get('gain', 1.0), GLASS_A(tp) if s.get('glass') else None)
            pages[pgi][y:y + s['size'], x:x + s['size']] = pic
            has[pgi][y:y + s['size'], x:x + s['size']] = True
        names = []
        for pgi, pg in enumerate(pages):
            m = has[pgi]
            if m.any():                                          # empty space takes the mean colour of the page, so mips do not darken
                mean = pg[m][:, :3].mean(0)
                pg[~m, :3] = mean
            png = TX.png_bytes(pg, alpha=(fmt != 'DXT1'))
            sha = assetstore.put(png)
            name = 'Sc' + sha[:10]
            names.append(name)
            textures.append(_tex_entry(name, sha, page, fmt, akind, True))
        for i, (pgi, x, y) in a['place'].items():
            s = slots[i]
            ts = float(s['size'])
            for c in s['classes']:
                sc_ = (ts - 1.0) / page
                off = class_off.get(c, np.zeros(2))
                class_tex[c] = dict(name=names[pgi], xf=[sc_, sc_, (x + 0.5) / page - float(off[0]) * sc_, (y + 0.5) / page - float(off[1]) * sc_], tile=True)
        pages_info.append(dict(format=fmt, kind=akind, page=page, pages=a['pages'], tiles=len(a['place'])))
    # 8. numbers
    pay = [t['bytes'] for t in textures]
    rep = dict(exposure=round(gain, 3), mean_brightness=round(mean_l, 3), highlight=round(float(peak_l), 3) if peak_l is not None else None, classes=len(cls), pictures_in=len({sess.classes[c]['image'] for c in cls if sess.classes[c]['image'] is not None}),
               slots=len(slots), duplicates_merged=len(cls) - len(slots), textures=len(textures), atlas=pages_info,
               atlased=len(atlased), wrapping=int(sum(1 for s in slots if s['wraps'])), shrunk=shrunk,
               bytes=int(sum(pay)), largest=int(max(pay) if pay else 0), budget=budget,
               opaque=sum(1 for s in slots if s['kind'] == 'opaque'), cutout=sum(1 for s in slots if s['kind'] == 'cutout'),
               blend=sum(1 for s in slots if s['kind'] == 'blend'), glass=sum(1 for s in slots if s.get('glass')),
               double_sided=int(sum(1 for c in cls if sess.classes[c]['double'])),
               bad_pictures=int(sum(1 for c in cls.values() if c.get('bad'))))
    notes = []
    if rep['cutout']:
        notes.append('%d cut-out pictures are written as 32-bit pictures and drawn alpha tested' % rep['cutout'])
    if rep['blend']:
        notes.append('%d see-through pictures are written as 32-bit pictures drawn blended%s' % (rep['blend'], ' (%d of them glass)' % rep['glass'] if rep['glass'] else ''))
    if rep['bad_pictures']:
        notes.append('%d pictures could not be read and became plain grey' % rep['bad_pictures'])
    surf = {c: _face_surface(cls[c]['mean']) for c in cls}
    sess.save_img_cache()
    return dict(textures=textures, class_tex=class_tex, report=rep, notes=notes, class_kind={c: cls[c]['kind'] for c in cls}, class_glass={c: bool(cls[c]['glass']) for c in cls}, class_surface=surf,
                class_mean={c: cls[c]['mean'] for c in cls})


def recipe_textures(entries):
    """The texture list of the recipe. A picture with alpha keeps its kind (`cutout` switches the alpha test on in the meshes that use it,
    `blend` the alpha blend): without it every tree card and glass pane is drawn as an opaque square."""
    out = []
    for t in entries:
        e = dict(name=t['name'], kind=t['kind'], size=t['size'], format=t['format'], seed=1)
        if t.get('alpha') in ('cutout', 'blend'):
            e['alpha'] = t['alpha']
        out.append(e)
    return out


def _tex_entry(name, sha, size, fmt, kind, atlas):
    return dict(name=name, kind=REF_KIND + sha, sha=sha, size=int(size), format=fmt, seed=1, alpha=kind, atlas=bool(atlas),
                bytes=int(TX.payload_size(fmt, size, size, TX.full_chain(size, size))))


def run_textures(sess, p, progress=None):
    cl = run_clean(sess, p, progress)
    key = _h([_key_select(p), p['clean'], p['textures']])
    return _stage(sess, 'textures', key, lambda: build_textures(sess, p, cl['soup'], progress))


# ---------------------------------------------------------------------------------------------- chunks
RECORD_V, RECORD_T = 32, 6


def _meters(stats):
    """The ceiling rows (the same shape the limits screens use) for the numbers of a chunk run."""
    from . import ledger
    rows = []
    for lid, used in (('G2', stats['section_tris_max']), ('M1', stats['max_submesh']), ('P5', stats['largest_model_bytes']),
                      ('P6', stats['largest_texture']), ('L1', stats['nodes']), ('P8', stats['info_bytes']),
                      ('G3', stats.get('max_hulls', 0)), ('L15', stats.get('max_hull_verts', 0))):
        rows.append(ledger._fill(ledger._row_base(lid), used))
    return rows


def build_chunks(sess, p, soup, tex, progress=None):
    from .mapgen.meshkit import Mesh
    sp = p['sections']
    T = soup.T
    cen = _tri_centres(soup)
    cx, cz = cen[:, 0], cen[:, 2]
    tri_cls = soup.tri_class().astype(np.int64)
    class_tex = tex['class_tex']
    names = sorted({v['name'] for v in class_tex.values()})
    tex_id = {n: i for i, n in enumerate(names)}
    cls_ids = sorted(class_tex)
    lut_tex = np.full(max(cls_ids) + 1, -1, np.int64)
    lut_xf = np.zeros((max(cls_ids) + 1, 4))
    lut_xf[:, 0] = lut_xf[:, 1] = 1.0
    lut_dbl = np.zeros(max(cls_ids) + 1, bool)
    for c in cls_ids:
        lut_tex[c] = tex_id[class_tex[c]['name']]
        lut_xf[c] = class_tex[c]['xf']
        lut_dbl[c] = bool(sess.classes[c]['double']) and tex['class_kind'].get(c, 'opaque') != 'opaque' and bool(sp.get('double_sided', True))
    tri_tex = lut_tex[tri_cls]
    tri_dbl = lut_dbl[tri_cls]
    # per-vertex final uv
    UV = soup.UV.astype(np.float64) * lut_xf[soup.VM][:, :2] + lut_xf[soup.VM][:, 2:]
    UV = UV.astype(np.float32)
    # sections
    sm = float(sp['section_m'])
    x0, z0 = float(cx.min()), float(cz.min())
    sx = np.floor((cx - x0) / sm).astype(np.int64)
    sz = np.floor((cz - z0) / sm).astype(np.int64)
    sec_key = sx * 100000 + sz
    sec_cap = int(sp.get('section_tris') or limits.value('G2'))
    limits_cell = dict(verts=int(sp['object_verts']), bytes=int(sp['object_bytes']), textures=int(sp['object_textures']))

    def stat(idx):
        t = T[idx]
        tt = tri_tex[idx]
        verts, nbytes = 0, 0
        vmax = 0
        for tx in np.unique(tt):
            m = tt == tx
            nv = len(np.unique(t[m].reshape(-1)))
            nd = int(tri_dbl[idx][m].sum())
            nv_all = nv + (nv if nd else 0)
            vmax = max(vmax, nv_all)
            verts += nv_all
            nbytes += nv_all * RECORD_V + (int(m.sum()) + nd) * RECORD_T
        return dict(verts_max=vmax, bytes=nbytes, textures=int(len(np.unique(tt))))
    sections, objects = [], []
    uniq = np.unique(sec_key)
    for si, sk in enumerate(uniq.tolist()):
        if progress:
            progress('Sections', si, len(uniq))
        sidx = np.nonzero(sec_key == sk)[0]
        tris_in = int(len(sidx) + tri_dbl[sidx].sum())
        ratio = 1.0
        if sp.get('reduce', True) and tris_in > sec_cap:
            ratio = sec_cap / float(tris_in)
        cells = SK.plan_cells(cx, cz, sidx, stat, limits_cell, min_cell=float(sp['min_cell']))
        sec = dict(id='%d_%d' % (sk // 100000, sk % 100000), ix=int(sk // 100000), iz=int(sk % 100000), objects=0, tris_in=tris_in, tris_out=0,
                   verts=0, bytes=0, ratio=round(ratio, 4), box=[x0 + (sk // 100000) * sm, z0 + (sk % 100000) * sm, x0 + (sk // 100000 + 1) * sm,
                                                           z0 + (sk % 100000 + 1) * sm])
        for ci, idx in enumerate(cells):
            for ob in _build_objects(soup, UV, tri_tex, tri_dbl, names, idx, ratio, cx, cz, '%s_%d' % (sec['id'], ci)):
                ob['section'] = sec['id']
                objects.append(ob)
                sec['objects'] += 1
                sec['tris_out'] += ob['tris']
                sec['verts'] += ob['verts']
                sec['bytes'] += ob['bytes']
        sections.append(sec)
    stats = dict(objects=len(objects), sections=len(sections), tris_in=int(sum(o['tris_before'] for o in objects)),
                 tris_out=int(sum(o['tris'] for o in objects)), verts=int(sum(o['verts'] for o in objects)),
                 max_submesh=int(max([o['max_submesh'] for o in objects] + [0])),
                 largest_model_bytes=int(max([o['bytes'] for o in objects] + [0])),
                 largest_texture=int(max([t['bytes'] for t in tex['textures']] + [0])),
                 section_tris_max=int(max([s['tris_out'] for s in sections] + [0])), nodes=int(2 * len(objects)),
                 info_bytes=int(sum(o['bytes'] for o in objects) + sum(t['bytes'] for t in tex['textures'])),
                 reduced_objects=int(sum(1 for o in objects if o['reduced'])), max_textures=int(max([o['textures'] for o in objects] + [0])))
    notes = []
    if stats['max_textures'] > 48:
        notes.append('Some parts use more than 48 pictures; the largest shipped model has 48.')
    over = [s['id'] for s in sections if s['tris_out'] > sec_cap]
    if over:
        notes.append('%d sections stay over %d triangles' % (len(over), sec_cap))
    return dict(sections=sections, objects=objects, stats=stats, meters=_meters(stats), notes=notes, names=names)


def _build_objects(soup, UV, tri_tex, tri_dbl, names, idx, ratio, cx, cz, oid, depth=0):
    """One object (or, when a sub-mesh would pass the engine cap after the weld, the pieces of it)."""
    from todct import meshtex as MT
    T = soup.T[idx]
    tt = tri_tex[idx]
    dbl = tri_dbl[idx]
    parts = []
    before = int(len(idx) + dbl.sum())
    for tx in np.unique(tt).tolist():
        m = tt == tx
        t = T[m]
        used, inv = np.unique(t.reshape(-1), return_inverse=True)
        sub = SK.Soup(soup.P[used], soup.N[used], UV[used], np.full(len(used), tx, np.int32), inv.reshape(-1, 3).astype(np.int64))
        sub = SK.weld_vertices(sub, 0.002)
        d = dbl[m]
        parts.append((tx, sub, bool(d.any())))
    reduced = False
    if ratio < 0.999:
        pp = [MT.Part(names[tx], s.P.copy(), s.N.copy(), s.UV.copy(), s.T.copy(), dict(name=names[tx])) for tx, s, _ in parts]
        red = MI.reduce_parts(pp, ratio)
        byname = {q.name: q for q in red}
        newp = []
        for (tx, s, d) in parts:
            q = byname.get(names[tx])
            if q is not None and len(q.tris):
                newp.append((tx, SK.Soup(q.P, q.N, q.UV, np.full(len(q.P), tx, np.int32), q.tris), d))
        parts = newp
        reduced = True
    # model space: the object's own origin (round metres, y 0)
    allp = np.concatenate([s.P for _, s, _ in parts]) if parts else np.zeros((1, 3), np.float32)
    lo, hi = allp.min(0), allp.max(0)
    origin = np.array([round(float((lo[0] + hi[0]) / 2)), 0.0, round(float((lo[2] + hi[2]) / 2))])
    biggest = 0
    for tx, s, d in parts:
        biggest = max(biggest, len(s.P) * (2 if d else 1))
    if biggest > 60000 and len(idx) > 1 and depth < 12:
        ax = 0 if (cx[idx].max() - cx[idx].min()) >= (cz[idx].max() - cz[idx].min()) else 1
        c = (cx if ax == 0 else cz)[idx]
        half = c < (c.min() + c.max()) / 2
        if half.all() or (~half).all():
            half = np.arange(len(idx)) < len(idx) // 2
        return (_build_objects(soup, UV, tri_tex, tri_dbl, names, idx[half], ratio, cx, cz, oid + 'a', depth + 1)
                + _build_objects(soup, UV, tri_tex, tri_dbl, names, idx[~half], ratio, cx, cz, oid + 'b', depth + 1))
    from .mapgen.meshkit import Mesh
    mesh = Mesh()
    tris = verts = 0
    for tx, s, d in parts:
        P = s.P.astype(np.float64) - origin
        N, U, Tr = s.N, s.UV, s.T
        if d:
            m_ = len(P)
            P = np.concatenate([P, P])
            N = np.concatenate([N, -N])
            U = np.concatenate([U, U])
            Tr = np.concatenate([Tr, Tr[:, [0, 2, 1]] + m_])
        mesh.add(names[tx], P, N, U, Tr)
        tris += len(Tr)
        verts += len(P)
    nb = verts * RECORD_V + tris * RECORD_T
    big = max([len(s.P) * (2 if d else 1) for _, s, d in parts] + [0])
    return [dict(id=oid, mesh=mesh, origin=[float(origin[0]), 0.0, float(origin[2])], tris=int(tris), tris_before=before, verts=int(verts),
                 bytes=int(nb), max_submesh=int(big), textures=len(parts), reduced=reduced, idx=idx,
                 box=[round(float(lo[0]), 2), round(float(lo[2]), 2), round(float(hi[0]), 2), round(float(hi[2]), 2)])]


def run_chunks(sess, p, progress=None):
    tx = run_textures(sess, p, progress)
    cl = run_clean(sess, p, progress)
    key = _h([_key_select(p), p['clean'], p['textures'], p['sections']])
    return _stage(sess, 'chunks', key, lambda: build_chunks(sess, p, cl['soup'], tx, progress))


# ---------------------------------------------------------------------------------------------- collision
def build_collision(sess, p, soup, tex, ch, progress=None):
    cp = p['collision']
    if not cp.get('enabled', True):
        return dict(per_object={}, stats=dict(pieces=0, max_hulls=0, max_hull_verts=0), notes=['Collision is off.'], surfaces={})
    T = soup.T
    tri_cls = soup.tri_class().astype(np.int64)
    kinds = tex['class_kind']
    solid_cls = np.zeros(max(kinds) + 1, bool)
    cg = tex.get('class_glass') or {}
    for c, k in kinds.items():
        solid_cls[c] = (k == 'opaque') or bool(cg.get(c))        # a glass front still stops the player
    ok = solid_cls[tri_cls]
    # decoration: islands smaller than skip_size_m
    P = soup.P
    vid, nid = SK._quant_ids(P, 0.002)
    root = SK.components(vid, T, nid)
    tc = root[vid[T[:, 0]]]
    comps, cinv = np.unique(tc, return_inverse=True)
    cinv = cinv.reshape(-1)
    cen = _tri_centres(soup)
    order = np.argsort(cinv, kind='stable')
    cnt = np.bincount(cinv)
    b = np.concatenate([[0], np.cumsum(cnt)])
    cs = cen[order]
    ext = np.stack([np.maximum.reduceat(cs[:, a], b[:-1]) - np.minimum.reduceat(cs[:, a], b[:-1]) for a in range(3)], 1)
    size = np.linalg.norm(ext, axis=1)
    small = size[cinv] < float(cp['skip_size_m'])
    ok &= ~small
    names = list(limits_surface_names())
    sur_name = lambda c: (cp.get('surface') or {}).get(str(c)) or tex['class_surface'].get(c) or cp.get('default') or 'Concrete'   # noqa: E731
    cls_surface = np.zeros(max(kinds) + 1, np.int64)
    for c in kinds:
        nm = sur_name(c)
        cls_surface[c] = names.index(nm) if nm in names else names.index('Concrete')
    tri_surface = cls_surface[tri_cls]
    per, hulls, mx_h, mx_v = {}, 0, 0, 0
    log = []
    limit_pieces = min(int(cp.get('max_pieces') or 2000), limits.value('G3'))
    objs = ch['objects']
    world = []
    for oi, ob in enumerate(objs):
        if progress and oi % 10 == 0:
            progress('Collision', oi, len(objs))
        idx = ob['idx']
        m = np.zeros(len(T), bool)
        m[idx] = True
        pcs = SK.collision(P, T, ok & m, tri_surface, dict(cp, max_pieces=limit_pieces), log, N=soup.N)
        o = np.array(ob['origin'])
        world.append((ob['id'], o, [dict(points=pc['points'], surface=int(pc['surface']), tris=pc['tris']) for pc in pcs]))
    flat = [(k, pc) for k, (_, _, pcs) in enumerate(world) for pc in pcs]
    kept, dropped = SK.thin_stacks([pc for _, pc in flat], float(cp.get('stack_tol_m', 0.6)), float(cp.get('stack_cover', 0.9)))
    keep_ids = {id(pc) for pc in kept}
    for oid, o, pcs in world:
        out = [dict(points=pc['points'] - o, surface=pc['surface'], tris=pc['tris']) for pc in pcs if id(pc) in keep_ids]
        per[oid] = out
        hulls += len(out)
        mx_h = max(mx_h, len(out))
        mx_v = max([mx_v] + [len(x['points']) for x in out])
    if dropped:
        log.append('collision: %d floor pieces repeated another one (stacked layers) and were left out' % dropped)
    area = {}
    for c in np.unique(tri_cls).tolist():
        area[c] = sur_name(c)
    st = dict(pieces=hulls, max_hulls=mx_h, max_hull_verts=mx_v, skipped_cutout=int((~solid_cls[tri_cls]).sum()), skipped_small=int(small.sum()))
    notes = list(dict.fromkeys(log))
    return dict(per_object=per, stats=st, notes=notes, surfaces=area, surface_names=names)


def limits_surface_names():
    from .mapgen import core
    return core.MATERIALS


def run_collision(sess, p, progress=None):
    ch = run_chunks(sess, p, progress)
    tx = run_textures(sess, p, progress)
    cl = run_clean(sess, p, progress)
    key = _h([_key_select(p), p['clean'], p['textures'], p['sections'], p['collision']])
    return _stage(sess, 'collision', key, lambda: build_collision(sess, p, cl['soup'], tx, ch, progress))


# ---------------------------------------------------------------------------------------------- the reports the screen shows
def report(sid, params, stage, progress=None):
    """Run the stages up to `stage` and return the numbers of that stage (and the earlier ones)."""
    sess = get(sid)
    p = merged(params)
    out = {}
    sel = run_select(sess, p, progress)
    out['select'] = sel['stats']
    if stage == 'select':
        return out
    cl = run_clean(sess, p, progress)
    out['clean'] = cl['report']
    if stage == 'clean':
        return out
    tx = run_textures(sess, p, progress)
    from . import ledger
    rows = [ledger._fill(ledger._row_base('P6'), tx['report']['largest']), ledger._fill(ledger._row_base('P2'), tx['report']['bytes'])]
    out['textures'] = dict(report=tx['report'], notes=tx['notes'], meters=rows, list=[{k: v for k, v in t.items() if k != 'kind'} for t in tx['textures']][:200])
    if stage == 'textures':
        return out
    ch = run_chunks(sess, p, progress)
    out['chunks'] = dict(stats=ch['stats'], meters=ch['meters'], notes=ch['notes'],
                         sections=ch['sections'], objects=[{k: v for k, v in o.items() if k not in ('mesh', 'idx')} for o in ch['objects']][:2000])
    if stage == 'chunks':
        return out
    co = run_collision(sess, p, progress)
    st = dict(ch['stats'], **{k: co['stats'][k] for k in ('max_hulls', 'max_hull_verts')})
    out['collision'] = dict(stats=co['stats'], notes=co['notes'], meters=_meters(st), surfaces=co['surfaces'], surface_names=co.get('surface_names'),
                            classes=class_rows(sess, tx, cl['soup']))
    return out


def class_rows(sess, tex, soup, limit=60):
    """The biggest material classes of the cleaned region with their surface (the screen lets the user change it)."""
    tri_cls = soup.tri_class()
    cnt = np.bincount(tri_cls, minlength=len(sess.classes))
    rows = []
    for c in np.argsort(-cnt)[:limit].tolist():
        if cnt[c] == 0:
            continue
        rows.append(dict(id=c, name=sess.classes[c]['name'], tris=int(cnt[c]), kind=tex['class_kind'].get(c), surface=tex['class_surface'].get(c)))
    return rows


# ---------------------------------------------------------------------------------------------- previews (vertex coloured glb)
def _glb(P, N, C, T):
    """P in game axes -> viewer axes (z negated), vertex colours, one mesh."""
    V = (P.astype(np.float32) * np.array([1, 1, -1], np.float32))
    Nn = (N.astype(np.float32) * np.array([1, 1, -1], np.float32))
    Tr = T.astype(np.uint32)[:, [0, 2, 1]]
    bin_ = bytearray()
    views, acc = [], []

    def add(arr, comp, typ, target, mm=False):
        arr = np.ascontiguousarray(arr)
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=arr.nbytes, target=target))
        bin_.extend(arr.tobytes())
        a = dict(bufferView=len(views) - 1, componentType=comp, count=int(arr.shape[0]) if typ != 'SCALAR' else int(arr.size), type=typ)
        if mm:
            a['min'], a['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        acc.append(a)
        return len(acc) - 1
    pa = add(V, 5126, 'VEC3', 34962, True)
    na = add(Nn, 5126, 'VEC3', 34962)
    ca = add(C.astype(np.uint8), 5121, 'VEC4', 34962)
    acc[ca]['normalized'] = True
    ia = add(Tr.reshape(-1), 5125, 'SCALAR', 34963)
    js = dict(asset=dict(version='2.0', generator='todms'), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0, name='scene')],
              meshes=[dict(primitives=[dict(attributes=dict(POSITION=pa, NORMAL=na, COLOR_0=ca), indices=ia, material=0)])],
              materials=[dict(doubleSided=True, pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=1.0))],
              accessors=acc, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    jb = json.dumps(js, separators=(',', ':')).encode('utf-8')
    jb += b' ' * (-len(jb) % 4)
    bb = bytes(bin_) + b'\0' * (-len(bin_) % 4)
    return struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bb)) + struct.pack('<II', len(jb), 0x4E4F534A) + jb + \
        struct.pack('<II', len(bb), 0x004E4942) + bb


def _class_colors(sess, classes):
    out = np.zeros((len(sess.classes), 4), np.uint8)
    for c in classes:
        k = sess.classes[c]
        mean = sess.info(k['image'])['mean'] if k['image'] is not None else k['color']
        out[c, :3] = np.clip(np.asarray(mean) * 255, 0, 255).astype(np.uint8)
        out[c, 3] = 255
    return out


def _shaded(sess, soup):
    """Vertex colours of a preview: the mean colour of each picture, lit from above-left so shapes read, brightened (captures are dark)."""
    col = _class_colors(sess, np.unique(soup.VM).tolist())[soup.VM].astype(np.float32)
    n = soup.N.astype(np.float32) * np.array([1, 1, 1], np.float32)
    light = np.array([0.35, 0.8, 0.5], np.float32)
    light /= np.linalg.norm(light)
    shade = 0.5 + 0.5 * np.clip(np.abs(n @ light), 0, 1)
    rgb = np.clip(col[:, :3] * 1.45 + 22.0, 0, 255) * shade[:, None]
    out = np.concatenate([np.clip(rgb, 0, 255), np.full((len(rgb), 1), 255, np.float32)], axis=1)
    return out.astype(np.uint8)


def _cdir():
    d = os.path.join(paths.cache_dir(), 'scene', 'preview')
    os.makedirs(d, exist_ok=True)
    return d


def sample_glb(sid, params, center, radius, max_tris=150000):
    """Raw geometry around `center` (game x, z at scale 1, unshifted) for picking the scale: the file's own units (scale 1), coloured by picture."""
    sess = get(sid)
    p = merged(params)
    p['scale'] = 1.0
    A = axes_matrix(p)
    cx, cz = float(center[0]), float(center[1])
    r = float(radius)
    poly = [[cx - r, cz - r], [cx + r, cz - r], [cx + r, cz + r], [cx - r, cz + r]]
    p['region'] = dict(polygon=poly, mode='clip')
    p['place'] = [0, 0, 0]
    sel = select(sess, p)
    soup = sel['soup']
    if soup.tris > max_tris:
        keep = np.arange(soup.tris)[:: int(math.ceil(soup.tris / max_tris))]
        soup = soup.subset(keep)
    key = _h([sid, p['up'], p['mirror'], p['yaw'], center, radius, 2])
    path = os.path.join(_cdir(), key + '.glb')
    with open(path, 'wb') as f:
        f.write(_glb(soup.P, soup.N, _shaded(sess, soup), soup.T))
    shift = sel['stats']['shift']
    return dict(url='/cache/scene/preview/' + key + '.glb', triangles=soup.tris, shift=shift, size=sel['stats']['size'])


def stage_glb(sid, params, stage, max_tris=250000):
    """The geometry after `stage` (select | clean) as a coloured glb; the result of the chunk stage coloured by section."""
    sess = get(sid)
    p = merged(params)
    if stage == 'select':
        soup = run_select(sess, p)['soup']
    else:
        soup = run_clean(sess, p)['soup']
    if soup.tris > max_tris:
        soup = soup.subset(np.arange(soup.tris)[:: int(math.ceil(soup.tris / max_tris))])
    key = _h([sid, stage, _key_select(p), p['clean'] if stage != 'select' else 0, 2])
    path = os.path.join(_cdir(), key + '.glb')
    with open(path, 'wb') as f:
        f.write(_glb(soup.P, soup.N, _shaded(sess, soup), soup.T))
    return dict(url='/cache/scene/preview/' + key + '.glb', triangles=soup.tris)


# ---------------------------------------------------------------------------------------------- send
TEMPLATE_MAP = dict(
    source='map10_runawaytrain',
    entry=dict(block='submap01_map02_lostoros_downtown.submap', pos=[-237, 2.5, -43.66],
               parent=dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'),
               size=[12, 6, 2], orient=[0, .70710678, 0, .70710678]),
    teleports=[],
    **{'return': dict(pos=[-52.0, 5.0, -52.0], size=[6, 6, 2], orient=[0, 0, 0, 1], target_map='MAINMAP_Map02_LosToros_Downtown',
                      target_submap='SUBMAP01_Map02_LosToros_Downtown', teleport_to='TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill',
                      teleport_block='overdose.main')})


def rescale_map(m, r):
    """The places of a map that were set or chosen relative to the scene, moved for a new scale (`r` = new scale / old scale).
    The scene's origin is its middle at the floor of its lowest point, so everything moves out from there by `r` (a standing place keeps its
    metre above the floor, a box keeps its own height). Not moved: anything in the host map (entrance, landing spot), the sizes of triggers and
    walls; recomputed from the new geometry by the caller: edges and water (their tiles stay within the size limit)."""
    out = json.loads(json.dumps(m))
    r = float(r)

    def stand(p):
        return [round(p[0] * r, 3), round(r * (p[1] - 1.0) + 1.0, 3), round(p[2] * r, 3)]

    def box(p, h):                                   # a trigger box moves out like the geometry: its middle keeps its place against the floor (a box set 0.7 m above the floor is 1.4 m above at double scale, still around the player)
        return [round(p[0] * r, 3), round(p[1] * r, 3), round(p[2] * r, 3)]
    if (out.get('arrival') or {}).get('pos'):
        out['arrival']['pos'] = stand(out['arrival']['pos'])
    if (out.get('return') or {}).get('pos'):
        out['return']['pos'] = box(out['return']['pos'], float((out['return'].get('size') or [6, 6, 2])[1]))
    for e in out.get('entries') or []:
        if (e.get('arrive') or {}).get('pos'):
            e['arrive']['pos'] = stand(e['arrive']['pos'])
        b = e.get('back')
        if b and b.get('pos'):
            b['pos'] = box(b['pos'], float((b.get('size') or [6, 6, 2])[1]))
    fog = (out.get('look') or {}).get('fog')
    if fog:
        for k in ('near', 'far'):
            if fog.get(k) is not None:
                fog[k] = round(float(fog[k]) * r, 1)
    sc = out.get('scene') or {}
    if sc.get('ground_y') is not None:
        sc['ground_y'] = round(float(sc['ground_y']) * r, 2)
    return out


def move_map(m, d):
    """Everything of a map that lives in the scene's own space, moved by `d` = [dx, dy, dz] (a new place of the scene in the world). The scene's
    footprint, its edge walls, the sea, the places of the entrances, the way back, named spots and the plan all move as one; what lies in a host
    map (entrance boxes, landing spots) stays. A place at the origin is the identity."""
    out = json.loads(json.dumps(m))
    dx, dy, dz = (float(v) for v in d)
    if not (dx or dy or dz):
        return out

    def pt(p):
        return [round(p[0] + dx, 3), round(p[1] + dy, 3), round(p[2] + dz, 3)]

    def xz(p):
        return [round(p[0] + dx, 3), round(p[1] + dz, 3)]

    def rc(r):
        return [round(r[0] + dx, 3), round(r[1] + dz, 3), round(r[2] + dx, 3), round(r[3] + dz, 3)]
    if (out.get('arrival') or {}).get('pos'):
        out['arrival']['pos'] = pt(out['arrival']['pos'])
    if (out.get('return') or {}).get('pos'):
        out['return']['pos'] = pt(out['return']['pos'])
    for t in out.get('teleports') or []:
        if t.get('pos'):
            t['pos'] = pt(t['pos'])
    for e in out.get('entries') or []:
        if (e.get('arrive') or {}).get('pos'):
            e['arrive']['pos'] = pt(e['arrive']['pos'])
        if (e.get('back') or {}).get('pos'):
            e['back']['pos'] = pt(e['back']['pos'])
    for w in out.get('edges') or []:
        if w.get('rect'):
            w['rect'] = rc(w['rect'])
        k = w.get('kill') or {}
        if k.get('below') is not None:
            k['below'] = round(float(k['below']) + dy, 3)
        if k.get('respawn'):
            k['respawn'] = xz(k['respawn'])
    for w in out.get('water') or []:
        if w.get('rect'):
            w['rect'] = rc(w['rect'])
        if w.get('level') is not None:
            w['level'] = round(float(w['level']) + dy, 3)
        if w.get('reset'):
            w['reset'] = xz(w['reset'])
    sc = out.get('scene') or {}
    if sc.get('ground_y') is not None:
        sc['ground_y'] = round(float(sc['ground_y']) + dy, 3)
    if (sc.get('water') or {}).get('level') is not None:
        sc['water']['level'] = round(float(sc['water']['level']) + dy, 3)
    for s in sc.get('streets') or []:
        if s.get('pos'):
            s['pos'] = pt(s['pos'])
    pl = sc.get('plan') or {}
    if pl.get('x0') is not None:
        pl['x0'] = round(float(pl['x0']) + dx, 3)
    if pl.get('z1') is not None:
        pl['z1'] = round(float(pl['z1']) + dz, 3)
    for p in (pl.get('steps') or {}).get('places') or []:
        p[0], p[1] = round(p[0] + dx, 3), round(p[1] + dz, 3)
    return out


def place_of(m):
    """Where a map's scene stands in the world (the `place` it was sent with): [x, y, z], the origin when it was never placed."""
    v = (((m.get('scene') or {}).get('params') or {}).get('place')) or [0, 0, 0]
    return [float(v[0]), float(v[1]), float(v[2])]


def kept_scene(old, summary):
    """The scene summary of a send that replaces an existing map: new numbers, but the project's own ground level."""
    return dict(summary, ground_y=(old.get('scene') or {}).get('ground_y', summary.get('ground_y')))


def _part_blob(part):
    return assetstore.put(zlib.compress(json.dumps(part, separators=(',', ':')).encode('utf-8'), 6))


def arrival_spot(soup):
    """A standing place near the middle: the highest upward-facing surface within 15 m of the centre, plus a metre."""
    P, T = soup.P, soup.T
    n, area = SK.tri_normals_area(P, T)
    cen = _tri_centres(soup)
    mid = (P.min(0) + P.max(0)) / 2
    d = np.hypot(cen[:, 0] - mid[0], cen[:, 2] - mid[2])
    for rad in (15.0, 40.0, 120.0, 1e9):
        m = (np.abs(n[:, 1]) > 0.8) & (d < rad) & (area > 0.5)
        if m.any():
            i = np.nonzero(m)[0]
            j = i[np.argmin(d[i])]
            return [round(float(cen[j, 0]), 2), round(float(cen[j, 1]) + 1.0, 2), round(float(cen[j, 2]), 2)]
    return [0.0, round(float(P[:, 1].max()) + 1.0, 2), 0.0]


def street_spots(soup, surface_of_class, count=3, cell=4.0):
    """Places to stand on a street, near the middle of the scene: flat road surface (an upward face whose picture reads as asphalt) in 4 m cells,
    joined into streets by neighbouring cells at about the same height; the best streets by size and nearness to the middle give a spot on the
    street and the way it runs (a yaw in degrees, facing the longer way along the street, in the engine's convention: 0 faces +z, 90 faces -x).
    -> [dict(pos [x, y, z], yaw, area, length)] best first; [] when the scene has no road surface."""
    P, T = soup.P, soup.T
    n, area = SK.tri_normals_area(P, T)
    cls = soup.tri_class().astype(np.int64)
    names = np.array([surface_of_class.get(int(c), 'Concrete') for c in range(int(cls.max()) + 1)])
    road = (n[:, 1] > 0.9) & (names[cls] == 'Asphalt')
    if not road.any():
        return []
    cen = _tri_centres(soup)[road]
    ar = area[road]
    mid = (P.min(0) + P.max(0)) / 2
    gx = np.floor((cen[:, 0] - mid[0]) / cell).astype(np.int64)
    gz = np.floor((cen[:, 2] - mid[2]) / cell).astype(np.int64)
    cells = {}
    for k, (x, z) in enumerate(zip(gx.tolist(), gz.tolist())):
        cells.setdefault((x, z), []).append(k)
    keep = {c: v for c, v in cells.items() if float(ar[v].sum()) >= 2.0}
    seen, streets = set(), []
    for c0 in keep:
        if c0 in seen:
            continue
        stack, comp = [c0], []
        seen.add(c0)
        while stack:
            c = stack.pop()
            comp.append(c)
            yc = float(np.median(cen[keep[c], 1]))
            for dx in (-2, -1, 0, 1, 2):                     # big road faces leave gaps between their centres: reach two cells
                for dz in (-2, -1, 0, 1, 2):
                    q = (c[0] + dx, c[1] + dz)
                    if q in keep and q not in seen and abs(float(np.median(cen[keep[q], 1])) - yc) <= 1.5:
                        seen.add(q)
                        stack.append(q)
        streets.append(comp)
    out = []
    for comp in streets:
        idx = np.concatenate([keep[c] for c in comp])
        a = float(ar[idx].sum())
        if a < 150.0:
            continue
        xz = cen[idx][:, [0, 2]]
        w = ar[idx]
        mu = (xz * w[:, None]).sum(0) / w.sum()
        dist = float(np.hypot(*(mu - mid[[0, 2]])))
        out.append((a / (1.0 + dist / 60.0), comp, idx, a))
    out.sort(key=lambda t: -t[0])
    res = []
    for _, comp, idx, a in out[:count]:
        xz = cen[idx][:, [0, 2]]
        w = ar[idx]
        mu = (xz * w[:, None]).sum(0) / w.sum()
        near = np.argsort(np.hypot(xz[:, 0] - mu[0], xz[:, 1] - mu[1]))[:1]
        pick = idx[near[0]]
        c0 = cen[pick]
        win = np.hypot(xz[:, 0] - c0[0], xz[:, 1] - c0[2]) < 30.0      # the way it runs around the spot
        d = xz[win] - xz[win].mean(0)
        _, _, vt = np.linalg.svd(d * np.sqrt(w[win])[:, None], full_matrices=False)
        ax = vt[0]
        t = d @ ax
        if abs(float(t.max())) < abs(float(t.min())):                    # face the longer way
            ax = -ax
        yaw = math.degrees(math.atan2(-ax[0], ax[1])) % 360.0
        res.append(dict(pos=[round(float(c0[0]), 2), round(float(c0[1]) + 1.0, 2), round(float(c0[2]), 2)], yaw=round(yaw, 1),
                        area=round(a), length=round(float(t.max() - t.min()), 1)))
    return res


def map_name_for(title, length=18, taken=()):
    """A readable map name of exactly `length` characters (the builder renames the clone source's strings in place): see world.suggest_map_name."""
    from . import world
    return world.suggest_map_name(title, length, taken)


def void_water(soup, level, reach=100.0, cell=4.0, min_area=1200.0, max_bodies=40, tile=160.0, max_resets=10):
    """Where the scene has no floor, water: the district of a capture is an island, and the sea between islands is simply not drawn.
    Water lies under everything that stands above it (streets, bridges, buildings hide it from above and a fall through a gap meets it);
    the footprints of the ground at or just above the water level (a sunken road, a quay, a bank) are left dry. They are rasterised; the empty cells of one connected stretch of at least `min_area`
    square metres (the rim of the region and `reach` metres beyond it count as empty) are cut into rectangles, largest first.
    -> [dict(id, rect [x0, z0, x1, z1], level, rule, cell)] (rectangles inside the region first, none longer than `tile` metres)."""
    from PIL import Image, ImageDraw
    P = soup.P.astype(np.float64)
    T = soup.T
    lo = P.min(0)
    hi = P.max(0)
    x0, z0 = float(lo[0]) - reach, float(lo[2]) - reach
    nx = int(math.ceil((float(hi[0]) + reach - x0) / cell))
    nz = int(math.ceil((float(hi[2]) + reach - z0) / cell))
    n, _ = SK.tri_normals_area(P, T)
    img = Image.new('L', (nx, nz), 0)
    dr = ImageDraw.Draw(img)
    low = (P[T[:, 0], 1] + P[T[:, 1], 1] + P[T[:, 2], 1]) / 3.0 < float(level) + 2.5
    for k in np.nonzero((n[:, 1] > 0.3) & low)[0]:
        dr.polygon([((P[i, 0] - x0) / cell, (P[i, 2] - z0) / cell) for i in T[k]], fill=255)
    cov = np.asarray(img) > 0
    img_all = Image.new('L', (nx, nz), 0)
    dr_all = ImageDraw.Draw(img_all)
    for k in np.nonzero(np.abs(n[:, 1]) > 0.3)[0]:
        dr_all.polygon([((P[i, 0] - x0) / cell, (P[i, 2] - z0) / cell) for i in T[k]], fill=255)
    anything = np.asarray(img_all) > 0
    pad = cov.copy()                                   # a little margin round buildings and slopes
    pad[1:, :] |= cov[:-1, :]
    pad[:-1, :] |= cov[1:, :]
    pad[:, 1:] |= cov[:, :-1]
    pad[:, :-1] |= cov[:, 1:]
    free = ~pad
    # keep the connected stretches that are big enough (a flood fill on the coarse grid)
    lab = np.zeros(free.shape, np.int32)
    cur = 0
    keep = np.zeros(free.shape, bool)
    for j0, i0 in zip(*np.nonzero(free)):
        if lab[j0, i0]:
            continue
        cur += 1
        stack = [(j0, i0)]
        lab[j0, i0] = cur
        cells = []
        while stack:
            j, i = stack.pop()
            cells.append((j, i))
            for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = j + dj, i + di
                if 0 <= a < nz and 0 <= b < nx and free[a, b] and not lab[a, b]:
                    lab[a, b] = cur
                    stack.append((a, b))
        if len(cells) * cell * cell >= min_area:
            for j, i in cells:
                keep[j, i] = True
    rects = []
    work = keep.copy()
    while len(rects) < max_bodies and work.any():
        h = np.zeros(nx, np.int32)                    # largest rectangle of set cells (histogram stack, row by row)
        best = (0, 0, 0, 0, 0)
        for j in range(nz):
            h = np.where(work[j], h + 1, 0)
            st = []
            for i in range(nx + 1):
                cur_h = int(h[i]) if i < nx else 0
                start = i
                while st and st[-1][1] >= cur_h:
                    si, sh = st.pop()
                    if sh * (i - si) > best[0]:
                        best = (sh * (i - si), si, j - sh + 1, i, j + 1)
                    start = si
                st.append((start, cur_h))
        if best[0] * cell * cell < min_area * 0.15:
            break
        _, a, b, c, d = best
        work[b:d, a:c] = False
        rects.append([round(x0 + a * cell, 1), round(z0 + b * cell, 1), round(x0 + c * cell, 1), round(z0 + d * cell, 1)])
    # one model must not span hundreds of metres (a water model 800 m long stopped the game while the map block loaded): cut every body into tiles
    tiled = []
    for r in rects:
        nxt = max(1, int(math.ceil((r[2] - r[0]) / tile)))
        nzt = max(1, int(math.ceil((r[3] - r[1]) / tile)))
        for a in range(nxt):
            for b in range(nzt):
                tiled.append([round(r[0] + (r[2] - r[0]) * a / nxt, 1), round(r[1] + (r[3] - r[1]) * b / nzt, 1),
                              round(r[0] + (r[2] - r[0]) * (a + 1) / nxt, 1), round(r[1] + (r[3] - r[1]) * (b + 1) / nzt, 1)])
    rects = tiled
    out = []
    for k, r in enumerate(rects):
        a0, a1 = int((r[0] - x0) / cell), max(int((r[0] - x0) / cell) + 1, int((r[2] - x0) / cell))
        b0, b1 = int((r[1] - z0) / cell), max(int((r[1] - z0) / cell) + 1, int((r[3] - z0) / cell))
        open_share = 1.0 - float(anything[b0:b1, a0:a1].mean()) if anything[b0:b1, a0:a1].size else 0.0
        # a reset acts where a player can fall into open water: inside the region, and over ground that is really empty (under a street the water is only a floor)
        inside = float(lo[0]) <= (r[0] + r[2]) / 2 <= float(hi[0]) and float(lo[2]) <= (r[1] + r[3]) / 2 <= float(hi[2]) and open_share >= 0.5 and len([1 for q in out if q['rule'] == 'reset']) < max_resets
        out.append(dict(id='sea%d' % (k + 1), rect=r, level=float(level), depth=2.0, bank=0.5, opaque=True, rule='reset' if inside else 'none',
                        cell=float(max(4.0, round(max(r[2] - r[0], r[3] - r[1]) / 40.0, 1)))))
    out.sort(key=lambda w: w['rule'] != 'reset')
    return out



def send(sid, params, target, progress=None):
    """Write the result as recipe data. target: dict(kind 'newmap' | 'section', id (existing project) or None, name, host for a section).
    -> dict(id, name, models, placements, textures, notes)."""
    from . import newmap
    sess = get(sid)
    p = merged(params)
    ch = run_chunks(sess, p, progress)
    tx = run_textures(sess, p, progress)
    co = run_collision(sess, p, progress)
    cl = run_clean(sess, p, progress)
    name = (target.get('name') or p.get('name') or 'Scene').strip()
    map_name = map_name_for(name, 18)                   # len('Map10_RunawayTrain'): the clone source of every new map
    folder = map_name
    models, places = [], []
    per = co['per_object']
    mapping = dict(Concrete=None)
    names_mat = co.get('surface_names') or limits_surface_names()
    for i, ob in enumerate(ch['objects']):
        if progress:
            progress('Writing the models', i, len(ch['objects']))
        mesh = ob['mesh']
        mesh.hulls = []                                  # the stage keeps the mesh: a second send must not stack the pieces twice
        for pc in per.get(ob['id'], []):
            mesh.hull(pc['points'], 'solid', names_mat[pc['surface']] if 0 <= pc['surface'] < len(names_mat) else 'Concrete')
        part = mesh.part()
        sha = _part_blob(part)
        mname = 'SC%04d' % i
        models.append(dict(name=mname, parts=[dict(type='mapgen', ref=sha)]))
        places.append(dict(model=mname, pos=[round(ob['origin'][0], 3), 0.0, round(ob['origin'][2], 3)], name='SCN_%04d' % i))
    textures = recipe_textures(tx['textures'])
    ng = dict(folder=folder, drop_source_content=True, drop_unused_assets=True, statically_lit=False, textures=textures, models=models, placements=places)
    stats = dict(ch['stats'], pieces=co['stats'].get('pieces', 0), triangles_in_region=cl['report']['triangles_in'])
    summary = dict(kind='scene', source=os.path.basename(sess.path), params=_public_params(p), stats=stats,
                   clean=cl['report'], textures=tx['report'], section_tris_max=stats['section_tris_max'], notes=ch['notes'] + tx['notes'] + co['notes'])
    streets = street_spots(cl['soup'], tx.get('class_surface') or {})
    if streets:                                                # on a street, looking down it
        arrive, yaw = streets[0]['pos'], streets[0]['yaw']
        summary['streets'] = streets
    else:
        arrive, yaw = arrival_spot(cl['soup']), 0.0
    h = math.radians(yaw)
    m = dict(TEMPLATE_MAP)
    m = json.loads(json.dumps(m))
    m.update(name=map_name, arrival=dict(pos=arrive, orient=[0.0, round(math.sin(h / 2), 6), 0.0, round(math.cos(h / 2), 6)], floor='none'), new_geometry=ng, scene=summary)
    m['return'] = dict(m['return'])
    m['return']['pos'] = [round(arrive[0] + math.sin(h) * 6.0, 2), arrive[1] + 1.0, round(arrive[2] - math.cos(h) * 6.0, 2)]     # six metres behind the arrival
    # the edge treatment: invisible walls along the border of the region (tall enough for every building), a kill plane under the scene that
    # puts a fallen player back on the street, and fog so the void past the edge reads as haze. Chosen here, editable in the Edges and Look tools.
    soup = cl['soup']
    pmin, pmax = soup.P.min(0), soup.P.max(0)
    inset = 1.0
    rect = [round(float(pmin[0]) + inset, 1), round(float(pmin[2]) + inset, 1), round(float(pmax[0]) - inset, 1), round(float(pmax[2]) - inset, 1)]
    ground = round(float(arrive[1]) - 1.0, 2)
    summary['ground_y'] = ground
    if target.get('edges', True):
        m['edges'] = [dict(id='rim', kind='invisible', rect=rect, height=round(float(pmax[1]) - ground + 20.0, 1),
                           kill=dict(below=round(float(pmin[1]) - 30.0, 1), respawn=[arrive[0], arrive[2]]))]
        m['look'] = dict(preset='city_day', fog=dict(near=90.0, far=380.0))
        m['backdrop'] = dict(kind='skyline', height='scene')     # a far ring of towers past the edge (the scene's own building heights), instead of bare sea
    old_level = None
    if target.get('id') and (target.get('kind') or 'newmap') != 'section':
        try:                                                   # a map sent before at another scale: its sea level moves out with the scale
            for om in newmap.get_project(target['id'])['params'].get('maps') or []:
                osc = om.get('scene') or {}
                if om.get('name') == map_name and (osc.get('water') or {}).get('level') is not None:
                    opy = place_of(om)[1]
                    old_level = (float(osc['water']['level']) - opy) * float(p['scale']) / float(((osc.get('params') or {}).get('scale')) or 1.0) + float(p['place'][1])
        except (OSError, ValueError, KeyError):
            pass
    if target.get('water', True):
        wl = target.get('water_level')
        wl = float(wl) if wl is not None else (round(old_level, 2) if old_level is not None else round(ground - 4.1, 2))
        bodies = void_water(soup, wl)
        for w in bodies:
            if w['rule'] == 'reset':
                w['reset'] = [arrive[0], arrive[2]]
        if bodies:
            m['water'] = bodies
            summary['water'] = dict(level=wl, bodies=len(bodies), area=int(sum((w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]) for w in bodies)))
    kind = target.get('kind') or 'newmap'
    pid = target.get('id')
    if kind == 'section':
        host = target.get('host') or {}
        if not host.get('block'):
            raise SceneError('choose the host section first')
        m = dict(name=map_name, placement='extension', host=host, carry=dict(mode='all'), new_geometry=ng, scene=summary)
    ratio = 1.0
    moved_by = prev_place = None
    if pid:
        proj = newmap.get_project(pid)['params']
        maps = proj.get('maps') or []
        for i, old in enumerate(maps):
            if old.get('name') == map_name:
                keep = {k: v for k, v in m.items() if k in ('new_geometry', 'scene')}
                old_scale = float((((old.get('scene') or {}).get('params') or {}).get('scale')) or 1.0)
                ratio = float(p['scale']) / old_scale
                old_place = place_of(old)
                new_place = [float(v) for v in p['place']]
                if any(abs(a - b) > 1e-6 for a, b in zip(old_place, new_place)):
                    moved_by = new_place
                    prev_place = old_place
                if abs(ratio - 1.0) > 1e-6 or moved_by is not None:
                    # a new scale or a new place: what was placed relative to the scene follows it (out from the scene's own middle, then to its new
                    # place); the edge walls and the water come from the new geometry
                    old = move_map(old, [-v for v in old_place])
                    if abs(ratio - 1.0) > 1e-6:
                        old = rescale_map(old, ratio)
                    old = move_map(old, new_place)
                    keep['scene'] = kept_scene(old, summary)
                    arr = (old.get('arrival') or {}).get('pos') or arrive
                    if m.get('edges'):
                        keep['edges'] = json.loads(json.dumps(m['edges']))
                        for e in keep['edges']:
                            if (e.get('kill') or {}).get('respawn'):
                                e['kill']['respawn'] = [arr[0], arr[2]]
                    if m.get('water'):
                        keep['water'] = json.loads(json.dumps(m['water']))
                        for w in keep['water']:
                            if w.get('reset'):
                                w['reset'] = [arr[0], arr[2]]
                    else:
                        old.pop('water', None)
                if abs(ratio - 1.0) <= 1e-6 and moved_by is None:
                    keep['scene'] = kept_scene(old, summary)         # the same scale: the ground level the project holds stays
                maps[i] = dict(old, **keep)
                break
        else:
            maps.append(m)
        proj['maps'] = maps
        params_out = proj
    else:
        params_out = dict(package=name, maps=[m])
    plan = None
    if kind != 'section':                                      # the picture of the streets, for the minimap and the mission placement view
        placed = [x for x in params_out['maps'] if x.get('name') == map_name]
        if placed:
            tm = placed[0]
            try:
                plan = plan_of(cl['soup'], tx.get('class_surface') or {}, float((tm.get('scene') or {}).get('ground_y', ground)), tm.get('water'), tx.get('class_mean'))
            except (ValueError, MemoryError):
                plan = None
            if plan:
                tm['scene'] = dict(tm.get('scene') or {}, plan=scenplan.info_of(plan))
    saved = newmap.save_project(params_out, pid)
    if plan:
        scenplan.write(newmap.directory(saved['id']), plan)
    moved = 0
    if pid and (abs(ratio - 1.0) > 1e-6 or moved_by is not None):
        from . import missions_tpl
        moved = missions_tpl.rescale_hosts(saved['id'], ratio, prev_place or [0, 0, 0], moved_by or [float(v) for v in p['place']])   # the missions on this map follow
    changed = abs(ratio - 1.0) > 1e-6 or moved_by is not None
    return dict(id=saved['id'], name=name, models=len(models), placements=len(places), textures=len(textures), notes=summary['notes'],
                section=kind == 'section', rescaled=dict(ratio=round(ratio, 6), place=list(moved_by) if moved_by else None, mission_projects=moved) if changed else None)


def _reads_as_road(surface, mean):
    """A street picture: asphalt by the surface rule, or a neutral mid-to-dark grey (a worn road reads as concrete to the surface rule)."""
    if surface == 'Asphalt':
        return True
    if not mean or len(mean) < 3:
        return False
    r, g, b = (float(v) for v in mean[:3])
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return max(r, g, b) - min(r, g, b) < 0.07 and 0.08 <= lum <= 0.52


def plan_of(soup, surface_of_class, ground_y, water=None, class_mean=None):
    """The plan of the cleaned scene (see scenplan): streets, open ground, buildings and the sea bodies of the map. None for an empty scene."""
    cls = soup.tri_class().astype(np.int64)
    if not len(cls):
        return scenplan.make(soup.P, soup.T, np.zeros(0, bool), ground_y)
    is_road = np.array([_reads_as_road(surface_of_class.get(c), (class_mean or {}).get(c)) for c in range(int(cls.max()) + 1)])
    return scenplan.make(soup.P, soup.T, is_road[cls], ground_y, [w['rect'] for w in (water or []) if w.get('rect')])


def _public_params(p):
    q = json.loads(json.dumps(p))
    q['region'] = dict(q.get('region') or {})
    return q


# ---------------------------------------------------------------------------------------------- texture kinds of the builder
def _scene_pixels(kind, size):
    img = TX.read_image(assetstore.get(kind[len(REF_KIND):]))
    if img.shape[0] != size or img.shape[1] != size:
        img = TX.resize(img, size, size)
    return img


_installed = []


def install_kinds():
    """Teach the builder's texture generator the kind `scene:<sha>` (a picture of the asset store): three channels when the picture is
    opaque (the DXT1 encoder), four when it carries alpha (the 32-bit encoder). Idempotent."""
    if _installed:
        return True
    import sys
    vend = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'vendor', 'newmap'))
    if vend not in sys.path:
        sys.path.append(vend)
    import tex_gen
    orig = tex_gen.generate

    def generate(kind, size, seed=1):
        if isinstance(kind, str) and kind.startswith(REF_KIND):
            img = _scene_pixels(kind, size)
            img = np.clip(img, 0.0, 1.0)
            return img[..., :3] if float(img[..., 3].min()) >= 0.999 else img
        return orig(kind, size, seed)
    tex_gen.generate = generate
    _installed.append(True)
    return True
