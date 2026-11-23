"""Companion tools part B in Mod Studio: routes and nav, mission graph, sections and transitions.

The logic is the core in backend/todct (nav, missions, sections, edits, blockedit). Blocks are read through the workspace
(ws.read_block: TOD HD's blocks when installed and "build on installed" is on, else blocks.naz).

The edits live in the mod: mod['nav'], mod['missions'], mod['sections'] (op grammar: todct/nav.py, missions.py,
sections.py docstrings). They are built as stage D of build.py (todct.edits.build) on top of the level edit and the
collision sets.
"""
import copy

_cache = {}          # (kind, key) -> model / graph / catalog (block bytes are keyed by ws.block_key)


def _core():
    from todct import nav, missions, sections, edits, blockedit
    return nav, missions, sections, edits, blockedit


def _read(ws):
    return lambda e: ws.read_block(e)[0]


def _key(ws, entries):
    out = []
    for e in entries:
        try:
            out.append(ws.block_key(e))
        except Exception:                                # noqa: BLE001
            out.append(e)
    return tuple(out)


def _err(e):
    return dict(error=str(e), kind=type(e).__name__)


# ---------------------------------------------------------------------------------------------- routes
JUNGLE = ['data_pc/overdose_the_game/overdose/shared/mainmap_map09_jungle.map',
          'data_pc/overdose_the_game/overdose/shared/submap01_map09_jungle.submap',
          'data_pc/overdose_the_game/overdose/shared/submap02_map09_jungle.submap',
          'data_pc/overdose_the_game/overdose/shared/mm010_ernestocruz.mission']
NAVBLOCK_FALLBACK = dict(entry='data_pc/overdose_the_game/overdose/shared/submap01_map09_jungle.submap',
                         frag='Chunk_01_Map_09_FillObjects.fragment', node='0x00300DE7')


def routes_model(ws, entries, ops=None, collision=None, progress=None):
    NV = _core()[0]
    entries = list(entries or JUNGLE)
    k = ('nav', _key(ws, entries))
    if k not in _cache:
        if progress:
            progress('reading the routes of %d blocks' % len(entries))
        _cache[k] = NV.model(entries, _read(ws))
    m = _cache[k]
    ops = list(ops or [])
    try:
        pv = NV.preview(m, ops)
        err = None
    except NV.NavError as e:
        pv, err = m, str(e)
    issues = NV.validate(pv, collision or [])
    nb = None
    for e, ex in m['blocks'].items():
        for b in ex['blockers']:
            if b.get('navblock'):
                nb = dict(entry=e, frag=b['frag'], node=b['node'])
                break
        if nb:
            break
    return dict(entries=entries, edit=m['edit'], routes=NV.routes(pv), issues=issues, ops_error=err,
                editable=NV.EDITABLE_PROPS, units=NV.UNITS, navblock_template=nb or NAVBLOCK_FALLBACK)


# ---------------------------------------------------------------------------------------------- missions
def mission_graph(ws, entry, ops=None, lint=False, progress=None):
    MS = _core()[1]
    k = ('graph', _key(ws, [entry]))
    if k not in _cache:
        if progress:
            progress('reading the trigger trees (missiontool)')
        _cache[k] = MS.graph(entry, ws.read_block(entry)[0])
    g = _cache[k]
    ops = [o for o in ops or [] if o.get('entry') == entry]
    out = MS.preview(g, ops) if ops else copy.deepcopy(g)
    out['ops'] = ops
    if lint:
        lk = ('lint', _key(ws, [entry]))
        if lk not in _cache:
            if progress:
                progress('missiontool lint')
            _cache[lk] = MS.lint(entry, ws.read_block(entry)[0])
        out['lint'] = _cache[lk]
    return out


def feedback_texts(ws):
    """The lines a feedback text can show (uk_Objective.txt, by ordinal): what 'Show text' picks from. -> [{i, text}]"""
    k = ('texts', _key(ws, ['data_pc/overdose_the_game/overdose/shared/overdose.main']))
    if k not in _cache:
        from . import sectext
        _cache[k] = sectext.shipped_lines(ws)
    return _cache[k]


# ---------------------------------------------------------------------------------------------- sections
def sections_catalog(ws, group=None, entries=None, ops=None, progress=None):
    NV, MS, SC, ED, BE = _core()
    if group:
        entries = SC.GROUPS[group]
    entries = [SC.full(e) for e in entries or SC.GROUPS[list(SC.GROUPS)[0]]]
    k = ('sections', _key(ws, entries))
    if k not in _cache:
        if progress:
            progress('reading the loader volumes')
        _cache[k] = SC.catalog(entries, _read(ws))
    cat = copy.deepcopy(_cache[k])
    ops = [o for o in ops or [] if o.get('entry') in entries]
    cat.update(entries=entries, ops=ops, gap_default=SC.GAP,
               groups=[dict(name=n, blocks=b) for n, b in SC.GROUPS.items()])
    if ops:
        import json
        ak = ('sections-after', _key(ws, entries), json.dumps(ops, sort_keys=True))
        if ak not in _cache:
            if progress:
                progress('building the section edit')
            built, rep = ED.build(_read(ws), sections=ops)
            after = dict(after=dict(result=rep.get('result'), error=rep.get('error'),
                                    checks=(rep.get('sections') or {}).get('checks'),
                                    teleports_after=(rep.get('sections') or {}).get('teleports_after')))
            if built:
                after['volumes_after'] = SC.catalog(entries, lambda e: built.get(e) or ws.read_block(e)[0])['volumes']
            _cache[ak] = after
        cat.update(copy.deepcopy(_cache[ak]))
    return cat


def fix_teleport(ws, group, vid, gap=None, progress=None):
    SC = _core()[2]
    cat = sections_catalog(ws, group=group, progress=progress)
    return dict(ops=SC.fix_teleport(cat, vid, float(gap) if gap not in (None, '') else SC.GAP))


def split_plan(ws, entry, axis='x', at=0.0, progress=None):
    SC = _core()[2]
    if progress:
        progress('scanning %s' % entry.split('/')[-1])
    return SC.split_plan(entry, ws.read_block(entry)[0], axis, float(at))


# ---------------------------------------------------------------------------------------------- check (build + verify)
def check(ws, mod, kinds=('nav', 'missions', 'sections'), progress=None):
    """Build the mod's part-B ops on the blocks Mod Studio builds on and verify them with the tools (navtool,
    missiontool graph + lint, transitions.catalog, submaptool); nothing is written."""
    ED = _core()[3]
    if progress:
        progress('building and verifying (%s)' % ', '.join(kinds))
    kw = {k: (mod.get(k) or []) if k in kinds else [] for k in ('nav', 'missions', 'sections')}
    from . import sectext
    text_lines = []
    try:
        kw['missions'], edits = sectext.resolve(kw['missions'])
        if edits:
            sectext.blocks(ws, edits)
            text_lines = [dict(area='texts', level='ok', text='text row %d: "%s"' % (e['ordinal'], e['value'])) for e in edits]
    except sectext.TextError as e:
        text_lines = [dict(area='texts', level='error', text=str(e))]
        kw['missions'] = []
    out, rep = ED.build(_read(ws), collision_sets=mod.get('collision') or [], **kw)
    lines = []
    for k in ('nav', 'missions', 'sections'):
        v = rep.get(k)
        for x in (v if isinstance(v, list) else [v] if v else []):
            for c in x.get('checks') or []:
                lines.append(dict(area=k, level='ok' if c[0] == 'PASS' else 'error', text=c[1]))
            for b in x.get('blocks') or []:
                for c in b.get('checks') or []:
                    lines.append(dict(area=k, level='ok' if c[0] == 'PASS' else 'error', text='%s: %s' % (b['entry'], c[1])))
            if x.get('lint'):
                L = x['lint']
                lines.append(dict(area='missiontool lint', level='ok' if not L['new_issues'] else 'warning',
                                  text='%s: %d issues before, %d after, new: %s' % (x.get('entry'), L['before'], L['after'],
                                                                                   '; '.join(L['new_issues']) or 'none')))
    for b in rep.get('blocks') or []:
        sv = b.get('submaptool_verify') or {}
        ri = sv.get('runtime_indices') or {}
        if sv:
            lines.append(dict(area='save safety', level='ok' if ri.get('unchanged', True) else 'error',
                              text='%s: %s existing nodes keep their index, %d new node(s) appended%s' % (
                                  b['entry'].split('/')[-1], ri.get('existing_nodes', '?'), len(ri.get('new_nodes') or []),
                                  '; ' + b['appended']['literal_clash_check'] if b.get('appended') else '')))
    lines += text_lines
    for n in rep.get('notes') or []:
        lines.append(dict(area='note', level='ok', text=n))
    if rep.get('error'):
        lines.append(dict(area='build', level='error', text=rep['error']))
    return dict(result=rep['result'], lines=lines, blocks=[dict(entry=b['entry'], bytes=b.get('bytes'),
                sha256=b.get('out_sha256')) for b in rep.get('blocks') or []], nav_issues=rep.get('nav_issues'))
