"""mapgen: the ground, roads and look generators of the new-map builder (pure Python + numpy: no UI, no game).

  from todms import mapgen
  params2 = mapgen.expand(params)              high-level keys -> the builder's primitives
  res = mapgen.expand_full(params)             the same plus {'stats': ..., 'notes': [...]}

Each map of a new-map recipe may carry these high-level keys (one module each, the module header documents the fields):
  terrain, ground_paint, roads, edges, water, scatter, look, backdrop, blockout
`expand` returns a COPY of the recipe in which every map that has such keys has them replaced by:
  new_geometry   textures, models (generated chunks, roads, walls, water planes, trees and rocks) and placements, merged into any
                 new_geometry the map already has (the builder's own `new_geometry` shape)
  walls          invisible-wall boxes of `edges` (appended)
  teleports      spots made for kill planes and water resets (appended)
  triggers       box triggers that teleport the player to a spot of the same map or end a mission (the builder writes them)
  lighting       the explicit sun, ambient, fog, sky and screen values (the builder writes them into the block's light nodes, copying the sky)
  traffic_routes seed traffic routes (the builder writes them as road folders with linked traffic points)
  shipped_models placements of shipped models from `scatter` (the builder copies each model and its pictures into the new map block)
  mapgen         {stats, notes} of the map
The project keeps the high-level keys (the editor replays strokes from them); only the copy handed to the builder is expanded.
The result is deterministic: the same input gives byte-identical output.
"""
import copy
import json

from . import core, texkinds, terrain, paint, ground, roads as roads_mod, edges as edges_mod, water as water_mod, scatter as scatter_mod, look
from . import geoplug, blockout as blockout_mod, backdrop as backdrop_mod
from .core import np, Out, MapgenError

HIGH_KEYS = ('terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'look', 'backdrop', 'blockout', 'scene')
__all__ = ['expand', 'expand_full', 'install_builder_plug', 'MapgenError', 'HIGH_KEYS', 'has_mapgen', 'terrain', 'paint', 'look']


def install_builder_plug():
    """Make the map builder's geometry step accept the generated parts (idempotent). expand() calls it."""
    texkinds.register()
    from .. import sceneimport
    sceneimport.install_kinds()                          # the `scene:<sha>` picture kind of an imported large scene
    return geoplug.install()


def has_mapgen(params):
    return any(k in m for m in (params or {}).get('maps', []) for k in HIGH_KEYS)


# texture names the generators share
def _tex_for(out):
    def tex_for(kind, n):
        if kind == 'road':
            return out.texture('R_Road%dL' % max(1, min(4, n)), texkinds.road_kind(n), 256, 'DXT1', 7)
        if kind == 'kerb':
            return out.texture('R_Kerb', 'concrete', 128, 'DXT1', 8)
        if kind == 'concrete':
            return out.texture('R_Concrete', 'concrete', 128, 'DXT1', 9)
        if kind == 'cliff':
            return out.texture('E_Cliff', 'cliff', 256, 'DXT1', 11)
        if kind == 'water':
            return out.texture('W_Water', 'water', 128, 'RGBA32', 12)
        if kind == 'sea':
            return out.texture('W_Sea', 'sea', 128, 'RGBA32', 15)
        raise MapgenError('unknown generator texture %s' % kind)
    return tex_for


def _kit_tex(out):
    def kit():
        return dict(bark=out.texture('S_Bark', 'wood', 128, 'DXT1', 13), leaf=out.texture('S_Leaf', 'foliage', 128, 'DXT1', 14),
                    rock=out.texture('S_Rock', 'cliff', 128, 'DXT1', 15))
    return kit


def _payload_bytes(size, fmt):
    pix = size * size
    return int((pix * (0.5 if fmt == 'DXT1' else 4.0)) * 4.0 / 3.0)


def _expand_map(m, assets=None):
    name = m.get('name') or 'map'
    out = Out(name)
    texkinds.register()
    tex_for = _tex_for(out)
    # --- the height grid, then everything that changes it
    H = terrain.build(m.get('terrain'), out)
    has_ground = bool(m.get('terrain'))
    if not has_ground and (m.get('scene') or {}).get('ground_y') is not None:
        H.flat = float(m['scene']['ground_y'])         # an imported scene: edges and spots sit at the street level
    if (m.get('ground_paint') or m.get('roads') or m.get('water') or m.get('edges') or m.get('scatter')) and not has_ground:
        out.note('This map has no terrain, so roads, water, edges and scatter sit on a flat plane at y %.1f.' % H.flat)
    waters = [water_mod.carve(w, k, H, out) for k, w in enumerate(m.get('water') or [])]
    built_roads = []
    for k, r in enumerate(m.get('roads') or []):
        built_roads.append(roads_mod.build_road(r, k, H, out, tex_for))
    # --- the ground
    extras = []
    chunks = []
    pal = []
    if has_ground:
        pal, tex_idx, surf = paint.build(H, m.get('ground_paint'), out, assets)
        asph = core.mat_index('Asphalt')
        for br in built_roads:
            if br['mask'] is not None:
                surf = np.where(br['mask'], asph, surf)
    elif m.get('ground_paint'):
        out.note('Ground paint needs a terrain: it was ignored.')
        pal = []
    for k, e in enumerate(m.get('edges') or []):
        edges_mod.build(e, k, H, out, tex_for)
    for w in waters:
        water_mod.build(w, H, out, tex_for)
    lines = [(b['centre'], b['half']) for b in built_roads if not b['info']['elevated']]
    sc_stats = []
    for k, s in enumerate(m.get('scatter') or []):
        sc_stats.append(scatter_mod.place(s, k, H, out, lines, waters, _kit_tex(out), extras))
    bo_stats = blockout_mod.build(m, out) if m.get('blockout') else None
    bd_stats = backdrop_mod.build(m, out) if m.get('backdrop') else None
    if has_ground:
        t = m['terrain']
        chunks = ground.build_chunks(H, tex_idx, surf, pal, float(t.get('uv', 0.125)), float(t.get('thickness', 1.5)),
                                     int(t.get('chunk', 24)), extras, out)
    # --- merge into the map
    mm = copy.deepcopy(m)
    for k in HIGH_KEYS:
        mm.pop(k, None)
    ng = mm.get('new_geometry')
    if ng is None:
        ng = dict(folder=name, drop_source_content=True, drop_unused_assets=True, statically_lit=False, textures=[], models=[], placements=[])
    for key in ('textures', 'models', 'placements'):
        ng.setdefault(key, [])
    have = {t['name'] for t in ng['textures']}
    ng['textures'] += [t for t in out.textures.values() if t['name'] not in have]
    clash = {x['name'] for x in ng['models']} & out.model_names
    if clash:
        raise MapgenError('generated model names clash with the map\'s own: %s' % ', '.join(sorted(clash)))
    ng['models'] += out.models
    ng['placements'] += out.placements
    mm['new_geometry'] = ng
    if out.walls:
        mm['walls'] = list(mm.get('walls') or []) + out.walls
    if out.teleports:
        names = {t['name'] for t in mm.get('teleports') or []}
        mm['teleports'] = list(mm.get('teleports') or []) + [t for t in out.teleports if t['name'] not in names]
    if out.triggers:
        mm['triggers'] = list(mm.get('triggers') or []) + out.triggers
    if out.traffic:
        mm['traffic_routes'] = out.traffic
    if out.shipped_models:
        mm['shipped_models'] = out.shipped_models
    lighting = None
    if m.get('look'):
        lighting = look.resolve(m['look'])
        for n in lighting.pop('notes'):
            out.note(n)
        mm['lighting'] = lighting
    # --- numbers
    tris = sum(c['triangles'] for c in chunks) + sum(b['info']['triangles'] for b in built_roads)
    for md in out.models:
        pass
    allparts = [(md['name'], p) for md in ng['models'] for p in md.get('parts', []) if p.get('type') == 'mapgen']
    from .meshkit import read_part
    verts = tris_all = hulls_n = max_sub = max_hv = 0
    for _, p in allparts:
        meshes, hs = read_part(p)
        for me in meshes:
            verts += len(me['P'])
            tris_all += len(me['I'])
            max_sub = max(max_sub, len(me['P']))
        hulls_n += len(hs)
        max_hv = max([max_hv] + [len(h[0]) for h in hs])
    tex_list = [dict(name=t['name'], kind=t['kind'], size=t['size'], format=t['format'], payload=_payload_bytes(t['size'], t['format']))
                for t in ng['textures']]
    steep = 0.0
    if has_ground:
        h = H.h
        sx = np.maximum(np.abs(h[:-1, 1:] - h[:-1, :-1]), np.abs(h[1:, 1:] - h[1:, :-1])) / H.cell
        sz = np.maximum(np.abs(h[1:, :-1] - h[:-1, :-1]), np.abs(h[1:, 1:] - h[:-1, 1:])) / H.cell
        steep = float((np.maximum(sx, sz) > roads_mod.SLOPE_WALK).mean() * 100.0)
    if assets:                                           # where each shipped model lives, so the builder can copy it
        for sm in out.shipped_models:
            blocks = ((assets.get('models') or {}).get(sm['model'].lower().replace(chr(92), '/')) or {}).get('blocks') or []
            if not blocks:
                blocks = ((assets.get('models') or {}).get('/data' + sm['model'].lower()) or {}).get('blocks') or []
            if blocks:
                sm['blocks'] = list(blocks[:3])
    instances = len(ng['placements']) + len(out.shipped_models)
    scene = m.get('scene') or {}
    stats = dict(map=name, triangles=tris_all, ground_triangles=max([sum(c['triangles'] for c in chunks), int(scene.get('section_tris_max') or 0)]), vertices=verts,
                 textures=len(tex_list), texture_list=tex_list, collision_pieces=hulls_n, models=len(ng['models']), instances=instances,
                 generated_instances=len(ng['placements']), shipped_instances=len(out.shipped_models),
                 nodes_added=len(ng['placements']) + len(out.shipped_models) + len(out.walls) + len(out.triggers) + len(out.teleports),
                 max_submesh_vertices=max_sub, max_hull_vertices=max_hv, max_hull_indices=max(0, (2 * max_hv - 4) * 3),
                 largest_texture=max([t['payload'] for t in tex_list] + [0]), ground_materials=len(pal) if has_ground else 0,
                 steep_percent=round(steep, 2), chunks=chunks, roads=[b['info'] for b in built_roads], water=out.stats['water'],
                 edges=out.stats['edges'], scatter=sc_stats, **(dict(blockout=bo_stats) if bo_stats else {}), **(dict(backdrop=bd_stats) if bd_stats else {}),
                 terrain=dict(cell=H.cell, nx=H.nx, nz=H.nz, origin=[H.ox, H.oz], min=round(float(H.h.min()), 3), max=round(float(H.h.max()), 3))
                 if has_ground else None)
    from .. import limits
    if has_ground and stats['ground_triangles'] > limits.value('G2'):
        out.note('The ground has %d triangles; more than %d draws slowly (there is no level of detail).' % (stats['ground_triangles'], limits.value('G2')))
    if steep > 25.0:
        out.note('%.0f%% of the ground is steeper than %d%%: the player cannot walk up it.' % (steep, roads_mod.SLOPE_WALK * 100))
    if max_sub > 60000 or max_hv > 255:
        out.note('A generated mesh passes a limit (more than 60,000 vertices in one sub-mesh or a collision piece over 255 vertices).')
    for n in (scene.get('notes') or []):
        out.note(n)
    mm['mapgen'] = dict(stats=stats, notes=list(out.notes))
    if (scene.get('plan') or {}).get('steps') is not None:
        mm['mapgen']['scene_steps'] = scene['plan']['steps']          # for the build check (the scene key itself is not handed on)
    pl = scene.get('plan') or {}
    if pl.get('x0') is not None and pl.get('w') and pl.get('h'):
        mm['mapgen']['scene_area'] = [pl['x0'], pl['z1'] - pl['h'] * pl['cell'], pl['x0'] + pl['w'] * pl['cell'], pl['z1']]     # where the district stands in the world
    return mm, stats, list(out.notes)


def expand_full(params, assets=None):
    """-> dict(params=expanded copy, stats={map name: numbers}, notes=[sentences]).
    assets: the asset index (todms.assetindex.load) when known: palette materials then name their closest shipped picture."""
    install_builder_plug()
    res = copy.deepcopy(params)
    stats, notes = {}, []
    many = len(res.get('maps', [])) > 1
    for i, m in enumerate(res.get('maps', [])):
        if not any(k in m for k in HIGH_KEYS):
            continue
        mm, st, nt = _expand_map(m, assets)
        res['maps'][i] = mm
        stats[mm.get('name') or 'map%d' % (i + 1)] = st
        notes += [('%s: %s' % (mm.get('name'), n)) if many else n for n in nt]
    return dict(params=res, stats=stats, notes=notes)


def expand(params, assets=None):
    """The recipe with its high-level keys rewritten into the builder's primitives (see the module header)."""
    return expand_full(params, assets)['params']


def dumps(params):
    """Canonical JSON text of an expanded recipe (what the determinism tests compare)."""
    return json.dumps(params, sort_keys=True, separators=(',', ':'), allow_nan=False)
