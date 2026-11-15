"""survey.py - list the placed models of a map whose static collision (ModelAsset+0x54 HullList) could be edited,
with the world AABB of their hulls, so an edit can be put where the player is.

  python -I survey.py OUT.json BLOCK [BLOCK ...]     (the .map first, then its .submap files, then overdose.main)
"""
import sys, os, json, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todcoll as tc
import export_map as em


def main():
    out = sys.argv[1]; paths = sys.argv[2:]
    BS = em.BlockSet(paths)
    ents = em.level_entities(paths)
    rows = []
    hullcache = {}
    for e in ents:
        typ = e['type']
        if not (typ == 'Model' or typ.endswith('(Model)')):
            continue
        ref = e['raw'].get(38)
        ref = ref.get('str') if isinstance(ref, dict) else None
        if not ref or not ref.lower().endswith('.model'):
            continue
        key = em.norm(ref)
        if key not in BS.models:
            continue
        bi, R = BS.models[key]
        info = BS.blocks[bi]['info']
        if key not in hullcache:
            f = tc.deref(info, R + 0x54)
            shapes = []
            if f is not None:
                reg, _ = tc.read_region(info, f, 'f54')
                shapes = reg['shapes']
            npiv = tc.i32(info, R + 0x34)
            pp = tc.deref(info, R + 0x30)
            npl = sum(1 for i in range(npiv) if tc.deref(info, pp + i * 0x7C + 0x44) is not None)
            hullcache[key] = (shapes, npl)
        shapes, npl = hullcache[key]
        T = e['world']
        wb = None
        if shapes:
            pts = [em.apply(T, v) for s in shapes if s['type'] == 4 for v in s['verts']]
            wb = [[min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]]
        rows.append(dict(model=ref, block=os.path.basename(BS.blocks[bi]['path']), fragment=e['fragment'],
                         node=e['nodeId'], name=e['name'], pos=list(T[0]), quat=list(T[1]), hulls=len(shapes),
                         pivot_lists=npl, world_aabb=wb))
    json.dump(rows, open(out, 'w'), indent=1)
    hl = [r for r in rows if r['hulls']]
    print('placed models', len(rows), 'with HullList', len(hl))
    for r in sorted(hl, key=lambda r: r['model']):
        a = r['world_aabb']
        print('%-70s hulls %5d  aabb x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f  %s' % (
            r['model'][-70:], r['hulls'], a[0][0], a[1][0], a[0][1], a[1][1], a[0][2], a[1][2], r['block']))


if __name__ == '__main__':
    main()
