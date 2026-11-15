"""model_edit.py - edit one MODEL record in TOD asset blocks and package the result the way TOD.exe loads it.

  python -I model_edit.py --edit edit.json --out DIR [--naz PATH] [--block FILE --entry NAME] [--zip NAME]

edit.json:
  {"model": "/data/Models/.../X.model",
   "blocks": ["data_pc/overdose_the_game/overdose/shared/submap01_map02_lostoros_downtown.submap", ...]
             (archive entries of blocks.naz to edit; each must hold the model; --block/--entry edits one file instead),
   "cover_collision": true,   grow the model sphere (+0x50) so it encloses all collision (needed in game, see
                              docs/subsystem_collision.md 11.4); default true
   "ops": [ ... applied in order ... ]}

ops:
  {"op": "pivot_collision", "pivot": 0, "remove": [shape indices], "keep_only": [...],
   "add_boxes": [BOX], "add_hulls": [HULL], "flags": [orByte, andByte] (optional), "delete_list": false}
        edits the CollisionList at pivot+0x44 (pivot space). A pivot without a list gets a new one.
        "delete_list": true removes the list (pivot+0x44 = null).
  {"op": "hulls", "remove": [...], "keep_only": [...], "add_boxes": [BOX], "add_hulls": [HULL],
   "from_pivot_lists": true, "delete_list": false}
        edits the model's static HullList (+0x54, model space). A model without one gets a new one, inserted where the
        serializer puts it (after the pivots and the +0x40 data, before the +0x58 object). "from_pivot_lists" moves
        the shapes of every per-pivot list into the HullList (transformed to model space) and deletes the pivot lists.
  {"op": "replace_model", "spec": MODELSPEC}
        rebuilds the whole record from a description (model_writer); the name stays the edited model's.
  {"op": "replace_mesh", "pivot": 0, "mesh": i, "with": MESH}   replace one submesh (geometry + texture refs)
  {"op": "remove_meshes", "pivot": 0, "meshes": [i, ...]}

BOX  = {"min": [x,y,z], "max": [x,y,z], "space": "model"|"world", "world": {"pos": [..], "quat": [x,y,z,w]},
        "surf": "0x02007C00", "facemat": 255, "name": "aux name"}       (world: the entity transform from the level,
        quaternion in the project's conjugated convention as export_map/placed.py print it)
HULL = {"verts": [[x,y,z], ...]} (convex hull computed) or {"obj": "file.obj", "scale": 1, "flip_z": false}
MESH = {"box": {"min": [..], "max": [..], "uv_scale": 1.0}} | {"obj": "file.obj", "scale": 1.0, "flip_z": true},
       plus "texrefs": [i], "smb_flags": "0xBA1BC000"
MODELSPEC = {"textures": [...], "template": true (copy header words / +0x58 object / submesh flags from the model
       being replaced), "pivots": [{"pos", "quat", "parent", "name", "meshes": [MESH...],
       "collision": {"boxes": [BOX], "hulls": [HULL], "from_meshes": true, "surf", "facemat"}}],
       "hulls": {"boxes": [...], "hulls": [...]}}

Output: DIR/<block file name> per edited block, DIR/<zip> (STORED, one entry per block, read back through the engine's
OpenZip/FindFile port), DIR/configpc_line.txt, DIR/report.json. Nothing is deployed and no game is touched.
"""
import argparse, copy, hashlib, json, math, os, struct, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todblock as tb
import todcoll as tc
import todmodel as tm
import model_writer as mw

DEFAULT_NAZ = r"C:\GOG Games\Total Overdose\blocks.naz"          # read only
BASE_ARCHIVES = ["blocks.naz", "sounds.naz", "videos00.naz", "videos01.naz"]
SENT_VEC = 0xBAAFFA00


class Fail(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def hexint(x, default):
    if x is None:
        return default
    return int(x, 16) if isinstance(x, str) else int(x)


# ------------------------------------------------------------------------------------------------ shapes from JSON
def box_from_json(b, pivot=0):
    mn, mx = b['min'], b['max']
    if b.get('space', 'model') == 'world':
        W = b['world']; q = tuple(W['quat'])
        iq = mw.qconj(q)
        corners = [mw.qrot(iq, (x - W['pos'][0], y - W['pos'][1], z - W['pos'][2]))
                   for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
        mn = [min(c[i] for c in corners) for i in range(3)]; mx = [max(c[i] for c in corners) for i in range(3)]
    return mw.box_shape(mn, mx, pivot=pivot, surf=hexint(b.get('surf'), 0x02007C00), facemat=b.get('facemat', 0xFF),
                        aux_name=b.get('name', ''))


def hull_from_json(h, pivot=0, base_dir='.'):
    if 'obj' in h:
        P, N, T, tris = mw.load_obj(os.path.join(base_dir, h['obj']), h.get('scale', 1.0), h.get('flip_z', False))
        pts = P
    else:
        pts = [tuple(v) for v in h['verts']]
    V, F = mw.convex_hull(pts)
    return mw.hull_shape(V, F, pivot=pivot, surf=hexint(h.get('surf'), 0x02007C00), facemat=h.get('facemat', 0xFF),
                         aux_name=h.get('name', ''))


def mesh_from_json(d, base_dir='.'):
    if 'box' in d:
        b = d['box']
        P, N, T, tris = mw.box_mesh(b['min'], b['max'], b.get('uv_scale', 1.0))
    elif 'obj' in d:
        P, N, T, tris = mw.load_obj(os.path.join(base_dir, d['obj']), d.get('scale', 1.0), d.get('flip_z', True))
    else:
        raise Fail('mesh needs "box" or "obj"')
    me = mw.mesh_from_triangles(P, N, T, tris, texrefs=d.get('texrefs', [0]),
                                smb_flags=hexint(d.get('smb_flags'), 0xBA1BC000), mb_flags=hexint(d.get('mb_flags'), 0xBAADE000))
    me['_points'] = P
    return me


# ------------------------------------------------------------------------------------------------ ops on the tree
def new_list(kind, shapes, w10):
    return dict(kind=kind, hdr=dict(vec=dict(cnt=len(shapes), cap=len(shapes), flags=SENT_VEC), w10=w10), shapes=shapes)


def edit_shapes(old, op, make_pivot, base_dir):
    """keep_only (order kept) then remove, both by index into the existing list; then the added shapes."""
    n = len(old)
    idx = list(op['keep_only']) if 'keep_only' in op else list(range(n))
    rem = set(op.get('remove', []))
    if any(i < 0 or i >= n for i in idx + list(rem)):
        raise Fail('shape index out of range (list has %d shapes)' % n)
    kept = [old[i] for i in idx if i not in rem]
    added = [box_from_json(b, make_pivot) for b in op.get('add_boxes', [])]
    added += [hull_from_json(h, make_pivot, base_dir) for h in op.get('add_hulls', [])]
    return kept, added


def op_pivot_collision(m, op, base_dir, log):
    pi = op.get('pivot', 0)
    if not 0 <= pi < len(m['pivots']):
        raise Fail('pivot %d out of range' % pi)
    P = m['pivots'][pi]
    if op.get('delete_list'):
        log.append('pivot %d: CollisionList deleted (%d shapes)' % (pi, len(P['coll']['shapes']) if P['coll'] else 0))
        P['coll'] = None
        return
    old = P['coll']['shapes'] if P['coll'] else []
    kept, added = edit_shapes(old, op, pi, base_dir)
    for s in added:
        s.pop('wrapper_tail', None)                     # CollisionList shapes have no Element wrapper
    shapes = kept + added
    if 'flags' in op:
        fl = tuple(op['flags'])
    elif P['coll'] is not None:
        w = P['coll']['hdr']['w10']
        fo, fa = w & 0xFF, (w >> 8) & 0xFF
        if added:
            ao, aa = mw.list_flags(added)
            fo, fa = fo | ao, fa & aa
        fl = (fo, fa)
    else:
        fl = mw.list_flags(shapes)
    hi = (P['coll']['hdr']['w10'] >> 16) if P['coll'] else 0xBAAC
    P['coll'] = new_list('piv', shapes, fl[0] | (fl[1] << 8) | (hi << 16))
    log.append('pivot %d: CollisionList %d -> %d shapes (kept %d, added %d), flags %02X/%02X'
               % (pi, len(old), len(shapes), len(kept), len(added), fl[0], fl[1]))


def pivot_world_of_tree(m):
    pv = []
    for P in m['pivots']:
        r = P['raw']
        pv.append(dict(pos=struct.unpack_from('<3f', r, 0), quat=struct.unpack_from('<4f', r, 12),
                       parent=struct.unpack_from('<i', r, 0x58)[0]))
    return mw.pivot_world(pv)


def op_hulls(m, op, base_dir, log):
    if op.get('delete_list'):
        log.append('HullList deleted')
        m['hulls'] = None
        return
    old = m['hulls']['shapes'] if m['hulls'] else []
    kept, added = edit_shapes(old, op, 0, base_dir)
    moved = []
    if op.get('from_pivot_lists'):
        PW = pivot_world_of_tree(m)
        for pi, P in enumerate(m['pivots']):
            if not P['coll']:
                continue
            for s in P['coll']['shapes']:
                s = copy.deepcopy(s)
                if s['type'] != 4:
                    raise Fail('moving OrientedBox shapes into a HullList is not implemented')
                T = PW[pi]
                ident = tuple(T[0]) == (0.0, 0.0, 0.0) and abs(T[1][3]) == 1.0
                if not ident:
                    s['verts'] = [tuple(mw.f32(c) for c in mw.apply(T, v)) for v in s['verts']]
                    s.pop('obj_keep', None); s['sphere'] = (0.0, 0.0, 0.0, -1.0)
                s['lowbyte'] = s['lowbyte'] & 0x80        # pivot index 0, as in every shipped HullList
                if 'obj_keep' in s:
                    ok = bytearray(s['obj_keep']); struct.pack_into('<I', ok, 0x2C, struct.unpack_from('<I', ok, 0x2C)[0] & ~0x7F)
                    s['obj_keep'] = bytes(ok)
                s['wrapper_tail'] = bytes(24)
                moved.append(s)
            log.append('pivot %d: %d shapes moved into the HullList, pivot list deleted' % (pi, len(P['coll']['shapes'])))
            P['coll'] = None
    for s in added:
        s['wrapper_tail'] = bytes(24)
    shapes = kept + moved + added
    w10 = m['hulls']['hdr']['w10'] if m['hulls'] else 0
    created = m['hulls'] is None
    m['hulls'] = new_list('f54', shapes, w10)
    log.append('HullList %s: %d -> %d shapes (kept %d, moved %d, added %d)'
               % ('created' if created else 'edited', len(old), len(shapes), len(kept), len(moved), len(added)))


def model_spec_from_json(d, old_m, base_dir):
    old = mw.spec_from_model(old_m)
    tmpl = d.get('template', True)
    pivots = []
    for pj in d['pivots']:
        meshes = [mesh_from_json(x, base_dir) for x in pj.get('meshes', [])]
        if tmpl and old['pivots'] and old['pivots'][0]['meshes']:
            for me in meshes:
                if 'smb_flags' not in pj:
                    me['smb_flags'] = old['pivots'][0]['meshes'][0]['smb_flags']
        coll = None
        cj = pj.get('collision')
        pi = len(pivots)
        if cj:
            shapes = [box_from_json(b, pi) for b in cj.get('boxes', [])]
            shapes += [hull_from_json(h, pi, base_dir) for h in cj.get('hulls', [])]
            if cj.get('from_meshes'):
                for me in meshes:
                    V, F = mw.convex_hull(me['_points'])
                    shapes.append(mw.hull_shape(V, F, pivot=pi, surf=hexint(cj.get('surf'), 0x02007C00),
                                                facemat=cj.get('facemat', 0xFF)))
            for s in shapes:
                s.pop('wrapper_tail', None)
            coll = dict(flags=cj.get('flags'), shapes=shapes)
        for me in meshes:
            me.pop('_points', None)
        pivots.append(dict(name=pj.get('name'), name2=pj.get('name2'), pos=tuple(pj.get('pos', (0, 0, 0))),
                           quat=tuple(pj.get('quat', (0, 0, 0, 1))), parent=pj.get('parent', -1), w5c=pj.get('w5c', -1),
                           w60=pj.get('w60', 1 if meshes else 2), box=None, meshes=meshes, collision=coll, v34=[], v48=[]))
    hulls = None
    if d.get('hulls'):
        hj = d['hulls']
        hulls = [box_from_json(b, 0) for b in hj.get('boxes', [])] + [hull_from_json(h, 0, base_dir) for h in hj.get('hulls', [])]
    spec = dict(name=old['name'], textures=d['textures'], pivots=pivots, hulls=hulls, x40=None, sphere=None,
                cover_collision=False)
    if tmpl:
        spec['header'] = old['header']
        spec['o58'] = old['o58']
    return spec


def apply_ops(m, edit, base_dir, log):
    """Returns the new tree (collision ops edit the decoded tree in place; model/mesh ops go through the writer)."""
    for op in edit['ops']:
        kind = op['op']
        if kind == 'pivot_collision':
            op_pivot_collision(m, op, base_dir, log)
        elif kind == 'hulls':
            op_hulls(m, op, base_dir, log)
        elif kind == 'replace_model':
            spec = model_spec_from_json(op['spec'], m, base_dir)
            m = mw.build_tree(spec, derive=True)
            log.append('model rebuilt by the writer: %d pivots, %d submeshes, %d textures'
                       % (len(spec['pivots']), sum(len(p['meshes']) for p in spec['pivots']), len(spec['textures'])))
        elif kind in ('replace_mesh', 'remove_meshes'):
            spec = mw.spec_from_model(m)
            spec['sphere'] = None                       # geometry changes: derive the model sphere again
            for P in spec['pivots']:
                P['box'] = None
            P = spec['pivots'][op.get('pivot', 0)]
            if kind == 'replace_mesh':
                me = mesh_from_json(op['with'], base_dir); me.pop('_points', None)
                old = P['meshes'][op['mesh']]
                if 'smb_flags' not in op['with']:
                    me['smb_flags'] = old['smb_flags']
                P['meshes'][op['mesh']] = me
                log.append('pivot %d submesh %d replaced (%d vertices, %d triangles)'
                           % (op.get('pivot', 0), op['mesh'], len(me['vertex_bytes']) // 32, len(me['indices']) // 3))
            else:
                rm = set(op['meshes'])
                P['meshes'] = [me for i, me in enumerate(P['meshes']) if i not in rm]
                log.append('pivot %d submeshes %s removed' % (op.get('pivot', 0), sorted(rm)))
            m = mw.build_tree(spec, derive=True)
        else:
            raise Fail('unknown op ' + kind)
    return m


def cover_collision(m, log):
    """Grow the model sphere radius (+0x50) so every collision vertex (model space) lies inside it."""
    PW = pivot_world_of_tree(m)
    pts = []
    for pi, P in enumerate(m['pivots']):
        if P['coll']:
            for s in P['coll']['shapes']:
                pts += [mw.apply(PW[pi], v) for v in (s['verts'] if s['type'] == 4 else mw.box_corners(s))]
    if m['hulls']:
        for s in m['hulls']['shapes']:
            pts += list(s['verts']) if s['type'] == 4 else mw.box_corners(s)
    cx, cy, cz, r = struct.unpack_from('<4f', m['raw'], 0x44)
    if not pts:
        return dict(radius=r, grown=False)
    need = max(math.dist((cx, cy, cz), p) for p in pts)
    rep = dict(centre=[cx, cy, cz], radius_old=r, farthest_collision_vertex=need, grown=False, radius_new=r)
    if need > r + 1e-4:
        raw = bytearray(m['raw'])
        rep['radius_new'] = mw.f32(need + 0.5)
        struct.pack_into('<f', raw, 0x50, rep['radius_new'])
        m['raw'] = bytes(raw)
        rep['grown'] = True
        log.append('model sphere radius grown %.3f -> %.3f to cover collision' % (r, rep['radius_new']))
    return rep


# ------------------------------------------------------------------------------------------------ the quadtree port
def hull_tree(shapes):
    """FUN_00856830 / FUN_008591a0 parameters (port of coll_replace.hull_tree)."""
    def sphere_of(h):
        if h['type'] != 4:
            return (*h['center'], math.sqrt(sum((x * 0.5) ** 2 for x in h['size'])))
        if h['sphere'][3] >= 0.0:
            return h['sphere']
        V = h['verts']
        c = [(min(v[i] for v in V) + max(v[i] for v in V)) * 0.5 for i in range(3)]
        return (c[0], c[1], c[2], max(math.dist(c, v) for v in V))
    sp = [sphere_of(s) for s in shapes]
    E = max(max(-(s[0] - s[3]), s[0] + s[3], s[2] + s[3], -(s[2] - s[3])) for s in sp)
    size = E * 2.0
    depth = int(math.log(size / 1.0) / math.log(2.0)) if size > 1 else 0
    return dict(elements=len(shapes), extent=E, root_size=size, depth=depth, cell=size / (1 << depth))


# ------------------------------------------------------------------------------------------------ block surgery
def find_model(info, starts, name):
    hits = [k for k, R in enumerate(starts) if tb.u32(info, R) == 3 and tb.record_name(info, R).lower() == name.lower()]
    if len(hits) != 1:
        raise Fail('model %s found %d times in the block' % (name, len(hits)))
    return hits[0]


def collision_regions(m):
    regs = [('piv', P['coll']) for P in m['pivots'] if P['coll']]
    if m['hulls']:
        regs.append(('f54', m['hulls']))
    return regs


def verify(old, new_bytes, k_mod, rec_new, m_old, m_new, render_changed):
    rep = {}
    chk = tb.Block(new_bytes, old.ext)
    s2 = tb.record_starts(chk.info, chk.n)
    s1 = tb.record_starts(old.info, old.n)
    e1 = s1[1:] + [len(old.info)]; e2 = s2[1:] + [len(chk.info)]
    rep['1_strict_parse'] = dict(N=chk.n, records_found=len(s2), info_bytes_old=len(old.info), info_bytes_new=len(chk.info))
    if (chk.timestamp, chk.prop_ck, chk.cmd_ck, chk.prefix) != (old.timestamp, old.prop_ck, old.cmd_ck, old.prefix):
        raise Fail('block header changed')
    if chk.payloads != old.payloads:
        raise Fail('payloads changed')
    same = 0
    for k in range(old.n):
        if k == k_mod:
            continue
        if bytes(chk.info[s2[k]:e2[k]]) != bytes(old.info[s1[k]:e1[k]]):
            raise Fail('untouched record %d changed' % k)
        same += 1
    rep['2_other_records_identical'] = same
    info = bytes(chk.info); R = s2[k_mod]
    if info[R:e2[k_mod]] != rec_new:
        raise Fail('edited record not where expected')
    m2 = tm.decode(info, R, e2[k_mod])
    if tm.encode(m2) != rec_new:
        raise Fail('edited record does not re-encode identically')
    rep['3_edited_record'] = dict(bytes_old=e1[k_mod] - s1[k_mod], bytes_new=len(rec_new), decodes=True,
                                  reencodes_identically=True, layout_allocations=len(m2['layout']))
    # every model of the new block decodes and re-encodes; every collision region round-trips
    nmod = nreg = 0
    for k, Rk in enumerate(s2):
        if tb.u32(info, Rk) != 3:
            continue
        mk = tm.decode(info, Rk, e2[k])
        if tm.encode(mk) != info[Rk:e2[k]]:
            raise Fail('model record %d does not round-trip' % k)
        nmod += 1
        nreg += len(collision_regions(mk))
    rep['4_all_models_roundtrip'] = dict(models=nmod, collision_regions=nreg)
    # render meshes (the project's extractor) unchanged unless the edit changes them
    import tod_model_extract as me
    a = me.extract_model(bytes(old.info), s1[k_mod], 'old'); b = me.extract_model(info, R, 'new')
    def sig(mm):
        return [(x['pivot'], len(x['verts']), x['indices'][:50], x['verts'][:5]) for x in mm['meshes']] if mm else None
    if not render_changed and sig(a) != sig(b):
        raise Fail('render meshes read differently after a collision-only edit')
    rep['5_render_meshes'] = dict(changed=render_changed, meshes_old=len(a['meshes']) if a else 0,
                                  meshes_new=len(b['meshes']) if b else 0,
                                  verts_new=sum(len(x['verts']) for x in b['meshes']) if b else 0)
    # model sphere covers collision
    PW = pivot_world_of_tree(m2)
    cx, cy, cz, r = struct.unpack_from('<4f', m2['raw'], 0x44)
    far = 0.0
    for pi, P in enumerate(m2['pivots']):
        if P['coll']:
            for s in P['coll']['shapes']:
                for v in (s['verts'] if s['type'] == 4 else mw.box_corners(s)):
                    far = max(far, math.dist((cx, cy, cz), mw.apply(PW[pi], v)))
    if m2['hulls']:
        for s in m2['hulls']['shapes']:
            for v in (s['verts'] if s['type'] == 4 else mw.box_corners(s)):
                far = max(far, math.dist((cx, cy, cz), v))
    rep['6_sphere_covers_collision'] = dict(radius=r, farthest_collision_vertex=far, ok=far <= r + 1e-4)
    if m2['hulls']:
        rep['7_hull_quadtree'] = dict(before=hull_tree(m_old['hulls']['shapes']) if m_old['hulls'] else None,
                                      after=hull_tree(m2['hulls']['shapes']))
    # shape sanity for every shape of the edited record
    bad = []
    for kind, reg in collision_regions(m2):
        for j, s in enumerate(reg['shapes']):
            if s['type'] != 4:
                continue
            nv = len(s['verts'])
            if nv > 255 or s['bits'] != max(1, nv.bit_length()) or len(s['facemat']) != len(s['faces']):
                bad.append((kind, j))
            if any(i >= nv for f in s['faces'] for i in f):
                bad.append((kind, j, 'index'))
    if bad:
        raise Fail('inconsistent shapes %s' % bad[:5])
    rep['8_shapes_consistent'] = True
    return rep, m2


def write_zip(path, entries, naz):
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        for entry, data in entries:
            zi = zipfile.ZipInfo(entry, date_time=(2005, 8, 21, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED; zi.create_system = 0; zi.external_attr = 0
            zf.writestr(zi, data)
    os.replace(tmp, path)
    a = tb.Archive(path)
    base = tb.Archive(naz)
    out = []
    for entry, data in entries:
        hit = a.find('/' + entry)
        if a.naz or hit is None or hit[2] != entry or hit[1] != len(data):
            raise Fail('zip: engine lookup failed for ' + entry)
        with open(path, 'rb') as f:
            f.seek(hit[0])
            if f.read(hit[1]) != data:
                raise Fail('zip: bytes at the engine offset differ for ' + entry)
        if base.find('/' + entry) is None:
            raise Fail('zip: %s is not an entry of blocks.naz (the override would never be asked for)' % entry)
        out.append(dict(entry=entry, data_offset=hit[0], bytes=len(data), sha256=sha(data)))
    collide = [n for c, (_, _, n) in base.table.items() if c in a.table and n != a.table[c][2]]
    if collide:
        raise Fail('zip: name hash collides with ' + collide[0])
    return dict(zip_bytes=os.path.getsize(path), entries=out, engine_lookup_ok=True)


def run(edit, out_dir, naz, block_file=None, entry=None, zip_name='model_override.zip', base_dir='.'):
    os.makedirs(out_dir, exist_ok=True)
    arch = tb.Archive(naz)
    jobs = []
    if block_file:
        jobs.append((open(block_file, 'rb').read(), entry or os.path.basename(block_file), block_file))
    else:
        for e in edit['blocks']:
            jobs.append((arch.read(e), e, e))
    rep = dict(edit=edit, blocks=[])
    zentries = []
    for data, ent, src in jobs:
        log = []
        br = dict(block=src, entry=ent, base_sha256=sha(data), log=log)
        rep['blocks'].append(br)
        ext = os.path.splitext(ent)[1]
        old = tb.Block(data, ext)
        info = bytes(old.info)
        starts = tb.record_starts(info, old.n); ends = starts[1:] + [len(info)]
        k = find_model(info, starts, edit['model'])
        R, E = starts[k], ends[k]
        m_old = tm.decode(info, R, E)
        if tm.encode(m_old) != info[R:E]:
            raise Fail('model does not round-trip before the edit')
        m = tm.decode(info, R, E)                      # a fresh copy to edit
        render_changed = any(op['op'] in ('replace_model', 'replace_mesh', 'remove_meshes') for op in edit['ops'])
        m = apply_ops(m, edit, base_dir, log)
        if edit.get('cover_collision', True):
            br['sphere'] = cover_collision(m, log)
        rec = tm.encode(m)
        nb = tb.Block(data, ext)
        nb.info = bytearray(info[:R] + rec + info[E:])
        out = nb.serialize()
        r, m2 = verify(old, out, k, rec, m_old, m, render_changed)
        br.update(r)
        br['record_index'] = k
        name = os.path.basename(ent)
        with open(os.path.join(out_dir, name), 'wb') as f:
            f.write(out)
        br['block_sha256'] = sha(out); br['block_bytes'] = len(out); br['block_bytes_old'] = len(data)
        zentries.append((ent, out))
    rep['zip'] = write_zip(os.path.join(out_dir, zip_name), zentries, naz)
    line = 'filesystem = ' + ', '.join([zip_name] + BASE_ARCHIVES)
    open(os.path.join(out_dir, 'configpc_line.txt'), 'w').write(line + '\n')
    rep['configpc_line'] = line
    rep['result'] = 'PASS'
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--edit', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--naz', default=DEFAULT_NAZ)
    ap.add_argument('--block', help='edit this block file instead of the archive entries (e.g. a TOD HD rebuilt block)')
    ap.add_argument('--entry', help='archive entry name for --block')
    ap.add_argument('--zip', default='model_override.zip')
    a = ap.parse_args()
    edit = json.load(open(a.edit))
    try:
        rep = run(edit, a.out, a.naz, a.block, a.entry, a.zip, os.path.dirname(os.path.abspath(a.edit)))
    except Fail as e:
        rep = dict(edit=edit, result='FAIL: %s' % e)
    json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str)[:6000])


if __name__ == '__main__':
    main()
