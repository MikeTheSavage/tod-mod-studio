"""The install journal (K12). An install or uninstall is several writes in the game folder: the pack archive, configpc.txt and our
records. Before anything is written an intent record, todms_install.json, is saved in the game folder. When the writes start it also
holds the finished target (pack hash, configpc.txt text, every record). The next start of the app reconciles: it finishes the
writes when the pack archive is already in place (or fully copied), and puts the old state back otherwise."""
import base64
import hashlib
import json
import os

NAME = 'todms_install.json'
FORMAT = 1


class SimulatedCrash(Exception):
    """Raised by a test hook between two writes."""


def path(folder):
    return os.path.join(folder, NAME)


def atomic_json(p, obj):
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(p + '.part', p)


def atomic_bytes(p, data):
    with open(p + '.part', 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(p + '.part', p)


def file_sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read(folder):
    try:
        with open(path(folder), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_json(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def capture(folder, record_paths):
    """The state a rollback puts back: the configpc.txt bytes and every record file (None = absent)."""
    cfg = os.path.join(folder, 'configpc.txt')
    raw = None
    if os.path.exists(cfg):
        with open(cfg, 'rb') as f:
            raw = base64.b64encode(f.read()).decode()
    return dict(configpc=raw,
                records={p: _read_json(p) for p in record_paths})


def begin(folder, op, previous):
    atomic_json(path(folder), dict(format=FORMAT, state='intent', op=op, previous=previous))


def commit(folder, target):
    """target: dict(pack=<name>, pack_tmp=<name or None>, pack_sha256=<hash or None>, pack_bytes, configpc=<bytes as base64>,
    records={path: json or None}, remove=[file names to delete])."""
    j = read(folder)
    j.update(state='writing', target=target)
    atomic_json(path(folder), j)


def finish(folder):
    try:
        os.remove(path(folder))
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ the writes
def perform(folder, target, hook=None):
    """The three writes, in order: the pack archive, configpc.txt, the records. Every step can run again (idempotent)."""
    pack = os.path.join(folder, target['pack'])
    tmp = os.path.join(folder, target['pack_tmp']) if target.get('pack_tmp') else None
    if tmp and os.path.exists(tmp):
        os.replace(tmp, pack)
    elif not target.get('pack_sha256') and os.path.exists(pack):
        os.remove(pack)
    if hook:
        hook(0)
    if target.get('configpc') is not None:
        atomic_bytes(os.path.join(folder, 'configpc.txt'), base64.b64decode(target['configpc']))
    if hook:
        hook(1)
    for p, content in target['records'].items():
        if content is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            atomic_json(p, content)
    for n in target.get('remove', []):
        q = os.path.join(folder, n)
        if os.path.exists(q) and os.path.isfile(q):
            os.remove(q)
    if hook:
        hook(2)


def rollback(folder, j):
    prev = j.get('previous') or {}
    tmp = (j.get('target') or {}).get('pack_tmp')
    if tmp and os.path.exists(os.path.join(folder, tmp)):
        os.remove(os.path.join(folder, tmp))
    if prev.get('configpc') is not None:
        atomic_bytes(os.path.join(folder, 'configpc.txt'), base64.b64decode(prev['configpc']))
    for p, content in (prev.get('records') or {}).items():
        if content is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            atomic_json(p, content)


def reconcile(folder):
    """Called at app start (and after a failed write). -> dict(action=...): none | discarded | rolled_forward | rolled_back."""
    j = read(folder)
    if not j:
        return dict(action='none')
    t = j.get('target')
    if j.get('state') != 'writing' or not t:
        for n in os.listdir(folder):
            if n.endswith('.part') and n.lower().startswith('todms_'):
                os.remove(os.path.join(folder, n))
        finish(folder)
        return dict(action='discarded', op=j.get('op'))
    pack = os.path.join(folder, t['pack'])
    tmp = os.path.join(folder, t['pack_tmp']) if t.get('pack_tmp') else None
    sha = t.get('pack_sha256')
    ok = False
    if sha:
        if os.path.exists(pack) and os.path.getsize(pack) == t.get('pack_bytes') and file_sha(pack) == sha:
            ok = True
        elif tmp and os.path.exists(tmp) and os.path.getsize(tmp) == t.get('pack_bytes') and file_sha(tmp) == sha:
            ok = True
    else:
        ok = not os.path.exists(pack)
    if ok:
        perform(folder, t)
        finish(folder)
        return dict(action='rolled_forward', op=j.get('op'))
    rollback(folder, j)
    finish(folder)
    return dict(action='rolled_back', op=j.get('op'))
