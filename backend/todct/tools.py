"""Import the project's verified TOD tools for the core.

The tools are Mod Studio's vendored copy (backend/vendor/tools), already on sys.path through
todms.paths.setup_tools().
The core needs: fragment_writer (fragtool, fragedit, todfrag, todblock), model_writer (todmodel, model_writer,
model_edit) and todcoll. model_edit / model_writer insert their own folders at the FRONT of sys.path when imported;
that order is restored here so the host's module choice (e.g. Mod Studio's newer tod_model_extract) stays.
"""
import importlib
import os
import sys

# env TOD_TOOLS overrides; the default is Mod Studio's vendored copy (backend/vendor/tools)
DEFAULT_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vendor', 'tools')
_mods = None


def tools_dir():
    return os.environ.get('TOD_TOOLS') or DEFAULT_TOOLS


def _importable(name):
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _patch_hulls(mw):
    """The gift-wrapping hull stacks a triangle on every coplanar point triple; a blob shadow darkens once per layer.
    Every hull Mod Studio builds goes through model_writer.convex_hull, so it is cleaned to one fan per plane here."""
    if getattr(mw.convex_hull, 'one_layer', False):
        return
    from . import hullclean
    raw = mw.convex_hull

    def convex_hull(points, eps=1e-6):
        V, F = raw(points, eps)
        return hullclean.clean(V, F)
    convex_hull.one_layer = True
    mw.convex_hull = convex_hull
    shape = mw.hull_shape

    def hull_shape(verts, faces, *a, **kw):
        hullclean.audit(verts, faces, kw.get('aux_name') or '')
        return shape(verts, faces, *a, **kw)
    mw.hull_shape = hull_shape


def load():
    """-> namespace with ft, fe, tf, tb, tm, mw, me (model_edit), tc."""
    global _mods
    if _mods is not None:
        return _mods
    sys.dont_write_bytecode = True
    root = tools_dir()
    if not _importable('fragtool'):
        for sub in ('fragment_writer',):
            p = os.path.join(root, sub)
            if p not in sys.path:
                sys.path.insert(0, p)
    before = list(sys.path)
    if not _importable('todmodel'):
        for sub in ('model_writer',):
            p = os.path.join(root, sub)
            if os.path.isdir(p) and p not in sys.path:
                sys.path.append(p)
    import fragtool as ft
    import fragedit as fe
    import todfrag as tf
    import todblock as tb
    import todcoll as tc
    import todmodel as tm
    import model_writer as mw
    import model_edit as me
    # model_edit put model_writer and model_writer/proj first: restore the host's order (keep any new entries last)
    added = [p for p in sys.path if p not in before]
    sys.path[:] = before + [p for p in added if p not in before]

    _patch_hulls(mw)

    class NS:
        pass
    ns = NS()
    ns.ft, ns.fe, ns.tf, ns.tb, ns.tc, ns.tm, ns.mw, ns.me = ft, fe, tf, tb, tc, tm, mw, me
    _mods = ns
    return ns


_more = {}
# module -> tool folder (part B: routes, missions, sections). Each folder is appended to sys.path only when the module
# is not importable yet (Mod Studio's vendored copies are already on the path), and sys.path is restored afterwards
# because some tools insert their own folder at the front on import (missiontool does).
MORE = {'submaptool': 'level_streaming', 'nodemap': 'save_editor', 'navtool': 'navigation',
        'missiontool': 'missions', 'missionenums': 'missions', 'transitions': 'seamless'}


def load_more(name):
    """Import one of the part-B tools (navtool, missiontool, submaptool, nodemap, transitions) after load()."""
    if name in _more:
        return _more[name]
    load()
    before = list(sys.path)
    if not _importable(name):
        p = os.path.join(tools_dir(), MORE[name])
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
        if name == 'submaptool':                       # submaptool needs nodemap (save_editor) too
            q = os.path.join(tools_dir(), 'save_editor')
            if os.path.isdir(q) and q not in sys.path:
                sys.path.append(q)
    mod = importlib.import_module(name)
    added = [p for p in sys.path if p not in before]
    sys.path[:] = before + added
    _more[name] = mod
    return mod
