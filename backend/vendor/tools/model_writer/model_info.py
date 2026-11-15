"""model_info.py - the pivot walker as a report: every allocation of a MODEL record in serializer order, the pivots,
submeshes, collision lists and hull list, with offsets (record-relative).

  python -I model_info.py BLOCKFILE MODELNAME-SUBSTRING [--layout] [--json OUT]
"""
import argparse, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import todblock as tb
import todmodel as tm


def f(b, o, n=1):
    return struct.unpack_from('<%df' % n, b, o)


def describe(m):
    out = dict(name=m['name']['s'].decode('latin-1'), record_bytes=m['content_end'],
               header=dict(sphere_centre=f(m['raw'], 0x44, 3), sphere_radius=f(m['raw'], 0x50)[0],
                           w18=hex(struct.unpack_from('<I', m['raw'], 0x18)[0]),
                           w5c=hex(struct.unpack_from('<I', m['raw'], 0x5C)[0])),
               textures=[t['s'].decode('latin-1') for t in m['texnames']], pivots=[])
    for i, P in enumerate(m['pivots']):
        r = P['raw']
        pd = dict(index=i, name=P['name']['s'].decode('latin-1') if P['name'] else None,
                  name2=P['name2']['s'].decode('latin-1') if P['name2'] else None,
                  pos=f(r, 0, 3), quat=f(r, 12, 4), parent=struct.unpack_from('<i', r, 0x58)[0],
                  w5c=struct.unpack_from('<i', r, 0x5C)[0], w60=struct.unpack_from('<i', r, 0x60)[0],
                  box_size=f(r, 0x64, 3), box_centre=f(r, 0x70, 3), submeshes=[],
                  v34=len(P['v34']['data']) // 4, v48=len(P['v48']['data']) // 4)
        for S in P['smbs']:
            M = S['mb']
            sd = dict(flags38=hex(struct.unpack_from('<I', S['raw'], 0x38)[0]),
                      texrefs=list(struct.unpack('<%di' % (len(S['v08']['data']) // 4), S['v08']['data'])),
                      v18=len(S['v18']['data']) // 4, v28=len(S['v28']['data']) // 4)
            if M:
                vb, ib = M['vb_raw'], M['ib_raw']
                sd.update(mb_kind=M['kind'], mb_flags=hex(struct.unpack_from('<I', M['raw'], 4)[0]),
                          verts=struct.unpack_from('<I', vb, 0)[0], fvf=hex(struct.unpack_from('<I', vb, 8)[0]),
                          stride=struct.unpack_from('<H', vb, 0x14)[0], decl=struct.unpack_from('<I', vb, 0x18)[0],
                          indices=struct.unpack_from('<I', ib, 0)[0],
                          prim='list' if struct.unpack_from('<I', ib, 4)[0] else 'strip',
                          bounds_centre=f(M['raw'], 0x24, 3), bounds_radius=f(M['raw'], 0x30)[0],
                          bounds_half=f(M['raw'], 0x34, 3))
            pd['submeshes'].append(sd)
        if P['coll']:
            c = P['coll']
            w10 = c['hdr']['w10']
            pd['collision_list'] = dict(flagsA=w10 & 0xFF, flagsB=(w10 >> 8) & 0xFF, shapes=[shape_desc(s) for s in c['shapes']])
        out['pivots'].append(pd)
    if m['hulls']:
        out['hull_list'] = [shape_desc(s) for s in m['hulls']['shapes']]
    out['x40_vectors'] = len(m['x40']['data']) if m['x40'] else None
    return out


def shape_desc(s):
    if s['type'] == 1:
        return dict(type='box', size=s['size'], centre=s['center'], quat=s['quat'], surf=hex(s['surf']))
    V = s['verts']
    mn = [min(v[i] for v in V) for i in range(3)]; mx = [max(v[i] for v in V) for i in range(3)]
    return dict(type='hull', pivot=s['lowbyte'] & 0x7F, nverts=len(V), nfaces=len(s['faces']), aabb=[mn, mx],
                surf=hex(s['surf']), flags20=hex(s['flags20']), facemat=sorted(set(s['facemat'])),
                aux_name=(s.get('aux') or {}).get('name'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('block'); ap.add_argument('model')
    ap.add_argument('--layout', action='store_true', help='print every allocation')
    ap.add_argument('--json')
    a = ap.parse_args()
    b = tb.Block(open(a.block, 'rb').read(), os.path.splitext(a.block)[1])
    info = bytes(b.info)
    st = tb.record_starts(info, b.n); en = st[1:] + [len(info)]
    hits = [(k, R) for k, R in enumerate(st) if tb.u32(info, R) == 3 and a.model.lower() in tb.record_name(info, R).lower()]
    for k, R in hits:
        m = tm.decode(info, R, en[k])
        d = describe(m)
        d['record_index'] = k; d['record_offset'] = R
        print(json.dumps(d, indent=1, default=lambda x: round(x, 4) if isinstance(x, float) else str(x)))
        if a.layout:
            for off, n, what in m['layout']:
                print('  %06x %6d %s' % (off, n, what))
        if a.json:
            json.dump(d, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
