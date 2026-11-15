"""Write the proven global property and command tables (GOG TOD.exe + database.bin) as JSON.

property_table.json: {"builtin": 711, "crc_builtin": ..., "crc_loaded": ..., "properties": [[name, type], ...]}
command_table.json : {"builtin": 290, "crc_builtin": ..., "crc_loaded": ..., "commands": [string, ...]}
The CRCs are computed here exactly as FUN_00873440 / FUN_00871DD0 do and are asserted against the values the
shipped asset blocks carry (propCk 0x65C37710, cmdCk 0xE5AE7722) and the engine's builtin value (0xE99606BA).
"""
import json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
from buildlist import build, ck
from dbck import parse_db
from cmdck import cmdlist, canon_ret
calls = json.load(open(os.path.join(HERE, 'regcalls.json')))
pl, rej, _ = build(calls)
assert not rej and len(pl) == 711
dbp, dbc = parse_db()
props = [[n, t] for n, t, _ in pl] + [s.split(':', 1) for s in dbp]
pstr = ['%s:%s' % (n, t) for n, t in props]
pb, plo = ck(pstr[:711]), ck(pstr)
assert pb == 0xE99606BA and plo == 0x65C37710, (hex(pb), hex(plo))
cb = [canon_ret(s) for s in cmdlist(calls)]
cd = [canon_ret(s) for s in dbc]
assert len(cb) == 290
cbk, clo = ck(cb), ck(cb + cd)
assert clo == 0xE5AE7722, hex(clo)
site = {n.lower(): s for n, t, s in pl}
json.dump(dict(source='GOG TOD.exe md5 d9beb351b3c78ee9f14a766a368f3ff9 (InitEntitiesDatabase FUN_0093C950 static replay) + '
                      'data_pc/scripts/stable/database.bin (md5 2415eb947f7c805019e365c29aa02421)',
               builtin=711, crc_builtin='%08X' % pb, crc_loaded='%08X' % plo,
               crc_rule='tod_crc(FUN_004657C0) over concat(u32le(index) + "name:type") for every global property',
               properties=props, builtin_register_function=[site[n.lower()] for n, t in props[:711]]),
          open(os.path.join(HERE, 'property_table.json'), 'w'), indent=0)
json.dump(dict(source='same', builtin=290, crc_builtin='%08X' % cbk, crc_loaded='%08X' % clo,
               crc_rule='tod_crc over concat(u32le(index) + "name(args)[:RetType]") for every global command',
               commands=cb + cd), open(os.path.join(HERE, 'command_table.json'), 'w'), indent=0)
print('ok', len(props), len(cb + cd), '%08X %08X %08X %08X' % (pb, plo, cbk, clo))
