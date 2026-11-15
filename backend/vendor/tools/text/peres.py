"""Minimal PE resource reader for TOD.exe (read only): RT_STRING tables."""
import struct, os
EXE = os.environ.get('TOD_EXE', r'C:\GOG Games\Total Overdose\TOD.exe')
def load(exe=EXE):
    d = open(exe, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    opt = struct.unpack_from('<H', d, pe + 20)[0]
    ddir = pe + 24 + 96   # PE32 data directories
    rsrc_rva, rsrc_size = struct.unpack_from('<II', d, ddir + 8 * 2)
    secs = []
    for i in range(nsec):
        o = pe + 24 + opt + 40 * i
        vsize, va, rsize, roff = struct.unpack_from('<IIII', d, o + 8)
        secs.append((va, max(vsize, rsize), roff))
    def off(rva):
        for va, sz, ro in secs:
            if va <= rva < va + sz: return ro + rva - va
        raise ValueError(hex(rva))
    base = off(rsrc_rva)
    def entries(dir_off):
        n1, n2 = struct.unpack_from('<HH', d, dir_off + 12)
        out = []
        for k in range(n1 + n2):
            name, data = struct.unpack_from('<II', d, dir_off + 16 + 8 * k)
            out.append((name, data))
        return out
    res = {}
    for tname, tdata in entries(base):
        if tname != 6 or not (tdata & 0x80000000): continue   # RT_STRING
        for bname, bdata in entries(base + (tdata & 0x7FFFFFFF)):
            for lname, ldata in entries(base + (bdata & 0x7FFFFFFF)):
                rva, size = struct.unpack_from('<II', d, base + ldata)
                p = off(rva); end = p + size
                for i in range(16):
                    if p >= end: break
                    n = struct.unpack_from('<H', d, p)[0]; p += 2
                    s = d[p:p + 2 * n].decode('utf-16-le'); p += 2 * n
                    if n: res[((bname - 1) * 16 + i, lname)] = s
    return res
if __name__ == '__main__':
    import sys, json
    r = load()
    print(len(r), 'strings')
    ids = sorted(set(k[0] for k in r)); langs = sorted(set(k[1] for k in r))
    print('ids', ids[:80], 'langs', langs)
