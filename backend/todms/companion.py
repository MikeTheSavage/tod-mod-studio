"""Companion tools in Mod Studio (shared core: backend/todct, vendored from the Unreal TODLevelEditor plugin).

  collision generator   a .glb / .gltf / .obj file placed in a map -> convex pieces with a TOD surface -> a collision
                        set of the current mod (built into a host model's HullList when the mod is built)
  asset replacements    read-only overview: every TOD model of the user's game with its maps and use counts, a TOD
                        thumbnail, and the Unreal replacement rows carried by the mod (or read from an Unreal project's
                        Config/TODBridge folder). Mod Studio does not render Unreal assets.
"""
import json
import os
import shutil

from . import paths


def _co():
    from todct import collision, decomp, meshio, surfaces, assets, todmod
    return collision, decomp, meshio, surfaces, assets, todmod


# ---------------------------------------------------------------------------------------------- collision
def catalog():
    CO, DE, MI, SU, AS, TM = _co()
    c = SU.catalog()
    c['methods'] = [dict(id='solid', text='Solid parts (closed meshes: walls with openings, steps, ruins)'),
                    dict(id='surface', text='Surface patches (open meshes, terrain; like the shipped exporter)'),
                    dict(id='hull', text='One convex hull (crates, rocks)')]
    c['defaults'] = DE.DEFAULTS
    return c


def mesh_preview(path, max_tris=60000):
    """The file's triangles in TOD axes (for placing it in the 3D view before generating)."""
    CO, DE, MI, SU, AS, TM = _co()
    V, F, parts = MI.read_mesh(path)
    V, F = MI.to_game_axes(V, F)
    step = max(1, len(F) // max_tris)
    return dict(path=path, name=os.path.basename(path), verts=V.round(4).tolist(), tris=F[::step], triangles=len(F),
                parts=parts, min=V.min(0).round(3).tolist(), max=V.max(0).round(3).tolist(),
                material=SU.guess_material(os.path.basename(path), *[p['name'] for p in parts]))


def generate(req, progress=None):
    """req: {path, label, map, pos, rot (true quat) | yaw, scale, method, material, surface, visual_only, host,
    concavity, max_pieces, resolution, angle_deg, thickness, id} -> collision set."""
    CO, DE, MI, SU, AS, TM = _co()
    import math
    log = []
    rot = req.get('rot')
    if rot is None:
        a = math.radians(float(req.get('yaw') or 0.0)) / 2
        rot = [0.0, math.sin(a), 0.0, math.cos(a)]
    scale = req.get('scale') or [1, 1, 1]
    if isinstance(scale, (int, float)):
        scale = [scale] * 3
    surf = '0x%08X' % SU.parse_word(req.get('surface') or 'solid')
    src = dict(editor='modstudio', file=os.path.basename(req['path']), pos=req.get('pos'), rot=rot, scale=scale)
    if req.get('visual_only'):
        pieces = []
    else:
        if progress:
            progress('reading the mesh')
        V, F, parts = MI.read_mesh(req['path'])
        V, F = MI.to_game_axes(V, F)
        kw = {k: req[k] for k in ('concavity', 'max_pieces', 'resolution', 'angle_deg', 'thickness') if req.get(k) is not None}
        if progress:
            progress('convex decomposition (%s)' % req.get('method', 'solid'))
        pieces = CO.pieces_from_mesh(V, F, req.get('pos') or [0, 0, 0], rot, scale, method=req.get('method') or 'solid',
                                     material=req.get('material') or 'Stone', surface=surf, log=log, **kw)
    s = dict(kind=CO.KIND, version=CO.VERSION, id=req.get('id') or CO.slug(req.get('label') or os.path.basename(req['path'])),
             label=req.get('label') or os.path.splitext(os.path.basename(req['path']))[0], map=req['map'],
             visual_only=bool(req.get('visual_only')), host=req.get('host') or 'auto', source=src,
             method=req.get('method') or 'solid', pieces=pieces)
    notes = CO.validate_set(s)
    return dict(set=s, log=log, notes=notes, stats=CO.set_stats(s))


def map_key_for(ws, map_id):
    """Mod Studio catalog map id (e.g. 'map09') -> the collision core's map key ('map09_jungle')."""
    CO = _co()[0]
    import fragtool as ft
    for n in ft.archive().names:
        if '/shared/' in n.lower() and n.lower().split('/')[-1].startswith('mainmap_' + map_id.lower() + '_'):
            return CO.map_key_of(n)
    return map_id


def check(ws, sets, progress=None):
    """Build the sets on the blocks the game loads now (TOD HD's when installed), verify, nothing written."""
    CO = _co()[0]
    import fragtool as ft
    names = ft.archive().names
    out = []
    for mk, ss in CO.group_by_map(sets).items():
        if progress:
            progress('building collision for %s' % mk)
        ctx = CO.MapContext(mk, CO.map_entries(names, mk), lambda e: ws.read_block(e)[0])
        _, r = CO.apply_sets(ctx, ss)
        for b in r['blocks']:
            for h in b['hosts']:
                h.pop('model_edit_verify', None)
        out.append(r)
    return dict(result='PASS', maps=out, layer=CO.layer(sets))


def existing_near(ws, map_id, centre, radius=40.0):
    CO = _co()[0]
    import fragtool as ft
    mk = map_key_for(ws, map_id)
    ctx = CO.MapContext(mk, CO.map_entries(ft.archive().names, mk), lambda e: ws.read_block(e)[0])
    return dict(items=CO.existing_layer(ctx, centre, radius))


# ---------------------------------------------------------------------------------------------- assets
def _cfg():
    AS = _co()[4]
    d = os.path.join(paths.cache_dir(), 'assets')
    os.makedirs(d, exist_ok=True)
    return AS.Config(d)


def census(ws, progress=None):
    AS = _co()[4]
    import fragtool as ft
    arch = ft.archive()
    doc = AS.census(lambda e: ws.read_block(e)[0], arch.names, progress)
    AS._save(_cfg().census_path, doc)
    return dict(models=len(doc['rows']), maps=doc['maps'], seconds=doc['seconds'])


def asset_rows(ws, q, mod=None):
    """Rows for the overview. The Unreal columns come from the mod's "assets" section and, when set, an Unreal
    project's Config/TODBridge folder (settings: ue_config)."""
    AS = _co()[4]
    cfg = _cfg()
    cen = cfg.census()
    if cen is None:
        return dict(ready=False, rows=[], maps=[])
    ue_dir = ws.settings.get('ue_config')
    if ue_dir and os.path.isdir(ue_dir):
        ucfg = AS.Config(ue_dir)
        rs = AS.rows(ucfg, census_doc=cen)
        source = ue_dir
    else:
        rs = AS.rows(cfg, census_doc=cen)
        source = None
    mrows = ((mod or {}).get('assets') or {}).get('rows') or {}
    for r in rs:
        m = mrows.get(r['key'])
        if m:
            r['ue_assigned'] = m.get('ue')
            r['marker'] = m.get('collision') or r.get('marker', '')
            r['from_mod'] = True
    total = len(rs)
    rs = AS.filter_rows(rs, q.get('map') or None, int(q.get('min') or 0), q.get('q') or '', q.get('only') or None)
    off, lim = int(q.get('offset') or 0), int(q.get('limit') or 200)
    ue_thumbs = os.path.join(ue_dir, 'thumbs_ue') if ue_dir else None
    for r in rs[off:off + lim]:
        r['thumb'] = '/cache/assets/thumbs/%s.png' % r['key'] if os.path.exists(
            os.path.join(cfg.folder, 'thumbs', r['key'] + '.png')) else None
        r['ue_thumb'] = None
        if ue_thumbs and r.get('ue_assigned'):
            src = os.path.join(ue_thumbs, r['key'] + '.png')
            if os.path.exists(src):                          # copied into the cache so the app can serve it
                dst = os.path.join(cfg.folder, 'ue_thumbs', r['key'] + '.png')
                if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                r['ue_thumb'] = '/cache/assets/ue_thumbs/%s.png' % r['key']
    return dict(ready=True, total=total, count=len(rs), rows=rs[off:off + lim], maps=cen['maps'], ue_config=source,
                mod_rows=len(mrows))


def thumbs(ws, keys, progress=None):
    AS = _co()[4]
    import fragtool as ft
    cfg = _cfg()
    cen = (cfg.census() or {}).get('rows', {})
    names = {n.split('/')[-1].lower(): n for n in ft.archive().names if '/shared/' in n.lower()}
    done = []
    for i, k in enumerate(keys):
        r = cen.get(k)
        if not r:
            continue
        if progress:
            progress('thumbnail %s' % r['name'], i, len(keys))
        out = os.path.join(cfg.folder, 'thumbs', k + '.png')
        try:
            AS.thumbnail(lambda e: ws.read_block(e)[0], names[r['blocks'][0].lower()], r['path'], out)
            done.append(k)
        except Exception:                               # noqa: BLE001  (a thumbnail is optional)
            pass
    return dict(done=done)
