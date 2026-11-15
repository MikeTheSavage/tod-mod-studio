"""Collision generator core: new geometry -> TOD game collision, written into a model's HullList by the model writer.

A COLLISION SET is the unit both editors save (in the Unreal session, in a Mod Studio mod, in a .todmod file):

  {"kind": "todct-collision", "version": 1,
   "id": "ruin-wall-01", "label": "Ruin wall block", "map": "map09_jungle",
   "visual_only": false,              true = the mesh is scenery only (far forest): no collision is written
   "host": "auto" | "/data/Models/.../TER_Chunk_01.model",
   "source": {"editor": "unreal" | "modstudio", "asset": "/Game/...", "file": "x.glb", "actor": "label",
              "pos": [x,y,z], "rot": [x,y,z,w], "scale": [sx,sy,sz]},         where it came from (information)
   "method": "solid" | "surface" | "hull" | "ue_vhacd" | "ue_simple",
   "pieces": [{"verts": [[x,y,z], ...],            game WORLD coordinates (metres, TOD axes), convex, <= 255
               "faces": [[i,j,k,...], ...],          polygons, outward
               "material": "Stone",                  facecoll.mat face material (name or index)
               "surface": "0x02007C00"}]}             SurfacePropFields word (or a preset name of surfaces.PRESETS)

Pieces are stored in world space so the recipe does not depend on how a host is chosen: every build transforms them
into the host model's space. Building (apply_sets) for each host model:
  1. finds the host: a model with a HullList that the map places exactly ONCE (a model placed several times would
     get the new collision at every placement), auto = the one whose bounding sphere needs the least growth;
  2. edits the decoded MODEL record (model_writer's todmodel tree): the pieces are appended to the HullList as
     VertexCloud shapes (model_writer.hull_shape), the model sphere grows to cover them (model_edit.cover_collision,
     the engine's registration gate, subsystem_collision.md 11.4.1);
  3. re-serialises the record and splices it into the block, then runs model_edit.verify (strict block parse,
     header/payloads unchanged, every other record byte-identical, the record re-encodes identically, every model of
     the block round-trips, sphere covers collision, shapes consistent, quadtree parameters) and our own read-back:
     the new shapes, transformed back to world space, equal the recipe within 1 mm, with their materials and words.
"""
import collections
import copy
import hashlib
import json
import math
import os
import re
import struct

import numpy as np

from . import geom, decomp, surfaces, tools

KIND = 'todct-collision'
VERSION = 1
P_FRAGMENT = 9
READBACK_TOL = 1e-3          # m: world-space read-back of float32 model-space vertices


class CollisionError(ValueError):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------- recipe
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or 'collision').lower()).strip('-')[:40] or 'collision'


def new_set(label, map_key, pieces, method, source=None, host='auto', visual_only=False, set_id=None):
    s = dict(kind=KIND, version=VERSION, id=set_id or slug(label), label=label, map=map_key,
             visual_only=bool(visual_only), host=host or 'auto', source=source or {}, method=method, pieces=pieces)
    validate_set(s)
    return s


def piece_json(verts, faces, material='Stone', surface='0x02007C00', nd=6):
    return dict(verts=[[round(float(c), nd) for c in v] for v in np.asarray(verts)], faces=[list(map(int, f)) for f in faces],
                material=surfaces.material_name(surfaces.material_index(material)) if material not in (None, 255, 'none') else 'none',
                surface='0x%08X' % surfaces.parse_word(surface))


def validate_set(s):
    """Raise CollisionError for anything the writer would refuse later; returns a list of notes."""
    notes = []
    if s.get('kind') != KIND:
        raise CollisionError('not a collision set (kind %r)' % s.get('kind'))
    if int(s.get('version', 0)) > VERSION:
        raise CollisionError('collision set version %s is newer than this tool (%d)' % (s.get('version'), VERSION))
    if not s.get('map'):
        raise CollisionError('%s: no map' % s.get('id'))
    if s.get('visual_only'):
        return ['%s: visual only, no collision' % s.get('id')]
    if not s.get('pieces'):
        raise CollisionError('%s: no pieces' % s.get('id'))
    for i, p in enumerate(s['pieces']):
        V = np.asarray(p['verts'], dtype=np.float64)
        if V.ndim != 2 or V.shape[1] != 3 or len(V) < 3:
            raise CollisionError('%s piece %d: needs at least 3 vertices' % (s['id'], i))
        if len(V) > 255:
            raise CollisionError('%s piece %d: %d vertices (a TOD collision shape holds at most 255)' % (s['id'], i, len(V)))
        if not np.all(np.isfinite(V)):
            raise CollisionError('%s piece %d: non-finite coordinates' % (s['id'], i))
        ent = sum(len(f) + 1 for f in p['faces'])
        if ent > 4095:
            raise CollisionError('%s piece %d: index stream %d entries (limit 4095)' % (s['id'], i, ent))
        if any(not (0 <= k < len(V)) for f in p['faces'] for k in f):
            raise CollisionError('%s piece %d: face index out of range' % (s['id'], i))
        surfaces.material_index(p.get('material', 'Stone'))
        surfaces.parse_word(p.get('surface', surfaces.DEFAULT_WORD))
        if len(p['faces']) >= 4 and not geom.is_convex_hull_of(V, p['faces'], V, tol=1e-3):
            notes.append('%s piece %d is not convex: the game collides with its convex hull' % (s['id'], i))
    return notes


def set_stats(s):
    P = [np.asarray(p['verts']) for p in s.get('pieces') or []]
    if not P:
        return dict(pieces=0)
    A = np.concatenate(P)
    return dict(pieces=len(P), verts=int(sum(len(p) for p in P)), max_verts=int(max(len(p) for p in P)),
                min=A.min(0).round(3).tolist(), max=A.max(0).round(3).tolist())


# ---------------------------------------------------------------------------------------------- mesh -> pieces
def pieces_from_mesh(V, F, frame_pos=(0, 0, 0), frame_quat=(0, 0, 0, 1), frame_scale=(1, 1, 1), method='solid',
                     material='Stone', surface='0x02007C00', log=None, **kw):
    """V, F in the mesh's own frame (TOD axes, before scale); the frame places it in the game world:
    world = R(frame_quat) * (scale * v) + frame_pos. Decomposition runs in the scaled local frame (axis cuts follow
    the mesh), the pieces come back in world space."""
    Vs = np.asarray(V, dtype=np.float64) * np.asarray(frame_scale, dtype=np.float64)
    if np.linalg.det(np.diag(frame_scale)) < 0:
        F = [[t[0], t[2], t[1]] for t in F]
    pcs = decomp.decompose(Vs, F, method=method, log=log, **kw)
    out = []
    for p in pcs:
        W = geom.apply_trs(p['verts'], frame_pos, frame_quat)
        out.append(piece_json(W, p['faces'], material, surface))
    return out


def pieces_from_point_sets(sets, material='Stone', surface='0x02007C00'):
    """Hulls computed elsewhere (Unreal V-HACD / simple collision), already in world space."""
    return [piece_json(p['verts'], p['faces'], material, surface) for p in decomp.pieces_from_point_sets(sets)]


# ---------------------------------------------------------------------------------------------- the map's blocks
BLOCK_EXTS = ('.map', '.submap')


def map_key_of(entry):
    """'.../submap01_map09_jungle.submap' or mainmap_map09_jungle.map -> 'map09_jungle'."""
    base = entry.replace('\\', '/').split('/')[-1].lower()
    m = re.match(r'(?:mainmap|submap\d+)_(map\d+_[a-z0-9_]+?)(?:_(?:de|es|fr|it|uk))?\.(?:map|submap)$', base)
    if not m:
        raise CollisionError('%s is not a map or submap block' % entry)
    return m.group(1)


def map_entries(names, map_key):
    """Shared (language-independent) map + submap entries of a map, map block first."""
    mk = map_key.lower()
    out = [n for n in names if '/shared/' in n.lower() and n.lower().endswith(BLOCK_EXTS)
           and (n.lower().split('/')[-1].startswith('mainmap_' + mk + '.') or
                re.match(r'submap\d+_' + re.escape(mk) + r'\.submap$', n.lower().split('/')[-1]))]
    return sorted(out, key=lambda n: (not n.lower().split('/')[-1].startswith('mainmap'), n.lower()))


class Host:
    def __init__(self, name, entry, frag, node, world, sphere, hulls, record_entries):
        self.name, self.entry, self.frag, self.node, self.world = name, entry, frag, node, world
        self.sphere, self.hulls, self.record_entries = sphere, hulls, record_entries

    def json(self):
        return dict(model=self.name, placed_in=self.entry.split('/')[-1], fragment=self.frag.split('/')[-1],
                    node='0x%08X' % self.node, world_pos=[round(c, 4) for c in self.world[0]],
                    world_quat=[round(c, 6) for c in self.world[1]], sphere_centre_model=[round(c, 3) for c in self.sphere[:3]],
                    sphere_radius=round(self.sphere[3], 3), hulls=self.hulls,
                    record_in=[e.split('/')[-1] for e in self.record_entries])


class MapContext:
    """Model records and Model placements of one map's blocks (read through `read(entry) -> raw`)."""

    def __init__(self, map_key, entries, read):
        self.K = tools.load()
        self.map_key = map_key
        self.entries = list(entries)
        self.read = read
        self.raw = {e: read(e) for e in self.entries}
        self._scan()

    def _scan(self):
        K = self.K
        T = K.ft.types()
        self.models = collections.defaultdict(list)          # lower name -> [(entry, k, R, E)]
        self.placements = collections.defaultdict(list)       # lower name -> [(entry, frag, node, mult, world)]
        for e in self.entries:
            raw = self.raw[e]
            ext = os.path.splitext(e)[1]
            b = K.tb.Block(raw, ext)
            info = bytes(b.info)
            starts = K.tb.record_starts(info, b.n)
            ends = starts[1:] + [len(info)]
            for k, R in enumerate(starts):
                if K.tb.u32(info, R) == 3:
                    self.models[K.tb.record_name(info, R).lower()].append((e, k, R, ends[k]))
            frs, _ = K.ft.fragments(b)
            docs = {}
            for k, nm in frs:
                if len(b.payloads[k]) > 24:
                    try:
                        docs[k] = K.fe.FragDoc(b.payloads[k], T, nm)
                    except Exception:                 # noqa: BLE001  (unreadable fragment: no placements from it)
                        pass
            inst = collections.defaultdict(list)       # fragment basename -> [k of the fragment holding the node]
            for k, d in docs.items():
                for n, recs in d._index()[0].items():
                    r = recs.get(P_FRAGMENT)
                    if r is None:
                        continue
                    v = d.frag.value(r)
                    if v:
                        inst[v.replace('\\', '/').split('/')[-1].lower()].append(k)
            root = os.path.splitext(e.split('/')[-1])[0].lower() + '.fragment'
            names = dict(frs)
            memo = {}

            def mult(k, depth=0):
                if k in memo:
                    return memo[k]
                base = names[k].replace('\\', '/').split('/')[-1].lower()
                if depth > 12:
                    return 0
                if base == root:
                    m = 1
                else:
                    m = sum(mult(k2, depth + 1) for k2 in inst.get(base, []))
                memo[k] = m
                return m
            cache = {}
            for k, d in docs.items():
                m = mult(k)
                if m == 0:
                    continue
                owner = None
                for n in d.created_ids():
                    t = d.type_of(n) or ''
                    if not (t == 'Model' or t.endswith('(Model)')):
                        continue
                    ref = d.get(n, 'modelres')
                    if not ref:
                        continue
                    nm = ref.replace('\\', '/').lower()
                    if not nm.startswith('/data/'):
                        nm = '/data' + (nm if nm.startswith('/') else '/' + nm)
                    if owner is None:
                        owner = K.ft.owner_chain(b, frs, k, T, cache=cache)[0] if m == 1 else K.fe.IDENT
                    W = d.world(n, owner) if m == 1 else None
                    self.placements[nm].append((e, names[k], n, m, W))

    def hull_models(self):
        """Models with a HullList that the map places exactly once (and whose shipped shapes pass the model writer's
        consistency check, which model_edit.verify applies to every shape of an edited record)."""
        K = self.K
        out = []
        self.refused_hosts = {}
        for nm, recs in self.models.items():
            e, k, R, E = recs[0]
            pl = self.placements.get(nm, [])
            total = sum(p[3] for p in pl)
            if total != 1:
                continue
            m = self._decode(e, R, E)
            if not m['hulls']:
                continue
            odd = shipped_anomalies(m)
            if odd:
                self.refused_hosts[nm] = odd
                continue
            pe, pf, pn, _, W = pl[0]
            sph = struct.unpack_from('<4f', m['raw'], 0x44)
            out.append(Host(nm, pe, pf, pn, W, sph, len(m['hulls']['shapes']),
                            [r[0] for r in recs]))
        return out

    def _decode(self, e, R, E):
        K = self.K
        b = K.tb.Block(self.raw[e], os.path.splitext(e)[1])
        return K.tm.decode(bytes(b.info), R, E)

    def model_name(self, lower):
        """Original spelling of a model name."""
        recs = self.models.get(lower.lower())
        if not recs:
            return lower
        e, k, R, E = recs[0]
        b = self.K.tb.Block(self.raw[e], os.path.splitext(e)[1])
        return self.K.tb.record_name(bytes(b.info), R)

    def choose_host(self, points_world, hint='auto'):
        P = np.asarray(points_world, dtype=np.float64).reshape(-1, 3)
        cands = self.hull_models()
        if hint and hint != 'auto':
            cands = [h for h in cands if h.name == hint.lower() or h.name.endswith(hint.lower())]
            if not cands:
                raise CollisionError('host model %s is not a HullList model placed once in %s' % (hint, self.map_key))
        if not cands:
            raise CollisionError('%s has no model with a HullList placed exactly once: nowhere to put new static '
                                 'collision' % self.map_key)
        best = None
        for h in cands:
            c = np.asarray(geom.qrot(h.world[1], h.sphere[:3])) + np.asarray(h.world[0])
            need = float(np.max(np.linalg.norm(P - c, axis=1)))
            grow = max(0.0, need - h.sphere[3])
            key = (round(grow, 3), -h.sphere[3], h.name)
            if best is None or key < best[0]:
                best = (key, h, grow)
        return best[1], best[2]


def shipped_anomalies(m):
    """Shapes model_edit.verify would call inconsistent (e.g. TER_Chunk_02 of Map09 ships hull 270 with 4 face
    materials for 3 faces): such a model cannot be a host, because the writer's check covers the whole record."""
    bad = []
    regs = [P['coll'] for P in m['pivots'] if P['coll']] + ([m['hulls']] if m['hulls'] else [])
    for reg in regs:
        for j, s in enumerate(reg['shapes']):
            if s['type'] != 4:
                continue
            nv = len(s['verts'])
            if nv > 255 or s['bits'] != max(1, nv.bit_length()) or len(s['facemat']) != len(s['faces']) or                     any(i >= nv for f in s['faces'] for i in f):
                bad.append('shape %d: %d vertices, %d faces, %d face materials' % (j, nv, len(s['faces']), len(s['facemat'])))
    return bad


# ---------------------------------------------------------------------------------------------- building
def to_model_space(host, verts_world):
    """model = conj(q) * (world - pos), with the host instance's true world rotation q (project convention)."""
    K = tools.load()
    iq = K.fe.qconj(host.world[1])
    p0 = host.world[0]
    return [K.fe.qrot(iq, (v[0] - p0[0], v[1] - p0[1], v[2] - p0[2])) for v in verts_world]


def to_world(host, verts_model):
    K = tools.load()
    q, p0 = host.world[1], host.world[0]
    out = []
    for v in verts_model:
        r = K.fe.qrot(q, v)
        out.append((r[0] + p0[0], r[1] + p0[1], r[2] + p0[2]))
    return out


def plan(ctx, sets):
    """-> (jobs {host lower name: dict(host, grow, items=[(set, piece index)])}, notes, skipped)."""
    jobs, notes, skipped = collections.OrderedDict(), [], []
    for s in sets:
        validate_set(s)
        if s.get('visual_only'):
            skipped.append('%s (%s): visual only, no collision written' % (s.get('label') or s['id'], s['id']))
            continue
        if s['map'].lower() != ctx.map_key.lower():
            raise CollisionError('%s belongs to %s, not %s' % (s['id'], s['map'], ctx.map_key))
        pts = np.concatenate([np.asarray(p['verts']) for p in s['pieces']])
        host, grow = ctx.choose_host(pts, s.get('host', 'auto'))
        j = jobs.setdefault(host.name, dict(host=host, grow=0.0, items=[]))
        j['grow'] = max(j['grow'], grow)
        j['items'] += [(s, i) for i in range(len(s['pieces']))]
        notes.append('%s: %d pieces -> %s (placed in %s)%s' % (s['id'], len(s['pieces']), ctx.model_name(host.name),
                                                           host.entry.split('/')[-1],
                                                           (', sphere grows %.2f m' % grow) if grow > 0 else ''))
    return jobs, notes, skipped


def shapes_for(job):
    K = tools.load()
    host = job['host']
    out = []
    for s, i in job['items']:
        p = s['pieces'][i]
        Vm = to_model_space(host, p['verts'])
        shp = K.mw.hull_shape(Vm, [list(f) for f in p['faces']], pivot=0, surf=surfaces.parse_word(p.get('surface', surfaces.DEFAULT_WORD)),
                              facemat=surfaces.material_index(p.get('material', 'Stone')),
                              aux_name=('todct:%s:%d' % (s['id'], i))[:60])
        shp['wrapper_tail'] = bytes(24)
        out.append(shp)
    return out


def edit_record(info, R, E, job, log):
    """Decode the host record, append the pieces to its HullList, grow the sphere. -> (m_old, m_new, rec bytes)."""
    K = tools.load()
    m_old = K.tm.decode(info, R, E)
    if K.tm.encode(m_old) != info[R:E]:
        raise CollisionError('host model does not round-trip before the edit')
    m = K.tm.decode(info, R, E)
    old = m['hulls']['shapes'] if m['hulls'] else []
    added = shapes_for(job)
    w10 = m['hulls']['hdr']['w10'] if m['hulls'] else 0
    m['hulls'] = K.me.new_list('f54', old + added, w10)
    log.append('HullList %d -> %d shapes (+%d new pieces)' % (len(old), len(old) + len(added), len(added)))
    sph = K.me.cover_collision(m, log)
    rec = K.tm.encode(m)
    return m_old, m, rec, sph, len(old)


def apply_to_block(raw, entry, jobs_here):
    """Apply every job whose host record lives in this block. -> (new raw, report)."""
    K = tools.load()
    ext = os.path.splitext(entry)[1]
    rep = dict(entry=entry, base_sha256=sha(raw), base_bytes=len(raw), hosts=[])
    cur = raw
    for job in jobs_here:
        old = K.tb.Block(cur, ext)
        info = bytes(old.info)
        starts = K.tb.record_starts(info, old.n)
        ends = starts[1:] + [len(info)]
        k = K.me.find_model(info, starts, job['name'])
        R, E = starts[k], ends[k]
        log = []
        try:
            m_old, m_new, rec, sph, n_old = edit_record(info, R, E, job, log)
            nb = K.tb.Block(cur, ext)
            nb.info = bytearray(info[:R] + rec + info[E:])
            out = nb.serialize()
            ver, m2 = K.me.verify(old, out, k, rec, m_old, m_new, False)
        except K.me.Fail as e:
            raise CollisionError('%s %s: model writer check failed: %s' % (entry.split('/')[-1], job['name'], e))
        rb = readback(m2, job, n_old)
        hrep = dict(model=job['name'], record_index=k, record_bytes_old=E - R, record_bytes_new=len(rec), log=log,
                    sphere=sph, model_edit_verify=_json(ver), readback=rb, host=job['host'].json())
        if not rb['ok']:
            raise CollisionError('%s: read-back differs: %s' % (entry.split('/')[-1], rb['problems'][:3]))
        rep['hosts'].append(hrep)
        cur = out
    rep.update(out_sha256=sha(cur), bytes=len(cur), grew=len(cur) - len(raw))
    return cur, rep


def readback(m2, job, n_old):
    """The appended shapes, decoded from the written record and moved back to world space, equal the recipe."""
    shapes = m2['hulls']['shapes'][n_old:]
    probs = []
    worst = 0.0
    if len(shapes) != len(job['items']):
        probs.append('expected %d new shapes, found %d' % (len(job['items']), len(shapes)))
    for (s, i), shp in zip(job['items'], shapes):
        p = s['pieces'][i]
        W = np.asarray(to_world(job['host'], shp['verts']))
        Vr = np.asarray(p['verts'], dtype=np.float64)
        if W.shape != Vr.shape:
            probs.append('%s piece %d: %d vertices written, %d in the recipe' % (s['id'], i, len(W), len(Vr)))
            continue
        err = float(np.max(np.linalg.norm(W - Vr, axis=1)))
        worst = max(worst, err)
        if err > READBACK_TOL:
            probs.append('%s piece %d: %.4f m off' % (s['id'], i, err))
        if shp['surf'] != surfaces.parse_word(p.get('surface', surfaces.DEFAULT_WORD)):
            probs.append('%s piece %d: surface word 0x%08X' % (s['id'], i, shp['surf']))
        if set(shp['facemat']) != {surfaces.material_index(p.get('material', 'Stone'))}:
            probs.append('%s piece %d: face material %s' % (s['id'], i, sorted(set(shp['facemat']))))
        if len(shp['verts']) > 255:
            probs.append('%s piece %d: %d vertices' % (s['id'], i, len(shp['verts'])))
    return dict(ok=not probs, shapes=len(shapes), max_world_error_m=worst, problems=probs,
                shapes_detail=[len(shp['verts']) for shp in shapes])


def _json(x):
    return json.loads(json.dumps(x, default=str))


def apply_sets(ctx, sets, base_raw=None):
    """Build every collision set of this map. base_raw: {entry: raw} to build on (e.g. blocks the level editor
    already changed); other entries start from ctx.raw. -> (new raw per changed entry, report)."""
    base_raw = dict(base_raw or {})
    jobs, notes, skipped = plan(ctx, sets)
    per_entry = collections.defaultdict(list)
    for nm, j in jobs.items():
        j['name'] = ctx.model_name(nm)
        for e in j['host'].record_entries:
            per_entry[e].append(j)
    out, blocks = {}, []
    for e, js in per_entry.items():
        raw = base_raw.get(e, ctx.raw[e])
        new, rep = apply_to_block(raw, e, js)
        out[e] = new
        blocks.append(rep)
    pieces = sum(len(j['items']) for j in jobs.values())
    report = dict(result='PASS', map=ctx.map_key, sets=len(sets), pieces=pieces, notes=notes, skipped=skipped,
                  blocks=blocks, max_piece_vertices=max([len(s2['pieces'][i]['verts']) for j in jobs.values()
                                                         for s2, i in j['items']] + [0]))
    return out, report


def group_by_map(sets):
    g = collections.OrderedDict()
    for s in sets:
        g.setdefault(s['map'].lower(), []).append(s)
    return g


# ---------------------------------------------------------------------------------------------- collision layer
def layer(sets, include_visual_only=True):
    """What both editors draw: per piece world-space triangles, class colour, material, words (JSON)."""
    items = []
    for s in sets:
        for i, p in enumerate(s.get('pieces') or []):
            V = np.asarray(p['verts'], dtype=np.float64)
            tris = []
            for f in p['faces']:
                for k in range(1, len(f) - 1):
                    tris.append([f[0], f[k], f[k + 1]])
            word = surfaces.parse_word(p.get('surface', surfaces.DEFAULT_WORD))
            items.append(dict(set=s['id'], label=s.get('label'), piece=i, visual_only=bool(s.get('visual_only')),
                              verts=V.round(5).tolist(), tris=tris, material=p.get('material'),
                              surface='0x%08X' % word, cls=surfaces.surface_class(word),
                              colour=surfaces.CLASS_COLOURS['new']))
        if not s.get('pieces') and include_visual_only:
            items.append(dict(set=s['id'], label=s.get('label'), piece=-1, visual_only=True, verts=[], tris=[]))
    return dict(kind='todct-collision-layer', items=items)


def layer_glb(path, sets):
    """The new collision as a .glb in glTF axes (z negated), green, for pictures and other viewers."""
    from . import meshio
    ms = []
    for it in layer(sets)['items']:
        if not it['tris']:
            continue
        V = np.asarray(it['verts'])
        V = V * np.array([1, 1, -1])
        ms.append(dict(name='%s_%d' % (it['set'], it['piece']), verts=V, tris=[[t[0], t[2], t[1]] for t in it['tris']],
                       color=(0.1, 0.95, 0.45, 0.6)))
    return meshio.write_glb(path, ms)


# ---------------------------------------------------------------------------------------------- existing collision
def existing_layer(ctx, centre, radius, max_items=4000):
    """Level collision (HullLists of models placed once) near a point, in world space: for showing the new pieces
    against what the game already has."""
    K = ctx.K
    C = np.asarray(centre, dtype=np.float64)
    items = []
    for h in ctx.hull_models():
        e, k, R, E = ctx.models[h.name][0]
        m = ctx._decode(e, R, E)
        for j, s in enumerate(m['hulls']['shapes']):
            if s['type'] != 4:
                continue
            W = np.asarray(to_world(h, s['verts']))
            if np.min(np.linalg.norm(W - C, axis=1)) > radius:
                continue
            tris = [[f[0], f[q], f[q + 1]] for f in s['faces'] for q in range(1, len(f) - 1)]
            items.append(dict(model=h.name.split('/')[-1], shape=j, verts=W.round(4).tolist(), tris=tris,
                              cls=surfaces.surface_class(s['surf'])))
            if len(items) >= max_items:
                return items
    return items
