"""Save-safe block builder of the companion tools (routes, missions, sections): edits of existing entities plus NEW
entities appended after every existing node of their block, linked to their parent by a literal entity id.

Why this is save-safe and why the literal parent works (GOG TOD.exe; docs/subsystem_level_streaming.md 5.3, the
fragment writer doc 6, the save format doc 5; re-read from the decompile for the route editor, 2026-10-20):

  * Saves address nodes by (block, creation index). AssetManager::AddEntity (0x875FA0) gives every create the next
    free slot of its block (cursor AssetManager+0x1B0+4*block) and returns (block+1) << 20 | slot. Appending creates
    after the last create of the fragment the block instantiates LAST keeps every existing slot.
  * ApplyFragmentResource (0x85D990) installs a fresh key -> entity map at AssetManager+0x1D0 for each fragment it
    applies (key 0 = the owner, every create adds its key) and restores the previous map afterwards.
  * FindEntityById (0x879740) looks the id up in that map first; a miss falls through to
    vEntity[block][id & 0xFF8FFFFF] with the block from bits 20..22. So a set record or Entity value holding
    (block << 20) | runtime index resolves to the existing node of that block. The save loader (FUN_008AA770) resolves
    every save record through the same function with exactly that id form (((field + 0x1000) * 0x100) | index), so
    the id form and the creation-index model (save_editor/nodemap.py: all records of the 9 shipped saves parse with
    zero resyncs; 13 test saves loaded in game by the level editor's Play-from-here runs) are proven by data.
  * The trap: a literal equal to a KEY of the fragment being applied resolves to that local node instead. Every
    literal is therefore checked against all keys of the destination fragment (refused on a clash).
  * Parent and child order: the parent setter attaches with FUN_0088E8A0, which inserts after the last sibling whose
    'order' (node+0x12, short) is strictly smaller: a new node with order k goes in front of an existing sibling
    with order k. Track points, sign-post folders and trigger children are read in that order.
  * A literal can only name a node of the SAME block that exists before the destination fragment is applied (the
    destination is the last one, so every other node of the block exists) and lives as long as the block. Other
    blocks are refused (load order map < submap < mission, and a block can unload while another stays).

Builder:
  b = Builder(read)                       read(entry) -> bytes of the block to build on (shipped or already edited)
  b.set(entry, frag, node, prop, value)   existing entity (fragtool apply_ops 'set')
  b.move(entry, frag, node, pos, orient=None)          world position (and TRUE world rotation)
  b.append(entry, uid, src=(src_entry, frag, node), parent=('ref', frag, node) | ('new', uid) | None,
           order=None, name=None, sets={}, pos=None, rot=None, deep=False)
  b.new_block(entry, clone_of, rename_root=(old, new), localized=True)
  out, report = b.build()                 {entry: bytes}; raises BuildError with the reason
  engine_view(raw, entry)                 the block as the engine links it (literal-parented nodes moved under their
                                          parent's fragment): what navtool / missiontool must see
"""
import collections
import hashlib
import os
import random
import struct

from . import tools

BLOCK_BITS = {'.main': 1, '.map': 2, '.submap': 3, '.mission': 4, '.cutscene': 5, '.playerdata': 6}
LANGS = ['uk', 'de', 'fr', 'es', 'it']


class BuildError(ValueError):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def hx(n):
    return '0x%08X' % n


def mods():
    M = tools.load()
    return M.ft, M.fe, M.tf, M.tb, tools.load_more('submaptool')


def frag_name(frs, sub):
    """Full fragment record name from a full name or a unique (case-insensitive) substring."""
    if sub is None:
        raise BuildError('fragment missing')
    s = str(sub).replace('\\', '/').lower()
    exact = [n for _, n in frs if n.lower() == s]
    if exact:
        return exact[0]
    tail = [n for _, n in frs if n.lower().split('/')[-1] == s.split('/')[-1]]
    if len(tail) == 1:
        return tail[0]
    hits = [n for _, n in frs if s in n.lower()]
    if len(hits) != 1:
        raise BuildError('fragment %r matches %d fragments' % (sub, len(hits)))
    return hits[0]


def node_id(v):
    if isinstance(v, int):
        return v
    return int(str(v), 16)


class BlockInfo:
    """One block's bytes with the views the builder needs (fragments, owner chains, creation order)."""

    def __init__(self, entry, raw, nodemap_entry=None):
        ft, fe, tf, tb, smt = mods()
        self.entry, self.raw = entry, raw
        self.ext = os.path.splitext(entry)[1].lower()
        self.bits = BLOCK_BITS[self.ext]
        self.T = ft.types()
        self.b = tb.Block(raw, self.ext)
        self.frs, _ = ft.fragments(self.b)
        self.by_name = {nm: k for k, nm in self.frs}
        self._docs, self._owner = {}, {}
        self.nodemap_entry = nodemap_entry or entry
        self._nodes = None

    def doc(self, nm):
        ft, fe, tf, tb, smt = mods()
        if nm not in self._docs:
            self._docs[nm] = fe.FragDoc(self.b.payloads[self.by_name[nm]], self.T, nm)
        return self._docs[nm]

    def owner(self, nm):
        ft, fe, tf, tb, smt = mods()
        if nm not in self._owner:
            self._owner[nm], _ = ft.owner_chain(self.b, self.frs, self.by_name[nm], self.T)
        return self._owner[nm]

    def nodes(self):
        """[runtime index, type, fragment, key, name, path] for every node the block creates (nodemap rules)."""
        ft, fe, tf, tb, smt = mods()
        if self._nodes is None:
            self._nodes = smt.nodes_of(self.b, self.nodemap_entry)
        return self._nodes

    def instances(self, nm):
        doc = self.doc(nm)
        ids = doc.created_ids()
        if not ids:
            return 0
        first = ids[0]
        return sum(1 for n in self.nodes() if n[2] == nm and n[3] == first)

    def runtime_index(self, nm, key):
        hits = [n for n in self.nodes() if n[2] == nm and n[3] == key]
        if len(hits) != 1:
            raise BuildError('%s %s: %d runtime instances (a node of a prefab used several times cannot be a literal '
                             'parent)' % (nm.split('/')[-1], hx(key), len(hits)))
        return hits[0][0]

    def literal(self, nm, key):
        return (self.bits << 20) | self.runtime_index(nm, key)

    def last_fragment(self):
        """(name, next runtime index): the fragment instantiated last, refused when it is a prefab placed more than
        once (an append there would add a node to every instance)."""
        ft, fe, tf, tb, smt = mods()
        try:
            lf, nxt, _ = smt.last_fragment(self.b, self.nodemap_entry)
        except smt.Fail as e:
            raise BuildError('%s: %s' % (self.entry.split('/')[-1], e))
        n = self.instances(lf)
        if n != 1:
            raise BuildError('%s cannot take new entities save-safely: the fragment it instantiates last (%s) is a '
                             'prefab placed %d times, so a node appended there would appear in every instance'
                             % (self.entry.split('/')[-1], lf.split('/')[-1], n))
        return lf, nxt

    def world(self, nm, key):
        return self.doc(nm).world(key, self.owner(nm))


class Builder:
    def __init__(self, read):
        ft, fe, tf, tb, smt = mods()
        self.read = read
        self.T = ft.types()
        self.ops = collections.defaultdict(list)          # entry -> fragtool ops on existing entities
        self.appends = collections.defaultdict(list)      # entry -> append specs
        self.newblocks = collections.OrderedDict()        # entry -> spec
        self.extra = {}                                    # entry -> bytes copied as is (language blocks)
        self.uids = {}                                     # uid -> (entry, key)
        self.notes = []

    # ------------------------------------------------------------------ requests
    def set(self, entry, frag, node, prop, value):
        self.ops[entry].append(dict(op='set', fragment=frag, entity=hx(node_id(node)), prop=prop, value=value))

    def move(self, entry, frag, node, pos=None, rot=None):
        ft, fe, tf, tb, smt = mods()
        op = dict(op='move', fragment=frag, entity=hx(node_id(node)), space='world')
        if pos is not None:
            op['pos'] = [float(x) for x in pos]
        if rot is not None:
            op['orient'] = list(fe.qconj(fe.qnorm(tuple(rot))))      # fragtool takes the STORED quaternion
        self.ops[entry].append(op)

    def append(self, entry, uid, src, parent=None, order=None, name=None, sets=None, pos=None, rot=None, deep=False,
               child_sets=None):
        """child_sets (deep copies): [{"type": create type, "index": n (optional: nth of that type in subtree order),
        "set": {prop: value}}] applied to the copied children."""
        if uid in self.uids or any(a['uid'] == uid for L in self.appends.values() for a in L):
            raise BuildError('duplicate new-entity id %r' % uid)
        self.appends[entry].append(dict(uid=uid, src=src, parent=parent, order=order, name=name, sets=dict(sets or {}),
                                        pos=pos, rot=rot, deep=deep, child_sets=list(child_sets or [])))

    def new_block(self, entry, clone_of, rename_root=None, localized=True):
        self.newblocks[entry] = dict(clone_of=clone_of, rename_root=rename_root, localized=localized)

    # ------------------------------------------------------------------ build
    def _base(self, entry):
        ft, fe, tf, tb, smt = mods()
        if entry in self.newblocks:
            nb = self.newblocks[entry]
            src = self.read(nb['clone_of'])
            ext = os.path.splitext(entry)[1]
            b = tb.Block(src, ext)
            if nb.get('rename_root'):
                old, new = nb['rename_root']
                frs, _ = ft.fragments(b)
                hits = [n for _, n in frs if n.split('/')[-1] == old]
                if len(hits) != 1:
                    raise BuildError('rename_root: %s found %d times in %s' % (old, len(hits), nb['clone_of']))
                newfull = hits[0][:-len(old)] + new
                if len(newfull) != len(hits[0]):
                    raise BuildError('rename_root: the new root name must have the same length as %s (INFO records '
                                     'are fixed size)' % old)
                info = bytes(b.info)
                if info.count(hits[0].encode()) != 1:
                    raise BuildError('rename_root: %s is not unique in the INFO buffer' % hits[0])
                b.info = bytearray(info.replace(hits[0].encode(), newfull.encode()))
                nb['renamed'] = (hits[0], newfull)
            raw = b.serialize()
            if nb.get('localized', True):
                srcbase = os.path.splitext(nb['clone_of'].split('/')[-1])[0]
                newbase = os.path.splitext(entry.split('/')[-1])[0]
                root = entry.rsplit('/shared/', 1)[0]
                for lg in LANGS:
                    se = '%s/%s/%s_%s%s' % (root, lg, srcbase, lg, ext)
                    try:
                        data = self.read(se)
                    except Exception:                     # noqa: BLE001
                        data = None
                    if data:
                        self.extra['%s/%s/%s_%s%s' % (root, lg, newbase, lg, ext)] = data
            return raw, src
        raw = self.read(entry)
        return raw, raw

    def build(self):
        ft, fe, tf, tb, smt = mods()
        T = self.T
        entries = list(self.newblocks) + [e for e in list(self.ops) + list(self.appends) if e not in self.newblocks]
        entries = list(dict.fromkeys(entries))
        out, rep = {}, dict(blocks=[], notes=self.notes)
        for entry in entries:
            raw0, orig = self._base(entry)
            ext = os.path.splitext(entry)[1].lower()
            r0 = ft.roundtrip_block(raw0, ext, T)
            if r0['fail'] or not r0['block_identical']:
                raise BuildError('%s: the base block does not round-trip' % entry)
            nb_spec = self.newblocks.get(entry)
            nm_entry = entry if (not nb_spec or nb_spec.get('rename_root')) else nb_spec['clone_of']
            brep = dict(entry=entry, base_sha256=sha(raw0), base_bytes=len(raw0))
            raw1, allowed = raw0, set()
            ops = self.ops.get(entry) or []
            if ops:
                try:
                    old, nb, docs, intended = ft.apply_ops(raw0, ext, ops, T)
                    raw1 = nb.serialize()
                    vr, chk = ft.verify_block(old, raw1, ext, docs, intended, T)
                except (ft.Fail, fe.EditError) as e:
                    raise BuildError('%s: %s' % (entry.split('/')[-1], e))
                allowed = {(x['node'], x['prop']) for x in intended if x['kind'] == 'set'}
                brep['existing_ops'] = dict(ops=len(ops), fragtool_verify_block='PASS')
            raw2 = raw1
            if self.appends.get(entry):
                raw2, grep = self._graft_block(entry, raw1, nm_entry)
                brep['appended'] = grep
            # save safety: no existing node changes its runtime index; old records kept in order; creates first
            renamed = self.newblocks.get(entry, {}).get('renamed')
            smt.ORIG_ENTRY[entry] = nb_spec['clone_of'] if nb_spec else entry
            try:
                vr = smt.verify(entry, raw0 if entry not in self.newblocks else orig, raw2, ext, renamed,
                                brep.get('appended', {}).get('nodes', []), T, allowed)
            except smt.Fail as e:
                raise BuildError(str(e))
            brep['submaptool_verify'] = dict(header_info=vr.get('header_info'),
                                             changed_fragments=[x.split('/')[-1] for x in vr.get('changed_fragments', [])],
                                             runtime_indices=vr.get('runtime_indices'))
            r1 = ft.roundtrip_block(raw2, ext, T)
            if r1['fail'] or not r1['block_identical']:
                raise BuildError('%s: the built block does not round-trip' % entry)
            brep.update(out_sha256=sha(raw2), bytes=len(raw2), roundtrip=dict(fragments=r1['fragments'],
                                                                             records=r1['records'], identical=True))
            out[entry] = raw2
            rep['blocks'].append(brep)
        for e, d in self.extra.items():
            out[e] = d
            rep['blocks'].append(dict(entry=e, bytes=len(d), out_sha256=sha(d), copied='language block of the new section'))
        rep['uids'] = {u: [e, hx(k)] for u, (e, k) in self.uids.items()}
        return out, rep

    def _graft_block(self, entry, raw, nm_entry):
        ft, fe, tf, tb, smt = mods()
        T = self.T
        bi = BlockInfo(entry, raw, nm_entry)
        lf, nxt = bi.last_fragment()
        dst = bi.doc(lf)
        used = set()
        for k, nm in bi.frs:
            for r in tf.Fragment(bi.b.payloads[k], T).records:
                used.add(r.node)
        dst.used_ids = used
        literals = []
        newkeys = {}                      # uid -> key in dst
        newworld = {}                     # uid -> world transform
        nodes_rep = []
        src_cache = {}

        def src_doc(e, frag):
            key = (e, frag)
            if key not in src_cache:
                sraw = raw if e == entry else self.read(e)
                sb = BlockInfo(e, sraw)
                nm = frag_name(sb.frs, frag)
                src_cache[key] = (sb, nm, sb.doc(nm))
            return src_cache[key]

        def resolve_parent(p):
            """-> (u32 value written, world transform of the parent, description)"""
            if p is None or p == ('owner',):
                return 0, bi.owner(lf), 'owner of %s' % lf.split('/')[-1]
            if p[0] == 'new':
                if p[1] not in newkeys:
                    raise BuildError('parent %r is not an earlier new entity of %s' % (p[1], entry.split('/')[-1]))
                return newkeys[p[1]], newworld[p[1]], 'new %s' % p[1]
            nm = frag_name(bi.frs, p[1])
            key = node_id(p[2])
            if key not in bi.doc(nm).created_ids():
                raise BuildError('parent %s not in %s' % (hx(key), nm.split('/')[-1]))
            W = bi.world(nm, key)
            if nm == lf:
                return key, W, 'local %s' % hx(key)
            lit = bi.literal(nm, key)
            literals.append((lit, nm, key))
            return lit, W, 'literal %s = %s %s (runtime index 0x%X)' % (hx(lit), nm.split('/')[-1], hx(key), lit & 0xFFFFF)

        def value_ref(v):
            """Entity values in 'sets': ('ref', frag, node) / ('new', uid) / plain."""
            if isinstance(v, (list, tuple)) and v and v[0] in ('ref', 'new'):
                return resolve_parent(tuple(v))[0]
            if isinstance(v, list):
                return [value_ref(x) for x in v]
            return v

        rnd = random.Random(0x7D0C)
        for a in self.appends[entry]:
            sb, snm, sdoc = src_doc(a['src'][0], a['src'][1])
            sn = node_id(a['src'][2])
            if sn not in sdoc.created_ids():
                raise BuildError('template %s not in %s' % (hx(sn), snm.split('/')[-1]))
            pval, PW, pdesc = resolve_parent(a['parent'])
            if pval:
                dst.used_ids.add(pval)                    # a new key must never equal a literal
            nodes = sdoc.subtree(sn) if a['deep'] else [sn]
            new = dst.new_ids(len(nodes), (bi.bits << 20) | 1)
            m = dict(zip(nodes, new))
            creates = {r.node: r for r in sdoc.records if r.op == tf.CREATE}
            last_create = max(i for i, r in enumerate(dst.records) if r.op == tf.CREATE)
            dst.records[last_create + 1:last_create + 1] = [tf.Record(m[n], tf.CREATE, raw=creates[n].raw) for n in nodes]
            override = {T.index(p) for p in a['sets']}
            for n in nodes:
                for r in sdoc.sets_of(n):
                    if n == sn and r.prop in override:
                        continue
                    rw = r.raw
                    if r.prop == fe.P_PARENT and n == sn:
                        rw = struct.pack('<I', pval)
                    else:
                        t = T.parse(T.ptype(r.prop))
                        if 'entity' in repr(t):
                            for v in smt.entity_values(T, r.prop, rw):
                                if v is not None and v not in m:
                                    raise BuildError('template %s/%s: %s points outside the copied entities (%s); '
                                                     'set it explicitly' % (snm.split('/')[-1], hx(n), T.name(r.prop), hx(v)))
                            rw = sdoc._remap_value(r.prop, rw, m)
                    if r.prop in (fe.P_UID0, fe.P_UID1) and struct.unpack('<i', rw[:4])[0] != 0:
                        rw = struct.pack('<i', rnd.randint(1, 2 ** 31 - 1))
                    dst.records.append(tf.Record(m[n], tf.SET, r.prop, rw, r.hi))
            dst.modified = True
            dst._gen += 1
            root = m[sn]
            if not any(r.prop == fe.P_PARENT for r in sdoc.sets_of(sn)):
                dst.set_prop(root, fe.P_PARENT, pval, note=False)
            for p, v in a['sets'].items():
                dst.set_prop(root, p, ft.value_in(dst, p, value_ref(v)) if not _is_entity(T, p) else value_ref(v), note=False)
            if a['name'] is not None:
                dst.set_prop(root, fe.P_NAME, a['name'], note=False)
            for cs in a.get('child_sets') or []:
                hit = [m[n] for n in nodes if n != sn and sdoc.type_of(n) == cs['type']]
                if 'index' in cs:
                    hit = hit[cs['index']:cs['index'] + 1]
                if not hit:
                    raise BuildError('child_sets: no %s in the copied subtree of %s' % (cs['type'], hx(sn)))
                for h in hit:
                    for p, v in cs['set'].items():
                        dst.set_prop(h, p, ft.value_in(dst, p, v) if not _is_entity(T, p) else value_ref(v), note=False)
            if a['order'] is not None:
                dst.set_prop(root, fe.P_ORDER, int(a['order']), note=False)
            # transform: world -> local under the parent
            cur_local = sdoc.local(sn)
            wq = fe.qconj(fe.qnorm(tuple(a['rot']))) if a['rot'] is not None else None
            if a['pos'] is not None or wq is not None:
                SW = sdoc.world(sn, sb.owner(snm))
                wp = tuple(float(x) for x in a['pos']) if a['pos'] is not None else SW[0]
                wq = wq if wq is not None else SW[1]
                L = fe.compose(fe.inverse(PW), (wp, wq))
                dst.set_prop(root, fe.P_POS, [tf.f32(x) + 0.0 for x in L[0]], note=False)
                if a['rot'] is not None or dst.get(root, fe.P_ORIENT) is not None:
                    dst.set_prop(root, fe.P_ORIENT, [tf.f32(x) + 0.0 for x in fe.qnorm(fe.qconj(L[1]))], note=False)
                W = fe.compose(PW, dst.local(root))
            else:
                W = fe.compose(PW, cur_local)
            newkeys[a['uid']] = root
            newworld[a['uid']] = W
            self.uids[a['uid']] = (entry, root)
            nodes_rep.append(dict(uid=a['uid'], key=hx(root), keys=[hx(m[n]) for n in nodes],
                                  template='%s %s %s' % (a['src'][0].split('/')[-1], snm.split('/')[-1], hx(sn)),
                                  type=sdoc.type_of(sn), parent=pdesc, order=a['order'], world_pos=[round(x, 4) for x in W[0]]))
        # the trap: a literal equal to a key of the destination fragment would resolve to that local node
        keys = set(dst.created_ids())
        clash = [(hx(l), nm.split('/')[-1], hx(k)) for l, nm, k in literals if l in keys or l == 0]
        if clash:
            raise BuildError('%s: literal parent id(s) %s equal keys of %s, where FindEntityById would resolve them to '
                             'the local node instead: not safe' % (entry.split('/')[-1], clash, lf.split('/')[-1]))
        bi.b.payloads[bi.by_name[lf]] = dst.payload()
        out = bi.b.serialize()
        return out, dict(into=lf, next_runtime_index='0x%X' % nxt, nodes=nodes_rep,
                         literals=[dict(literal=hx(l), fragment=nm.split('/')[-1], key=hx(k)) for l, nm, k in literals],
                         literal_clash_check='PASS (%d literals, none equals a key of %s)' % (len(literals), lf.split('/')[-1]))


def _is_entity(T, p):
    t = T.parse(T.ptype(T.index(p)))
    return 'entity' in repr(t)


# ---------------------------------------------------------------------------------------------- engine view
def engine_view(raw, entry, nodemap_entry=None):
    """The block as the engine links it: every node of the last-instantiated fragment whose parent is a literal id
    (block bits | runtime index) is moved, with its subtree, under that parent in the parent's fragment (parent
    rewritten to the local key). Analysis only (navtool / missiontool cannot follow literals); never shipped.
    Returns (bytes, moved: [(key, parent fragment, parent key)])."""
    ft, fe, tf, tb, smt = mods()
    bi = BlockInfo(entry, raw, nodemap_entry)
    try:
        lf, _ = bi.last_fragment()
    except BuildError:
        return raw, []
    T = bi.T
    by_idx = {}
    for n in bi.nodes():
        by_idx.setdefault(n[0], []).append(n)
    L = bi.doc(lf)
    ids = set(L.created_ids())
    moved = []
    groups = collections.defaultdict(list)
    for n in L.created_ids():
        p = L.get(n, fe.P_PARENT) or 0
        if p in (0, 0xFFFFFFFF) or p in ids:
            continue
        if ((p >> 20) & 7) != bi.bits:
            continue
        hit = by_idx.get(p & 0xFF8FFFFF) or []
        if len(hit) != 1:
            continue
        groups[hit[0][2]].append((n, hit[0][3]))
    if not groups:
        return raw, []
    for nm, lst in groups.items():
        D = bi.doc(nm)
        for n, key in lst:
            sub = L.subtree(n)
            subset = set(sub)
            creates = {r.node: r for r in L.records if r.op == tf.CREATE}
            last_create = max(i for i, r in enumerate(D.records) if r.op == tf.CREATE)
            D.records[last_create + 1:last_create + 1] = [tf.Record(x, tf.CREATE, raw=creates[x].raw) for x in sub]
            for x in sub:
                for r in L.sets_of(x):
                    rw = r.raw
                    if x == n and r.prop == fe.P_PARENT:
                        rw = struct.pack('<I', key)
                    else:
                        t = T.parse(T.ptype(r.prop))
                        if 'entity' in repr(t):
                            # literals of nodes of D -> D's local keys
                            mp = {}
                            for v in smt.entity_values(T, r.prop, rw):
                                if v and v not in subset and ((v >> 20) & 7) == bi.bits and v not in ids:
                                    h = by_idx.get(v & 0xFF8FFFFF) or []
                                    if len(h) == 1 and h[0][2] == nm:
                                        mp[v] = h[0][3]
                            if mp:
                                rw = L._remap_value(r.prop, rw, mp)
                    D.records.append(tf.Record(x, tf.SET, r.prop, rw, r.hi))
            L.records = [r for r in L.records if r.node not in subset]
            L.modified = True
            L._gen += 1
            D.modified = True
            D._gen += 1
            moved.append((hx(n), nm.split('/')[-1], hx(key)))
    for nm in list(groups) + [lf]:
        bi.b.payloads[bi.by_name[nm]] = bi.doc(nm).payload()
    return bi.b.serialize(), moved
