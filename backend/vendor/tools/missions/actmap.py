"""Map ActionType / Do_What values to what a Trigger_Activate_* class does, from the GOG decompile.

Every Trigger_Activate_* class follows one pattern: command_activate -> (Delay > 0: delayed message 0x13) ->
command_delayed_message -> worker -> action body (switch on ActionType) -> common_trigger helper FUN_00631E90
(sound + APBonus) -> Activated = !Reactivate. This finds the body (first callee of the worker) and prints its
comparisons on the action variable with the commands sent / helpers called in each branch.

  python actmap.py Trigger_Activate_Player [more classes]   (heuristic: read the body to confirm)
"""
import json, os, re, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fn2, skel

CLS = {c['name']: c for c in json.load(open(os.path.join(HERE, 'data', 'classes.json') if os.path.exists(os.path.join(HERE, 'data', 'classes.json')) else os.path.join(HERE, '..', 'out', 'classes.json')))}


def addr(s):
    m = re.search(r'([0-9a-fA-F]{6,8})$', s or '')
    return int(m.group(1), 16) if m else None


def callees(text):
    body = text.split('{', 1)[1] if '{' in text else text
    out = []
    for m in re.finditer(r'FUN_0048c[ed][f1]0\(\w+,(?:FUN|LAB)_00([0-9a-f]{6})|FUN_00([0-9a-f]{6})\(', body):
        x = m.group(1) or m.group(2)
        out.append(int(x, 16))
    return out


def body_of(cname):
    c = CLS[cname]
    idx = fn2.load()
    dm = [m for m in c['methods'] if m['command'].startswith('command_delayed_message')]
    if not dm:
        return None, []
    t, _ = fn2.body(idx, addr(dm[0]['method']))
    chain = []
    for w in callees(t):
        if w in (0x88C8D0, 0x48CD50, 0x48CE10, 0x48CDF0, 0x869E60, 0x86A6A0, 0x86B4B0, 0x631E90):
            continue
        chain.append(w)
        wt, _ = fn2.body(idx, w)
        for b in callees(wt):
            if b in (0x88C8D0, 0x48CD50, 0x631E90, 0x86A6A0, 0x86B4B0, 0x48CE10, 0x48CDF0, 0x48E6A0, 0x48E8F0, 0x48E470, 0x48CD00, 0x869E60, 0x48F2E0, 0x48E700, 0x86A6C0, 0x87AE70, 0x87AE10):
                continue
            chain.append(b)
            return b, chain
    return None, chain


def branches(fa):
    idx = fn2.load()
    t, _ = fn2.body(idx, fa)
    out = []
    for ln in t.splitlines():
        s = ln.strip()
        m = re.findall(r'(\w+) == (0x[0-9a-f]+|\d+)', s)
        cases = re.match(r'case (0x[0-9a-f]+|\d+):', s)
        n = skel.annotate(s)
        calls = [c for c in re.findall(r'(FUN_00[0-9a-f]{6})\(', s)
                 if c not in ('FUN_0086a340', 'FUN_00869e60', 'FUN_0086a6a0', 'FUN_0086a6c0', 'FUN_0086b4b0',
                              'FUN_0086bb80', 'FUN_00869e80', 'FUN_00869ea0', 'FUN_0048e8f0')]
        if m or cases or n or calls:
            out.append('   %-80s %s' % (s[:80], '; '.join(n + calls)))
    return t, out


if __name__ == '__main__':
    for cn in sys.argv[1:]:
        b, chain = body_of(cn)
        print('#### %s  chain %s  body %s' % (cn, ' -> '.join('%06X' % x for x in chain), '%06X' % b if b else None))
        if b:
            _, lines = branches(b)
            print('\n'.join(lines))
        print()
