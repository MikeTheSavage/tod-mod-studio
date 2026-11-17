"""One shared check of archive slots, archive sizes, zip rules and entry-name hashes. Every install path runs it (limits P1-P4).

  slots   the engine mounts every name on the `filesystem =` line that exists on disk, plus the `<lang>_` variant of each name
          (the language is probed from the sounds archives). A directory, a 0-byte file or a locked file counts as well.
  size    a zip Mod Studio writes stays below 1.9 GB (warning) and below 0x7FFFFFFF bytes (refused).
  zip     STORED entries only, no archive comment, equal local and central extra lengths, legal names.
  hash    the engine finds an entry by CRC-32 of its lower-case name: no two names in the whole chain may share it.
  config  configpc.txt ends with a newline (otherwise the engine drops the whole filesystem value).
"""
import os
import re
import struct
import zipfile

from . import limits

LANGS = ('es', 'fr', 'de', 'it', 'uk')              # probed in this order; the last one found wins
OWN_PREFIXES = ('todms_',)


def tod_crc(b):
    """The engine's file-name hash (CRC-32 polynomial, LSB-first feed, 4 zero bytes appended)."""
    r = 0
    for c in bytes(b) + b'\0\0\0\0':
        for bit in range(8):
            top = r & 0x80000000
            r = ((r << 1) & 0xFFFFFFFF) | ((c >> bit) & 1)
            if top:
                r ^= 0x04C11DB7
    return r


def engine_name(name):
    b = name.encode('latin-1', 'replace') if isinstance(name, str) else bytes(name)
    b = b.replace(b'\\', b'/')
    return bytes(c + 32 if 0x41 <= c <= 0x5A else c for c in b)


def name_crc(entry):
    return tod_crc(engine_name(entry))


# ------------------------------------------------------------------------------------------------ slots
def active_language(folder):
    lang = None
    for lg in LANGS:
        for ext in ('naz', 'zip'):
            if os.path.exists(os.path.join(folder, '%s_sounds.%s' % (lg, ext))):
                lang = lg
    return lang


def slot_users(folder, names):
    """The names that take an archive slot: every listed name that exists (file, directory, empty file), and the `<lang>_`
    variant of each that exists. -> list of names, in mount order, without repeats."""
    lang = active_language(folder)
    out, seen = [], set()
    for n in names:
        for cand in (n, ('%s_%s' % (lang, n)) if lang else None):
            if cand and cand.lower() not in seen and os.path.exists(os.path.join(folder, cand)):
                seen.add(cand.lower())
                out.append(cand)
    return out


def slot_count(folder, names):
    users = slot_users(folder, names)
    return dict(count=len(users), users=users, limit=limits.value('P1'))


def slot_check(folder, fs, add=None, remove=()):
    """Refuse a filesystem line that would need more than 8 slots. `add` is a name about to be created (counted even though
    it is not on disk yet). Returns the slot report of the line after the change."""
    rm = {a.lower() for a in remove}
    after = [a for a in fs if a.lower() not in rm and a.lower() != (add or '').lower()]
    if add:
        after.insert(0, add)
    users = slot_users(folder, [a for a in after if a != add])
    if add:
        users.insert(0, add)
    lim = limits.value('P1')
    if len(users) > lim:
        raise ValueError('The game can only load %d archive files and this would make %d (%s). Remove one of the other '
                         'mods or map packages first.' % (lim, len(users), ', '.join(users)))
    return dict(count=len(users), users=users, limit=lim)


# ------------------------------------------------------------------------------------------------ size
def size_check(path):
    """-> list of (level, text). Refuses (error) at the hard limit, warns above the soft one."""
    n = os.path.getsize(path)
    hard, soft = limits.value('P2'), limits.value('P2_soft')
    name = os.path.basename(path)
    if n >= hard:
        return [('error', '%s is %.2f GB: the game cannot read an archive of 2 GB or more.' % (name, n / 1e9))]
    if n >= soft:
        return [('warn', '%s is %.2f GB, close to the 2 GB limit of one archive.' % (name, n / 1e9))]
    return []


# ------------------------------------------------------------------------------------------------ zip rules
_NAME = re.compile(r'^[a-z0-9_.\-]+$')
_LANG_PREFIX = re.compile(r'^(uk|fr|it|de|es|dk)_')


def zip_rules(path, check_names=True):
    """P3 rules for an archive Mod Studio writes. -> list of problem texts (empty = fine)."""
    out = []
    base = os.path.basename(path)
    if not re.fullmatch(r'[A-Za-z0-9_.\-]+', base) or _LANG_PREFIX.match(base.lower()):
        out.append('%s: the archive name may only use letters, digits, dot, dash and underscore, and no language prefix.' % base)
    with zipfile.ZipFile(path) as z:
        if z.comment:
            out.append('%s has a zip comment, which shifts the end record the game reads.' % base)
        with open(path, 'rb') as f:
            for zi in z.infolist():
                if zi.compress_type != zipfile.ZIP_STORED:
                    out.append('%s: "%s" is compressed; the game only reads stored entries.' % (base, zi.filename))
                    continue
                f.seek(zi.header_offset)
                h = f.read(30)
                if len(h) < 30 or h[:4] != b'PK\x03\x04':
                    out.append('%s: "%s" has a broken local header.' % (base, zi.filename))
                    continue
                nlen, xlen = struct.unpack_from('<HH', h, 26)
                if xlen != len(zi.extra):
                    out.append('%s: "%s" has different extra fields in the local and central headers.' % (base, zi.filename))
                if check_names:
                    leaf = zi.filename.replace('\\', '/').split('/')[-1]
                    if not _NAME.match(leaf) or _LANG_PREFIX.match(leaf):
                        out.append('%s: the entry name "%s" is not allowed (lower-case letters, digits, . _ - only; no language prefix).' % (base, zi.filename))
                    if ' ' in zi.filename or ',' in zi.filename:
                        out.append('%s: the entry name "%s" has a space or comma.' % (base, zi.filename))
    return out


def config_problems(folder):
    p = os.path.join(folder, 'configpc.txt')
    if not os.path.exists(p):
        return []
    with open(p, 'rb') as f:
        b = f.read()
    out = []
    if b and not b.endswith(b'\n'):
        out.append('configpc.txt does not end with a new line: the game would ignore the archive list.')
    if b[:3] == b'\xef\xbb\xbf' or b[:2] in (b'\xff\xfe', b'\xfe\xff'):
        out.append('configpc.txt starts with a byte-order mark: the game would ignore the first line.')
    return out


# ------------------------------------------------------------------------------------------------ name hashes
def zip_crcs(path):
    """{crc: lower-case entry name} of a zip."""
    with zipfile.ZipFile(path) as z:
        return {name_crc(n): engine_name(n).decode('latin-1') for n in z.namelist()}


def crc_conflicts(names, others):
    """names: entry names about to be written. others: [(label, {crc: name})] of every other archive in the chain.
    -> list of texts: a name that hashes like a DIFFERENT name (the same name is a normal override)."""
    out = []
    mine = {}
    for n in names:
        en = engine_name(n).decode('latin-1')
        c = name_crc(n)
        if c in mine and mine[c] != en:
            out.append('"%s" and "%s" have the same name hash.' % (mine[c], en))
        mine[c] = en
    for label, table in others:
        for c, en in mine.items():
            o = table.get(c)
            if o is not None and o != en:
                out.append('"%s" has the same name hash as "%s" in %s.' % (en, o, label))
    return out


def chain_crcs(folder, names, loader=None):
    """[(label, {crc: name})] of the mounted archives (zip or naz). loader(path) -> {crc: name} overrides how an archive is read."""
    out = []
    for n in names:
        p = os.path.join(folder, n)
        if not os.path.isfile(p):
            continue
        try:
            if loader:
                t = loader(p)
            elif n.lower().endswith('.zip'):
                t = zip_crcs(p)
            else:
                continue
        except Exception:                                   # an archive that cannot be read is not checked
            continue
        if t:
            out.append((n, t))
    return out


# ------------------------------------------------------------------------------------------------ the one entry point
def preflight(folder, fs, pack_zip=None, pack_name=None, remove=(), loader=None, others=None):
    """Everything that must hold before a pack goes into the game. Raises ValueError (plain text) on a problem; returns the warnings.
    fs: the current filesystem line; pack_zip: the finished archive (None = removing everything); remove: names that leave the line."""
    warns = []
    slot_check(folder, fs, add=pack_name if pack_zip else None, remove=list(remove) + ([pack_name] if pack_name else []))
    if pack_zip:
        probs = zip_rules(pack_zip)
        if probs:
            raise ValueError(probs[0])
        for lvl, txt in size_check(pack_zip):
            if lvl == 'error':
                raise ValueError(txt)
            warns.append(txt)
        with zipfile.ZipFile(pack_zip) as z:
            names = z.namelist()
        mounted = [a for a in fs if a.lower() not in {r.lower() for r in remove} and a.lower() != (pack_name or '').lower()]
        if others is None:
            others = chain_crcs(folder, slot_users(folder, mounted), loader)
        bad = crc_conflicts(names, others)
        if bad:
            raise ValueError('A block name clashes with another file the game loads: ' + bad[0])
    return warns


# ------------------------------------------------------------------------------------------------ writing
def write_stored_zip(path, entries, mtime_from=None):
    """entries: iterable of (name, bytes) or (name, ZipFile, ZipInfo). Writes STORED, no comment, fixed dates (the same layout as
    the fragment writer). Atomic (.part, then rename). Returns the byte size."""
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        for e in entries:
            name = e[0]
            data = e[1] if len(e) == 2 else e[1].read(e[2])
            zi = zipfile.ZipInfo(name, date_time=(2005, 8, 21, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 0
            zi.external_attr = 0
            zf.writestr(zi, data)
    os.replace(tmp, path)
    if mtime_from and os.path.exists(mtime_from):
        st = os.stat(mtime_from)
        os.utime(path, (st.st_atime, st.st_mtime))
    return os.path.getsize(path)


def merge_zips(out, zips, mtime_from=None):
    """Merge archives: the LATER one in `zips` wins a name (each later stage was built on top of the earlier output).
    -> {name: index of the zip it came from}."""
    owner = {}
    handles = [zipfile.ZipFile(p) for p in zips]
    try:
        for i, z in enumerate(handles):
            for n in z.namelist():
                owner[n] = i
        def gen():
            for n in sorted(owner):
                z = handles[owner[n]]
                yield (n, z, z.getinfo(n))
        write_stored_zip(out, gen(), mtime_from)
    finally:
        for z in handles:
            z.close()
    return owner
