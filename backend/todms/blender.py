"""The Blender bridge: models sent from Blender land in the model import screen.

  receive(settings, body)   the add-on's POST: a model (an exported .glb, or an .obj with its .mtl and pictures) into the cache
  pending()                 the screen asks which models arrived since it last looked (once each)
  announce(port, on)        a one-line file in the user folder that tells the add-on which port the running app listens on
  addon_text()              the add-on itself (one .py, Blender 2.79 to 5.x)

Localhost only, off until switched on in Settings. A request that comes from a web page (it carries an Origin) is refused, and the
add-on has to send its own header, which a page cannot do without a pre-flight the server never answers.
"""
import base64
import os
import re
import threading
import time

from . import paths

MAX_BYTES = 256 * 1024 * 1024
OK_EXT = ('.obj', '.mtl', '.glb', '.gltf', '.bin', '.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.webp', '.tif', '.tiff')
MODEL_EXT = ('.glb', '.gltf', '.obj')
HEADER = 'X-TODMS-Bridge'
PORT_FILE = 'blender_port.txt'
_lock = threading.Lock()
_queue = []


class BridgeError(ValueError):
    def __init__(self, msg, code=400):
        ValueError.__init__(self, msg)
        self.code = code


def _dir():
    d = os.path.join(paths.cache_dir(), 'blender')
    os.makedirs(d, exist_ok=True)
    return d


def _clean(rel):
    """A relative file name from the add-on, made safe: no drive, no .., plain characters only."""
    parts = [p for p in re.split(r'[\\/]+', str(rel)) if p and p not in ('.', '..') and ':' not in p]
    parts = [re.sub(r'[^\w .()+\-]', '_', p)[:80] for p in parts][:4]
    return os.path.join(*parts) if parts else ''


def _prune(keep=12):
    base = _dir()
    subs = sorted((os.path.join(base, d) for d in os.listdir(base)), key=os.path.getmtime)
    import shutil
    for d in subs[:-keep]:
        shutil.rmtree(d, ignore_errors=True)


def receive(settings, body):
    if not settings.get('blender_bridge'):
        raise BridgeError('Send from Blender is off. Switch it on in Settings.', 403)
    files = (body or {}).get('files')
    if not isinstance(files, list) or not files:
        raise BridgeError('nothing was sent')
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-%03d' % (int(time.time() * 1000) % 1000)
    out = os.path.join(_dir(), stamp)
    main, total = None, 0
    os.makedirs(out, exist_ok=True)
    for f in files:
        rel = _clean((f or {}).get('name', ''))
        if not rel or os.path.splitext(rel)[1].lower() not in OK_EXT:
            continue
        try:
            data = base64.b64decode(f.get('data') or '', validate=False)
        except Exception:                                      # noqa: BLE001
            raise BridgeError('the data could not be read')
        total += len(data)
        if total > MAX_BYTES:
            raise BridgeError('the model is too big to send')
        fn = os.path.join(out, rel)
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with open(fn, 'wb') as fh:
            fh.write(data)
        if os.path.splitext(rel)[1].lower() in MODEL_EXT and (main is None or rel == _clean(body.get('main', ''))):
            main = fn
    if main is None:
        raise BridgeError('no model file came with it')
    item = dict(path=main, name=os.path.splitext(os.path.basename(main))[0], app=str(body.get('app') or '')[:40])
    with _lock:
        _queue.append(item)
    _prune()
    return dict(ok=True, name=item['name'])


def pending():
    with _lock:
        out = list(_queue)
        del _queue[:]
    return out


def clear():
    with _lock:
        del _queue[:]


def port_file():
    return os.path.join(paths.user_dir(), PORT_FILE)


def announce(port, on):
    """The add-on reads this file when its port field is 0 (automatic)."""
    try:
        if on:
            with open(port_file(), 'w') as f:
                f.write(str(int(port)))
        elif os.path.exists(port_file()):
            os.remove(port_file())
    except OSError:
        pass


def addon_path():
    return os.path.join(paths.DATA, 'blender', 'tod_mod_studio.py')


def addon_text():
    with open(addon_path(), 'rb') as f:
        return f.read()
