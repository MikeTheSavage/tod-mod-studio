"""The asset index: which blocks hold each model and each texture, which models use which texture, and which of them TOD HD (or any
other earlier archive) has already replaced.

Built once from the game's blocks (a job, a few minutes), cached in <cache>/assets/asset_index.json. A texture or a model that lives in
several blocks is one entry with every block listed, because a replacement has to reach every copy (each block carries its own).

  textures  lower-case name -> dict(name, w, h, fmt, levels, size, blocks [entries], hd [entries where the record differs from blocks.naz])
  models    lower-case name -> dict(name, textures [lower-case names], blocks, hd, size_bytes)
"""
import hashlib
import json
import os
import struct
import time

import numpy as np

from . import paths

VERSION = 2
SENT = 0xBAADF00D
KINDS = ('.main', '.map', '.submap', '.mission', '.playerdata')


def index_path():
    d = os.path.join(paths.cache_dir(), 'assets')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'asset_index.json')


def fast_starts(info, n):
    """Record heads of an INFO blob (16-aligned, sentinel at +12, type <= 10, a name pointer to '/...'): numpy pre-filter, exact test after."""
    a = np.frombuffer(bytes(info[:len(info) // 16 * 16]), dtype='<u4').reshape(-1, 4)
    cand = np.nonzero((a[:, 3] == SENT) & (a[:, 0] <= 10))[0]
    out = []
    for c in cand:
        o = int(c) * 16
        np_ = (o + 4 + int(a[c, 1])) & 0xFFFFFFFC
        if np_ < len(info) and info[np_] == 0x2F:
            e = info.find(b'\0', np_, min(len(info), np_ + 1024))
            if e > 0 and all(32 <= ch < 127 for ch in info[np_:e]):
                out.append(o)
    return out


def _name(info, R):
    np_ = (R + 4 + struct.unpack_from('<I', info, R + 4)[0]) & 0xFFFFFFFC
    return bytes(info[np_:info.find(b'\0', np_)]).decode('latin-1')


def texture_fields(info, R):
    """-> dict(w, h, fmt, levels) of a TEXTURE record, or None."""
    try:
        gp = struct.unpack_from('<i', info, R + 0x28)[0]
        if gp == 0:
            return None
        G = R + 0x28 + gp
        w, h = struct.unpack_from('<II', info, G + 0x14)
        fmt = struct.unpack_from('<i', info, G + 0x1C)[0]
        lw = struct.unpack_from('<I', info, G + 0x24)[0]
        return dict(w=w, h=h, fmt={1: 'RGBA32', 7: 'DXT1'}.get(fmt, 'other%d' % fmt), levels=(lw >> 1) & 0xFF)
    except Exception:                                         # noqa: BLE001
        return None


def scan_block(raw, ext, tb, tm):
    """-> dict(textures {lname: dict}, models {lname: dict}) of one block."""
    b = tb.Block(raw, ext)
    info = bytes(b.info)
    starts = fast_starts(info, b.n)
    if len(starts) != b.n:
        starts = tb.record_starts(info, b.n)
    ends = starts[1:] + [len(info)]
    tex, mod = {}, {}
    for k, R in enumerate(starts):
        t = struct.unpack_from('<I', info, R)[0]
        if t == 0:
            f = texture_fields(info, R)
            if f:
                nm = _name(info, R)
                f.update(name=nm, size=len(b.payloads[k]), sig=hashlib.sha1(info[R:ends[k]] + b.payloads[k]).hexdigest()[:16])
                tex[nm.lower()] = f
        elif t == 3:
            nm = _name(info, R)
            try:
                m = tm.decode(info, R, ends[k])
                names = [x['s'].decode('latin-1').lower() for x in m['texnames']]
            except Exception:                                 # noqa: BLE001
                names = []
            mod[nm.lower()] = dict(name=nm, textures=names, size_bytes=ends[k] - R,
                                   sig=hashlib.sha1(info[R:ends[k]]).hexdigest()[:16])
    return dict(textures=tex, models=mod)


def build(ws, progress=None):
    from todct import tools
    K = tools.load()
    game = ws.game
    base = game.base()
    names = sorted(n for n in base.names if '/shared/' in n.lower() and n.lower().endswith(KINDS)
                   and not n.lower().split('/')[-1].startswith('mainmenu'))
    textures, models = {}, {}
    t0 = time.time()
    for i, e in enumerate(names):
        if progress:
            progress('textures and models of %s' % e.split('/')[-1], i, len(names))
        ext = os.path.splitext(e)[1]
        raw, src = game.read_block(e, ws.base_mode)
        try:
            cur = scan_block(raw, ext, K.tb, K.tm)
        except Exception:                                     # noqa: BLE001
            continue
        ref = None
        if src.lower() != 'blocks.naz':
            try:
                ref = scan_block(base.read(e), ext, K.tb, K.tm)
            except Exception:                                 # noqa: BLE001
                ref = None
        for kind, store in (('textures', textures), ('models', models)):
            for ln, r in cur[kind].items():
                d = store.setdefault(ln, dict(name=r['name'], blocks=[], hd=[]))
                if kind == 'textures':
                    d.update(w=r['w'], h=r['h'], fmt=r['fmt'], levels=r['levels'], size=r['size'])
                else:
                    d.update(textures=r['textures'], size_bytes=r['size_bytes'])
                d['blocks'].append(e)
                if ref is not None:
                    o = ref[kind].get(ln)
                    if o is None or o['sig'] != r['sig']:
                        d['hd'].append(e)
    users = {}
    for ln, m in models.items():
        for t in m['textures']:
            users.setdefault(t, []).append(ln)
    for ln, t in textures.items():
        t['users'] = sorted(users.get(ln, []))
    doc = dict(version=VERSION, built=time.strftime('%Y-%m-%d %H:%M:%S'), seconds=round(time.time() - t0, 1), blocks=len(names),
               game=_game_id(ws), textures=textures, models=models)
    p = index_path()
    with open(p + '.part', 'w', encoding='utf-8') as f:
        json.dump(doc, f, separators=(',', ':'))
    os.replace(p + '.part', p)
    _CACHE.clear()
    return dict(textures=len(textures), models=len(models), blocks=len(names), seconds=doc['seconds'])


def _game_id(ws):
    try:
        return '%s|%d' % (ws.game.naz, os.path.getsize(ws.game.naz)) + '|' + json.dumps(ws.game.signature(), default=str)
    except Exception:                                         # noqa: BLE001
        return ''


_CACHE = {}


def load(ws=None):
    """The cached index or None (not built yet, or built for another game folder)."""
    p = index_path()
    if not os.path.exists(p):
        return None
    mt = os.path.getmtime(p)
    if _CACHE.get('mt') != mt:
        try:
            with open(p, encoding='utf-8') as f:
                _CACHE.update(doc=json.load(f), mt=mt)
        except Exception:                                     # noqa: BLE001
            return None
    doc = _CACHE['doc']
    if doc.get('version') != VERSION:
        return None
    if ws is not None and ws.game is not None and doc.get('game') != _game_id(ws):
        return None
    return doc


def ensure(ws, progress=None):
    doc = load(ws)
    if doc is None:
        build(ws, progress)
        doc = load(ws)
    return doc


def norm(name):
    s = (name or '').lower().replace('\\', '/')
    if not s.startswith('/'):
        s = '/' + s
    if not s.startswith('/data/'):
        s = '/data' + s
    return s


def rows(doc, q):
    """Texture list for the editor: search text, only used-by, offset/limit."""
    t = (q.get('q') or '').lower()
    only = q.get('only')
    out = []
    for ln, r in doc['textures'].items():
        if t and t not in ln:
            continue
        if only == 'hd' and not r['hd']:
            continue
        if only == 'unused' and r['users']:
            continue
        out.append(dict(key=ln, name=r['name'], w=r['w'], h=r['h'], fmt=r['fmt'], size=r['size'], users=len(r['users']),
                        blocks=len(r['blocks']), hd=bool(r['hd'])))
    out.sort(key=lambda x: (-x['users'], x['key']))
    return out
