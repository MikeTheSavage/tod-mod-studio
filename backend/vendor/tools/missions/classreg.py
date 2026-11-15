"""Extract every script class registration (Scriptbaked, FUN_0048a530) from the GOG decompile.

For each class: name, registering function, main handler (+0x60), members in registration order
(FUN_0048af10(prop_id, default, 0)) with name/type from the proven property table, their byte offset in
the script data block (header = ceil(2n/32) words, then each member by its type size in words, FUN_0048aa60),
and the methods (FUN_0048a690(cmd_id, thread_handler, method)) with the command names.

  python classreg.py [-o classes.json] [--txt classes.txt] [--only NAME ...]
"""
import argparse, json, os, re, struct, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.environ.get('TOD_REF', os.path.join(HERE, '..', 'ref'))
os.environ.setdefault('TOD_EXE', os.path.join(REF, 'TOD_gog.exe'))
sys.path.insert(0, HERE)
import pe

PT = json.load(open(os.path.join(os.environ.get('TOD_TABLES_DIR') or HERE, 'property_table.json')))['properties']
CT = json.load(open(os.path.join(os.environ.get('TOD_TABLES_DIR') or HERE, 'command_table.json')))['commands']

# member size in 32-bit words, by type (FUN_0048aa60 adds *(type+0x18)); lists/dicts checked against accesses
WORDS = {'integer': 1, 'number': 1, 'truth': 1, 'color': 1, 'Entity': 1, 'string': 1, 'vector': 3,
         'quaternion': 4}


def tsize(t):
    if t in WORDS:
        return WORDS[t]
    if t.lower().startswith('list(') or t.lower().startswith('dict('):
        return 1            # one word (list object pointer): proven by Trigger_Root predicate 0x7FD190 (+0x20 NumConditions, +0x30 TriggerOn, +0x34 ConditionsNeeded, +0x54 ConditionsMet)
    return None


def funcs(path):
    """yield (addr, name, text) for each function in decomp.c"""
    cur, buf, addr = None, [], None
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('//==== FUNC '):
                if cur is not None:
                    yield addr, cur, ''.join(buf)
                m = re.match(r'//==== FUNC (\S+) @ ([0-9A-F]{8})', line)
                cur, addr, buf = m.group(1), int(m.group(2), 16), []
            elif cur is not None:
                buf.append(line)
    if cur is not None:
        yield addr, cur, ''.join(buf)


def default_text(tok):
    tok = tok.strip()
    if tok == '0':
        return None
    if tok.startswith('"'):
        return tok.strip('"')
    m = re.match(r'&?(?:DAT|s_\w*?)_([0-9a-fA-F]{8})', tok)
    if m:
        try:
            return pe.cstr(int(m.group(1), 16), 128)
        except Exception:
            return tok
    return tok


def parse(text):
    out = []
    for m in re.finditer(r'FUN_0048a530\("([^"]+)",([^,]+),(\d+),(\d+)\)', text):
        out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', default=os.path.join(HERE, 'data', 'classes.json'))
    ap.add_argument('--txt', default=os.path.join(HERE, 'data', 'classes.txt'))
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args()
    classes = []
    for addr, fname, text in funcs(os.path.join(REF, 'decomp.c')):
        ms = parse(text)
        if not ms:
            continue
        if fname == 'FUN_0048a530':
            continue
        name = ms[0].group(1)
        if a.only and name not in a.only:
            continue
        handler = re.search(r'\*\(code \*\*\)\(iVar\d+ \+ 0x60\) = (\w+);', text)
        members = []
        for mm in re.finditer(r'FUN_0048af10\((0x[0-9a-f]+|\d+),([^,]*(?:"[^"]*")?[^,]*),(\d+)\);', text):
            pid = int(mm.group(1), 0)
            pn, pt = PT[pid] if pid < len(PT) else ('#%d' % pid, '?')
            members.append(dict(id=pid, name=pn, type=pt, default=default_text(mm.group(2))))
        n = len(members)
        off = 4 * ((2 * n + 31) // 32)
        approx = False
        for mb in members:
            mb['off'] = off
            s = tsize(mb['type'])
            if s is None:
                s = 1; approx = True
            off += 4 * s
        methods = []
        for mm in re.finditer(r'FUN_0048a690\((0x[0-9a-f]+|\d+),&?(\w+),&?(\w+)\);', text):
            cid = int(mm.group(1), 0)
            methods.append(dict(id=cid, command=CT[cid] if cid < len(CT) else '#%d' % cid,
                                thread=mm.group(2), method=mm.group(3)))
        classes.append(dict(name=name, reg=fname, reg_addr='%08X' % addr,
                            handler=handler.group(1) if handler else None,
                            members=members, data_size=off, layout_approx=approx, methods=methods))
    json.dump(classes, open(a.o, 'w'), indent=1)
    with open(a.txt, 'w', encoding='utf-8') as f:
        for c in classes:
            f.write('== %s  reg %s  handler %s  data %d B%s\n' % (c['name'], c['reg'], c['handler'], c['data_size'],
                                                                  ' (approx)' if c['layout_approx'] else ''))
            for mb in c['members']:
                f.write('   +%03X %4d %-32s %-14s %s\n' % (mb['off'], mb['id'], mb['name'], mb['type'],
                                                          '' if mb['default'] is None else repr(mb['default'])))
            for me in c['methods']:
                f.write('   cmd %4d %-50s %s / %s\n' % (me['id'], me['command'], me['thread'], me['method']))
    print('classes', len(classes), '->', a.o, a.txt)


if __name__ == '__main__':
    main()
