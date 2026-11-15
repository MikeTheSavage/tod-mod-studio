"""Minimal PE reader for the GOG TOD.exe copy: va -> bytes."""
import struct, os
EXE = os.environ.get('TOD_EXE', r'C:\GOG Games\Total Overdose\TOD.exe')   # read only
_d = open(EXE, 'rb').read()
_pe = struct.unpack_from('<I', _d, 0x3C)[0]
_nsec = struct.unpack_from('<H', _d, _pe + 6)[0]
_opt = struct.unpack_from('<H', _d, _pe + 20)[0]
BASE = struct.unpack_from('<I', _d, _pe + 24 + 28)[0]
SECS = []
for i in range(_nsec):
    o = _pe + 24 + _opt + 40 * i
    name = _d[o:o+8].rstrip(b'\0').decode()
    vsize, va, rsize, roff = struct.unpack_from('<IIII', _d, o + 8)
    SECS.append((name, BASE + va, vsize, roff, rsize))
def read(va, n):
    for name, sva, vs, ro, rs in SECS:
        if sva <= va < sva + max(vs, rs):
            off = va - sva
            b = _d[ro + off: ro + min(off + n, rs)]
            return b + bytes(n - len(b))
    raise ValueError('va %x not mapped' % va)
def u32(va): return struct.unpack('<I', read(va, 4))[0]
def cstr(va, n=256):
    b = read(va, n); return b.split(b'\0', 1)[0].decode('latin-1')
if __name__ == '__main__':
    import sys
    for s in SECS: print(s[0], hex(s[1]), hex(s[2]))
    for a in sys.argv[1:]: print(a, repr(cstr(int(a, 16))))
