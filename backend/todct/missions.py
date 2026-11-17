"""Mission graph editor core (companion tools part B) of TOD Mod Studio.

A mission is data: trigger trees in the fragments of a .mission block (docs/subsystem_mission_scripting.md 5).
A root (box, sphere, Node or NodeLogical) owns conditions (each waits for one event code, TrueOn, from an activator)
and actions (ActionType, a target found by ActivateWho / TargetName, Delay). The root fires when all / any / N of its
conditions are met (TriggerOn) and sleeps and re-arms with Reactivate. missiontool.py decodes the trees and names the
codes (missionenums.py); this module turns them into a node graph and edits them save-safely.

  g = graph(entry, read)                   triggers (cards: conditions, actions) + edges (action -> trigger it acts on)
                                           + a layout (column = steps from the mission start), readable names
  issues = lint(entry, raw)                missiontool check (with overdose.main and the mission's map/submap)
  add_to_builder(builder, ops, read)       blockedit requests
  verify(entry, ops, raw_before, raw_after)  graph of the built block (engine view) shows each op; lint before/after

Mission ops (entry = full archive entry; frag = fragment; node '0x%08X'; new entities get an 'id'):
  {"op": "set",      entry, frag, node|id, prop, value}            any value: TrueOn, ActivatorType, ActionType,
                                                                    TargetName, ActivateWho, Delay, Reactivate,
                                                                    ReactivateDelay, TriggerOn, ConditionsNeeded ...
  {"op": "rewire",   entry, frag, action, to: {frag, node} | id}   the action is fired by another trigger (its parent
                                                                    becomes that root; save-safe: no node created)
  {"op": "retarget", entry, frag, action, target: "Name", who: 3}  what the action acts on (TargetName/ActivateWho)
  {"op": "add_trigger", id, entry, template, name, pos, size, yaw, parent: {frag, node} | null, params: {...}}
                     templates: go_to_point, kill_n, timer, spawn_group, camera_cut, objective_text
                     params: objective, count, seconds, target, camera, hold, text, action (override), reactivate
  {"op": "add_action", id, entry, root: {frag, node} | id, action: kind, params}
  {"op": "disable_trigger", entry, frag, node}                     root flag bit 0 (NODE_DISABLE): never fires until
                                                                    an Enable action (5) enables it; save-safe
"""
import collections
import json
import math
import os
import re
import tempfile

from . import blockedit as BE
from . import tools


class MissionError(ValueError):
    pass


def mt():
    return tools.load_more('missiontool')


def me():
    return tools.load_more('missionenums')


def short(e):
    return (e or '').replace('\\', '/').split('/')[-1]


def fshort(f):
    return (f or '').replace('\\', '/').split('/')[-1]


# Shipped single nodes the templates copy (found by a scan of all 64 mission blocks for childless nodes whose
# values point nowhere outside themselves; type strings the engine knows, so the creates load).
M10 = 'data_pc/overdose_the_game/overdose/shared/mm010_ernestocruz.mission'
M10F = '/data/Overdose_THE_GAME/Missions/MainMissions/MM010_ErnestoCruz.fragment'
SHARED = 'data_pc/overdose_the_game/overdose/shared/'
PARTS = {
    'root_box': (M10, M10F, '0x00400205', 'Trigger_Root(CollisionBox): enter box (flags 0, like MM010_objective_update)'),
    'root_node': (M10, M10F, '0x004001B3', 'Trigger_Root(Node): no volume'),
    'root_logical': (M10, M10F, '0x0040030D', 'Trigger_Root(NodeLogical): logic events'),
    'cond_enter': (M10, M10F, '0x0040000B', 'Trigger_Condition TrueOn 1 (the player enters)'),
    'cond_start': (M10, M10F, '0x004001B4', 'Trigger_Condition TrueOn 6 (mission start)'),
    'cond_timer': (SHARED + 'mm040_getthetrucks.mission', 'MM040_GetTheTrucks.fragment', '0x004006F2',
                   'Trigger_Condition TrueOn 14 (true at once / after IntervalTrue s)'),
    'cond_kill': (SHARED + 'subm_04_down_somsal_kill.mission', 'SubM_04_Down_SomSal_Kill.fragment', '0x004018EB',
                  'Trigger_Condition_Logical TrueOn 9 (an enemy killed; TrigAmount hits)'),
    'act_obj_complete': (M10, M10F, '0x00400245', 'Trigger_Activate_Objective 72 (objective completed)'),
    'act_obj_activate': (M10, M10F, '0x00400246', 'Trigger_Activate_Objective 75 (objective active)'),
    'act_obj_text': (M10, M10F, '0x004002A6', 'Trigger_Activate_Objective 79 (feedback text)'),
    'act_enable': (M10, M10F, '0x004000DB', 'Trigger_Activate_Enable_Disable 5 (enable: spawns a group)'),
    'act_trig': (M10, M10F, '0x0040000C', 'Trigger_Activate_Trig_Noaction_Reactivate 10 (trig the target)'),
    'act_camera': (M10, M10F, '0x0040022D', 'Trigger_Activate_Camera 32 (cut to camera node)'),
}
ACTIONS = {          # action kind -> (part, sets from params)
    'complete_objective': ('act_obj_complete', lambda p: {'TargetName': p['objective']}),
    'activate_objective': ('act_obj_activate', lambda p: {'TargetName': p['objective']}),
    'objective_text': ('act_obj_text', lambda p: dict({'TargetName': p['objective']},
                                                      **({'FeedbackText': int(p['text'])} if p.get('text') is not None else {}))),
    'enable': ('act_enable', lambda p: {'TargetName': p['target'], 'ActionType': 5, 'ActivateWho': 3}),
    'disable': ('act_enable', lambda p: {'TargetName': p['target'], 'ActionType': 6, 'ActivateWho': 3}),
    'trig': ('act_trig', lambda p: {'TargetName': p['target'], 'ActivateWho': 3}),
    'camera_cut': ('act_camera', lambda p: dict({'TargetName': p['camera']},
                                                **({'ActivationTime': float(p['hold'])} if p.get('hold') is not None else {}))),
}
TEMPLATES = collections.OrderedDict([
    ('go_to_point', dict(label='Go to a point', root='root_box', cond='cond_enter', action='complete_objective',
                         needs=['objective'], help='A box; when Ram enters it, the action runs (default: complete an objective).')),
    ('kill_n', dict(label='Kill N enemies', root='root_logical', cond='cond_kill', action='complete_objective',
                    needs=['count', 'objective'], help='Fires after N enemy kills (logic event 9, TrigAmount = N).')),
    ('timer', dict(label='Timer', root='root_node', cond='cond_timer', action='trig', needs=['seconds', 'target'],
                   help='Fires IntervalTrue seconds after it is enabled (TrueOn 14). Create it disabled and enable it '
                        'from another trigger to start the clock.')),
    ('spawn_group', dict(label='Spawn a group', root='root_box', cond='cond_enter', action='enable', needs=['target'],
                         help='When Ram enters the box, enable a folder of placeholders (that is how TOD spawns enemies).')),
    ('camera_cut', dict(label='Camera cut', root='root_box', cond='cond_enter', action='camera_cut', needs=['camera'],
                        help='When Ram enters the box, cut to a camera node for "hold" seconds.')),
    ('objective_text', dict(label='Objective text', root='root_box', cond='cond_enter', action='objective_text',
                            needs=['objective'], help='When Ram enters the box, show an objective\'s feedback text '
                                                      '(text = ordinal in uk_Objective.txt, e.g. 57 "Get to the plane on the airstrip").')),
])


# ---------------------------------------------------------------------------------------------- reading
def mblock(raw, entry):
    """missiontool.Block over bytes."""
    M = mt()
    with tempfile.TemporaryDirectory() as d:
        fn = os.path.join(d, short(entry))
        with open(fn, 'wb') as f:
            f.write(raw)
        B = M.Block(fn, entry)
    B.entry = entry
    return B


_ctx_cache = {}


def context(entry):
    """overdose.main and, for a mission, its map and submap blocks (missiontool.context_for, cached)."""
    if entry not in _ctx_cache:
        M = mt()
        dummy = type('X', (), {})()
        dummy.entry = entry
        _ctx_cache[entry] = M.context_for(dummy)
    return _ctx_cache[entry]


def _code(x):
    for k in ('ActionType', 'Do_What'):
        if k in x:
            return x[k]
    return None


def graph(entry, raw, with_context=True):
    """Node graph of a block's trigger trees (engine view: literal-parented new triggers sit under their parent)."""
    ev, moved = BE.engine_view(raw, entry)
    B = mblock(ev, entry)
    if with_context:
        B.add_context(context(entry))
    G = mt().graph(B)
    trig = collections.OrderedDict()
    name_to_ids = collections.defaultdict(list)
    for f in G:
        fr = fshort(f['fragment'])
        for t in f['triggers']:
            tid = '%s|%s' % (fr, t['node'])
            conds = []
            for c in t.get('if') or []:
                ev_code = c.get('event', '')
                conds.append(dict(node=c['node'], name=c.get('name') or '', cls=c['cls'], code=_int(ev_code.split(' ')[0]),
                                  event=ev_code, activator=c.get('activator'),
                                  extra={k: v for k, v in c.items() if k not in ('node', 'name', 'cls', 'base', 'event', 'activator')}))
            acts = []

            def walk(lst, depth):
                for a in lst:
                    if isinstance(a, str):
                        continue
                    acts.append(dict(node=a['node'], name=a.get('name') or '', cls=a['cls'], short=a['cls'].replace('Trigger_Activate_', ''),
                                     code=_code(a), does=a.get('does'), target=a.get('target'), who=a.get('ActivateWho'),
                                     target_name=(a.get('args') or {}).get('TargetName'), delay=a.get('delay'), depth=depth,
                                     args={k: v for k, v in (a.get('args') or {}).items() if k != 'TargetName'}))
                    walk(a.get('then') or [], depth + 1)
            walk(t.get('do') or [], 0)
            rec = dict(id=tid, frag=fr, node=t['node'], name=t.get('name') or '', cls=t['cls'], base=t.get('base'),
                       path=t.get('path'), pos=t.get('world_pos'), box=t.get('box_whl'), radius=t.get('radius'),
                       trigger_on=t.get('TriggerOn'), needed=t.get('ConditionsNeeded'), reactivate=t.get('Reactivate'),
                       reactivate_delay=t.get('ReactivateDelay'), start_mission=t.get('Start_Mission'),
                       conditions=conds, actions=acts, new=any(m[0] == t['node'] for m in moved))
            trig[tid] = rec
            if t.get('name'):
                name_to_ids[t['name'].lower()].append(tid)
    # edges: an action whose target is a trigger root (by TargetName, FindNode semantics: first match)
    edges = []
    for tid, t in trig.items():
        for a in t['actions']:
            tn = (a.get('target_name') or '').lower()
            hits = name_to_ids.get(tn) or []
            if not hits and a.get('who') in (2, 4):
                continue
            for h in hits[:1]:
                edges.append(dict(src=tid, action=a['node'], dst=h, kind=_edge_kind(a)))
            if t['conditions'] and any(c['code'] == 3 for c in t['conditions']):
                pass
    # death conditions name their activator: draw "dies -> trigger" edges from triggers that enable that placeholder?
    # (kept simple: action -> trigger edges only)
    _layout(trig, edges)
    starts = [tid for tid, t in trig.items() if any(c['code'] == 6 for c in t['conditions'])]
    return dict(kind='todct-mission-graph', version=1, entry=entry, block=short(entry), triggers=list(trig.values()),
                edges=edges, starts=starts, literal_linked=moved, enums=enum_tables())


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _edge_kind(a):
    c, code = a['short'], a.get('code')
    if c == 'Enable_Disable':
        return {5: 'enables', 6: 'disables', 7: 'toggles'}.get(code, 'enable/disable %s' % code)
    if c == 'Trig_Noaction_Reactivate':
        return {10: 'trigs', 29: 're-arms', 45: 'damages', 43: 'starts AI'}.get(code, 'acts %s' % code)
    return c.lower()


def _layout(trig, edges):
    """column = longest chain of action edges from a source trigger (start triggers first), row = order in column."""
    incoming = collections.defaultdict(set)
    out = collections.defaultdict(set)
    for e in edges:
        if e['src'] != e['dst']:
            out[e['src']].add(e['dst'])
            incoming[e['dst']].add(e['src'])
    col = {}
    order = list(trig)
    # longest path on the DAG part (cycles cut by visiting order)
    state = {}

    def depth(t, stack=()):
        if t in col:
            return col[t]
        if t in stack:
            return 0
        d = 0
        for s in incoming.get(t, ()):
            if s not in stack:
                d = max(d, depth(s, stack + (t,)) + 1)
        col[t] = d
        return d
    for t in order:
        depth(t)
    starts = {t for t, r in trig.items() if any(c['code'] == 6 for c in r['conditions'])}
    rows = collections.defaultdict(int)
    for t in sorted(order, key=lambda t: (col[t], t not in starts, order.index(t))):
        trig[t]['column'] = col[t]
        trig[t]['row'] = rows[col[t]]
        rows[col[t]] += 1


def enum_tables():
    E = me()
    out = {}
    for k in ('COND_TRUEON', 'LOGIC_TRUEON', 'ACTIVATOR_TYPE', 'TRIGGER_ON', 'ACTIVATE_WHO'):
        v = getattr(E, k, None)
        if isinstance(v, dict):
            out[k] = {str(a): (b[0] if isinstance(b, (list, tuple)) else str(b)) for a, b in v.items()}
    act = getattr(E, 'ACTION', None)
    if isinstance(act, dict):
        out['ACTION'] = {cls: {str(a): (b[0] if isinstance(b, (list, tuple)) else str(b)) for a, b in d.items()}
                         for cls, d in act.items() if isinstance(d, dict)}
    out['TEMPLATES'] = {k: dict(label=v['label'], needs=v['needs'], help=v['help'], action=v['action'])
                        for k, v in TEMPLATES.items()}
    out['ACTION_KINDS'] = list(ACTIONS)
    return out


def lint(entry, raw, with_context=True):
    ev, _ = BE.engine_view(raw, entry)
    B = mblock(ev, entry)
    if with_context:
        B.add_context(context(entry))
    return mt().check(B)


# ---------------------------------------------------------------------------------------------- build
def _part(k):
    e, fr, node, _ = PARTS[k]
    return (e, fr, node)


def _yawq(yaw):
    h = math.radians(float(yaw or 0.0)) / 2.0
    return [0.0, math.sin(h), 0.0, math.cos(h)]


def _action_sets(kind, params):
    if kind not in ACTIONS:
        raise MissionError('unknown action kind %r (one of %s)' % (kind, ', '.join(ACTIONS)))
    part, fn = ACTIONS[kind]
    try:
        sets = fn(params)
    except KeyError as e:
        raise MissionError('action %s needs the parameter %s' % (kind, e))
    if params.get('delay') is not None:
        sets['Delay'] = float(params['delay'])
    return part, sets


def _ref(entry, x):
    """{frag, node} -> ('ref', frag, node); 'id' string -> ('new', id)."""
    if x is None:
        return None
    if isinstance(x, str):
        return ('new', x)
    return ('ref', x['frag'], x['node'])


def add_to_builder(B, ops, read=None):
    notes = []
    for o in ops:
        op, e = o['op'], o['entry']
        if op == 'set':
            if o.get('id') and not o.get('node'):
                _new_set(B, o['id'], {o['prop']: o['value']})
            else:
                B.set(e, o['frag'], o['node'], o['prop'], o['value'])
        elif op == 'retarget':
            B.set(e, o['frag'], o['action'], 'TargetName', o['target'])
            if o.get('who') is not None:
                B.set(e, o['frag'], o['action'], 'ActivateWho', int(o['who']))
        elif op == 'rewire':
            to = o['to']
            if isinstance(to, str):
                raise MissionError('rewire to a new trigger: add the action with add_action instead')
            if fshort(to['frag']) == fshort(o['frag']):
                B.set(e, o['frag'], o['action'], 'parent', to['node'])
                notes.append('%s: action %s now fired by %s (same fragment, local parent)' % (short(e), o['action'], to['node']))
            else:
                raise MissionError('rewire across fragments (%s -> %s) would need a literal parent applied before its '
                                   'target exists; move actions within one fragment' % (fshort(o['frag']), fshort(to['frag'])))
        elif op == 'disable_trigger':
            if o.get('flags_now') is None and read is None:
                raise MissionError('disable_trigger needs the block (read) or flags_now')
            if o.get('flags_now') is not None:
                flags = int(o['flags_now'])
            else:
                bi = BE.BlockInfo(e, read(e))
                flags = int(bi.doc(BE.frag_name(bi.frs, o['frag'])).get(BE.node_id(o['node']), 'flags') or 0)
            B.set(e, o['frag'], o['node'], 'flags', flags | 1)
        elif op == 'add_trigger':
            T = TEMPLATES.get(o['template'])
            if T is None:
                raise MissionError('unknown template %r' % o['template'])
            p = dict(o.get('params') or {})
            for k in T['needs']:
                if k == 'objective' and (o.get('params') or {}).get('action') not in (None, 'complete_objective',
                                                                                       'activate_objective', 'objective_text'):
                    continue
                if p.get(k) in (None, ''):
                    raise MissionError('template %s needs %s' % (o['template'], k))
            rid = o['id']
            root_sets = {}
            if T['root'] == 'root_box':
                sz = [float(x) for x in (o.get('size') or [4.0, 4.0, 4.0])]
                root_sets.update(width=sz[0], height=sz[1], length=sz[2])
            if p.get('reactivate') is not None:
                root_sets['Reactivate'] = bool(p['reactivate'])
            if p.get('disabled'):
                root_sets['flags'] = 1
            pos = o.get('pos')
            if T['root'] == 'root_box' and pos is None:
                raise MissionError('template %s needs a position' % o['template'])
            B.append(e, rid, _part(T['root']), parent=_ref(e, o.get('parent')), name=o.get('name') or rid,
                     pos=pos, rot=_yawq(o.get('yaw')) if T['root'] == 'root_box' else None, sets=root_sets, order=1)
            csets = {}
            if T['cond'] == 'cond_timer':
                csets['IntervalTrue'] = float(p['seconds'])
            if T['cond'] == 'cond_kill':
                csets['TrigAmount'] = int(p['count'])
            B.append(e, rid + '_cond', _part(T['cond']), parent=('new', rid), name='Condition_' + (o.get('name') or rid),
                     sets=csets, order=1, pos=pos)
            kind = p.get('action') or T['action']
            part, asets = _action_sets(kind, p)
            B.append(e, rid + '_act', _part(part), parent=('new', rid), name='Activate_' + (o.get('name') or rid),
                     sets=asets, order=2, pos=pos)
            notes.append('%s: new trigger %s (%s): root + condition + action %s, appended after the block\'s last '
                         'node' % (short(e), rid, o['template'], kind))
        elif op == 'add_action':
            part, asets = _action_sets(o['action'], o.get('params') or {})
            B.append(e, o['id'], _part(part), parent=_ref(e, o['root']), name=(o.get('params') or {}).get('name') or o['id'],
                     sets=asets, order=int(o.get('order') or 100))
        else:
            raise MissionError('unknown mission op %r' % op)
    return notes


def _new_set(B, uid, sets):
    for L in B.appends.values():
        for a in L:
            if a['uid'] == uid:
                a['sets'].update(sets)
                return
    raise MissionError('new entity %s: set before it was added' % uid)


# ---------------------------------------------------------------------------------------------- verification
def verify(entry, ops, raw_before, raw_after):
    """The built block read back through missiontool (engine view): every op is visible in the graph; lint before
    and after (new issues listed)."""
    g0 = graph(entry, raw_before)
    g1 = graph(entry, raw_after)
    by0 = {t['id']: t for t in g0['triggers']}
    by1 = {t['id']: t for t in g1['triggers']}
    act1 = {(t['frag'], a['node']): (t, a) for t in g1['triggers'] for a in t['actions']}
    checks = []
    for o in ops:
        if o['entry'] != entry:
            continue
        if o['op'] == 'rewire':
            hit = act1.get((fshort(o['frag']), o['action']))
            want = '%s|%s' % (fshort(o['to']['frag']), o['to']['node'])
            ok = hit is not None and hit[0]['id'] == want
            checks.append(('PASS' if ok else 'FAIL', 'rewire: action %s is fired by %s%s' % (
                o['action'], hit[0]['name'] if hit else '?', '' if ok else ' (expected %s)' % want)))
        elif o['op'] == 'retarget':
            hit = act1.get((fshort(o['frag']), o['action']))
            ok = hit is not None and (hit[1].get('target_name') or '') == o['target']
            checks.append(('PASS' if ok else 'FAIL', 'retarget: %s -> %s (%s)' % (o['action'], o['target'],
                                                                                  hit[1].get('target') if hit else '?')))
        elif o['op'] == 'add_trigger':
            new = [t for t in g1['triggers'] if t['name'] == (o.get('name') or o['id']) and t['id'] not in by0]
            ok = len(new) == 1 and new[0]['conditions'] and new[0]['actions']
            d = ''
            if new:
                t = new[0]
                d = '%s%s at %s: IF %s DO %s' % (t['cls'], t['base'], t.get('pos'),
                                                [c['event'] for c in t['conditions']],
                                                ['%s %s -> %s' % (a['short'], a['code'], a.get('target')) for a in t['actions']])
                if o.get('pos') is not None and t.get('pos'):
                    ok = ok and all(abs(a - b) < 1e-3 for a, b in zip(t['pos'], o['pos']))
            checks.append(('PASS' if ok else 'FAIL', 'add_trigger %s: %s' % (o['id'], d or 'not found')))
        elif o['op'] == 'set' and o.get('node'):
            checks.append(('PASS', 'set %s.%s = %r' % (o['node'], o['prop'], o['value'])))
    l0 = set(lint(entry, raw_before))
    l1 = set(lint(entry, raw_after))
    new_issues = sorted(l1 - l0)
    gone = sorted(l0 - l1)
    res = 'PASS' if all(c[0] == 'PASS' for c in checks) else 'FAIL'
    return dict(result=res, checks=checks, lint=dict(before=len(l0), after=len(l1), new_issues=new_issues,
                                                     resolved=gone), triggers_before=len(by0), triggers_after=len(by1))


# ---------------------------------------------------------------------------------------------- preview (for the UIs)
def preview(g, ops):
    """The graph with the ops applied (fast, no build): what the editor draws between builds. Built and verified
    graphs come from graph() on the built block."""
    import copy
    g = copy.deepcopy(g)
    trig = collections.OrderedDict((t['id'], t) for t in g['triggers'])
    en = g.get('enums') or {}
    for i, o in enumerate(ops):
        if o['entry'] != g['entry']:
            continue
        op = o['op']
        fr = fshort(o.get('frag'))
        if op == 'set':
            key = o.get('node') or o.get('id')
            for t in trig.values():
                if (t['frag'] == fr and t['node'] == key) or t['id'] == 'new|%s' % key:
                    _apply_root_set(t, o['prop'], o['value'], en)
                for c in t['conditions']:
                    if c['node'] == key and (t['frag'] == fr or t.get('new')):
                        c['extra'][o['prop']] = o['value']
                        if o['prop'] == 'TrueOn':
                            c['code'] = int(o['value'])
                            c['event'] = '%s %s' % (o['value'], (en.get('COND_TRUEON') or {}).get(str(o['value']), '?'))
                for a in t['actions']:
                    if a['node'] == key and (t['frag'] == fr or t.get('new')):
                        if o['prop'] in ('ActionType', 'Do_What'):
                            a['code'] = o['value']
                        elif o['prop'] == 'TargetName':
                            a['target_name'] = o['value']
                            a['target'] = '%r (edited)' % o['value']
                        elif o['prop'] == 'ActivateWho':
                            a['who'] = o['value']
                        elif o['prop'] == 'Delay':
                            a['delay'] = o['value']
                        else:
                            a['args'][o['prop']] = o['value']
        elif op == 'retarget':
            for t in trig.values():
                for a in t['actions']:
                    if t['frag'] == fr and a['node'] == o['action']:
                        a['target_name'] = o['target']
                        a['target'] = '%r (edited)' % o['target']
                        if o.get('who') is not None:
                            a['who'] = o['who']
        elif op == 'rewire':
            src = next(((t, a) for t in trig.values() for a in t['actions'] if t['frag'] == fr and a['node'] == o['action']), None)
            dst = trig.get('%s|%s' % (fshort(o['to']['frag']), o['to']['node']))
            if src and dst:
                src[0]['actions'] = [a for a in src[0]['actions'] if a['node'] != o['action']]
                dst['actions'].append(dict(src[1], rewired_from=src[0]['name']))
        elif op == 'disable_trigger':
            t = trig.get('%s|%s' % (fr, o['node']))
            if t:
                t['disabled'] = True
        elif op == 'add_trigger':
            T = TEMPLATES.get(o['template']) or {}
            p = dict(o.get('params') or {})
            kind = p.get('action') or T.get('action')
            cond = {'cond_enter': (1, '1 actor enters the root volume'), 'cond_kill': (9, '9 an enemy killed'),
                    'cond_timer': (14, '14 true at once / after IntervalTrue s'),
                    'cond_start': (6, '6 mission start')}.get(T.get('cond'), (None, '?'))
            root_cls = {'root_box': '(CollisionBox)', 'root_node': '(Node)', 'root_logical': '(NodeLogical)'}.get(T.get('root'), '')
            tid = 'new|%s' % o['id']
            part = ACTIONS.get(kind, (None,))[0] or ''
            tgt = p.get('objective') or p.get('target') or p.get('camera')
            trig[tid] = dict(id=tid, frag='(new)', node=o['id'], name=o.get('name') or o['id'], cls='Trigger_Root',
                             base=root_cls, pos=o.get('pos'), box=o.get('size'), trigger_on='0 all conditions met (AND)',
                             new=True, conditions=[dict(node=o['id'] + '_cond', name='Condition', cls='Trigger_Condition',
                                                        code=cond[0], event=cond[1], activator='0 the player',
                                                        extra={k: p[k] for k in ('count', 'seconds') if k in p})],
                             actions=[dict(node=o['id'] + '_act', name=kind, cls=part, short=kind, code=None, does=kind,
                                           target=tgt, target_name=tgt, who=3, delay=p.get('delay'), depth=0, args={})])
        elif op == 'add_action':
            rid = ('new|%s' % o['root']) if isinstance(o['root'], str) else '%s|%s' % (fshort(o['root']['frag']), o['root']['node'])
            t = trig.get(rid)
            p = o.get('params') or {}
            tgt = p.get('objective') or p.get('target') or p.get('camera')
            if t:
                t['actions'].append(dict(node=o['id'], name=o['action'], cls=ACTIONS.get(o['action'], ('',))[0],
                                         short=o['action'], code=None, does=o['action'], target=tgt, target_name=tgt,
                                         who=3, delay=p.get('delay'), depth=0, args={}, new=True))
    names = collections.defaultdict(list)
    for tid, t in trig.items():
        if t.get('name'):
            names[t['name'].lower()].append(tid)
    g['edges'] = []
    for tid, t in trig.items():
        for a in t['actions']:
            for h in (names.get((a.get('target_name') or '').lower()) or [])[:1]:
                g['edges'].append(dict(src=tid, action=a['node'], dst=h, kind=_edge_kind(dict(a, short=a.get('short') or ''))))
    _layout(trig, g['edges'])
    g['triggers'] = list(trig.values())
    return g


def _apply_root_set(t, prop, value, en):
    if prop == 'TriggerOn':
        t['trigger_on'] = '%s %s' % (value, (en.get('TRIGGER_ON') or {}).get(str(value), ''))
    elif prop == 'Reactivate':
        t['reactivate'] = value
    elif prop == 'ReactivateDelay':
        t['reactivate_delay'] = value
    elif prop == 'ConditionsNeeded':
        t['needed'] = value
    elif prop == 'name':
        t['name'] = value
    elif prop == 'flags':
        t['disabled'] = bool(int(value) & 1)
