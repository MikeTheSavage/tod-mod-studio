"""Block surgery for imported and replaced models and replaced textures.

A block is a list of records (INFO slices + payloads). This module
  * patches TEXTURE records in place (TOD HD's strict texture rewrite: same record, new format / size / payload),
  * appends new TEXTURE and MODEL records at the end (the proven way new-map models enter a block),
  * replaces one MODEL record by another built from the importer's geometry,
and then proves the result: every record that was not meant to change is byte-identical (INFO slice and payload), the appended
records are exactly the intended ones, maximumAssetSize equals the largest payload, TOD HD's strict reader parses the block and
every written model decodes and re-encodes to the same bytes.
"""
import hashlib
import os
import struct
import sys

import numpy as np

from . import lightfit, paths
from . import hdblock as _hdblock

SENTINEL = 0xBAADF00D


class AssetError(Exception):
    pass


def hd():
    p = os.path.join(paths.BACKEND, 'vendor', 'hd')
    if p not in sys.path:
        sys.path.append(p)
    import tod_hd_game
    return tod_hd_game


def K():
    from todct import tools
    return tools.load()


def a16(x):
    return (x + 15) & ~15


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------------------------------------ names
def slug_of(text):
    import re
    s = re.sub(r'[^a-z0-9]+', '_', (text or 'model').lower()).strip('_')[:40] or 'model'
    return s


def model_path(slug):
    return '/data/models/todms/%s/%s.model' % (slug, slug)


def texture_name(slug, i):
    return '/data/models/todms/%s/%s_%d.bmp' % (slug, slug, i)


# ------------------------------------------------------------------------------------------------ records
class Records:
    """INFO of a block split into records (16-aligned slices) with their payloads, editable (see vendor/newmap/newgeo.py)."""

    def __init__(self, tb, block):
        from .assetindex import fast_starts
        info = bytes(block.info)
        st = fast_starts(info, block.n)
        if len(st) != block.n:
            st = tb.record_starts(info, block.n)
        en = st[1:] + [len(info)]
        self.items = []
        for k, (R, E) in enumerate(zip(st, en)):
            self.items.append(dict(type=tb.u32(info, R), name=tb.record_name(info, R), rec=info[R:E], payload=block.payloads[k]))

    def find(self, name, typ=None):
        low = name.lower()
        hits = [i for i, it in enumerate(self.items) if it['name'].lower() == low and (typ is None or it['type'] == typ)]
        return hits

    def write_into(self, block):
        block.info = bytearray(b''.join(i['rec'] for i in self.items))
        block.payloads = [i['payload'] for i in self.items]
        block.n = len(self.items)


_TPL = {}


def texture_templates(ws):
    """One shipped DXT1 and one RGBA32 record (bytes) to copy the record layout from (from overdose.main)."""
    key = getattr(ws.game, 'folder', '')
    if key in _TPL:
        return _TPL[key]
    k = K()
    sys.path.insert(0, os.path.join(paths.BACKEND, 'vendor', 'newmap'))
    paths.ensure_cpu_guard()
    import tex_gen as TXG
    from . import game
    out = None
    for e in [game.MAIN_ENTRY] + sorted(n for n in ws.game.base().names if n.lower().endswith('.mission'))[:6]:
        raw, _ = ws.read_block(e)
        b = k.tb.Block(raw, os.path.splitext(e)[1])
        info = bytes(b.info)
        st = k.tb.record_starts(info, b.n)
        try:
            out = TXG.find_templates(info, st, len(st))
            break
        except ValueError:
            continue
    if out is None:
        raise AssetError('no shipped texture record to copy the layout from')
    _TPL[key] = out
    return out


def texture_record(name, w, h, fmt, levels, tmpl):
    sys.path.insert(0, os.path.join(paths.BACKEND, 'vendor', 'newmap'))
    import tex_gen as TXG
    rec = TXG.texture_record(name, w, h, fmt, levels, tmpl[fmt])
    return rec + bytes(a16(len(rec)) - len(rec))


# ------------------------------------------------------------------------------------------------ the model spec
def pivot_matrix_ok(P):
    q = P['quat']
    return abs(abs(q[3]) - 1.0) < 1e-5 and P['parent'] == -1


def old_model_info(m):
    """Facts about a decoded model record the importer needs: skinned?, mesh pivots, bbox in model space, LOD0 mesh count."""
    k = K()
    spec = k.mw.spec_from_model(m)
    skinned = any(me['kind'] == 'skin' for P in spec['pivots'] for me in P['meshes'])
    PW = k.mw.pivot_world(spec['pivots'])
    pts = []
    for i, P in enumerate(spec['pivots']):
        for me in P['meshes']:
            if me['smb_flags'] & 1:
                continue
            V = k.mw.vertex_positions(me)
            if V:
                A = np.asarray(V, dtype=np.float64)
                pts.append(np.asarray([k.mw.apply(PW[i], tuple(v)) for v in A[::max(1, len(A) // 600)]]))
    if pts:
        A = np.concatenate(pts)
        mn, mx = A.min(0), A.max(0)
    else:
        mn = mx = np.zeros(3)
    mp = [i for i, P in enumerate(spec['pivots']) if any(not (me['smb_flags'] & 1) for me in P['meshes'])]
    lod0 = sum(1 for P in spec['pivots'] for me in P['meshes'] if not (me['smb_flags'] & 1))
    return dict(spec=spec, skinned=skinned, mesh_pivots=mp, min=mn, max=mx, lod0=lod0, pivots=len(spec['pivots']),
                collision='hulls' if m['hulls'] else ('pivot' if any(P['coll'] for P in m['pivots']) else 'none'),
                names=[P['name'] for P in spec['pivots']])


def new_spec(baked, name, tex_names, shapes):
    k = K()
    mw = k.mw
    from todct import modelimport as MI
    meshes = [MI.mesh_dict(mw, g, g['tex'], baked.textures[g['tex']].get('alpha')) for g in baked.groups]
    return dict(name=name, textures=list(tex_names),
                pivots=[dict(name=None, name2=None, pos=(0.0, 0.0, 0.0), quat=(0.0, 0.0, 0.0, 1.0), parent=-1, w5c=-1, w60=1, box=None,
                             meshes=meshes, collision=None, v34=[], v48=[])],
                hulls=shapes or None, x40=None, sphere=None, cover_collision=True)


def replace_spec(old_m, baked, new_tex_names, shapes, keep_collision):
    """The old model's description with the visible meshes of its first mesh pivot swapped (other pivots, names, collision kept)."""
    k = K()
    mw = k.mw
    from todct import modelimport as MI
    info = old_model_info(old_m)
    if info['skinned']:
        raise AssetError('a skinned model (character) cannot be replaced')
    if not info['mesh_pivots']:
        raise AssetError('the model has no visible mesh to replace')
    spec = info['spec']
    pi = info['mesh_pivots'][0]
    P = spec['pivots'][pi]
    if not pivot_matrix_ok(P):
        raise AssetError('the part that carries the mesh is turned or hangs under another part: replace this model another way')
    off = np.asarray(P['pos'], dtype=np.float64)            # a part that is only moved: the mesh is written relative to it
    keep_old = sorted({t for j, Q in enumerate(spec['pivots']) if j != pi for me in Q['meshes'] for t in me['texrefs']})
    remap = {o: n for n, o in enumerate(keep_old)}
    for j, Q in enumerate(spec['pivots']):
        if j != pi:
            for me in Q['meshes']:
                me['texrefs'] = [remap[t] for t in me['texrefs']]
    base = len(keep_old)
    tmpl = next((me for me in P['meshes'] if not (me['smb_flags'] & 1)), P['meshes'][0])
    meshes = []
    for g in baked.groups:
        me = MI.mesh_dict(mw, dict(g, P=(g['P'].astype(np.float64) - off).astype(np.float32)), base + g['tex'])
        me['smb_flags'] = (tmpl['smb_flags'] & ~1 & ~0x60) | MI.ALPHA_BITS.get(baked.textures[g['tex']].get('alpha') or 'opaque', 0)
        meshes.append(me)
    if any(me['smb_flags'] & 1 for me in P['meshes']):          # the model has a far-detail copy of its meshes: keep that structure
        import copy
        far = []
        for me in meshes:
            c = copy.deepcopy(me)
            c['smb_flags'] = me['smb_flags'] | 1
            far.append(c)
        meshes = meshes + far
    P['meshes'] = meshes
    spec['textures'] = [spec['textures'][i] for i in keep_old] + list(new_tex_names)
    spec['sphere'] = None
    for Q in spec['pivots']:
        Q['box'] = None
    spec['cover_collision'] = True
    if not keep_collision:
        for Q in spec['pivots']:
            Q['collision'] = None
        spec['hulls'] = shapes or None
    return spec


def readback(rec, baked, pivot, offset=None):
    """Decode the written record and compare its render meshes of `pivot` with what was baked: vertex and triangle counts, bounding box,
    texture references, every triangle wound against its normals. Raises AssetError. -> facts."""
    k = K()
    m = k.tm.decode(rec, 0, len(rec))
    spec = k.mw.spec_from_model(m)
    P = spec['pivots'][pivot]
    meshes = [me for me in P['meshes'] if not (me['smb_flags'] & 1)]
    nv = sum(len(me['vertex_bytes']) // me['vb']['stride'] for me in meshes)
    nt = sum(len(me['indices']) // 3 for me in meshes)
    if me_count(meshes) != len(baked.groups):
        raise AssetError('read-back: %d sub-meshes written, %d planned' % (me_count(meshes), len(baked.groups)))
    if nv != baked.stats['vertices'] or nt != baked.stats['triangles']:
        raise AssetError('read-back: %d vertices and %d triangles written, %d and %d planned' % (nv, nt, baked.stats['vertices'], baked.stats['triangles']))
    pts, bad = [], 0
    for me in meshes:
        st = me['vb']['stride']
        vb = me['vertex_bytes']
        V = np.frombuffer(vb, dtype=np.uint8).reshape(-1, st)[:, :24].copy().view('<f4').reshape(-1, 6)
        pts.append(V[:, :3])
        idx = np.asarray(me['indices'], np.int64).reshape(-1, 3)
        a, b, c = V[idx[:, 0], :3], V[idx[:, 1], :3], V[idx[:, 2], :3]
        n = np.cross(b - a, c - a)
        vn = V[idx[:, 0], 3:] + V[idx[:, 1], 3:] + V[idx[:, 2], 3:]
        bad += int(((n * vn).sum(1) > 1e-9).sum())
        ln = np.linalg.norm(V[:, 3:], axis=1)
        if np.abs(ln - 1).max() > 1e-3:
            raise AssetError('read-back: a normal is not a unit vector')
    A = np.concatenate(pts)
    if offset is not None:
        A = A + np.asarray(offset, dtype=np.float64)
    mn, mx = A.min(0), A.max(0)
    err = max(float(np.abs(mn - np.asarray(baked.stats['min'])).max()), float(np.abs(mx - np.asarray(baked.stats['max'])).max()))
    if err > 1e-3:
        raise AssetError('read-back: the written mesh is %.4f m off the planned one' % err)
    if bad:
        raise AssetError('read-back: %d triangles are wound with their normals (inside out)' % bad)
    return dict(vertices=nv, triangles=nt, bbox_error_m=round(err, 6), inside_out=0)


def me_count(meshes):
    return len(meshes)


def swap_rules(old_info, baked):
    """The M6 swap rules for a replacement -> list of (level, text). Warnings, never refusals (only M1/M2 refuse, in the importer)."""
    out = []
    if len(old_info['mesh_pivots']) > 1:
        out.append(('warn', 'The model has %d parts with meshes: only the first is replaced, the rest keep their old meshes' % len(old_info['mesh_pivots'])))
    if baked.stats['submeshes'] != old_info['lod0']:
        out.append(('warn', 'Sub-mesh count %d differs from the original %d' % (baked.stats['submeshes'], old_info['lod0'])))
    omn, omx = old_info['min'], old_info['max']
    nmn, nmx = np.asarray(baked.stats['min']), np.asarray(baked.stats['max'])
    oext, next_ = omx - omn, nmx - nmn
    big = [a for a in range(3) if oext[a] > 1e-6 and next_[a] > oext[a] * 1.10 + 1e-6]
    if big:
        out.append(('warn', 'Bigger than the original by more than 10 %% (%s)' % ', '.join('xyz'[a] for a in big)))
    if nmn[1] < omn[1] - 0.30:
        out.append(('warn', 'Reaches %.2f m below the original lowest point (limit 0.30 m)' % (omn[1] - nmn[1])))
    return out


# ------------------------------------------------------------------------------------------------ one block
def _encode_tree(tree):
    k = K()
    rec = k.tm.encode(tree)
    return rec + bytes(a16(len(rec)) - len(rec))


def apply_block(ws, entry, raw, tjobs, mjobs):
    """tjobs: [dict(id, name, fmt, w, h, img (float RGBA, final size), alpha_cut)]; mjobs: [dict(id, mode, path|target, slug, baked, shapes, keep_collision, name)].
    -> (new raw, report)."""
    k = K()
    G = hd()
    ext = os.path.splitext(entry)[1]
    rep = dict(entry=entry, textures=[], models=[], base_bytes=len(raw), base_sha256=sha(raw))
    cur = raw
    pre_light = None
    # ---- 1. texture replacement in place (TOD HD's verified rewrite)
    if tjobs:
        from todct import texture as TX
        blk = _hdblock.Block(cur, ext)
        index = {r['name'].lower(): r for r in blk.textures()}
        repl, enc = {}, {}
        for j in tjobs:
            r = index.get(j['name'].lower())
            if r is None:
                raise AssetError('%s: texture %s is not in this block' % (entry.split('/')[-1], j['name']))
            mips = r['mip_mode'] == 1
            key = (j['id'], mips)
            if key not in enc:
                enc[key] = TX.encode(j['img'], j['fmt'], j.get('alpha_cut', 0.5), mips=mips)
            payload, levels = enc[key]
            repl[r['index']] = (j['fmt'], j['w'], j['h'], levels, payload)
            rep['textures'].append(dict(name=r['name'], old=dict(fmt=G.FMT_NAME[r['fmt']], w=r['w'], h=r['h'], payload=blk.sizes[r['index']]),
                                        new=dict(fmt=j['fmt'], w=j['w'], h=j['h'], payload=len(payload)), id=j.get('id')))
        try:
            cur, _ = G.rewrite_block(cur, ext, repl)
        except G.GameDataError as e:
            raise AssetError('%s: %s' % (entry.split('/')[-1], e))
    # ---- 2. models
    if mjobs:
        tpl = texture_templates(ws)
        b = k.tb.Block(cur, ext)
        recs = Records(k.tb, b)
        before = len(recs.items)
        changed = set()
        cur0, swapped = cur, []
        for j in mjobs:
            baked = j['baked']
            names = []
            for i, t in enumerate(baked.textures):
                nm = texture_name(j['slug'], i)
                if recs.find(nm):
                    raise AssetError('%s: %s already exists in the block' % (entry.split('/')[-1], nm))
                names.append(nm)
                recs.items.append(dict(type=0, name=nm, rec=texture_record(nm, t['w'], t['h'], t['fmt'], t['levels'], tpl),
                                       payload=t['payload']))
            if j['mode'] == 'new':
                full = model_path(j['slug'])
                if recs.find(full):
                    raise AssetError('%s: %s already exists in the block' % (entry.split('/')[-1], full))
                spec = new_spec(baked, full, names, j.get('shapes'))
                tree = k.mw.build_tree(spec, derive=True)
                rec = _encode_tree(tree)
                rb = readback(rec, baked, 0)
                recs.items.append(dict(type=3, name=full, rec=rec, payload=b''))
                rep['models'].append(dict(id=j['id'], mode='new', name=full, record_bytes=len(rec), readback=rb, vertices=baked.stats['vertices'],
                                          triangles=baked.stats['triangles'], textures=[dict(name=n, w=t['w'], h=t['h'], fmt=t['fmt'],
                                                                                          payload=len(t['payload'])) for n, t in zip(names, baked.textures)]))
            else:
                hits = recs.find(j['target'], 3)
                if len(hits) != 1:
                    raise AssetError('%s: model %s found %d times' % (entry.split('/')[-1], j['target'], len(hits)))
                it = recs.items[hits[0]]
                m_old = k.tm.decode(it['rec'], 0, len(it['rec']))
                if k.tm.encode(m_old) != it['rec'][:len(k.tm.encode(m_old))]:
                    raise AssetError('%s does not round-trip before the edit' % j['target'])
                m_old = k.tm.decode(it['rec'], 0, len(it['rec']))
                spec = replace_spec(m_old, baked, names, j.get('shapes'), j.get('keep_collision', True))
                tree = k.mw.build_tree(spec, derive=True)
                rec = _encode_tree(tree)
                oi = old_model_info(m_old)
                rb = readback(rec, baked, oi['mesh_pivots'][0], oi['spec']['pivots'][oi['mesh_pivots'][0]]['pos'])
                rep['models'].append(dict(id=j['id'], mode='replace', name=it['name'], record_bytes=len(rec), old_record_bytes=len(it['rec']), readback=rb,
                                          vertices=baked.stats['vertices'], triangles=baked.stats['triangles'],
                                          textures=[dict(name=n, w=t['w'], h=t['h'], fmt=t['fmt'], payload=len(t['payload']))
                                                    for n, t in zip(names, baked.textures)]))
                it['rec'] = rec
                changed.add(hits[0])
                swapped.append((it['name'], oi['mesh_pivots'][0]))
        recs.write_into(b)
        cur = b.serialize()
        # lighting phase 2: the baked lighting of the replaced models is fitted to their new meshes (each model on its own; a model that
        # cannot be fitted stays as it was and is reported, the stage then unlights its placed copies)
        rep['lighting'] = []
        pre_light = cur
        for name, pivot in swapped:
            try:
                HL = lightfit.hl()
                new, lr = lightfit.retarget_model(cur, ext, name, pivot, lightfit.model_geometry(HL, cur0, ext, name), lightfit.model_geometry(HL, cur, ext, name))
            except Exception as ex:                      # a block this reader does not understand: nothing is rewritten
                new, lr = cur, dict(model=name, status='fallback', reason='its lighting could not be read (%s)' % ex, instances=[], uids=[], fallback=[],
                                    records=[], patches=[], growth=0, regenerated=0, pivot=pivot)
            cur = new
            rep['lighting'].append(lr)
        rep['appended'] = len(recs.items) - before
        rep['changed_records'] = sorted(changed)
    rep.update(out_bytes=len(cur), out_sha256=sha(cur))
    rep['verify'] = verify_block(raw, cur, ext, rep, pre_light)
    return cur, rep


# ------------------------------------------------------------------------------------------------ proof
def verify_block(base_raw, new_raw, ext, rep, pre_light=None):
    """Every record that was not meant to change is byte-identical; the appended and changed records are the intended ones; the block is
    well formed (strict TOD HD reader, maximumAssetSize, every written model round-trips). Retargeted lighting is proven on its own against
    pre_light, the block just before the retarget: other records identical, counts of every retargeted key, strict read-back. Raises AssetError."""
    k = K()
    G = hd()
    a, b = k.tb.Block(base_raw, ext), k.tb.Block(new_raw, ext)
    if (a.timestamp, a.prop_ck, a.cmd_ck, a.prefix) != (b.timestamp, b.prop_ck, b.cmd_ck, b.prefix):
        raise AssetError('block header changed')
    ra, rb = Records(k.tb, a), Records(k.tb, b)
    names_changed = {t['name'].lower() for t in rep.get('textures', [])} | {m['name'].lower() for m in rep.get('models', []) if m['mode'] == 'replace'}
    names_changed |= {n.lower() for r in rep.get('lighting', []) if r['status'] == 'retargeted' for n in r['records']}      # the retargeted lighting records
    same = 0
    for i, x in enumerate(ra.items):
        y = rb.items[i]
        if x['name'].lower() in names_changed:
            if y['name'] != x['name'] or y['type'] != x['type']:
                raise AssetError('record %d (%s) changed identity' % (i, x['name']))
            continue
        if x['rec'] != y['rec'] or x['payload'] != y['payload'] or x['name'] != y['name']:
            raise AssetError('untouched record %d (%s) changed' % (i, x['name']))
        same += 1
    new_names = [it['name'] for it in rb.items[len(ra.items):]]
    want = [t['name'] for m in rep.get('models', []) for t in m['textures']] + [m['name'] for m in rep.get('models', []) if m['mode'] == 'new']
    if sorted(n.lower() for n in new_names) != sorted(n.lower() for n in want):
        raise AssetError('appended records differ from the plan: %s vs %s' % (new_names[:4], want[:4]))
    chk = _hdblock.Block(new_raw, ext)                                   # strict: record scan, texture payload = engine size rule, M == max(sizes)
    nmod = 0
    for it in rb.items:
        if it['type'] == 3 and (it['name'].lower() in names_changed or it['name'] in new_names):
            m = k.tm.decode(it['rec'], 0, len(it['rec']))
            if k.tm.encode(m) != it['rec'][:len(k.tm.encode(m))]:
                raise AssetError('model %s does not re-encode identically' % it['name'])
            nmod += 1
    if chk.max_asset > G.LOAD_BUFFER_CAP and chk.max_asset > a.max_asset:
        raise AssetError('maximumAssetSize %d is over the proven load buffer (%d)' % (chk.max_asset, G.LOAD_BUFFER_CAP))
    light = None
    if any(r['status'] == 'retargeted' for r in rep.get('lighting', [])):
        try:
            light = lightfit.verify(pre_light, new_raw, ext, rep['lighting'])
        except (lightfit.LightError, G.GameDataError) as e:
            raise AssetError('baked lighting: %s' % e)
    return dict(result='PASS', records_before=len(ra.items), records_after=len(rb.items), untouched_identical=same,
                changed=len(names_changed), appended=len(new_names), models_roundtrip=nmod, max_asset=chk.max_asset,
                info_bytes=[len(a.info), len(b.info)], lighting=light)
