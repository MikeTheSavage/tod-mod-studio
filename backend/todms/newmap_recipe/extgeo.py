"""new_geometry inside an EXTENSION section (wave 3, showcase worker).

A separate map builds its own ground through newgeo.build (a clone of Map10 with the train level taken out). An extension section is a copy
of a host section instead, so this module takes the section's base block (the host's copy with the root renamed, cut down by `carry`) and
adds to it:
  1. the texture and model records of `new_geometry` (newgeo.make_textures / make_models: the same writers, so a model is the same bytes),
  2. one Folder under the section's root fragment and one Model node per placement, cloned from the shipped Map10 terrain nodes that newgeo
     uses (so every engine property keeps a shipped value; `statically_lit` off until the bake turns it on),
  3. the world-space collision triangles of the placed models (for the floor checks).
Nothing is taken out of the host copy here: what stays of the host is the business of `carry`.
"""
import numpy as np


class ExtGeoError(Exception):
    pass


def _template(K, NG, src, T):
    """The shipped Map10 terrain Folder and Model node (a FragDoc of its root fragment) and its texture record templates."""
    ft, fe, tb, S = K.ft, K.fe, K.tb, K.S
    raw = ft.archive().read(ft.resolve_entry(src['map_entry']))
    b = tb.Block(raw, '.map')
    fr = S.frags_of(b)
    name = [n for n in fr if n.split('/')[-1] == src['root']][0]
    doc = fe.FragDoc(b.payloads[fr[name]], T, name)
    info = bytes(b.info)
    st = tb.record_starts(info, b.n)
    templates = NG.TX.find_templates(info, st, len(st))
    return doc, doc.find(NG.TERRAIN_TEMPLATE_FOLDER), doc.find(NG.TERRAIN_TEMPLATE_MODEL), templates


def add_geometry(raw, ext, root_name, ng, src, K, T, NG):
    """raw: the section's base block. ng: the new_geometry dict (folder, textures, models, placements, statically_lit). src: the clone source
    entry (SOURCES) that owns the template nodes. -> (new raw, report dict like newgeo.build's, world collision triangles)."""
    ft, fe, tb, tm, mw, S = K.ft, K.fe, K.tb, K.tm, K.mw, K.S
    rep = dict(steps=[])
    folder = ng.get('folder') or 'SceneExt'
    b = tb.Block(raw, ext)
    recs = NG.Records(tb, b)
    ridx = [i for i, it in enumerate(recs.items) if it['name'] == root_name]
    if len(ridx) != 1:
        raise ExtGeoError('the root fragment %s is not in the section block' % root_name)
    ridx = ridx[0]
    sdoc, tmpl_folder, tmpl_model, templates = _template(K, NG, src, T)
    tex = NG.make_textures(ng['textures'], templates, folder)
    models = NG.make_models(ng['models'], folder, tex, mw, tm, rep)
    by_short = {mo['short']: mo for mo in models}
    have = {it['name'].lower() for it in recs.items}
    clash = [n for n in [t['name'] for t in tex.values()] + [mo['full'] for mo in models] if n.lower() in have]
    if clash:
        raise ExtGeoError('the host section already holds %s: give the geometry another folder name' % clash[0])
    # every node id of the block (a graft must not reuse one)
    used = set()
    for it in recs.items:
        if it['type'] == 4 and len(it['payload']) >= 24:
            try:
                used |= set(fe.FragDoc(it['payload'], T, it['name']).created_ids())
            except Exception:                                   # noqa: BLE001
                pass
    d = fe.FragDoc(recs.items[ridx]['payload'], T, root_name)
    S.BLOCK_BITS_FOR_DOC[id(d)] = S.BLOCK_BITS[ext]
    fmap = S.graft(d, sdoc, tmpl_folder, False, 0, T, used, 1)
    new_folder = fmap[tmpl_folder]
    folder_name = ng.get('folder_node', 'SCENE_EXT')
    d.set_prop(new_folder, fe.P_NAME, folder_name, note=False)
    d.move(new_folder, pos=[0.0, 0.0, 0.0], orient=[0.0, 0.0, 0.0, 1.0], space='local')
    sl = bool(ng.get('statically_lit', False))
    placed = []
    for k, pl in enumerate(ng['placements']):
        if pl['model'] not in by_short:
            raise ExtGeoError('placement %d: unknown model %r' % (k, pl['model']))
        m = S.graft(d, sdoc, tmpl_model, False, new_folder, T, used, 2 + k)
        node = m[tmpl_model]
        d.set_prop(node, fe.P_NAME, pl.get('name') or 'EXTGEO_%d' % k, note=False)
        d.set_prop(node, 'modelres', by_short[pl['model']]['full'][5:], note=False)
        d.set_prop(node, 'statically_lit', sl, note=False)
        d.set_prop(node, 'dynamically_lit', True, note=False)
        d.move(node, pos=[float(x) for x in pl['pos']], orient=[0.0, 0.0, 0.0, 1.0], space='local')
        if 'lod_threshold' in pl:
            d.set_prop(node, 'lod_threshold', float(pl['lod_threshold']), note=False)
        placed.append(dict(name=pl.get('name'), model=pl['model'], pos=pl['pos'], node='0x%08X' % node))
    recs.items[ridx]['payload'] = d.payload()
    for t in tex.values():
        recs.items.append(dict(type=0, name=t['name'], rec=t['record'], payload=t['payload']))
    for mo in models:
        recs.items.append(dict(type=3, name=mo['full'], rec=mo['record'], payload=b''))
    recs.write_into(b)
    out = b.serialize()
    r1 = ft.roundtrip_block(out, ext, T)
    checks = [('section block: every fragment re-serialises exactly, block identical', not r1['fail'] and r1['block_identical'])]
    chk = tb.Block(out, ext)
    st = tb.record_starts(bytes(chk.info), chk.n)
    checks.append(('record scan finds all %d records' % chk.n, len(st) == chk.n))
    checks.append(('max asset %d bytes <= 1,351,384 (largest shipped M)' % chk.max_asset, chk.max_asset <= NG.TX.MAX_PAYLOAD))
    info = bytes(chk.info)
    en = st[1:] + [len(info)]
    bad = 0
    for R, E in zip(st, en):
        if tb.u32(info, R) == 3 and tb.record_name(info, R) in {mo['full'] for mo in models}:
            mm = tm.decode(info, R, E)
            bad += tm.encode(mm) != info[R:E]
    checks.append(('%d new models decode and re-encode identically' % len(models), bad == 0))
    world = []
    for pl in ng['placements']:
        P0 = np.asarray(pl['pos'], dtype=float)
        for t in by_short[pl['model']]['hull_tris']:
            world.append(tuple(np.asarray(v, dtype=float) + P0 for v in t))
    rep.update(map_file=None, root_fragment=root_name, folder_node=folder_name, folder_node_id='0x%08X' % new_folder,
               models=[{k: v for k, v in mo.items() if k not in ('record', 'hull_tris')} for mo in models],
               textures=[dict(name=t['name'], w=t['w'], h=t['h'], fmt=t['fmt'], payload=len(t['payload'])) for t in tex.values()],
               placements=placed, checks=[dict(check=c, ok=bool(ok)) for c, ok in checks], map_bytes=len(out), info_bytes=len(chk.info),
               max_asset=chk.max_asset, records=chk.n)
    if not all(ok for _, ok in checks):
        raise ExtGeoError('new_geometry checks failed: %s' % [c for c, ok in checks if not ok])
    return out, rep, world
