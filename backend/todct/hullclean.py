"""One face per plane for convex collision hulls.

The engine darkens a blob shadow once for every hull face that lies under it, so two triangles that cover the same
patch of one plane draw the shadow twice. The gift-wrapping hull in model_writer emits every coplanar point triple as a
face: a k-cornered flat top becomes C(k,3) overlapping triangles (4 corners: 2 layers, 6: 8, 8: 20, 12: 70) and the
shadow turns black. `clean` rebuilds each plane as one triangle fan over its ordered outline; `overlaps` finds planes
whose triangles cover more than the outline (used by the build check).
"""
import math

NTOL = 2e-4        # 1 - cos of the largest angle between the faces of one plane (about 1 degree)
LAYER_MIN = 1.9     # a plane covered about twice or more counts as stacked (a slightly bent cap covers 1.0x)
DTOL = 1e-3        # plane offset tolerance (metres); float32 corners are only that flat


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v):
    n = math.sqrt(_dot(v, v))
    return None if n < 1e-12 else (v[0] / n, v[1] / n, v[2] / n)


def planes(verts, faces):
    """Group faces by plane. -> list of dict(n=outward unit normal, d=offset, faces=[face index]) (degenerate faces skipped)."""
    out = []
    for fi, f in enumerate(faces):
        if len(f) < 3:
            continue
        n = _unit(_cross(_sub(verts[f[1]], verts[f[0]]), _sub(verts[f[2]], verts[f[0]])))
        if n is None:
            continue
        d = _dot(n, verts[f[0]])
        for g in out:
            if _dot(n, g['n']) > 1.0 - NTOL and abs(_dot(g['n'], verts[f[0]]) - g['d']) <= DTOL:   # against the group's own normal: a tilt of the face's own would move the offset with the distance from the origin
                g['faces'].append(fi)
                break
        else:
            out.append(dict(n=n, d=d, faces=[fi]))
    return out


def _outline(pts2):
    """Convex outline (indices, counter-clockwise, collinear points dropped) of 2D points (monotone chain)."""
    order = sorted(range(len(pts2)), key=lambda i: (pts2[i][0], pts2[i][1]))

    def turn(o, a, b):
        return (pts2[a][0] - pts2[o][0]) * (pts2[b][1] - pts2[o][1]) - (pts2[a][1] - pts2[o][1]) * (pts2[b][0] - pts2[o][0])
    lo, up = [], []
    for i in order:
        while len(lo) >= 2 and turn(lo[-2], lo[-1], i) <= 1e-9:
            lo.pop()
        lo.append(i)
    for i in reversed(order):
        while len(up) >= 2 and turn(up[-2], up[-1], i) <= 1e-9:
            up.pop()
        up.append(i)
    return lo[:-1] + up[:-1]


def _basis(n):
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _unit(_cross(a, n))
    return u, _cross(n, u)                 # (u, v, n) is right-handed: counter-clockwise in (u, v) faces along n


def _polygon(verts, group_faces, faces, n):
    """Ordered outline (vertex indices, counter-clockwise seen from outside) of the vertices of one plane's faces."""
    idx = sorted({i for fi in group_faces for i in faces[fi]})
    u, v = _basis(n)
    pts2 = [(_dot(verts[i], u), _dot(verts[i], v)) for i in idx]
    ring = _outline(pts2)
    return [idx[k] for k in ring], [pts2[k] for k in ring]


def _area2(poly2):
    return sum(poly2[i][0] * poly2[(i + 1) % len(poly2)][1] - poly2[(i + 1) % len(poly2)][0] * poly2[i][1] for i in range(len(poly2))) / 2.0


def overlaps(verts, faces):
    """Planes whose triangles together cover more than their outline. -> list of dict(normal, faces, layers)."""
    bad = []
    for g in planes(verts, faces):
        if len(g['faces']) < 2:
            continue
        ring, ring2 = _polygon(verts, g['faces'], faces, g['n'])
        if len(ring) < 3:
            continue
        outline = abs(_area2(ring2))
        cover = 0.0
        for fi in g['faces']:
            f = faces[fi]
            for k in range(1, len(f) - 1):
                cover += abs(_dot(_cross(_sub(verts[f[k]], verts[f[0]]), _sub(verts[f[k + 1]], verts[f[0]])), g['n'])) / 2.0
        if outline > 1e-12 and cover > outline * LAYER_MIN:
            bad.append(dict(normal=g['n'], faces=len(g['faces']), layers=round(cover / outline, 2)))
    return bad


def clean(verts, faces):
    """-> (verts, faces) with exactly one fan of triangles per plane; vertices no face uses any more are dropped."""
    out = []
    for g in planes(verts, faces):
        ring, ring2 = _polygon(verts, g['faces'], faces, g['n'])
        if len(ring) < 3:
            continue
        for k in range(1, len(ring) - 1):
            out.append([ring[0], ring[k], ring[k + 1]])
    used = sorted({i for f in out for i in f})
    remap = {o: k for k, o in enumerate(used)}
    return [tuple(verts[i]) for i in used], [[remap[i] for i in f] for f in out]


# What the hulls written since the last reset looked like (the new-map build reports it as a check).
AUDIT = dict(hulls=0, stacked=0, layers=0.0, first='')


def audit_reset():
    AUDIT.update(hulls=0, stacked=0, layers=0.0, first='')


def audit(verts, faces, name=''):
    AUDIT['hulls'] += 1
    bad = overlaps(verts, faces)
    if bad:
        AUDIT['stacked'] += 1
        AUDIT['layers'] = max(AUDIT['layers'], max(b['layers'] for b in bad))
        if not AUDIT['first']:
            AUDIT['first'] = name or 'a hull'
    return bad


def audit_check():
    """-> the build check row for the hulls written since audit_reset()."""
    a = AUDIT
    if a['stacked'] and a['stacked'] > 0.01 * a['hulls']:       # a few bent slivers are not the problem; a stack on every flat top is
        return dict(check='collision hulls: one face per plane', result='WARN',
                    evidence='%d of %d hulls have stacked coplanar faces (up to %.0f layers, first in %s): a blob shadow under them turns dark'
                    % (a['stacked'], a['hulls'], a['layers'], a['first']))
    return dict(check='collision hulls: one face per plane', result='PASS', evidence='%d hulls, %d with a stacked face' % (a['hulls'], a['stacked']))
