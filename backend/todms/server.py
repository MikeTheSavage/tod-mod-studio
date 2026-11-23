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
OPEN_FILES = []        # mod files the shell handed to the program (a double click); the UI offers to add them once
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


_OV = dict(t=0, running=False)


def h_overview(q, body):
    """Read-only facts for the status bar and the home page: game running, what is installed, jobs, mission slots."""
    import time
    from . import mods, newmap, missions_tpl, limits, game as gm
    w = ws()
    out = dict(ready=w.game is not None, jobs=[])
    for j in list(w.jobs.jobs.values()):
        if j['status'] in ('queued', 'running'):
            out['jobs'].append(dict(id=j['id'], kind=j['kind'], status=j['status'], message=j['message'], done=j['done'], total=j['total']))
    if not w.game:
        return out
    folder = w.game.folder
    if time.time() - _OV['t'] > 6:                     # the process list is slow: look at most every 6 seconds
        _OV['running'] = bool(gm.game_running(folder))
        _OV['t'] = time.time()
    out['game_running'] = _OV['running']
    out['folder'] = folder
    st = mods.installed_state(w)
    names = []
    for i in (st.get('mods') or []) if st.get('zip_present') else []:
        try:
            names.append(mods.get_mod(i).get('name') or i)
        except Exception:
            names.append(i)
    out['mods_installed'] = names
    nm = []
    try:
        for k, v in newmap.installed(folder).items():
            try:
                nm.append(dict(id=k, name=newmap.get_project(k)['params'].get('package') or v.get('name') or k))
            except Exception:
                nm.append(dict(id=k, name=v.get('name') or k))
    except Exception:
        pass
    out['new_maps'] = nm
    try:
        out.update(_pack_facts(w, folder))
    except Exception:
        pass
    try:
        rec = missions_tpl.installed(folder)
        projs = rec.get('projects', {})
        out['missions_installed'] = sum(len(p.get('indices', {})) for p in projs.values())
        out['mission_projects'] = [dict(id=k, name=p.get('name', k), count=len(p.get('indices', {}))) for k, p in projs.items()]
        out['mission_slots_total'] = limits.value('L7')
        out['mission_slots_left'] = max(0, limits.value('L7') - out['missions_installed'])
    except Exception:
        out['missions_installed'] = 0
    try:
        from . import testgame
        st = testgame.current()
        if st:
            out['test'] = dict(id=st['id'], status=st['status'], exit_code=st.get('exit_code'), crashed=bool(st.get('crash')), stopped=bool(st.get('stopped')))
    except Exception:
        pass
    out['gameplay_plus'] = any(os.path.exists(os.path.join(folder, n)) for n in ('TODGameplay.dll', 'todgameplay.dll'))
    return out


_STARTED = set()


def _startup(w, progress=None):
    from . import journal, pack
    r = journal.reconcile(w.game.folder)
    m = pack.migrate(w)
    return dict(journal=r, migrated=m)


def _pack_facts(w, folder):
    """Staleness (K4), the archive slots and the journal at the start. Cheap: file stats and one small read."""
    from . import pack, archives, game as gm
    out = {}
    if folder not in _STARTED:
        _STARTED.add(folder)
        w.jobs.start('startup', _startup, w)
    st = pack.stale(w)
    out['stale'] = st
    fs = gm.filesystem_line(gm.read_configpc(folder)) or list(gm.DEFAULT_FS)
    sc = archives.slot_count(folder, fs)
    out['archive_slots'] = dict(count=sc['count'], limit=sc['limit'])
    return out


def h_setup(q, body):
    folder = (body or {}).get('folder')
    if not folder or not os.path.isdir(folder):
        raise ApiError(400, 'folder not found')
    if not os.path.exists(os.path.join(folder, 'blocks.naz')):
        raise ApiError(400, 'no blocks.naz in this folder: pick the folder that holds TOD.exe and blocks.naz')
    return ws().jobs.start('setup', ws().set_game, folder)


def h_settings(q, body):
    w = ws()
    for k in ('build_on_installed', 'save_safe_delete', 'author', 'online', 'community_url', 'update_url', 'update_auto', 'blender_bridge', 'ccc_folder'):
        if k in body:
            w.settings[k] = body[k].strip() if isinstance(body[k], str) else body[k]
    w.save_settings()
    if 'blender_bridge' in body:
        from . import blender
        blender.announce(PORT[0], bool(w.settings.get('blender_bridge')))
        if not w.settings.get('blender_bridge'):
            blender.clear()
    return w.status()


def h_prepare(q, body):
    return need_game().jobs.start('prepare', ws().prepare_all)


def h_catalog(q, body):
    return need_game().catalog


def h_open(q, body):
    w = need_game()
    if not body.get('quiet'):         # a screen that only shows a map for context does not move the level editor's view
        w.settings['last_view'] = dict(map=body['map'], section=body.get('section'), missions=body.get('missions') or [])
        w.save_settings()
    return w.jobs.start('open', w.open_level, body['map'], body.get('section'), body.get('missions') or [], sections=body.get('sections'))


def h_starters(q, body):
    from . import starters
    return dict(starters=starters.listing())


def h_starter_open(q, body):
    from . import starters
    try:
        return starters.open_one(body['id'])
    except KeyError as e:
        raise ApiError(404, str(e))


def h_userlib_get(q, body):
    from . import userlib
    return userlib.load()


def h_userlib_set(q, body):
    from . import userlib
    try:
        return userlib.save_key(body.get('key'), body.get('value'))
    except ValueError as e:
        raise ApiError(400, str(e))


def h_entity(q, body):
    w = need_game()
    L = w.block_level(q['entry'])
    return L.entity_props(int(q['k']), int(q['node'], 16))


def h_models_find(q, body):
    w = need_game()
    names = [n for n in (body.get('names') or [])][:40]
    out = w.find_models([n for n in names if not any(str(m.get('path', '')).lower() == str(n).lower() for m in (body.get('imported') or []))])
    imp = [m for m in (body.get('imported') or []) if str(m.get('path', '')).lower() in {str(n).lower() for n in names}]
    if imp:                       # models imported into the open mod (todms/imports.py): the preview is the baked result
        from . import imports
        for rec in w.jobs.run_sync(lambda progress=None: imports.imported_records(w, imp)).values():
            if rec.get('path'):
                out[rec['path']] = rec
    return dict(models=out)


def h_ram_moves(q, body):
    from . import ramanim
    w = need_game()
    return w.jobs.start('ram', ramanim.build, w)


ENEMY_GROUP = dict(entry='data_pc/overdose_the_game/overdose/shared/submap01_map02_lostoros_downtown.submap',
                   frag='Police_Assault_MissionStructure_03.fragment', node='0x00300E08')


def h_names(q, body):
    """The shared name table: characters, behaviours, sides, weapons, pickups, vehicles."""
    from . import names
    return names.all_names()


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
        'model': lambda e: e.get('cat') == 'model' and (e['type'] or '') == 'Model',
    }
    fallback = ['data_pc/overdose_the_game/overdose/shared/mm092_escapejungle.mission',
                'data_pc/overdose_the_game/overdose/shared/submap01_map02_lostoros_downtown.submap']
    out = {}
    try:                                # an enemy is added as a whole fighter (body + weapon + short path), the shipped Downtown patrol
        e = ENEMY_GROUP['entry']
        L = w.level_json(e)
        frag = next(f['name'] for f in L['fragments'] if f['name'].endswith(ENEMY_GROUP['frag']))
        out['enemy'] = dict(entry=e, frag=frag, node=ENEMY_GROUP['node'], type='Folder', name='Enemy', group='enemy',
                            sub=dict(Model=23, AISubType=0, FactionID=9))
    except Exception:
        pass
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
    from . import mods, checks, ledger
    w = ws()
    stage = tempfile.mkdtemp(prefix='todms_check_')
    try:
        rep = mods.build_mods(w, [mod], stage, 'check.zip', progress)
        if progress:
            progress('checking')
        stats = {}
        lv = _levels_for(w, mod)
        res = checks.run(w, mod.get('level') or [], rep, lv, stats)
        rep.pop('_outs', None)
        return dict(checks=res, build=_slim(rep), ledger=ledger.heavy_from_stats(w, stats, rep, lv, os.path.join(stage, 'check.zip')))
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
    from . import mods, checks, problems, ledger
    w = ws()
    problems.refuse_if(problems.live_errors('level', mod), 'The mod cannot be exported')
    m = mods.save_mod(mod)
    d = os.path.join(mods.lib_dir(), m['id'], 'build')
    shutil.rmtree(d, ignore_errors=True)
    rep = mods.build_mods(w, [m], d, 'todms_%s.zip' % m['id'][:24], progress)
    stats = {}
    lv = _levels_for(w, m)
    res = checks.run(w, m.get('level') or [], rep, lv, stats)
    rep.pop('_outs', None)
    bad = [c['title'] for c in res if c['level'] == 'error']
    problems.refuse_if(bad, 'The mod cannot be exported')
    return dict(mod=m, checks=res, build=_slim(rep), folder=d, ledger=ledger.heavy_from_stats(w, stats, rep, lv, os.path.join(d, 'todms_%s.zip' % m['id'][:24])))


def h_export(q, body):
    need_game()
    return ws().jobs.start('export', _export_job, body['mod'])


def h_mod_save(q, body):
    from . import mods
    try:
        return mods.save_mod(body['mod'])
    except ValueError as e:
        raise ApiError(400, str(e))


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
    w = need_game()
    return w.jobs.start('uninstall', mods.uninstall, w)


def h_mod_export(q, body):
    from . import mods
    path = body.get('path') or _dialog('save', body.get('suggest', 'mod.todmod'))
    if not path:
        return dict(cancelled=True)
    return dict(path=mods.export_mod(body['id'], path))


def h_mods(q, body):
    from . import mods, profiles
    w = ws()
    unmet, cf = [], dict(clashes=[], merged=[], by_mod={}, counts=dict(clashes=0, merged=0))
    try:
        unmet = mods.requirements(w if w.game else None)
        cf = mods.conflict_report(folder=w.game.folder if w.game else None)
    except Exception:
        pass
    return dict(mods=mods.list_mods(), installed=mods.installed_state(w) if w.game else None,
                library=mods.lib_dir(), unmet=unmet, conflicts=cf, profiles=profiles.listing())


def h_mod_get(q, body):
    from . import mods
    try:
        return mods.get_mod(q['id'], for_edit=bool(q.get('edit')))
    except PermissionError as e:
        raise ApiError(403, str(e))
    except (OSError, ValueError):
        raise ApiError(404, 'That mod is not in the library.')


def h_mod_conflicts(q, body):
    from . import mods
    return mods.conflict_report((body or {}).get('ids'))


def h_variant(q, body):
    from . import compat
    return compat.variant(need_game().game)


def h_mod_import(q, body):
    from . import modshare, modfile
    path = body.get('path') or _dialog('open')
    if not path:
        return dict(cancelled=True)
    try:
        return modshare.import_any(path, ws().game)
    except (modfile.Unsafe, ValueError, PermissionError) as e:
        raise ApiError(400, str(e))


def h_mod_inspect(q, body):
    from . import modfile
    path = body.get('path') or _dialog('open')
    if not path:
        return dict(cancelled=True)
    return dict(path=path, **modfile.check_file(path))


def h_open_files(q, body):
    """The files the program was started with (given out once)."""
    out = list(OPEN_FILES)
    del OPEN_FILES[:]
    return dict(files=out)


def h_collection_export(q, body):
    from . import modshare
    path = body.get('path') or _dialog('save', (body.get('name') or 'collection') + '.todcollection')
    if not path:
        return dict(cancelled=True)
    try:
        return dict(path=modshare.export_collection(body['ids'], path, body.get('name'), body.get('author') or ws().settings.get('author', ''),
                                                    body.get('description')))
    except (ValueError, PermissionError) as e:
        raise ApiError(400, str(e))


def h_piece_sources(q, body):
    from . import userlib, mods, missions_tpl
    lib = userlib.load()
    ms = []
    for p in missions_tpl.list_projects():
        for m in p['project'].get('missions') or []:
            ms.append(dict(project=p['id'], mission=m['id'], name='%s - %s' % (p['project'].get('name'), m['id'])))
    return dict(prefabs=[dict(id=x.get('id'), name=x.get('name')) for x in lib['prefabs']],
                routes=[dict(id=m['id'], name=m['name'], count=m['nav_ops']) for m in mods.list_mods() if m['nav_ops']],
                tuning=[dict(id=m['id'], name=m['name'], count=m['data_values']) for m in mods.list_mods() if m['data_values']],
                missions=ms)


def h_piece_export(q, body):
    from . import modshare
    kind = body.get('kind')
    path = body.get('path') or _dialog('save', '%s.todpiece' % (body.get('name') or kind))
    if not path:
        return dict(cancelled=True)
    try:
        return dict(path=modshare.export_piece(kind, body['source'], path, body.get('name'), ws().settings.get('author', '')))
    except (ValueError, PermissionError, KeyError) as e:
        raise ApiError(400, str(e))


def h_profiles(q, body):
    from . import profiles
    return profiles.listing()


def h_profile_action(q, body):
    from . import profiles
    act = body.get('action')
    try:
        if act == 'create':
            return profiles.create(body.get('name'), body.get('copy', True))
        if act == 'rename':
            return profiles.rename(body['name'], body['to'])
        if act == 'delete':
            return profiles.delete(body['name'])
        if act == 'switch':
            w = ws()
            if w.game is None or not body.get('rebuild', True):
                return profiles.switch(None, body['name'], rebuild=False)
            return w.jobs.start('install', profiles.switch, w, body['name'])
    except ValueError as e:
        raise ApiError(400, str(e))
    raise ApiError(400, 'unknown profile action')


def h_community(q, body):
    from . import community
    try:
        if body.get('action') == 'get':
            return community.get_entry(ws().settings, body['id'], ws().game)
        return community.catalogue(ws().settings)
    except community.Offline as e:
        raise ApiError(409, str(e))
    except ValueError as e:
        raise ApiError(400, str(e))


def h_update(q, body):
    from . import community
    st = ws().settings
    act = body.get('action', 'check')
    try:
        if act == 'check':
            return community.check_update(st)
        if act == 'download':
            return community.download_update(st)
        if act == 'run':
            r = community.run_update(body['path'], bool(body.get('confirmed')))
            if WINDOW is not None and not DEV:
                threading.Timer(1.0, lambda: WINDOW.destroy()).start()
            return dict(started=r['started'])
    except community.Offline as e:
        raise ApiError(409, str(e))
    except ValueError as e:
        raise ApiError(400, str(e))
    raise ApiError(400, 'unknown update action')


def h_report(q, body):
    from . import support
    return support.report_problem(ws(), body.get('what'), body.get('steps'))


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
    elif kind == 'image':
        r = WINDOW.create_file_dialog(webview.OPEN_DIALOG, file_types=('Pictures (*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.dds)', 'All files (*.*)'))
    elif kind == 'addon':
        r = WINDOW.create_file_dialog(webview.SAVE_DIALOG, save_filename=suggest or 'tod_mod_studio.py', file_types=('Blender add-on (*.py)', 'All files (*.*)'))
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
    return companion.asset_rows(need_game(), body or {})


def h_assets_thumbs(q, body):
    from . import companion
    w = need_game()
    return w.jobs.start('thumbnails', companion.thumbs, w, list(body.get('keys') or [])[:400])


# ---------------------------------------------------------------------------------------------- the asset catalogue
def h_cat_rows(q, body):
    from . import catalogue
    return catalogue.rows(need_game(), body or {})


def h_cat_scan(q, body):
    from . import catalogue
    w = need_game()
    return w.jobs.start('catalogue-scan', catalogue.scan, w)


def h_cat_model(q, body):
    from . import catalogue
    w = need_game()
    try:
        return w.jobs.run_sync(lambda progress=None: catalogue.detail(w, body.get('key')))
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))


def h_cat_clips(q, body):
    from . import catalogue, clips
    w = need_game()
    try:
        return w.jobs.run_sync(lambda progress=None: clips.available(w, catalogue.row_of(w, body.get('key'))))
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))


def h_cat_skin(q, body):
    from . import catalogue, clips
    w = need_game()
    try:
        return w.jobs.run_sync(lambda progress=None: clips.skin(w, catalogue.row_of(w, body.get('key'))))
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))


def h_cat_clip(q, body):
    from . import catalogue, clips
    w = need_game()
    try:
        return w.jobs.run_sync(lambda progress=None: clips.clip(w, catalogue.row_of(w, body.get('key')), body.get('clip') or ''))
    except KeyError as e:
        raise ApiError(404, str(e).strip("'\""))


def h_cat_card(q, body):
    from . import catalogue
    need_game()
    try:
        return catalogue.save_card(body.get('key'), None if body.get('none') else body.get('png'))
    except (KeyError, ValueError) as e:
        raise ApiError(400, str(e).strip("'\""))


# ---------------------------------------------------------------------------------------------- part B
def h_routes_model(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('routes', CB.routes_model, w, body.get('entries'), body.get('ops'), body.get('collision'))


def h_missions_graph(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.start('missions', CB.mission_graph, w, body['entry'], body.get('ops'), bool(body.get('lint')))


def h_missions_texts(q, body):
    from . import companion_b as CB
    w = need_game()
    return w.jobs.run_sync(lambda progress=None: dict(texts=CB.feedback_texts(w)))


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
    from . import newmap, mapnet
    action = body['action']
    if action == 'save':
        return newmap.save_project(body['params'], body.get('id'))
    if action == 'import':
        return newmap.import_project(body['path'])
    w = need_game()
    if action == 'hosts':
        return w.jobs.start('new-map-hosts', newmap.entry_hosts, w)
    if action == 'removal':
        return w.jobs.run_sync(lambda progress=None: mapnet.removal_report(w, body['id']))
    if action in ('disable', 'enable'):
        return w.jobs.start('new-map-' + action, newmap.set_enabled, w, body['id'], action == 'enable')
    if action in ('check', 'build'):
        return w.jobs.start('new-map-' + action, newmap.run, w, body['id'], action == 'check')
    if action in ('install', 'uninstall'):
        return w.jobs.start('new-map-' + action, getattr(newmap, action), w, body['id'])
    if action == 'minimap':
        return w.jobs.start('new-map-minimap', newmap.minimap, w, body['id'])
    raise ApiError(400, 'unknown new-map action')


def h_newmap_allocation(q, body):
    from . import mapnet
    w = need_game()
    return w.jobs.run_sync(lambda progress=None: mapnet.allocation(w))


def h_newmap_hosts(q, body):
    from . import mapnet
    w = need_game()
    return w.jobs.start('new-map-hosts-view', mapnet.hosts, w)


def h_newmap_links(q, body):
    from . import mapnet
    w = need_game()
    return w.jobs.run_sync(lambda progress=None: mapnet.links(w))


def h_world_atlas(q, body):
    from . import world
    w = ws()
    return dict(bounds=world.bounds(), layout=world.atlas_default_layout(None), safe=world.SAFE_BOX, **world.templates_info())


def h_world_action(q, body):
    from . import world, newmap
    action = body.get('action')
    try:
        if action == 'sizes':
            return dict(sizes=world.size_presets(body.get('template') or 'blank'))
        if action == 'mapname':
            taken = [m.get('name') for p in newmap.list_projects() if p['id'] != body.get('id') for m in p['params'].get('maps', [])] + list(body.get('taken') or [])
            return dict(name=world.suggest_map_name(body.get('title'), int(body.get('length') or 18), taken))
        if action == 'start':
            info = newmap.info()
            key = body.get('source') or next(iter(info['sources']))
            src = info['sources'][key]
            taken = [m.get('name') for p in newmap.list_projects() for m in p['params'].get('maps', [])]
            w = ws()
            others = []
            for p in newmap.list_projects():
                for om in p['params'].get('maps', []):
                    for e in newmap.entries(om):
                        others.append((p['params'].get('package') or p['id'], e.get('block'), e.get('pos'), e.get('size') or [12, 6, 2], world._yaw_of(e.get('orient'))))
            return w.jobs.run_sync(lambda progress=None: world.start_project(body.get('template') or 'blank', body.get('size') or 'medium', key, src['map_name'],
                                                                             body.get('host'), taken, body.get('package'), w if w.game else None, others))
        if action == 'analyse':
            w = ws()
            others = [(p['params'].get('package') or p['id'], p['params']) for p in newmap.list_projects() if p['id'] != body.get('id')]
            return w.jobs.run_sync(lambda progress=None: world.analyse(w if w.game else None, body['params'], others))
        if action == 'edge':
            return dict(profile=world.edge_profile(body['map'], body['edge']))
        if action == 'export':
            return world.export_recipe(body['params'], body['path'])
    except (ValueError, KeyError, OSError) as e:
        raise ApiError(400, str(e))
    raise ApiError(400, 'unknown world action')


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


def h_pack_rebuild(q, body):
    from . import pack
    w = need_game()
    return w.jobs.start('rebuild', pack.rebuild, w)


def h_vanilla(q, body):
    from . import restore
    w = need_game()
    return w.jobs.start('restore-vanilla', restore.restore_vanilla, w)


def h_verify(q, body):
    from . import restore
    w = need_game()
    return w.jobs.start('verify', restore.verify, w)


def h_verify_repair(q, body):
    from . import restore
    w = need_game()
    return w.jobs.start('repair', restore.repair, w, list(body.get('names') or []))


def h_backups(q, body):
    from . import restore
    return dict(backups=restore.list_backups(need_game()))


def h_backup_restore(q, body):
    from . import restore
    w = need_game()
    return w.jobs.start('restore-backup', restore.restore_backup, w, body['id'])


def h_backup_delete(q, body):
    from . import restore
    return restore.delete_backups(need_game(), list(body.get('ids') or []))


def h_snapshots(q, body):
    from . import snapshots, saves
    return dict(snapshots=snapshots.list_snapshots(), folder=saves.saves_dir())


def h_snapshot_restore(q, body):
    from . import snapshots, saves, game as gm
    w = need_game()
    if gm.game_running(w.game.folder):
        raise ApiError(409, 'Total Overdose is running: close it first')
    return snapshots.restore(body['id'], saves.saves_dir())


def h_limits(q, body):
    from . import limits
    return dict(limits=limits.rows())


def h_ledger(q, body):
    """The ceiling ledger: every limit with vanilla + installed packages + this project = used. No game folder: the table with nothing measured."""
    from . import ledger
    w = ws()
    return ledger.compute(w, body.get('kind'), body.get('project'), body.get('id'), body.get('heavy'))


def h_problems(q, body):
    from . import problems
    return problems.collect(ws(), body.get('kind'), body.get('project'), body.get('id'), body.get('results'), body.get('heavy'))


def _pk(body):
    return body.get('kind'), body.get('id') or ('_current' if body.get('kind') == 'level' else '_draft')


def h_autosave_get(q, body):
    from . import projstore
    k = q.get('id') or ('_current' if q.get('kind') == 'level' else '_draft')
    return dict(autosave=projstore.autosaved(q.get('kind'), k))


def h_autosave(q, body):
    from . import projstore
    kind, key = _pk(body)
    if body.get('clear'):
        return projstore.clear_autosave(kind, key)
    return projstore.autosave(kind, key, body['project'])


def h_projsnaps_get(q, body):
    from . import projstore
    return dict(snapshots=projstore.list_snapshots(q.get('kind'), q['id']))


def h_projsnaps(q, body):
    from . import projstore
    kind, key = body.get('kind'), body['id']
    act = body.get('action')
    try:
        if act == 'save':
            r = projstore.snapshot(kind, key, body.get('name'), body['project'])
            return dict(snapshot=r, snapshots=projstore.list_snapshots(kind, key))
        if act == 'restore':
            return projstore.restore(kind, key, body['snapshot'], body.get('project'))
        if act == 'delete':
            return projstore.delete_snapshot(kind, key, body['snapshot'])
    except ValueError as e:
        raise ApiError(400, str(e))
    raise ApiError(400, 'unknown snapshot action')


def h_missiontpl_savefix(q, body):
    from . import saves
    w = need_game()
    return w.jobs.start('mission-save-update', saves.migrate_missions, w, body['source'], body.get('install_as'), body.get('folder'))



# ---------------------------------------------------------------------------------------------- test in game, debug area
TEST_STEPS = ('check', 'build', 'install', 'save', 'launch')


def _test_opts(body):
    o = dict(body.get('opts') or {})
    if o.get('pos') is not None:
        o['pos'] = [float(x) for x in o['pos']]
    if o.get('yaw') in ('', None):
        o['yaw'] = None
    if o.get('start_mission') in ('', None):
        o['start_mission'] = None
    return o


def _has_project(mod):
    return bool(mod) and bool(mod.get('level') or mod.get('data') or mod.get('collision') or mod.get('nav') or mod.get('missions') or mod.get('sections'))


def _test_job(body, progress=None):
    """Check, build, install into the test copy, make the test save, launch. Every step reports its number so the UI can show where it is
    (the job message is 'step|detail')."""
    from . import testgame, mods, problems, game as gm
    w = ws()
    if gm.game_running():
        raise RuntimeError('Total Overdose is running: close it first')
    mod = body.get('mod')
    real = bool(body.get('real'))
    opts = _test_opts(body)

    def step(i, sub=''):
        def f(msg=None, done=None, total=None):
            progress('%s|%s' % (TEST_STEPS[i], msg if msg else sub), done=i, total=len(TEST_STEPS))
        return f
    out = dict(steps=list(TEST_STEPS))
    has_project = _has_project(mod)
    step(0)()
    if has_project:
        r = _check_job(mod, step(0))
        bad = [c['title'] for c in r['checks'] if c['level'] == 'error']
        problems.refuse_if(bad, 'The test was not started')
        out['checks'] = dict(errors=len(bad), warnings=sum(1 for c in r['checks'] if c['level'] == 'warn'))
    rec = None
    if real:
        step(1)()
        if has_project:
            m = mods.save_mod(mod)
            o = mods.load_order()
            if m['id'] not in o['enabled']:
                mods.set_state(enabled=o['enabled'] + [m['id']])
            out['mod'] = m
        step(2)()
        mods.install(w, progress=step(2))
    else:
        step(1)()
        rec = testgame.make_copy(w, None, bool(body.get('allow_full_copy')), step(1))
        if rec.get('confirm'):
            return dict(out, confirm=rec['confirm'])
        step(2)()
        info = testgame.install_pack(w, rec, mod if has_project else None, None, step(2))
        out['installed'] = dict(mods=info['mods'], pack=info['pack'])
    step(3)()
    isolated = (not real) and testgame.isolation_works()
    put = testgame.put_save(w, rec, opts, isolated, step(3))
    out['save'] = put
    if body.get('no_launch'):
        return dict(out, launched=False)
    step(4)()
    st = testgame.launch(w, rec, put, keep=bool(body.get('keep')), label=(mod or {}).get('name'), real=real, bisect=body.get('bisect'))
    out['run'] = {k: v for k, v in st.items() if k != 'saves'}
    return out


def h_test_run(q, body):
    return need_game().jobs.start('testrun', _test_job, body)


def h_test_status(q, body):
    from . import testgame
    return testgame.status(ws() if ws().game else None, light=bool(q.get('light')))


def h_test_log(q, body):
    from . import testgame
    return testgame.live_log(int(q.get('offset') or 0))


def h_test_plan(q, body):
    from . import testgame
    return testgame.plan(need_game().game.folder, (body or {}).get('dest'))


def h_test_stop(q, body):
    from . import testgame
    return testgame.stop()


def h_test_keep(q, body):
    from . import testgame
    st = testgame.current()
    if st and st.get('status') == 'running':
        st['keep'] = bool(body.get('keep'))
        testgame._set(st)
    return dict(keep=bool(body.get('keep')))


def h_test_remove(q, body):
    from . import testgame
    return testgame.remove_install(body['id'], ws().game.folder if ws().game else None)


def h_test_missions(q, body):
    from . import saves
    return dict(missions=saves.missions(need_game(), body['source']))


def h_support(q, body):
    from . import support
    return support.build(need_game(), body.get('extra'))


def _bisect_path():
    return os.path.join(paths.user_dir(), 'bisect.json')


def _bisect_read():
    try:
        with open(_bisect_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _bisect_write(st):
    if st is None:
        try:
            os.remove(_bisect_path())
        except OSError:
            pass
        return
    with open(_bisect_path() + '.part', 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    os.replace(_bisect_path() + '.part', _bisect_path())


def _bisect_view(st):
    from . import mods, bisect_mods
    lib = mods.list_mods()
    on = [dict(id=m['id'], name=m['name']) for m in lib if m['enabled']]
    if not st:
        return dict(state=None, mods=on)
    names = {m['id']: m['name'] for m in lib}

    def nm(ids):
        return [names.get(i, i) for i in ids]
    view = dict(st, next=nm(bisect_mods.pending(st) or []), next_ids=bisect_mods.pending(st) or [], candidate_names=nm(st['candidates']),
                steps=[dict(s, names=nm(s['mods'])) for s in st['steps']], culprit_name=names.get(st.get('culprit')))
    return dict(state=view, mods=on)


def _bisect_test_job(body, progress=None):
    from . import testgame, bisect_mods, game as gm
    w = ws()
    if gm.game_running():
        raise RuntimeError('Total Overdose is running: close it first')
    st = _bisect_read()
    ids = bisect_mods.pending(st) if st else None
    if ids is None:
        raise ValueError('The search is finished.')
    rec = testgame.make_copy(w, None, bool(body.get('allow_full_copy')), progress)
    if rec.get('confirm'):
        return dict(confirm=rec['confirm'])
    testgame.install_pack(w, rec, None, ids, progress)
    opts = _test_opts(body)
    put = testgame.put_save(w, rec, opts, testgame.isolation_works(), progress)
    run = testgame.launch(w, rec, put, keep=True, label='Bisect', bisect=dict(ids=ids))
    return dict(run={k: v for k, v in run.items() if k != 'saves'}, mods=ids)


def h_bisect(q, body):
    return _bisect_view(_bisect_read())


def h_bisect_act(q, body):
    from . import mods, bisect_mods
    a = body.get('action')
    st = _bisect_read()
    if a == 'start':
        o = mods.load_order()
        st = bisect_mods.start([i for i in o['order'] if i in o['enabled']])
        _bisect_write(st)
    elif a == 'answer' and st:
        st = bisect_mods.answer(st, bool(body.get('bad')))
        _bisect_write(st)
    elif a == 'cancel':
        _bisect_write(None)
        st = None
    elif a == 'test':
        need_game()
        if not st:
            raise ApiError(409, 'Start a search first.')
        return ws().jobs.start('bisect', _bisect_test_job, body)
    return _bisect_view(st)


# ---------------------------------------------------------------------------------------------- model import and the texture editor
def _apierr(fn):
    from . import imports
    try:
        return fn()
    except (imports.ImportError_, KeyError) as e:
        raise ApiError(400, str(e).strip("'\""))
    except ValueError as e:
        raise ApiError(400, str(e))
    except MemoryError:
        raise ApiError(400, 'the model is too big to process')
    except Exception:                                          # noqa: BLE001  (the screen shows one plain line, never an exception text)
        import traceback
        traceback.print_exc()
        raise ApiError(400, 'this model could not be processed')


def h_import_analyze(q, body):
    from . import imports
    path = body.get('path') or _dialog('mesh')
    if not path:
        return dict(cancelled=True)
    return _apierr(lambda: imports.analyze(path))


def h_ccc_vehicles(q, body):
    from . import cccveh
    return cccveh.listing(ws().settings)


def h_ccc_analyze(q, body):
    from . import cccveh
    return _apierr(lambda: cccveh.analyze(ws().settings, body.get('id')))


def h_import_preview(q, body):
    from . import imports
    w = need_game()
    return w.jobs.start('import-preview', lambda progress=None: _apierr(lambda: imports.preview(w, body, progress)))


def h_import_entry(q, body):
    from . import imports
    w = need_game()
    return w.jobs.start('import-entry', lambda progress=None: _apierr(lambda: imports.entry(w, body, progress)))


def h_models_imported(q, body):
    from . import imports
    w = need_game()
    return dict(models=w.jobs.run_sync(lambda progress=None: imports.imported_records(w, body.get('models'))))


def h_blender_pending(q, body):
    from . import blender
    w = ws()
    if not w.settings.get('blender_bridge'):
        return dict(on=False, items=[])
    return dict(on=True, items=blender.pending())


def h_blender_addon(q, body):
    from . import blender
    path = body.get('path') or _dialog('addon', 'tod_mod_studio.py')
    if not path:
        return dict(cancelled=True)
    if os.path.isdir(path):
        path = os.path.join(path, 'tod_mod_studio.py')
    with open(path, 'wb') as f:
        f.write(blender.addon_text())
    return dict(path=path)


def h_blender_ping(q, body):
    return dict(ok=True, on=bool(ws().settings.get('blender_bridge')))


def h_blender_send(q, body):
    from . import blender
    try:
        return blender.receive(ws().settings, body)
    except blender.BridgeError as e:
        raise ApiError(e.code, str(e))


def h_models_search(q, body):
    from . import imports, assetindex
    w = need_game()
    doc = assetindex.load(w)
    if doc is None:
        return dict(ready=False, rows=[])
    return dict(ready=True, rows=imports.model_rows(doc, body.get('q') or '', int(body.get('limit') or 60)))


def h_tex_rows(q, body):
    from . import imports
    w = need_game()
    return imports.tex_rows(w, body)


def h_tex_build(q, body):
    from . import assetindex
    w = need_game()
    return w.jobs.start('texture-index', lambda progress=None: assetindex.build(w, progress))


def h_tex_info(q, body):
    from . import imports
    w = need_game()
    return _apierr(lambda: w.jobs.run_sync(lambda progress=None: imports.tex_info(w, body['name'])))


def h_tex_thumbs(q, body):
    from . import imports
    w = need_game()
    return dict(thumbs=w.jobs.run_sync(lambda progress=None: imports.tex_thumbs(w, list(body.get('names') or [])[:80])))


def h_tex_upload(q, body):
    from . import imports
    path = body.get('path')
    if not path and not body.get('data'):
        path = _dialog('image')
        if not path:
            return dict(cancelled=True)
    return _apierr(lambda: imports.upload(path, body.get('data'), body.get('name')))


def h_tex_render(q, body):
    from . import imports
    w = need_game()
    return w.jobs.start('texture-render', lambda progress=None: _apierr(lambda: imports.tex_render(w, body)))



# ------------------------------------------------------------------------------------------------ large scene import
def _scene(fn):
    from . import sceneimport
    try:
        return fn(sceneimport)
    except (sceneimport.SceneError, KeyError) as e:
        raise ApiError(400, str(e).strip("'\""))
    except ValueError as e:
        raise ApiError(400, str(e))


def _scene_job(kind, fn):
    from . import sceneimport

    def run(progress=None):
        try:
            return fn(sceneimport, progress)
        except (sceneimport.SceneError, KeyError) as e:
            raise ValueError(str(e).strip("'\""))
    return ws().jobs.start(kind, run)


def h_scene_open(q, body):
    path = body.get('path') or _dialog('mesh')
    if not path:
        return dict(cancelled=True)
    return _scene_job('scene-open', lambda m, progress: m.open_scene(path, progress))


def h_scene_overview(q, body):
    return _scene_job('scene-overview', lambda m, progress: m.overview(body['sid'], body.get('params'), progress))


def h_scene_count(q, body):
    return _scene(lambda m: m.count_region(body['sid'], body.get('params')))


def h_scene_sample(q, body):
    return _scene(lambda m: m.sample_glb(body['sid'], body.get('params'), body['center'], float(body.get('radius') or 40)))


def h_scene_glb(q, body):
    return _scene(lambda m: m.stage_glb(body['sid'], body.get('params'), body.get('stage') or 'clean'))


def h_scene_report(q, body):
    return _scene_job('scene-' + (body.get('stage') or 'clean'), lambda m, progress: m.report(body['sid'], body.get('params'), body.get('stage') or 'clean', progress))


def h_scene_send(q, body):
    return _scene_job('scene-send', lambda m, progress: m.send(body['sid'], body.get('params'), body.get('target') or {}, progress))


GET = {'/api/blender/ping': h_blender_ping, '/api/world/atlas': h_world_atlas, '/api/starters': h_starters, '/api/newmap/allocation': h_newmap_allocation, '/api/newmap/hosts': h_newmap_hosts, '/api/newmap/links': h_newmap_links, '/api/startup/files': h_open_files, '/api/variant': h_variant, '/api/profiles': h_profiles, '/api/userlib': h_userlib_get, '/api/testgame': h_test_status, '/api/testgame/log': h_test_log, '/api/bisect': h_bisect, '/api/autosave': h_autosave_get, '/api/projsnaps': h_projsnaps_get, '/api/backups': h_backups, '/api/snapshots': h_snapshots, '/api/limits': h_limits, '/api/missiontpl': h_missiontpl, '/api/newmaps': h_newmaps, '/api/status': h_status, '/api/overview': h_overview, '/api/catalog': h_catalog, '/api/entity': h_entity, '/api/mods': h_mods,
       '/api/mods/get': h_mod_get, '/api/saves': h_saves, '/api/enums': h_enums, '/api/names': h_names,
       '/api/token': h_token, '/api/companion/catalog': h_comp_catalog}
POST = {'/api/scene/open': h_scene_open, '/api/scene/overview': h_scene_overview, '/api/scene/count': h_scene_count, '/api/scene/sample': h_scene_sample, '/api/scene/glb': h_scene_glb, '/api/scene/report': h_scene_report, '/api/scene/send': h_scene_send, '/api/starters/open': h_starter_open, '/api/mods/conflicts': h_mod_conflicts, '/api/mods/inspect': h_mod_inspect, '/api/collections/export': h_collection_export, '/api/pieces/sources': h_piece_sources, '/api/pieces/export': h_piece_export, '/api/profiles': h_profile_action, '/api/community': h_community, '/api/update': h_update, '/api/report': h_report, '/api/userlib': h_userlib_set, '/api/testgame/run': h_test_run, '/api/testgame/plan': h_test_plan, '/api/testgame/stop': h_test_stop, '/api/testgame/keep': h_test_keep,
        '/api/testgame/remove': h_test_remove, '/api/saves/missions': h_test_missions, '/api/support/bundle': h_support, '/api/bisect': h_bisect_act, '/api/import/analyze': h_import_analyze, '/api/import/preview': h_import_preview, '/api/import/entry': h_import_entry,
        '/api/blender/send': h_blender_send, '/api/blender/pending': h_blender_pending, '/api/blender/addon': h_blender_addon, '/api/ccc/vehicles': h_ccc_vehicles, '/api/ccc/analyze': h_ccc_analyze, '/api/models/imported': h_models_imported, '/api/models/search': h_models_search,
        '/api/textures/rows': h_tex_rows, '/api/textures/build': h_tex_build, '/api/textures/info': h_tex_info,
        '/api/textures/thumbs': h_tex_thumbs, '/api/textures/upload': h_tex_upload, '/api/textures/render': h_tex_render,
        '/api/ledger': h_ledger, '/api/problems': h_problems, '/api/autosave': h_autosave, '/api/projsnaps': h_projsnaps, '/api/pack/rebuild': h_pack_rebuild, '/api/restore/vanilla': h_vanilla, '/api/verify': h_verify, '/api/verify/repair': h_verify_repair,
        '/api/backups/restore': h_backup_restore, '/api/backups/delete': h_backup_delete, '/api/snapshots/restore': h_snapshot_restore,
        '/api/missiontpl': h_missiontpl_action, '/api/missiontpl/savefix': h_missiontpl_savefix, '/api/newmaps': h_newmap_action, '/api/world': h_world_action, '/api/setup': h_setup, '/api/settings': h_settings, '/api/prepare': h_prepare, '/api/open': h_open,
        '/api/templates': h_templates, '/api/models/find': h_models_find, '/api/ram/moves': h_ram_moves, '/api/check': h_check, '/api/export': h_export, '/api/mods/save': h_mod_save,
        '/api/mods/delete': h_mod_delete, '/api/mods/state': h_mod_state, '/api/mods/install': h_mod_install,
        '/api/mods/uninstall': h_mod_uninstall, '/api/mods/export': h_mod_export, '/api/mods/import': h_mod_import,
        '/api/saves/make': h_save_make, '/api/dialog': h_dialog, '/api/reveal': h_reveal,
        '/api/collision/preview': h_coll_preview, '/api/collision/generate': h_coll_generate,
        '/api/collision/check': h_coll_check, '/api/collision/existing': h_coll_existing,
        '/api/assets/census': h_assets_census, '/api/assets/rows': h_assets_rows, '/api/assets/thumbs': h_assets_thumbs,
        '/api/catalogue/rows': h_cat_rows, '/api/catalogue/scan': h_cat_scan, '/api/catalogue/model': h_cat_model,
        '/api/catalogue/card': h_cat_card, '/api/catalogue/clips': h_cat_clips, '/api/catalogue/skin': h_cat_skin,
        '/api/catalogue/clip': h_cat_clip,
        '/api/routes/model': h_routes_model, '/api/missions/graph': h_missions_graph, '/api/missions/texts': h_missions_texts,
        '/api/sections/catalog': h_sections_catalog, '/api/sections/fix': h_sections_fix,
        '/api/sections/split': h_sections_split, '/api/partb/check': h_partb_check}


def _mapbuild_routes():
    from . import mapbuild_api
    return mapbuild_api.GET, mapbuild_api.POST


_mb_get, _mb_post = _mapbuild_routes()
GET.update(_mb_get)
POST.update(_mb_post)


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
        if urllib.parse.urlparse(self.path).path == '/api/blender/send':
            # the add-on of Blender: no page token, but never from a web page, only to this host, only with its own header
            host = (self.headers.get('Host') or '').split(':')[0]
            if self.headers.get('Origin') or self.headers.get('X-TODMS-Bridge') != '1' or host not in ('127.0.0.1', 'localhost'):
                return self._send(403, dict(error='not allowed'))
        elif self.headers.get('X-TODMS-Token') != TOKEN:
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


PORT = [0]


def serve(port=0):
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    PORT[0] = srv.server_address[1]
    try:
        from . import blender
        with open(os.path.join(paths.user_dir(), 'settings.json')) as f:
            blender.announce(PORT[0], bool(json.load(f).get('blender_bridge')))
    except Exception:                                          # noqa: BLE001
        pass
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
