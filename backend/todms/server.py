"""Local HTTP API (127.0.0.1 only) for the UI, plus the built UI and the cache files.

Every /api POST needs the session token the server puts into index.html, so other local programs cannot drive it.
"""
import json
import mimetypes
import os
import secrets
import shutil
import tempfile
import threading
import traceback
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from . import paths

TOKEN = secrets.token_hex(16)
WS = None
WINDOW = None          # pywebview window (for native dialogs), set by main.py
mimetypes.add_type('model/gltf-binary', '.glb')
mimetypes.add_type('application/octet-stream', '.dds')
mimetypes.add_type('text/javascript', '.js')


def ws():
    global WS
    if WS is None:
        from .workspace import Workspace
        WS = Workspace()
    return WS


def need_game():
    if ws().game is None:
        raise ApiError(409, 'pick your Total Overdose folder first')
    return ws()


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------------------------------------- handlers
def h_status(q, body):
    from . import mods
    s = ws().status()
    if ws().game:
        s['installed'] = mods.installed_state(ws())
    return s


def h_setup(q, body):
    folder = (body or {}).get('folder')
    if not folder or not os.path.isdir(folder):
        raise ApiError(400, 'folder not found')
    if not os.path.exists(os.path.join(folder, 'blocks.naz')):
        raise ApiError(400, 'no blocks.naz in this folder: pick the folder that holds TOD.exe and blocks.naz')
    return ws().jobs.start('setup', ws().set_game, folder)


def h_settings(q, body):
    w = ws()
    for k in ('build_on_installed', 'save_safe_delete', 'author', 'ue_config'):
        if k in body:
            w.settings[k] = body[k]
    w.save_settings()
    return w.status()


def h_prepare(q, body):
    return need_game().jobs.start('prepare', ws().prepare_all)


def h_catalog(q, body):
    return need_game().catalog


def h_open(q, body):
    w = need_game()
    w.settings['last_view'] = dict(map=body['map'], section=body.get('section'), missions=body.get('missions') or [])
    w.save_settings()
    return w.jobs.start('open', w.open_level, body['map'], body.get('section'), body.get('missions') or [])


def h_entity(q, body):
    w = need_game()
    L = w.block_level(q['entry'])
    return L.entity_props(int(q['k']), int(q['node'], 16))


def h_templates(q, body):
    """Palette templates: for each kind the first suitable entity in the given blocks (then known blocks)."""
    w = need_game()
    entries = [e for e in (body.get('entries') or []) if e]
    want = {
        'wall': lambda e: e['type'] == 'CollisionBox',
        'navblock': lambda e: e['type'] == 'CollisionBox',
        'trigger': lambda e: e['type'] == 'Trigger_Root(CollisionBox)',
        'pickup': lambda e: (e['type'] or '').startswith('goodie_placeholder'),
        'weapon': lambda e: (e['type'] or '').startswith('weapon_placeholder'),
        'vehicle': lambda e: (e['type'] or '').startswith('vehicle_placeholder'),
        'enemy': lambda e: (e['type'] or '').startswith('character_placeholder'),
        'trackpoint': lambda e: e['type'] == 'TrackPoint',
    }
    fallback = ['data_pc/overdose_the_game/overdose/shared/mm092_escapejungle.mission',
                'data_pc/overdose_the_game/overdose/shared/submap01_map02_lostoros_downtown.submap']
    out = {}
    for e in entries + [x for x in fallback if x not in entries]:
        try:
            L = w.level_json(e)
        except Exception:
            continue
        frag = {f['k']: f['name'] for f in L['fragments']}
        for kind, f in want.items():
            if kind in out:
                continue
            for ent in L['entities']:
                if f(ent) and ent['ed'] and not ent.get('off'):
                    out[kind] = dict(entry=e, frag=frag[ent['k']], node=ent['node'], type=ent['type'],
                                     name=ent.get('name'), size=ent.get('size'), sub=ent.get('sub'))
                    break
    return out


_ENUMS = None


def h_enums(q, body):
    """Names for the sub-type numbers (from the tools' tables and the game's VehicleDict)."""
    global _ENUMS
    w = need_game()
    if _ENUMS is None:
        e = {}
        try:
            import locotool as lt
            e['GoodieSubType'] = {str(k): v for k, v in lt.GOODIES.items()}
        except Exception:
            pass
        try:
            import weapons as wp
            e['WeaponSubType'] = {str(k): v for k, v in wp.GUNS.items()}
        except Exception:
            pass
        try:
            import todblock as tb
            import fragtool as ft
            import fragedit as fe
            from .game import MAIN_ENTRY
            raw, _ = w.read_block(MAIN_ENTRY)
            b = tb.Block(raw, '.main')
            frs, _ = ft.fragments(b)
            k, nm = ft.pick_fragment(frs, 'VehicleDict.fragment')
            d = fe.FragDoc(b.payloads[k], w.T, nm)
            vt = {}
            for n in d.created_ids():
                if 'vehicle_type' in (d.type_of(n) or ''):
                    vt[str(d.get(n, 'Specific_ID'))] = d.get(n, 'name')
            e['VehicleSubType'] = vt
        except Exception:
            pass
        e['CollisionFlags'] = {'1': 'Solid', '2': 'BulletProof', '4': 'Opaque', '8': 'CameraBlock', '16': 'Trigger',
                               '32': 'NavBlock', '64': 'Physics', '128': 'ActivateTriggers'}
        _ENUMS = e
    return _ENUMS


DEV = False


def h_token(q, body):
    if not DEV:
        raise ApiError(404, 'unknown endpoint')
    return dict(token=TOKEN)


def h_job(q, body, jid):
    j = ws().jobs.get(jid)
    if j is None:
        raise ApiError(404, 'no such job')
    return {k: v for k, v in j.items() if k != 'trace' or j.get('status') == 'failed'}


def _levels_for(w, mod):
    view = mod.get('view') or {}
    out = {}
    entries = set(op['entry'] for op in mod.get('level') or [])
    for e in entries:
        try:
            out[e] = w.level_json(e)
        except Exception:
            out[e] = None
    return out


def _check_job(mod, progress=None):
    from . import mods, checks
    w = ws()
    stage = tempfile.mkdtemp(prefix='todms_check_')
    try:
        rep = mods.build_mods(w, [mod], stage, 'check.zip', progress)
        if progress:
            progress('checking')
        res = checks.run(w, mod.get('level') or [], rep, _levels_for(w, mod))
        rep.pop('_outs', None)
        return dict(checks=res, build=_slim(rep))
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _slim(rep):
    out = dict(save_safe=rep.get('save_safe'), entries=rep.get('entries'), zip=rep.get('zip'))
    out['blocks'] = [{k: v for k, v in b.items() if k in ('entry', 'base_archive', 'bytes', 'base_bytes', 'save_safe',
                                                           'removed', 'uid_nodes', 'roundtrip', 'collision')} for b in rep['blocks']]
    out['collision'] = rep.get('collision')
    for b, rb in zip(out['blocks'], rep['blocks']):
        if rb.get('stage_b'):
            b['grafted'] = rb['stage_b']['grafted']
            b['runtime_indices'] = rb['stage_b']['checks'].get('runtime_indices')
        if rb.get('stage_a'):
            b['edited_fragments'] = rb['stage_a']['checks'].get('4_edited_fragments')
    return out


def h_check(q, body):
    need_game()
    return ws().jobs.start('check', _check_job, body['mod'])


def _export_job(mod, progress=None):
    from . import mods, checks
    w = ws()
    m = mods.save_mod(mod)
    d = os.path.join(mods.lib_dir(), m['id'], 'build')
    shutil.rmtree(d, ignore_errors=True)
    rep = mods.build_mods(w, [m], d, 'todms_%s.zip' % m['id'][:24], progress)
    res = checks.run(w, m.get('level') or [], rep, _levels_for(w, m))
    rep.pop('_outs', None)
    return dict(mod=m, checks=res, build=_slim(rep), folder=d)


def h_export(q, body):
    need_game()
    return ws().jobs.start('export', _export_job, body['mod'])


def h_mods(q, body):
    from . import mods
    return dict(mods=mods.list_mods(), installed=mods.installed_state(ws()) if ws().game else None,
                library=mods.lib_dir())


def h_mod_get(q, body):
    from . import mods
    return mods.get_mod(q['id'])


def h_mod_save(q, body):
    from . import mods
    return mods.save_mod(body['mod'])


def h_mod_delete(q, body):
    from . import mods
    mods.delete_mod(body['id'])
    return h_mods(q, body)


def h_mod_state(q, body):
    from . import mods
    mods.set_state(body.get('order'), body.get('enabled'))
    return h_mods(q, body)


def h_mod_install(q, body):
    from . import mods
    w = need_game()
    return w.jobs.start('install', mods.install, w)


def h_mod_uninstall(q, body):
    from . import mods
    return mods.uninstall(need_game())


def h_mod_export(q, body):
    from . import mods
    path = body.get('path') or _dialog('save', body.get('suggest', 'mod.todmod'))
    if not path:
        return dict(cancelled=True)
    return dict(path=mods.export_mod(body['id'], path))


def h_mod_import(q, body):
    from . import mods
    path = body.get('path') or _dialog('open')
    if not path:
        return dict(cancelled=True)
    return mods.import_mod(path)


def h_data(q, body, name):
    from . import dataed
    w = need_game()
    if name not in dataed.EDITORS:
        raise ApiError(404, 'no editor %s' % name)
    return w.jobs.run_sync(lambda progress=None: dataed.EDITORS[name][0](w))


def h_saves(q, body):
    from . import saves
    return saves.list_slots(need_game(), q.get('folder'))


def h_save_make(q, body):
    from . import saves
    w = need_game()
    r = w.jobs.run_sync(lambda progress=None: saves.make(w, body['source'], body.get('pos'), body.get('yaw'),
                                                          body.get('heal'), body.get('weapons'),
                                                          body.get('start_mission')))
    if body.get('install_as'):
        r['install'] = saves.install(w, r['path'], body['install_as'], body.get('folder'))
    return r


def h_dialog(q, body):
    kind = body.get('kind', 'folder')
    return dict(path=_dialog(kind, body.get('suggest')))


def _dialog(kind, suggest=None):
    if WINDOW is None:
        return None
    import webview
    if kind == 'folder':
        r = WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
    elif kind == 'mesh':
        r = WINDOW.create_file_dialog(webview.OPEN_DIALOG, file_types=('Meshes (*.glb;*.gltf;*.obj)', 'All files (*.*)'))
    elif kind == 'save':
        r = WINDOW.create_file_dialog(webview.SAVE_DIALOG, save_filename=suggest or 'mod.todmod',
                                      file_types=('TOD Mod Studio mod (*.todmod)', 'All files (*.*)'))
    else:
        r = WINDOW.create_file_dialog(webview.OPEN_DIALOG, file_types=('TOD Mod Studio mod (*.todmod)', 'All files (*.*)'))
    if not r:
        return None
    return r if isinstance(r, str) else r[0]


def h_reveal(q, body):
    p = body.get('path')
    if p and os.path.exists(p):
        os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
    return dict(ok=True)


# ---------------------------------------------------------------------------------------------- companion tools
def h_comp_catalog(q, body):
    from . import companion
    return companion.catalog()


def h_coll_preview(q, body):
    from . import companion
    path = body.get('path') or _dialog('mesh')
    if not path:
        return dict(cancelled=True)
    return companion.mesh_preview(path)


def h_coll_generate(q, body):
    from . import companion
    w = need_game()
    req = dict(body)
    if req.get('map') and not str(req['map']).count('_'):
        req['map'] = companion.map_key_for(w, req['map'])
    return w.jobs.start('collision', companion.generate, req)


def h_coll_check(q, body):
    from . import companion
    w = need_game()
    return w.jobs.start('collision-check', companion.check, w, body.get('sets') or [])


def h_coll_existing(q, body):
    from . import companion
    w = need_game()
    return w.jobs.run_sync(lambda progress=None: companion.existing_near(w, body['map'], body['centre'],
                                                                        float(body.get('radius') or 40)))


def h_assets_census(q, body):
    from . import companion
    w = need_game()
    return w.jobs.start('asset-census', companion.census, w)


def h_assets_rows(q, body):
    from . import companion
    return companion.asset_rows(need_game(), body or {}, (body or {}).get('mod'))


def h_assets_thumbs(q, body):
    from . import companion
    w = need_game()
    return w.jobs.start('thumbnails', companion.thumbs, w, list(body.get('keys') or [])[:400])


# ---------------------------------------------------------------------------------------------- part B
def h_routes_model(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('routes', CB.routes_model, w, body.get('entries'), body.get('ops'), body.get('collision'))


def h_missions_graph(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('missions', CB.mission_graph, w, body['entry'], body.get('ops'), bool(body.get('lint')))


def h_sections_catalog(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('sections', CB.sections_catalog, w, body.get('group'), body.get('entries'), body.get('ops'))


def h_sections_fix(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('fix-teleport', CB.fix_teleport, w, body['group'], body['volume'], body.get('gap'))


def h_sections_split(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('split-plan', CB.split_plan, w, body['entry'], body.get('axis') or 'x', body.get('at') or 0)


def h_partb_check(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('part-b-check', CB.check, w, body['mod'], tuple(body.get('kinds') or ('nav', 'missions', 'sections')))


def h_newmaps(q, body):
    from . import newmap
    def metadata(progress=None):
        return dict(projects=newmap.list_projects(), **newmap.info())
    return ws().jobs.run_sync(metadata)


def h_newmap_action(q, body):
    from . import newmap
    action = body['action']
    if action == 'save':
        return newmap.save_project(body['params'], body.get('id'))
    if action == 'import':
        return newmap.import_project(body['path'])
    w = need_game()
    if action == 'hosts':
        return w.jobs.start('new-map-hosts', newmap.entry_hosts, w)
    if action in ('check', 'build'):
        return w.jobs.start('new-map-' + action, newmap.run, w, body['id'], action == 'check')
    if action in ('install', 'uninstall'):
        return w.jobs.start('new-map-' + action, getattr(newmap, action), w, body['id'])
    raise ApiError(400, 'unknown new-map action')


def h_missiontpl(q, body):
    from . import missions_tpl as MT
    w = ws()
    def meta(progress=None):
        out = dict(projects=MT.list_projects(), samples=MT.sample_info(), limit=MT.SLOT_LIMIT)
        if w.game:
            out['types'] = MT.types_info(w)
            out['status'] = MT.status(w)
        return out
    return w.jobs.run_sync(meta)


def h_missiontpl_action(q, body):
    from . import missions_tpl as MT
    action = body['action']
    if action == 'save':
        return MT.save_project(body['project'], body.get('id'))
    if action == 'sample':
        return MT.open_sample(body['key'])
    w = need_game()
    if action == 'delete':
        return MT.delete_project(w, body['id'])
    jobs = dict(hosts=(MT.host_choices, ()), slots=(MT.slots, ()),
                schema=(MT.schema, (body.get('project'), body.get('type'), body.get('host'))),
                validate=(MT.validate, (body.get('project'), body.get('id'))),
                build=(MT.run_build, (body.get('id'),)), install=(MT.install, (body.get('id'),)),
                uninstall=(MT.uninstall, (body.get('id'),)))
    if action in jobs:
        fn, args = jobs[action]
        return w.jobs.start('mission-' + action, fn, w, *args)
    raise ApiError(400, 'unknown mission action')


def h_missiontpl_savefix(q, body):
    from . import saves
    w = need_game()
    return w.jobs.start('mission-save-update', saves.migrate_missions, w, body['source'], body.get('install_as'), body.get('folder'))


GET = {'/api/missiontpl': h_missiontpl, '/api/newmaps': h_newmaps, '/api/status': h_status, '/api/catalog': h_catalog, '/api/entity': h_entity, '/api/mods': h_mods,
       '/api/mods/get': h_mod_get, '/api/saves': h_saves, '/api/enums': h_enums,
       '/api/token': h_token, '/api/companion/catalog': h_comp_catalog}
POST = {'/api/missiontpl': h_missiontpl_action, '/api/missiontpl/savefix': h_missiontpl_savefix, '/api/newmaps': h_newmap_action, '/api/setup': h_setup, '/api/settings': h_settings, '/api/prepare': h_prepare, '/api/open': h_open,
        '/api/templates': h_templates, '/api/check': h_check, '/api/export': h_export, '/api/mods/save': h_mod_save,
        '/api/mods/delete': h_mod_delete, '/api/mods/state': h_mod_state, '/api/mods/install': h_mod_install,
        '/api/mods/uninstall': h_mod_uninstall, '/api/mods/export': h_mod_export, '/api/mods/import': h_mod_import,
        '/api/saves/make': h_save_make, '/api/dialog': h_dialog, '/api/reveal': h_reveal,
        '/api/collision/preview': h_coll_preview, '/api/collision/generate': h_coll_generate,
        '/api/collision/check': h_coll_check, '/api/collision/existing': h_coll_existing,
        '/api/assets/census': h_assets_census, '/api/assets/rows': h_assets_rows, '/api/assets/thumbs': h_assets_thumbs,
        '/api/routes/model': h_routes_model, '/api/missions/graph': h_missions_graph,
        '/api/sections/catalog': h_sections_catalog, '/api/sections/fix': h_sections_fix,
        '/api/sections/split': h_sections_split, '/api/partb/check': h_partb_check}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype='application/json', extra=None):
        if not isinstance(data, (bytes, bytearray)):
            data = json.dumps(data, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=86400' if '/assets/' in self.path or self.path.startswith('/cache/') else 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _api(self, table, body):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path.startswith('/api/job/'):
                return self._send(200, h_job(q, body, u.path.rsplit('/', 1)[1]))
            if u.path.startswith('/api/data/'):
                return self._send(200, h_data(q, body, u.path.rsplit('/', 1)[1]))
            fn = table.get(u.path)
            if fn is None:
                return self._send(404, dict(error='unknown endpoint'))
            return self._send(200, fn(q, body))
        except ApiError as e:
            return self._send(e.code, dict(error=str(e)))
        except Exception as e:
            return self._send(500, dict(error=str(e), trace=traceback.format_exc()))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith('/api/'):
            return self._api(GET, None)
        if u.path.startswith('/cache/'):
            return self._file(paths.cache_dir(), urllib.parse.unquote(u.path[len('/cache/'):]))
        rel = urllib.parse.unquote(u.path.lstrip('/')) or 'index.html'
        if not os.path.exists(os.path.join(paths.WEB, rel)):
            rel = 'index.html'
        if rel == 'index.html':
            html = open(os.path.join(paths.WEB, 'index.html'), 'rb').read()
            html = html.replace(b'</head>', b'<meta name="todms-token" content="' + TOKEN.encode() + b'"></head>', 1)
            return self._send(200, html, 'text/html; charset=utf-8')
        return self._file(paths.WEB, rel)

    def do_POST(self):
        if self.headers.get('X-TODMS-Token') != TOKEN:
            return self._send(403, dict(error='bad token'))
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, dict(error='bad json'))
        return self._api(POST, body)

    def _file(self, root, rel):
        root = os.path.abspath(root)
        p = os.path.abspath(os.path.join(root, rel))
        if not p.startswith(root + os.sep) or not os.path.isfile(p):
            return self._send(404, dict(error='not found'))
        ctype = mimetypes.guess_type(p)[0] or 'application/octet-stream'
        self._send(200, open(p, 'rb').read(), ctype)


def serve(port=0):
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
