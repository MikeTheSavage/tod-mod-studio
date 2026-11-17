"""The asset catalogue: every model of the player's game, browsable. Built from the game's own blocks.

  scan        census (maps, sections, counts, size, triangles) + the asset index (textures of each model), one job
  rows        filtered, sorted rows for the grid (category, map, size, triangles, uses, text)
  detail      one model: its glb with textures (the same extraction the level editor uses), measures, texture list,
              where it is used (maps and sections), the pivots, and whether clips can play on it
  save_thumb  the browser draws the card pictures with the real textures and hands them back to be kept
Categories come from todct/modelcat.py (one rules table).
"""
import base64
import json
import os
import re

from . import paths

CARD_DIR = 'thumbs_tex'
SIZE_BANDS = {'tiny': (0, 0.5), 'small': (0.5, 2), 'medium': (2, 8), 'large': (8, 40), 'huge': (40, 1e9)}
RAM_HEIGHT = 1.8


def _mc():
    from todct import modelcat
    return modelcat


def _as():
    from todct import assets
    return assets


def cfg():
    d = os.path.join(paths.cache_dir(), 'assets')
    os.makedirs(d, exist_ok=True)
    return _as().Config(d)


def card_dir():
    d = os.path.join(cfg().folder, CARD_DIR)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------------- the table
_MEMO = {}


def _stamp():
    out = []
    for p in (cfg().census_path, os.path.join(cfg().folder, 'asset_index.json')):
        try:
            out.append(os.path.getmtime(p))
        except OSError:
            out.append(0)
    return tuple(out)


def table(ws=None):
    """-> dict(rows [full rows], maps [keys], census built?) or None before the first scan. Cached by file time."""
    from . import assetindex
    st = _stamp()
    if _MEMO.get('stamp') == st and 'doc' in _MEMO:
        return _MEMO['doc']
    cen = cfg().census()
    if not cen or cen.get('version', 1) < 2:
        _MEMO.clear()
        return None
    MC = _mc()
    idx = assetindex.load(None) or {}
    imod = idx.get('models') or {}
    itex = idx.get('textures') or {}
    rows = []
    for r in _as().rows(cfg(), census_doc=cen):
        p = (r['path'] or '').lower()
        im = imod.get(p) or {}
        names = im.get('textures') or []
        r['cat'] = MC.category(p)
        r['label'] = MC.label(p)
        r['area'] = MC.area(p)
        names = list(dict.fromkeys(names))
        r['textures'] = len(names) if im else None
        r['hd'] = bool(im.get('hd'))
        r['nblocks'] = len(r.get('blocks') or [])
        r['tex_names'] = names
        r['px'] = sum((itex.get(t) or {}).get('w', 0) * (itex.get(t) or {}).get('h', 0) for t in names)
        r['dim'] = max(r['size'] or [0, 0, 0])
        rows.append(r)
    doc = dict(rows=rows, by_key={r['key']: r for r in rows}, maps=cen.get('maps', []), built=cen.get('built'),
               indexed=bool(idx))
    _MEMO.update(stamp=st, doc=doc)
    return doc


def scan(ws, progress=None):
    """Count the models (about a minute) and index their textures."""
    from . import assetindex, companion
    r = companion.census(ws, progress)
    if progress:
        progress('textures of the models')
    assetindex.build(ws, progress)
    _MEMO.clear()
    return dict(models=r['models'], maps=len(r['maps']), seconds=r['seconds'])


def _have_cards():
    """-> (keys with a picture, keys known to have no mesh to draw)"""
    try:
        fs = os.listdir(card_dir())
    except OSError:
        return set(), set()
    return {f[:-4] for f in fs if f.endswith('.png')}, {f[:-5] for f in fs if f.endswith('.none')}


def _slim(r, cards):
    return dict(key=r['key'], name=r['label'], path=r['path'], cat=r['cat'], kind=r['kind'], uses=r['uses'], tris=r['triangles'] or 0,
                size=r['size'], tex=r['textures'], maps=len(r['maps']), hd=r['hd'], card=r['key'] in cards[0], none=r['key'] in cards[1])


def filter_rows(rows, q):
    """The row filter, kept apart so a test can run it on a plain list."""
    t = (q.get('q') or '').lower().strip()
    terms = [x for x in re.split(r'\s+', t) if x]
    out = []
    smin = float(q['size_min']) if q.get('size_min') not in (None, '') else None
    smax = float(q['size_max']) if q.get('size_max') not in (None, '') else None
    band = SIZE_BANDS.get(q.get('band') or '')
    if band:
        smin, smax = band
    for r in rows:
        if q.get('map') and not r['maps'].get(q['map']):
            continue
        n = r['maps'].get(q['map'], 0) if q.get('map') else r['uses']
        if int(q.get('min_uses') or 0) and n < int(q['min_uses']):
            continue
        if q.get('unused') and r['uses']:
            continue
        if smin is not None and r['dim'] < smin:
            continue
        if smax is not None and r['dim'] >= smax:
            continue
        tr = r['triangles'] or 0
        if q.get('tris_min') not in (None, '') and tr < int(q['tris_min']):
            continue
        if q.get('tris_max') not in (None, '') and tr > int(q['tris_max']):
            continue
        if q.get('kind') and r['kind'] != q['kind']:
            continue
        if terms:
            hay = (r['label'] + ' ' + r['name'] + ' ' + (r['path'] or '')).lower()
            if not all(x in hay for x in terms):
                continue
        out.append(r)
    return out


SORTS = {
    'name': lambda r: r['label'].lower(),
    'uses': lambda r: (-r['uses'], r['label'].lower()),
    'tris': lambda r: (-(r['triangles'] or 0), r['label'].lower()),
    'size': lambda r: (-r['dim'], r['label'].lower()),
    'textures': lambda r: (-(r['textures'] or 0), r['label'].lower()),
}


def rows(ws, q):
    """-> dict(ready, count, total, rows [slim], cats [{id, label, count}], maps)."""
    doc = table(ws)
    MC = _mc()
    if doc is None:
        return dict(ready=False, rows=[], cats=MC.table(), maps=[], count=0, total=0)
    q = q or {}
    base = filter_rows(doc['rows'], {k: v for k, v in q.items() if k != 'cat'})
    counts = {}
    for r in base:
        counts[r['cat']] = counts.get(r['cat'], 0) + 1
    sel = [r for r in base if not q.get('cat') or r['cat'] == q['cat']]
    sel.sort(key=SORTS.get(q.get('sort') or 'uses', SORTS['uses']))
    cards = _have_cards()
    return dict(ready=True, total=len(doc['rows']), count=len(sel), indexed=doc['indexed'], built=doc['built'],
                rows=[_slim(r, cards) for r in sel], maps=doc['maps'],
                cats=[dict(c, count=counts.get(c['id'], 0)) for c in MC.table()])


# ---------------------------------------------------------------------------------------------- one model
def _map_id(key):
    m = re.match(r'(map\d\d)', key or '')
    return m.group(1) if m else (key or '')


def where_used(ws, row):
    """Maps and sections that place the model: [{map, map_key, title, section, entry, kind, count}], biggest first.
    section is the catalogue section entry, or None for the map block itself; missions carry kind 'mission'."""
    place = {}
    for m in ws.catalog['maps']:
        place[m['map_block']] = (m, None, 'map', m['title'].split(' ', 1)[-1] if ' ' in m['title'] else m['title'])
        for s in m['sections']:
            place[s['entry']] = (m, s['entry'], 'section', s['title'])
        for s in m['missions']:
            if s.get('entry'):
                place[s['entry']] = (m, None, 'mission', s.get('title') or s['entry'].split('/')[-1])
    out = []
    for e, n in (row.get('sections') or {}).items():
        hit = place.get(e)
        if not hit:
            out.append(dict(map=None, map_key=None, title=e.split('/')[-1], section=None, entry=e, kind='block', count=n))
            continue
        m, sec, kind, title = hit
        out.append(dict(map=m['id'], map_key=m['id'], map_title=m['title'], title=title, section=sec, entry=e, kind=kind, count=n))
    out.sort(key=lambda x: (-x['count'], x['title']))
    return out


def _cache_file(url):
    return os.path.join(paths.cache_dir(), *url[len('/cache/'):].split('/'))


def locate(ws, row):
    """-> (block entry that holds the model's mesh, its extraction record). The model's own home first, then the blocks the census saw it in."""
    n = row['path'].lower()
    cands = [ws.home_entry(n)]
    try:
        import fragtool as ft
        names = ft.archive().names
        for b in row.get('blocks') or []:
            e = next((x for x in names if x.lower().endswith('/' + b.lower())), None)
            if e and e not in cands:
                cands.append(e)
    except Exception:                                       # noqa: BLE001
        pass
    for e in cands:
        try:
            if n in ws.assets(e).models:
                rec = ws.model_table({n}, [e]).get(n)
                if rec and not rec.get('missing'):
                    return e, rec
        except Exception:                                   # noqa: BLE001  (try the next block)
            continue
    return cands[0], dict(missing=True)


def _pivots(ws, row, entry):
    """Pivot names, parents and model-space positions (viewer axes) for the bones toggle, cached with the catalogue."""
    f = os.path.join(cfg().folder, 'pivots_%s.json' % row['key'])
    try:
        with open(f, encoding='utf-8') as h:
            return json.load(h)
    except (OSError, ValueError):
        pass
    import tod_model_extract as me
    import export_map as ex
    A = ws.assets(entry)
    hit = A.models.get(row['path'].lower())
    out = []
    if hit:
        info = A.info
        R = hit[1]
        try:
            model = me.extract_model(info, R, row['path'])
            PW = ex.pivot_world(info, R)
            for i, p in enumerate(model['pivots']):
                par = PW and ex.tc.i32(info, ex.tc.deref(info, R + 0x30) + i * 0x7C + 0x58)
                pos = PW[i][0]
                out.append(dict(name=p.get('name') or 'pivot%d' % i, parent=par if 0 <= par < len(PW) and par != i else -1,
                                pos=[round(pos[0], 4), round(pos[1], 4), round(-pos[2], 4)]))
        except Exception:                                   # noqa: BLE001  (a model without readable pivots shows none)
            out = []
    with open(f + '.part', 'w', encoding='utf-8') as h:
        json.dump(out, h, separators=(',', ':'))
    os.replace(f + '.part', f)
    return out


def row_of(ws, key):
    doc = table(ws)
    row = doc and doc['by_key'].get(key)
    if row is None:
        raise KeyError('That model is not in the catalogue.')
    return row


def detail(ws, key):
    doc = table(ws)
    row = doc and doc['by_key'].get(key)
    if row is None:
        raise KeyError('That model is not in the catalogue.')
    from . import assetindex
    idx = assetindex.load(None) or {}
    itex = idx.get('textures') or {}
    entry, rec = locate(ws, row)
    texs = []
    for t in row['tex_names']:
        i = itex.get(t) or {}
        texs.append(dict(name=t, short=t.split('/')[-1].rsplit('.', 1)[0], w=i.get('w'), h=i.get('h'), fmt=i.get('fmt'),
                         size=i.get('size'), users=len(i.get('users') or []), hd=bool(i.get('hd')),
                         url=((rec.get('textures') or {}).get(t) or {}).get('url')))
    texs.sort(key=lambda t: not t['url'])                    # the ones on the mesh first; the rest are variants (wrecks, damage, detail levels)
    MC = _mc()
    out = dict(key=key, name=row['label'], path=row['path'], cat=row['cat'], cat_label=MC.LABEL.get(row['cat'], row['cat']),
               kind=row['kind'], size=row['size'], tris=row['triangles'], pivots_n=row.get('pivots'),
               collision=row['collision'], collision_shapes=row['collision_shapes'], hd=row['hd'], uses=row['uses'], ram=RAM_HEIGHT,
               rec=rec, textures=texs, where=where_used(ws, row), pivots=_pivots(ws, row, entry), blocks=row['nblocks'])
    return out


# ---------------------------------------------------------------------------------------------- card pictures
def save_card(key, data_url):
    """The browser's own render of the card (a data: URL, PNG), or None when the model has no mesh to draw (remembered, not retried)."""
    doc = table()
    if doc is None or key not in doc['by_key']:
        raise KeyError('Unknown model.')
    if data_url is None:
        open(os.path.join(card_dir(), key + '.none'), 'w').close()
        return dict(ok=True)
    m = re.match(r'data:image/png;base64,(.+)$', data_url or '')
    if not m:
        raise ValueError('Not a PNG picture.')
    raw = base64.b64decode(m.group(1))
    if not raw.startswith(b'\x89PNG') or len(raw) > 400000:
        raise ValueError('Not a usable picture.')
    f = os.path.join(card_dir(), key + '.png')
    with open(f + '.part', 'wb') as h:
        h.write(raw)
    os.replace(f + '.part', f)
    return dict(ok=True)
