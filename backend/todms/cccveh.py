"""A vehicle of the PSP game as a replacement for a TOD vehicle (Assets > model replace > "From Chili Con Carnage").

todct.ccc decodes the user's own game data into a part list. This module
  analyze()        keeps the assembled vehicle in the asset store, like a model file the user opened;
  bake()           the importer's bake of the whole vehicle (textures, limits, numbers) plus the meshes sorted by the TOD part that carries them;
  replace_spec()   the TOD model's own description with its visible meshes swapped part by part: the new body goes where the old body was,
                   each wheel on the wheel part of the same name (so it spins and steers), doors, windows, lights and bumpers on their
                   same-named parts; every old mesh of a part nothing replaces is dropped. Handling, collision and every other part stay the TOD vehicle's.
"""
import copy
import os

import numpy as np

from . import assetedit, assetstore, paths


class CccVehicleError(ValueError):
    pass


def folder(settings):
    return (settings or {}).get('ccc_folder') or ''


def listing(settings):
    from todct import ccc
    f = folder(settings)
    if not f:
        return dict(set=False, vehicles=[])
    if not ccc.resolve(f):
        return dict(set=True, found=False, vehicles=[])
    return dict(set=True, found=True, vehicles=[dict(id=v['id'], name=v['name']) for v in ccc.list_vehicles(f, paths.cache_dir())])


def analyze(settings, vid):
    """Same answer as imports.analyze for a file."""
    from todct import ccc, modelimport as MI, texture as TX
    from . import imports
    f = folder(settings)
    if not ccc.resolve(f):
        raise imports.ImportError_('the game data folder is not set')
    try:
        v = ccc.read_vehicle(f, vid, paths.cache_dir())
        scene = ccc.vehicle_scene(v)
    except ccc.CccError as e:
        raise imports.ImportError_(str(e))
    sha = assetstore.put(MI.scene_to_bytes(scene))
    st = scene.stats()
    ext = np.asarray(st['max']) - np.asarray(st['min'])
    imgs = []
    for im in scene.images:
        try:
            a = TX.read_image(im['data'])
            imgs.append(dict(name=im['name'], w=int(a.shape[1]), h=int(a.shape[0]), alpha=TX.has_alpha(a), thumb=imports._b64png(a, 72)))
        except TX.TextureError as e:
            imgs.append(dict(name=im['name'], error=str(e)))
    return dict(sha=sha, file=v.name, name=v.name, stats=st, extent=[round(float(x), 4) for x in ext], images=imgs,
                materials=sorted({(p.mat.get('name') or 'material') for p in scene.parts}), suggest=dict(up='y', mirror='', origin='none', ccc=True),
                reference_m=MI.REFERENCE_FIGURE_M, textured=True, ccc=dict(vehicle=vid))


# ---------------------------------------------------------------------------------------------- the TOD vehicle
def _world(spec):
    from todct import ccc
    W = []
    for P in spec['pivots']:
        M = np.eye(4)
        M[:3, :3] = ccc.quat_matrix(P['quat'])
        M[:3, 3] = P['pos']
        W.append(W[P['parent']] @ M if P['parent'] >= 0 else M)
    return W


def _has_meshes(P):
    return bool(P['meshes'])


def _targets(spec):
    """lower-case part name -> index, for the parts that carry meshes; and the body part."""
    by = {}
    for i, P in enumerate(spec['pivots']):
        if P.get('name') and _has_meshes(P):
            by.setdefault(P['name'].lower(), i)
    body = by.get('mainbody')
    if body is None:
        vis = [i for i, P in enumerate(spec['pivots']) if any(not (me['smb_flags'] & 1) for me in P['meshes'])]
        if not vis:
            raise CccVehicleError('the model has no visible mesh to replace')
        body = vis[0]
    return by, body


FIT_LIMIT = (0.7, 1.45)          # the body may be stretched to the target's wheels by this much at most; past it the vehicle is refused


def _is_wheel(name):
    return (name or '').lower().startswith('wheel_')


def _ccc_wheels(parts):
    """lower-case part name -> (centre, radius) of the vehicle's own wheels, from their meshes (game space)."""
    g = {}
    for q in parts:
        n = (q.mat.get('pivot') or '')
        if _is_wheel(n):
            g.setdefault(n.lower(), []).append(q.P.astype(np.float64))
    out = {}
    for n, a in g.items():
        A = np.concatenate(a)
        mn, mx = A.min(0), A.max(0)
        out[n] = ((mn + mx) / 2, float((mx[1] - mn[1] + mx[2] - mn[2]) / 4))
    return out


def _target_wheels(spec, W):
    """part index -> (centre, radius or None) of the wheel parts of the vehicle being replaced (model space)."""
    k = assetedit.K()
    out = {}
    for i, P in enumerate(spec['pivots']):
        if not (_is_wheel(P.get('name')) and P['meshes']):
            continue
        pts = []
        for me in P['meshes']:
            if me['smb_flags'] & 1 or 'vertex_bytes' not in me:
                continue
            pts.append(np.asarray(k.mw.vertex_positions(me), np.float64))
        if pts:
            A = np.concatenate(pts)
            mn, mx = A.min(0), A.max(0)
            c = W[i][:3, :3] @ ((mn + mx) / 2) + W[i][:3, 3]
            out[i] = (c, float((mx[1] - mn[1] + mx[2] - mn[2]) / 4))
        else:
            out[i] = (W[i][:3, 3].copy(), None)
    return out


def _pair_wheels(own, tw, by):
    """Each wheel of the vehicle to a wheel part of the target: the same name where there is one, else by place (front to back, left to right)."""
    if len(own) != len(tw):
        raise CccVehicleError('Does not fit: %d wheels against %d' % (len(own), len(tw)))
    if all(n in by and by[n] in tw for n in own) and len({by[n] for n in own}) == len(own):
        return {n: by[n] for n in own}, []
    a = sorted(own, key=lambda n: (-round(float(own[n][0][2]), 1), float(own[n][0][0])))
    b = sorted(tw, key=lambda i: (-round(float(tw[i][0][2]), 1), float(tw[i][0][0])))
    wt = dict(zip(a, b))
    return wt, sorted(n for n in wt if not (n in by and by[n] == wt[n]))


def fit_parts(parts, spec, by, W):
    """The vehicle's parts (game space, copies) fitted to the wheels of the vehicle being replaced, so no wheel floats or sinks:
    the wheels go on the target's wheel parts (same place, the target's wheel size, the vehicle's own wheel width); the body is
    stretched to the target's track and wheelbase and set down on the target's ground. -> (parts, wheel map, info)"""
    own = _ccc_wheels(parts)
    tw = _target_wheels(spec, W)
    if not own or not tw:
        return parts, {}, None
    wt, renamed = _pair_wheels(own, tw, by)
    names = sorted(own)
    C = np.array([own[n][0] for n in names])
    T = np.array([tw[wt[n]][0] for n in names])
    rc = np.array([own[n][1] for n in names])
    rt = np.array([tw[wt[n]][1] if tw[wt[n]][1] else own[n][1] for n in names])
    kr = rt / np.maximum(rc, 1e-6)                                                  # wheel size
    ax = float(np.abs(T[:, 0]).mean() / np.abs(C[:, 0]).mean()) if np.abs(C[:, 0]).mean() > 1e-6 else 1.0
    if C[:, 2].max() - C[:, 2].min() > 1e-3:
        az, tz = np.polyfit(C[:, 2], T[:, 2], 1)
        az, tz = float(az), float(tz)
    else:
        az, tz = 1.0, float((T[:, 2] - C[:, 2]).mean())
    kmean = float(kr.mean())
    if ax <= 0 or az <= 0 or kmean <= 0:
        raise CccVehicleError('Does not fit: the wheels are not in the same order')
    ay = float((ax * az * kmean) ** (1.0 / 3.0))
    lo, hi = FIT_LIMIT
    for label, v in (('track', ax), ('wheelbase', az), ('wheel size', float(kr.min())), ('wheel size', float(kr.max()))):
        if not lo <= v <= hi:
            raise CccVehicleError('Does not fit: %s x%.2f (allowed x%.2f to x%.2f)' % (label, v, lo, hi))
    gc = float((C[:, 1] - rc).mean())                                               # ground under the vehicle's own wheels ...
    gt = float((T[:, 1] - rt).mean())                                               # ... and under the target's
    body = np.array([ax, ay, az])
    out = []
    for q in parts:
        n = (q.mat.get('pivot') or '').lower()
        q = q.copy()
        P = q.P.astype(np.float64)
        if _is_wheel(n):
            c, _ = own[n]
            t = tw[wt[n]][0]
            k = float(kr[names.index(n)])
            S = np.array([1.0, k, k])
            P = t + (P - c) * S
            if q.N is not None:
                N = q.N.astype(np.float64) / S
                q.N = (N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)).astype(np.float32)
            q.mat['origin'] = [float(x) for x in t]
        else:
            P = np.stack([P[:, 0] * ax, gt + (P[:, 1] - gc) * ay, P[:, 2] * az + tz], 1)
            if q.N is not None:
                N = q.N.astype(np.float64) / body
                q.N = (N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)).astype(np.float32)
        q.P = P.astype(np.float32)
        out.append(q)
    return out, wt, dict(track=ax, wheelbase=az, height=ay, wheel=kmean, renamed=renamed)


def bake(scene, params, old_info, ref=None, progress=None):
    """MI.bake of the whole vehicle, plus baked.by_pivot = {part index: [group]} in each TOD part's own frame."""
    from todct import modelimport as MI
    from todct import meshtex as MT
    p = MI.params_of(params)
    p['origin'] = 'none'
    p['reduce'] = 1.0
    if old_info is None:
        return MI.bake(scene, p, ref=ref, progress=progress)
    if old_info.get('skinned'):
        raise CccVehicleError('a skinned model (character) cannot be replaced')
    spec = old_info['spec']
    by, body = _targets(spec)
    W = _world(spec)
    parts = [q for q in MI.transform(scene, p, ref) if len(q.tris)]
    parts, wt, fit = fit_parts(parts, spec, by, W)
    # the fitted vehicle is in game space already: the plain bake (preview, textures, numbers) takes it as it is
    p_game = dict(p, up='y', yaw=0.0, mirror='', scale=1.0)
    from todct import ccc
    baked = MI.bake(MT.Scene(parts, scene.images, scene.source, ccc.check_vehicle(parts)), p_game, ref=ref, progress=progress)     # the checks run again on the fitted vehicle
    keys, slot = [], {}
    for q in parts:
        k = MI._slot_key(q)
        if k not in slot:
            slot[k] = len(keys)
            keys.append(k)
    acc = {}
    wheel_parts = set()
    for q in parts:
        pv = (q.mat.get('pivot') or '').lower()
        ti = wt.get(pv, by.get(pv, body)) if pv else body
        P = q.P.astype(np.float64)
        N = q.N.astype(np.float64) if q.N is not None else None
        Wi = np.linalg.inv(W[ti])
        R = Wi[:3, :3]
        if pv in wt:                                                      # a wheel turns about its own part: its mesh is centred on it
            P = (P - np.asarray(q.mat['origin'], np.float64)) @ R.T
            wheel_parts.add(ti)
        else:
            P = P @ R.T + Wi[:3, 3]
        if N is not None:
            N = N @ R.T
            N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        else:
            N = MI.MT.smooth_normals(P, q.tris)
        UV = q.UV if q.UV is not None else np.zeros((len(P), 2), np.float32)
        acc.setdefault((ti, slot[MI._slot_key(q)]), []).append((P, N, UV, q.tris))
    by_pivot = {}
    for (ti, tex), items in sorted(acc.items()):
        Ps, Ns, Us, Ts, base = [], [], [], [], 0
        for P, N, UV, T in items:
            Ps.append(P)
            Ns.append(N)
            Us.append(UV)
            Ts.append(T + base)
            base += len(P)
        P, N, UV, T = (np.concatenate(x) for x in (Ps, Ns, Us, Ts))
        T = MI._orient(P.astype(np.float32), N.astype(np.float32), T)
        for cp, cn, cu, ct in MI._chunk(P.astype(np.float32), N.astype(np.float32), UV.astype(np.float32), T):
            by_pivot.setdefault(ti, []).append(dict(tex=tex, P=cp, N=cn, UV=cu, tris=ct))
    baked.by_pivot = by_pivot
    baked.wheel_parts = sorted(wheel_parts)
    baked.wheel_pos = {}                                                   # the wheels sit on the target's own wheel parts: nothing moves
    baked.fit = fit
    if fit:
        if fit['renamed']:
            baked.warnings.append('Wheels %s have no part of that name: each went to the wheel part in its place' % ', '.join(fit['renamed']))
        off = [(l, fit[k]) for l, k in (('length', 'wheelbase'), ('width', 'track'), ('wheels', 'wheel')) if abs(fit[k] - 1.0) > 0.03]
        if off:
            baked.warnings.append('Fitted to this vehicle: ' + ', '.join('%s x%.2f' % o for o in off))
    lost = sorted({q.mat['pivot'] for q in parts if _is_wheel(q.mat.get('pivot')) and q.mat['pivot'].lower() not in wt})
    if lost:                                                       # names differ: say what was done
        baked.warnings.append('No part named %s: that wheel is joined to the body (it will not turn)' % ', '.join(lost))
    # the preview and the checks use the assembled vehicle: same groups as the plain bake
    return baked


def replace_spec(old_m, baked, new_tex_names, shapes, keep_collision):
    k = assetedit.K()
    mw = k.mw
    from todct import modelimport as MI
    info = assetedit.old_model_info(old_m)
    if info['skinned']:
        raise assetedit.AssetError('a skinned model (character) cannot be replaced')
    spec = info['spec']
    for ti, groups in baked.by_pivot.items():
        if ti >= len(spec['pivots']):
            raise assetedit.AssetError('the vehicle does not fit this model')
    W = _world(spec)
    for ti, wp in (getattr(baked, 'wheel_pos', None) or {}).items():     # the wheel parts move to where the vehicle's own wheels were
        P = spec['pivots'][ti]
        par = W[P['parent']] if P['parent'] >= 0 else np.eye(4)
        P['pos'] = tuple(float(x) for x in (np.linalg.inv(par) @ np.append(wp, 1.0))[:3])
    for i, P in enumerate(spec['pivots']):
        if not P['meshes']:
            continue
        tmpl = next((me for me in P['meshes'] if not (me['smb_flags'] & 1)), P['meshes'][0])
        far = any(me['smb_flags'] & 1 for me in P['meshes'])
        meshes = []
        for g in baked.by_pivot.get(i, []):
            me = MI.mesh_dict(mw, g, g['tex'])
            me['smb_flags'] = (tmpl['smb_flags'] & ~1 & ~0x60) | MI.ALPHA_BITS.get(baked.textures[g['tex']].get('alpha') or 'opaque', 0)
            meshes.append(me)
        if far:
            meshes = meshes + [dict(copy.deepcopy(me), smb_flags=me['smb_flags'] | 1) for me in meshes]
        P['meshes'] = meshes
    spec['textures'] = list(new_tex_names)
    spec['sphere'] = None
    for Q in spec['pivots']:
        Q['box'] = None
    spec['cover_collision'] = True
    if not keep_collision:
        for Q in spec['pivots']:
            Q['collision'] = None
        spec['hulls'] = shapes or None
    return spec


def readback(rec, baked):
    """The written record against the plan: per part, the number of vertices and triangles, and the whole vehicle's bounding box."""
    k = assetedit.K()
    m = k.tm.decode(rec, 0, len(rec))
    spec = k.mw.spec_from_model(m)
    W = _world(spec)
    nv = nt = 0
    pts = []
    for i, P in enumerate(spec['pivots']):
        meshes = [me for me in P['meshes'] if not (me['smb_flags'] & 1)]
        want = baked.by_pivot.get(i, [])
        if len(meshes) != len(want):
            raise assetedit.AssetError('read-back: part %d holds %d sub-meshes, %d planned' % (i, len(meshes), len(want)))
        for me in meshes:
            st = me['vb']['stride']
            V = np.frombuffer(me['vertex_bytes'], dtype=np.uint8).reshape(-1, st)[:, :24].copy().view('<f4').reshape(-1, 6)
            nv += len(V)
            nt += len(me['indices']) // 3
            pts.append(V[:, :3].astype(np.float64) @ W[i][:3, :3].T + W[i][:3, 3])
    exp_v = sum(len(g['P']) for gs in baked.by_pivot.values() for g in gs)
    exp_t = sum(len(g['tris']) for gs in baked.by_pivot.values() for g in gs)
    if (nv, nt) != (exp_v, exp_t):
        raise assetedit.AssetError('read-back: %d vertices and %d triangles written, %d and %d planned' % (nv, nt, exp_v, exp_t))
    A = np.concatenate(pts)
    return dict(vertices=nv, triangles=nt, bbox=[A.min(0).round(3).tolist(), A.max(0).round(3).tolist()], parts=len(baked.by_pivot))
