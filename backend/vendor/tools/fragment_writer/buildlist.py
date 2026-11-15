import json, struct, sys, os
sys.dont_write_bytecode = True
from todblock import tod_crc
from dbck import parse_db
HERE = os.path.dirname(os.path.abspath(__file__))
CANON = {'list(entity)': 'list(Entity)'}
def build(calls, canon=CANON):
    plist, pmap, rejected = [], {}, []
    clist, cmap = [], {}
    for kind, s, t, site, ex in calls:
        if kind in ('P', 'PR'):
            if kind == 'PR':
                name, t = s.split(':', 1)
            else:
                name = s
            t = canon.get(t, t)
            key = name.lower()
            if key in pmap:
                idx = pmap[key]
                if plist[idx][1].lower() == t.lower():
                    continue
                rejected.append((name, t, site, plist[idx]))
                continue
            pmap[key] = len(plist); plist.append((name, t, site))
        else:
            key = s.split(':')[0].lower()            # FUN_00872590 keys commands by the text before ':'
            if key in cmap:
                continue
            cmap[key] = len(clist); clist.append((s, site))
    return plist, rejected, clist
def ck(strings):
    buf = bytearray()
    for i, s in enumerate(strings):
        buf += struct.pack('<I', i) + s.encode('latin-1')
    return tod_crc(bytes(buf))
if __name__ == '__main__':
    calls = json.load(open(os.path.join(HERE, 'regcalls.json')))
    plist, rej, clist = build(calls)
    print('builtin props', len(plist), 'rejected', len(rej), 'cmds', len(clist))
    for r in rej[:20]: print('  rej', r)
    strs = ['%s:%s' % (n, t) for n, t, _ in plist]
    print('builtin CRC %08X (want E99606BA)' % ck(strs))
    dbp, dbc = parse_db()
    print('loaded CRC %08X (want 65C37710)' % ck(strs + dbp))
