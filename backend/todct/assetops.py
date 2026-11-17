"""Recipe version 4: the `models` and `textures` lists of a .todmod.

  models   one entry per imported or replaced model
             {id, name, mode: 'new' | 'replace',
              path   (new: the game path the model gets, /data/models/todms/<slug>/<slug>.model)
              target (replace: the game model it takes over, lower case /data/... .model)
              source {sha, file}      the scene blob (todct.modelimport.scene_to_bytes) in the asset store
              params {...}            todct.modelimport.DEFAULTS keys: up, mirror, yaw, scale, origin, reduce, max_tex, tex_format,
                                      double_sided, collision {mode, material, max_pieces}, keep_collision, textures {slot: {fmt, max}}
              stats  {...}            numbers measured at import (vertices, triangles, texture bytes ...): the live meters read them
              view   {...}            what the editor shows (preview url, picture)}
  textures one entry per replaced or edited game texture
             {id, target (lower case /data/... .bmp name),
              source {sha, file} | {game: true}     an image in the asset store, or the game's own texture as it is now
              crop [x, y, w, h] | null, w, h (final power-of-two size), fmt 'DXT1' | 'RGBA32',
              edits {hue, brightness, contrast, saturation, tint, tint_amount, alpha, alpha_cut}}

The entries hold no game data and no big arrays: the files they point at live in the asset store (todms/assetstore.py) and travel
inside an exported .todmod.
"""
import re

from . import texture as TX

MODES = ('new', 'replace')
MAX_VERTS = 65535            # M1
HEX = re.compile(r'^[0-9a-f]{16,64}$')


class AssetOpError(ValueError):
    pass


def _need(cond, text):
    if not cond:
        raise AssetOpError(text)


def validate_models(models):
    seen = set()
    for i, m in enumerate(models or []):
        w = 'model %d' % i
        _need(isinstance(m, dict), w + ': not an object')
        _need(m.get('id') and m['id'] not in seen, w + ': needs a unique id')
        seen.add(m['id'])
        _need(m.get('mode') in MODES, w + ': mode must be new or replace')
        if m['mode'] == 'new':
            _need(str(m.get('path', '')).lower().startswith('/data/') and str(m['path']).lower().endswith('.model'), w + ': needs a /data/....model path')
            _need(len(m['path']) <= 256, w + ': path longer than 256 characters (M9)')
        else:
            _need(str(m.get('target', '')).lower().startswith('/data/') and str(m['target']).lower().endswith('.model'), w + ': needs a target model')
        src = m.get('source') or {}
        _need(HEX.match(str(src.get('sha', ''))), w + ': the source file is missing')
        p = m.get('params') or {}
        _need(float(p.get('scale', 1.0)) > 0, w + ': scale must be above zero')
        _need(0 < float(p.get('reduce', 1.0)) <= 1.0, w + ': reduce is a fraction above zero up to 1')
        st = m.get('stats') or {}
        if st.get('max_mesh_vertices', 0) > MAX_VERTS:
            raise AssetOpError('%s: a sub-mesh would hold %d vertices; the engine reads 16-bit indices (at most %d)' % (w, st['max_mesh_vertices'], MAX_VERTS))
    return []


def validate_textures(texts):
    seen = set()
    for i, t in enumerate(texts or []):
        w = 'texture %d' % i
        _need(isinstance(t, dict), w + ': not an object')
        _need(t.get('id') and t['id'] not in seen, w + ': needs a unique id')
        seen.add(t['id'])
        _need(str(t.get('target', '')).lower().startswith('/data/'), w + ': needs the game texture name')
        src = t.get('source') or {}
        _need(src.get('game') or HEX.match(str(src.get('sha', ''))), w + ': the image is missing')
        _need(t.get('fmt') in TX.FMT, w + ': format must be DXT1 or RGBA32')
        tw, th = int(t.get('w', 0)), int(t.get('h', 0))
        _need(TX.is_pow2(tw) and TX.is_pow2(th), w + ': sides must be powers of two (%dx%d)' % (tw, th))
        _need(max(tw, th) <= TX.MAX_DIM, w + ': sides above %d' % TX.MAX_DIM)
        if t['fmt'] == 'DXT1':
            _need(min(tw, th) >= 4, w + ': DXT1 needs at least 4 pixels on each side')
        _need(TX.payload_size(t['fmt'], tw, th, TX.full_chain(tw, th)) <= TX.LOAD_BUFFER_CAP,
              w + ': %dx%d %s is over the %d byte load buffer' % (tw, th, t['fmt'], TX.LOAD_BUFFER_CAP))
        if t.get('crop') is not None:
            _need(len(t['crop']) == 4, w + ': crop is [x, y, w, h]')
    return []


def blob_shas(models, texts):
    out = set()
    for m in models or []:
        out.add(m['source']['sha'])
    for t in texts or []:
        s = (t.get('source') or {}).get('sha')
        if s:
            out.add(s)
    return sorted(out)
