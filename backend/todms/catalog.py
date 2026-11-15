"""Maps, sections (submaps) and missions of the user's game, from blocks.naz and the mission registry
(tools/missions/missiontool.chain: MissionDict map/submap of every mission)."""
import os
import re

from .game import SHARED

PRETTY = {
    'map01': 'DEA HQ / US Border', 'map02': 'Los Toros Downtown', 'map03': 'Los Toros Industrial',
    'map04': 'Train Harbour', 'map06': "Virgillo's Farm", 'map07': 'Meat Factory', 'map08': 'Hacienda',
    'map09': 'Jungle', 'map10': 'Runaway Train',
}


def _stem(entry):
    return os.path.splitext(entry.split('/')[-1])[0]


def build(game, progress=None):
    names = sorted(n for n in game.names() if n.startswith(SHARED))
    maps = {}
    for n in names:
        m = re.match(re.escape(SHARED) + r'mainmap_(map\d\d)_(.+)\.map$', n)
        if m:
            mid = m.group(1)
            maps[mid] = dict(id=mid, title='%s %s' % (mid.capitalize(), PRETTY.get(mid, m.group(2).replace('_', ' ').title())),
                             map_block=n, sections=[], missions=[])
    for n in names:
        m = re.match(re.escape(SHARED) + r'submap(\d\d)_(map\d\d)_(.+)\.submap$', n)
        if m and m.group(2) in maps:
            maps[m.group(2)]['sections'].append(dict(entry=n, id='SUBMAP%s' % m.group(1),
                                                     title='Section %s %s' % (m.group(1), m.group(3).replace('_', ' ').title()),
                                                     size=game.names()[n][1]))
    if progress:
        progress('reading the mission registry')
    missions = []
    try:
        import missiontool as mt
        ch = mt.chain()
        for r in ch['missions']:
            blk = r.get('block')
            if not blk:
                continue
            entry = SHARED + blk
            mapname = (r.get('map') or '').lower()
            mm = re.search(r'map\d\d', mapname)
            sub = (r.get('submap') or '')
            sm = re.match(r'SUBMAP(\d\d)_Map(\d\d)', sub, re.I)
            rec = dict(entry=entry, id=_stem(entry), title=r.get('folder') or _stem(entry), type=r.get('type'),
                       index=r.get('index'),
                       section=(SHARED + 'submap%s_map%s_%s.submap' % (sm.group(1), sm.group(2), sub.split('_', 2)[2].lower()))
                       if sm else None,
                       objectives=[o.get('DisplayText') or o.get('name') for o in (r.get('objectives') or [])])
            missions.append(rec)
            if mm and mm.group(0) in maps:
                maps[mm.group(0)]['missions'].append(rec)
    except Exception as e:                              # the editor still works without mission names
        missions.append(dict(error=str(e)))
    # missions the registry does not name (other .mission blocks): listed per map by name only
    known = {m.get('entry') for m in missions}
    extra = [n for n in names if n.endswith('.mission') and n not in known]
    return dict(maps=[maps[k] for k in sorted(maps)], other_missions=[dict(entry=n, id=_stem(n), title=_stem(n))
                                                                     for n in extra])
