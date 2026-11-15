"""Census of trigger/mission entity types and their enum-like members over every block (mission research).

  python census.py [-o ../out/census.json]

For every create record whose type string names a Trigger_*/mission class, count the values of the integer/truth
members (ActionType, TrueOn, ActivatorType, ActivateWho, TriggerOn, ...). Values are counted per class (the part
of the type string before '(').
"""
import argparse, collections, json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft

KEYS = ('ActionType', 'Sub_Type', 'TrueOn', 'ActivatorType', 'ActivateWho', 'TriggerOn', 'ConditionsNeeded',
        'FireRandomActions', 'NumRandomActions', 'Reactivate', 'Do_What', 'End_Mission_Result', 'Base_Type',
        'Start_Mission', 'Trig_on', 'LastMission', 'SetCondition_True', 'IntervalTrue', 'Method', 'TrigAmount',
        'IsNegation', 'CollisionFlags', 'UseFeedbackText', 'Mission', 'Delay', 'ReactivateDelay', 'StayTime',
        'Mode', 'Type', 'ActionsList')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', default=os.path.join(HERE, '..', 'out', 'census.json'))
    a = ap.parse_args()
    arch = ft.archive()
    T = ft.types()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS)
    cls = collections.defaultdict(lambda: {'count': 0, 'blocks': collections.Counter(),
                                           'members': collections.defaultdict(collections.Counter),
                                           'base': collections.Counter()})
    for nm in names:
        if '/shared/' not in nm and not nm.endswith('.main'):
            continue
        raw, entry, ext = ft.load_block_bytes(nm)
        b = tb.Block(raw, ext)
        frs, _ = ft.fragments(b)
        short = entry.rsplit('/', 1)[-1]
        for k, fnm in frs:
            doc = fe.FragDoc(b.payloads[k], T, fnm)
            for n in doc.created_ids():
                ty = doc.type_of(n) or ''
                c = ty.split('(')[0]
                if not (c.startswith('Trigger') or 'ission' in c or c.startswith('Tutorial') or
                        c in ('Trig_disabler', 'node_trigger_activator', 'cutscene_ctrl', 'default_cutscene')):
                    continue
                d = cls[c]
                d['count'] += 1
                d['blocks'][short] += 1
                d['base'][ty[len(c):]] += 1
                for r in doc.sets_of(n):
                    pn = T.name(r.prop)
                    if pn in KEYS:
                        v = doc.frag.value(r)
                        if isinstance(v, float):
                            v = round(v, 3)
                        if isinstance(v, list):
                            v = len(v)
                        d['members'][pn][str(v)] += 1
    out = {}
    for c in sorted(cls):
        d = cls[c]
        out[c] = dict(count=d['count'], base=dict(d['base']), nblocks=len(d['blocks']),
                      members={k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in d['members'].items()})
    json.dump(out, open(a.o, 'w'), indent=1)
    for c, d in out.items():
        print('%-45s %6d  %s' % (c, d['count'], ' '.join('%s=%s' % (k, dict(list(v.items())[:12]))
                                                       for k, v in d['members'].items()
                                                       if k in ('ActionType', 'TrueOn', 'ActivatorType',
                                                                'ActivateWho', 'TriggerOn', 'Do_What',
                                                                'End_Mission_Result'))))


if __name__ == '__main__':
    main()
