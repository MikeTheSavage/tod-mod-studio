"""The read side of the new-map network (wave 3): which shipped sections can take an entrance or a section, every loader link between
maps (for the atlas), the numbers handed out, and what removing or disabling a map touches.

Pure functions take recipe params and return plain dicts; the ones that read the game take a workspace.
"""
import os
import re

from . import mapalloc

NODES_PER_ENTRANCE = 12


def short(e):
    return str(e or '').replace('\\', '/').split('/')[-1].lower()


def block_label(block):
    """'submap01_map02_lostoros_downtown.submap' -> 'Map02 Los Toros Downtown, section 1' (a plain label for lists)."""
    b = short(block)
    m = re.match(r'(mainmap|submap(\d+))_map(\d+)_(.*)\.(map|submap)$', b)
    if not m:
        return b
    tail = m.group(4).replace('lostoros', 'los toros').replace('_', ' ').strip()
    return 'Map%s %s%s' % (m.group(3), tail, '' if m.group(1) == 'mainmap' else ', section %d' % int(m.group(2)))


def _entrances(m):
    es = list(m.get('entries') or [])
    if m.get('entry'):
        es.append(dict(m['entry'], id=m['entry'].get('id', 'entry')))
    return es


# ------------------------------------------------------------------------------------------------ links (atlas link layer)
def links_from(projects):
    """projects: [(key, label, params)] -> dict(maps=[{key, name, project, placement}], links=[...]).
    A link: {from: {kind 'shipped'|'new', name, block, pos}, to: {...}, kind 'enter'|'back'|'section'|'section_back', project,
    one_way, vehicle, prompt, lock}. Every new map is a node; a shipped section named by an entrance is a node of kind shipped."""
    maps, links = [], []
    for key, label, params in projects:
        for m in (params or {}).get('maps') or []:
            if m.get('placement') == 'extension':
                h = m.get('host') or {}
                hb = short(h.get('block'))
                maps.append(dict(key=key, project=label, name=m.get('name'), placement='extension', host=hb))
                for kind, side in (('section', 'enter'), ('section_back', 'leave')):
                    box = h.get(side) or {}
                    a = dict(kind='shipped', name=block_label(hb), block=hb, pos=box.get('pos'))
                    b = dict(kind='new', name=m.get('name'), block=None, pos=None)
                    links.append(dict(**{'from': a if kind == 'section' else b, 'to': b if kind == 'section' else a}, kind=kind, project=label,
                                      one_way=False, vehicle=False, prompt=h.get('prompt', 'touch'), lock=None))
                continue
            maps.append(dict(key=key, project=label, name=m.get('name'), placement=m.get('placement', 'separate'),
                             neighbour=m.get('neighbour')))
            ret = m.get('return')
            for e in _entrances(m):
                hb = short(e.get('block'))
                src = dict(kind='shipped', name=block_label(hb), block=hb, pos=e.get('pos'))
                dst = dict(kind='new', name=m.get('name'), block=None, pos=((e.get('arrive') or {}).get('pos') or m['arrival'].get('pos')))
                links.append(dict(**{'from': src, 'to': dst}, kind='enter', project=label, one_way=bool(e.get('one_way')),
                                  vehicle=bool(e.get('vehicle')), prompt=e.get('prompt', 'touch'), lock=e.get('lock'), entry=e.get('id')))
                bk = e.get('back')
                if bk and not e.get('one_way'):
                    links.append(dict(**{'from': dict(kind='new', name=m.get('name'), block=None, pos=bk.get('pos')),
                                         'to': dict(kind='shipped', name=block_label(hb), block=hb, pos=(bk.get('spot') or {}).get('pos'))},
                                      kind='back', project=label, one_way=False, vehicle=bool(e.get('vehicle')), prompt=bk.get('prompt', 'touch'),
                                      lock=None, entry=e.get('id')))
            if ret:
                links.append(dict(**{'from': dict(kind='new', name=m.get('name'), block=None, pos=ret.get('pos')),
                                     'to': dict(kind='shipped', name=ret.get('target_submap') or ret.get('target_map'),
                                                block=short(ret.get('teleport_block')) or None, pos=None)},
                                  kind='back', project=label, one_way=False, vehicle=False, prompt=ret.get('prompt', 'touch'), lock=None, entry=None))
    return dict(maps=maps, links=links)


def links(ws):
    from . import newmap
    rows = []
    for pid in _project_ids(ws):
        try:
            p = newmap.get_project(pid)['params']
        except Exception:                                  # noqa: BLE001
            continue
        rows.append((pid, p.get('package') or pid, p))
    out = links_from(rows)
    inst = set(newmap.installed(ws.game.folder)) if ws.game else set()
    for m in out['maps']:
        m['installed'] = m['key'] in inst
    return out


def _project_ids(ws):
    from . import newmap
    try:
        return [p['id'] for p in newmap.list_projects()]
    except Exception:                                      # noqa: BLE001
        return []


# ------------------------------------------------------------------------------------------------ the numbers
def allocation(ws):
    """The id map: what is installed, what the next install would take, and the limits."""
    from . import newmap
    folder = ws.game.folder if ws.game else None
    alloc = mapalloc.read(folder) if folder else dict(format=1, owners={})
    rows = mapalloc.table(alloc)
    inst = newmap.installed(folder) if folder else {}
    names = {}
    for pid, rec in inst.items():
        names[mapalloc.key_of(rec.get('params'), pid)] = dict(project=pid, name=rec.get('name'), disabled=bool(rec.get('disabled')))
    for r in rows:
        r.update(names.get(r['key'], {}))
    lim = mapalloc.limits(alloc)
    return dict(owners=rows, limits=lim, measured_maps=mapalloc.MEASURED_MAPS,
                note=('Maps up to %d are measured; the next one is not.' % mapalloc.MEASURED_MAPS) if lim['total_maps'] >= mapalloc.MEASURED_MAPS else None,
                stable='A map keeps its numbers until it is removed, so saves made on it keep working when others are added or removed.')


# ------------------------------------------------------------------------------------------------ hosts (what can take an entrance)
def hosts(ws, progress=None):
    """Every shipped block an entrance or a section copy can use, with the builder's verdict and the room left."""
    from . import newmap, ledger
    listing = newmap.entry_hosts(ws, progress)
    inst = newmap.installed(ws.game.folder) if ws.game else {}
    adds = ledger._host_additions([r.get('params') for r in inst.values() if r.get('params') and not r.get('disabled')])
    out = []
    for h in listing.get('hosts', []):
        b = short(h['block'])
        base = ledger.HOST_POOLS.get(b)
        n = adds.get(b, 0)
        row = dict(block=b, label=block_label(b), offer=bool(h.get('offer')), ok=bool(h.get('ok')), proven=h.get('proven'), reason=h.get('reason'),
                   default_parent=h.get('default_parent'), last_fragment=h.get('last_fragment'), entrances=n // NODES_PER_ENTRANCE,
                   section_copy=b.endswith('.submap') and bool(h.get('offer')))
        if base:
            row['free_main'] = round(10000 - (base[0] + n * ledger.NODE_MAIN))
            row['free_aux'] = round(12200 - (base[1] + n * ledger.NODE_AUX))
        else:
            row['free_main'] = row['free_aux'] = None           # not measured for this section
        out.append(row)
    return dict(hosts=out, supported=listing.get('supported', False))


# ------------------------------------------------------------------------------------------------ safe removal
def folder_ids(main_bytes):
    """{registry folder name: entity id} of an overdose.main (bytes). The entity id is what a save stores for the block folders."""
    from . import newmap
    r = newmap.load_recipe()
    ft, fe, tb, S = r.ft, r.fe, r.tb, r.S
    T = ft.types()
    b = tb.Block(main_bytes, '.main')
    fr = S.frags_of(b)
    nm = [n for n in fr if n.lower().endswith('overdose.scene')][0]
    d = fe.FragDoc(b.payloads[fr[nm]], T, nm)
    out = {}
    for n in d.created_ids():
        t = d.type_of(n) or ''
        if 'Map_ID' in t or 'SubMap_ID' in t:
            out[d.get(n, fe.P_NAME)] = int(n)
    return out


def project_folder_names(params):
    """The registry folder names a project's maps own (extension sections get generated names: found by id in the pack)."""
    names = []
    for m in (params or {}).get('maps') or []:
        if m.get('placement') == 'extension':
            continue
        names += ['MAINMAP_%s' % m.get('name'), 'SUBMAP01_%s' % m.get('name')]
    return names


def save_header_ids(path):
    """The loaded-block folder ids of a save file (read from the header only): [map, submap, ...] or None."""
    import struct
    try:
        with open(path, 'rb') as f:
            head = f.read(0x60)
        ids = struct.unpack_from('<6i', head, 0x3C)
        return list(ids)
    except Exception:                                      # noqa: BLE001
        return None


def saves_on(folder_ids_wanted, folders):
    """Saves (slots) whose header names one of the folder ids: [{where, name}]. folders: [(label, path)]."""
    out = []
    want = set(folder_ids_wanted)
    for label, fold in folders:
        if not fold or not os.path.isdir(fold):
            continue
        for fn in sorted(os.listdir(fold)):
            p = os.path.join(fold, fn)
            if not (os.path.isfile(p) and fn.lower().startswith('slot') and os.path.getsize(p) == 0x50000):
                continue
            ids = save_header_ids(p)
            if ids and want.intersection(i for i in ids if i > 0):
                out.append(dict(where=label, name=fn))
    return out


def removal_report(ws, pid):
    """What taking project `pid` out (or switching it off) touches: its maps, the entrances in shipped sections, the missions that use it, and
    the saves that stand on its maps. Nothing is changed; the saves are only read (a copy is kept by the install itself)."""
    from . import newmap, pack, missions_tpl, saves, snapshots, game
    folder = ws.game.folder
    rec = newmap.installed(folder).get(pid)
    params = (rec or {}).get('params') or {}
    mrec = missions_tpl.installed(folder)
    if not params:
        for p in (mrec.get('projects') or {}).values():
            if pid in (p.get('newmaps') or {}):
                params = p['newmaps'][pid]
    hosted = [dict(project=k, name=v.get('name'), missions=len(v.get('indices') or {})) for k, v in (mrec.get('projects') or {}).items()
              if pid in (v.get('newmaps') or {})]
    entrances = []
    for m in params.get('maps') or []:
        for e in ([] if m.get('placement') == 'extension' else _entrances(m)):
            entrances.append(dict(map=m.get('name'), block=short(e.get('block')), label=block_label(e.get('block'))))
        if m.get('placement') == 'extension':
            entrances.append(dict(map=m.get('name'), block=short((m.get('host') or {}).get('block')), label=block_label((m.get('host') or {}).get('block'))))
    standing = []
    z = os.path.join(folder, game.PACK_ZIP)
    if os.path.exists(z):
        import zipfile
        try:
            with zipfile.ZipFile(z) as zf:
                ids = folder_ids(zf.read(newmap_main_entry()))
            mine = [ids[n] for n in project_folder_names(params) if n in ids]
            for sec in (mapalloc.read(folder).get('owners', {}).get(mapalloc.key_of(params, pid), {}).get('sections') or []):
                mine += [v for k, v in ids.items() if k.upper().startswith('SUBMAP') and False]
            dirs = [('your saves', saves.saves_dir())]
            snap = snapshots.root()
            if os.path.isdir(snap):
                for d in sorted(os.listdir(snap), reverse=True)[:3]:
                    dirs.append(('copy %s' % d, os.path.join(snap, d, 'saves')))
            standing = saves_on(mine, dirs)
        except Exception:                                  # noqa: BLE001  (a pack that cannot be read reports nothing rather than guessing)
            standing = []
    return dict(project=pid, maps=[m.get('name') for m in params.get('maps') or []], entrances=entrances, missions=hosted, saves=standing,
                backup='A copy of your saves is made before the change; no save is rewritten.')


def newmap_main_entry():
    from . import game
    return game.MAIN_ENTRY
