"""Tiny x86-32 interpreter for the engine's property setter/getter stubs (static: runs the exe's own bytes).
Supports the instruction subset these stubs use; known helper calls are modelled in Python (ports of the
exe's own helpers, see the bottom of the file)."""
import struct, math
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_REG, X86_OP_IMM, X86_OP_MEM
import pe
md = Cs(CS_ARCH_X86, CS_MODE_32); md.detail = True


def f32(x):
    try:
        return struct.unpack('<f', struct.pack('<f', x))[0]
    except OverflowError:
        return math.copysign(float('inf'), x)


def u2f(u): return struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]


def f2u(f):
    try:
        return struct.unpack('<I', struct.pack('<f', f))[0]
    except OverflowError:
        return 0x7f800000 if f > 0 else 0xff800000


class Unsupported(Exception):
    pass


OBJ = 0x10000000
STK = 0x20000000
RET = 0xDEAD0000


class Emu:
    R8 = {'al': ('eax', 0), 'ah': ('eax', 8), 'bl': ('ebx', 0), 'bh': ('ebx', 8), 'cl': ('ecx', 0), 'ch': ('ecx', 8),
          'dl': ('edx', 0), 'dh': ('edx', 8)}
    R16 = {'ax': 'eax', 'bx': 'ebx', 'cx': 'ecx', 'dx': 'edx', 'si': 'esi', 'di': 'edi', 'bp': 'ebp', 'sp': 'esp'}

    def __init__(self, objsize=0x400, fill=0):
        self.mem = {}
        for i in range(objsize):
            self.mem[OBJ + i] = fill
        self.r = dict(eax=0, ebx=0, ecx=OBJ, edx=0, esi=0, edi=0, ebp=0, esp=STK)
        self.x = [0.0] * 8
        self.st = []
        self.zf = self.cf = self.sf = self.of = self.pf = 0
        self.writes = set()
        self.calls = []
        self.hooks = {}
        self.trace = []
        self.indirect_args = None   # set to N to treat indirect calls as no-ops that pop N stack args
        self.approx = False
        self.native_calls = True    # run un-hooked direct callees from the exe's bytes

    def rb(self, a):
        a &= 0xffffffff
        if a in self.mem:
            return self.mem[a]
        if 0x400000 <= a < 0xC00000:
            return pe.read(a, 1)[0]
        return 0

    def wb(self, a, v):
        a &= 0xffffffff
        self.mem[a] = v & 0xff
        if OBJ <= a < OBJ + 0x10000:
            self.writes.add(a - OBJ)

    def rd(self, a, n=4):
        return int.from_bytes(bytes(self.rb(a + i) for i in range(n)), 'little')

    def wd(self, a, v, n=4):
        for i in range(n):
            self.wb(a + i, (v >> (8 * i)) & 0xff)

    def greg(self, n):
        if n in self.r:
            return self.r[n]
        if n in self.R8:
            b, s = self.R8[n]
            return (self.r[b] >> s) & 0xff
        if n in self.R16:
            return self.r[self.R16[n]] & 0xffff
        raise Unsupported('reg ' + n)

    def sreg(self, n, v):
        if n in self.r:
            self.r[n] = v & 0xffffffff
            return
        if n in self.R8:
            b, s = self.R8[n]
            self.r[b] = (self.r[b] & ~(0xff << s) | ((v & 0xff) << s)) & 0xffffffff
            return
        if n in self.R16:
            b = self.R16[n]
            self.r[b] = (self.r[b] & 0xffff0000) | (v & 0xffff)
            return
        raise Unsupported('reg ' + n)

    def ea(self, ins, op):
        m = op.mem
        a = m.disp
        if m.base:
            a += self.greg(ins.reg_name(m.base))
        if m.index:
            a += self.greg(ins.reg_name(m.index)) * m.scale
        return a & 0xffffffff

    def rop(self, ins, op):
        if op.type == X86_OP_REG:
            n = ins.reg_name(op.reg)
            if n.startswith('xmm'):
                return f2u(self.x[int(n[3:])])
            return self.greg(n)
        if op.type == X86_OP_IMM:
            return op.imm & ((1 << (8 * op.size)) - 1)
        return self.rd(self.ea(ins, op), op.size)

    def wop(self, ins, op, v):
        if op.type == X86_OP_REG:
            n = ins.reg_name(op.reg)
            if n.startswith('xmm'):
                self.x[int(n[3:])] = u2f(v)
                return
            self.sreg(n, v)
            return
        self.wd(self.ea(ins, op), v, op.size)

    def xr(self, ins, op):
        return int(ins.reg_name(op.reg)[3:])

    def rflt(self, ins, op):
        if op.type == X86_OP_REG:
            return self.x[self.xr(ins, op)]
        return u2f(self.rd(self.ea(ins, op)))

    def rmemf(self, ins, op):
        a = self.ea(ins, op)
        if op.size == 4:
            return u2f(self.rd(a))
        if op.size == 8:
            return struct.unpack('<d', bytes(self.rb(a + i) for i in range(8)))[0]
        raise Unsupported('fp size')

    def push(self, v):
        self.r['esp'] = (self.r['esp'] - 4) & 0xffffffff
        self.wd(self.r['esp'], v)

    def pop(self):
        v = self.rd(self.r['esp'])
        self.r['esp'] = (self.r['esp'] + 4) & 0xffffffff
        return v

    def arg(self, i):  # stack arg i (0-based) at a call: [esp + 4 + 4i] (return address on top)
        return self.rd(self.r['esp'] + 4 + 4 * i)

    def setfl(self, res, size=4):
        m = (1 << (8 * size)) - 1
        res &= m
        self.zf = int(res == 0)
        self.sf = (res >> (8 * size - 1)) & 1
        self.pf = int(bin(res & 0xff).count('1') % 2 == 0)

    def call(self, va):
        self.calls.append(va)
        if va in self.hooks:
            return self.hooks[va](self)
        raise Unsupported('call %x' % va)

    def run(self, va, maxn=600):
        pc = va
        for _ in range(maxn):
            if pc == RET:
                return
            ins = next(md.disasm(pe.read(pc, 16), pc))
            nxt = pc + ins.size
            mn = ins.mnemonic
            ops = ins.operands
            self.trace.append(pc)
            if mn == 'int3':
                raise Unsupported('int3 at %x' % pc)
            if mn in ('mov', 'movd', 'movzx'):
                self.wop(ins, ops[0], self.rop(ins, ops[1]))
            elif mn == 'movsx':
                v = self.rop(ins, ops[1])
                b = 8 * ops[1].size
                if v >> (b - 1):
                    v -= 1 << b
                self.wop(ins, ops[0], v)
            elif mn == 'lea':
                self.wop(ins, ops[0], self.ea(ins, ops[1]))
            elif mn == 'push':
                self.push(self.rop(ins, ops[0]))
            elif mn == 'pop':
                self.wop(ins, ops[0], self.pop())
            elif mn in ('add', 'sub', 'and', 'or', 'xor', 'cmp', 'test', 'adc', 'sbb'):
                a = self.rop(ins, ops[0])
                b = self.rop(ins, ops[1])
                sz = ops[0].size
                m = (1 << (8 * sz)) - 1
                if ops[1].type == X86_OP_IMM and ops[1].size < sz and (b >> (8 * ops[1].size - 1)):
                    b |= m & ~((1 << (8 * ops[1].size)) - 1)
                b &= m
                if mn == 'add':
                    r = a + b; self.cf = int(r > m)
                elif mn == 'adc':
                    r = a + b + self.cf; self.cf = int(r > m)
                elif mn in ('sub', 'cmp'):
                    r = a - b
                    self.cf = int(a < b)
                    sa, sb, sr = a >> (8 * sz - 1), b >> (8 * sz - 1), (r & m) >> (8 * sz - 1)
                    self.of = int(sa != sb and sr != sa)
                elif mn == 'sbb':
                    r = a - b - self.cf; self.cf = int(a < b + self.cf)
                elif mn in ('and', 'test'):
                    r = a & b; self.cf = self.of = 0
                elif mn == 'or':
                    r = a | b; self.cf = self.of = 0
                else:
                    r = a ^ b; self.cf = self.of = 0
                self.setfl(r, sz)
                if mn not in ('cmp', 'test'):
                    self.wop(ins, ops[0], r & m)
            elif mn in ('inc', 'dec', 'neg', 'not'):
                a = self.rop(ins, ops[0])
                sz = ops[0].size
                m = (1 << (8 * sz)) - 1
                r = {'inc': a + 1, 'dec': a - 1, 'neg': -a, 'not': ~a}[mn] & m
                if mn != 'not':
                    self.setfl(r, sz)
                self.wop(ins, ops[0], r)
            elif mn in ('shl', 'shr', 'sar'):
                a = self.rop(ins, ops[0])
                c = (self.rop(ins, ops[1]) if len(ops) > 1 else 1) & 31
                sz = ops[0].size
                m = (1 << (8 * sz)) - 1
                if mn == 'shl':
                    r = (a << c) & m
                elif mn == 'shr':
                    r = a >> c
                else:
                    s = a - (1 << 8 * sz) if a >> (8 * sz - 1) else a
                    r = (s >> c) & m
                if c:
                    self.setfl(r, sz)
                self.wop(ins, ops[0], r)
            elif mn == 'imul' and len(ops) == 3:
                a = self.rop(ins, ops[1])
                if a >> 31:
                    a -= 1 << 32
                self.wop(ins, ops[0], (a * ops[2].imm) & 0xffffffff)
            elif mn == 'movss':
                if ops[0].type == X86_OP_REG:
                    self.x[self.xr(ins, ops[0])] = self.rflt(ins, ops[1])
                else:
                    self.wd(self.ea(ins, ops[0]), f2u(self.x[self.xr(ins, ops[1])]))
            elif mn in ('movaps', 'movups'):
                self.x[self.xr(ins, ops[0])] = self.rflt(ins, ops[1])
            elif mn in ('xorps', 'pxor'):
                if ops[0].reg == ops[1].reg:
                    self.x[self.xr(ins, ops[0])] = 0.0
                else:
                    raise Unsupported('xorps')
            elif mn in ('mulss', 'addss', 'subss', 'divss', 'minss', 'maxss'):
                d = self.xr(ins, ops[0])
                a = self.x[d]
                b = self.rflt(ins, ops[1])
                if mn == 'divss':
                    r = a / b if b else math.copysign(float('inf'), a)
                else:
                    r = {'mulss': a * b, 'addss': a + b, 'subss': a - b, 'minss': min(a, b), 'maxss': max(a, b)}[mn]
                self.x[d] = f32(r)
            elif mn in ('comiss', 'ucomiss'):
                a = self.rflt(ins, ops[0])
                b = self.rflt(ins, ops[1])
                if a != a or b != b:
                    self.zf = self.pf = self.cf = 1
                else:
                    self.zf = int(a == b); self.cf = int(a < b); self.pf = 0
            elif mn == 'cvttss2si':
                self.wop(ins, ops[0], int(self.rflt(ins, ops[1])) & 0xffffffff)
            elif mn == 'cvtss2si':
                self.wop(ins, ops[0], int(round(self.rflt(ins, ops[1]))) & 0xffffffff)
            elif mn == 'cvtsi2ss':
                v = self.rop(ins, ops[1])
                if v >> 31:
                    v -= 1 << 32
                self.x[self.xr(ins, ops[0])] = f32(float(v))
            elif mn == 'fld':
                if ops[0].type == X86_OP_MEM:
                    self.st.insert(0, self.rmemf(ins, ops[0]))
                else:
                    self.st.insert(0, self.st[int(ins.reg_name(ops[0].reg)[3:-1]) if '(' in ins.reg_name(ops[0].reg) else 0])
            elif mn == 'fild':
                v = self.rd(self.ea(ins, ops[0]), ops[0].size)
                b = 8 * ops[0].size
                if v >> (b - 1):
                    v -= 1 << b
                self.st.insert(0, float(v))
            elif mn in ('fadd', 'fmul', 'fsub', 'fdiv', 'fsubr', 'fdivr') and len(ops) == 1 and ops[0].type == X86_OP_MEM:
                b = self.rmemf(ins, ops[0])
                a = self.st[0]
                if mn == 'fdiv' and b == 0: self.st[0] = math.copysign(float('inf'), a)
                elif mn == 'fdivr' and a == 0: self.st[0] = math.copysign(float('inf'), b)
                else: self.st[0] = {'fadd': a + b, 'fmul': a * b, 'fsub': a - b, 'fdiv': a / b if b else 0, 'fsubr': b - a, 'fdivr': b / a if a else 0}[mn]
            elif mn in ('fstp', 'fst') and ops[0].type == X86_OP_MEM:
                v = self.st[0]
                if ops[0].size == 4:
                    self.wd(self.ea(ins, ops[0]), f2u(v))
                else:
                    self.wd(self.ea(ins, ops[0]), struct.unpack('<Q', struct.pack('<d', v))[0], 8)
                if mn == 'fstp':
                    self.st.pop(0)
            elif mn == 'fstp':   # fstp st(0) etc.
                self.st.pop(0)
            elif mn.startswith('j'):
                t = ops[0].imm if ops[0].type == X86_OP_IMM else None
                c = {'jmp': True, 'je': self.zf, 'jne': not self.zf, 'jbe': self.cf or self.zf, 'ja': not (self.cf or self.zf),
                     'jb': self.cf, 'jae': not self.cf, 'jp': self.pf, 'jnp': not self.pf, 'js': self.sf, 'jns': not self.sf,
                     'jl': self.sf != self.of, 'jge': self.sf == self.of, 'jle': self.zf or self.sf != self.of,
                     'jg': (not self.zf) and self.sf == self.of}.get(mn)
                if c is None:
                    raise Unsupported(mn)
                if c:
                    if t is None:
                        raise Unsupported('indirect jmp at %x' % pc)
                    if t in self.hooks:   # tail call: behaves like call + ret of the stub
                        rv = self.call(t)
                        if rv is not None:
                            self.r['eax'] = rv & 0xffffffff
                        ra = self.pop()
                        self.r['esp'] = (self.r['esp'] + getattr(self, 'tail_pop', 0)) & 0xffffffff
                        if ra == RET:
                            return
                        pc = ra
                        continue
                    nxt = t
            elif mn == 'call':
                if ops[0].type != X86_OP_IMM:
                    if self.indirect_args is None:
                        raise Unsupported('indirect call at %x' % pc)
                    self.calls.append(('indirect', pc))
                    self.r['esp'] = (self.r['esp'] + 4 * self.indirect_args) & 0xffffffff
                    self.approx = True
                    pc = nxt
                    continue
                self.push(nxt)
                if ops[0].imm not in self.hooks and self.native_calls:
                    self.calls.append(ops[0].imm)
                    pc = ops[0].imm
                    continue
                rv = self.call(ops[0].imm)
                ra = self.pop()
                if rv is not None:
                    self.r['eax'] = rv & 0xffffffff
                nxt = ra
            elif mn == 'ret':
                ra = self.pop()
                if ops:
                    self.r['esp'] = (self.r['esp'] + ops[0].imm) & 0xffffffff
                if ra == RET:
                    return
                nxt = ra
            elif mn == 'nop':
                pass
            elif mn == 'fabs':
                self.st[0] = abs(self.st[0])
            elif mn == 'fchs':
                self.st[0] = -self.st[0]
            elif mn == 'fldz':
                self.st.insert(0, 0.0)
            elif mn == 'fld1':
                self.st.insert(0, 1.0)
            elif mn == 'lahf':
                ah = (self.sf << 7) | (self.zf << 6) | (self.pf << 2) | 2 | self.cf
                self.sreg('ah', ah)
            elif mn in ('fadd', 'fmul', 'fsub', 'fdiv', 'faddp', 'fmulp', 'fsubp', 'fdivp', 'fsubr', 'fdivr', 'fsubrp', 'fdivrp') and all(o.type == X86_OP_REG for o in ops):
                idx = [int(ins.reg_name(o.reg)[3:-1]) if '(' in ins.reg_name(o.reg) else 0 for o in ops]
                if len(idx) == 1:
                    idx = [1, 0] if mn.endswith('p') else [0, idx[0]]
                d, sidx = idx
                a, b = self.st[d], self.st[sidx]
                base = mn.rstrip('p') if mn not in ('fsubrp', 'fdivrp') else mn[:-1]
                if base == 'fadd': r = a + b
                elif base == 'fmul': r = a * b
                elif base == 'fsub': r = a - b
                elif base == 'fsubr': r = b - a
                elif base == 'fdiv': r = a / b if b else math.copysign(float('inf'), a)
                else: r = b / a if a else math.copysign(float('inf'), b)
                self.st[d] = r
                if mn.endswith('p'):
                    self.st.pop(0)
            elif mn == 'fxch':
                i = int(ins.reg_name(ops[0].reg)[3:-1]) if ops and '(' in ins.reg_name(ops[0].reg) else 1
                self.st[0], self.st[i] = self.st[i], self.st[0]
            elif mn == 'setne':
                self.wop(ins, ops[0], int(not self.zf))
            elif mn == 'sete':
                self.wop(ins, ops[0], int(self.zf))
            elif mn == 'cdq':
                self.r['edx'] = 0xffffffff if self.r['eax'] >> 31 else 0
            else:
                raise Unsupported('%s %s at %x' % (mn, ins.op_str, pc))
            pc = nxt
        raise Unsupported('too long')


# ---- ports of the exe's helpers ----
def ftol(x):  # 0x951640: C truncation toward zero
    if x != x or math.isinf(x) or abs(x) >= 2 ** 31:
        return 0x80000000
    return int(x) & 0xffffffff


def enc12(v):  # 0x424D10 (float arg): round, keep 8 significant bits, 4-bit exponent
    esi = ftol(v + 0.5)
    if esi >> 31:
        esi -= 1 << 32
    e = 0
    a = esi
    while a >= 0x2000:
        a >>= 1
        e += 1
    r = (((1 << (e + 3)) + esi) & 0xffffffff) >> e
    if r >= 0x1000:
        e += 1
    return (r & 0xff0) | e


def dec12(p, scale):  # 0x424D60
    e = p & 0xf
    m = (0x1000 if e else 0) | (p & 0xff0)
    return scale * 7.465161e-09 * (m << (e - 1) if e else m)


def enc8(v):  # 0x424C60 (st0): 5 significant bits, 3-bit exponent
    i = ftol(v)
    if i >> 31:
        i -= 1 << 32
    e = 0
    a = i
    while a > 0x1ff:
        a >>= 1
        e += 1
    r = (((1 << (e + 2)) + i) & 0xffffffff) >> e
    if r > 0xff:
        e += 1
    return (r & 0xf8) | e


def dec8(p, scale):  # 0x424CB0
    e = p & 7
    m = (0x100 if e else 0) | (p & 0xf8)
    return scale * 3.1001986e-05 * (m << (e - 1) if e else m)


def dec12s(p, scale):  # 0x424C10
    e = p & 0xf
    m = (0x1000 if e else 0) | (p & 0xfe0)
    v = m << (e - 1) if e else m
    if p & 0x10:
        v = -v
    return scale * 7.479799e-09 * v
