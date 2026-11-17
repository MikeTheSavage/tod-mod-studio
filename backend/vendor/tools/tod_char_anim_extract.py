#!/usr/bin/env python3
"""
TOD combined skinned-character + animation -> single glTF (.glb).

Builds ONE glb that the asset viewer can play: the character's skinned mesh (or rigid
hierarchical mesh) PLUS every compatible animation clip, with the clips driving the exact bone
nodes the skin binds to.

Why this works cleanly: both the skin (tod_model_extract.build_skinned_glb) and the animation
tracks (tod_anim_extract.decode_anim) index bones by the SAME pivot index, and glTF node N here
IS bone/joint N. So an animation channel targeting node N animates skin joint N. Non-skinned
meshes are rigid-bound to their owning pivot by build_skinned_glb, so rigid characters (e.g. the
chicken) animate too.

Clip selection ('--match'):
  own        - clips whose name starts with the model stem (e.g. ram_*)
  compatible - clips whose driven-pivot count is close to this model's pivot count (default).
               This naturally groups the shared 50-bone human skeleton (ram/civil/elvez/hooker/
               cezar/mendez/...) together while excluding the chicken (~15 bones), and vice-versa.
  all        - every clip in the anim block (clipped to this model's pivot count)

Examples:
  tod_char_anim_extract.py overdose.main --model ram                 # player + all human clips
  tod_char_anim_extract.py overdose.main --model chicken             # chicken + chicken clips
  tod_char_anim_extract.py submapXX.submap --model elvez --anim-block overdose.main
"""
import struct, sys, os, argparse
import tod_model_extract as me
import tod_anim_extract as ae
import tod_model_to_gltf as g

FPS = 30.0

def clip_entries(info, base):
    kf = me.deref(info, base + 0x5C)
    if kf is None: return 0
    n = struct.unpack_from('<I', info, kf)[0]
    return n if 0 < n < 4096 else 0

def build_combined(model, clips):
    """clips: list of (name, decoded_anim). Returns (gltf, blob) = skin + animations."""
    gltf, blob = me.build_skinned_glb(model)   # nodes 0..npiv-1 are the bones; +mesh/skin
    blob = bytearray(blob)
    npiv = len(model['pivots'])

    def add_acc(data, comp, typ, count, mn=None, mx=None):
        nonlocal blob
        while len(blob) % 4: blob.append(0)
        off = len(blob); blob += data
        gltf['bufferViews'].append({'buffer': 0, 'byteOffset': off, 'byteLength': len(data)})
        a = {'bufferView': len(gltf['bufferViews']) - 1, 'componentType': comp, 'count': count, 'type': typ}
        if mn is not None: a['min'] = mn; a['max'] = mx
        gltf['accessors'].append(a)
        return len(gltf['accessors']) - 1

    anims = []
    for name, a in clips:
        nf = a['frames']
        if nf <= 0: continue
        # Match the float32 accessor values exactly in both payload and bounds.
        # Decimal rounding can push a frame endpoint above the 30 Hz boundary;
        # a glTF importer then adds a whole frame (82/346 police clips).
        times = [ae.frame_time_float32(f, FPS) for f in range(nf)]
        tin = add_acc(struct.pack('<%df' % nf, *times), 5126, 'SCALAR', nf, [0.0], [max(times)])
        samplers = []; channels = []
        for bi, t in enumerate(a['tracks']):
            if bi >= npiv: break
            if t['rot']:
                so = add_acc(struct.pack('<%df' % (nf * 4), *[c for q in t['rot'] for c in q]), 5126, 'VEC4', nf)
                samplers.append({'input': tin, 'output': so, 'interpolation': 'LINEAR'})
                channels.append({'sampler': len(samplers) - 1, 'target': {'node': bi, 'path': 'rotation'}})
            if t['pos']:
                so = add_acc(struct.pack('<%df' % (nf * 3), *[c for v in t['pos'] for c in v]), 5126, 'VEC3', nf)
                samplers.append({'input': tin, 'output': so, 'interpolation': 'LINEAR'})
                channels.append({'sampler': len(samplers) - 1, 'target': {'node': bi, 'path': 'translation'}})
        if channels:
            anims.append({'name': name, 'samplers': samplers, 'channels': channels})
    gltf['animations'] = anims
    gltf['buffers'][0]['byteLength'] = len(blob)
    return gltf, bytes(blob), len(anims)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('block', help='block holding the MODEL (skinned/rigid mesh)')
    ap.add_argument('--model', required=True, help='model name substring (the character)')
    ap.add_argument('--anim-block', default=None, help='block holding the .animation clips (default: same block)')
    ap.add_argument('--match', choices=['own', 'compatible', 'all'], default='compatible')
    ap.add_argument('--tol', type=float, default=0.35, help='compatible: allowed |entries-npiv|/npiv')
    ap.add_argument('--no-pos', action='store_true', help='drop position tracks (rotation-only) — diagnostic')
    ap.add_argument('--root-pos-only', action='store_true', help='keep position tracks on root bone(s) only')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--remap', default=None, help='JSON file with a FIXED bone remap (legacy, from '
                    'tod_remap_parse.py). Default is the STATIC per-clip remap derived by name-match '
                    '(tod_anim_remap) — preferred, needs no runtime.')
    ap.add_argument('--no-static-remap', action='store_true',
                    help='disable static per-clip name-match remap (diagnostic).')
    args = ap.parse_args()

    import tod_anim_remap as rm
    remap = None
    if args.remap:
        import json
        rd = json.load(open(args.remap))
        # accept either a bare list, or {"<key>":[...]} keyed by bone-count/character
        if isinstance(rd, list):
            remap = rd
        elif isinstance(rd, dict):
            remap = rd.get('remap') or rd  # set later by bone count once npiv known
    minfo = me.load_info(args.block)
    mrec = next(((b, n) for b, n in me.find_model_records(minfo) if args.model.lower() in n.lower()), None)
    if not mrec: sys.exit('model not found: ' + args.model)
    model = me.extract_model(minfo, *mrec)
    # ENGINE SKINNING CONVENTION (verified 2026-06-18 against runtime capture: tod_locals2.log +
    # bone-matrix solve). Two corrections vs the asset's raw fields, applied here on the skinned
    # skeleton only (leaves the static-geometry path untouched):
    #   1) the real parent index is at pivot+0x58 (extract_model reads +0x4C, which is 0 = flat).
    #   2) the engine's bone rotation is the TRANSPOSE of the standard quat->matrix, i.e. every
    #      rotation quaternion (bind + animation) must be CONJUGATED. Composing the engine's own
    #      captured quats this way reproduces a coherent pose (edge-big 208 vs bind 194); the old
    #      no-conjugate/flat path scrambled to 824+.
    import struct as _st
    _pivptr = me.deref(minfo, mrec[0] + 0x30)
    for _i, _p in enumerate(model['pivots']):
        _p['parent'] = _st.unpack_from('<i', minfo, _pivptr + _i * 0x7C + 0x58)[0]
        _q = _p['quat']; _p['quat'] = [-_q[0], -_q[1], -_q[2], _q[3]]
    npiv = len(model['pivots'])
    nv = sum(len(x['verts']) for x in model['meshes'])
    skinned = any(x.get('skinned') for x in model['meshes'])
    stem = os.path.splitext(os.path.basename(model['name']))[0].lower()
    print('model %r: %d pivots, %d meshes, %d verts (%s)' % (model['name'], npiv, len(model['meshes']), nv,
                                                             'skinned' if skinned else 'rigid'))
    # resolve a bone-count-keyed remap dict to the list for this skeleton
    if isinstance(remap, dict):
        remap = remap.get(str(npiv)) or remap.get(npiv)
    if remap:
        print('  using bone remap (%d entries)' % len(remap))

    ainfo = me.load_info(args.anim_block) if args.anim_block else minfo
    clips = []; skipped = 0
    for b, n in ae.find_anim_records(ainfo):
        an = os.path.splitext(os.path.basename(n))[0]
        ne = clip_entries(ainfo, b)
        if args.match == 'own':
            if not an.lower().startswith(stem): continue
        elif args.match == 'compatible':
            if ne == 0 or abs(ne - npiv) > max(10, npiv * args.tol): skipped += 1; continue
        # STATIC per-clip remap: each .ani names its own channels; derive the model->entry map by
        # case-insensitive bone-name match (engine FUN_009032d0). A fixed --remap overrides this.
        clip_remap = remap
        if clip_remap is None and not args.no_static_remap:
            clip_remap, _ = rm.derive_remap(ainfo, b, model['pivots'], me.deref)
        a = ae.decode_anim(ainfo, b, npiv, remap=clip_remap)
        if not a: continue
        # conjugate decoded rotation quats to match the engine's transposed-rotation convention
        for _t in a['tracks']:
            if _t.get('rot'): _t['rot'] = [(-x, -y, -z, w) for (x, y, z, w) in _t['rot']]
        if args.no_pos:
            for t in a['tracks']: t['pos'] = None
        elif args.root_pos_only:
            roots = set(i for i, p in enumerate(model['pivots'])
                        if not (0 <= p['parent'] < npiv and p['parent'] != i))
            for i, t in enumerate(a['tracks']):
                if i not in roots: t['pos'] = None
        clips.append((an, a))
    if not clips: sys.exit('no compatible clips found (try --match own/all)')

    gltf, blob, nan = build_combined(model, clips)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', stem + '.charanim.glb')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    g.write_glb(out, gltf, blob)
    print('wrote %s\n  %d clips bundled (%d skipped as incompatible), %d bones, %.1f MB'
          % (out, nan, skipped, npiv, len(blob) / 1e6))

if __name__ == '__main__':
    main()
