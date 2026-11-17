"""Autosave and named snapshots of a project (a level mod, a mission project, a new-map project).

The stored project is the SAME JSON the project's own save writes (mod.json, mission project.json, new-map params.json): this module only
keeps extra copies of it in the user folder, so nothing new is invented for the data itself.

  <home>/autosave/<kind>/<key>.json          the last unsaved state, written a few seconds after each change
  <home>/project_snapshots/<kind>/<key>/<id>.json   named versions: {id, name, created, auto, project}

  kind   'level' | 'mission' | 'newmap'
  key    the project id; the working level mod without an id uses '_current'; a new, never saved mission or map project '_draft'
"""
import json
import os
import re
import time

from . import paths

KINDS = ('level', 'mission', 'newmap')
MAX_SNAPSHOTS = 30             # per project; the automatic ones (before a restore) go first when the folder is full
_seq = [0]


def _key(k):
    k = k or '_draft'
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', k):
        raise ValueError('invalid project id')
    return k


def _kind(kind):
    if kind not in KINDS:
        raise ValueError('unknown project kind')
    return kind


def _write(p, value):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(value, f, indent=1, allow_nan=False, default=str)
    os.replace(p + '.part', p)


def _read(p):
    with open(p, encoding='utf-8-sig') as f:
        return json.load(f)


# ------------------------------------------------------------------------------------------------ the saved project (the project's own file)
def saved_path(kind, key):
    """The file the project's own save writes, or None."""
    from . import mods, missions_tpl, newmap
    if kind == 'level':
        p = os.path.join(mods.lib_dir(), _key(key), 'mod.json')
    elif kind == 'mission':
        p = os.path.join(missions_tpl.directory(_key(key)), 'project.json')
    else:
        p = os.path.join(newmap.directory(_key(key)), 'params.json')
    return p if os.path.exists(p) else None


def saved_project(kind, key):
    p = saved_path(_kind(kind), key)
    return _read(p) if p else None


# ------------------------------------------------------------------------------------------------ autosave
def _auto_path(kind, key):
    return os.path.join(paths.user_dir(), 'autosave', _kind(kind), _key(key) + '.json')


def autosave(kind, key, project, now=None):
    """Keep the unsaved state. Cheap: one small file, replaced."""
    if not isinstance(project, (dict, list)):
        raise ValueError('nothing to keep')
    t = time.time() if now is None else now
    _write(_auto_path(kind, key), dict(saved_at=t, project=project))
    return dict(saved_at=t)


def autosaved(kind, key):
    """-> dict(saved_at, project, newer) or None. newer: the autosave is younger than the project's own saved file (or there is none),
    which is the case after a crash or a forced close with unsaved changes."""
    p = _auto_path(kind, key)
    if not os.path.exists(p):
        return None
    try:
        a = _read(p)
    except Exception:
        return None
    sp = saved_path(kind, key) if _key(key) not in ('_draft', '_current') else None
    a['newer'] = sp is None or a['saved_at'] > os.path.getmtime(sp) + 0.001
    return a


def clear_autosave(kind, key):
    p = _auto_path(kind, key)
    if os.path.exists(p):
        os.remove(p)
    return dict(ok=True)


# ------------------------------------------------------------------------------------------------ snapshots
def _dir(kind, key):
    return os.path.join(paths.user_dir(), 'project_snapshots', _kind(kind), _key(key))


def _new_id(now):
    _seq[0] += 1
    return '%s-%03d-%d' % (time.strftime('%Y%m%d-%H%M%S', time.localtime(now)), int((now % 1) * 1000), _seq[0])


def list_snapshots(kind, key):
    d = _dir(kind, key)
    out = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith('.json'):
                try:
                    j = _read(os.path.join(d, n))
                    out.append(dict(id=j['id'], name=j['name'], created=j['created'], auto=bool(j.get('auto')),
                                    size=os.path.getsize(os.path.join(d, n))))
                except Exception:
                    continue
    out.sort(key=lambda s: (s['created'], s['id']), reverse=True)
    return out


def _rotate(kind, key):
    """Keep at most MAX_SNAPSHOTS: drop the oldest automatic ones first, then the oldest of any."""
    d = _dir(kind, key)
    snaps = sorted(list_snapshots(kind, key), key=lambda s: (s['created'], s['id']))       # oldest first
    over = len(snaps) - MAX_SNAPSHOTS
    for s in [x for x in snaps if x['auto']] + [x for x in snaps if not x['auto']]:
        if over <= 0:
            break
        os.remove(os.path.join(d, s['id'] + '.json'))
        over -= 1


def snapshot(kind, key, name, project, auto=False, now=None):
    t = time.time() if now is None else now
    sid = _new_id(t)
    nm = (name or '').strip() or time.strftime('%d %b %H:%M', time.localtime(t))
    _write(os.path.join(_dir(kind, key), sid + '.json'), dict(id=sid, name=nm[:80], created=t, auto=auto, project=project))
    _rotate(kind, key)
    return dict(id=sid, name=nm[:80], created=t, auto=auto)


def get_snapshot(kind, key, sid):
    if not re.fullmatch(r'[0-9a-zA-Z_-]+', sid or ''):
        raise ValueError('invalid snapshot id')
    p = os.path.join(_dir(kind, key), sid + '.json')
    if not os.path.exists(p):
        raise ValueError('no such snapshot')
    return _read(p)


def delete_snapshot(kind, key, sid):
    if not re.fullmatch(r'[0-9a-zA-Z_-]+', sid or ''):
        raise ValueError('invalid snapshot id')
    p = os.path.join(_dir(kind, key), sid + '.json')
    if os.path.exists(p):
        os.remove(p)
    return dict(snapshots=list_snapshots(kind, key))


def restore(kind, key, sid, current=None, now=None):
    """Take a snapshot of the state you have now (the open project, or else the saved file), then hand back the chosen version.
    The caller loads it as an unsaved change: nothing is overwritten on disk here."""
    snap = get_snapshot(kind, key, sid)
    cur = current if current is not None else saved_project(kind, key)
    taken = None
    if cur is not None:
        taken = snapshot(kind, key, 'Before restoring "%s"' % snap['name'], cur, auto=True, now=now)
    return dict(project=snap['project'], name=snap['name'], taken=taken, snapshots=list_snapshots(kind, key))
