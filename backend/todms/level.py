"""Level view of one asset block: every entity the engine creates when the block loads, with world transforms,
an editor category, the instance path, the runtime (save) index, and route links.

The walk follows the engine (and tools/save_editor/nodemap.py): the block's root fragment creates its entities in
record order, then each 'fragment' property record (in stream order) instantiates that fragment under the node that
carries it, depth first. Fragments missing from the block are looked up in overdose.main (prefabs such as
PKS_HighMounted.fragment). World = owner * ... * parent * local with the stored quaternion conjugated (the project
convention the fragment writer, and the collision lab use).

An entity is editable when its fragment lives in this block and is instantiated exactly once; entities of prefab
fragments placed several times (or living in overdose.main) are shown but read-only, because a change would apply to
every instance.
"""
import collections
import math
import os
import re

import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft

BLOCK_BITS = {'.main': 1, '.map': 2, '.submap': 3, '.mission': 4, '.cutscene': 5, '.playerdata': 6}
EXTRA_NODES = {'shadow': 1, 'bullet': 10, 'lensflaremanager': 4}       # nodemap.EXTRA_NODES
P_FRAGMENT = 9

# ------------------------------------------------------------------ categories (editor layers)
CATEGORIES = [
    # key, label, colour, shown by default
    ('pickup', 'Pickups and goodies', '#ffd23f', True),
    ('weapon', 'Weapon pickups', '#ff9f1c', True),
    ('character', 'Enemies and civilians', '#ef476f', True),
    ('vehicle', 'Vehicles', '#06d6a0', True),
    ('trigger', 'Trigger boxes', '#4cc9f0', True),
    ('wall', 'Invisible walls', '#f72585', True),
    ('navblock', 'Nav blockers', '#b5179e', True),
    ('route', 'Route points', '#80ed99', True),
    ('marker', 'Mission markers', '#ffbe0b', True),
    ('model', 'Level geometry', '#adb5bd', True),
    ('havoc', 'Destructible objects', '#e07a5f', True),
    ('light', 'Lights', '#fff3b0', False),
    ('sound', 'Sound', '#9d4edd', False),
    ('effect', 'Effects and particles', '#ff70a6', False),
    ('box', 'Other boxes', '#7f8c8d', False),
    ('logic', 'Logic and folders', '#6c757d', False),
]
CAT_KEYS = [c[0] for c in CATEGORIES]


def base_class(t):
    m = re.fullmatch(r'([^()]+)\(([^()]+)\)', t or '')
    return (m.group(1), m.group(2)) if m else (t or '', t or '')


def categorize(t, get):
    """t = create type string; get(prop) -> value."""
    name, base = base_class(t)
    tl, nl, bl = (t or '').lower(), name.lower(), base.lower()
    if nl.startswith('goodie_placeholder'):
        return 'pickup'
    if nl.startswith('weapon_placeholder'):
        return 'weapon'
    if nl.startswith(('character_placeholder', 'character_deathpose', 'animal_placeholder')):
        return 'character'
    if nl.startswith('vehicle_placeholder') or nl.startswith('vehicle_root'):
        return 'vehicle'
    if 'havocplaceholder' in tl or nl.startswith('destructable'):
        return 'havoc'
    if 'trackpoint' in tl or bl in ('track',) or nl in ('database_traffic_point', 'signpost') or \
            nl.startswith(('database_traffic_point', 'pathtype', 'ai_track')) or tl == 'signpost':
        return 'route'
    if 'mission' in nl and nl.startswith('trigger_root') or 'marker' in nl or 'savepoint' in nl or \
            (get('name') or '').lower().startswith(('taskgiver', 'savepoint', 'mission_marker')):
        return 'marker'
    if bl in ('collisionbox', 'collisionsphere'):
        flags = get('CollisionFlags') or 0
        if nl.startswith(('trigger', 'soundtrigger')) or flags & 16:
            return 'trigger' if not nl.startswith('soundtrigger') else 'sound'
        if flags & 32 and not flags & 1:
            return 'navblock'
        if flags & 1:
            return 'wall'
        return 'box'
    if bl == 'model' or t == 'Model':
        return 'model' if get('modelres') else 'logic'
    if bl == 'light' or 'lensflare' in tl:
        return 'light'
    if 'sound' in tl:
        return 'sound'
    if 'particle' in tl or 'effect' in tl or bl in ('sprite', 'geometryeffect', 'shadow'):
        return 'effect'
    return 'logic'


SUBTYPE_PROPS = ('GoodieSubType', 'WeaponSubType', 'VehicleSubType', 'AISubType', 'FactionID', 'ObjectSubType',
                 'CollisionFlags', 'Model', 'Respawnable', 'IsVIP')


def norm_model(path):
    s = (path or '').lower().replace('\\', '/')
    if not s.startswith('/data/'):
        s = '/data' + (s if s.startswith('/') else '/' + s)
    return s


class Instance:
    __slots__ = ('frag', 'k', 'node', 'inst', 'owner', 'runtime', 'path')

    def __init__(self, frag, k, node, inst, owner, runtime, path):
        self.frag, self.k, self.node, self.inst, self.owner, self.runtime, self.path = \
            frag, k, node, inst, owner, runtime, path


class BlockLevel:
    def __init__(self, entry, raw, T, main_lookup=None):
        """main_lookup(short_fragment_name) -> (name, payload) from overdose.main, for prefabs the block lacks."""
        self.entry = entry
        self.ext = os.path.splitext(entry)[1].lower()
        self.T = T
        self.b = tb.Block(raw, self.ext)
        self.frs, _ = ft.fragments(self.b)
        self.short = {}
        for k, nm in self.frs:
            self.short.setdefault(nm.replace('\\', '/').split('/')[-1].lower(), (k, nm))
        self.main_lookup = main_lookup
        self._docs = {}
        self.instances = []
        self.inst_count = collections.Counter()
        self.external = []
        self.root = self._root_fragment()
        self._walk()

    def _root_fragment(self):
        if self.ext == '.main':
            for k, nm in self.frs:
                if nm.lower().endswith('overdose.scene'):
                    return nm
        base = os.path.splitext(self.entry.split('/')[-1])[0].lower()
        hit = self.short.get(base + '.fragment')
        if hit is None:
            raise ValueError('root fragment of %s not found' % self.entry)
        return hit[1]

    def doc(self, nm):
        if nm not in self._docs:
            k = self.k_of(nm)
            payload = self.b.payloads[k] if k is not None else self._ext_payload(nm)
            self._docs[nm] = fe.FragDoc(payload, self.T, nm)
        return self._docs[nm]

    def k_of(self, nm):
        for k, n in self.frs:
            if n == nm:
                return k
        return None

    def _ext_payload(self, nm):
        if self.main_lookup is None:
            raise KeyError(nm)
        r = self.main_lookup(nm.replace('\\', '/').split('/')[-1].lower())
        if r is None:
            raise KeyError(nm)
        return r[1]

    def _resolve(self, ref):
        s = ref.replace('\\', '/').split('/')[-1].lower()
        if s in self.short:
            return self.short[s][1], True
        if self.main_lookup is not None:
            r = self.main_lookup(s)
            if r is not None:
                return r[0], False
        return None, False

    def _walk(self):
        counter = [1 if self.ext != '.main' else 5]
        own_frag = set(nm for _, nm in self.frs)

        def inst(nm, owner, depth, path):
            d = self.doc(nm)
            n_inst = self.inst_count[nm]
            self.inst_count[nm] += 1
            k = self.k_of(nm)
            for r in d.records:
                if r.op == tf.CREATE:
                    t = tf.decode_value(r.raw, 0, ('string',))
                    self.instances.append(Instance(nm, k, r.node, n_inst, owner, counter[0], path))
                    counter[0] += 1 + EXTRA_NODES.get(base_class(t)[1].lower(), 0)
            if depth > 12:
                return
            for r in d.records:
                if r.op == tf.SET and r.prop == P_FRAGMENT:
                    ref = d.frag.value(r)
                    if not ref:
                        continue
                    tgt, local = self._resolve(ref)
                    if tgt is None:
                        self.external.append((nm, r.node, ref))
                        continue
                    W = d.world(r.node, owner)
                    inst(tgt, W, depth + 1, path + [(nm, r.node)])
        inst(self.root, fe.IDENT, 0, [])
        self.own_frags = own_frag
        self.next_runtime = counter[0]

    # ------------------------------------------------------------------ JSON for the editor
    def entities(self, key):
        """key: short block key for ids. Returns (entities, links)."""
        out = []
        idmap = {}
        T = self.T
        for i in self.instances:
            d = self.doc(i.frag)
            n = i.node
            t = d.type_of(n)
            def get(p, d=d, n=n):
                try:
                    return d.get(n, p)
                except KeyError:
                    return None
            cat = categorize(t, get)
            W = d.world(n, i.owner)
            editable = i.frag in self.own_frags and self.inst_count[i.frag] == 1
            eid = '%s|%d|%08X|%d' % (key, i.k if i.k is not None else -1, n, i.inst)
            idmap.setdefault((i.frag, n), eid)
            rec = dict(id=eid, frag=i.frag.replace('\\', '/').split('/')[-1], k=i.k, node='0x%08X' % n,
                       inst=i.inst, type=t, cat=cat, name=get('name'), pos=[round(x, 5) for x in W[0]],
                       rot=[round(x, 7) for x in fe.qnorm(W[1])], ri=i.runtime, ed=editable)
            par = get('parent') or 0
            if par:
                rec['parent'] = '%s|%d|%08X|%d' % (key, i.k if i.k is not None else -1, par, i.inst)
            if cat in ('model',):
                rec['model'] = norm_model(get('modelres'))
            elif t and t.endswith('(Model)') and get('modelres'):
                rec['model'] = norm_model(get('modelres'))
            _, base = base_class(t)
            if base.lower() == 'collisionbox' or (t or '').lower().endswith('(collisionbox)'):
                rec['size'] = [get('width') or 1.0, get('height') or 1.0, get('length') or 1.0]
            elif base.lower() == 'collisionsphere':
                rec['radius'] = get('radius') or 1.0
            elif get('boundradius'):
                rec['radius'] = get('boundradius')
            sub = {}
            for p in SUBTYPE_PROPS:
                v = get(p)
                if v is not None and not isinstance(v, (list, dict)):
                    sub[p] = v
            if sub:
                rec['sub'] = sub
            if get('flags') and (get('flags') & 1):
                rec['disabled'] = True
            if self._off(i, d, n):
                rec['off'] = True
            out.append(rec)
        links = self._links(idmap, out)
        return out, links

    def _off(self, inst, d, n):
        """True when the entity or any ancestor (inside its fragment, or an instancing node) is disabled at load
        (node flags bit 0, NODE_DISABLE): it only appears when a trigger enables it."""
        key = (inst.frag, inst.inst, n)
        memo = self.__dict__.setdefault('_offmemo', {})
        if key in memo:
            return memo[key]
        res, seen, m = False, set(), n
        while m and m not in seen:
            seen.add(m)
            try:
                if (d.get(m, 'flags') or 0) & 1:
                    res = True
                    break
                m = d.get(m, fe.P_PARENT) or 0
            except KeyError:
                break
        if not res:
            for fnm, node in inst.path:
                try:
                    if (self.doc(fnm).get(node, 'flags') or 0) & 1:
                        res = True
                        break
                except KeyError:
                    pass
        memo[key] = res
        return res

    def _links(self, idmap, ents):
        """Route lines between entity ids: track points in engine child order, traffic next-point links,
        pedestrian sign-post connections."""
        links = []
        byfrag = collections.defaultdict(list)
        for i in self.instances:
            if i.inst == 0:
                byfrag[i.frag].append(i.node)
        for nm, nodes in byfrag.items():
            d = self.doc(nm)
            typ = {n: d.type_of(n) or '' for n in nodes}
            if not any(('Track' in t) or t.startswith('database_traffic_point') or t == 'SignPost' for t in typ.values()):
                continue
            kids = _child_order(d)
            for n in nodes:
                t = typ[n]
                if base_class(t)[1] == 'Track' or t == 'Track':
                    pts = [c for c in kids.get(n, []) if 'TrackPoint' in typ.get(c, '')]
                    if any('AI_track_point' in typ.get(c, '') for c in pts):
                        kind = 'vehicle'
                    elif t.startswith('Pathtype'):
                        kind = 'goto' if not (d.get(n, 'PathType') or 0) else 'patrol'
                    elif t.startswith('AI_track'):
                        kind = 'patrol'
                    else:
                        kind = 'object'            # plain Track: moving objects, elevators, camera paths
                    for a, b in zip(pts, pts[1:]):
                        if (nm, a) in idmap and (nm, b) in idmap:
                            links.append([idmap[(nm, a)], idmap[(nm, b)], kind])
                    if pts and d.get(n, 'connectends') and len(pts) > 2:
                        links.append([idmap[(nm, pts[-1])], idmap[(nm, pts[0])], kind])
                elif t == 'SignPost':
                    for c in d.get(n, 'connections') or []:
                        if c and (nm, c) in idmap and c > n:
                            links.append([idmap[(nm, n)], idmap[(nm, c)], 'ped'])
            # traffic: NameOfNextPoint = a descendant of the point's grandparent with that name
            tps = [n for n in nodes if typ[n].startswith('database_traffic_point')]
            if tps:
                par = {n: (d.get(n, fe.P_PARENT) or 0) for n in nodes}
                byname = collections.defaultdict(list)
                for n in nodes:
                    v = d.get(n, fe.P_NAME)
                    if v:
                        byname[v.lower()].append(n)
                for n in tps:
                    nx = d.get(n, 'NameOfNextPoint')
                    if not nx:
                        continue
                    gp = par.get(par.get(n, 0), 0)
                    for h in byname.get(nx.lower(), []):
                        p, seen, ok = par.get(h, 0), set(), gp == 0
                        while p and p not in seen and not ok:
                            ok = p == gp
                            seen.add(p)
                            p = par.get(p, 0)
                        if ok and (nm, h) in idmap:
                            links.append([idmap[(nm, n)], idmap[(nm, h)], 'traffic'])
                            break
        return links

    def models_used(self):
        out = collections.Counter()
        for i in self.instances:
            d = self.doc(i.frag)
            try:
                m = d.get(i.node, 'modelres')
            except KeyError:
                m = None
            if m:
                out[norm_model(m)] += 1
        return out

    def entity_props(self, frag_k, node):
        nm = dict(self.frs)[frag_k]
        d = self.doc(nm)
        T = self.T
        props = []
        for r in d.sets_of(node):
            v = d.frag.value(r)
            t = T.ptype(r.prop)
            if t == 'Entity' and v is not None:
                v = '0x%08X' % v
            props.append(dict(name=T.name(r.prop), type=t, value=v))
        return dict(type=d.type_of(node), path=d.path_of(node), props=props)


def _child_order(doc):
    """{parent: [children in engine order]} (navtool.child_order: order #5 as a signed short, FUN_0088E8A0)."""
    import struct
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
            v = ((v & 0xFFFF) ^ 0x8000) - 0x8000
            order[r.node] = v
            if r.node in parent:
                p = parent[r.node]
                detach(r.node)
                attach(r.node, p)
        elif r.prop == fe.P_PARENT:
            v = struct.unpack('<I', r.raw[:4])[0]
            p = 0 if v in (0, 0xFFFFFFFF) else v
            detach(r.node)
            parent[r.node] = p
            attach(r.node, p)
    return kids
