"""Rewrite one model's static collision (model+0x54 HullList) in an asset block and package it like TOD.exe loads it.

  python coll_replace.py --block <archive name or file> --edit edit.json --out DIR [--deploy TESTGAME]

edit.json:
  {"model": "/data/Models/.../X.model",
   "remove": [hull indices to drop],
   "add_boxes": [{"min": [x,y,z], "max": [x,y,z], "space": "model" | "world",
                  "world": {"pos": [..], "quat": [x,y,z,w]}      (only for space world: the entity transform),
                  "surf": "0x02007C00", "facemat": 255, "name": "..."}]}

What is written (all of it follows the engine's NativeSerializer layout that tools/roundtrip.py reproduces byte for byte
on all 5141 shipped collision regions):
  - the HullList region re-encoded at the same offset with the edited element list (todcoll.write_region),
  - the model's +0x58 object (always the last thing in a MODEL record, directly after the HullList; checked) moved
    by the size delta, with the header's +0x58 self-relative pointer patched; nothing else in the record moves,
  - the record padded to 16, later records shifted (unchanged bytes), block header S updated (N, timestamp, checksums,
    sizes table and payloads unchanged).
The hull quadtree (HullList+0x10) is NOT stored: the engine builds it at load (FUN_00856830 from FUN_00857960 mode 3
and Scene::BuildSceneTree 0x896BA0); it stays 0 on disk. New hulls get bounding-sphere radius -1 (the engine computes
it, FUN_00854130 -> FUN_008b0680), exactly like the shipped per-pivot hulls.

Checks (all must pass, else nothing is packaged): strict block parse and record scan; header unchanged; every other
record byte-identical; modified record: bytes before the region identical, region decodes and re-encodes identically,
removed hulls gone and kept hulls identical, added boxes decode to the intended vertices/faces (closed, outward);
the +0x58 object identical; the render-mesh extractor reads the same meshes; every collision region of every model in
the new block round-trips; the load-time quadtree parameters (port of FUN_00856830/FUN_008591a0) are computed for
before/after; the zip is read back through the engine's OpenZip/FindFile port.
"""
import argparse, hashlib, json, math, os, shutil, struct, subprocess, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todblock as tb
import todcoll as tc

NAZ = os.environ.get("TOD_NAZ", r"C:\GOG Games\Total Overdose\blocks.naz")   # the GOG archive; read only
FORBIDDEN_DEPLOY = [os.path.normcase(os.path.abspath(p)) for p in
                    (r"C:\GOG Games\Total Overdose",)]
BASE_ARCHIVES = ["blocks.naz", "sounds.naz", "videos00.naz", "videos01.naz"]
ZIP_NAME = "coll_override.zip"


class Fail(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ geometry helpers
def qconj(q): return (-q[0], -q[1], -q[2], q[3])
def qrot(q, v):
    x, y, z, w = q; vx, vy, vz = v
    tx = 2*(y*vz - z*vy); ty = 2*(z*vx - x*vz); tz = 2*(x*vy - y*vx)
    return (vx+w*tx+(y*tz-z*ty), vy+w*ty+(z*tx-x*tz), vz+w*tz+(x*ty-y*tx))
def f32(x): return struct.unpack('<f', struct.pack('<f', x))[0]

BOX_TRIS = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2),
            (1, 3, 7), (1, 7, 5)]


def box_hull(mn, mx, template, surf=None, facemat=None, name=None):
    """8-vertex VertexCloud box: 12 triangles, cross(v1-v0, v2-v0) pointing outward (the shipped convention)."""
    verts = [(f32(x), f32(y), f32(z)) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    faces = [list(t) for t in BOX_TRIS]
    cen = [(mn[i] + mx[i]) / 2 for i in range(3)]
    for f in faces:                                    # orient each face outward
        a, b, c = (verts[i] for i in f)
        n = [(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]), (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),
             (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])]
        if sum(n[i] * (a[i] - cen[i]) for i in range(3)) < 0:
            f[1], f[2] = f[2], f[1]
    nv = len(verts)
    aux = dict(raw=tc.AUX_TEMPLATE, name=name if name is not None else (template['aux'] or {}).get('name', ''))
    return dict(type=4, sphere=(0.0, 0.0, 0.0, -1.0), extrude=(0.0, 0.0, 0.0),
                flags20=template['flags20'], surf=surf if surf is not None else template['surf'], x28=0,
                lowbyte=template['lowbyte'] & 0x7F, bits=max(1, nv.bit_length()), verts=verts, faces=faces,
                facemat=[facemat if facemat is not None else 0xFF] * len(faces), u16list=None, facesurf=None,
                aux=aux, wrapper_tail=bytes(24))


# ------------------------------------------------------------------ the engine's load-time hull quadtree (parameters)
def support_extent(h, d):
    return max(v[0] * d[0] + v[1] * d[1] + v[2] * d[2] for v in h['verts'])


def sphere_of(h):
    if h['sphere'][3] >= 0.0:
        return h['sphere']
    V = h['verts']                                     # FUN_008b0680: AABB centre (FUN_008aff90), max distance
    c = [(min(v[i] for v in V) + max(v[i] for v in V)) * 0.5 for i in range(3)]
    return (c[0], c[1], c[2], max(math.dist(c, v) for v in V))


def hull_tree(shapes):
    """Port of FUN_00856830 + FUN_008591a0 + FUN_00859310 (parameters only): root covers [-E, E] in model X/Z, where E is
    the largest |x +- r| / |z +- r| over the element bounding spheres; size 2E (DAT_009b363c = 2.0), minimum cell 1.0,
    depth = (int)log2(size), cell = size / 2^depth. Each element is filed by its X/Z support extents."""
    sp = [sphere_of(s) for s in shapes]
    mnx = min(s[0] - s[3] for s in sp); mxx = max(s[0] + s[3] for s in sp)
    mnz = min(s[2] - s[3] for s in sp); mxz = max(s[2] + s[3] for s in sp)
    E = max(-mnx, mxx, mxz, -mnz)
    size = E * 2.0
    depth = int(math.log(size / 1.0) / math.log(2.0))
    cell = size / (1 << depth)
    outside = 0; cells = []
    for s in shapes:
        x0 = -support_extent(s, (-1, 0, 0)); x1 = support_extent(s, (1, 0, 0))
        z0 = -support_extent(s, (0, 0, -1)); z1 = support_extent(s, (0, 0, 1))
        ix0 = int((x0 + size * 0.5) / cell); ix1 = int((x1 + size * 0.5) / cell)
        iz0 = int((z0 + size * 0.5) / cell); iz1 = int((z1 + size * 0.5) / cell)
        if min(ix0, iz0) < 0 or max(ix1, iz1) >= (1 << depth):
            outside += 1
        cells.append((ix0, ix1, iz0, iz1))
    return dict(elements=len(shapes), extent=E, root_size=size, depth=depth, cell=cell, elements_outside_root=outside), cells


# ------------------------------------------------------------------ record surgery
def model_record_index(info, starts, model):
    hits = [k for k, R in enumerate(starts) if tc.u32(info, R) == 3 and tb.record_name(info, R).lower() == model.lower()]
    if len(hits) != 1:
        raise Fail('model %s found %d times in the block' % (model, len(hits)))
    return hits[0]


def rebuild_model(info, R, E, edit):
    lo = tc.deref(info, R + 0x54)
    o58 = tc.deref(info, R + 0x58)
    if lo is None:
        raise Fail('model has no HullList (+0x54); adding a new list is not implemented here')
    if o58 is None:
        raise Fail('model has no +0x58 object')
    reg, end = tc.read_region(info, lo, 'f54')
    if end != o58:
        raise Fail('HullList is not directly followed by the +0x58 object')
    c0, c5c = tc.i32(info, o58 + 4), tc.i32(info, o58 + 0x60)
    if c0 or c5c:
        raise Fail('+0x58 object carries list data; its content end is not derived here')
    content_end = o58 + 0x6C
    if E != tb.a16(content_end) or any(info[content_end:E]):
        raise Fail('record does not end at align16(+0x58 object end)')
    old_shapes = reg['shapes']
    remove = set(edit.get('remove', []))
    if any(i < 0 or i >= len(old_shapes) for i in remove):
        raise Fail('remove index out of range')
    template = next(s for s in old_shapes if s['type'] == 4)
    kept = [s for i, s in enumerate(old_shapes) if i not in remove]
    added = []
    for b in edit.get('add_boxes', []):
        mn, mx = b['min'], b['max']
        if b.get('space', 'model') == 'world':
            W = b['world']; q = qconj(tuple(W['quat'])); iq = qconj(q)       # entity rotation (conjugated convention)
            corners = [qrot(iq, (x - W['pos'][0], y - W['pos'][1], z - W['pos'][2]))
                       for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
            mn = [min(c[i] for c in corners) for i in range(3)]; mx = [max(c[i] for c in corners) for i in range(3)]
        surf = int(b['surf'], 16) if isinstance(b.get('surf'), str) else b.get('surf')
        added.append(box_hull(mn, mx, template, surf, b.get('facemat'), b.get('name')))
    new_reg = dict(kind='f54', hdr=dict(vec=dict(cnt=len(kept) + len(added), cap=len(kept) + len(added),
                                                 flags=reg['hdr']['vec']['flags']), w10=0),
                   shapes=kept + added)
    region = tc.write_region(new_reg, lo)
    delta = (lo + len(region)) - o58
    head = bytearray(info[R:lo])
    struct.pack_into('<I', head, 0x58, (tc.u32(info, R + 0x58) + delta) & 0xFFFFFFFF)
    # Model bounding sphere (header +0x44 centre, +0x50 radius, model space). The scene registers the model by it, and
    # sphere probes (the player's body, the camera) never see a hull outside it (in game, run r5: Ram ran through a
    # block added 37 m outside Chunk_10's sphere; run r6 with the radius grown: held). Grow the radius when needed.
    cx, cy, cz, rad = struct.unpack_from('<4f', info, R + 0x44)
    need = max(math.dist((cx, cy, cz), v) for sh in new_reg['shapes'] if sh['type'] == 4 for v in sh['verts'])
    bounds = dict(centre=[cx, cy, cz], radius_old=rad, farthest_hull_vertex=need, radius_new=rad)
    if need > rad and edit.get('grow_bounds', True):
        bounds['radius_new'] = f32(need + 0.5)
        struct.pack_into('<f', head, 0x50, bounds['radius_new'])
    obj58 = info[o58:content_end]
    rec = bytes(head) + region + obj58
    rec += bytes(tb.a16(len(rec)) - len(rec))
    return rec, dict(old_hulls=len(old_shapes), removed=sorted(remove), added=len(added), new_hulls=len(new_reg['shapes']),
                     region_bytes_old=end - lo, region_bytes_new=len(region), record_bytes_old=E - R,
                     record_bytes_new=len(rec), bounds=bounds), old_shapes, new_reg, added


def verify(old, new_bytes, k_mod, R_old, E_old, rec, edit, old_shapes, added):
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
    rep['2_untouched_records_identical'] = same
    info = bytes(chk.info); R = s2[k_mod]
    if info[R:e2[k_mod]] != rec:
        raise Fail('modified record not where expected')
    lo_old = tc.deref(old.info, R_old + 0x54); lo = tc.deref(info, R + 0x54)
    if info[R:R + 0x50] + info[R + 0x54:R + 0x58] + info[R + 0x5C:lo] !=             bytes(old.info[R_old:R_old + 0x50]) + bytes(old.info[R_old + 0x54:R_old + 0x58]) + bytes(old.info[R_old + 0x5C:lo_old]):
        raise Fail('bytes before the HullList changed (other than the +0x50 radius and the +0x58 pointer)')
    reg, end = tc.read_region(info, lo, 'f54')
    if tc.write_region(reg, lo) != info[lo:end]:
        raise Fail('new HullList does not re-encode identically')
    if end != tc.deref(info, R + 0x58):
        raise Fail('+0x58 pointer does not follow the new HullList')
    if info[end:end + 0x6C] != bytes(old.info[tc.deref(old.info, R_old + 0x58):tc.deref(old.info, R_old + 0x58) + 0x6C]):
        raise Fail('+0x58 object changed')
    remove = set(edit.get('remove', []))
    kept_old = [s for i, s in enumerate(old_shapes) if i not in remove]
    for a, b in zip(kept_old, reg['shapes']):
        for key in ('verts', 'faces', 'surf', 'flags20', 'facemat', 'sphere', 'lowbyte'):
            if a.get(key) != b.get(key):
                raise Fail('kept hull field %s changed' % key)
    for want, got in zip(added, reg['shapes'][len(kept_old):]):
        if want['verts'] != got['verts'] or want['faces'] != got['faces'] or got['facemat'] != want['facemat']:
            raise Fail('added hull does not decode to the intended geometry')
        edges = {}
        for f in got['faces']:
            for q in range(3):
                edges[(f[q], f[(q + 1) % 3])] = edges.get((f[q], f[(q + 1) % 3]), 0) + 1
        if not all(edges.get((b, a), 0) == 1 for (a, b) in edges):
            raise Fail('added box is not a closed manifold')
    rep['3_modified_record'] = dict(region_reencodes=True, kept_hulls_identical=len(kept_old),
                                    added_hulls_decode=len(added), closed_outward_boxes=True, obj58_identical=True)
    import tod_model_extract as me
    a = me.extract_model(bytes(old.info), R_old, 'old'); b = me.extract_model(info, R, 'new')
    def sig(m):
        return [(x['pivot'], len(x['verts']), x['indices'][:50], x['verts'][:5]) for x in m['meshes']] if m else None
    if sig(a) != sig(b):
        raise Fail('render meshes read differently after the edit')
    rep['4_render_meshes_unchanged'] = len(a['meshes']) if a else 0
    nreg = 0
    for Rk in s2:
        if tc.u32(info, Rk) != 3:
            continue
        pp = tc.deref(info, Rk + 0x30)
        regs = [('piv', tc.deref(info, pp + i * 0x7C + 0x44)) for i in range(tc.i32(info, Rk + 0x34))]
        regs = [r for r in regs if r[1] is not None]
        f = tc.deref(info, Rk + 0x54)
        if f is not None:
            regs.append(('f54', f))
        for kind, l in regs:
            g, e = tc.read_region(info, l, kind)
            if tc.write_region(g, l) != info[l:e]:
                raise Fail('collision region of record at %x does not round-trip' % Rk)
            nreg += 1
    rep['5_all_collision_regions_roundtrip'] = nreg
    t_old, _ = hull_tree(old_shapes)
    t_new, cells = hull_tree(reg['shapes'])
    if t_new['elements_outside_root']:
        raise Fail('an element falls outside the quadtree root')
    rep['6_load_time_quadtree'] = dict(before=t_old, after=t_new, added_cells=cells[len(kept_old):])
    return rep, chk


def write_zip(path, entry, data):
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        zi = zipfile.ZipInfo(entry, date_time=(2005, 8, 21, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_STORED; zi.create_system = 0; zi.external_attr = 0
        zf.writestr(zi, data)
    os.replace(tmp, path)
    st = os.stat(NAZ)
    os.utime(path, (st.st_atime, st.st_mtime))
    a = tb.Archive(path)
    hit = a.find('/' + entry)
    if a.naz or hit is None or hit[2] != entry or hit[1] != len(data):
        raise Fail('zip: engine lookup failed')
    with open(path, 'rb') as f:
        f.seek(hit[0])
        if f.read(hit[1]) != data:
            raise Fail('zip: bytes at the engine offset differ')
    base = tb.Archive(NAZ)
    collide = [n for c, (_, _, n) in base.table.items() if c in a.table and n != a.table[c][2]]
    if collide:
        raise Fail('zip: name hash collides with ' + collide[0])
    return dict(zip_bytes=os.path.getsize(path), entry=entry, data_offset=hit[0], engine_lookup_ok=True,
                sha256_block=sha(data))


def game_running():
    out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout.lower()
    return '"tod.exe"' in out or '"totaloverdose.exe"' in out


def deploy(game_dir, zip_path):
    gd = os.path.normcase(os.path.abspath(game_dir))
    if any(gd == f or gd.startswith(f + os.sep) for f in FORBIDDEN_DEPLOY):
        raise Fail('refusing to deploy into %s' % game_dir)
    if game_running():
        raise Fail('a game is running; not touching any game folder now')
    shutil.copy2(zip_path, os.path.join(game_dir, ZIP_NAME))
    return dict(deployed_to=game_dir, note='add %s first on the filesystem line of configpc.txt to use it' % ZIP_NAME)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--block', required=True, help='archive entry name (e.g. data_pc/.../submap01_map09_jungle.submap) or a file')
    ap.add_argument('--edit', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--deploy')
    ap.add_argument('--entry', help='archive entry name for the zip when --block is a file (e.g. a TOD HD rebuilt block)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    edit = json.load(open(a.edit))
    if os.path.exists(a.block):
        base = open(a.block, 'rb').read(); entry = a.entry
    else:
        base = tb.Archive(NAZ).read(a.block); entry = a.block
    ext = os.path.splitext(a.block)[1]
    rep = dict(block=a.block, base_sha256=sha(base), edit=edit)
    try:
        old = tb.Block(base, ext)
        info = bytes(old.info)
        starts = tb.record_starts(info, old.n); ends = starts[1:] + [len(info)]
        k = model_record_index(info, starts, edit['model'])
        rec, summary, old_shapes, new_reg, added = rebuild_model(info, starts[k], ends[k], edit)
        rep['summary'] = summary
        nb = tb.Block(base, ext)
        nb.info = bytearray(info[:starts[k]] + rec + info[ends[k]:])
        out = nb.serialize()
        r, chk = verify(old, out, k, starts[k], ends[k], rec, edit, old_shapes, added)
        rep.update(r)
        name = os.path.basename(a.block)
        with open(os.path.join(a.out, name), 'wb') as f:
            f.write(out)
        rep['block_sha256'] = sha(out); rep['block_bytes'] = len(out)
        if entry:
            rep['zip'] = write_zip(os.path.join(a.out, ZIP_NAME), entry, out)
            line = 'filesystem = ' + ', '.join([ZIP_NAME] + BASE_ARCHIVES)
            open(os.path.join(a.out, 'configpc_line.txt'), 'w').write(line + '\n')
            rep['configpc_line'] = line
            if a.deploy:
                rep['deploy'] = deploy(a.deploy, os.path.join(a.out, ZIP_NAME))
        rep['result'] = 'PASS'
    except Fail as e:
        rep['result'] = 'FAIL: %s' % e
    json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != '6_load_time_quadtree'}, indent=1))
    if '6_load_time_quadtree' in rep:
        q = rep['6_load_time_quadtree']; print('quadtree before', q['before']); print('quadtree after ', q['after'])


if __name__ == '__main__':
    main()
