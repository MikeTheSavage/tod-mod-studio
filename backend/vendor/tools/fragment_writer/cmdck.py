"""Command-list checksum (FUN_00871DD0): builtin commands from the registration replay (key = text before ':',
lowercased; FUN_00872590 reuses an existing key) + database.bin commands, return type canonicalised (entity -> Entity)."""
import json, struct, sys, os, re
sys.dont_write_bytecode = True
from buildlist import ck
from dbck import parse_db
HERE = os.path.dirname(os.path.abspath(__file__))
calls = json.load(open(os.path.join(HERE, 'regcalls.json')))
dbp, dbc = parse_db()
def cmdlist(calls):
    cl, seen = [], set()
    for kind, s, t, site, ex in calls:
        if kind[0] != 'C': continue
        key = s.split(':')[0].lower()
        if key in seen: continue
        seen.add(key); cl.append(s)
    return cl
cl = cmdlist(calls)
TYPEC = {'entity': 'Entity', 'number': 'number', 'integer': 'integer', 'truth': 'truth', 'vector': 'vector',
         'string': 'string', 'quaternion': 'quaternion', 'color': 'color'}
def canon_ret(s):
    if ':' in s:
        a, r = s.split(':', 1)
        return a + ':' + TYPEC.get(r.lower(), r)
    return s
if __name__ == '__main__':
    print('builtin cmds', len(cl))
    for name, f in [('raw', lambda s: s), ('canon_ret', canon_ret)]:
        L = [f(s) for s in cl]
        D = [f(s) for s in dbc]
        print(name, 'builtin %08X' % ck(L), 'loaded %08X (want E5AE7722)' % ck(L + D))
