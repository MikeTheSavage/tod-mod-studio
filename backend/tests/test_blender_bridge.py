"""The Blender bridge: the receiving end (todms/blender.py and its routes) and the add-on file (data/blender/tod_mod_studio.py).

The add-on runs inside Blender 2.79 to 5.x, so its version branches are tested here with a stand-in `bpy`; the real thing is proven
by the importer's own run of Blender 4.5 (see NOTES).
"""
import ast
import base64
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, HERE)
ADDON = os.path.join(ROOT, 'backend', 'data', 'blender', 'tod_mod_studio.py')
import meshfix as F  # noqa: E402


def load_addon(version=None):
    """The add-on module. version=None: no Blender (plain functions only); else a stand-in bpy of that version."""
    name = 'todms_addon_test'
    sys.modules.pop(name, None)
    if version is None:
        sys.modules.pop('bpy', None)
    else:
        bpy = types.ModuleType('bpy')
        bpy.app = types.SimpleNamespace(version=version)
        bpy.types = types.SimpleNamespace(Operator=object, Panel=object, WindowManager=types.SimpleNamespace())
        bpy.utils = types.SimpleNamespace(registered=[], register_class=lambda c: bpy.utils.registered.append(c),
                                          unregister_class=lambda c: bpy.utils.registered.remove(c))
        props = types.ModuleType('bpy.props')
        props.IntProperty = lambda **kw: ('int', kw)
        props.EnumProperty = lambda **kw: ('enum', kw)
        bpy.props = props
        sys.modules['bpy'], sys.modules['bpy.props'] = bpy, props
    spec = importlib.util.spec_from_file_location(name, ADDON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAddonFile(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop('bpy', None)
        sys.modules.pop('bpy.props', None)

    def test_python_35_syntax(self):
        """Blender 2.79 ships Python 3.5: no f-strings, no variable annotations, no type hints."""
        src = open(ADDON, encoding='utf-8').read()
        tree = ast.parse(src, feature_version=(3, 5))
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.JoinedStr, ast.AnnAssign))])
        self.assertFalse(re.search(r'\bf["\']', src))
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef):
                self.assertIsNone(n.returns)
                self.assertTrue(all(a.annotation is None for a in n.args.args))
        info = [n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'bl_info'][0]
        bl = ast.literal_eval(info.value)
        self.assertEqual(bl['blender'], (2, 79, 0))

    def test_version_branches(self):
        a = load_addon()
        self.assertFalse(a.new_api((2, 79, 0)))
        self.assertTrue(a.new_api((2, 80, 0)) and a.new_api((5, 3, 0)))
        self.assertEqual(a.region_type((2, 79, 0)), 'TOOLS')
        self.assertEqual(a.region_type((2, 93, 0)), 'UI')
        self.assertEqual(a.default_format((2, 79, 0)), 'OBJ')
        self.assertEqual(a.default_format((2, 82, 0)), 'OBJ')
        self.assertEqual(a.default_format((2, 93, 0)), 'GLB')
        # (version, has gltf, has wm.obj_export, has export_scene.obj, want) -> exporter
        cases = [((2, 79, 0), False, False, True, 'GLB', 'obj_old'),
                 ((2, 79, 0), False, False, True, 'OBJ', 'obj_old'),
                 ((2, 93, 0), True, False, True, 'GLB', 'gltf'),
                 ((2, 93, 0), True, False, True, 'OBJ', 'obj_old'),
                 ((3, 6, 0), True, True, True, 'OBJ', 'obj_new'),
                 ((4, 5, 9), True, True, False, 'OBJ', 'obj_new'),
                 ((4, 5, 9), True, True, False, 'GLB', 'gltf'),
                 ((5, 3, 0), True, True, False, 'GLB', 'gltf'),
                 ((5, 3, 0), False, True, False, 'GLB', 'obj_new')]
        for ver, g, wm, old, want, exp in cases:
            self.assertEqual(a.pick_exporter(ver, g, wm, old, want)[0], exp, (ver, want))
        self.assertIsNone(a.pick_exporter((2, 79, 0), False, False, False, 'OBJ')[0])
        self.assertIn('glTF', a.pick_exporter((2, 79, 0), False, False, True, 'GLB')[1])

    def test_register_under_each_version(self):
        for ver, region, cat in (((2, 79, 0), 'TOOLS', 'TOD'), ((2, 93, 0), 'UI', 'TOD Mod Studio'), ((4, 5, 9), 'UI', 'TOD Mod Studio'),
                                 ((5, 3, 0), 'UI', 'TOD Mod Studio')):
            a = load_addon(ver)
            self.assertEqual(a.TODMS_PT_panel.bl_region_type, region)
            self.assertEqual(a.TODMS_PT_panel.bl_category, cat)
            a.register()
            import bpy
            self.assertEqual(len(bpy.utils.registered), 2)
            self.assertEqual(bpy.types.WindowManager.todms_format[1]['default'], 'OBJ' if ver < (2, 83, 0) else 'GLB')
            a.unregister()
            self.assertEqual(bpy.utils.registered, [])
            self.assertFalse(hasattr(bpy.types.WindowManager, 'todms_port'))

    def test_port_lookup_and_file_collection(self):
        a = load_addon()
        tmp = tempfile.mkdtemp()
        try:
            with patch.dict(os.environ, APPDATA=tmp):
                self.assertEqual(a.find_port(0), 0)
                os.makedirs(os.path.join(tmp, 'TODModStudio'))
                F.write(os.path.join(tmp, 'TODModStudio', 'blender_port.txt'), '4321\n')
                self.assertEqual(a.find_port(0), 4321)
                self.assertEqual(a.find_port(99), 99)
            F.write(os.path.join(tmp, 'out', 'a.obj'), 'v 0 0 0')
            F.write(os.path.join(tmp, 'out', 'tex', 'b.png'), b'x')
            F.write(os.path.join(tmp, 'out', 'junk.exe'), b'x')
            names = sorted(f['name'] for f in a.collect(os.path.join(tmp, 'out')))
            self.assertEqual(names, ['a.obj', 'tex/b.png'])
            self.assertEqual(a.safe_name('my/ugly:name?'), 'my_ugly_name_')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nothing_listening_gives_a_plain_line(self):
        a = load_addon()
        ok, msg = a.post_model(1, [], 'a.obj', 'Blender 4.5')
        self.assertFalse(ok)
        self.assertIn('not running', msg)


class TestBridgeServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='bridge')
        self.env = patch.dict(os.environ, TODMS_HOME=os.path.join(self.tmp, 'home'), TODMS_CACHE=os.path.join(self.tmp, 'cache'),
                              TODMS_SAVES=os.path.join(self.tmp, 'saves'))
        self.env.start()
        from todms import server, blender
        self.server, self.blender = server, blender
        self.srv = server.serve(0)
        self.port = self.srv.server_address[1]
        self.ws = server.ws()
        blender.clear()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, files, headers=None, main='a.obj'):
        body = json.dumps(dict(files=files, main=main, app='Blender 4.5')).encode()
        req = urllib.request.Request('http://127.0.0.1:%d/api/blender/send' % self.port, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        for k, v in (headers if headers is not None else {'X-TODMS-Bridge': '1'}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    @staticmethod
    def f(name, data=b'v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n'):
        return dict(name=name, data=base64.b64encode(data).decode())

    def test_off_by_default_and_needs_its_header(self):
        self.ws.settings['blender_bridge'] = False
        code, r = self.post([self.f('a.obj')])
        self.assertEqual(code, 403)
        self.assertIn('Settings', r['error'])
        self.ws.settings['blender_bridge'] = True
        self.assertEqual(self.post([self.f('a.obj')], headers={})[0], 403)                      # no header
        self.assertEqual(self.post([self.f('a.obj')], headers={'X-TODMS-Bridge': '1', 'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.post([self.f('a.obj')], headers={'X-TODMS-Bridge': '1', 'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.blender.pending(), [])

    def test_a_model_arrives_once_and_opens(self):
        self.ws.settings['blender_bridge'] = True
        code, r = self.post([self.f('a.obj'), self.f('a.mtl', b'newmtl x\n'), self.f('tex/t.png', F.png())])
        self.assertEqual((code, r['name']), (200, 'a'))
        items = self.blender.pending()
        self.assertEqual(len(items), 1)
        self.assertTrue(os.path.isfile(items[0]['path']))
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(items[0]['path']), 'tex', 't.png')))
        self.assertEqual(self.blender.pending(), [])
        from todms import imports
        self.assertEqual(imports.analyze(items[0]['path'])['stats']['triangles'], 1)

    def test_unsafe_names_and_kinds_are_dropped(self):
        self.ws.settings['blender_bridge'] = True
        code, r = self.post([self.f('../../evil.glb'), self.f('C:/x/evil.exe'), self.f('ok.obj')], main='ok.obj')
        self.assertEqual(code, 200)
        p = self.blender.pending()[0]['path']
        folder = os.path.dirname(p)
        self.assertEqual(sorted(os.listdir(folder)), ['evil.glb', 'ok.obj'])         # the .. was dropped, the .exe never written
        self.assertEqual(self.post([self.f('x.exe')])[0], 400)
        self.assertEqual(self.post([])[0], 400)

    def test_port_file_follows_the_switch(self):
        self.blender.announce(self.port, True)
        self.assertEqual(open(self.blender.port_file()).read(), str(self.port))
        self.blender.announce(self.port, False)
        self.assertFalse(os.path.exists(self.blender.port_file()))

    def test_add_on_text_ships_and_round_trips_through_the_add_on(self):
        self.assertIn(b'bl_info', self.blender.addon_text())
        self.ws.settings['blender_bridge'] = True
        a = load_addon()
        out = os.path.join(self.tmp, 'out')
        F.write(os.path.join(out, 'cube.obj'), 'v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 3\n')
        ok, msg = a.post_model(self.port, a.collect(out), 'cube.obj', 'Blender 4.5')
        self.assertTrue(ok, msg)
        self.assertEqual(self.blender.pending()[0]['name'], 'cube')
        self.ws.settings['blender_bridge'] = False
        ok, msg = a.post_model(self.port, a.collect(out), 'cube.obj', 'Blender 4.5')
        self.assertFalse(ok)
        self.assertIn('Settings', msg)


if __name__ == '__main__':
    unittest.main()
