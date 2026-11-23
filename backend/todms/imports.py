"""Model import and the texture editor: the calls the server routes make.

Model import
  analyze(path)            read a .glb / .gltf / .obj, keep it in the asset store, report what is in it
  preview(ws, req)         bake it with the chosen settings and write a textured .glb of the result (the preview shows what is encoded);
                           also the numbers against the limits and the swap rules of a replacement
  entry(ws, req)           the `models` entry of the recipe for the project
Texture editor
  rows / info / thumb      the game's textures, with the models that use them
  upload(path)             an image of the user's, kept in the asset store
  render(ws, req)          the edited texture, encoded and decoded back (what the game will show), with the quality and the size
"""
import base64
import hashlib
import json
import os

import numpy as np

from . import assetedit, assetindex, assets_stage, assetstore, limits, paths


class ImportError_(ValueError):
    pass


def _cdir(*parts):
    d = os.path.join(paths.cache_dir(), 'assets', *parts)
    os.makedirs(d, exist_ok=True)
    return d


def _url(*parts):
    return '/cache/assets/' + '/'.join(parts)


def _h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _b64png(img, size=None):
    from todct import texture as TX
    if size and max(img.shape[:2]) > size:
        s = size / max(img.shape[:2])
        img = TX.resize(img, max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s)))
    return 'data:image/png;base64,' + base64.b64encode(TX.png_bytes(TX.checker_under(img) if TX.has_alpha(img) else img)).decode('ascii')


# ------------------------------------------------------------------------------------------------ analyze
def clean_path(path):
    """A path as people paste it: quotes (Copy as path), a file:// address, stray spaces."""
    p = str(path or '').strip().strip('"').strip("'").strip()
    if p.lower().startswith('file:///'):
        from urllib.parse import unquote
        p = unquote(p[8:])
    return os.path.expandvars(os.path.expanduser(p))


def analyze(path, progress=None):
    from todct import meshtex, modelimport as MI, texture as TX
    path = clean_path(path)
    if not os.path.isfile(path):
        raise ImportError_('that file does not exist')
    try:
        scene = meshtex.read(path)
    except meshtex.MeshTexError as e:
        raise ImportError_(str(e))
    except MemoryError:
        raise ImportError_('the file is too big to open')
    except Exception:                                          # noqa: BLE001  (never show an exception text)
        raise ImportError_('the file could not be read')
    data = MI.scene_to_bytes(scene)
    sha = assetstore.put(data)
    st = scene.stats()
    ext = np.asarray(st['max']) - np.asarray(st['min'])
    imgs = []
    for i, im in enumerate(scene.images):
        try:
            a = TX.read_image(im['data'])
            imgs.append(dict(name=im['name'], w=int(a.shape[1]), h=int(a.shape[0]), alpha=TX.has_alpha(a), thumb=_b64png(a, 72)))
        except TX.TextureError as e:
            imgs.append(dict(name=im['name'], error=str(e)))
    ext_l = os.path.splitext(path)[1].lower()
    up = 'z' if (ext_l == '.obj' and ext[2] > ext[1] * 1.25) else 'y'
    mats = sorted({(p.mat.get('name') or 'material') for p in scene.parts})
    return dict(sha=sha, file=os.path.basename(path), name=os.path.splitext(os.path.basename(path))[0], stats=st, extent=[round(float(x), 4) for x in ext],
                images=imgs, materials=mats, suggest=dict(up=up, mirror='z'), reference_m=MI.REFERENCE_FIGURE_M,
                warnings=list(getattr(scene, 'warnings', [])),
                textured=any(p.UV is not None and p.mat.get('image') is not None for p in scene.parts))


# ------------------------------------------------------------------------------------------------ preview
def _status(lid, used):
    return limits.status(lid, used)


def evaluate(baked, old_info=None):
    """The numbers of a bake against the limits (M1, P5, P6, P7, L15) as rows the screen shows."""
    from . import ledger
    st = baked.stats
    rows = [ledger._fill(ledger._row_base('M1'), st['max_mesh_vertices']),
            ledger._fill(ledger._row_base('P6'), st['largest_texture']),
            ledger._fill(ledger._row_base('P5'), st['largest_texture'])]
    cm = baked.collision
    if cm:
        nv = max(len(p['verts']) for p in cm)
        ni = max(sum(len(f) + 1 for f in p['faces']) for p in cm)
        rows.append(ledger._fill(ledger._row_base('L15'), nv))
        rows.append(ledger._fill(ledger._row_base('L15_index'), ni))
    notes = [dict(level='warn', text=w) for w in baked.warnings]
    if old_info is not None:
        for lv, t in assetedit.swap_rules(old_info, baked):
            notes.append(dict(level=lv, text=t))
    refuse = [r for r in rows if r['status'] == 'red' and limits.enforce(r['id']) == 'refuse']
    return rows, notes, refuse


def tex_summary(baked):
    return [dict(w=t['w'], h=t['h'], fmt=t['fmt'], bytes=t['payload_bytes'], psnr=t.get('psnr'), alpha=t['alpha'], source=t['source']) for t in baked.textures]


def preview(ws, req, progress=None):
    """req: {sha, params, mode: 'new'|'replace', target}. -> dict(url, stats, textures, limits, notes, original)."""
    from todct import modelimport as MI
    key = _h(dict(sha=req['sha'], params=req.get('params'), mode=req.get('mode'), target=req.get('target'),
                  game=getattr(getattr(ws, 'game', None), 'folder', None)))
    scene = MI.scene_from_bytes(assetstore.get(req['sha']))
    old_info, ref, orig = None, None, None
    if req.get('mode') == 'replace' and req.get('target'):
        m = dict(mode='replace', target=req['target'], source=dict(sha=req['sha']), params=req.get('params') or {})
        doc = assetindex.ensure(ws, progress)
        r = doc['models'].get(req['target'].lower())
        if not r:
            raise ImportError_('that model is not in the game')
        baked, old_info, ref = assets_stage.bake_model(ws, m, doc, progress)
        orig = dict(hd=bool(r.get('hd')), blocks=len(r['blocks']), textures=len(r['textures']))
        try:
            orig['mesh'] = ws.find_models([req['target'].lower()]).get(req['target'].lower())
        except Exception:                                      # noqa: BLE001
            orig['mesh'] = None
        orig['size'] = [round(float(x), 3) for x in (old_info['max'] - old_info['min'])]
        orig['min'] = [round(float(x), 3) for x in old_info['min']]
        orig['max'] = [round(float(x), 3) for x in old_info['max']]
        orig['collision'] = old_info['collision']
        orig['pivots'] = old_info['pivots']
        orig['skinned'] = old_info['skinned']
    else:
        baked = MI.bake(scene, req.get('params') or {}, progress=progress)
    fn = os.path.join(_cdir('preview'), key + '.glb')
    if not os.path.exists(fn):
        with open(fn + '.part', 'wb') as f:
            f.write(MI.preview_glb(baked))
        os.replace(fn + '.part', fn)
    rows, notes, refuse = evaluate(baked, old_info)
    return dict(url=_url('preview', key + '.glb'), key=key, stats=baked.stats, textures=tex_summary(baked), limits=rows, notes=notes,
                refused=[r['id'] for r in refuse], original=orig, collision=dict(pieces=len(baked.collision),
                                                                                  vertices=sum(len(p['verts']) for p in baked.collision)))


def model_record(url, baked_stats):
    """The record shape of workspace.model_table, for an imported model (the editor's live preview reads it)."""
    st = baked_stats
    return dict(url=url, bound=[0, (st['min'][1] + st['max'][1]) / 2, 0, max(st['size']) / 2 + 0.01], coll=0, tris=st['triangles'], hulls=0, textures={}, imported=True)


def entry(ws, req, progress=None):
    """The recipe entry for the project."""
    from todct import modelimport as MI
    pv = preview(ws, req, progress)
    mode = req.get('mode') or 'new'
    name = (req.get('name') or '').strip() or (os.path.splitext((req.get('file') or 'model'))[0])
    e = dict(id=req.get('id') or 'm' + _h([req['sha'], name, mode, req.get('target')])[:8], name=name, mode=mode,
             source=dict(sha=req['sha'], file=req.get('file')), params=MI.params_of(req.get('params')),
             stats=dict(vertices=pv['stats']['vertices'], triangles=pv['stats']['triangles'], max_mesh_vertices=pv['stats']['max_mesh_vertices'],
                        texture_bytes=pv['stats']['texture_bytes'], largest_texture=pv['stats']['largest_texture'], record_bytes=pv['stats']['record_bytes'],
                        size=pv['stats']['size'], min=pv['stats']['min'], max=pv['stats']['max'], submeshes=pv['stats']['submeshes'],
                        textures=[dict(w=t['w'], h=t['h'], fmt=t['fmt'], bytes=t['bytes']) for t in pv['textures']],
                        collision_pieces=pv['collision']['pieces']),
             view=dict(url=pv['url']))
    if mode == 'replace':
        e['target'] = req['target'].lower()
    else:
        e['path'] = assetedit.model_path(assetedit.slug_of(name))
    return dict(entry=e, preview=pv)


def imported_records(ws, models):
    """{id: record} for imported (new) models of a project: re-bakes the preview when its file is gone. `model_table` shape plus `path`."""
    out = {}
    for m in models or []:
        if m.get('mode') != 'new':
            continue
        try:
            r = preview(ws, dict(sha=m['source']['sha'], params=m.get('params'), mode='new'))
            rec = model_record(r['url'], r['stats'])
            rec['path'] = m['path'].lower()
            out[m['id']] = rec
        except Exception as e:                                 # noqa: BLE001
            out[m['id']] = dict(missing=True, reason=str(e))
    return out


# ------------------------------------------------------------------------------------------------ the texture editor
def model_rows(doc, q, limit=60):
    """Game models for the "replace" picker: search by name; thumbnails and use counts come from the model catalogue when it was built."""
    t = (q or '').lower()
    out = []
    cen = None
    AS = None
    try:
        from todct import assets as AS
        cen = (AS.Config(_cdir()).census() or {}).get('rows')
    except Exception:                                          # noqa: BLE001
        cen = None
    for ln, m in doc['models'].items():
        if t and t not in ln:
            continue
        row = dict(path=ln, name=m['name'].split('/')[-1].rsplit('.', 1)[0], blocks=len(m['blocks']), textures=len(m['textures']), hd=bool(m['hd']))
        c = cen.get(AS.stem_key(ln)) if cen else None
        if c:
            row.update(size=c.get('size'), kind=c.get('kind'), uses=sum((c.get('maps') or {}).values()))
            if os.path.exists(os.path.join(_cdir('thumbs'), AS.stem_key(ln) + '.png')):
                row['thumb'] = _url('thumbs', AS.stem_key(ln) + '.png')
        out.append(row)
    out.sort(key=lambda r: (-(r.get('uses') or 0), r['name']))
    return out[:limit]


def tex_rows(ws, q):
    doc = assetindex.load(ws)
    if doc is None:
        return dict(ready=False, rows=[], total=0)
    rs = assetindex.rows(doc, q)
    off, lim = int(q.get('offset') or 0), int(q.get('limit') or 120)
    return dict(ready=True, total=len(doc['textures']), count=len(rs), rows=rs[off:off + lim], built=doc['built'])


def tex_info(ws, name):
    from todct import texture as TX
    doc = assetindex.ensure(ws)
    r = doc['textures'].get(name.lower())
    if not r:
        raise ImportError_('that texture is not in the game')
    users = []
    for u in r['users']:
        mm = doc['models'].get(u) or {}
        users.append(dict(path=u, name=(mm.get('name') or u).split('/')[-1].rsplit('.', 1)[0], shared_with=len(mm.get('textures') or [])))
    fmt = r['fmt']
    return dict(key=name.lower(), name=r['name'], w=r['w'], h=r['h'], fmt=fmt, levels=r['levels'], size=r['size'], blocks=len(r['blocks']),
                hd=bool(r['hd']), users=users, thumb=_url('tex', tex_thumb(ws, name)),
                max_side=dict(DXT1=TX.max_dim_for_cap('DXT1'), RGBA32=TX.max_dim_for_cap('RGBA32')),
                keep_dxt1=(fmt == 'DXT1'), cap=limits.value('P6'), cap_block=limits.value('P5'))


def tex_thumb(ws, name):
    """Cached 96 px picture of the game's texture; returns the file name."""
    from todct import texture as TX
    doc = assetindex.ensure(ws)
    r = doc['textures'][name.lower()]
    fn = _h([name.lower(), r['size'], r['w'], r['h'], doc.get('game')]) + '.png'
    p = os.path.join(_cdir('tex'), fn)
    if not os.path.exists(p):
        img, _ = assets_stage.game_texture_image(ws, name, doc)
        s = 96 / max(img.shape[:2])
        if s < 1:
            img = TX.resize(img, max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s)))
        with open(p + '.part', 'wb') as f:
            f.write(TX.png_bytes(TX.checker_under(img)))
        os.replace(p + '.part', p)
    return fn


def tex_thumbs(ws, names, progress=None):
    out = {}
    doc = assetindex.ensure(ws)
    names = sorted(names, key=lambda n: (doc['textures'].get(n.lower()) or {'blocks': ['']})['blocks'][0])      # one block at a time
    for i, n in enumerate(names):
        if progress:
            progress('picture %d / %d' % (i + 1, len(names)), i, len(names))
        try:
            out[n] = _url('tex', tex_thumb(ws, n))
        except Exception:                                      # noqa: BLE001
            out[n] = None
    return out


def upload(path=None, data=None, name=None):
    """An image file of the user's -> the asset store. -> dict(sha, w, h, name, alpha, preview)."""
    from todct import texture as TX
    if data is None:
        if not path or not os.path.isfile(path):
            raise ImportError_('that file does not exist')
        with open(path, 'rb') as f:
            data = f.read()
        name = os.path.basename(path)
    else:
        data = base64.b64decode(data)
    try:
        img = TX.read_image(data)
    except TX.TextureError as e:
        raise ImportError_(str(e))
    sha = assetstore.put(data)
    return dict(sha=sha, w=int(img.shape[1]), h=int(img.shape[0]), name=name, alpha=TX.has_alpha(img), preview=_b64png(img, 160))


def tex_render(ws, req):
    """req: {target, source: {sha}|{game: true}, crop, w, h, fmt, edits}. -> the picture the game will show, and the numbers."""
    from todct import texture as TX
    t = dict(id='x', target=req['target'], source=req.get('source') or dict(game=True), crop=req.get('crop'), w=int(req['w']), h=int(req['h']),
             fmt=req['fmt'], edits=req.get('edits') or {})
    rows = []
    if not (TX.is_pow2(t['w']) and TX.is_pow2(t['h'])):
        raise ImportError_('both sides must be powers of two')
    if t['w'] > TX.MAX_DIM or t['h'] > TX.MAX_DIM:
        raise ImportError_('sides above %d are not read by the game' % TX.MAX_DIM)
    if t['fmt'] == 'DXT1' and min(t['w'], t['h']) < 4:
        raise ImportError_('DXT1 needs at least 4 pixels on each side')
    img, cut = assets_stage.render_texture(ws, t)
    payload, levels = TX.encode(img, t['fmt'], cut)
    dec = TX.decode_payload(payload, t['fmt'], t['w'], t['h'])
    size = len(payload)
    from . import ledger
    rows.append(ledger._fill(ledger._row_base('P6'), size))
    return dict(png=_b64png(dec, 512), source_png=_b64png(img, 512), psnr=TX.psnr(img, dec), bytes=size, levels=levels, w=t['w'], h=t['h'], fmt=t['fmt'],
                alpha=TX.has_alpha(dec), limits=rows, refused=size > limits.value('P5'))
