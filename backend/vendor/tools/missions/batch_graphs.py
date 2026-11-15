"""Graph + lint every shared .mission block (mission research batch)."""
import json, os, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import missiontool as mt, fragtool as ft
arch = ft.archive()
names = sorted(n for n in arch.names if n.endswith('.mission') and '/shared/' in n)
summary = []
for n in names:
    t0 = time.time()
    B = mt.Block(n); B.add_context(mt.context_for(B))
    G = mt.graph(B)
    base = n.rsplit('/', 1)[-1]
    open(os.path.join(HERE, '..', 'out', 'graphs', base + '.txt'), 'w', encoding='utf-8').write(mt.graph_text(G))
    iss = mt.check(B)
    nt = sum(len(f['triggers']) for f in G)
    na = 0
    def cnt(lst):
        global na
        for a in lst:
            if isinstance(a, dict):
                na += 1; cnt(a.get('then') or [])
    for f in G:
        for t in f['triggers']:
            cnt(t.get('do', []))
    summary.append(dict(block=base, triggers=nt, actions=na, issues=len(iss), issue_list=iss, secs=round(time.time() - t0, 1)))
    print(base, nt, na, len(iss), flush=True)
json.dump(summary, open(os.path.join(HERE, '..', 'out', 'graphs', 'summary.json'), 'w'), indent=1)
