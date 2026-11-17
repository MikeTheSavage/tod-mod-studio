"""The world side of the New maps screen (wave 3, worker world): where a new map lives, how it is entered, how a project starts.

Pure functions over recipe params unless a workspace is passed. Nothing here changes a recipe by itself: the screen asks, shows and
commits through its own undo. Editor-only keys it writes into a map (ignored by the builder):
  atlas  {pos [x, z], yaw}          where the map sits in the editor's world layout (never a game coordinate)
  card   {title, description, author, theme, size, picture}   the map identity card
"""
import json
import math
import os
import re

from . import paths

SAFE_BOX = 16000.0                     # M0 Q7: a coordinate beyond this loses float precision
SIZE_PRESETS = [dict(id='small', label='Small', cells=[40, 40], cell=2.0),
                dict(id='medium', label='Medium', cells=[80, 80], cell=2.0),
                dict(id='large', label='Large', cells=[100, 100], cell=3.0)]
_cache = {}


def short(e):
    return str(e or '').replace('\\', '/').split('/')[-1].lower()


# ------------------------------------------------------------------------------------------------ the atlas stand-ins
def bounds():
    """Section boxes and a coarse object grid per shipped block (data/world_bounds.json, made by scripts/world_bounds.py)."""
    if 'b' not in _cache:
        with open(os.path.join(paths.DATA, 'world_bounds.json'), encoding='utf-8') as f:
            _cache['b'] = json.load(f)
    return _cache['b']


def atlas_default_layout(maps=None, columns=3):
    """A tidy first layout for the shipped maps: a grid of equal cells. -> {map id: [x, z]} where the map's own origin lands in the editor layout.
    Editor-only: in the game every map keeps its own space."""
    ids = sorted({v['map'] for v in bounds().values()})
    boxes = {}
    for mid in ids:
        bs = [v['box'] for v in bounds().values() if v['map'] == mid and v['kind'] == 'map'] or [[-300, -300, 300, 300]]
        boxes[mid] = bs[0]
    pitch = max(max(b[2] - b[0], b[3] - b[1]) for b in boxes.values()) + 600.0
    pitch = math.ceil(pitch / 100.0) * 100.0
    out = {}
    for n, mid in enumerate(ids):
        b = boxes[mid]
        cx, cz = (n % columns) * pitch, -(n // columns) * pitch
        out[mid] = [round(cx - (b[0] + b[2]) / 2), round(cz - (b[1] + b[3]) / 2)]
    return out


# ------------------------------------------------------------------------------------------------ rectangles in the editor layout
def rect_of_map(m):
    """The footprint of a new map in ITS OWN space: [x0, z0, x1, z1], from its terrain, else a square of the size preset about the arrival."""
    t = m.get('terrain')
    if t:
        from .mapgen import terrain, core
        H = terrain.build(t, core.Out('w'))
        if H.h is not None:
            return [H.ox, H.oz, H.ox + H.nx * H.cell, H.oz + H.nz * H.cell]
    size = {p['id']: p['cells'][0] * p['cell'] for p in SIZE_PRESETS}.get((m.get('card') or {}).get('size'), 300.0)
    a = (m.get('arrival') or {}).get('pos') or [0, 0, 0]
    return [a[0] - size / 2, a[2] - size / 2, a[0] + size / 2, a[2] + size / 2]


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _atlas_rect(m):
    r = rect_of_map(m)
    at = m.get('atlas') or {}
    p = at.get('pos') or [0, 0]
    cx, cz = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    w, h = r[2] - r[0], r[3] - r[1]
    return [p[0] - w / 2, p[1] - h / 2, p[0] + w / 2, p[1] + h / 2], (cx, cz)


# ------------------------------------------------------------------------------------------------ templates and size presets
TEMPLATES = [dict(id='blank', label='Blank'), dict(id='desert', label='Desert compound'), dict(id='canyon', label='Canyon road'),
             dict(id='town', label='Town block'), dict(id='shell', label='Shipped map copy')]


def _template_keys(tid, size):
    """The mapgen keys of a template at a size preset ({id, cells, cell})."""
    nx, nz = size['cells']
    cell = size['cell']
    half = nx * cell / 2.0
    ter = dict(cell=cell, size=[nx, nz], noise=dict(seed=3, amp=0.25, scale=30))
    if tid == 'blank':
        return dict(terrain=ter, ground_paint=dict(palette=['dirt']), look=dict(preset='clear_day'))
    if tid == 'desert':
        ter.update(noise=dict(seed=11, amp=0.9, scale=28), strokes=[dict(tool='flatten', pos=[0, 0], radius=half * 0.35, strength=1.0, height=0.0)])
        return dict(terrain=ter, ground_paint=dict(palette=['sand', 'dirt', 'rock'], default='sand', rock_slope=0.5,
                                                   strokes=[dict(material='dirt', pos=[0, 0], radius=half * 0.3)]),
                    roads=[dict(id='gate', points=[[-half * 0.9, 0], [-half * 0.3, 0]], width=7, lanes=2)],
                    edges=[dict(id='rim', kind='cliff', rect=[-half, -half, half, half], height=7)],
                    scatter=[dict(id='rocks', rect=[-half * 0.9, -half * 0.9, half * 0.9, half * 0.9], items=[dict(kind='rock', weight=1)], density=0.0008)],
                    look=dict(preset='red_dust'))
    if tid == 'canyon':
        ter.update(noise=dict(seed=5, amp=1.2, scale=36), strokes=[
            dict(tool='raise', pos=[0, -half * 0.8], radius=half * 0.45, strength=9.0), dict(tool='raise', pos=[0, half * 0.8], radius=half * 0.45, strength=9.0),
            dict(tool='smooth', pos=[0, 0], radius=half * 0.5, strength=1.0, passes=2)])
        return dict(terrain=ter, ground_paint=dict(palette=['dirt', 'rock', 'sand'], default='dirt', rock_slope=0.45),
                    roads=[dict(id='canyon_road', points=[[-half * 0.9, 0], [-half * 0.3, half * 0.1], [half * 0.3, -half * 0.1], [half * 0.9, 0]], width=8, lanes=2)],
                    edges=[dict(id='rim', kind='invisible', rect=[-half, -half, half, half], height=12)],
                    look=dict(preset='train_dust'))
    if tid == 'town':
        ter.update(noise=dict(seed=2, amp=0.1, scale=40))
        return dict(terrain=ter, ground_paint=dict(palette=['asphalt', 'dirt', 'grass'], default='dirt'),
                    roads=[dict(id='main_street', points=[[-half * 0.9, 0], [half * 0.9, 0]], width=9, lanes=2),
                           dict(id='cross_street', points=[[0, -half * 0.9], [0, half * 0.9]], width=7, lanes=2)],
                    edges=[dict(id='fence', kind='invisible', rect=[-half, -half, half, half], height=10)],
                    look=dict(preset='bright_blue'))
    return {}


def size_estimate(size_id, tid='blank'):
    """Expected share of the ground limits (G2 triangles, G3 collision pieces) for a template at a size preset. Cached."""
    key = ('est', size_id, tid)
    if key in _cache:
        return _cache[key]
    from . import mapgen, ledger
    size = next(s for s in SIZE_PRESETS if s['id'] == size_id)
    m = dict(name='Map11_Estimate', source='map10_runawaytrain', arrival=dict(pos=[0, 2, 0], orient=[0, 0, 0, 1]), **_template_keys(tid, size))
    st = mapgen.expand_full(dict(package='estimate', maps=[m]))['stats']['Map11_Estimate']
    rows = {r['id']: r for r in ledger.mapgen_rows({'Map11_Estimate': st})}
    side = size['cells'][0] * size['cell']

    def pct(rid, used):
        mx = rows[rid]['max']
        return dict(id=rid, label=rows[rid]['label'], used=used, max=mx, pct=round(100.0 * used / mx, 1))
    out = dict(id=size_id, label=size['label'], side=side, cells=size['cells'], cell=size['cell'],
               meters=[pct('G2', st['ground_triangles']), pct('G3', max([c.get('hulls', 0) for c in st['chunks']] or [0])),
                       pct('G1', st['ground_materials'])],
               chunks=len(st['chunks']))
    _cache[key] = out
    return out


def size_presets(tid='blank'):
    return [size_estimate(s['id'], tid) for s in SIZE_PRESETS]


_FILL = {3: ['Hub', 'Row', 'Map'], 4: ['City', 'Zone', 'Town', 'Yard', 'Area', 'Park', 'Dock'], 5: ['Block', 'World', 'Plaza', 'Arena', 'Field'],
         6: ['Sector', 'Street', 'Island', 'Harbor', 'Square'], 7: ['Quarter', 'Station', 'Gardens'], 8: ['District', 'Crossing']}


def _fill_options(gap):
    """Every way to make exactly `gap` letters from one or two plain words (shortest word list first), else a word plus digits."""
    out = []
    if gap in _FILL:
        out += [[w] for w in _FILL[gap]]
    for a in sorted(_FILL, reverse=True):
        b = gap - a
        if b in _FILL and a >= b:
            out += [[x, y] for x in _FILL[a] for y in _FILL[b] if x != y]
    if not out and gap > 0:                                        # one or two letters over: digits close the gap
        out = [['2'] if gap == 1 else ['02']]
    return out


def suggest_map_name(title, length=18, taken=(), number=11):
    """A readable map name of exactly `length` characters (the builder renames the clone source's strings in place, so the length is fixed):
    MapNN_ + the words of the display name that fit whole, then plain words (City, Block, ...) to the exact length; a one-word title longer
    than the room is cut. A name in `taken` is skipped. 'Showcase' -> 'Map11_ShowcaseCity'."""
    pre = 'Map%02d_' % number
    room = max(length - len(pre), 1)
    words = [w[:1].upper() + (w[1:] if not w.isupper() or len(w) <= 4 else w[1:].lower()) for w in re.findall(r'[A-Za-z0-9]+', str(title or ''))]
    core = ''
    for w in words:
        if len(core) + len(w) <= room:
            core += w
    if not core:
        core = (words[0] if words else 'Scene')[:room]
    gap = room - len(core)
    low = {str(t).lower() for t in taken}
    opts = _fill_options(gap) if gap > 0 else [[]]
    have = core.lower()
    opts = [o for o in opts if not any(w.lower() in have for w in o)] or opts
    for o in opts:
        cand = pre + core + ''.join(o)
        if cand.lower() not in low:
            return cand
    for k in range(2, 100):                                        # every wording taken: a number in the last characters
        cand = (pre + core + ''.join(opts[0]))[:length - len(str(k))] + str(k)
        if cand.lower() not in low:
            return cand
    return pre + core + ''.join(opts[0])


def _unique_name(source_name, taken, tag='World'):
    """A map name with the same length as the clone source's (the builder demands it): MapNN_ + words."""
    n = len(source_name)
    low = {t.lower() for t in taken}
    for num in range(11, 40):
        cand = suggest_map_name(tag, n, low, num)
        if cand.lower() not in low:
            return cand
    return source_name


def start_project(tid, size_id, source_key, source_name, host, taken_names=(), package=None, ws=None, others=()):
    """A new project recipe from a template. host = {block, parent, pos, ...} or None (a plain entrance in the Downtown plaza)."""
    size = next(s for s in SIZE_PRESETS if s['id'] == size_id)
    keys = _template_keys(tid, size)
    from .mapgen import terrain, core
    H = terrain.build(keys.get('terrain'), core.Out('w')) if keys.get('terrain') else None
    ay = float(H.at(0.0, 0.0)) + 1.5 if H is not None and H.h is not None else 5.0
    half = size['cells'][0] * size['cell'] / 2.0
    host = host or dict(block='submap01_map02_lostoros_downtown.submap', pos=[-237.0, 2.5, -43.66],
                        parent=dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'))
    name = _unique_name(source_name, taken_names, {'blank': 'Blank', 'desert': 'Desert', 'canyon': 'Canyon', 'town': 'Town'}.get(tid, 'Copy'))
    entry = dict(id='entrance_1', block=host['block'], pos=host['pos'], size=[12, 6, 2], orient=[0, 0.70710678, 0, 0.70710678],
                 arrive=dict(pos=[0.0, round(ay, 2), 0.0], yaw=0),
                 back=dict(pos=[round(min(half * 0.5, 16.0), 2), round(ay + 0.5, 2), 0.0], size=[8, 5, 1.5],
                           spot=dict(pos=[host['pos'][0] + 6, host['pos'][1], host['pos'][2] + 3], yaw=180)))
    if host.get('parent'):
        entry['parent'] = host['parent']
    if ws is not None:                    # a first spot clear of roads, triggers and other portals
        spot = _clear_spot(ws, entry, others)
        if spot:
            dx, dz = spot[0] - entry['pos'][0], spot[1] - entry['pos'][2]
            entry['pos'] = [round(spot[0], 2), entry['pos'][1], round(spot[1], 2)]
            entry['back']['spot']['pos'] = [round(entry['back']['spot']['pos'][0] + dx, 2), entry['back']['spot']['pos'][1], round(entry['back']['spot']['pos'][2] + dz, 2)]
    m = dict(name=name, source=source_key, arrival=dict(pos=[0.0, round(ay, 2), 0.0], orient=[0, 0, 0, 1], floor='declared' if H is not None else 'vanilla'),
             entries=[entry], teleports=[], placement='separate', card=dict(title=(package or 'My new map'), size=size_id, theme={'desert': 'Desert', 'canyon': 'Canyon', 'town': 'Town'}.get(tid, '')))
    if H is None or tid == 'shell':
        m['arrival'] = dict(pos=[980.5, 4.7, 337.0], orient=[0, 0, 0, 1], floor='vanilla')
        entry['arrive'] = dict(pos=[980.5, 4.7, 337.0], yaw=0)
        entry['back'] = dict(pos=[980.5, 6.0, 330.0], size=[8, 5, 1.5], spot=entry['back']['spot'])
    else:
        m.update(keys)
    return dict(package=package or 'My new map', maps=[m])


def _clear_spot(ws, entry, others):
    """The nearest spot (rings of 12 m about the wanted one) whose host-side box is clear. -> (x, z) or None when nothing near is clear."""
    x0, z0 = entry['pos'][0], entry['pos'][2]
    tried = [(0, 0)] + [(dx, dz) for r in (1, 2, 3, 4) for dx in range(-r, r + 1) for dz in range(-r, r + 1) if max(abs(dx), abs(dz)) == r]
    for dx, dz in tried:
        e = dict(entry, pos=[x0 + dx * 12.0, entry['pos'][1], z0 + dz * 12.0])
        try:
            if not host_footprint(ws, e, others):
                return (e['pos'][0], e['pos'][2])
        except Exception:                # noqa: BLE001
            return None
    return None


def templates_info():
    return dict(templates=TEMPLATES, sizes=SIZE_PRESETS)


# ------------------------------------------------------------------------------------------------ host-side footprint
def _host_entities(ws, block):
    for m in ws.catalog['maps']:
        for e in [m['map_block']] + [s['entry'] for s in m['sections']]:
            if short(e) == short(block):
                return ws.level_json(e)['entities']
    return []


def _box_hit(p, c, size, yaw, pad=0.0):
    """Is point p (x, z) inside the box centred c (x, z), size (w, _, l), turned by yaw degrees?"""
    dx, dz = p[0] - c[0], p[1] - c[1]
    a = math.radians(-yaw)
    lx, lz = dx * math.cos(a) - dz * math.sin(a), dx * math.sin(a) + dz * math.cos(a)
    return abs(lx) <= size[0] / 2 + pad and abs(lz) <= size[2] / 2 + pad


def _yaw_of(q):
    if not q:
        return 0.0
    x, y, z, w = q
    return math.degrees(math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)))


def host_footprint(ws, entry, others=()):
    """What the host-side box of one entrance sits on. -> list of {level, title, detail}. others = [(label, block, pos, size, yaw)] other portals."""
    out = []
    size = entry.get('size') or [12, 6, 2]
    pos = entry.get('pos')
    if not pos or not ws or not ws.game:
        return out
    yaw = _yaw_of(entry.get('orient'))
    c = (pos[0], pos[2])
    roads, trig = 0, []
    for e in _host_entities(ws, entry.get('block')):
        p = e.get('pos')
        if not p or abs(p[1] - pos[1]) > max(size[1], 8.0) + 6:
            continue
        if e.get('cat') == 'route' and 'traffic' in (e.get('type') or '') and _box_hit((p[0], p[2]), c, size, yaw, 1.0):
            roads += 1
        elif e.get('cat') == 'trigger' and _box_hit((p[0], p[2]), c, size, yaw, 0.0):
            trig.append(e.get('name') or e.get('type'))
    if roads:
        out.append(dict(level='warn', title='The entrance box sits on a road (%d traffic points inside)' % roads,
                        detail='Cars would drive through it. Move it to the kerb or a pavement.', code='road'))
    if trig:
        out.append(dict(level='warn', title='The entrance box overlaps %d existing trigger%s' % (len(trig), '' if len(trig) == 1 else 's'),
                        detail=', '.join(sorted(set(str(t) for t in trig))[:4]), code='trigger'))
    for label, block, opos, osize, oyaw in others:
        if short(block) != short(entry.get('block')) or not opos:
            continue
        if abs(opos[0] - pos[0]) < (size[0] + osize[0]) / 2 and abs(opos[2] - pos[2]) < (size[2] + osize[2]) / 2:
            out.append(dict(level='error', title='The entrance box overlaps another portal (%s)' % label, detail='Two portals cannot share a spot.', code='portal'))
    return out


# ------------------------------------------------------------------------------------------------ arrivals and seams
def _heights(m):
    from .mapgen import terrain, core
    return terrain.build(m['terrain'], core.Out('w')) if m.get('terrain') else None


def arrival_checks(m):
    """The arrival spots of one map against its own generated ground (when it has one). -> list of {level, title, detail, where}."""
    out = []
    H = _heights(m)
    spots = [('arrival', m.get('arrival'))]
    for e in list(m.get('entries') or []) + ([m['entry']] if m.get('entry') else []):
        if e.get('arrive'):
            spots.append(('entrance ' + str(e.get('id')), e['arrive']))
    box_of = [(str(e.get('id')), e.get('back')) for e in (m.get('entries') or []) if e.get('back')] + ([('return', m['return'])] if m.get('return') else [])
    for label, s in spots:
        if not s or not s.get('pos'):
            continue
        x, y, z = s['pos']
        if H is not None and H.h is not None:
            if not bool(H.inside(x, z)):
                out.append(dict(level='error', title='The %s lies outside the map ground' % label, detail='Move it onto the ground.', where=label))
                continue
            g = float(H.at(x, z))
            if y < g - 0.5:
                out.append(dict(level='error', title='The %s is under the ground (%.1f m)' % (label, g - y), detail='Raise it to the surface.', where=label))
            elif y > g + 6:
                out.append(dict(level='warn', title='The %s hangs %.0f m above the ground' % (label, y - g), detail='The player would fall.', where=label))
        for bl, b in box_of:
            if not b or not b.get('pos'):
                continue
            size = b.get('size') or [8, 5, 1.5]
            if _box_hit((x, z), (b['pos'][0], b['pos'][2]), size, _yaw_of(b.get('orient')), 1.0):
                out.append(dict(level='error', title='The %s stands inside the way back box (%s)' % (label, bl), detail='It would send the player straight back.', where=label))
    return out


def edge_profile(m, edge, samples=24):
    """Ground heights along one edge of the map's ground ('n' z max, 's' z min, 'e' x max, 'w' x min), in the map's own space."""
    H = _heights(m)
    if H is None or H.h is None:
        return None
    x0, z0, x1, z1 = H.ox, H.oz, H.ox + H.nx * H.cell, H.oz + H.nz * H.cell
    pts = []
    for i in range(samples + 1):
        t = i / samples
        pts.append({'e': (x1, z0 + (z1 - z0) * t), 'w': (x0, z0 + (z1 - z0) * t), 'n': (x0 + (x1 - x0) * t, z1), 's': (x0 + (x1 - x0) * t, z0)}[edge])
    return dict(edge=edge, points=[[round(x, 2), round(z, 2)] for x, z in pts], heights=[round(float(H.at(x, z)), 2) for x, z in pts])


def _look_of_block(block):
    from .mapgen import look
    mm = re.search(r'(?:^|_)map(\d+)(?:_|$)', short(block))
    if not mm:
        return None
    for bid in look.data()['blocks']:
        if bid.startswith('mainmap_map%s_' % mm.group(1)):
            return look._from_block(bid)
    return None


def light_compare(m, host_block):
    """Sun and ambient brightness and fog distance of the new map against the host's map block. -> list of items."""
    from .mapgen import look
    out = []
    if not m.get('look'):
        return out
    mine = look.resolve(m['look'])
    theirs = _look_of_block(host_block)
    if not theirs:
        return out

    def val(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    for label, ks, tol in (('sun brightness', ('sun', 'brightness'), 0.6), ('ambient brightness', ('ambient', 'brightness'), 0.25)):
        a, b = val(mine, *ks), val(theirs, *ks)
        if a is not None and b is not None and abs(a - b) > tol:
            out.append(dict(level='warn', title='The %s differs from the next map (%.2f against %.2f)' % (label, a, b),
                            detail='The light changes at the join. Pick the same look.', code='light'))
    fa, fb = val(mine, 'fog', 'far'), val(theirs, 'fog', 'far')
    if fa is not None and fb is not None and abs(fa - fb) > 0.5 * max(fa, fb):
        out.append(dict(level='warn', title='The fog distance differs from the next map (%.0f m against %.0f m)' % (fa, fb), detail='The horizon jumps at the join.', code='fog'))
    return out


def road_compare(m, other):
    """Road widths of two new maps of one project where they meet: warns when the widest roads differ."""
    ra = [r.get('width', 8) for r in m.get('roads') or []]
    rb = [r.get('width', 8) for r in other.get('roads') or []]
    if ra and rb and abs(max(ra) - max(rb)) > 1.0:
        return [dict(level='warn', title='Road width differs at the join (%.0f m against %.0f m)' % (max(ra), max(rb)), detail='Match the road widths.', code='road_width')]
    return []


def scene_area(m):
    """Where a scene map stands in the world: [x0, z0, x1, z1] of its plan, in the map's own coordinates (None for a map without a scene plan)."""
    pl = (m.get('scene') or {}).get('plan') or {}
    if pl.get('x0') is None or not pl.get('w') or not pl.get('h'):
        return None
    c = float(pl.get('cell') or 1.0)
    return [float(pl['x0']), float(pl['z1']) - pl['h'] * c, float(pl['x0']) + pl['w'] * c, float(pl['z1'])]


def _over_shipped(m):
    """A scene map that lies over a shipped map's footprint: the radar and every place read by position take the wrong map."""
    a = scene_area(m)
    if not a:
        return []
    from . import minimap as MM
    over = MM.overlaps([a[0] - MM.MARGIN, a[1] - MM.MARGIN, a[2] + MM.MARGIN, a[3] + MM.MARGIN], MM.SHIPPED_BOUNDS)
    if not over:
        return []
    return [dict(level='warn', title="The map's footprint lies over %s" % ', '.join(over),
                 detail='Give it its own place in the world (Send > Place), away from every shipped map.', where='atlas')]


def analyse(ws, params, projects_other=()):
    """Live checks of one project that need numbers: arrivals, host footprints, guard box, overlaps, seams (light and roads).
    projects_other = [(label, params)] of the other projects, for the portal overlap check. -> dict(maps=[{index, name, items}], items)"""
    maps = params.get('maps') or []
    out = dict(maps=[], items=[])
    others = []
    for label, p in projects_other:
        for om in (p or {}).get('maps') or []:
            for e in list(om.get('entries') or []) + ([om['entry']] if om.get('entry') else []):
                others.append(('%s / %s' % (label, e.get('id')), e.get('block'), e.get('pos'), e.get('size') or [12, 6, 2], _yaw_of(e.get('orient'))))
    rects = []
    for i, m in enumerate(maps):
        items = []
        if m.get('placement') != 'extension':
            try:
                items += arrival_checks(m)
            except Exception as e:           # noqa: BLE001
                items.append(dict(level='warn', title='The ground could not be measured', detail=str(e), where='arrival'))
            for e in list(m.get('entries') or []) + ([m['entry']] if m.get('entry') else []):
                for it in host_footprint(ws, e, others):
                    it['where'] = 'entrance ' + str(e.get('id'))
                    items.append(it)
            items += _over_shipped(m)
            try:
                r, _ = _atlas_rect(m)
                at = (m.get('atlas') or {}).get('pos')
                if at and (max(abs(r[0]), abs(r[1]), abs(r[2]), abs(r[3])) > SAFE_BOX):
                    items.append(dict(level='warn', title='The map lies outside the safe box (16 km)', detail='Move it closer to the middle.', where='atlas'))
                rects.append((i, r))
            except Exception:                # noqa: BLE001
                pass
        nb = m.get('neighbour') or {}
        if m.get('placement') == 'aligned' and nb.get('map'):
            other = next((o for o in maps if o.get('name') == nb['map']), None)
            if other is not None:
                items += road_compare(m, other)
            else:
                items += light_compare(m, nb['map'])
        if m.get('placement') == 'extension':
            items += light_compare(m, (m.get('host') or {}).get('block'))
        for it in items:
            it['map'] = i
        out['maps'].append(dict(index=i, name=m.get('name'), items=items))
        out['items'] += items
    for a in range(len(rects)):
        for b in range(a + 1, len(rects)):
            if _overlap(rects[a][1], rects[b][1]):
                it = dict(level='warn', title='%s and %s overlap in the layout' % (maps[rects[a][0]].get('name'), maps[rects[b][0]].get('name')),
                          detail='They each keep their own space in the game; the layout is only a picture.', where='atlas', map=rects[a][0])
                out['items'].append(it)
                out['maps'][rects[a][0]]['items'].append(it)
    return out


def export_recipe(params, path):
    """Write the project recipe to a file other people can import (the same file the Import box opens)."""
    from . import newmap
    newmap.validate(params)
    if os.path.isdir(path):
        path = os.path.join(path, re.sub(r'[^A-Za-z0-9_-]+', '_', params.get('package') or 'map') + '.json')
    newmap.write(path, params)
    return dict(path=path)
