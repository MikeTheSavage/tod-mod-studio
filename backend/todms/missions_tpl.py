"""Mission templates: pick a mission type, place its giver and points on a map, set its numbers, build and install.

The mission template library (vendor/missions/todtpl, see scripts/vendor_missions.py) does the building. This module is the
Mod Studio side: projects, host choices, the combined build of everything installed in one game, and installing it.

Rules this module keeps:
  * ONE build per game install. The library numbers objective text rows in order per build, so every mission of the
    install is built as ONE project (the projects marked as installed in the game folder, plus the one being built).
  * At most 17 new missions per game install, shared by all projects (the library's own message is shown).
  * Builds run on the game's REAL archive chain (configpc.txt, so on top of Gameplay+ or TOD HD when they are installed).
  * The mission package (mission blocks + texts merged) is the LAST stage of the pack, todms_pack.zip (pack.py).
  * A new-map host is built into the mission package. A New maps package of the same map is taken out when the
    missions are installed (it would be the same blocks twice).
Projects are stored like the New maps projects, in <TODMS_HOME>/mission_projects/<id>/project.json.
"""
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import shutil
import sys
import uuid

from . import paths, game, mods, newmap, limits, mapalloc

ZIP = 'todms_missions.zip'
RECORD = 'todms_missions.json'
SLOT_LIMIT = limits.value('P1')      # archives the engine mounts from the filesystem line
MISSION_SLOTS = limits.value('L7')   # new mission indices per install
FORMAT = 1


# ------------------------------------------------------------------------------------------------ projects
def root():
    p = os.path.join(paths.user_dir(), 'mission_projects')
    os.makedirs(p, exist_ok=True)
    return p


def directory(pid):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', pid or ''):
        raise ValueError('invalid mission project id')
    return os.path.join(root(), pid)


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, default=str).encode()).hexdigest()


def _scale_pt(v, r, old=(0.0, 0.0, 0.0), new=(0.0, 0.0, 0.0)):
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return v
    return [None if c is None else round((float(c) - o) * r + n, 3) for c, o, n in zip(v, old, new)]


def _scale_rect(v, r, old, new):
    return [round((float(v[0]) - old[0]) * r + new[0], 3), round((float(v[1]) - old[2]) * r + new[2], 3),
            round((float(v[2]) - old[0]) * r + new[0], 3), round((float(v[3]) - old[2]) * r + new[2], 3)]


def rescale_hosts(newmap_id, r, old_place=(0.0, 0.0, 0.0), new_place=(0.0, 0.0, 0.0)):
    """A new map changed its scale (`r` = new / old) or its place in the world: in every mission project that uses it, the host area, its ground
    height and the positions of the missions on it (points, point lists, rectangles; sizes stay) move out from the scene's middle and on to the
    new place. -> projects changed."""
    L = lib()
    kinds = {}
    changed = 0
    old, new = [float(v) for v in old_place], [float(v) for v in new_place]
    for rec in list_projects():
        proj = copy.deepcopy(rec['project'])
        mine = {h['id'] for h in proj.get('hosts') or [] if h.get('kind') == 'new_map' and h.get('newmap_id') == newmap_id}
        if not mine:
            continue
        for h in proj['hosts']:
            if h['id'] in mine:
                if h.get('area'):
                    h['area'] = _scale_rect(h['area'], r, old, new)
                if h.get('ground_y') is not None:
                    h['ground_y'] = round((float(h['ground_y']) - old[1]) * r + new[1], 3)
                if h.get('bounds'):
                    h['bounds'] = _scale_rect(h['bounds'], r, old, new)
        for m in proj.get('missions') or []:
            if m.get('host') not in mine:
                continue
            if m['type'] not in kinds:
                kinds[m['type']] = {s['key']: s['kind'] for s in L.template_schema(m['type'], None).get('params', [])}
            ks = kinds[m['type']]
            pr = m.get('params') or {}
            for k, v in list(pr.items()):
                kd = ks.get(k)
                if kd == 'point':
                    pr[k] = _scale_pt(v, r, old, new)
                elif kd == 'points':
                    pr[k] = [_scale_pt(q, r, old, new) for q in v]
                elif kd == 'rect':
                    pr[k] = _scale_rect(v, r, old, new)
                elif kd == 'rects':
                    pr[k] = [_scale_rect(q, r, old, new) for q in v]
        save_project(proj, rec['id'])
        changed += 1
    return changed


def check_project(project):
    """Structure only (the library checks the contents): plain messages for anything that cannot be saved."""
    if not isinstance(project, dict):
        raise ValueError('a mission project needs a name, hosts and missions')
    if not str(project.get('name') or '').strip():
        raise ValueError('give the mission project a name')
    hosts = project.get('hosts') or []
    ids = [h.get('id') for h in hosts]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('every host needs its own name')
    for h in hosts:
        if h.get('kind') not in ('new_map', 'existing'):
            raise ValueError('a host is either a new map or an existing map section')
        if h['kind'] == 'new_map' and not h.get('newmap_id'):
            raise ValueError('choose which New maps project the host "%s" is' % h['id'])
        if h['kind'] == 'new_map':
            newmap.directory(h['newmap_id'])
        if h['kind'] == 'existing' and not h.get('block'):
            raise ValueError('choose the map section of the host "%s"' % h['id'])
    mids = [m.get('id') for m in project.get('missions') or []]
    if any(not i for i in mids) or len(set(mids)) != len(mids):
        raise ValueError('every mission needs its own name')
    from . import characters
    for m in project.get('missions') or []:
        eb = m.get('enemy_body')
        if eb in (None, '', 'template'):
            continue
        try:
            ok = characters.row(int(eb)) is not None and characters.row(int(eb))['placeable']
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError('the enemy body of "%s" cannot be placed' % m['id'])


def get_project(pid):
    d = directory(pid)
    p = dict(id=pid, project=newmap.read(os.path.join(d, 'project.json')), path=d)
    for name in ('build',):
        f = os.path.join(d, name + '.json')
        if os.path.exists(f):
            p[name] = newmap.read(f)
    return p


def list_projects():
    return [get_project(pid) for pid in sorted(os.listdir(root())) if os.path.isfile(os.path.join(root(), pid, 'project.json'))]


def save_project(project, pid=None):
    check_project(project)
    pid = pid or uuid.uuid4().hex[:12]
    d = directory(pid)
    os.makedirs(d, exist_ok=True)
    newmap.write(os.path.join(d, 'project.json'), dict(project, format=FORMAT))
    return get_project(pid)


def delete_project(ws, pid):
    if ws.game and pid in installed(ws.game.folder).get('projects', {}):
        raise ValueError('This mission project is installed in your game. Uninstall it first.')
    shutil.rmtree(directory(pid), ignore_errors=True)
    return dict(message='Mission project deleted')


# ------------------------------------------------------------------------------------------------ samples
VENDOR = os.path.join(paths.BACKEND, 'vendor', 'missions')
SAMPLES = {
    'mesa': dict(title='Mesa Compound', files=('mesa_map.json', 'mesa_compound.json'), id='sample-mesa-compound',
                 text='A new walled compound map with all 17 mission types, one giver each. It uses ALL 17 new mission slots: '
                      'installing it leaves no room for other new missions in the same game.'),
    'race': dict(title='A race in the yard', files=('second_map_params.json', os.path.join(paths.DATA, 'starters', 'race_yard.json')),
                 id='sample-race-yard', text='A small yard map with one checkpoint race: a short way to see a mission from start to finish.'),
    'yard': dict(title='Two missions in a small yard', files=('second_map_params.json', 'second_map_ghost_showdown.json'),
                 id='sample-yard', text='A small yard map with a showdown and a ghost mission: a short way to see the whole flow.'),
}


def _sample_file(name):
    return name if os.path.isabs(name) else os.path.join(VENDOR, 'samples', name)


def sample_info():
    out = []
    for key, s in SAMPLES.items():
        proj = json.load(open(_sample_file(s['files'][1]), encoding='utf-8'))
        out.append(dict(key=key, title=s['title'], text=s['text'], missions=len(proj['missions']), id=s['id'],
                        uses_all_slots=len(proj['missions']) >= MISSION_SLOTS))
    return out


def open_sample(key):
    """Create (or refresh) the sample's New maps project and mission project; returns the mission project."""
    s = SAMPLES[key]
    maps = json.load(open(_sample_file(s['files'][0]), encoding='utf-8'))
    lib = json.load(open(_sample_file(s['files'][1]), encoding='utf-8'))
    maps['package'] = s['title'] + ' (sample map)'
    newmap.save_project(maps, s['id'])
    hosts = []
    for h in lib['hosts']:
        hosts.append(dict({k: v for k, v in h.items() if k not in ('comment',)}, newmap_id=s['id']))
    missions = [dict(id=m['id'], type=m['type'], host=m['host'], index=m.get('index', 'auto'), params=m.get('params') or {})
                for m in lib['missions']]
    return save_project(dict(name=s['title'] + ' (sample)', hosts=hosts, missions=missions, options={},
                             sample=key), s['id'])


# ------------------------------------------------------------------------------------------------ the library
_STATE = {}


def recipe():
    if 'recipe' not in _STATE:
        _STATE['recipe'] = newmap.load_recipe()
    return _STATE['recipe']


def lib(ws=None):
    """The vendored template library, bound to Mod Studio's own tools and to the new-map recipe (one submaptool)."""
    paths.setup_tools()
    paths.ensure_cpu_guard()
    if 'lib' not in _STATE:
        base = os.path.join(paths.BACKEND, 'vendor', 'missions')
        if base not in sys.path:
            sys.path.append(base)
        import todtpl
        from todtpl import tpl_env
        tpl_env.configure(blocks_naz=ws.game.naz if ws else os.path.join(os.environ.get('TOD_NAZ', ''), ''),
                          backend=paths.BACKEND, maps_tools=os.path.join(paths.BACKEND, 'vendor', 'newmap'),
                          textool_dir=os.path.join(paths.VENDOR, 'text'), missiontool_dir=os.path.join(paths.VENDOR, 'missions'),
                          home=paths.user_dir(), cache=paths.cache_dir(), shipped_strings=None)
        _STATE['lib'] = todtpl
    return _STATE['lib']


@contextlib.contextmanager
def session(ws):
    """Bind the shared tool modules to this game for one library call (callers hold the jobs lock); restore afterwards."""
    L = lib(ws)
    from todtpl import tpl_env
    from . import mapgen
    mapgen.install_builder_plug()                    # a host map made of generated parts or an imported scene needs the builder's part and picture kinds
    paths.setup_tools(ws.game.naz)
    tpl_env.CFG['blocks_naz'] = ws.game.naz
    E = tpl_env.get()
    tpl_env._MAKEMAP = recipe()             # the recipe bound to the ONE vendored submaptool
    ft = E.ft
    old = (ft._arch, ft.GOG_NAZ, ft.write_zip)
    oldwrite = ft.write_zip
    try:
        ft._arch, ft.GOG_NAZ = ws.game.base(), ws.game.naz
        ft.write_zip = lambda p, e, **kw: oldwrite(p, e, naz_for_mtime=ws.game.naz)
        recipe().ft._arch = ft._arch
        yield L
    finally:
        ft._arch, ft.GOG_NAZ, ft.write_zip = old
        try:
            E.overlay.configure([])           # never leave the Gameplay+ reader switched on for the other tabs
        except Exception:                      # noqa: BLE001
            pass


def chain_paths(ws):
    return [os.path.join(ws.game.folder, a) for a in ws.game.chain('effective')]


def chain_signature(ws):
    return game.chain_signature(ws.game.folder, [os.path.basename(p) for p in chain_paths(ws)])


# ------------------------------------------------------------------------------------------------ the install record
def record_path(folder):
    return os.path.join(folder, RECORD)


def installed(folder):
    p = record_path(folder)
    return newmap.read(p) if os.path.exists(p) else {}


def installed_newmap_ids(folder):
    """New maps projects that the installed mission package contains as host maps."""
    return sorted({nid for p in installed(folder).get('projects', {}).values() for nid in p.get('newmaps', {})})


# ------------------------------------------------------------------------------------------------ compose one library project
def snapshot_of(pid, project):
    """Everything a build needs from a project: the project and the params of the New maps projects it uses."""
    nms = {}
    for h in project.get('hosts') or []:
        if h['kind'] == 'new_map':
            nms[h['newmap_id']] = newmap.get_project(h['newmap_id'])['params']
    return dict(name=project['name'], project=project, newmaps=nms)


# Project-level keys of a new-map project (not part of one map): they go to blocks that already work, so they have to travel with the maps
CARRY_KEYS = ('existing_spots', 'existing_vehicles', 'existing_enemies', 'test_loaders')


def carried(params):
    """{key: [entries]} of the project-level keys a new-map project holds."""
    return {k: copy.deepcopy(params[k]) for k in CARRY_KEYS if (params or {}).get(k)}


def carry_missing(wanted, used):
    """Keys (and entry counts) that were requested but are not in the params the build really used -> list of text."""
    out = []
    for k, ents in wanted.items():
        have = (used or {}).get(k) or []
        for e in ents:
            if e not in have:
                out.append('%s: %s did not reach the build' % (k, e.get('name') or e.get('block') or e.get('target_map') or 'an entry'))
    return out


def compose(entries, pins=None, alloc=None, extra_maps=None, carry=None):
    """entries: [(pid, snapshot)] -> (library project, {library mission id: (pid, mission id)}, {library host id: (pid, host id)}).
    pins: {(pid, mission id): (type, index)}: a mission keeps the index it had when it was installed."""
    pins = pins or {}
    multi = len(entries) > 1
    maps, offset = [], {}
    hosts, missions, idmap, hostmap = [], [], {}, {}
    keep = False
    extra = carry if carry is not None else {}
    for pid, snap in entries:
        for nid, params in snap['newmaps'].items():
            if nid not in offset:
                offset[nid] = len(maps)
                entry = ((alloc or {}).get('owners') or {}).get(mapalloc.key_of(params, nid))
                maps.extend(copy.deepcopy((mapalloc.inject(newmap.expand(params), entry) if entry else newmap.expand(params))['maps']))
                for k, v in carried(params).items():
                    extra.setdefault(k, []).extend(v)
    for nid, params in (extra_maps or []):           # standalone new maps folded into this pass (after the maps the missions use)
        if nid not in offset:
            offset[nid] = len(maps)
            entry = ((alloc or {}).get('owners') or {}).get(mapalloc.key_of(params, nid))
            maps.extend(copy.deepcopy((mapalloc.inject(newmap.expand(params), entry) if entry else newmap.expand(params))['maps']))
            for k, v in carried(params).items():
                extra.setdefault(k, []).extend(v)
    for pid, snap in entries:
        proj = snap['project']
        pre = (pid + '~') if multi else ''
        keep = keep or bool((proj.get('options') or {}).get('keep_map_enemies'))
        for h in proj.get('hosts') or []:
            hd = {k: v for k, v in h.items() if k not in ('newmap_id',)}
            hd['id'] = pre + h['id']
            if h['kind'] == 'new_map':
                hd['map_index'] = offset[h['newmap_id']] + int(h.get('map_index', 0))
            if h['kind'] == 'existing' and not hd.get('bounds') and hd.get('area'):
                # nothing of a mission may lie outside the bounds: the play area plus a margin, grown to hold every giver box of this host
                a = hd['area']
                b = [a[0] - 10.0, a[1] - 10.0, a[2] + 10.0, a[3] + 10.0]
                for m in proj.get('missions') or []:
                    gp = (m.get('params') or {}).get('giver_pos')
                    if m.get('host') == h['id'] and gp:
                        r = ((m.get('params') or {}).get('giver_size') or 6.0) / 2 + 2.0
                        b = [min(b[0], gp[0] - r), min(b[1], gp[2] - r), max(b[2], gp[0] + r), max(b[3], gp[2] + r)]
                hd['bounds'] = b
            hosts.append(hd)
            hostmap[hd['id']] = (pid, h['id'])
        for m in proj.get('missions') or []:
            md = dict(id=pre + m['id'], type=m['type'], host=pre + (m.get('host') or (proj['hosts'][0]['id'] if proj.get('hosts') else '')),
                      index=m.get('index', 'auto'), params=copy.deepcopy(m.get('params') or {}))
            pin = pins.get((pid, m['id']))
            if pin and pin[0] == m['type'] and md['index'] in (None, 'auto'):
                md['index'] = pin[1]
            missions.append(md)
            idmap[md['id']] = (pid, m['id'])
    lp = dict(format=1, package='todms_missions', hosts=hosts, missions=missions,
              options={'keep_map_enemies': True} if keep else {})
    if maps:
        lp['new_map'] = dict(package='todms_missions', maps=maps, **{k: v for k, v in extra.items() if v})
    return lp, idmap, hostmap


def enemy_bodies(snaps, idmap):
    """{library mission id: character body number} for the missions whose project asks for one (`enemy_body` on the mission, beside `params`:
    the template library never sees it; build_set applies it afterwards to the finished mission block)."""
    out = {}
    for lid, (pid, mid) in idmap.items():
        for m in (snaps.get(pid, {}).get('project', {}).get('missions') or []):
            if m.get('id') == mid and m.get('enemy_body') not in (None, '', 'template'):
                out[lid] = int(m['enemy_body'])
    return out


def apply_bodies(ws, merged, manifest, bodies):
    """Rewrite the merged archive so the named missions' enemies wear the chosen body (todms.characters.retag_block on each mission block)."""
    import zipfile
    from . import characters
    from todtpl import tpl_env
    ft = tpl_env.get().ft
    with zipfile.ZipFile(merged) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    done = {}
    for m in manifest['missions']:
        n = bodies.get(m['id'])
        if n is None:
            continue
        name = next((k for k in entries if k.lower().endswith('/' + m['block'].lower())), None)
        if name is None:
            raise ValueError('the block of %s is not in the built archive' % m['id'])
        rep = {}
        entries[name] = characters.retag_block(ws, name, entries[name], n, rep)
        done[m['id']] = rep
    rp = ft.write_zip(merged, sorted(entries.items()))
    import hashlib
    with open(merged, 'rb') as f:
        h = hashlib.sha256(f.read()).hexdigest()
    return dict(sha256=h, bytes=rp['zip_bytes'], done=done)


def display_name(snaps, pid, mid):
    name = snaps.get(pid, {}).get('name') or pid
    return '%s / %s' % (name, mid) if len(snaps) > 1 else mid


def translate(messages, idmap, snaps):
    out = []
    for m in messages:
        m = dict(m)
        w = m.get('where')
        if w in idmap:
            pid, mid = idmap[w]
            m['where'] = mid
            m['project'] = pid
        out.append(m)
    return out


def entries_for(ws, pid, project=None):
    """The combined set for this game: every installed project except `pid`, then `pid` itself (current version)."""
    rec = installed(ws.game.folder)
    ents, pins = [], {}
    for opid, p in rec.get('projects', {}).items():
        for mid, (ty, idx) in p.get('indices', {}).items():
            pins[(opid, mid)] = (ty, idx)
        if opid != pid:
            ents.append((opid, dict(name=p['name'], project=p['project'], newmaps=p['newmaps'])))
    proj = project or get_project(pid)['project']
    ents.append((pid, snapshot_of(pid, proj)))
    return ents, pins


def other_used(ents, pid, pins):
    """{project name: [indices]} of the installed projects other than pid (for the library's cap message)."""
    out = {}
    for opid, snap in ents:
        if opid == pid:
            continue
        out[snap['name']] = [pins[(opid, m['id'])][1] for m in snap['project'].get('missions') or [] if (opid, m['id']) in pins]
    return out


# ------------------------------------------------------------------------------------------------ slots
def pool(ws, progress=None):
    """The fixed pool of new mission indices of this game install and how many are free."""
    key = ('pool', ws.game.folder, json.dumps(chain_signature(ws)))
    if key not in _STATE:
        with session(ws) as L:
            from todtpl import tpl_core
            chain = chain_paths(ws)
            _STATE[key] = sorted(tpl_core.pool(chain))
    return _STATE[key]


def slots(ws, progress=None):
    full = pool(ws)
    rec = installed(ws.game.folder)
    used = {}
    for pid, p in rec.get('projects', {}).items():
        used[pid] = dict(name=p['name'], count=len(p.get('indices', {})))
    n = sum(u['count'] for u in used.values())
    return dict(total=len(full), used=n, left=len(full) - n, pool=full, projects=used)


# ------------------------------------------------------------------------------------------------ host choices and geometry
def plan_view(pid, m):
    """The top-down picture of a scene map (streets, buildings, water) for the placement view; None for any other map."""
    info = (m.get('scene') or {}).get('plan')
    if not info:
        return None
    from . import scenplan
    return scenplan.view(newmap.directory(pid), info)


def host_geometry(host):
    return dict(id=host.id, kind=host.kind, area=list(host.area), bounds=list(host.bounds), ground_y=host.ground_y,
                obstacles=[list(o) for o in host.obst], reserved=[list(r) for r in host.reserved],
                arrival=host.arrival, spots=list(host.spots), walls=list(host.walls) if host.walls else None,
                start_spot=host.start_spot, unit=host.unit)


def host_choices(ws, progress=None):
    """New-map hosts (from the New maps projects, with their drawing data) and existing map sections (with reasons for refused ones)."""
    paths.setup_tools()
    lib(ws)
    from todtpl import tpl_host
    nms = []
    for p in newmap.list_projects():
        maps = []
        for i, m in enumerate(p['params']['maps']):
            try:
                h = tpl_host.Host(dict(id='probe', kind='new_map', map_index=i), m)
                maps.append(dict(index=i, name=m['name'], source=m.get('source'), geometry=dict(host_geometry(h), plan=plan_view(p['id'], m))))
            except Exception as e:                       # noqa: BLE001
                maps.append(dict(index=i, name=m.get('name'), source=m.get('source'), error=str(e)))
        nms.append(dict(id=p['id'], title=p['params'].get('package') or p['id'], maps=maps))
    ex = newmap.entry_hosts(ws, progress)
    return dict(newmaps=nms, existing=ex['hosts'], existing_supported=ex['supported'],
                presets=dict(downtown=dict(block='submap01_map02_lostoros_downtown.submap', map_ids_from_slot=33,
                                           area=[-255.0, -75.0, -215.0, -25.0], ground_y=2.5,
                                           note='Downtown, the alley section: tested in the game.')))


def types_info(ws):
    L = lib(ws)
    out = []
    for name in L.tpl_build.list_templates():
        s = L.template_schema(name, None)
        out.append(dict(name=name, title=s['title'], summary=s['summary'], host_needs=s['host_needs']))
    return out


def schema(ws, project, mtype, host_id, progress=None):
    """The settings of a mission type, with the defaults laid out on the chosen host."""
    with session(ws) as L:
        from todtpl import tpl_host, tpl_build
        ents = [('draft', dict(name=project.get('name') or 'draft', project=project, newmaps={
            h['newmap_id']: newmap.get_project(h['newmap_id'])['params'] for h in project.get('hosts') or [] if h['kind'] == 'new_map'}))]
        lp, idmap, hostmap = compose(ents)
        nm, hosts = tpl_host.load_project_hosts(lp)
        host = hosts.get(host_id)
        if host is None:
            raise ValueError('choose a host first')
        slot = host.d.get('map_ids_from_slot')
        if host.kind == tpl_host.EXISTING and slot is not None and not host.map_ids:
            try:
                info = tpl_build.slot_award_info(tpl_build.tpl_env.get(), int(slot))
                host.map_ids = dict(map=info['map'], submap=info['submap'], start_map=info['start_map'])
                if info.get('start_spot'):
                    host.start_spot = info['start_spot']
                    host.spots.append(info['start_spot'])
            except tpl_build.BuildError:
                pass
        sc = L.template_schema(mtype, host)
        sc['host'] = host_geometry(host)
        hd = next((h for h in project.get('hosts') or [] if h.get('id') == host_id and h.get('kind') == 'new_map'), None)
        if hd:
            try:
                mm = newmap.get_project(hd['newmap_id'])['params']['maps'][int(hd.get('map_index') or 0)]
                sc['host']['plan'] = plan_view(hd['newmap_id'], mm)
            except (OSError, ValueError, KeyError, IndexError):
                pass
        return sc


# ------------------------------------------------------------------------------------------------ validate / build
def _msgs(e):
    return [m if isinstance(m, dict) else dict(level='error', where='project', text=str(m)) for m in e.messages]


def _cap_message(ws, ents, pid, pins):
    full = pool(ws)
    snap = dict(ents)[pid]
    return __import__('todtpl').tpl_core.pool_message(chain_paths(ws), other_used(ents, pid, pins), len(snap['project'].get('missions') or [])) \
        if len(full) else None


ARRIVE_GIVER_MARGIN = 0.5   # metres around a giver box inside which a landing spot is refused


def arrival_giver_messages(lp):
    """Errors for a landing spot (map arrival, teleport, entrance arrival) inside one of the project's giver boxes.
    A custom entrance arrival placed in a giver box stopped TOD.exe a few seconds after arriving (release testing, not reproduced
    on every layout), so the build refuses it: the player would also be offered the mission the moment he lands."""
    msgs = []
    maps = (lp.get('new_map') or {}).get('maps') or []
    hosts = {h['id']: h for h in lp.get('hosts') or []}
    for m in lp.get('missions') or []:
        h = hosts.get(m.get('host')) or {}
        prm = m.get('params') or {}
        gp = prm.get('giver_pos')
        if h.get('kind') != 'new_map' or not gp or gp[0] is None or gp[2] is None:
            continue
        idx = h.get('map_index', 0)
        if not 0 <= idx < len(maps):
            continue
        half = float(prm.get('giver_size') or 6.0) / 2 + ARRIVE_GIVER_MARGIN
        mp = maps[idx]
        spots = [('arrival', (mp.get('arrival') or {}).get('pos'))]
        spots += [('spot %s' % t.get('name'), t.get('pos')) for t in mp.get('teleports') or []]
        spots += [('entrance %s' % e.get('id'), (e.get('arrive') or {}).get('pos')) for e in mp.get('entries') or []]
        for label, pt in spots:
            if pt and abs(pt[0] - gp[0]) <= half and abs(pt[2] - gp[2]) <= half:
                msgs.append(dict(level='error', where=m['id'], text='The %s lands the player inside the giver box of "%s". Move one of them out of the other.' % (label, m['id'])))
    return msgs


def validate(ws, project, pid=None, progress=None):
    """Plain-language messages for one project (checked together with the other installed ones, for the slot count)."""
    pid = pid or 'draft'
    if progress:
        progress('Checking the missions')
    with session(ws) as L:
        ents, pins = entries_for(ws, pid, project)
        lp, idmap, hostmap = compose(ents, pins)
        snaps = dict(ents)
        # only this project's missions are checked in detail; the others are installed and were checked when built
        mine = [m for m in lp['missions'] if idmap[m['id']][0] == pid]
        others = [m for m in lp['missions'] if idmap[m['id']][0] != pid]
        cap = _cap_message(ws, ents, pid, pins)
        try:
            lp_mine = dict(lp, missions=mine, hosts=[h for h in lp['hosts'] if hostmap[h['id']][0] == pid])
            if not mine:
                return dict(ok=False, messages=[dict(level='error', where='project', text='The project has no missions yet.')], index={})
            res = L.validate(lp_mine, chain_paths(ws), used=other_used(ents, pid, pins))
        except L.BuildError as e:
            return dict(ok=False, messages=translate(_msgs(e), idmap, snaps), index={})
        msgs = list(res['project'])
        for v in res['missions'].values():
            msgs += v
        msgs += arrival_giver_messages(lp_mine)
        if cap and not any(cap in m['text'] for m in msgs):
            msgs.insert(0, dict(level='error', where='project', text=cap))
        res_ok = not any(m['level'] == 'error' for m in msgs)
        return dict(ok=res_ok, messages=translate(msgs, idmap, snaps), index={idmap[k][1]: v for k, v in res['index'].items()},
                    free=res.get('free_indices'), pool=res.get('pool'))


def _internal_note(text):
    """Lint lines about leftovers of the shipped mission the template starts from: expected, never visible in the game."""
    return text.startswith('allowed') or 'is a shipped text' in text


def build_set(ws, ents, pins, out_dir, progress=None, pid=None, extra_chain=(), overlay_entries=None, alloc=None, extra_maps=None):
    """Build the combined set into out_dir; returns the result record (not stored).
    extra_chain: the pack stages built before this one (mods, new maps), read in front of the game's archives;
    overlay_entries: every block they touched (the library reads those from the stages instead of blocks.naz)."""
    snaps = dict(ents)
    with session(ws) as L:
        from todtpl import tpl_build
        wanted = {}
        lp, idmap, hostmap = compose(ents, pins, alloc, extra_maps, carry=wanted)
        bodies = enemy_bodies(snaps, idmap)
        chain = list(extra_chain) + chain_paths(ws)
        if overlay_entries:
            lp['options'] = dict(lp.get('options') or {}, overlay_entries=list(overlay_entries))
        cap = None
        if pid:
            cap = _cap_message(ws, ents, pid, pins)
        if cap:
            return dict(ok=False, messages=[dict(level='error', where='project', text=cap)])
        bad = arrival_giver_messages(lp)
        if bad:
            return dict(ok=False, messages=translate(bad, idmap, snaps))
        os.makedirs(out_dir, exist_ok=True)
        try:
            res = L.build(lp, chain, out_dir, progress=progress)
            merged = os.path.join(out_dir, ZIP)
            mrep = tpl_build.merge_package(res, merged)
        except L.BuildError as e:
            return dict(ok=False, messages=translate(_msgs(e), idmap, snaps))
        for z in res['zips']:                  # the merged archive holds everything; free the 120 MB of loose copies
            if os.path.exists(z):
                os.remove(z)
        for sub in ('map', 'text'):
            shutil.rmtree(os.path.join(out_dir, sub), ignore_errors=True)
        manifest = json.load(open(res['manifest'], encoding='utf-8'))
        if bodies:
            try:
                mrep.update(apply_bodies(ws, merged, manifest, bodies))
            except (ValueError, KeyError) as e:
                return dict(ok=False, messages=[dict(level='error', where='project', text='Enemy body: %s' % e)])
        if wanted:                             # a project-level key that the build did not receive must fail loudly, never vanish
            try:
                used = json.load(open(os.path.join(out_dir, 'params_used.json'), encoding='utf-8'))
            except (OSError, ValueError):
                used = {}
            lost = carry_missing(wanted, used)
            if lost:
                return dict(ok=False, messages=[dict(level='error', where='project', text=t) for t in lost[:6]])
        lint = {idmap[k][1] if k in idmap else k: v for k, v in res['lint'].items()}
        warns = []
        for k, lines in res['lint'].items():
            for ln in lines:
                if ln.startswith('warn') and not _internal_note(ln[4:].strip()):
                    warns.append(dict(level='warn', where=idmap[k][1] if k in idmap else k, text=ln[4:].strip()))
        return dict(ok=bool(res['ok']), lint_errors=res['lint_errors'], messages=warns + [
            dict(level='error', where=idmap[k][1] if k in idmap else k, text=ln.split(' ', 1)[1].strip())
            for k, lines in res['lint'].items() for ln in lines if ln.startswith(('ERROR', 'STRUCT'))],
            zip=merged, sha256=mrep['sha256'], bytes=mrep['bytes'], entries=mrep['entries'],
            index_of=_index_of(res['indices'], idmap), idmap={k: list(v) for k, v in idmap.items()},
            migrate_entries=manifest['migrate_entries'], thread_keys=manifest.get('thread_keys', []),
            missions=[dict(project=idmap[m['id']][0], id=idmap[m['id']][1], type=m['type'], index=m['index'], name=m['name'],
                           host=hostmap[m['host']][1], giver=m['giver'], rows=m['text_rows']) for m in manifest['missions']],
            lint=lint, hosts={k: list(v) for k, v in hostmap.items()})


def _index_of(indices, idmap):
    out = {}
    for k, v in indices.items():
        out.setdefault(idmap[k][0], {})[idmap[k][1]] = v
    return out


def _project_records(ents, res):
    """What the game folder remembers per project: its inputs and the index each mission got (so it keeps it)."""
    out = {}
    for p_, s in ents:
        types = {m['id']: m['type'] for m in s['project'].get('missions') or []}
        out[p_] = dict(name=s['name'], project=s['project'], newmaps=s['newmaps'],
                       indices={mid: [types[mid], idx] for mid, idx in res['index_of'].get(p_, {}).items()})
    return out


def run_build(ws, pid, progress=None):
    """Build the combined set including this project. The result is bound to exactly these inputs."""
    ents, pins = entries_for(ws, pid)
    snaps = dict(ents)
    rev = revision(dict(entries=[(p, s) for p, s in ents], pins=sorted((list(k), list(v)) for k, v in pins.items()),
                        chain=chain_signature(ws)))
    runs = os.path.join(directory(pid), 'runs')
    shutil.rmtree(runs, ignore_errors=True)          # one build at a time per project: each one is about 120 MB
    d = os.path.join(runs, uuid.uuid4().hex[:12])
    if progress:
        progress('Building the missions')
    try:
        res = build_set(ws, ents, pins, d, progress, pid)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    if not res.get('ok'):
        shutil.rmtree(d, ignore_errors=True)
    record = dict(revision=rev, folder=d, combined=[p for p, _ in ents], ok=bool(res.get('ok')), result=res,
                  built_with=dict(chain=[a[0] for a in chain_signature(ws)]))
    if res.get('ok'):
        record['sha256'] = res['sha256']
    newmap.write(os.path.join(directory(pid), 'build.json'), record)
    return record


# ------------------------------------------------------------------------------------------------ install / uninstall
def install(ws, pid, progress=None):
    from . import pack
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    project = get_project(pid)
    b = project.get('build') or {}
    if not b.get('ok') or not b.get('sha256'):
        raise ValueError('Build this version of the missions successfully before installing them')
    ents, pins = entries_for(ws, pid)
    rev = revision(dict(entries=[(p, s) for p, s in ents], pins=sorted((list(k), list(v)) for k, v in pins.items()),
                        chain=chain_signature(ws)))
    if b['revision'] != rev:
        raise ValueError('The missions or the game files changed since the last build. Build again before installing.')
    z = os.path.join(b['folder'], ZIP)
    if newmap.file_hash(z) != b['sha256']:
        raise ValueError('The built package changed. Build it again before installing.')
    res = b['result']
    projects = _project_records(ents, res)
    r = pack.apply(ws, 'install missions', missions=dict(projects=projects), progress=progress,
                   hints=dict(missions_built=dict(zip=z, sha256=b['sha256'], result=res)))
    rec = r['missions']
    return dict(rec, message='Installed %d mission%s' % (len(res['missions']), '' if len(res['missions']) == 1 else 's'))


def uninstall(ws, pid, progress=None):
    from . import pack
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    rec = installed(folder)
    if pid not in rec.get('projects', {}):
        return dict(message='These missions are not installed in this game folder')
    rest = {k: v for k, v in rec['projects'].items() if k != pid}
    if progress and rest:
        progress('Rebuilding the remaining missions')
    pack.apply(ws, 'remove missions', missions=dict(projects=rest) if rest else {}, progress=progress)
    if not rest:
        return dict(message='Mission package removed. New maps that were part of it can be installed again from the New maps tab.')
    return dict(message='Missions removed; the rest was rebuilt')


def status(ws):
    rec = installed(ws.game.folder) if ws.game else {}
    return dict(installed=bool(rec.get('projects')), projects={k: dict(name=v['name'], count=len(v['indices']))
                                                               for k, v in rec.get('projects', {}).items()},
                missions=rec.get('missions', []), zip_present=os.path.exists(os.path.join(ws.game.folder, game.PACK_ZIP)) if ws.game else False)
