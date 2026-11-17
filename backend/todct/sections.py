"""Section and transition tools core (companion tools part B) of TOD Mod Studio. Background: docs/subsystem_level_streaming.md (blocks, the swap, adding and splitting submaps) and
docs/subsystem_seamless_transitions.md (every loader volume; the 7 teleport loaders: the Downtown-Harbour bridge x2,
the Downtown-Industrial tunnel x3, the farm pass x2).

A section (submap) border is a pair of loader volumes: a Trigger_Root box or sphere in each block with a
Trigger_Activate_Load_Unload_Save action (ActionType 21) whose TargetName is the other block's folder. Without
Teleport_to the engine keeps the player where he is; a teleport loader moves him because its box stands in the wrong
order for walking (the exit box comes before the other block's return box). The fix (package T1 of tools/seamless):
empty both Teleport_to values and move one box past the other: set and move ops on existing nodes, save-safe.

  cat = catalog(entries, read)              every loader volume of the blocks: box (centre, size, rotation, corners),
                                            targets, teleport, return loader, class (seamless transitions.catalog),
                                            order along the border, and a fix for each teleport
  ops = fix_teleport(cat, volume_id, gap)   section ops that turn a teleport pair into a walk border
  add_to_builder(builder, ops, read)        blockedit requests (also 'add_section')
  verify(cat_before, ops, out, read)        transitions.catalog on the built blocks + the box-order check
  plan = split_plan(entry, raw, axis, at)   read-only: what a cut at a plane would split (submaptool splitplan)

Section ops:
  {"op": "set_teleport", entry, frag, node, value: ""}               Teleport_to of a loader action
  {"op": "move_loader",  entry, frag, node, pos}                      a loader root (its sprites move with it)
  {"op": "add_section",  id, map_entry, source_submap, new_index (2 digits), specific_id | null (= next free id,
                         raising common.SUBMAPS_MAX), loader_in: {pos, size, yaw}, loader_back: {pos, size, yaw}}
                         new submap block (renamed copy of the source + its language blocks), its database_SubMap_ID
                         folder beside the map's MAINMAP_ folder, its load-screen entry, and a loader on each side
                         (in the map block when a submap's last fragment is a shared prefab)
"""
import collections
import math
import os
import re

from . import blockedit as BE
from . import tools

SHARED = 'data_pc/overdose_the_game/overdose/shared/'
MAIN = SHARED + 'overdose.main'
GAP = 23.0          # T1's hysteresis: the moved box's near face 23 m past the other box (z -540 vs -508.7)
GROUPS = collections.OrderedDict([
    ('Downtown 01 + Harbour 01 (the bridge)', ['submap01_map02_lostoros_downtown.submap', 'submap01_map04_lostoros_train_harbour.submap']),
    ('Downtown 02 + Industrial 02/04 (the tunnel)', ['submap02_map02_lostoros_downtown.submap', 'submap02_map03_lostoros_industrial.submap',
                                                     'submap04_map03_lostoros_industrial.submap']),
    ('Farm 01 + 02 (the pass)', ['submap01_map06_virgillos_farm.submap', 'submap02_map06_virgillos_farm.submap']),
    ('Jungle 01 + 02', ['mainmap_map09_jungle.map', 'submap01_map09_jungle.submap', 'submap02_map09_jungle.submap']),
])
TELEPORT_KNOWN = 7


class SectionError(ValueError):
    pass


def short(e):
    return (e or '').replace('\\', '/').split('/')[-1]


def full(e):
    return e if '/' in e else SHARED + e.lower()


# ---------------------------------------------------------------------------------------------- scanning
def _qrot(q, v):
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return [v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx)]


def scan(entry, raw, names=()):
    """Loader volumes (ActionType 21) of one block + positions of nodes with the given names."""
    M = tools.load()
    ft, fe, tb = M.ft, M.fe, M.tb
    T = ft.types()
    ext = os.path.splitext(entry)[1].lower()
    b = tb.Block(raw, ext)
    frs, _ = ft.fragments(b)
    want = {n.lower() for n in names if n}
    loaders, found = [], {}
    cache = {}
    for k, nm in frs:
        if len(b.payloads[k]) <= 24:
            continue
        d = fe.FragDoc(b.payloads[k], T, nm)
        owner = None
        for n in d.created_ids():
            ty = d.type_of(n) or ''
            nmv = d.get(n, 'name')
            if want and nmv and nmv.lower() in want:
                if owner is None:
                    owner, _ = ft.owner_chain(b, frs, k, T, cache=cache)
                found.setdefault(nmv.lower(), dict(block=short(entry), pos=[round(x, 3) for x in d.world(n, owner)[0]]))
            if ty.startswith('Trigger_Activate_Load_Unload_Save') and d.get(n, 'ActionType') == 21:
                root, seen = d.get(n, 'parent') or 0, set()
                while root and root not in seen and not (d.type_of(root) or '').startswith('Trigger_Root'):
                    seen.add(root)
                    root = d.get(root, 'parent') or 0
                if owner is None:
                    owner, _ = ft.owner_chain(b, frs, k, T, cache=cache)
                rec = dict(block=short(entry), entry=entry, frag=nm, action=BE.hx(n), action_name=d.get(n, 'name'),
                           target=d.get(n, 'TargetName'), teleport=d.get(n, 'Teleport_to') or '', root=None)
                if root:
                    W = d.world(root, owner)
                    q = fe.qnorm(W[1])           # TRUE world rotation (compose uses conjugated stored quaternions)
                    size = [d.get(root, 'width'), d.get(root, 'height'), d.get(root, 'length')]
                    centre = list(W[0])
                    if d.get(root, 'left') is not None:          # Trigger_Root(MockupBox): left/right/front/back
                        l, r_, f_, b_ = [float(d.get(root, k) or 0) for k in ('left', 'right', 'front', 'back')]
                        size = [r_ - l, d.get(root, 'height'), b_ - f_]
                        off = _qrot(q, [(l + r_) / 2, 0.0, (f_ + b_) / 2])
                        centre = [centre[j] + off[j] for j in range(3)]
                    rec['root'] = dict(node=BE.hx(root), name=d.get(root, 'name'), type=d.type_of(root),
                                       pos=[round(x, 3) for x in centre], node_pos=[round(x, 3) for x in W[0]],
                                       rot=[round(x, 6) for x in q],
                                       size=size, radius=d.get(root, 'radius'), flags=d.get(root, 'flags'))
                loaders.append(rec)
    return loaders, found


def _corners(pos, size, rot):
    if not size or size[0] is None:
        return None
    hx_, hy, hz = [float(s) / 2 for s in size]
    out = []
    for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        v = _qrot(rot, [sx * hx_, 0.0, sz * hz])
        out.append([round(pos[0] + v[0], 3), round(pos[2] + v[2], 3)])
    return out


def _extent(size, rot, d, radius=None):
    """Half extent of the volume along the horizontal unit direction d (x, z)."""
    if radius:
        return float(radius)
    hx_, hy, hz = [float(s or 0) / 2 for s in size]
    ax = _qrot(rot, [1.0, 0.0, 0.0])
    az = _qrot(rot, [0.0, 0.0, 1.0])
    return abs(ax[0] * d[0] + ax[2] * d[1]) * hx_ + abs(az[0] * d[0] + az[2] * d[1]) * hz


def catalog(entries, read):
    """Every loader volume of the blocks, classified with the seamless tools' transitions.catalog."""
    entries = [full(e) for e in entries]
    raws = {e: read(e) for e in entries}
    first = {e: scan(e, raws[e])[0] for e in entries}
    tele = {l['teleport'] for L in first.values() for l in L if l['teleport']}
    found = {}
    if tele:
        for e in entries:
            _, f = scan(e, raws[e], tele)
            for k, v in f.items():
                found.setdefault(k, v)
    D = {}
    for e in entries:
        ents = [dict(f='', t='Node', c='node', name=n, p=v['pos'], size=None) for n, v in found.items() if v['block'] == short(e)]
        # transitions.find_node matches names exactly as written: give it the spelling the loaders use
        spell = {t.lower(): t for t in tele}
        for x in ents:
            x['name'] = spell.get(x['name'], x['name'])
        D[short(e)] = dict(loaders=[dict(fragment=short(l['frag']), target=l['target'], teleport=l['teleport'] or None,
                                         root=l['root'] and dict(name=l['root']['name'], type=l['root']['type'], pos=l['root']['pos'],
                                                                  size=l['root']['size'], radius=l['root']['radius']))
                                    for l in first[e]], ents=ents)
    TR = tools.load_more('transitions')
    cat = TR.catalog(D)
    vols = []
    for i, c in enumerate(cat):
        acts = [l for l in first[full(c['block'])] if l['root'] and l['root']['name'] == c['name'] and l['root']['pos'] == c['pos']]
        r0 = acts[0]['root'] if acts else {}
        vid = '%s|%s' % (c['block'], r0.get('node'))
        v = dict(id=vid, block=c['block'], entry=full(c['block']), frag=acts[0]['frag'] if acts else None, node=r0.get('node'),
                 node_pos=r0.get('node_pos'), root_type=r0.get('type'),
                 name=c['name'], cls=c['class'], pos=c['pos'], size=c['size'], radius=c['radius'], rot=r0.get('rot'),
                 corners=_corners(c['pos'], c['size'], r0.get('rot') or [0, 0, 0, 1]) if not c['radius'] else None,
                 targets=c['targets'], target=c['target'], target_block=c['target_block'], map_change=c['map_change'],
                 teleports=c['teleports'], teleport_dest=c['tele_dest'], teleport_dist=c['tele_dist'],
                 return_loader=c['return_loader'],
                 actions=[dict(frag=l['frag'], node=l['action'], name=l['action_name'], target=l['target'], teleport=l['teleport'])
                          for l in acts])
        vols.append(v)
    by_id = {v['id']: v for v in vols}
    # pairs and order along the border; a fix for each teleport
    for v in vols:
        v['pair'] = None
        rl = v['return_loader']
        if rl:
            back = [w for w in vols if w['block'] == v['target_block'] and w['name'] == rl['name'] and w['pos'] == rl['pos']]
            if back:
                v['pair'] = back[0]['id']
        v['order'] = _order(v, by_id.get(v['pair']) if v['pair'] else None)
        if v['cls'] == 'TELEPORT':
            v['fix'] = _fix(v, by_id.get(v['pair']) if v['pair'] else None, GAP)
    groups = [dict(name=k, blocks=b) for k, b in GROUPS.items()]
    return dict(kind='todct-sections', version=1, blocks=[short(e) for e in entries], volumes=vols, groups=groups,
                teleports=sum(1 for v in vols if v['cls'] == 'TELEPORT'))


def _dir(v, w):
    """Horizontal unit direction across the border: for a teleport loader (its box comes first) from this box towards
    the other block's return box; for a walk loader from the return box towards this one (it lies beyond)."""
    if not w:
        return None
    d = [w['pos'][0] - v['pos'][0], w['pos'][2] - v['pos'][2]]
    if v.get('cls') != 'TELEPORT' and not v.get('teleports'):
        d = [-d[0], -d[1]]
    L = math.hypot(*d)
    return [d[0] / L, d[1] / L] if L > 1e-6 else None


def _order(v, w, d=None):
    """Box order along the border direction: 'walk' when this exit box lies beyond the other block's return box (the
    player is past it after the swap), 'wrong' when it comes first (the engine must teleport the player)."""
    d = d or _dir(v, w)
    if not d or not w:
        return None
    s = (v['pos'][0] - w['pos'][0]) * d[0] + (v['pos'][2] - w['pos'][2]) * d[1]
    ev = _extent(v['size'], v['rot'] or [0, 0, 0, 1], d, v['radius'])
    ew = _extent(w['size'], w['rot'] or [0, 0, 0, 1], d, w['radius'])
    gap = s - ev - ew
    return dict(dir=[round(d[0], 4), round(d[1], 4)], along=round(s, 2), gap=round(gap, 2),
                state='walk' if gap > 0 else 'wrong')


def _fix(v, w, gap):
    """T1: empty Teleport_to on both loaders, move this box past the other along the border direction."""
    if not w:
        return dict(possible=False, why='no return loader found in %s' % v.get('target_block'))
    d = _dir(v, w)
    if not d:
        return dict(possible=False, why='the two boxes share a centre')
    ev = _extent(v['size'], v['rot'] or [0, 0, 0, 1], d, v['radius'])
    ew = _extent(w['size'], w['rot'] or [0, 0, 0, 1], d, w['radius'])
    s_now = (v['pos'][0] - w['pos'][0]) * d[0] + (v['pos'][2] - w['pos'][2]) * d[1]
    t = (ew + ev + gap) - s_now                   # how far to move v along d
    new = [round(v['pos'][0] + d[0] * t, 3), v['pos'][1], round(v['pos'][2] + d[1] * t, 3)]
    ops = [dict(op='set_teleport', entry=v['entry'], frag=a['frag'], node=a['node'], value='') for a in v['actions'] if a['teleport']]
    ops += [dict(op='set_teleport', entry=w['entry'], frag=a['frag'], node=a['node'], value='') for a in w['actions'] if a['teleport']]
    off = [round(v['pos'][j] - (v.get('node_pos') or v['pos'])[j], 4) for j in range(3)]
    ops.append(dict(op='move_loader', entry=v['entry'], frag=v['frag'], node=v['node'], pos=new,
                    centre_offset=off if any(abs(x) > 1e-4 for x in off) else None,
                    border=dict(dir=[round(d[0], 6), round(d[1], 6)], other=w['id'])))
    return dict(possible=True, moves=v['id'], move_by=round(t, 2), new_pos=new, other=w['id'], gap=gap, ops=ops,
                note='Both blocks must hold the ground between the boxes (the bridge road is in both Downtown 01 and '
                     'Harbour 01; the tunnel and the farm pass need a look, seamless doc 1.3).')


def fix_teleport(cat, vid, gap=GAP):
    v = next((x for x in cat['volumes'] if x['id'] == vid), None)
    if v is None:
        raise SectionError('no loader volume %s' % vid)
    if v['cls'] != 'TELEPORT':
        raise SectionError('%s is not a teleport loader (%s)' % (v['name'], v['cls']))
    by = {x['id']: x for x in cat['volumes']}
    f = _fix(v, by.get(v['pair']), gap)
    if not f['possible']:
        raise SectionError(f['why'])
    return f['ops']


# ---------------------------------------------------------------------------------------------- build
def add_to_builder(B, ops, read):
    notes = []
    for o in ops:
        op = o['op']
        if op == 'set_teleport':
            B.set(o['entry'], o['frag'], o['node'], 'Teleport_to', o.get('value', ''))
        elif op == 'move_loader':
            pos = o['pos']
            if o.get('centre_offset'):
                pos = [pos[j] - o['centre_offset'][j] for j in range(3)]
            B.move(o['entry'], o['frag'], o['node'], pos=pos)
        elif op == 'add_section':
            notes += _add_section(B, o, read)
        else:
            raise SectionError('unknown section op %r' % op)
    return notes


def _map_folder_nodes(read):
    """Overdose.scene: the Maps folders (database_Map_ID / database_SubMap_ID), common(Node), load screens."""
    M = tools.load()
    ft, fe, tb = M.ft, M.fe, M.tb
    T = ft.types()
    raw = read(MAIN)
    bi = BE.BlockInfo(MAIN, raw)
    scene = BE.frag_name(bi.frs, 'Overdose.scene')
    d = bi.doc(scene)
    out = dict(scene=scene, folders={}, common=None)
    for n in d.created_ids():
        ty = d.type_of(n) or ''
        if ty.startswith('database_SubMap_ID') or ty.startswith('database_Map_ID'):
            out['folders'][d.get(n, 'name')] = dict(node=BE.hx(n), type=ty, parent=BE.hx(d.get(n, 'parent') or 0),
                                                    specific_id=d.get(n, 'Specific_ID'), fragment=d.get(n, 'fragment'))
        if ty == 'common(Node)':
            out['common'] = BE.hx(n)
    ls = BE.frag_name(bi.frs, 'LoadScreens.fragment')
    dl = bi.doc(ls)
    out['loadscreens'] = dict(frag=ls, entries={})
    for n in dl.created_ids():
        if (dl.get(n, 'name') or '') == 'Sub_Maps_Loadscreens':
            out['loadscreens']['folder'] = BE.hx(n)
        if (dl.type_of(n) or '').startswith('database_SubMap_LoadScreen'):
            out['loadscreens']['entries'][dl.get(n, 'Sub_Map')] = BE.hx(n)
    return out


def _loader_template(entry, raw):
    """A shipped loader subtree of the block (root + action + sprites), or None."""
    L, _ = scan(entry, raw)
    for l in L:
        if l['root'] and l['root']['type'] == 'Trigger_Root(CollisionBox)' and not l['teleport']:
            return l
    return L[0] if L else None


def _add_section(B, o, read):
    """New submap = renamed copy of a source submap (same-length name), registered beside the map's MAINMAP_ folder,
    with loaders both ways. Mirrors package S1 of docs/subsystem_level_streaming.md 7."""
    notes = []
    src = full(o['source_submap'])
    m = re.match(r'submap(\d\d)_(map\d\d_.+)\.submap$', short(src))
    if not m:
        raise SectionError('source must be a submapNN_mapMM_*.submap block')
    nn = '%02d' % int(o['new_index'])
    new_entry = SHARED + 'submap%s_%s.submap' % (nn, m.group(2))
    try:
        read(new_entry)
        raise SectionError('%s already exists' % short(new_entry))
    except SectionError:
        raise
    except Exception:                                   # noqa: BLE001
        pass
    info = _map_folder_nodes(read)
    src_folder = next((k for k, v in info['folders'].items() if v['fragment'] and v['fragment'].split('/')[-1].lower()
                       == short(src).replace('.submap', '.fragment')), None)
    if src_folder is None:
        raise SectionError('no database_SubMap_ID folder for %s' % short(src))
    sf = info['folders'][src_folder]
    old_root = sf['fragment'].split('/')[-1]
    new_root = re.sub(r'^SUBMAP\d\d', 'SUBMAP' + nn, old_root, flags=re.I)
    new_name = new_root[:-len('.fragment')]
    B.new_block(new_entry, src, rename_root=(old_root, new_root), localized=True)
    used = sorted(v['specific_id'] for v in info['folders'].values() if v['type'].startswith('database_SubMap_ID'))
    sid = o.get('specific_id')
    if sid is None:
        sid = max(used) + 1
    raise_max = sid >= 21
    if raise_max:
        B.set(MAIN, info['scene'], info['common'], 'SUBMAPS_MAX', sid + 1)
        notes.append('common.SUBMAPS_MAX 21 -> %d (DB_SUBMAP_LIST, the radar table and the load-screen list are sized '
                     'by it; the radar shows no location for id %d)' % (sid + 1, sid))
    else:
        notes.append('Specific_ID %d reused: missions, taxis and radar keyed to it now load %s' % (sid, new_name))
    B.append(MAIN, o['id'] + '_folder', (MAIN, info['scene'], sf['node']), parent=('ref', info['scene'], sf['parent']),
             name=new_name, sets={'fragment': sf['fragment'].rsplit('/', 1)[0] + '/' + new_root, 'Specific_ID': sid})
    ls = info['loadscreens']
    tmpl_ls = ls['entries'].get(sf['specific_id'])
    if tmpl_ls and ls.get('folder'):
        B.append(MAIN, o['id'] + '_loadscreen', (MAIN, ls['frag'], tmpl_ls), parent=('ref', ls['frag'], ls['folder']),
                 deep=True, name='%s_loadscreen' % new_name, sets={'Sub_Map': sid})
    # loaders: into the new section from the source submap (or its map block), and back
    map_entry = full(o.get('map_entry') or 'mainmap_%s.map' % m.group(2))
    src_raw = read(src)
    tpl = _loader_template(src, src_raw) or _loader_template(map_entry, read(map_entry))
    if tpl is None:
        raise SectionError('no loader to copy in %s or its map block' % short(src))

    def can_take(entry, raw):
        try:
            BE.BlockInfo(entry, raw).last_fragment()
            return True
        except BE.BuildError as e:
            notes.append(str(e))
            return False
    for side, spec, home, target in (('in', o['loader_in'], src, new_name), ('back', o['loader_back'], new_entry, src_folder)):
        here = home
        if not can_take(src, src_raw):               # the copy has the same fragments as the source
            here = map_entry
            notes.append('loader %s goes into %s (the map block is resident with every submap of the map)'
                         % (side, short(map_entry)))
        yaw = math.radians(float(spec.get('yaw') or 0.0))
        sz = [float(x) for x in spec.get('size') or (12.0, 6.0, 2.0)]
        B.append(here, '%s_loader_%s' % (o['id'], side), (tpl['entry'], tpl['frag'], tpl['root']['node']), deep=True,
                 parent=None, name='TriggerLoad_' + target, pos=spec['pos'],
                 rot=[0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)],
                 sets={'width': sz[0], 'height': sz[1], 'length': sz[2]},
                 child_sets=[{'type': 'Trigger_Activate_Load_Unload_Save(NodeLogical)',
                              'set': {'TargetName': target, 'name': 'ActionLoad_' + target, 'Teleport_to': ''}}])
    notes.append('new section %s (id %d) = copy of %s' % (new_name, sid, short(src)))
    return notes


# ---------------------------------------------------------------------------------------------- verification
def verify(cat_before, ops, out, read):
    """transitions.catalog on the built blocks (+ unchanged ones of the catalogue) and the box-order check."""
    entries = [full(b) for b in cat_before['blocks']]

    def read2(e):
        return out[e] if e in out else read(e)
    after = catalog(entries, read2)
    moved = {o['node']: o for o in ops if o['op'] == 'move_loader'}
    cleared = {o['node'] for o in ops if o['op'] == 'set_teleport'}
    checks = []
    by_b = {v['id']: v for v in cat_before['volumes']}
    by_a = {v['id']: v for v in after['volumes']}
    for vid, v in by_b.items():
        touched = v['node'] in moved or any(a['node'] in cleared for a in v['actions'])
        if not touched:
            continue
        a = by_a.get(vid)
        if a is None:
            checks.append(('FAIL', '%s: volume missing after the build' % v['name']))
            continue
        checks.append(('PASS' if a['cls'] == 'WALK' else 'FAIL', '%s (%s): %s -> %s (transitions.catalog), return loader %s m'
                       % (v['name'], v['block'], v['cls'], a['cls'], (a['return_loader'] or {}).get('dist'))))
        if v['node'] in moved:
            ok = all(abs(x - y) < 1e-3 for x, y in zip(a['pos'], moved[v['node']]['pos']))
            checks.append(('PASS' if ok else 'FAIL', '%s centre now %s' % (v['name'], a['pos'])))
        o = {}
        if v['node'] in moved and moved[v['node']].get('border'):
            bd = moved[v['node']]['border']
            o = _order(a, by_a.get(bd['other']), bd['dir']) or {}
        if v['node'] in moved and o:
            checks.append(('PASS' if o.get('state') == 'walk' else 'FAIL',
                           '%s lies %.1f m past %s along the road (gap %.1f m): after the swap the return box is behind'
                           % (v['name'], o['along'], (by_a.get(moved[v['node']]['border']['other']) or {}).get('name'), o['gap'])))
    before_tp = cat_before['teleports']
    res = 'PASS' if checks and all(c[0] == 'PASS' for c in checks) else 'FAIL'
    return dict(result=res, checks=checks, teleports_before=before_tp, teleports_after=after['teleports'],
                catalog_after=after)


# ---------------------------------------------------------------------------------------------- split planner
def split_plan(entry, raw, axis='x', at=0.0):
    """Read-only (docs/subsystem_level_streaming.md 6): what a cut of the section at a plane would divide."""
    M = tools.load()
    smt = tools.load_more('submaptool')
    ft = M.ft
    T = ft.types()
    import unittest.mock as um
    with um.patch.object(ft.archive(), 'read', lambda e, _r=raw: _r):
        r = smt.scan_block(entry, T, positions=True)
    ax = 'xyz'.index(axis)
    side = collections.Counter()
    per_cat = collections.defaultdict(collections.Counter)
    pts = []
    for e in r['_ents']:
        if not any(abs(x) > 1e-3 for x in e['p']):
            continue
        s = 'A' if e['p'][ax] < at else 'B'
        side[s] += 1
        per_cat[e['c']][s] += 1
        if e['c'] in ('model', 'collision_box', 'trigger_volume', 'placeholder', 'route'):
            pts.append([round(e['p'][0], 1), round(e['p'][2], 1), e['c'][0], s])
    groups = collections.defaultdict(set)
    for e in r['_ents']:
        if e['c'] == 'route' and any(abs(x) > 1e-3 for x in e['p']):
            groups[(e['f'], e['par'])].add('A' if e['p'][ax] < at else 'B')
    straddle = []
    for e in r['_ents']:
        if e['c'] == 'trigger_volume' and e['size'] and e['size'][0]:
            half = max(x or 0 for x in e['size']) / 2.0
            if abs(e['p'][ax] - at) < half:
                straddle.append(dict(name=e['name'], pos=[round(x, 2) for x in e['p']]))
    return dict(kind='todct-split-plan', entry=entry, block=short(entry), axis=axis, at=at, placed_entities=dict(side),
                by_category={k: dict(v) for k, v in per_cat.items()}, route_groups=len(groups),
                routes_crossing=sum(1 for v in groups.values() if len(v) == 2), trigger_volumes_straddling=straddle,
                loaders_now=len(r['loaders']), points=pts[:20000],
                not_solved=['removing the far half shifts node indices of the block (saves made inside it break; the save '
                            'editor can migrate them)', 'assets are not pruned (both halves keep every model and texture)',
                            'names: traffic, pedestrians, missions and intermissions find entities by name; radar, taxis, '
                            'ZAP and load screens key on Specific_ID', 'loaders on both sides with a gap; trigger volumes and '
                            'routes that straddle the plane'],
                read_only=True)
