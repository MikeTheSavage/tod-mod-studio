"""Randomised writer self-test over shipped blocks (read only): for each sampled fragment apply a random mix of
set (new value), set (add a property the entity lacks), move (local and world), clone (shallow and deep) and remove
(an unreferenced leaf), then run fragtool's full block verification. Usage: selftest.py [n_blocks] [seed]"""
import lowprio, sys, os, random, json, time, traceback
sys.dont_write_bytecode = True
import todblock as tb, todfrag as tf, fragedit as fe, fragtool as ft

def main(nblocks=40, seed=1234):
    T = ft.types()
    rnd = random.Random(seed)
    names = sorted(n for n in ft.archive().names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS)
    rnd.shuffle(names)
    res = dict(blocks=0, fragments=0, ops=0, pass_=0, fail=[], skipped=0)
    t0 = time.time()
    for name in names:
        if res['blocks'] >= nblocks:
            break
        raw, entry, ext = ft.load_block_bytes(name)
        b = tb.Block(raw, ext)
        frs, _ = ft.fragments(b)
        frs = [(k, nm) for k, nm in frs if len(tf.Fragment(b.payloads[k], T).records) > 20]
        if not frs:
            continue
        res['blocks'] += 1
        for k, nm in rnd.sample(frs, min(3, len(frs))):
            d = fe.FragDoc(b.payloads[k], T, nm)
            ids = d.created_ids()
            ops = []
            for _ in range(rnd.randint(2, 6)):
                n = rnd.choice(ids)
                kind = rnd.choice(['set', 'add', 'move', 'movew', 'clone', 'deepclone', 'remove'])
                props = d._index()[0].get(n, {})
                if kind == 'set' and props:
                    p = rnd.choice(list(props))
                    t = T.parse(T.ptype(p))
                    if t[0] == 'simple' and t[1] in ('number', 'integer'):
                        ops.append(dict(op='set', fragment=nm, entity='0x%08X' % n, prop='#%d' % p,
                                        value=(rnd.uniform(-100, 100) if t[1] == 'number' else rnd.randint(-5, 500))))
                    elif t[0] == 'string':
                        ops.append(dict(op='set', fragment=nm, entity='0x%08X' % n, prop='#%d' % p,
                                        value='fw_test_%d' % rnd.randint(0, 10**6)))
                elif kind == 'add':
                    cands = [i for i, (pn, pt) in enumerate(T.props) if pt in ('number', 'integer', 'truth', 'vector')
                             and i not in props and i > 711]
                    p = rnd.choice(cands)
                    pt = T.ptype(p)
                    v = {'number': 1.5, 'integer': 7, 'truth': True, 'vector': [1.0, 2.0, 3.0]}[pt]
                    ops.append(dict(op='set', fragment=nm, entity='0x%08X' % n, prop='#%d' % p, value=v))
                elif kind in ('move', 'movew'):
                    ops.append(dict(op='move', fragment=nm, entity='0x%08X' % n,
                                    pos=[rnd.uniform(-300, 300), rnd.uniform(-5, 30), rnd.uniform(-300, 300)],
                                    orient=[0.0, rnd.uniform(-1, 1), 0.0, rnd.uniform(0.1, 1)],
                                    space='world' if kind == 'movew' else 'local'))
                elif kind in ('clone', 'deepclone'):
                    ops.append(dict(op='clone', fragment=nm, entity='0x%08X' % n, deep=(kind == 'deepclone'),
                                    name='fw_clone_%d' % rnd.randint(0, 999)))
                elif kind == 'remove':
                    leaves = [x for x in ids if not d.children(x) and not d.references_to({x})]
                    if leaves:
                        ops.append(dict(op='remove', fragment=nm, entity='0x%08X' % rnd.choice(leaves)))
            # removal after a clone of the same node would be odd but legal; ops on removed nodes are skipped
            seen_removed, ops2 = set(), []
            for o in ops:
                if o['entity'] in seen_removed: continue
                if o['op'] == 'remove': seen_removed.add(o['entity'])
                ops2.append(o)
            if not ops2:
                res['skipped'] += 1; continue
            res['fragments'] += 1; res['ops'] += len(ops2)
            try:
                old, nb, docs, intended = ft.apply_ops(raw, ext, [dict(o, fragment=nm) for o in ops2], T)
                out = nb.serialize()
                ft.verify_block(old, out, ext, docs, intended, T)
                res['pass_'] += 1
            except Exception as e:
                res['fail'].append(dict(block=entry, fragment=nm, ops=ops2, error='%s: %s' % (type(e).__name__, e),
                                        tb=traceback.format_exc()[-600:]))
    res['seconds'] = round(time.time() - t0, 1)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'selftest.json')
    json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps({k: (v if k != 'fail' else len(v)) for k, v in res.items()}))
    for f in res['fail'][:5]:
        print(f['fragment'], f['error'])


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40, int(sys.argv[2]) if len(sys.argv) > 2 else 1234)
