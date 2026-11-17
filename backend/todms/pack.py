"""The ONE archive Mod Studio puts in the game: todms_pack.zip (K1).

Three parts are installed independently and recorded as inputs:
  mods      the enabled mod ids (installed.json in the library folder)
  newmaps   {project id: record with the params it was built from} (todms_newmaps.json in the game folder)
  missions  the mission projects with their snapshots (todms_missions.json in the game folder)
Installing, removing or changing any part rebuilds the pack from the recorded inputs, in this order:
  1. mods       built on the game's own archives (Gameplay+, TOD HD ...)
  2. new maps   each one built reading the earlier stages through base_overlay (the entry list widened to every block they touched)
  3. missions   built with the earlier stages in front of the game's archives
and the finished stage archives are merged (a later stage wins a block it rebuilt, because it was built on top of the earlier one).
The writes (pack, configpc.txt, records) are journaled (journal.py) and every install first copies the saves folder (snapshots.py).
"""
import base64
import copy
import datetime
import hashlib
import json
import os
import shutil
import sys
import zipfile

from . import archives, game, journal, mapalloc, paths, snapshots

RECORD = 'todms_pack.json'
NEWMAP_RECORD = 'todms_newmaps.json'
MISSIONS_RECORD = 'todms_missions.json'
_DEFAULT_ENTRIES = (game.MAIN_ENTRY, game.SHARED + 'submap01_map02_lostoros_downtown.submap', 'data_pc/overdose_the_game/overdose/uk/overdose_uk.main')
KEEP = object()                 # "this part stays as recorded"
STAGE_DIR = 'pack_stage'


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


# ------------------------------------------------------------------------------------------------ records
def _read(p):
    try:
        with open(p, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def record_path(folder):
    return os.path.join(folder, RECORD)


def read_record(folder):
    return _read(record_path(folder)) or {}


def installed_json():
    from . import mods
    return os.path.join(mods.lib_dir(), 'installed.json')


def record_paths(folder):
    return [installed_json(), record_path(folder), os.path.join(folder, NEWMAP_RECORD), os.path.join(folder, MISSIONS_RECORD),
            mapalloc.path(folder)]


def read_inputs(folder):
    inst = _read(installed_json()) or {}
    pk = read_record(folder)
    mods_ids = list(inst.get('mods') or []) if pk.get('sha256') and inst.get('installed') else []
    return dict(mods=mods_ids, newmaps=_read(os.path.join(folder, NEWMAP_RECORD)) or {},
                missions=_read(os.path.join(folder, MISSIONS_RECORD)) or {}, alloc=mapalloc.read(folder))


def owners_of(state):
    """[(owner key, params, label)] of every installed new map in install order: the new-map records, then the maps only a mission
    package carries. The key is the project's permanent uid."""
    out, seen = [], set()
    for pid, rec in (state.get('newmaps') or {}).items():
        params = rec.get('params')
        if params:
            k = mapalloc.key_of(params, pid)
            if k not in seen:
                seen.add(k)
                out.append((k, params, rec.get('name') or pid))
    for p in ((state.get('missions') or {}).get('projects') or {}).values():
        for nid, params in (p.get('newmaps') or {}).items():
            k = mapalloc.key_of(params, nid)
            if k not in seen:
                seen.add(k)
                out.append((k, params, (params or {}).get('package') or nid))
    return out


def ents_pins(rec):
    """The mission record -> (entries, pins) as missions_tpl builds from them."""
    ents, pins = [], {}
    for pid, p in (rec.get('projects') or {}).items():
        ents.append((pid, dict(name=p['name'], project=p['project'], newmaps=p['newmaps'])))
        for mid, (ty, idx) in (p.get('indices') or {}).items():
            pins[(pid, mid)] = (ty, idx)
    return ents, pins


def superseded_newmaps(missions):
    return sorted({nid for p in (missions.get('projects') or {}).values() for nid in p.get('newmaps', {})})


# ------------------------------------------------------------------------------------------------ stage cache
def stage_dir():
    d = os.path.join(paths.cache_dir(), STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _cached(kind, key, fresh_dir=False):
    """-> path of the cached zip for (kind, key), or None. A new key for a kind drops that kind's older entries (disk space)."""
    return os.path.join(stage_dir(), '%s_%s.zip' % (kind, key))


def _drop_old(kind, keep):
    import re
    for n in os.listdir(stage_dir()):
        if re.fullmatch(re.escape(kind) + r'_[0-9a-f]{24}\.zip', n) and os.path.join(stage_dir(), n) not in keep:
            try:
                os.remove(os.path.join(stage_dir(), n))
            except OSError:
                pass
            try:
                os.remove(os.path.join(stage_dir(), n[:-4] + '.json'))
            except OSError:
                pass


def _entries_of(z):
    with zipfile.ZipFile(z) as f:
        return f.namelist()


def widened_entries(prior):
    """Every block an earlier stage touched, plus the entries the overlay serves by default."""
    bo = sys.modules.get('base_overlay')
    out = set(bo.DEFAULT_ENTRIES if bo else _DEFAULT_ENTRIES)
    for z in prior:
        out.update(_entries_of(z))
    return sorted(out)


# ------------------------------------------------------------------------------------------------ stages
def _stage_mods(ws, ids, prior, hints, progress):
    from . import mods
    objs = hints.get('mod_objects') or {}      # mods that are not in the library (a test run of the open project)
    ml = [objs[i] if i in objs else mods.get_mod(i) for i in ids]
    sig = ws.game.signature() if hasattr(ws.game, 'signature') else None
    key = _key('mods', ml, sig, getattr(ws, 'base_mode', None), getattr(ws, 'settings', {}).get('save_safe_delete'))
    z, meta = _cached('mods', key), None
    if os.path.exists(z) and os.path.exists(z[:-4] + '.json'):
        meta = _read(z[:-4] + '.json')
    else:
        out = os.path.join(paths.cache_dir(), 'install_stage')
        shutil.rmtree(out, ignore_errors=True)
        rep = mods.build_mods(ws, ml, out, 'stage_mods.zip', progress)
        rep.pop('_outs', None)
        if not rep.get('entries'):
            shutil.rmtree(out, ignore_errors=True)
            return None
        os.replace(os.path.join(out, 'stage_mods.zip'), z)
        shutil.rmtree(out, ignore_errors=True)
        meta = dict(blocks=[dict(entry=b['entry'], base=b['base_archive'], bytes=b['bytes']) for b in rep['blocks']], save_safe=rep['save_safe'])
        journal.atomic_json(z[:-4] + '.json', meta)
    _drop_old('mods', [z])
    return dict(name='mods', zip=z, meta=meta)


def _stage_newmaps(ws, newmaps, superseded, prior, hints, progress):
    """Switched-off maps stay in the record (their numbers stay reserved) but add nothing to the pack."""
    off = {pid: r for pid, r in newmaps.items() if r.get('disabled')}
    if not off:
        return _stage_newmaps_on(ws, newmaps, superseded, prior, hints, progress)
    out, recs = _stage_newmaps_on(ws, {pid: r for pid, r in newmaps.items() if pid not in off}, superseded, prior, hints, progress)
    recs.update(off)
    return out, recs


def _stage_newmaps_on(ws, newmaps, superseded, prior, hints, progress):
    from . import newmap
    out, recs = [], {}
    alloc = hints.get('alloc') or {}
    folded = set(hints.get('folded') or [])
    live = [(pid, rec) for pid, rec in newmaps.items() if pid not in superseded]
    plain = [(pid, rec) for pid, rec in live if pid not in folded and not (rec.get('frozen') and os.path.exists(rec['frozen']))]
    if len(plain) > 1:
        merged_ids = {pid for pid, _ in plain}
        for pid, rec in live:                    # a frozen archive keeps its own stage, ahead of the merged one
            if pid not in merged_ids and pid not in folded:
                st, r_ = _stage_newmaps(ws, {pid: rec}, set(), prior, dict(hints, folded=[], alloc=alloc), progress)
                out += st
                recs.update(r_)
                prior = list(prior) + [x['zip'] for x in st]
        st = _stage_newmaps_merged(ws, plain, prior, hints, progress)
        out.append(st)
        recs.update({pid: rec for pid, rec in plain})
        for pid, rec in live:
            if pid in folded:
                recs[pid] = rec
        return out, recs
    for pid, rec in newmaps.items():
        if pid in folded:
            recs[pid] = rec
            continue
        if pid in superseded:
            continue
        shas = [archives_sha(p) for p in prior]
        entry = (alloc.get('owners') or {}).get(mapalloc.key_of(rec.get('params'), pid))
        key = _key('newmap', pid, rec.get('params'), shas, rec.get('frozen_sha256'), entry)
        z = _cached('newmap_' + pid, key)
        if not os.path.exists(z):
            if rec.get('frozen') and os.path.exists(rec['frozen']):
                shutil.copy2(rec['frozen'], z)
            else:
                params = rec.get('params')
                if not params:
                    raise ValueError('The new map "%s" has no recorded settings to rebuild from. Build and install it again.' % pid)
                src = None
                if not prior and hints.get('newmap_built', {}).get(pid) and mapalloc.is_default(entry):
                    src = hints['newmap_built'][pid]
                if src and os.path.exists(src):
                    shutil.copy2(src, z)
                else:
                    d = os.path.join(paths.cache_dir(), 'pack_newmap_build')
                    shutil.rmtree(d, ignore_errors=True)
                    ov = (prior, widened_entries(prior)) if prior else None
                    built = newmap.build_params(ws, params, d, ov, progress, alloc_entry=entry)
                    os.replace(built, z)
                    shutil.rmtree(d, ignore_errors=True)
        _drop_old('newmap_' + pid, [z])
        out.append(dict(name='newmap:' + pid, zip=z))
        prior = list(prior) + [z]
        recs[pid] = rec
    return out, recs


def _stage_newmaps_merged(ws, items, prior, hints, progress):
    """Two or more new-map projects in ONE builder pass: the entries every project adds to the same shipped block (Downtown
    SUBMAP01 is the usual one) are replayed onto one copy of that block, entry by entry, under node names that carry the map's own name.
    A second pass over a block the first pass already appended to is refused by the save-safety rule, so chained passes cannot do this."""
    from . import newmap
    alloc = hints.get('alloc') or {}
    maps, extra, used = [], {}, []
    for pid, rec in items:
        entry = (alloc.get('owners') or {}).get(mapalloc.key_of(rec.get('params'), pid))
        pr = newmap.prepared(rec['params'], entry)
        maps.extend(copy.deepcopy(pr['maps']))
        for k in ('existing_enemies', 'existing_givers', 'test_loaders', 'existing_vehicles', 'existing_spots'):
            extra.setdefault(k, []).extend(copy.deepcopy(pr.get(k) or []))
        used.append((pid, rec.get('params'), entry))
    combined = dict(package='todms_newmaps', maps=maps, **{k: v for k, v in extra.items() if v})
    shas = [archives_sha(p) for p in prior]
    z = _cached('newmaps', _key('newmaps', used, shas))
    if not os.path.exists(z):
        d = os.path.join(paths.cache_dir(), 'pack_newmap_build')
        shutil.rmtree(d, ignore_errors=True)
        ov = (prior, widened_entries(prior)) if prior else None
        built = newmap.build_params(ws, combined, d, ov, progress, expanded=True)
        os.replace(built, z)
        shutil.rmtree(d, ignore_errors=True)
    _drop_old('newmaps', [z])
    return dict(name='newmaps', zip=z)


def archives_sha(p):
    return journal.file_sha(p)


def _stage_missions(ws, missions, prior, hints, progress):
    from . import missions_tpl as MT
    ents, pins = ents_pins(missions)
    if not ents:
        return None
    alloc = hints.get('alloc') or {}
    more = hints.get('extra_maps') or []
    rev = MT.revision(dict(entries=[(p, s) for p, s in ents], pins=sorted((list(k), list(v)) for k, v in pins.items()),
                           chain=MT.chain_signature(ws), prior=[archives_sha(p) for p in prior],
                           **(dict(alloc=alloc.get('owners')) if alloc.get('owners') else {}),
                           **(dict(extra_maps=more) if more else {})))
    z = _cached('missions', rev[:24])
    meta = _read(z[:-4] + '.json') if os.path.exists(z) else None
    if meta is None:
        built = hints.get('missions_built')
        if built and not prior and not more and os.path.exists(built['zip']) and built.get('sha256') == journal.file_sha(built['zip']):
            shutil.copy2(built['zip'], z)
            res = built['result']
        else:
            d = os.path.join(paths.cache_dir(), 'pack_missions_build')
            shutil.rmtree(d, ignore_errors=True)
            extra = dict(alloc=alloc) if alloc.get('owners') else {}
            if more:
                extra['extra_maps'] = more
            res = MT.build_set(ws, ents, pins, d, progress, None, extra_chain=prior,
                               overlay_entries=widened_entries(prior) if prior else None, **extra)
            if not res.get('ok'):
                raise ValueError('The missions did not build: ' + '; '.join(m['text'] for m in res.get('messages', [])[:3]))
            os.replace(res['zip'], z)
            shutil.rmtree(d, ignore_errors=True)
        meta = dict(index_of=res['index_of'], migrate_entries=res['migrate_entries'], thread_keys=res.get('thread_keys', []),
                    missions=res['missions'], sha256=journal.file_sha(z))
        journal.atomic_json(z[:-4] + '.json', meta)
    _drop_old('missions', [z])
    return dict(name='missions', zip=z, meta=meta, ents=ents)


STAGES = dict(mods=_stage_mods, newmaps=_stage_newmaps, missions=_stage_missions)


# ------------------------------------------------------------------------------------------------ build the pack
def build(ws, state, progress=None, hints=None, out=None):
    """Build every stage and merge them into `out` (default: the .part file next to the pack in the game folder).
    -> dict(zips, stages, newmaps, missions_meta, parts) ; zips empty when nothing is installed."""
    hints = dict(hints or {})
    if state.get('alloc') is not None:
        hints['alloc'] = state['alloc']
    folder = ws.game.folder
    prior, stages = [], []
    if state['mods']:
        s = STAGES['mods'](ws, state['mods'], prior, hints, progress)
        if s:
            stages.append(s)
            prior.append(s['zip'])
    sup = superseded_newmaps(state['missions'])
    if (state['missions'] or {}).get('projects'):
        # the missions library builds its host maps itself; the other new maps go into the same pass (one overdose.main edit, one pass
        # over each shared host block), so they are folded in instead of getting a stage of their own
        fold = [pid for pid, rec in state['newmaps'].items() if pid not in sup and rec.get('params') and not rec.get('disabled')
                and not (rec.get('frozen') and os.path.exists(rec['frozen']))]
        hints['folded'] = fold
        hints['extra_maps'] = [(pid, state['newmaps'][pid]['params']) for pid in fold]
    nms, recs = STAGES['newmaps'](ws, state['newmaps'], sup, prior, hints, progress) if state['newmaps'] else ([], {})
    for s in nms:
        stages.append(s)
        prior.append(s['zip'])
    try:
        ms = STAGES['missions'](ws, state['missions'], prior, hints, progress) if state['missions'].get('projects') else None
    except ValueError:
        if any(s['name'].startswith('newmap') for s in stages):
            raise ValueError('A new map and mission templates cannot be installed together yet: the map builder adds one map package '
                             'to the main game data per build. Remove the new map or the missions first.')
        raise
    if ms:
        stages.append(ms)
        prior.append(ms['zip'])
    return dict(stages=stages, newmaps=recs, superseded=sup, missions=ms)


def _write_pack(ws, stages, tmp):
    """One stage: a plain copy of its bytes. Several: merged, a later stage wins a block."""
    zips = [s['zip'] for s in stages]
    if len(zips) == 1:
        shutil.copy2(zips[0], tmp)
        owner = {n: 0 for n in _entries_of(zips[0])}
    else:
        owner = archives.merge_zips(tmp, zips, getattr(ws.game, 'naz', None))
    return {n: stages[i]['name'] for n, i in owner.items()}


# ------------------------------------------------------------------------------------------------ apply
CRASH_HOOK = None                # tests: called with the index of the write that just finished (0 pack, 1 configpc, 2 records)


def own_names_on_line(fs):
    return [a for a in fs if game.is_own_archive(a)]


def apply(ws, op, mods=KEEP, newmaps=KEEP, missions=KEEP, progress=None, hints=None):
    """Change the recorded inputs and rebuild the pack. mods: list of ids; newmaps: {id: record}; missions: the missions record
    ({'projects': ...}) or {}. -> dict(pack=<record>, installed=<the installed.json record>, warnings=[...], missions=<record>)."""
    from . import mods as M, saves, restore
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    journal.reconcile(folder)
    migrate(ws)
    cur = read_inputs(folder)
    new = dict(mods=cur['mods'] if mods is KEEP else list(mods), newmaps=cur['newmaps'] if newmaps is KEEP else dict(newmaps),
               missions=cur['missions'] if missions is KEEP else (missions or {}))
    new['alloc'] = mapalloc.assign(cur['alloc'], owners_of(new))
    gate = op.startswith('install')
    if gate:
        from . import problems
        problems.install_gate(ws, new)                  # a project with an error is refused before anything is touched
    if progress:
        progress('Saving a copy of your saves')
    snapshots.take(saves.saves_dir(), op)
    try:
        restore.make_backup(ws, op)
    except Exception:                                    # a backup that fails never blocks the install
        pass
    rec_paths = record_paths(folder)
    journal.begin(folder, op, journal.capture(folder, rec_paths))
    tmp_name = game.PACK_ZIP + '.part'
    tmp = os.path.join(folder, tmp_name)
    try:
        b = build(ws, new, progress, hints)
        stages = b['stages']
        # the missions record: what the build assigned
        mrec = {}
        if b['missions']:
            m = b['missions']
            res = m['meta']
            projects = {}
            for p_, s in m['ents']:
                types = {x['id']: x['type'] for x in s['project'].get('missions') or []}
                projects[p_] = dict(name=s['name'], project=s['project'], newmaps=s['newmaps'],
                                    indices={mid: [types[mid], idx] for mid, idx in res['index_of'].get(p_, {}).items()})
            mrec = dict(zip=game.PACK_ZIP, sha256=res['sha256'], projects=projects, migrate_entries=res['migrate_entries'],
                        thread_keys=res.get('thread_keys', []), missions=res['missions'],
                        taken_out_new_maps=sorted((set(cur['missions'].get('taken_out_new_maps', [])) | set(cur['newmaps'])) & set(b['superseded'])))
        fs = game.filesystem_line(game.read_configpc(folder)) or list(game.DEFAULT_FS)
        legacy = [a for a in fs if game.is_own_archive(a)] + [n for n in os.listdir(folder) if game.is_own_archive(n) and n.lower().endswith('.zip')]
        legacy = sorted({a for a in legacy if a.lower() != game.PACK_ZIP})
        owner = {}
        if stages:
            if progress:
                progress('Putting the pack together')
            owner = _write_pack(ws, stages, tmp)
        else:
            if os.path.exists(tmp):
                os.remove(tmp)
        loader = None
        if hasattr(ws.game, 'archive'):
            def loader(p):
                n = os.path.basename(p)
                if p.lower().endswith('.zip'):
                    return archives.zip_crcs(p)
                a = ws.game.archive(n)
                return {c: v[2].lower() for c, v in a.table.items()}
        if gate and stages:
            problems.install_gate(ws, {}, tmp)          # P8: the level data of the finished pack against the MAIN_ASSETS pool
        warns = archives.preflight(folder, fs, tmp if stages else None, game.PACK_ZIP, remove=legacy, loader=loader)
        # ---- the target state
        line_after = M.filesystem_text(folder, game.PACK_ZIP if stages else None, remove=[game.PACK_ZIP] + legacy)
        sig = ws.game.signature() if hasattr(ws.game, 'signature') else []
        pk = None
        if stages:
            pk = dict(format=1, zip=game.PACK_ZIP, sha256=journal.file_sha(tmp), bytes=os.path.getsize(tmp), built=_now(),
                      chain_signature=sig, stages=[s['name'] for s in stages], owner=owner, configpc_line=line_after['line'])
        inst_old = _read(installed_json()) or {}
        mods_meta = next((s['meta'] for s in stages if s['name'] == 'mods'), None)
        inst = dict(installed=_now() if mods_meta else None, mods=list(new['mods']) if mods_meta else [],
                    zip=os.path.join(folder, game.PACK_ZIP) if mods_meta else None,
                    configpc_line=line_after['line'] if mods_meta else None,
                    blocks=(mods_meta or {}).get('blocks', []), save_safe=(mods_meta or {}).get('save_safe', True),
                    tod_hd=ws.game.has_hd() if hasattr(ws.game, 'has_hd') else False, chain_signature=sig)
        recs = {installed_json(): inst, record_path(folder): pk,
                os.path.join(folder, NEWMAP_RECORD): (b['newmaps'] or None), os.path.join(folder, MISSIONS_RECORD): (mrec or None),
                mapalloc.path(folder): (new['alloc'] if new['alloc'].get('owners') else None)}
        target = dict(pack=game.PACK_ZIP, pack_tmp=tmp_name if stages else None, pack_sha256=pk['sha256'] if pk else None,
                      pack_bytes=pk['bytes'] if pk else None, configpc=base64.b64encode(line_after['text'].encode('latin-1')).decode(),
                      records=recs, remove=legacy)
        M.config_backups(folder)
        journal.commit(folder, target)
    except BaseException:
        journal.reconcile(folder)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    if progress:
        progress('Writing the game files')
    try:
        journal.perform(folder, target, CRASH_HOOK)
    except journal.SimulatedCrash:
        raise
    except BaseException:
        journal.reconcile(folder)
        raise
    journal.finish(folder)
    return dict(pack=pk, installed=inst, missions=mrec, warnings=warns, line=line_after['line'])


def rebuild(ws, progress=None):
    """The same inputs, built again on the game as it is now (after Gameplay+ or TOD HD changed)."""
    cur = read_inputs(ws.game.folder)
    return apply(ws, 'rebuild', mods=cur['mods'], newmaps=cur['newmaps'], missions=cur['missions'], progress=progress)


# ------------------------------------------------------------------------------------------------ staleness (K4)
def stale(ws):
    """-> dict(stale=False) or dict(stale=True, changed=[archive names]): the game's archives differ from what the pack was built on."""
    folder = ws.game.folder
    rec = read_record(folder)
    if not rec.get('sha256') or not rec.get('chain_signature'):
        return dict(stale=False)
    now = {a[0]: a[1:] for a in ws.game.signature()}
    then = {a[0]: a[1:] for a in rec['chain_signature']}
    changed = sorted(n for n in set(now) | set(then) if now.get(n) != then.get(n))
    if not os.path.exists(os.path.join(folder, game.PACK_ZIP)):
        return dict(stale=True, changed=[game.PACK_ZIP])
    return dict(stale=bool(changed), changed=changed)


# ------------------------------------------------------------------------------------------------ migration of the old three zips
def legacy_present(folder):
    return [n for n in os.listdir(folder) if game.is_own_archive(n) and n.lower().endswith('.zip') and n.lower() != game.PACK_ZIP]


def migrate(ws):
    """An install made before the pack (todms_mods.zip, todms_newmap_<id>.zip, todms_missions.zip): put the archives together as they
    were seen by the game (the first archive on the line wins a block) into the pack, keep the chain order, record the inputs.
    Nothing is rebuilt. -> dict(migrated=[names]) or None."""
    from . import newmap, mods as M
    folder = ws.game.folder
    old = legacy_present(folder)
    if not old or game.game_running(folder):
        return None
    journal.reconcile(folder)
    fs = game.filesystem_line(game.read_configpc(folder)) or []
    order = [a for a in fs if a in old] + [a for a in old if a not in fs]
    # the game searches the line from the front: an earlier archive hides a later one, so the merge lists them last-first
    merged_order = [os.path.join(folder, a) for a in reversed(order)]
    tmp_name = game.PACK_ZIP + '.part'
    tmp = os.path.join(folder, tmp_name)
    owner = archives.merge_zips(tmp, merged_order, getattr(ws.game, 'naz', None))
    rec_paths = record_paths(folder)
    journal.begin(folder, 'migrate', journal.capture(folder, rec_paths))
    try:
        warns = archives.preflight(folder, fs, tmp, game.PACK_ZIP, remove=old)
    except ValueError:
        os.remove(tmp)
        journal.finish(folder)
        raise
    inst = _read(installed_json()) or {}
    nm_old = _read(os.path.join(folder, NEWMAP_RECORD)) or {}
    nm_new = {}
    for pid, r in nm_old.items():
        params, verified = None, False
        try:
            params = newmap.get_project(pid)['params']
            verified = newmap.revision(params) == r.get('revision')
        except Exception:
            pass
        nm_new[pid] = dict(revision=r.get('revision'), params=params, unverified=not verified, name=(params or {}).get('package') or pid)
    ml = list(inst.get('mods') or []) if os.path.exists(os.path.join(folder, game.MOD_ZIP)) else []
    line = M.filesystem_text(folder, game.PACK_ZIP, remove=[game.PACK_ZIP] + old)
    sig = ws.game.signature() if hasattr(ws.game, 'signature') else []
    pk = dict(format=1, zip=game.PACK_ZIP, sha256=journal.file_sha(tmp), bytes=os.path.getsize(tmp), built=_now(), chain_signature=sig,
              stages=['migrated'], owner={n: 'migrated' for n in owner}, configpc_line=line['line'], migrated_from=order)
    inst2 = dict(inst, installed=inst.get('installed') or _now(), mods=ml, zip=os.path.join(folder, game.PACK_ZIP) if ml else None,
                 configpc_line=line['line'], chain_signature=sig)
    ms = _read(os.path.join(folder, MISSIONS_RECORD))
    if ms:
        ms = dict(ms, zip=game.PACK_ZIP, configpc_line=line['line'])
    recs = {installed_json(): inst2, record_path(folder): pk, os.path.join(folder, NEWMAP_RECORD): nm_new or None,
            os.path.join(folder, MISSIONS_RECORD): ms}
    target = dict(pack=game.PACK_ZIP, pack_tmp=tmp_name, pack_sha256=pk['sha256'], pack_bytes=pk['bytes'],
                  configpc=base64.b64encode(line['text'].encode('latin-1')).decode(), records=recs, remove=old)
    journal.commit(folder, target)
    journal.perform(folder, target, CRASH_HOOK)
    journal.finish(folder)
    return dict(migrated=order, warnings=warns)
