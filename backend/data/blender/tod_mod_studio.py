# TOD Mod Studio: send the selected objects from Blender to the model import screen of a running Mod Studio.
# One file, Blender 2.79 to 5.x. Install: Edit > Preferences > Add-ons > Install (2.79) / Install from Disk (2.8 and later),
# pick this file, switch it on. The panel is in the 3D view sidebar (N key), tab "TOD Mod Studio".
# Mod Studio must be running with "Send from Blender" switched on in its Settings.
#
# Written for Python 3.5 (Blender 2.79): no f-strings and no variable annotations.

bl_info = {
    "name": "TOD Mod Studio",
    "author": "TOD Mod Studio",
    "version": (1, 0, 0),
    "blender": (2, 79, 0),
    "location": "3D View > Sidebar > TOD Mod Studio",
    "description": "Send the selection to TOD Mod Studio",
    "category": "Import-Export",
}

import base64
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request

try:
    import bpy
    from bpy.props import EnumProperty, IntProperty
except ImportError:          # imported outside Blender (tests of the plain functions)
    bpy = None

SEND_EXT = ('.obj', '.mtl', '.glb', '.gltf', '.bin', '.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.webp', '.tif', '.tiff')
MAX_BYTES = 200 * 1024 * 1024


# ------------------------------------------------------------------------------------------------ the plain functions (no Blender needed)
def new_api(version):
    """Blender 2.80 and later: annotations for properties, the sidebar is the UI region, wm.obj_export instead of export_scene.obj."""
    return tuple(version) >= (2, 80, 0)


def pick_exporter(version, has_gltf, has_wm_obj, has_old_obj, want):
    """-> ('gltf'|'obj_new'|'obj_old'|None, note). want: 'GLB' or 'OBJ'."""
    if want == 'GLB' and has_gltf:
        return 'gltf', ''
    note = ''
    if want == 'GLB':
        note = 'This Blender has no glTF exporter; sending an OBJ instead.'
    if has_wm_obj:
        return 'obj_new', note
    if has_old_obj:
        return 'obj_old', note
    return None, 'This Blender has no OBJ or glTF exporter.'


def default_format(version):
    """glTF where the exporter ships with Blender (2.83 and later), OBJ before."""
    return 'GLB' if tuple(version) >= (2, 83, 0) else 'OBJ'


def region_type(version):
    return 'UI' if new_api(version) else 'TOOLS'


def port_file():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'TODModStudio', 'blender_port.txt')


def find_port(typed):
    """The port typed in the panel, or (0) the one the running Mod Studio wrote down."""
    if typed and int(typed) > 0:
        return int(typed)
    try:
        with open(port_file()) as f:
            return int(f.read().strip())
    except (IOError, OSError, ValueError):
        return 0


def collect(folder):
    """-> [{name, data}] for every exported file under folder (names relative, forward slashes)."""
    out, total = [], 0
    for root, dirs, files in os.walk(folder):
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in SEND_EXT:
                continue
            full = os.path.join(root, fn)
            total += os.path.getsize(full)
            if total > MAX_BYTES:
                raise ValueError('The selection is too big to send.')
            with open(full, 'rb') as f:
                data = base64.b64encode(f.read()).decode('ascii')
            out.append({'name': os.path.relpath(full, folder).replace('\\', '/'), 'data': data})
    return out


def post_model(port, files, main, app):
    """POST to the running Mod Studio. -> (ok, message)"""
    body = json.dumps({'files': files, 'main': main, 'app': app}).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:%d/api/blender/send' % port, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-TODMS-Bridge', '1')
    try:
        r = urllib.request.urlopen(req, timeout=60)
        r.read()
        return True, 'Sent. It is open in the model import screen.'
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode('utf-8')).get('error') or ''
        except Exception:
            msg = ''
        return False, msg or 'Mod Studio refused it.'
    except (urllib.error.URLError, OSError):
        return False, 'Mod Studio is not running, or the port is wrong.'


def safe_name(name):
    s = ''.join(c if (c.isalnum() or c in ' _-.') else '_' for c in (name or 'model')).strip(' .')
    return s[:60] or 'model'


# ------------------------------------------------------------------------------------------------ inside Blender
def _export(context, folder, name, want):
    ops = bpy.ops
    ver = bpy.app.version
    kind, note = pick_exporter(ver, hasattr(ops.export_scene, 'gltf'), hasattr(ops.wm, 'obj_export'), hasattr(ops.export_scene, 'obj'), want)
    if kind == 'gltf':
        path = os.path.join(folder, name + '.glb')
        ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True)
    elif kind == 'obj_new':
        path = os.path.join(folder, name + '.obj')
        ops.wm.obj_export(filepath=path, export_selected_objects=True, path_mode='COPY')
    elif kind == 'obj_old':
        path = os.path.join(folder, name + '.obj')
        ops.export_scene.obj(filepath=path, use_selection=True, use_materials=True, path_mode='COPY')
    else:
        raise RuntimeError(note)
    return path, note


def _send(context, want, typed_port):
    sel = [o for o in context.selected_objects if o.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT')]
    if not sel:
        return False, 'Select a mesh first.'
    port = find_port(typed_port)
    if not port:
        return False, 'Type the port shown in Mod Studio Settings.'
    folder = tempfile.mkdtemp(prefix='todms_')
    try:
        name = safe_name(sel[0].name if len(sel) == 1 else (bpy.path.display_name_from_filepath(bpy.data.filepath) or sel[0].name))
        try:
            path, note = _export(context, folder, name, want)
        except Exception as e:
            return False, 'The export failed: ' + str(e).strip().splitlines()[-1][:120] if str(e).strip() else 'The export failed.'
        try:
            files = collect(folder)
        except ValueError as e:
            return False, str(e)
        ok, msg = post_model(port, files, os.path.basename(path), 'Blender ' + '.'.join(str(x) for x in bpy.app.version[:2]))
        return ok, (note + ' ' + msg).strip() if ok else msg
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if bpy is not None:
    class TODMS_OT_send(bpy.types.Operator):
        bl_idname = "todms.send"
        bl_label = "Send to Mod Studio"
        bl_description = "Send the selected objects to the model import screen of TOD Mod Studio"

        def execute(self, context):
            wm = context.window_manager
            ok, msg = _send(context, wm.todms_format, wm.todms_port)
            self.report({'INFO'} if ok else {'ERROR'}, msg)
            return {'FINISHED'} if ok else {'CANCELLED'}

    class TODMS_PT_panel(bpy.types.Panel):
        bl_label = "TOD Mod Studio"
        bl_idname = "TODMS_PT_panel"
        bl_space_type = 'VIEW_3D'
        bl_region_type = region_type(bpy.app.version)
        bl_category = "TOD Mod Studio" if new_api(bpy.app.version) else "TOD"

        def draw(self, context):
            wm = context.window_manager
            col = self.layout.column()
            col.prop(wm, "todms_format", text="Format")
            col.prop(wm, "todms_port", text="Port")
            col.operator("todms.send", icon='EXPORT')

    _CLASSES = (TODMS_OT_send, TODMS_PT_panel)

    def register():
        bpy.types.WindowManager.todms_port = IntProperty(
            name="Port", description="0 finds the running Mod Studio by itself; otherwise the port shown in its Settings",
            default=0, min=0, max=65535)
        bpy.types.WindowManager.todms_format = EnumProperty(
            name="Format", items=(('GLB', "glTF (.glb)", "Best for most models"), ('OBJ', "OBJ", "OBJ with its textures")),
            default=default_format(bpy.app.version))
        for c in _CLASSES:
            bpy.utils.register_class(c)

    def unregister():
        for c in reversed(_CLASSES):
            bpy.utils.unregister_class(c)
        del bpy.types.WindowManager.todms_port
        del bpy.types.WindowManager.todms_format

    if __name__ == "__main__":
        register()
