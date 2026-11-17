"""Blockout: grey boxes first, real pieces later.

Recipe key `blockout` (a list):
  {"id": "b1", "pos": [x, y, z]           centre of the bottom face
   "size": [w, h, l], "yaw": 0,           metres, degrees about +y
   "material": "fence" | "glass" | null,   a cut-out wire fence or a see-through pane instead of a grey box (no solid hull: thin hull)
   "label": "...",                        editor only
   "piece": {"model": "/data/Models/...", "name": "..."} | null}

A plain box becomes one part of ONE generated model `BLOCKOUT` (texture `B_Grey`), placed once at the origin, with one solid hull per box.
A box that has a `piece` is not drawn: the shipped model goes to `shipped_models` at the box's position (the builder copies the model and its
pictures into the new map's block, see make_new_map.shipped_into_geometry). A placed model has no turn in the builder, so a piece whose box is
turned is placed unturned, and a note says so.
"""
import math

from .core import np, yaw_quat
from .meshkit import Mesh

TEXTURE = 'B_Grey'
PANELS = {'fence': ('B_Fence', 'fence', 'thin', 'Wirefence'), 'glass': ('B_Glass', 'glass', 'thin', 'SolidGlass')}     # material -> (texture, kind, hull, surface)


def geometry(m):
    """-> (Mesh or None, [shipped placement dicts]) for the `blockout` key of one map."""
    mesh, shipped = Mesh(), []
    for b in m.get('blockout') or []:
        x, y, z = [float(v) for v in b['pos']]
        w, h, l = [float(v) for v in b.get('size', [4, 3, 4])]
        yaw = float(b.get('yaw', 0))
        if b.get('piece') and b['piece'].get('model'):
            shipped.append(dict(model=b['piece']['model'], pos=[round(x, 3), round(y, 3), round(z, 3)], orient=yaw_quat(math.radians(yaw)), blockout=b.get('id'), yaw=yaw))
            continue
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        lo, hi = (-w / 2, 0.0, -l / 2), (w / 2, h, l / 2)
        pan = PANELS.get(b.get('material'))
        tex = pan[0] if pan else TEXTURE
        sub = Mesh()
        sub.box(tex, lo, hi, uv=(1.0 / max(w, l, h, 0.5)) if pan else 0.25, collide=False)
        for g in sub.groups.values():
            P = np.concatenate(g['P'])
            N = np.concatenate(g['N'])
            mesh.add(tex, P @ R.T + [x, y, z], N @ R.T, np.concatenate(g['T']), np.concatenate(g['I']))
        pts = [(a, bb, cc) for a in (lo[0], hi[0]) for bb in (lo[1], hi[1]) for cc in (lo[2], hi[2])]
        mesh.hull(np.asarray(pts) @ R.T + [x, y, z], pan[2] if pan else 'solid', pan[3] if pan else 'Concrete')
    return (mesh if not mesh.empty() else None), shipped


def build(m, out):
    """Add the boxes of one map to the collector `out`. -> dict(boxes, pieces) for the stats."""
    mesh, shipped = geometry(m)
    if mesh is not None:
        used = {b.get('material') for b in m.get('blockout') or [] if not (b.get('piece') and b['piece'].get('model'))}
        if used - set(PANELS):
            out.texture(TEXTURE, 'concrete', 128, 'DXT1', 21)
        for mat in sorted(x for x in used if x in PANELS):
            tex, kind, _, _ = PANELS[mat]
            out.texture(tex, kind, 128, 'RGBA32', 22)
        out.model('BLOCKOUT', [mesh.part()])
        out.place('BLOCKOUT', [0.0, 0.0, 0.0], 'BLOCKOUT_ALL')
    out.shipped_models += shipped
    turned = sum(1 for s in shipped if abs(s['yaw']) % 360 > 1e-6)
    if turned:
        out.note('%d blockout piece%s turned: a placed game model cannot be turned yet, so %s placed facing the default way.'
                 % (turned, '' if turned == 1 else 's', 'it is' if turned == 1 else 'they are'))
    return dict(boxes=len(m.get('blockout') or []) - len(shipped), pieces=len(shipped))
