"""Export one model's render mesh (LOD0) and collision (model space) as two glbs, optionally cut at a height so the
inside of a building is visible.   python model_glb.py BLOCK MODELNAME OUTPREFIX [--cut-y Y]"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_map as ex, todcoll as tc, todblock as tb

ap = argparse.ArgumentParser()
ap.add_argument('block'); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cut-y', type=float)
a = ap.parse_args()
BS = ex.BlockSet([a.block])
bi, R = BS.models[ex.norm(a.model)]
info = BS.blocks[bi]['info']
m = ex.me.extract_model(info, R, a.model)
PW = ex.pivot_world(info, R)
render = ex.Mesh(); coll = ex.Mesh()
cut = a.cut_y if a.cut_y is not None else 1e9
for mesh in m['meshes']:
    if mesh['source_lod'] != 0:
        continue
    verts = [ex.apply(PW[mesh['pivot']], v[0]) for v in mesh['verts']]
    idx = mesh['indices'] if mesh['isTriangles'] else ex.me.g.strip_to_tris(mesh['indices'])
    tris = [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
    tris = [t for t in tris if min(verts[k][1] for k in t) < cut]
    render.add(verts, tris)
n = 0
for space, pi, s in ex.model_collision(info, R):
    M = ex.IDENT if space == 'model' else PW[pi]
    if s['type'] != 4:
        continue
    verts = [ex.apply(M, v) for v in s['verts']]
    if min(v[1] for v in verts) >= cut:
        continue
    tris = [(f[0], f[k], f[k + 1]) for f in s['faces'] for k in range(1, len(f) - 1)]
    coll.add(verts, tris, ex.CLASS_COLOR[ex.surf_class(s['surf'])])
    n += 1
ex.write_glb(a.out + '_render.glb', [('render', render)])
ex.write_glb(a.out + '_collision.glb', [('collision', coll)])
print('hulls drawn', n)
