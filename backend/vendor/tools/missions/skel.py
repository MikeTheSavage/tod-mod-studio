"""Skeleton view of decompiled script functions: every line that sends a command, reads/writes a property by id,
switches script state, or calls another function, with command / property names resolved.

  python skel.py 790A20 788740 ...      (addresses; bodies from fn2.py)
  python skel.py --class master_mission_ctrl   (all methods of a class, from out/classes.json)

Resolves: FUN_0086a340(cmd,..) send command; FUN_00869e60(-k,..) receiver-local command (index k-2 into the
receiver's method table sorted by command id); FUN_0086a6a0/FUN_0086a6c0/FUN_0086bb80(prop,..) get/set property;
FUN_0048ce10/FUN_0048cdf0(thread, state, ...) state switch; data-block offsets +0x.. of the class when --class.
"""
import json, os, re, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fn2

PT = json.load(open(os.path.join(os.environ.get('TOD_TABLES_DIR') or HERE, 'property_table.json')))['properties']
CT = json.load(open(os.path.join(os.environ.get('TOD_TABLES_DIR') or HERE, 'command_table.json')))['commands']
CLS = None


def classes():
    global CLS
    if CLS is None:
        CLS = json.load(open(os.path.join(HERE, 'data', 'classes.json') if os.path.exists(os.path.join(HERE, 'data', 'classes.json')) else os.path.join(HERE, '..', 'out', 'classes.json')))
    return CLS


def num(s):
    s = s.strip()
    try:
        v = int(s, 0)
    except ValueError:
        return None
    if v >= 0x80000000:
        v -= 1 << 32
    return v


def annotate(line, offs=None):
    notes = []
    for m in re.finditer(r'FUN_0086a340\(([^,()]+)', line):
        v = num(m.group(1))
        if v is not None and 0 <= v < len(CT):
            notes.append('SEND %s' % CT[v])
    for m in re.finditer(r'FUN_00869e60\(([^,()]+)', line):
        v = num(m.group(1))
        if v is not None:
            notes.append('SEND-LOCAL %d (method #%d of receiver)' % (v, -v - 2) if v < 0 else 'SEND-LOCAL %d' % v)
    for fn, what in (('FUN_0086a6a0', 'GET'), ('FUN_0086a6c0', 'SET'), ('FUN_0086bb80', 'GETL'),
                     ('FUN_00869e80', 'GETM'), ('FUN_00869ea0', 'SETM')):
        for m in re.finditer(fn + r'\(([^,()]+)', line):
            v = num(m.group(1))
            if v is not None and fn in ('FUN_0086a6a0', 'FUN_0086a6c0', 'FUN_0086bb80') and 0 <= v < len(PT):
                notes.append('%s %s' % (what, PT[v][0]))
            elif v is not None:
                notes.append('%s member#%d' % (what, v))
    for m in re.finditer(r'FUN_0048c[ed][f1]0\((\w+),(\w+)', line):
        notes.append('STATE -> %s/%s' % (m.group(1), m.group(2)))
    if offs:
        for m in re.finditer(r'\(iVar\d+ \+ (0x[0-9a-f]+)\)', line):
            o = int(m.group(1), 16)
            if o in offs:
                notes.append('+%X=%s' % (o, offs[o]))
    return notes


def skeleton(addr, offs=None, out=print):
    idx = fn2.load()
    text, exact = fn2.body(idx, addr)
    if not text:
        out('// none %08X' % addr)
        return
    out(text.splitlines()[0] if exact else '// containing function for %08X' % addr)
    for ln in text.splitlines()[1:]:
        s = ln.strip()
        if not s:
            continue
        n = annotate(s, offs)
        key = re.search(r'(switch|case |FUN_|if \(|while|goto|return|LAB_)', s)
        if n or (key and ('FUN_' in s or s.startswith(('case', 'switch')))):
            out('   %-90s %s' % (s[:90], ('// ' + '; '.join(n)) if n else ''))


def main():
    a = sys.argv[1:]
    if a and a[0] == '--class':
        for c in classes():
            if c['name'] == a[1]:
                offs = {m['off']: m['name'] for m in c['members']}
                seen = set()
                print('#### class', c['name'], 'handler', c['handler'])
                for me in [{'command': 'handler', 'thread': c['handler'], 'method': c['handler']}] + c['methods']:
                    for k in ('thread', 'method'):
                        v = me[k]
                        if not v:
                            continue
                        mm = re.search(r'([0-9a-fA-F]{6,8})$', v)
                        if not mm:
                            continue
                        ad = int(mm.group(1), 16)
                        if ad in seen:
                            continue
                        seen.add(ad)
                        print('\n### %s (%s)' % (me['command'], k))
                        skeleton(ad, offs)
        return
    for x in a:
        skeleton(int(x, 16))
        print()


if __name__ == '__main__':
    main()
