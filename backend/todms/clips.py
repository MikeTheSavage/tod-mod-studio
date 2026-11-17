"""Character animation clips for the catalogue: the clips of the game that fit a rigged model, and the data to play them.

The clips are the ANIMATION records of the shared asset block (todct/animcodec.py decodes them). A clip names its channels after the
model's pivots; a clip fits a model when most of the model's named pivots have a channel (one humanoid skeleton is shared by every
person in the game, so the player's clips play on all of them).

The viewer skins on the CPU from this data:
  skin(ws, key)         bind pose of the skeleton (local position + rotation per pivot, parent) and the vertices with their joint weights
  clip(ws, key, name)   per pivot: the rotation (and position) of every frame, matched by pivot name, rotations conjugated for the
                        engine's rotation convention (the engine's bone rotation is the transpose of the usual quaternion matrix)
"""
import json
import os
import struct

from . import paths

VERSION = 1
_MEM = {}


def _cfg():
    from . import catalogue
    return catalogue.cfg()


def _main():
    from .game import MAIN_ENTRY
    return MAIN_ENTRY


def _short(n):
    return n.replace('\\', '/').split('/')[-1].rsplit('.', 1)[0]


def index(ws):
    """Every clip: name, frames, fps, loop, channel names. Cached on disk, keyed by the shared block as the game serves it."""
    from todct import animcodec as AC
    key = ws.block_key(_main())
    if _MEM.get('key') == key:
        return _MEM['clips']
    f = os.path.join(_cfg().folder, 'clips_index.json')
    try:
        with open(f, encoding='utf-8') as h:
            d = json.load(h)
        if d.get('version') == VERSION and d.get('key') == key:
            _MEM.update(key=key, clips=d['clips'])
            return d['clips']
    except (OSError, ValueError):
        pass
    A = ws.assets(_main())
    info = A.info
    clips = []
    for R in A.starts:
        if struct.unpack_from('<I', info, R)[0] != 9:
            continue
        try:
            h = AC.decode_record(info, R)
        except Exception:                                   # noqa: BLE001  (an unusual clip is left out)
            continue
        fps = struct.unpack('<f', struct.pack('<I', h['f20']))[0]
        fr = struct.unpack('<i', struct.pack('<I', h['frames']))[0]
        clips.append(dict(name=h['name'], short=_short(h['name']), R=R, frames=fr, fps=round(fps, 3), loop=h['loop'],
                          chans=[c['name'] for c in h['chans']]))
    with open(f + '.part', 'w', encoding='utf-8') as h:
        json.dump(dict(version=VERSION, key=key, clips=clips), h, separators=(',', ':'))
    os.replace(f + '.part', f)
    _MEM.update(key=key, clips=clips)
    return clips


def _rig(ws, row):
    """-> (info, R, model dict) of a model whose pivots carry a skeleton, with the real parent links."""
    import tod_model_extract as me
    from . import catalogue
    entry, rec = catalogue.locate(ws, row)
    A = ws.assets(entry)
    hit = A.models.get(row['path'].lower())
    if hit is None:
        raise KeyError('That model has no mesh here.')
    R = hit[1]
    m = me.extract_model(A.info, R, row['path'])
    base = me.deref(A.info, R + 0x30)
    for i, p in enumerate(m['pivots']):
        p['parent'] = struct.unpack_from('<i', A.info, base + i * 0x7C + 0x58)[0]
    return A.info, R, m


def _named(m):
    return [p['name'].lower() for p in m['pivots'] if p.get('name')]


def fits(clip, names):
    """True when the clip drives most of the named pivots."""
    if not names:
        return False
    have = {c.lower() for c in clip['chans']}
    hit = sum(1 for n in names if n in have)
    return hit >= 4 and hit >= 0.6 * len(names)


def available(ws, row):
    """-> dict(clips [{name, short, frames, fps, loop, seconds, own}], rigged). Empty when the model is not a person or animal."""
    if row.get('kind') != 'skeletal' and not (row['path'] or '').lower().startswith('/data/animals/'):
        return dict(clips=[], rigged=False)
    try:
        info, R, m = _rig(ws, row)
    except Exception:                                       # noqa: BLE001
        return dict(clips=[], rigged=False)
    names = _named(m)
    stem = row['path'].replace('\\', '/').split('/')[-1].rsplit('.', 1)[0].lower()
    out = []
    for c in index(ws):
        if c['frames'] > 1 and fits(c, names):
            out.append(dict(name=c['short'], frames=c['frames'], fps=c['fps'], loop=c['loop'] == 0,
                            seconds=round(c['frames'] / (c['fps'] or 25.0), 2), own=c['short'].lower().startswith(stem)))
    out.sort(key=lambda c: (not c['own'], c['name'].lower()))
    return dict(clips=out, rigged=True)


def skin(ws, row):
    """The bind pose and the vertices, for skinning in the browser. Game axes (the viewer negates z)."""
    info, R, m = _rig(ws, row)
    piv = []
    for p in m['pivots']:
        q = p['quat']
        piv.append(dict(name=p['name'] or '', parent=p['parent'], pos=[round(v, 6) for v in p['pos']],
                        quat=[round(-q[0], 7), round(-q[1], 7), round(-q[2], 7), round(q[3], 7)]))       # conjugated: the engine's convention
    meshes = []
    for mesh in m['meshes']:
        if not mesh['verts']:
            continue
        idx = mesh['indices']
        if not mesh['isTriangles']:
            import tod_model_to_gltf as g
            idx = g.strip_to_tris(idx)
        idx = [i for i in idx]
        skinned = bool(mesh.get('skinned') and mesh['joints'])
        ti = mesh.get('texidx', -1)
        tex = m['textures'][ti].lower() if 0 <= ti < len(m['textures']) else None
        meshes.append(dict(
            tex=tex, skinned=skinned, pivot=mesh['pivot'],
            pos=[round(c, 5) for v in mesh['verts'] for c in v[0]], nrm=[round(c, 4) for v in mesh['verts'] for c in v[3]],
            uv=[round(c, 5) for v in mesh['verts'] for c in v[1]],
            joints=[j for js in mesh['joints'] for j in js] if skinned else [], weights=[round(w, 5) for ws_ in mesh['weights'] for w in ws_] if skinned else [],
            idx=idx))
    return dict(pivots=piv, meshes=meshes, textures=m['textures'])


def clip(ws, row, name):
    """Per pivot of the model: rotation and position of every frame ([x, y, z, w] rotations, conjugated), or None for the bind value."""
    from todct import animcodec as AC
    info, R, m = _rig(ws, row)
    pick = next((c for c in index(ws) if c['short'].lower() == name.lower()), None)
    if pick is None:
        raise KeyError('No such clip.')
    h = AC.decode_record(ws.assets(_main()).info, pick['R'])
    frames = struct.unpack('<i', struct.pack('<I', h['frames']))[0]
    lut = {}
    for c in h['chans']:
        lut.setdefault(c['name'].lower(), c)
    rot, pos, st_rot, st_pos = [], [], [], []
    for p in m['pivots']:
        c = lut.get((p['name'] or '').lower()) if p.get('name') else None
        r = ps = None
        sr = sp = False
        if c and c['ori']:
            kind, v = c['ori']
            sr = kind == 'static'
            vals = [v] if sr else v
            r = [round(x, 6) for q in vals for x in (-q[1] / 32767.0, -q[2] / 32767.0, -q[3] / 32767.0, q[0] / 32767.0)]
        if c and c['pos']:
            kind, v = c['pos']
            sp = kind == 'static'
            vals = [v] if sp else v
            ps = [round(x, 6) for t in vals for x in t]
        rot.append(r); pos.append(ps); st_rot.append(sr); st_pos.append(sp)
    fps = struct.unpack('<f', struct.pack('<I', h['f20']))[0]
    return dict(name=pick['short'], frames=frames, fps=fps, loop=h['loop'] == 0, rot=rot, pos=pos, rot_static=st_rot, pos_static=st_pos)
