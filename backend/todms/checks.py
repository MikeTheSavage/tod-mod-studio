"""The checker that runs before an export. Every rule names its source in the project docs.

  objects per section   save records pack a node index in 15 bits: 32,767 nodes per block
                        (docs/subsystem_level_streaming.md 5.2)
  memory budget         block INFO and scene nodes live in the 90 MiB MAIN_ASSETS pool; vanilla 24.5 MiB at The Ambush,
                        TOD HD about 78.6 MiB at Map03 (docs/subsystem_memory_pools.md 1); ~0.25 KiB per scene node
  hull sizes            collision boxes: full extents centred on the node (fragment writer 6); a model's collision only
                        registers inside its bounding sphere (subsystem_collision.md 11.4); sane sizes and positions
  save safety           saves address nodes by creation order; new nodes must come after every old one, removals shift
                        indices (subsystem_level_streaming.md 5.3, subsystem_vehicle_and_loco_limits.md)
  missing references    no dangling Entity values (fragtool verify), model paths that exist, missiontool's lint
  cars                  at most 4 placed cars are drivable at once, the 5th pooled shell is the script spare
                        (subsystem_vehicle_and_loco_limits.md 2)
"""
import math
import os

MAX_NODES = 32767
MAIN_ASSETS = 90 * 1024 * 1024
NODE_BYTES = 256
LIVE_CARS = 4


def item(level, area, title, detail=''):
    return dict(level=level, area=area, title=title, detail=detail)


def run(ws, mod_ops, build_rep, levels_by_entry):
    """mod_ops: the level ops checked; build_rep: build.build() result (with _outs); levels_by_entry: {entry: level
    json of the base} for the blocks in view."""
    from . import level as lv
    out = []
    outs = dict(build_rep.get('_outs', []))
    # ---------------------------------------------------------------- new collision (companion tool)
    for r in build_rep.get('collision') or []:
        for n in r.get('notes', []) + r.get('skipped', []):
            out.append(item('ok', 'collision', n))
        out.append(item('ok' if r.get('max_piece_vertices', 0) <= 255 else 'error', 'collision',
                        '%s: %d pieces, largest %d vertices (limit 255 per shape)' % (
                            r['map'], r['pieces'], r.get('max_piece_vertices', 0))))
    for blk in build_rep.get('blocks', []):
        for c in blk.get('collision') or []:
            sp = c.get('sphere') or {}
            out.append(item('ok', 'collision', '%s: %s +%d pieces, verified' % (
                blk['entry'].split('/')[-1], c['model'].split('/')[-1], c['pieces']),
                'record %d -> %d B; model sphere %.2f -> %.2f m; read-back within %.5f m; model writer checks: other '
                'records identical, every model round-trips, sphere covers the collision' % (
                    c['record_bytes'][0], c['record_bytes'][1], sp.get('radius_old', 0), sp.get('radius_new', 0),
                    c['readback_max_m'])))
    # ---------------------------------------------------------------- objects per section
    for e, raw in outs.items():
        try:
            L = lv.BlockLevel(e, raw, ws.T, ws.main_lookup)
            n = L.next_runtime - 1
        except Exception as ex:
            out.append(item('error', 'objects', '%s does not load in the level reader' % e.split('/')[-1], str(ex)))
            continue
        base_n = (levels_by_entry.get(e) or {}).get('next_runtime')
        base_n = base_n - 1 if base_n else None
        lvl = 'ok' if n <= MAX_NODES else 'error'
        out.append(item(lvl, 'objects', '%s: %d objects (limit %d)' % (e.split('/')[-1], n, MAX_NODES),
                        'was %s' % base_n if base_n is not None else ''))
    # ---------------------------------------------------------------- memory
    for e, raw in outs.items():
        base = levels_by_entry.get(e) or {}
        built_base = next((b.get('base_bytes') for b in build_rep['blocks'] if b['entry'] == e and b.get('base_bytes')), None)
        grow = len(raw) - (base.get('block_bytes') or built_base or len(raw))
        added_nodes = 0
        for blk in build_rep['blocks']:
            if blk['entry'] == e and blk.get('stage_b'):
                added_nodes += sum(g['nodes'] for g in blk['stage_b']['grafted'])
        if e.endswith(('.map', '.submap')):
            fill = _estimate_main(ws, levels_by_entry) + added_nodes * NODE_BYTES
            lvl = 'ok' if fill < MAIN_ASSETS * 0.9 else 'warn'
            out.append(item(lvl, 'memory', '%s: %+d bytes of level data, +%d scene nodes' % (
                e.split('/')[-1], grow, added_nodes), 'MAIN_ASSETS estimate %.1f of 90 MiB with this map and section '
                'resident%s' % (fill / 1048576.0, ' (TOD HD measured 78.6 MiB at Map03: keep additions small)'
                                 if ws.game.has_hd() else '')))
        else:
            out.append(item('ok' if grow < 256 * 1024 else 'warn', 'memory', '%s: %+d bytes, +%d nodes' % (
                e.split('/')[-1], grow, added_nodes), 'mission and main blocks use their own asset pools; fragments '
                'grow by the edit size only'))
    # ---------------------------------------------------------------- hull sizes
    bad = 0
    for op in mod_ops:
        size = (op.get('set') or {}).get('size') if op['op'] == 'add' else None
        s = None
        if op['op'] == 'add':
            st = op.get('set') or {}
            if 'width' in st:
                s = [st.get('width'), st.get('height'), st.get('length')]
        elif op['op'] == 'set' and op.get('prop') in ('width', 'height', 'length'):
            s = [op['value']]
        if s:
            for v in s:
                if v is None:
                    continue
                if not (0.05 <= float(v) <= 512):
                    bad += 1
                    out.append(item('error', 'hulls', 'box size %.2f m is outside 0.05 .. 512 m' % float(v),
                                    '%s %s' % (op.get('frag', ''), op.get('node', op.get('uid', '')))))
                elif float(v) > 100:
                    out.append(item('warn', 'hulls', 'box side %.0f m: very large boxes fall into many quadtree cells'
                                    % float(v), ''))
        p = op.get('pos')
        if p and any(abs(x) > 16000 for x in p):
            bad += 1
            out.append(item('error', 'hulls', 'position %s is outside +-16 km' % [round(x, 1) for x in p], ''))
    for e, L in levels_by_entry.items():
        models = (L or {}).get('_model_table') or {}
        for name, m in models.items():
            b = m.get('bound')
            if b and b[3] is not None and b[3] < 0 and m.get('hulls'):
                out.append(item('warn', 'hulls', '%s has collision but no bounding sphere' % name, ''))
    if not bad:
        out.append(item('ok', 'hulls', 'collision boxes and positions are in range', ''))
    # ---------------------------------------------------------------- save safety
    removed = [x for b in build_rep['blocks'] for x in b.get('removed', [])]
    if removed:
        out.append(item('error', 'saves', '%d object(s) removed: saves made in these sections will load wrongly'
                        % len(removed), 'Use "retire" (the default delete) instead of "remove" to keep old saves working. ' +
                        ', '.join(removed[:6])))
    else:
        for b in build_rep['blocks']:
            sb = b.get('stage_b')
            if sb:
                ri = sb['checks'].get('runtime_indices') or {}
                out.append(item('ok' if ri.get('unchanged') else 'warn', 'saves',
                                '%s: %d new object(s) appended after every old one; old save indices unchanged (%s '
                                'checked)' % (b['entry'].split('/')[-1], len(sb['grafted']), ri.get('existing_nodes')),
                                'appended to %s' % sb['grafted'][0]['into']))
        if not any(b.get('stage_b') for b in build_rep['blocks']):
            out.append(item('ok', 'saves', 'no objects added or removed: old saves keep working', ''))
    # ---------------------------------------------------------------- references
    dangl = 0
    for b in build_rep['blocks']:
        for f in (b.get('stage_a') or {}).get('checks', {}).get('4_edited_fragments', []):
            dangl += f.get('dangling_refs') or 0
    out.append(item('ok', 'references', 'no new dangling references (fragment writer verify)', ''))
    for op in mod_ops:
        if op['op'] == 'set' and op.get('prop') == 'modelres':
            name = op['value'].lower()
            if not name.startswith('/data'):
                name = '/data' + name
            ok = any(name in ws.assets(e).models for e in list(outs) + ['data_pc/overdose_the_game/overdose/shared/overdose.main'])
            out.append(item('ok' if ok else 'error', 'references', 'model %s %s' % (op['value'], 'found' if ok else
                                                                                       'is not in the loaded blocks'), ''))
    for e, raw in outs.items():
        if e.endswith('.mission'):
            out.extend(_mission_lint(ws, e, raw))
    # ---------------------------------------------------------------- cars
    out.extend(cars(ws, outs, levels_by_entry))
    return out


def _estimate_main(ws, levels_by_entry):
    """Measured anchor: 18.6 MiB at the menu (overdose.main INFO + its scene graph); add the INFO and the scene nodes of
    the map and section blocks in view (docs/subsystem_memory_pools.md 1; ~0.25 KiB per node)."""
    tot = 18.6 * 1048576
    for e, L in levels_by_entry.items():
        if e.endswith(('.map', '.submap')) and L:
            tot += (L.get('info_bytes') or 0) + (L.get('nodes') or 0) * NODE_BYTES
    if ws.game.has_hd():
        tot = max(tot, 78.6 * 1048576)
    return tot


def _mission_lint(ws, entry, raw):
    try:
        import missiontool as mt
        import tempfile
        base, _ = ws.read_block(entry)
        res = []
        for tag, data in (('base', base), ('new', raw)):
            with tempfile.NamedTemporaryFile(suffix='.mission', delete=False) as f:
                f.write(data)
                p = f.name
            try:
                B = mt.Block(p, entry)
                res.append(mt.check(B))
            finally:
                os.unlink(p)
        nb = _count_issues(res[0])
        nn = _count_issues(res[1])
        lvl = 'ok' if nn <= nb else 'warn'
        return [item(lvl, 'references', '%s: mission lint %d issue(s) (vanilla %d)' % (entry.split('/')[-1], nn, nb),
                     'tools/missions/missiontool.py check')]
    except Exception as e:
        return [item('warn', 'references', 'mission lint not run for %s' % entry.split('/')[-1], str(e))]


def _count_issues(r):
    if isinstance(r, dict):
        return sum(len(v) if isinstance(v, list) else 0 for k, v in r.items() if k not in ('ok', 'counts'))
    if isinstance(r, list):
        return len(r)
    return 0


def cars(ws, outs, levels_by_entry):
    """Placed cars (vehicle_placeholder, not traffic) per block, and the largest group within 100 m."""
    from . import level as lv
    res = []
    for e, L in levels_by_entry.items():
        if e in outs:
            ents, _ = lv.BlockLevel(e, outs[e], ws.T, ws.main_lookup).entities('x')
        else:
            ents = (L or {}).get('entities') or []
        cars_ = [x for x in ents if x['cat'] == 'vehicle' and (x['type'] or '').startswith('vehicle_placeholder')
                 and not (x.get('sub') or {}).get('Traffic_System_Placeholder')]
        if not cars_:
            continue
        best = _cluster(cars_)
        base_cars = [x for x in ((L or {}).get('entities') or []) if x['cat'] == 'vehicle' and
                     (x['type'] or '').startswith('vehicle_placeholder')]
        base_best = _cluster(base_cars)
        lvl = 'ok' if best <= max(LIVE_CARS, base_best) else 'warn'
        res.append(item(lvl, 'cars', '%s: %d placed cars, up to %d within 100 m of each other' % (
            e.split('/')[-1], len(cars_), best),
            'Only %d placed cars are drivable at once (code constant at 0x7635C5); the others stay static models. '
            'Vanilla: %d cars, up to %d close together.' % (LIVE_CARS, len(base_cars), base_best) if best > LIVE_CARS else ''))
    return res


def _cluster(cars_):
    best = 0
    for a in cars_:
        best = max(best, sum(1 for b in cars_ if math.dist(a['pos'], b['pos']) <= 100.0))
    return best
