"""near.py - list static hulls (ModelAsset+0x54) of a map near a world point, in world space.

  python -I near.py X Y Z RADIUS BLOCK [BLOCK ...]     (the .map first, then its .submap files, then overdose.main)

Prints per hull: model, hull index, world AABB, vertex/face count, surface word, face materials, and the hull's
horizontal distance to the point. Uses the same placement as export_map.py (fragment Model entities).
"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todcoll as tc
import export_map as em


def hulls_world(paths):
    BS = em.BlockSet(paths)
    ents = em.level_entities(paths)
    cache = {}
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
        if key not in cache:
            cache[key] = (em.model_collision(info, R), em.pivot_world(info, R))
        shapes, PW = cache[key]
        k = 0
        for space, pi, s in shapes:
            idx = k if space == 'model' else 'piv%d' % pi
            if space == 'model':
                k += 1
            M = e['world'] if space == 'model' else em.compose(e['world'], PW[pi])
            if s['type'] != 4:
                vs, _ = em.box_corners_tris(s['size'], s['center'], s['quat'])
                s = dict(s, verts=vs, faces=[], facemat=[])
                idx = 'box-' + str(idx)
            yield dict(model=ref, entity=e, index=idx, shape=s, world=[em.apply(M, v) for v in s['verts']])


def main():
    x, y, z, rad = map(float, sys.argv[1:5])
    paths = sys.argv[5:]
    rows = []
    for h in hulls_world(paths):
        W = h['world']
        mn = [min(v[i] for v in W) for i in range(3)]; mx = [max(v[i] for v in W) for i in range(3)]
        dx = max(mn[0] - x, 0, x - mx[0]); dz = max(mn[2] - z, 0, z - mx[2])
        d = math.hypot(dx, dz)
        if d <= rad and mn[1] - 3 <= y <= mx[1] + 3:
            rows.append((d, h, mn, mx))
    rows.sort(key=lambda r: r[0])
    for d, h, mn, mx in rows:
        s = h['shape']
        print('%5.2f m  %-55s hull %6s  x %8.2f..%8.2f y %6.2f..%6.2f z %8.2f..%8.2f  nv %3d nf %3d surf %08X mats %s' % (
            d, h['model'].split('/')[-1][:55], h['index'], mn[0], mx[0], mn[1], mx[1], mn[2], mx[2], len(s['verts']),
            len(s['faces']), s['surf'], sorted(set(s['facemat']))))


if __name__ == '__main__':
    main()
