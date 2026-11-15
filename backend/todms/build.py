"""Turn editor changes into rebuilt blocks, verified by the tools' own checks, and one override zip.

Edits (one list per mod, applied in mod order) use stable keys: block entry, fragment name, node id.

  {"op": "move",   "entry": E, "frag": F, "node": "0x..", "pos": [x,y,z], "rot": [x,y,z,w]}   world, true rotation
  {"op": "set",    "entry": E, "frag": F, "node": "0x..", "prop": "name", "value": V}
  {"op": "delete", "entry": E, "frag": F, "node": "0x..", "mode": "retire" | "remove"}
  {"op": "add",    "uid": "n1", "entry": E, "template": {"entry": E2, "frag": F2, "node": "0x.."},
                   "name": "...", "pos": [..], "rot": [..], "set": {prop: value}}
  {"op": "frag",   "entry": E, "ops": [fragment writer ops]}         raw ops (the data editors produce these)

Per block:
  stage A  move / set / disable / remove / raw ops through the fragment writer (fragtool.apply_ops) and its full
           verification (fragtool.verify_block: only the intended records change, no dangling references, ...)
  stage B  adds as save-safe grafts: the new entities are appended to the fragment the engine instantiates LAST in
           the block (so no existing node changes its save index), parented to that fragment's owner (entity 0), the
           same rule as the Unreal TODLevelEditor; submaptool.verify then checks that every existing node keeps its
           runtime index. Delete = retire (moved 5 km below the world, collision flags 0), also as there.
  finally  fragtool.roundtrip_block on the result (exact parse / re-serialise) and the engine OpenZip/FindFile
           read-back of the zip (fragtool.write_zip).
"""
import hashlib
import json
import os
import random
import struct

import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft
import submaptool as smt

from . import level as lv

BLOCK_BITS = lv.BLOCK_BITS


class BuildError(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def _node(v):
    return int(v, 16) if isinstance(v, str) else int(v)


def _frag_sel(frs, name):
    """Full fragment record name -> the same name (fragtool.pick_fragment accepts the exact name)."""
    for k, nm in frs:
        if nm == name:
            return nm
    short = name.replace('\\', '/').split('/')[-1].lower()
    hits = [nm for k, nm in frs if nm.replace('\\', '/').split('/')[-1].lower() == short]
    if len(hits) != 1:
        raise BuildError('fragment %s not found in the block' % name)
    return hits[0]


def _entity_values(T, prop, raw):
    t = T.parse(T.ptype(prop))
    if 'entity' not in repr(t):
        return []
    out = []

    def walk(v, t):
        if t[0] == 'entity':
            out.append(v)
        elif t[0] == 'list':
            for x in v:
                walk(x, t[1])
        elif t[0] == 'dict':
            for _, x in v:
                walk(x, t[1])
        elif t[0] == 'struct':
            for fn, ftp in t[2]:
                walk(v[fn], ftp)
    walk(tf.decode_value(raw, 0, t), t)
    return out


def _remap(T, prop, raw, fn):
    t = T.parse(T.ptype(prop))
    v = tf.decode_value(raw, 0, t)

    def walk(v, t):
        if t[0] == 'entity':
            return fn(v)
        if t[0] == 'list':
            return [walk(x, t[1]) for x in v]
        if t[0] == 'dict':
            return [[k, walk(x, t[1])] for k, x in v]
        if t[0] == 'struct':
            return {f: walk(v[f], ft_) for f, ft_ in t[2]}
        return v
    return tf.encode_value(walk(v, t), t)


# ---------------------------------------------------------------------------------------------- stage A
def stage_a(entry, raw, ops, T, report):
    ext = os.path.splitext(entry)[1]
    b = tb.Block(raw, ext)
    frs, _ = ft.fragments(b)
    fops = []
    docs = {}

    def doc(nm):
        if nm not in docs:
            k = [k for k, n in frs if n == nm][0]
            docs[nm] = fe.FragDoc(b.payloads[k], T, nm)
        return docs[nm]
    for op in ops:
        kind = op['op']
        if kind == 'frag':
            fops += op['ops']
            continue
        nm = _frag_sel(frs, op['frag'])
        n = _node(op['node'])
        if kind == 'move':
            o = dict(op='move', fragment=nm, entity='0x%08X' % n, space='world')
            if op.get('pos') is not None:
                o['pos'] = [float(x) for x in op['pos']]
            if op.get('rot') is not None:
                o['orient'] = list(fe.qconj(fe.qnorm([float(x) for x in op['rot']])))
            fops.append(o)
        elif kind == 'set':
            fops.append(dict(op='set', fragment=nm, entity='0x%08X' % n, prop=op['prop'], value=op['value']))
        elif kind == 'delete':
            if op.get('mode', 'disable') == 'remove':
                fops.append(dict(op='remove', fragment=nm, entity='0x%08X' % n, deep=True))
                report['save_safe'] = False
                report.setdefault('removed', []).append('%s %s' % (nm.split('/')[-1], '0x%08X' % n))
            else:
                # retire (the Unreal TODLevelEditor rule): kept, moved 5 km below the world, collision flags 0
                d = doc(nm)
                k = [k for k, x in frs if x == nm][0]
                owner, _ = ft.owner_chain(b, frs, k, T)
                W = d.world(n, owner)
                fops.append(dict(op='move', fragment=nm, entity='0x%08X' % n, space='world',
                                 pos=[W[0][0], W[0][1] - 5000.0, W[0][2]]))
                if d.get(n, 'CollisionFlags') is not None:
                    fops.append(dict(op='set', fragment=nm, entity='0x%08X' % n, prop='CollisionFlags', value=0))
        else:
            raise BuildError('unknown op %s' % kind)
    if not fops:
        return raw
    # merge repeated sets/moves of the same record (the writer verifies one intended value per record)
    merged, seen = [], {}
    for o in fops:
        key = (o['op'], o['fragment'], o.get('entity'), o.get('prop')) if o['op'] in ('set', 'move') else None
        if key and key in seen:
            merged[seen[key]] = o
            continue
        if key:
            seen[key] = len(merged)
        merged.append(o)
    try:
        old, nb, fdocs, intended = ft.apply_ops(raw, ext, merged, T)
        new = nb.serialize()
        vr, _ = ft.verify_block(old, new, ext, fdocs, intended, T)
    except (ft.Fail, fe.EditError, KeyError, ValueError) as e:
        raise BuildError('%s: %s' % (entry.split('/')[-1], e))
    report['stage_a'] = dict(ops=len(merged), checks=_short_checks(vr))
    return new


def _short_checks(vr):
    out = {}
    for k, v in vr.items():
        if k == '4_edited_fragments':
            out[k] = [{x: f[x] for x in ('fragment', 'payload_old', 'payload_new', 'changed_props', 'new_entities',
                                          'removed_entities', 'dangling_refs', 'shipped_order_invariant',
                                          'independent_reader') if x in f} for f in v]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------------------------- stage B
def stage_b(ws, entry, raw, adds, T, report, uid_nodes):
    """Save-safe adds, the same rule as the Unreal TODLevelEditor (todle_build.graft): the template's
    subtree is appended after the last create of the fragment the block instantiates LAST, its root parented to 0
    (that fragment's owner, the shipped resolution path; no literal ids). Templates whose subtree points at other
    entities are refused."""
    ext = os.path.splitext(entry)[1]
    bits = BLOCK_BITS[ext]
    L = lv.BlockLevel(entry, raw, T, ws.main_lookup)
    last = L.instances[-1].frag
    if L.inst_count[last] != 1 or last not in L.own_frags:
        raise BuildError('%s: the fragment the engine loads last (%s) is a prefab used %d times, so new objects '
                         'cannot be added to this block without shifting save indices. Put them in the map or a '
                         'mission layer instead.' % (entry.split('/')[-1], last.split('/')[-1], L.inst_count[last]))
    owner = next(i for i in L.instances if i.frag == last).owner       # world transform of entity 0 of that fragment
    b = L.b
    k_last = L.k_of(last)
    dst = fe.FragDoc(b.payloads[k_last], T, last)
    used = set()
    for k, nm in L.frs:
        if len(b.payloads[k]) > 24:
            for r in tf.Fragment(b.payloads[k], T).records:
                used.add(r.node)
    grafted = []
    src_cache = {}
    for ai, op in enumerate(adds):
        te = op['template']
        if te['entry'] == entry:
            sL = L
        else:
            if te['entry'] not in src_cache:
                r2, _ = ws.read_block(te['entry'])
                src_cache[te['entry']] = lv.BlockLevel(te['entry'], r2, T, ws.main_lookup)
            sL = src_cache[te['entry']]
        snm = _frag_sel(sL.frs, te['frag'])
        src = sL.doc(snm)
        sn = _node(te['node'])
        if sn not in src.created_ids():
            raise BuildError('template %s not found' % te['node'])
        nodes = src.subtree(sn) if op.get('deep', False) else [sn]
        m = _graft(dst, src, nodes, sn, T, used, bits, seed=op.get('seed', 4000 + ai))
        root = m[sn]
        sets = dict(op.get('set') or {})
        if op.get('name'):
            sets['name'] = op['name']
        for p, v in sets.items():
            dst.set_prop(root, p, ft.value_in(dst, p, v), note=False)
        wp = tuple(op['pos']) if op.get('pos') is not None else tuple(src.world(sn, fe.IDENT)[0])
        wq = fe.qnorm(tuple(op['rot'])) if op.get('rot') is not None else fe.qnorm(src.world(sn, fe.IDENT)[1])
        Lc = fe.compose(fe.inverse(owner), (wp, wq))
        dst.set_prop(root, fe.P_POS, [tf.f32(x) + 0.0 for x in Lc[0]], note=False)
        dst.set_prop(root, fe.P_ORIENT, [tf.f32(x) + 0.0 for x in fe.qnorm(fe.qconj(Lc[1]))], note=False)
        uid_nodes[op.get('uid')] = (last, root)
        grafted.append(dict(uid=op.get('uid'), template='%s:%s:%s' % (te['entry'].split('/')[-1], snm.split('/')[-1],
                                                                       te['node']),
                            into=last.split('/')[-1], new_key='0x%08X' % root, nodes=len(nodes),
                            parent='0 (owner of %s)' % last.split('/')[-1]))
    b.payloads[k_last] = dst.payload()
    new = b.serialize()
    try:
        vr = smt.verify(entry, raw, new, ext, None, grafted, T, set())
    except (smt.Fail, ft.Fail) as e:
        raise BuildError('%s: %s' % (entry.split('/')[-1], e))
    report['stage_b'] = dict(grafted=grafted, checks={k: v for k, v in vr.items() if k != 'grafted'})
    return new


def _graft(dst, src, nodes, src_root, T, used, bits, seed):
    """Copy the subtree after dst's last create, root parent 0; Entity values must stay inside the copy."""
    dst.used_ids = used
    new = dst.new_ids(len(nodes), bits << 20)
    m = dict(zip(nodes, new))
    creates = {r.node: r for r in src.records if r.op == tf.CREATE}
    last_create = max(i for i, r in enumerate(dst.records) if r.op == tf.CREATE)
    dst.records[last_create + 1:last_create + 1] = [tf.Record(m[n], tf.CREATE, raw=creates[n].raw) for n in nodes]
    rnd = random.Random(seed)
    for n in nodes:
        for r in src.sets_of(n):
            raw = r.raw
            if r.prop == fe.P_PARENT and n == src_root:
                raw = struct.pack('<I', 0)
            else:
                vals = _entity_values(T, r.prop, raw)
                for v in vals:
                    if v is not None and v not in m:
                        raise BuildError('the template %s has %s = 0x%08X, which points outside the copied object; a '
                                         'copy cannot keep that link save-safely (pick another template)'
                                         % ('0x%08X' % src_root, T.name(r.prop), v))
                if vals:
                    raw = src._remap_value(r.prop, raw, m)
            if r.prop in (fe.P_UID0, fe.P_UID1) and struct.unpack('<i', raw[:4])[0] != 0:
                raw = struct.pack('<i', rnd.randint(1, 2 ** 31 - 1))
            dst.records.append(tf.Record(m[n], tf.SET, r.prop, raw, r.hi))
    if not any(r.prop == fe.P_PARENT for r in src.sets_of(src_root)):
        dst.records.append(tf.Record(m[src_root], tf.SET, fe.P_PARENT, struct.pack('<I', 0)))
    dst.modified = True
    dst._gen += 1
    return m


# ---------------------------------------------------------------------------------------------- stage C
def stage_c(ws, sets, outs, rep, progress=None):
    """Collision generator sets -> host model HullLists (todct.collision: the model writer's record edit,
    model_edit.verify, a world-space read-back). Same code and rules as the Unreal TODLevelEditor export."""
    from todct import collision as CO
    T = ws.T
    built = dict(outs)
    names = ft.archive().names
    rep['collision'] = []
    for mk, ss in CO.group_by_map(sets).items():
        if progress:
            progress('collision for %s' % mk)
        ents = CO.map_entries(names, mk)

        def read(e):
            return built[e] if e in built else ws.read_block(e)[0]
        try:
            ctx = CO.MapContext(mk, ents, read)
            new, r = CO.apply_sets(ctx, ss, base_raw={e: built[e] for e in ents if e in built})
        except CO.CollisionError as e:
            raise BuildError('collision: %s' % e)
        for e, raw in new.items():
            ext = os.path.splitext(e)[1]
            r1 = ft.roundtrip_block(raw, ext, T)
            if r1['fail'] or not r1['block_identical']:
                raise BuildError('%s: the block with new collision does not round-trip' % e)
            hosts = next((b['hosts'] for b in r['blocks'] if b['entry'] == e), [])
            info = [dict(model=h['model'], pieces=h['readback']['shapes'],
                         record_bytes=[h['record_bytes_old'], h['record_bytes_new']],
                         readback_max_m=h['readback']['max_world_error_m'], sphere=h['sphere'], verify='PASS')
                    for h in hosts]
            blk = next((b for b in rep['blocks'] if b['entry'] == e), None)
            if blk is None:
                base, src = ws.read_block(e)
                blk = dict(entry=e, base_archive=src, base_sha256=sha(base), base_bytes=len(base), save_safe=True)
                rep['blocks'].append(blk)
            blk.update(out_sha256=sha(raw), bytes=len(raw), collision=info,
                       roundtrip=dict(fragments=r1['fragments'], records=r1['records'], identical=r1['block_identical']))
            built[e] = raw
        rep['collision'].append({k: v for k, v in r.items() if k != 'blocks'})
    return sorted(built.items())


# ---------------------------------------------------------------------------------------------- whole build
def stage_d(ws, part_b, outs, rep, collision=None, progress=None):
    """Companion tools part B (routes, missions, sections) on top of stages A-C: todct.edits, the same code and rules
    as the Unreal TODLevelEditor export (new entities appended after every existing node of their block, literal
    parent links; verified by navtool, missiontool graph + lint, seamless transitions.catalog, submaptool verify)."""
    from todct import edits as ED
    if progress:
        progress('routes, missions, sections')
    base = dict(outs)
    out, r = ED.build(lambda e: ws.read_block(e)[0], base=base, collision_sets=collision, **part_b)
    rep['companion_edits'] = {k: v for k, v in r.items() if k != 'blocks'}
    if r['result'] not in ('PASS', 'NOTHING'):
        raise BuildError('routes / missions / sections: %s %s' % (r['result'], r.get('error') or ''))
    built = dict(outs)
    for e, raw in out.items():
        br = next((x for x in r['blocks'] if x['entry'] == e), {})
        blk = next((b for b in rep['blocks'] if b['entry'] == e), None)
        if blk is None:
            blk = dict(entry=e, save_safe=True)
            try:
                b0, src = ws.read_block(e)
                blk.update(base_archive=src, base_sha256=sha(b0), base_bytes=len(b0))
            except Exception:                         # noqa: BLE001  (a new section block)
                blk.update(new_block=True)
            rep['blocks'].append(blk)
        blk.update(out_sha256=sha(raw), bytes=len(raw),
                   companion_edits={k: br.get(k) for k in ('existing_ops', 'appended', 'submaptool_verify', 'roundtrip', 'copied')
                                    if br.get(k)})
        built[e] = raw
    return sorted(built.items())


def build(ws, level_ops, frag_ops_by_entry, out_dir, zip_name, progress=None, collision=None, part_b=None):
    """level_ops: editor ops (all mods, in order). frag_ops_by_entry: {entry: [fragment writer ops]} from the data
    editors. collision: collision sets (companion tools, shared with the Unreal plugin), built last into their host
    models' HullLists. Writes out_dir/<zip_name> and report.json; returns the report."""
    T = ws.T
    per = {}
    for op in level_ops:
        per.setdefault(op['entry'], []).append(op)
    for e, ops in frag_ops_by_entry.items():
        per.setdefault(e, []).insert(0, dict(op='frag', entry=e, ops=ops))
    os.makedirs(out_dir, exist_ok=True)
    rep = dict(blocks=[], save_safe=True)
    outs = []
    for i, (entry, ops) in enumerate(sorted(per.items())):
        if progress:
            progress('building %s' % entry.split('/')[-1], i, len(per))
        base, src = ws.read_block(entry)
        ext = os.path.splitext(entry)[1]
        r0 = ft.roundtrip_block(base, ext, T)
        if r0['fail'] or not r0['block_identical']:
            raise BuildError('%s: the base block does not round-trip' % entry)
        brep = dict(entry=entry, base_archive=src, base_sha256=sha(base), save_safe=True)
        plain = [o for o in ops if o['op'] != 'add']
        adds = [o for o in ops if o['op'] == 'add']
        raw = stage_a(entry, base, plain, T, brep)
        uid_nodes = {}
        if adds:
            raw = stage_b(ws, entry, raw, adds, T, brep, uid_nodes)
        r1 = ft.roundtrip_block(raw, ext, T)
        if r1['fail'] or not r1['block_identical']:
            raise BuildError('%s: the rebuilt block does not round-trip: %s' % (entry, r1['fail'][:3]))
        brep.update(out_sha256=sha(raw), bytes=len(raw), base_bytes=len(base), roundtrip=dict(
            fragments=r1['fragments'], records=r1['records'], identical=r1['block_identical']))
        brep['uid_nodes'] = {k: ['%s' % v[0], '0x%08X' % v[1]] for k, v in uid_nodes.items() if k}
        if not brep['save_safe']:
            rep['save_safe'] = False
        rep['blocks'].append(brep)
        outs.append((entry, raw))
    if collision:
        outs = stage_c(ws, collision, outs, rep, progress)
    if part_b and any(part_b.values()):
        outs = stage_d(ws, part_b, outs, rep, collision, progress)
    zp = os.path.join(out_dir, zip_name)
    if outs:
        rep['zip'] = ft.write_zip(zp, outs, naz_for_mtime=ws.game.naz)
    rep['entries'] = [e for e, _ in outs]
    json.dump(rep, open(os.path.join(out_dir, 'report.json'), 'w'), indent=1, default=str)
    rep['_outs'] = outs
    return rep
