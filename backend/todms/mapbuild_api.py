"""Routes of the in-map building tools (todms.mapbuild). server.py merges GET and POST into its tables.
Every body carries `map` = ONE map of the recipe (only its generator keys matter); answers are small and cached by the hash of those keys."""
from . import mapbuild
from .mapgen.core import MapgenError


def _srv():
    from . import server
    return server


def _guard(fn):
    try:
        return fn()
    except MapgenError as e:
        raise _srv().ApiError(400, str(e))
    except (KeyError, ValueError, TypeError) as e:
        raise _srv().ApiError(400, 'The map could not be read: %s' % e)


def h_field(q, body):
    return _guard(lambda: mapbuild.field(body.get('map') or {}))


def h_preview(q, body):
    return _guard(lambda: mapbuild.preview(body.get('map') or {}, bool(body.get('ground')), bool(body.get('collision'))))


def h_heightmap(q, body):
    def run():
        if body.get('action') == 'import':
            return dict(terrain=mapbuild.heightmap_import(body))
        return mapbuild.heightmap_export(body.get('map') or {}, body.get('kind', 'png'))
    return _guard(run)


def h_plan(q, body):
    return _guard(lambda: mapbuild.simulate(body.get('map') or {}, body.get('plan') or [], body.get('loaders') or [], body.get('path') or []))


def h_topdown(q, body):
    return _guard(lambda: mapbuild.top_down(body.get('map') or {}, int(body.get('size', 256)), float(body.get('contrast', 1.0))))


def h_minimap(q, body):
    from . import minimap
    srv = _srv()
    assets = None
    try:
        from . import assetindex
        assets = assetindex.load(None)
    except Exception:                                                  # noqa: BLE001
        assets = None
    test = body.get('test')
    mp = dict(body.get('map') or {})
    info = (mp.get('scene') or {}).get('plan')
    if info and body.get('pid'):                                       # a scene map: its plan (streets, buildings, water) is kept in the project folder
        from . import newmap, scenplan
        try:
            mp['_plan'] = scenplan.read(newmap.directory(str(body['pid'])), info)
        except ValueError:
            mp['_plan'] = None
    try:
        return minimap.preview(mp, assets, int(body.get('size', 512)), [float(test[0]), float(test[1])] if test else None)
    except minimap.MinimapError as e:
        raise srv.ApiError(400, str(e))
    except MapgenError as e:
        raise srv.ApiError(400, str(e))
    except (KeyError, ValueError, TypeError) as e:
        raise srv.ApiError(400, 'The map could not be read: %s' % e)


def h_bake(q, body):
    from . import bakeprev
    return _guard(lambda: bakeprev.preview(body.get('map') or {}, str(body.get('quality') or 'draft')))


def h_looks(q, body):
    return mapbuild.look_presets()


def h_kits(q, body):
    srv = _srv()
    return mapbuild.kits(srv.need_game())


GET = {'/api/mapbuild/looks': h_looks, '/api/mapbuild/kits': h_kits}
POST = {'/api/mapbuild/field': h_field, '/api/mapbuild/preview': h_preview, '/api/mapbuild/heightmap': h_heightmap,
        '/api/mapbuild/plan': h_plan, '/api/mapbuild/topdown': h_topdown, '/api/mapbuild/minimap': h_minimap,
        '/api/mapbuild/bake': h_bake}
