"""Map and section numbers for new maps (wave 3 core).

A recipe never fixes its own numbers. Every new-map project carries a permanent `uid`; the numbers are handed out at INSTALL time,
across every installed project, and are kept stable afterwards (the game folder's `todms_alloc.json`, written by the pack's journal
together with the other install records).

Why stable: a save records the folder ids of the blocks it stands on (map + submap ids of the six block folders). Remove a map that
was installed first and the others must not slide down into its numbers, or the saves made on them would load another map. So an id
once given stays with its project until that project is removed; a freed id is reused by the next install (lowest first).
A gap below a used id is possible; the game has not been measured with an empty slot in the map list, so the limits rows say so.

Maps: ids from MAP_BASE up (the recipe writes MAPS_MAX = highest id + 1), submaps from SUB_BASE up. A map takes one map id and one
submap id; an extension section (placement "extension") takes one submap id only.
"""
import copy
import json
import os
import uuid

NAME = 'todms_alloc.json'
MAP_BASE = 9                    # the game's own MAPS_MAX (ids 0-8 are shipped maps)
SUB_BASE = 21                   # the game's own SUBMAPS_MAX
MEASURED_MAPS = 13              # total maps proven in game (ids 0-12): 4 new ones
MEASURED_NEW = MEASURED_MAPS - MAP_BASE


def new_uid():
    return uuid.uuid4().hex[:16]


def key_of(params, pid=None):
    """The permanent owner key of a project."""
    return (params or {}).get('uid') or ('p_' + (pid or 'unknown'))


def path(folder):
    return os.path.join(folder, NAME)


def read(folder):
    try:
        with open(path(folder), encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault('format', 1)
    data.setdefault('owners', {})
    return data


def shape(params):
    """(number of maps, number of extension sections) a project needs."""
    maps = [m for m in (params or {}).get('maps', [])]
    ext = sum(1 for m in maps if m.get('placement') == 'extension')
    return len(maps) - ext, ext, [m.get('placement') == 'extension' for m in maps]


def _lowest(used, base):
    n = base
    while n in used:
        n += 1
    return n


def assign(alloc, owners):
    """alloc: the allocation record; owners: [(key, params, label)] in install order. -> a NEW allocation record.
    Owners already present keep every id they have (extra maps get new ids, dropped maps give theirs back); owners no longer
    listed are released."""
    out = dict(format=1, owners={})
    old = alloc.get('owners', {})
    want = {k: (p, lab) for k, p, lab in owners}
    for k, (p, lab) in want.items():             # first pass: keep what exists
        n_maps, n_ext, flags = shape(p)
        prev = old.get(k, {})
        rows = list(prev.get('maps', []))[:n_maps]
        secs = list(prev.get('sections', []))[:n_ext]
        out['owners'][k] = dict(label=lab, maps=[dict(r) for r in rows], sections=list(secs))
    used_m = {r['map_id'] for o in out['owners'].values() for r in o['maps']}
    used_s = {r['submap_id'] for o in out['owners'].values() for r in o['maps']} | \
             {s for o in out['owners'].values() for s in o['sections']}
    for k, p, lab in owners:                     # second pass: new numbers, in install order
        n_maps, n_ext, flags = shape(p)
        o = out['owners'][k]
        while len(o['maps']) < n_maps:
            mid, sid = _lowest(used_m, MAP_BASE), _lowest(used_s, SUB_BASE)
            used_m.add(mid)
            used_s.add(sid)
            o['maps'].append(dict(map_id=mid, submap_id=sid))
        while len(o['sections']) < n_ext:
            sid = _lowest(used_s, SUB_BASE)
            used_s.add(sid)
            o['sections'].append(sid)
    return out


def inject(params, entry):
    """A copy of the params with each map's `map_id` / `submap_id` (and `section_id` for extensions) filled in from the allocation."""
    p = copy.deepcopy(params)
    mi = si = 0
    for m in p.get('maps', []):
        if m.get('placement') == 'extension':
            m['section_id'] = entry['sections'][si]
            si += 1
        else:
            m['map_id'] = entry['maps'][mi]['map_id']
            m['submap_id'] = entry['maps'][mi]['submap_id']
            mi += 1
    return p


def limits(alloc):
    """-> dict(maps_max, submaps_max, new_maps, measured, holes, over_measured)."""
    ms = [r['map_id'] for o in alloc.get('owners', {}).values() for r in o['maps']]
    ss = [r['submap_id'] for o in alloc.get('owners', {}).values() for r in o['maps']] + \
         [s for o in alloc.get('owners', {}).values() for s in o['sections']]
    maps_max = max(ms) + 1 if ms else MAP_BASE
    subs_max = max(ss) + 1 if ss else SUB_BASE
    holes = [n for n in range(MAP_BASE, maps_max) if n not in set(ms)]
    return dict(maps_max=maps_max, submaps_max=subs_max, new_maps=len(ms), total_maps=MAP_BASE + len(ms),
                measured_maps=MEASURED_MAPS, over_measured=max(0, maps_max - MEASURED_MAPS), holes=holes,
                sections=len(ss) - len(ms))


def table(alloc):
    """The id map the UI reads: [{key, label, maps: [{map_id, submap_id}], sections}]."""
    return [dict(key=k, label=o.get('label'), maps=o['maps'], sections=o['sections']) for k, o in sorted(alloc.get('owners', {}).items())]


def is_default(entry):
    """True when the numbers equal what a recipe picks on its own on an untouched game (the first free ones, in order)."""
    if not entry:
        return True
    if entry.get('sections'):
        return False
    return all(r['map_id'] == MAP_BASE + i and r['submap_id'] == SUB_BASE + i for i, r in enumerate(entry.get('maps', [])))
