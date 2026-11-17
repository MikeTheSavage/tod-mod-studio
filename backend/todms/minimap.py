"""Minimap of a new map: a top-down picture in the game's radar style, written as the tile pack the Gameplay+ minimap reads.

The vanilla radar has no map picture: in a new map it shows an empty disc (the radar's location index has no entry for a new section; measured).
Gameplay+ draws a picture inside that disc from a baked tile pack and picks the pack by the player's POSITION. This module makes such a pack
for a Mod Studio map from the generator data (height grid, ground paint, roads, water, edges, scatter, walls), without the game and
without Gameplay+'s baker, and writes it into Mod Studio's OWN folder (never into Gameplay+'s):

  build(m, out_dir, name)         -> dict(files, line, bounds, ...)   <name>.mmp, <name>.occ and the minimap.txt line of the map
  calibrate(out_dir, info, layers)-> checks: a known world position lands on the pixel the DLL computes, and shows the right ink
  overlaps(bounds, others)        -> names of maps whose pack area covers the same positions (the DLL cannot tell them apart)
  merge_lines(lines, text)        -> minimap.txt text with these lines added (a name already listed is replaced)

Pack format (hud/bake/minimap_bake.cpp of Gameplay+): "MMP1", u32 version 1, f32 x0, f32 z1 (top left), f32 texel metres of level 0 (0.25),
u32 tile px 512, u32 border px 4, u32 levels 2; per level u32 cols, rows, table offset; each table = cols * rows of (u32 offset, u32 size),
0 = empty tile. A tile is one 8-bit palette PNG (one IDAT, filter 0, a tRNS alpha table) of 512 px; the outer 4 px repeat the neighbours.
Tile (col, row) of level L covers 504 * 0.25 * 2^L metres; column = (x - x0) / s, row = (z1 - z) / s. Plain ground stays transparent so the
radar's parchment shows; ink is straight alpha. The inks and line widths are the baker's own.
"""
import math
import os
import struct
import zlib

import numpy as np

from . import scenplan
from .mapgen import core, terrain, paint, texkinds
from .mapgen import roads as roads_mod, water as water_mod, scatter as scatter_mod
from .mapgen.core import in_polygon

TEXEL0 = 0.25
TILE_PX = 512
BORDER_PX = 4
INNER = TILE_PX - 2 * BORDER_PX
LEVELS = 2
CELL_OCC = 16.0
MARGIN = 24.0
MAX_AREA = 4_000_000.0          # square metres a pack may cover (a larger map is refused with a plain reason)

INK = dict(road=(122, 88, 48), kerb=(72, 46, 22), grass=(92, 104, 40), dirt=(134, 98, 54), water=(46, 92, 120), wline=(30, 66, 92),
           rock=(112, 84, 58), wall=(44, 27, 12), tree=(74, 92, 38), treel=(38, 50, 20), bush=(96, 112, 48), cont=(120, 84, 46),
           out=(34, 20, 9))
# metres of line width per level (the baker's STYLES)
STYLE = [dict(kerb=0.20, wall=0.30, tree_line=0.20, contour=0.11, outline=0.42), dict(kerb=0.32, wall=0.46, tree_line=0.32, contour=0.18, outline=0.66)]
CONTOUR_STEP = 4.0
GROUND_INK = dict(grass=('grass', 0.30), dirt=('dirt', 0.34), sand=('dirt', 0.26), rock=('rock', 0.55), asphalt=('road', 0.5))


class MinimapError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ the layers
class Layers:
    """What the picture is made of, from the map's own generator keys (high-level recipe keys, not the expanded recipe)."""

    def __init__(self, m, assets=None):
        self.name = m.get('name') or 'map'
        out = core.Out(self.name)
        texkinds.register()
        from . import mapgen as MG
        tex_for = MG._tex_for(out)
        self.H = H = terrain.build(m.get('terrain'), out)
        self.has_ground = bool(m.get('terrain'))
        # a scene map: its plan (streets, buildings, water seen from above) stands in for terrain, roads and ponds
        self.plan = m.get('_plan')
        self.sdf = {}
        if self.plan is not None:
            g, c = self.plan['grid'], self.plan['cell']
            self.sdf = dict(road=scenplan.sdf(g, scenplan.ROAD, c), building=scenplan.sdf(g, scenplan.BUILDING, c), water=scenplan.sdf(g, scenplan.WATER, c),
                            open=scenplan.sdf(g, (scenplan.GROUND, scenplan.ROAD), c))
        self.waters = [] if self.plan is not None else [water_mod.carve(w, k, H, out) for k, w in enumerate(m.get('water') or [])]
        self.roads = []
        for k, r in enumerate(m.get('roads') or []):
            b = roads_mod.build_road(r, k, H, out, tex_for)
            self.roads.append(dict(id=b['info']['id'], centre=np.asarray(b['centre'], dtype=float), half=float(b['half']),
                                   elevated=bool(b['info']['elevated'])))
        self.palette, self.cells = [], None
        if self.has_ground:
            pal, tex_idx, _ = paint.build(H, m.get('ground_paint'), out, assets)
            self.palette = [p['id'] for p in pal]
            self.cells = tex_idx
        self.edges = []
        for e in m.get('edges') or []:
            try:
                self.edges.append(core.polygon_of(e, 'edge %s' % e.get('id')))
            except core.MapgenError:
                pass
        self.walls = [dict(pos=w['pos'], size=w['size'], orient=w.get('orient') or [0, 0, 0, 1]) for w in (m.get('walls') or [])]
        # trees, rocks and bushes: the scatter areas as the generators place them
        self.trees = []
        lines = [(r['centre'], r['half']) for r in self.roads if not r['elevated']]
        for k, s in enumerate(m.get('scatter') or []):
            before = len(out.placements)
            scatter_mod.place(s, k, H, out, lines, self.waters, MG._kit_tex(out), [])
            for pl in out.placements[before:]:
                kind = 'tree' if '_tree_' in pl['model'] else ('rock' if '_rock_' in pl['model'] else 'bush')
                self.trees.append((pl['pos'][0], pl['pos'][2], kind))
            for sm in out.shipped_models:
                self.trees.append((sm['pos'][0], sm['pos'][2], 'rock'))
            out.shipped_models.clear()
        if self.plan is not None:
            b = scenplan.bounds(self.plan)
            if b is None:
                raise MinimapError('this map has nothing to draw: its plan is empty')
            x0, z0, x1, z1 = b
        elif self.has_ground:
            x0, z0 = H.ox, H.oz
            x1, z1 = H.ox + H.nx * H.cell, H.oz + H.nz * H.cell
        else:
            xs = [p[0] for r in self.roads for p in r['centre']] + [w['pos'][0] for w in self.walls] + [t[0] for t in self.trees]
            zs = [p[1] for r in self.roads for p in r['centre']] + [w['pos'][2] for w in self.walls] + [t[1] for t in self.trees]
            if not xs:
                raise MinimapError('this map has nothing to draw: add a terrain, a road or a wall')
            x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
        self.extent = [x0 - MARGIN, z0 - MARGIN, x1 + MARGIN, z1 + MARGIN]
        if (self.extent[2] - self.extent[0]) * (self.extent[3] - self.extent[1]) > MAX_AREA:
            raise MinimapError('the map is larger than a minimap pack can cover (%d square metres); draw a smaller area' % MAX_AREA)


# ------------------------------------------------------------------------------------------------ drawing
def _over(acc, mask_alpha, ink):
    """acc: (n, n, 4) float premultiplied; draw `ink` with per-pixel alpha."""
    a = np.clip(mask_alpha, 0.0, 1.0)[..., None]
    c = np.array(ink, dtype=np.float32)[None, None, :]
    acc[..., :3] = acc[..., :3] * (1.0 - a) + c * a
    acc[..., 3:4] = acc[..., 3:4] * (1.0 - a) + a


def _edge(d, w, s):
    """Anti-aliased band: 1 inside distance w, falling over one pixel (s metres)."""
    return np.clip((w - d) / s + 0.5, 0.0, 1.0)


def _seg_distance(X, Z, a, b):
    abx, abz = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + abz * abz
    if l2 < 1e-12:
        return np.hypot(X - a[0], Z - a[1])
    t = np.clip(((X - a[0]) * abx + (Z - a[1]) * abz) / l2, 0.0, 1.0)
    return np.hypot(X - (a[0] + t * abx), Z - (a[1] + t * abz))


def _poly_edge_distance(X, Z, poly, box):
    d = np.full(X.shape, 1e9, dtype=np.float32)
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if max(a[0], b[0]) < box[0] or min(a[0], b[0]) > box[2] or max(a[1], b[1]) < box[1] or min(a[1], b[1]) > box[3]:
            continue
        d = np.minimum(d, _seg_distance(X, Z, a, b))
    return d


def _draw_plan(acc, L, X, Z, s, st, level_index):
    """The plan of a scene in the baker's inks: open ground as a light wash, roads brown with kerb lines, buildings as hatched blocks with an
    ink outline, water blue with its shore line. Every edge comes from a distance field, so it is finer than a plan cell."""
    P, F = L.plan, L.sdf
    inside = lambda d: np.clip((-d) / s + 0.5, 0.0, 1.0)            # noqa: E731
    d_open = scenplan.bilinear(F['open'], P, X, Z)
    d_road = scenplan.bilinear(F['road'], P, X, Z)
    d_bld = scenplan.bilinear(F['building'], P, X, Z)
    d_wat = scenplan.bilinear(F['water'], P, X, Z)
    if min(d_open.min(), d_bld.min(), d_wat.min()) > 4.0:
        return
    _over(acc, inside(d_open) * 0.22, INK['dirt'])
    _over(acc, inside(d_wat) * 0.62, INK['water'])
    _over(acc, _edge(np.abs(d_wat), st['outline'] * 0.5, s) * 0.9, INK['wline'])
    _over(acc, inside(d_road) * 0.78, INK['road'])
    _over(acc, _edge(np.abs(d_road), st['kerb'] * 0.5, s) * 0.95, INK['kerb'])
    fill = inside(d_bld)
    sp = (1.5, 2.4)[level_index]
    t = ((X + Z) / sp) % 1.0
    line = _edge(np.minimum(t, 1.0 - t) * sp / math.sqrt(2.0), st['contour'] * 0.9, s)
    _over(acc, fill * 0.35, INK['dirt'])
    _over(acc, fill * line * 0.55, INK['wall'])
    _over(acc, _edge(np.abs(d_bld), st['wall'] * 0.5 + 0.1, s) * 0.95, INK['wall'])


def render_tile(L, level, level_col, level_row, x0, z1, level_index):
    """-> (512, 512, 4) uint8 straight-alpha RGBA of one tile, or None when it is empty."""
    s = TEXEL0 * (2 ** level_index)
    st = STYLE[level_index]
    cs = (np.arange(TILE_PX, dtype=np.float64) - BORDER_PX + level_col * INNER + 0.5) * s + x0
    rs = z1 - (np.arange(TILE_PX, dtype=np.float64) - BORDER_PX + level_row * INNER + 0.5) * s
    X, Z = np.meshgrid(cs, rs)
    box = (cs[0] - 4, rs[-1] - 4, cs[-1] + 4, rs[0] + 4)
    acc = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    H = L.H
    inside = None
    if L.has_ground:
        inside = H.inside(X, Z)
        if not inside.any():
            pass
        else:
            ci = np.clip(((X - H.ox) / H.cell).astype(int), 0, H.nx - 1)
            cj = np.clip(((Z - H.oz) / H.cell).astype(int), 0, H.nz - 1)
            idx = L.cells[cj, ci]
            for pi, pid in enumerate(L.palette):
                ink = GROUND_INK.get(pid)
                if not ink:
                    continue
                sel = inside & (idx == pi)
                if sel.any():
                    _over(acc, sel.astype(np.float32) * ink[1], INK[ink[0]])
            # contour lines every CONTOUR_STEP metres
            h = H.at(X, Z)
            gx = (H.at(X + H.cell * 0.5, Z) - H.at(X - H.cell * 0.5, Z)) / H.cell
            gz = (H.at(X, Z + H.cell * 0.5) - H.at(X, Z - H.cell * 0.5)) / H.cell
            grad = np.maximum(np.hypot(gx, gz), 0.02)
            dist = np.abs(((h + CONTOUR_STEP * 0.5) % CONTOUR_STEP) - CONTOUR_STEP * 0.5) / grad
            _over(acc, _edge(dist, st['contour'] * 0.5, s) * 0.55 * inside, INK['cont'])
    if L.plan is not None:
        _draw_plan(acc, L, X, Z, s, st, level_index)
    for w in L.waters:
        pxy = w['poly']
        if max(p[0] for p in pxy) < box[0] or min(p[0] for p in pxy) > box[2] or max(p[1] for p in pxy) < box[1] or min(p[1] for p in pxy) > box[3]:
            continue
        m = in_polygon(X, Z, pxy)
        if m.any():
            _over(acc, m.astype(np.float32) * 0.62, INK['water'])
            d = _poly_edge_distance(X, Z, pxy, box)
            _over(acc, _edge(d, st['outline'] * 0.5, s) * 0.9, INK['wline'])
    for r in L.roads:
        c = r['centre']
        d = np.full(X.shape, 1e9, dtype=np.float32)
        for i in range(len(c) - 1):
            a, b = c[i], c[i + 1]
            if (max(a[0], b[0]) + r['half'] + 2 < box[0] or min(a[0], b[0]) - r['half'] - 2 > box[2]
                    or max(a[1], b[1]) + r['half'] + 2 < box[1] or min(a[1], b[1]) - r['half'] - 2 > box[3]):
                continue
            d = np.minimum(d, _seg_distance(X, Z, a, b))
        if d.min() > r['half'] + 2:
            continue
        _over(acc, _edge(d, r['half'], s) * 0.78, INK['road'])
        _over(acc, _edge(np.abs(d - r['half']), st['kerb'] * 0.5, s) * 0.95, INK['kerb'])
    for e in L.edges:
        d = _poly_edge_distance(X, Z, e, box)
        if d.min() < 3:
            _over(acc, _edge(d, st['wall'] * 0.5 + 0.2, s) * 0.95, INK['wall'])
    for w in L.walls:
        px, pz = w['pos'][0], w['pos'][2]
        hx, hz = w['size'][0] / 2.0, w['size'][2] / 2.0
        if px + hx < box[0] or px - hx > box[2] or pz + hz < box[1] or pz - hz > box[3]:
            continue
        qy, qw = w['orient'][1], w['orient'][3]
        yaw = 2.0 * math.atan2(qy, qw)
        ca, sa = math.cos(yaw), math.sin(yaw)
        lx = (X - px) * ca - (Z - pz) * sa
        lz = (X - px) * sa + (Z - pz) * ca
        dd = np.maximum(np.abs(lx) - hx, np.abs(lz) - hz)
        _over(acc, _edge(dd, 0.0, s) * 0.95, INK['wall'])
    for (tx, tz, kind) in L.trees:
        if tx < box[0] - 3 or tx > box[2] + 3 or tz < box[1] - 3 or tz > box[3] + 3:
            continue
        rad = {'tree': 1.7, 'bush': 0.9, 'rock': 1.3}[kind]
        dd = np.hypot(X - tx, Z - tz)
        _over(acc, _edge(dd, rad, s) * 0.85, INK['tree' if kind == 'tree' else ('bush' if kind == 'bush' else 'rock')])
        _over(acc, _edge(np.abs(dd - rad), st['tree_line'] * 0.5, s) * 0.9, INK['treel'])
    if acc[..., 3].max() < 0.004:
        return None
    a = acc[..., 3:4]
    rgb = np.where(a > 1e-4, acc[..., :3] / np.maximum(a, 1e-4), 0.0)
    out = np.concatenate([np.clip(rgb, 0, 255), np.clip(a, 0, 1) * 255.0], axis=-1)
    return np.rint(out).astype(np.uint8)


# ------------------------------------------------------------------------------------------------ PNG and pack
def _chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_tile(rgba):
    """One 8-bit palette PNG: PLTE, tRNS, a single IDAT, filter 0 on every row (what the DLL's own decoder reads)."""
    from PIL import Image
    flat = rgba.reshape(-1, 4)
    cols, inv = np.unique(flat, axis=0, return_inverse=True)
    if len(cols) <= 256:
        pal, idx = cols, inv.reshape(rgba.shape[:2]).astype(np.uint8)
    else:
        q = Image.fromarray(rgba, 'RGBA').quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        pal = np.array(q.getpalette('RGBA'), dtype=np.uint8).reshape(-1, 4)
        idx = np.asarray(q, dtype=np.uint8)
    raw = b''.join(b'\0' + idx[r].tobytes() for r in range(idx.shape[0]))
    plte = pal[:, :3].tobytes()
    trns = pal[:, 3].tobytes().rstrip(b'\xff')
    out = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', rgba.shape[1], rgba.shape[0], 8, 3, 0, 0, 0)) + _chunk(b'PLTE', plte)
    if trns:
        out += _chunk(b'tRNS', trns)
    return out + _chunk(b'IDAT', zlib.compress(raw, 6)) + _chunk(b'IEND', b'')


def decode_tile(png):
    """The reverse of encode_tile (and of the baker's tiles): -> (n, n, 4) uint8. Mirrors the DLL's reader: one IDAT, palette, filter 0."""
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    at, pal, trns, idat, w, h = 8, None, b'', None, 0, 0
    while at + 12 <= len(png):
        ln = struct.unpack('>I', png[at:at + 4])[0]
        tag, body = png[at + 4:at + 8], png[at + 8:at + 8 + ln]
        if tag == b'IHDR':
            w, h = struct.unpack('>II', body[:8])
            if body[8] != 8 or body[9] != 3 or body[12] != 0:
                raise MinimapError('not an 8-bit palette PNG without interlace')
        elif tag == b'PLTE':
            pal = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif tag == b'tRNS':
            trns = body
        elif tag == b'IDAT':
            if idat is not None:
                raise MinimapError('more than one IDAT chunk')
            idat = body
        at += 12 + ln
    raw = zlib.decompress(idat)
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(h, w + 1)
    if rows[:, 0].any():
        raise MinimapError('a filtered row')
    idx = rows[:, 1:]
    a = np.full(len(pal), 255, dtype=np.uint8)
    a[:len(trns)] = np.frombuffer(trns, dtype=np.uint8)
    return np.concatenate([pal[idx], a[idx][..., None]], axis=-1)


def level_grid(width_m, height_m, level):
    cover = INNER * TEXEL0 * (2 ** level)
    return int(math.ceil(width_m / cover)), int(math.ceil(height_m / cover))


def write_occ(path, L, x0, z1, cols0, rows0):
    cell = CELL_OCC
    wm, hm = cols0 * INNER * TEXEL0, rows0 * INNER * TEXEL0
    cols, rows = int(math.ceil(wm / cell)), int(math.ceil(hm / cell))
    xs = x0 + (np.arange(cols) + 0.5) * cell
    zs = z1 - (np.arange(rows) + 0.5) * cell
    X, Z = np.meshgrid(xs, zs)
    ok = L.H.inside(X, Z) if L.has_ground else np.zeros(X.shape, dtype=bool)
    if L.plan is not None:
        walk = L.sdf['open']
        for dx in (-0.4, 0.0, 0.4):
            for dz in (-0.4, 0.0, 0.4):
                ok |= scenplan.bilinear(walk, L.plan, X + dx * cell, Z + dz * cell) < cell * 0.5
        ok |= scenplan.bilinear(L.sdf['building'], L.plan, X, Z) < 0
    for r in L.roads:
        c = r['centre']
        for i in range(len(c) - 1):
            ok |= _seg_distance(X, Z, c[i], c[i + 1]) <= r['half'] + cell * 0.5
    lines = ['occ %.1f %d %d %.2f %.2f' % (cell, cols, rows, x0, z1)] + [''.join('1' if v else '0' for v in row) for row in ok]
    with open(path, 'w', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def build(m, out_dir, name=None, assets=None, progress=None):
    """Draw the pack of one map recipe (the HIGH-LEVEL keys: terrain, roads, water, ... as the project stores them).
    -> dict(name, file, occ, line, bounds [x0, z0, x1, z1], tiles, bytes, layers)."""
    L = Layers(m, assets)
    name = (name or m.get('name') or 'map').lower()
    if name.startswith('mainmap_'):
        name = name[len('mainmap_'):]
    x0, zlo, x1, z1 = L.extent
    cols0, rows0 = level_grid(x1 - x0, z1 - zlo, 0)
    grids = [level_grid(x1 - x0, z1 - zlo, k) for k in range(LEVELS)]
    os.makedirs(out_dir, exist_ok=True)
    hdr = 32 + 12 * LEVELS
    tables = []
    at = hdr
    for (c, r) in grids:
        tables.append(at)
        at += c * r * 8
    body = bytearray()
    entries = [[(0, 0)] * (c * r) for (c, r) in grids]
    count = 0
    total = sum(c * r for c, r in grids)
    done = 0
    for lv, (c, r) in enumerate(grids):
        for row in range(r):
            for col in range(c):
                done += 1
                if progress and done % 20 == 0:
                    progress('Drawing the minimap', done, total)
                t = render_tile(L, lv, col, row, x0, z1, lv)
                if t is None:
                    continue
                png = encode_tile(t)
                entries[lv][row * c + col] = (at + len(body), len(png))
                body += png
                count += 1
    head = bytearray(b'MMP1')
    head += struct.pack('<I', 1) + struct.pack('<ff', x0, z1) + struct.pack('<f', TEXEL0) + struct.pack('<III', TILE_PX, BORDER_PX, LEVELS)
    for lv, (c, r) in enumerate(grids):
        head += struct.pack('<III', c, r, tables[lv])
    tab = bytearray()
    for lv in range(LEVELS):
        for off, sz in entries[lv]:
            tab += struct.pack('<II', off, sz)
    pack = bytes(head) + bytes(tab) + bytes(body)
    fn = '%s.mmp' % name
    with open(os.path.join(out_dir, fn), 'wb') as f:
        f.write(pack)
    occ = '%s.occ' % name
    write_occ(os.path.join(out_dir, occ), L, x0, z1, cols0, rows0)
    wpx, hpx = cols0 * INNER, rows0 * INNER
    zmin = z1 - rows0 * INNER * TEXEL0
    xmax = x0 + cols0 * INNER * TEXEL0
    line = '%s %.2f %.2f %.2f %.2f %d %d %s' % (name, x0, zmin, xmax, z1, wpx, hpx, fn)
    return dict(name=name, file=fn, occ=occ, line=line, bounds=[x0, zmin, xmax, z1], width=wpx, height=hpx, tiles=count, bytes=len(pack), layers=L)


# ------------------------------------------------------------------------------------------------ the index
# the pack areas of the nine shipped maps (Gameplay+'s minimap.txt; measured by its own baker), for the overlap check
SHIPPED_BOUNDS = {
    'map01_dea_hq_us_border': [-900.62, 277.04, 359.38, 1285.04], 'map02_lostoros_downtown': [-429.45, -1016.78, 578.55, 747.22],
    'map03_lostoros_industrial': [-1028.83, -525.24, 105.17, 734.76], 'map04_lostoros_train_harbour': [-903.57, -2313.93, -21.57, -297.93],
    'map06_virgillos_farm': [-45.09, -2461.06, 1844.91, -571.06], 'map07_meat_factory': [1829.88, -2156.35, 3089.88, -1274.35],
    'map08_hacienda': [-974.28, -1558.12, -470.28, -1180.12], 'map09_jungle': [-2814.18, -4923.60, 209.82, -1647.60],
    'map10_runawaytrain': [293.76, -2380.58, 2309.76, 1273.42]}


def parse_line(line):
    p = line.split()
    if len(p) != 8:
        return None
    return dict(name=p[0], bounds=[float(p[1]), float(p[2]), float(p[3]), float(p[4])], width=int(p[5]), height=int(p[6]), file=p[7])


def overlaps(bounds, others):
    """Names of the other packs (dict name -> [x0, z0, x1, z1]) that cover any of the same positions: the DLL picks a pack by position,
    so two packs over one place are ambiguous."""
    out = []
    for n, b in others.items():
        if bounds[0] < b[2] and b[0] < bounds[2] and bounds[1] < b[3] and b[1] < bounds[3]:
            out.append(n)
    return sorted(out)


def merge_lines(lines, text=''):
    """minimap.txt with `lines` added: a map already listed is replaced, the header and the other maps stay."""
    keep = [l for l in (text or '').splitlines() if l.strip()]
    head = [l for l in keep if l.startswith('#')] or ['# TODGameplay minimap index: name x0 z0 x1 z1 width height file']
    cur = {}
    for l in keep:
        if not l.startswith('#') and parse_line(l):
            cur[l.split()[0]] = l
    for l in lines:
        cur[l.split()[0]] = l
    return '\n'.join(head + [cur[k] for k in sorted(cur)]) + '\n'


# ------------------------------------------------------------------------------------------------ calibration
def pixel_of(info, x, z):
    """The pack pixel (level 0) of a world position, as the DLL computes it: ((x - x0) / texel, (z1 - z) / texel)."""
    b = info['bounds']
    return (x - b[0]) / TEXEL0, (b[3] - z) / TEXEL0


def sample(pack, info, x, z, level=0):
    """The RGBA of the pack at a world position (level 0 or 1), read back from the written file."""
    px, pz = pixel_of(info, x, z)
    s = 2 ** level
    px, pz = px / s, pz / s
    cols, rows, tab = struct.unpack_from('<III', pack, 32 + 12 * level)
    col, row = int(px // INNER), int(pz // INNER)
    if not (0 <= col < cols and 0 <= row < rows):
        return None
    off, sz = struct.unpack_from('<II', pack, tab + (row * cols + col) * 8)
    if not sz:
        return (0, 0, 0, 0)
    t = decode_tile(pack[off:off + sz])
    return tuple(int(v) for v in t[int(pz - row * INNER) + BORDER_PX, int(px - col * INNER) + BORDER_PX])


def _open_water_point(L, w):
    """A point inside the pond that is as far from every road as possible (a bridge over the pond would hide the water)."""
    xs, zs = [p[0] for p in w['poly']], [p[1] for p in w['poly']]
    best, bd = (sum(xs) / len(xs), sum(zs) / len(zs)), -1.0
    gx, gz = np.meshgrid(np.linspace(min(xs), max(xs), 15), np.linspace(min(zs), max(zs), 15))
    inside = in_polygon(gx, gz, w['poly'])
    for x, z, ok in zip(gx.ravel(), gz.ravel(), inside.ravel()):
        if not ok:
            continue
        d = min([float(_seg_distance(np.array([x]), np.array([z]), r['centre'][i], r['centre'][i + 1])[0]) - r['half']
                 for r in L.roads for i in range(len(r['centre']) - 1)] + [99.0])
        if d > bd:
            best, bd = (float(x), float(z)), d
    return best


def calibrate(out_dir, info):
    """The check of ideas 79: places whose picture is known must show it where the DLL looks.
    Road centres and points well off the road (and the middle of a pond) are read back from the written pack at the pixel the DLL computes.
    -> list of dict(check, result, evidence)."""
    L = info['layers']
    with open(os.path.join(out_dir, info['file']), 'rb') as f:
        pack = f.read()
    checks = []
    hdr = struct.unpack_from('<4sIffffIII', pack, 0)
    ok = hdr[0] == b'MMP1' and abs(hdr[2] - info['bounds'][0]) < 1e-3 and abs(hdr[3] - info['bounds'][3]) < 1e-3 and hdr[4] == TEXEL0
    checks.append(dict(check='minimap header: corner and scale', result='PASS' if ok else 'FAIL', evidence='x0 %.2f z1 %.2f texel %.2f' % (hdr[2], hdr[3], hdr[4])))
    for r in L.roads:
        c = r['centre']
        picks = [len(c) // 4, len(c) // 2, (3 * len(c)) // 4]
        bad = []
        for i in picks:
            if i + 1 >= len(c):
                continue
            mid = (c[i] + c[i + 1]) / 2.0
            v = sample(pack, info, mid[0], mid[1])
            # the road ink (or its kerb) must be under the centre line
            if not v or v[3] < 100 or abs(v[0] - INK['road'][0]) > 40:
                bad.append(('on', round(float(mid[0]), 1), round(float(mid[1]), 1), v))
        checks.append(dict(check='minimap calibration: road %s centre shows the road' % r['id'], result='FAIL' if bad else 'PASS',
                           evidence=str(bad[:1]) if bad else '%d spots checked at the pixel the DLL computes' % len(picks)))
    for w in L.waters:
        px, pz = _open_water_point(L, w)
        v = sample(pack, info, px, pz)
        good = bool(v) and v[3] > 100 and v[2] > v[0]
        checks.append(dict(check='minimap calibration: water %s shows water' % w['id'], result='PASS' if good else 'FAIL', evidence=str(v)))
    if L.plan is not None:                                  # a scene: the most interior cell of each class must show its ink where the DLL looks
        P = L.plan
        for cls, key in ((scenplan.ROAD, 'road'), (scenplan.BUILDING, 'building'), (scenplan.WATER, 'water')):
            f = L.sdf[key]
            if not (P['grid'] == cls).any():
                continue
            r, c = np.unravel_index(int(np.argmin(f)), f.shape)
            x = P['x0'] + (c + 0.5) * P['cell']
            z = P['z1'] - (r + 0.5) * P['cell']
            v = sample(pack, info, x, z)
            if key == 'road':
                good = bool(v) and v[3] > 150 and abs(v[0] - INK['road'][0]) < 40
            elif key == 'water':
                good = bool(v) and v[3] > 100 and v[2] > v[0]
            else:
                good = bool(v) and v[3] > 60
            checks.append(dict(check='minimap calibration: scene plan, %s shows %s' % (key, key), result='PASS' if good else 'FAIL',
                               evidence='%s at %.1f, %.1f' % (v, x, z)))
    # a spot of plain nothing: far outside every feature, inside the pack
    b = info['bounds']
    v = sample(pack, info, b[0] + 2.0, b[3] - 2.0)
    checks.append(dict(check='minimap calibration: the margin is empty', result='PASS' if v is not None and v[3] < 30 else 'FAIL', evidence=str(v)))
    return checks


# ------------------------------------------------------------------------------------------------ the editor's picture
PARCHMENT = (226, 208, 170)


def _ink_name(rgb):
    best, bd = 'ground', 1e9
    for k, v in INK.items():
        d = sum((int(a) - b) ** 2 for a, b in zip(rgb, v))
        if d < bd:
            best, bd = k, d
    return best if bd < 2500 else 'ground'


def preview(m, assets=None, max_px=512, test=None):
    """The picture the minimap pack will hold, as one image for the editor (level 1, 0.5 m per texel, drawn by the same code as the pack, over the radar's
    parchment), plus where the DLL looks for a world position.
    test = [x, z] -> `at`: dict(inside, pixel [px, pz] in the level 0 pack, ink) read back from the picture at that position.
    -> dict(png (base64), width, height, bounds [x0, z0, x1, z1] of the picture, pack [x0, z0, x1, z1] (the area the pack covers), overlaps [names], at)"""
    import base64
    import io
    from PIL import Image
    L = Layers(m, assets)
    x0, zlo, x1, z1 = L.extent
    s = TEXEL0 * 2
    cols, rows = level_grid(x1 - x0, z1 - zlo, 1)
    wpx, hpx = int(math.ceil((x1 - x0) / s)), int(math.ceil((z1 - zlo) / s))
    img = np.zeros((rows * INNER, cols * INNER, 4), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            t = render_tile(L, 1, c, r, x0, z1, 1)
            if t is not None:
                img[r * INNER:(r + 1) * INNER, c * INNER:(c + 1) * INNER] = t[BORDER_PX:-BORDER_PX, BORDER_PX:-BORDER_PX]
    img = img[:hpx, :wpx]
    a = img[..., 3:4].astype(np.float32) / 255.0
    rgb = np.rint(img[..., :3] * a + np.array(PARCHMENT, dtype=np.float32) * (1 - a)).astype(np.uint8)
    pil = Image.fromarray(rgb, 'RGB')
    if max(pil.size) > max_px:
        k = max_px / max(pil.size)
        pil = pil.resize((max(1, int(pil.size[0] * k)), max(1, int(pil.size[1] * k))), Image.BILINEAR)
    buf = io.BytesIO()
    pil.save(buf, 'PNG')
    cols0, rows0 = level_grid(x1 - x0, z1 - zlo, 0)
    pack = [x0, z1 - rows0 * INNER * TEXEL0, x0 + cols0 * INNER * TEXEL0, z1]
    out = dict(png=base64.b64encode(buf.getvalue()).decode('ascii'), width=pil.size[0], height=pil.size[1], bounds=[x0, z1 - hpx * s, x0 + wpx * s, z1],
               pack=pack, overlaps=overlaps(pack, SHIPPED_BOUNDS), at=None)
    if test:
        px, pz = (test[0] - x0) / TEXEL0, (z1 - test[1]) / TEXEL0
        ix, iz = int((test[0] - x0) / s), int((z1 - test[1]) / s)
        inside = 0 <= ix < wpx and 0 <= iz < hpx
        out['at'] = dict(inside=inside, pixel=[round(px, 1), round(pz, 1)], ink=_ink_name(rgb[iz, ix]) if inside else None)
    return out
