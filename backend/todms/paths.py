"""Where things live: the app's own folders, the vendored tools, the per-user data folder."""
import os
import sys

FROZEN = getattr(sys, 'frozen', False)
# backend/ in a source checkout; the PyInstaller bundle root when frozen
if FROZEN:
    BACKEND = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(BACKEND, 'vendor', 'tools')
DATA = os.path.join(BACKEND, 'data')
WEB = os.path.join(BACKEND, 'web')

APP_NAME = 'TODModStudio'


def user_dir():
    """Settings, mod library and backups: %APPDATA%/TODModStudio (override: TODMS_HOME)."""
    d = os.environ.get('TODMS_HOME') or os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir():
    """Extracted meshes, textures, level layouts: %LOCALAPPDATA%/TODModStudio/cache (override: TODMS_CACHE)."""
    d = os.environ.get('TODMS_CACHE') or os.path.join(
        os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), APP_NAME, 'cache')
    os.makedirs(d, exist_ok=True)
    return d


def tables_dir():
    d = os.path.join(cache_dir(), 'tables')
    os.makedirs(d, exist_ok=True)
    return d


_tools_ready = False


def setup_tools(naz=None):
    """Make the vendored tools importable. The fragment writer goes first: every tool folder carries an identical copy
    of todblock/todfrag/fragedit/fragtool, so one copy is shared. TOD_NAZ tells every tool which blocks.naz to read."""
    global _tools_ready
    os.environ['TOD_TABLES_DIR'] = tables_dir()
    if naz:
        os.environ['TOD_NAZ'] = naz
    if _tools_ready:
        return
    order = ['fragment_writer', '', 'level_streaming', 'save_editor', 'missions', 'collision', 'navigation',
             'weapons', 'vehicles', 'loco', 'camera', 'limits', 'model_writer', 'seamless']
    for i, sub in enumerate(order):
        p = os.path.join(VENDOR, sub) if sub else VENDOR
        if p not in sys.path:
            sys.path.insert(i, p)
    sys.dont_write_bytecode = True
    _tools_ready = True


_guard_done = False


def ensure_cpu_guard():
    """Keep this process off CPU cores that divide packed floats wrongly (faulty cores found on the lab machine). Cheap, once,
    and a no-op everywhere else. Imported before any build that uses numpy (map textures, collision, missions)."""
    global _guard_done
    if _guard_done:
        return
    _guard_done = True
    p = os.path.join(BACKEND, 'vendor', 'newmap')
    if p not in sys.path:
        sys.path.append(p)
    try:
        import cpu_guard  # noqa: F401  (guards at import)
    except Exception:
        pass
