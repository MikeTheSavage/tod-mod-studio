"""tpl_env.py - the ONLY place that knows where the TOD tool chain lives.

The templates need: the block/fragment tools (todct: blockedit.Builder, tools.load -> ft/fe/tf/tb), the text tool (textool: edit text rows),
the mission linter (missiontool.check), the new-map recipe (make_new_map.build) and the base_overlay (read a Gameplay+ data zip instead of
the shipped blocks). All of them are imported IN PROCESS (no subprocess, no env-var-only switches).

A host application (TOD Mod Studio) that already has these modules on sys.path calls  configure(...)  with its own locations (or pre-imports the
modules: anything already in sys.modules is used as is). Defaults come from environment variables and the vendored layout.

    from templates import tpl_env
    tpl_env.configure(blocks_naz=r'C:\\GOG Games\\Total Overdose\\blocks.naz')
    E = tpl_env.get()          # namespace: ft fe tf tb BE T SHARED MAIN read() textool missiontool make_map overlay
"""
import contextlib, importlib, io, os, sys
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
NEW_CONTENT = os.path.dirname(os.path.dirname(HERE))                  # the new_content work folder (upstream layout)

CFG = dict(
    blocks_naz=os.environ.get('TOD_NAZ') or r'C:\GOG Games\Total Overdose\blocks.naz',   # the base game's blocks.naz (read only)
    backend=os.environ.get('TODMS_BACKEND') or os.path.dirname(os.path.dirname(os.path.dirname(HERE))),   # todms + todct (Mod Studio's backend)
    maps_tools=os.path.join(NEW_CONTENT, 'maps', 'tools'),            # make_new_map.py, base_overlay.py, cpu_guard.py, newgeo.py ...
    textool_dir=os.path.join(NEW_CONTENT, 'missions', 'work', 'texttool'),
    missiontool_dir=os.path.join(NEW_CONTENT, 'missions', 'tools'),
    home=os.path.join(NEW_CONTENT, 'missions', 'work', 'home'),
    cache=os.path.join(NEW_CONTENT, 'missions', 'work', 'cache'),
    shipped_strings=os.environ.get('TOD_SHIPPED_STRINGS', ''),        # dump of the shipped uk texts (optional: used for the blank-row check)
)
SHARED = 'data_pc/overdose_the_game/overdose/shared/'
MAIN = SHARED + 'overdose.main'
_NS = None


def configure(**kw):
    """override any CFG key (before the first get())"""
    global _NS
    for k, v in kw.items():
        if k not in CFG:
            raise KeyError('unknown setting %s' % k)
        if _NS is not None and CFG[k] != v:
            raise RuntimeError('tpl_env.configure(%s) after the tools were loaded; configure first' % k)
        CFG[k] = v


def _import_from(dirpath, name):
    """import module `name` found in dirpath, APPENDING dirpath to sys.path (never in front: the host's own copies win)"""
    if dirpath not in sys.path:
        sys.path.append(dirpath)
    return importlib.import_module(name)


class NS:
    pass


def get():
    """load (once) and return the tool namespace"""
    global _NS
    if _NS is not None:
        return _NS
    os.environ.setdefault('TODMS_HOME', CFG['home'])
    os.environ.setdefault('TODMS_CACHE', CFG['cache'])
    os.environ['TOD_NAZ'] = CFG['blocks_naz']
    if CFG['backend'] not in sys.path:
        sys.path.insert(0, CFG['backend'])
    if CFG['maps_tools'] not in sys.path:
        sys.path.append(CFG['maps_tools'])
    n = NS()
    n.cfg = CFG
    n.cpu_guard = importlib.import_module('cpu_guard')               # this machine's logical CPUs 4 and 5 divide packed floats wrongly
    n.overlay = importlib.import_module('base_overlay')
    try:
        from todms import paths
        paths.setup_tools(CFG['blocks_naz'])
    except ImportError:
        pass                                                          # the host already set its tools up
    from todct import tools, blockedit as BE
    M = tools.load()
    n.ft, n.fe, n.tf, n.tb = M.ft, M.fe, M.tf, M.tb
    n.BE = BE
    n.T = None
    n.SHARED, n.MAIN = SHARED, MAIN
    n.read = lambda e: n.ft.archive().read(e)
    n.types = lambda: n.ft.types()
    _NS = n
    return n


_TEXTOOL = _MISSIONTOOL = _MAKEMAP = None


def textool():
    global _TEXTOOL
    if _TEXTOOL is None:
        get()
        os.environ['TOD_NAZ'] = CFG['blocks_naz']
        if 'lowprio' not in sys.modules:                              # textool's lowprio lowers the process priority through ctypes: not wanted in a host app
            import types as _t
            sys.modules['lowprio'] = _t.ModuleType('lowprio')
        _TEXTOOL = _import_from(CFG['textool_dir'], 'textool')
        _TEXTOOL.GOG_NAZ = CFG['blocks_naz']
    return _TEXTOOL


def missiontool():
    global _MISSIONTOOL
    if _MISSIONTOOL is None:
        get()
        _MISSIONTOOL = _import_from(CFG['missiontool_dir'], 'missiontool')
    return _MISSIONTOOL


def make_map():
    global _MAKEMAP
    if _MAKEMAP is None:
        get()
        # make_new_map needs ITS OWN submaptool (maps_tools/level_streaming): a host app's older vendored copy may already sit in sys.modules and lacks clone_of_file
        # (new_geometry maps). Import the recipe against the recipe's copy, then put the host's copy back.
        saved = sys.modules.pop('submaptool', None)
        ls = os.path.join(CFG['maps_tools'], 'level_streaming')
        if ls not in sys.path:
            sys.path.insert(0, ls)
        try:
            _MAKEMAP = _import_from(CFG['maps_tools'], 'make_new_map')
        finally:
            recipe_st = sys.modules.get('submaptool')
            if saved is not None:
                sys.modules['submaptool'] = saved
        if recipe_st is not None and getattr(_MAKEMAP, 'S', None) is not recipe_st:
            raise RuntimeError('make_new_map did not bind the recipe submaptool')
    return _MAKEMAP


@contextlib.contextmanager
def quiet():
    """swallow stdout of the old tools that print progress"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def set_chain(base_archives, entries=None):
    """Point the overlay at the zips of the game's filesystem chain (see base_overlay.configure). Returns the entries served from a zip."""
    n = get()
    return n.overlay.configure(list(base_archives or []), entries)


def find_blocks_naz(base_archives):
    """the blocks.naz of a chain (first item whose file name is blocks.naz) or None"""
    for p in base_archives or []:
        if os.path.basename(str(p)).lower() == 'blocks.naz':
            return str(p)
    return None
