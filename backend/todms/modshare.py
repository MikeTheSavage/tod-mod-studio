"""Sharing: collections (.todcollection: mods plus their order, installed together) and single pieces (.todpiece: one prefab, one route set,
one tuning preset or one mission). A single mod is mods.export_mod / mods.import_mod. Every file goes through modfile's safety check first.
"""
import datetime
import json
import os
import re
import uuid

from . import compat, migrate, mods, modfile


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _write(path, obj):
    with open(path + '.part', 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(path + '.part', path)
    return path


# ------------------------------------------------------------------------------------------------ collections
def export_collection(ids, path, name, author='', description=''):
    """The listed mods, in the listed order, in one file. A mod whose author forbids sharing stops the export (plain message)."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError('Pick at least one mod.')
    shares = [mods.share_dict(i) for i in ids]
    obj = dict(format=modfile.FORMATS['collection'], schema=modfile.SCHEMA, name=str(name or 'My collection')[:80], author=str(author or '')[:80],
               description=str(description or '')[:1000], created=_now(), mods=shares, order=[m['id'] for m in shares],
               enabled=[m['id'] for m in shares])
    return _write(path, obj)


def import_collection(obj, notes=None, game=None):
    """Every mod of the collection goes into the library (a newer version of a mod you have updates it in place) and is switched on, in the
    collection's order after the mods you already have. -> dict(kind, name, mods=[{id, name, status}], unmet=[...])."""
    results = []
    for m in obj['mods']:
        m = dict(m)
        migrate.upgrade_object(m)
        try:
            r = mods.import_obj(m)
            results.append(dict(id=r['id'], name=r.get('name'), status=r['import']['status']))
        except ValueError as e:
            results.append(dict(id=m.get('id'), name=m.get('name'), status='skipped', reason=str(e)))
    o = mods.load_order()
    placed = [r['id'] for r in results if r['status'] in ('added', 'copy')]
    order = [i for i in o['order'] if i not in placed] + placed
    enabled = list(o['enabled'])
    for r in results:
        if r['status'] in ('added', 'copy') and r['id'] not in enabled:
            enabled.append(r['id'])
    mods.set_state(order, enabled)
    unmet = compat.check_requirements(mods.library(), [i for i in order if i in enabled], compat.environment(game))
    return dict(kind='collection', name=obj.get('name'), mods=results, unmet=unmet)


# ------------------------------------------------------------------------------------------------ pieces
def _piece(kind, name, data, author=''):
    return dict(format=modfile.FORMATS['piece'], schema=modfile.SCHEMA, kind=kind, name=str(name or kind)[:80], author=str(author or '')[:80],
                created=_now(), data=data)


def export_piece(kind, source, path, name=None, author=''):
    """kind: 'prefab' (source = prefab id), 'routes' (source = mod id), 'tuning' (source = {mod, editor?}), 'mission' (source = {project, mission})."""
    if kind == 'prefab':
        from . import userlib
        p = next((x for x in userlib.load()['prefabs'] if x.get('id') == source), None)
        if not p:
            raise ValueError('That prefab is not in your library.')
        return _write(path, _piece(kind, name or p.get('name'), dict(prefab=p), author))
    if kind == 'routes':
        m = _shareable(source)
        if not m.get('nav'):
            raise ValueError('This mod has no routes.')
        return _write(path, _piece(kind, name or '%s routes' % m.get('name'), dict(nav=m['nav']), author or m.get('author')))
    if kind == 'tuning':
        src = source if isinstance(source, dict) else dict(mod=source)
        m = _shareable(src['mod'])
        data = {k: v for k, v in (m.get('data') or {}).items() if v and (not src.get('editor') or k == src['editor'])}
        if not data:
            raise ValueError('This mod has no game data values.')
        return _write(path, _piece(kind, name or '%s tuning' % m.get('name'), dict(data=data), author or m.get('author')))
    if kind == 'mission':
        from . import missions_tpl
        pr = missions_tpl.get_project(source['project'])['project']
        ms = next((x for x in pr.get('missions') or [] if x.get('id') == source['mission']), None)
        if not ms:
            raise ValueError('That mission is not in the project.')
        host = next((h for h in pr.get('hosts') or [] if h.get('id') == ms.get('host')), None)
        return _write(path, _piece(kind, name or ms['id'], dict(mission=ms, host=host), author))
    raise ValueError('Unknown kind of piece.')


def _shareable(mid):
    m = mods.get_mod(mid)
    if m.get('origin') == 'imported' and not mods._reusable(m):
        raise PermissionError('The author does not allow "%s" to be shared again.' % (m.get('name') or mid))
    return m


def import_piece(obj):
    kind, data = obj['kind'], obj['data']
    name = obj.get('name') or kind
    if kind == 'prefab':
        from . import userlib
        p = data.get('prefab')
        if not isinstance(p, dict) or not isinstance(p.get('items'), list) or not p['items'] or len(p['items']) > 2000:
            raise ValueError('The prefab in this file is not in the expected form.')
        for it in p['items']:
            if not isinstance(it, dict) or not (isinstance(it.get('dpos'), list) and len(it['dpos']) == 3 and all(isinstance(x, (int, float)) for x in it['dpos'])):
                raise ValueError('The prefab in this file is not in the expected form.')
        lib = userlib.load()['prefabs']
        p = dict(p, name=str(p.get('name') or name)[:80])
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', str(p.get('id') or '')) or any(x.get('id') == p['id'] for x in lib):
            p['id'] = 'pf' + uuid.uuid4().hex[:8]
        userlib.save_key('prefabs', lib + [p])
        return dict(kind=kind, name=p['name'], id=p['id'])
    if kind in ('routes', 'tuning'):
        m = dict(format=mods.FORMAT, name=name, author=obj.get('author') or '', description='Piece: %s' % kind, level=[], data={}, view=None,
                 page=dict(version='1.0', reuse=True), schema=modfile.SCHEMA)
        if kind == 'routes':
            if not isinstance(data.get('nav'), list):
                raise ValueError('The route set in this file is not in the expected form.')
            m['nav'] = data['nav']
        else:
            if not isinstance(data.get('data'), dict):
                raise ValueError('The tuning in this file is not in the expected form.')
            m['data'] = data['data']
        from todct import todmod
        m['version'] = todmod.version_needed(m)
        r = mods.import_obj(m)
        return dict(kind=kind, name=r['name'], id=r['id'])
    if kind == 'mission':
        from . import missions_tpl
        ms, host = data.get('mission'), data.get('host')
        if not isinstance(ms, dict) or not isinstance(host, dict) or not ms.get('id'):
            raise ValueError('The mission in this file is not in the expected form.')
        project = dict(name=name, hosts=[host], missions=[dict(ms, host=host.get('id'))], options={})
        r = missions_tpl.save_project(project)
        return dict(kind=kind, name=name, id=r['id'])
    raise ValueError('Unknown kind of piece.')


# ------------------------------------------------------------------------------------------------ any file
def _import_parsed(kind, obj, notes, game, backup=None):
    if kind == 'mod':
        bak = backup
        if migrate.needs_upgrade(obj):
            bak = bak or migrate.backup_copy(obj=obj, label=str(obj.get('name') or 'mod'))
            notes = list(notes or []) + migrate.upgrade_object(obj)
        r = mods.import_obj(obj, notes)
        if bak:
            r['import']['backup'] = bak
        return dict(kind='mod', id=r['id'], name=r.get('name'), **r['import'], unmet=requirements_for(r['id'], game))
    if kind == 'collection':
        return import_collection(obj, notes, game)
    return import_piece(obj)


def import_any(path, game=None):
    """Check, upgrade if older (after a backup copy of the file), and add whatever kind of file this is. -> dict(kind, ...)"""
    kind, obj, notes = modfile.read(path)
    bak = migrate.backup_copy(src_path=path) if kind == 'mod' and migrate.needs_upgrade(obj) else None
    return _import_parsed(kind, obj, notes, game, bak)


def import_bytes(data, game=None):
    """The same for a file that was downloaded (nothing is written to disk before the check)."""
    kind, obj, notes = modfile.parse(data)
    return _import_parsed(kind, obj, notes, game)


def requirements_for(mid, game=None):
    """What a mod needs that is not met right now (as if it were switched on). Plain sentences."""
    lib = mods.library()
    return compat.check_requirements(lib, [mid] if mid in lib else [], compat.environment(game))
