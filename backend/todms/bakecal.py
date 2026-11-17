"""Calibration of the bake against the shipped maps: bake a shipped section's own geometry and compare with the baked colours the game
ships for it. Used by the tests (the sun convention, the gains) and by anyone who wants to look at the numbers again.

    sample = shipped_sample(archive_read(entry), '.submap', K, T)       # world vertices, normals, shipped luminance, occluder triangles
    calibrate(sample, lights)                                             # {corr, mae, ...} of the bake against the shipped colours
"""
import numpy as np

from . import bake, raycast, paths
from .lightfit import hl
from . import hdblock as _hdblock

LUM = np.array([0.299, 0.587, 0.114])


def shipped_sample(raw, ext, K, T, max_vertices=None):
    """Every placed model with baked per-vertex colours of one block -> dict(P, N, lum, occ (n, 3, 3) triangles of the near-detail meshes of
    every placed model, instances). Parts other than pivot 0 are left out."""
    paths.ensure_cpu_guard()
    hl()
    import tod_hd_game as G
    HL = hl()
    blk = _hdblock.Block(raw, ext)
    recs = HL._parse_block(blk)
    models = bake.read_models(raw, ext)
    byuid = {}
    for r in blk.records:
        if r['type'] != 4:
            continue
        d = K.fe.FragDoc(blk.payloads[r['index']], T, r['name'])
        for n in d.created_ids():
            mr = d.get(n, 'modelres')
            if mr:
                byuid.setdefault((d.get(n, 'unique_id0'), d.get(n, 'unique_id1')), []).append((d, n, mr))

    def model_of(mr):
        k = mr.lower()
        return models.get(k if k.startswith('/data') else '/data' + k)

    Ps, Ns, Ls, occ = [], [], [], []
    for lst in byuid.values():
        for d, n, mr in lst:
            mod = model_of(mr)
            if mod is None or not mod['pivots'] or not mod['pivots'][0]:
                continue
            pos, quat = d.world(n)
            for me in mod['pivots'][0]:
                if len(me['I']) and not me['flags'] & 1:
                    occ.append((bake.rotate(quat, me['P']) + np.asarray(pos))[me['I'].reshape(-1, 3)])
    n_inst = 0
    for rec in recs:
        pay = blk.payloads[rec.index]
        uid_of = {v: rec.uid_keys[i] for i, v in enumerate(rec.uid_values)}
        per = {}
        for k, w in enumerate(rec.keys):
            e = rec.entries[rec.values[k]]
            if e['buffer'] is not None and ((w[0] >> 16) & 0xFFFF) == 0:
                b = e['buffer']
                per.setdefault(w[1] & 0xFFFF, {})[w[0] & 0xFFFF] = np.frombuffer(pay, '<u4', b['count'], b['data_offset'])
        for inst, meshes in per.items():
            path = uid_of.get(inst)
            nodes = byuid.get(tuple(path[-1])) if path else None
            if not nodes or len(nodes) != 1:
                continue
            d, n, mr = nodes[0]
            mod = model_of(mr)
            if mod is None or not mod['pivots']:
                continue
            pos, quat = d.world(n)
            n_inst += 1
            for j, cols in meshes.items():
                if j >= len(mod['pivots'][0]):
                    continue
                me = mod['pivots'][0][j]
                if len(me['P']) != len(cols) or me['N'] is None:
                    continue
                Ps.append(bake.rotate(quat, me['P']) + np.asarray(pos))
                Ns.append(bake.rotate(quat, me['N']))
                Ls.append(bake.from_d3dcolor(cols) @ LUM)
    P = np.concatenate(Ps) if Ps else np.zeros((0, 3))
    N = np.concatenate(Ns) if Ns else np.zeros((0, 3))
    L = np.concatenate(Ls) if Ls else np.zeros(0)
    if max_vertices and len(P) > max_vertices:
        sel = np.random.default_rng(1).choice(len(P), max_vertices, replace=False)
        P, N, L = P[sel], N[sel], L[sel]
    return dict(P=P, N=N, lum=L, occ=np.concatenate(occ) if occ else np.zeros((0, 3, 3)), instances=n_inst)


def predict(sample, tree, lights, shadows=True):
    """Luminance the bake model gives the sample's vertices (flat ambient + sun N.L, shadows optional, clamped), without sky occlusion."""
    P, N = sample['P'], sample['N']
    to_sun = -np.asarray(lights['sun_dir'], np.float64)
    ndl = np.clip(N @ to_sun, 0.0, 1.0)
    lit = np.ones(len(P))
    if shadows:
        todo = np.nonzero(ndl > 1e-4)[0]
        lit[todo] = ~tree.occluded(P[todo] + N[todo] * bake.SURFACE_EPS, np.tile(to_sun, (len(todo), 1)), bake.SHADOW_REACH, tmin=bake.SHADOW_START)
    col = bake.GAIN_AMBIENT * lights['ambient'][None, :] + (bake.GAIN_SUN * ndl * lit)[:, None] * lights['sun'][None, :]
    return np.clip(col, 0.0, 1.0) @ LUM


def calibrate(sample, lights, tree=None):
    """-> dict(vertices, corr_sun, corr_shadow, mae_sun, mae_shadow): the correlation of the model's luminance with the shipped one and the mean
    absolute difference, with the sun alone and with shadows."""
    if tree is None:
        tree = raycast.Tree(sample['occ'])
    ref = sample['lum']
    out = dict(vertices=int(len(ref)))
    for key, sh in (('sun', False), ('shadow', True)):
        p = predict(sample, tree, lights, sh)
        out['corr_' + key] = float(np.corrcoef(p, ref)[0, 1])
        out['mae_' + key] = float(np.abs(p - ref).mean())
    return out


def lights_of(block_id, axis=None, conj=True):
    """The shipped sun and ambient of a block (backend/data/look_presets.json) as bake lights; axis / conj choose another reading of the
    stored orient (for the convention test)."""
    from .mapgen import look
    b = look.data()['blocks'][block_id]['lights']
    s = next(l for l in b if l['kind'] == 'directional')
    a = next(l for l in b if l['kind'] == 'ambient')
    q = np.asarray(s['orient'], np.float64)
    q = q / np.linalg.norm(q)
    qq = (-q[0], -q[1], -q[2], q[3]) if conj else tuple(q)
    d = bake.rotate(qq, np.asarray(axis if axis is not None else bake.SUN_AXIS, np.float64))
    return dict(sun_dir=d / np.linalg.norm(d), sun=bake.colour3(s['static_color'], s['brightness']), ambient=bake.colour3(a['static_color'], a['brightness']))
