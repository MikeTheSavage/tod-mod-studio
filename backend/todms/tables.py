"""Property and command tables for the user's own game.

The tools decode fragments with the global property list: 711 builtin properties (registered by TOD.exe code; the
list ships with the app in data/builtin_tables.json) followed by the 5,283 properties of the game's
data_pc/scripts/stable/database.bin. The database part is read here from the user's blocks.naz, never shipped.
The result is checked the way the engine checks it: the CRC over every "index + name:type" must equal the propCk
in the block headers (and the same for commands / cmdCk).
"""
import json
import os
import struct

from . import paths

_TYPEC = {'entity': 'Entity', 'number': 'number', 'integer': 'integer', 'truth': 'truth', 'vector': 'vector',
          'string': 'string', 'quaternion': 'quaternion', 'color': 'color'}


def _canon_ret(s):
    if ':' in s:
        a, r = s.split(':', 1)
        return a + ':' + _TYPEC.get(r.lower(), r)
    return s


def _parse_db(d):
    p = 0
    secs = []
    for _ in range(2):
        n = struct.unpack_from('<I', d, p)[0]
        p += 4
        lst = []
        for _ in range(n):
            ln = struct.unpack_from('<I', d, p)[0]
            p += 4
            lst.append(d[p:p + ln].rstrip(b'\0').decode('latin-1'))
            p += ln
        secs.append(lst)
    if p != len(d):
        raise ValueError('database.bin: %d trailing bytes' % (len(d) - p))
    return secs


def _crc(strings):
    import todblock as tb
    buf = bytearray()
    for i, s in enumerate(strings):
        buf += struct.pack('<I', i) + s.encode('latin-1')
    return tb.tod_crc(bytes(buf))


def ready():
    d = paths.tables_dir()
    return all(os.path.exists(os.path.join(d, f)) for f in
               ('property_table.json', 'command_table.json', 'global_properties.json'))


def build(archive, header_prop_ck, header_cmd_ck, progress=None):
    """archive: todblock.Archive of the user's blocks.naz. Writes the three tables into paths.tables_dir()."""
    bi = json.load(open(os.path.join(paths.DATA, 'builtin_tables.json')))
    raw = archive.read('data_pc/scripts/stable/database.bin')
    dbp, dbc = _parse_db(raw)
    props = [list(x) for x in bi['builtin_properties']] + [s.split(':', 1) for s in dbp]
    pstr = ['%s:%s' % (n, t) for n, t in props]
    if progress:
        progress('checking the property list against the game (%d properties)' % len(pstr))
    pb = _crc(pstr[:len(bi['builtin_properties'])])
    pl = _crc(pstr)
    cmds = list(bi['builtin_commands']) + [_canon_ret(s) for s in dbc]
    cl = _crc(cmds)
    if '%08X' % pb != bi['crc_builtin_properties']:
        raise ValueError('builtin property table damaged (CRC %08X)' % pb)
    if pl != header_prop_ck or cl != header_cmd_ck:
        raise ValueError('this game\'s database.bin does not match its own block headers (props %08X/%08X, commands '
                         '%08X/%08X): unsupported game version' % (pl, header_prop_ck, cl, header_cmd_ck))
    d = paths.tables_dir()
    src = 'builtin: app (static replay of TOD.exe InitEntitiesDatabase); loaded: this user\'s database.bin'
    json.dump(dict(source=src, builtin=len(bi['builtin_properties']), crc_builtin='%08X' % pb, crc_loaded='%08X' % pl,
                   crc_rule=bi['crc_rule_properties'], properties=props,
                   builtin_register_function=bi['builtin_register_function']),
              open(os.path.join(d, 'property_table.json'), 'w'), indent=0)
    json.dump(dict(source=src, builtin=len(bi['builtin_commands']), crc_builtin='%08X' % _crc(bi['builtin_commands']),
                   crc_loaded='%08X' % cl, crc_rule=bi['crc_rule_commands'], commands=cmds),
              open(os.path.join(d, 'command_table.json'), 'w'), indent=0)
    json.dump(pstr, open(os.path.join(d, 'global_properties.json'), 'w'), indent=0)
    return dict(properties=len(props), commands=len(cmds), propCk='%08X' % pl, cmdCk='%08X' % cl)
