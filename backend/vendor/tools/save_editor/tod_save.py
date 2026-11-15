#!/usr/bin/env python3
"""Total Overdose save editor (PC/GOG build 1925).  Read-only on the game install; never writes a profile.

  python tod_save.py info     SLOT                      readable summary (progress, position, health, weapons, power-ups)
  python tod_save.py verify   SLOT [SLOT...]            decode -> JSON -> encode must be byte-identical
  python tod_save.py to-json  SLOT OUT.json             full lossless JSON (every record, typed)
  python tod_save.py from-json IN.json OUT_SLOT         rebuild a valid slot (CRCs, zlib, padding recomputed)
  python tod_save.py find     SLOT REGEX                print records whose node type/name/property matches
  python tod_save.py diff     SLOT_A SLOT_B             header, summary and record differences
  python tod_save.py edit     SLOT OUT_SLOT [ops]       semantic edits, see --help of 'edit'
  python tod_save.py settings Slot11 [--keys-from SLOT] [--to-json F | --from-json F --out OUT]

SLOT = a copy of %USERPROFILE%/Documents/Total Overdose/savegames/SlotNN (0x50000 bytes).
The game install (blocks.naz) is read to name and type every record: set TOD_GAME_DIR if it is not
C:\\GOG Games\\Total Overdose.
"""
import argparse, json, os, sys, math, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import savefile, editlib, settings

FORBIDDEN = [os.path.normcase(os.path.join(os.path.expanduser('~'), 'Documents', 'Total Overdose')),
             os.path.normcase(savefile.GAME_DIR)]


def safe_out(path):
    p = os.path.normcase(os.path.abspath(path))
    for f in FORBIDDEN:
        if p.startswith(f):
            sys.exit('refusing to write into %s (work on copies; install a test save by hand)' % f)
    return path


def load(path):
    return savefile.decode(open(path, 'rb').read())


def cmd_info(a):
    s = editlib.Save(load(a.slot))
    out = editlib.summary(s)
    if a.json:
        print(json.dumps(out, indent=1))
        return
    for k, v in out.items():
        if k in ('weapons', 'powerups', 'missions'):
            continue
        print('%-45s %s' % (k, v))
    print('weapons (own/dual ammo/max clip1/clip2):')
    for k, v in out.get('weapons', {}).items():
        print('   %-17s %s%s %4d/%-4d %3d/%-3d' % (k, 'X' if v['own'] else '.', 'D' if v['dual'] else ' ',
                                                 v['ammo'], v['max'], v['clip1'], v['clip2']))
    print('power-ups (count/max):', ', '.join('%s %d/%d' % (k, v[0], v[1]) for k, v in out.get('powerups', {}).items()))
    print('missions (C complete, o open):')
    for m in out['missions']:
        print('   %2d %-13s %s%s hi=%-6s %s' % (m['i'], m['type'], 'C' if m['complete'] else '.', 'o' if m['open'] else ' ',
                                             m['hiscore'], m['name']))


def cmd_verify(a):
    ok = True
    for p in a.slot:
        b = open(p, 'rb').read()
        j = savefile.decode(b)
        b2 = savefile.encode(json.loads(json.dumps(j)))
        same = b2 == b
        ok &= same and all(j['checks'].values()) and not j['parse_problems']
        print('%s records=%d problems=%d checks=%s roundtrip=%s' % (p, len(j['records']), len(j['parse_problems']),
                                                                    all(j['checks'].values()), 'IDENTICAL' if same else 'DIFFERENT'))
    sys.exit(0 if ok else 1)


def cmd_tojson(a):
    j = load(a.slot)
    with open(safe_out(a.out), 'w') as f:
        json.dump(j, f, indent=a.indent)
    print('wrote', a.out, len(j['records']), 'records')


def cmd_fromjson(a):
    j = json.load(open(a.json))
    b = savefile.encode(j)
    open(safe_out(a.out), 'wb').write(b)
    j2 = savefile.decode(b)
    print('wrote', a.out, 'checks', j2['checks'], 'problems', len(j2['parse_problems']))


def cmd_find(a):
    j = load(a.slot)
    rx = re.compile(a.regex, re.I)
    for r in j['records']:
        if 'n' not in r:
            continue
        info = j['nodes'].get(r['n'], {})
        hay = '%s %s %s %s' % (r['n'], info.get('type'), info.get('name'), r.get('name'))
        if rx.search(hay):
            v = json.dumps(r['v'])[:a.width] if 'v' in r else ('thread=%s' % r.get('thread') if 'thread' in r else 'raw')
            print('%-8s %-45s %-24s %3x %-30s %s' % (r['n'], (info.get('type') or '')[:45], (info.get('name') or '')[:24],
                                                     r['p'], r.get('name') or '', v))


def cmd_diff(a):
    ja, jb = load(a.a), load(a.b)
    for k in ('folders', 'game_time_ms', 'frame'):
        if ja['header'][k] != jb['header'][k]:
            print('header.%s: %s -> %s' % (k, ja['header'][k], jb['header'][k]))
    if ja['summary'] != jb['summary']:
        print('summary: %s -> %s' % (ja['summary']['items'], jb['summary']['items']))
    def idx(j):
        return {(r['n'], r['p']): r for r in j['records'] if 'n' in r}
    ia, ib = idx(ja), idx(jb)
    removed = [k for k in ia if k not in ib]
    added = [k for k in ib if k not in ia]
    changed = [k for k in ia if k in ib and json.dumps(ia[k], sort_keys=True) != json.dumps(ib[k], sort_keys=True)]
    blocks = {}
    for k in removed:
        blocks[k[0].split(':')[0]] = blocks.get(k[0].split(':')[0], 0) + 1
    print('removed %d records (by block %s), added %d, changed %d' % (len(removed), blocks, len(added), len(changed)))
    for k in added + changed:
        r = ib[k]
        info = jb['nodes'].get(k[0], ja['nodes'].get(k[0], {}))
        before = json.dumps(ia[k].get('v', ia[k].get('thread')))[:a.width] if k in ia else '(new)'
        after = json.dumps(r.get('v', r.get('thread')))[:a.width]
        print('  %-8s %-40s %-22s %s: %s -> %s' % (k[0], (info.get('type') or '')[:40], (info.get('name') or '')[:22],
                                                  r.get('name', 'p%x' % k[1]), before, after))


def parse_vec(t):
    v = [float(x) for x in t.split(',')]
    return v


def cmd_edit(a):
    j = load(a.slot)
    s = editlib.Save(j)
    log = []
    if a.start_mission is not None:
        r = editlib.start_mission(s, a.start_mission, player_at_teleport=not a.keep_position)
        log.append(('start_mission', {k: v for k, v in r.items() if k not in ('moved', 'blocks')}))
    if a.move:
        v = parse_vec(a.move)
        log.append(('move_player', s.move_player(v[:3], v[3] if len(v) > 3 else None)))
    if a.near:
        target = parse_vec(a.near)
        cur = s.player_pos()
        dx, dz = target[0] - cur[0], target[2] - cur[2]
        if a.from_dir:
            fd = parse_vec(a.from_dir)
            dx, dz = -fd[0], -fd[1]
        L = math.hypot(dx, dz) or 1.0
        pos = [target[0] - dx / L * a.dist, target[1], target[2] - dz / L * a.dist]
        yaw = math.degrees(math.atan2(dx, dz)) + 180.0          # Kapow characters face local -Z
        log.append(('near', s.move_player(pos, yaw)))
    if a.heal:
        log.append(('heal', s.heal()))
    if a.give_weapons:
        s.give_weapons('all', 'max')
        log.append(('give_weapons', 'all owned, reserve ammo = max'))
    if a.powerups:
        counts = {}
        for kv in a.powerups.split(','):
            k, v = kv.split('=')
            counts[k] = v
        log.append(('powerups', s.set_powerups(counts)))
    if a.score is not None:
        log.append(('score', s.set(s.player_status(), 'OverallScore', a.score)))
    if a.unlock:
        log.append(('unlock', s.unlock(a.unlock)))
    for spec in a.set or []:
        key, rest = spec.split('.', 1)
        prop, val = rest.split('=', 1)
        log.append(('set', key, prop, s.set(key, prop, json.loads(val))))
    b = savefile.encode(s.j)
    open(safe_out(a.out), 'wb').write(b)
    j2 = savefile.decode(b)
    ok = all(j2['checks'].values()) and not j2['parse_problems']
    for l in log:
        print(json.dumps(l, default=str)[:600])
    print('wrote %s (re-decode: checks %s, problems %d) -> %s' % (a.out, all(j2['checks'].values()),
                                                                 len(j2['parse_problems']), 'OK' if ok else 'FAILED'))
    if a.report:
        out = editlib.summary(editlib.Save(j2))
        json.dump({'edits': log, 'after': out}, open(safe_out(a.report), 'w'), indent=1, default=str)


def cmd_settings(a):
    b = open(a.slot, 'rb').read()
    if a.from_json:
        j = json.load(open(a.from_json))
        out = settings.encode(j)
        open(safe_out(a.out), 'wb').write(out)
        print('wrote', a.out, 'crc ok', settings.decode(out)['crc_ok'])
        return
    j = settings.decode(b)
    print('crc ok:', j['crc_ok'], ' roundtrip:', settings.encode(j) == b)
    keys = None
    if a.keys_from:   # key index -> key name table (cache node DB_KEY_INDEX_TO_KEYSTRING_LIST) of any game save
        s = editlib.Save(load(a.keys_from))
        kl = s.get(s.node1(r'cache\(Node\)'), 'DB_KEY_INDEX_TO_KEYSTRING_LIST') or []
        keys = [x if isinstance(x, str) else (x or {}).get('s') for x in kl]
    if a.to_json:
        json.dump(j, open(safe_out(a.to_json), 'w'), indent=1)
    else:
        for e in j['values']:
            extra = ''
            if keys and e['name'].startswith('InputKey_') and isinstance(e['v'], int) and 0 <= e['v'] < len(keys):
                extra = '  (%s)' % keys[e['v']]
            print('  %-34s %-8s %s%s' % (e['name'], e['t'], e['v'], extra))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('info'); p.add_argument('slot'); p.add_argument('--json', action='store_true'); p.set_defaults(f=cmd_info)
    p = sp.add_parser('verify'); p.add_argument('slot', nargs='+'); p.set_defaults(f=cmd_verify)
    p = sp.add_parser('to-json'); p.add_argument('slot'); p.add_argument('out'); p.add_argument('--indent', type=int, default=None); p.set_defaults(f=cmd_tojson)
    p = sp.add_parser('from-json'); p.add_argument('json'); p.add_argument('out'); p.set_defaults(f=cmd_fromjson)
    p = sp.add_parser('find'); p.add_argument('slot'); p.add_argument('regex'); p.add_argument('--width', type=int, default=120); p.set_defaults(f=cmd_find)
    p = sp.add_parser('diff'); p.add_argument('a'); p.add_argument('b'); p.add_argument('--width', type=int, default=100); p.set_defaults(f=cmd_diff)
    p = sp.add_parser('edit', help='semantic edits')
    p.add_argument('slot'); p.add_argument('out')
    p.add_argument('--start-mission', type=int, help='EXPERIMENTAL: Mission_List index to (re)start (blocks reloaded fresh)')
    p.add_argument('--keep-position', action='store_true', help='with --start-mission: do not move Ram to the TELEPORT node')
    p.add_argument('--move', help='x,y,z[,yaw_deg] new player position (Kapow units = metres; y is up)')
    p.add_argument('--near', help='x,y,z of a target (an enemy): put Ram --dist m away facing it')
    p.add_argument('--from-dir', help='dx,dz: approach direction for --near (default: from Ram\'s current position)')
    p.add_argument('--dist', type=float, default=5.0)
    p.add_argument('--heal', action='store_true', help='DamageTaken = 0')
    p.add_argument('--give-weapons', action='store_true', help='own every weapon, reserve ammo = max')
    p.add_argument('--powerups', help='e.g. rewind=max,loco=2,ram=2 (names: %s)' % ','.join(editlib.POWERUPS[1:]))
    p.add_argument('--score', type=int, help='database_player_status.OverallScore')
    p.add_argument('--unlock', choices=['open', 'complete'], help='open: every valid mission open; complete: also mark story missions complete')
    p.add_argument('--set', action='append', help="raw: NODE.PROP=JSON, e.g. 1:cf.OverallScore=100000")
    p.add_argument('--report', help='write a JSON report of the edits and the resulting summary')
    p.set_defaults(f=cmd_edit)
    p = sp.add_parser('settings'); p.add_argument('slot'); p.add_argument('--to-json'); p.add_argument('--from-json'); p.add_argument('--out')
    p.add_argument('--keys-from', help='a game save slot to name the InputKey_* indices')
    p.set_defaults(f=cmd_settings)
    a = ap.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
