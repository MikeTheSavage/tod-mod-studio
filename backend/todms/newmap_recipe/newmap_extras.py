"""Block-level writers of the new-map builder that the submaptool grafts cannot do: copying SHIPPED records (ground pictures, models,
skies) into a new map block, writing the look into its light nodes, and cutting an extension section down to a region or to nothing.

make_new_map.py binds this module to its own tool namespace (`bind`) and calls:
  install(NG)                 newgeo learns two more kinds of input: a texture with `shipped` (a real picture of the game, copied with its
                              record) and a model with `shipped` (a real model of the game, copied with its pictures)
  apply_look_block(...)       the `lighting` of an expanded map written into the fragments of its blocks (+ the sky records it needs)
  prune_section(...)          carry region / nothing for an extension section
  sightlines(...)             the "the player could see past the edge" check
Nothing here changes a shipped block: donors are only read.
"""
import math
import struct
import os
import sys

NS = {}                  # ft, fe, tb, tf, S, NG, tm (bound by make_new_map)
_CACHE = {}              # entry -> NG.Records of a shipped block (last one only)
NOTES = []               # plain sentences about what could not be done exactly (read by the builder)
SCAN_LIMIT = 600


def bind(**kw):
    NS.update(kw)


def note(s):
    if s not in NOTES:
        NOTES.append(s)


# ------------------------------------------------------------------------------------------------ donors
def _records(entry):
    """NG.Records of a shipped block, read only."""
    key = entry.lower()
    if _CACHE.get('key') == key:
        return _CACHE['recs']
    ft, tb, NG = NS['ft'], NS['tb'], NS['NG']
    ent = ft.resolve_entry(entry)
    raw = ft.archive().read(ent)
    recs = NG.Records(tb, tb.Block(raw, os.path.splitext(ent)[1]))
    _CACHE.clear()
    _CACHE.update(key=key, recs=recs)
    return recs


def _norm(name):
    s = (name or '').replace('\\', '/').lower()
    if not s.startswith('/'):
        s = '/' + s
    if not s.startswith('/data/'):
        s = '/data' + s
    return s


def find_donor(kind, name, hints=(), also=()):
    """(entry, item, records) of the record `name` in a shipped block: first in `hints` (block entries, from the asset index), then in `also`
    (blocks already open), else by scanning the game's blocks (slow, once). kind: 'texture' (type 0) or 'model' (type 3)."""
    want = 0 if kind == 'texture' else 3
    ln = _norm(name)
    tried = set()
    for e in list(hints) + list(also):
        if e in tried:
            continue
        tried.add(e)
        try:
            recs = _records(e)
        except Exception:                                   # noqa: BLE001
            continue
        for it in recs.items:
            if it['type'] == want and it['name'].lower() == ln:
                return e, it, recs
    ft = NS['ft']
    n = 0
    for e in sorted(ft.archive().names):
        low = e.lower()
        if '/shared/' not in low or not low.endswith(('.map', '.submap')) or e in tried:
            continue
        n += 1
        if n > SCAN_LIMIT:
            break
        try:
            recs = _records(e)
        except Exception:                                   # noqa: BLE001
            continue
        for it in recs.items:
            if it['type'] == want and it['name'].lower() == ln:
                return e, it, recs
    return None


def _tex_fields(rec):
    from todms import assetindex
    f = assetindex.texture_fields(rec, 0)
    return f or dict(w=0, h=0, fmt='?')


def _texture_entry(item):
    import numpy as np
    f = _tex_fields(item['rec'])
    return dict(name=item['name'], record=item['rec'], payload=item['payload'], w=f['w'], h=f['h'], fmt=f['fmt'],
                preview=np.zeros((4, 4, 3), dtype='uint8'), shipped=True)


# ------------------------------------------------------------------------------------------------ newgeo: shipped pictures and models
def install(NG):
    """Idempotent. newgeo.make_textures / make_models accept shipped inputs."""
    if getattr(NG, '_todms_extras', False):
        return True
    orig_tex, orig_mod = NG.make_textures, NG.make_models

    def make_textures(spec_tex, templates, folder):
        gen, ship = [], []
        used = set()
        for t in spec_tex:
            if t.get('shipped'):
                d = find_donor('texture', t['shipped'], t.get('shipped_blocks') or [])
                if d and d[1]['name'].lower() not in used:
                    used.add(d[1]['name'].lower())
                    ship.append((t['name'], d[1]))
                    continue
                note('The shipped picture %s was not found in the game; a generated picture is used for %s.' % (t['shipped'].split('/')[-1], t['name']))
            gen.append(t)
        out = orig_tex(gen, templates, folder)
        for nm, it in ship:
            out[nm] = _texture_entry(it)
        return {t['name']: out[t['name']] for t in spec_tex if t['name'] in out}

    def make_models(spec_models, folder, tex, mw, tm, log):
        gen = [m for m in spec_models if not m.get('shipped')]
        ship = [m for m in spec_models if m.get('shipped')]
        out = orig_mod(gen, folder, tex, mw, tm, log)
        for md in ship:
            d = find_donor('model', md['shipped'], md.get('shipped_blocks') or [])
            if not d:
                raise NG.GeoError('shipped model %s is not in the game blocks' % md['shipped'])
            entry, it, recs = d
            m = tm.decode(it['rec'], 0, len(it['rec']))
            names = [t['s'].decode('latin-1') for t in m['texnames']]
            for tn in names:
                key = '@' + _norm(tn)
                if key in tex or any(v.get('name', '').lower() == _norm(tn) for v in tex.values()):
                    continue
                td = next((x for x in recs.items if x['type'] == 0 and x['name'].lower() == _norm(tn)), None)
                if td is None:
                    dd = find_donor('texture', tn, [entry])
                    td = dd[1] if dd else None
                if td is None:
                    raise NG.GeoError('picture %s of shipped model %s is not in the game blocks' % (tn, md['shipped']))
                tex[key] = _texture_entry(td)
            out.append(dict(short=md['name'], full=it['name'], record=it['rec'], textures=names, vertices=0, triangles=0, hull_tris=[],
                            hulls=len(m.get('hulls') or []) if isinstance(m, dict) else 0, bytes=len(it['rec']), sphere=[0.0, 0.0, 0.0, 0.0],
                            shipped=True))
        return out

    NG.make_textures, NG.make_models = make_textures, make_models
    NG._todms_extras = True
    return True


# ------------------------------------------------------------------------------------------------ look
def sky_records(want_model, hints=()):
    """The model record and picture records of a shipped sky: -> [item, ...] (model first) or None."""
    tm = NS['tm']
    d = find_donor('model', want_model, hints)
    if not d:
        return None
    entry, it, recs = d
    m = tm.decode(it['rec'], 0, len(it['rec']))
    out = [it]
    for t in m['texnames']:
        td = next((x for x in recs.items if x['type'] == 0 and x['name'].lower() == _norm(t['s'].decode('latin-1'))), None)
        if td is None:
            return None
        out.append(td)
    return out


def apply_look_block(raw, ext, lighting, T, drop_old_sky=False, root_name=None):
    """Write `lighting` (look.resolve) into the fragments of one block. -> (new raw or None when nothing changed, report dict)."""
    from todms.mapgen import look
    tb, fe, NG, S, tm = NS['tb'], NS['fe'], NS['NG'], NS['S'], NS['tm']
    b = tb.Block(raw, ext)
    recs = NG.Records(tb, b)
    names = {i['name'].lower() for i in recs.items}
    docs, idx = {}, {}
    for k, i in enumerate(recs.items):
        if i['type'] != 4 or len(i['payload']) < 24:
            continue
        try:
            docs[i['name']] = fe.FragDoc(i['payload'], T, i['name'])
            idx[i['name']] = k
        except Exception:                                   # noqa: BLE001
            continue
    has_sky_node = any((d.type_of(n) or '') == 'SkyBox' for d in docs.values() for n in d.created_ids())
    sky = lighting.get('sky')
    want = look.skies().get(sky) if sky else None
    avail = []
    added = []
    if want and has_sky_node:
        if _norm(want) in names:
            avail.append(sky)
        else:
            rows = sky_records(want, _sky_hints(sky))
            if rows:
                for r in rows:
                    if r['name'].lower() not in names:
                        recs.items.append(dict(r))
                        names.add(r['name'].lower())
                        added.append(r['name'])
                avail.append(sky)
    rep = look.apply_look(docs, lighting, avail)
    for nm in rep['changed']:
        recs.items[idx[nm]]['payload'] = docs[nm].payload()
    rep['added_records'] = added
    if not rep['changed'] and not added:
        return None, rep
    if drop_old_sky and added and root_name:
        dropped, _ = NG.drop_unused(recs, SimpleK(), [root_name], {})
        rep['dropped_records'] = len(dropped)
    recs.write_into(b)
    return b.serialize(), rep


class SimpleK:
    """The bits of the namespace newgeo.drop_unused reads."""
    def __getattr__(self, k):
        return NS[k]


SKY_HINTS = {}


def _sky_hints(sky):
    from todms.mapgen import look
    out = []
    for s in look.data()['skies']:
        if s['id'] == sky:
            for e in s.get('used_by') or []:
                if e not in out:
                    out.append(e)
    return out


# ------------------------------------------------------------------------------------------------ extension sections: carry
def polygon_from_region(region):
    """region: [x0, z0, x1, z1] (a rectangle) or a list of [x, z] corners -> list of [x, z]."""
    r = list(region or [])
    if len(r) == 4 and not isinstance(r[0], (list, tuple)):
        x0, z0, x1, z1 = [float(v) for v in r]
        return [[min(x0, x1), min(z0, z1)], [max(x0, x1), min(z0, z1)], [max(x0, x1), max(z0, z1)], [min(x0, x1), max(z0, z1)]]
    if len(r) >= 3 and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in r):
        return [[float(p[0]), float(p[1])] for p in r]
    raise ValueError('a region is a rectangle [x0, z0, x1, z1] or a list of at least three [x, z] corners')


def inside(poly, x, z):
    c = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / ((zj - zi) or 1e-12) + xi:
            c = not c
        j = i
    return c


KEEP_ALWAYS = ('default_global_light', 'FOG_Controller', 'SkyBox', 'default_GFX', 'MenuCamera')
# Only what is DRAWN is cut by position. Game test (wave 3 proofs, runs r1-r6): cutting the logic nodes (triggers, placeholders, traffic
# points, key frames ...) together with the drawn ones made the game exit during the load of the section; cutting only the drawn
# ones (or only the logic ones) loads and plays. A drawn node of a model is kept when its bounding sphere reaches the region, because
# a ground piece is placed by its centre and can be far larger than the region.
VISUAL = ('Model', 'SignPost', 'generic_', 'Sprite', 'Particle')


def is_visual(type_name):
    return any(w in (type_name or '') for w in VISUAL) and not any(w in (type_name or '') for w in KEEP_ALWAYS)


def reaches(poly, x, z, r):
    """Is the point within r metres of the polygon (or inside it)?"""
    if inside(poly, x, z):
        return True
    if r <= 0:
        return False
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        dx, dz = bx - ax, bz - az
        L2 = dx * dx + dz * dz
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / L2))
        if math.hypot(x - (ax + t * dx), z - (az + t * dz)) <= r:
            return True
    return False


def _frag_base(v):
    return (v or '').replace(chr(92), '/').split('/')[-1].lower()


def instancing(docs):
    """{fragment base name: [(record index, node)]} of the nodes whose `fragment` property places it."""
    fe = NS['fe']
    out = {}
    for k, d in docs.items():
        for n in d.created_ids():
            v = d.get(n, 'fragment')
            if v:
                out.setdefault(_frag_base(v), []).append((k, n))
    return out


class Frags:
    """The fragment documents of one block with the world transform of each one's placing node (prefabs: identity, flagged)."""

    def __init__(self, raw, ext, T):
        tb, fe, NG = NS['tb'], NS['fe'], NS['NG']
        self.b = tb.Block(raw, ext)
        self.recs = NG.Records(tb, self.b)
        self.docs = {}
        for k, it in enumerate(self.recs.items):
            if it['type'] == 4 and len(it['payload']) >= 24:
                try:
                    self.docs[k] = fe.FragDoc(it['payload'], T, it['name'])
                except Exception:                               # noqa: BLE001
                    pass
        self.ins = instancing(self.docs)
        self.base_of = {k: _frag_base(self.recs.items[k]['name']) for k in self.docs}
        self._cache = {}

    def owner(self, k, depth=0):
        fe = NS['fe']
        if k in self._cache:
            return self._cache[k]
        hits = self.ins.get(self.base_of[k], [])
        if len(hits) != 1 or depth > 8:
            res = (fe.IDENT, len(hits) > 1)
        else:
            k2, n = hits[0]
            up, _ = self.owner(k2, depth + 1)
            res = (self.docs[k2].world(n, up), False)
        self._cache[k] = res
        return res


def node_positions(raw, ext, T, kinds=('Model',)):
    """[(type, x, y, z)] of the leaf nodes of the given type names (substring match) in a block's fragments, in world space."""
    F = Frags(raw, ext, T)
    out = []
    for k, d in F.docs.items():
        W0, prefab = F.owner(k)
        for n in d.created_ids():
            t = d.type_of(n) or ''
            if any(w in t for w in kinds):
                try:
                    p = d.world(n, W0)[0]
                except Exception:                               # noqa: BLE001
                    continue
                out.append((t, p[0], p[1], p[2]))
    return out


def occupancy(raw, ext, T, cell=24.0):
    """The set of (ix, iz) ground cells of `cell` metres that hold a Model node: a coarse picture of what a block draws."""
    return {(int(math.floor(x / cell)), int(math.floor(z / cell))) for _, x, _, z in node_positions(raw, ext, T)}


def prune_section(raw, ext, poly, T, root_name=None, hold=()):
    """Cut the copy of a host section down for an extension section. Keeps: the light, fog, sky and screen nodes; every node whose world
    position lies inside `poly` (None = none); the folders above what is kept. A fragment that several nodes place (a prefab) is kept or
    dropped whole by the position of the nodes that place it. Then every model, picture and fragment nothing names any more is dropped.
    -> (new raw, dict(kept, removed, dropped_records, notes))."""
    fe, NG = NS['fe'], NS['NG']
    F = Frags(raw, ext, T)
    b, recs, docs = F.b, F.recs, F.docs
    owner = F.owner
    tm = NS['tm']
    radius = {}                                                 # model record name -> bounding sphere radius
    for it in recs.items:
        if it['type'] == 3:
            try:
                m = tm.decode(it['rec'], 0, len(it['rec']))
                radius[it['name'].lower().replace(chr(92), '/')] = struct.unpack_from('<4f', m['raw'], 0x44)       # centre (model space) + radius
            except Exception:                                   # noqa: BLE001
                pass
    kept = removed = 0
    notes = []
    for k, d in docs.items():
        W0, prefab = owner(k)
        ids = d.created_ids()
        if not ids or prefab:
            kept += len(ids)
            continue
        parents = {n: (d.get(n, fe.P_PARENT) or 0) for n in ids}
        has_kid = {p for p in parents.values() if p in parents}
        keep = set()
        for n in ids:
            if n in has_kid:
                continue
            t = d.type_of(n) or ''
            if any(w in t for w in KEEP_ALWAYS):
                keep.add(n)
                continue
            if not is_visual(t):                                # logic nodes always stay (see VISUAL)
                keep.add(n)
                continue
            if poly is None:
                continue
            try:
                p = d.world(n, W0)[0]
            except Exception:                                   # noqa: BLE001
                keep.add(n)
                continue
            r, cx, cz = 0.0, 0.0, 0.0
            if 'Model' in t:
                ref = (d.get(n, 'modelres') or '').replace(chr(92), '/').lower()
                key = ref if ref.startswith('/data') else '/data' + ref
                sph = radius.get(key) or radius.get(ref)
                if sph:
                    cx, cz, r = float(sph[0]), float(sph[2]), float(sph[3]) + 5.0       # the sphere centre is in model space (not turned here: a margin covers it)
            if reaches(poly, p[0] + cx, p[2] + cz, r):
                keep.add(n)
        for n in list(keep):
            q = parents[n]
            while q in parents and q not in keep:
                keep.add(q)
                q = parents[q]
        roots = [n for n in ids if parents[n] not in parents]
        for n in roots:
            keep.add(n)
        drop = {n for n in ids if n not in keep}
        for n in [n for n in ids if n in drop and parents[n] not in drop]:
            sub = d.subtree(n)
            try:
                d.remove(n, deep=True)
                removed += len(sub)
            except Exception as e:                              # noqa: BLE001
                notes.append('%s stays (%s)' % (d.get(n, fe.P_NAME) or '0x%08X' % n, str(e)[:80]))
                kept += len(sub)
        kept += len(keep & set(ids))
        recs.items[k]['payload'] = d.payload()
    dropped = []
    if root_name:
        # the baked lighting of the section is looked up by the surviving meshes; its name does not appear in a fragment text any more after the
        # root is renamed, so the reference scan would drop it and every ground piece and building would draw black (game test r6, r7)
        light = [it['name'] for it in recs.items if it['type'] == 10]
        dropped, _ = NG.drop_unused(recs, SimpleK(), [root_name] + list(hold) + light, {})
    recs.write_into(b)
    return b.serialize(), dict(kept=kept, removed=removed, dropped_records=len(dropped), notes=notes)


# ------------------------------------------------------------------------------------------------ sight lines
def sightlines(walk, bounds, loaded, step=6.0, eye=1.7, far=90.0):
    """Warning data for "the player could see past the edge".
    walk: [(x, y, z)] samples of the section's walkable area; bounds: polygon [[x, z], ...] of the loaded section (what is drawn);
    loaded: a function (x, z) -> True when something is loaded there (the section or the map block). Casts rays in 8 directions from
    each sample; a ray that leaves `bounds` while still within `far` metres and lands on unloaded space marks the sample.
    -> list of dict(pos, dir_deg, distance) for the worst few."""
    hits = []
    for (x, y, z) in walk:
        for k in range(8):
            a = k * math.pi / 4.0
            dx, dz = math.cos(a), math.sin(a)
            d = step
            while d <= far:
                px, pz = x + dx * d, z + dz * d
                if not inside(bounds, px, pz):
                    if not loaded(px, pz):
                        hits.append(dict(pos=[round(x, 1), round(y, 1), round(z, 1)], dir_deg=int(math.degrees(a)), distance=round(d, 1)))
                    break
                d += step
    hits.sort(key=lambda h: h['distance'])
    return hits
