"""New-map project library and in-process adapter for the unmodified vendored recipe.

Projects are plain PARAMS JSON. Check/build output is revision-bound and never overwrites a previous build.
All recipe calls run under Workspace.jobs' lock (the shared tools change process globals).
"""
import contextlib
import ast
import copy
import functools
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sys
import uuid
import zipfile

from . import paths, game, mods


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


def validate(params):
    if not isinstance(params, dict) or not isinstance(params.get('maps'), list) or not params['maps']:
        raise ValueError('a project needs at least one map')
    for m in params['maps']:
        if not m.get('name') or not m.get('source') or not m.get('arrival') or not m.get('return'):
            raise ValueError('each map needs a name, clone source, arrival and return spot')
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
        for spot in [m['arrival'], m['return']] + entries(m) + m.get('teleports', []):
            for key, count in [('pos', 3), ('orient', 4), ('size', 3)]:
                v = spot.get(key)
                if v is None and key != 'pos':
                    continue
                if not isinstance(v, list) or len(v) != count or any(
                        not isinstance(x, (int, float)) or not math.isfinite(x) for x in v):
                    raise ValueError('%s needs %d finite numbers' % (key, count))
                if key == 'size' and min(v) <= 0:
                    raise ValueError('box sizes must be greater than zero')
                if key == 'orient' and sum(x*x for x in v) < 1e-12:
                    raise ValueError('facing quaternion cannot be zero')


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
        sp = importlib.util.spec_from_file_location('todms_newmap_recipe', os.path.join(p, 'make_new_map.py'))
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


def run_argv(argv, ws):
    """Call the recipe's CLI entry point, with argv, in this process. No subprocess or recipe logic copy."""
    recipe = load_recipe()
    ft = recipe.ft
    oldargv, oldarch, oldnaz, oldwrite = sys.argv, ft._arch, ft.GOG_NAZ, ft.write_zip
    oldpath = list(sys.path)
    oldtools = os.environ.get('TOD_TOOLS')
    result = {}
    original = recipe.build

    def capture(*a, **kw):
        rep = original(*a, **kw)
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
        with contextlib.redirect_stdout(io.StringIO()):
            recipe.main()
        return result
    finally:
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


def run(ws, pid, check_only=False, progress=None):
    project = get_project(pid)
    params = copy.deepcopy(project['params'])
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


def refuse_conflict(a, b):
    overlap = sorted(set(a) & set(b))
    if overlap:
        raise ValueError('These packages rebuild the same block: %s. Remove the installed package or mod first.' % ', '.join(overlap))


def installed(folder):
    p = os.path.join(folder, 'todms_newmaps.json')
    return read(p) if os.path.exists(p) else {}


def check_mod_conflicts(folder, zip_path):
    candidate = archive_entries(zip_path)
    for rec in installed(folder).values():
        p = os.path.join(folder, rec['zip'])
        if os.path.exists(p):
            refuse_conflict(candidate, archive_entries(p))


def install(ws, pid, progress=None):
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
    candidate = archive_entries(z)
    modzip = os.path.join(folder, game.MOD_ZIP)
    if os.path.exists(modzip):
        refuse_conflict(candidate, archive_entries(modzip))
    mz = os.path.join(folder, game.MISSIONS_ZIP)
    if os.path.exists(mz):
        refuse_conflict(candidate, archive_entries(mz))
    records = installed(folder)
    for other, rec in records.items():
        if other != pid and os.path.exists(os.path.join(folder, rec['zip'])):
            refuse_conflict(candidate, archive_entries(os.path.join(folder, rec['zip'])))
    name = 'todms_newmap_' + pid + '.zip'
    dst = os.path.join(folder, name)
    if os.path.exists(dst) and pid not in records:
        raise ValueError('A file with this package name already exists in the game folder')
    if os.path.exists(dst):
        shutil.copy2(dst, dst + '.todms_backup')
    shutil.copy2(z, dst + '.part')
    os.replace(dst + '.part', dst)
    line = mods.set_filesystem(folder, name, remove=[name])
    records[pid] = dict(zip=name, revision=b['revision'], configpc_line=line)
    write(os.path.join(folder, 'todms_newmaps.json'), records)
    return records[pid]


def uninstall(ws, pid, progress=None):
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    directory(pid)
    records = installed(folder)
    rec = records.get(pid)
    if not rec:
        return dict(message='This project is not installed in this game folder')
    name = 'todms_newmap_' + pid + '.zip'
    mods.set_filesystem(folder, None, remove=[name])
    p = os.path.join(folder, name)
    if os.path.exists(p):
        os.remove(p)
    records.pop(pid)
    write(os.path.join(folder, 'todms_newmaps.json'), records)
    return dict(message='New-map package removed')
