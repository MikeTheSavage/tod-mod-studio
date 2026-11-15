"""Slot11 (settings file) <-> JSON.

Written by Entity::SaveScriptDataToFile (FUN_0086B650 -> FUN_0086B110) for the database_settings_dict node:
  u32 count (= number of script members, 67)
  count x ( u32 size_in_dwords , value[size] )   values in the CopyNoAllocate layout of each member's type
  u32 CRC  = Kapow CRC over all preceding bytes (SavePoint::GenerateAndWriteCRC FUN_00874310)
Member names/types come from the exe's Scriptbaked table for 'database_settings_dict'.
"""
import struct, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kcrc, ktypes, kmodel

SCRIPT = 'database_settings_dict'


def members():
    out = []
    for m in kmodel.SCRIPTS[SCRIPT]['members']:
        n, t = kmodel.GPROPS[m['id']].rsplit(':', 1)
        out.append((n, t))
    return out


def decode(b):
    n = len(b) // 4
    w = struct.unpack('<%dI' % n, b[:n * 4])
    crc_ok = kcrc.crc(b[:-4]) == w[-1]
    cnt = w[0]
    mem = members()
    if cnt != len(mem):
        raise ValueError('member count %d != %d' % (cnt, len(mem)))
    i, vals = 1, []
    for name, t in mem:
        size = w[i]
        v, end = ktypes.read(w, i + 1, ktypes.parse_type(t))
        if end != i + 1 + size:
            raise ValueError('size mismatch for %s' % name)
        vals.append({'name': name, 't': t, 'v': v})
        i = end
    if i != n - 1:
        raise ValueError('trailing data')
    return {'format': 'tod-settings/1', 'crc_ok': crc_ok, 'values': vals}


def encode(j):
    words = [len(j['values'])]
    for e in j['values']:
        v = ktypes.write(ktypes.parse_type(e['t']), e['v'])
        words += [len(v)] + v
    b = struct.pack('<%dI' % len(words), *words)
    return b + struct.pack('<I', kcrc.crc(b))
