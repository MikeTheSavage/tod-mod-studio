"""tpl_build.py - build(project, base_archives, out_dir) and validate(project, base_archives).

PROJECT (JSON dict)
{
  "format": 1, "package": "name of the package",
  "new_map": { make_new_map params ... }   |  "new_map_path": "file.json" (relative to base_dir)      optional: the host new map(s)
  "hosts": [ {"id": "mesa", "kind": "new_map", "map_index": 0, "area": [x0,z0,x1,z1], "ground_y": 20.0, ...},
             {"id": "alley", "kind": "existing", "block": "submap01_map02_lostoros_downtown.submap", "parent": {...},
              "map_ids": {"map": 1, "submap": 3, "start_map": 3}, "area": [...], "start_spot": "TELEPORTPOINT_..."} ],
  "missions": [ {"id": "m1", "type": "showdown", "host": "mesa", "index": 71 | "auto", "params": { ... }} ],
  "options": {"zip_name": "mesa_missions.zip", "text_zip_name": "text_override.zip", "keep_map_enemies": false, "overlay_entries": null,
              "map_cache": "dir (dev speed-up: reuse the map build of identical params)", "keep_intermediate": false}
}
BASE_ARCHIVES: the game's filesystem chain in priority order, e.g. [gameplay_plus_data.zip, blocks.naz, sounds.naz, ...]. The first blocks.naz is the
base game; zips earlier in the chain (Gameplay+) are read through the overlay (overdose.main, the Downtown submap, the uk text block).
OUTPUT (out_dir): <zip_name> (first archive), text/<text_zip_name> (second), manifest.json (indices, award runtime indices, text rows: what the save
migration needs), award_runtime_index.json (old format), lint.txt, report.json, params_used.json.
"""
import copy, importlib, json, math, os, re, shutil, struct, sys, time, zipfile
sys.dont_write_bytecode = True
from . import tpl_env, tpl_core, tpl_host, tpl_lib, tpl_variant
from .tpl_core import ParamError
from .types._base import Inst

TYPE_NAMES = ['showdown', 'stunt', 'race', 'frenzy', 'destroy', 'rescue', 'chase', 'hold', 'ghost', 'defuse', 'arena', 'combo', 'lava', 'marked',
              'capture', 'endurance', 'style']
_MODS = {}


def template_module(name):
    if name not in _MODS:
        if name not in TYPE_NAMES:
            raise ParamError('Unknown mission type "%s" (known: %s).' % (name, ', '.join(TYPE_NAMES)))
        _MODS[name] = importlib.import_module('%s.types.%s' % (__package__, name))
    return _MODS[name]


def list_templates():
    return [template_module(n).NAME for n in TYPE_NAMES]


def template_schema(name, host=None):
    return tpl_core.schema_json(template_module(name), host)


class BuildError(Exception):
    def __init__(self, messages):
        self.messages = messages
        super().__init__('; '.join(m['text'] if isinstance(m, dict) else str(m) for m in messages))


def _msg(level, where, text):
    return dict(level=level, where=where, text=text)


# ------------------------------------------------------------------------------------------------ project -> plan
class Plan:
    pass


def load_project(project, base_dir='.'):
    if isinstance(project, (str, os.PathLike)):
        base_dir = os.path.dirname(os.path.abspath(project))
        project = json.load(open(project, encoding='utf-8'))
    return project, base_dir


def make_plan(project, base_chain, used=(), base_dir='.'):
    """resolve hosts, instances (type, host, index, parameters) and collect plain-language messages. Does not build anything."""
    project, base_dir = load_project(project, base_dir)
    plan = Plan()
    plan.project, plan.base_dir, plan.msgs = project, base_dir, []
    plan.options = dict(project.get('options', {}))
    E = tpl_env.get()
    if base_chain is not None:
        tpl_env.set_chain(base_chain, plan.options.get('overlay_entries'))
    try:
        plan.new_map, plan.hosts = tpl_host.load_project_hosts(project, base_dir)
    except tpl_host.HostError as e:
        plan.msgs.append(_msg('error', 'project', str(e)))
        plan.new_map, plan.hosts = None, {}
    for h in plan.hosts.values():
        if h.kind == tpl_host.EXISTING and h.d.get('map_ids_from_slot') is not None and not h.map_ids:
            try:
                info = slot_award_info(E, int(h.d['map_ids_from_slot']))
                h.map_ids = dict(map=info['map'], submap=info['submap'], start_map=info['start_map'])
                if not h.start_spot and info.get('start_spot'):
                    h.start_spot = info['start_spot']
                    h.spots.append(info['start_spot'])
            except BuildError as e:
                plan.msgs += [dict(m) for m in e.messages]
    plan.instances = []
    missions = project.get('missions', [])
    if not missions:
        plan.msgs.append(_msg('error', 'project', 'The project has no missions.'))
    # ---- indices
    full_pool = tpl_core.pool(base_chain)
    um = tpl_core._used_map(used)
    free = [i for i in full_pool if i not in um]
    plan.pool, plan.free = full_pool, free
    refuse = tpl_core.pool_message(base_chain, used, len(missions))
    if refuse:
        plan.msgs.append(_msg('error', 'project', refuse))
    claimed = {}
    for m in missions:                                    # explicit indices first
        if m.get('index') not in (None, 'auto'):
            i = int(m['index'])
            if i not in full_pool:
                plan.msgs.append(_msg('error', m.get('id', m.get('type')), 'Index %d is not a free mission index of this game install (free: %s).' % (i, ', '.join(map(str, full_pool)))))
            elif i in um:
                plan.msgs.append(_msg('error', m.get('id', m.get('type')), 'Index %d is already used by %s.' % (i, ', '.join(um[i]))))
            elif i in claimed:
                plan.msgs.append(_msg('error', m.get('id', m.get('type')), 'Index %d is used twice in this project.' % i))
            claimed[i] = m
    avail = [i for i in free if i not in claimed]
    seen_types = {}
    for n, m in enumerate(missions):
        mid = m.get('id') or '%s%d' % (m.get('type'), n + 1)
        try:
            mod = template_module(m.get('type'))
        except ParamError as e:
            plan.msgs.append(_msg('error', mid, str(e)))
            continue
        hid = m.get('host')
        if hid is None and len(plan.hosts) == 1:
            hid = next(iter(plan.hosts))
        host = plan.hosts.get(hid)
        if host is None:
            plan.msgs.append(_msg('error', mid, 'The mission names the host "%s" which the project does not define.' % hid))
            continue
        if m.get('index') in (None, 'auto'):
            if mod.LEGACY_INDEX in avail:
                idx = mod.LEGACY_INDEX
            elif avail:
                idx = avail[0]
            else:
                plan.msgs.append(_msg('error', mid, 'No free mission index is left for this mission.'))
                continue
            avail.remove(idx)
        else:
            idx = int(m['index'])
        first = mod.NAME not in seen_types
        seen_types[mod.NAME] = True
        inst = Inst(idx, first, mid)
        p, pm = tpl_core.resolve(mod, m.get('params'), host)
        plan.msgs += [_msg(l, mid, t) for l, t in pm]
        if not any(l == 'error' for l, _t in pm):
            try:
                plan.msgs += [_msg(l, mid, t) for l, t in mod.constraints(p, host)]
            except Exception as e:                        # noqa: BLE001
                plan.msgs.append(_msg('error', mid, 'Could not check the settings: %s' % e))
        plan.instances.append(dict(id=mid, mod=mod, host=host, inst=inst, p=p, raw=m))
    plan.instances.sort(key=lambda r: r['inst'].index)
    return plan


# ------------------------------------------------------------------------------------------------ static checks (validate)
def _box_gap(a, b):
    gx = abs(a[0] - b[0]) - (a[2] + b[2]) / 2
    gz = abs(a[1] - b[1]) - (a[2] + b[2]) / 2
    return max(gx, gz)


EXISTING_GIVER_WARN = ('This giver box sits in an existing map section. A game that loads the section fresh (a new game, or after any mission start or '
                       'end or a trip through a map loader) shows it at once. A save that already holds the section needs the Mod Studio save update '
                       '("Update a save for new missions"), which gives the box its script thread; a save that does not list this section shows the box only '
                       'after the section is reloaded once.')


def static_checks(plan):
    msgs = []
    warned = set()
    for r in plan.instances:
        if r['host'].kind != tpl_host.NEW_MAP and r['host'].id not in warned:
            warned.add(r['host'].id)
            msgs.append(_msg('warn', r['id'], EXISTING_GIVER_WARN))
    boxes = []
    for r in plan.instances:
        sp = r['p']
        gx, gy, gz = sp['giver_pos']
        boxes.append((r, gx, gz, sp['giver_size']))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[0]['host'] is not b[0]['host']:
                continue
            gap = _box_gap(a[1:], b[1:])
            if gap < 3.0:
                msgs.append(_msg('error', a[0]['id'], 'The giver box of "%s" is only %.1f m from the giver box of "%s". Keep at least 3 m between giver boxes (4 m is better).' % (a[0]['id'], gap, b[0]['id'])))
            elif gap < 4.0:
                msgs.append(_msg('warn', a[0]['id'], 'The giver box of "%s" is %.1f m from the giver box of "%s". 4 m or more is better.' % (a[0]['id'], gap, b[0]['id'])))
    for r in plan.instances:
        h, sp, mid = r['host'], r['p'], r['id']
        gx, gy, gz = sp['giver_pos']
        half = sp['giver_size'] / 2
        a = h.bounds
        if not (a[0] <= gx - half and gx + half <= a[2] and a[1] <= gz - half and gz + half <= a[3]):
            msgs.append(_msg('error', mid, 'The giver box sticks out of the map bounds (%.0f..%.0f, %.0f..%.0f).' % (a[0], a[2], a[1], a[3])))
        if not h.inside(gx, gz, 0.0):
            msgs.append(_msg('warn', mid, 'The giver box is outside the play area of the host; make sure the player can walk there.'))
        for (x0, z0, x1, z1, lab) in h.obst:
            if x0 - half <= gx <= x1 + half and z0 - half <= gz <= z1 + half and x0 <= gx <= x1 and z0 <= gz <= z1:
                msgs.append(_msg('error', mid, 'The giver box centre is inside "%s". Move it to open ground.' % lab))
                break
        for (x0, z0, x1, z1, lab) in h.reserved:
            if lab == 'arrival' and x0 <= gx <= x1 and z0 <= gz <= z1:
                msgs.append(_msg('warn', mid, 'The giver box stands on the arrival spot, where the player appears.'))
    # reachability from the arrival (needs obstacle data of the host)
    by_host = {}
    for r in plan.instances:
        by_host.setdefault(r['host'].id, []).append(r)
    for hid, rs in by_host.items():
        h = rs[0]['host']
        ap = h.arrival.get('pos') or h.d.get('arrival_pos')
        if not ap or not h.obst:
            continue
        targets = [(r['id'], r['p']['giver_pos'][0], r['p']['giver_pos'][2], r['p']['giver_size']) for r in rs]
        res = h.reach((ap[0], ap[2]), targets)
        for r in rs:
            d = res.get(r['id'])
            if d is None:
                msgs.append(_msg('error', r['id'], 'The player cannot walk from the arrival spot to the giver box of "%s": something blocks the way.' % r['id']))
            else:
                c = h.clearance(r['p']['giver_pos'][0], r['p']['giver_pos'][2])
                if c < 2.0:
                    msgs.append(_msg('warn', r['id'], 'The giver box centre is only %.1f m from a wall or prop; a box edge may touch it.' % c))
    # text checks
    names, descs, loads = {}, {}, {}
    to = None
    try:
        to = tpl_env.textool()
        glyphs = to.fonts('uk')['/data/Fonts/ODPS2.font']['glyphs']
    except Exception:                                    # noqa: BLE001
        glyphs = None
    for r in plan.instances:
        sp, mid = r['p'], r['id']
        for key, what in (('name', 'name'), ('description', 'description'), ('load_mid', 'loading line'), ('load_low', 'loading line')):
            v = sp[key]
            if '\t' in v:
                msgs.append(_msg('error', mid, 'The %s contains a tab character.' % what))
            if glyphs is not None and v:
                miss = to.undrawable([ord(ch) for ch in v], glyphs)
                if miss:
                    msgs.append(_msg('warn', mid, 'The game fonts cannot draw %s in the %s.' % (' '.join(sorted(set(chr(c) if isinstance(c, int) else str(c) for c in miss))), what)))
        if not sp['name'].strip():
            msgs.append(_msg('error', mid, 'The mission needs a name.'))
        for k, d in (('name', names), ('description', descs)):
            d.setdefault(sp[k].strip().lower(), []).append(mid)
        if sp['load_mid'].strip():
            loads.setdefault(sp['load_mid'].strip().lower(), []).append(mid)
    for lab, d in (('name', names), ('description', descs), ('loading line', loads)):
        for v, ids in d.items():
            if len(ids) > 1:
                msgs.append(_msg('warn', ids[0], 'The %s "%s" is used by %d missions (%s). Players cannot tell them apart.' % (lab, v[:40], len(ids), ', '.join(ids))))
    return msgs


def validate(project, base_archives, used=(), base_dir='.', deep=False, work_dir=None):
    """Plain-language messages per mission instance: {'ok': bool, 'project': [...], 'missions': {id: [...]}, 'index': {id: index}}.
    Each message is {'level': 'error'|'warn'|'info', 'where': id, 'text': ...}. deep=True also builds into work_dir (a temp folder) and adds the lint."""
    plan = make_plan(project, base_archives, used, base_dir)
    msgs = list(plan.msgs)
    if not any(m['level'] == 'error' for m in msgs):
        msgs += static_checks(plan)
    out = dict(project=[m for m in msgs if m['where'] == 'project'], missions={}, index={r['id']: r['inst'].index for r in plan.instances},
               free_indices=plan.free, pool=plan.pool)
    for m in msgs:
        if m['where'] != 'project':
            out['missions'].setdefault(m['where'], []).append(m)
    if deep and not any(m['level'] == 'error' for m in msgs):
        import tempfile
        wd = work_dir or tempfile.mkdtemp(prefix='tplval_')
        try:
            res = build(project, base_archives, wd, used=used, base_dir=base_dir)
            for iid, lines in res['lint'].items():
                for ln in lines:
                    lvl = 'error' if ln.startswith(('ERROR', 'STRUCT')) else 'warn' if ln.startswith('warn') else None
                    if lvl:
                        out['missions'].setdefault(iid, []).append(_msg(lvl, iid, 'Lint: ' + ln.split(' ', 1)[1].strip()))
        except BuildError as e:
            out['project'] += [m if isinstance(m, dict) else _msg('error', 'project', str(m)) for m in e.messages]
        finally:
            if not work_dir:
                shutil.rmtree(wd, ignore_errors=True)
    out['ok'] = not any(m['level'] == 'error' for ms in list(out['missions'].values()) + [out['project']] for m in ms)
    return out


# ------------------------------------------------------------------------------------------------ build
_AWARD_TYPES = None


def award_types(E, base_main_raw):
    """{mission index: (Award_1_Type, Award_2_Type)} read from the base overdose.main (database_mission_award nodes)"""
    T = E.ft.types()
    bi = E.BE.BlockInfo(E.MAIN, base_main_raw)
    out = {}
    for k, nm in bi.frs:
        if nm.split('/')[-1] not in tpl_core.REG_FRAGMENTS:
            continue
        d = bi.doc(nm)
        for r in d.records:
            if r.op == 'create' and b'database_mission_award' in r.raw:
                n = r.node
                try:
                    out[d.get(n, 'Mission')] = (d.get(n, 'Award_1_Type', None), d.get(n, 'Award_2_Type', None))
                except Exception:                      # noqa: BLE001
                    pass
    return out


def slot_award_info(E, slot):
    """{'map', 'submap', 'start_map', 'start_spot'} of the shipped award of registry slot `slot` (proven values to start a mission in an existing map)"""
    T = E.ft.types()
    bi = E.BE.BlockInfo(E.MAIN, E.read(E.MAIN))
    for k, nm in bi.frs:
        if nm.split('/')[-1] not in tpl_core.REG_FRAGMENTS:
            continue
        d = bi.doc(nm)
        for r in d.records:
            if r.op == 'create' and b'database_mission_award' in r.raw and d.get(r.node, 'Mission', None) == slot:
                return dict(map=d.get(r.node, 'Mission_Map'), submap=d.get(r.node, 'Mission_SubMap'), start_map=d.get(r.node, 'Mission_StartMap'),
                            start_spot=d.get(r.node, 'Teleport_to_on_start'))
    raise BuildError([_msg('error', 'project', 'No shipped award for registry slot %s.' % slot)])


def pass_medal_type(types, slot):
    """Award_3_Type (the pass medal): 1 = Health Skill, 34 = Stamina, 38 = Weapon, 10 = Carry More Ammo, the first one the template slot's Award_1 / Award_2 do not use"""
    used = set(types.get(slot, ()))
    for t in (1, 34, 38, 10):
        if t not in used:
            return t
    return 1


def find_registry(E, T, rd, main, idx):
    bi = E.BE.BlockInfo(main, rd(main))
    folder = award = None
    for k, nm in bi.frs:
        if nm.split('/')[-1] not in tpl_core.REG_FRAGMENTS:
            continue
        creates = {}
        for r in bi.doc(nm).records:
            if r.op == 'create':
                creates[r.node] = r.raw
            elif r.prop is not None and T.name(r.prop) == 'Mission' and struct.unpack('<i', r.raw[:4])[0] == idx:
                if b'database_Mission_ID' in creates.get(r.node, b''):
                    folder = r.node
                if b'database_mission_award' in creates.get(r.node, b''):
                    award = r.node
    return folder, award


def shipped_rows():
    rows = {}
    path = tpl_env.CFG.get('shipped_strings')
    if path and os.path.exists(path):
        for ln in open(path, encoding='utf-8'):
            f = ln.rstrip(chr(10)).split(chr(9))
            if len(f) >= 5 and f[1] in ('uk_Mission.txt', 'uk_Objective.txt') and f[2].isdigit():
                rows[(f[1], int(f[2]))] = f[4]
    return rows


def resolve_values(d, texts):
    return {k: (texts[v] if isinstance(v, str) and v.startswith('@') else v) for k, v in d.items()}


def _yaw_quat(deg):
    th = math.radians(deg)
    return [0.0, math.sin(th / 2.0), 0.0, math.cos(th / 2.0)]


def _params_hash(obj):
    import hashlib
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def build(project, base_archives, out_dir, used=(), base_dir='.', progress=None):
    """Build the package. Returns {'ok', 'zips': [...], 'manifest': path, 'lint': {id: [lines]}, 'indices': {id: index}, 'awards': {index: runtime}}.
    Raises BuildError (plain-language messages) when the project is not buildable."""
    say = progress or (lambda s: None)
    base_archives = [str(a) for a in base_archives]
    naz = tpl_env.find_blocks_naz(base_archives)
    if naz:
        tpl_env.configure(blocks_naz=naz)
    E = tpl_env.get()
    plan = make_plan(project, base_archives, used, base_dir)
    errs = [m for m in plan.msgs if m['level'] == 'error']
    if not errs:
        errs = [m for m in static_checks(plan) if m['level'] == 'error']
    if errs:
        raise BuildError(errs)
    opts = plan.options
    out = os.path.abspath(out_dir)
    os.makedirs(out, exist_ok=True)
    MAINMAP = E.MAIN
    T = E.ft.types()
    specs = []
    for r in plan.instances:
        sp = r['mod'].make(r['p'], r['host'], r['inst'])
        sp.host, sp.iid = r['host'], r['id']
        specs.append(sp)
    # ---------------------------------------------------------------- 1. host maps with one giver per mission
    for sp in specs:
        g = sp.GIVER
        sp.host.reserve(g['pos'][0], g['pos'][2], g['size'] / 2 + 1.5, g['size'] / 2 + 1.5, 'giver ' + sp.NAME)
    npar = copy.deepcopy(plan.new_map) if plan.new_map else None
    existing_givers = []
    thread_keys = []
    if npar:
        for hid, h in plan.hosts.items():
            if h.kind == tpl_host.NEW_MAP and not opts.get('keep_map_enemies'):
                npar['maps'][h.d.get('map_index', 0)].pop('enemies', None)
        for h in plan.hosts.values():
            if h.kind == tpl_host.NEW_MAP:
                npar['maps'][h.d.get('map_index', 0)]['givers'] = []
    for sp in specs:
        g = sp.GIVER
        gd = dict(name=g['name'], pos=list(g['pos']), mission=sp.INDEX, size=g['size'], height=g['height'])
        if g['yaw']:
            gd['orient'] = _yaw_quat(g['yaw'])
        if sp.host.kind == tpl_host.NEW_MAP:
            npar['maps'][sp.host.d.get('map_index', 0)]['givers'].append(gd)
        else:
            if not sp.host.block:
                raise BuildError([_msg('error', sp.iid, 'The existing host "%s" needs "block" (the map section that takes the giver box).' % sp.host.id)])
            gd.update(block=sp.host.block)
            if sp.host.parent:
                gd['parent'] = sp.host.parent
            existing_givers.append(gd)
    if npar is None:
        npar = dict(package=project_name(plan), maps=[])
    if existing_givers:
        npar['existing_givers'] = existing_givers
    json.dump(npar, open(os.path.join(out, 'params_used.json'), 'w'), indent=1)
    MAPDIR = os.path.join(out, 'map')
    mapfiles, mans = {}, []
    if npar['maps'] or existing_givers:
        say('building the host map')
        cache = opts.get('map_cache')
        cdir = os.path.join(cache, _params_hash([npar, base_archives, E.overlay.active_key()])) if cache else None
        if cdir and os.path.exists(os.path.join(cdir, 'stream_override.zip')):
            shutil.rmtree(MAPDIR, ignore_errors=True)
            shutil.copytree(cdir, MAPDIR)
        else:
            mm = tpl_env.make_map()
            fails = []
            for attempt in range(3):                       # the recipe failed once at random inside numpy texture noise: retry
                shutil.rmtree(MAPDIR, ignore_errors=True)
                with tpl_env.quiet():
                    rep = mm.build(copy.deepcopy(npar), MAPDIR)
                if rep['result'] in ('PASS', 'CHECK-ONLY'):
                    break
                fails.append(rep['result'])
            else:
                raise BuildError([_msg('error', 'project', 'The map recipe failed (3 tries): %s' % ' | '.join(fails))])
            if cdir:
                os.makedirs(cache, exist_ok=True)
                shutil.copytree(MAPDIR, cdir)
        mz = zipfile.ZipFile(os.path.join(MAPDIR, 'stream_override.zip'))
        mapfiles = {n: mz.read(n) for n in mz.namelist()}
        mz.close()
        mans = json.load(open(os.path.join(MAPDIR, 'manifest.json')))['maps']
        thread_keys = existing_giver_nodes(MAPDIR, existing_givers)
    # ---------------------------------------------------------------- 2. mission blocks + registry
    overrides = {}
    for s in specs:
        bp = tpl_variant.resolve(s.TEMPLATE.get('block_path'))        # 'variant:<name>' -> a file made from the player's own blocks
        if bp:
            ent = E.SHARED + s.TEMPLATE['block']
            if ent in overrides and overrides[ent] != bp:
                raise BuildError([_msg('error', s.iid, 'Two missions use the same shipped block with different variant files.')])
            overrides[ent] = bp

    def read2(e):
        if e in mapfiles:
            return mapfiles[e]
        if e in overrides:
            return open(overrides[e], 'rb').read()
        return E.read(e)
    B = E.BE.Builder(read2)
    main_names = {str(n[4]) for n in E.BE.BlockInfo(MAINMAP, read2(MAINMAP)).nodes() if n[4]}
    atypes = award_types(E, E.read(MAINMAP))
    text_edits, texts_by_index, ctx_logs, obj_rows = [], {}, {}, []
    obj_next = tpl_core.OBJECTIVE_TEXT0
    shipped = shipped_rows()
    used_folders = set()
    for s in specs:
        h = s.host
        if h.kind == tpl_host.NEW_MAP:
            man = mans[h.d.get('map_index', 0)]
            map_ids = dict(map=man['map_id'], submap=man['submap_id'], start_map=man['submap_id'])
        else:
            map_ids = h.map_ids
            for k in ('map', 'submap', 'start_map'):
                if k not in map_ids:
                    raise BuildError([_msg('error', s.iid, 'The existing host "%s" needs map_ids {map, submap, start_map}.' % h.id)])
        s.map_ids = map_ids
    for s in specs:
        rank = plan.pool.index(s.INDEX)
        txt = tpl_core.alloc_texts(s, rank, obj_next)
        for key_, o_ in txt.items():
            if key_ in ('name', 'description', 'real_name', 'teaser', 'load_mid', 'load_low') and shipped.get(('uk_Mission.txt', o_), '') != '':
                raise BuildError([_msg('error', s.iid, 'uk_Mission row %d already holds a shipped string %r' % (o_, shipped[('uk_Mission.txt', o_)][:40]))])
            if key_.startswith('@') and shipped.get(('uk_Objective.txt', o_), '') != '':
                raise BuildError([_msg('error', s.iid, 'uk_Objective row %d already holds a shipped string' % o_)])
        obj_next += len(s.TEXT['objectives'])
        texts_by_index[s.INDEX] = txt
        T_ = s.TEMPLATE
        SRC = E.SHARED + T_['block']
        old_root, new_root = T_['root'], s.NEW_ROOT
        if len(old_root) != len(new_root):
            raise BuildError([_msg('error', s.iid, 'internal: NEW_ROOT %r must have the length of the template root %r' % (new_root, old_root))])
        NEW = E.SHARED + new_root[:-9].lower() + '.mission'
        s.NEW = NEW
        B.new_block(NEW, SRC, rename_root=(old_root, new_root), localized=True)
        bi = E.BE.BlockInfo(SRC, read2(SRC))
        ctx = tpl_lib.Ctx(B, E.BE, T, NEW, SRC, old_root, new_root, bi, s.host, s, txt)
        s.design(ctx)
        ctx_logs[s.iid] = ctx.log
        folder, award = find_registry(E, T, read2, MAINMAP, T_['slot'])
        FOLDER_NAME = s.FOLDER_NAME
        if FOLDER_NAME in used_folders or FOLDER_NAME in main_names:
            raise BuildError([_msg('error', s.iid, 'The registry folder name %s already exists.' % FOLDER_NAME)])
        used_folders.add(FOLDER_NAME)
        FRAGPATH = '/data/Overdose_THE_GAME/Missions/SubMissions/%s' % new_root
        award_sets = {'Award_3_ActionPoints': s.PASS_SCORE}
        award_sets.update({'Mission_Map': s.map_ids['map'], 'Mission_SubMap': s.map_ids['submap'], 'Mission_StartMap': s.map_ids['start_map'],
                           'Teleport_to_on_start': s.START_SPOT})
        award_sets.update({'LoadScreen_Main_Text': txt['name'], 'LoadScreen_Mid_Text': txt['load_mid'], 'LoadScreen_Low_Text': txt['load_low'],
                           'BonusMission_name': txt['name'], 'Award_3_Type': pass_medal_type(atypes, T_['slot'])})
        award_sets.update({'Mission_Name': txt['name'], 'Mission_Real_Name': txt['real_name'], 'Mission_Description': txt['description'],
                           'Mission_teaser': txt['teaser']})
        for k, v in s.AWARD_SCORES.items():
            award_sets.setdefault(k, v)
        for k, v in s.AWARD_SETS.items():
            award_sets[k] = txt[v] if isinstance(v, str) and v.startswith('@') else v
        B.append(MAINMAP, 'm_folder_%d' % s.INDEX, (MAINMAP, 'Missions.fragment', folder), parent=('ref', 'Missions.fragment', 0x00100058),
                 name=FOLDER_NAME, sets={'fragment': FRAGPATH, 'Mission': s.INDEX})
        B.append(MAINMAP, 'm_award_%d' % s.INDEX, (MAINMAP, 'MissionDict.fragment', award), parent=('ref', 'Database.fragment', 0x00100618), deep=True,
                 name='SubM_%d_Mesa_award' % s.INDEX,
                 sets=dict(award_sets, Mission=s.INDEX, Mission_Folder=FOLDER_NAME, PlaceInList=99),
                 child_sets=[{'type': 'database_mission_objective(NodeLogical)', 'index': i, 'set': resolve_values(o, txt)}
                             for i, o in enumerate(s.OBJECTIVES)])
        tx = s.TEXT
        nd = tx['name'] + chr(10) + tx['description']
        text_edits += [dict(file='uk_Mission.txt', ordinal=txt['name'], value=tx['name']),
                       dict(file='uk_Mission.txt', ordinal=txt['real_name'], value=tx['name']),
                       dict(file='uk_Mission.txt', ordinal=txt['description'], value=nd),
                       dict(file='uk_Mission.txt', ordinal=txt['teaser'], value=nd)]
        text_edits += [dict(file='uk_Mission.txt', ordinal=txt['load_mid'], value=tx.get('load_mid', tx['name'])),
                       dict(file='uk_Mission.txt', ordinal=txt['load_low'], value=tx.get('load_low', ' '))]
        for key, val in tx['objectives']:
            obj_rows.append((txt['@' + key], val))
        say('%-9s index %d: block %s' % (s.NAME, s.INDEX, NEW.split('/')[-1]))
    for o, val in sorted(obj_rows):
        if o <= 351:
            text_edits.append(dict(file='uk_Objective.txt', ordinal=o, value=val))
        else:
            assert o == 352 + sum(1 for x, _v in obj_rows if 352 <= x < o), 'objective rows must be contiguous from 352'
            text_edits.append(dict(file='uk_Objective.txt', append=dict(key='OBJ_MESA_%d' % o, value=val)))
    built, rep = B.build()
    merged = dict(mapfiles)
    merged.update(built)
    zip_name = opts.get('zip_name', 'mesa_missions.zip')
    zp = os.path.join(out, zip_name)
    rep['zip'] = E.ft.write_zip(zp, sorted(merged.items()))
    # ---------------------------------------------------------------- 3. texts (in process)
    td = os.path.join(out, 'text')
    os.makedirs(td, exist_ok=True)
    ej = os.path.join(td, 'edit.json')
    json.dump(dict(description='mesa mission texts', langs=['uk', 'de', 'fr', 'es', 'it'], edits=text_edits), open(ej, 'w'), indent=1)
    to = tpl_env.textool()
    to._ARCH = None
    with tpl_env.quiet():
        rc = to.cmd_edit(type('A', (), dict(edit=ej, out=td, deploy=None))())
    if rc:
        raise BuildError([_msg('error', 'project', 'The text tool failed: see %s' % os.path.join(td, 'report.json'))])
    text_zip = os.path.join(td, 'text_override.zip')
    if opts.get('text_zip_name') and opts['text_zip_name'] != 'text_override.zip':
        shutil.move(text_zip, os.path.join(td, opts['text_zip_name']))
        text_zip = os.path.join(td, opts['text_zip_name'])
    # ---------------------------------------------------------------- 4. award runtime indices
    ob = [b for b in rep['blocks'] if b['entry'].endswith('overdose.main') and 'appended' in b][0]['appended']
    nxt = ob['next_runtime_index']
    cursor = int(nxt, 16) if isinstance(nxt, str) else nxt
    awards = {}
    for nd_ in ob['nodes']:
        if nd_['uid'].startswith('m_award_'):
            awards[int(nd_['uid'].split('_')[-1])] = cursor
        cursor += len(nd_['keys'])
    json.dump({str(k): '0x%X' % v for k, v in awards.items()}, open(os.path.join(out, 'award_runtime_index.json'), 'w'), indent=1)
    json.dump(rep, open(os.path.join(out, 'report.json'), 'w'), indent=1, default=str)
    manifest = dict(format=1, package=project_name(plan), built_at=time.strftime('%Y-%m-%d %H:%M:%S'), base_archives=base_archives,
                    zips=[zip_name, 'text/' + os.path.basename(text_zip)],
                    pool=plan.pool,
                    missions=[dict(id=s.iid, type=s.NAME, index=s.INDEX, name=s.TEXT['name'], host=s.host.id, template_slot=s.TEMPLATE['slot'],
                                   award_runtime_index=awards[s.INDEX], award_runtime_index_hex='0x%X' % awards[s.INDEX], folder=s.FOLDER_NAME,
                                   block=s.NEW.split('/')[-1], giver=dict(name=s.GIVER['name'], pos=s.GIVER['pos'], size=s.GIVER['size']),
                                   map_ids=s.map_ids, start_spot=s.START_SPOT,
                                   text_rows=dict((k, v) for k, v in texts_by_index[s.INDEX].items())) for s in specs],
                    migrate_entries=['%d:%X:%d' % (s.INDEX, awards[s.INDEX], s.TEMPLATE['slot']) for s in specs],
                    thread_keys=thread_keys)
    json.dump(manifest, open(os.path.join(out, 'manifest.json'), 'w'), indent=1)
    # ---------------------------------------------------------------- 5. lint
    lint, bad = run_lint(E, T, out, specs, mapfiles, built, mans, texts_by_index, plan)
    json.dump(dict(lint=lint, bad=bad), open(os.path.join(out, 'lint.json'), 'w'), indent=1)
    # ---------------------------------------------------------------- disk hygiene
    for f in os.listdir(td):
        if f.endswith('.main'):
            os.remove(os.path.join(td, f))
    if os.path.isdir(MAPDIR) and not opts.get('keep_intermediate'):
        for f in os.listdir(MAPDIR):
            p = os.path.join(MAPDIR, f)
            if f not in ('manifest.json', 'recipe_report.json', 'configpc_line.txt'):
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    return dict(ok=bad == 0, zips=[zp, text_zip], manifest=os.path.join(out, 'manifest.json'), lint=lint, lint_errors=bad,
                indices={s.iid: s.INDEX for s in specs}, awards=awards, logs=ctx_logs)


def existing_giver_nodes(mapdir, existing_givers):
    """[{block, index, mission}]: the runtime index (hex string) of every mission giver box this build grafted into an EXISTING map block.
    An old save has no script thread for such a node (docs s19.5), so the save update adds one (migrate_save_copy). Read from the
    submaptool report of the map build (runtime_indices.new_nodes); the giver boxes are the Trigger_Root_Mission nodes, in graft order."""
    if not existing_givers:
        return []
    rp = os.path.join(mapdir, 'report.json')
    if not os.path.exists(rp):
        raise BuildError([_msg('error', 'project', 'The map build left no report, so the giver boxes in existing sections cannot be located.')])
    rep = json.load(open(rp))
    per = {}
    for b in rep.get('blocks', []):
        ck = b.get('checks') if isinstance(b.get('checks'), dict) else {}
        nodes = [n for n in (ck.get('runtime_indices') or {}).get('new_nodes', []) if str(n[1]).startswith('Trigger_Root_Mission')]
        per[b['entry'].replace(chr(92), '/').split('/')[-1].lower()] = [int(n[0], 16) for n in nodes]
    out = []
    used = {}
    for g in existing_givers:
        blk = g['block'].lower()
        i = used.get(blk, 0)
        used[blk] = i + 1
        if i >= len(per.get(blk, [])):
            raise BuildError([_msg('error', 'project', 'Could not find the giver box "%s" in the built block %s.' % (g['name'], g['block']))])
        out.append(dict(block=g['block'], index=per[blk][i], name=g['name'], mission=g['mission']))
    return out


def project_name(plan):
    return plan.project.get('package') or 'mission_templates'


TEXT_PROPS = ('Mission_Name', 'Mission_Real_Name', 'Mission_Description', 'Mission_teaser', 'LoadScreen_Main_Text', 'LoadScreen_Mid_Text', 'LoadScreen_Low_Text', 'BonusMission_name')


def text_leaks(E, main_raw, T, specs, texts_by_index):
    """{index: [errors]}: an award text property that does not point at one of the mission's own allocated rows is a leftover template string"""
    warns = {}
    bi = E.BE.BlockInfo(E.MAIN, main_raw)
    out = {}
    for k, nm in bi.frs:
        doc = bi.doc(nm)
        creates = {r.node: r.raw for r in doc.records if r.op == 'create'}
        for r in doc.records:
            if r.prop is not None and T.name(r.prop) == 'Mission' and b'database_mission_award' in creates.get(r.node, b''):
                idx = struct.unpack('<i', r.raw[:4])[0]
                if idx not in texts_by_index:
                    continue
                own = {v for kk, v in texts_by_index[idx].items() if not kk.startswith('@')}
                for pn in TEXT_PROPS:
                    v = doc.get(r.node, pn, None)
                    if v is not None and v not in own:
                        out.setdefault(idx, []).append('award text %s = %s is not one of this mission own rows (template string leak)' % (pn, v))
    own_obj = {}
    for sp in specs:
        for o in sp.OBJECTIVES:
            if o.get('name'):
                own_obj[o['name']] = sp.INDEX
    shipped = shipped_rows()
    for n in bi.nodes():
        if n[4] in own_obj:
            doc = bi.doc(n[2])
            idx = own_obj[n[4]]
            own = set(texts_by_index[idx].values())
            for pn in ('DisplayText', 'CounterText'):
                v = doc.get(n[3], pn, None)
                if v and v not in own:
                    warns.setdefault(idx, []).append('objective %s %s = %s is a shipped text: %r' % (n[4], pn, v, shipped.get(('uk_Objective.txt', v), '?')[:60]))
    return out, warns


def run_lint(E, T, out, specs, mapfiles, built, mans, texts_by_index, plan):
    """returns ({instance id: [lines]}, number of errors). Lines start with 'ERROR', 'warn', 'STRUCT' or 'ok'; lint.txt is written in the old format."""
    MAINMAP = E.MAIN
    extra = set()
    ents = [MAINMAP] + [m['map_block'] for m in mans] + [m['submap_block'] for m in mans]
    for h in plan.hosts.values():
        if h.kind == tpl_host.EXISTING and h.block:
            ents.append(h.block if '/' in h.block else E.SHARED + h.block)
    for e in dict.fromkeys(ents):
        raw = built.get(e) or mapfiles.get(e)
        if raw is None:
            try:
                raw = E.read(e)
            except Exception:                              # noqa: BLE001
                continue
        extra |= set(tpl_lib.block_names(E.BE, e, raw).keys())
    leaks, leak_warns = text_leaks(E, built[MAINMAP], T, specs, texts_by_index)
    mt = tpl_env.missiontool()
    lines_by, lines, bad = {}, [], 0
    for s in specs:
        NEW = s.NEW
        errs, warns = tpl_lib.lint_block(E.BE, T, NEW, built[NEW], extra, s.ALLOW_UNRESOLVED, bounds=s.host.bounds, outside_ok=s.OUTSIDE_OK)
        tmp = os.path.join(out, '_lint_%s.mission' % s.NAME)
        open(tmp, 'wb').write(built[NEW])
        try:
            B = mt.Block(tmp, NEW)
            B.add_context(mt.context_for(B))
            issues = mt.check(B)
        finally:
            os.remove(tmp)
        struct_issues = [l for l in issues if l.strip() and 'not in this block or its context' not in l]
        if s.PASS_SCORE > 0:
            warns = warns + ['PASS_SCORE %d: these templates pay about 10 points per kill (stunt combos, goodies and time add more); check the mission can earn it, else success shows YOU NEED AT LEAST N POINTS' % s.PASS_SCORE]
        errs = errs + leaks.get(s.INDEX, [])
        warns = warns + leak_warns.get(s.INDEX, []) + list(s.warnings)
        ls = ['== %s (index %d) ==' % (s.NAME, s.INDEX)]
        ls += ['ERROR ' + e for e in errs] + ['warn  ' + w for w in warns] + ['STRUCT ' + x for x in struct_issues]
        bad += len(errs) + len(struct_issues)
        if not errs and not struct_issues:
            ls.append('ok')
        lines += ls
        lines_by[s.iid] = ls[1:]
    open(os.path.join(out, 'lint.txt'), 'w').write('\n'.join(lines) + '\n')
    return lines_by, bad


# The script-thread record of a mission giver box (Trigger_Root_Mission): the same 17 dwords for every vanilla giver in every save (docs s19.5).
THREAD_RAW = ['00000011', '00000002', '00000000', '00000002', '00000000', '00000000', '00000003', '00000001', '00000000', '00000000',
              '00000000', 'ffffffff', 'ffffffff', '00000001', '00000000', '00000001', '00000000']
SLOT_OF_EXT = {'.map': 2, '.submap': 3, '.mission': 4}


def add_giver_threads(savefile, editlib, path, thread_keys):
    """Write the script-thread record into the save at `path` (in place: a COPY) for every giver box grafted into an existing map block.
    Returns {'patched': [{mission, block, key}], 'skipped': [{mission, block, reason}]}. A save can only carry the record when it lists that
    block (the map / submap / mission slot of its header); a save that lacks the block loads it fresh at the next load and the box is then
    inert until the block is reloaded (any mission start or end, or a trip through a map loader)."""
    s = editlib.Save(savefile.decode(open(path, 'rb').read()))
    have = {}
    for slot, bf in s.world.blocks.items():
        have[slot] = os.path.basename(bf).lower()
    recs = s.j['records']
    done, skipped = [], []
    for tk in thread_keys:
        blk = tk['block'].lower()
        slot = SLOT_OF_EXT.get(os.path.splitext(blk)[1])
        if slot is None or have.get(slot) != blk:
            skipped.append(dict(mission=tk.get('mission'), block=tk['block'],
                                reason='this save does not contain the section "%s" (it holds %s)' % (
                                    tk['block'], have.get(slot) or 'no section of this kind')))
            continue
        key = '%d:%x' % (slot, tk['index'])
        if s.node_records(key):
            skipped.append(dict(mission=tk.get('mission'), block=tk['block'], reason='the save already has records for that node'))
            continue
        pos = len(recs)
        for n, r in enumerate(recs):
            if 'n' in r and savefile.parse_key(r['n']) > (slot, tk['index']):
                pos = n
                break
        recs.insert(pos, {'n': key, 'p': 0, 'thread': 1, 'raw': list(THREAD_RAW)})
        done.append(dict(mission=tk.get('mission'), block=tk['block'], key=key))
    if done:
        open(path, 'wb').write(savefile.encode(s.j))
    return dict(patched=done, skipped=skipped)


def migrate_save_copy(manifest_path, src_save, out_save, migrate_py=None):
    """Write a migrated COPY of a save that can start every mission of the built package (never in place). Uses missions/types/migrate_save.py
    for the mission list entries, then adds the script-thread record of every giver box in an EXISTING map section when the save lists
    that section (without it the box never offers). Returns {'patched': [...], 'skipped': [...]} for the giver boxes."""
    mf = json.load(open(manifest_path))
    mp = migrate_py or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'types', 'migrate_save.py')
    import importlib.util
    sp = importlib.util.spec_from_file_location('tpl_migrate_save', mp)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    ents = []
    for e in mf['migrate_entries']:
        i, aw, sl = e.split(':')
        ents.append((int(i), int(aw, 16), int(sl)))
    m.migrate(src_save, out_save, ents)
    return add_giver_threads(m.savefile, m.editlib, out_save, mf.get('thread_keys') or [])


def merge_package(result, out_zip):
    """Merge the package's two archives (mission zip + text zip) into ONE stored archive (what a Gameplay+ install uses: the engine mounts 8 archive slots, one merged archive
    leaves a spare). Entry names must not clash. Returns {'zip', 'bytes', 'sha256', 'entries'}."""
    import hashlib
    E = tpl_env.get()
    entries = {}
    for zp in result['zips']:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n in entries:
                    raise BuildError([_msg('error', 'project', 'Cannot merge: %s is in both archives.' % n)])
                entries[n] = z.read(n)
    rep = E.ft.write_zip(out_zip, sorted(entries.items()))
    h = hashlib.sha256(open(out_zip, 'rb').read()).hexdigest()
    return dict(zip=out_zip, bytes=rep['zip_bytes'], sha256=h, entries=len(entries))
