"""TOD level streaming tool: map/submap census, streaming graph, save-safe grafts, and new-submap packages (GOG build).

  python submaptool.py census [-o census.json] [--only SUBSTR]     blocks, assets, entities, bounds, loaders
  python submaptool.py graph  [-o graph.json]                       which trigger loads which block (all blocks)
  python submaptool.py lastfrag BLOCK                               last-created fragment / next runtime index
  python submaptool.py splitplan BLOCK --axis x --at VALUE          what a split of BLOCK at a plane would cut
  python submaptool.py build SPEC.json --out DIR [--deploy TESTGAME] build a package (see below)

Engine facts this tool relies on (docs/subsystem_level_streaming.md):
  * A block's runtime node index = creation order (save_editor/nodemap.py). Saves address nodes by (block, index),
    so a new entity must be created AFTER every existing one or old saves break. 'graft' appends entities to the
    fragment that is instantiated last in the block and links them to their parent by a LITERAL entity id
    ((block << 20) | runtime index), which FindEntityById (0x879740) resolves when the key is not a local one.
  * Scene::LoadMap (0x8932A0) needs a submap Folder to be a sibling of its map Folder (Folder_::_87E640).
  * The block file of a Folder is <dir>/shared/<basename of its 'fragment'>.<ext of block_id> plus one
    <dir>/<lang>/<basename>_<lang>.<ext> per language (Folder_::LoadAssetBlock 0x87E8D0).

SPEC (build):
{ "description": "...", "zip": "stream_override.zip",
  "new_blocks": [ {"entry": "<new archive entry>", "clone_of": "<entry>", "rename_root": ["OLD.fragment", "NEW.fragment"],
                   "localized": true} ],
  "blocks": [ {"block": "<entry or new entry>",
               "ops": [ {"op": "set", ... fragtool set/move ops on EXISTING entities (no creates) ...},
                        {"op": "graft", "from_block": "<entry>", "from_fragment": F, "entity": SEL, "deep": true,
                         "parent": {"fragment": F2, "entity": SEL2},          (any fragment of THIS block)
                         "name": "...", "pos": [x,y,z], "orient": [x,y,z,w], "set": {prop: value},
                         "child_sets": [{"type": "<create type>", "index": i (optional, nth of that type in
                                        subtree order), "set": {prop: value}}]} ] } ] }
"""
import argparse, collections, hashlib, json, math, os, struct, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ_TOOLS = os.path.dirname(HERE)
def _tooldir(name):
    local = os.path.join(HERE, '..', name)
    return local if os.path.isdir(local) else os.path.join(PROJ_TOOLS, name)
FW = os.environ.get('TOD_FW', _tooldir('fragment_writer'))
SE = os.environ.get('TOD_SE', _tooldir('save_editor'))
sys.path.insert(0, FW)
import todblock as tb
import todfrag as tf
import fragedit as fe
import fragtool as ft
sys.path.insert(1, SE)
import nodemap

LANGS = ['uk', 'de', 'fr', 'es', 'it']
TNAME = {0: 'texture', 1: 'font', 2: 'text', 3: 'model', 4: 'fragment', 5: 'movie', 6: 'cutscene', 7: 'sound',
         8: 'stream', 9: 'animation', 10: 'meshcolor'}
MAIN = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
BLOCK_BITS = {'.main': 1, '.map': 2, '.submap': 3, '.mission': 4, '.cutscene': 5, '.playerdata': 6}


class Fail(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ block helpers
def frags_of(b):
    info = bytes(b.info)
    out = {}
    for k, R in enumerate(tb.record_starts(info, b.n)):
        nm = tb.record_name(info, R)
        if tb.u32(info, R) == 4:
            out[nm] = k
    return out


_main_frags = None
def main_frags():
    global _main_frags
    if _main_frags is None:
        b = tb.Block(ft.archive().read(MAIN), '.main')
        _main_frags = {nm: b.payloads[k] for nm, k in frags_of(b).items()}
    return _main_frags


def root_fragment(b, entry):
    """Root fragment of a block: for overdose.main the scene; else the fragment named like the block file."""
    fr = frags_of(b)
    if entry.endswith('.main'):
        return [n for n in fr if n.lower().endswith('overdose.scene')][0]
    base = os.path.splitext(entry.split('/')[-1])[0].lower()
    hits = [n for n in fr if n.split('/')[-1].lower() == base + '.fragment']
    if len(hits) != 1:
        raise Fail('root fragment of %s: %d candidates' % (entry, len(hits)))
    return hits[0]


def nodes_of(b, entry):
    """[runtime_idx, type, fragment, stored_id, name, path] for every node the block creates (nodemap rules)."""
    payloads = {nm: b.payloads[k] for nm, k in frags_of(b).items()}
    root = root_fragment(b, entry)
    if entry.endswith('.main'):
        return nodemap.build(payloads, root, 5)
    return nodemap.build(payloads, root, 1, fallback=[main_frags()])


def last_fragment(b, entry):
    nodes = nodes_of(b, entry)
    last = nodes[-1]
    frag = last[2]
    # the last fragment must own a contiguous run of creates at the very end (no nested expansion after them)
    run = [n for n in nodes if n[2] == frag]
    tail = nodes[-len(run):]
    if any(n[2] != frag for n in tail):
        raise Fail('last fragment %s is instantiated more than once or expands nested fragments last' % frag)
    return frag, last[0] + 1 + nodemap.EXTRA_NODES.get(nodemap._cls(last[1]), 0), nodes


# ------------------------------------------------------------------ graft (save-safe append with literal parent)
def literal_for(b, entry, frag_name, selector, T):
    """(literal entity id, world transform) of an existing entity, addressed by its runtime index."""
    fr = frags_of(b)
    nm = ft.pick_fragment(list((k, n) for n, k in fr.items()), frag_name)[1]
    d = fe.FragDoc(b.payloads[fr[nm]], T, nm)
    key = d.find(selector)
    nodes = nodes_of(b, entry)
    hits = [n for n in nodes if n[2] == nm and n[3] == key]
    if len(hits) != 1:
        raise Fail('parent %s/%s: %d runtime instances (prefab fragments cannot be literal parents)' % (nm, selector, len(hits)))
    idx = hits[0][0]
    bits = BLOCK_BITS[os.path.splitext(entry)[1]]
    owner, _ = ft.owner_chain(b, [(k, n) for n, k in fr.items()], fr[nm], T)
    W = d.world(key, owner)
    return (bits << 20) | idx, W, dict(fragment=nm, key='0x%08X' % key, runtime_index='0x%X' % idx, path=d.path_of(key))


def entity_values(T, prop, raw):
    t = T.parse(T.ptype(prop))
    if 'entity' not in repr(t):
        return []
    v = tf.decode_value(raw, 0, t)
    out = []
    def walk(v, t):
        if t[0] == 'entity':
            out.append(v)
        elif t[0] == 'list':
            for x in v: walk(x, t[1])
        elif t[0] == 'dict':
            for _, x in v: walk(x, t[1])
        elif t[0] == 'struct':
            for fn, ftp in t[2]: walk(v[fn], ftp)
    walk(v, t)
    return out


def graft(dst, src, src_node, deep, parent_literal, T, used_ids, seed):
    """Copy src entity (subtree) into FragDoc dst: creates appended after dst's last create, sets at the end.
    The root's parent becomes parent_literal; Entity values inside the subtree are remapped; any other Entity
    value (0 = owner, or a node outside the subtree) is refused because its meaning changes in dst."""
    import random
    nodes = src.subtree(src_node) if deep else [src_node]
    dst.used_ids = used_ids
    like = (1 << 20) * BLOCK_BITS_FOR_DOC[id(dst)]
    new = dst.new_ids(len(nodes), like)
    m = dict(zip(nodes, new))
    creates = {r.node: r for r in src.records if r.op == tf.CREATE}
    last_create = max(i for i, r in enumerate(dst.records) if r.op == tf.CREATE)
    dst.records[last_create + 1:last_create + 1] = [tf.Record(m[n], tf.CREATE, raw=creates[n].raw) for n in nodes]
    rnd = random.Random(seed)
    for n in nodes:
        for r in src.sets_of(n):
            raw = r.raw
            if r.prop == fe.P_PARENT and n == src_node:
                raw = struct.pack('<I', parent_literal)
            else:
                vals = entity_values(T, r.prop, raw)
                for v in vals:
                    if v is None:
                        continue
                    if v not in m:
                        raise Fail('graft: %s of 0x%08X points outside the copied subtree (0x%08X)' % (T.name(r.prop), n, v))
                raw = src._remap_value(r.prop, raw, m)
            if r.prop in (fe.P_UID0, fe.P_UID1) and struct.unpack('<i', raw[:4])[0] != 0:
                raw = struct.pack('<i', rnd.randint(1, 2**31 - 1))
            dst.records.append(tf.Record(m[n], tf.SET, r.prop, raw, r.hi))
    if not any(r.prop == fe.P_PARENT for r in src.sets_of(src_node)):
        dst.records.append(tf.Record(m[src_node], tf.SET, fe.P_PARENT, struct.pack('<I', parent_literal)))
    dst.modified = True
    dst._gen += 1
    return m


BLOCK_BITS_FOR_DOC = {}


# ------------------------------------------------------------------ verification
def verify(entry, old_raw, new_raw, ext, renamed, grafted, T, allowed=()):
    """Checks: header/INFO identical (except an intended same-length root rename), untouched payloads identical,
    edited fragments parse and re-serialize exactly, every old record kept in order, creates-first ordering,
    and NO existing node changes its runtime index (save compatibility)."""
    rep = {}
    ob, nb = tb.Block(old_raw, ext), tb.Block(new_raw, ext)
    if (ob.timestamp, ob.prop_ck, ob.cmd_ck, ob.n) != (nb.timestamp, nb.prop_ck, nb.cmd_ck, nb.n):
        raise Fail('%s: header changed' % entry)
    oi, ni = bytes(ob.info), bytes(nb.info)
    if renamed:
        old, new = renamed
        if len(old) != len(new) or oi.count(old.encode()) != 1:
            raise Fail('%s: rename not unique/same length' % entry)
        oi = oi.replace(old.encode(), new.encode())
    if oi != ni:
        raise Fail('%s: INFO buffer differs beyond the rename' % entry)
    rep['header_info'] = 'identical' + (' (root renamed %s -> %s)' % renamed if renamed else '')
    changed = [k for k in range(ob.n) if ob.payloads[k] != nb.payloads[k]]
    fr = {k: n for n, k in frags_of(nb).items()}
    for k in changed:
        if k not in fr:
            raise Fail('%s: non-fragment asset %d changed' % (entry, k))
        old_f, new_f = tf.Fragment(ob.payloads[k], T), tf.Fragment(nb.payloads[k], T)
        if new_f.serialize() != nb.payloads[k]:
            raise Fail('%s: %s does not re-serialize' % (entry, fr[k]))
        o, n = old_f.records, new_f.records
        def key(r):
            if r.op == tf.SET and (r.node, r.prop) in allowed:
                return (r.node, r.op, r.prop)
            return r.to_bytes()
        okeys = [key(r) for r in o]
        it = iter(key(r) for r in n)
        if not all(any(x == y for y in it) for x in okeys):
            raise Fail('%s: %s lost or reordered an original record' % (entry, fr[k]))
        ops = [r.op for r in n]
        if tf.SET in ops and tf.CREATE in ops[ops.index(tf.SET):] and fr[k].split('/')[-1].lower() not in (
                'missions.fragment', 'overdose.scene', 'playerdata.fragment'):
            raise Fail('%s: %s breaks the creates-first rule' % (entry, fr[k]))
    rep['changed_fragments'] = [fr[k] for k in changed]
    rep['untouched_assets_identical'] = ob.n - len(changed)
    # runtime index stability
    try:
        no = nodes_of(ob, ORIG_ENTRY.get(entry, entry))
    except Fail:
        no = None
    nn = nodes_of(nb, entry)
    if no is not None:
        sig_o = [(n[0], n[1], n[2].split('/')[-1], n[3]) for n in no]
        sig_n = [(n[0], n[1], n[2].split('/')[-1], n[3]) for n in nn[:len(no)]]
        if renamed:
            rn = (renamed[0].split('/')[-1], renamed[1].split('/')[-1])
            sig_o = [(a, b2, rn[1] if c == rn[0] else c, d) for a, b2, c, d in sig_o]
        if sig_o != sig_n:
            bad = next(i for i, (x, y) in enumerate(zip(sig_o, sig_n)) if x != y)
            raise Fail('%s: existing node index changed at %s -> %s' % (entry, sig_o[bad], sig_n[bad]))
        rep['runtime_indices'] = dict(existing_nodes=len(no), unchanged=True,
                                      new_nodes=[('0x%X' % n[0], n[1], n[2].split('/')[-1]) for n in nn[len(no):]])
    rep['grafted'] = grafted
    return rep


ORIG_ENTRY = {}


# ------------------------------------------------------------------ commands
def cmd_build(a):
    T = ft.types()
    spec = json.load(open(a.spec))
    os.makedirs(a.out, exist_ok=True)
    rep = dict(spec=spec, blocks=[])
    data = {}            # entry -> bytes (current)
    base = {}            # entry -> bytes (base for verification)
    renames = {}
    try:
        for nbk in spec.get('new_blocks', []):
            if nbk.get('clone_of_file'):
                # base block built by newgeo.py (own ground, root already renamed): used as is; `lang_from` names the
                # shipped block whose language stubs are copied
                src = open(nbk['clone_of_file'], 'rb').read()
                ext = os.path.splitext(nbk['entry'])[1]
                if nbk['entry'] in ft.archive().names:
                    raise Fail('%s already exists in blocks.naz' % nbk['entry'])
                data[nbk['entry']] = src
                base[nbk['entry']] = src
                ORIG_ENTRY[nbk['entry']] = nbk['entry']
                if nbk.get('localized', True):
                    srcbase = os.path.splitext(ft.resolve_entry(nbk['lang_from']).split('/')[-1])[0]
                    newbase = os.path.splitext(nbk['entry'].split('/')[-1])[0]
                    root = nbk['entry'].rsplit('/shared/', 1)[0]
                    for lg in LANGS:
                        se = '%s/%s/%s_%s%s' % (root, lg, srcbase, lg, ext)
                        if se in ft.archive().names:
                            data['%s/%s/%s_%s%s' % (root, lg, newbase, lg, ext)] = ft.archive().read(se)
                continue
            src = ft.archive().read(ft.resolve_entry(nbk['clone_of']))
            ext = os.path.splitext(nbk['entry'])[1]
            b = tb.Block(src, ext)
            if nbk['entry'] in ft.archive().names:
                raise Fail('%s already exists in blocks.naz' % nbk['entry'])
            if nbk.get('rename_root'):
                old, new = nbk['rename_root']
                fr = frags_of(b)
                hits = [n for n in fr if n.split('/')[-1] == old]
                if len(hits) != 1:
                    raise Fail('rename_root: %s found %d times' % (old, len(hits)))
                oldfull = hits[0]
                newfull = oldfull[:-len(old)] + new
                if len(newfull) != len(oldfull):
                    raise Fail('rename_root: new name must have the same length (INFO records are fixed-size)')
                info = bytes(b.info)
                b.info = bytearray(info.replace(oldfull.encode(), newfull.encode()))
                renames[nbk['entry']] = (oldfull, newfull)
            data[nbk['entry']] = b.serialize()
            base[nbk['entry']] = src
            ORIG_ENTRY[nbk['entry']] = ft.resolve_entry(nbk['clone_of'])
            if nbk.get('localized', True):
                srcbase = os.path.splitext(ft.resolve_entry(nbk['clone_of']).split('/')[-1])[0]
                newbase = os.path.splitext(nbk['entry'].split('/')[-1])[0]
                root = nbk['entry'].rsplit('/shared/', 1)[0]
                for lg in LANGS:
                    se = '%s/%s/%s_%s%s' % (root, lg, srcbase, lg, ext)
                    if se in ft.archive().names:
                        data['%s/%s/%s_%s%s' % (root, lg, newbase, lg, ext)] = ft.archive().read(se)
        for bs in spec.get('blocks', []):
            entry = bs['block'] if bs['block'] in data else ft.resolve_entry(bs['block'])
            ext = os.path.splitext(entry)[1]
            raw = data.get(entry) or ft.archive().read(entry)
            base.setdefault(entry, raw)
            r0 = ft.roundtrip_block(base[entry], ext, T)
            if r0['fail'] or not r0['block_identical']:
                raise Fail('base block %s does not round-trip' % entry)
            plain = [op for op in bs['ops'] if op['op'] in ('set', 'move')]
            if any(op['op'] not in ('set', 'move', 'graft') for op in bs['ops']):
                raise Fail('only set, move and graft ops are save-safe here (clone/add_* create nodes mid-block)')
            allowed = set()
            if plain:
                old, nb, docs, intended = ft.apply_ops(raw, ext, plain, T)
                raw = nb.serialize()
                allowed = {(x['node'], x['prop']) for x in intended if x['kind'] == 'set'}
            grafts = [op for op in bs['ops'] if op['op'] == 'graft']
            grafted = []
            if grafts:
                b = tb.Block(raw, ext)
                lf, next_idx, _ = last_fragment(b, entry)
                fr = frags_of(b)
                dst = fe.FragDoc(b.payloads[fr[lf]], T, lf)
                BLOCK_BITS_FOR_DOC[id(dst)] = BLOCK_BITS[ext]
                used = set()
                for nm, k in fr.items():
                    for r in tf.Fragment(b.payloads[k], T).records:
                        used.add(r.node)
                for i, op in enumerate(grafts):
                    sraw = data.get(op['from_block']) or ft.archive().read(ft.resolve_entry(op['from_block']))
                    sb = tb.Block(sraw, os.path.splitext(op['from_block'])[1])
                    sfr = frags_of(sb)
                    snm = ft.pick_fragment(list((k, n) for n, k in sfr.items()), op['from_fragment'])[1]
                    src = fe.FragDoc(sb.payloads[sfr[snm]], T, snm)
                    sn = src.find(op['entity'])
                    lit, PW, pinfo = literal_for(b, entry, op['parent']['fragment'], op['parent']['entity'], T)
                    m = graft(dst, src, sn, op.get('deep', True), lit, T, used, seed=op.get('seed', 1000 + i))
                    root = m[sn]
                    for p, v in dict(op.get('set', {})).items():
                        dst.set_prop(root, p, ft.value_in(dst, p, v), note=False)
                    if op.get('name'):
                        dst.set_prop(root, fe.P_NAME, op['name'], note=False)
                    for cs in op.get('child_sets', []):
                        hit = [m[n] for n in m if src.type_of(n) == cs['type'] and n != sn]
                        if 'index' in cs:
                            hit = hit[cs['index']:cs['index'] + 1]
                        if not hit:
                            raise Fail('child_sets: no %s in the grafted subtree' % cs['type'])
                        for h in hit:
                            for p, v in cs['set'].items():
                                dst.set_prop(h, p, ft.value_in(dst, p, v), note=False)
                    if op.get('pos') is not None or op.get('orient') is not None:
                        # world -> local under the literal parent
                        wp = tuple(op['pos']) if op.get('pos') is not None else None
                        wq = fe.qconj(fe.qnorm(tuple(op['orient']))) if op.get('orient') is not None else \
                            fe.qconj(fe.qnorm(tuple(src.get(sn, fe.P_ORIENT) or (0, 0, 0, 1))))
                        L = fe.compose(fe.inverse(PW), (wp or (0.0, 0.0, 0.0), wq))
                        if wp is not None:
                            dst.set_prop(root, fe.P_POS, [tf.f32(x) + 0.0 for x in L[0]], note=False)
                        dst.set_prop(root, fe.P_ORIENT, [tf.f32(x) + 0.0 for x in fe.qnorm(fe.qconj(L[1]))], note=False)
                    grafted.append(dict(source='%s:%s:%s' % (op['from_block'].split('/')[-1], snm.split('/')[-1], op['entity']),
                                        into=lf, new_keys={'0x%08X' % k: '0x%08X' % v for k, v in m.items()},
                                        parent=pinfo, parent_literal='0x%08X' % lit, parent_world=PW))
                b.payloads[fr[lf]] = dst.payload()
                raw = b.serialize()
            data[entry] = raw
            vr = verify(entry, base[entry], raw, ext, renames.get(entry), grafted, T, allowed)
            rep['blocks'].append(dict(entry=entry, base_sha256=sha(base[entry]), out_sha256=sha(raw), bytes=len(raw), checks=vr))
        for e in data:
            if e not in [x['entry'] for x in rep['blocks']]:
                rep['blocks'].append(dict(entry=e, out_sha256=sha(data[e]), bytes=len(data[e]), checks='copied/renamed only'))
        for e, d in data.items():
            open(os.path.join(a.out, e.split('/')[-1]), 'wb').write(d)
        zn = spec.get('zip', 'stream_override.zip')
        zp = os.path.join(a.out, zn)
        rep['zip'] = ft.write_zip(zp, sorted(data.items()))
        line = 'filesystem = ' + ', '.join([zn] + ft.BASE_ARCHIVES)
        open(os.path.join(a.out, 'configpc_line.txt'), 'w').write(line + '\n')
        rep['configpc_line'] = line
        if a.deploy:
            gd = os.path.normcase(os.path.abspath(a.deploy))
            if any(gd == f or gd.startswith(f + os.sep) for f in ft.FORBIDDEN_DEPLOY):
                raise Fail('refusing to deploy into %s' % a.deploy)
            if ft.game_running():
                raise Fail('a game is running')
            import shutil
            shutil.copy2(zp, os.path.join(a.deploy, zn))
        rep['result'] = 'PASS'
    except (Fail, fe.EditError, ft.Fail, KeyError, ValueError) as e:
        rep['result'] = 'FAIL: %s' % e
    json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(result=rep['result'], zip=rep.get('zip'), blocks=[
        dict(entry=x['entry'].split('/')[-1], bytes=x['bytes'],
             new_nodes=(x['checks'].get('runtime_indices', {}).get('new_nodes') if isinstance(x['checks'], dict) else None))
        for x in rep['blocks']]), indent=1, default=str))
    return 0 if rep['result'] == 'PASS' else 1


def category(t):
    tl = (t or '').lower()
    if tl == 'model' or tl.endswith('(model)'):
        return 'model'
    if 'collisionbox' in tl or 'collisionsphere' in tl:
        return 'trigger_volume' if 'trigger' in tl else 'collision_box'
    if tl.startswith('trigger_'):
        return 'trigger_logic'
    if 'trackpoint' in tl or 'track)' in tl or tl == 'track' or 'pathtype' in tl:
        return 'route'
    if 'placeholder' in tl:
        return 'placeholder'
    if 'sound' in tl:
        return 'sound'
    if 'light' in tl:
        return 'light'
    if 'particle' in tl:
        return 'particle'
    if 'folder' in tl:
        return 'folder'
    return 'other'


def scan_block(entry, T, positions=False):
    raw = ft.archive().read(entry)
    ext = os.path.splitext(entry)[1]
    b = tb.Block(raw, ext)
    info = bytes(b.info)
    starts = tb.record_starts(info, b.n)
    by_type, bytes_type = collections.Counter(), collections.Counter()
    for k, R in enumerate(starts):
        t = TNAME.get(tb.u32(info, R), str(tb.u32(info, R)))
        by_type[t] += 1
        bytes_type[t] += len(b.payloads[k])
    frs = [(k, tb.record_name(info, R)) for k, R in enumerate(starts) if tb.u32(info, R) == 4]
    cats, pts, loads, ents = collections.Counter(), [], [], []
    cache = {}
    n_ent = 0
    for k, name in frs:
        if len(b.payloads[k]) <= 24:
            continue
        d = fe.FragDoc(b.payloads[k], T, name)
        owner, _ = ft.owner_chain(b, frs, k, T, cache=cache)
        for n in d._index()[1]:
            n_ent += 1
            ty = d.type_of(n)
            c = category(ty)
            cats[c] += 1
            if c in ('model', 'collision_box', 'trigger_volume', 'placeholder', 'route') or positions:
                p = d.world(n, owner)[0]
                if all(math.isfinite(x) for x in p):
                    if c in ('model', 'collision_box') and any(abs(x) > 1e-3 for x in p):
                        pts.append(p)
                    if positions:
                        ents.append(dict(f=name.split('/')[-1], n=n, t=ty, c=c, p=p, name=d.get(n, 'name'), par=d.get(n, 'parent') or 0,
                                         size=[d.get(n, 'width'), d.get(n, 'height'), d.get(n, 'length')] if c == 'trigger_volume' else None))
            if ty and ty.startswith('Trigger_Activate_Load_Unload_Save') and d.get(n, 'ActionType') == 21:
                root, seen = d.get(n, 'parent') or 0, set()
                while root and root not in seen and not (d.type_of(root) or '').startswith('Trigger_Root'):
                    seen.add(root)
                    root = d.get(root, 'parent') or 0
                ri = None
                if root:
                    RW = d.world(root, owner)
                    ri = dict(name=d.get(root, 'name'), type=d.type_of(root), pos=[round(x, 2) for x in RW[0]],
                              size=[d.get(root, 'width'), d.get(root, 'height'), d.get(root, 'length')],
                              radius=d.get(root, 'radius'))
                loads.append(dict(fragment=name.split('/')[-1], target=d.get(n, 'TargetName'),
                                  teleport=d.get(n, 'Teleport_to'), root=ri))
    bounds = None
    if pts:
        xs, ys, zs = zip(*pts)
        def q(v, f):
            s = sorted(v); return round(s[int(f * (len(s) - 1))], 1)
        bounds = dict(n=len(pts), p02=[q(xs, .02), q(ys, .02), q(zs, .02)], p98=[q(xs, .98), q(ys, .98), q(zs, .98)],
                      min=[round(min(xs), 1), round(min(ys), 1), round(min(zs), 1)],
                      max=[round(max(xs), 1), round(max(ys), 1), round(max(zs), 1)])
    r = dict(entry=entry, bytes=len(raw), info_bytes=len(b.info), payload_bytes=sum(b.sizes), assets=b.n,
             assets_by_type=dict(by_type), payload_bytes_by_type=dict(bytes_type), fragments=len(frs),
             entities=n_ent, categories=dict(cats), bounds=bounds, loaders=loads)
    if positions:
        r['_ents'] = ents
    return r


def cmd_census(a):
    T = ft.types()
    names = sorted(n for n in ft.archive().names if '/shared/' in n and n.endswith(tuple(a.ext.split(','))))
    if a.only:
        names = [n for n in names if a.only.lower() in n.lower()]
    out = []
    print('%-46s %7s %7s %7s %5s %6s %5s %5s %5s %5s  %s' % ('block', 'MB', 'infoMB', 'texMB', 'frags', 'ents', 'model',
                                                            'cbox', 'trig', 'load', 'model bounds p02..p98 (x,z)'))
    for n in names:
        r = scan_block(n, T)
        out.append(r)
        c, bd = r['categories'], r['bounds']
        print('%-46s %7.2f %7.2f %7.2f %5d %6d %5d %5d %5d %5d  %s' % (
            n.split('/')[-1][:46], r['bytes'] / 2**20, r['info_bytes'] / 2**20,
            r['payload_bytes_by_type'].get('texture', 0) / 2**20, r['fragments'], r['entities'], c.get('model', 0),
            c.get('collision_box', 0), c.get('trigger_volume', 0), len(r['loaders']),
            '' if not bd else 'x %.0f..%.0f z %.0f..%.0f' % (bd['p02'][0], bd['p98'][0], bd['p02'][2], bd['p98'][2])), flush=True)
    if a.o:
        json.dump(out, open(a.o, 'w'), indent=1)


def cmd_graph(a):
    T = ft.types()
    names = sorted(n for n in ft.archive().names if '/shared/' in n and n.endswith(('.map', '.submap', '.mission')))
    edges = collections.Counter()
    detail = []
    for n in names:
        r = scan_block(n, T)
        for l in r['loaders']:
            edges[(n.split('/')[-1], l['target'])] += 1
            detail.append(dict(block=n.split('/')[-1], **l))
    for (s, t), c in sorted(edges.items()):
        print('%-48s -> %-44s x%d' % (s, t, c))
    if a.o:
        json.dump(dict(edges=[dict(src=s, target=t, count=c) for (s, t), c in sorted(edges.items())], loaders=detail),
                  open(a.o, 'w'), indent=1)


def cmd_lastfrag(a):
    entry = ft.resolve_entry(a.block)
    b = tb.Block(ft.archive().read(entry), os.path.splitext(entry)[1])
    lf, nxt, nodes = last_fragment(b, entry)
    print(json.dumps(dict(block=entry, nodes=len(nodes), last_index='0x%X' % nodes[-1][0], last_fragment=lf,
                          next_runtime_index='0x%X' % nxt, root=root_fragment(b, entry)), indent=1))


def cmd_splitplan(a):
    T = ft.types()
    entry = ft.resolve_entry(a.block)
    r = scan_block(entry, T, positions=True)
    ax = 'xyz'.index(a.axis)
    side = collections.Counter()
    per_cat = collections.defaultdict(collections.Counter)
    for e in r['_ents']:
        if not any(abs(x) > 1e-3 for x in e['p']):
            continue
        s = 'A' if e['p'][ax] < a.at else 'B'
        side[s] += 1
        per_cat[e['c']][s] += 1
    groups = collections.defaultdict(set)
    for e in r['_ents']:
        if e['c'] == 'route' and any(abs(x) > 1e-3 for x in e['p']):
            groups[(e['f'], e['par'])].add('A' if e['p'][ax] < a.at else 'B')
    crossing_routes = sum(1 for v in groups.values() if len(v) == 2)
    straddle = 0
    for e in r['_ents']:
        if e['c'] == 'trigger_volume' and e['size'] and e['size'][0]:
            half = max(x or 0 for x in e['size']) / 2.0
            if abs(e['p'][ax] - a.at) < half:
                straddle += 1
    print(json.dumps(dict(block=entry, axis=a.axis, at=a.at, placed_entities=dict(side),
                          route_groups=len(groups), routes_crossing_the_plane=crossing_routes,
                          trigger_volumes_straddling=straddle,
                          by_category={k: dict(v) for k, v in per_cat.items()},
                          loaders_now=len(r['loaders'])), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('census'); p.add_argument('-o'); p.add_argument('--only'); p.add_argument('--ext', default='.map,.submap')
    p = sp.add_parser('graph'); p.add_argument('-o')
    p = sp.add_parser('lastfrag'); p.add_argument('block')
    p = sp.add_parser('splitplan'); p.add_argument('block'); p.add_argument('--axis', default='x'); p.add_argument('--at', type=float, required=True)
    p = sp.add_parser('build'); p.add_argument('spec'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    a = ap.parse_args()
    return {'census': cmd_census, 'graph': cmd_graph, 'lastfrag': cmd_lastfrag, 'splitplan': cmd_splitplan,
            'build': cmd_build}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main() or 0)
