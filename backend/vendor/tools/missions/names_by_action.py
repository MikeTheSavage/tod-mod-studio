"""Sample authored entity names per (class, ActionType / Do_What / TrueOn / ActivatorType) value over all shared blocks."""
import collections, json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import todblock as tb, fragedit as fe, fragtool as ft
arch = ft.archive(); T = ft.types()
KEYS = ('ActionType', 'Do_What', 'TrueOn', 'ActivatorType', 'ActivateWho', 'TriggerOn', 'End_Mission_Result')
res = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for nm in sorted(arch.names):
    if os.path.splitext(nm)[1].lower() not in tb.BLOCK_EXTS or ('/shared/' not in nm): continue
    raw, entry, ext = ft.load_block_bytes(nm); b = tb.Block(raw, ext); frs, _ = ft.fragments(b)
    for k, fnm in frs:
        doc = fe.FragDoc(b.payloads[k], T, fnm)
        for n in doc.created_ids():
            ty = doc.type_of(n) or ''; c = ty.split('(')[0]
            if not c.startswith('Trigger'): continue
            name = doc.get(n, 'name', '') or ''
            par = doc.get(n, 'parent', 0)
            pname = (doc.get(par, 'name', '') or '') if par in doc.created_ids() else ''
            for kk in KEYS:
                v = doc.get(n, kk, None)
                if v is None: continue
                if isinstance(v, float): v = round(v, 3)
                res[c]['%s=%s' % (kk, v)][name or ('<'+pname+'>')] += 1
out = {c: {k: v.most_common(14) for k, v in d.items()} for c, d in res.items()}
json.dump(out, open('../out/names_by_action.json', 'w'), indent=1)
for c in sorted(out):
    for k in sorted(out[c], key=lambda s: (s.split('=')[0], int(float(s.split('=')[1])) if s.split('=')[1].lstrip('-').replace('.','').isdigit() else 0)):
        if k.startswith(('ActionType', 'Do_What', 'TrueOn', 'ActivatorType')):
            print('%s %s: %s' % (c, k, ', '.join('%s(%d)' % x for x in out[c][k][:8])))
