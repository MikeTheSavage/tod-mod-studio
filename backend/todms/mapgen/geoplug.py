"""Teach the map builder's geometry step the generated `mapgen` model part.

The vendored geometry kit (vendor/newmap/geomkit.py, newgeo.py) builds a model from parts of four shipped types. A generated model
carries one part {"type": "mapgen", ...} (triangle meshes per texture and convex collision pieces, see meshkit.py). `install()` wraps
newgeo.make_models so that part is poured into the model builder before the model is encoded; nothing in the vendored files changes
and an old builder that never calls install() refuses the unknown part type instead of building an empty model.

Call install() once in the process that runs the map builder (expand() does it for you: the build follows in the same process).
"""
import os
import sys

from . import core
from .meshkit import read_part
from .core import SURF_WORDS

_VENDOR = os.path.join(core.BACKEND, 'vendor', 'newmap')
PENDING = {}
_state = {}
ALPHA = {}                                   # texture short name -> 'cutout' | 'blend' for the build in progress
SMB_FLAGS = {'cutout': 0xBA1BC040, 'blend': 0xBA1BC020}      # the submesh flags of shipped cut-out foliage and of shipped glass


def set_alpha(kinds):
    """Texture short names that carry alpha (from the textures of the map's new_geometry) -> their kind, for the next build."""
    ALPHA.clear()
    ALPHA.update({k: v for k, v in (kinds or {}).items() if v in SMB_FLAGS})


def _modules():
    if _VENDOR not in sys.path:
        sys.path.append(_VENDOR)
    import geomkit
    import newgeo
    return geomkit, newgeo


def pour(mb, part):
    """Add one decoded `mapgen` part to a geomkit.ModelBuilder."""
    meshes, hulls = read_part(part)
    for m in meshes:
        g = mb.group(m['tex'])
        base = len(g.P)
        g.P += [tuple(float(c) for c in p) for p in m['P']]
        g.N += [tuple(float(c) for c in n) for n in m['N']]
        g.T += [tuple(float(c) for c in t) for t in m['T']]
        g.tris += [(base + int(a), base + int(b), base + int(c)) for a, b, c in m['I']]
    for pts, surf, mat in hulls:
        mb.hulls.append(([tuple(float(c) for c in p) for p in pts], SURF_WORDS[surf], mat))


def install():
    """Idempotent. -> True when the wrapper is active."""
    if _state.get('on'):
        return True
    GK, NG = _modules()
    Original = GK.ModelBuilder

    class MapgenBuilder(Original):
        def __init__(self, name):
            Original.__init__(self, name)
            for part in PENDING.pop(name, []):
                pour(self, part)

    orig_make = NG.make_models
    orig_spec = GK.build_spec

    def build_spec(mb, mw, tex_names, flags=None):
        spec = orig_spec(mb, mw, tex_names, flags)
        for ti, t in enumerate(mb.textures()):
            fl = SMB_FLAGS.get(ALPHA.get(t))
            if fl:
                spec['pivots'][0]['meshes'][ti]['smb_flags'] = fl
        return spec

    def make_models(spec_models, folder, tex, mw, tm, log):
        clean = []
        for md in spec_models:
            mg = [p for p in md.get('parts', []) if p.get('type') == 'mapgen']
            if mg:
                PENDING['/data/Models/%s/%s.model' % (folder, md['name'])] = mg
            clean.append(dict(md, parts=[p for p in md.get('parts', []) if p.get('type') != 'mapgen']))
        GK.ModelBuilder = MapgenBuilder
        GK.build_spec = build_spec
        try:
            return orig_make(clean, folder, tex, mw, tm, log)
        finally:
            GK.ModelBuilder = Original
            GK.build_spec = orig_spec
            PENDING.clear()

    NG.make_models = make_models
    _state.update(on=True, original=orig_make, geomkit=GK, newgeo=NG)
    return True


def uninstall():
    if _state.get('on'):
        _state['newgeo'].make_models = _state['original']
        _state.clear()
