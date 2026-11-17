"""The bake step of a new map with its own geometry: baked lighting for every placed generated model.

Runs after the geometry blocks are written (`newgeo.build`) and before the graft recipe uses them. For the map block it
  1. reads back every generated model record (positions, normals, indices as the engine will read them),
  2. bakes per-vertex colours for every placed instance (`bake.py`): the map's sun and ambient light, shadows against all placed triangles,
  3. replaces the block's lighting record by one that holds exactly these instances (`lightrec.py`) and turns `statically_lit` on for them,
  4. reads the block back: HD's strict record reader, then for every placed node the engine's own lookups (unique-id path -> instance key ->
     one entry per mesh with the colour count of the mesh).
Any step that fails leaves the block as it was written by the geometry builder (dynamic lighting) and says why in the report.
"""
import os
import time

import numpy as np

from . import bake, lightrec, raycast, paths
from .lightfit import hl


class BakeSkip(Exception):
    """A plain-words reason the map keeps dynamic lighting."""


def default_lighting():
    from .mapgen import look
    return look.presets()['train_dust']['look']          # the clone source's own look


def run(geo, m, K, T, progress=None, ext='.map', replace=True):
    """geo: the result of newgeo.build (map_file is rewritten in place on success). m: the map entry (bake settings, lighting).
    -> report dict(status 'baked' | 'skipped', reason, seconds, instances, vertices, triangles, quality, checks [...])."""
    paths.ensure_cpu_guard()
    opts = dict(m.get('bake') or {})
    rep = dict(status='skipped', reason='', quality=opts.get('quality') or bake.DEFAULT_QUALITY, instances=0, vertices=0, triangles=0,
               seconds=0.0, checks=[])
    if opts.get('enabled') is False:
        rep['reason'] = 'switched off'
        return rep
    t0 = time.time()
    try:
        _run(geo, m, K, T, rep, progress, ext, replace)
        rep['status'] = 'baked'
    except BakeSkip as e:
        rep['reason'] = str(e)
    except (bake.BakeError, lightrec.RecordError) as e:
        rep['reason'] = 'the lighting could not be baked (%s)' % e
    rep['seconds'] = round(time.time() - t0, 2)
    return rep


def _run(geo, m, K, T, rep, progress, ext='.map', replace=True):
    import sys
    hl()
    import tod_hd_game as G
    HL = lightrec.HL()
    tb, fe = K.tb, K.fe
    sys.path.insert(0, os.path.join(paths.BACKEND, 'vendor', 'newmap'))
    import newgeo
    q = rep['quality']
    if q not in bake.QUALITY:
        raise BakeSkip('unknown quality %r' % q)
    ng = (geo['report'].get('placements') or [])
    if not ng:
        raise BakeSkip('the map has no generated geometry')
    lighting = m.get('lighting') or default_lighting()
    lights = bake.look_lights(lighting)
    rep['sun'] = [round(float(x), 4) for x in lights['sun_dir']]
    with open(geo['map_file'], 'rb') as f:
        raw = f.read()
    b = tb.Block(raw, ext)
    recs = newgeo.Records(tb, b)
    lit_idx = [i for i, it in enumerate(recs.items) if it['type'] == lightrec.TYPE]
    if len(lit_idx) != 1:
        raise BakeSkip('the clone source carries %d lighting records, not one' % len(lit_idx))
    li = lit_idx[0]
    root_name = geo['root_fragment']
    ridx = [i for i, it in enumerate(recs.items) if it['name'] == root_name][0]
    doc = fe.FragDoc(recs.items[ridx]['payload'], T, root_name)
    models = bake.read_models(raw, ext)
    # ---- every placed instance
    items = []
    full_of = {mo['short']: mo['full'].lower() for mo in geo['report']['models']}
    for pl in ng:
        node = int(pl['node'], 16)
        mod = models.get(full_of.get(pl['model']))
        if mod is None:
            raise BakeSkip('the model %s was not found in the block' % pl['model'])
        piv = [p for p in mod['pivots'] if p]
        if len(piv) != 1 or mod['pivots'][0] == []:
            raise BakeSkip('the model %s has more than one part' % pl['model'])
        pos, quat = doc.world(node)
        uid = (doc.get(node, 'unique_id0'), doc.get(node, 'unique_id1'))
        if uid == (0, 0) or uid[0] is None:
            raise BakeSkip('a placed node has no unique id')
        items.append(dict(node=node, name=pl.get('name'), uid=(int(uid[0]), int(uid[1])), pos=pos, quat=quat, meshes=mod['pivots'][0]))
    if len({i['uid'] for i in items}) != len(items):
        raise BakeSkip('two placed nodes share a unique id')
    # ---- world geometry
    tri_chunks, P_all, N_all, spans = [], [], [], []
    start = 0
    for it in items:
        sp = []
        for j, me in enumerate(it['meshes']):
            P = bake.rotate(it['quat'], me['P']) + np.asarray(it['pos'], np.float64) if len(me['P']) else me['P']
            N = me['N'] if me['N'] is not None else bake.vertex_normals(me['P'], me['I'])
            N = bake.rotate(it['quat'], N) if len(N) else N
            if len(me['I']):
                tri_chunks.append(P[me['I'].reshape(-1, 3)])
            P_all.append(P)
            N_all.append(N)
            sp.append((start, start + len(P)))
            start += len(P)
        it['spans'] = sp
    P_all = np.concatenate(P_all) if P_all else np.zeros((0, 3))
    N_all = np.concatenate(N_all) if N_all else np.zeros((0, 3))
    tris = np.concatenate(tri_chunks) if tri_chunks else np.zeros((0, 3, 3))
    rep['vertices'], rep['triangles'], rep['instances'] = int(len(P_all)), int(len(tris)), len(items)
    rep['payload_bytes'] = int(4 * sum(max(4, e - s) for it in items for s, e in it['spans']))
    from . import limits
    cap = int(limits.value('P5'))
    if rep['payload_bytes'] > cap:
        raise BakeSkip('the baked colours would take %d bytes in the block (the most one asset may hold is %d)' % (rep['payload_bytes'], cap))
    tree = raycast.Tree(tris)
    col, stats = bake.bake_vertices(P_all, N_all, lights, tree, q, progress)
    rep.update(stats)
    lv = (m.get('bake') or {}).get('level')
    if lv is not False:                                          # match the level of the shipped maps (bake.calibrate_level); {"level": false} keeps the plain bake
        lv = lv if isinstance(lv, dict) else {}
        col, rep['level'] = bake.calibrate_level(col, float(lv.get('mean', bake.LEVEL_TARGET_MEAN)), float(lv.get('floor', bake.LEVEL_FLOOR)))
    d3d = bake.to_d3dcolor(col)
    rep['mean_luminance'] = round(float((bake.from_d3dcolor(d3d) @ np.array([0.299, 0.587, 0.114])).mean()), 4) if len(d3d) else 0.0
    # ---- the record
    name = recs.items[li]['name']
    desc = []
    for it in items:
        desc.append(dict(path=(it['uid'],), meshes=[
            dict(pivot=0, mesh=j, colours=d3d[s:e], indices=me['RI']) for j, ((s, e), me) in enumerate(zip(it['spans'], it['meshes']))]))
    if not replace:                                             # an extension section keeps the host's baked drawing: its instances join ours
        old_recs, blk = lightrec.read(raw, ext, name)
        if len(old_recs) != 1:
            raise BakeSkip('the lighting record of the section is not readable')
        held = lightrec.describe(old_recs[0], blk)
        if sum(len(i['meshes']) for i in held) != len(old_recs[0].keys):
            raise BakeSkip('the host lighting has entries that cannot be carried over')
        ours = {i['path'] for i in desc}
        held = [i for i in held if i['path'] not in ours]
        rep['carried_instances'] = len(held)
        desc = held + desc
        rep['payload_bytes'] += int(sum(4 * max(4, len(me['colours'])) for i in held for me in i['meshes'] if me.get('single') is None))
        if rep['payload_bytes'] > cap:
            raise BakeSkip('the baked colours of the host and the new geometry would take %d bytes (the most one asset may hold is %d)' % (rep['payload_bytes'], cap))
    info, payload, summ = lightrec.build(name, desc)
    rep['record'] = summ
    recs.items[li] = dict(recs.items[li], rec=info, payload=payload)
    for it in items:
        doc.set_prop(it['node'], 'statically_lit', True, note=False)
    recs.items[ridx]['payload'] = doc.payload()
    recs.write_into(b)
    out = b.serialize()
    rep['record_name'] = name
    rep['nodes'] = [dict(name=it['name'], uid=list(it['uid']), counts=[(len(me['P']), len(me['RI'])) for me in it['meshes']],
                         flags=[me['flags'] for me in it['meshes']]) for it in items]
    rep['ext'] = ext
    rep['checks'] = [verify(out, ext, name, rep['nodes'])]
    with open(geo['map_file'], 'wb') as f:
        f.write(out)
    rep['bytes'] = len(out)
    chk = tb.Block(out, ext)                                   # the geometry report's numbers now describe the baked block
    geo['report'].update(map_bytes=len(out), info_bytes=len(chk.info), max_asset=chk.max_asset)
    rep['max_asset'] = chk.max_asset


def verify(raw, ext, name, nodes):
    """Read the block back: HD's strict record reader, then the engine's own lookups for every placed node.
    nodes: [dict(name, uid, counts [(vertices, indices)], flags [u32])] of pivot 0. Raises RecordError. -> a sentence."""
    HL = lightrec.HL()
    recs, blk = lightrec.read(raw, ext, name)
    if len(recs) != 1:
        raise lightrec.RecordError('the lighting record is not in the block')
    rec = recs[0]
    d = HL._record_dict(rec, blk)
    bad = []
    for nd in nodes:
        ik = HL.instance_key(d, (tuple(nd['uid']),))
        if ik < 0:
            bad.append('%s: the engine does not find its instance' % nd['name'])
            continue
        r = HL.simulate_binding(d, ik, [[tuple(c) for c in nd['counts']]], False, [list(nd['flags'])])
        got = {(p, j): e for p, j, e in r['lookups']}
        for j, (vc, ic) in enumerate(nd['counts']):
            e = got.get((0, j), -1)
            buf = d['entries'][e]['buffer'] if e >= 0 else None
            if e < 0 or buf is None or buf['count'] != vc or buf['index_count'] != ic:
                bad.append('%s mesh %d' % (nd['name'], j))
    if bad:
        raise lightrec.RecordError('%d meshes of placed nodes do not find their colours (%s)' % (len(bad), bad[0]))
    return '%d instances, %d meshes found by the engine lookup, counts equal the meshes' % (len(nodes), sum(len(n['counts']) for n in nodes))


def verify_final(raw, ext, bk):
    return verify(raw, ext, bk['record_name'], bk['nodes'])
