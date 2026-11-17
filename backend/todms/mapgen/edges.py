"""Map edges: cliff walls or invisible walls around a polygon, and an optional kill plane that sends a fallen player back to a spot.

Recipe key `edges` (a list):
  {"id": "rim", "kind": "cliff" | "invisible",
   "polygon": [[x, z], ...] | "rect": [x0, z0, x1, z1] | "circle": [x, z, r],       the line the wall follows (closed)
   "height": 8.0,                  wall height above the local ground
   "thickness": 1.2,               cliff wall thickness (invisible walls are 0.6)
   "kill": {"below": -20.0,        a trigger plane this far down (world y) ...
            "respawn": "SPOT" | [x, z]}}      ... that moves the player to a named spot or to the ground at [x, z]
A cliff is a rough rock wall (render mesh + collision pieces); an invisible wall is the builder's own CollisionBox node (`walls`).
There is no native fall recovery in the game that a new map can use: the kill plane is a teleport trigger (see the notes).
"""
import math

from .core import np, MapgenError, polygon_of, rng, yaw_quat
from .meshkit import Mesh

SEG = 6.0               # metres per wall segment
INVISIBLE_SEG = 16.0
SEG_PER_MODEL = 60


def _segments(poly, seg):
    pts = []
    n = len(poly)
    for i in range(n):
        a = np.array(poly[i], dtype=float)
        b = np.array(poly[(i + 1) % n], dtype=float)
        L = float(np.hypot(*(b - a)))
        k = max(1, int(math.ceil(L / seg)))
        for j in range(k):
            pts.append((a + (b - a) * (j / k), a + (b - a) * ((j + 1) / k)))
    return pts


def build(edge, k, H, out, tex_for):
    eid = str(edge.get('id') or 'edge%d' % (k + 1))
    poly = polygon_of(edge, 'edge %s' % eid)
    kind = edge.get('kind', 'cliff')
    height = float(edge.get('height', 8.0))
    info = dict(id=eid, kind=kind, length=0.0, pieces=0, triangles=0)
    if kind == 'invisible':
        for n, (a, b) in enumerate(_segments(poly, INVISIBLE_SEG)):
            L = float(np.hypot(*(b - a)))
            mid = (a + b) / 2.0
            g0, g1 = float(H.at(a[0], a[1])), float(H.at(b[0], b[1]))
            base = min(g0, g1, float(H.at(mid[0], mid[1])))
            top = max(g0, g1, float(H.at(mid[0], mid[1]))) + height
            yaw = -math.atan2(b[1] - a[1], b[0] - a[0])
            out.walls.append(dict(name='EDGE_%s_%d' % (eid.upper(), n), pos=[round(float(mid[0]), 3), round((base - 1.0 + top) / 2.0, 3), round(float(mid[1]), 3)],
                                  size=[round(L + 0.2, 3), round(top - base + 1.0, 3), 0.6], orient=yaw_quat(yaw), flags=3))
            info['length'] += L
            info['pieces'] += 1
    elif kind == 'cliff':
        th = float(edge.get('thickness', 1.2))
        r = rng('edge', eid, 'jitter')
        segs = _segments(poly, SEG)
        tex = tex_for('cliff', 0)
        for part, a0 in enumerate(range(0, len(segs), SEG_PER_MODEL)):
            chunk = segs[a0:a0 + SEG_PER_MODEL]
            origin = chunk[0][0]
            mesh = Mesh()
            for a, b in chunk:
                L = float(np.hypot(*(b - a)))
                d = (b - a) / max(L, 1e-9)
                nrm = np.array([d[1], -d[0]])                       # one side of the wall; the other gets the opposite normal
                ya, yb = float(H.at(a[0], a[1])), float(H.at(b[0], b[1]))
                ym = float(H.at(*((a + b) / 2.0)))
                base = min(ya, yb, ym) - 2.0
                ta = max(ya, ym) + height + float(r.random()) * 1.6 - 0.8
                tb = max(yb, ym) + height + float(r.random()) * 1.6 - 0.8
                o = np.array(origin)
                A, B = a - o, b - o
                for sgn in (1.0, -1.0):
                    off = nrm * th / 2.0 * sgn
                    p = [(A[0] + off[0], base, A[1] + off[1]), (B[0] + off[0], base, B[1] + off[1]),
                         (B[0] + off[0], tb, B[1] + off[1]), (A[0] + off[0], ta, A[1] + off[1])]
                    n3 = (nrm[0] * sgn, 0.0, nrm[1] * sgn)
                    mesh.add(tex, p, [n3] * 4, [(0, base * 0.2), (L * 0.2, base * 0.2), (L * 0.2, tb * 0.2), (0, ta * 0.2)], [(0, 1, 2), (0, 2, 3)])
                o1, o2 = nrm * th / 2.0, -nrm * th / 2.0
                topq = [(A[0] + o1[0], ta, A[1] + o1[1]), (B[0] + o1[0], tb, B[1] + o1[1]), (B[0] + o2[0], tb, B[1] + o2[1]), (A[0] + o2[0], ta, A[1] + o2[1])]
                mesh.add(tex, topq, [(0, 1, 0)] * 4, [(0, 0), (L * 0.2, 0), (L * 0.2, th * 0.2), (0, th * 0.2)], [(0, 1, 2), (0, 2, 3)])
                hp = []
                for sgn in (1.0, -1.0):
                    off = nrm * th / 2.0 * sgn
                    hp += [(A[0] + off[0], base, A[1] + off[1]), (B[0] + off[0], base, B[1] + off[1]),
                           (B[0] + off[0], tb, B[1] + off[1]), (A[0] + off[0], ta, A[1] + off[1])]
                mesh.hull(hp, 'solid', 'Stone')
                info['length'] += L
                info['pieces'] += 1
            name = 'E_%s_%d' % (eid, part)
            out.model(name, [mesh.part()])
            out.place(name, [float(origin[0]), 0.0, float(origin[1])], name='EDGE_%s_%d' % (eid.upper(), part))
            info['triangles'] += mesh.counts()['triangles']
    else:
        raise MapgenError('edge %s: kind must be cliff or invisible' % eid)
    kill = edge.get('kill')
    if kill:
        xs = [p[0] for p in poly]
        zs = [p[1] for p in poly]
        below = float(kill.get('below', -20.0))
        size = [round(max(xs) - min(xs) + 400.0, 3), 20.0, round(max(zs) - min(zs) + 400.0, 3)]
        spot = _spot(kill.get('respawn'), 'EDGE_%s_SAFE' % eid.upper(), poly, H, out)
        out.triggers.append(dict(id='kill_%s' % eid, kind='teleport', reason='fall', pos=[round((max(xs) + min(xs)) / 2.0, 3), round(below - 10.0, 3),
                                                                                               round((max(zs) + min(zs)) / 2.0, 3)],
                                 size=size, orient=[0.0, 0.0, 0.0, 1.0], teleport_to=spot))
        out.note('Kill plane of edge %s: no native fall recovery exists for a new map, so a teleport trigger below y %.0f sends the player to %s. '
                 'A teleport to a spot of the same map has not been tried in game.' % (eid, below, spot))
        info['kill_below'] = below
    out.stats['edges'].append(info)
    return info


def _spot(respawn, default_name, poly, H, out):
    """A teleport spot name: an existing name stays, a point becomes a new spot on the ground there, none = the polygon centre."""
    if isinstance(respawn, str):
        return respawn
    if respawn:
        x, z = float(respawn[0]), float(respawn[1])
    else:
        x = sum(p[0] for p in poly) / len(poly)
        z = sum(p[1] for p in poly) / len(poly)
    y = float(H.at(x, z)) + 1.0
    if not any(t['name'] == default_name for t in out.teleports):
        out.teleports.append(dict(name=default_name, pos=[round(x, 3), round(y, 3), round(z, 3)], orient=[0.0, 0.0, 0.0, 1.0]))
    return default_name
