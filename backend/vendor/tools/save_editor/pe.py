"""Minimal PE reader for the GOG TOD.exe (read-only): VA -> file offset, read bytes/strings."""
import struct
EXE = r'C:/GOG Games/Total Overdose/TOD.exe'

class PE:
    def __init__(self, path=EXE):
        self.d = open(path, 'rb').read()
        d = self.d
        pe = struct.unpack_from('<I', d, 0x3C)[0]
        nsec = struct.unpack_from('<H', d, pe + 6)[0]
        opt = struct.unpack_from('<H', d, pe + 20)[0]
        self.base = struct.unpack_from('<I', d, pe + 24 + 28)[0]
        self.secs = []
        so = pe + 24 + opt
        for i in range(nsec):
            name = d[so:so + 8].rstrip(b'\0').decode('latin-1')
            vsize, va, rsize, raw = struct.unpack_from('<IIII', d, so + 8)
            self.secs.append((name, self.base + va, vsize, raw, rsize))
            so += 40

    def off(self, va):
        for name, sva, vsize, raw, rsize in self.secs:
            if sva <= va < sva + max(vsize, rsize):
                o = va - sva
                return raw + o if o < rsize else None
        return None

    def read(self, va, n):
        o = self.off(va)
        return None if o is None else self.d[o:o + n]

    def u32(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def cstr(self, va, maxlen=256):
        b = self.read(va, maxlen)
        if b is None:
            return None
        return b.split(b'\0')[0].decode('latin-1')
