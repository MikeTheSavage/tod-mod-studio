import os, struct, sys
sys.dont_write_bytecode = True
from todblock import tod_crc
def parse_db(path=None):
    """path None: read data_pc/scripts/stable/database.bin from the GOG blocks.naz (read only)."""
    if path is None or not os.path.exists(path):
        import todblock
        naz = os.environ.get('TOD_NAZ', r'C:\GOG Games\Total Overdose\blocks.naz')
        d = todblock.Archive(naz).read('data_pc/scripts/stable/database.bin')
    else:
        d = open(path, 'rb').read()
    p = 0; secs = []
    for _ in range(2):
        n = struct.unpack_from('<I', d, p)[0]; p += 4; L = []
        for i in range(n):
            ln = struct.unpack_from('<I', d, p)[0]; p += 4
            L.append(d[p:p+ln].rstrip(b'\0').decode('latin-1')); p += ln
        secs.append(L)
    assert p == len(d), (p, len(d))
    return secs
def listck(strings, start=0):
    buf = bytearray()
    for i, s in enumerate(strings):
        buf += struct.pack('<I', start + i) + s.encode('latin-1')
    return tod_crc(bytes(buf))
if __name__ == '__main__':
    props, cmds = parse_db()
    print(len(props), len(cmds), props[:3], cmds[:3])
    print('cmd ck db-only', hex(listck(cmds)))
