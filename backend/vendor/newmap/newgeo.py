"""newgeo.py - the "new_geometry" step of make_new_map.py: turn a clone of Map10's blocks into a map with its OWN ground.

Input  : one map entry of the params with "new_geometry" (see make_new_map.py docstring), the source blocks from
         blocks.naz (read only), the clone's final names.
Output : two BASE block files (map + submap, root fragments already renamed) that make_new_map then feeds to
         submaptool as the clone source, so the usual graft recipe (arrival, loaders, walls, savepoint, pickups, models)
         runs on top of them unchanged.

What it does to the Map10 map block (a new block: saves do not address it, so node indices may change freely):
  1. root rename (same length)
  2. remove the train level from the root fragment (MM125 / MM120 folders and the instancing folders of the havoc
     objects, soundtriggers, default data, surround geometry); LightSettings (sky, fog, sun, lights) and the menu camera stay
  3. drop_unused_assets: remove every model / texture / fragment record nothing refers to any more (names are plain
     ASCII in the fragment payloads and in the model texture lists), keep the sky and the lighting asset
  4. append the new texture records (DXT1 / RGBA32, with their payloads) and model records (model_writer, HullList)
  5. one Folder + one Model node per placement in the root fragment (cloned from a shipped terrain Model node, so every
     engine property keeps a shipped value); statically_lit False (no MeshColor entry exists for a new node)
Every written block is re-parsed with TWO independent readers (the fragment writer's and TOD HD's strict texture reader
that checks each texture payload against the engine's size rule) and every model is decoded and re-encoded.
"""
import json
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_MW = os.path.join(os.environ.get('TOD_TOOLS') or os.path.join(os.path.dirname(HERE), 'tools'), 'model_writer')
if _MW not in sys.path:
    sys.path.insert(1, _MW)
import tex_gen as TX            # noqa: E402
import geomkit as GK            # noqa: E402

DROP_FOLDERS = ['MM125_SaveAngelFolder', 'MM120_RunawayTrainFolder', 'Soundtriggers', 'MAINMAP10_HavocObjects',
                'MAINMAP10_Default_Data', 'Surround_Geometry']
TERRAIN_TEMPLATE_FOLDER = '0x002000ED'          # Folder "Terrain" (identity transform) of Map10's root fragment
TERRAIN_TEMPLATE_MODEL = '0x002000F3'           # Model Terrain_Canyon_Tile_01: a shipped hull-collision terrain node (flags 2320)


class GeoError(Exception):
    pass


def a16(x):
    return (x + 15) & ~15


# ------------------------------------------------------------------------------------------------ block records
class Records:
    """INFO of a block split into records (16-aligned slices) with their payloads, editable."""

    def __init__(self, tb, block):
        info = bytes(block.info)
        st = tb.record_starts(info, block.n)
        en = st[1:] + [len(info)]
        self.tb = tb
        self.items = []
        for k, (R, E) in enumerate(zip(st, en)):
            self.items.append(dict(type=tb.u32(info, R), name=tb.record_name(info, R), rec=info[R:E], payload=block.payloads[k]))

    def names(self):
        return [i['name'] for i in self.items]

    def write_into(self, block):
        block.info = bytearray(b''.join(i['rec'] for i in self.items))
        block.payloads = [i['payload'] for i in self.items]
        block.n = len(self.items)


def rename_root(raw, ext, tb, old, new, fr_names):
    """Same-length root fragment rename: the full /data/... path of `old` inside INFO."""
    b = tb.Block(raw, ext)
    hits = [n for n in fr_names(b) if n.split('/')[-1] == old]
    if len(hits) != 1:
        raise GeoError('rename_root: %s found %d times' % (old, len(hits)))
    oldfull = hits[0]
    newfull = oldfull[:-len(old)] + new
    if len(newfull) != len(oldfull):
        raise GeoError('rename_root: new name must have the same length')
    b.info = bytearray(bytes(b.info).replace(oldfull.encode(), newfull.encode()))
    return b


# ------------------------------------------------------------------------------------------------ textures and models
def make_textures(spec_tex, templates, folder):
    """-> {short name: dict(full name, record, payload, w, h, fmt)}"""
    out = {}
    for t in spec_tex:
        nm = t['name']
        full = '/data/Models/%s/textures/%s.bmp' % (folder, nm)
        size = int(t.get('size', 256))
        fmt = t.get('format', 'DXT1')
        rec, pay, prev = TX.build_texture(full, t.get('kind', nm.lower()), size, fmt, int(t.get('seed', 1)), templates)
        out[nm] = dict(name=full, record=rec, payload=pay, w=size, h=size, fmt=fmt, preview=prev)
    return out


def make_models(spec_models, folder, tex, mw, tm, log):
    """-> list of dict(short, full, record, stats). Model record names: /data/Models/<folder>/<name>.model"""
    out = []
    texmap = {k: v['name'] for k, v in tex.items()}
    for md in spec_models:
        short = md['name']
        full = '/data/Models/%s/%s.model' % (folder, short)
        mb = GK.ModelBuilder(full)
        for p in md['parts']:
            t = p['type']
            col = p.get('collide', True)
            if t == 'box':
                mb.add_box(p['min'], p['max'], p['tex'], p.get('uv', 0.25), tuple(p.get('skip', ())), col, p.get('material'),
                           p.get('surface'), tuple(p.get('uv_off', (0.0, 0.0))))
            elif t == 'wedge':
                mb.add_wedge(p['min'], p['max'], p['rise'], p['tex'], p.get('uv', 0.25), col, p.get('material'), p.get('surface'))
            elif t == 'rock':
                mb.add_rock(p['center'], p['radius'], p['tex'], p.get('uv', 0.2), p.get('squash', 0.7), p.get('seed', 1), col,
                            p.get('material', 'Stone'), p.get('surface'))
            elif t == 'heightfield':
                mb.add_heightfield(p['xs'], p['zs'], p['heights'], p['tex'], p.get('steep_tex'), p.get('steep', 1.2),
                                   p.get('uv', 0.125), p.get('collide'), p.get('material', 'Dirt'), p.get('surface'))
            else:
                raise GeoError('model %s: unknown part type %r' % (short, t))
        bad = [t for t in mb.textures() if t not in texmap]
        if bad:
            raise GeoError('model %s uses undeclared textures %s' % (short, bad))
        spec = GK.build_spec(mb, mw, texmap)
        tree = mw.build_tree(spec, derive=True)
        rec = tm.encode(tree)
        rec = rec + bytes(a16(len(rec)) - len(rec))
        m2 = tm.decode(rec, 0, len(rec))
        if tm.encode(m2) != rec and tm.encode(m2) != rec[:len(tm.encode(m2))]:
            raise GeoError('model %s does not round-trip' % short)
        htris = []
        for sh in spec['hulls'] or []:
            V = sh['verts']
            for f in sh['faces']:
                for k in range(1, len(f) - 1):
                    htris.append((V[f[0]], V[f[k]], V[f[k + 1]]))
        verts = sum(len(g.P) for g in mb.groups.values())
        tris = sum(len(g.tris) for g in mb.groups.values())
        out.append(dict(short=short, full=full, record=rec, textures=mb.textures(), vertices=verts, triangles=tris, hull_tris=htris,
                        hulls=len(mb.hulls), bytes=len(rec),
                        sphere=[round(x, 3) for x in struct.unpack_from('<4f', m2['raw'], 0x44)]))
    return out


# ------------------------------------------------------------------------------------------------ dropping assets
def referenced_text(recs, frag_payload_lower):
    pass


def drop_unused(recs, K, keep_names, log):
    """Remove records nothing refers to. Fragments are kept when the root, a kept fragment's Folder `fragment` property
    (any string occurrence of their path) or keep_names mentions them; models when a kept fragment payload names them;
    textures when a kept model lists them or a kept fragment payload names them. Iterates to a fixed point."""
    tb, tm = K.tb, K.tm
    keep = [True] * len(recs.items)
    low = [i['name'].lower() for i in recs.items]
    tail = [n[5:] if n.startswith('/data') else n for n in low]
    kn = {n.lower() for n in keep_names}
    changed = True
    rounds = 0
    while changed:
        changed = False
        rounds += 1
        frag_text = b'\0'.join(recs.items[k]['payload'].lower() for k, i in enumerate(recs.items) if i['type'] == 4 and keep[k])
        # texts naming assets: kept fragments + kept models' texture lists
        model_tex = set()
        for k, i in enumerate(recs.items):
            if i['type'] == 3 and keep[k]:
                m = tm.decode(i['rec'], 0, len(i['rec']))
                for t in m['texnames']:
                    s = t['s'].decode('latin-1').lower()
                    model_tex.add(s[5:] if s.startswith('/data') else s)
        for k, i in enumerate(recs.items):
            if not keep[k]:
                continue
            t, n = i['type'], low[k]
            if n in kn or n.endswith('.fragment') and k == 0:
                continue
            if t == 4:                             # fragments are referenced by file name (the folder prefix differs per map)
                ok = n.split('/')[-1].encode() in frag_text or n in kn
            elif t == 3:
                ok = tail[k].encode() in frag_text
            elif t == 0:
                ok = tail[k] in model_tex or tail[k].encode() in frag_text
            elif t == 10:                         # MeshColor (baked lighting): the lighting asset is named by StaticLighting
                ok = tail[k].encode() in frag_text
            else:
                ok = True                          # anything else: keep
            if not ok:
                keep[k] = False
                changed = True
    dropped = [(recs.items[k]['type'], recs.items[k]['name'], len(recs.items[k]['rec']), len(recs.items[k]['payload']))
               for k in range(len(keep)) if not keep[k]]
    recs.items = [i for k, i in enumerate(recs.items) if keep[k]]
    return dropped, rounds


# ------------------------------------------------------------------------------------------------ the main entry
def build(m, src, name, out_dir, K, T, fragtool_dir=None):
    """Returns dict(map_file, submap_file, report). m: the map entry; src: SOURCES entry of make_new_map."""
    ft, fe, tb, tf, tm, mw, S = K.ft, K.fe, K.tb, K.tf, K.tm, K.mw, K.S
    ng = m['new_geometry']
    rep = dict(steps=[])
    folder = ng.get('folder', name)                       # asset folder name under /data/Models/
    os.makedirs(out_dir, exist_ok=True)
    # --- sources
    arch = ft.archive()
    map_ent, sub_ent = ft.resolve_entry(src['map_entry']), ft.resolve_entry(src['submap_entry'])
    mroot = src['root'].replace(src['map_name'], name)
    sroot = src['subroot'].replace(src['map_name'], name)
    frnames = lambda b: list(S.frags_of(b))
    b = rename_root(arch.read(map_ent), '.map', tb, src['root'], mroot, frnames)
    sb = rename_root(arch.read(sub_ent), '.submap', tb, src['subroot'], sroot, frnames)
    rep['steps'].append('root fragments renamed %s -> %s, %s -> %s' % (src['root'], mroot, src['subroot'], sroot))
    recs = Records(tb, b)
    fr = S.frags_of(b)
    root_name = [n for n in fr if n.split('/')[-1] == mroot][0]
    # --- 2. nodes of the root fragment
    ridx = [i for i, it in enumerate(recs.items) if it['name'] == root_name][0]
    d = fe.FragDoc(recs.items[ridx]['payload'], T, root_name)
    d.used_ids = set()
    folder_name = ng.get('folder_node', 'MESA_COMPOUND')
    tmpl_folder = d.find(TERRAIN_TEMPLATE_FOLDER)
    tmpl_model = d.find(TERRAIN_TEMPLATE_MODEL)
    new_folder, _ = d.clone(tmpl_folder, deep=False, parent=0, name=folder_name)
    # --- 4. textures and models
    info0 = bytes(b.info)
    st0 = tb.record_starts(info0, b.n)
    templates = TX.find_templates(info0, st0, len(st0))
    tex = make_textures(ng['textures'], templates, folder)
    models = make_models(ng['models'], folder, tex, mw, tm, rep)
    by_short = {mo['short']: mo for mo in models}
    # --- placements (Model nodes under the folder)
    placed = []
    sl = ng.get('statically_lit', False)
    for k, pl in enumerate(ng['placements']):
        if pl['model'] not in by_short:
            raise GeoError('placement %d: unknown model %r' % (k, pl['model']))
        node, _ = d.clone(tmpl_model, deep=False, parent=new_folder, name=pl.get('name'))
        d.set_prop(node, 'modelres', by_short[pl['model']]['full'][5:], note=False)
        d.set_prop(node, 'statically_lit', bool(sl), note=False)
        d.set_prop(node, 'dynamically_lit', True, note=False)
        d.move(node, pos=[float(x) for x in pl['pos']], orient=[0.0, 0.0, 0.0, 1.0], space='local')
        if 'lod_threshold' in pl:
            d.set_prop(node, 'lod_threshold', float(pl['lod_threshold']), note=False)
        placed.append(dict(name=pl.get('name'), model=pl['model'], pos=pl['pos'], node='0x%08X' % node))
    removed = 0
    if ng.get('drop_source_content', True):
        for fn in DROP_FOLDERS:
            n = d.find({'name': fn})
            removed += len(d.subtree(n))
            d.remove(n, deep=True)
        rep['steps'].append('removed %d nodes of the train level (%s)' % (removed, ', '.join(DROP_FOLDERS)))
    recs.items[ridx]['payload'] = d.payload()
    # --- 3. drop what nothing refers to (before the new records are appended: they are all referenced)
    dropped = []
    if ng.get('drop_unused_assets', True):
        dropped, rounds = drop_unused(recs, K, [root_name], rep)
        rep['steps'].append('dropped %d records (%d INFO bytes, %d payload bytes) in %d rounds'
                            % (len(dropped), sum(x[2] for x in dropped), sum(x[3] for x in dropped), rounds))
    # --- append the new records
    for t in tex.values():
        recs.items.append(dict(type=0, name=t['name'], rec=t['record'], payload=t['payload']))
    for mo in models:
        recs.items.append(dict(type=3, name=mo['full'], rec=mo['record'], payload=b''))
    recs.write_into(b)
    out_map = os.path.join(out_dir, 'base_' + os.path.basename(map_ent).replace('map10_runawaytrain', name.lower()))
    raw = b.serialize()
    open(out_map, 'wb').write(raw)
    out_sub = os.path.join(out_dir, 'base_' + os.path.basename(sub_ent).replace('map10_runawaytrain', name.lower()))
    open(out_sub, 'wb').write(sb.serialize())
    # --- checks
    checks = []
    r1 = ft.roundtrip_block(raw, '.map', T)
    checks.append(('map block: every fragment re-serialises exactly, block identical', not r1['fail'] and r1['block_identical']))
    chk = tb.Block(raw, '.map')
    st = tb.record_starts(bytes(chk.info), chk.n)
    checks.append(('record scan finds all %d records' % chk.n, len(st) == chk.n))
    if os.environ.get('TOD_HD_APP'):                # the author's TOD HD app folder (tod_hd_game.py, not included)
        sys.path.insert(0, os.environ['TOD_HD_APP'])
    try:
        import tod_hd_game as G
        gb = G.Block(raw, '.map')
        ntex = len(gb.textures())
        checks.append(('TOD HD strict reader: %d textures, every payload equals the engine size rule' % ntex, True))
    except Exception as e:                          # noqa: BLE001
        checks.append(('TOD HD strict reader: %s' % e, False))
    info = bytes(chk.info)
    en = st[1:] + [len(info)]
    nmod = 0
    for k, (R, E) in enumerate(zip(st, en)):
        if tb.u32(info, R) == 3:
            mm = tm.decode(info, R, E)
            if tm.encode(mm) != info[R:E]:
                checks.append(('model %s round-trips' % tb.record_name(info, R), False))
            nmod += 1
    checks.append(('%d models decode and re-encode identically' % nmod, True))
    checks.append(('max asset %d bytes <= 1,351,384 (largest shipped M)' % chk.max_asset, chk.max_asset <= TX.MAX_PAYLOAD))
    rep.update(map_file=out_map, submap_file=out_sub, root_fragment=root_name, folder_node=folder_name,
               folder_node_id='0x%08X' % new_folder, models=[{k: v for k, v in mo.items() if k not in ('record', 'hull_tris')} for mo in models],
               textures=[dict(name=t['name'], w=t['w'], h=t['h'], fmt=t['fmt'], payload=len(t['payload'])) for t in tex.values()],
               placements=placed, dropped=[dict(type=x[0], name=x[1], info=x[2], payload=x[3]) for x in dropped],
               checks=[dict(check=c, ok=ok) for c, ok in checks], map_bytes=len(raw), info_bytes=len(chk.info),
               max_asset=chk.max_asset, records=chk.n)
    if not all(ok for _, ok in checks):
        raise GeoError('new_geometry checks failed: %s' % [c for c, ok in checks if not ok])
    # texture previews next to the build
    try:
        from PIL import Image
        os.makedirs(os.path.join(out_dir, 'textures'), exist_ok=True)
        for k, t in tex.items():
            Image.fromarray(t['preview']).save(os.path.join(out_dir, 'textures', k + '.png'))
    except Exception:                               # noqa: BLE001
        pass
    world_tris = []                                   # all placed collision, world space (for the recipe's floor checks)
    for pl in ng['placements']:
        P0 = np.asarray(pl['pos'], dtype=float)
        for t in by_short[pl['model']]['hull_tris']:
            world_tris.append(tuple(np.asarray(v, dtype=float) + P0 for v in t))
    return dict(map_file=out_map, submap_file=out_sub, report=rep, root_fragment=root_name, folder_node=folder_name,
                collision_tris=world_tris)
