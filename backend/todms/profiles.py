"""Mod profiles: named sets of switched-on mods with their load order ("vanilla plus", "experimental").

The ACTIVE profile is the live state in mods/order.json (what the Mods screen edits and the install reads); every change to it is mirrored
into the profile's own entry, so switching back finds the list as it was left. Switching a profile saves a copy of the saves folder
first (snapshots.py, labelled with the profile), then rebuilds the pack from the new list; the built stage is cached by its inputs,
so going back to a list that was built before is quick.
"""
import json
import os

from . import mods, snapshots

FILE = 'profiles.json'
DEFAULT = 'Main'


def _path():
    return os.path.join(mods.lib_dir(), FILE)


def _read():
    try:
        with open(_path(), encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d.get('profiles'), dict) and d['profiles']:
            return d
    except (OSError, ValueError):
        pass
    o = mods.load_order()
    return dict(active=DEFAULT, profiles={DEFAULT: dict(order=list(o['order']), enabled=list(o['enabled']))})


def _write(d):
    p = _path()
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=1)
    os.replace(p + '.part', p)


def sync(order_state):
    """Called whenever the live list changes: mirror it into the active profile."""
    d = _read()
    d['profiles'].setdefault(d['active'], {})
    d['profiles'][d['active']].update(order=list(order_state['order']), enabled=list(order_state['enabled']))
    _write(d)


def listing():
    d = _read()
    lib = {m['id']: m for m in mods.list_mods()}
    out = []
    for name, p in d['profiles'].items():
        en = [i for i in p.get('enabled', []) if i in lib]
        out.append(dict(name=name, active=name == d['active'], enabled=len(en), mods=[lib[i]['name'] for i in p.get('order', []) if i in en],
                        saves=p.get('saves')))
    return dict(active=d['active'], profiles=out)


def _name(n):
    n = ' '.join(str(n or '').split())[:40]
    if not n:
        raise ValueError('Give the profile a name.')
    return n


def create(name, copy=True):
    d = _read()
    name = _name(name)
    if name in d['profiles']:
        raise ValueError('There is already a profile called "%s".' % name)
    o = mods.load_order()
    d['profiles'][name] = dict(order=list(o['order']) if copy else list(o['order']), enabled=list(o['enabled']) if copy else [])
    _write(d)
    return listing()


def rename(old, new):
    d = _read()
    new = _name(new)
    if old not in d['profiles']:
        raise ValueError('No such profile.')
    if new != old and new in d['profiles']:
        raise ValueError('There is already a profile called "%s".' % new)
    d['profiles'] = {(new if k == old else k): v for k, v in d['profiles'].items()}
    if d['active'] == old:
        d['active'] = new
    _write(d)
    return listing()


def delete(name):
    d = _read()
    if name == d['active']:
        raise ValueError('Switch to another profile before deleting this one.')
    if name not in d['profiles']:
        raise ValueError('No such profile.')
    d['profiles'].pop(name)
    _write(d)
    return listing()


def switch(ws, name, progress=None, rebuild=True):
    """Make `name` the live list and rebuild the pack from it. -> dict(active, installed, snapshot)."""
    d = _read()
    if name not in d['profiles']:
        raise ValueError('No such profile.')
    cur = mods.load_order()
    d['profiles'][d['active']].update(order=list(cur['order']), enabled=list(cur['enabled']))
    snap = None
    if rebuild and ws is not None and ws.game is not None:
        from . import game, saves
        if game.game_running(ws.game.folder):
            raise RuntimeError('Total Overdose is running: close it first')
        if progress:
            progress('Saving a copy of your saves')
        snap = snapshots.take(saves.saves_dir(), 'before profile %s' % name)
        d['profiles'][d['active']]['saves'] = (snap or {}).get('id')
    lib = {m['id'] for m in mods.list_mods()}
    p = d['profiles'][name]
    order = [i for i in p.get('order', []) if i in lib] + sorted(i for i in lib if i not in p.get('order', []))
    enabled = [i for i in p.get('enabled', []) if i in lib]
    old_active = d['active']
    d['active'] = name
    d['profiles'][name].update(order=order, enabled=enabled)
    _write(d)
    mods.set_state(order, enabled)             # mirrors into the (new) active profile
    installed = None
    if rebuild and ws is not None and ws.game is not None:
        try:
            installed = mods.install(ws, progress, label='install profile %s' % name)
        except BaseException:
            d = _read()                         # the switch is undone when the rebuild is refused (for example a missing need)
            d['active'] = old_active
            _write(d)
            o = d['profiles'][old_active]
            mods.set_state(o.get('order', []), o.get('enabled', []))
            raise
    return dict(active=name, installed=installed, snapshot=snap)
