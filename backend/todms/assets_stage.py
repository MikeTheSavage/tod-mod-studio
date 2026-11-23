"""Build stage "assets": imported and replaced models, replaced and edited textures, written into the blocks that hold them.

Runs inside build.build between the level ops (stages A and B) and the collision stage:
  1. every model entry is baked once (todct.modelimport: transform, reduce, textures encoded, collision pieces);
  2. the blocks it goes into are found
       new model       the blocks of the `add` ops that place it
       replacement     every block that holds the model (the asset index), because each block carries its own copy
       texture         every block that holds the texture
  3. per block: textures patched in place, models replaced or appended, the result proven (assetedit.verify_block);
  4. baked lighting of a replaced model: the block's lighting entries are fitted to the new meshes (todms.lightfit, TOD HD's key and record
     code), for every placed instance that provably belongs to the model, shared parts included. Only a placed copy whose lighting could not
     be fitted (no lighting record, more new meshes than old ones, another model shares its lighting ...) gets statically_lit = false, and a
     note says why; a copy inside a part the game shares between blocks cannot be changed from here and keeps its old lighting (note).
"""
import os

import numpy as np

from . import assetedit, assetindex, assetstore, limits
from . import hdblock as _hdblock


class AssetsError(Exception):
    pass


def _norm(name):
    return assetindex.norm(name)


# ------------------------------------------------------------------------------------------------ level ops
def model_paths(models):
    return {_norm(m['path']): m for m in models if m.get('mode') == 'new'}


def prepare_adds(level_ops, assets):
    """Placed copies of an imported model are not statically lit (a new node has no baked lighting entry)."""
    if not assets or not assets.get('models'):
        return level_ops
    new = model_paths(assets['models'])
    out = []
    for o in level_ops:
        st = (o.get('set') or {}) if o.get('op') == 'add' else None
        if st and st.get('modelres') and _norm(st['modelres']) in new and 'statically_lit' not in st:
            o = dict(o, set=dict(st, statically_lit=False))
        out.append(o)
    return out


def hosts_of_new(level_ops, assets):
    out = {}
    new = model_paths(assets['models'])
    for o in level_ops:
        if o.get('op') != 'add':
            continue
        mr = (o.get('set') or {}).get('modelres')
        if mr and _norm(mr) in new:
            m = new[_norm(mr)]
            out.setdefault(m['id'], [])
            if o['entry'] not in out[m['id']]:
                out[m['id']].append(o['entry'])
    return out


# ------------------------------------------------------------------------------------------------ textures
_BLOCKS = {}


def _strict_block(ws, entry):
    """TOD HD's strict reader on a block, the last few kept (thumbnails of many textures read the same block)."""
    G = assetedit.hd()
    key = (entry, ws.block_key(entry))
    if key not in _BLOCKS:
        raw, _ = ws.read_block(entry)
        while len(_BLOCKS) >= 3:
            _BLOCKS.pop(next(iter(_BLOCKS)))
        _BLOCKS[key] = _hdblock.Block(raw, os.path.splitext(entry)[1])
    return _BLOCKS[key]


def game_texture_image(ws, name, doc=None):
    """The game's texture as it is now (the first block that holds it) -> float RGBA of the top mip, plus its record facts."""
    from todct import texture as TX
    G = assetedit.hd()
    doc = doc or assetindex.ensure(ws)
    r = doc['textures'].get(name.lower())
    if not r:
        raise AssetsError('texture %s is not in the game blocks' % name)
    entry = r['blocks'][0]
    blk = _strict_block(ws, entry)
    rec = next(x for x in blk.textures() if x['name'].lower() == name.lower())
    img = TX.decode_payload(blk.payloads[rec['index']], G.FMT_NAME[rec['fmt']], rec['w'], rec['h'])
    return img, dict(w=rec['w'], h=rec['h'], fmt=G.FMT_NAME[rec['fmt']], levels=rec['levels'], payload=len(blk.payloads[rec['index']]),
                     entry=entry)


def render_texture(ws, t, doc=None):
    """A texture entry of the recipe -> (float RGBA at the final size, alpha cut). Source image, crop, resize, edits; nothing else."""
    from todct import texture as TX
    src = t.get('source') or {}
    if src.get('game'):
        img, _ = game_texture_image(ws, t['target'], doc)
    else:
        img = TX.read_image(assetstore.get(src['sha']))
    if t.get('crop'):
        x, y, w, h = t['crop']
        img = TX.crop(img, x, y, w, h)
    w, h = int(t['w']), int(t['h'])
    if img.shape[:2] != (h, w):
        img = TX.resize(img, w, h)
    e = dict(t.get('edits') or {})
    if t['fmt'] == 'DXT1' and e.get('alpha') in (None, 'keep') and TX.has_alpha(img):
        e['alpha'] = 'threshold'
        e.setdefault('alpha_cut', 0.5)
    img = TX.apply_edits(img, e)
    return img, float(e.get('alpha_cut', 0.5))


# ------------------------------------------------------------------------------------------------ models
def bake_model(ws, m, doc=None, progress=None):
    """-> (baked, old_info or None, ref)."""
    from todct import modelimport as MI
    scene = MI.scene_from_bytes(assetstore.get(m['source']['sha']))
    params = dict(m.get('params') or {})
    old_info, ref = None, None
    if m['mode'] == 'replace':
        doc = doc or assetindex.ensure(ws)
        r = doc['models'].get(m['target'].lower())
        if not r:
            raise AssetsError('model %s is not in the game blocks' % m['target'])
        k = assetedit.K()
        entry = r['blocks'][0]
        raw, _ = ws.read_block(entry)
        b = k.tb.Block(raw, os.path.splitext(entry)[1])
        recs = assetedit.Records(k.tb, b)
        hit = recs.find(m['target'], 3)
        it = recs.items[hit[0]]
        old_info = assetedit.old_model_info(k.tm.decode(it['rec'], 0, len(it['rec'])))
        ref = (old_info['min'], old_info['max'])
    if params.get('ccc'):
        from . import cccveh
        baked = cccveh.bake(scene, params, old_info, ref=ref, progress=progress)
    else:
        baked = MI.bake(scene, params, ref=ref, progress=progress)
    return baked, old_info, ref


def _uid(d, node):
    try:
        return (int(d.get(node, 'unique_id0')), int(d.get(node, 'unique_id1')))
    except (KeyError, TypeError, ValueError):
        return None


def lit_ops(ws, entry, raw, target_paths, fitted=None):
    """The statically_lit = false ops for the placed copies of the replaced models whose baked lighting was NOT fitted.
    fitted: {model path: set of (unique_id0, unique_id1)} of the instances that were. -> (ops, shared, kept)"""
    from . import level as lv
    L = lv.BlockLevel(entry, raw, ws.T, ws.main_lookup)
    fitted = fitted or {}
    ops, seen, shared, kept = [], set(), 0, 0
    for i in L.instances:
        d = L.doc(i.frag)
        try:
            mr = d.get(i.node, 'modelres')
        except KeyError:
            continue
        if not mr or lv.norm_model(mr) not in target_paths:
            continue
        if _uid(d, i.node) in fitted.get(lv.norm_model(mr), ()):
            if (i.frag, i.node) not in seen:
                seen.add((i.frag, i.node))
                kept += 1
            continue
        if i.frag not in L.own_frags:
            shared += 1                                       # inside a part the game shares between blocks: cannot be changed from here
            continue
        if (i.frag, i.node) in seen:
            continue
        seen.add((i.frag, i.node))
        try:
            cur = d.get(i.node, 'statically_lit')
        except KeyError:
            cur = None
        if cur is not False:
            ops.append(dict(op='set', entry=entry, frag=i.frag, node='0x%08X' % i.node, prop='statically_lit', value=False))
    return ops, shared, kept


# ------------------------------------------------------------------------------------------------ the stage
def stage_assets(ws, assets, level_ops, outs, rep, progress=None):
    """-> the new sorted list of (entry, raw). rep gains rep['assets'] and per block `assets` records."""
    from . import build as B
    import fragtool as ft
    models, texts = assets.get('models') or [], assets.get('textures') or []
    built = dict(outs)
    arep = dict(models=[], textures=[], notes=[], blocks=[])
    rep['assets'] = arep
    need_index = any(m['mode'] == 'replace' for m in models) or bool(texts)
    doc = assetindex.ensure(ws, progress) if need_index else None
    jobs = {}                                                  # entry -> dict(t=[], m=[])

    def job(entry):
        return jobs.setdefault(entry, dict(t=[], m=[]))
    # ---- models
    placed = hosts_of_new(level_ops, assets) if models else {}
    lit_targets = {}
    for mi, m in enumerate(models):
        if progress:
            progress('model %s' % m.get('name', m['id']), mi, len(models))
        baked, old_info, ref = bake_model(ws, m, doc)
        st = baked.stats
        if st['max_mesh_vertices'] > limits.value('M1'):
            raise AssetsError('%s: a sub-mesh would hold %d vertices (limit %d)' % (m.get('name'), st['max_mesh_vertices'], limits.value('M1')))
        if m['mode'] == 'new':
            entries = placed.get(m['id'], [])
            if not entries:
                arep['notes'].append(dict(level='warn', id=m['id'], text='%s is not placed anywhere, so it is not written' % m.get('name')))
        else:
            entries = doc['models'][m['target'].lower()]['blocks']
            for lv_, text in assetedit.swap_rules(old_info, baked):
                arep['notes'].append(dict(level=lv_, id=m['id'], text='%s: %s' % (m.get('name'), text)))
            hd_blocks = doc['models'][m['target'].lower()].get('hd') or []
            if hd_blocks:
                arep['notes'].append(dict(level='warn', id=m['id'], text='%s was already replaced by another mod or TOD HD; this one goes on top' % m.get('name')))
            lit_targets.setdefault('all', set()).add(_norm(m['target']))
        slug = assetedit.slug_of(os.path.splitext(m['path'].split('/')[-1])[0] if m['mode'] == 'new' else m['id'])
        if m['mode'] == 'replace':
            slug = 'r_' + assetedit.slug_of(m['id'])
        shapes = None
        if baked.collision and (m['mode'] == 'new' or not (m.get('params') or {}).get('keep_collision', True)):
            from todct import modelimport as MI
            shapes = MI.hull_shapes(assetedit.K().mw, baked.collision, 0, os.path.basename(m.get('path') or m.get('target') or 'model'))
        for e in entries:
            job(e)['m'].append(dict(id=m['id'], name=m.get('name'), mode=m['mode'], path=m.get('path'), target=m.get('target'), slug=slug,
                                    baked=baked, shapes=shapes, keep_collision=(m.get('params') or {}).get('keep_collision', True)))
        arep['models'].append(dict(id=m['id'], name=m.get('name'), mode=m['mode'], path=m.get('path'), blocks=len(entries), vertices=st['vertices'],
                                   triangles=st['triangles'], texture_bytes=st['texture_bytes'], largest_texture=st['largest_texture'],
                                   max_mesh_vertices=st['max_mesh_vertices'], size=st['size']))
    # ---- textures
    for ti, t in enumerate(texts):
        if progress:
            progress('texture %s' % t['target'].split('/')[-1], ti, len(texts))
        r = doc['textures'].get(t['target'].lower())
        if not r:
            raise AssetsError('texture %s is not in the game blocks' % t['target'])
        img, cut = render_texture(ws, t, doc)
        users = r.get('users') or []
        mine = {_norm(m.get('target') or '') for m in models}
        others = [u for u in users if u not in mine]
        if others:
            arep['notes'].append(dict(level='warn', id=t['id'], text='%s is also used by %d other model%s' % (
                t['target'].split('/')[-1], len(others), '' if len(others) == 1 else 's')))
        if r.get('hd'):
            arep['notes'].append(dict(level='warn', id=t['id'], text='%s was already replaced by another mod or TOD HD; its extra shading data will not match' % t['target'].split('/')[-1]))
        pay = None
        for e in r['blocks']:
            job(e)['t'].append(dict(id=t['id'], name=t['target'], fmt=t['fmt'], w=int(t['w']), h=int(t['h']), img=img, alpha_cut=cut))
        from todct import texture as TX
        arep['textures'].append(dict(id=t['id'], name=t['target'], fmt=t['fmt'], w=int(t['w']), h=int(t['h']), blocks=len(r['blocks']),
                                     payload=TX.payload_size(t['fmt'], int(t['w']), int(t['h']), TX.full_chain(int(t['w']), int(t['h']))),
                                     users=len(users)))
    # ---- blocks
    T = ws.T
    for bi, (entry, j) in enumerate(sorted(jobs.items())):
        if progress:
            progress('writing %s' % entry.split('/')[-1], bi, len(jobs))
        raw = built[entry] if entry in built else ws.read_block(entry)[0]
        ext = os.path.splitext(entry)[1]
        base, src = ws.read_block(entry)
        try:
            new, brep = assetedit.apply_block(ws, entry, raw, j['t'], j['m'])
        except assetedit.AssetError as e:
            raise AssetsError(str(e))
        lit = []
        targets = {_norm(x['target']) for x in j['m'] if x['mode'] == 'replace'}
        fitted, kept = {}, 0
        for lr in brep.get('lighting') or []:
            if lr['status'] == 'retargeted':
                fitted.setdefault(_norm(lr['model']), set()).update(tuple(u) for u in lr['uids'])
            if lr['status'] in ('fallback', 'retargeted'):
                why = lr.get('reason') or (lr['fallback'][0]['reason'] if lr['fallback'] else '')
                if why:
                    arep['notes'].append(dict(level='warn', id=None, text='%s: %s: baked lighting not fitted for %d placed instance(s) (%s)' % (
                        entry.split('/')[-1], lr['model'].split('/')[-1], max(len(lr['fallback']), 1), why)))
        if targets:
            ops, shared, kept = lit_ops(ws, entry, new, targets, fitted)
            if shared:
                arep['notes'].append(dict(level='warn', id=None, text='%s: %d placed copies sit inside shared parts and keep their old baked lighting (they may look dark)' % (
                    entry.split('/')[-1], shared)))
            if ops:
                tmp = dict(save_safe=True)
                try:
                    new = B.stage_a(entry, new, ops, T, tmp)
                except B.BuildError as e:
                    arep['notes'].append(dict(level='warn', id=None, text='%s: the lighting flag could not be set on %d placed copies (%s)' % (
                        entry.split('/')[-1], len(ops), e)))
                    ops = []
                lit = ops
        r1 = ft.roundtrip_block(new, ext, T)
        if r1['fail'] or not r1['block_identical']:
            raise AssetsError('%s: the block with the new assets does not round-trip' % entry.split('/')[-1])
        brep['lit_unset'] = len(lit)
        brep['lit_kept'] = kept
        blk = next((b for b in rep['blocks'] if b['entry'] == entry), None)
        if blk is None:
            blk = dict(entry=entry, base_archive=src, base_sha256=B.sha(base), base_bytes=len(base), save_safe=True)
            rep['blocks'].append(blk)
        blk.update(out_sha256=B.sha(new), bytes=len(new), assets=brep,
                   roundtrip=dict(fragments=r1['fragments'], records=r1['records'], identical=r1['block_identical']))
        built[entry] = new
        arep['blocks'].append(dict(entry=entry, models=[m['id'] for m in j['m']], textures=[t['id'] for t in j['t']],
                                   verify=brep['verify'], bytes=[len(base), len(new)], lit_unset=len(lit), lit_kept=kept, lighting=brep['verify'].get('lighting')))
    return sorted(built.items())
