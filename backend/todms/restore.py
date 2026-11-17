"""Restore to vanilla, verify the game files, and the backup manager.

A backup (restore point) is taken before every install and uninstall and before a restore: configpc.txt and the recorded inputs of
the pack (mod ids, new maps with their settings, mission projects). The archives are not copied (they are rebuilt from the inputs).
"""
import datetime
import hashlib
import json
import os
import shutil

from . import game, journal, paths

KEEP = 20
# What a clean GOG install is known to hold. Everything else is recorded the first time it is checked.
KNOWN = {'blocks.naz': dict(sha256='58a9339bbad317d1daa2af663869aeeeb8c4ad31530d690680f2118e3556d107'),
         'TOD.exe': dict(md5=game.GOG_EXE_MD5)}


def root():
    d = os.path.join(paths.user_dir(), 'backups')
    os.makedirs(d, exist_ok=True)
    return d


def _stamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')


def _dir_bytes(d):
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _n, fn in os.walk(d) for f in fn)


# ------------------------------------------------------------------------------------------------ backups
def make_backup(ws, label):
    from . import pack
    folder = ws.game.folder
    sid = _stamp()
    d = os.path.join(root(), sid)
    os.makedirs(d)
    cfg = os.path.join(folder, 'configpc.txt')
    if os.path.exists(cfg):
        shutil.copy2(cfg, os.path.join(d, 'configpc.txt'))
    journal.atomic_json(os.path.join(d, 'inputs.json'), pack.read_inputs(folder))
    journal.atomic_json(os.path.join(d, 'backup.json'), dict(label=label, created=datetime.datetime.now().isoformat(timespec='seconds'),
                                                            folder=folder))
    for old in sorted(os.listdir(root()), reverse=True)[KEEP:]:
        shutil.rmtree(os.path.join(root(), old), ignore_errors=True)
    return sid


def list_backups(ws):
    out = []
    folder = ws.game.folder
    for sid in sorted(os.listdir(root()), reverse=True):
        mf = os.path.join(root(), sid, 'backup.json')
        if not os.path.isfile(mf):
            continue
        try:
            with open(mf, encoding='utf-8') as f:
                m = json.load(f)
        except Exception:
            continue
        if m.get('folder') and os.path.normcase(m['folder']) != os.path.normcase(folder):
            continue
        out.append(dict(id=sid, kind='restore point', label=m.get('label'), created=m.get('created'), bytes=_dir_bytes(os.path.join(root(), sid))))
    for n, label in (('configpc.txt.todms_backup', 'configpc.txt before Mod Studio'), ('configpc.txt.todms_last', 'configpc.txt before the last change')):
        p = os.path.join(folder, n)
        if os.path.exists(p):
            out.append(dict(id='file:' + n, kind='file', label=label,
                            created=datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec='seconds'), bytes=os.path.getsize(p)))
    return out


def restore_backup(ws, bid, progress=None):
    from . import pack
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    if bid.startswith('file:'):
        n = os.path.basename(bid[5:])
        src = os.path.join(folder, n)
        if not n.startswith('configpc.txt.todms_') or not os.path.exists(src):
            raise ValueError('That backup is gone.')
        dst = os.path.join(folder, 'configpc.txt')
        if os.path.exists(dst):
            shutil.copy2(dst, dst + '.todms_last')
        shutil.copy2(src, dst + '.part')
        os.replace(dst + '.part', dst)
        return dict(restored=n)
    d = os.path.join(root(), os.path.basename(bid))
    if not os.path.isdir(d):
        raise ValueError('That backup is gone.')
    with open(os.path.join(d, 'inputs.json'), encoding='utf-8') as f:
        inp = json.load(f)
    r = pack.apply(ws, 'restore a backup', mods=inp.get('mods') or [], newmaps=inp.get('newmaps') or {}, missions=inp.get('missions') or {},
                   progress=progress)
    return dict(restored=bid, line=r['line'])


def delete_backups(ws, ids):
    n = 0
    folder = ws.game.folder
    for bid in ids:
        if bid.startswith('file:'):
            p = os.path.join(folder, os.path.basename(bid[5:]))
            if os.path.basename(p).startswith('configpc.txt.todms_') and os.path.exists(p):
                os.remove(p)
                n += 1
        else:
            d = os.path.join(root(), os.path.basename(bid))
            if os.path.isdir(d):
                shutil.rmtree(d)
                n += 1
    return dict(deleted=n)


# ------------------------------------------------------------------------------------------------ restore to vanilla
def restore_vanilla(ws, progress=None):
    """Every Mod Studio archive and config entry out of the game. configpc.txt keeps every other line (and every other archive).
    A backup is taken first (pack.apply does it). The mod library and the projects stay in the app."""
    from . import pack
    r = pack.apply(ws, 'restore to vanilla', mods=[], newmaps={}, missions={}, progress=progress)
    folder = ws.game.folder
    left = [n for n in os.listdir(folder) if game.is_own_archive(n)]
    return dict(line=r['line'], left=left)


# ------------------------------------------------------------------------------------------------ verify
def _clean_file():
    return os.path.join(paths.user_dir(), 'verified_clean.json')


def _hashes(p, want_md5=False):
    s, m = hashlib.sha256(), hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(4 << 20), b''):
            s.update(chunk)
            if want_md5:
                m.update(chunk)
    return s.hexdigest(), (m.hexdigest() if want_md5 else None)


def verify(ws, progress=None):
    """Hash the GOG archives and TOD.exe against the known-clean list. A file that is not on the list yet is recorded as clean the first
    time (its size and hash). -> dict(files=[{name, status: ok | recorded | changed | missing, size, backup}])."""
    folder = ws.game.folder
    try:
        with open(_clean_file(), encoding='utf-8') as f:
            allc = json.load(f)
    except Exception:
        allc = {}
    key = os.path.normcase(os.path.abspath(folder))
    clean = allc.setdefault(key, {})
    out = []
    names = list(game.GOG_ARCHIVES) + ['TOD.exe']
    for i, n in enumerate(names):
        if progress:
            progress('Checking %s' % n, i, len(names))
        p = os.path.join(folder, n)
        if not os.path.exists(p):
            out.append(dict(name=n, status='missing', size=None, backup=False))
            continue
        sha, md5 = _hashes(p, want_md5=n in KNOWN and 'md5' in KNOWN[n])
        want = clean.get(n) or {}
        known = KNOWN.get(n, {})
        status = 'ok'
        if known.get('sha256'):
            status = 'ok' if sha == known['sha256'] else 'changed'
        elif known.get('md5'):
            status = 'ok' if md5 == known['md5'] else 'changed'
        elif want.get('sha256'):
            status = 'ok' if sha == want['sha256'] else 'changed'
        else:
            clean[n] = dict(size=os.path.getsize(p), sha256=sha)
            status = 'recorded'
        bak = p + '.todms_backup'
        has_bak = False
        if status == 'changed' and os.path.exists(bak):
            ref = known.get('sha256') or want.get('sha256')
            has_bak = bool(ref) and _hashes(bak)[0] == ref
        out.append(dict(name=n, status=status, size=os.path.getsize(p), backup=has_bak))
    journal.atomic_json(_clean_file(), allc)
    return dict(files=out, ok=all(f['status'] in ('ok', 'recorded', 'missing') for f in out))


def repair(ws, names, progress=None):
    """Put a changed file back from its .todms_backup (only when the backup is the known-clean file)."""
    folder = ws.game.folder
    if game.game_running(folder):
        raise RuntimeError('Total Overdose is running: close it first')
    rep = {f['name']: f for f in verify(ws, progress)['files']}
    done = []
    for n in names:
        f = rep.get(n)
        if not f or f['status'] != 'changed' or not f['backup']:
            continue
        p = os.path.join(folder, n)
        shutil.copy2(p + '.todms_backup', p + '.part')
        os.replace(p + '.part', p)
        done.append(n)
    return dict(restored=done)
