"""placed.py - list the placed Model entities of a map near a world point, with what each model carries.

  python -I placed.py X Y Z RADIUS BLOCK [BLOCK ...]     (the .map first, then its .submap files, then overdose.main)

Columns: horizontal distance, model, block that holds the MODEL record, entity world position, pivots, submeshes,
vertices, per-pivot CollisionLists (shapes), HullList shapes, model bounding radius.
"""
import sys, os, math, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todmodel as tm
import export_map as em


def summary(info, R):
    m = tm.decode(info, R)
    nsmb = sum(len(P['smbs']) for P in m['pivots'])
    nv = sum(struct.unpack_from('<I', S['mb']['vb_raw'], 0)[0] for P in m['pivots'] for S in P['smbs'] if S['mb'])
    pl = [(i, len(P['coll']['shapes'])) for i, P in enumerate(m['pivots']) if P['coll']]
    hl = len(m['hulls']['shapes']) if m['hulls'] else 0
    rad = struct.unpack_from('<f', m['raw'], 0x50)[0]
    return dict(piv=len(m['pivots']), smb=nsmb, nv=nv, pl=pl, hl=hl, rad=rad)


def main():
    x, y, z, rad = map(float, sys.argv[1:5])
    paths = sys.argv[5:]
    BS = em.BlockSet(paths)
    rows = []
    cache = {}
    for e in em.level_entities(paths):
        typ = e['type']
        if not (typ == 'Model' or typ.endswith('(Model)')):
            continue
        ref = e['raw'].get(38)
        ref = ref.get('str') if isinstance(ref, dict) else None
        if not ref or not ref.lower().endswith('.model'):
            continue
        key = em.norm(ref)
        p = e['world'][0]
        d = math.hypot(p[0] - x, p[2] - z)
        if d > rad:
            continue
        if key not in BS.models:
            rows.append((d, ref, '(not in these blocks)', p, None)); continue
        bi, R = BS.models[key]
        if key not in cache:
            cache[key] = summary(BS.blocks[bi]['info'], R)
        rows.append((d, ref, os.path.basename(BS.blocks[bi]['path']), p, cache[key]))
    rows.sort(key=lambda r: r[0])
    for d, ref, blk, p, s in rows:
        if s is None:
            print('%6.2f m %-50s %s' % (d, ref.split('/')[-1][:50], blk)); continue
        print('%6.2f m %-44s %-34s pos %8.2f %6.2f %8.2f piv %2d smb %2d nv %5d pivlists %-14s hulls %4d R %.2f' % (
            d, ref.split('/')[-1][:44], blk[:34], p[0], p[1], p[2], s['piv'], s['smb'], s['nv'], s['pl'], s['hl'], s['rad']))


if __name__ == '__main__':
    main()
