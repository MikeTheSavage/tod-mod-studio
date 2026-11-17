"""Save snapshots: the whole saves folder (about 3.6 MB: 11 slots plus Gameplay+ sidecar files) is copied before every install and
uninstall and before a restore. The last 20 are kept. A snapshot is a plain folder copy under <TODMS_HOME>/save_snapshots."""
import datetime
import hashlib
import json
import os
import shutil

from . import paths

KEEP = 20


def root():
    d = os.path.join(paths.user_dir(), 'save_snapshots')
    os.makedirs(d, exist_ok=True)
    return d


def _files(folder):
    out = []
    for dp, _dn, fn in os.walk(folder):
        for f in fn:
            p = os.path.join(dp, f)
            out.append((os.path.relpath(p, folder).replace(os.sep, '/'), p))
    return sorted(out)


def _digest(folder):
    h = hashlib.sha256()
    n = 0
    for rel, p in _files(folder):
        h.update(rel.encode())
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        n += os.path.getsize(p)
    return h.hexdigest(), n


def list_snapshots():
    out = []
    for d in sorted(os.listdir(root()), reverse=True):
        mf = os.path.join(root(), d, 'snapshot.json')
        if os.path.isfile(mf):
            try:
                with open(mf, encoding='utf-8') as f:
                    m = json.load(f)
            except Exception:
                continue
            out.append(dict(id=d, label=m.get('label'), created=m.get('created'), files=len(m.get('files', [])), bytes=m.get('bytes', 0)))
    return out


def take(folder, label):
    """Copy the saves folder. Returns the snapshot record, None when there is no saves folder. A folder identical to the newest
    snapshot is not copied again."""
    if not folder or not os.path.isdir(folder):
        return None
    dig, nbytes = _digest(folder)
    snaps = list_snapshots()
    if snaps:
        with open(os.path.join(root(), snaps[0]['id'], 'snapshot.json'), encoding='utf-8') as f:
            m = json.load(f)
        if m.get('digest') == dig:
            return dict(snaps[0], reused=True)
    sid = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    d = os.path.join(root(), sid)
    os.makedirs(os.path.join(d, 'saves'))
    files = []
    for rel, p in _files(folder):
        dst = os.path.join(d, 'saves', rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(p, dst)
        files.append(dict(name=rel, bytes=os.path.getsize(p)))
    mf = dict(label=label, created=datetime.datetime.now().isoformat(timespec='seconds'), source=folder, digest=dig, bytes=nbytes, files=files)
    with open(os.path.join(d, 'snapshot.json'), 'w', encoding='utf-8') as f:
        json.dump(mf, f, indent=1)
    rotate()
    return dict(id=sid, label=label, created=mf['created'], files=len(files), bytes=nbytes)


def rotate(keep=KEEP):
    snaps = list_snapshots()
    for s in snaps[keep:]:
        shutil.rmtree(os.path.join(root(), s['id']), ignore_errors=True)


def restore(sid, folder):
    """Put a snapshot back. A snapshot of the current folder is taken first. Files are replaced whole (never edited in place);
    files that were not in the snapshot are removed."""
    src = os.path.join(root(), os.path.basename(sid), 'saves')
    if not os.path.isdir(src):
        raise ValueError('That snapshot is gone.')
    before = take(folder, 'before restoring ' + sid)
    os.makedirs(folder, exist_ok=True)
    want = {rel for rel, _p in _files(src)}
    for rel, p in _files(src):
        dst = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(p, dst + '.part')
        os.replace(dst + '.part', dst)
    removed = []
    for rel, p in _files(folder):
        if rel not in want and not rel.endswith('.part'):
            os.remove(p)
            removed.append(rel)
    return dict(restored=sid, files=len(want), removed=removed, backup=before)
