"""Backdrop: a ring of distant towers, so the view past the edge of a map reads as a city and not as flat sea to the horizon.

Recipe key `backdrop` (a dict; absent or `{"kind": "none"}` draws nothing):
  {"kind": "skyline",
   "gap": [60, 330]             metres beyond the map's rim (the `edges` rectangle, else the scene's own extent) the towers stand
   "count": 96                  towers in the ring (at most 400)
   "height": [30, 150]          metres above the base, or "scene": heights drawn from the scene's own buildings (the plan keeps them)
   "width": [18, 46], "depth": [16, 34]
   "base": y                    where the towers start (default: 6 m under the street level, so they rise out of the sea)
   "seed": 1}
The ring is four generated models (one per side of the rim) with one box per tower: five faces, no floor, no collision, one picture
(`B_Skyline`, a slate facade with lit windows, 128 px). Nothing here is collidable or placed inside the playable area; the cost is
about 20 vertices a tower. The towers are drawn through the map's fog, so they stand in haze like a far city.
"""
import math

from .core import np, MapgenError
from .meshkit import Mesh

TEXTURE = 'B_Skyline'
DEFAULTS = dict(kind='skyline', gap=[60.0, 330.0], count=96, height=[30.0, 150.0], width=[18.0, 46.0], depth=[16.0, 34.0], seed=1)
MAX_COUNT = 400
UV = 0.036                         # one repeat of the picture per 28 m: windows of about 3.5 m


def settings(m):
    b = m.get('backdrop')
    if not b or b.get('kind') in (None, 'none'):
        return None
    if b['kind'] != 'skyline':
        raise MapgenError('backdrop kind %r is not known (skyline or none)' % b['kind'])
    s = dict(DEFAULTS)
    s.update({k: v for k, v in b.items() if v is not None})
    s['count'] = int(s['count'])
    if not 1 <= s['count'] <= MAX_COUNT:
        raise MapgenError('backdrop count must be 1 to %d' % MAX_COUNT)
    for k in ('gap', 'width', 'depth'):
        if len(s[k]) != 2 or s[k][0] <= 0 or s[k][1] < s[k][0]:
            raise MapgenError('backdrop %s needs two numbers, the smaller first' % k)
    if s['height'] != 'scene' and (len(s['height']) != 2 or s['height'][0] <= 0 or s['height'][1] < s['height'][0]):
        raise MapgenError('backdrop height needs two numbers (or "scene")')
    return s


def rim_of(m):
    """The rectangle [x0, z0, x1, z1] the ring goes around: the first edge rectangle, else the scene plan's extent."""
    for e in m.get('edges') or []:
        r = e.get('rect')
        if r and len(r) == 4:
            return [float(v) for v in r]
    p = (m.get('scene') or {}).get('plan')
    if p:
        return [float(p['x0']), float(p['z1']) - p['h'] * float(p['cell']), float(p['x0']) + p['w'] * float(p['cell']), float(p['z1'])]
    return None


def towers(m, s, rim, ground):
    """-> list of dict(side, cx, cz, w, d, h, y0): the towers, deterministic for the seed."""
    rng = np.random.default_rng(int(s['seed']))
    x0, z0, x1, z1 = rim
    hs = None
    if s['height'] == 'scene':
        hs = [float(v) for v in ((m.get('scene') or {}).get('plan') or {}).get('heights') or []]
    base = float(s['base']) if s.get('base') is not None else ground - 6.0
    per = 2.0 * ((x1 - x0) + (z1 - z0))
    out = []
    for k in range(s['count']):
        t = (k + float(rng.random()) * 0.8) / s['count'] * per          # along the perimeter, a little jitter
        gap = float(rng.uniform(*s['gap']))
        w = float(rng.uniform(*s['width']))
        d = float(rng.uniform(*s['depth']))
        if hs:
            h = float(hs[int(rng.integers(0, len(hs)))]) * float(rng.uniform(0.8, 1.5))
        else:
            lo, hi = (s['height'] if s['height'] != 'scene' else DEFAULTS['height'])
            h = float(rng.uniform(lo, hi))
        h = max(h, 12.0)
        a = t
        if a < x1 - x0:                                               # the south side (low z), then east, north, west
            side, cx, cz = 'S', x0 + a, z0 - gap
        elif a < (x1 - x0) + (z1 - z0):
            side, cx, cz = 'E', x1 + gap, z0 + (a - (x1 - x0))
        elif a < 2 * (x1 - x0) + (z1 - z0):
            side, cx, cz = 'N', x1 - (a - (x1 - x0) - (z1 - z0)), z1 + gap
        else:
            side, cx, cz = 'W', x0 - gap, z1 - (a - 2 * (x1 - x0) - (z1 - z0))
        out.append(dict(side=side, cx=cx, cz=cz, w=w, d=d, h=h, y0=base))
    return out


def build(m, out):
    """Add the ring of one map to the collector `out`. -> dict(towers, models) for the stats, or None."""
    s = settings(m)
    if s is None:
        return None
    rim = rim_of(m)
    if rim is None:
        out.note('The backdrop needs the map\'s rim (an edge rectangle) or an imported scene: it was left out.')
        return None
    ground = float((m.get('scene') or {}).get('ground_y') or 0.0)
    ts = towers(m, s, rim, ground)
    out.texture(TEXTURE, 'skyline', 128, 'DXT1', 31)
    models = 0
    for side in 'SENW':
        mesh = Mesh()
        mine = [t for t in ts if t['side'] == side]
        for t in mine:
            mesh.box(TEXTURE, (t['cx'] - t['w'] / 2, t['y0'], t['cz'] - t['d'] / 2), (t['cx'] + t['w'] / 2, t['y0'] + t['h'], t['cz'] + t['d'] / 2),
                     uv=UV, skip=('-y',), collide=False)
        if not mine:
            continue
        # a Mesh gathers its boxes per picture; the model is the whole ring side
        name = 'BACKDROP_%s' % side
        out.model(name, [mesh.part()])
        out.place(name, [0.0, 0.0, 0.0], 'BD_%s' % side)
        models += 1
    return dict(towers=len(ts), models=models, rim=rim, base=ts[0]['y0'] if ts else None)
