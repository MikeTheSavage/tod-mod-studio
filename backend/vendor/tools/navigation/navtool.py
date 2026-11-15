"""TOD navigation data tool (GOG build): decode, check, draw and edit the NPC / traffic navigation networks.

  python navtool.py export <block> [-o nav.json]                 every nav entity of one block, world coordinates
  python navtool.py check  <block> [...] | --all [-o report.json] integrity checks (links, names, symmetry, components)
  python navtool.py image  <nav.json> -o map.png [--backdrop coll.glb] [--bbox x0 z0 x1 z1] [--px-per-m 2]
  python navtool.py gltf   <nav.json> -o nav.glb [--backdrop coll.glb]
  python navtool.py apply  <navedit.json> --out DIR [--deploy TESTGAME]   nav-level edits -> verified block + zip
  python navtool.py roundtrip <block> [...] | --all              export -> no-op apply -> same bytes; edit -> re-export diff

<block> is an archive entry name of blocks.naz (a bare file name is looked up), or a block file on disk (give
--entry, or "entry" in the edit file, with its archive name).

What is decoded (see docs/subsystem_navigation.md for the engine side):
  traffic   database_road_folder(Group) / database_junction_point(Group) folders holding database_traffic_point
            (NodeSpatial) points: NameOfNextPoint (link by name, resolved like FUN_006556E0: a descendant of the
            point's grandparent with that name), NameOfPointGroup (junction arm colour Green/Blue/Red/Yellow),
            Sub_Type (0 road, 1 junction IN, 2 junction OUT, 3 end, 4 spawn), Curve_Factor_Straight/Right/Left.
            Junction IN points link to every OUT (Sub_Type 2 or 4) of another colour in the same junction group.
            Each link becomes a section with turn type (FUN_006550F0), length and curve handle
            (length * Curve_Factor_<turn> * 0.13).
  peds      Pedestriansystem(Folder) > Folder > SignPost {connections list(Entity) #260}; undirected graph
            (the engine makes every connection mutual, FUN_00921360 / FUN_009212A0); Neighborhood(Node) circles.
  tracks    Track / Pathtype(Track) / AI_track(Track) with TrackPoint children in engine child order (sorted by
            'order', FUN_0088E8A0). Pathtype PathType 0 = an enemy GotoPath, else a patrol path (FUN_005D4190).
  blockers  CollisionBox entities (CollisionFlags #71; 32 = NavBlock: Navigator obstacle probes use mask 0x21).
  misc      interest_point, database_taxipoint, vehicle_teleport_safe_point, VehicleRepulsor, character
            placeholders with their GotoPath / patrol tracks.

navedit.json:
{ "block": "submap01_map02_lostoros_downtown.submap", ["entry": "..."],
  "ops": [
   {"op": "move",        "frag": F, "node": N, "pos": [x, y, z]}                world position of any point entity
   {"op": "link",        "frag": F, "a": N1, "b": N2}                           SignPost link, both sides
   {"op": "unlink",      "frag": F, "a": N1, "b": N2}
   {"op": "add_signpost","frag": F, "like": N, "pos": [..], "connect": [N...], "split": [N1, N2]}
                         new SignPost cloned from N (same parent folder); split = cut N1-N2 and connect both
   {"op": "remove_signpost", "frag": F, "node": N}                              unlink everywhere, then remove
   {"op": "set_next",    "frag": F, "node": N, "next": "name" | null}           traffic link; null = end point (Sub_Type 3)
   {"op": "add_traffic_point", "frag": F, "after": N, "name": "X1", "pos": [..]}  splice a road point after N
   {"op": "add_trackpoint", "frag": F, "track": T, "like": P, "pos": [..]}     appended (order = max + 1)
   {"op": "remove_trackpoint", "frag": F, "node": P}
   {"op": "add_navblock", "frag": F, "like": CB, "pos": [..], "size": [w, h, l], "orient": [x,y,z,w], "flags": 32}
   {"op": "set",         "frag": F, "node": N, "prop": "name or #index", "value": V}
  ] }
F = fragment record name or a unique substring; N = "0x00300781" or a name path inside the fragment.
Instead of "ops", "from_export": [original nav.json, edited nav.json] derives the ops from the differences
(moved points, changed connections / next names, signposts and track points marked "new": true with "like",
entries deleted from the edited file).
"""
import argparse, collections, copy, hashlib, json, math, os, struct, sys, zlib
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.environ.get('TOD_FW'), os.path.join(HERE, '..', 'fragment_writer'), os.path.join(HERE, '..', 'fw')):
    if cand and os.path.exists(os.path.join(cand, 'fragtool.py')):
        sys.path.insert(0, os.path.abspath(cand))
        break
import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft

T = None
def types():
    global T
    if T is None:
        T = ft.types()
    return T

# ------------------------------------------------------------------ entity type names (create records)
TP = 'database_traffic_point(NodeSpatial)'
ROAD = 'database_road_folder(Group)'
JUNC = 'database_junction_point(Group)'
SIGN = 'SignPost'
PEDSYS = 'Pedestriansystem(Folder)'
TRACK_TYPES = ('Track', 'Pathtype(Track)', 'AI_track(Track)')
MISC_TYPES = ('interest_point(NodeSpatial)', 'database_taxipoint(Node)', 'vehicle_teleport_safe_point(Node)',
              'VehicleRepulsor(Node)')
COLOURS = ('Green', 'Blue', 'Red', 'Yellow')
# FUN_006550F0: (from colour, to colour) -> 1 (right) / 2 (left); anything else (incl. opposite arms) 0 straight
TURN = {('Green', 'Yellow'): 1, ('Green', 'Red'): 2, ('Blue', 'Red'): 1, ('Blue', 'Yellow'): 2,
        ('Red', 'Green'): 1, ('Red', 'Blue'): 2, ('Yellow', 'Blue'): 1, ('Yellow', 'Green'): 2}
TURN_NAME = {0: 'straight', 1: 'right', 2: 'left'}
CURVE_HANDLE = 0.13            # DAT_009BE04C, section.dist = length * Curve_Factor * 0.13
SUBTYPE = {0: 'road', 1: 'junction_in', 2: 'junction_out', 3: 'end', 4: 'spawn'}
NAVBLOCK = 32


def is_point(ty):
    return ty == 'TrackPoint' or (ty or '').endswith('(TrackPoint)')


def is_collisionbox(ty):
    return ty == 'CollisionBox' or (ty or '').endswith('(CollisionBox)')


def hx(n):
    return '0x%08X' % n


def r6(v):
    return [round(float(x), 6) for x in v]


# ------------------------------------------------------------------ block loading
class BlockView:
    """All fragments of one block as FragDocs with owner transforms."""

    def __init__(self, block, entry=None):
        self.raw, self.entry, self.ext = ft.load_block_bytes(block, entry)
        self.block = tb.Block(self.raw, self.ext)
        self.frs, _ = ft.fragments(self.block)
        self.docs = {}
        self.owner = {}
        self.owner_desc = {}
        for k, nm in self.frs:
            self.docs[k] = fe.FragDoc(self.block.payloads[k], types(), nm)
        cache = {}
        for k, nm in self.frs:
            W, desc = ft.owner_chain(self.block, self.frs, k, types(), cache=cache)
            self.owner[k], self.owner_desc[k] = W, desc

    def name(self, k):
        return dict(self.frs)[k]


def child_order(doc):
    """Replay the record stream like the engine: 'order' (#5, node+0x12, signed 16-bit) and 'parent' (#7) insert a
    node into its parent's child list sorted by order (FUN_0088E8A0; equal order goes before the existing ones).
    Returns {parent: [children in engine order]} (parent 0 = the owning entity)."""
    order, parent, kids = {}, {}, collections.defaultdict(list)

    def attach(n, p):
        lst = kids[p]
        o = order.get(n, 0)
        if lst and order.get(lst[0], 0) < o:
            i = 0
            while i + 1 < len(lst) and order.get(lst[i + 1], 0) < o:
                i += 1
            lst.insert(i + 1, n)
        else:
            lst.insert(0, n)

    def detach(n):
        p = parent.get(n)
        if p is not None and n in kids[p]:
            kids[p].remove(n)

    for r in doc.records:
        if r.op != tf.SET:
            continue
        if r.prop == fe.P_ORDER:
            v = struct.unpack('<i', r.raw[:4])[0]
            v = ((v & 0xFFFF) ^ 0x8000) - 0x8000            # stored as a 16-bit short
            order[r.node] = v
            if r.node in parent:
                p = parent[r.node]; detach(r.node); attach(r.node, p)
        elif r.prop == fe.P_PARENT:
            v = struct.unpack('<I', r.raw[:4])[0]
            p = 0 if v in (0, 0xFFFFFFFF) else v
            detach(r.node)
            parent[r.node] = p
            attach(r.node, p)
    return kids


# ------------------------------------------------------------------ export
def export(bv):
    Tt = types()
    out = dict(block=bv.entry, fragments=[], traffic=dict(folders=[], points=[], sections=[]),
               peds=dict(systems=[], signposts=[], neighborhoods=[]), tracks=[], blockers=[], misc=[],
               placeholders=[])
    for k, nm in bv.frs:
        doc = bv.docs[k]
        ids = doc.created_ids()
        if not ids:
            continue
        typ = {n: doc.type_of(n) for n in ids}
        interesting = any(t in (TP, ROAD, JUNC, SIGN, PEDSYS) or t in TRACK_TYPES or is_point(t) or
                          is_collisionbox(t) or t in MISC_TYPES or (t or '').startswith('Neighborhood(')
                          or (t or '').startswith('character_placeholder') for t in typ.values())
        if not interesting:
            continue
        own = bv.owner[k]
        W = {}
        def world(n):
            if n not in W:
                W[n] = doc.world(n, own)
            return W[n]
        kids = child_order(doc)
        par = {n: (doc.get(n, fe.P_PARENT) or 0) for n in ids}
        nm_of = {n: doc.get(n, fe.P_NAME) for n in ids}
        fshort = nm.replace('\\', '/').split('/')[-1]
        out['fragments'].append(dict(record=k, name=nm, owner_chain=bv.owner_desc[k],
                                     owner_pos=r6(own[0]), entities=len(ids)))
        base = dict(frag=fshort)

        def ent(n, **kw):
            d = dict(base, node=hx(n), type=typ[n], name=nm_of[n], path=doc.path_of(n),
                     pos=r6(world(n)[0]))
            d.update(kw)
            return d

        def flags(n):
            return doc.get(n, 'flags') or 0

        def disabled_chain(n):
            seen = set()
            while n and n not in seen:
                seen.add(n)
                if flags(n) & 1:
                    return True
                n = par.get(n, 0)
            return False

        # ---------------- traffic
        by_name = collections.defaultdict(list)
        for n in ids:
            if nm_of[n] is not None:
                by_name[nm_of[n].lower()].append(n)

        def descendants_named(root, name):
            hits = []
            for n in by_name.get((name or '').lower(), []):
                p, seen = par.get(n, 0), set()
                while p and p not in seen:
                    if p == root:
                        hits.append(n); break
                    seen.add(p); p = par.get(p, 0)
                if root == 0 and n not in hits:
                    hits.append(n)
            return hits

        for n in ids:
            if typ[n] in (ROAD, JUNC):
                out['traffic']['folders'].append(ent(
                    n, kind='junction' if typ[n] == JUNC else 'road', flags=flags(n),
                    TrafficMaxDensity=doc.get(n, 'TrafficMaxDensity'), TrafficMaxSpeed=doc.get(n, 'TrafficMaxSpeed'),
                    TrafficAllowLargeVehicles=doc.get(n, 'TrafficAllowLargeVehicles'),
                    IgnoreJunctionAccess=doc.get(n, 'IgnoreJunctionAccess'), UseCustomCurve=doc.get(n, 'UseCustomCurve'),
                    CustomCurveValue=doc.get(n, 'CustomCurveValue')))
        tps = [n for n in ids if typ[n] == TP]
        point_rec = {}
        for n in tps:
            st = doc.get(n, 'Sub_Type') or 0
            p = par.get(n, 0)
            in_junction = typ.get(p) == JUNC
            eff = st
            notes = []
            if st in (1, 2) and not in_junction:
                eff = 3; notes.append('junction point outside a junction group -> end')
            nxt_name = doc.get(n, 'NameOfNextPoint')
            nexts, status = [], 'ok'
            gp = par.get(p, 0)
            if eff == 1:
                grp = doc.get(n, 'NameOfPointGroup')
                for s in kids.get(p, []):
                    if typ.get(s) == TP and s != n and (doc.get(s, 'Sub_Type') or 0) in (2, 4) and \
                            (doc.get(s, 'NameOfPointGroup') or '') != (grp or ''):
                        nexts.append(s)
                status = 'junction' if nexts else 'junction_without_exit'
            elif eff != 3:
                hits = descendants_named(gp, nxt_name) if nxt_name else []
                hits = [h for h in hits if typ.get(h) == TP]
                if not hits:
                    eff = 3; status = 'missing_next' if nxt_name else 'no_next'
                    notes.append('next %r not found -> end' % nxt_name if nxt_name else 'no NameOfNextPoint -> end')
                else:
                    if len(hits) > 1:
                        status = 'ambiguous_next'
                        notes.append('%d points named %r; the engine picks one by its name hash table' % (len(hits), nxt_name))
                    nexts = [hits[0]]
            else:
                status = 'end'
            point_rec[n] = dict(eff=eff, nexts=nexts)
            out['traffic']['points'].append(ent(
                n, folder=nm_of.get(p), folder_node=hx(p) if p else None, junction=in_junction, flags=flags(n),
                Sub_Type=st, sub_type=SUBTYPE.get(st, st), effective_sub_type=SUBTYPE.get(eff, eff),
                group=doc.get(n, 'NameOfPointGroup'), next_name=nxt_name, next=[hx(x) for x in nexts], status=status,
                curve=[doc.get(n, 'Curve_Factor_Straight'), doc.get(n, 'Curve_Factor_Right'),
                       doc.get(n, 'Curve_Factor_Left')], notes=notes))
        prev = collections.defaultdict(list)
        for n in tps:
            for m in point_rec[n]['nexts']:
                prev[m].append(n)
                a, b = world(n)[0], world(m)[0]
                L = math.dist(a, b)
                if st_from_out(doc, n):
                    turn = 0
                else:
                    turn = TURN.get((doc.get(n, 'NameOfPointGroup'), doc.get(m, 'NameOfPointGroup')), 0)
                cf = [doc.get(n, 'Curve_Factor_Straight'), doc.get(n, 'Curve_Factor_Right'),
                      doc.get(n, 'Curve_Factor_Left')][turn]
                cf = 2.5 if cf is None else cf
                out['traffic']['sections'].append(dict(base, frm=hx(n), to=hx(m), turn=TURN_NAME[turn],
                                                       length=round(L, 4), curve_factor=cf,
                                                       handle=round(L * cf * CURVE_HANDLE, 4)))
        for p in out['traffic']['points']:
            if p['frag'] == fshort:
                p['prev'] = [hx(x) for x in prev.get(int(p['node'], 16), [])]

        # ---------------- pedestrians
        for n in ids:
            t = typ[n]
            if t == PEDSYS:
                groups = []
                for g in kids.get(n, []):
                    groups.append(dict(node=hx(g), name=nm_of.get(g), flags=flags(g),
                                       points=[hx(c) for c in kids.get(g, [])]))
                out['peds']['systems'].append(ent(n, flags=flags(n), groups=groups))
            elif t == SIGN:
                con = doc.get(n, 'connections') or []
                out['peds']['signposts'].append(ent(n, folder=nm_of.get(par.get(n, 0)), flags=flags(n),
                                                    connections=[hx(c) for c in con]))
            elif (t or '').startswith('Neighborhood('):
                d = ent(n, flags=flags(n), disabled_at_load=disabled_chain(n))
                for key in ('NeighborhoodID', 'BorderDistance', 'PoliceResponceChance', 'PedestrianDensity',
                            'SupMapNeighborhood'):
                    d[key] = doc.get(n, key)
                d['groups'] = [[doc.get(n, 'PedestrianGroup_%02d' % i), doc.get(n, 'PedestrianGroup_%02d_Minimum' % i),
                                doc.get(n, 'PedestrianGroup_%02d_Maxmium' % i)] for i in range(1, 7)]
                out['peds']['neighborhoods'].append(d)

        # ---------------- tracks
        for n in ids:
            t = typ[n]
            if t not in TRACK_TYPES:
                continue
            pts = [c for c in kids.get(n, []) if is_point(typ.get(c))]
            kind = 'track'
            if t == 'Pathtype(Track)':
                kind = 'goto' if (doc.get(n, 'PathType') or 0) == 0 else 'patrol'
            elif t == 'AI_track(Track)':
                kind = 'ai_track'
            elif any(typ.get(c) == 'AI_track_point(TrackPoint)' for c in pts):
                kind = 'vehicle'
            owners = [hx(s) for s in kids.get(par.get(n, 0), []) if (typ.get(s) or '').startswith('character_placeholder')]
            pl = []
            for c in pts:
                d = dict(node=hx(c), type=typ[c], name=nm_of.get(c), order=doc.get(c, fe.P_ORDER), flags=flags(c),
                         pos=r6(world(c)[0]))
                for key in ('speed', 'target_speed', 'slag_dist', 'Slide_time', 'Stay_In_Vehicle', 'Pause_point',
                            'Is_Here_Distance', 'movetype'):
                    v = doc.get(c, key)
                    if v is not None:
                        d[key] = v
                pl.append(d)
            out['tracks'].append(ent(n, kind=kind, flags=flags(n), PathType=doc.get(n, 'PathType'),
                                     looping=doc.get(n, 'looping'), pingpong=doc.get(n, 'pingpong'),
                                     spline=doc.get(n, 'spline'), placeholders=owners, points=pl,
                                     other_children=[hx(c) for c in kids.get(n, []) if c not in pts]))

        # ---------------- blockers and misc
        for n in ids:
            t = typ[n]
            if is_collisionbox(t):
                cf = doc.get(n, 'CollisionFlags') or 0
                Wn = world(n)
                out['blockers'].append(ent(n, collisionflags=cf, navblock=bool(cf & NAVBLOCK), flags=flags(n),
                                           orient=r6(fe.qconj(Wn[1])),
                                           size=[doc.get(n, 'width'), doc.get(n, 'height'), doc.get(n, 'length')]))
            elif t in MISC_TYPES:
                d = ent(n, flags=flags(n))
                for key in ('InterestPointType', 'InterestPointRadius', 'boundradius', 'MapID', 'SubMapID',
                            'MenuDescription', 'LifeTime', 'ImpulseMagnitude'):
                    v = doc.get(n, key)
                    if v is not None:
                        d[key] = v
                out['misc'].append(d)
            elif (t or '').startswith('character_placeholder'):
                d = ent(n, flags=flags(n))
                for key in ('Model', 'AISubType', 'FactionID', 'Goto_Movement', 'Always_Complete_Goto',
                            'GotoPath_start_at', 'GotopointDamage_mod', 'DesiredRange', 'CustomDesiredRange',
                            'DontHunt', 'PedestrianGroup'):
                    v = doc.get(n, key)
                    if v is not None:
                        d[key] = hx(v) if key == 'GotoPath_start_at' and isinstance(v, int) and v else v
                sib = [s for s in kids.get(par.get(n, 0), []) if typ.get(s) == 'Pathtype(Track)']
                d['goto_tracks'] = [hx(s) for s in sib if (doc.get(s, 'PathType') or 0) == 0]
                d['patrol_tracks'] = [hx(s) for s in sib if (doc.get(s, 'PathType') or 0) != 0]
                out['placeholders'].append(d)
    assign_neighborhoods(out)
    out['summary'] = summary(out)
    return out


def st_from_out(doc, n):
    return (doc.get(n, 'Sub_Type') or 0) == 2


def assign_neighborhoods(out):
    """FUN_007537D0: nearest enabled Neighborhood (NeighborhoodID != 17) whose BorderDistance (3-D) contains the
    point, else the DefaultNeighborhood (overdose.main). Capacity (TotalMaximum / CurrentlyInUseList) is runtime."""
    hoods = [h for h in out['peds']['neighborhoods'] if not h['disabled_at_load'] and h.get('NeighborhoodID') != 17]
    for s in out['peds']['signposts']:
        best, bd = None, 1e30
        for h in hoods:
            d = math.dist(s['pos'], h['pos'])
            if d < (h.get('BorderDistance') or 50.0) and d < bd:
                best, bd = h, d
        s['neighborhood'] = best['name'] if best else 'DefaultNeighborhood'


def components(nodes, edges):
    parent = {n: n for n in nodes}
    def f(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = f(a), f(b)
            if ra != rb: parent[ra] = rb
    c = collections.Counter(f(n) for n in nodes)
    return sorted(c.values(), reverse=True)


def summary(out):
    s = {}
    tp = out['traffic']['points']
    s['traffic_points'] = len(tp)
    s['traffic_folders'] = collections.Counter(f['kind'] for f in out['traffic']['folders'])
    s['traffic_sub_types'] = collections.Counter(p['sub_type'] for p in tp)
    s['traffic_status'] = collections.Counter(p['status'] for p in tp)
    s['traffic_sections'] = len(out['traffic']['sections'])
    s['traffic_turns'] = collections.Counter(x['turn'] for x in out['traffic']['sections'])
    sp = out['peds']['signposts']
    key = lambda d: (d['frag'], d['node'])
    allsp = {key(d) for d in sp}
    edges = set()
    asym = dangling = selfl = 0
    con = {key(d): {(d['frag'], c) for c in d['connections']} for d in sp}
    for a, cs in con.items():
        for b in cs:
            if b not in allsp:
                dangling += 1; continue
            if b == a: selfl += 1
            if a not in con.get(b, ()): asym += 1
            edges.add(tuple(sorted((a, b))))
    s['signposts'] = len(sp)
    s['signpost_links'] = len(edges)
    s['signpost_asymmetric'] = asym
    s['signpost_dangling'] = dangling
    s['signpost_self_links'] = selfl
    s['signpost_degree'] = dict(sorted(collections.Counter(len(d['connections']) for d in sp).items()))
    comp = components(allsp, edges)
    s['signpost_components'] = len(comp)
    s['signpost_component_sizes'] = comp[:12]
    s['neighborhoods'] = len(out['peds']['neighborhoods'])
    s['neighborhood_assignment'] = collections.Counter(d.get('neighborhood') for d in sp)
    s['tracks'] = collections.Counter(t['kind'] for t in out['tracks'])
    s['track_points'] = sum(len(t['points']) for t in out['tracks'])
    s['blockers'] = len(out['blockers'])
    s['navblock_boxes'] = sum(1 for b in out['blockers'] if b['navblock'])
    s['misc'] = collections.Counter(m['type'] for m in out['misc'])
    s['placeholders'] = len(out['placeholders'])
    s['placeholders_with_goto'] = sum(1 for p in out['placeholders'] if p['goto_tracks'])
    s['placeholders_with_patrol'] = sum(1 for p in out['placeholders'] if p['patrol_tracks'])
    return {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in s.items()}


def cmd_export(a):
    bv = BlockView(a.block, a.entry)
    out = export(bv)
    text = json.dumps(out, indent=1, default=str)
    if a.o:
        open(a.o, 'w', encoding='utf-8').write(text)
        print('wrote %s' % a.o)
        print(json.dumps(out['summary'], indent=1, default=str))
    else:
        print(text)


# ------------------------------------------------------------------ check (all blocks)
def check_block(entry):
    bv = BlockView(entry)
    out = export(bv)
    s = out['summary']
    issues = []
    for p in out['traffic']['points']:
        if p['status'] in ('missing_next', 'ambiguous_next', 'junction_without_exit'):
            issues.append(dict(kind='traffic_' + p['status'], frag=p['frag'], node=p['node'], name=p['name'],
                               next_name=p['next_name']))
        if p['notes'] and p['status'] not in ('missing_next', 'ambiguous_next'):
            issues.append(dict(kind='traffic_note', frag=p['frag'], node=p['node'], name=p['name'], notes=p['notes']))
    dup = collections.Counter((p['frag'], (p['name'] or '').lower()) for p in out['traffic']['points'])
    for (fr, nm), c in dup.items():
        if c > 1:
            issues.append(dict(kind='traffic_duplicate_name', frag=fr, name=nm, count=c))
    for d in out['peds']['signposts']:
        if not d['connections']:
            issues.append(dict(kind='signpost_isolated', frag=d['frag'], node=d['node']))
    for t in out['tracks']:
        if not t['points'] and t['kind'] in ('goto', 'patrol'):
            issues.append(dict(kind='empty_path', frag=t['frag'], node=t['node'], name=t['name']))
    return out, s, issues


def cmd_check(a):
    try:
        import lowprio  # noqa
    except Exception:
        pass
    arch = ft.archive()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS) if a.all else \
        [ft.resolve_entry(b) if not os.path.exists(b) else b for b in a.blocks]
    rep = dict(blocks={}, totals=collections.Counter(), issues=collections.Counter())
    for n in names:
        out, s, issues = check_block(n)
        if not (s['traffic_points'] or s['signposts'] or s['track_points'] or s['navblock_boxes']):
            continue
        rep['blocks'][n.split('/')[-1]] = dict(summary=s, issues=issues)
        for k in ('traffic_points', 'traffic_sections', 'signposts', 'signpost_links', 'signpost_asymmetric',
                  'signpost_dangling', 'track_points', 'blockers', 'navblock_boxes', 'placeholders',
                  'placeholders_with_goto', 'placeholders_with_patrol'):
            rep['totals'][k] += s[k]
        for kk, v in s['tracks'].items():
            rep['totals']['tracks_' + kk] += v
        for i in issues:
            rep['issues'][i['kind']] += 1
    rep['totals'] = dict(rep['totals']); rep['issues'] = dict(rep['issues'])
    rep['blocks_with_nav'] = len(rep['blocks'])
    text = json.dumps(rep, indent=1, default=str)
    if a.o:
        open(a.o, 'w', encoding='utf-8').write(text)
    print(json.dumps(dict(blocks_with_nav=rep['blocks_with_nav'], totals=rep['totals'], issues=rep['issues']), indent=1))


# ------------------------------------------------------------------ geometry backdrop (collision / render glb)
def read_glb_tris(path, max_tris=None):
    """Positions (TOD coordinates: glb z negated back) and triangle index lists of every mesh in a glb."""
    d = open(path, 'rb').read()
    magic, ver, length = struct.unpack_from('<III', d, 0)
    jl, jt = struct.unpack_from('<II', d, 12)
    js = json.loads(d[20:20 + jl])
    bo = 20 + jl
    bl, bt = struct.unpack_from('<II', d, bo)
    binc = d[bo + 8: bo + 8 + bl]
    def acc(i):
        A = js['accessors'][i]; V = js['bufferViews'][A['bufferView']]
        off = V.get('byteOffset', 0) + A.get('byteOffset', 0)
        n = A['count']
        if A['type'] == 'VEC3':
            return [struct.unpack_from('<3f', binc, off + 12 * j) for j in range(n)]
        fmt = {5125: 'I', 5123: 'H', 5121: 'B'}[A['componentType']]
        sz = struct.calcsize(fmt)
        return list(struct.unpack_from('<%d%s' % (n, fmt), binc, off))
    out = []
    for m in js['meshes']:
        for p in m['primitives']:
            P = [(x, y, -z) for x, y, z in acc(p['attributes']['POSITION'])]
            I = acc(p['indices']) if 'indices' in p else list(range(len(P)))
            out.append((m.get('name', ''), P, I))
    return out


# ------------------------------------------------------------------ image
LAYER_COLOURS = dict(road=(40, 90, 230), junction=(0, 190, 220), spawn=(0, 160, 0), end=(200, 0, 0),
                     sign=(30, 150, 50), hood=(150, 110, 200), goto=(230, 120, 0), patrol=(220, 30, 160),
                     vehicle=(140, 70, 20), track=(120, 120, 120), navblock=(230, 0, 230), solid=(120, 0, 0))


def cmd_image(a):
    from PIL import Image, ImageDraw
    nav = json.load(open(a.nav, encoding='utf-8'))
    pts = [p['pos'] for p in nav['traffic']['points']] + [s['pos'] for s in nav['peds']['signposts']] + \
          [q['pos'] for t in nav['tracks'] for q in t['points']]
    back = read_glb_tris(a.backdrop) if a.backdrop else []
    if a.bbox:
        x0, z0, x1, z1 = a.bbox
    else:
        xs = [p[0] for p in pts]; zs = [p[2] for p in pts]
        if back:
            for _, P, _ in back:
                xs += [p[0] for p in P[::7]]; zs += [p[2] for p in P[::7]]
        x0, x1, z0, z1 = min(xs) - 10, max(xs) + 10, min(zs) - 10, max(zs) + 10
    s = a.px_per_m
    Wd, Ht = int((x1 - x0) * s) + 1, int((z1 - z0) * s) + 1
    img = Image.new('RGB', (Wd, Ht), (250, 250, 248))
    dr = ImageDraw.Draw(img)
    def P(p):                       # top view: x to the right, z up (north up)
        return ((p[0] - x0) * s, (z1 - p[2]) * s)
    if back:
        ys = [p[1] for _, Pp, _ in back for p in Pp]
        ylo, yhi = (min(ys), max(ys)) if ys else (0, 1)
        tris = []
        for name, Pp, I in back:
            for i in range(0, len(I) - 2, 3):
                A, B, C = Pp[I[i]], Pp[I[i + 1]], Pp[I[i + 2]]
                ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
                vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
                ny = uz * vx - ux * vz
                nl = math.sqrt((uy * vz - uz * vy) ** 2 + ny ** 2 + (ux * vy - uy * vx) ** 2) or 1
                h = max(A[1], B[1], C[1])
                tris.append((h, abs(ny) / nl, (A, B, C)))
        tris.sort(key=lambda t: t[0])
        for h, up, (A, B, C) in tris:
            t = (h - ylo) / ((yhi - ylo) or 1)
            g = int(205 - 70 * t) if up > 0.5 else int(150 - 60 * t)
            dr.polygon([P(A), P(B), P(C)], fill=(g, g, g + 6))
    for h in nav['peds']['neighborhoods']:
        if h['disabled_at_load']:
            continue
        r = (h.get('BorderDistance') or 0) * s
        c = P(h['pos'])
        dr.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=LAYER_COLOURS['hood'], width=1)
    sp = {(d['frag'], d['node']): d for d in nav['peds']['signposts']}
    done = set()
    for k, d in sp.items():
        for c in d['connections']:
            b = sp.get((d['frag'], c))
            if not b: continue
            e = tuple(sorted((k, (d['frag'], c))))
            if e in done: continue
            done.add(e)
            dr.line([P(d['pos']), P(b['pos'])], fill=LAYER_COLOURS['sign'], width=max(1, int(s * 0.4)))
    for d in sp.values():
        c = P(d['pos']); r = max(1.5, s * 0.6)
        dr.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=LAYER_COLOURS['sign'])
    tp = {(p['frag'], p['node']): p for p in nav['traffic']['points']}
    for x in nav['traffic']['sections']:
        A, B = tp[(x['frag'], x['frm'])], tp[(x['frag'], x['to'])]
        col = LAYER_COLOURS['junction'] if A['effective_sub_type'] == 'junction_in' else LAYER_COLOURS['road']
        pa, pb = P(A['pos']), P(B['pos'])
        dr.line([pa, pb], fill=col, width=max(1, int(s * 0.6)))
        L = math.dist(pa, pb)
        if L > 6:                     # arrow head at 70 %
            ux, uy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
            m = (pa[0] + 0.7 * (pb[0] - pa[0]), pa[1] + 0.7 * (pb[1] - pa[1]))
            hsz = max(3, s * 1.5)
            dr.polygon([(m[0] + ux * hsz, m[1] + uy * hsz), (m[0] - uy * hsz * 0.6, m[1] + ux * hsz * 0.6),
                        (m[0] + uy * hsz * 0.6, m[1] - ux * hsz * 0.6)], fill=col)
    for p in tp.values():
        col = {'spawn': LAYER_COLOURS['spawn'], 'end': LAYER_COLOURS['end']}.get(p['effective_sub_type'])
        if col:
            c = P(p['pos']); r = max(2, s * 1.2)
            dr.rectangle([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=col, width=2)
    for t in nav['tracks']:
        col = LAYER_COLOURS.get(t['kind'], LAYER_COLOURS['track'])
        q = [P(x['pos']) for x in t['points']]
        if len(q) > 1:
            dr.line(q, fill=col, width=max(1, int(s * 0.7)))
        for c in q:
            r = max(1.5, s * 0.5)
            dr.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=col)
    for b in nav['blockers']:
        if not (b['navblock'] or a.all_boxes):
            continue
        w, h, l = [(v or 0) for v in b['size']]
        q = b['orient']
        corners = []
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            v = fe.qrot(fe.qconj(fe.qnorm(q)), (sx * w / 2, 0, sz * l / 2))
            corners.append(P((b['pos'][0] + v[0], 0, b['pos'][2] + v[2])))
        dr.polygon(corners, outline=LAYER_COLOURS['navblock' if b['navblock'] else 'solid'], width=2)
    if a.label:
        for p in tp.values():
            dr.text(P(p['pos']), p['name'] or '', fill=(20, 40, 120))
    img.save(a.o)
    print('wrote %s (%dx%d px, x %.1f..%.1f, z %.1f..%.1f, %.2f px/m)' % (a.o, Wd, Ht, x0, x1, z0, z1, s))


# ------------------------------------------------------------------ glTF
class GlbWriter:
    def __init__(self):
        self.bin = bytearray(); self.js = dict(asset=dict(version='2.0', generator='navtool.py'), scenes=[dict(nodes=[])],
                                                scene=0, nodes=[], meshes=[], materials=[], accessors=[],
                                                bufferViews=[], buffers=[])

    def _view(self, data, target):
        while len(self.bin) % 4: self.bin += b'\0'
        off = len(self.bin); self.bin += data
        self.js['bufferViews'].append(dict(buffer=0, byteOffset=off, byteLength=len(data), target=target))
        return len(self.js['bufferViews']) - 1

    def mesh(self, name, pos, idx, mode, rgba):
        if not pos or not idx: return
        gp = [(x, y, -z) for x, y, z in pos]            # TOD left-handed y-up -> glTF: negate z (project rule)
        pv = self._view(struct.pack('<%df' % (3 * len(gp)), *[c for p in gp for c in p]), 34962)
        mn = [min(p[i] for p in gp) for i in range(3)]; mx = [max(p[i] for p in gp) for i in range(3)]
        self.js['accessors'].append(dict(bufferView=pv, componentType=5126, count=len(gp), type='VEC3', min=mn, max=mx))
        pa = len(self.js['accessors']) - 1
        iv = self._view(struct.pack('<%dI' % len(idx), *idx), 34963)
        self.js['accessors'].append(dict(bufferView=iv, componentType=5125, count=len(idx), type='SCALAR'))
        ia = len(self.js['accessors']) - 1
        self.js['materials'].append(dict(name=name, pbrMetallicRoughness=dict(baseColorFactor=list(rgba), metallicFactor=0.0,
                                                                              roughnessFactor=1.0),
                                         alphaMode='BLEND' if rgba[3] < 1 else 'OPAQUE', doubleSided=True))
        self.js['meshes'].append(dict(name=name, primitives=[dict(attributes=dict(POSITION=pa), indices=ia, mode=mode,
                                                                  material=len(self.js['materials']) - 1)]))
        self.js['nodes'].append(dict(name=name, mesh=len(self.js['meshes']) - 1))
        self.js['scenes'][0]['nodes'].append(len(self.js['nodes']) - 1)

    def write(self, path):
        while len(self.bin) % 4: self.bin += b'\0'
        self.js['buffers'] = [dict(byteLength=len(self.bin))]
        j = json.dumps(self.js, separators=(',', ':')).encode()
        while len(j) % 4: j += b' '
        out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(self.bin))
        out += struct.pack('<II', len(j), 0x4E4F534A) + j + struct.pack('<II', len(self.bin), 0x004E4942) + self.bin
        open(path, 'wb').write(out)


def cmd_gltf(a):
    nav = json.load(open(a.nav, encoding='utf-8'))
    G = GlbWriter()
    lift = 0.3
    def up(p): return (p[0], p[1] + lift, p[2])
    def lines(name, segs, rgba):
        pos, idx = [], []
        for p, q in segs:
            idx += [len(pos), len(pos) + 1]; pos += [up(p), up(q)]
        G.mesh(name, pos, idx, 1, rgba)
    tp = {(p['frag'], p['node']): p for p in nav['traffic']['points']}
    road = [(tp[(x['frag'], x['frm'])]['pos'], tp[(x['frag'], x['to'])]['pos']) for x in nav['traffic']['sections']
            if tp[(x['frag'], x['frm'])]['effective_sub_type'] != 'junction_in']
    junc = [(tp[(x['frag'], x['frm'])]['pos'], tp[(x['frag'], x['to'])]['pos']) for x in nav['traffic']['sections']
            if tp[(x['frag'], x['frm'])]['effective_sub_type'] == 'junction_in']
    arrows = []
    for p, q in road + junc:
        L = math.dist(p, q)
        if L < 1: continue
        u = [(q[i] - p[i]) / L for i in range(3)]
        m = [p[i] + 0.7 * (q[i] - p[i]) for i in range(3)]
        side = (-u[2], 0, u[0])
        t = [m[i] - 1.2 * u[i] for i in range(3)]
        arrows += [(m, [t[i] + 0.6 * side[i] for i in range(3)]), (m, [t[i] - 0.6 * side[i] for i in range(3)])]
    lines('traffic_road', road, (0.16, 0.35, 0.9, 1)); lines('traffic_junction', junc, (0, 0.75, 0.86, 1))
    lines('traffic_arrows', arrows, (0.1, 0.2, 0.6, 1))
    sp = {(d['frag'], d['node']): d for d in nav['peds']['signposts']}
    segs, done = [], set()
    for k, d in sp.items():
        for c in d['connections']:
            b = sp.get((d['frag'], c))
            e = tuple(sorted((k, (d['frag'], c))))
            if b and e not in done:
                done.add(e); segs.append((d['pos'], b['pos']))
    lines('pedestrian_signposts', segs, (0.12, 0.6, 0.2, 1))
    for kind, col in (('goto', (0.9, 0.47, 0, 1)), ('patrol', (0.86, 0.12, 0.63, 1)), ('vehicle', (0.55, 0.27, 0.08, 1)),
                      ('ai_track', (0.55, 0.27, 0.08, 1)), ('track', (0.5, 0.5, 0.5, 1))):
        segs = []
        for t in nav['tracks']:
            if t['kind'] == kind:
                q = [x['pos'] for x in t['points']]
                segs += list(zip(q, q[1:]))
        lines('tracks_' + kind, segs, col)
    pos, idx = [], []
    for h in nav['peds']['neighborhoods']:
        if h['disabled_at_load']: continue
        r = h.get('BorderDistance') or 0
        base = len(pos)
        for i in range(48):
            ang = 2 * math.pi * i / 48
            pos.append((h['pos'][0] + r * math.cos(ang), h['pos'][1], h['pos'][2] + r * math.sin(ang)))
            idx += [base + i, base + (i + 1) % 48]
    G.mesh('neighborhoods', pos, idx, 1, (0.6, 0.45, 0.8, 1))
    pos, idx = [], []
    for b in nav['blockers']:
        if not b['navblock']: continue
        w, h, l = [(v or 0) for v in b['size']]
        q = fe.qconj(fe.qnorm(b['orient']))
        base = len(pos)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    v = fe.qrot(q, (sx * w / 2, sy * h / 2, sz * l / 2))
                    pos.append(tuple(b['pos'][i] + v[i] for i in range(3)))
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            idx += [base + f[0], base + f[1], base + f[2], base + f[0], base + f[2], base + f[3]]
    G.mesh('navblock_boxes', pos, idx, 4, (0.9, 0, 0.9, 0.45))
    if a.backdrop:
        P, I = [], []
        for name, Pp, Ii in read_glb_tris(a.backdrop):
            o = len(P); P += Pp; I += [o + i for i in Ii]
        G.mesh('backdrop', P, I, 4, (0.72, 0.72, 0.74, 1))
    G.write(a.o)
    print('wrote %s (%d meshes)' % (a.o, len(G.js['meshes'])))


# ------------------------------------------------------------------ apply (edits)
class Editor:
    """Nav-level edits on top of the fragment writer's FragDoc; records the 'intended' list fragtool verifies."""

    def __init__(self, raw, ext):
        self.raw, self.ext = raw, ext
        self.b = tb.Block(raw, ext)
        self.frs, _ = ft.fragments(self.b)
        self.docs, self.intended, self.log = {}, [], []
        self.block_ids = set()
        for k, nm in self.frs:
            for r in tf.Fragment(self.b.payloads[k], types()).records:
                self.block_ids.add(r.node)
        self.owner_cache = {}

    def doc(self, sub):
        k, nm = ft.pick_fragment(self.frs, sub)
        if k not in self.docs:
            d = fe.FragDoc(self.b.payloads[k], types(), nm)
            d.used_ids = self.block_ids
            d.owner, d.owner_desc = ft.owner_chain(self.b, self.frs, k, types(), cache=self.owner_cache)
            self.docs[k] = d
        return k, self.docs[k]

    def _set(self, k, d, n, prop, value):
        if d.set_prop(n, prop, value):
            self.intended.append(dict(k=k, kind='set', node=n, prop=types().index(prop)))

    def connections(self, d, n):
        return list(d.get(n, 'connections') or [])

    def place(self, d, n, pos, orient=None):
        """World position (and optional world orientation) -> parent-relative records. Without an orientation only
        'pos' is written, so the entity's orient record stays byte-identical."""
        if orient is not None:
            d.move(n, pos, orient, 'world', d.owner)
            return
        par = d.get(n, fe.P_PARENT) or 0
        PW = d.world(par, d.owner) if par else d.owner
        L = fe.compose(fe.inverse(PW), (tuple(pos), (0.0, 0.0, 0.0, 1.0)))
        d.set_prop(n, fe.P_POS, [tf.f32(x) + 0.0 for x in L[0]])

    def op_move(self, o):
        k, d = self.doc(o['frag']); n = d.find(o['node'])
        self.place(d, n, o['pos'], o.get('orient'))
        self.intended.append(dict(k=k, kind='set', node=n, prop=fe.P_POS))
        if o.get('orient') is not None:
            self.intended.append(dict(k=k, kind='set', node=n, prop=fe.P_ORIENT))
        self.log.append(dict(op='move', node=hx(n), pos=o['pos']))

    def _need_sign(self, d, n):
        if d.type_of(n) != SIGN:
            raise ft.Fail('%s is a %s, not a SignPost' % (hx(n), d.type_of(n)))

    def op_link(self, o, on=True):
        k, d = self.doc(o['frag']); A, B = d.find(o['a']), d.find(o['b'])
        self._need_sign(d, A); self._need_sign(d, B)
        if A == B: raise ft.Fail('self link')
        for x, y in ((A, B), (B, A)):
            c = self.connections(d, x)
            if on and y not in c: c.append(y)
            if not on and y in c: c = [z for z in c if z != y]
            self._set(k, d, x, 'connections', c)
        self.log.append(dict(op='link' if on else 'unlink', a=hx(A), b=hx(B)))

    def op_unlink(self, o):
        self.op_link(o, on=False)

    def op_add_signpost(self, o):
        k, d = self.doc(o['frag']); src = d.find(o['like'])
        self._need_sign(d, src)
        root, m = d.clone(src, deep=False, parent=None, name=o.get('name'))
        conn = [d.find(x) for x in o.get('connect', [])]
        if o.get('split'):
            A, B = [d.find(x) for x in o['split']]
            for x, y in ((A, B), (B, A)):
                c = [z for z in self.connections(d, x) if z != y]
                self._set(k, d, x, 'connections', c)
            conn += [A, B]
        conn = list(dict.fromkeys(conn))
        d.set_prop(root, 'connections', conn, note=False)
        for x in conn:
            c = self.connections(d, x)
            if root not in c:
                self._set(k, d, x, 'connections', c + [root])
        self.place(d, root, o['pos'])
        self.intended.append(dict(k=k, kind='clone', src=src, root=root, map=m, sets={types().index('connections')},
                                  snapshot=d.last_clone_snapshot, src_types=d.last_clone_types))
        self.log.append(dict(op='add_signpost', new=hx(root), like=hx(src), connections=[hx(x) for x in conn], pos=o['pos']))
        return root

    def op_remove_signpost(self, o):
        k, d = self.doc(o['frag']); n = d.find(o['node'])
        self._need_sign(d, n)
        for x in d.created_ids():
            if x != n and d.type_of(x) == SIGN:
                c = self.connections(d, x)
                if n in c:
                    self._set(k, d, x, 'connections', [z for z in c if z != n])
        d.remove(n, deep=False)
        self.intended.append(dict(k=k, kind='remove', nodes={n}))
        self.log.append(dict(op='remove_signpost', node=hx(n)))

    def op_set_next(self, o):
        k, d = self.doc(o['frag']); n = d.find(o['node'])
        if d.type_of(n) != TP: raise ft.Fail('%s is not a traffic point' % hx(n))
        if o['next'] is None:
            self._set(k, d, n, 'NameOfNextPoint', '')
            self._set(k, d, n, 'Sub_Type', 3)
        else:
            self._set(k, d, n, 'NameOfNextPoint', o['next'])
        self.log.append(dict(op='set_next', node=hx(n), next=o['next']))

    def op_add_traffic_point(self, o):
        k, d = self.doc(o['frag']); A = d.find(o['after'])
        if d.type_of(A) != TP: raise ft.Fail('%s is not a traffic point' % hx(A))
        names = {(d.get(x, fe.P_NAME) or '').lower() for x in d.created_ids()}
        if o['name'].lower() in names: raise ft.Fail('name %r already used in %s' % (o['name'], d.name))
        old_next = d.get(A, 'NameOfNextPoint')
        root, m = d.clone(A, deep=False, parent=None, name=o['name'])
        sets = {}
        if (d.get(root, 'Sub_Type') or 0) != 0:
            sets['Sub_Type'] = 0
        sets['NameOfNextPoint'] = old_next or ''
        for p, v in sets.items():
            d.set_prop(root, p, v, note=False)
        self.place(d, root, o['pos'])
        self._set(k, d, A, 'NameOfNextPoint', o['name'])
        self.intended.append(dict(k=k, kind='clone', src=A, root=root, map=m, sets={types().index(p) for p in sets},
                                  snapshot=d.last_clone_snapshot, src_types=d.last_clone_types))
        self.log.append(dict(op='add_traffic_point', new=hx(root), after=hx(A), name=o['name'], next=old_next, pos=o['pos']))
        return root

    def op_add_trackpoint(self, o):
        k, d = self.doc(o['frag']); Tn = d.find(o['track']); src = d.find(o['like'])
        if not is_point(d.type_of(src)): raise ft.Fail('%s is not a track point' % hx(src))
        root, m = d.clone(src, deep=False, parent=Tn)
        self.place(d, root, o['pos'])
        self.intended.append(dict(k=k, kind='clone', src=src, root=root, map=m, sets=set(),
                                  snapshot=d.last_clone_snapshot, src_types=d.last_clone_types))
        self.log.append(dict(op='add_trackpoint', new=hx(root), track=hx(Tn), like=hx(src), pos=o['pos'],
                             order=d.get(root, fe.P_ORDER)))
        return root

    def op_remove_trackpoint(self, o):
        k, d = self.doc(o['frag']); n = d.find(o['node'])
        if not is_point(d.type_of(n)): raise ft.Fail('%s is not a track point' % hx(n))
        d.remove(n, deep=False)
        self.intended.append(dict(k=k, kind='remove', nodes={n}))
        self.log.append(dict(op='remove_trackpoint', node=hx(n)))

    def op_add_navblock(self, o):
        k, d = self.doc(o['frag']); src = d.find(o['like'])
        if not is_collisionbox(d.type_of(src)): raise ft.Fail('%s is not a CollisionBox' % hx(src))
        root, m = d.clone(src, deep=False, parent=None, name=o.get('name'))
        sets = {'CollisionFlags': o.get('flags', NAVBLOCK)}
        if 'size' in o:
            sets['width'], sets['height'], sets['length'] = [float(x) for x in o['size']]
        for p, v in sets.items():
            d.set_prop(root, p, v, note=False)
        self.place(d, root, o['pos'], o.get('orient'))
        self.intended.append(dict(k=k, kind='clone', src=src, root=root, map=m, sets={types().index(p) for p in sets},
                                  snapshot=d.last_clone_snapshot, src_types=d.last_clone_types))
        self.log.append(dict(op='add_navblock', new=hx(root), like=hx(src), pos=o['pos'], size=o.get('size'),
                             flags=sets['CollisionFlags']))
        return root

    def op_set(self, o):
        k, d = self.doc(o['frag']); n = d.find(o['node'])
        self._set(k, d, n, o['prop'], ft.value_in(d, o['prop'], o['value']))
        self.log.append(dict(op='set', node=hx(n), prop=o['prop'], value=o['value']))

    def run(self, ops):
        for o in ops:
            getattr(self, 'op_' + o['op'])(o)
        nb = tb.Block(self.raw, self.ext)
        for k, d in self.docs.items():
            nb.payloads[k] = d.payload()
        return nb


def ops_from_export(orig, edited):
    """Nav ops from the differences of two nav.json files (positions, signpost connections, traffic next names,
    new / deleted signposts and track points)."""
    ops = []
    def idx(lst): return {(d['frag'], d['node']): d for d in lst}
    def moved(a, b): return any(abs(x - y) > 1e-4 for x, y in zip(a['pos'], b['pos']))
    o_sp, e_sp = idx(orig['peds']['signposts']), idx(edited['peds']['signposts'])
    newmap = {}
    for key, d in e_sp.items():
        if d.get('new'):
            ops.append(dict(op='add_signpost', frag=d['frag'], like=d['like'], pos=d['pos'], connect=[],
                            _tmp=d['node']))
    for key, d in o_sp.items():
        if key not in e_sp:
            ops.append(dict(op='remove_signpost', frag=d['frag'], node=d['node']))
    for key, d in e_sp.items():
        if d.get('new') or key not in o_sp: continue
        if moved(o_sp[key], d):
            ops.append(dict(op='move', frag=d['frag'], node=d['node'], pos=d['pos']))
    edges_o = {tuple(sorted((k[1], c))) + (k[0],) for k, d in o_sp.items() for c in d['connections']}
    edges_e = {tuple(sorted((k[1], c))) + (k[0],) for k, d in e_sp.items() for c in d['connections']}
    for a, b, fr in sorted(edges_o - edges_e):
        if (fr, a) in e_sp and (fr, b) in e_sp:
            ops.append(dict(op='unlink', frag=fr, a=a, b=b))
    for a, b, fr in sorted(edges_e - edges_o):
        ops.append(dict(op='link', frag=fr, a=a, b=b))
    o_tp, e_tp = idx(orig['traffic']['points']), idx(edited['traffic']['points'])
    for key, d in e_tp.items():
        if key not in o_tp: continue
        if moved(o_tp[key], d):
            ops.append(dict(op='move', frag=d['frag'], node=d['node'], pos=d['pos']))
        if (d.get('next_name') or None) != (o_tp[key].get('next_name') or None):
            ops.append(dict(op='set_next', frag=d['frag'], node=d['node'], next=d.get('next_name')))
    o_tr, e_tr = idx(orig['tracks']), idx(edited['tracks'])
    for key, t in e_tr.items():
        if key not in o_tr: continue
        op_pts = {q['node']: q for q in o_tr[key]['points']}
        ep_pts = {q['node']: q for q in t['points']}
        for q in t['points']:
            if q.get('new'):
                ops.append(dict(op='add_trackpoint', frag=t['frag'], track=t['node'], like=q['like'], pos=q['pos']))
            elif q['node'] in op_pts and moved(op_pts[q['node']], q):
                ops.append(dict(op='move', frag=t['frag'], node=q['node'], pos=q['pos']))
        for n in op_pts:
            if n not in ep_pts:
                ops.append(dict(op='remove_trackpoint', frag=t['frag'], node=n))
    # new signposts: link ops that name the temporary node id are rewritten after creation (see apply)
    return ops


def apply_spec(spec, out_dir, deploy=None):
    Tt = types()
    os.makedirs(out_dir, exist_ok=True)
    raw, entry, ext = ft.load_block_bytes(spec['block'], spec.get('entry'))
    if os.path.exists(spec['block']) and not spec.get('entry'):
        raise ft.Fail('block given as a file needs "entry" (its archive name)')
    if 'from_export' in spec:
        a, b = spec['from_export']
        ops = ops_from_export(json.load(open(a, encoding='utf-8')), json.load(open(b, encoding='utf-8')))
    else:
        ops = spec['ops']
    rep = dict(spec={k: v for k, v in spec.items() if k != 'ops'}, ops=ops, entry=entry)
    r0 = ft.roundtrip_block(raw, ext, Tt)
    if r0['fail'] or not r0['block_identical']:
        raise ft.Fail('base block does not round-trip')
    ed = Editor(raw, ext)
    tmp = {}
    real = []
    for o in ops:
        o = dict(o)
        for key in ('a', 'b', 'node', 'like'):
            if o.get(key) in tmp: o[key] = tmp[o[key]]
        if 'connect' in o: o['connect'] = [tmp.get(x, x) for x in o['connect']]
        t = o.pop('_tmp', None)
        res = getattr(ed, 'op_' + o['op'])(o)
        if t: tmp[t] = hx(res)
        real.append(o)
    nb = ed.run([])
    out = nb.serialize()
    vr, chk = ft.verify_block(ed.b, out, ext, ed.docs, ed.intended, Tt)
    # nav-level proof: re-export and compare with the base export
    before = export_from_bytes(raw, entry, ext)
    after = export_from_bytes(out, entry, ext)
    diff = nav_diff(before, after)
    fn = os.path.join(out_dir, os.path.basename(entry))
    open(fn, 'wb').write(out)
    zp = os.path.join(out_dir, ft.ZIP_NAME)
    zrep = ft.write_zip(zp, [(entry, out)])
    line = 'filesystem = ' + ', '.join([ft.ZIP_NAME] + ft.BASE_ARCHIVES)
    open(os.path.join(out_dir, 'configpc_line.txt'), 'w').write(line + '\n')
    rep.update(ops_resolved=real, log=ed.log, base_sha256=ft.sha(raw), out=fn, out_sha256=ft.sha(out),
               out_bytes=len(out), checks=vr, nav_diff=diff, zip=zrep, configpc_line=line,
               summary_before=before['summary'], summary_after=after['summary'])
    if deploy:
        gd = os.path.normcase(os.path.abspath(deploy))
        if any(gd == f or gd.startswith(f + os.sep) for f in ft.FORBIDDEN_DEPLOY):
            raise ft.Fail('refusing to deploy into %s' % deploy)
        if ft.game_running():
            raise ft.Fail('a game is running; not touching any game folder now')
        import shutil
        shutil.copy2(zp, os.path.join(deploy, ft.ZIP_NAME))
        rep['deploy'] = deploy
    rep['result'] = 'PASS'
    json.dump(rep, open(os.path.join(out_dir, 'report.json'), 'w'), indent=1, default=str)
    return rep


def export_from_bytes(raw, entry, ext):
    tmpbv = BlockView.__new__(BlockView)
    tmpbv.raw, tmpbv.entry, tmpbv.ext = raw, entry, ext
    tmpbv.block = tb.Block(raw, ext)
    tmpbv.frs, _ = ft.fragments(tmpbv.block)
    tmpbv.docs = {k: fe.FragDoc(tmpbv.block.payloads[k], types(), nm) for k, nm in tmpbv.frs}
    tmpbv.owner, tmpbv.owner_desc = {}, {}
    cache = {}
    for k, nm in tmpbv.frs:
        tmpbv.owner[k], tmpbv.owner_desc[k] = ft.owner_chain(tmpbv.block, tmpbv.frs, k, types(), cache=cache)
    return export(tmpbv)


def nav_diff(a, b):
    """Entity-level differences between two exports (what the game's nav model will see change)."""
    out = dict(signposts=[], traffic=[], tracks=[], blockers=[])
    def idx(lst): return {(d['frag'], d['node']): d for d in lst}
    for name, la, lb, keys in (('signposts', a['peds']['signposts'], b['peds']['signposts'], ('pos', 'connections')),
                               ('traffic', a['traffic']['points'], b['traffic']['points'],
                                ('pos', 'next_name', 'next', 'effective_sub_type', 'prev')),
                               ('blockers', a['blockers'], b['blockers'], ('pos', 'size', 'collisionflags'))):
        A, B = idx(la), idx(lb)
        for key in sorted(set(A) | set(B)):
            if key not in A:
                out[name].append(dict(added=key[1], frag=key[0], **{k: B[key].get(k) for k in keys}))
            elif key not in B:
                out[name].append(dict(removed=key[1], frag=key[0]))
            else:
                ch = {k: [A[key].get(k), B[key].get(k)] for k in keys if A[key].get(k) != B[key].get(k)}
                if ch:
                    out[name].append(dict(changed=key[1], frag=key[0], **ch))
    A, B = idx(a['tracks']), idx(b['tracks'])
    for key in sorted(set(A) | set(B)):
        pa = [(q['node'], q['pos']) for q in A.get(key, {}).get('points', [])]
        pb = [(q['node'], q['pos']) for q in B.get(key, {}).get('points', [])]
        if pa != pb:
            out['tracks'].append(dict(track=key[1], frag=key[0], before=pa, after=pb))
    return out


def cmd_apply(a):
    spec = json.load(open(a.edit, encoding='utf-8'))
    try:
        import lowprio  # noqa
    except Exception:
        pass
    try:
        rep = apply_spec(spec, a.out, a.deploy)
        short = dict(result=rep['result'], zip=rep['zip']['zip'], out_sha256=rep['out_sha256'][:16], log=rep['log'],
                     nav_diff=rep['nav_diff'], configpc_line=rep['configpc_line'])
    except (ft.Fail, fe.EditError, KeyError, ValueError) as e:
        short = dict(result='FAIL: %s' % e)
        os.makedirs(a.out, exist_ok=True)
        json.dump(short, open(os.path.join(a.out, 'report.json'), 'w'), indent=1)
    print(json.dumps(short, indent=1, default=str))
    return 0 if short['result'] == 'PASS' else 1


# ------------------------------------------------------------------ round trip
def roundtrip_one(entry):
    """1. the fragment codec round trip of the block (fragtool); 2. no-op nav apply -> identical bytes;
    3. export -> ops_from_export(export, export) is empty; 4. export of the re-serialized block == export."""
    raw, entry, ext = ft.load_block_bytes(entry)
    r0 = ft.roundtrip_block(raw, ext, types())
    ed = Editor(raw, ext)
    nb = ed.run([])
    same = nb.serialize() == raw
    e1 = export_from_bytes(raw, entry, ext)
    ops = ops_from_export(e1, json.loads(json.dumps(e1)))
    e2 = export_from_bytes(nb.serialize(), entry, ext)
    return dict(entry=entry.split('/')[-1], codec_ok=(not r0['fail'] and r0['block_identical']), noop_identical=same,
                diff_ops=len(ops), reexport_identical=(json.dumps(e1, default=str) == json.dumps(e2, default=str)),
                nav=dict(tp=e1['summary']['traffic_points'], sp=e1['summary']['signposts'],
                         trk=e1['summary']['track_points'], nb=e1['summary']['navblock_boxes']))


def cmd_roundtrip(a):
    try:
        import lowprio  # noqa
    except Exception:
        pass
    arch = ft.archive()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS) if a.all else a.blocks
    res, bad = [], 0
    for n in names:
        r = roundtrip_one(n)
        if not (r['nav']['tp'] or r['nav']['sp'] or r['nav']['trk'] or r['nav']['nb']) and a.all:
            continue
        ok = r['codec_ok'] and r['noop_identical'] and r['diff_ops'] == 0 and r['reexport_identical']
        bad += not ok
        res.append(r)
        if not ok or not a.all:
            print(json.dumps(r))
    tot = dict(blocks=len(res), failures=bad, traffic_points=sum(r['nav']['tp'] for r in res),
               signposts=sum(r['nav']['sp'] for r in res), track_points=sum(r['nav']['trk'] for r in res))
    if a.o:
        json.dump(dict(totals=tot, blocks=res), open(a.o, 'w'), indent=1)
    print(json.dumps(tot))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('export'); p.add_argument('block'); p.add_argument('--entry'); p.add_argument('-o')
    p = sp.add_parser('check'); p.add_argument('blocks', nargs='*'); p.add_argument('--all', action='store_true'); p.add_argument('-o')
    p = sp.add_parser('image'); p.add_argument('nav'); p.add_argument('-o', required=True); p.add_argument('--backdrop')
    p.add_argument('--bbox', nargs=4, type=float); p.add_argument('--px-per-m', type=float, default=2.0)
    p.add_argument('--label', action='store_true'); p.add_argument('--all-boxes', action='store_true')
    p = sp.add_parser('gltf'); p.add_argument('nav'); p.add_argument('-o', required=True); p.add_argument('--backdrop')
    p = sp.add_parser('apply'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    p = sp.add_parser('roundtrip'); p.add_argument('blocks', nargs='*'); p.add_argument('--all', action='store_true'); p.add_argument('-o')
    a = ap.parse_args()
    return {'export': cmd_export, 'check': cmd_check, 'image': cmd_image, 'gltf': cmd_gltf, 'apply': cmd_apply,
            'roundtrip': cmd_roundtrip}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
