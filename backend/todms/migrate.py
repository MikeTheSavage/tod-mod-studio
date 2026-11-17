"""Opening an older mod upgrades it, after a backup copy (idea 92).

A recipe carries `schema`: the revision of the file layout (the recipe `version` is a different number: it says which kinds of content
the mod uses). A file with a lower schema is brought up one step at a time; every step is small and listed in STEPS. Before the first
change the original file is copied to <home>/migration_backups/. A file that is already current is never touched.

  library mods      upgraded when the library is listed or a mod is read (upgrade_library / upgrade_mod)
  .todmod files     upgraded in memory when imported (upgrade_object); the file on disk is only ever read
  autosave / saves  a project that comes back from the browser store passes through /api/mods/upgrade
"""
import datetime
import json
import os
import shutil

from . import modfile, paths

CURRENT = modfile.SCHEMA


def backup_dir():
    d = os.path.join(paths.user_dir(), 'migration_backups')
    os.makedirs(d, exist_ok=True)
    return d


def _step_1(m):
    """Recipes of the first tool: keys of a tool that is gone are dropped."""
    from todct import todmod
    before = set(m)
    todmod.legacy_keys(m)
    return ['dropped %s' % ', '.join(sorted(before - set(m)))] if before - set(m) else []


def _step_5(m):
    """Schema 5: the mod page and the requirements. Older mods get empty ones (version 1.0), nothing else changes."""
    notes = []
    if not isinstance(m.get('page'), dict):
        m['page'] = {}
        notes.append('added the mod page')
    m['page'].setdefault('version', '1.0')
    m['page'].setdefault('reuse', True)
    if not isinstance(m.get('requires'), dict):
        m['requires'] = {}
    return notes


STEPS = [(1, _step_1), (5, _step_5)]       # (schema this step produces, function(recipe) -> notes)


def schema_of(m):
    try:
        return int(m.get('schema') or 0)
    except (TypeError, ValueError):
        return 0


def needs_upgrade(m):
    return isinstance(m, dict) and m.get('format') == modfile.FORMATS['mod'] and schema_of(m) < CURRENT


def upgrade_object(m):
    """Bring a recipe up to the current schema in place. -> list of what changed (empty when it was current)."""
    if schema_of(m) > CURRENT:
        raise ValueError('This mod was made with a newer Mod Studio (file layout %d, this one reads up to %d). Update Mod Studio to open it.'
                         % (schema_of(m), CURRENT))
    notes = []
    have = schema_of(m)
    for to, fn in STEPS:
        if have < to:
            notes += fn(m)
    if have < CURRENT:
        m['schema'] = CURRENT
        notes.insert(0, 'file layout %d to %d' % (have, CURRENT))
    return notes


def backup_copy(src_path=None, obj=None, label='mod'):
    """Copy the original (a file, or an object that is about to change) into the backup folder. -> the backup path."""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    name = os.path.basename(src_path) if src_path else label + '.json'
    dst = os.path.join(backup_dir(), '%s_%s' % (stamp, name))
    if src_path and os.path.isfile(src_path):
        shutil.copy2(src_path, dst)
    else:
        with open(dst, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=1)
    return dst


def upgrade_mod(mid):
    """One library mod: backup, upgrade, write back. -> dict(upgraded=bool, notes, backup)."""
    from . import mods
    p = os.path.join(mods.lib_dir(), mid, 'mod.json')
    with open(p, encoding='utf-8') as f:
        m = json.load(f)
    if not needs_upgrade(m):
        return dict(upgraded=False, notes=[], backup=None)
    bak = backup_copy(src_path=p)
    notes = upgrade_object(m)
    tmp = p + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(m, f, indent=1)
    os.replace(tmp, p)
    return dict(upgraded=True, notes=notes, backup=bak)


def upgrade_library():
    from . import mods
    out = {}
    for d in sorted(os.listdir(mods.lib_dir())):
        if os.path.isfile(os.path.join(mods.lib_dir(), d, 'mod.json')):
            try:
                r = upgrade_mod(d)
            except (OSError, ValueError):
                continue
            if r['upgraded']:
                out[d] = r
    return out


def read_older(path):
    """Read a .todmod of any age for importing: the file is only read. -> (recipe upgraded in memory, notes, backup path or None).
    The backup copy is made when the layout had to change, so the person keeps the original even if they delete the file."""
    kind, obj, _ = modfile.read(path)
    if kind != 'mod':
        return obj, [], None
    older = needs_upgrade(obj)
    bak = backup_copy(src_path=path) if older else None
    return obj, (upgrade_object(obj) if older else []), bak
