"""Static replay of the GOG TOD.exe builtin script registration (InitEntitiesDatabase FUN_0093C950).

Walks the Register functions in call order (decompile text order, recursing into callees that themselves register),
collects property registrations (16 typed wrappers (name,type,...), FUN_0086D370 (type,name,...), FUN_00486D90 (type,
name,...), FUN_008736B0(str,flag)) and command registrations (FUN_0086EC70/FUN_0086EDC0(cmd,...), FUN_00872590(cmd,flag)),
then applies the engine's list semantics (FUN_008736B0: existing name with the same type -> reused, same name other type
-> rejected, else appended) and checks the result against the CRCs (FUN_00873440 / FUN_00871DD0: tod_crc over
u32 index + "name:type").
"""
import re, os, sys, json, struct, bisect, pickle
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
import pe
from todblock import tod_crc

REF = os.environ.get('TOD_REF', os.path.join(HERE, '..', 'ref'))   # decomp.c = Ghidra FullDump of the GOG exe
src = open(os.path.join(REF, 'decomp.c'), 'rb').read().decode('utf-8', 'replace')
funcs = {}
for m in re.finditer(r'^//==== FUNC (\S+) @ ([0-9A-F]{8})', src, re.M):
    funcs[int(m.group(2), 16)] = m.start()
keys = sorted(funcs)
def body(addr):
    i = keys.index(addr)
    s = funcs[addr]; e = funcs[keys[i + 1]] if i + 1 < len(keys) else len(src)
    return src[s:e]

PROP_WRAP = {0x86d6d0, 0x86d730, 0x86d930, 0x86d990, 0x86d9f0, 0x86db90, 0x86dbf0, 0x86ddf0, 0x86de50, 0x86e050,
             0x86e0b0, 0x86e2b0, 0x86e510, 0x86e570, 0x86e770, 0x86e7d0}
PROP_TN = {0x86d370, 0x486d90}
PROP_RAW = {0x8736b0}
CMD_WRAP = {0x86ec70, 0x86edc0, 0x86ed80}
CMD_RAW = {0x872590}
ALLREG = PROP_WRAP | PROP_TN | PROP_RAW | CMD_WRAP | CMD_RAW
TYPES = {'DAT_00a3cec0': 'number', 'DAT_00a3cec4': 'truth', 'DAT_00a3ceb8': 'integer', 'DAT_00a3ceb0': 'string',
         'DAT_00a3ceb4': 'vector', 'DAT_00a3cee0': 'Entity', 'DAT_00a3ce98': 'quaternion', 'DAT_00a3cea4': 'color',
         'DAT_00a3ce94': 'nothing'}

def split_args(s, i):
    """s[i] is just after '('. Return (args list, index after ')')."""
    args, depth, cur, q = [], 0, [], False
    while i < len(s):
        c = s[i]
        if q:
            cur.append(c)
            if c == chr(92): cur.append(s[i + 1]); i += 2; continue
            if c == '"': q = False
        elif c == '"': q = True; cur.append(c)
        elif c == '(': depth += 1; cur.append(c)
        elif c == ')':
            if depth == 0:
                args.append(''.join(cur).strip()); return args, i + 1
            depth -= 1; cur.append(c)
        elif c == ',' and depth == 0: args.append(''.join(cur).strip()); cur = []
        else: cur.append(c)
        i += 1
    raise ValueError('unbalanced')

def strval(a):
    a = a.strip()
    m = re.fullmatch(r'"(.*)"', a, re.S)
    if m:
        return bytes(m.group(1), 'latin-1').decode('unicode_escape')
    m = re.fullmatch(r'&?(?:DAT|s_\w+?)_?([0-9a-fA-F]{8})', a)
    if m:
        return pe.cstr(int(m.group(1), 16))
    m = re.fullmatch(r'\(\w+ \*\)(.*)', a)
    if m: return strval(m.group(1))
    return None

callre = re.compile(r'FUN_([0-9a-f]{8})\(')
_reg_cache = {}
def registers(addr, stack=()):
    """True if addr (transitively) contains a registration call."""
    if addr in ALLREG: return True
    if addr in _reg_cache: return _reg_cache[addr]
    if addr not in funcs or addr in stack: return False
    _reg_cache[addr] = False
    r = any(registers(int(m.group(1), 16), stack + (addr,)) for m in callre.finditer(body(addr)))
    _reg_cache[addr] = r
    return r

def walk(addr, out, stack=(), cls=None):
    b = body(addr)
    local = {}
    for m in callre.finditer(b):
        a = int(m.group(1), 16)
        if a == addr and m.start() < b.find('{'):  # the definition line
            continue
        # skip the definition header occurrence
        line_start = b.rfind('\n', 0, m.start()) + 1
        if b[line_start:m.start()].strip().startswith(('void', 'int', 'undefined', 'uint', 'bool', 'char')) and m.start() < b.find('{'):
            continue
        try:
            args, end = split_args(b, m.end())
        except ValueError:
            continue
        # local type assignment  uVarN = FUN_00863070("list(x)")
        if a == 0x863070:
            pre = b[line_start:m.start()]
            mm = re.match(r'\s*(\w+) = $', pre)
            if mm:
                local[mm.group(1)] = strval(args[0])
            if b[line_start:m.start()].strip().startswith('DAT_'):
                mm = re.match(r'\s*(DAT_\w+) = $', pre)
                if mm: TYPES[mm.group(1)] = strval(args[0])
            continue
        def tname(x):
            x = x.strip()
            if x in TYPES: return TYPES[x]
            if x in local: return local[x]
            return '?' + x
        site = '%08X' % addr
        if a in PROP_WRAP:
            out.append(('P', strval(args[0]), tname(args[1]), site, 1))
        elif a in PROP_TN:
            out.append(('P', strval(args[1]), tname(args[0]), site, 1))
        elif a in PROP_RAW:
            out.append(('PR', strval(args[0]), args[1].strip(), site, 0))
        elif a in CMD_WRAP:
            out.append(('C', strval(args[0]), None, site, 1))
        elif a in CMD_RAW:
            out.append(('CR', strval(args[0]), args[1].strip(), site, 0))
        elif a in funcs and a not in stack and a != addr and registers(a):
            walk(a, out, stack + (addr,))
    return out

def init_order():
    b = body(0x93c950)
    return [int(m.group(1), 16) for m in re.finditer(r'FUN_([0-9a-f]{8})\(', b)][1:]  # skip the def line

if __name__ == '__main__':
    out = []
    walk(0x93c950, out)
    json.dump(out, open(os.path.join(HERE, 'regcalls.json'), 'w'), indent=0)
    print('calls', len(out), 'props', sum(1 for x in out if x[0].startswith('P')), 'cmds', sum(1 for x in out if x[0].startswith('C')))
    unk = [x for x in out if x[1] is None or (x[2] or '').startswith('?')]
    print('unresolved', len(unk), unk[:20])
