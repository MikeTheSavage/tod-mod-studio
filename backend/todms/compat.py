"""Compatibility between mods: which of them change the same thing, who wins, what a mod needs, and which game this is.

Everything here reads recipes only (no game, no build). The load order is the list order: a mod LOWER in the list loads later and
wins a true clash. Two mods that change different things in the same block both apply (the builder works per object and per
value); only the same object and property (or the same model, texture or collision set) is a clash.
"""
import json
import os
import re

MAX_ROWS = 300


# ------------------------------------------------------------------------------------------------ versions
def vkey(s):
    """'1.10.2' -> (1, 10, 2); anything that is not numbers counts as 0."""
    out = []
    for p in re.split(r'[.\-+ ]', str(s or '0')):
        m = re.match(r'\d+', p)
        out.append(int(m.group(0)) if m else 0)
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return tuple(out)


def vcmp(a, b):
    a, b = vkey(a), vkey(b)
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def mod_version(m):
    return str(((m.get('page') or {}).get('version')) or '1.0')


def app_version():
    from . import support
    return support._version()


# ------------------------------------------------------------------------------------------------ conflicts
def _short(entry):
    return str(entry or '').replace('\\', '/').split('/')[-1]


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _data_block(editor, key):
    if editor == 'weapons':
        return 'overdose.main'
    try:
        if editor == 'vehicles':
            import vehtool as vt
            return _short(vt.TUN[key][0][0])
    except Exception:
        pass
    return editor


def mod_items(m):
    """-> list of (group, key, value, label, block, kind). `group` is the thing that clashes when two mods give it different values;
    `block` is the game file it lives in (for the 'same block, different things' count)."""
    out = []
    for o in m.get('level') or []:
        op, e = o.get('op'), o.get('entry')
        if op in ('move', 'set', 'delete'):
            node = (e, o.get('frag'), o.get('node'))
            wh = '%s %s' % (_short(o.get('frag')), o.get('node'))
            if op == 'set':
                out.append((('prop',) + node + (o.get('prop'),), o.get('value'), str(o.get('prop')), _short(e), 'value', wh))
            elif op == 'move':
                if o.get('pos') is not None:
                    out.append((('pos',) + node, o['pos'], 'position', _short(e), 'value', wh))
                if o.get('rot') is not None:
                    out.append((('rot',) + node, o['rot'], 'rotation', _short(e), 'value', wh))
            else:
                out.append((('del',) + node, o.get('mode', 'disable'), 'removed', _short(e), 'removed', wh))
        elif op == 'add':
            out.append((('add', o.get('uid')), dict(o, view=None), 'added object %s' % (o.get('name') or o.get('uid')), _short(e), 'value', ''))
        elif op == 'frag':
            for r in o.get('ops') or []:
                if r.get('op') in ('set', 'move'):
                    k = ('frag', e, r.get('fragment'), r.get('entity'), r.get('prop'), r.get('op'))
                    out.append((k, r.get('value', r.get('pos', r.get('orient'))), str(r.get('prop') or r.get('op')),
                                _short(e), 'value', '%s %s' % (_short(r.get('fragment')), r.get('entity'))))
    for ed, vals in (m.get('data') or {}).items():
        for k, v in vals.items():
            out.append((('data', ed, k), v, k, _data_block(ed, k), 'value', ed))
    for x in m.get('models') or []:
        t = (x.get('target') or x.get('path') or '').lower()
        out.append((('model', t), dict(x, id=None, view=None, stats=None), _short(t), 'models', 'model', ''))
    for x in m.get('textures') or []:
        out.append((('texture', x['target'].lower()), dict(x, id=None), _short(x['target']), 'textures', 'texture', ''))
    for s in m.get('collision') or []:
        out.append((('collision', s['id']), s, (s.get('name') or s['id']), 'collision', 'collision', ''))
    for kind in ('nav', 'missions', 'sections'):
        for o in m.get(kind) or []:
            ident = next((o[k] for k in ('node', 'id', 'action', 'track', 'a') if o.get(k) is not None), None)
            out.append(((kind, o.get('op'), o.get('entry') or o.get('map_entry'), str(ident), o.get('prop')), o,
                        '%s %s' % (o.get('op'), ident), _short(o.get('entry') or o.get('map_entry')), 'value', kind))
    return out


def shared_hosts(mod_list, newmaps=None, missions=None):
    """Shipped blocks that more than one installed thing adds entries to (loaders, givers, other nodes): the pack replays them onto ONE copy of
    the block, entry by entry, under node names that carry each owner's own name; nothing here is a clash. -> [{block, owners, entries}].
    newmaps: the installed new-map records; missions: the installed mission record."""
    from . import mapnet
    use = {}

    def add(block, kind, name, n):
        b = _short(block).lower()
        if b:
            use.setdefault(b, {}).setdefault((kind, name), 0)
            use[b][(kind, name)] += n
    for m in mod_list or []:
        blocks = {}
        for _k, _v, _l, blk, _kind, _w in mod_items(m):
            blocks[blk] = blocks.get(blk, 0) + 1
        for b, n in blocks.items():
            if b and b.lower().endswith(('.map', '.submap')):
                add(b, 'mod', m.get('name') or m.get('id'), n)
    for pid, rec in (newmaps or {}).items():
        if rec.get('disabled'):
            continue
        for m in ((rec.get('params') or {}).get('maps') or []):
            if m.get('placement') == 'extension':
                add((m.get('host') or {}).get('block'), 'new map', rec.get('name') or pid, 1)
                continue
            for e in mapnet._entrances(m):
                add(e.get('block'), 'new map', rec.get('name') or pid, 2)
    for pid, p in ((missions or {}).get('projects') or {}).items():
        for h in (p.get('project') or {}).get('hosts') or []:
            if h.get('kind') == 'existing' and h.get('block'):
                add(h['block'], 'missions', p.get('name') or pid, 1)
        for nid, params in (p.get('newmaps') or {}).items():
            for m in (params or {}).get('maps') or []:
                for e in ([] if m.get('placement') == 'extension' else mapnet._entrances(m)):
                    add(e.get('block'), 'new map', params.get('package') or nid, 2)
    out = []
    for b, who in sorted(use.items()):
        if len({k for k in who}) > 1 and len({k[1] for k in who}) > 1:
            out.append(dict(block=b, label=mapnet.block_label(b), owners=[dict(kind=k[0], name=k[1], entries=n) for k, n in sorted(who.items())],
                            entries=sum(who.values())))
    return out


def conflicts(mod_list):
    """mod_list: recipes in load order. -> dict(clashes=[...], merged=[...], by_mod={id: {clashes, merged}}, counts).
    A clash: the same item set to different values by two or more mods (the last one in the list wins).
    Merged: mods that touch the same block but different items (both apply)."""
    groups, blocks = {}, {}
    for idx, m in enumerate(mod_list):
        for key, val, label, block, kind, where in mod_items(m):
            groups.setdefault(key, []).append((idx, val, label, block, kind, where))
            blocks.setdefault(block, {}).setdefault(idx, set()).add(key)
    clashes, by = [], {}

    def bump(m, k):
        d = by.setdefault(m.get('id') or str(id(m)), dict(clashes=0, merged=0))
        d[k] += 1
    for key, rows in groups.items():
        per_mod = {}
        for idx, val, label, block, kind, where in rows:
            per_mod[idx] = (val, label, block, kind, where)     # a mod that sets one item twice: its last value counts
        if len(per_mod) < 2:
            continue
        vals = [v[0] for v in per_mod.values()]
        if all(_same(vals[0], v) for v in vals[1:]):
            continue
        order = sorted(per_mod)
        win = order[-1]
        lab = per_mod[win][1]
        kind = per_mod[win][3]
        if kind == 'value' and any(per_mod[i][3] == 'removed' for i in order):
            kind = 'removed'
        clashes.append(dict(kind=kind, label=lab, block=per_mod[win][2], where=per_mod[win][4], key=list(map(str, key)), winner=mod_list[win].get('id'),
                            mods=[dict(id=mod_list[i].get('id'), name=mod_list[i].get('name'), value=_brief(per_mod[i][0]), wins=i == win) for i in order]))
        for i in order:
            bump(mod_list[i], 'clashes')
    # a delete and an edit of the same object by different mods
    nodes = {}
    for key, rows in groups.items():
        if key[0] in ('prop', 'pos', 'rot', 'del'):
            nodes.setdefault(key[1:4] if key[0] != 'prop' else key[1:4], []).append((key, rows))
    for node, parts in nodes.items():
        dels = {r[0] for key, rows in parts if key[0] == 'del' for r in rows}
        edits = {r[0] for key, rows in parts if key[0] != 'del' for r in rows}
        if dels and (edits - dels):
            idxs = sorted(dels | edits)
            if len(idxs) > 1:
                first = next(r for key, rows in parts for r in rows)
                clashes.append(dict(kind='removed', label='removed and changed', block=first[3], where=first[5], key=['node'] + list(map(str, node)),
                                    winner=mod_list[idxs[-1]].get('id'),
                                    mods=[dict(id=mod_list[i].get('id'), name=mod_list[i].get('name'),
                                               value='removes it' if i in dels else 'changes it', wins=i == idxs[-1]) for i in idxs]))
                for i in idxs:
                    bump(mod_list[i], 'clashes')
    merged = []
    clash_blocks = {c['block'] for c in clashes}
    for block, per in blocks.items():
        if len(per) < 2:
            continue
        keys = [per[i] for i in sorted(per)]
        shared = set.intersection(*keys) if keys else set()
        if len(set().union(*keys)) > len(shared) and block:
            merged.append(dict(block=block, mods=[mod_list[i].get('id') for i in sorted(per)], items=len(set().union(*keys)),
                               with_clash=block in clash_blocks))
            for i in per:
                bump(mod_list[i], 'merged')
    total = len(clashes)
    return dict(clashes=clashes[:MAX_ROWS], merged=merged, by_mod=by, counts=dict(clashes=total, merged=len(merged)))


def _brief(v):
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return s if len(s) <= 60 else s[:57] + '...'


# ------------------------------------------------------------------------------------------------ requirements
def normalise_requires(r):
    r = dict(r or {})
    out = {}
    if r.get('gameplay_plus') in (True, False):
        out['gameplay_plus'] = r['gameplay_plus']
    if str(r.get('min_app') or '').strip():
        out['min_app'] = str(r['min_app']).strip()
    mods = []
    for x in r.get('mods') or []:
        if isinstance(x, str):
            x = dict(id=x)
        if isinstance(x, dict) and re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', str(x.get('id') or '')):
            mods.append(dict(id=x['id'], version=str(x.get('version') or '')))
    if mods:
        out['mods'] = mods
    return out


def check_requirements(library, enabled_ids, env):
    """library: {id: recipe} of every mod; enabled_ids: the enabled ids in order; env: dict(app=<version>, gameplay_plus=<bool>).
    -> list of dict(mod, name, text): plain sentences, one per unmet need. Only the enabled mods are checked."""
    out = []
    on = set(enabled_ids)
    for mid in enabled_ids:
        m = library.get(mid)
        if not m:
            continue
        name = m.get('name') or mid
        r = normalise_requires(m.get('requires'))

        def add(t, mid=mid, name=name):
            out.append(dict(mod=mid, name=name, text=t))
        if r.get('gameplay_plus') is True and not env.get('gameplay_plus'):
            add('"%s" needs Gameplay+, which is not in your game.' % name)
        if r.get('gameplay_plus') is False and env.get('gameplay_plus'):
            add('"%s" is made for the original game and does not work with Gameplay+.' % name)
        if r.get('min_app') and vcmp(env.get('app'), r['min_app']) < 0:
            add('"%s" needs Mod Studio %s or newer. You have %s.' % (name, r['min_app'], env.get('app')))
        for d in r.get('mods') or []:
            dep = library.get(d['id'])
            if not dep:
                add('"%s" needs the mod "%s", which you do not have.' % (name, d['id']))
                continue
            dn = dep.get('name') or d['id']
            if d['id'] not in on:
                add('"%s" needs the mod "%s". It is not switched on.' % (name, dn))
            elif d.get('version') and vcmp(mod_version(dep), d['version']) < 0:
                add('"%s" needs "%s" version %s or newer. You have %s.' % (name, dn, d['version'], mod_version(dep)))
    return out


# ------------------------------------------------------------------------------------------------ game variant
SUPPORT = (('gog', 'en'), 'GOG, English: supported. Everything in Mod Studio works.')


def variant(game):
    """Which game this is and what Mod Studio can do with it (the ceilings table, X2): only the GOG build in English is fully
    supported. -> dict(store, language, languages, supported, text)."""
    folder = game.folder
    names = [n.lower() for n in os.listdir(folder)] if os.path.isdir(folder) else []
    gog = game.is_gog_exe or any(n.startswith('goggame-') for n in names)
    store = 'gog' if gog else 'retail'
    langs = sorted({m.group(1) for m in (re.match(r'([a-z]{2})_sounds\.naz$', n) for n in names) if m})
    try:
        for n in game.names():
            m = re.search(r'/overdose/([a-z]{2})/overdose_\1\.main$', n)
            if m and m.group(1) not in langs:
                langs.append(m.group(1))
    except Exception:
        pass
    lang = 'en' if (not langs or 'uk' in langs) else langs[0]
    if store == 'gog' and lang == 'en' and game.is_gog_exe:
        text, ok = 'GOG game, English: fully supported.', True
    elif store == 'gog' and lang == 'en':
        text, ok = 'GOG game with a changed TOD.exe: data mods work, some features are off.', False
    elif store == 'gog':
        text, ok = 'GOG game, another language: data mods work; new text is written for English only.', False
    else:
        text, ok = 'Retail game: data mods should work but are not tested. Features that need Gameplay+ or TOD HD are off.', False
    return dict(store=store, language=lang, languages=langs, exe_md5=game.exe_md5, supported=ok, text=text)


def environment(game):
    gp = bool(game) and any(os.path.exists(os.path.join(game.folder, n)) for n in ('TODGameplay.dll', 'todgameplay.dll'))
    return dict(app=app_version(), gameplay_plus=gp)
