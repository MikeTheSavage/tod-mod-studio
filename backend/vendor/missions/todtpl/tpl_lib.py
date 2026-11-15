"""tpl_lib.py - helpers shared by the template modules (Ctx, lint, park_strays, asset install). Port of missions/types/mesa_lib.py with the
Mesa constants (centre 800/800, ground 20, bounds 79) replaced by the HOST the mission is placed in (tpl_host.Host).

  Ctx        what a template's design(ctx) gets: the Builder, the new mission block, node lookup, move/set helpers; ctx.world = the Host
  lint_*     structural lint of a built mission block ('every TargetName resolves' + 'nothing outside the host bounds')
Data only; nothing here touches the game.
"""
import json, math, os, re, struct, sys
sys.dont_write_bytecode = True

GY_DY = 0.8                              # a character placeholder stands this far above the ground (ground 20.0 + 0.8 = 20.8 in the Mesa)


def hx(n):
    return '0x%08X' % n


class Ctx:
    """Handed to a type spec's design(ctx). Everything that edits the NEW mission block goes through here so the order of
    Builder operations (and so the bytes of the block) is the order the spec wrote them."""

    def __init__(self, B, BE, T, new_entry, src_entry, old_root, new_root, bi, world, spec, texts):
        self.B, self.BE, self.T = B, BE, T
        self.NEW, self.SRC, self.old_root, self.new_root = new_entry, src_entry, old_root, new_root
        self.bi, self.world, self.spec = bi, world, spec
        self.texts = texts                      # key -> ordinal (allocated by the builder, see build_mesa_missions.alloc_texts)
        self._nodes = None
        self.moved = set()                      # (fragment, key) of every node the spec already placed (park_strays leaves them alone)
        self.log = []

    # ---- lookup
    def nodes(self):
        """[(runtime index, type, fragment, key, name, path)] of the TEMPLATE block"""
        if self._nodes is None:
            self._nodes = self.bi.nodes()
        return self._nodes

    def frag(self, f):
        """fragment name as the NEW block has it (the template root fragment is renamed)"""
        return self.new_root if f.split('/')[-1] == self.old_root else f.split('/')[-1]

    def find(self, name=None, type=None, regex=None, under=None):
        """nodes of the template block matching name (case insensitive), type prefix and/or name regex"""
        out = []
        for n in self.nodes():
            idx, ty, f, key, nm, path = n
            if name is not None and str(nm).lower() != name.lower():
                continue
            if type is not None and not ty.startswith(type):
                continue
            if regex is not None and not re.search(regex, str(nm) or ''):
                continue
            out.append(n)
        return out

    def one(self, name=None, type=None, regex=None):
        r = self.find(name, type, regex)
        if len(r) != 1:
            raise RuntimeError('expected one node name=%r type=%r regex=%r, found %d' % (name, type, regex, len(r)))
        return r[0]

    def doc_of(self, n):
        return self.bi.doc(n[2])

    def get(self, n, prop, default=None):
        return self.doc_of(n).get(n[3], prop, default)

    def parent_key(self, n):
        return self.get(n, 'parent', 0)

    def chain(self, n):
        """ancestors (nearest first) as [(key, type, name)] inside the same fragment"""
        by = {x[3]: x for x in self.nodes() if x[2] == n[2]}
        out, k, seen = [], self.parent_key(n), set()
        while k and k in by and k not in seen:
            seen.add(k)
            a = by[k]; out.append(a)
            k = self.get(a, 'parent', 0)
        return out

    def _pos_of(self, n):
        """template world position (what the Builder believes): bi.world = (pos, quat)"""
        return [float(v) for v in self.bi.world(n[2], n[3])[0]]

    def engine_pos(self, n):
        """position as the ENGINE composes it: under a NodeLogical parent L it is world(L).pos + local pos (no rotation)"""
        lp = self.logical_parent(n)
        if lp is None:
            return self._pos_of(n)
        pp = self.get(lp, 'pos', [0, 0, 0]); lc = self.get(n, 'pos', [0, 0, 0])
        return [pp[0] + lc[0], pp[1] + lc[1], pp[2] + lc[2]]

    # ---- edit
    def set(self, n, prop, value):
        self.B.set(self.NEW, self.frag(n[2]), n[3], prop, value)

    def move(self, n, pos, rot=None):
        """world move through the Builder; for nodes under a NodeLogical parent use place() (trap 20.3 #2)"""
        self.moved.add((n[2], n[3]))
        self.B.move(self.NEW, self.frag(n[2]), n[3], pos=list(pos), rot=rot)

    def logical_parent(self, n):
        for a in self.chain(n):
            if '(NodeLogical)' in a[1] and 'Trigger_Root' not in a[1]:
                return a
        return None

    def place(self, n, pos):
        """put node n at WORLD pos. Under a NodeLogical parent the engine ADDS the parent's local pos (docs 20.3 #2): write the
        local pos = target - parent pos and an identity orientation. Otherwise a plain world move."""
        lp = self.logical_parent(n)
        if lp is None:
            self.move(n, pos)
            return
        pp = self.get(lp, 'pos', [0, 0, 0])               # the parent's LOCAL pos (proven: docs 20.3 #2), not its composed world
        self.moved.add((n[2], n[3]))
        self.set(n, 'pos', [pos[0] - pp[0], pos[1] - pp[1], pos[2] - pp[2]])
        self.set(n, 'orient', [0.0, 0.0, 0.0, 1.0])

    def resize_box(self, n, w=None, h=None, l=None):
        for p, v in (('width', w), ('height', h), ('length', l)):
            if v is not None:
                self.set(n, p, float(v))

    def siblings(self, n):
        pk = self.parent_key(n)
        return [x for x in self.nodes() if x[2] == n[2] and self.get(x, 'parent', 0) == pk and x[3] != n[3]]

    def place_enemy(self, char, xz, y=None, health_mod=None, damage_mod=None, damage_modify=None):
        """Move a character_placeholder to world (x, y, z) and shift every spatial sibling in its folder (weapon / wear
        placeholders) by the same offset; optional easier-enemy tuning."""
        if y is None:
            y = self.world.gy(xz[0], xz[1]) + GY_DY
        op = self._pos_of(char)
        d = (xz[0] - op[0], y - op[1], xz[1] - op[2])
        self.move(char, (xz[0], y, xz[1]))
        for s in self.siblings(char):
            kind = s[1].split('(')[0]
            if kind == 'wear_placeholder':             # the template parks these at a meaningless far-away pos: put it on the character
                self.move(s, (xz[0], y, xz[1]))
            elif kind in ('weapon_placeholder', 'Pathtype', 'Trigger_Root', 'Model'):
                sp = self._pos_of(s)                    # keeps its offset to the character (a patrol path keeps its shape)
                self.move(s, (sp[0] + d[0], sp[1] + d[1], sp[2] + d[2]))
        if health_mod is not None:
            self.set(char, 'Health_mod', health_mod)
        if damage_mod is not None:
            self.set(char, 'Damage_mod', damage_mod)
        if damage_modify is not None:                  # INTEGER multiplier (0 = harmless, 1 = normal): the float Damage_mod did not keep Ram alive in the stunt / frenzy runs
            self.set(char, 'Damage_modify', int(damage_modify))

    def set_weapons(self, char, subtype=0):
        """WeaponSubType of the weapon placeholders that belong to this character (0 = Beretta pistol, 5 = shotgun, ...)"""
        n = 0
        for s in self.siblings(char):
            if s[1].startswith('weapon_placeholder'):
                self.set(s, 'WeaponSubType', int(subtype)); n += 1
        return n

    def _free_uid(self, uid):
        """Builder uids are global to the build: a second mission of the same type in one project would repeat a template's literal uid. Later instances get a suffix (the uid is internal; the first instance, and so the Mesa sample, keeps its name)."""
        u, i = uid, 2
        while u in self.B.uids or any(a['uid'] == u for L in self.B.appends.values() for a in L):
            u = '%s__%d' % (uid, i)
            i += 1
        return u

    def add_action_from(self, src, parent, uid, name=None, sets=None):
        """like add_action, the template is a node of ANOTHER shipped block: src = (block entry under shared/, fragment name, node key)"""
        from_entry = 'data_pc/overdose_the_game/overdose/shared/' + src[0]
        uid = self._free_uid(uid)
        self.B.append(self.NEW, uid, (from_entry, src[1], src[2]),
                      parent=('ref', self.frag(parent[2]), parent[3]), name=name, sets=dict(sets or {}))
        self.log.append('add_action_from %s under %s' % (uid, parent[4]))

    def add_action(self, template, parent, uid, name=None, sets=None):
        """Append a COPY of an existing action node (template) under another root (parent) of the new block (Builder.append, save-safe).
        sets: property overrides, e.g. {'Delay': 5.0, 'TargetName': 'X'}."""
        uid = self._free_uid(uid)
        st = dict(sets or {})
        st.setdefault('flags', int(self.get(template, 'flags', 0)) & ~1)         # a clone of the already EDITED block inherits a disabled state (3c trap): the template's own flags, enabled
        self.B.append(self.NEW, uid, (self.NEW, self.frag(template[2]), template[3]),
                      parent=('ref', self.frag(parent[2]), parent[3]), name=name, sets=st)
        self.log.append('add_action %s under %s' % (uid, parent[4]))

    def disable_folder(self, n):
        """a folder that stays disabled (flags bit 0) when its team is enabled: removes a template enemy from the mission"""
        self.set(n, 'flags', int(self.get(n, 'flags', 0)) | 1)

    def retarget_names(self, mapping, props=('TargetName', 'SpecificActivator'), classes=None, skip=()):
        """Set every string property in `props` of the template block whose value (case folded) is a key of `mapping`
        (dict or callable old -> new/None) to the new name. classes: type prefixes to restrict to. skip: node names to leave."""
        f = mapping if callable(mapping) else (lambda s, m={k.lower(): v for k, v in mapping.items()}: m.get(s.lower()))
        T = self.T
        n_set = 0
        by_key = {(x[2], x[3]): x for x in self.nodes()}
        for k, nm in self.bi.frs:
            doc = self.bi.doc(nm)
            for r in doc.records:
                if r.prop is None or T.name(r.prop) not in props:
                    continue
                n = by_key.get((nm, r.node))
                if n is None or (classes and not any(n[1].startswith(c) for c in classes)) or n[4] in skip:
                    continue
                try:
                    v = doc.get(r.node, T.name(r.prop))
                except Exception:                                  # noqa: BLE001
                    continue
                if not isinstance(v, str) or not v:
                    continue
                new = f(v)
                if new and new != v:
                    self.B.set(self.NEW, self.frag(nm), r.node, T.name(r.prop), new)
                    n_set += 1
        self.log.append('retarget_names %d' % n_set)
        return n_set

    def retarget_camera_cuts(self, names=None, to='PlayerCharacter'):
        """camera cuts (Trigger_Activate_Camera) that point at a node of the old map: cut to the player instead"""
        n = 0
        for x in self.find(type='Trigger_Activate_Camera'):
            if names is not None and x[4] not in names:
                continue
            self.set(x, 'TargetName', to); self.set(x, 'LookAt', 0); n += 1
        self.log.append('camera cuts retargeted %d' % n)
        return n


# ------------------------------------------------------------------------------------------------ lint
STRUCTURAL = ('character_placeholder', 'vehicle_placeholder', 'weapon_placeholder', 'wear_placeholder', 'Model',
              'generic_object_effect', 'Pathtype', 'TrackPoint', 'Trigger_Root(CollisionBox)', 'Trigger_Root(CollisionSphere)',
              'Trigger_Root_Mission', 'Trigger_Root_Mission(CollisionBox)')


def block_names(BE, entry, raw):
    """{lower name: type} for every named node of a block"""
    bi = BE.BlockInfo(entry, raw)
    return {str(n[4]).lower(): n[1] for n in bi.nodes() if n[4]}


def lint_block(BE, T, entry, raw, extra_names, allow_unresolved=(), bounds=None, outside_ok=None):
    """Lint one built mission block. Returns (errors, warnings).
      - every TargetName of every action resolves to a node of: this block, `extra_names` (new overdose.main + mesa blocks + shipped
        always-loaded names), except names in allow_unresolved (dead references to the old map the template had; reason in the spec)
      - every placed object (STRUCTURAL types) lies inside the mesa bounds (engine world: NodeLogical parents add their pos)"""
    bi = BE.BlockInfo(entry, raw)
    errs, warns = [], []
    if bounds is None:
        raise ValueError('lint_block needs the host bounds (x0, z0, x1, z1)')
    nodes = bi.nodes()
    mine = {str(n[4]).lower() for n in nodes if n[4]}
    by_key = {(n[2], n[3]): n for n in nodes}
    allow = {a.lower() for a in allow_unresolved}
    seen_unres = {}
    for k, nm in bi.frs:
        doc = bi.doc(nm)
        for r in doc.records:
            if r.prop is None or T.name(r.prop) != 'TargetName':
                continue
            n = by_key.get((nm, r.node))
            try:
                v = doc.get(r.node, 'TargetName')
            except Exception:                                      # noqa: BLE001
                continue
            if not isinstance(v, str) or not v:
                continue
            lv = v.lower()
            if lv in mine or lv in extra_names or lv in ('playercharacter',):
                continue
            seen_unres.setdefault(v, []).append(n[4] if n else '?')
    for v, who in sorted(seen_unres.items()):
        msg = 'TargetName %r does not resolve (used by %s)' % (v, ', '.join(sorted(set(map(str, who)))[:4]))
        (warns if v.lower() in allow else errs).append(msg if v.lower() not in allow else 'allowed: ' + msg)
    # Trig action (Trig_Noaction_Reactivate) with ActivateWho 2 (= the root's parent) AND a TargetName: if the TargetName was set by a spec the engine still uses the parent
    # (a retargeted copy crashed the game to black in stage 3c: set ActivateWho 3 together with the new TargetName)
    for n in nodes:
        if n[1].startswith('Trigger_Activate_Trig_Noaction'):
            d_ = bi.doc(n[2])
            if d_.get(n[3], 'ActivateWho', None) == 2 and d_.get(n[3], 'TargetName', ''):
                warns.append('Trig action %s (%s) has ActivateWho 2 but TargetName %r: retargeted copy? set ActivateWho 3' % (n[4], hex(n[3]), d_.get(n[3], 'TargetName', '')))
    # bounds
    out = []
    for n in nodes:
        base = n[1]
        if not (base.split('(')[0] in ('character_placeholder', 'vehicle_placeholder', 'weapon_placeholder', 'wear_placeholder',
                                       'Model', 'generic_object_effect', 'TrackPoint') or      # a Pathtype's own pos is only a pivot: its TrackPoints are checked
                base in ('Trigger_Root(CollisionBox)', 'Trigger_Root(CollisionSphere)', 'Trigger_Root_Mission(CollisionBox)')):
            continue
        p = [float(v) for v in bi.world(n[2], n[3])[0]]
        # under a NodeLogical parent the engine adds the parent's pos to the local pos without rotating it (docs 20.3 #2)
        doc = bi.doc(n[2])
        k = doc.get(n[3], 'parent', 0)
        guard = 0
        while k and guard < 40:
            a = by_key.get((n[2], k)); guard += 1
            if a is None:
                break
            if '(NodeLogical)' in a[1] and 'Trigger_Root' not in a[1]:
                pp = doc.get(a[3], 'pos', [0, 0, 0]); lc = doc.get(n[3], 'pos', [0, 0, 0])
                p = [pp[0] + lc[0], pp[1] + lc[1], pp[2] + lc[2]]
                break
            k = doc.get(k, 'parent', 0)
        if abs(p[0]) < 20.0 and abs(p[2]) < 20.0:
            continue                       # prefab-instance child: its parent carries the position (the instance itself is linted)
        if not (bounds[0] <= p[0] <= bounds[2] and bounds[1] <= p[2] <= bounds[3]):
            out.append('%s %s at (%.1f, %.1f, %.1f)' % (n[1].split('(')[0], n[4] or '-', p[0], p[1], p[2]))
    if out:
        msg = '%d placed objects outside the mesa bounds: %s%s' % (len(out), '; '.join(out[:6]), ' ...' if len(out) > 6 else '')
        if outside_ok:
            warns.append('allowed (%s): %s' % (outside_ok, msg))
        else:
            errs.append(msg)
    return errs, warns


HIDE_CLOCK_SRC = ('subm_06_indu_chepoi_race.mission', 'SubM_06_Indu_ChePoi_Race.fragment', 0x401251)    # ACT_Disable_Countdown (Racing_Countdown 84)


def hide_clock(ctx, routes, tag, delay=0.3):
    """Stage 2a fix: the template's Countdown stop (25) leaves the clock on screen (it kept running in Downtown after the mission ended).
    Append a copy of the race's 'disable countdown' action (Racing_Countdown 84) under every end route of the mission."""
    for i, r in enumerate(routes):
        ctx.add_action_from(HIDE_CLOCK_SRC, ctx.one(name=r), '%s_hideclock_%d' % (tag, i), name='ACT_HideClock', sets={'Delay': float(delay)})


def park_strays(ctx, park, y=None, step=0.7):
    """Sweep: every structural node of the template (see STRUCTURAL) that the engine would still place outside the mesa after the spec's own
    moves (old-map leftovers: paths, markers, vehicles, cameras' helpers) is parked on the dunes at `park` = (x, z) world. Nodes whose local
    pos is near the origin are children of prefab instances (their parent carries the position) and are left alone."""
    k = 0
    bd = ctx.world.bounds
    if y is None:
        y = ctx.world.gy(park[0], park[1]) + 1.0
    for n in ctx.nodes():
        if not any(n[1].startswith(t) for t in STRUCTURAL):
            continue
        if (n[2], n[3]) in ctx.moved:
            continue
        p = ctx.engine_pos(n)
        if abs(p[0]) < 20.0 and abs(p[2]) < 20.0:
            continue
        if not (bd[0] <= p[0] <= bd[2] and bd[1] <= p[2] <= bd[3]):
            ctx.move(n, (park[0] + step * (k % 20), y, park[1] + step * (k // 20)))
            k += 1
    ctx.log.append('park_strays %d' % k)
    return k


# ------------------------------------------------------------------------------------------------ assets (was mesa_assets.py)
def _records(tb, block):
    info = bytes(block.info)
    st = tb.record_starts(info, block.n)
    en = st[1:] + [len(info)]
    return [dict(type=tb.u32(info, R), name=tb.record_name(info, R), rec=info[R:E_], payload=block.payloads[k]) for k, (R, E_) in enumerate(zip(st, en))]


def install_assets(ctx, src_entry, model_names, skip_if_in=None):
    """Copy compiled asset records (models + textures) from a shipped block into the NEW mission block: a Model node whose model record is not in a
    resident block is drawn as a giant rainbow prism. Patches ctx.B.build so the built block of ctx.NEW gets the records appended."""
    from . import tpl_env
    E = tpl_env.get()
    tb = E.ft.tb
    skip_if_in = skip_if_in or (E.SHARED + 'overdose.main',)
    src = tb.Block(E.read(src_entry), '.' + src_entry.rsplit('.', 1)[1])
    srec = _records(tb, src)
    by = {r['name'].lower(): r for r in srec}
    have = set()
    for e in skip_if_in:
        b = tb.Block(E.read(e), '.' + e.rsplit('.', 1)[1])
        have |= {r['name'].lower() for r in _records(tb, b)}
    add, seen = [], set()
    for mn in model_names:
        m = by[mn.lower()]
        add.append(m); seen.add(mn.lower())
        for t in sorted(set(x.decode() for x in re.findall(rb'/data/[A-Za-z0-9_/\.\- ]+\.bmp', m['rec']))):
            tl = t.lower()
            if tl in seen or tl in have or tl not in by:
                continue
            add.append(by[tl]); seen.add(tl)
    ctx.log.append('assets copied into the block: %s' % [a['name'].rsplit('/', 1)[-1] for a in add])
    orig = ctx.B.build
    new_entry = ctx.NEW

    def build():
        out, rep = orig()
        b = tb.Block(out[new_entry], '.mission')
        items = _records(tb, b)
        names = {i['name'].lower() for i in items}
        items += [dict(a) for a in add if a['name'].lower() not in names]
        b.info = bytearray(b''.join(i['rec'] for i in items))
        b.payloads = [i['payload'] for i in items]
        b.n = len(items)
        out[new_entry] = b.serialize()
        rep.setdefault('asset_records_added', {})[new_entry.split('/')[-1]] = [a['name'] for a in add]
        return out, rep
    ctx.B.build = build


# ------------------------------------------------------------------------------------------------ helpers shared by several templates
def enemy_levels(ctx):
    """{level folder name: [character placeholders]} of a SubM_20 (JavPer) based block"""
    chars = [n for n in ctx.find(type='character_placeholder') if str(n[4]).startswith('Enemy_')]
    by_level = {}
    for c in chars:
        lvl = [a for a in ctx.chain(c) if str(a[4]).startswith('SubM_20_Down_JavPer_Kill_LEVEL')]
        by_level.setdefault(lvl[0][4] if lvl else '?', []).append(c)
    return chars, by_level


def folder_of(ctx, c):
    pk = ctx.parent_key(c)
    return [x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0]


def pick_enemy(by_level, level, nm):
    cands = by_level[level]
    if nm.startswith('@'):                                   # '@19a' / '@19b': the two first of the four placeholders that share the name Enemy_19
        same = sorted([c for c in cands if c[4] == 'Enemy_19'], key=lambda c: c[3])
        return same[0 if nm == '@19a' else 1]
    return [c for c in cands if c[4] == nm][0]


def park_spares(ctx, spares, region, min_sep=1.2, margin=0.5, disable=True):
    """spares = placeholders that do not fight: fitted into `region` (world rect) and their folders disabled"""
    W = ctx.world
    sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=region, min_sep=min_sep, margin=margin)
    for c, xz in zip(spares, sp):
        ctx.place_enemy(c, xz)
        if disable:
            ctx.disable_folder(folder_of(ctx, c))


def park_javper_boxes(ctx, park):
    """SubM_20 family: the Downtown walk-in boxes and world triggers parked + disabled. park = (x, z) anchor (Mesa: centre + (-60, 55))"""
    px, pz = park
    y = ctx.world.gy(px, pz) + 1.0
    boxes = [n for n in ctx.find(type='Trigger_Root(CollisionBox)') if n[4] and ('Enemy_Enable_Radar' in n[4])] + ctx.find(name='Trigger', type='Trigger_Root(CollisionBox)')
    for k, b in enumerate(boxes):
        ctx.move(b, (px + 4.0 * k, y, pz + 5.0))
        ctx.set(b, 'flags', int(ctx.get(b, 'flags', 0)) | 1)
    for nm in ('TRIG_SubM_20_Elev_indicator', 'TRIG_SubM_20_cam_slidingwire', 'Activate_music_slidingwire', 'Activate_music_slidingwire_02'):
        n = ctx.one(name=nm)
        ctx.move(n, (px, y, pz - 5.0))
        ctx.set(n, 'flags', int(ctx.get(n, 'flags', 0)) | 1)


def ground_pt(host, pt, dy=0.0):
    """user point [x, y|None, z] -> (x, y_ground + dy, z)"""
    return (pt[0], host.gy(pt[0], pt[2], pt[1]) + dy, pt[2])


def snap_pt(host, pt, margin=1.2, taken=(), min_sep=0.0, snap=True):
    """user point -> (x, z) on free ground (or unchanged when snap is off)"""
    if not snap:
        return pt[0], pt[2]
    return host.snap(pt[0], pt[2], margin=margin, taken=taken, min_sep=min_sep)
