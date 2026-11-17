"""Roads: a spline (control points, width, lanes, kerb) becomes an asphalt ribbon draped on the terrain, kerbs, lane markings (in
the texture), asphalt collision and a seed traffic route; with `elevated: true` it is a bridge or ramp (deck, side walls, pillars).

Recipe key `roads` (a list; every field but `points` is optional):
  {"id": "main", "points": [[x, z] or [x, z, height], ...],     control points; a third number pins the road height there
   "width": 8.0, "lanes": 2,                               one texture with 1 to 4 lanes of markings across the width
   "kerb": true,                                           a low concrete kerb on both sides (draped roads)
   "step": 2.0,                                            metres between cross-sections
   "grade": true,                                          flatten the terrain under a draped road (and a shoulder beside it)
   "shoulder": 6.0,                                        metres over which the grading blends back into the terrain
   "elevated": false,                                      bridge or ramp: the deck follows the heights of the control points (the two
                                                           end points without a height sit on the ground, a middle point without one is
                                                           free), pillars reach down to the ground
   "deck": {"thickness": 0.8, "wall": 1.0, "pillar_every": 12.0},      (elevated only)
   "traffic": true}                                        seed a two-way traffic route along the road
"""
import math

from .core import np, MapgenError, smoothstep
from .meshkit import Mesh

LIFT = 0.06                 # asphalt sits this far above the graded ground (avoids z-fighting with the ground mesh)
KERB_H, KERB_W = 0.18, 0.30
SLOPE_CAR, SLOPE_WALK = 0.15, 0.35
SEG_SAMPLES = 160           # cross-sections per generated model
HULL_EVERY = 4.0            # metres of road per collision piece
TRAFFIC_EVERY = 12.0


def _cr(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)


def spline(pts, step):
    """Catmull-Rom through 2-D control points, resampled every `step` metres of arc. -> (n, 2) array, arc length array."""
    P = np.asarray(pts, dtype=float)
    if len(P) == 2:
        dense = np.linspace(P[0], P[1], 64)
    else:
        ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
        seg = []
        for i in range(1, len(ext) - 2):
            for t in np.linspace(0, 1, 24, endpoint=(i == len(ext) - 3)):
                seg.append(_cr(ext[i - 1], ext[i], ext[i + 1], ext[i + 2], t))
        dense = np.array(seg)
    d = np.hypot(*np.diff(dense, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(d)])
    total = float(s[-1])
    n = max(2, int(math.ceil(total / step)) + 1)
    q = np.linspace(0.0, total, n)
    return np.stack([np.interp(q, s, dense[:, 0]), np.interp(q, s, dense[:, 1])], axis=1), q


def _anchor_stations(pts2, ctrl, xz, s):
    """Arc length of each control point on the resampled line (nearest sample)."""
    out = []
    for p in pts2:
        out.append(int(np.argmin(np.hypot(xz[:, 0] - p[0], xz[:, 1] - p[1]))))
    return out


def profile(road, xz, s, H, out):
    """Height of the road centre at every sample. Draped: the terrain along the line, low-passed. Elevated: the control point heights."""
    pts = road['points']
    ground = H.at(xz[:, 0], xz[:, 1])
    if not road.get('elevated'):
        n = len(ground)
        k = max(1, int(round(16.0 / max(float(s[1] - s[0]), 0.1))))
        pad = np.pad(ground, k, mode='edge')
        ker = np.ones(2 * k + 1) / (2 * k + 1)
        y = np.convolve(pad, ker, mode='valid')[:n]
        fixed = [(i, float(p[2])) for i, p in zip(_anchor_stations([[q[0], q[1]] for q in pts], pts, xz, s), pts) if len(p) == 3]
        if fixed:
            return _pin(y, fixed)
        return y
    anchors = []
    idx = _anchor_stations([[q[0], q[1]] for q in pts], pts, xz, s)
    for k, (i, p) in enumerate(zip(idx, pts)):
        if len(p) == 3:
            anchors.append((i, float(p[2])))
        elif k in (0, len(pts) - 1):                       # the ends sit on the ground; a middle point without y is left free
            anchors.append((i, float(ground[i]) + float(road.get('lift', 0.0))))
    anchors.sort()
    y = np.zeros(len(xz))
    if anchors[0][0] > 0:
        y[:anchors[0][0]] = anchors[0][1]
    for (i0, y0), (i1, y1) in zip(anchors[:-1], anchors[1:]):
        if i1 <= i0:
            continue
        t = (np.arange(i0, i1 + 1) - i0) / float(i1 - i0)
        y[i0:i1 + 1] = y0 + (y1 - y0) * smoothstep(t)
    y[anchors[-1][0]:] = anchors[-1][1]
    return y


def _pin(y, fixed):
    y = y.copy()
    for i, v in fixed:
        d = v - y[i]
        w = np.exp(-((np.arange(len(y)) - i) / 8.0) ** 2)
        y += d * w
    return y


def frames(xz):
    t = np.gradient(xz, axis=0)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    t = t / np.where(ln < 1e-9, 1.0, ln)
    left = np.stack([-t[:, 1], t[:, 0]], axis=1)
    return t, left


def grade_terrain(H, xz, y, half, shoulder):
    """Flatten the grid under a draped road and blend the sides into the terrain. -> boolean (nz, nx) cell mask of the asphalt."""
    X, Z = H.mesh()
    best = np.full(H.h.shape, np.inf)
    by = np.zeros(H.h.shape)
    reach = half + shoulder
    for i in range(len(xz) - 1):
        a, b = xz[i], xz[i + 1]
        lo = np.minimum(a, b) - reach
        hi = np.maximum(a, b) + reach
        i0 = max(int((lo[0] - H.ox) // H.cell), 0)
        i1 = min(int((hi[0] - H.ox) // H.cell) + 2, H.nx + 1)
        j0 = max(int((lo[1] - H.oz) // H.cell), 0)
        j1 = min(int((hi[1] - H.oz) // H.cell) + 2, H.nz + 1)
        if i1 <= i0 or j1 <= j0:
            continue
        x, z = X[j0:j1, i0:i1], Z[j0:j1, i0:i1]
        d = b - a
        L2 = float(d @ d)
        t = np.clip(((x - a[0]) * d[0] + (z - a[1]) * d[1]) / max(L2, 1e-12), 0.0, 1.0)
        dist = np.hypot(x - (a[0] + t * d[0]), z - (a[1] + t * d[1]))
        sl = (slice(j0, j1), slice(i0, i1))
        better = dist < best[sl]
        best[sl] = np.where(better, dist, best[sl])
        by[sl] = np.where(better, y[i] + (y[i + 1] - y[i]) * t, by[sl])
    w = 1.0 - smoothstep((best - half) / max(shoulder, 1e-6))
    w = np.where(best <= half, 1.0, w)
    H.h = H.h * (1 - w) + by * w
    cx = H.ox + (np.arange(H.nx) + 0.5) * H.cell
    cz = H.oz + (np.arange(H.nz) + 0.5) * H.cell
    CX, CZ = np.meshgrid(cx, cz)
    cb = np.full((H.nz, H.nx), np.inf)
    for i in range(len(xz) - 1):
        a, b = xz[i], xz[i + 1]
        d = b - a
        L2 = float(d @ d)
        lo = np.minimum(a, b) - half - H.cell
        hi = np.maximum(a, b) + half + H.cell
        i0 = max(int((lo[0] - H.ox) // H.cell), 0)
        i1 = min(int((hi[0] - H.ox) // H.cell) + 1, H.nx)
        j0 = max(int((lo[1] - H.oz) // H.cell), 0)
        j1 = min(int((hi[1] - H.oz) // H.cell) + 1, H.nz)
        if i1 <= i0 or j1 <= j0:
            continue
        x, z = CX[j0:j1, i0:i1], CZ[j0:j1, i0:i1]
        t = np.clip(((x - a[0]) * d[0] + (z - a[1]) * d[1]) / max(L2, 1e-12), 0.0, 1.0)
        dist = np.hypot(x - (a[0] + t * d[0]), z - (a[1] + t * d[1]))
        cb[j0:j1, i0:i1] = np.minimum(cb[j0:j1, i0:i1], dist)
    return cb <= half


# ------------------------------------------------------------------------------------------------ meshes
def obox(mesh, tex, cx, cz, y0, y1, hx, hz, yaw, uv, material, surface='solid', skip=()):
    """A box turned about +y by `yaw` (model space)."""
    c, s = math.cos(yaw), math.sin(yaw)

    def R(px, pz):
        return (cx + px * c - pz * s, cz + px * s + pz * c)
    corners = [R(-hx, -hz), R(hx, -hz), R(hx, hz), R(-hx, hz)]
    bot = [(x, y0, z) for x, z in corners]
    top = [(x, y1, z) for x, z in corners]
    mesh.add(tex, top, [(0, 1, 0)] * 4, [(x * uv, z * uv) for x, _, z in top], [(0, 1, 2), (0, 2, 3)])
    mesh.add(tex, bot, [(0, -1, 0)] * 4, [(x * uv, z * uv) for x, _, z in bot], [(0, 1, 2), (0, 2, 3)])
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        n = np.array([b[1] - a[1], 0.0, -(b[0] - a[0])])
        ln = np.linalg.norm(n)
        n = n / ln if ln > 1e-9 else np.array([1.0, 0, 0])
        q = [(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1])]
        ln_ab = math.hypot(b[0] - a[0], b[1] - a[1])
        mesh.add(tex, q, [n] * 4, [(0, 0), (ln_ab * uv, 0), (ln_ab * uv, (y1 - y0) * uv), (0, (y1 - y0) * uv)], [(0, 1, 2), (0, 2, 3)])
    mesh.hull(bot + top, surface, material)


def _surface_strip(mesh, tex, Lp, Rp, y, tex_v, down=False):
    """Triangles of a ribbon between left and right edge points at heights y (arrays), uv v from tex_v."""
    n = len(Lp)
    P = np.zeros((2 * n, 3))
    P[0::2, 0], P[0::2, 2], P[0::2, 1] = Lp[:, 0], Lp[:, 1], y
    P[1::2, 0], P[1::2, 2], P[1::2, 1] = Rp[:, 0], Rp[:, 1], y
    T = np.zeros((2 * n, 2))
    T[0::2, 0], T[1::2, 0] = 0.0, 1.0
    T[0::2, 1] = T[1::2, 1] = tex_v
    # normals from the ribbon itself
    N = np.zeros((2 * n, 3))
    tang = np.gradient(P[0::2] + P[1::2], axis=0)
    across = P[0::2] - P[1::2]
    nn = np.cross(across, tang)
    ln = np.linalg.norm(nn, axis=1, keepdims=True)
    nn = nn / np.where(ln < 1e-9, 1.0, ln)
    nn = np.where(nn[:, 1:2] < 0, -nn, nn)
    if down:
        nn = -nn
    N[0::2] = nn
    N[1::2] = nn
    k = np.arange(n - 1) * 2
    tris = np.concatenate([np.stack([k, k + 1, k + 3], 1), np.stack([k, k + 3, k + 2], 1)])
    mesh.add(tex, P, N, T, tris)


def _wall(mesh, tex, A, B, ya0, ya1, yb0, yb1, outward, uv=0.25):
    """A vertical quad strip along points A -> B (arrays of xz) between heights; outward = unit xz normal array."""
    n = len(A)
    P = np.zeros((2 * n, 3))
    P[0::2, 0], P[0::2, 2], P[0::2, 1] = A[:, 0], A[:, 1], ya0
    P[1::2, 0], P[1::2, 2], P[1::2, 1] = A[:, 0], A[:, 1], ya1
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(A, axis=0).T))])
    T = np.zeros((2 * n, 2))
    T[0::2, 0] = T[1::2, 0] = d * uv
    T[0::2, 1], T[1::2, 1] = ya0 * uv, ya1 * uv
    N = np.zeros((2 * n, 3))
    N[0::2, 0] = N[1::2, 0] = outward[:, 0]
    N[0::2, 2] = N[1::2, 2] = outward[:, 1]
    k = np.arange(n - 1) * 2
    tris = np.concatenate([np.stack([k, k + 1, k + 3], 1), np.stack([k, k + 3, k + 2], 1)])
    mesh.add(tex, P, N, T, tris)


def _hull_runs(n, step_m, samples_step):
    k = max(1, int(round(step_m / max(samples_step, 1e-6))))
    idx = list(range(0, n - 1, k)) + [n - 1]
    return list(zip(idx[:-1], idx[1:]))


def build_road(road, k, H, out, tex_for):
    """Build one road. -> dict(info stats, centre (xz samples), half width, mask (cells or None))."""
    rid = str(road.get('id') or 'road%d' % (k + 1))
    pts = road.get('points') or []
    if len(pts) < 2:
        raise MapgenError('road %s needs at least 2 points' % rid)
    for p in pts:
        if len(p) not in (2, 3) or any(not math.isfinite(float(v)) for v in p):
            raise MapgenError('road %s: every point is [x, z] or [x, z, height]' % rid)
    w = float(road.get('width', 8.0))
    if not 1.5 <= w <= 40.0:
        raise MapgenError('road %s: the width must be between 1.5 and 40 metres' % rid)
    lanes = int(road.get('lanes', 2))
    step = float(road.get('step', 2.0))
    road = dict(road, points=[list(map(float, p)) for p in pts])
    xz, s = spline([[p[0], p[1]] for p in road['points']], step)
    y = profile(road, xz, s, H, out)
    elevated = bool(road.get('elevated'))
    half = w / 2.0
    kerb = bool(road.get('kerb', not elevated))
    mask = None
    if not elevated and road.get('grade', True) and H.h is not None:
        mask = grade_terrain(H, xz, y, half + (KERB_W if kerb else 0.0), float(road.get('shoulder', 6.0)))
        # the surface follows the graded ground exactly
    t, left = frames(xz)
    L = xz + left * half
    R = xz - left * half
    road_tex = tex_for('road', lanes)
    kerb_tex = tex_for('kerb', 0)
    conc_tex = tex_for('concrete', 0)
    deck = dict(thickness=0.8, wall=1.0, pillar_every=12.0)
    deck.update(road.get('deck') or {})
    yy = y + LIFT
    ds = float(s[1] - s[0]) if len(s) > 1 else step
    models, tris_total, hull_total = [], 0, 0
    n = len(xz)
    for part, a in enumerate(range(0, n - 1, SEG_SAMPLES - 1)):
        b = min(a + SEG_SAMPLES, n)
        if b - a < 2:
            continue
        sl = slice(a, b)
        origin = (float(xz[a, 0]), float(xz[a, 1]))
        o = np.array(origin)
        mesh = Mesh()
        _surface_strip(mesh, road_tex, L[sl] - o, R[sl] - o, yy[sl], s[sl] / ROAD_TILE)
        out_l, out_r = left[sl], -left[sl]
        if kerb and not elevated:
            for side, sgn in ((L, 1.0), (R, -1.0)):
                e0 = side[sl] - o
                e1 = side[sl] + left[sl] * sgn * KERB_W - o
                top_y = yy[sl] + KERB_H
                _wall(mesh, kerb_tex, e0, e0, yy[sl], top_y, yy[sl], top_y, -left[sl] * sgn)
                _surface_strip(mesh, kerb_tex, e0 if sgn > 0 else e1, e1 if sgn > 0 else e0, top_y, s[sl] * 0.5)
                _wall(mesh, kerb_tex, e1, e1, top_y, yy[sl] - 0.15, top_y, yy[sl] - 0.15, left[sl] * sgn)
        if elevated:
            th = float(deck['thickness'])
            for side, sgn in ((L, 1.0), (R, -1.0)):
                e = side[sl] - o
                _wall(mesh, conc_tex, e, e, yy[sl] - th, yy[sl], yy[sl] - th, yy[sl], left[sl] * sgn)
            Lp, Rp = L[sl] - o, R[sl] - o
            _surface_strip(mesh, conc_tex, Rp, Lp, yy[sl] - th, s[sl] * 0.25, down=True)
            wl = float(deck['wall'])
            if wl > 0:
                for side, sgn in ((L, 1.0), (R, -1.0)):
                    e_in = side[sl] - left[sl] * sgn * 0.3 - o
                    e_out = side[sl] - o
                    top = yy[sl] + wl
                    _wall(mesh, conc_tex, e_out, e_out, yy[sl], top, yy[sl], top, left[sl] * sgn)
                    _wall(mesh, conc_tex, e_in, e_in, yy[sl], top, yy[sl], top, -left[sl] * sgn)
                    _surface_strip(mesh, conc_tex, e_out if sgn > 0 else e_in, e_in if sgn > 0 else e_out, top, s[sl] * 0.25)
        # collision: asphalt pieces along the road
        th_h = float(deck['thickness']) if elevated else 0.3
        for i0, i1 in _hull_runs(b - a, HULL_EVERY, ds):
            i0 += a
            i1 += a
            pts8 = []
            for i in (i0, i1):
                for side in (L, R):
                    pts8.append((side[i, 0] - o[0], yy[i], side[i, 1] - o[1]))
                    pts8.append((side[i, 0] - o[0], yy[i] - th_h, side[i, 1] - o[1]))
            mesh.hull(pts8, 'solid', 'Asphalt')
            if elevated and float(deck['wall']) > 0:
                for side, sgn in ((L, 1.0), (R, -1.0)):
                    ws = []
                    for i in (i0, i1):
                        for off in (0.0, -0.3):
                            ws.append((side[i, 0] + left[i, 0] * sgn * off - o[0], yy[i], side[i, 1] + left[i, 1] * sgn * off - o[1]))
                            ws.append((side[i, 0] + left[i, 0] * sgn * off - o[0], yy[i] + float(deck['wall']), side[i, 1] + left[i, 1] * sgn * off - o[1]))
                    mesh.hull(ws, 'thin', 'Concrete')
        if elevated:
            every = max(3.0, float(deck['pillar_every']))
            stations = list(range(a, b, max(1, int(round(every / ds)))))
            for i in stations:
                ground = float(H.at(xz[i, 0], xz[i, 1]))
                bottom = yy[i] - float(deck['thickness'])
                if bottom - ground < 1.0:
                    continue
                yaw = -math.atan2(t[i, 1], t[i, 0])
                offs = [0.0] if w <= 9.0 else [-w / 4.0, w / 4.0]
                for off in offs:
                    cx = xz[i, 0] + left[i, 0] * off - o[0]
                    cz = xz[i, 1] + left[i, 1] * off - o[1]
                    gnd = float(H.at(xz[i, 0] + left[i, 0] * off, xz[i, 1] + left[i, 1] * off))
                    obox(mesh, conc_tex, cx, cz, gnd - 1.0, bottom, 0.6, 0.6, yaw, 0.25, 'Concrete')
        name = 'R_%s_%d' % (rid, part)
        out.model(name, [mesh.part()])
        out.place(name, [origin[0], 0.0, origin[1]], name='ROAD_%s_%d' % (rid.upper(), part))
        c = mesh.counts()
        models.append(dict(model=name, triangles=c['triangles'], vertices=c['vertices'], hulls=c['hulls'], max_submesh=c['max_submesh'],
                           max_hull_vertices=c['max_hull_vertices']))
        tris_total += c['triangles']
        hull_total += c['hulls']
    # slopes
    run = np.maximum(np.diff(s), 1e-6)
    slope = np.abs(np.diff(y)) / run
    smooth = np.convolve(slope, np.ones(5) / 5.0, mode='same') if len(slope) >= 5 else slope
    worst = float(smooth.max()) if len(smooth) else 0.0
    wi = int(np.argmax(smooth)) if len(smooth) else 0
    info = dict(id=rid, length=round(float(s[-1]), 2), samples=n, width=w, lanes=lanes, elevated=elevated, triangles=tris_total, hulls=hull_total,
                models=[m['model'] for m in models], max_slope=round(worst, 4), worst_at=[round(float(xz[wi, 0]), 2), round(float(xz[wi, 1]), 2)],
                graded_cells=int(mask.sum()) if mask is not None else 0)
    if worst > SLOPE_WALK:
        out.note('Road %s climbs %.0f%% near (%.0f, %.0f): too steep to walk (over %d%%) and for cars (over %d%%).'
                 % (rid, worst * 100, xz[wi, 0], xz[wi, 1], SLOPE_WALK * 100, SLOPE_CAR * 100))
    elif worst > SLOPE_CAR:
        out.note('Road %s climbs %.0f%% near (%.0f, %.0f): cars may struggle over %d%%.' % (rid, worst * 100, xz[wi, 0], xz[wi, 1], SLOPE_CAR * 100))
    if road.get('traffic', True):
        out.traffic += _traffic(rid, xz, yy, left, s, w, lanes)
    return dict(info=info, centre=xz, half=half + (KERB_W if kerb else 0.0), mask=mask, models=models)


ROAD_TILE = 8.0


def _traffic(rid, xz, yy, left, s, w, lanes):
    """Two chains of traffic points (one per direction, a quarter of the width off the centre), every TRAFFIC_EVERY metres."""
    total = float(s[-1])
    n = max(2, int(total // TRAFFIC_EVERY) + 1)
    q = np.linspace(0.0, total, n)
    cx = np.interp(q, s, xz[:, 0])
    cz = np.interp(q, s, xz[:, 1])
    cy = np.interp(q, s, yy)
    lx = np.interp(q, s, left[:, 0])
    lz = np.interp(q, s, left[:, 1])
    nrm = np.hypot(lx, lz)
    lx, lz = lx / np.where(nrm < 1e-9, 1, nrm), lz / np.where(nrm < 1e-9, 1, nrm)
    off = w / 4.0 if lanes >= 2 else 0.0
    routes = []
    for tag, sgn, order in (('F', -1.0, range(n)), ('B', 1.0, range(n - 1, -1, -1))):
        if lanes < 2 and tag == 'B':
            continue
        pts = []
        idx = list(order)
        for m, i in enumerate(idx):
            pts.append(dict(name='TRAFFIC_%s_%s_%d' % (rid.upper(), tag, m),
                            pos=[round(float(cx[i] + lx[i] * sgn * off), 3), round(float(cy[i] + 0.1), 3), round(float(cz[i] + lz[i] * sgn * off), 3)],
                            next='TRAFFIC_%s_%s_%d' % (rid.upper(), tag, m + 1) if m + 1 < len(idx) else None))
        routes.append(dict(road=rid, direction=tag, boundradius=round(w / (2.0 * max(lanes, 1)), 2), points=pts))
    return routes
