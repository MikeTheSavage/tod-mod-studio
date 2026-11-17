"""New-map project library and in-process adapter for the unmodified vendored recipe.

Projects are plain PARAMS JSON. Check/build output is revision-bound and never overwrites a previous build.
All recipe calls run under Workspace.jobs' lock (the shared tools change process globals).
"""
import contextlib
import ast
import copy
import functools
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import math
import os
import re
import shutil
import sys
import uuid
import zipfile

from . import paths, game, mods, mapalloc
from todct import hullclean


def read(p):
    with open(p, encoding='utf-8-sig') as f:
        return json.load(f)


def write(p, value):
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(value, f, indent=1, allow_nan=False)
    os.replace(p + '.part', p)


def root():
    p = os.path.join(paths.user_dir(), 'newmaps')
    os.makedirs(p, exist_ok=True)
    return p


def directory(pid):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', pid or ''):
        raise ValueError('invalid new-map project id')
    return os.path.join(root(), pid)


def revision(params):
    return hashlib.sha256(json.dumps(params, sort_keys=True, allow_nan=False).encode()).hexdigest()


def entries(m):
    legacy = [dict(m['entry'], id=m['entry'].get('id', 'entry'))] if m.get('entry') else []
    return legacy + m.get('entries', [])


PLACEMENTS = ('separate', 'extension', 'aligned')
CARRY_MODES = ('all', 'region', 'nothing')
MARKER_ICONS = ('none', 'church', 'bullring', 'downtown', 'harbour', 'industrial', 'border', 'angel')      # what an entrance shows (same list as the recipe's)
MARKER_BEAMS = ('none', 'slim', 'full')
LOCK_REFUSED = {'cash': 'the game cannot test how much money the player holds',
                'money': 'the game cannot test how much money the player holds',
                'item': 'the game cannot test what the player carries', 'items': 'the game cannot test what the player carries',
                'time': 'the game cannot test the time of day', 'time_of_day': 'the game cannot test the time of day'}


def _nums(v, count, what):
    if not isinstance(v, list) or len(v) != count or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v):
        raise ValueError('%s needs %d finite numbers' % (what, count))


def _spot_numbers(spot):
    for key, count in [('pos', 3), ('orient', 4), ('size', 3)]:
        v = spot.get(key)
        if v is None and key != 'pos':
            continue
        _nums(v, count, key)
        if key == 'size' and min(v) <= 0:
            raise ValueError('box sizes must be greater than zero')
        if key == 'orient' and sum(x*x for x in v) < 1e-12:
            raise ValueError('facing quaternion cannot be zero')


def _entry_options(e):
    """The wave 3 entrance options: arrive, back, one_way, vehicle, prompt, lock, marker."""
    for k in ('arrive', 'back'):
        if e.get(k) is not None:
            if not isinstance(e[k], dict):
                raise ValueError('entry %s must be an object' % k)
            _spot_numbers(e[k])
            if k == 'arrive' and e[k].get('yaw') is not None:
                _nums([e[k]['yaw']], 1, 'yaw')
    if e.get('back') and e['back'].get('spot') is not None:
        _spot_numbers(e['back']['spot'])
    if e.get('prompt') not in (None, 'touch', 'use'):
        raise ValueError('an entrance prompt is touch or use')
    for k in ('one_way', 'vehicle'):
        if e.get(k) is not None and not isinstance(e[k], bool):
            raise ValueError('%s is true or false' % k)
    if e.get('marker') is not None:
        mk = e['marker']
        if not isinstance(mk, dict):
            raise ValueError('an entrance marker is {icon, beam}')
        if mk.get('icon') is not None and mk['icon'] not in MARKER_ICONS:
            raise ValueError('marker icon: choose %s' % ', '.join(MARKER_ICONS))
        if mk.get('beam') is not None and mk['beam'] not in MARKER_BEAMS:
            raise ValueError('marker beam: choose %s' % ', '.join(MARKER_BEAMS))
    if e.get('lock') is not None:
        lock = e['lock']
        if not isinstance(lock, dict):
            raise ValueError('lock must be an object')
        for k in lock:
            if k in LOCK_REFUSED:
                raise ValueError('An entrance cannot be locked by %s: %s. Lock it by a mission instead.' % (k, LOCK_REFUSED[k]))
        if not isinstance(lock.get('mission'), int) or isinstance(lock.get('mission'), bool) or lock['mission'] < 0:
            raise ValueError('a lock needs the number of the mission that unlocks it')


def validate(params):
    if not isinstance(params, dict) or not isinstance(params.get('maps'), list) or not params['maps']:
        raise ValueError('a project needs at least one map')
    for m in params['maps']:
        place = m.get('placement', 'separate')
        if place not in PLACEMENTS:
            raise ValueError('placement must be separate, extension or aligned')
        if place == 'extension':
            if not m.get('name'):
                raise ValueError('each section needs a name')
            h = m.get('host') or {}
            if not h.get('block'):
                raise ValueError('choose the host section for the extension')
            for k in ('enter', 'leave'):
                if not isinstance(h.get(k), dict):
                    raise ValueError('an extension needs host.%s (the loader box)' % k)
                _spot_numbers(h[k])
            mode = (m.get('carry') or {}).get('mode', 'all')
            if mode not in CARRY_MODES:
                raise ValueError('carry mode is all, region or nothing')
            if mode == 'region':
                _nums((m.get('carry') or {}).get('region'), 4, 'carry.region')
            for w in m.get('walls', []):
                _spot_numbers(w)
            continue
        if not m.get('name') or not m.get('source') or not m.get('arrival'):
            raise ValueError('each map needs a name, clone source and arrival')
        if place == 'aligned':
            nb = m.get('neighbour')
            if not isinstance(nb, dict) or not nb.get('map'):
                raise ValueError('an aligned map needs its neighbour (neighbour.map)')
            if nb.get('offset') is not None:
                _nums(nb['offset'], 3, 'neighbour.offset')
        names = [t.get('name') for t in m.get('teleports', [])]
        if any(not n for n in names) or len(set(names)) != len(names):
            raise ValueError('arrival spot names must be filled in and unique')
        ids = [e.get('id') for e in entries(m)]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('entry spot names must be filled in and unique in each map')
        for e in entries(m):
            if not e.get('block'):
                raise ValueError('choose a section block for each entry spot')
            if e.get('arrive_at') and e['arrive_at'] not in names:
                raise ValueError('entry arrival spot does not exist: ' + e['arrive_at'])
            _entry_options(e)
        has_way_out = bool(m.get('return')) or any(e.get('back') and not e.get('one_way') for e in entries(m))
        if not has_way_out:
            raise ValueError('each map needs an unlocked way out: a return spot, or an entrance with its own way back')
        spots = [m['arrival']] + entries(m) + m.get('teleports', []) + ([m['return']] if m.get('return') else [])
        for spot in spots:
            _spot_numbers(spot)
    if params.get('uid') is not None and not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', str(params['uid'])):
        raise ValueError('invalid project uid')


def get_project(pid):
    d = directory(pid)
    p = dict(id=pid, params=read(os.path.join(d, 'params.json')), path=d)
    for name in ('build', 'check'):
        f = os.path.join(d, name + '.json')
        if os.path.exists(f):
            p[name] = read(f)
    return p


def list_projects():
    out = []
    for pid in sorted(os.listdir(root())):
        if os.path.isfile(os.path.join(root(), pid, 'params.json')):
            out.append(get_project(pid))
    return out


def save_project(params, pid=None):
    validate(params)
    if not params.get('uid'):
        params['uid'] = mapalloc.new_uid()          # the permanent identity: map numbers are given out from it at install time
    pid = pid or uuid.uuid4().hex[:12]
    d = directory(pid)
    os.makedirs(d, exist_ok=True)
    write(os.path.join(d, 'params.json'), params)
    return get_project(pid)


def import_project(path):
    p = os.path.join(path, 'manifest.json') if os.path.isdir(path) else path
    data = read(p)
    # A manifest describes the result, not all recipe inputs. Recover the exact recipe from a build snapshot,
    # or ask for the original JSON rather than inventing walls, collision or a return destination.
    if data.get('base_limits') is not None or os.path.basename(p).lower() == 'manifest.json':
        folder = os.path.dirname(p)
        for f in ('params.json', 'recipe_params.json'):
            candidate = os.path.join(folder, f)
            if os.path.isfile(candidate):
                return save_project(read(candidate))
        # Older recipe builds lack a params snapshot. Keep the manifest's known fields and recover a return
        # loader from spec.json. Unknown inputs remain visible in the import warning.
        spec_path = os.path.join(folder, 'spec.json')
        if not os.path.isfile(spec_path):
            raise ValueError('This older build has no recipe snapshot or spec.json. Import its original PARAMS JSON.')
        spec = read(spec_path)
        maps = []
        for mm in data['maps']:
            m = {k: copy.deepcopy(mm[k]) for k in ('name', 'source', 'arrival', 'entry', 'entries', 'teleports') if k in mm}
            if m.get('entries'):
                m.pop('entry', None)  # In a manifest, entry is also a summary of entries[0]. PARAMS are additive.
            ops = [o for b in spec['blocks'] if short(b['block']) in (short(mm['map_block']), short(mm['submap_block'])) for o in b['ops']]
            arrival_op = next((o for o in ops if o.get('name') == mm['arrival_node']), None)
            if arrival_op:
                recovered = {o['name']: dict(name=o['name'], pos=o['pos'], orient=o.get('orient', [0, 0, 0, 1]))
                             for o in ops if o is not arrival_op and o.get('op') == 'graft'
                             and all(o.get(k) == arrival_op.get(k) for k in ('from_block', 'from_fragment', 'entity'))}
                m['teleports'] = [dict(recovered.get(t['name'], {}), **t) for t in m['teleports']] if 'teleports' in m else list(recovered.values())
            loaders = [o for o in ops if o.get('name') in ('TriggerLoad_MAINMAP_Return', 'TriggerLoad_SUBMAP_Return')]
            if len(loaders) != 2:
                raise ValueError('this build has no complete return spot; import its original PARAMS JSON')
            r = loaders[0]
            actions = [o['child_sets'][0]['set'] for o in loaders]
            m['return'] = dict(pos=r['pos'], orient=r.get('orient', [0, 0, 0, 1]),
                               size=[r['set'][k] for k in ('width', 'height', 'length')],
                               target_map=actions[0]['TargetName'], target_submap=actions[1]['TargetName'],
                               teleport_to=actions[0]['Teleport_to'], teleport_block='overdose.main')
            if short(mm['submap_block']) in [short(b['block']) for b in spec['blocks']
                                           if any(o.get('name') == mm['arrival_node'] for o in b['ops'])]:
                m['nodes_in'] = 'submap'
            # The original recipe is needed to reproduce collision, props, enemies etc.; do not pretend otherwise.
            maps.append(m)
        data = dict(package=data.get('package', 'Imported'), maps=maps,
                    import_warning='Imported arrival, entry and return spots from this older build. Other contents '
                                   '(walls, collision, props and enemies) need the original PARAMS JSON. Check the return node block.')
    return save_project(data)


def short(e):
    return e.replace('\\', '/').split('/')[-1].lower()


def load_recipe():
    paths.setup_tools()
    import fragtool, submaptool, todfrag  # noqa: F401 (preload the app's patched codecs)
    # Use the app's codecs: their only local adaptations locate per-user property tables and bundled tools.
    # Bind submaptool explicitly from the recipe snapshot, restoring the companion module after import.
    p = os.path.join(paths.BACKEND, 'vendor', 'newmap')
    oldpath, oldenv = list(sys.path), dict(os.environ)
    oldsub = sys.modules.get('submaptool')
    try:
        os.environ.update(TOD_TOOLS=paths.VENDOR, TOD_FW=os.path.join(paths.VENDOR, 'fragment_writer'),
                          TOD_SE=os.path.join(paths.VENDOR, 'save_editor'))
        sp = importlib.util.spec_from_file_location('todms_newmap_submaptool', os.path.join(paths.VENDOR, 'level_streaming', 'submaptool.py'))   # the ONE vendored submaptool (has clone_of_file)
        sub = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(sub)
        sys.modules['submaptool'] = sub
        sp = importlib.util.spec_from_file_location('todms_newmap_recipe', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'newmap_recipe', 'make_new_map.py'))
        recipe = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(recipe)
        return recipe
    finally:
        sys.path[:] = oldpath
        if oldsub is None:
            sys.modules.pop('submaptool', None)
        else:
            sys.modules['submaptool'] = oldsub
        for k in ('TOD_TOOLS', 'TOD_FW', 'TOD_SE'):
            if k in oldenv:
                os.environ[k] = oldenv[k]
            else:
                os.environ.pop(k, None)


@functools.lru_cache(maxsize=1)
def info():
    r = load_recipe()
    # Inspect syntax, excluding the docstring, so documenting a planned interface cannot enable it prematurely.
    with open(r.__file__, encoding='utf-8') as f:
        src = f.read()
    supported = any(isinstance(n, ast.Constant) and n.value == 'entries' for n in ast.walk(ast.parse(src)))
    return dict(sources=r.SOURCES, entries_supported=supported)


def overlay_module():
    bo = sys.modules.get('base_overlay')
    if bo is None:
        load_recipe()
        bo = sys.modules.get('base_overlay')
    return bo


def run_argv(argv, ws, overlay=None):
    """Call the recipe's CLI entry point, with argv, in this process. No subprocess or recipe logic copy.
    overlay: (zips, entries) = earlier pack stages the recipe reads (overdose.main and every block they changed) instead of blocks.naz's."""
    recipe = load_recipe()
    ft = recipe.ft
    oldargv, oldarch, oldnaz, oldwrite = sys.argv, ft._arch, ft.GOG_NAZ, ft.write_zip
    oldpath = list(sys.path)
    oldtools = os.environ.get('TOD_TOOLS')
    result = {}
    original = recipe.build
    hullclean.audit_reset()

    def capture(*a, **kw):
        rep = original(*a, **kw)
        if isinstance(rep, dict) and rep.get('checks') is not None and hullclean.AUDIT['hulls']:
            rep['checks'].append(hullclean.audit_check())
        result.update(rep)
        # Old recipes return early on --check-only without writing their report.
        write(os.path.join(a[1], 'recipe_report.json'), rep)
        return rep

    try:
        os.environ['TOD_TOOLS'] = paths.VENDOR
        ft._arch = ws.game.base()
        ft.GOG_NAZ = ws.game.naz
        ft.write_zip = lambda p, e, **kw: oldwrite(p, e, naz_for_mtime=ws.game.naz)
        recipe.build = capture
        sys.argv = [recipe.__file__] + list(argv)
        if overlay and overlay[0]:
            overlay_module().configure(list(overlay[0]), list(overlay[1]) if overlay[1] else None)
        with contextlib.redirect_stdout(io.StringIO()):
            recipe.main()
        return result
    finally:
        if overlay and overlay[0]:
            overlay_module().configure([])
        sys.argv, ft._arch, ft.GOG_NAZ, ft.write_zip = oldargv, oldarch, oldnaz, oldwrite
        sys.path[:] = oldpath
        if oldtools is None:
            os.environ.pop('TOD_TOOLS', None)
        else:
            os.environ['TOD_TOOLS'] = oldtools


_HOSTS = {}


def entry_hosts(ws, progress=None):
    """Which existing blocks can take an entry loader pair (the recipe's list_entry_hosts): offer, proven, reason per block.
    Cached per game folder and recipe version. Older recipes without the listing return an empty list."""
    recipe = load_recipe()
    if not hasattr(recipe, 'list_entry_hosts'):
        return dict(hosts=[], supported=False)
    key = (ws.game.base(), file_hash(recipe.__file__))
    if key not in _HOSTS:
        if progress:
            progress('Checking which map sections can take an entry')
        ft = recipe.ft
        oldarch, oldnaz, oldtools = ft._arch, ft.GOG_NAZ, os.environ.get('TOD_TOOLS')
        try:
            os.environ['TOD_TOOLS'] = paths.VENDOR
            ft._arch, ft.GOG_NAZ = ws.game.base(), ws.game.naz
            _HOSTS[key] = recipe.list_entry_hosts()
        finally:
            ft._arch, ft.GOG_NAZ = oldarch, oldnaz
            if oldtools is None:
                os.environ.pop('TOD_TOOLS', None)
            else:
                os.environ['TOD_TOOLS'] = oldtools
    return dict(hosts=_HOSTS[key], supported=True)


def expand(params, assets=None):
    """The map generator's hook (todms.mapgen, another worker's module): high-level recipe keys become the primitives the builder knows.
    Without that module the recipe passes through unchanged."""
    mod = sys.modules.get('todms.mapgen')
    if mod is None:
        try:
            spec = importlib.util.find_spec('todms.mapgen')
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            return params
        mod = importlib.import_module('todms.mapgen')
    fn = getattr(mod, 'expand', None)
    if not fn:
        return params
    if 'assets' in inspect.signature(fn).parameters:
        # the asset index (when built) lets the generators name the game's own pictures and models; a missing index is not an error
        if assets is None and has_generator_keys(params):
            try:
                from . import assetindex
                assets = assetindex.load()
            except Exception:                                    # noqa: BLE001
                assets = None
        return fn(copy.deepcopy(params), assets)
    return fn(copy.deepcopy(params))


def has_generator_keys(params):
    return any(k in m for m in (params or {}).get('maps', []) for k in ('ground_paint', 'scatter'))


def prepared(params, alloc_entry=None):
    """What the builder receives: the expanded recipe with the allocated numbers filled in."""
    p = expand(params)
    if alloc_entry:
        p = mapalloc.inject(p, alloc_entry)
    return p


def build_params(ws, params, out_dir, overlay=None, progress=None, alloc_entry=None, expanded=False):
    """Build the new-map package of recorded params into out_dir, reading earlier pack stages through `overlay` (zips, entries).
    alloc_entry: this project's map and section numbers from the install allocation (mapalloc).
    -> the path of stream_override.zip. Raises ValueError with the recipe's failing checks."""
    validate(params)
    if not expanded:
        params = prepared(params, alloc_entry)
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, 'params.json')
    write(p, params)
    if progress:
        progress('Building the new-map package')
    rep = run_argv([p, '--out', out_dir], ws, overlay=overlay)
    bad = [c for c in rep.get('checks', []) if c.get('result') == 'FAIL']
    if rep.get('result') != 'PASS' or bad:
        raise ValueError('The map package did not build: ' + '; '.join(str(c.get('name') or c)[:120] for c in bad[:3]))
    return os.path.join(out_dir, 'stream_override.zip')


def run(ws, pid, check_only=False, progress=None):
    project = get_project(pid)
    params = prepared(copy.deepcopy(project['params']))
    validate(params)
    if not info()['entries_supported']:
        for m in params['maps']:
            es = entries(m)
            if len(es) != 1 or es[0].get('arrive_at'):
                raise ValueError('The bundled map builder supports one entry to the main arrival. Update the vendored recipe for multiple entries or named arrivals.')
            m['entry'] = es[0]
            m.pop('entries', None)
            if not m['entry'].get('parent'):
                raise ValueError('This older map builder needs an entry parent. Import an existing recipe or set the parent fields.')
    d = os.path.join(directory(pid), 'runs', uuid.uuid4().hex[:12])
    os.makedirs(d)
    p = os.path.join(d, 'params.json')
    write(p, params)
    if progress:
        progress('Checking the map recipe' if check_only else 'Building the new-map package')
    rep = run_argv([p, '--out', d] + (['--check-only'] if check_only else []), ws)
    record = dict(revision=revision(project['params']), folder=d, report=rep)
    if not check_only and rep.get('result') == 'PASS' and not any(c['result'] == 'FAIL' for c in rep.get('checks', [])):
        z = os.path.join(d, 'stream_override.zip')
        record['sha256'] = file_hash(z)
    write(os.path.join(directory(pid), ('check' if check_only else 'build') + '.json'), record)
    return record


def file_hash(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def archive_entries(p):
    with zipfile.ZipFile(p) as z:
        return {n.replace('\\', '/').lower() for n in z.namelist()}


def installed(folder):
    p = os.path.join(folder, 'todms_newmaps.json')
    return read(p) if os.path.exists(p) else {}


def install(ws, pid, progress=None):
    from . import pack
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    from . import missions_tpl
    if pid in missions_tpl.installed_newmap_ids(folder):
        raise ValueError('This map is already installed as part of your mission templates (its missions are built into it). '
                         'Uninstall those missions first if you want the plain map.')
    project = get_project(pid)
    b = project.get('build') or {}
    if b.get('revision') != revision(project['params']) or not b.get('sha256'):
        raise ValueError('Build this version of the project successfully before installing it')
    z = os.path.join(b['folder'], 'stream_override.zip')
    if file_hash(z) != b['sha256']:
        raise ValueError('The built package changed. Build it again before installing.')
    records = dict(installed(folder))
    records[pid] = dict(revision=b['revision'], params=copy.deepcopy(project['params']), sha256=b['sha256'],
                        name=project['params'].get('package') or pid)
    r = pack.apply(ws, 'install a new map', newmaps=records, hints=dict(newmap_built={pid: z}), progress=progress)
    return dict(records[pid], zip=game.PACK_ZIP, configpc_line=r['line'])


def _hosted_missions(folder, pid):
    from . import missions_tpl
    return {k: v for k, v in (missions_tpl.installed(folder).get('projects') or {}).items() if pid in (v.get('newmaps') or {})}


def uninstall(ws, pid, progress=None):
    """Take a new map out of the pack: its entrances in the shipped sections and the missions built on it go with it. The saves that
    stand on it are reported (never rewritten); a copy of the saves is made first by the install itself."""
    from . import pack, mapnet
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    directory(pid)
    records = dict(installed(folder))
    hosted = _hosted_missions(folder, pid)
    if pid not in records and not hosted:
        return dict(message='This project is not installed in this game folder')
    report = mapnet.removal_report(ws, pid)
    records.pop(pid, None)
    kw = {}
    if hosted:
        from . import missions_tpl
        rest = {k: v for k, v in (missions_tpl.installed(folder).get('projects') or {}).items() if k not in hosted}
        kw['missions'] = dict(projects=rest) if rest else {}
    pack.apply(ws, 'remove a new map', newmaps=records, progress=progress, **kw)
    return dict(message='New-map package removed', report=report)


def set_enabled(ws, pid, enabled, progress=None):
    """Switch an installed map off (or on again) without losing its numbers: the pack is rebuilt without its entrances and without the
    missions built on it; they are kept in the record and come back when it is switched on. The report says which saves stand on it."""
    from . import pack, mapnet, missions_tpl
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    records = {k: dict(v) for k, v in installed(folder).items()}
    if pid not in records:
        raise ValueError('This project is not installed in this game folder')
    rec = records[pid]
    if bool(rec.get('disabled')) == (not enabled):
        return dict(message='Already %s' % ('on' if enabled else 'off'))
    kw = {}
    report = None
    mrec = missions_tpl.installed(folder)
    allp = dict(mrec.get('projects') or {})
    if enabled:
        back = rec.pop('held_missions', None) or {}
        rec.pop('disabled', None)
        if back:
            allp.update(back)
            kw['missions'] = dict(projects=allp)
    else:
        report = mapnet.removal_report(ws, pid)
        hosted = _hosted_missions(folder, pid)
        rec['disabled'] = True
        if hosted:
            rec['held_missions'] = hosted
            rest = {k: v for k, v in allp.items() if k not in hosted}
            kw['missions'] = dict(projects=rest) if rest else {}
    pack.apply(ws, 'install a new map' if enabled else 'switch a new map off', newmaps=records, progress=progress, **kw)
    return dict(message='Map switched on' if enabled else 'Map switched off', report=report)


def minimap(ws, pid, progress=None):
    """Draw the minimap pack of every map of a project that has generator keys (terrain, roads, water, ...), into the project's own
    folder (`minimap/`): one pack and one occupancy file per map and an index of its own. Vanilla radar gets nothing (an empty disc);
    the Gameplay+ minimap reads the pack by position. -> dict(folder, maps [dict(name, line, bounds, tiles, bytes, overlaps)], checks)."""
    from . import minimap as mm
    project = get_project(pid)
    folder = os.path.join(directory(pid), 'minimap')
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    assets = None
    try:
        from . import assetindex
        assets = assetindex.load(ws)
    except Exception:                                            # noqa: BLE001
        assets = None
    maps, checks, lines, taken = [], [], [], dict(mm.SHIPPED_BOUNDS)
    for m in project['params'].get('maps', []):
        plan = None
        if ((m.get('scene') or {}).get('plan')):                  # a scene map is drawn from its plan (streets, buildings, water seen from above)
            from . import scenplan
            plan = scenplan.read(directory(pid), m['scene']['plan'])
        if plan is None and not any(k in m for k in ('terrain', 'roads', 'water', 'edges', 'scatter')):
            continue
        info = mm.build(dict(m, _plan=plan) if plan is not None else m, folder, None, assets, progress)
        over = mm.overlaps(info['bounds'], taken)
        taken[info['name']] = info['bounds']
        for c in mm.calibrate(folder, info):
            checks.append(c)
        if over:
            checks.append(dict(check='minimap area of %s' % info['name'], result='WARN',
                               evidence='the pack covers places that the pack of %s also covers; the minimap picks a pack by position, so move the map' % ', '.join(over)))
        lines.append(info['line'])
        maps.append(dict(name=info['name'], line=info['line'], bounds=info['bounds'], tiles=info['tiles'], bytes=info['bytes'], overlaps=over))
    if not maps:
        raise ValueError('This project has no ground, roads or water to draw a minimap from')
    with open(os.path.join(folder, 'minimap.txt'), 'w', newline=chr(10)) as f:
        f.write(mm.merge_lines(lines))
    return dict(folder=folder, maps=maps, checks=checks, vanilla='The original radar shows an empty disc in a new map; only the Gameplay+ minimap draws this picture.')
