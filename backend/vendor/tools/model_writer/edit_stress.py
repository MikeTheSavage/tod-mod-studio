"""edit_stress.py - exercise the pivot walker / re-serializer with collision edits on every model of the game.

For every MODEL record of every block (read-only on the archive) up to four synthetic edits are made on the decoded
tree, the record is encoded, decoded again (the decoder asserts the serializer's allocation order at every allocation,
so a wrong pointer or a wrong alignment anywhere after the edit fails), re-encoded (must be identical), and compared:
everything except the edited list must be semantically unchanged, and the edited list must hold the intended shapes.
  E1 add a box to the first pivot that has a CollisionList (all later pivot allocations move)
  E2 create a CollisionList on the first pivot that has none
  E3 add a box to the HullList, creating the HullList when the model has none
  E4 remove shape 0 of the first CollisionList with 2+ shapes
"""
import collections, copy, json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import todblock as tb
import todmodel as tm
import model_writer as mw
from model_roundtrip_strict import strip, coll_strip

SENT = 0xBAAFFA00


def norm_spec(m):
    """Semantic view without any pointer word: model_writer.spec_from_model, collision as shape signatures, pointer
    words inside kept raw blobs masked."""
    sp = mw.spec_from_model(m)
    sp['o58'] = sp['o58'][4:0x5C] + sp['o58'][0x60:]
    if sp.get('x40_raw'):
        sp['x40_raw'] = sp['x40_raw'][4:]
    for P in sp['pivots']:
        P['collision'] = None if P['collision'] is None else (P['collision']['flags'], shapes_sig(P['collision']))
        for me in P['meshes']:
            t = me['extra'].get('tail')
            if t is not None and me['kind'] == 'skin':
                me['extra']['tail'] = t[8:]
            elif t is not None and me['kind'] == 'f8':
                me['extra']['tail'] = t[4:16] + t[20:]
    sp['hulls'] = shapes_sig(dict(shapes=sp['hulls'])) if sp['hulls'] is not None else None
    return sp


def shapes_sig(reg):
    if reg is None:
        return None
    return [(s['type'], s.get('verts') or s.get('size'), s.get('faces'), s.get('surf'), s.get('facemat'))
            for s in reg['shapes']]


def check(m_old, m_new, where_key):
    enc = tm.encode(m_new)
    m2 = tm.decode(enc, 0, len(enc))           # asserts the allocation order everywhere
    if tm.encode(m2) != enc:
        return 'reencode'
    want = norm_spec(m_new)
    got = norm_spec(m2)
    if want != got:
        return 'semantic'
    o = norm_spec(m_old)
    kind, idx = where_key
    if kind == 'piv':
        o['pivots'][idx]['collision'] = got['pivots'][idx]['collision']
    else:
        o['hulls'] = got['hulls']
        if 'hulls_w10' in got:
            o['hulls_w10'] = got['hulls_w10']
    if o != got:
        return 'untouched_changed'
    return None


def main():
    arch = tb.Archive(r'C:\GOG Games\Total Overdose\blocks.naz')
    C = collections.Counter(); fails = []
    box = lambda pi: mw.box_shape((-0.5, 0, -0.5), (0.5, 1.0, 0.5), pivot=pi)
    for name in sorted(n for n in arch.names if os.path.splitext(n)[1] in tb.BLOCK_EXTS):
        try:
            b = tb.Block(arch.read(name), os.path.splitext(name)[1]); info = bytes(b.info)
            st = tb.record_starts(info, b.n)
        except Exception:
            continue
        en = st[1:] + [len(info)]
        for k, R in enumerate(st):
            if tb.u32(info, R) != 3:
                continue
            m0 = tm.decode(info, R, en[k])
            pl = [i for i, P in enumerate(m0['pivots']) if P['coll']]
            nl = [i for i, P in enumerate(m0['pivots']) if not P['coll']]
            edits = []
            if pl:
                edits.append(('E1', ('piv', pl[0])))
            if nl:
                edits.append(('E2', ('piv', nl[0])))
            edits.append(('E3', ('hull', None)))
            two = [i for i in pl if len(m0['pivots'][i]['coll']['shapes']) >= 2]
            if two:
                edits.append(('E4', ('piv', two[0])))
            for ename, key in edits:
                m = tm.decode(info, R, en[k])
                if ename == 'E1':
                    c = m['pivots'][key[1]]['coll']
                    s = box(key[1]); s.pop('wrapper_tail', None)
                    c['shapes'] = c['shapes'] + [s]
                elif ename == 'E2':
                    s = box(key[1]); s.pop('wrapper_tail', None)
                    m['pivots'][key[1]]['coll'] = dict(kind='piv', hdr=dict(vec=dict(cnt=1, cap=1, flags=SENT),
                                                                          w10=0x4F | (0x4F << 8) | (0xBAAC << 16)), shapes=[s])
                elif ename == 'E3':
                    s = box(0)
                    if m['hulls']:
                        m['hulls']['shapes'] = m['hulls']['shapes'] + [s]
                    else:
                        m['hulls'] = dict(kind='f54', hdr=dict(vec=dict(cnt=1, cap=1, flags=SENT), w10=0), shapes=[s])
                elif ename == 'E4':
                    c = m['pivots'][key[1]]['coll']
                    c['shapes'] = c['shapes'][1:]
                try:
                    r = check(m0, m, key)
                except Exception as e:
                    r = 'exception ' + repr(e)[:120]
                if r is None:
                    C[ename + '_ok'] += 1
                else:
                    C[ename + '_FAIL'] += 1
                    if len(fails) < 20:
                        fails.append([name.split('/')[-1], k, tb.record_name(info, R), ename, r])
    print(json.dumps(dict(counts=dict(C), fails=fails), indent=1))


if __name__ == '__main__':
    main()
