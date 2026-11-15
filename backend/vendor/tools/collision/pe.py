import os, struct, sys
class PE:
    def __init__(self, path):
        self.d=open(path,'rb').read(); d=self.d
        e=struct.unpack_from('<I',d,0x3c)[0]
        nsec=struct.unpack_from('<H',d,e+6)[0]; opt=struct.unpack_from('<H',d,e+20)[0]
        self.base=struct.unpack_from('<I',d,e+24+28)[0]
        self.secs=[]
        s=e+24+opt
        for i in range(nsec):
            name=d[s:s+8].rstrip(b'\0'); vs,va,rs,ra=struct.unpack_from('<IIII',d,s+8)
            self.secs.append((name,va,vs,ra,rs)); s+=40
    def read(self, va, n):
        rva=va-self.base
        for name,sva,vs,ra,rs in self.secs:
            if sva<=rva<sva+max(vs,rs):
                o=ra+rva-sva; return self.d[o:o+n]
        raise KeyError(hex(va))
    def f(self, va, n=1): return struct.unpack('<%df'%n, self.read(va,4*n))
    def u(self, va, n=1): return struct.unpack('<%dI'%n, self.read(va,4*n))
if __name__=='__main__':
    p=PE(os.environ.get('TOD_EXE', r'C:\GOG Games\Total Overdose\TOD.exe'))
    for a in sys.argv[1:]:
        va=int(a,16); print(a, p.f(va,4), [hex(x) for x in p.u(va,4)])
