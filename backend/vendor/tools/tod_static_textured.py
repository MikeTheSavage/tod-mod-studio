#!/usr/bin/env python3
"""
Batch-regenerate STATIC textured glTF previews (the Geometry-tab models) with the corrected
geometry pipeline + per-mesh textures. Replaces the old broken dumps (wrong scale, single shared
texture). Scans asset blocks, dedups models by name, writes <Content>/Meshes_Textured/<name>.glb.
"""
import sys, os, struct, json, glob
import tod_model_extract as me
import tod_model_to_gltf as mg
import tod_dds
from tod_validated_texture_aliases import resolve_validated_alias

_PROJ = os.environ.get('TOD_PROJECT', '')   # the author's TOD Project folder (not included)
TEXBASE = [os.path.join(_PROJ, 'TODPrototype', 'Content', 'Textures'),
           os.path.join(_PROJ, 'TOD_Extract', 'blocks', 'data_pc')] if _PROJ else []
OUTDIR = os.path.join(_PROJ, 'TODPrototype', 'Content', 'Meshes_Textured')   # relative to the working folder when unset
_tex_cache = {}

def resolve_tex(ref):
    if not ref: return None
    alias = resolve_validated_alias(ref)
    if alias: return alias
    base = os.path.splitext(ref.lstrip('/'))[0]
    for b in TEXBASE:
        for ext in ('.dds', '.DDS'):
            p = os.path.join(b, base + ext)
            if os.path.exists(p): return p
    # variant fallback: vehicles/props store the texref as a BASE name (e.g. Sedan_Body)
    # while disk has paint/skin variants (Sedan_Body_Silver.dds...). Pick the first variant.
    for b in TEXBASE:
        hits = sorted(glob.glob(os.path.join(b, base + '_*.dds')) + glob.glob(os.path.join(b, base + '*.dds')))
        if hits: return hits[0]
    # last resort: texref path prefix can disagree with disk; match on basename anywhere.
    bn = os.path.basename(base).lower()
    idx = _basename_index()
    return idx.get(bn) or next((p for n, p in idx.items() if n.startswith(bn + '_')), None)

_bn_idx = None
def _basename_index():
    global _bn_idx
    if _bn_idx is None:
        _bn_idx = {}
        for b in TEXBASE:
            for p in glob.glob(os.path.join(b, '**', '*.dds'), recursive=True):
                _bn_idx.setdefault(os.path.splitext(os.path.basename(p))[0].lower(), p)
    return _bn_idx

def tex_png(ref):
    """-> (png_bytes_or_None, has_transparency)."""
    if ref in _tex_cache: return _tex_cache[ref]
    p = resolve_tex(ref); png = None; alpha = False
    if p:
        try: png, alpha = tod_dds.dds_to_png_and_alpha(p)
        except Exception: png = None
    _tex_cache[ref] = (png, alpha)
    return _tex_cache[ref]

def _is_ident(M, eps=1e-5):
    return all(abs(M[i][j] - (1.0 if i == j else 0.0)) <= eps for i in range(3) for j in range(4))

def bake_pivots(model, info, base):
    """Bake each RIGID mesh's pivot WORLD transform into its POSITIONS + NORMALS.

    Rigid (non-skinned) meshes are stored in pivot-LOCAL space; the old exporter wrote the raw
    verts under one identity glTF node, so meshes hanging under rotated/offset pivots baked
    wrong (162/1133 textured models affected, 73 with rotation — e.g. door levers, air vents,
    the chicken). Math ported from tod_char_textured / tod_model_to_gltf: the engine skinning
    convention is parent index at pivot+0x58 and CONJUGATED quaternions (runtime-verified).
    Smooth-skinned meshes already store verts in MODEL space -> left untouched.
    Mutates model['meshes'][*]['verts'] in place.
    """
    piv = model['pivots']
    pivptr = me.deref(info, base + 0x30)
    piv2 = [{'pos': p['pos'],
             'quat': [-p['quat'][0], -p['quat'][1], -p['quat'][2], p['quat'][3]],  # conjugate
             'parent': struct.unpack_from('<i', info, pivptr + i * 0x7C + 0x58)[0]}
            for i, p in enumerate(piv)]
    Wm = mg.world_mats(piv2)
    for m in model['meshes']:
        if m.get('skinned'):
            continue                    # smooth-skinned verts are already model-space
        M = Wm[m['pivot']]
        if _is_ident(M):
            continue
        nv = []
        for v in m['verts']:
            p = mg.xform(M, v[0])
            n = mg.xform3(M, v[3])
            ln = (n[0]*n[0] + n[1]*n[1] + n[2]*n[2]) ** 0.5 or 1.0
            nv.append((p,) + tuple(v[1:3]) + ((n[0]/ln, n[1]/ln, n[2]/ln),) + tuple(v[4:]))
        m['verts'] = nv

def build_static(model):
    blob = bytearray(); bv = []; acc = []; images = []; textures = []; materials = []; prims = []
    def pack(data):
        while len(blob) % 4: blob.append(0)
        o = len(blob); blob.extend(data); return o, len(data)
    def aadd(off, ln, comp, typ, count, mn=None, mx=None):
        bv.append({'buffer': 0, 'byteOffset': off, 'byteLength': ln})
        a = {'bufferView': len(bv)-1, 'componentType': comp, 'count': count, 'type': typ}
        if mn is not None: a['min'] = mn; a['max'] = mx
        acc.append(a); return len(acc)-1
    for mi, m in enumerate(model['meshes']):
        if not m['verts']: continue
        # HANDEDNESS (fix 2026-07-03): kapow model space is LEFT-handed (D3D9); glTF is RIGHT-handed.
        # Writing raw coords mirrored every UE import about its local XZ plane (LR-mirrored signs
        # floating away from their buildings, holes in mirrored collision). Negate Z on positions
        # and normals so the glb is true right-handed glTF; UE's Y-up->Z-up import then yields
        # exactly the k2u placement contract (kx, -kz, ky).
        # WINDING (fix 2026-09-05): do NOT also reverse the index order. Kapow triangles are D3D
        # clockwise-front; the mirror alone turns them into glTF counter-clockwise-front. Reversing
        # too made every mesh inside-out — invisible with doubleSided materials, but Chaos culls
        # back faces on complex-collision traces/sweeps, so characters fell through every floor.
        pos = [(v[0][0], v[0][1], -v[0][2]) for v in m['verts']]
        nrm = [(v[3][0], v[3][1], -v[3][2]) for v in m['verts']]
        uv = [v[1] for v in m['verts']]
        idx = m['indices'] if m['isTriangles'] else me_strip(m['indices'])
        if not idx: continue
        idx = [idx[i] for i in range(0, len(idx) - len(idx) % 3)]  # keep D3D order (see WINDING above)
        o, l = pack(struct.pack('<%dI' % len(idx), *idx)); ia = aadd(o, l, 5125, 'SCALAR', len(idx))
        pmin = [min(p[i] for p in pos) for i in range(3)]; pmax = [max(p[i] for p in pos) for i in range(3)]
        o, l = pack(struct.pack('<%df' % (len(pos)*3), *[c for p in pos for c in p])); pa = aadd(o, l, 5126, 'VEC3', len(pos), pmin, pmax)
        o, l = pack(struct.pack('<%df' % (len(nrm)*3), *[c for n in nrm for c in n])); na = aadd(o, l, 5126, 'VEC3', len(nrm))
        o, l = pack(struct.pack('<%df' % (len(uv)*2), *[c for u in uv for c in u])); ua = aadd(o, l, 5126, 'VEC2', len(uv))
        prim = {'attributes': {'POSITION': pa, 'NORMAL': na, 'TEXCOORD_0': ua}, 'indices': ia, 'mode': 4}
        # ground-truth per-mesh texture: TextureReferencesList[ smb.m_TextureReferences[0] ]
        ti = m.get('texidx', -1)
        if not (0 <= ti < len(model['textures'])):
            ti = mi if mi < len(model['textures']) else 0
        ref = model['textures'][ti] if model['textures'] else None
        png, alpha = tex_png(ref)
        if png:
            o, l = pack(png); bv.append({'buffer': 0, 'byteOffset': o, 'byteLength': l})
            images.append({'bufferView': len(bv)-1, 'mimeType': 'image/png'})
            textures.append({'source': len(images)-1})
            mat = {'pbrMetallicRoughness': {'baseColorTexture': {'index': len(textures)-1},
                   'metallicFactor': 0.0, 'roughnessFactor': 1.0}, 'doubleSided': True}
            if alpha:  # sign/decal/effect cards: alpha-clip the transparent background (was opaque gray quads)
                mat['alphaMode'] = 'MASK'; mat['alphaCutoff'] = 0.5
            materials.append(mat)
            prim['material'] = len(materials)-1
        if 'source_flags' in m:
            prim['extras'] = {'tod_source_flags': m['source_flags'],
                             'tod_source_lod': m['source_flags'] & 31,
                             'tod_source_mesh_offset': m['source_mesh_offset'],
                             'tod_native_render_flags_pending': True}
            if 'source_meshbuffer_flags' in m:
                prim['extras'].update({
                    'tod_source_meshbuffer_offset': m['source_meshbuffer_offset'],
                    'tod_source_meshbuffer_flags': m['source_meshbuffer_flags'],
                    'tod_native_environment_requested': bool(m['source_meshbuffer_flags'] & 4),
                })
        prims.append(prim)
    if not prims: return None, None
    gltf = {'asset': {'version': '2.0', 'generator': 'tod_static_textured'},
            'buffers': [{'byteLength': len(blob)}], 'bufferViews': bv, 'accessors': acc,
            'images': images, 'textures': textures, 'materials': materials,
            'meshes': [{'primitives': prims}], 'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
    return gltf, bytes(blob)

def me_strip(idx):
    out = []
    for i in range(len(idx)-2):
        a, b, c = idx[i], idx[i+1], idx[i+2]
        if a == b or b == c or a == c: continue
        out += [a, c, b] if (i & 1) else [a, b, c]
    return out

def write_glb(path, gltf, blob):
    j = json.dumps(gltf).encode('utf-8')
    while len(j) % 4: j += b' '
    b = bytearray(blob)
    while len(b) % 4: b.append(0)
    out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + 8 + len(b))
    out += struct.pack('<I', len(j)) + b'JSON' + j + struct.pack('<I', len(b)) + b'BIN\x00' + bytes(b)
    open(path, 'wb').write(out)

def out_name(modelname):
    # match the existing convention: '/data/characters/ram/ram.model' -> 'data_characters_ram_ram.glb'
    n = modelname.lstrip('/').replace('.model', '')
    return n.replace('/', '_') + '.glb'

def select_source_lod(meshes, lod=0):
    """Highest-detail preview selection; preserve every matching source buffer.

    Metadata is mandatory: guessing LOD from vertex counts loses geometry.
    Runtime LOD selection and native blend/depth flags need separate UE support.
    """
    if not isinstance(lod, int) or not 0 <= lod <= 31:
        raise ValueError('Source LOD must be an integer from 0 through 31')
    if any('source_flags' not in mesh for mesh in meshes):
        raise ValueError('Missing native mesh flags; refusing heuristic LOD selection')
    return [mesh for mesh in meshes if (mesh['source_flags'] & 31) == lod]


def main():
    import time
    # --resume: skip outputs already regenerated recently (the full pass can die mid-run on
    # Drive write stalls; relaunch with --resume until it completes).
    RESUME = '--resume' in sys.argv
    FRESH_AFTER = time.time() - 36 * 3600
    blocks = (glob.glob('TOD_Extract/blocks/**/*.main', recursive=True) +
              glob.glob('TOD_Extract/blocks/**/*.submap', recursive=True))
    blocks = [b for b in blocks if os.path.getsize(b) > 2000]
    os.makedirs(OUTDIR, exist_ok=True)
    done = set(); n_written = 0; n_tex = 0; n_models = 0
    for bi, blk in enumerate(blocks):
        try: info = me.load_info(blk)
        except Exception: continue
        for p, name in me.find_model_records(info):
            if name in done: continue
            done.add(name); n_models += 1
            if RESUME:
                op = os.path.join(OUTDIR, out_name(name))
                try:
                    if os.path.exists(op) and os.path.getmtime(op) > FRESH_AFTER:
                        continue
                except OSError:
                    pass
            try:
                model = me.extract_model(info, p, name)
                if not model or not model['meshes']: continue
                if not model.get('textures'): continue   # only (re)build textured ones
                bake_pivots(model, info, p)              # pivot-local -> model space (see docstring)
                # Native Model::Render (GOG 0x884EB0) draws ALL buffers at
                # the selected LOD. Texture/pivot identity does not imply
                # duplicate geometry; largest-per-texture deleted authored faces.
                model['meshes'] = select_source_lod(model['meshes'], 0)
                gltf, blob = build_static(model)
                if not gltf: continue
                write_glb(os.path.join(OUTDIR, out_name(name)), gltf, blob)
                n_written += 1
                if gltf['images']: n_tex += 1
            except Exception:
                continue
        if (bi+1) % 20 == 0:
            print('  ...%d/%d blocks, %d models seen, %d glbs written (%d textured)' % (bi+1, len(blocks), n_models, n_written, n_tex), flush=True)
    print('DONE: %d unique models, %d textured glbs written -> %s' % (n_models, n_written, OUTDIR))

if __name__ == '__main__':
    main()
