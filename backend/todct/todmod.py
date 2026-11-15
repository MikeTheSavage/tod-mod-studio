"""The .todmod recipe shared by TOD Mod Studio and the Unreal TODLevelEditor plugin.

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
  "assets": {"kind": "todct-asset-overrides", "rows": {stem: {ue, kind, path, collision}}}
                                     Unreal replacements (the bridge's asset_overrides.json rows); Mod Studio shows them
  "source": {"editor": "unreal" | "modstudio", ...}       where the recipe was made
Version 3 adds (companion tools part B; written only when used):
  "nav": [nav ops]            todct.nav (routes: track points, SignPosts, traffic points, NavBlock boxes)
  "missions": [mission ops]   todct.missions (trigger values, rewired actions, triggers from templates)
  "sections": [section ops]   todct.sections (loader Teleport_to / position, new sections)
Entries are full archive entry names (data_pc/overdose_the_game/overdose/shared/<block>), fragments full record
names, nodes '0x%08X'. Coordinates are the game's (TOD axes, metres); the Unreal side converts with the bridge rule.
"""
import copy
import datetime
import json
import re
import uuid

from . import collision as CO

FORMAT = 'todms-mod'
VERSION_MAX = 3
SHARED_PREFIX = 'data_pc/overdose_the_game/overdose/shared/'


class ModError(ValueError):
    pass


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def new_mod(name, author='', description='', level=None, data=None, collision=None, assets=None, source=None,
            nav=None, missions=None, sections=None):
    m = dict(format=FORMAT, version=1, id=None, name=name or 'My mod', author=author or '', description=description or '',
             level=list(level or []), data=dict(data or {}), view=None, created=now(), updated=now())
    if collision:
        m['collision'] = list(collision)
    if assets and assets.get('rows'):
        m['assets'] = assets
    if source:
        m['source'] = source
    for k, v in (('nav', nav), ('missions', missions), ('sections', sections)):
        if v:
            m[k] = list(v)
    m['version'] = version_needed(m)
    return m


def version_needed(m):
    if m.get('nav') or m.get('missions') or m.get('sections'):
        return 3
    return 2 if (m.get('collision') or (m.get('assets') or {}).get('rows')) else 1


def full_entry(short_or_entry):
    s = short_or_entry.replace('\\', '/')
    return s if '/' in s else SHARED_PREFIX + s


def short(entry):
    return (entry or '').replace('\\', '/').split('/')[-1]


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
    rows = (m.get('assets') or {}).get('rows') or {}
    for k, r in rows.items():
        if not k.startswith('data_') or not str(r.get('ue', '')).startswith('/'):
            raise ModError('asset row %s: needs a stem key and a /Game/... asset' % k)
    from . import edits as ED
    for kind in ED.KINDS:
        try:
            ED.validate_ops(kind, m.get(kind))
        except ValueError as e:
            raise ModError(str(e))
    if version_needed(m) > int(m.get('version', 1)):
        raise ModError('the recipe uses collision/assets/route/mission/section data but says version %s' % m.get('version'))
    return notes


def load(path):
    with open(path, encoding='utf-8') as f:
        m = json.load(f)
    validate(m)
    return m


def save(m, path):
    m = copy.deepcopy(m)
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
                asset_rows=len((m.get('assets') or {}).get('rows') or {}), source=(m.get('source') or {}).get('editor'),
                nav_ops=len(m.get('nav') or []), mission_ops=len(m.get('missions') or []),
                section_ops=len(m.get('sections') or []))


# ---------------------------------------------------------------------------------------------- Unreal coordinates
def game_to_ue_loc(p):
    """The bridge's rule (TodbConvert.h, 714/714 rotated Map09 props)."""
    return [p[0] * 100.0, -p[2] * 100.0, p[1] * 100.0]


def ue_to_game_loc(L):
    return [L[0] / 100.0, L[2] / 100.0, -L[1] / 100.0]


def true_to_ue_quat(q):
    return [q[0], -q[2], q[1], q[3]]


def ue_to_true_quat(u):
    return [u[0], u[2], -u[1], u[3]]


def ue_edits(m):
    """The level ops as edits the Unreal plugin applies to its actors (pure; the plugin finds the actors).
    Returns (edits, carried): carried = what Unreal does not edit (data values, raw fragment ops)."""
    edits = []
    for o in m.get('level') or []:
        op = o['op']
        base = dict(block=short(o.get('entry')), fragment=o.get('frag'), key=o.get('node'), label=o.get('label'))
        if op == 'move':
            e = dict(base, action='move')
            if o.get('pos') is not None:
                e['ue_loc'] = game_to_ue_loc(o['pos'])
                e['game_pos'] = list(o['pos'])
            if o.get('rot') is not None:
                e['ue_quat'] = true_to_ue_quat(o['rot'])
            edits.append(e)
        elif op == 'set':
            edits.append(dict(base, action='set', prop=o['prop'], value=json.dumps(o['value'])))
        elif op == 'delete':
            edits.append(dict(base, action='hard_delete' if o.get('mode') == 'remove' else 'retire'))
        elif op == 'add':
            t = o['template']
            edits.append(dict(action='add', uid=o['uid'], block=short(o['entry']), name=o.get('name'),
                              template='%s|%s|%s' % (short(t['entry']), short(t['frag']), t['node']),
                              template_entry=t['entry'], template_frag=t['frag'], template_key=t['node'],
                              ue_loc=game_to_ue_loc(o['pos']) if o.get('pos') is not None else None,
                              ue_quat=true_to_ue_quat(o['rot']) if o.get('rot') is not None else None,
                              props={k: json.dumps(v) for k, v in (o.get('set') or {}).items()},
                              view=o.get('view') or {}))
    carried = dict(data=m.get('data') or {}, frag_ops=[o for o in m.get('level') or [] if o['op'] == 'frag'])
    return edits, carried


def merge_assets(rows_a, rows_b):
    out = dict(rows_a or {})
    out.update(rows_b or {})
    return out


def new_id(name):
    base = re.sub(r'[^a-z0-9]+', '-', (name or 'mod').lower()).strip('-')[:40] or 'mod'
    return '%s-%s' % (base, uuid.uuid4().hex[:6])
