"""Mod files that travel between people: .todmod (one mod), .todcollection (mods plus their order) and .todpiece (one prefab, route
set, tuning preset or mission). All three are recipes and assets, never code. Every file is checked here before anything is written
to the library: executable content, path tricks, entries nobody expects and oversized or lying embedded files are refused (idea 42).

A file is JSON, or a zip that holds mod.json plus screenshots (a package from a download site). Nothing in either is ever run.
"""
import base64
import binascii
import io
import json
import os
import re
import zipfile
import zlib

MAX_FILE = 256 * 1024 * 1024
MAX_JSON = 64 * 1024 * 1024
MAX_BLOB = 128 * 1024 * 1024            # one embedded file, after unpacking
MAX_SHOTS = 6
MAX_SHOT_BYTES = 700 * 1024
FORMATS = dict(mod='todms-mod', collection='todms-collection', piece='todms-piece')
EXTENSIONS = dict(mod='.todmod', collection='.todcollection', piece='.todpiece')
SCHEMA = 5

TOP_KEYS = {'format', 'version', 'schema', 'id', 'name', 'author', 'description', 'level', 'data', 'collision', 'nav', 'missions',
            'sections', 'models', 'textures', 'view', 'created', 'updated', 'editor', 'blobs', 'page', 'requires', 'origin', 'built', 'assets', 'source'}
COLLECTION_KEYS = {'format', 'schema', 'name', 'author', 'description', 'version', 'created', 'mods', 'order', 'enabled', 'page'}
PIECE_KEYS = {'format', 'schema', 'kind', 'name', 'author', 'created', 'data', 'blobs', 'description'}
PAGE_KEYS = {'version', 'changelog', 'credits', 'screenshots', 'reuse', 'license', 'summary'}
PATH_KEYS = {'entry', 'path', 'file', 'target', 'source', 'map_entry', 'source_submap', 'frag', 'fragment', 'like', 'template', 'model', 'modelres'}
EXEC_EXT = {'.exe', '.dll', '.bat', '.cmd', '.com', '.scr', '.ps1', '.psm1', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.msi', '.lnk', '.hta',
            '.jar', '.py', '.pyc', '.pyw', '.sh', '.cpl', '.reg', '.sys', '.so', '.dylib', '.pif', '.gadget', '.inf', '.url'}
MAGIC = ((b'MZ', 'a Windows program'), (b'\x7fELF', 'a program'), (b'#!', 'a script'), (b'MSCF', 'a cabinet archive'),
         (b'Rar!', 'a RAR archive'), (b'7z\xbc\xaf', 'a 7-Zip archive'), (b'\xca\xfe\xba\xbe', 'a program'), (b'\xcf\xfa\xed\xfe', 'a program'),
         (b'<script', 'a script'), (b'<?php', 'a script'), (b'@echo', 'a script'))
IMAGE_MAGIC = ((b'\x89PNG\r\n\x1a\n', 'png'), (b'\xff\xd8\xff', 'jpeg'), (b'BM', 'bmp'), (b'DDS ', 'dds'))
ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
SEG_BAD = re.compile(r'(^|[\\/])\.\.([\\/]|$)')
DRIVE = re.compile(r'^[A-Za-z]:|^\\|^//')


class Unsafe(ValueError):
    """The file was refused. .problems = the plain sentences, one per thing found."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__('This file was not added: ' + ' '.join(self.problems[:4]) + (' (and %d more)' % (len(self.problems) - 4) if len(self.problems) > 4 else ''))


def _exec_name(s):
    ext = os.path.splitext(str(s).replace('\\', '/').split('/')[-1].lower())[1]
    return ext in EXEC_EXT


def _bad_path(s):
    s = str(s)
    return bool(SEG_BAD.search(s) or DRIVE.match(s) or '\x00' in s)


def _walk_paths(v, key, out, where):
    """Every string under a path-like key: no '..', no absolute or drive path, no executable extension."""
    if isinstance(v, dict):
        for k, x in v.items():
            _walk_paths(x, k, out, where + '/' + str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _walk_paths(x, key, out, where)
    elif isinstance(v, str) and key in PATH_KEYS:
        if _bad_path(v):
            out.append('A file name inside the mod points outside the game data ("%s").' % v[:60])
        elif _exec_name(v):
            out.append('The mod names a program file ("%s").' % v[:60])


def _numbers(v, out, st):
    if isinstance(v, dict):
        for x in v.values():
            _numbers(x, out, st)
    elif isinstance(v, list):
        for x in v:
            _numbers(x, out, st)
    elif isinstance(v, bool):
        pass
    elif isinstance(v, (int, float)):
        if v != v or v in (float('inf'), float('-inf')):
            out.append('The mod holds a number that is not valid.')
        elif abs(v) > 1e12:
            st['huge'] = st.get('huge', 0) + 1


def _blob_problems(sha, b64, out):
    """Unpack one embedded file with a size cap and look at what it is."""
    if not re.fullmatch(r'[0-9a-f]{16,64}', str(sha)):
        out.append('An embedded file has a name that is not a file fingerprint.')
        return
    try:
        raw = base64.b64decode(b64, validate=True)
        d = zlib.decompressobj()
        data = d.decompress(raw, MAX_BLOB + 1)
    except (binascii.Error, zlib.error, ValueError, TypeError):
        out.append('An embedded file is damaged.')
        return
    if len(data) > MAX_BLOB or d.unconsumed_tail:
        out.append('An embedded file is far too large.')
        return
    kind = file_kind(data)
    if kind is None:
        out.append('An embedded file is not a picture or a model scene.')
    elif kind.startswith('bad:'):
        out.append('An embedded file is %s.' % kind[4:])


def file_kind(data):
    """'png' | 'jpeg' | 'bmp' | 'dds' | 'tga' | 'scene' | 'bad:<what>' | None."""
    head = data[:16]
    for m, what in MAGIC:
        if head.startswith(m):
            return 'bad:' + what
    for m, k in IMAGE_MAGIC:
        if head.startswith(m):
            return k
    if head.startswith(b'PK\x03\x04'):
        return 'scene' if _scene_ok(data) else 'bad:an archive with unexpected content'
    if len(data) > 18 and data[1] in (0, 1) and data[2] in (1, 2, 3, 9, 10, 11):
        return 'tga'
    return None


def _scene_ok(data):
    """An npz: only .npy members, and none of them holds python objects (that would need pickle)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        total = 0
        for i in z.infolist():
            if not i.filename.endswith('.npy') or _bad_path(i.filename) or '/' in i.filename:
                return False
            total += i.file_size
            if total > MAX_BLOB:
                return False
            with z.open(i) as f:
                h = f.read(160)
            if not h.startswith(b'\x93NUMPY') or b'|O' in h or b"'O'" in h or b'object' in h:
                return False
        return True
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def _check_page(p, out):
    if not isinstance(p, dict):
        out.append('The mod page is not in the expected form.')
        return
    for k in p:
        if k not in PAGE_KEYS:
            out.append('The mod page holds an unexpected entry ("%s").' % str(k)[:30])
    shots = p.get('screenshots') or []
    if not isinstance(shots, list) or len(shots) > MAX_SHOTS:
        out.append('The mod page has more than %d screenshots.' % MAX_SHOTS)
        return
    for s in shots:
        try:
            raw = base64.b64decode(s.get('data') or '', validate=True)
        except (binascii.Error, ValueError, AttributeError, TypeError):
            out.append('A screenshot is damaged.')
            continue
        if len(raw) > MAX_SHOT_BYTES:
            out.append('A screenshot is too large.')
        elif not (raw.startswith(b'\x89PNG') or raw.startswith(b'\xff\xd8\xff')):
            out.append('A screenshot is not a picture.')
    if not isinstance(p.get('changelog') or [], list):
        out.append('The changelog is not in the expected form.')


def check_mod(m):
    """-> (problems, notes) for one recipe dict. problems refuse the file; notes are shown (counts, odd values)."""
    out, st = [], {}
    if not isinstance(m, dict):
        return ['The file is not a mod.'], []
    for k in m:
        if k not in TOP_KEYS:
            out.append('The mod holds an entry that mods do not have ("%s").' % str(k)[:30])
    if m.get('id') is not None and not ID_RE.match(str(m['id'])):
        out.append('The mod has an id that is not allowed.')
    for k in ('level', 'collision', 'nav', 'missions', 'sections', 'models', 'textures'):
        if m.get(k) is not None and not isinstance(m[k], list):
            out.append('The "%s" part of the mod is not a list.' % k)
    if m.get('data') is not None and not isinstance(m['data'], dict):
        out.append('The "data" part of the mod is not in the expected form.')
    body = {k: v for k, v in m.items() if k not in ('blobs', 'page')}
    _walk_paths(body, '', out, '')
    _numbers(body, out, st)
    _check_page(m.get('page') or {}, out)
    blobs = m.get('blobs') or {}
    if not isinstance(blobs, dict):
        out.append('The embedded files are not in the expected form.')
    else:
        for s, b in blobs.items():
            _blob_problems(s, b, out)
    notes = []
    if st.get('huge'):
        notes.append('%d values are far outside the game world.' % st['huge'])
    return list(dict.fromkeys(out)), notes


def check_collection(c):
    out = []
    if not isinstance(c, dict):
        return ['The file is not a collection.']
    for k in c:
        if k not in COLLECTION_KEYS:
            out.append('The collection holds an entry that collections do not have ("%s").' % str(k)[:30])
    if not isinstance(c.get('mods'), list) or not c['mods']:
        out.append('The collection holds no mods.')
        return out
    if len(c['mods']) > 100:
        out.append('The collection holds more than 100 mods.')
    for m in c['mods']:
        out += check_mod(m)[0]
    return list(dict.fromkeys(out))


def check_piece(p):
    out = []
    if not isinstance(p, dict):
        return ['The file is not a piece.']
    for k in p:
        if k not in PIECE_KEYS:
            out.append('The piece holds an entry that pieces do not have ("%s").' % str(k)[:30])
    if p.get('kind') not in ('prefab', 'routes', 'tuning', 'mission'):
        out.append('The piece is of a kind this version does not know.')
    if not isinstance(p.get('data'), dict):
        out.append('The piece holds no data.')
        return out
    if len(json.dumps(p['data'])) > 8 * 1024 * 1024:
        out.append('The piece is far too large.')
    _walk_paths(p['data'], '', out, '')
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------------------------ reading a file
def _zip_object(data):
    """A zip package: mod.json (or one .todmod / .todcollection / .todpiece) plus screenshots/*.png|jpg and a short readme. Nothing else."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Unsafe(['The file is damaged.'])
    problems, main = [], None
    total = 0
    for i in z.infolist():
        n = i.filename
        total += i.file_size
        if _bad_path(n):
            problems.append('The package has a file outside its own folder ("%s").' % n[:60])
        elif i.is_dir():
            continue
        elif _exec_name(n):
            problems.append('The package holds a program file ("%s").' % n[:60])
        elif n in ('mod.json', 'collection.json', 'piece.json') or n.lower().endswith(tuple(EXTENSIONS.values())):
            main = i
        elif re.fullmatch(r'screenshots/[A-Za-z0-9_.-]+\.(png|jpg|jpeg)', n) or n.lower() in ('readme.txt', 'page.md', 'sha256.txt'):
            pass
        else:
            problems.append('The package holds a file that mods do not have ("%s").' % n[:60])
    if total > MAX_FILE:
        problems.append('The package is far too large when unpacked.')
    if problems:
        raise Unsafe(problems)
    if main is None or main.file_size > MAX_JSON:
        raise Unsafe(['The package holds no mod.'])
    obj = json.loads(z.read(main).decode('utf-8-sig'))
    if isinstance(obj, dict) and obj.get('format') == FORMATS['mod'] and not (obj.get('page') or {}).get('screenshots'):
        shots = []
        for i in z.infolist():
            if i.filename.startswith('screenshots/') and len(shots) < MAX_SHOTS:
                shots.append(dict(name=os.path.basename(i.filename), data=base64.b64encode(z.read(i)).decode('ascii')))
        if shots:
            obj.setdefault('page', {})['screenshots'] = shots
    return obj


def parse(data):
    """bytes -> (kind, object, notes). Raises Unsafe with plain sentences for anything that must not be added."""
    if len(data) > MAX_FILE:
        raise Unsafe(['The file is far too large (over %d MB).' % (MAX_FILE >> 20)])
    head = data[:4]
    if head.startswith(b'PK'):
        obj = _zip_object(data)
    else:
        for m, what in MAGIC:
            if data.startswith(m):
                raise Unsafe(['The file is %s, not a mod.' % what])
        if len(data) > MAX_JSON + MAX_BLOB:
            raise Unsafe(['The file is far too large.'])
        try:
            obj = json.loads(data.decode('utf-8-sig'))
        except (ValueError, UnicodeDecodeError):
            raise Unsafe(['The file is not a mod file.'])
    if not isinstance(obj, dict):
        raise Unsafe(['The file is not a mod file.'])
    fmt = obj.get('format')
    kind = next((k for k, v in FORMATS.items() if v == fmt), None)
    if kind is None:
        raise Unsafe(['The file is not a TOD Mod Studio file.'])
    notes = []
    if kind == 'mod':
        problems, notes = check_mod(obj)
    elif kind == 'collection':
        problems = check_collection(obj)
    else:
        problems = check_piece(obj)
    if problems:
        raise Unsafe(problems)
    return kind, obj, notes


def read(path):
    if os.path.getsize(path) > MAX_FILE:
        raise Unsafe(['The file is far too large (over %d MB).' % (MAX_FILE >> 20)])
    with open(path, 'rb') as f:
        return parse(f.read())


def check_file(path):
    """Safe or not, without adding anything. -> dict(ok, kind, name, notes, problems)."""
    try:
        kind, obj, notes = read(path)
    except Unsafe as e:
        return dict(ok=False, problems=e.problems)
    except OSError as e:
        return dict(ok=False, problems=[str(e)])
    return dict(ok=True, kind=kind, name=obj.get('name'), notes=notes, problems=[])
