"""Model import: files as Blender (2.79 to 5.x) and other tools write them must load, or fail with one plain line.

Every case here is a small synthetic file (meshfix.py). A texture that is missing or unreadable falls back to the material colour with
a warning; an unknown extension or attribute is ignored with a warning; a required extension we cannot honour (Draco) says so.
"""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, HERE)
import meshfix as F  # noqa: E402


def env(tmp):
    return patch.dict(os.environ, TODMS_HOME=os.path.join(tmp, 'home'), TODMS_CACHE=os.path.join(tmp, 'cache'), TODMS_SAVES=os.path.join(tmp, 'saves'))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='imptest')
        self.d = os.path.join(self.tmp, 'files')
        os.makedirs(self.d)
        self.env = env(self.tmp)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, path):
        from todct import meshtex
        return meshtex.read(path)

    def through(self, path, **params):
        """The UI's path: analyze, then bake with the suggested settings. -> (analysis, baked)"""
        from todms import imports, assetstore
        from todct import modelimport as MI
        r = imports.analyze(path)
        sc = MI.scene_from_bytes(assetstore.get(r['sha']))
        return r, MI.bake(sc, dict(up=r['suggest']['up'], **params))

    def fails(self, path):
        from todms import imports
        with self.assertRaises(imports.ImportError_) as cm:
            imports.analyze(path)
        msg = str(cm.exception)
        self.assertLess(len(msg), 110, msg)
        for bad in ('Traceback', 'array', 'shape', 'Error', 'KeyError', 'object', 'line '):
            self.assertNotIn(bad, msg)
        return msg


# ------------------------------------------------------------------------------------------------ OBJ
class TestObj(Base):
    def test_279_texture_path_of_another_machine_found_beside_the_file(self):
        p = F.obj_279(self.d, tex_in='tex.png')
        sc = self.load(p)
        self.assertEqual(len(sc.images), 1)
        self.assertEqual(sc.warnings, [])
        self.through(p)

    def test_279_missing_texture_uses_colour_and_warns(self):
        p = F.obj_279(self.d)
        r, b = self.through(p)
        self.assertTrue(any('texture file is missing' in w for w in r['warnings']))
        self.assertTrue(any('texture file is missing' in w for w in b.warnings))
        self.assertEqual(len(b.textures), 1)

    def test_texture_found_in_a_subfolder_and_with_another_extension(self):
        p = F.obj_279(self.d, tex_line='map_Kd textures\\wood.jpg')
        F.write(os.path.join(self.d, 'sub', 'wood.png'), F.png())
        self.assertEqual(len(self.load(p).images), 1)

    def test_blender_relative_prefix_and_options_and_spaces(self):
        p = F.obj_279(self.d, tex_line='map_Kd -s 1 1 1 -o 0 0 0 //my tex.png', tex_in='my tex.png')
        self.assertEqual(len(self.load(p).images), 1)

    def test_null_material_names_and_no_material(self):
        for n in ('(null)', 'None', None, ''):
            d = os.path.join(self.d, 'n%s' % abs(hash(n)))
            p = F.obj_279(d, usemtl=n)
            r, b = self.through(p)
            self.assertGreater(b.stats['triangles'], 0)

    def test_crlf_bom_and_odd_lines(self):
        txt = '﻿# x\r\nv 0 0 0\r\nv 1 0 0 0.5 0.5 0.5\r\nv 1 1 0\r\nv 0 1 0\r\nvt 0.5\r\nvt 0.1 0.2 0.0\r\nvn 0 0 1\r\n' \
              'g empty\r\ng quad\r\nusemtl\r\ns 1\r\nf 1/1/1 2/2/1 3/2/1 4/1/1\r\nl 1 2\r\np 3\r\nf 1 2\r\n'
        r, b = self.through(F.obj_text(self.d, txt))
        self.assertEqual(b.stats['triangles'], 2)

    def test_negative_indices(self):
        txt = 'v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf -4 -3 -2 -1\n'
        self.assertEqual(self.through(F.obj_text(self.d, txt))[1].stats['triangles'], 2)

    def test_bad_face_skipped_with_warning(self):
        txt = 'v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\nf 1 2 9\nf 1 x 3\nv 1\n'
        r, b = self.through(F.obj_text(self.d, txt))
        self.assertEqual(b.stats['triangles'], 1)
        self.assertTrue(any('skipped' in w for w in b.warnings))

    def test_one_value_kd_and_alpha_and_tr(self):
        txt = 'mtllib x.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nusemtl A\nf 1 2 3\nusemtl B\nf 1 3 2\n'
        mtl = 'newmtl A\nKd 0.5\nd -halo 0.5\nnewmtl B\nKd 1 0 0\nTr 0.25\nmap_Kd\nKe 0 0 0\nNi 1.45\nillum 4\n'
        sc = self.load(F.obj_text(self.d, txt, mtl=mtl))
        by = {p.name: p for p in sc.parts}
        self.assertAlmostEqual(by['A'].mat['color'][0], 0.5)
        self.assertAlmostEqual(by['A'].mat['color'][3], 0.5)
        self.assertAlmostEqual(by['B'].mat['color'][3], 0.75)

    def test_material_file_missing_warns(self):
        txt = 'mtllib gone.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nusemtl A\nf 1 2 3\n'
        sc = self.load(F.obj_text(self.d, txt))
        self.assertTrue(any('material file' in w for w in sc.warnings))

    def test_mtl_name_with_spaces(self):
        txt = 'mtllib my materials.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nusemtl Red Paint\nf 1 2 3\n'
        F.write(os.path.join(self.d, 'my materials.mtl'), 'newmtl Red Paint\nKd 1 0 0\n')
        sc = self.load(F.obj_text(self.d, txt))
        self.assertEqual(sc.parts[0].mat['color'][:3], [1.0, 0.0, 0.0])

    def test_unreadable_texture_falls_back(self):
        p = F.obj_279(self.d, tex_line='map_Kd t.png')
        F.write(os.path.join(self.d, 't.png'), b'not a picture at all')
        r, b = self.through(p)
        self.assertTrue(any('could not be read' in w for w in b.warnings))

    def test_quoted_pasted_path(self):
        from todms import imports
        p = F.obj_279(self.d, tex_in='tex.png')
        self.assertEqual(imports.clean_path('"%s"' % p), p)
        self.assertEqual(imports.analyze('  "%s" ' % p)['file'], 'cube279.obj')

    def test_empty_and_wrong_files_give_plain_messages(self):
        self.assertIn('no faces', self.fails(F.obj_text(self.d, '# nothing\nv 0 0 0\n')))
        self.assertIn('no faces', self.fails(F.obj_text(self.d, '', name='e')))
        self.assertIn('.glb', self.fails(F.write(os.path.join(self.d, 'a.fbx'), b'x')))
        self.assertIn('does not exist', self.fails(os.path.join(self.d, 'nope.obj')))

    def test_binary_junk_as_obj(self):
        self.fails(F.write(os.path.join(self.d, 'j.obj'), os.urandom(500)))


# ------------------------------------------------------------------------------------------------ glTF
def tri_doc(g=None, **kw):
    g = g or F.G()
    g.mesh([F.quad_prim(g, **kw)])
    return g


class TestGltf(Base):
    def test_index_types_and_no_indices(self):
        for it in (5121, 5123, 5125):
            g = F.G()
            g.mesh([g.prim(F.QUAD, [0, 1, 2, 0, 2, 3], index_type=it)])
            self.assertEqual(len(self.load(g.glb(os.path.join(self.d, 'i%d.glb' % it))).parts[0].tris), 2)
        g = F.G()
        g.mesh([g.prim([(0, 0, 0), (1, 0, 0), (0, 1, 0)])])
        self.assertEqual(len(self.load(g.glb(os.path.join(self.d, 'noidx.glb'))).parts[0].tris), 1)

    def test_strip_and_fan_modes(self):
        g = F.G()
        g.mesh([g.prim(F.QUAD, [0, 1, 3, 2], mode=5), g.prim(F.QUAD, [0, 1, 2, 3], mode=6)])
        sc = self.load(g.glb(os.path.join(self.d, 'sf.glb')))
        self.assertEqual([len(p.tris) for p in sc.parts], [2, 2])

    def test_lines_and_points_skipped_with_warning(self):
        g = F.G()
        g.mesh([g.prim(F.QUAD, [0, 1, 1, 2], mode=1), F.quad_prim(g)])
        sc = self.load(g.glb(os.path.join(self.d, 'l.glb')))
        self.assertEqual(len(sc.parts), 1)
        self.assertTrue(any('skipped' in w for w in sc.warnings))

    def test_sparse_accessor_and_accessor_without_view(self):
        g = F.G()
        base = np.zeros((4, 3), np.float32)
        a = g.acc(base, 5126, 'VEC3')
        del g.js['accessors'][a]['bufferView']
        ib = g.view(np.array([1, 2, 3], np.uint16).tobytes())
        vb = g.view(np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32).tobytes())
        g.js['accessors'][a]['sparse'] = dict(count=3, indices=dict(bufferView=ib, componentType=5123), values=dict(bufferView=vb))
        g.js['accessors'][a].update(min=[0, 0, 0], max=[1, 1, 0])
        ix = g.acc([0, 1, 2, 0, 2, 3], 5123, 'SCALAR')
        g.js['meshes'].append(dict(primitives=[dict(attributes=dict(POSITION=a), indices=ix)]))
        g.js['nodes'].append(dict(mesh=0))
        g.js['scenes'][0]['nodes'].append(0)
        sc = self.load(g.glb(os.path.join(self.d, 'sp.glb')))
        self.assertEqual(sc.parts[0].P[2].tolist(), [1.0, 1.0, 0.0])

    def test_interleaved_stride(self):
        g = F.G()
        g.mesh([g.prim(F.QUAD, [0, 1, 2, 0, 2, 3])])
        pos = g.js['meshes'][0]['primitives'][0]['attributes']['POSITION']
        a = g.acc(np.array(F.QUAD, np.float32), 5126, 'VEC3', stride_pad=4)
        g.js['meshes'][0]['primitives'][0]['attributes']['POSITION'] = a
        sc = self.load(g.glb(os.path.join(self.d, 'st.glb')))
        self.assertEqual(sc.parts[0].P[2].tolist(), [1.0, 1.0, 0.0])

    def test_second_uv_set_and_missing_normals(self):
        g = F.G()
        t = g.image_view(F.png())
        m = g.material(tex=dict(index=t, texCoord=1))
        g.mesh([g.prim(F.QUAD, [0, 1, 2, 0, 2, 3], uv=[(0, 0)] * 4, uv1=[(0, 1), (1, 1), (1, 0), (0, 0)], normals=False, material=m)])
        sc = self.load(g.glb(os.path.join(self.d, 'uv1.glb')))
        self.assertEqual(sc.parts[0].UV[1].tolist(), [1.0, 1.0])
        self.assertIsNone(sc.parts[0].N)
        self.through(os.path.join(self.d, 'uv1.glb'))

    def test_texture_transform_applied(self):
        g = F.G()
        t = g.image_view(F.png())
        m = g.material(tex=dict(index=t, extensions=dict(KHR_texture_transform=dict(offset=[0.5, 0], scale=[0.5, 1]))))
        g.js['extensionsUsed'] = ['KHR_texture_transform']
        g.js['extensionsRequired'] = ['KHR_texture_transform']
        g.mesh([F.quad_prim(g, material=m)])
        sc = self.load(g.glb(os.path.join(self.d, 'tt.glb')))
        self.assertAlmostEqual(float(sc.parts[0].UV[1][0]), 1.0)
        self.assertAlmostEqual(float(sc.parts[0].UV[0][0]), 0.5)
        self.assertEqual(sc.warnings, [])

    def test_embedded_buffers_and_data_uri_image(self):
        import base64
        g = F.G()
        t = g.image_uri('data:image/png;base64,' + base64.b64encode(F.png()).decode())
        g.mesh([F.quad_prim(g, material=g.material(tex=t))])
        p = g.gltf(os.path.join(self.d, 'emb.gltf'), embedded=True)
        r, b = self.through(p)
        self.assertEqual(len(self.load(p).images), 1)

    def test_separate_files_with_spaces_in_names(self):
        g = F.G()
        g.mesh([F.quad_prim(g, material=g.material(tex=g.image_uri('my%20tex.png')))])
        F.write(os.path.join(self.d, 'my tex.png'), F.png())
        p = g.gltf(os.path.join(self.d, 'spaced name.gltf'))
        self.assertTrue(os.path.exists(os.path.join(self.d, 'spaced name.bin')))
        self.assertEqual(len(self.load(p).images), 1)

    def test_missing_bin_and_missing_image(self):
        g = F.G()
        g.mesh([F.quad_prim(g, material=g.material(tex=g.image_uri('gone.png'), color=[0.2, 0.4, 0.6, 1]))])
        p = g.gltf(os.path.join(self.d, 'a.gltf'))
        sc = self.load(p)
        self.assertTrue(any('texture file is missing' in w for w in sc.warnings))
        os.remove(os.path.join(self.d, 'a.bin'))
        self.assertIn('data file a.bin is missing', self.fails(p))

    def test_draco_required_gives_one_clear_line(self):
        g = F.G()
        g.mesh([F.quad_prim(g)])
        g.js['extensionsRequired'] = ['KHR_draco_mesh_compression']
        self.assertIn('Draco', self.fails(g.glb(os.path.join(self.d, 'd.glb'))))
        g2 = F.G()
        g2.mesh([F.quad_prim(g2)])
        g2.js['meshes'][0]['primitives'][0]['extensions'] = {'KHR_draco_mesh_compression': {'bufferView': 0, 'attributes': {}}}
        self.assertIn('Draco', self.fails(g2.glb(os.path.join(self.d, 'd2.glb'))))

    def test_material_extensions_are_ignored_even_when_required(self):
        g = F.G()
        m = g.material(color=[1, 0, 0, 1])
        g.js['materials'][m]['extensions'] = {'KHR_materials_emissive_strength': {'emissiveStrength': 2}, 'KHR_materials_clearcoat': {}}
        g.js['extensionsUsed'] = ['KHR_materials_emissive_strength', 'KHR_materials_clearcoat']
        g.js['extensionsRequired'] = ['KHR_materials_clearcoat']
        g.mesh([F.quad_prim(g, material=m)])
        sc = self.load(g.glb(os.path.join(self.d, 'ext.glb')))
        self.assertEqual(sc.warnings, [])
        g.js['extensionsRequired'] = ['VENDOR_something_new']
        sc = self.load(g.glb(os.path.join(self.d, 'ext2.glb')))
        self.assertTrue(any('not supported' in w for w in sc.warnings))

    def test_unknown_attributes_and_bad_alpha_mode(self):
        g = F.G()
        col = g.acc(np.ones((4, 4)), 5126, 'VEC4')
        m = g.material(alphaMode='WEIRD')
        g.mesh([F.quad_prim(g, material=m, extra_attr=dict(COLOR_0=col, _CUSTOM=col, JOINTS_0=col))])
        sc = self.load(g.glb(os.path.join(self.d, 'u.glb')))
        self.assertEqual(sc.parts[0].mat['alpha'], 'opaque')

    def test_webp_texture_and_junk_image_fall_back(self):
        g = F.G()
        t = g.image_view(b'RIFF\x10\x00\x00\x00WEBPVP8 junk', 'image/webp')
        g.js['textures'][t] = dict(extensions=dict(EXT_texture_webp=dict(source=0)))
        g.js['extensionsUsed'] = ['EXT_texture_webp']
        g.mesh([F.quad_prim(g, material=g.material(tex=t))])
        r, b = self.through(g.glb(os.path.join(self.d, 'w.glb')))
        self.assertTrue(any('could not be read' in w for w in b.warnings))

    def test_nul_padded_json_bom_and_glb_named_gltf(self):
        g = F.G()
        g.mesh([F.quad_prim(g)])
        self.assertEqual(len(self.load(g.glb(os.path.join(self.d, 'nul.glb'), pad=b'\0')).parts), 1)
        self.assertEqual(len(self.load(g.gltf(os.path.join(self.d, 'bom.gltf'), bom=True)).parts), 1)
        g.glb(os.path.join(self.d, 'binary.gltf'))
        self.assertEqual(len(self.load(os.path.join(self.d, 'binary.gltf')).parts), 1)

    def test_indices_out_of_range_skipped(self):
        g = F.G()
        g.mesh([g.prim(F.QUAD, [0, 1, 2, 0, 2, 9])])
        sc = self.load(g.glb(os.path.join(self.d, 'oor.glb')))
        self.assertEqual(len(sc.parts[0].tris), 1)
        self.assertTrue(any('missing points' in w for w in sc.warnings))

    def test_broken_files_give_plain_lines(self):
        g = F.G()
        g.mesh([F.quad_prim(g)])
        p = g.glb(os.path.join(self.d, 'ok.glb'))
        with open(p, 'rb') as f:
            data = f.read()
        self.fails(F.write(os.path.join(self.d, 'cut.glb'), data[:60]))
        self.fails(F.write(os.path.join(self.d, 'cut2.glb'), data[:len(data) - 40]))
        self.fails(F.write(os.path.join(self.d, 'junk.glb'), b'glTF' + os.urandom(100)))
        self.fails(F.write(os.path.join(self.d, 'junk.gltf'), b'{"hello": 1}'))
        self.fails(F.write(os.path.join(self.d, 'text.gltf'), b'not json'))
        self.fails(F.write(os.path.join(self.d, 'v1.gltf'), b'{"asset": {"version": "1.0"}}'))
        self.assertIn('no triangle', self.fails(F.write(os.path.join(self.d, 'empty.gltf'), b'{"asset": {"version": "2.0"}}')))

    def test_skinned_mesh_ignores_its_node_transform(self):
        g = F.G()
        g.mesh([F.quad_prim(g)], skin=0, translation=[100, 0, 0])
        g.js['skins'] = [dict(joints=[0])]
        sc = self.load(g.glb(os.path.join(self.d, 'sk.glb')))
        self.assertEqual(float(sc.parts[0].P[:, 0].max()), 1.0)

    def test_node_transforms_and_mirrored_scale(self):
        g = F.G()
        g.mesh([F.quad_prim(g)], translation=[10, 0, 0], scale=[-2, 2, 2])
        sc = self.load(g.glb(os.path.join(self.d, 'x.glb')))
        self.assertEqual(sorted(set(sc.parts[0].P[:, 0].round(3).tolist())), [8.0, 10.0])

    def test_blender_293_shape_end_to_end(self):
        """Blender 2.93's exporter: ushort indices, a PNG in the buffer, doubleSided, no extensions required."""
        g = F.G('Khronos glTF Blender I/O v1.7.33')
        t = g.image_view(F.png())
        m = g.material(tex=t, doubleSided=True)
        g.js['textures'][t]['sampler'] = 0
        g.js['samplers'] = [dict(magFilter=9729, minFilter=9987)]
        g.mesh([F.quad_prim(g, material=m)], name='Cube')
        r, b = self.through(g.glb(os.path.join(self.d, 'b293.glb')))
        self.assertTrue(r['textured'])
        self.assertEqual(r['warnings'], [])


class TestServerMessages(Base):
    def test_unexpected_failure_shows_one_plain_line(self):
        from todms import server
        from todms import imports
        with patch.object(imports, 'preview', side_effect=RuntimeError('boom [3,4] shape (3,)')):
            with self.assertRaises(server.ApiError) as cm:
                server._apierr(lambda: imports.preview(None, {}))
        self.assertNotIn('boom', str(cm.exception.args))


if __name__ == '__main__':
    unittest.main()
