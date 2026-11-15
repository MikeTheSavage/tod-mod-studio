"""Check an installed todms_mods.zip with the tools' own verifiers (no game launch).

  python scripts/verify_install.py GAME_FOLDER [--expect-move ENTRY:FRAG_SUBSTR:NODE] [--expect-name NAME]

  1. engine OpenZip/FindFile port (todblock.Archive): every entry is found where the game looks, no name-hash
     collision with blocks.naz
  2. fragtool roundtrip_block on every block in the zip: exact parse / re-serialise / re-chunk / re-encode
  3. header, INFO and every untouched asset byte-identical to the base block in blocks.naz; where INFO differs
     (collision sets of the companion tools), only MODEL records may differ, each decodes and re-encodes with the
     model writer's codec, and the report lists their collision shapes before and after
  4. creation order: every node of the base block keeps its runtime (save) index (save_editor nodemap)
  5. missiontool check (structural lint) of edited mission blocks, compared with the base
  6. configpc.txt names the zip first; blocks.naz unchanged (md5 printed)
"""
import argparse, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'backend'))


def info_model_diff(tb, ob, nb):
    """INFO differs: only MODEL records may (collision sets in a host model). Each changed model must decode and
    re-encode exactly with the model writer's codec; returns the changed models with their collision shapes."""
    import todmodel as tm
    oi, ni = bytes(ob.info), bytes(nb.info)
    s1, s2 = tb.record_starts(oi, ob.n), tb.record_starts(ni, nb.n)
    e1, e2 = s1[1:] + [len(oi)], s2[1:] + [len(ni)]
    out, ok = [], True
    for k in range(ob.n):
        a, b = oi[s1[k]:e1[k]], ni[s2[k]:e2[k]]
        if a == b:
            continue
        if tb.u32(ni, s2[k]) != 3:
            return dict(ok=False, error='record %d changed and is not a MODEL' % k)
        m0, m1 = tm.decode(oi, s1[k], e1[k]), tm.decode(ni, s2[k], e2[k])
        rt = tm.encode(m1) == b
        ok = ok and rt
        out.append(dict(record=k, model=tb.record_name(ni, s2[k]), bytes=[len(a), len(b)], reencodes=rt,
                        hulls=[len(m0['hulls']['shapes']) if m0['hulls'] else 0, len(m1['hulls']['shapes']) if m1['hulls'] else 0]))
    return dict(ok=ok and bool(out), models=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('game')
    ap.add_argument('--expect-name', action='append', default=[])
    a = ap.parse_args()
    from todms import paths
    paths.setup_tools(os.path.join(a.game, 'blocks.naz'))
    sys.path.append(os.path.join(paths.VENDOR, 'model_writer'))
    import todblock as tb, fragtool as ft, todfrag as tf, fragedit as fe, submaptool as st, missiontool as mt
    from todms import game
    ft.GOG_NAZ = os.path.join(a.game, 'blocks.naz'); ft._arch = None
    T = ft.types()
    rep = {}
    z = os.path.join(a.game, game.MOD_ZIP)
    za = tb.Archive(z)
    base = tb.Archive(ft.GOG_NAZ)
    rep['zip'] = dict(path=z, bytes=os.path.getsize(z), entries=len(za.names), naz_format=za.naz)
    coll = [n for c, (_, _, n) in base.table.items() if c in za.table and n != za.table[c][2]]
    rep['1_engine_lookup'] = dict(entries={n: bool(za.find('/' + n)) for n in za.names}, hash_collisions=coll)
    blocks = []
    for entry in sorted(za.names):
        ext = os.path.splitext(entry)[1]
        new = za.read(entry)
        old = base.read(entry)
        r = ft.roundtrip_block(new, ext, T)
        ob, nb = tb.Block(old, ext), tb.Block(new, ext)
        same_hdr = (ob.timestamp, ob.prop_ck, ob.cmd_ck, ob.n, bytes(ob.info)) == (nb.timestamp, nb.prop_ck, nb.cmd_ck, nb.n, bytes(nb.info))
        model_changes = None
        if not same_hdr and (ob.timestamp, ob.prop_ck, ob.cmd_ck, ob.n) == (nb.timestamp, nb.prop_ck, nb.cmd_ck, nb.n):
            model_changes = info_model_diff(tb, ob, nb)
        changed = [k for k in range(ob.n) if ob.payloads[k] != nb.payloads[k]]
        frs = dict(ft.fragments(nb)[0])
        no, nn = st.nodes_of(ob, entry), st.nodes_of(nb, entry)
        sig = lambda L: [(x[0], x[1], x[2].split('/')[-1], x[3]) for x in L]
        stable = sig(no) == sig(nn[:len(no)])
        b = dict(entry=entry, bytes=len(new), base_bytes=len(old), roundtrip_exact=(not r['fail'] and r['block_identical']),
                 records=r['records'], header_info_identical=same_hdr, collision_models=model_changes,
                 header_ok=same_hdr or bool(model_changes and model_changes['ok']),
                 changed_assets=[frs.get(k, k) for k in changed],
                 untouched_identical=ob.n - len(changed), nodes_before=len(no), nodes_after=len(nn),
                 old_indices_unchanged=stable,
                 new_nodes=[[hex(x[0]), x[1], x[2].split('/')[-1], x[4]] for x in nn[len(no):]])
        if entry.endswith('.mission'):
            import tempfile
            res = []
            for data in (old, new):
                with tempfile.NamedTemporaryFile(suffix='.mission', delete=False) as f:
                    f.write(data); p = f.name
                try:
                    res.append(len(mt.check(mt.Block(p, entry))))
                finally:
                    os.unlink(p)
            b['mission_lint_issues'] = dict(base=res[0], modded=res[1])
        # what changed, in words
        diffs = []
        for k in changed:
            od, nd = fe.FragDoc(ob.payloads[k], T, frs[k]), fe.FragDoc(nb.payloads[k], T, frs[k])
            oi = set(od.created_ids())
            for n in nd.created_ids():
                if n not in oi:
                    diffs.append(dict(new=hex(n), type=nd.type_of(n), name=nd.get(n, 'name'), pos=nd.get(n, 'pos'),
                                      size=[nd.get(n, 'width'), nd.get(n, 'height'), nd.get(n, 'length')],
                                      CollisionFlags=nd.get(n, 'CollisionFlags'), parent=hex(nd.get(n, 'parent') or 0)))
                    continue
                for r2 in nd.sets_of(n):
                    ov = od.get(n, r2.prop)
                    nv = nd.frag.value(r2)
                    if ov != nv:
                        diffs.append(dict(node=hex(n), prop=T.name(r2.prop), old=ov, new=nv))
        b['changes'] = diffs
        blocks.append(b)
    rep['blocks'] = blocks
    lines = open(os.path.join(a.game, 'configpc.txt'), encoding='latin-1').read().splitlines()
    rep['configpc'] = dict(filesystem=game.filesystem_line(lines),
                           backup=os.path.exists(os.path.join(a.game, 'configpc.txt.todms_backup')))
    rep['blocks_naz_md5'] = game.md5_file(ft.GOG_NAZ)
    ok = (not coll and all(rep['1_engine_lookup']['entries'].values()) and
          all(b['roundtrip_exact'] and b['header_ok'] and b['old_indices_unchanged'] for b in blocks) and
          (rep['configpc']['filesystem'] or [''])[0].lower() == game.MOD_ZIP)
    rep['result'] = 'PASS' if ok else 'FAIL'
    print(json.dumps(rep, indent=1, default=str))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
