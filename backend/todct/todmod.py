"""The .todmod recipe of TOD Mod Studio.

A .todmod is TOD Mod Studio's mod.json (format "todms-mod"): a recipe, never game data. Version 1 holds
  "level": [ops]      Mod Studio's level grammar (todms/build.py):
                        move   {entry, frag, node, pos [x,y,z] world m, rot [x,y,z,w] TRUE world rotation}
                        set    {entry, frag, node, prop, value}
                        delete {entry, frag, node, mode: retire|remove}
                        add    {uid, entry, template {entry, frag, node}, name, pos, rot, set {prop: value}, view}
                        frag   {entry, ops: [raw fragment writer ops]}         (data editors)
  "data": {editor: {key: value}}   Mod Studio's data editors (weapons, vehicles, loco, camera)
Version 2 adds (written only when used, so a version-1 reader is never given data it would silently drop):
  "collision": [collision sets]      todct.collision (pieces in world space; built into a host model's HullList)
Recipes written before this version may also carry "assets" and "source"; they are read and ignored (see legacy_keys).
Version 3 adds (companion tools part B; written only when used):
  "nav": [nav ops]            todct.nav (routes: track points, SignPosts, traffic points, NavBlock boxes)
  "missions": [mission ops]   todct.missions (trigger values, rewired actions, triggers from templates)
  "sections": [section ops]   todct.sections (loader Teleport_to / position, new sections)
Version 4 adds (model import and texture editor; written only when used; see todct/assetops.py):
  "models": [model entries]   imported models (new, placed by `add` ops) and replaced game models
  "textures": [texture entries]  replaced or edited game textures
The old "assets" key (rows of a tool that is gone) is still dropped on read; it is NOT the same thing as "models".
Entries are full archive entry names (data_pc/overdose_the_game/overdose/shared/<block>), fragments full record
names, nodes '0x%08X'. Coordinates are the game's (TOD axes, metres).
"""
import copy
import datetime
import json
import re
import uuid

from . import collision as CO
from . import assetops as AO

FORMAT = 'todms-mod'
VERSION_MAX = 4
SHARED_PREFIX = 'data_pc/overdose_the_game/overdose/shared/'


class ModError(ValueError):
    pass


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def new_mod(name, author='', description='', level=None, data=None, collision=None, nav=None, missions=None, sections=None,
            models=None, textures=None):
    m = dict(format=FORMAT, version=1, id=None, name=name or 'My mod', author=author or '', description=description or '',
             level=list(level or []), data=dict(data or {}), view=None, created=now(), updated=now())
    if collision:
        m['collision'] = list(collision)
    for k, v in (('nav', nav), ('missions', missions), ('sections', sections), ('models', models), ('textures', textures)):
        if v:
            m[k] = list(v)
    m['version'] = version_needed(m)
    return m


def version_needed(m):
    if m.get('models') or m.get('textures'):
        return 4
    if m.get('nav') or m.get('missions') or m.get('sections'):
        return 3
    return 2 if m.get('collision') else 1


def full_entry(short_or_entry):
    s = short_or_entry.replace('\\', '/')
    return s if '/' in s else SHARED_PREFIX + s


def short(entry):
    return (entry or '').replace('\\', '/').split('/')[-1]


LEGACY_KEYS = ('assets', 'source')       # written by older recipes for a tool that is gone: ignored, never an error


def legacy_keys(m):
    """Drop the keys of older recipes that no longer mean anything (in place); returns m."""
    for k in LEGACY_KEYS:
        m.pop(k, None)
    return m


def validate(m):
    """Raise ModError for anything a builder would refuse; return notes."""
    if m.get('format') != FORMAT:
        raise ModError('not a TOD mod recipe (format %r)' % m.get('format'))
    if int(m.get('version', 1)) > VERSION_MAX:
        raise ModError('this mod needs a newer tool (recipe version %s, this reads up to %d)' % (m.get('version'), VERSION_MAX))
    notes = []
    for i, o in enumerate(m.get('level') or []):
        op = o.get('op')
        if op not in ('move', 'set', 'delete', 'add', 'frag'):
            raise ModError('level op %d: unknown op %r' % (i, op))
        if op in ('move', 'set', 'delete'):
            for k in ('entry', 'frag', 'node'):
                if not o.get(k):
                    raise ModError('level op %d (%s): missing %s' % (i, op, k))
            if not re.match(r'^0x[0-9a-fA-F]{8}$', str(o['node'])):
                raise ModError('level op %d: node %r is not 0x%%08X' % (i, o['node']))
        if op == 'add' and not (o.get('template') and o.get('entry') and o.get('uid')):
            raise ModError('level op %d (add): needs uid, entry and template' % i)
    for s in m.get('collision') or []:
        notes += CO.validate_set(s)
    from . import edits as ED
    for kind in ED.KINDS:
        try:
            ED.validate_ops(kind, m.get(kind))
        except ValueError as e:
            raise ModError(str(e))
    try:
        AO.validate_models(m.get('models'))
        AO.validate_textures(m.get('textures'))
    except AO.AssetOpError as e:
        raise ModError(str(e))
    if version_needed(m) > int(m.get('version', 1)):
        raise ModError('the recipe uses collision/route/mission/section/model/texture data but says version %s' % m.get('version'))
    return notes


def load(path):
    with open(path, encoding='utf-8') as f:
        m = legacy_keys(json.load(f))
    validate(m)
    return m


def save(m, path):
    m = legacy_keys(copy.deepcopy(m))
    m['format'] = FORMAT
    m['version'] = version_needed(m)
    m['updated'] = now()
    validate(m)
    m.pop('built', None)
    with open(path + '.part', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(m, f, indent=1)
    import os
    os.replace(path + '.part', path)
    return path


def summary(m):
    lv = m.get('level') or []
    c = {}
    for o in lv:
        c[o['op']] = c.get(o['op'], 0) + 1
    return dict(name=m.get('name'), version=m.get('version'), level_ops=len(lv), by_op=c,
                data_values=sum(len(v) for v in (m.get('data') or {}).values()),
                collision_sets=len(m.get('collision') or []),
                collision_pieces=sum(len(s.get('pieces') or []) for s in m.get('collision') or []),
                nav_ops=len(m.get('nav') or []), mission_ops=len(m.get('missions') or []),
                section_ops=len(m.get('sections') or []), models=len(m.get('models') or []), textures=len(m.get('textures') or []))


def new_id(name):
    base = re.sub(r'[^a-z0-9]+', '-', (name or 'mod').lower()).strip('-')[:40] or 'mod'
    return '%s-%s' % (base, uuid.uuid4().hex[:6])
