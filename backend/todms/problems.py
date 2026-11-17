"""The Problems list: one list of errors and warnings for the current project, from every source that can find one.

  checks.py       the live rules on the op list and the collision sets (no build), and the results of the last Check
  routes, sections, mission logic   the lines of the part-B check
  mission template validate(), new-map validate()   the project rules of the two builders
  the ledger      every meter that is red (error when its limit refuses, otherwise a warning) or amber (warning)

Every row says where its cause is (`jump`), so the panel can select the object, open the screen or frame the camera.
Export and install refuse while an error is left; a crash-class limit has no override.
"""
import hashlib

from . import limits, checks, ledger

COVERED = ('L15', 'L15_index', 'L16_pos', 'L16_box', 'M1', 'P6')       # the live rules above already report these with their own cause


def _row(level, source, title, detail='', jump=None):
    pid = hashlib.sha1(('%s|%s|%s' % (source, title, detail)).encode('utf-8', 'replace')).hexdigest()[:10]
    return dict(id=pid, level=level, source=source, title=title, detail=detail or '', jump=jump or {})


# where a new-map problem is fixed: (words in the text) -> (area of the New maps screen, build tool). The same table is in frontend/src/world/worldlib.js
# (jumpOf), which the Ready list uses; keep them equal.
NEWMAP_JUMP = [
    (r'edge of view|seam|footprint|in the layout|safe box|neighbour|aligned|fog distance|differs from the next|road width differs', ('atlas', None)),
    (r'entrance|arrival|way back|portal|vehicle box|way out|trigger box|host section|loader box|return', ('entrances', None)),
    (r'minimap', ('map', 'minimap')),
    (r'quadtree|\bnodes?\b', ('map', 'scatter')),
    (r'road|traffic|bridge|ramp', ('map', 'roads')),
    (r'water|pond|kill|invisible wall|cliff|\bedges?\b', ('map', 'edges')),
    (r'tree|rock|bush|scatter|shipped', ('map', 'scatter')),
    (r'\blook\b|sun|ambient|fog|sky|light|screen', ('map', 'look')),
    (r'blockout|piece', ('map', 'blockout')),
    (r'section|loader', ('map', 'sections')),
    (r'picture|texture|material|paint', ('map', 'paint')),
    (r'triangle|ground|terrain|steep|collision|hull|vertices|sub-mesh', ('map', 'terrain')),
]


def newmap_jump(text, detail='', map_index=None):
    """-> dict(screen='newmaps', area, tool, map): the place that fixes a new-map problem, from the words of its text."""
    import re
    j = dict(screen='newmaps')
    hay = ('%s %s' % (text or '', '')).lower()
    for pat, (area, tool) in NEWMAP_JUMP:
        if re.search(pat, hay):
            j['area'] = area
            if tool:
                j['tool'] = tool
            break
    if map_index is not None:
        j['map'] = map_index
    return j


def _from_checks(items, source='checks'):
    out = []
    for c in items or []:
        if c.get('level') in ('error', 'warn'):
            out.append(_row(c['level'], c.get('area') or source, c['title'], c.get('detail'), c.get('ref') or dict(screen='level')))
    return out


def _from_lines(lines):
    """The part-B check: dict(area, level, text)."""
    out = []
    scr = dict(nav='routes', missions='missions', sections='sections')
    for x in lines or []:
        lv = x.get('level')
        if lv in ('error', 'warning', 'warn'):
            area = x.get('area') or ''
            out.append(_row('error' if lv == 'error' else 'warn', area, x.get('text') or '', '',
                            dict(screen=scr.get(area, 'level'))))
    return out


def _from_ledger(rows, kind):
    out = []
    for r in rows:
        if r['id'] in COVERED or (kind and kind not in r['kinds']) or r['status'] not in ('red', 'amber'):
            continue
        p = r.get('parts') or {}
        if r['status'] == 'amber' and (p.get('vanilla') or 0) and not ((p.get('packages') or 0) + (p.get('project') or 0)):
            continue                                    # the game's own use alone is no problem of this project
        if r['status'] == 'amber' and 'project' in p and not (p.get('project') or 0):
            continue                                    # nor is what the installed packages use: a project lists only its own rows
        used, mx = r['used'], r['max']
        title = '%s: %s of %s %s' % (r['label'], _num(used), _num(mx), r['unit'])
        if r['status'] == 'red':
            lvl = 'error' if r['enforce'] == 'refuse' else 'warn'
        else:
            lvl = 'warn'
        jump = dict(screen=r['jump'] or 'level')
        if r.get('items') and r['items'][0].get('jump'):
            jump = dict(r['items'][0]['jump'])
        out.append(_row(lvl, 'limits', title, r['effect'], jump))
    return out


def _num(v):
    if isinstance(v, float) and v != int(v):
        return '%.1f' % v
    return '{:,}'.format(int(v))


def collect(ws, kind, project, pid=None, results=None, heavy=None):
    """-> dict(problems, errors, warnings, rows (the ledger of this screen))."""
    results = results or {}
    probs = []
    led = ledger.compute(ws, kind, project, pid, heavy)
    if kind == 'level':
        items, _ = checks.ops_items((project or {}).get('level') or [])
        probs += _from_checks(items, 'level')
        probs += _from_checks(checks.collision_items((project or {}).get('collision')), 'collision')
        probs += _from_checks(checks.asset_items((project or {}).get('models'), (project or {}).get('textures')), 'assets')
        probs += _from_checks((results.get('check') or {}).get('checks'))
        for k in ('nav', 'missions', 'sections'):
            probs += _from_lines((results.get(k) or {}).get('lines'))
    elif kind == 'mission':
        from . import missions_tpl as MT
        try:
            MT.check_project(project)
        except ValueError as e:
            probs.append(_row('error', 'mission', str(e), '', dict(screen='mtpl')))
        for m in (results.get('tpl') or {}).get('messages') or []:
            if m.get('level') in ('error', 'warn', 'warning'):
                probs.append(_row('error' if m['level'] == 'error' else 'warn', 'mission', m.get('text') or '', m.get('where') or '',
                                  dict(screen='mtpl', mission=_mission_of(m))))
    elif kind == 'newmap':
        from . import newmap
        try:
            newmap.validate(project)
        except ValueError as e:
            probs.append(_row('error', 'newmap', str(e), '', dict(screen='newmaps')))
        for c in (results.get('newmap') or {}).get('checks') or []:
            if c.get('level') in ('error', 'warn'):
                probs.append(_row(c['level'], 'newmap', c.get('title') or c.get('text') or '', c.get('detail'),
                                  c.get('jump') or newmap_jump(c.get('title') or c.get('text'))))
    if kind == 'newmap':
        try:
            from . import mapbuild
            probs += mapbuild.problems_for(project)
        except Exception:
            pass
    probs += _from_ledger(led['rows'], kind)
    if kind == 'newmap':                                  # every row of this screen says which area and tool fixes it
        for p in probs:
            if p['jump'].get('screen') == 'newmaps' and 'area' not in p['jump']:
                p['jump'] = {**newmap_jump(p['title']), **p['jump']}
    seen, out = set(), []
    for p in probs:
        if p['id'] in seen:
            continue
        seen.add(p['id'])
        out.append(p)
    out.sort(key=lambda p: 0 if p['level'] == 'error' else 1)
    return dict(problems=out, errors=sum(1 for p in out if p['level'] == 'error'),
                warnings=sum(1 for p in out if p['level'] == 'warn'), ledger=led)


def _mission_of(m):
    w = m.get('where')
    return w if isinstance(w, str) and w != 'project' else None


# ------------------------------------------------------------------------------------------------ the gates
def live_errors(kind, project, ws=None, pid=None):
    """Errors that need no build: -> list of texts. Used by export and install (no override)."""
    out = []
    if kind == 'level':
        items, _ = checks.ops_items((project or {}).get('level') or [])
        items += checks.collision_items((project or {}).get('collision'))
        items += checks.asset_items((project or {}).get('models'), (project or {}).get('textures'))
        out += [i['title'] for i in items if i['level'] == 'error']
    elif kind == 'newmap':
        from . import newmap
        try:
            newmap.validate(project)
        except ValueError as e:
            out.append(str(e))
    return out


def refuse_if(errors, what):
    if errors:
        more = ' (and %d more)' % (len(errors) - 1) if len(errors) > 1 else ''
        raise ValueError('%s: %s%s. Fix it in the Problems list first.' % (what, errors[0], more))


def install_gate(ws, state, tmp_zip=None):
    """Before anything goes into the game: every project in the new state has no error, and no crash-class limit is red.
    state: dict(mods=[ids], newmaps={id: record}, missions={...}). Raises ValueError with a plain message."""
    from . import mods
    for mid in state.get('mods') or []:
        try:
            m = mods.get_mod(mid)
        except Exception:
            continue
        refuse_if(live_errors('level', m), 'The mod "%s" has a problem' % (m.get('name') or mid))
    for pid, rec in (state.get('newmaps') or {}).items():
        if rec.get('params'):
            refuse_if(live_errors('newmap', rec['params']), 'The new map "%s" has a problem' % (rec.get('name') or pid))
    n = sum(len(p.get('indices', {})) for p in ((state.get('missions') or {}).get('projects') or {}).values())
    if n > limits.value('L7'):
        refuse_if(['%d new missions need %d slots; the game has %d free' % (n, n, limits.value('L7'))], 'Too many missions')
    if tmp_zip:
        used = ledger.p8_from_pack(ws, tmp_zip)
        if used is not None and limits.status('P8', used) == 'red':
            raise ValueError('The level data would use about %.0f MiB of the %d MiB the game reserves for it, and the game crashes while loading '
                             'such a level. Remove some objects or maps.' % (used / 1048576.0, limits.value('P8') // 1048576))


def from_mapgen(res):
    """Problems of a map generator expansion (mapgen.expand_full): its plain-sentence notes as warnings and the generator meters
    (ledger.mapgen_rows) that are red or amber. For the new-map screen: collect() callers add the list to their own."""
    out = [_row('warn', 'mapgen', n, '', newmap_jump(n)) for n in (res or {}).get('notes') or []]
    out += _from_ledger(ledger.mapgen_rows((res or {}).get('stats')), 'newmap')
    return out
