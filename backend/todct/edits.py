"""Companion edits (part B) built together: routes (nav ops), missions (mission ops), sections (section ops) on top of
whatever the build already produced, in one blockedit.Builder, then verified by the project's tools:
  routes    navtool re-export (engine view) == the edited route model
  missions  missiontool graph shows each op; missiontool lint before/after (new issues listed)
  sections  seamless transitions.catalog on the built blocks + the box-order check; submaptool verify (indices)
Mod Studio calls build() as stage D of a mod build.

  out, rep = build(read, nav=[...], missions=[...], sections=[...], base={entry: bytes})
"""
from . import blockedit as BE
from . import nav as NV
from . import missions as MS
from . import sections as SC

KINDS = ('nav', 'missions', 'sections')


def entries_of(ops):
    out = []
    for o in ops or []:
        for k in ('entry',):
            if o.get(k) and o[k] not in out:
                out.append(o[k])
        if o.get('op') == 'add_navblock' and o.get('like', {}).get('entry'):
            pass
    return out


def build(read, nav=None, missions=None, sections=None, base=None, collision_sets=None, verify=True):
    """read(entry) -> shipped/installed bytes; base: {entry: bytes} already built by the host (used first).
    Returns ({entry: bytes} of every block this stage changed or created, report)."""
    base = dict(base or {})

    def read2(e):
        return base[e] if e in base else read(e)
    nav, missions, sections = list(nav or []), list(missions or []), list(sections or [])
    rep = dict(result='PASS', notes=[], nav=None, missions=None, sections=None)
    if not (nav or missions or sections):
        rep['result'] = 'NOTHING'
        return {}, rep
    B = BE.Builder(read2)
    m = None
    if nav:
        m = NV.model_with_raw(entries_of(nav), read2)
        pv = NV.preview(NV.public(m), nav)
        rep['nav_issues'] = NV.validate(pv, collision_sets)
        rep['notes'] += NV.add_to_builder(B, m, nav)
    if missions:
        rep['notes'] += MS.add_to_builder(B, missions, read2)
    cat0 = None
    if sections:
        fix_entries = [o['entry'] for o in sections if o['op'] in ('set_teleport', 'move_loader')]
        if fix_entries:
            cat0 = SC.catalog(list(dict.fromkeys(fix_entries)), read2)
        rep['notes'] += SC.add_to_builder(B, sections, read2)
    try:
        out, brep = B.build()
    except BE.BuildError as e:
        rep['result'] = 'REFUSED'
        rep['error'] = str(e)
        return {}, rep
    rep['blocks'] = brep['blocks']
    rep['new_entities'] = brep['uids']
    if verify:
        if nav:
            rep['nav'] = NV.verify(m, nav, out)
            if rep['nav']['result'] != 'PASS':
                rep['result'] = 'FAIL'
        if missions:
            rep['missions'] = []
            for e in dict.fromkeys(o['entry'] for o in missions):
                if e in out:
                    v = MS.verify(e, missions, read2(e), out[e])
                    rep['missions'].append(dict(entry=BE.short(e) if hasattr(BE, 'short') else e.split('/')[-1], **v))
                    if v['result'] != 'PASS':
                        rep['result'] = 'FAIL'
        if cat0 is not None:
            v = SC.verify(cat0, sections, out, read2)
            v.pop('catalog_after', None)
            rep['sections'] = v
            if v['result'] != 'PASS':
                rep['result'] = 'FAIL'
    return out, rep


def validate_ops(kind, ops):
    """Shape check for recipes (todmod) before anything is built."""
    need = {
        'nav': {'move': ('entry', 'frag', 'node', 'pos'), 'insert_point': ('id', 'entry', 'frag', 'track', 'pos'),
                'remove_point': ('entry', 'frag', 'node'), 'reorder': ('entry', 'frag', 'track', 'points'),
                'link': ('entry', 'frag', 'a', 'b'), 'unlink': ('entry', 'frag', 'a', 'b'),
                'add_signpost': ('id', 'entry', 'frag', 'like', 'pos'), 'remove_signpost': ('entry', 'frag', 'node'),
                'set_next': ('entry', 'frag', 'node'), 'add_traffic_point': ('id', 'entry', 'frag', 'after', 'name', 'pos'),
                'add_navblock': ('id', 'entry', 'like', 'pos', 'size'), 'retire_navblock': ('entry', 'frag', 'node'),
                'set': ('entry', 'prop')},
        'missions': {'set': ('entry', 'prop'), 'rewire': ('entry', 'frag', 'action', 'to'),
                     'retarget': ('entry', 'frag', 'action', 'target'), 'add_trigger': ('id', 'entry', 'template'),
                     'add_action': ('id', 'entry', 'root', 'action'), 'add_vehicle': ('id', 'entry', 'pos'), 'disable_trigger': ('entry', 'frag', 'node')},
        'sections': {'set_teleport': ('entry', 'frag', 'node'), 'move_loader': ('entry', 'frag', 'node', 'pos'),
                     'add_section': ('id', 'source_submap', 'new_index', 'loader_in', 'loader_back')},
    }[kind]
    for i, o in enumerate(ops or []):
        op = o.get('op')
        if op not in need:
            raise ValueError('%s op %d: unknown op %r' % (kind, i, op))
        for k in need[op]:
            if o.get(k) in (None, ''):
                raise ValueError('%s op %d (%s): missing %s' % (kind, i, op, k))
        if op == 'set' and not (o.get('node') or o.get('id')):
            raise ValueError('%s op %d (set): needs node or id' % (kind, i))
    return True
