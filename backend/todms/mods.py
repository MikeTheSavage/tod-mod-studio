"""Mod library, sharing and installation.

A mod is a recipe, never game data: mod.json holds the level edits and data-editor values. Building it reads the
player's own blocks (TOD HD's when installed) and writes one override zip. Sharing exports the recipe as a .todmod
file (JSON); the receiver's app rebuilds it from their own game.

Install: every enabled mod, in list order, is built into ONE zip, todms_mods.zip, in the game folder, listed first on
configpc.txt's "filesystem =" line (ahead of TOD HD's zips when present). configpc.txt is backed up before the first
change; blocks.naz and every other game file are never written.
"""
import datetime
import json
import os
import re
import shutil
import uuid

from . import paths
from .game import MOD_ZIP, DEFAULT_FS, read_configpc, filesystem_line, game_running

FORMAT = 'todms-mod'


def _version(m):
    """Recipe version (todct.todmod): 3 with route/mission/section ops, 2 with collision sets or Unreal asset rows, else 1."""
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
        return json.load(open(_order_file()))
    except Exception:
        return dict(order=[], enabled=[])


def save_order(o):
    json.dump(o, open(_order_file(), 'w'), indent=1)


def list_mods():
    o = load_order()
    mods = {}
    for d in os.listdir(lib_dir()):
        p = os.path.join(lib_dir(), d, 'mod.json')
        if os.path.exists(p):
            try:
                m = json.load(open(p))
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
                        asset_rows=len((m.get('assets') or {}).get('rows') or {}),
                        nav_ops=len(m.get('nav') or []), mission_ops=len(m.get('missions') or []),
                        section_ops=len(m.get('sections') or []),
                        source=(m.get('source') or {}).get('editor') or 'modstudio'))
    return out


def get_mod(mid):
    return json.load(open(os.path.join(lib_dir(), mid, 'mod.json')))


def save_mod(m):
    if not m.get('id'):
        base = re.sub(r'[^a-z0-9]+', '-', (m.get('name') or 'mod').lower()).strip('-')[:40] or 'mod'
        m['id'] = '%s-%s' % (base, uuid.uuid4().hex[:6])
        m['created'] = _now()
    m['format'] = FORMAT
    m['version'] = _version(m)
    m['updated'] = _now()
    d = os.path.join(lib_dir(), m['id'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'mod.json')
    json.dump(m, open(p + '.part', 'w'), indent=1)
    os.replace(p + '.part', p)
    o = load_order()
    if m['id'] not in o['order']:
        o['order'].append(m['id'])
        save_order(o)
    return m


def delete_mod(mid):
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


def export_mod(mid, path):
    m = get_mod(mid)
    share = {k: v for k, v in m.items() if k not in ('built',)}
    json.dump(share, open(path, 'w'), indent=1)
    return path


def import_mod(path):
    from todct import todmod
    m = json.load(open(path, encoding='utf-8'))
    if m.get('format') != FORMAT:
        raise ValueError('not a TOD Mod Studio mod file')
    todmod.validate(m)            # versions 1-3 (3: routes, missions, sections) are read; newer ones are refused
    m.pop('id', None)
    return save_mod(m)


# ---------------------------------------------------------------------------------------------- build / install
def combined(mod_list):
    level, data, coll = [], {}, {}
    for m in mod_list:
        level += m.get('level') or []
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
    return build.build(ws, level, frag, out_dir, zip_name, progress, collision=coll, part_b=combined_part_b(mod_list))


def set_filesystem(folder, first, remove=None):
    """configpc.txt: put `first` (or nothing) in front of the current archives; keep every other line."""
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
    if os.path.exists(p):
        bak = p + '.todms_backup'
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        shutil.copy2(p, p + '.todms_last')
    nl = '\r\n' if (os.path.exists(p) and b'\r\n' in open(p, 'rb').read()) else '\n'
    data = '\n'.join(out).rstrip('\n') + '\n'
    open(p + '.part', 'w', encoding='latin-1', newline=nl).write(data)
    os.replace(p + '.part', p)
    return new_line


def install(ws, progress=None):
    g = ws.game
    if game_running(g.folder):
        raise RuntimeError('Total Overdose is running: close it first')
    o = load_order()
    mods = [get_mod(i) for i in o['order'] if i in o['enabled']]
    stage = os.path.join(paths.cache_dir(), 'install_stage')
    shutil.rmtree(stage, ignore_errors=True)
    if not mods:
        return uninstall(ws)
    rep = build_mods(ws, mods, stage, MOD_ZIP, progress)
    if not rep.get('entries'):
        return uninstall(ws)
    from . import newmap
    newmap.check_mod_conflicts(g.folder, os.path.join(stage, MOD_ZIP))
    dst = os.path.join(g.folder, MOD_ZIP)
    shutil.copy2(os.path.join(stage, MOD_ZIP), dst + '.part')
    os.replace(dst + '.part', dst)
    line = set_filesystem(g.folder, MOD_ZIP)
    rep.pop('_outs', None)
    rec = dict(installed=_now(), mods=[m['id'] for m in mods], zip=dst, configpc_line=line,
               blocks=[dict(entry=b['entry'], base=b['base_archive'], bytes=b['bytes']) for b in rep['blocks']],
               save_safe=rep['save_safe'], tod_hd=g.has_hd())
    json.dump(rec, open(os.path.join(lib_dir(), 'installed.json'), 'w'), indent=1)
    return rec


def uninstall(ws):
    g = ws.game
    if game_running(g.folder):
        raise RuntimeError('Total Overdose is running: close it first')
    z = os.path.join(g.folder, MOD_ZIP)
    if os.path.exists(z):
        os.remove(z)
    line = None
    fs = filesystem_line(read_configpc(g.folder))
    if fs and any(a.lower() == MOD_ZIP for a in fs):
        line = set_filesystem(g.folder, None)
    rec = dict(installed=None, mods=[], configpc_line=line)
    json.dump(rec, open(os.path.join(lib_dir(), 'installed.json'), 'w'), indent=1)
    return rec


def installed_state(ws):
    try:
        rec = json.load(open(os.path.join(lib_dir(), 'installed.json')))
    except Exception:
        rec = {}
    if ws.game:
        rec['zip_present'] = os.path.exists(os.path.join(ws.game.folder, MOD_ZIP))
        rec['filesystem_line'] = filesystem_line(read_configpc(ws.game.folder))
    return rec
