"""Route and nav editor core (companion tools part B) of TOD Mod Studio.

What it edits (docs/subsystem_navigation.md; navtool.py decodes it, this module builds on its export):
  traffic   database_traffic_point nodes linked by NameOfNextPoint inside road / junction folders
  peds      SignPost nodes with a two-way 'connections' list, Neighborhood circles (BorderDistance)
  tracks    Pathtype(Track) GotoPath / patrol and Track / AI_track with TrackPoint children in 'order'
  blockers  CollisionBox with CollisionFlags bit 32 (NavBlock)

Nav ops (world coordinates in TOD axes, metres; entry = full archive entry; frag = fragment name; node '0x%08X';
new entities get an 'id' that later ops may use in place of a node):
  {"op": "move",            entry, frag, node, pos}
  {"op": "insert_point",    id, entry, frag, track, before: node|id|null (null = after the last point), pos,
                            like: node (template point, default the neighbour), set: {prop: value}}
  {"op": "remove_point",    entry, frag, node}                     detached from its track (save-safe, no delete)
  {"op": "reorder",         entry, frag, track, points: [node|id, ...]}     new point sequence (relink a route)
  {"op": "link" | "unlink", entry, frag, a, b}                      SignPosts, both ends
  {"op": "add_signpost",    id, entry, frag, like, pos, connect: [node...], split: [a, b] (optional)}
  {"op": "remove_signpost", entry, frag, node}                      unlinked everywhere, taken out of the system
  {"op": "set_next",        entry, frag, node, next: name | null}   traffic link (null = end point)
  {"op": "add_traffic_point", id, entry, frag, after, name, pos}    spliced after 'after'
  {"op": "add_navblock",    id, entry, like: {entry, frag, node}, pos, size: [w, h, l], yaw: deg, flags: 32}
  {"op": "retire_navblock", entry, frag, node}                      moved 5 km below, CollisionFlags 0
  {"op": "set",             entry, frag, node|id, prop, value}      speed (TrackPoint #120), target_speed (km/h),
                            slag_dist (arrival slack, m), boundradius (traffic lane radius, m), TrafficMaxSpeed,
                            Curve_Factor_*, BorderDistance (Neighborhood radius), width/height/length ...

How new points stay save-safe and get the parent link the engine needs: blockedit.py (append after the block's
last-instantiated fragment, literal parent = (block << 20) | runtime index, order = the slot in front of the next
point; FUN_0088E8A0 inserts a node after the last sibling with a strictly smaller order).

  m = model(entries, read)              navtool export of each block as the engine links it + what can be edited
  p = preview(m, ops)                   the model with the ops applied (what the editor draws)
  issues = validate(p, collision_sets)  dangling links, one-way links, routes through new collision, unreachable points
  add_to_builder(builder, m, ops)       the build requests (blockedit.Builder)
  verify(m, ops, out)                   navtool re-export of the built blocks == preview, per op
"""
import collections
import copy
import math

from . import blockedit as BE
from . import tools

NAVBLOCK = 32
RETIRE_DROP = 5000.0
EDITABLE_PROPS = {
    'TrackPoint': ['speed', 'flags', 'Is_Here_Distance', 'movetype'],
    'AI_track_point': ['target_speed', 'slag_dist', 'Slide_time', 'Stay_In_Vehicle', 'Pause_point'],
    'traffic_point': ['boundradius', 'Curve_Factor_Straight', 'Curve_Factor_Right', 'Curve_Factor_Left', 'Sub_Type'],
    'road_folder': ['TrafficMaxSpeed', 'TrafficMaxDensity', 'TrafficAllowLargeVehicles'],
    'Neighborhood': ['BorderDistance', 'PedestrianDensity', 'NeighborhoodID'],
    'track': ['looping', 'pingpong', 'spline', 'PathType'],
    'navblock': ['width', 'height', 'length', 'CollisionFlags'],
}
UNITS = {'speed': 'TrackPoint speed (engine value; GotoPath runs use Goto_Movement)', 'target_speed': 'km/h (x 1/3.6 in the engine)',
         'slag_dist': 'm (arrival slack, the vehicle lane tolerance)', 'boundradius': 'm (traffic point radius, the lane half-width)',
         'BorderDistance': 'm (Neighborhood circle radius)', 'TrafficMaxSpeed': 'unit open (18 / 25 / 15 shipped; m/s likely)'}


class NavError(ValueError):
    pass


def nt():
    return tools.load_more('navtool')


def short(e):
    return (e or '').replace('\\', '/').split('/')[-1]


def fshort(f):
    return (f or '').replace('\\', '/').split('/')[-1]


# ---------------------------------------------------------------------------------------------- model
def export_block(entry, raw):
    """navtool export of the block as the engine links it (literal-parented new points under their track)."""
    ev, moved = BE.engine_view(raw, entry)
    ext = '.' + entry.rsplit('.', 1)[-1].lower()
    ex = nt().export_from_bytes(ev, entry, ext)
    ex['literal_linked'] = moved
    return ex


def model(entries, read):
    """{'blocks': {entry: navtool export}, 'edit': {entry: {last_fragment, can_append, reason}}}"""
    out = dict(kind='todct-nav-model', version=1, blocks={}, edit={})
    for e in entries:
        raw = read(e)
        out['blocks'][e] = export_block(e, raw)
        bi = BE.BlockInfo(e, raw)
        try:
            lf, nxt = bi.last_fragment()
            out['edit'][e] = dict(last_fragment=lf, next_runtime_index='0x%X' % nxt, can_append=True)
        except BE.BuildError as x:
            out['edit'][e] = dict(can_append=False, reason=str(x))
    return out


def _idx(lst):
    return {(fshort(d['frag']), d['node']): d for d in lst}


def find_track(m, entry, frag, track):
    for t in m['blocks'][entry]['tracks']:
        if fshort(t['frag']) == fshort(frag) and t['node'] == track:
            return t
    raise NavError('track %s %s not in %s' % (fshort(frag), track, short(entry)))


def track_of_point(m, entry, frag, node):
    for t in m['blocks'][entry]['tracks']:
        if fshort(t['frag']) == fshort(frag) and any(p['node'] == node for p in t['points']):
            return t
    return None


def routes(m):
    """Flat list for the editor: every route with its points (ordered), links and editable values."""
    out = []
    for e, ex in m['blocks'].items():
        for t in ex['tracks']:
            out.append(dict(entry=e, block=short(e), frag=fshort(t['frag']), node=t['node'], kind=t['kind'],
                            name=t.get('name'), path=t.get('path'), looping=t.get('looping'), pingpong=t.get('pingpong'),
                            placeholders=t.get('placeholders'), points=[dict(node=p['node'], pos=p['pos'], order=p.get('order'),
                            type=p.get('type'), new=p.get('new'), **{k: p[k] for k in ('speed', 'target_speed', 'slag_dist')
                                                                      if k in p}) for p in t['points']]))
        sp = ex['peds']['signposts']
        if sp:
            out.append(dict(entry=e, block=short(e), kind='signposts', name='Pedestrian network', points=[
                dict(node=s['node'], frag=fshort(s['frag']), pos=s['pos'], connections=s['connections'], new=s.get('new'))
                for s in sp]))
        tp = ex['traffic']['points']
        if tp:
            out.append(dict(entry=e, block=short(e), kind='traffic', name='Traffic network', points=[
                dict(node=p['node'], frag=fshort(p['frag']), name=p.get('name'), pos=p['pos'], next=p.get('next'),
                     next_name=p.get('next_name'), sub_type=p.get('effective_sub_type'), new=p.get('new')) for p in tp]))
        nb = [b for b in ex['blockers'] if b.get('navblock')]
        if nb:
            out.append(dict(entry=e, block=short(e), kind='navblocks', name='NavBlock boxes', points=[
                dict(node=b['node'], frag=fshort(b['frag']), pos=b['pos'], size=b['size'], orient=b['orient'],
                     flags=b['collisionflags'], new=b.get('new')) for b in nb]))
        hoods = ex['peds']['neighborhoods']
        if hoods:
            out.append(dict(entry=e, block=short(e), kind='neighborhoods', name='Neighborhoods', points=[
                dict(node=h['node'], frag=fshort(h['frag']), name=h.get('name'), pos=h['pos'], radius=h.get('BorderDistance'))
                for h in hoods]))
    return out


# ---------------------------------------------------------------------------------------------- preview
def _ref(o, k='node'):
    return o.get(k) if o.get(k) is not None else o.get('id')


def preview(m, ops):
    """The model with the ops applied: what the editor draws and validate. New entities carry 'new': True and their
    op id as node."""
    p = copy.deepcopy(m)
    for i, o in enumerate(ops):
        op = o['op']
        e = o['entry']
        if e not in p['blocks']:
            raise NavError('op %d: block %s is not in the nav model' % (i, short(e)))
        ex = p['blocks'][e]
        fr = fshort(o.get('frag'))
        if op == 'move':
            hit = _find_any(ex, fr, _ref(o))
            if not hit:
                raise NavError('op %d move: %s %s not found' % (i, fr, _ref(o)))
            for h in hit:
                h['pos'] = [float(x) for x in o['pos']]
        elif op == 'insert_point':
            t = _track(ex, fr, o['track'], i)
            pts = t['points']
            like = o.get('like') or (pts[-1]['node'] if pts else None)
            base = next((q for q in pts if q['node'] == like), pts[0] if pts else dict(type='TrackPoint'))
            q = dict(copy.deepcopy(base), node=o['id'], pos=[float(x) for x in o['pos']], new=True, like=like)
            q.update(o.get('set') or {})
            if o.get('before') in (None, ''):
                pts.append(q)
            else:
                j = next((k for k, x in enumerate(pts) if x['node'] == o['before']), None)
                if j is None:
                    raise NavError('op %d insert_point: %s is not a point of track %s' % (i, o['before'], o['track']))
                pts.insert(j, q)
        elif op == 'remove_point':
            t = _track_of(ex, fr, o['node'])
            if t is None:
                raise NavError('op %d remove_point: %s is not on a track' % (i, o['node']))
            t['points'] = [x for x in t['points'] if x['node'] != o['node']]
        elif op == 'reorder':
            t = _track(ex, fr, o['track'], i)
            by = {x['node']: x for x in t['points']}
            if sorted(by) != sorted(o['points']):
                raise NavError('op %d reorder: the new sequence must hold exactly the track\'s points' % i)
            t['points'] = [by[n] for n in o['points']]
        elif op in ('link', 'unlink'):
            sp = _sp(ex, fr)
            a, b = sp.get(o['a']), sp.get(o['b'])
            if a is None or b is None:
                raise NavError('op %d %s: both ends must be SignPosts of %s' % (i, op, fr))
            for x, y in ((a, b), (b, a)):
                c = [z for z in x['connections'] if z != y['node']]
                if op == 'link':
                    c.append(y['node'])
                x['connections'] = c
        elif op == 'add_signpost':
            sp = _sp(ex, fr)
            like = sp.get(o['like'])
            if like is None:
                raise NavError('op %d add_signpost: template %s is not a SignPost' % (i, o['like']))
            q = dict(copy.deepcopy(like), node=o['id'], pos=[float(x) for x in o['pos']], connections=[], new=True)
            conn = list(o.get('connect') or [])
            if o.get('split'):
                A, B = o['split']
                for x, y in ((A, B), (B, A)):
                    sp[x]['connections'] = [z for z in sp[x]['connections'] if z != y]
                conn += [A, B]
            for c in dict.fromkeys(conn):
                q['connections'].append(c)
                sp[c]['connections'].append(o['id'])            # the engine makes every link mutual (FUN_009212A0)
            ex['peds']['signposts'].append(q)
        elif op == 'remove_signpost':
            sp = _sp(ex, fr)
            for x in sp.values():
                x['connections'] = [z for z in x['connections'] if z != o['node']]
            ex['peds']['signposts'] = [x for x in ex['peds']['signposts'] if not (fshort(x['frag']) == fr and x['node'] == o['node'])]
        elif op == 'set_next':
            tp = _tp(ex, fr)
            x = tp.get(_ref(o))
            if x is None:
                raise NavError('op %d set_next: %s is not a traffic point' % (i, _ref(o)))
            x['next_name'] = o['next']
            _resolve_traffic(ex, fr)
        elif op == 'add_traffic_point':
            tp = _tp(ex, fr)
            A = tp.get(o['after'])
            if A is None:
                raise NavError('op %d add_traffic_point: %s is not a traffic point' % (i, o['after']))
            if any((x.get('name') or '').lower() == o['name'].lower() for x in tp.values()):
                raise NavError('op %d add_traffic_point: the name %s is taken in %s' % (i, o['name'], fr))
            q = dict(copy.deepcopy(A), node=o['id'], name=o['name'], pos=[float(x) for x in o['pos']],
                     next_name=A.get('next_name'), Sub_Type=0, new=True)
            A['next_name'] = o['name']
            ex['traffic']['points'].append(q)
            _resolve_traffic(ex, fr)
        elif op == 'add_navblock':
            yaw = math.radians(float(o.get('yaw') or 0.0))
            ex['blockers'].append(dict(frag='(new)', node=o['id'], type='CollisionBox', name=o.get('name') or 'navigation_block',
                                       pos=[float(x) for x in o['pos']], size=[float(x) for x in o['size']],
                                       orient=[0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)],
                                       collisionflags=int(o.get('flags', NAVBLOCK)), navblock=bool(int(o.get('flags', NAVBLOCK)) & NAVBLOCK),
                                       new=True))
        elif op == 'retire_navblock':
            b = next((x for x in ex['blockers'] if fshort(x['frag']) == fr and x['node'] == o['node']), None)
            if b is None:
                raise NavError('op %d retire_navblock: %s not found' % (i, o['node']))
            b['pos'] = [b['pos'][0], b['pos'][1] - RETIRE_DROP, b['pos'][2]]
            b['collisionflags'] = 0
            b['navblock'] = False
        elif op == 'set':
            hit = _find_any(ex, fr, _ref(o)) or _find_new(ex, _ref(o))
            if not hit:
                raise NavError('op %d set: %s not found' % (i, _ref(o)))
            for h in hit:
                h[o['prop']] = o['value']
                if o['prop'] in ('width', 'height', 'length') and 'size' in h:
                    h['size'][('width', 'height', 'length').index(o['prop'])] = float(o['value'])
                if o['prop'] == 'CollisionFlags':
                    h['collisionflags'] = int(o['value'])
                    h['navblock'] = bool(int(o['value']) & NAVBLOCK)
                if o['prop'] == 'BorderDistance':
                    h['BorderDistance'] = float(o['value'])
        else:
            raise NavError('op %d: unknown nav op %r' % (i, op))
    return p


def _find_any(ex, fr, node):
    out = []
    for t in ex['tracks']:
        if fshort(t['frag']) == fr and t['node'] == node:
            out.append(t)
        for q in t['points']:
            if (fshort(t['frag']) == fr or q.get('new')) and q['node'] == node:
                out.append(q)
    for lst in (ex['peds']['signposts'], ex['traffic']['points'], ex['traffic']['folders'], ex['blockers'],
                ex['peds']['neighborhoods'], ex['misc']):
        for x in lst:
            if (fshort(x['frag']) == fr or x.get('new')) and x['node'] == node:
                out.append(x)
    return out


def _find_new(ex, node):
    return [x for x in _find_any(ex, '(new)', node) if x.get('new')]


def _track(ex, fr, node, i):
    for t in ex['tracks']:
        if fshort(t['frag']) == fr and t['node'] == node:
            return t
    raise NavError('op %d: track %s %s not found' % (i, fr, node))


def _track_of(ex, fr, node):
    for t in ex['tracks']:
        if fshort(t['frag']) == fr and any(q['node'] == node for q in t['points']):
            return t
    return None


def _sp(ex, fr):
    return {x['node']: x for x in ex['peds']['signposts'] if fshort(x['frag']) == fr or x.get('new')}


def _tp(ex, fr):
    return {x['node']: x for x in ex['traffic']['points'] if fshort(x['frag']) == fr or x.get('new')}


def _resolve_traffic(ex, fr):
    """Re-resolve next links by name inside one fragment (FUN_006556E0: a descendant of the grandparent; the tool
    keeps names unique per fragment, so a name match is the link)."""
    tp = [x for x in ex['traffic']['points'] if fshort(x['frag']) == fr or x.get('new')]
    names = collections.defaultdict(list)
    for x in tp:
        if x.get('name'):
            names[x['name'].lower()].append(x['node'])
    for x in tp:
        if x.get('effective_sub_type') in ('junction_in',):
            continue
        nn = (x.get('next_name') or '').lower()
        hits = names.get(nn, []) if nn else []
        x['next'] = hits[:1]
        if nn and not hits:
            x['status'] = 'missing_next'
        elif len(hits) > 1:
            x['status'] = 'ambiguous_next'
        elif not nn:
            x['status'] = 'end'
            x['effective_sub_type'] = 'end'
        else:
            x['status'] = 'ok'


# ---------------------------------------------------------------------------------------------- validation
def _planes(piece):
    V = piece['verts']
    out = []
    for f in piece['faces']:
        if len(f) < 3:
            continue
        a = V[f[0]]
        n = [0.0, 0.0, 0.0]
        for k in range(1, len(f) - 1):                 # polygon normal (sum of fan triangles), outward winding
            b, c = V[f[k]], V[f[k + 1]]
            u = [b[j] - a[j] for j in range(3)]
            w = [c[j] - a[j] for j in range(3)]
            n = [n[0] + u[1] * w[2] - u[2] * w[1], n[1] + u[2] * w[0] - u[0] * w[2], n[2] + u[0] * w[1] - u[1] * w[0]]
        L = math.sqrt(sum(x * x for x in n))
        if L < 1e-12:
            continue
        n = [x / L for x in n]
        out.append((n, sum(n[j] * a[j] for j in range(3))))
    return out


def segment_hits_convex(p0, p1, planes, eps=1e-6):
    """Liang-Barsky clip of the segment against the convex piece (inside: n.x <= d). -> entry parameter or None."""
    t0, t1 = 0.0, 1.0
    d = [p1[j] - p0[j] for j in range(3)]
    for n, dd in planes:
        den = sum(n[j] * d[j] for j in range(3))
        num = dd - sum(n[j] * p0[j] for j in range(3))
        if abs(den) < eps:
            if num < -eps:
                return None
            continue
        t = num / den
        if den > 0:
            t1 = min(t1, t)
        else:
            t0 = max(t0, t)
        if t0 > t1 + eps:
            return None
    return t0


def _box_planes(pos, size, orient):
    """Planes of an oriented box (TOD axes; orient = TRUE world rotation as navtool exports it)."""
    hx_, hy, hz = [float(s or 0) / 2.0 for s in size]
    q = orient or [0, 0, 0, 1]

    def rot(v):
        x, y, z, w = q
        tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
        return [v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx)]
    out = []
    for axis, h in ((0, hx_), (1, hy), (2, hz)):
        for sgn in (1, -1):
            n = [0.0, 0.0, 0.0]
            n[axis] = float(sgn)
            n = rot(n)
            out.append((n, sum(n[j] * pos[j] for j in range(3)) + h))
    return out


def segments(p):
    """(kind, label, a, b, ref) for every walked segment of the preview model."""
    out = []
    for e, ex in p['blocks'].items():
        for t in ex['tracks']:
            pts = t['points']
            pairs = list(zip(pts, pts[1:]))
            if t.get('looping') and len(pts) > 2:
                pairs.append((pts[-1], pts[0]))
            for a, b in pairs:
                out.append((t['kind'], t.get('name') or t['node'], a['pos'], b['pos'],
                            dict(entry=e, frag=fshort(t['frag']), track=t['node'], a=a['node'], b=b['node'])))
        sp = {x['node']: x for x in ex['peds']['signposts']}
        seen = set()
        for x in ex['peds']['signposts']:
            for c in x['connections']:
                key = tuple(sorted((x['node'], c)))
                if c in sp and key not in seen:
                    seen.add(key)
                    out.append(('signpost', 'SignPost link', x['pos'], sp[c]['pos'], dict(entry=e, a=x['node'], b=c)))
        tp = {x['node']: x for x in ex['traffic']['points']}
        for x in ex['traffic']['points']:
            for c in x.get('next') or []:
                if c in tp:
                    out.append(('traffic', x.get('name') or x['node'], x['pos'], tp[c]['pos'], dict(entry=e, a=x['node'], b=c)))
    return out


def validate(p, collision_sets=None, body_height=1.0, climb=4.0):
    """Issues of the preview model: [{severity, kind, message, pos, ref}]."""
    iss = []

    def add(sev, kind, msg, pos=None, **ref):
        iss.append(dict(severity=sev, kind=kind, message=msg, pos=pos, ref=ref))
    for e, ex in p['blocks'].items():
        b = short(e)
        # dangling and one-way SignPost links
        sp = {x['node']: x for x in ex['peds']['signposts']}
        for x in ex['peds']['signposts']:
            for c in x['connections']:
                if c not in sp:
                    add('error', 'dangling', '%s: SignPost %s links to %s, which does not exist' % (b, x['node'], c), x['pos'],
                        entry=e, node=x['node'])
                elif x['node'] not in sp[c]['connections']:
                    add('error', 'one_way', '%s: SignPost link %s -> %s is one-way; pedestrian links must be two-way '
                        '(the engine links both ends, so the result depends on load order)' % (b, x['node'], c), x['pos'],
                        entry=e, node=x['node'], other=c)
        # traffic names
        for x in ex['traffic']['points']:
            st = x.get('status')
            if st in ('missing_next', 'ambiguous_next', 'junction_without_exit'):
                add('error' if st != 'ambiguous_next' else 'warning', 'dangling',
                    '%s: traffic point %s (%s): %s %r' % (b, x.get('name'), x['node'], st.replace('_', ' '), x.get('next_name')),
                    x['pos'], entry=e, node=x['node'])
        # tracks
        for t in ex['tracks']:
            if not t['points']:
                add('error', 'dangling', '%s: %s %s has no points' % (b, t['kind'], t.get('name') or t['node']), t.get('pos'),
                    entry=e, track=t['node'])
            for a, c in zip(t['points'], t['points'][1:]):
                dy = c['pos'][1] - a['pos'][1]
                if t['kind'] in ('goto', 'patrol') and abs(dy) > climb:
                    add('warning', 'unreachable', '%s: %s %s: the leg %s -> %s climbs %.1f m; enemies walk legs straight '
                        '(no path-finding), so the next point may be unreachable' % (b, t['kind'], t.get('name'), a['node'],
                                                                                    c['node'], dy), c['pos'], entry=e, track=t['node'], node=c['node'])
            for q in t['points']:
                if q['pos'][1] < -1000:
                    add('warning', 'unreachable', '%s: point %s of %s lies %.0f m below the world (retired?)' % (
                        b, q['node'], t.get('name'), -q['pos'][1]), q['pos'], entry=e, track=t['node'], node=q['node'])
        # signpost reachability (components)
        if sp:
            parent = {n: n for n in sp}

            def f(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            for x in sp.values():
                for c in x['connections']:
                    if c in sp:
                        ra, rb = f(x['node']), f(c)
                        if ra != rb:
                            parent[ra] = rb
            comp = collections.Counter(f(n) for n in sp)
            big = comp.most_common(1)[0][0]
            for n, x in sp.items():
                if not x['connections']:
                    add('warning', 'unreachable', '%s: SignPost %s has no links (only the random-post fallback reaches it)'
                        % (b, n), x['pos'], entry=e, node=n)
                elif f(n) != big and x.get('new'):
                    add('warning', 'unreachable', '%s: new SignPost %s is not connected to the main pedestrian network'
                        % (b, n), x['pos'], entry=e, node=n)
        # traffic reachability from spawn points
        tp = {x['node']: x for x in ex['traffic']['points']}
        if tp:
            spawn = [n for n, x in tp.items() if x.get('Sub_Type') == 4 or x.get('effective_sub_type') == 'spawn']
            seen, stack = set(spawn), list(spawn)
            while stack:
                n = stack.pop()
                for c in tp[n].get('next') or []:
                    if c in tp and c not in seen:
                        seen.add(c)
                        stack.append(c)
            if spawn:
                for n, x in tp.items():
                    if n not in seen and x.get('new'):
                        add('warning', 'unreachable', '%s: new traffic point %s (%s) is not reachable from any spawn point'
                            % (b, x.get('name'), n), x['pos'], entry=e, node=n)
    # crossings: new collision pieces and new NavBlock boxes
    solids = []
    for s in collision_sets or []:
        if s.get('visual_only'):
            continue
        for k, pc in enumerate(s.get('pieces') or []):
            solids.append(('collision', '%s piece %d' % (s.get('label') or s.get('id'), k), _planes(pc)))
    for e, ex in p['blocks'].items():
        for bx in ex['blockers']:
            if bx.get('new') and bx.get('navblock'):
                solids.append(('navblock', 'new NavBlock %s' % bx['node'], _box_planes(bx['pos'], bx['size'], bx.get('orient'))))
    if solids:
        for kind, label, a, c, ref in segments(p):
            A = [a[0], a[1] + body_height, a[2]]
            C = [c[0], c[1] + body_height, c[2]]
            for sk, sl, pl in solids:
                if sk == 'navblock' and kind not in ('goto', 'patrol', 'signpost'):
                    continue
                t = segment_hits_convex(A, C, pl)
                if t is not None:
                    hit = [A[j] + (C[j] - A[j]) * t for j in range(3)]
                    msg = ('%s %s (%s -> %s) crosses %s' % (kind, label, ref.get('a'), ref.get('b'), sl))
                    if sk == 'collision':
                        msg += ': walkers on this leg will stop at it (move the route or the geometry)'
                    else:
                        msg += (': a GotoPath run is stopped by its body probe there (no avoidance on GotoPaths)'
                                if kind == 'goto' else ': the Navigator steers around it')
                    iss.append(dict(severity='warning' if sk == 'collision' else 'info', kind='crossing', message=msg,
                                    pos=[round(x, 3) for x in hit], ref=ref))
    return iss


# ---------------------------------------------------------------------------------------------- build
def _orders(seq, cur):
    """Orders for the final point sequence. seq: items (existing node or new id); cur: {existing node: order}.
    Keep the existing orders when the new points fit in front of their successor (FUN_0088E8A0: a node goes after the
    last sibling with a strictly smaller order) and the existing points stay ascending; else renumber all by 10.
    -> ({item: order}, renumbered)"""
    ex = [x for x in seq if x in cur]
    ok = all(cur[a] < cur[b] for a, b in zip(ex, ex[1:]))
    res = {x: cur[x] for x in ex}
    if ok:
        i = 0
        while i < len(seq) and ok:
            if seq[i] in cur:
                i += 1
                continue
            j = i
            while j < len(seq) and seq[j] not in cur:
                j += 1
            run = seq[i:j]
            prev = cur[seq[i - 1]] if i > 0 else None
            nxt = cur[seq[j]] if j < len(seq) else None
            k = len(run)
            if nxt is None:
                vals = [(prev or 0) + 1 + n for n in range(k)]
            else:
                vals = [nxt - k + 1 + n for n in range(k)]
                if prev is not None and vals[0] <= prev:
                    ok = False
                    break
            if any(v < -32768 or v > 32767 for v in vals):
                ok = False
                break
            for x, v in zip(run, vals):
                res[x] = v
            i = j
    if ok:
        return res, False
    return {x: 10 * (n + 1) for n, x in enumerate(seq)}, True


def add_to_builder(B, m, ops, log=None):
    """Turn nav ops into blockedit requests. Returns notes."""
    notes = []
    tracks = {}                        # (entry, frag, track) -> [items]
    track_info = {}
    new_points = {}                    # id -> op
    for o in ops:
        if o['op'] in ('insert_point', 'remove_point', 'reorder'):
            e = o['entry']
            fr = fshort(o['frag'])
            tn = o.get('track') or (track_of_point(m, e, fr, o['node']) or {}).get('node')
            if tn is None:
                raise NavError('%s: %s is not on a track' % (o['op'], o.get('node')))
            key = (e, fr, tn)
            if key not in tracks:
                t = find_track(m, e, fr, tn)
                tracks[key] = [q['node'] for q in t['points']]
                track_info[key] = t
            seq = tracks[key]
            if o['op'] == 'insert_point':
                if o.get('before') in (None, ''):
                    seq.append(o['id'])
                else:
                    if o['before'] not in seq:
                        raise NavError('insert_point: %s is not a point of %s' % (o['before'], tn))
                    seq.insert(seq.index(o['before']), o['id'])
                new_points[o['id']] = o
            elif o['op'] == 'remove_point':
                seq.remove(o['node'])
                t = track_info[key]
                B.set(e, t['frag'], o['node'], 'parent', _parent_of(m, e, t['frag'], tn))
                notes.append('%s: point %s detached from %s (parent -> the track\'s parent; no node deleted)' % (short(e), o['node'], tn))
            else:
                if sorted(o['points']) != sorted(seq):
                    raise NavError('reorder of %s must name exactly its points' % tn)
                tracks[key] = list(o['points'])
    for (e, fr, tn), seq in tracks.items():
        t = track_info[(e, fr, tn)]
        cur = {q['node']: q.get('order') or 0 for q in t['points']}
        cur = {k: v for k, v in cur.items() if k in seq}
        orders, renum = _orders(seq, cur)
        if renum:
            notes.append('%s %s: point orders renumbered by 10 (no free slot between the neighbours)' % (short(e), t.get('name') or tn))
        for x in seq:
            if x in cur and orders[x] != cur[x]:
                B.set(e, t['frag'], x, 'order', orders[x])
        for x in seq:
            if x in new_points:
                o = new_points[x]
                pts = {q['node']: q for q in t['points']}
                like = o.get('like')
                if not like:
                    i = seq.index(x)
                    nb = [y for y in seq[:i][::-1] if y in pts] + [y for y in seq[i:] if y in pts]
                    like = nb[0] if nb else None
                if like is None:
                    raise NavError('insert_point %s: the track has no point to copy; give "like"' % x)
                sets = dict(o.get('set') or {})
                B.append(e, x, (e, t['frag'], like), parent=('ref', t['frag'], tn), order=orders[x], pos=o['pos'], sets=sets)
                notes.append('%s: new point %s in %s at order %d (literal parent = the track)' % (short(e), x, t.get('name') or tn, orders[x]))
    for o in ops:
        op, e = o['op'], o['entry']
        fr = o.get('frag')
        if op in ('insert_point', 'remove_point', 'reorder'):
            continue
        if op == 'move':
            if _is_new(o.get('node'), ops):
                _new_sets(B, o['node'], pos=o['pos'])
            else:
                B.move(e, fr, o['node'], pos=o['pos'])
        elif op in ('link', 'unlink'):
            ex = m['blocks'][e]
            sp = _sp(ex, fshort(fr))
            for x, y in ((o['a'], o['b']), (o['b'], o['a'])):
                if _is_new(x, ops):
                    raise NavError('%s: link a new SignPost through add_signpost "connect"' % op)
                c = _connections_now(B, e, fr, x, sp)
                c = [z for z in c if z != y]
                if op == 'link':
                    if _is_new(y, ops):
                        continue                 # the new post's own list carries it; the engine adds both ends
                    c.append(y)
                _set_connections(B, e, fr, x, c)
        elif op == 'add_signpost':
            ex = m['blocks'][e]
            sp = _sp(ex, fshort(fr))
            like = sp[o['like']]
            folder = _parent_of(m, e, fr, o['like'])
            conn = list(o.get('connect') or [])
            if o.get('split'):
                A, Bn = o['split']
                for x, y in ((A, Bn), (Bn, A)):
                    _set_connections(B, e, fr, x, [z for z in _connections_now(B, e, fr, x, sp) if z != y])
                conn += [A, Bn]
            refs = [('ref', fr, c) for c in dict.fromkeys(conn)]
            B.append(e, o['id'], (e, like['frag'], o['like']), parent=('ref', fr, folder), pos=o['pos'],
                     sets={'connections': refs})
            notes.append('%s: new SignPost %s with %d links (its own list; the engine adds the other ends, FUN_009212A0)'
                         % (short(e), o['id'], len(refs)))
        elif op == 'remove_signpost':
            ex = m['blocks'][e]
            sp = _sp(ex, fshort(fr))
            for n, x in sp.items():
                if o['node'] in (x.get('connections') or []) and n != o['node']:
                    _set_connections(B, e, fr, n, [z for z in _connections_now(B, e, fr, n, sp) if z != o['node']])
            _set_connections(B, e, fr, o['node'], [])
            folder = _parent_of(m, e, fr, o['node'])
            system = _parent_of(m, e, fr, folder) if folder else 0
            B.set(e, fr, o['node'], 'parent', _parent_of(m, e, fr, system) if system else 0)
        elif op == 'set_next':
            if o['next'] is None:
                B.set(e, fr, o['node'], 'NameOfNextPoint', '')
                B.set(e, fr, o['node'], 'Sub_Type', 3)
            else:
                B.set(e, fr, o['node'], 'NameOfNextPoint', o['next'])
        elif op == 'add_traffic_point':
            ex = m['blocks'][e]
            tp = _tp(ex, fshort(fr))
            A = tp[o['after']]
            folder = _parent_of(m, e, fr, o['after'])
            B.append(e, o['id'], (e, A['frag'], o['after']), parent=('ref', fr, folder), name=o['name'], pos=o['pos'],
                     sets={'NameOfNextPoint': A.get('next_name') or '', 'Sub_Type': 0})
            B.set(e, fr, o['after'], 'NameOfNextPoint', o['name'])
        elif op == 'add_navblock':
            L = o['like']
            yaw = math.radians(float(o.get('yaw') or 0.0))
            sz = [float(x) for x in o['size']]
            B.append(e, o['id'], (L['entry'], L['frag'], L['node']), parent=None, name=o.get('name') or 'navigation_block',
                     pos=o['pos'], rot=[0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)],
                     sets={'width': sz[0], 'height': sz[1], 'length': sz[2], 'CollisionFlags': int(o.get('flags', NAVBLOCK))})
        elif op == 'retire_navblock':
            b = next(x for x in m['blocks'][e]['blockers'] if fshort(x['frag']) == fshort(fr) and x['node'] == o['node'])
            B.move(e, fr, o['node'], pos=[b['pos'][0], b['pos'][1] - RETIRE_DROP, b['pos'][2]])
            B.set(e, fr, o['node'], 'CollisionFlags', 0)
        elif op == 'set':
            if _is_new(_ref(o), ops):
                _new_sets(B, _ref(o), **{o['prop']: o['value']})
            else:
                B.set(e, fr, o['node'], o['prop'], o['value'])
        else:
            raise NavError('unknown nav op %r' % op)
    return notes


def _is_new(x, ops):
    return isinstance(x, str) and not x.lower().startswith('0x') and any(o.get('id') == x for o in ops)


def _new_sets(B, uid, pos=None, **sets):
    for L in B.appends.values():
        for a in L:
            if a['uid'] == uid:
                if pos is not None:
                    a['pos'] = [float(v) for v in pos]
                a['sets'].update(sets)
                return
    raise NavError('new entity %s: set before it was added' % uid)


def _connections_now(B, e, fr, node, sp):
    """The connection list of an existing post including earlier ops of this build."""
    for op in reversed(B.ops.get(e, [])):
        if op['op'] == 'set' and op['prop'] == 'connections' and op['entity'] == node and fshort(op['fragment']) == fshort(fr):
            return list(op['value'])
    return list(sp[node]['connections'])


def _set_connections(B, e, fr, node, conns):
    L = B.ops[e]
    L[:] = [op for op in L if not (op['op'] == 'set' and op['prop'] == 'connections' and op['entity'] == node
                                    and fshort(op['fragment']) == fshort(fr))]
    B.set(e, fr, node, 'connections', list(conns))


def _parent_of(m, e, fr, node):
    """Parent key of an existing node, read from the block (navtool's export does not carry parents)."""
    raw = m.get('_raw', {}).get(e)
    if raw is None:
        raise NavError('model has no block bytes for %s (use model_with_raw)' % short(e))
    bi = m.setdefault('_bi', {}).get(e)
    if bi is None:
        bi = BE.BlockInfo(e, raw)
        m['_bi'][e] = bi
    nm = BE.frag_name(bi.frs, fr)
    p = bi.doc(nm).get(BE.node_id(node), 'parent') or 0
    return BE.hx(p) if p else 0


def model_with_raw(entries, read):
    m = model(entries, read)
    m['_raw'] = {e: read(e) for e in entries}
    return m


def public(m):
    return {k: v for k, v in m.items() if not k.startswith('_')}


# ---------------------------------------------------------------------------------------------- verification
def _close(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def verify(m, ops, out):
    """Re-export every built block with navtool (engine view) and compare with preview(m, ops): track sequences and
    positions, SignPost links (runtime: mutual), traffic next names, NavBlock boxes. -> report"""
    want = preview(public(m), ops)
    rep = dict(blocks=[], result='PASS')
    for e in want['blocks']:
        if e not in out:
            continue
        got = export_block(e, out[e])
        W = want['blocks'][e]
        res = dict(entry=short(e), checks=[])
        # tracks: same sequence of positions (new points matched by position)
        for t in W['tracks']:
            g = next((x for x in got['tracks'] if fshort(x['frag']) == fshort(t['frag']) and x['node'] == t['node']), None)
            if g is None:
                res['checks'].append(('FAIL', 'track %s missing after the build' % t['node']))
                continue
            wp = [q['pos'] for q in t['points']]
            gp = [q['pos'] for q in g['points']]
            ok = len(wp) == len(gp) and all(_close(a, b) for a, b in zip(wp, gp))
            changed = any(q.get('new') for q in t['points']) or [q['node'] for q in t['points']] != [
                q['node'] for q in next(x for x in m['blocks'][e]['tracks'] if x['node'] == t['node'] and fshort(x['frag']) == fshort(t['frag']))['points']]
            if changed or not ok:
                res['checks'].append(('PASS' if ok else 'FAIL', '%s %s: %d points in engine order%s' % (
                    t['kind'], t.get('name') or t['node'], len(gp), '' if ok else ' (expected %d: %s, got %s)' % (len(wp), wp, gp))))
        # signposts (runtime links are mutual: compare as undirected edge sets by position)
        def edges(ex, mutual):
            pos = {x['node']: tuple(round(v, 3) for v in x['pos']) for x in ex['peds']['signposts']}
            E = set()
            for x in ex['peds']['signposts']:
                for c in x['connections']:
                    if c in pos:
                        E.add(tuple(sorted((pos[x['node']], pos[c]))))
            return E
        if W['peds']['signposts'] or got['peds']['signposts']:
            a, b = edges(W, True), edges(got, True)
            res['checks'].append(('PASS' if a == b else 'FAIL', 'SignPost links (runtime, mutual): %d expected, %d built%s'
                                  % (len(a), len(b), '' if a == b else '; differ by %d' % len(a ^ b))))
        if W['traffic']['points']:
            a = {(round(x['pos'][0], 3), round(x['pos'][2], 3), (x.get('next_name') or '').lower()) for x in W['traffic']['points']}
            b = {(round(x['pos'][0], 3), round(x['pos'][2], 3), (x.get('next_name') or '').lower()) for x in got['traffic']['points']}
            res['checks'].append(('PASS' if a == b else 'FAIL', 'traffic points and next names: %d' % len(b)))
        # plain CollisionBoxes only: trigger roots with a box (e.g. a mission op's new go-to trigger) are not nav data
        def plain(lst):
            return [x for x in lst if not (x.get('type') or '').startswith('Trigger')]
        a = sorted((tuple(round(v, 2) for v in x['pos']), x.get('collisionflags')) for x in plain(W['blockers']))
        b = sorted((tuple(round(v, 2) for v in x['pos']), x.get('collisionflags')) for x in plain(got['blockers']))
        if a != b:
            res['checks'].append(('FAIL', 'CollisionBoxes differ: %d expected, %d built' % (len(a), len(b))))
        elif any(x.get('new') for x in W['blockers']) or any(o['op'] in ('add_navblock', 'retire_navblock') for o in ops if o['entry'] == e):
            res['checks'].append(('PASS', 'CollisionBoxes / NavBlocks: %d, positions and flags as edited' % len(b)))
        if any(c[0] == 'FAIL' for c in res['checks']):
            rep['result'] = 'FAIL'
        res['literal_linked'] = got.get('literal_linked')
        rep['blocks'].append(res)
    return rep
