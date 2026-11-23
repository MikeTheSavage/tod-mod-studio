"""Character models as enemies and people: which models the game has, what each one needs, and how a block gets one it lacks.

A `character_placeholder` names its body with `Model` (a number, 0 to 31). The mesh of that body is not global: every block that
uses a body carries the mesh and its textures as asset records and registers it with a `database_model_resource` node
(`Character_Model` = the number). Only the pedestrian body (23) and Ram (20) live in the always-loaded main block, so a placeholder
that asks for any other body in a block that does not carry it has nothing to draw.

This module
  * serves the table (name, group, usual behaviour and side, texture sets, which blocks carry the body),
  * works out which models an edit needs that the target block lacks, and
  * copies the model and its textures from a shipped block that has them, plus the registering node (the build adds it as an `add`).
Data about the shipped blocks is mined once from the retail game (scripts/mine_characters.py) and kept in data/characters_mined.json.
"""
import json
import os
import re

from . import names

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_RESIDENT = (20, 23)                        # Ram and the pedestrian body: registered in overdose.main
MAIN_PATHS = {20: '/characters/ram/ram.model', 23: '/characters/civil/civil.model'}
HOSTILE = 9                                      # FactionID of the enemy side
_MINED = None
_TABLE = None


def mined():
    global _MINED
    if _MINED is None:
        with open(os.path.join(HERE, 'data', 'characters_mined.json'), encoding='utf-8') as f:
            _MINED = {int(k): v for k, v in json.load(f).items()}
    return _MINED


def _usual(uses):
    """(behaviour, side) most used by the shipped placeholders of a body; enemy placements win when there are any."""
    rows = []
    for k, n in (uses or {}).items():
        ai, fac = k.split('|')
        rows.append((int(ai), int(fac), n))
    host = [r for r in rows if r[1] == HOSTILE]
    pool = host or rows
    if not pool:
        return None, None
    best = max(pool, key=lambda r: r[2])
    return best[0], best[1]


def table():
    """One row per model number (0 to 31), sorted: name, group, usual behaviour and side, looks, whether it can be placed."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    m = mined()
    rows = []
    for n in sorted(names.CHARACTERS):
        nm, group = names.CHARACTERS[n]
        info = m.get(n) or {}
        paths = info.get('paths') or ([MAIN_PATHS[n]] if n in MAIN_PATHS else [])
        ai, side = _usual(info.get('uses'))
        sets = sorted(int(k) for k in (info.get('textures') or {}))
        if n == 23:
            sets = sorted(set(sets) | set(names.PEDESTRIAN_LOOKS))
        placeable = bool(paths) and n != 20
        if group == 'enemy' and side not in (None, HOSTILE) and any(int(k.split('|')[1]) == HOSTILE for k in (info.get('uses') or {})):
            side = HOSTILE
        rows.append(dict(id=n, name=nm, group=group, paths=paths, file=(paths[0].rsplit('/', 1)[-1] if paths else ''), placeable=placeable,
                         ai=ai if ai is not None else 0, side=side if side is not None else HOSTILE,
                         looks=[dict(id=t, name=names.look_name(n, t)) for t in (sets or [0])],
                         resident=n in MAIN_RESIDENT, blocks=sorted((info.get('blocks') or {}).keys())))
    _TABLE = rows
    return rows


def row(n):
    for r in table():
        if r['id'] == int(n):
            return r
    return None


def enemies():
    """The models the enemy picker offers: placed as a fighting enemy in the shipped data."""
    return [r for r in table() if r['placeable'] and r['group'] == 'enemy']


def left_out():
    """Models that cannot be offered, with the reason (shown in NOTES, never in the UI)."""
    out = []
    for r in table():
        if r['placeable']:
            continue
        out.append((r['id'], r['name'], 'the player body' if r['id'] == 20 else 'no mesh in any block of the game'))
    return out


# ---------------------------------------------------------------------------------------------- what an edit needs
def _model_of(op):
    """The Model number an op leaves on a character: an add with set.Model, a set of prop Model; else None."""
    if op.get('op') == 'add':
        v = (op.get('set') or {}).get('Model')
    elif op.get('op') == 'set' and op.get('prop') == 'Model':
        v = op.get('value')
    else:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def needed(ops):
    """{entry: set of model numbers} the ops put on characters."""
    out = {}
    for o in ops:
        n = _model_of(o)
        if n is None or not o.get('entry'):
            continue
        out.setdefault(o['entry'], set()).add(n)
    return out


def _norm(p):
    return str(p or '').lower().replace('\\', '/')


def has_resource(raw, ext, model):
    """True when the block already registers this body (its model path occurs in a fragment payload) or the main block does."""
    n = int(model)
    if n in MAIN_RESIDENT:
        return True
    r = row(n)
    if not r or not r['paths']:
        return False
    import todblock as tb
    b = tb.Block(raw, ext)
    want = [p.lower().encode() for p in r['paths']]
    for k, p in enumerate(b.payloads):
        low = bytes(p).lower()
        if any(w in low for w in want):
            # a fragment payload only: asset records carry their names in the info, not in payloads
            return True
    return False


def missing(ws, entry, raw, models):
    """The models of `models` the block `raw` (entry) cannot draw yet."""
    ext = os.path.splitext(entry)[1]
    return sorted(n for n in set(models) if not has_resource(raw, ext, n))


def donor(n, prefer=None):
    """(entry, frag, node, path) of the shipped block that supplies body n: a small mission block when there is one."""
    info = mined().get(int(n)) or {}
    blocks = info.get('blocks') or {}
    if not blocks:
        raise ValueError('model %s has no mesh in the game' % n)
    order = sorted(blocks.items(), key=lambda kv: (not kv[1]['entry'].endswith('.mission'), kv[0].startswith(('intermission', 'gameover')), kv[0]))
    short, d = order[0]
    return d['entry'], d['frag'], d['node'], d['path']


def resource_ops(ws, entry, models, existing_uids=()):
    """`add` ops (the build's own kind) that register each body in the block: a copy of the shipped resource node."""
    ops = []
    for n in sorted(models):
        e, frag, node, path = donor(n)
        ops.append(dict(op='add', uid='res_model_%d' % n, entry=entry, template=dict(entry=e, frag=frag, node=node),
                        name='TODMS_body_%d' % n, set={}, pos=None, rot=None, system=True))
    return ops


# ---------------------------------------------------------------------------------------------- copy the mesh and textures
def _records(tb, block):
    info = bytes(block.info)
    st = tb.record_starts(info, block.n)
    en = st[1:] + [len(info)]
    return [dict(type=tb.u32(info, R), name=tb.record_name(info, R), rec=info[R:E], payload=block.payloads[k]) for k, (R, E) in enumerate(zip(st, en))]


def copy_assets(ws, entry, raw, models, report=None):
    """The block's bytes with the mesh and textures of every body in `models` appended (when the block has no such records)."""
    import todblock as tb
    ext = os.path.splitext(entry)[1]
    b = tb.Block(raw, ext)
    items = _records(tb, b)
    have = {i['name'].lower() for i in items}
    added = []
    for n in sorted(models):
        if int(n) in MAIN_RESIDENT:
            continue
        e, frag, node, path = donor(n)
        sraw, _ = ws.read_block(e)
        sb = tb.Block(sraw, os.path.splitext(e)[1])
        srec = _records(tb, sb)
        by = {i['name'].lower(): i for i in srec}
        mname = ('/data' + _norm(path)) if not _norm(path).startswith('/data') else _norm(path)
        if mname not in by:
            raise ValueError('the donor block %s has no record %s' % (e.rsplit('/', 1)[-1], mname))
        want = [by[mname]]
        for t in sorted(set(x.decode() for x in re.findall(rb'/data/[A-Za-z0-9_/\.\- ]+\.bmp', by[mname]['rec']))):
            if t.lower() in by:
                want.append(by[t.lower()])
        for it in want:
            if it['name'].lower() in have:
                continue
            items.append(dict(it))
            have.add(it['name'].lower())
            added.append(it['name'])
    if not added:
        return raw
    b.info = bytearray(b''.join(i['rec'] for i in items))
    b.payloads = [i['payload'] for i in items]
    b.n = len(items)
    if report is not None:
        report['character_assets'] = [a.rsplit('/', 1)[-1] for a in added]
    return b.serialize()


# ---------------------------------------------------------------------------------------------- a whole block (mission templates)
def retag_block(ws, entry, raw, model, report=None):
    """The block's bytes with every enemy-side placeholder wearing body `model`; the body is registered and its mesh copied when the block lacks
    it. Used on the mission blocks the template library builds (their bandits come from the template's shipped block)."""
    from . import build as B, level as lv
    T = ws.T
    n = int(model)
    if row(n) is None or not row(n)['placeable']:
        raise ValueError('model %s cannot be placed' % model)
    L = lv.BlockLevel(entry, raw, T, ws.main_lookup)
    ents, _ = L.entities('retag')
    fn = {k: nm for k, nm in L.frs}
    ops = [dict(op='set', entry=entry, frag=fn[e['k']], node=e['node'], prop='Model', value=n)
           for e in ents if e['cat'] == 'character' and (e.get('sub') or {}).get('FactionID') == HOSTILE and (e.get('sub') or {}).get('Model') != n]
    rep = report if report is not None else {}
    rep['retagged'] = len(ops)
    if ops:
        raw = B.stage_a(entry, raw, ops, T, rep)
    if missing(ws, entry, raw, [n]):
        uid = {}
        raw = B.stage_b(ws, entry, raw, resource_ops(ws, entry, [n]), T, rep, uid)
        raw = copy_assets(ws, entry, raw, [n], rep)
    return raw
