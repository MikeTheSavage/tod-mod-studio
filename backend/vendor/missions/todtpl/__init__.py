"""TOD Mod Studio mission TEMPLATE library: 17 mission types you place on YOUR map and tune with parameters.

    import templates                                   # (or the vendored package name)
    templates.list_templates()                        # ['showdown', 'stunt', ...]
    templates.template_schema('ghost', host)          # parameter schema (+ defaults laid out on a host) for the UI
    templates.free_indices(base_archives, used=())    # the fixed pool of mission indices still free
    templates.validate(project, base_archives)        # plain-language messages per mission
    templates.build(project, base_archives, out_dir)  # the package zips + manifest + lint

See README.md.
"""
import sys
sys.dont_write_bytecode = True
from .tpl_build import build, validate, list_templates, template_schema, BuildError, migrate_save_copy, make_plan  # noqa: F401
from .tpl_core import free_indices, pool, pool_message, P, ParamError  # noqa: F401
from . import tpl_env  # noqa: F401
