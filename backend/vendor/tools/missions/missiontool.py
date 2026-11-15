"""TOD mission scripting tool (GOG build): read missions as logic graphs, list the story chain and the free-roam
mission loaders, and write mission edits through the fragment writer.

  python missiontool.py chain [-o chain.json] [--txt chain.txt]
        story/sub-mission registry: Missions.fragment index -> folder, block, MissionDict award record
        (map/submap, teleport, intro cutscene, FollowUpMission, objectives), delivery validity, loaders
  python missiontool.py graph <block> [--fragment SUBSTR] [-o graph.json] [--txt graph.txt]
        every trigger root with its conditions and actions decoded (events, activators, actions, targets)
  python missiontool.py spawns <block> [-o spawns.json]      character/vehicle placeholders + who acts on them
  python missiontool.py objectives <block>                    objective actions and the objective records
  python missiontool.py hub [-o hub.json]                     mission loaders in every intermission block
  python missiontool.py check <block|file> [--entry E]        structural lint of a (edited) mission block
  python missiontool.py edit <edit.json> --out DIR [--deploy TESTGAME]   = fragtool.py edit (verified writer)

<block> = archive entry or bare name (mm010_ernestocruz.mission) or a block file on disk (then --entry).
Reads blocks.naz read-only. Enum meanings and their evidence: missionenums.py.
"""
import argparse, collections, json, os, re, struct, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft
import missionenums as me

T = None


def types():
    global T
    if T is None:
        T = ft.types()
    return T


class Block:
    """All fragments of one block, with a case-insensitive name index (the engine's FindNode folds A-Z)."""

    def __init__(self, name, entry=None):
        if os.path.exists(name):
            raw = open(name, 'rb').read()
            ext = os.path.splitext(entry or name)[1].lower()
            self.entry = entry or name
        else:
            raw, self.entry, ext = ft.load_block_bytes(name)
        self.raw = raw
        self.b = tb.Block(raw, ext)
        frs, _ = ft.fragments(self.b)
        self.frags = []
        for k, nm in frs:
            self.frags.append((k, nm, fe.FragDoc(self.b.payloads[k], types(), nm)))
        self.names = collections.defaultdict(list)
        for fi, (k, nm, d) in enumerate(self.frags):
            for n in d.created_ids():
                v = d.get(n, 'name', None)
                if v:
                    self.names[v.lower()].append((fi, n))

    def find(self, name):
        return self.names.get((name or '').lower(), [])

    def add_context(self, others):
        """Other blocks searched when a TargetName is not in this block (overdose.main, the mission's map/submap)."""
        self.context = [o for o in others if o is not None]

    def find_context(self, name):
        for o in getattr(self, 'context', []):
            h = o.find(name)
            if h:
                return o, h
        return None, []


def cls_of(t):
    t = t or ''
    return t.split('(')[0], (t[t.index('('):] if '(' in t else '')


def short(v):
    if isinstance(v, float):
        return float('%.4g' % v)
    if isinstance(v, (list, tuple)):
        return [short(x) for x in v]
    return v


def ent_label(d, n):
    if n in (0, None):
        return 'owner'
    if n == 0xFFFFFFFF:
        return 'none'
    if n not in d.created_ids():
        return '0x%08X?' % n
    return '%s [%s] 0x%08X' % (d.get(n, 'name', '') or '', d.type_of(n), n)


def props(d, n, skip=()):
    out = collections.OrderedDict()
    for r in d.sets_of(n):
        pn = types().name(r.prop)
        if pn in skip:
            continue
        out[pn] = d.frag.value(r)
    return out


NODE_BOILER = {'block_id', 'script_priority', 'order', 'renderordergroup', 'parent', 'disable_on_cutscene',
               'use_aux_quadtree', 'lod_threshold', 'fade_threshold', 'slow_fade', 'traverse_distance',
               'unique_id0', 'unique_id1', 'UserType', 'pos', 'orient', 'name', 'PrintDebug', 'dummy1'}


def resolve_target(B, fi, d, act, p):
    """Static stand-in for the resolver 0x631940 (ActivateWho)."""
    cls, _ = cls_of(d.type_of(act))
    who = p.get('ActivateWho')
    if who is None:
        who = {'Trigger_Activate_Door': 2, 'Trigger_Activate_Weapons': 0, 'Trigger_Activate_Countdown': 0,
               'Trigger_Activate_Prop': 0, 'Trigger_Activate_Overall_Score': 0}.get(cls, 3)
    if who == 0:
        return who, 'player'
    if who == 1:
        return who, None
    if who in (2, 4):
        root = d.get(act, 'parent', 0)
        tgt = d.get(root, 'parent', 0) if root in d.created_ids() else 0
        if who == 4 and tgt in d.created_ids():
            tgt = d.get(tgt, 'parent', 0)
        return who, ent_label(d, tgt) if tgt else 'owner of the fragment instance'
    nm = p.get('TargetName')
    if not nm:
        return who, None
    if cls == 'Trigger_Activate_Cutscene':
        nm = nm + '_player'        # FUN_007E1690 looks up "%s_player" (cutscene_ctrl(MoviePlayer) in Cutscenes.fragment)
    hits = B.find(nm)
    if not hits:
        o, h = B.find_context(nm)
        if h:
            od = o.frags[h[0][0]][2]
            return who, '%s in %s/%s%s' % (ent_label(od, h[0][1]), o.entry.rsplit('/', 1)[-1],
                                           o.frags[h[0][0]][1].rsplit('/', 1)[-1], ' (+%d more)' % (len(h) - 1) if len(h) > 1 else '')
        return who, '%r (not in this block or its context blocks)' % nm
    lab = []
    for hfi, hn in hits[:3]:
        hd = B.frags[hfi][2]
        lab.append('%s%s' % (ent_label(hd, hn), '' if hfi == fi else ' in ' + B.frags[hfi][1].rsplit('/', 1)[-1]))
    return who, '; '.join(lab) + (' (+%d more)' % (len(hits) - 3) if len(hits) > 3 else '')


def describe_action(B, fi, d, a):
    cls, base = cls_of(d.type_of(a))
    p = props(d, a)
    out = collections.OrderedDict(node='0x%08X' % a, name=p.get('name', ''), cls=cls, base=base)
    at = p.get('ActionType')
    dw = p.get('Do_What')
    if at is not None:
        out['ActionType'] = at
        out['does'] = me.action_meaning(cls, at)
    if dw is not None and cls in me.DO_WHAT:
        out['Do_What'] = dw
        out['does'] = me.do_what_meaning(cls, dw)
    who, tgt = resolve_target(B, fi, d, a, p)
    if who is not None:
        out['ActivateWho'] = who
    out['target'] = tgt
    if p.get('Delay'):
        out['delay'] = short(p['Delay'])
    extra = {k: short(v) for k, v in p.items() if k not in NODE_BOILER and k not in
             ('ActionType', 'Do_What', 'ActivateWho', 'Delay', 'Sub_Type', 'flags', 'APBonus')}
    if p.get('APBonus'):
        extra['APBonus'] = p['APBonus']
    out['args'] = extra
    kids = [c for c in d.children(a)]
    if kids:
        out['then'] = [describe_action(B, fi, d, c) if cls_of(d.type_of(c))[0].startswith('Trigger_Activate')
                       else ent_label(d, c) for c in kids]
    return out


def describe_condition(d, c):
    cls, base = cls_of(d.type_of(c))
    p = props(d, c)
    out = collections.OrderedDict(node='0x%08X' % c, name=p.get('name', ''), cls=cls, base=base)
    to = p.get('TrueOn')
    if to is None:
        to = {'Trigger_Condition': 2, 'Trigger_Condition_Logical': 0, 'Trigger_Condition_Mission': 7,
              'Trigger_Condition_Mission_More': 7}.get(cls)
    if cls == 'Trigger_Condition_Logical':
        out['event'] = '%s %s' % (to, me.LOGIC_TRUEON.get(to, ('?',))[0])
    elif cls.startswith('Trigger_Condition_Mission'):
        out['event'] = '%s %s' % (to, me.MISSION_COND_TRUEON.get(to, ('?',))[0])
    else:
        out['event'] = '%s %s' % (to, me.COND_TRUEON.get(to, ('?',))[0])
    at = p.get('ActivatorType', 0 if cls in ('Trigger_Condition', 'Trigger_Condition_Vehicle',
                                              'Trigger_Condition_Counter') else None)
    if at is not None and to != 6:
        out['activator'] = '%s %s' % (at, me.ACTIVATOR_TYPE.get(at, ('?',))[0])
    for k in ('SpecificActivator', 'LastMission', 'IntervalTrue', 'SetCondition_True', 'ShowInHUD', 'HUDName',
              'TrigAmount', 'PointsNeeded', 'IsNegation', 'Specific_Mission', 'APBonus'):
        if k in p and p[k] not in (None, '', 0, False, -1):
            out[k] = short(p[k])
    return out


def describe_root(B, fi, d, r):
    cls, base = cls_of(d.type_of(r))
    p = props(d, r)
    W = d.world(r)
    out = collections.OrderedDict(node='0x%08X' % r, name=p.get('name', ''), cls=cls, base=base,
                                  path=d.path_of(r), world_pos=short(list(W[0])))
    if base == '(CollisionBox)':
        out['box_whl'] = short([p.get('width'), p.get('height'), p.get('length')])
    elif base == '(CollisionSphere)':
        out['radius'] = short(p.get('radius'))
    if 'CollisionFlags' in p:
        out['CollisionFlags'] = p['CollisionFlags']
    if cls == 'Trigger_Root_Mission':
        out['Start_Mission'] = p.get('Start_Mission', -1)
        to = p.get('Trig_on', 0)
        out['starts_on'] = {0: 'player enters', 1: 'player presses USE inside'}.get(to, to)
        out['note'] = 'Command_Start_Load_Mission(Start_Mission, true) (native 0x7FFD60)'
        return out
    to = p.get('TriggerOn', 0)
    out['TriggerOn'] = '%s %s' % (to, me.TRIGGER_ON.get(to, ('?',))[0])
    if to == 2:
        out['ConditionsNeeded'] = short(p.get('ConditionsNeeded'))
    for k in ('Reactivate', 'ReactivateDelay', 'FireRandomActions', 'NumRandomActions'):
        if p.get(k) not in (None, 0, False, 1) or (k == 'Reactivate' and p.get(k)):
            out[k] = short(p.get(k))
    conds, acts, other = [], [], []
    for c in d.children(r):
        ccls = cls_of(d.type_of(c))[0]
        if ccls.startswith('Trigger_Condition'):
            conds.append(describe_condition(d, c))
        elif ccls.startswith('Trigger_Activate') or ccls.startswith('Trigger_Lock'):
            acts.append(describe_action(B, fi, d, c))
        else:
            other.append(ent_label(d, c))
    out['if'] = conds
    out['do'] = acts
    if other:
        out['children'] = other
    return out


def graph(B, fsub=None):
    res = []
    for fi, (k, nm, d) in enumerate(B.frags):
        if fsub and fsub.lower() not in nm.lower():
            continue
        roots = [n for n in d.created_ids() if cls_of(d.type_of(n))[0] in
                 ('Trigger_Root', 'Trigger_Root_Mission', 'Trigger_Root_ZAP', 'Trigger_Root_Menu', 'Trigger_direct')]
        if not roots:
            continue
        res.append(dict(fragment=nm, record=k, triggers=[describe_root(B, fi, d, r) for r in roots]))
    return res


def graph_text(G):
    L = []
    for f in G:
        L.append('=== %s (%d triggers)' % (f['fragment'], len(f['triggers'])))
        for t in f['triggers']:
            geo = ('box %s' % t['box_whl']) if 'box_whl' in t else ('sphere r=%s' % t['radius'] if 'radius' in t else 'no volume')
            L.append('TRIGGER %s  [%s%s]  %s  at %s, %s' % (t['name'], t['cls'], t['base'], t['node'],
                                                            t['world_pos'], geo))
            L.append('   path %s' % t['path'])
            if t['cls'] == 'Trigger_Root_Mission':
                L.append('   starts mission %s when %s' % (t['Start_Mission'], t['starts_on']))
                continue
            L.append('   fires when: %s%s' % (t['TriggerOn'], ''.join('; %s=%s' % (k, t[k]) for k in
                     ('ConditionsNeeded', 'Reactivate', 'ReactivateDelay', 'FireRandomActions', 'NumRandomActions')
                     if k in t)))
            for c in t['if']:
                ev = re.split(r'[:(;]', c['event'])[0].strip()[:70]
                L.append('   IF  %-40s [%s] on %s%s%s' % (c['name'], c['cls'], ev,
                         (' by ' + re.split(r'[(:]', c['activator'])[0].strip()) if 'activator' in c else '',
                         ''.join(' %s=%s' % (k, c[k]) for k in c if k not in ('node', 'name', 'cls', 'base', 'event', 'activator'))))

            def acts(lst, ind):
                for a in lst:
                    if isinstance(a, str):
                        L.append('%s   (child %s)' % (ind, a))
                        continue
                    code = a.get('ActionType', a.get('Do_What', ''))
                    does = (a.get('does') or '')
                    does = re.split(r'[:(;]', does)[0].strip()[:60]
                    L.append('%sDO  %-40s [%s %s] %s -> %s%s' % (ind, a['name'], a['cls'].replace('Trigger_Activate_', ''),
                             code, does, a.get('target'),
                             (' after %ss' % a['delay']) if a.get('delay') else ''))
                    if a['args']:
                        L.append('%s      %s' % (ind, ', '.join('%s=%s' % kv for kv in a['args'].items())[:300]))
                    if a.get('then'):
                        acts(a['then'], ind + '      ')
            acts(t['do'], '   ')
    return '\n'.join(L) + '\n'


def spawns(B):
    acts_on = collections.defaultdict(list)
    for f in graph(B):
        for t in f['triggers']:
            def walk(lst):
                for a in lst:
                    if isinstance(a, str):
                        continue
                    tg = a.get('target') or ''
                    for m in re.finditer(r'0x([0-9A-F]{8})', tg):
                        acts_on[int(m.group(1), 16)].append('%s:%s(%s) by trigger %s' % (
                            a['cls'].replace('Trigger_Activate_', ''), a.get('ActionType', a.get('Do_What', '')),
                            a.get('does') or '', t['name']))
                    walk(a.get('then') or [])
            walk(t.get('do', []))
    out = []
    for fi, (k, nm, d) in enumerate(B.frags):
        for n in d.created_ids():
            cls, base = cls_of(d.type_of(n))
            if cls not in ('character_placeholder', 'vehicle_placeholder', 'traffic_vehicle_placeholder',
                           'weapon_placeholder', 'goodie_placeholder', 'animal_placeholder'):
                continue
            p = props(d, n)
            W = d.world(n)
            rec = collections.OrderedDict(fragment=nm.rsplit('/', 1)[-1], node='0x%08X' % n, name=p.get('name', ''),
                                          cls=cls, path=d.path_of(n), world_pos=short(list(W[0])),
                                          flags=p.get('flags', 0), disabled_at_load=bool((p.get('flags') or 0) & 1))
            for kk in ('Model', 'AISubType', 'FactionID', 'Morale', 'MissionObjectiveKill', 'IsVIP', 'DontHunt',
                       'Goto_Movement', 'Health_mod', 'Damage_mod', 'ResourceType', 'Sub_Type', 'Vehicle_Model'):
                if kk in p:
                    rec[kk] = short(p[kk])
            kids = [ent_label(d, c) for c in d.children(n)]
            if kids:
                rec['children'] = kids
            rec['acted_on_by'] = acts_on.get(n, [])
            out.append(rec)
    return out


# ------------------------------------------------------------------------------------------------------- chain
MAIN_CACHE = {}


def context_for(B):
    """overdose.main always; for a .mission block also its map and submap (from the MissionDict award record)."""
    out = []
    if 'main' not in MAIN_CACHE:
        MAIN_CACHE['main'] = Block('overdose.main')
    if not B.entry.endswith('overdose.main'):
        out.append(MAIN_CACHE['main'])
    if B.entry.endswith('.mission'):
        if 'chain' not in MAIN_CACHE:
            MAIN_CACHE['chain'] = chain()
        C = MAIN_CACHE['chain']
        base = B.entry.rsplit('/', 1)[-1].lower()
        for r in C['missions']:
            if (r.get('block') or '').lower() == base:
                arch = ft.archive()
                for nm in (r.get('map'), r.get('submap')):
                    if not nm:
                        continue
                    for e in arch.names:
                        if '/shared/' in e and e.rsplit('/', 1)[-1].lower().startswith(nm.lower() + '.'):
                            out.append(Block(e))
                break
    return out


def chain():
    M = Block('overdose.main')
    def frag(sub):
        for fi, (k, nm, d) in enumerate(M.frags):
            if nm.endswith(sub):
                return d
    mis, mdict, scene = frag('/Missions.fragment'), frag('/MissionDict.fragment'), frag('/Overdose.scene')
    maps, submaps = {}, {}
    for n in scene.created_ids():
        c = cls_of(scene.type_of(n))[0]
        if c == 'database_Map_ID':
            maps[scene.get(n, 'Specific_ID')] = scene.get(n, 'name')
        elif c == 'database_SubMap_ID':
            submaps[scene.get(n, 'Specific_ID')] = scene.get(n, 'name')
    valid = {}
    for n in scene.created_ids():
        if scene.get(n, 'name') == 'CompleteGame':
            for r in scene.sets_of(n):
                pn = types().name(r.prop)
                if pn.startswith('Valid_'):
                    valid[pn[6:]] = scene.frag.value(r)
    # fragment path -> block
    arch = ft.archive()
    where = {}
    for nm in arch.names:
        if '/shared/' in nm and nm.endswith('.mission'):
            raw = arch.read(nm)
            for m in re.finditer(rb'/data/Overdose_THE_GAME/Missions/[^\x00]+?\.fragment', raw):
                where.setdefault(m.group(0).decode('latin-1').lower(), nm.rsplit('/', 1)[-1])
    idx = {}
    folders = {}
    for n in mis.created_ids():
        fp = mis.get(n, 'fragment')
        if fp:
            folders[(mis.get(n, 'name') or '').lower()] = fp
    for n in mis.created_ids():
        if cls_of(mis.type_of(n))[0] == 'database_Mission_ID':
            fp = mis.get(n, 'fragment')
            key = ('/data' + fp if fp.startswith('/') else fp).lower()
            idx[mis.get(n, 'Mission')] = dict(folder=mis.get(n, 'name'), fragment=fp,
                                              block=where.get(key) or where.get(key.replace('/data/data', '/data')))
    awards = {}
    for n in mdict.created_ids():
        if cls_of(mdict.type_of(n))[0] == 'database_mission_award':
            p = props(mdict, n, NODE_BOILER)
            objs = []
            for c in mdict.children(n):
                if cls_of(mdict.type_of(c))[0] == 'database_mission_objective':
                    q = props(mdict, c, NODE_BOILER)
                    objs.append(dict(name=mdict.get(c, 'name'), DisplayText=q.get('DisplayText'),
                                     counter=q.get('HasObjectivesCounter'), MaxCounter=q.get('MaxCounter'),
                                     AutoCompleteOnMax=q.get('AutoCompleteOnMax')))
            p['objectives'] = objs
            p['record_name'] = mdict.get(n, 'name')
            awards[p.get('Mission')] = p
    def blk(fp):
        if not fp:
            return None
        if not fp.lower().startswith('/data/'):
            fp = '/data/Overdose_THE_GAME/Missions/' + fp if not fp.startswith('/') else '/data' + fp
        return where.get(fp.lower())
    rows = []
    for i in sorted(set(idx) | set(awards)):
        a = awards.get(i, {})
        r = collections.OrderedDict(index=i)
        if i in idx:
            r.update(idx[i])
            r['block'] = blk(idx[i]['fragment'])
        elif a.get('Mission_Folder'):
            fp = folders.get(a['Mission_Folder'].lower())
            r.update(dict(folder=a['Mission_Folder'], fragment=fp, block=blk(fp)))
        r.update(dict(award_record=a.get('record_name'), type={0: 'story', 1: 'sub', 2: 'intermission'}.get(
            a.get('Mission_Type'), a.get('Mission_Type')), place=a.get('PlaceInList'),
            map=maps.get(a.get('Mission_Map')), submap=submaps.get(a.get('Mission_SubMap')),
            teleport=a.get('Teleport_to_on_start'), intro_cutscene=a.get('CutsceneToPlay'),
            FollowUpMission=a.get('FollowUpMission'), Sub_To_Activate=a.get('Sub_To_Activate'),
            NoEndMissionScreen=a.get('NoEndMissionScreen'), Is_Tutorial=a.get('Is_Tutorial'),
            min_score_award3=a.get('Award_3_ActionPoints'), objectives=a.get('objectives', [])))
        rows.append(r)
    return dict(maps=maps, submaps=submaps, delivery_valid_complete_game=valid, missions=rows)


def hub():
    arch = ft.archive()
    out = []
    for nm in sorted(arch.names):
        if '/shared/' not in nm or not nm.endswith('.mission'):
            continue
        short_nm = nm.rsplit('/', 1)[-1]
        if not (short_nm.startswith('intermission') or short_nm.startswith('gameover')):
            continue
        B = Block(nm)
        for fi, (k, fnm, d) in enumerate(B.frags):
            for n in d.created_ids():
                cls, base = cls_of(d.type_of(n))
                if cls == 'Trigger_Root_Mission':
                    W = d.world(n)
                    out.append(dict(block=short_nm, fragment=fnm.rsplit('/', 1)[-1], kind='mission marker (Trigger_Root_Mission)',
                                    name=d.get(n, 'name'), start_mission=d.get(n, 'Start_Mission'),
                                    trig_on=d.get(n, 'Trig_on'), pos=short(list(W[0]))))
                elif cls == 'Trigger_Activate_Cutscene' and (d.get(n, 'Start_Mission', -1) or -1) >= 0:
                    root = d.get(n, 'parent', 0)
                    W = d.world(root) if root in d.created_ids() else d.world(n)
                    out.append(dict(block=short_nm, fragment=fnm.rsplit('/', 1)[-1], kind='story loader (cutscene)',
                                    name=d.get(root, 'name') if root in d.created_ids() else '',
                                    start_mission=d.get(n, 'Start_Mission'), cutscene=d.get(n, 'TargetName'),
                                    radar_on_submap=d.get(n, 'Radar_on_Submap'), pos=short(list(W[0]))))
    return out


# ------------------------------------------------------------------------------------------------------- check
def check(B):
    """Lint: every trigger has conditions and actions, every TargetName resolves in the block or is a known
    global/cutscene name, TrueOn/ActionType values are known for the class."""
    issues = []
    G = graph(B)
    for f in G:
        for t in f['triggers']:
            if t['cls'] == 'Trigger_Root_Mission':
                continue
            if not t['if']:
                issues.append('%s: trigger %s has no condition' % (f['fragment'], t['name']))
            if not t['do']:
                issues.append('%s: trigger %s has no action' % (f['fragment'], t['name']))
            for c in t['if']:
                if '?' in c['event']:
                    issues.append('%s: %s/%s unknown event %s' % (f['fragment'], t['name'], c['name'], c['event']))

            def walk(lst):
                for a in lst:
                    if isinstance(a, str):
                        continue
                    if 'ActionType' in a and a['cls'] in me.ACTION and a.get('does') is None:
                        issues.append('%s: %s/%s ActionType %s not used by %s' % (f['fragment'], t['name'], a['name'],
                                                                                 a['ActionType'], a['cls']))
                    if a.get('target') and 'not in this block or its context' in a['target'] and a['cls'] not in (
                            'Trigger_Activate_Cutscene', 'Trigger_Activate_Load_Unload_Save', 'Trigger_Activate_Sound'):
                        issues.append('%s: %s/%s target %s' % (f['fragment'], t['name'], a['name'], a['target']))
                    walk(a.get('then') or [])
            walk(t['do'])
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('chain'); p.add_argument('-o'); p.add_argument('--txt')
    p = sp.add_parser('graph'); p.add_argument('block'); p.add_argument('--entry'); p.add_argument('--fragment')
    p.add_argument('--no-context', action='store_true')
    p.add_argument('-o'); p.add_argument('--txt')
    p = sp.add_parser('spawns'); p.add_argument('block'); p.add_argument('--entry'); p.add_argument('-o')
    p = sp.add_parser('objectives'); p.add_argument('block'); p.add_argument('--entry')
    p = sp.add_parser('hub'); p.add_argument('-o')
    p = sp.add_parser('check'); p.add_argument('block'); p.add_argument('--entry')
    p = sp.add_parser('edit'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    a = ap.parse_args()
    if a.cmd == 'chain':
        C = chain()
        txt = ['%3s %-6s %-34s %-38s %-26s FU  intro cutscene / teleport' % ('idx', 'type', 'folder', 'block', 'map/submap')]
        for r in C['missions']:
            txt.append('%3s %-6s %-34s %-38s %-26s %-3s %s / %s' % (r['index'], r.get('type'), r.get('folder'),
                       r.get('block'), (r.get('submap') or ''), r.get('FollowUpMission'), r.get('intro_cutscene'),
                       r.get('teleport')))
            for o in r['objectives']:
                txt.append('      objective %-40s text %s%s' % (o['name'], o['DisplayText'],
                           ' counter max %s%s' % (o['MaxCounter'], ' auto-complete' if o['AutoCompleteOnMax'] else '')
                           if o['counter'] else ''))
        if a.o:
            json.dump(C, open(a.o, 'w'), indent=1)
        t = '\n'.join(txt) + '\n'
        if a.txt:
            open(a.txt, 'w', encoding='utf-8').write(t)
        else:
            sys.stdout.write(t)
    elif a.cmd == 'graph':
        B = Block(a.block, a.entry)
        if not a.no_context:
            B.add_context(context_for(B))
        G = graph(B, a.fragment)
        if a.o:
            json.dump(G, open(a.o, 'w'), indent=1)
        t = graph_text(G)
        if a.txt:
            open(a.txt, 'w', encoding='utf-8').write(t)
            print('wrote', a.txt, sum(len(f['triggers']) for f in G), 'triggers')
        elif not a.o:
            sys.stdout.write(t)
    elif a.cmd == 'spawns':
        S = spawns(Block(a.block, a.entry))
        if a.o:
            json.dump(S, open(a.o, 'w'), indent=1)
        for s in S:
            print('%-12s %-40s %-24s %s %s%s' % (s['node'], s['name'] or '-', s['cls'], s['world_pos'],
                  'DISABLED ' if s['disabled_at_load'] else '', ' | '.join(s['acted_on_by'][:3])))
    elif a.cmd == 'objectives':
        B = Block(a.block, a.entry)
        for f in graph(B):
            for t in f['triggers']:
                def walk(lst):
                    for x in lst:
                        if isinstance(x, str):
                            continue
                        if x['cls'] == 'Trigger_Activate_Objective':
                            print('%-45s %-4s %-40s -> %s  [trigger %s]' % (x['name'], x.get('ActionType'), x.get('does'),
                                  x['args'].get('TargetName'), t['name']))
                        walk(x.get('then') or [])
                walk(t.get('do', []))
    elif a.cmd == 'hub':
        H = hub()
        if a.o:
            json.dump(H, open(a.o, 'w'), indent=1)
        for h in H:
            print('%-40s %-26s mission %3s %-50s %s' % (h['block'], h['kind'], h['start_mission'], h['name'], h['pos']))
    elif a.cmd == 'check':
        B = Block(a.block, a.entry)
        B.add_context(context_for(B))
        iss = check(B)
        print('\n'.join(iss) if iss else 'no issues')
        print('%d issues' % len(iss))
    elif a.cmd == 'edit':
        sys.argv = ['fragtool.py', 'edit', a.edit, '--out', a.out] + (['--deploy', a.deploy] if a.deploy else [])
        ft.main()


if __name__ == '__main__':
    main()
