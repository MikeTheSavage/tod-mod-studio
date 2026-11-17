"""Mod library, sharing and installation.

A mod is a recipe, never game data: mod.json holds the level edits and data-editor values. Building it reads the
player's own blocks (TOD HD's when installed) and writes one override zip. Sharing exports the recipe as a .todmod
file (JSON); the receiver's app rebuilds it from their own game.

Install: every enabled mod, in list order, is built as the first stage of the pack, todms_pack.zip (pack.py), listed first on
configpc.txt's "filesystem =" line (ahead of TOD HD's zips when present). configpc.txt is backed up before the first
change; blocks.naz and every other game file are never written.
"""
import datetime
import json
import os
import re
import shutil
import uuid

from . import compat, migrate, modfile, paths
from .game import MOD_ZIP, PACK_ZIP, DEFAULT_FS, read_configpc, filesystem_line, game_running

FORMAT = 'todms-mod'


def _version(m):
    """Recipe version (todct.todmod): 4 with models or textures, 3 with route/mission/section ops, 2 with collision sets, else 1."""
    from todct import todmod
    return todmod.version_needed(m)


def lib_dir():
    d = os.path.join(paths.user_dir(), 'mods')
    os.makedirs(d, exist_ok=True)
    return d


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _order_file():
    return os.path.join(lib_dir(), 'order.json')


def load_order():
    try:
        with open(_order_file(), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return dict(order=[], enabled=[])


def save_order(o):
    with open(_order_file(), 'w', encoding='utf-8') as f:
        json.dump(o, f, indent=1)
    try:
        from . import profiles
        profiles.sync(o)                       # the active profile follows the live list
    except Exception:
        pass


_UPGRADED = set()


def _upgrade_once():
    d = lib_dir()
    if d not in _UPGRADED:
        _UPGRADED.add(d)
        try:
            migrate.upgrade_library()
        except Exception:
            pass


def list_mods():
    _upgrade_once()
    o = load_order()
    mods = {}
    for d in os.listdir(lib_dir()):
        p = os.path.join(lib_dir(), d, 'mod.json')
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as f:
                    m = json.load(f)
                mods[m['id']] = m
            except Exception:
                continue
    order = [i for i in o['order'] if i in mods] + sorted(i for i in mods if i not in o['order'])
    out = []
    for i in order:
        m = mods[i]
        out.append(dict(id=i, name=m.get('name'), author=m.get('author'), description=m.get('description'),
                        updated=m.get('updated'), enabled=i in o['enabled'], level_ops=len(m.get('level') or []),
                        data_values=sum(len(v) for v in (m.get('data') or {}).values()), view=m.get('view'),
                        collision_sets=len(m.get('collision') or []),
                        nav_ops=len(m.get('nav') or []), mission_ops=len(m.get('missions') or []),
                        section_ops=len(m.get('sections') or []), models=len(m.get('models') or []),
                        textures=len(m.get('textures') or []), version=compat.mod_version(m),
                        requires=compat.normalise_requires(m.get('requires')), imported=m.get('origin') == 'imported',
                        reuse=_reusable(m), shots=len((m.get('page') or {}).get('screenshots') or [])))
    return out


def _reusable(m):
    return (m.get('page') or {}).get('reuse') is not False


def get_mod(mid, for_edit=False):
    _safe_id(mid)
    with open(os.path.join(lib_dir(), mid, 'mod.json'), encoding='utf-8') as f:
        m = json.load(f)
    if migrate.needs_upgrade(m):
        try:
            migrate.upgrade_mod(mid)
            with open(os.path.join(lib_dir(), mid, 'mod.json'), encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, ValueError):
            pass
    if for_edit and m.get('origin') == 'imported' and not _reusable(m):
        raise PermissionError('The author does not allow others to edit "%s". You can still switch it on and off and put it in your game.'
                              % (m.get('name') or mid))
    return m


def _safe_id(mid):
    if not modfile.ID_RE.match(str(mid or '')):
        raise ValueError('not a mod id')
    return mid


def library():
    """{id: recipe} of every mod in the library."""
    out = {}
    for d in os.listdir(lib_dir()):
        if os.path.isfile(os.path.join(lib_dir(), d, 'mod.json')):
            try:
                out[d] = get_mod(d)
            except (OSError, ValueError):
                continue
    return out


def save_mod(m):
    from todct import todmod, assetops
    todmod.legacy_keys(m)
    try:
        assetops.validate_models(m.get('models'))
        assetops.validate_textures(m.get('textures'))
    except assetops.AssetOpError as e:
        raise ValueError(str(e))
    _normalise_page(m)
    if not m.get('id'):
        base = re.sub(r'[^a-z0-9]+', '-', (m.get('name') or 'mod').lower()).strip('-')[:40] or 'mod'
        m['id'] = '%s-%s' % (base, uuid.uuid4().hex[:6])
        m['created'] = _now()
    _safe_id(m['id'])
    m['format'] = FORMAT
    m['schema'] = migrate.CURRENT
    m['version'] = _version(m)
    m['updated'] = _now()
    d = os.path.join(lib_dir(), m['id'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'mod.json')
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(m, f, indent=1)
    os.replace(p + '.part', p)
    o = load_order()
    if m['id'] not in o['order']:
        o['order'].append(m['id'])
        save_order(o)
    return m


def _normalise_page(m):
    """The mod page and the requirements: shapes and limits (screenshots at most 6, each small), nothing else changes."""
    page = m.get('page')
    if page is None:
        page = m['page'] = {}
    if not isinstance(page, dict):
        raise ValueError('The mod page is not in the expected form.')
    page['version'] = str(page.get('version') or '1.0').strip()[:24] or '1.0'
    if not re.fullmatch(r'\d+(\.\d+){0,3}([-+][0-9A-Za-z.-]+)?', page['version']):
        raise ValueError('The version must be numbers separated by dots, for example 1.2.')
    page['reuse'] = page.get('reuse') is not False
    for k in ('credits', 'license'):
        if k in page:
            page[k] = str(page[k] or '')[:2000]
    page['changelog'] = [dict(version=str(c.get('version') or '')[:24], date=str(c.get('date') or '')[:24], text=str(c.get('text') or '')[:4000])
                         for c in (page.get('changelog') or []) if isinstance(c, dict)][:100]
    page['screenshots'] = [dict(name=str(x.get('name') or 'shot')[:60], data=x.get('data') or '', caption=str(x.get('caption') or '')[:120])
                           for x in (page.get('screenshots') or []) if isinstance(x, dict)][:modfile.MAX_SHOTS]
    page.pop('summary', None)
    problems = []
    modfile._check_page(page, problems)
    if problems:
        raise ValueError(problems[0])
    m['requires'] = compat.normalise_requires(m.get('requires'))


def delete_mod(mid):
    _safe_id(mid)
    shutil.rmtree(os.path.join(lib_dir(), mid), ignore_errors=True)
    o = load_order()
    o['order'] = [i for i in o['order'] if i != mid]
    o['enabled'] = [i for i in o['enabled'] if i != mid]
    save_order(o)


def set_state(order=None, enabled=None):
    o = load_order()
    if order is not None:
        o['order'] = list(order)
    if enabled is not None:
        o['enabled'] = list(enabled)
    save_order(o)
    return o


def share_dict(mid):
    """The recipe of one library mod as it travels: no build leftovers, the files it uses embedded."""
    from . import assetstore
    m = get_mod(mid)
    if m.get('origin') == 'imported' and not _reusable(m):
        raise PermissionError('The author does not allow "%s" to be shared again.' % (m.get('name') or mid))
    share = {k: v for k, v in m.items() if k not in ('built',)}
    blobs = assetstore.embed(m)
    if blobs:
        share['blobs'] = blobs
    return share


def export_mod(mid, path):
    share = share_dict(mid)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(share, f, indent=1)
    return path


def _same_content(a, b):
    skip = ('updated', 'created', 'blobs', 'origin', 'built', 'view', 'id')
    f = lambda m: json.dumps({k: v for k, v in m.items() if k not in skip}, sort_keys=True, default=str)
    return f(a) == f(b)


def import_obj(m, notes=None):
    """Add a checked recipe to the library. The same id with a newer version updates that mod in place (its place in the load order
    and its on/off state stay); the same version is "already there"; an older version is refused. -> the mod, plus `import`."""
    from todct import todmod
    from . import assetstore
    todmod.legacy_keys(m)
    migrate.upgrade_object(m)
    todmod.validate(m)
    assetstore.unpack(m.pop('blobs', None))
    m.pop('built', None)
    mid = m.get('id')
    info = dict(status='added', notes=list(notes or []))
    have = None
    if mid:
        try:
            have = get_mod(mid)
        except (OSError, ValueError):
            have = None
    if have:
        c = compat.vcmp(compat.mod_version(m), compat.mod_version(have))
        info['from_version'] = compat.mod_version(have)
        if c > 0:
            _keep_history(mid)
            m['created'] = have.get('created') or m.get('created')
            info['status'] = 'updated'
        elif c == 0 and _same_content(m, have):
            return dict(have, **{'import': dict(info, status='same')})
        elif c < 0:
            raise ValueError('You already have a newer version of "%s" (%s). This file is %s.'
                             % (have.get('name') or mid, compat.mod_version(have), compat.mod_version(m)))
        else:
            m['id'] = None
            m['name'] = '%s (copy)' % (m.get('name') or 'mod')
            info['status'] = 'copy'
    m['origin'] = 'imported'
    out = save_mod(m)
    out['import'] = info
    return out


def _keep_history(mid, keep=30):
    """The old mod.json before an update, so a bad update can be put back by hand."""
    d = os.path.join(lib_dir(), mid, 'history')
    os.makedirs(d, exist_ok=True)
    src = os.path.join(lib_dir(), mid, 'mod.json')
    if os.path.exists(src):
        try:
            with open(src, encoding='utf-8') as f:
                ver = compat.mod_version(json.load(f))
        except Exception:
            ver = 'x'
        shutil.copy2(src, os.path.join(d, '%s_v%s.json' % (datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'), re.sub(r'[^0-9A-Za-z.-]', '', ver))))
    for old in sorted(os.listdir(d))[:-keep]:
        os.remove(os.path.join(d, old))


def import_mod(path):
    """A .todmod (or a .todcollection / .todpiece: use modshare.import_any for those). The file is checked first; an older layout is
    upgraded after a backup copy."""
    obj, notes, bak = migrate.read_older(path)
    if obj.get('format') != FORMAT:
        raise ValueError('This is not a single mod file. Use Import for collections and pieces.')
    r = import_obj(obj, notes)
    if bak:
        r['import']['backup'] = bak
    return r


# ---------------------------------------------------------------------------------------------- build / install
def combined_assets(mod_list):
    """Models and textures of all mods in mod order; a later mod's entry for the same target (or the same imported path) wins."""
    models, texts = {}, {}
    for m in mod_list:
        for x in m.get('models') or []:
            models[(x.get('target') or x.get('path') or '').lower()] = x
        for x in m.get('textures') or []:
            texts[x['target'].lower()] = x
    return list(models.values()), list(texts.values())


def combined(mod_list):
    """The mods in load order merged into one set of edits. Different objects and different values all apply; the same object and
    property (or data key, or collision set id) takes the value of the LAST mod in the list. An added object's uid that two mods
    share is renamed for the later one, so both objects exist."""
    level, data, coll = [], {}, {}
    used = set()
    for mi, m in enumerate(mod_list):
        for o in m.get('level') or []:
            if o.get('op') == 'add' and o.get('uid') in used:
                o = dict(o, uid='%s~%d' % (o['uid'], mi))
            level.append(o)
        used.update(o['uid'] for o in m.get('level') or [] if o.get('op') == 'add' and o.get('uid'))
        for ed, vals in (m.get('data') or {}).items():
            data.setdefault(ed, {}).update(vals)
        for s in m.get('collision') or []:
            coll[s['id']] = s                    # a later mod's set with the same id wins
    return level, data, list(coll.values())


def combined_part_b(mod_list):
    """Companion tools part B ops of all mods, in mod order (routes, missions, sections)."""
    out = dict(nav=[], missions=[], sections=[])
    for m in mod_list:
        for k in out:
            out[k] += m.get(k) or []
    return out


def build_mods(ws, mod_list, out_dir, zip_name, progress=None):
    from . import build, dataed
    level, data, coll = combined(mod_list)
    frag = dataed.all_ops(ws, data)
    models, texts = combined_assets(mod_list)
    return build.build(ws, level, frag, out_dir, zip_name, progress, collision=coll, part_b=combined_part_b(mod_list),
                       assets=dict(models=models, textures=texts) if (models or texts) else None)


def filesystem_text(folder, first, remove=None):
    """configpc.txt as it should be after putting `first` (or nothing) in front of the current archives; every other line stays.
    -> dict(text=<the whole file>, line=<the new filesystem line>). Writes nothing."""
    p = os.path.join(folder, 'configpc.txt')
    lines = read_configpc(folder)
    fs = filesystem_line(lines) or list(DEFAULT_FS)
    remove = {a.lower() for a in (remove if remove is not None else [MOD_ZIP])}
    fs = [a for a in fs if a.lower() not in remove]
    if first:
        fs = [first] + fs
    new_line = 'filesystem = ' + ', '.join(fs)
    out, done = [], False
    idx = [i for i, ln in enumerate(lines) if re.match(r'\s*filesystem\s*=', ln, re.I)]
    for i, ln in enumerate(lines):
        if idx and i == idx[-1]:
            out.append(new_line)
            done = True
        elif i in idx:
            continue
        else:
            out.append(ln)
    if not done:
        out.append(new_line)
    nl = '\n'
    if os.path.exists(p):
        with open(p, 'rb') as f:
            nl = '\r\n' if b'\r\n' in f.read() else '\n'
    data = ('\n'.join(out).rstrip('\n') + '\n').replace('\n', nl)
    return dict(text=data, line=new_line)


def config_backups(folder):
    """configpc.txt.todms_backup (the file as it was before our first change, kept once) and .todms_last (before the latest change)."""
    p = os.path.join(folder, 'configpc.txt')
    if os.path.exists(p):
        bak = p + '.todms_backup'
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        shutil.copy2(p, p + '.todms_last')


def set_filesystem(folder, first, remove=None):
    """configpc.txt: put `first` (or nothing) in front of the current archives; keep every other line."""
    p = os.path.join(folder, 'configpc.txt')
    r = filesystem_text(folder, first, remove)
    config_backups(folder)
    with open(p + '.part', 'wb') as f:
        f.write(r['text'].encode('latin-1'))
    os.replace(p + '.part', p)
    return r['line']


def install(ws, progress=None, label=None):
    """Every enabled mod, in list order, goes into the pack (pack.py): the mods stage comes first, new maps and missions on top."""
    from . import pack
    g = ws.game
    if game_running(g.folder):
        raise RuntimeError('Total Overdose is running: close it first')
    o = load_order()
    ids = [i for i in o['order'] if i in o['enabled']]
    unmet = requirements(ws, ids)
    if unmet:
        raise ValueError(' '.join(u['text'] for u in unmet))
    return pack.apply(ws, label or ('install mods' if ids else 'remove mods'), mods=ids, progress=progress)['installed']


def requirements(ws, ids=None):
    """What the switched-on mods need and the game does not have (plain sentences). Read only."""
    o = load_order()
    ids = [i for i in o['order'] if i in o['enabled']] if ids is None else list(ids)
    return compat.check_requirements(library(), ids, compat.environment(ws.game if ws else None))


def conflict_report(ids=None, folder=None):
    """Clashes and merges between the mods that are switched on (or `ids`), in load order. With a game folder it also lists the
    shipped blocks several installed things add entries to (the pack merges them)."""
    o = load_order()
    ids = [i for i in o['order'] if i in o['enabled']] if ids is None else list(ids)
    lib = library()
    ml = [dict(lib[i], id=i) for i in ids if i in lib]
    out = compat.conflicts(ml)
    if folder:
        from . import pack
        cur = pack.read_inputs(folder)
        out['shared_hosts'] = compat.shared_hosts(ml, cur['newmaps'], cur['missions'])
    return out


def uninstall(ws, progress=None):
    """Take the mods out of the pack (new maps and missions stay)."""
    from . import pack
    g = ws.game
    if game_running(g.folder):
        raise RuntimeError('Total Overdose is running: close it first')
    return pack.apply(ws, 'remove mods', mods=[], progress=progress)['installed']


def installed_state(ws):
    try:
        rec = json.load(open(os.path.join(lib_dir(), 'installed.json')))
    except Exception:
        rec = {}
    if ws.game:
        rec['zip_present'] = bool(rec.get('mods')) and os.path.exists(os.path.join(ws.game.folder, PACK_ZIP))
        rec['filesystem_line'] = filesystem_line(read_configpc(ws.game.folder))
    return rec
