"""The ceiling ledger: for every limit in limits.json, vanilla + installed packages + the current project = used, against the value.

  live    computed at once from the project (the op list, the collision sets, the mission and new-map projects): nodes added per
          block, placed cars, new mission slots, new map ids, archive slots, text lengths, collision piece sizes, coordinates, box sizes.
  check   filled from the build report of a Check: INFO bytes after the rewrite against the MAIN_ASSETS pool (P8), the largest
          payload of a block (P5), the zip size (P2). Without a Check these rows are grey ("run Check").
  grey    a limit whose confidence is UNKNOWN, a rule that has no number, or a number nothing measures yet. Never green.

The colours and the refuse/warn decision live in limits.py (one table: limits.json). The vanilla numbers per block are cached next to the
level cache (<block dir>/ledger.json).
"""
import json
import os

from . import limits, checks, paths

NEAR = 100.0                   # metres: placed cars this close to each other share the live-car limit (checks.cars)

# which screen a limit is shown on (the meter strip and the views). 'all' = every screen
SCOPES = dict(
    M1=('level',), P6=('level',), L1=('level',), L4=('level',), L15=('level',), L15_index=('level',), L16_pos=('level',), L16_box=('level',),
    P8=('level',), P5=('level',), P2=('level', 'mission', 'newmap'), P1=('level', 'mission', 'newmap'),
    L7=('mission',), L8=('newmap',), L11=('mission',), Q_main=('newmap',), Q_aux=('newmap',), S_nodes=('newmap',), L5=('newmap',),
    L8_sections=('newmap',),
    G1=('newmap',), G2=('newmap',), G3=('newmap',),
)
# where a click goes (the Problems panel and the meters)
JUMP = dict(G1='newmaps', G2='newmaps', G3='newmaps', M1='import', P6='textures', L1='level', L4='level', L15='collision', L15_index='collision', L16_pos='level', L16_box='level', P8='level',
            P5='level', P2='mods', P1='mods', L7='mtpl', L8='newmaps', L11='mtpl', Q_main='newmaps', Q_aux='newmaps', S_nodes='newmaps', L5='newmaps',
            L8_sections='newmaps')
HEAVY = ('P8', 'P5', 'P2')


# ------------------------------------------------------------------------------------------------ vanilla baseline per block
def baseline(ws, entry, payload=False):
    """Nodes, INFO bytes, block bytes (and the largest payload on request) of the block as the game ships it. Cached beside level.json."""
    key = ws.block_key(entry)
    p = os.path.join(ws.block_dir(key), 'ledger.json')
    try:
        with open(p, encoding='utf-8') as f:
            j = json.load(f)
        if j.get('version') == 1 and (not payload or 'max_payload' in j):
            return j
    except Exception:
        j = None
    L = ws.level_json(entry)
    j = dict(version=1, entry=entry, nodes=L['nodes'], info_bytes=L['info_bytes'], block_bytes=L['block_bytes'], next_runtime=L['next_runtime'])
    if payload:
        try:
            sizes = ws.block_level(entry).b.sizes
            j['max_payload'] = max(sizes) if len(sizes) else 0
        except Exception:
            pass
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(j, f)
    os.replace(p + '.part', p)
    return j


def remember(ws, entry, L):
    """Write the baseline of a block that was just read (L = its level json), so the ledger knows every level that was opened."""
    try:
        p = os.path.join(ws.block_dir(ws.block_key(entry)), 'ledger.json')
        if not os.path.exists(p):
            with open(p + '.part', 'w', encoding='utf-8') as f:
                json.dump(dict(version=1, entry=entry, nodes=L['nodes'], info_bytes=L['info_bytes'], block_bytes=L['block_bytes'],
                               next_runtime=L['next_runtime']), f)
            os.replace(p + '.part', p)
    except Exception:
        pass


def known_baselines(ws):
    """Every baseline written so far (a level that was opened)."""
    out = []
    root = os.path.join(paths.cache_dir(), 'blocks')
    try:
        for d in os.listdir(root):
            p = os.path.join(root, d, 'ledger.json')
            if os.path.isfile(p):
                try:
                    with open(p, encoding='utf-8') as f:
                        out.append(json.load(f))
                except Exception:
                    pass
    except OSError:
        pass
    return out


# ------------------------------------------------------------------------------------------------ the installed packages
def installed_ops(ws, skip_id=None):
    """-> (level ops, collision sets, mod ids) of the mods installed in the game folder (the current mod is left out: it replaces itself)."""
    from . import mods
    if not ws.game:
        return [], [], []
    ids = [i for i in (mods.installed_state(ws).get('mods') or []) if i != skip_id]
    ops, coll = [], []
    for i in ids:
        try:
            m = mods.get_mod(i)
        except Exception:
            continue
        ops += m.get('level') or []
        coll += m.get('collision') or []
    return ops, coll, ids


def installed_assets(ws, skip_id=None):
    """-> (models, textures) of the mods installed in the game folder (the current mod is left out)."""
    from . import mods
    if not ws.game:
        return [], []
    ms, ts = [], []
    for i in [i for i in (mods.installed_state(ws).get('mods') or []) if i != skip_id]:
        try:
            m = mods.get_mod(i)
        except Exception:
            continue
        ms += m.get('models') or []
        ts += m.get('textures') or []
    return ms, ts


def _row_base(lid):
    r = limits.get(lid)
    return dict(id=lid, label=r['label'], value=r['value'], unit=r['unit'], scope=r['scope'], effect=r['effect'],
                confidence=r['confidence'], source=r['source'], enforce=limits.enforce(lid),
                max=limits.meter_max(lid) if isinstance(limits.meter_max(lid), (int, float)) else None,
                note=r.get('meter_note'), kinds=list(SCOPES.get(lid, ())), jump=JUMP.get(lid))


def _fill(row, used, parts=None, items=None, mode='live', reason=None):
    row['used'] = used
    row['parts'] = parts or {}
    row['items'] = items or []
    row['mode'] = mode
    row['status'] = limits.status(row['id'], used)
    if row['status'] == 'grey':
        row['reason'] = reason or ('not measured' if (limits.is_unknown(limits.get(row['id'])) or row['max'] is None) else 'run Check')
    row['pct'] = round(100.0 * used / row['max'], 1) if (used is not None and row['max']) else None
    return row


# ------------------------------------------------------------------------------------------------ the live meters
def _blocks_with_adds(ops):
    out = {}
    for o in ops:
        if o.get('op') == 'add' and o.get('entry'):
            out[o['entry']] = out.get(o['entry'], 0) + 1
    return out


def _is_car(o):
    v = o.get('view') or {}
    t = v.get('type') or ''
    return o.get('op') == 'add' and v.get('cat') == 'vehicle' and t.startswith('vehicle_placeholder') and o.get('pos')


def meter_nodes(ws, pkg_ops, ops, heavy):
    """L1: per block, vanilla nodes + added by the installed mods + added by this project. One node per added object until a Check measures
    the real count (a template can bring a small subtree)."""
    row = _row_base('L1')
    a, b = _blocks_with_adds(pkg_ops), _blocks_with_adds(ops)
    measured = (heavy or {}).get('L1') or {}
    items = []
    for e in sorted(set(a) | set(b)):
        try:
            v = baseline(ws, e)['nodes']
        except Exception:
            continue
        proj = measured.get(e, b.get(e, 0))
        items.append(dict(label=e.split('/')[-1], entry=e, vanilla=v, packages=a.get(e, 0), project=proj, used=v + a.get(e, 0) + proj,
                          jump=dict(screen='level', entry=e)))
    if not items:
        base = [x['nodes'] for x in known_baselines(ws) if 'nodes' in x]
        if not base:
            return _fill(row, None, reason='open a level first')
        return _fill(row, max(base), dict(vanilla=max(base), packages=0, project=0), [], 'live')
    items.sort(key=lambda x: -x['used'])
    w = items[0]
    return _fill(row, w['used'], dict(vanilla=w['vanilla'], packages=w['packages'], project=w['project']), items,
                 'check' if measured else 'live')


def _cluster_max(positions):
    best = 0
    import math
    for p in positions:
        best = max(best, sum(1 for q in positions if math.dist(p, q) <= NEAR))
    return best


def meter_cars(ws, pkg_ops, ops):
    """L4: the most placed cars within 100 m of each other, per block (vanilla placed cars + packages + this project)."""
    row = _row_base('L4')
    blocks = {}
    for tag, lst in (('packages', pkg_ops), ('project', ops)):
        for o in lst:
            if _is_car(o):
                blocks.setdefault(o['entry'], dict(packages=[], project=[]))[tag].append(o['pos'])
    items = []
    for e, d in blocks.items():
        van = []
        try:
            L = ws.level_json(e)
            van = [x['pos'] for x in L['entities'] if x['cat'] == 'vehicle' and (x['type'] or '').startswith('vehicle_placeholder')
                   and not (x.get('sub') or {}).get('Traffic_System_Placeholder')]
        except Exception:
            pass
        v, p, q = _cluster_max(van), _cluster_max(van + d['packages']), _cluster_max(van + d['packages'] + d['project'])
        items.append(dict(label=e.split('/')[-1], entry=e, vanilla=v, packages=p - v, project=q - p, used=q, jump=dict(screen='level', entry=e)))
    if not items:
        return _fill(row, 0, dict(vanilla=0, packages=0, project=0))
    items.sort(key=lambda x: -x['used'])
    w = items[0]
    return _fill(row, w['used'], dict(vanilla=w['vanilla'], packages=w['packages'], project=w['project']), items)


def _strings(v, out, path=''):
    if isinstance(v, str):
        out.append((path, v))
    elif isinstance(v, dict):
        for k, x in v.items():
            if k in ('id', 'block', 'entry', 'host', 'type', 'newmap_id', 'format', 'created', 'updated', 'kind'):
                continue
            _strings(x, out, path + '/' + str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _strings(x, out, path + '/' + str(i))


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


def meter_text(project):
    """L11: the longest text in a mission project (UTF-16 units; the engine ends a string at a unit with low byte 0)."""
    row = _row_base('L11')
    found = []
    _strings((project or {}).get('missions') or [], found)
    if not found:
        return _fill(row, 0, dict(vanilla=0, packages=0, project=0))
    ranked = sorted(((utf16_len(s), p, s) for p, s in found), reverse=True)
    items = [dict(label=s[:40], used=n, project=n, jump=dict(screen='mtpl', path=p)) for n, p, s in ranked[:5]]
    return _fill(row, ranked[0][0], dict(vanilla=0, packages=0, project=ranked[0][0]), items)


def meter_collision(sets, pkg_sets):
    rows = []
    vmax, imax = 0, 0
    items_v, items_i = [], []
    for tag, lst in (('packages', pkg_sets), ('project', sets)):
        for s in lst or []:
            if s.get('visual_only'):
                continue
            for i, p in enumerate(s.get('pieces') or []):
                nv = len(p.get('verts') or [])
                ni = sum(len(f) + 1 for f in p.get('faces') or [])
                vmax, imax = max(vmax, nv), max(imax, ni)
                jump = dict(screen='collision', set=s.get('id'), piece=i)
                items_v.append(dict(label='%s piece %d' % (s.get('id'), i), used=nv, **{tag: nv}, jump=jump))
                items_i.append(dict(label='%s piece %d' % (s.get('id'), i), used=ni, **{tag: ni}, jump=jump))
    for lid, mx, its in (('L15', vmax, items_v), ('L15_index', imax, items_i)):
        its.sort(key=lambda x: -x['used'])
        rows.append(_fill(_row_base(lid), mx, dict(vanilla=0, packages=0, project=mx), its[:5]))
    return rows


def meter_assets(models, texts, pkg_models, pkg_texts):
    """M1: most vertices in one sub-mesh of an imported model. P6: the biggest texture payload (a model's textures and edited game textures)."""
    from todct import texture as TX
    rows = []
    v_items, t_items = [], []
    for tag, ms, ts in (('packages', pkg_models, pkg_texts), ('project', models, texts)):
        for m in ms or []:
            st = m.get('stats') or {}
            jump = dict(screen='import', model=m.get('id'))
            v_items.append(dict(label=m.get('name') or m.get('id'), used=st.get('max_mesh_vertices') or 0, **{tag: st.get('max_mesh_vertices') or 0}, jump=jump))
            t_items.append(dict(label=m.get('name') or m.get('id'), used=st.get('largest_texture') or 0, **{tag: st.get('largest_texture') or 0}, jump=jump))
        for t in ts or []:
            try:
                size = TX.payload_size(t['fmt'], int(t['w']), int(t['h']), TX.full_chain(int(t['w']), int(t['h'])))
            except Exception:                                  # noqa: BLE001
                continue
            t_items.append(dict(label=t['target'].split('/')[-1], used=size, **{tag: size}, jump=dict(screen='textures', texture=t['target'])))
    for lid, its in (('M1', v_items), ('P6', t_items)):
        its.sort(key=lambda x: -x['used'])
        top = its[0]['used'] if its else 0
        pk = max([x['used'] for x in its if 'packages' in x] + [0])
        rows.append(_fill(_row_base(lid), top, dict(vanilla=0, packages=pk, project=top if top > pk else 0), its[:5]))
    return rows


def meter_ranges(pkg_ops, ops):
    """L16: furthest position and longest box side."""
    out = []
    far = [0.0, None]
    side = [0.0, None]
    for tag, lst in (('packages', pkg_ops), ('project', ops)):
        for o in lst:
            p = o.get('pos')
            if p:
                m = max(abs(x) for x in p)
                if m > far[0]:
                    far = [m, o]
            st = o.get('set') or {}
            vs = [st.get(k) for k in ('width', 'height', 'length') if st.get(k) is not None]
            if o.get('op') == 'set' and o.get('prop') in ('width', 'height', 'length'):
                vs.append(o.get('value'))
            if vs and max(float(v) for v in vs) > side[0]:
                side = [max(float(v) for v in vs), o]
    for lid, (val, o) in (('L16_pos', far), ('L16_box', side)):
        its = [dict(label=(o.get('name') or o.get('node') or o.get('uid') or ''), used=round(val, 2), project=round(val, 2),
                    jump=checks._op_ref(o))] if o else []
        out.append(_fill(_row_base(lid), round(val, 2), dict(vanilla=0, packages=0, project=round(val, 2)), its))
    return out


def meter_slots(ws):
    """P1: archive slots as the engine counts them, now. Vanilla = the game's own archives, packages = ours."""
    row = _row_base('P1')
    if not ws.game:
        return _fill(row, None, reason='pick the game folder')
    from . import archives, game as gm
    fs = gm.filesystem_line(gm.read_configpc(ws.game.folder)) or list(gm.DEFAULT_FS)
    sc = archives.slot_count(ws.game.folder, fs)
    own = [u for u in sc['users'] if gm.is_own_archive(u)]
    van = sc['count'] - len(own)
    items = [dict(label=u, used=1) for u in sc['users']]
    return _fill(row, sc['count'], dict(vanilla=van, packages=len(own), project=0), items)


def meter_missions(ws, project, pid):
    row = _row_base('L7')
    from . import missions_tpl as MT
    pk = 0
    if ws.game:
        try:
            for k, p in MT.installed(ws.game.folder).get('projects', {}).items():
                if k != pid:
                    pk += len(p.get('indices', {}))
        except Exception:
            pass
    mine = len((project or {}).get('missions') or [])
    return _fill(row, pk + mine, dict(vanilla=0, packages=pk, project=mine), [], 'live')


def meter_maps(ws, params, pid):
    row = _row_base('L8')
    from . import newmap
    van = len((ws.catalog or {}).get('maps') or [])
    pk = 0
    if ws.game:
        try:
            pk = sum(len((v.get('params') or {}).get('maps') or [1]) for k, v in newmap.installed(ws.game.folder).items() if k != pid)
        except Exception:
            pk = 0
    mine = len((params or {}).get('maps') or [])
    out = _fill(row, van + pk + mine, dict(vanilla=van, packages=pk, project=mine), [])
    if out['max'] and out['used'] > out['max']:
        out['status'] = 'amber'                        # past the measured 13 the game is simply not measured: a warning, never a stop
        out['reason'] = 'more than %d maps is not measured' % out['max']
    return out


# ------------------------------------------------------------------------------------------------ new-map pools (wave 3)
# Quadtree use per section. The densest shipped section (Downtown SUBMAP01) holds 5,886 nodes and used 7,910 of the 10,000 main and
# 9,808 of the 12,200 aux quadtree nodes at its peak (M0 measurements, Q5): about 1.34 and 1.67 per node. New content is an ESTIMATE
# from that ratio on top of the section it is cloned from.
NODE_MAIN, NODE_AUX = 1.34, 1.67
SOURCE_POOLS = {                         # clone source -> (main, aux) peak of the section as shipped (M0 table: the train section)
    'map10_runawaytrain': (1904, 3645), 'map08_hacienda': (1831, 6015)}
DROPPED_POOLS = (250, 250)               # a map that dropped its source content (new geometry): a bare section plus the 98-node vehicle database it keeps
HOST_POOLS = {                           # shipped sections an entrance or a section copy sits in (M0 table)
    'submap01_map02_lostoros_downtown.submap': (7910, 9808), 'submap03_map02_lostoros_downtown.submap': (3702, 5154),
    'mainmap_map02_lostoros_downtown.map': (7910, 9808), 'mainmap_map04_lostoros_train_harbour.map': (2515, 2284)}
ENTRANCE_NODES = 12                      # a loader pair: two roots, two conditions, two actions, four sprites
ENEMY_NODES = 7                          # character, weapon, path and three track points
ENEMY_RADIUS = 45.0                      # a placeholder is collected inside about 45 m of the camera
CHAR_FREE, CHAR_MISSION = 8, 6


def _map_nodes(m):
    """Nodes a map's recipe adds (not counting the source section)."""
    n = len(m.get('walls') or []) + len(m.get('teleports') or []) + len(m.get('models') or []) + len(m.get('pickups') or [])
    n += len(m.get('givers') or []) + (1 if m.get('savepoint') else 0) + 3 + 2          # arrival, return pair (2 x 5 counted below)
    n += 10
    n += ENEMY_NODES * (len(m.get('enemies') or []) + len(m.get('dotd_enemies') or []))
    n += 8 * len(m.get('dotd') or [])
    geo = m.get('new_geometry') or {}
    n += len(geo.get('placements') or [])
    return n


def _entrances(m):
    es = list(m.get('entries') or [])
    if m.get('entry'):
        es.append(m['entry'])
    return es


def _cluster(positions, radius):
    import math
    best = 0
    for p in positions:
        best = max(best, sum(1 for q in positions if math.dist(p, q) <= radius))
    return best


def _section_rows(params, label_prefix=''):
    """-> [dict(label, main, aux, block)] one per section the project builds or touches."""
    rows = []
    for m in (params or {}).get('maps') or []:
        if m.get('placement') == 'extension':
            host = ((m.get('host') or {}).get('block') or '').lower()
            bm, ba = HOST_POOLS.get(host, (7910, 9808))      # a copy of the whole host section
            add = 12 + 5 * len(m.get('walls') or [])
            rows.append(dict(label='%s%s' % (label_prefix, m.get('name') or 'Section'), main=bm + add * NODE_MAIN, aux=ba + add * NODE_AUX, block=None))
            continue
        geo = m.get('new_geometry') or {}
        bm, ba = DROPPED_POOLS if geo.get('drop_source_content', True) and geo else SOURCE_POOLS.get(m.get('source'), (1904, 3645))
        n = _map_nodes(m)
        rows.append(dict(label='%s%s' % (label_prefix, m.get('name') or 'Map'), main=bm + n * NODE_MAIN, aux=ba + n * NODE_AUX, block=None))
    return rows


def _host_additions(params_list):
    """{host block: nodes the projects add to it}: entrances of every project that point at it (and the way into extension sections)."""
    add = {}
    for params in params_list:
        for m in (params or {}).get('maps') or []:
            if m.get('placement') == 'extension':
                b = ((m.get('host') or {}).get('block') or '').lower()
                add[b] = add.get(b, 0) + 6
                continue
            for e in _entrances(m):
                b = (e.get('block') or '').lower()
                add[b] = add.get(b, 0) + ENTRANCE_NODES + (6 if e.get('lock') else 0) + (6 if e.get('back') and e['back'].get('spot') else 0)
    return add


def meter_newmap(ws, params, pid):
    """Q_main, Q_aux, S_nodes, L5 and L8_sections for a new-map project plus the installed ones."""
    from . import newmap, mapalloc
    others = []
    if ws.game:
        try:
            others = [v.get('params') for k, v in newmap.installed(ws.game.folder).items() if k != pid and v.get('params')]
        except Exception:
            others = []
    mine = params or {}
    secs = _section_rows(mine)
    for p in others:
        secs += _section_rows(p, 'installed: ')
    adds = _host_additions([mine] + others)
    for blk, n in adds.items():
        bm, ba = HOST_POOLS.get(blk, (7910, 9808))
        secs.append(dict(label='Host section (%s)' % blk.replace('.submap', '').replace('.map', '').replace('_', ' '), main=bm + n * NODE_MAIN,
                         aux=ba + n * NODE_AUX, block=blk))
    out = []
    for lid, key in (('Q_main', 'main'), ('Q_aux', 'aux')):
        row = _row_base(lid)
        items = sorted((dict(label=s['label'], used=round(s[key]), jump=dict(screen='newmaps')) for s in secs), key=lambda x: -x['used'])
        if not items:
            out.append(_fill(row, None, reason='no new map yet'))
            continue
        w = items[0]
        van = max([HOST_POOLS.get(s['block'], (0, 0))[0 if key == 'main' else 1] for s in secs if s['block']] + [0])
        out.append(_fill(row, w['used'], dict(vanilla=van, packages=0, project=max(0, w['used'] - van)) if van else dict(vanilla=0, packages=0, project=w['used']),
                         items, mode='estimate'))
    row = _row_base('S_nodes')
    chg = 0
    for p in [mine] + others:
        for m in (p or {}).get('maps') or []:
            chg += ENEMY_NODES * (len(m.get('enemies') or []) + len(m.get('dotd_enemies') or [])) + len(m.get('pickups') or []) \
                + len(m.get('givers') or []) + (1 if m.get('savepoint') else 0)
    out.append(_fill(row, chg, dict(vanilla=0, packages=0, project=chg), [], mode='estimate'))
    row = _row_base('L5')
    best, where = 0, None
    for m in mine.get('maps') or []:
        pts = [e['pos'] for e in (m.get('enemies') or []) + (m.get('dotd_enemies') or []) if e.get('pos')]
        c = _cluster([(p[0], p[2]) for p in pts], ENEMY_RADIUS) if pts else 0
        if c > best:
            best, where = c, m.get('name')
    items = [dict(label='%s: %d together; %d wait while a mission runs' % (where, best, max(0, best - CHAR_MISSION)), used=best)] if where and best > CHAR_MISSION else []
    out.append(_fill(row, best, dict(vanilla=0, packages=0, project=best), items, mode='estimate'))
    row = _row_base('L8_sections')
    alloc = mapalloc.read(ws.game.folder) if ws.game else {'owners': {}}
    key = mapalloc.key_of(mine, pid)
    taken = sum(len(o['maps']) + len(o['sections']) for k, o in alloc.get('owners', {}).items() if k != key)
    own = sum(1 for m in mine.get('maps') or [])
    used = mapalloc.SUB_BASE + taken + own
    out.append(_fill(row, used, dict(vanilla=mapalloc.SUB_BASE, packages=taken, project=own), []))
    return out


def meter_size(ws, heavy, pack_bytes=None):
    """P2: the pack on disk (installed) + the zip this project builds (after a Check)."""
    row = _row_base('P2')
    pk = pack_bytes
    if pk is None and ws.game:
        from . import game as gm
        p = os.path.join(ws.game.folder, gm.PACK_ZIP)
        pk = os.path.getsize(p) if os.path.exists(p) else 0
    h = (heavy or {}).get('P2')
    if h is None:
        if pk:
            return _fill(row, pk, dict(vanilla=0, packages=pk, project=0), [], 'live')
        return _fill(row, 0, dict(vanilla=0, packages=0, project=0), [], 'live')
    return _fill(row, (pk or 0) + h, dict(vanilla=0, packages=pk or 0, project=h), [], 'check')


def _heavy_row(lid, heavy, jump=None):
    row = _row_base(lid)
    h = (heavy or {}).get(lid)
    if h is None:
        return _fill(row, None, reason='run Check', mode='check')
    return _fill(row, h['used'], h.get('parts'), h.get('items'), 'check')


# ------------------------------------------------------------------------------------------------ the whole ledger
def mapgen_rows(stats):
    """Rows for what the map generators (todms/mapgen) add to a new map: M1 P6 L15 L15_index L1 and the generator rows G1-G3.
    stats: the `stats` of mapgen.expand_full (map name -> numbers) or one map's numbers. Each row says where its biggest share is."""
    if stats and 'map' in stats:
        stats = {stats['map']: stats}
    rows = []
    maps = list((stats or {}).items())

    def top(key):
        return max([s.get(key) or 0 for _, s in maps] + [0])

    def items(key, label=None):
        its = [dict(label=n, used=s.get(key) or 0, project=s.get(key) or 0, jump=dict(screen='newmaps')) for n, s in maps]
        its.sort(key=lambda x: -x['used'])
        return its[:5]
    chunk_hulls = max([c['hulls'] for _, s in maps for c in s.get('chunks') or []] + [0])
    for lid, used, its in (('M1', top('max_submesh_vertices'), items('max_submesh_vertices')),
                           ('P6', top('largest_texture'), items('largest_texture')),
                           ('L15', top('max_hull_vertices'), items('max_hull_vertices')),
                           ('L15_index', top('max_hull_indices'), items('max_hull_indices')),
                           ('L1', top('nodes_added'), items('nodes_added')),
                           ('G1', top('ground_materials'), items('ground_materials')),
                           ('G2', top('ground_triangles'), items('ground_triangles')),
                           ('G3', chunk_hulls, [])):
        rows.append(_fill(_row_base(lid), used, dict(vanilla=0, packages=0, project=used), its))
    return rows


def compute(ws, kind=None, project=None, pid=None, heavy=None):
    """Every row of limits.json with its measurement. kind: 'level' | 'mission' | 'newmap' | None (the whole install only).
    project: the mod (level), the mission project or the new-map params. heavy: the numbers a Check measured (see heavy_from_stats)."""
    pkg_ops, pkg_coll, pkg_ids = installed_ops(ws, skip_id=pid if kind == 'level' else None)
    pkg_models, pkg_texts = installed_assets(ws, skip_id=pid if kind == 'level' else None)
    ops = (project or {}).get('level') or [] if kind == 'level' else []
    coll = (project or {}).get('collision') or [] if kind == 'level' else []
    def safe(lids, fn, *args):
        try:
            r = fn(*args)
            return r if isinstance(r, list) else [r]
        except Exception:
            return [_fill(_row_base(l), None, reason='not measured') for l in lids]
    rows = {}
    gen = None
    if kind == 'newmap':                              # generator keys (terrain, roads, scatter ...) count as what they build
        try:
            from . import mapbuild
            gen = mapbuild.expanded(project)
        except Exception:
            gen = None
    for lids, fn, args in (
            (['L1'], meter_nodes, (ws, pkg_ops, ops, heavy)),
            (['L4'], meter_cars, (ws, pkg_ops, ops)),
            (['L15', 'L15_index'], meter_collision, (coll, pkg_coll)),
            (['L16_pos', 'L16_box'], meter_ranges, (pkg_ops, ops)),
            (['M1', 'P6'], meter_assets, ((project or {}).get('models') if kind == 'level' else [], (project or {}).get('textures') if kind == 'level' else [],
                                          pkg_models, pkg_texts)),
            (['L7'], meter_missions, (ws, project if kind == 'mission' else None, pid if kind == 'mission' else None)),
            (['L8'], meter_maps, (ws, project if kind == 'newmap' else None, pid if kind == 'newmap' else None)),
            (['L11'], meter_text, (project if kind == 'mission' else None,)),
            (['Q_main', 'Q_aux', 'S_nodes', 'L5', 'L8_sections'], meter_newmap, (ws, (gen['params'] if gen else project) if kind == 'newmap' else None, pid if kind == 'newmap' else None)),
            (['P1'], meter_slots, (ws,)),
            (['P2'], meter_size, (ws, heavy))):
        for r in safe(lids, fn, *args):
            rows[r['id']] = r
    for lid in ('P8', 'P5'):
        rows[lid] = _heavy_row(lid, heavy)
    if gen:
        for r in mapgen_rows(gen['stats']):
            if r['id'] in ('G1', 'G2', 'G3'):
                rows[r['id']] = r
    out = []
    for r in limits.rows():
        lid = r['id']
        if lid in rows:
            out.append(rows[lid])
        elif lid in ('P2_soft', 'P8_node'):
            continue
        else:
            out.append(_fill(_row_base(lid), None, mode='none', reason='not measured' if limits.is_unknown(r) or not isinstance(r['value'], (int, float)) else 'not measured'))
    return dict(rows=out, kind=kind, worst=worst(out, kind))


def worst(rows, kind=None, n=3):
    """The most used meters of the screen's kind, red first."""
    order = dict(red=0, amber=1, ok=2, grey=3)
    live = [r for r in rows if r['status'] != 'grey' and (not kind or kind in r['kinds'])]
    live.sort(key=lambda r: (order[r['status']], -(r['pct'] or 0)))
    return [r['id'] for r in live[:n]]


def refusals(rows):
    """The red rows that stop an install or an export: crash-class limits (limits.json enforce = refuse)."""
    return [r for r in rows if r['status'] == 'red' and r['enforce'] == 'refuse']


# ------------------------------------------------------------------------------------------------ the heavy part
def heavy_from_stats(ws, stats, build_rep, levels_by_entry, zip_path=None):
    """Numbers a Check measured: INFO after the rewrite against MAIN_ASSETS (P8), the largest payload (P5), the zip (P2), real node counts (L1).
    stats: what checks.run filled in."""
    out = {}
    blocks = stats.get('blocks') or {}
    if stats.get('p8'):
        van, grow = stats['p8']
        out['P8'] = dict(used=int(van + grow), parts=dict(vanilla=int(van), packages=0, project=int(grow)),
                         items=[dict(label=e.split('/')[-1], used=b['info_bytes'], project=b['info_bytes'], entry=e) for e, b in blocks.items()
                                if e.endswith(('.map', '.submap'))])
    if blocks:
        best, items, van_max = 0, [], 0
        for e, b in blocks.items():
            try:
                bl = baseline(ws, e, payload=True).get('max_payload') or 0
            except Exception:
                bl = 0
            van_max = max(van_max, bl)
            best = max(best, b['max_payload'])
            items.append(dict(label=e.split('/')[-1], entry=e, vanilla=bl, project=max(0, b['max_payload'] - bl), used=b['max_payload']))
        items.sort(key=lambda x: -x['used'])
        out['P5'] = dict(used=best, parts=dict(vanilla=van_max, packages=0, project=max(0, best - van_max)), items=items[:5])
    if zip_path and os.path.exists(zip_path):
        out['P2'] = os.path.getsize(zip_path)
    grafted = {}
    for b in (build_rep or {}).get('blocks') or []:
        if b.get('stage_b'):
            grafted[b['entry']] = sum(g['nodes'] for g in b['stage_b']['grafted'])
    if grafted:
        out['L1'] = grafted
    return out


def p8_from_pack(ws, zip_path):
    """P8 for a finished pack: per map (the map block and its sections resident together) the same estimate Check uses, from the INFO bytes
    and node counts of the blocks inside the zip. -> bytes of the worst map, or None when the blocks cannot be read."""
    import re
    import zipfile
    from . import level as lv
    groups = {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            for n in z.namelist():
                if not n.lower().endswith(('.map', '.submap')):
                    continue
                m = re.search(r'map(\d+)', n.lower())
                key = m.group(1) if m else n
                L = lv.BlockLevel(n, z.read(n), ws.T, ws.main_lookup)
                groups.setdefault(key, {})[n] = dict(info_bytes=len(L.b.info), nodes=len(L.instances))
        if not groups:
            return None
        return max(checks._estimate_main(ws, g) for g in groups.values())
    except Exception:
        return None
