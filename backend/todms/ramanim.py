"""Ram with a handful of move clips as one glb, for the Tune move previews.

Built from the user's own game data through the vendored character tool and cached; nothing is shipped."""
import os
import re
import struct

from . import paths

CLIPS = re.compile(r'^ram_(idle_breathe_aware|walk|run|run_gun_aim|run_land|jump_running|jump_running_midair|jump_standing|'
                   r'weapon_idle_gun|aim_hi_gun|shoot_hi_gun|reload_gun|locomove|rammove_idle|rammove_run|'
                   r'shootdodge_(front|back|left|right)_(jump|midair|land)_gun|wallvault_(left|right)_gun)$')
VERSION = 1


def _info(raw):
    ts, pck, cck, total, infosize, datasize = struct.unpack_from('<IIIiII', raw, 0)
    if not (0 < total < 100000 and 0 < infosize < len(raw)):
        raise ValueError('unexpected block header')
    return raw[24:24 + infosize]


def build(ws, progress=None):
    """-> dict(url, clips). Cached under <cache>/assets/ram_moves_v<n>.glb."""
    paths.setup_tools()
    out_dir = os.path.join(paths.cache_dir(), 'assets')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'ram_moves_v%d.glb' % VERSION)
    idx = out + '.json'
    import json
    if os.path.exists(out) and os.path.exists(idx):
        return json.load(open(idx))
    import tod_model_extract as me
    import tod_anim_extract as ae
    import tod_anim_remap as rm
    import tod_char_anim_extract as ca
    import tod_model_to_gltf as g
    from .game import MAIN_ENTRY
    if progress:
        progress('Reading the player')
    raw, _ = ws.read_block(MAIN_ENTRY)
    info = _info(raw)
    mrec = next(((b, n) for b, n in me.find_model_records(info) if '/characters/ram/ram.model' in n.lower()), None)
    if not mrec:
        raise RuntimeError('the player model was not found')
    model = me.extract_model(info, *mrec)
    pivptr = me.deref(info, mrec[0] + 0x30)
    for i, p in enumerate(model['pivots']):
        p['parent'] = struct.unpack_from('<i', info, pivptr + i * 0x7C + 0x58)[0]
        q = p['quat']
        p['quat'] = [-q[0], -q[1], -q[2], q[3]]
    npiv = len(model['pivots'])
    clips = []
    for b, n in ae.find_anim_records(info):
        an = os.path.splitext(os.path.basename(n))[0]
        if not CLIPS.match(an):
            continue
        remap, _ = rm.derive_remap(info, b, model['pivots'], me.deref)
        a = ae.decode_anim(info, b, npiv, remap=remap)
        if not a:
            continue
        for t in a['tracks']:
            if t.get('rot'):
                t['rot'] = [(-x, -y, -z, w) for (x, y, z, w) in t['rot']]
        clips.append((an, a))
        if progress:
            progress('Reading moves', len(clips), None)
    if not clips:
        raise RuntimeError('no player moves found')
    gltf, blob, count = ca.build_combined(model, clips)
    tmp = out + '.tmp'
    g.write_glb(tmp, gltf, blob)
    os.replace(tmp, out)
    res = dict(url='/cache/assets/' + os.path.basename(out), clips=sorted(n for n, _ in clips), count=count)
    json.dump(res, open(idx, 'w'))
    return res
