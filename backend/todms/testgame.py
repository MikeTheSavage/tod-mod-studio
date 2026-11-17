"""Test in game: a PRIVATE copy of the player's game, the open mod installed into it, a test save, the game launched from it.

The player's own game folder is never written. The test copy shares the big archives with it through hard links when both are on the
same drive (a few MB are real files: TOD.exe, configpc.txt and every small file, so a write in the copy cannot reach the original).
Across drives a full copy is needed and the caller must confirm it first.

Saves: TOD asks Windows for the Documents folder (SHGetFolderPathA, CSIDL_PERSONAL). When that folder is `%USERPROFILE%\\Documents` (the
default) the copy is started with USERPROFILE pointing into the test copy, so the game reads and writes ONLY the test copy's own
savegames. When Documents is redirected, the test save goes into the real save folder instead, between two save snapshots (snapshots.py),
and the snapshot is put back when the game exits.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from . import debuglog, game as gm, paths, saves, snapshots

MARKER = 'todms_test_copy.json'
PROFILE = 'todms_profile'
LOG_NAME = 'todms_test_log.txt'
LINK_EXT = ('.naz', '.zip')
LINK_MIN = 32 << 20
KEEP_RUNS = 10
SAVE_SUBDIR = os.path.join('Documents', 'Total Overdose', 'savegames')


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _atomic_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(p + '.part', p)


def _read_json(p, default=None):
    try:
        with open(p, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------------------------------------ which files are shared
def _skip(rel):
    """Files that never go into a test copy: our own archives and records, logs, dumps, leftovers of earlier runs, the profile folder."""
    n = rel.replace('\\', '/').lower().split('/')
    if PROFILE in n[:-1]:
        return True
    b = n[-1]
    if b.startswith('todms_') or b.endswith(('.todms_backup', '.todms_last', '.part', '.dmp', '.log')):
        return True
    return bool(re.match(r'^tod.*log.*\.(txt|log)$', b))


def _linkable(rel, size):
    b = rel.lower()
    return (b.endswith(LINK_EXT) or size >= LINK_MIN) and os.path.basename(b) != 'configpc.txt' and not gm.is_own_archive(os.path.basename(b))


def source_files(src):
    out = []
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn if d.lower() != PROFILE]
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, src)
            if _skip(rel):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((rel, p, st.st_size))
    return sorted(out)


def _first_existing(p):
    p = os.path.abspath(p)
    while p and not os.path.exists(p):
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    return p


def _writable(d):
    try:
        t = os.path.join(d, '.todms_probe_%s' % uuid.uuid4().hex[:6])
        with open(t, 'w') as f:
            f.write('x')
        os.remove(t)
        return True
    except OSError:
        return False


def default_dest(src):
    """Next to the game (same drive), or under the app's folder when that is not writable."""
    src = os.path.abspath(src).rstrip('\\/')
    base = os.path.basename(src) or 'game'
    sib = os.path.join(os.path.dirname(src), base + ' (test copy)')
    if _writable(os.path.dirname(src)):
        return sib
    return os.path.join(paths.user_dir(), 'test_games', base)


def _same_volume(a, b):
    try:
        return os.stat(_first_existing(a)).st_dev == os.stat(_first_existing(b)).st_dev
    except OSError:
        return False


def _can_link(src_file, dest):
    d = _first_existing(dest)
    probe = os.path.join(d, '.todms_link_%s' % uuid.uuid4().hex[:6])
    try:
        os.link(src_file, probe)
    except OSError:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return True


def plan(src, dest=None):
    """What a test copy would cost. needs_confirm: a full copy across drives (the caller must show `extra_bytes` and ask)."""
    dest = os.path.abspath(dest or default_dest(src))
    files = source_files(src)
    link_b = sum(s for r, p, s in files if _linkable(r, s))
    real_b = sum(s for r, p, s in files if not _linkable(r, s))
    first = next((p for r, p, s in files if _linkable(r, s)), None)
    linked = bool(first) and _same_volume(src, dest) and _can_link(first, dest)
    extra = real_b + (0 if linked else link_b)
    try:
        free = shutil.disk_usage(_first_existing(dest)).free
    except OSError:
        free = 0
    return dict(dest=dest, mode='linked' if linked else 'copied', real_bytes=real_b, link_bytes=link_b, total_bytes=real_b + link_b,
                extra_bytes=extra, free_bytes=free, enough=free > extra + (512 << 20), needs_confirm=not linked)


# ------------------------------------------------------------------------------------------------ the list of test copies
def installs_path():
    return os.path.join(paths.user_dir(), 'installs.json')


def load_installs():
    return _read_json(installs_path(), []) or []


def save_installs(lst):
    _atomic_json(installs_path(), lst)


def get_install(iid):
    for i in load_installs():
        if i['id'] == iid:
            return i
    return None


def list_installs():
    out = []
    for i in load_installs():
        ok = os.path.exists(os.path.join(i['folder'], MARKER))
        out.append(dict(i, exists=ok))
    return out


def _ensure(srcp, dstp, link):
    """Make dstp match srcp as a link or as a real copy. Never writes through a link: copies go to a new name, then replace."""
    os.makedirs(os.path.dirname(dstp), exist_ok=True)
    if link:
        try:
            if os.path.exists(dstp) and os.path.samefile(srcp, dstp):
                return
        except OSError:
            pass
        if os.path.lexists(dstp):
            os.remove(dstp)
        os.link(srcp, dstp)
        return
    if os.path.exists(dstp):
        a, b = os.stat(srcp), os.stat(dstp)
        if a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime) and b.st_nlink == 1:
            return
    shutil.copy2(srcp, dstp + '.part')
    os.replace(dstp + '.part', dstp)


def sync(src, dest, linked, progress=None):
    files = source_files(src)
    for i, (rel, p, size) in enumerate(files):
        if progress and i % 8 == 0:
            progress('Copying the game', done=i, total=len(files))
        if rel.lower() == 'configpc.txt':
            continue                                   # written by write_config
        _ensure(p, os.path.join(dest, rel), linked and _linkable(rel, size))


def make_copy(ws, dest=None, allow_full=False, progress=None):
    """Create (or refresh) the test copy of the open game. -> the install record, or dict(confirm=<plan>) when a full copy needs a yes."""
    src = ws.game.folder
    p = plan(src, dest)
    for i in load_installs():
        if os.path.normcase(os.path.abspath(i['folder'])) == os.path.normcase(p['dest']) and os.path.exists(os.path.join(i['folder'], MARKER)):
            rec = i
            break
        if i.get('source') == src and os.path.exists(os.path.join(i['folder'], MARKER)) and dest is None:
            rec = i
            p = plan(src, i['folder'])
            break
    else:
        rec = None
    if rec is None:
        d = p['dest']
        if os.path.normcase(d) == os.path.normcase(os.path.abspath(src)) or os.path.normcase(os.path.abspath(src)).startswith(os.path.normcase(d) + os.sep):
            raise ValueError('The test copy cannot be the game folder itself.')
        if os.path.exists(d) and os.listdir(d):
            raise ValueError('That folder is not empty: pick a new folder for the test copy.')
    if p['needs_confirm'] and not allow_full:
        return dict(confirm=p)
    if not p['enough']:
        raise ValueError('There is not enough free space for the test copy (%d MB needed).' % ((p['extra_bytes'] + (512 << 20)) >> 20))
    d = rec['folder'] if rec else p['dest']
    os.makedirs(d, exist_ok=True)
    sync(src, d, p['mode'] == 'linked', progress)
    if rec is None:
        rec = dict(id=uuid.uuid4().hex[:8], role='test', folder=d, source=src, created=_now())
    rec.update(mode=p['mode'], real_bytes=p['real_bytes'], link_bytes=p['link_bytes'], total_bytes=p['total_bytes'], synced=_now())
    _atomic_json(os.path.join(d, MARKER), dict(id=rec['id'], source=src, created=rec['created'], note='A private test copy made by TOD Mod Studio. Safe to delete.'))
    lst = [i for i in load_installs() if i['id'] != rec['id']] + [rec]
    save_installs(lst)
    return rec


def remove_install(iid, real_folder=None):
    """Delete a test copy. Only folders that carry our marker and are in the list; hard links are unlinked, the original files stay."""
    rec = get_install(iid)
    if not rec:
        raise ValueError('No such test copy.')
    d = rec['folder']
    if real_folder and os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(real_folder)):
        raise ValueError('That is your game folder.')
    cur = current()
    if cur and cur.get('install') == iid and cur.get('status') == 'running':
        raise ValueError('The test copy is in use: close the game first.')
    if os.path.isdir(d):
        if not os.path.exists(os.path.join(d, MARKER)):
            raise ValueError('That folder is not a test copy made here, so it is left alone.')
        if gm.game_running(d):
            raise ValueError('The game is running from that copy: close it first.')

        def _fix(fn, p, exc):
            try:
                os.chmod(p, 0o700)
                fn(p)
            except OSError:
                pass
        shutil.rmtree(d, onerror=_fix)
    save_installs([i for i in load_installs() if i['id'] != iid])
    return dict(removed=d)


# ------------------------------------------------------------------------------------------------ config of the copy
def write_config(src, dest, first, remove):
    """The copy's configpc.txt: the player's file, then the archive line with `first` (the test pack, or nothing) in front, and the engine log
    key (the player's own when the file already has one, e.g. TOD HD's). -> dict(log=<path>, line=<filesystem line>)."""
    from . import mods
    cfg = os.path.join(dest, 'configpc.txt')
    s = os.path.join(src, 'configpc.txt')
    if os.path.exists(s):
        shutil.copyfile(s, cfg + '.part')
    else:
        open(cfg + '.part', 'wb').close()
    os.replace(cfg + '.part', cfg)
    r = mods.filesystem_text(dest, first, remove=remove)
    text = r['text']
    lines = text.splitlines()
    val = debuglog.configured_log(lines)
    if not val:
        nl = '\r\n' if '\r\n' in text else '\n'
        text = text.rstrip('\r\n') + nl + 'logdumpfile = ' + LOG_NAME + nl
        val = LOG_NAME
    with open(cfg + '.part', 'wb') as f:
        f.write(text.encode('latin-1'))
    os.replace(cfg + '.part', cfg)
    return dict(log=debuglog.resolve(dest, val), line=r['line'], own_log=(val == LOG_NAME))


def log_path(folder):
    v = debuglog.configured_log(gm.read_configpc(folder))
    return debuglog.resolve(folder, v) if v else os.path.join(folder, LOG_NAME)


# ------------------------------------------------------------------------------------------------ install the open mod into the copy
def install_pack(ws, rec, mod=None, mod_ids=None, progress=None):
    """Build what the player would install (the enabled mods, the new maps and mission projects that are in the game, plus the open project)
    and put it into the TEST copy only. -> dict(stages, mods=[names], log, line)."""
    from . import archives, journal, mods as M, pack, problems
    d = rec['folder']
    src = ws.game.folder
    cur = pack.read_inputs(src)
    if mod_ids is None:
        o = M.load_order()
        mod_ids = [i for i in o['order'] if i in o['enabled']]
    ids = list(mod_ids)
    hints = {}
    names = []
    for i in ids:
        try:
            names.append(M.get_mod(i).get('name') or i)
        except Exception:
            names.append(i)
    has_project = bool(mod) and bool((mod.get('level') or mod.get('data') or mod.get('collision') or mod.get('nav') or mod.get('missions') or mod.get('sections')))
    if has_project:
        cid = mod.get('id') or 'open-project'
        if cid in ids:
            ids = [i for i in ids]
        else:
            ids.append(cid)
            names.append(mod.get('name') or 'Open mod')
        hints['mod_objects'] = {cid: dict(mod, id=cid)}
        problems.refuse_if(problems.live_errors('level', mod), 'The mod "%s" has a problem' % (mod.get('name') or 'Open mod'))
    state = dict(mods=ids, newmaps=cur['newmaps'], missions=cur['missions'])
    problems.install_gate(ws, dict(state, mods=[i for i in ids if i not in hints.get('mod_objects', {})]))
    if progress:
        progress('Building')
    b = pack.build(ws, state, progress, hints)
    stages = b['stages']
    tmp = os.path.join(d, gm.PACK_ZIP + '.part')
    if stages:
        pack._write_pack(ws, stages, tmp)
    elif os.path.exists(tmp):
        os.remove(tmp)
    fs = gm.filesystem_line(gm.read_configpc(src)) or list(gm.DEFAULT_FS)
    legacy = sorted({a for a in fs if gm.is_own_archive(a) and a.lower() != gm.PACK_ZIP})
    if stages:
        problems.install_gate(ws, {}, tmp)
        loader = None
        if hasattr(ws.game, 'archive'):
            def loader(p):
                n = os.path.basename(p)
                if p.lower().endswith('.zip'):
                    return archives.zip_crcs(p)
                a = ws.game.archive(n)
                return {c: v[2].lower() for c, v in a.table.items()}
        try:
            archives.preflight(src, fs, tmp, gm.PACK_ZIP, remove=legacy, loader=loader)
        except ValueError:
            os.remove(tmp)
            raise
    cfg = write_config(src, d, gm.PACK_ZIP if stages else None, [gm.PACK_ZIP] + legacy)
    final = os.path.join(d, gm.PACK_ZIP)
    if stages:
        if os.path.lexists(final):
            os.remove(final)
        os.replace(tmp, final)
    elif os.path.lexists(final):
        os.remove(final)
    for n in os.listdir(d):
        if gm.is_own_archive(n) and n.lower() != gm.PACK_ZIP and os.path.isfile(os.path.join(d, n)):
            os.remove(os.path.join(d, n))              # a record of an older install that was linked in
    info = dict(installed=_now(), mods=names, stages=[s['name'] for s in stages], pack=gm.PACK_ZIP if stages else None,
                sha256=journal.file_sha(final) if stages else None, line=cfg['line'], log=cfg['log'])
    _atomic_json(os.path.join(d, 'todms_test.json'), info)
    return info


# ------------------------------------------------------------------------------------------------ saves
def isolation_works():
    """True when the Documents folder comes from %USERPROFILE%, so a changed USERPROFILE moves the game's saves."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
            v, t = winreg.QueryValueEx(k, 'Personal')
        return t == winreg.REG_EXPAND_SZ and '%userprofile%' in v.lower()
    except Exception:
        return False


def profile_saves(rec):
    return os.path.join(rec['folder'], PROFILE, SAVE_SUBDIR)


def newest_slot(folder=None):
    folder = folder or saves.saves_dir()
    best = None
    if os.path.isdir(folder):
        for fn in os.listdir(folder):
            p = os.path.join(folder, fn)
            if fn.lower().startswith('slot') and fn.lower() != 'slot11' and os.path.getsize(p) == 0x50000:
                if best is None or os.path.getmtime(p) > os.path.getmtime(best):
                    best = p
    return best


def put_save(ws, rec, opts, isolated, progress=None):
    """Make the test save and put it where the game will look. -> dict(slot, mode, snapshot, notes, log).
    Isolated: a fresh profile inside the test copy holds the player's settings and the one test save (Slot00), nothing else."""
    real = saves.saves_dir()
    source = opts.get('source') or newest_slot(real)
    have = bool(opts.get('save', True)) and bool(source) and os.path.exists(source)
    out = dict(notes=[])
    made = None
    if have:
        made = saves.make(ws, source, pos=opts.get('pos'), yaw=opts.get('yaw'), heal=bool(opts.get('heal')), weapons=bool(opts.get('weapons')),
                          start_mission=None, name='TestRun_%s' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'),
                          god=bool(opts.get('god')), ammo=bool(opts.get('ammo')), unlock=opts.get('unlock'))
        out.update(made=made['path'], log=made['log'], notes=list(made.get('notes', [])), player=made.get('player'))
        if opts.get('start_mission') is not None:      # such a save stops the game on load (M0): never made for play
            out['notes'].append(saves.START_MISSION_NOTE)
    if isolated:
        d = profile_saves(rec)
        shutil.rmtree(os.path.join(rec['folder'], PROFILE), ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        if os.path.isdir(real):
            for fn in os.listdir(real):
                p = os.path.join(real, fn)
                low = fn.lower()
                if os.path.isfile(p) and (low == 'slot11' or (low.startswith('todgameplay') and low.endswith('.txt') and os.path.getsize(p) < 65536)):
                    shutil.copy2(p, os.path.join(d, fn))
        if made:
            shutil.copy2(made['path'], os.path.join(d, 'Slot00'))
        out.update(mode='isolated', slot='Slot00' if made else None, folder=d)
        return out
    if not made:
        return dict(skipped=True, note='No save to start from: the game opens at its menu.')
    # the shared folder: a snapshot before, the save in a free slot, the snapshot is put back when the game exits
    snap = snapshots.take(real, 'before a test run')
    free = next(('Slot%02d' % n for n in range(0, 11) if not os.path.exists(os.path.join(real, 'Slot%02d' % n))), None)
    slot = free or os.path.basename(source)
    r = saves.install(ws, made['path'], slot, real)
    out.update(mode='shared', slot=slot, folder=real, snapshot=(snap or {}).get('id'), backup=r.get('backup'))
    return out


# ------------------------------------------------------------------------------------------------ the run
_LOCK = threading.RLock()
_PROC = {}                         # run id -> Popen of the game WE started


def runs_dir():
    d = os.path.join(paths.user_dir(), 'test_runs')
    os.makedirs(d, exist_ok=True)
    return d


def state_path():
    return os.path.join(paths.user_dir(), 'testrun.json')


def current():
    return _read_json(state_path())


def _set(st):
    _atomic_json(state_path(), st)


def pid_alive(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.lower()
    except Exception:
        return False
    return '"tod.exe"' in out or '"totaloverdose.exe"' in out


def launch(ws, rec, put, keep=False, label=None, real=False, bisect=None):
    """Start the game from the test copy (or, for `real`, from the player's own folder). Refuses while any TOD.exe runs."""
    folder = ws.game.folder if real else rec['folder']
    if gm.game_running():
        raise RuntimeError('Total Overdose is running: close it first')
    exe = os.path.join(folder, 'TOD.exe')
    if not os.path.exists(exe):
        raise RuntimeError('TOD.exe is not in %s' % folder)
    env = dict(os.environ)
    isolated = bool(put) and put.get('mode') == 'isolated' and not real
    if isolated:
        env['USERPROFILE'] = os.path.join(rec['folder'], PROFILE)
    lp = log_path(folder)
    try:
        os.remove(lp)                                    # a fresh log for this run (the game starts one anyway)
    except OSError:
        pass
    proc = subprocess.Popen([exe], cwd=folder, env=env)
    rid = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    st = dict(id=rid, status='running', pid=proc.pid, started=_now(), folder=folder, install=None if real else rec['id'], real=real, log=lp,
              keep=bool(keep) or real, saves=put, label=label, bisect=bisect, exit_code=None)
    with _LOCK:
        _PROC[rid] = proc
        _set(st)
    threading.Thread(target=_watch, args=(rid, proc), daemon=True).start()
    return st


def _watch(rid, proc):
    code = proc.wait()
    finish(rid, code)


def finish(rid, code):
    """After the game exited: keep the log, summarise it, put the saves back, remove the test copy unless it is kept."""
    with _LOCK:
        st = current() or {}
        if st.get('id') != rid or st.get('status') != 'running':
            return st
        text = ''
        try:
            with open(st['log'], 'rb') as f:
                text = f.read().decode('latin-1')
        except OSError:
            pass
        rd = os.path.join(runs_dir(), rid)
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, 'engine.log'), 'w', encoding='latin-1', newline='') as f:
            f.write(text)
        st['ended'] = _now()
        st['exit_code'] = code
        st['summary'] = debuglog.summarize(text)
        st['crash'] = None if st.get('stopped') else (debuglog.crash_report(code, text) if text or code else None)
        st['log_kept'] = os.path.join(rd, 'engine.log')
        notes = []
        put = st.get('saves') or {}
        if put.get('mode') == 'shared' and put.get('snapshot'):
            try:
                snapshots.restore(put['snapshot'], put['folder'])
                notes.append('Your saves were put back as they were before the test.')
            except Exception as e:
                notes.append('Your saves could not be put back: %s' % e)
        if put.get('mode') == 'shared' and not put.get('snapshot') and put.get('slot'):
            p = os.path.join(put['folder'], put['slot'])
            if os.path.exists(p):
                os.remove(p)
        st['status'] = 'exited'
        _set(st)                                         # the copy may be removed now: nothing runs from it
        if st.get('install') and not st.get('keep'):
            try:
                remove_install(st['install'])
                st['install_removed'] = True
            except Exception as e:
                notes.append('The test copy could not be removed: %s' % e)
        st['notes'] = notes
        st['status'] = 'exited'
        _atomic_json(os.path.join(rd, 'run.json'), {k: v for k, v in st.items()})
        _set(st)
        _PROC.pop(rid, None)
        _trim_runs()
        return st


def _trim_runs():
    ds = sorted(d for d in os.listdir(runs_dir()) if os.path.isdir(os.path.join(runs_dir(), d)))
    for d in ds[:-KEEP_RUNS]:
        shutil.rmtree(os.path.join(runs_dir(), d), ignore_errors=True)


def reconcile():
    """At the start of the app: a run that was left 'running' (the app closed while the game ran) is finished now if the game is gone."""
    st = current()
    if st and st.get('status') == 'running' and st['id'] not in _PROC:
        if not pid_alive(st.get('pid')):
            finish(st['id'], None)
    return current()


def stop():
    """Close the game WE started (never another TOD.exe)."""
    st = current()
    if not st or st.get('status') != 'running':
        return dict(stopped=False)
    st['stopped'] = True                                 # closed from the app: not a crash
    _set(st)
    proc = _PROC.get(st['id'])
    if proc is not None:
        proc.terminate()
        return dict(stopped=True)
    if pid_alive(st.get('pid')):
        subprocess.run(['taskkill', '/PID', str(st['pid'])], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return dict(stopped=True)
    return dict(stopped=False)


def status(ws=None, light=False):
    st = reconcile() or {}
    out = dict(run={k: v for k, v in st.items() if k not in ('summary',)} if st else None,
               installs=list_installs(), isolation=isolation_works(), running=bool(st and st.get('status') == 'running'))
    if st and st.get('status') == 'exited':
        out['summary'] = st.get('summary')
    if ws is not None and ws.game and not light:
        out['plan'] = plan(ws.game.folder)
        out['slots'] = saves.list_slots(ws)['slots']
    return out


def live_log(offset=0):
    st = current()
    if not st:
        return dict(text='', offset=0, size=0, running=False)
    if st.get('status') == 'exited' and st.get('log_kept'):
        r = debuglog.read_chunk(st['log_kept'], offset)
    else:
        r = debuglog.read_chunk(st['log'], offset)
    r['running'] = st.get('status') == 'running'
    return r
