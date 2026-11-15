"""Player movement tunables of Total Overdose (GOG build): read every value, write changes back.

Two kinds of tunables (docs/subsystem_player_movement.md sections 6 and 7):

  data   properties in overdose.main fragments (AnimDict locomotion slots, the player's camera_system, CameraDict,
         PhysicCtrl, database_player_status). Read with the fragment writer's codec; written by building a
         frag_override.zip with tools/fragment_writer (byte-exact, verified; list it first on configpc.txt's
         "filesystem =" line).
  code   float constants and immediates in TOD.exe that the locomotion code reads (accel/stop factors, top speeds,
         stick scaling, lean thresholds, turn scales...). Read from the exe file; written as movefeel.ini for the
         dinput8 proxy tools/movement/proxy (the proxy redirects each instruction to its own copy of the constant
         at load time, after checking the shipped bytes; the exe file is never modified).

usage (Python 3.12; set MSYS_NO_PATHCONV=1 under Git Bash):
  movetune.py show [--exe TOD.exe]                    every tunable with its current value and where it lives
  movetune.py export out.json                         current values (data + code) as a JSON you can edit
  movetune.py build edit.json --out DIR               edit.json = {"data": {name: value}, "code": {name: value},
                                                      "features": {key: value}} -> DIR/frag_override.zip (if any data
                                                      change), DIR/movefeel.ini (code + features), DIR/build_report.json;
                                                      every written value is read back from the output
  movetune.py selftest                                round trips: unchanged data -> byte-identical block; changed data
                                                      and code values read back; code patch undo -> identical bytes

Block source: the GOG archive C:/GOG Games/Total Overdose/blocks.naz (read only), or TOD_NAZ. The fragment writer
modules are looked up next to this file's parent (tools/fragment_writer) or in FW_DIR.
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.environ.get('FW_DIR') or os.path.join(os.path.dirname(HERE), 'fragment_writer')
if not os.path.exists(os.path.join(FW, 'fragtool.py')):
    FW = os.path.join(HERE, 'fw')
sys.path.insert(0, FW)
sys.dont_write_bytecode = True
import fragtool as ft          # noqa: E402
import fragedit as fe          # noqa: E402
import todblock as tb          # noqa: E402

GOG_EXE = os.environ.get('TOD_EXE', r'C:/GOG Games/Total Overdose/TOD.exe')
EXE_MD5 = 'd9beb351b3c78ee9f14a766a368f3ff9'
MAIN = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
ANIMDICT = '/data/Scripts/fragments/AnimDict.fragment'
CPC = '/data/Scripts/fragments/CharacterPlayerControlled.fragment'
CAMDICT = '/data/Scripts/fragments/CameraDict.fragment'
ESSENTIALS = '/data/Scripts/fragments/GameplayEssentials.fragment'

# ------------------------------------------------------------------------------------------------ data tunables
# name: (fragment, entity selector, property, note)
DATA = {}
for slot, note in [('walk', 'walk 15 fr, 1.544 m/cycle'), ('run', 'run 17 fr, 4.029 m/cycle'),
                   ('run_lean_left', 'lean 17 fr, 4.029 m'), ('run_lean_right', 'lean 17 fr, 4.029 m'),
                   ('run_land', 'after a jump'), ('sprint', 'sprint 13 fr, 4.468 m/cycle'),
                   ('run_backwards', 'back 17 fr, 3.223 m/cycle'), ('strafe_left', 'strafe 17 fr, 3.02 m/cycle'),
                   ('strafe_right', 'strafe 17 fr, 3.02 m/cycle')]:
    DATA['anim.%s.cps' % slot] = (ANIMDICT, 'PlayerAnims/normal/moves/' + slot, 'speed', 'cycles/s; ' + note)
    DATA['anim.%s.blend' % slot] = (ANIMDICT, 'PlayerAnims/normal/moves/' + slot, 'crossblendspeed', 'crossblend 1/s (5 = 0.2 s)')
DATA['anim.idle_stand.blend'] = (ANIMDICT, 'PlayerAnims/normal/idles/stand', 'crossblendspeed', 'run->idle blend 1/s')
for p in ('MaxAngle', 'AngleEaseInSpeed', 'MaxDistance', 'DistanceMoveOutSpeed', 'DistanceMoveInSpeed', 'DistanceZFactor'):
    DATA['cam.player.%s' % p] = (CPC, 'Animation/CameraCtrl', p, 'player camera_system until a trigger sets a camera type')
    for t in ('CharacterCombatCam', 'CharacterNormalCam', 'VehicleDefaultCam'):
        DATA['camdict.%s.%s' % (t, p)] = (CAMDICT, t, p, 'CameraDict type (set_camera_type; MoveOut forced to 0.3)')
DATA['cam.player.CameraPos.pos'] = (CPC, 'Animation/CameraCtrl/CameraPos', 'pos', 'camera pivot offset from the character (m)')
DATA['cam.player.CameraPos.orient'] = (CPC, 'Animation/CameraCtrl/CameraPos', 'orient', 'camera pivot pitch (quaternion)')
DATA['phys.player.TimeStep'] = (CPC, 'PhysicCtrl', 'TimeStep', 'fixed physics step (s); every per-step factor depends on it')
for p in ('StaminaGainStanding', 'StaminaGainRunning', 'StaminaCostSprinting', 'StaminaCostShootdodge',
          'PC_VisionAngle', 'PC_LockAngle'):
    DATA['status.%s' % p] = (ESSENTIALS, 'MasterCtrlAux/PlayerStatusCtrl', p, 'database_player_status')

# ------------------------------------------------------------------------------------------------ code tunables
# name: (vanilla, [(site VA, shipped bytes hex, operand offset, kind)], meaning). Same table as proxy/movefeel.cpp.
CODE = {
    'vel_run_keep': (0.75, [(0x561237, 'f30f10057c399b00', 4, 'memf')], 'run/strafe: velocity kept per 0.04 s step'),
    'vel_run_gain': (0.25, [(0x561057, 'f30f1005e06a9b00', 4, 'memf'), (0x5611BB, 'f30f1005e06a9b00', 4, 'memf')],
                     'run/strafe: share of k*stick added per step (keep+gain = 1 keeps the top speed)'),
    'vel_k_forward': (6.0, [(0x561155, 'f30f1005846b9b00', 4, 'memf')], 'top speed m/s (sim) forward/back'),
    'vel_k_side': (5.0, [(0x560FF1, 'f30f1005c8be9b00', 4, 'memf')], 'top speed m/s (sim) with any sideways stick'),
    'vel_sprint_keep': (0.75, [(0x560B18, 'f30f10057c399b00', 4, 'memf')], 'sprint: kept per step'),
    'vel_sprint_gain': (2.25, [(0x560B02, 'f30f100d30f69b00', 4, 'memf')], 'sprint: added per step (top = gain/(1-keep) = 9)'),
    'vel_stop_keep': (0.5, [(0x55E67A, 'f30f1005c8379b00', 4, 'memf')], 'stopping: velocity kept per step'),
    'vel_stop_cut2': (0.05, [(0x55E7CA, 'f30f1005e83b9b00', 4, 'memf')], 'stopping: |v|^2 below which v = 0'),
    'vel_walk_keep': (0.75, [(0x561CFC, 'f30f10057c399b00', 4, 'memf')], 'walk state (OnlyWalk): kept per step'),
    'vel_walk_gain': (0.3325, [(0x561C7A, 'f30f100d34f69b00', 4, 'memf')], 'walk state: added per step (top 1.33)'),
    'player_speed_mult': (0.95, [(0x55FCCA, '683333733f', 1, 'imm'), (0x560EE4, '683333733f', 1, 'imm')],
                          'player SpeedMultiplier at full stick (anim rate AND physics clock)'),
    'stick_mult_mid': (0.8, [(0x560E02, '68cdcc4c3f', 1, 'imm')], 'SpeedMultiplier for 0.5 <= |stick| < 0.75'),
    'stick_mult_low': (0.65, [(0x560D0A, '686666263f', 1, 'imm')], 'SpeedMultiplier for |stick| < 0.5'),
    'stick_scale_mid': (1.35, [(0x560E41, 'f30f10052cf69b00', 4, 'memf')], 'stick scale for 0.5 <= |stick| < 0.75'),
    'stick_scale_low': (1.7, [(0x560D49, 'f30f100524e29b00', 4, 'memf')], 'stick scale for |stick| < 0.5'),
    'lean_right_turn': (45.0, [(0x56956B, '0f2f0544f69b00', 3, 'memf')], 'run: turn deg/s above which lean right plays'),
    'lean_left_turn': (-45.0, [(0x5696FF, 'f30f100540f69b00', 4, 'memf')], 'run: turn deg/s below which lean left plays'),
    'mouse_yaw_scale': (180.0, [(0x73FF47, 'f30f5905d4f09b00', 4, 'memf')], 'turn deg/s = MouseDeltaX * this'),
    'mouse_pitch_scale': (180.0, [(0x73FFE8, 'f30f5905d4f09b00', 4, 'memf')], 'aim pitch = MouseDeltaY * this'),
    'pad_yaw_right': (180.0, [(0x73E33A, 'f30f590dd4f09b00', 4, 'memf')], 'pad turn = right^3*this + left^3*pad_yaw_left'),
    'pad_yaw_left': (-180.0, [(0x73E352, 'f30f5905d0f09b00', 4, 'memf')], 'see pad_yaw_right'),
    'autoturn_slow': (6.2831855, [(0x57CD72, 'f30f5905cc379b00', 4, 'memf')], 'target-lock turn rad/s under 1 m/s'),
    'autoturn_fast': (10.995574, [(0x57CE25, 'f30f590564f79b00', 4, 'memf')], 'target-lock turn rad/s over 1 m/s'),
    'sprint_tap_decay': (4.0, [(0x73F80F, 'f30f590d5c359b00', 4, 'memf'), (0x73DDA3, 'f30f590d5c359b00', 4, 'memf')],
                         'double-tap counter decay /s (tap window 1/decay s)'),
    'sprint_hold_gain': (5.0, [(0x73F95B, 'f30f5905c8be9b00', 4, 'memf'), (0x73DED9, 'f30f5905c8be9b00', 4, 'memf')],
                         'counter gain /s while sprint is held'),
}
FEATURES = {'phase_sync': 'copy the outgoing loco clip phase into the incoming one (hook 0x55B7E3)',
            'phase_sync_all_characters': '1 = NPCs too',
            'mouse_accumulate': 'frame-rate independent mouse turn (hooks 0x73FFD5, 0x73E3F9, 0x57D504)',
            'mouse_seconds_per_frame': 'degrees per frame = turn * this (0.95/60 = vanilla average at 60 fps)',
            'diagonal_normalize': 'clamp the stick to length 1 (W+D 7.07 -> 5 m/s)',
            'run_camera_offset': 'experimental: enable the run state camera offset code that ships switched off',
            'log_motion': 'log the player position/velocity/yaw every integrate to tod_movefeel.log (for velmodel.py check)'}


class Exe:
    def __init__(self, path=GOG_EXE, data=None):
        self.path = path
        self.d = bytearray(open(path, 'rb').read() if data is None else data)
        pe = struct.unpack_from('<I', self.d, 0x3C)[0]
        n = struct.unpack_from('<H', self.d, pe + 6)[0]
        opt = struct.unpack_from('<H', self.d, pe + 20)[0]
        self.base = struct.unpack_from('<I', self.d, pe + 24 + 28)[0]
        self.secs = []
        for i in range(n):
            o = pe + 24 + opt + i * 40
            vs, va, rs, ro = struct.unpack_from('<IIII', self.d, o + 8)
            self.secs.append((self.base + va, vs, ro, rs))

    def off(self, va):
        for sva, vs, ro, rs in self.secs:
            if sva <= va < sva + max(vs, rs):
                return ro + va - sva
        raise ValueError('VA %08X outside the image' % va)

    def rd(self, va, n):
        o = self.off(va)
        return bytes(self.d[o:o + n])

    def wr(self, va, b):
        o = self.off(va)
        self.d[o:o + len(b)] = b

    def md5(self):
        return hashlib.md5(self.d).hexdigest()


def code_value(exe, name, pool=None):
    """current value of a code tunable; with pool = {va: float} (a simulated proxy pool) redirected operands resolve there."""
    vanilla, sites, _ = CODE[name]
    vals = []
    for va, orig, opoff, kind in sites:
        if kind == 'imm':
            vals.append(struct.unpack('<f', exe.rd(va + opoff, 4))[0])
        else:
            ptr = struct.unpack('<I', exe.rd(va + opoff, 4))[0]
            if pool is not None and ptr in pool:
                vals.append(pool[ptr])
            else:
                vals.append(struct.unpack('<f', exe.rd(ptr, 4))[0])
    if any(abs(v - vals[0]) > 1e-6 for v in vals):
        raise ValueError('%s: sites disagree %s' % (name, vals))
    return vals[0]


def code_sites_ok(exe, name):
    return all(exe.rd(va, len(orig) // 2).hex() == orig for va, orig, _, _ in CODE[name][1])


def simulate_proxy(exe, values):
    """apply movefeel.ini constants to an in-memory exe the way the proxy does; returns (pool, undo list)."""
    pool, undo, nxt = {}, [], 0x7F000000
    for name, v in values.items():
        if not code_sites_ok(exe, name):
            raise ValueError('%s: shipped bytes differ' % name)
        slot = nxt
        nxt += 4
        pool[slot] = float(struct.unpack('<f', struct.pack('<f', v))[0])
        for va, orig, opoff, kind in CODE[name][1]:
            undo.append((va + opoff, exe.rd(va + opoff, 4)))
            exe.wr(va + opoff, struct.pack('<I', slot) if kind == 'memf' else struct.pack('<f', v))
    return pool, undo


def load_main(block=None):
    raw, entry, ext = ft.load_block_bytes(block or MAIN, MAIN if block else None)
    return raw, entry, ext


def data_values(raw, ext):
    b = tb.Block(raw, ext)
    frs, _ = ft.fragments(b)
    T = ft.types()
    docs, out = {}, {}
    for name, (frag, sel, prop, _) in DATA.items():
        if frag not in docs:
            k, nm = ft.pick_fragment(frs, frag)
            docs[frag] = fe.FragDoc(b.payloads[k], T, nm)
        d = docs[frag]
        n = d.find(sel)
        v = d.get(n, prop)
        out[name] = list(v) if isinstance(v, tuple) else v
    return out


def cmd_show(argv):
    exe = Exe(argv[argv.index('--exe') + 1] if '--exe' in argv else GOG_EXE)
    raw, entry, ext = load_main()
    print('exe %s md5 %s%s' % (exe.path, exe.md5(), '' if exe.md5() == EXE_MD5 else '  (NOT the GOG build the sites were taken from)'))
    print('block %s sha256 %s' % (entry, hashlib.sha256(raw).hexdigest()[:16]))
    print('\n# data (overdose.main fragments)')
    vals = data_values(raw, ext)
    for name, (frag, sel, prop, note) in DATA.items():
        v = vals[name]
        vs = '%.6g' % v if isinstance(v, float) else json.dumps(v)
        print('  %-44s %-26s %s : %s.%s  (%s)' % (name, vs, frag.split('/')[-1], sel, prop, note))
    print('\n# code (TOD.exe; written through movefeel.ini + the dinput8 proxy)')
    for name, (van, sites, note) in CODE.items():
        ok = code_sites_ok(exe, name)
        v = code_value(exe, name) if ok else float('nan')
        print('  %-20s %-10.6g %s  sites %s  %s' % (name, v, 'ok ' if ok else 'BYTES DIFFER',
                                                  ','.join('%06X' % s[0] for s in sites), note))
    print('\n# proxy features (movefeel.ini)')
    for k, v in FEATURES.items():
        print('  %-28s %s' % (k, v))
    return 0


def cmd_export(argv):
    exe = Exe(GOG_EXE)
    raw, entry, ext = load_main()
    out = dict(data=data_values(raw, ext), code={n: code_value(exe, n) for n in CODE},
               features={'phase_sync': 0, 'mouse_accumulate': 0, 'mouse_seconds_per_frame': round(0.95 / 60, 6),
                         'diagonal_normalize': 0, 'run_camera_offset': 0})
    json.dump(out, open(argv[2], 'w'), indent=1)
    print('wrote %s (%d data, %d code values)' % (argv[2], len(out['data']), len(out['code'])))
    return 0


def build(spec, outdir, verbose=True):
    """returns report dict; raises on any failure. Writes nothing outside outdir."""
    os.makedirs(outdir, exist_ok=True)
    rep = dict(spec=spec, result='FAIL')
    data = spec.get('data', {})
    code = spec.get('code', {})
    feats = spec.get('features', {})
    for n in data:
        if n not in DATA:
            raise KeyError('unknown data tunable %s' % n)
    for n in code:
        if n not in CODE:
            raise KeyError('unknown code tunable %s' % n)
    for n in feats:
        if n not in FEATURES:
            raise KeyError('unknown feature %s' % n)
    # data -> fragment edit through the fragment writer (verify_block does the full check list)
    if data:
        raw, entry, ext = load_main()
        ops = [dict(op='set', fragment=DATA[n][0], entity=DATA[n][1], prop=DATA[n][2], value=v) for n, v in data.items()]
        T = ft.types()
        r0 = ft.roundtrip_block(raw, ext, T)
        if r0['fail'] or not r0['block_identical']:
            raise RuntimeError('base block does not round-trip')
        old, nb, docs, intended = ft.apply_ops(raw, ext, ops, T)
        newb = nb.serialize()
        vr, chk = ft.verify_block(old, newb, ext, docs, intended, T)
        back = data_values(newb, ext)
        bad = {n: (v, back[n]) for n, v in data.items() if not same(v, back[n])}
        if bad:
            raise RuntimeError('read-back mismatch %s' % bad)
        fn = os.path.join(outdir, os.path.basename(entry))
        open(fn, 'wb').write(newb)
        zp = os.path.join(outdir, ft.ZIP_NAME)
        rep['zip'] = ft.write_zip(zp, [(entry, newb)])
        rep['block'] = dict(entry=entry, base_sha256=hashlib.sha256(raw).hexdigest(),
                            out_sha256=hashlib.sha256(newb).hexdigest(), identical_to_base=(newb == raw),
                            readback=back and {n: back[n] for n in data})
        open(os.path.join(outdir, 'frag_edit.json'), 'w').write(json.dumps(
            {'description': 'movetune data changes', 'blocks': [{'block': MAIN, 'ops': ops}]}, indent=1))
        rep['configpc_line'] = 'filesystem = ' + ', '.join([ft.ZIP_NAME] + ft.BASE_ARCHIVES)
    # code + features -> movefeel.ini, checked against the exe and through a simulated proxy pass
    if code or feats:
        exe = Exe(GOG_EXE)
        pristine = bytes(exe.d)
        pool, undo = simulate_proxy(exe, code)
        back = {n: code_value(exe, n, pool) for n in code}
        bad = {n: (v, back[n]) for n, v in code.items() if abs(back[n] - v) > 1e-6 * max(1, abs(v))}
        for va, b in reversed(undo):
            exe.wr(va, b)
        if bad or bytes(exe.d) != pristine:
            raise RuntimeError('code read-back mismatch %s or undo not identical' % bad)
        lines = ['# movefeel.ini - written by tools/movement/movetune.py; put next to TOD.exe with the movefeel dinput8.dll',
                 '# code constants (vanilla values in comments)']
        for n, v in code.items():
            lines.append('%s = %.7g    # vanilla %.7g: %s' % (n, v, CODE[n][0], CODE[n][2]))
        lines.append('# features')
        for n, v in feats.items():
            lines.append('%s = %s    # %s' % (n, v, FEATURES[n]))
        open(os.path.join(outdir, 'movefeel.ini'), 'w', newline='\r\n').write('\n'.join(lines) + '\n')
        rep['code_readback'] = back
    rep['result'] = 'PASS'
    json.dump(rep, open(os.path.join(outdir, 'build_report.json'), 'w'), indent=1, default=str)
    if verbose:
        print(json.dumps({k: rep[k] for k in rep if k in ('result', 'zip', 'configpc_line', 'code_readback')}, indent=1, default=str))
    return rep


def same(a, b):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    return a == b


def cmd_build(argv):
    spec = json.load(open(argv[2]))
    out = argv[argv.index('--out') + 1]
    try:
        build(spec, out)
    except Exception as e:  # noqa: BLE001
        print('FAIL: %s' % e)
        return 1
    return 0


def cmd_selftest(argv):
    import tempfile
    tmp = tempfile.mkdtemp(prefix='movetune_')
    exe = Exe(GOG_EXE)
    ok = True
    print('exe md5 %s %s' % (exe.md5(), 'GOG' if exe.md5() == EXE_MD5 else 'UNEXPECTED'))
    # 1 code: every site has the shipped bytes; vanilla values match the table
    for n, (van, sites, _) in CODE.items():
        good = code_sites_ok(exe, n) and abs(code_value(exe, n) - van) < 1e-4 * max(1, abs(van))
        ok &= good
        if not good:
            print('  code %s: FAIL' % n)
    print('1 code table: %d tunables, %d sites, shipped bytes and vanilla values %s' % (
        len(CODE), sum(len(s[1]) for s in CODE.values()), 'OK' if ok else 'FAIL'))
    # 2 data unchanged -> block byte-identical
    raw, entry, ext = load_main()
    cur = data_values(raw, ext)
    T = ft.types()
    ops = [dict(op='set', fragment=DATA[n][0], entity=DATA[n][1], prop=DATA[n][2], value=v) for n, v in cur.items()
           if v is not None]
    old, nb, docs, intended = ft.apply_ops(raw, ext, ops, T)
    same_block = nb.serialize() == raw
    ok &= same_block
    print('2 data round trip: %d values written back unchanged -> overdose.main %s' % (
        len(ops), 'byte-identical' if same_block else 'DIFFERS'))
    # 3 changed data + code -> read back
    spec = json.load(open(os.path.join(HERE, 'proposal.json')))
    rep = build(spec, tmp, verbose=False)
    print('3 proposal build: %s; %d data values read back from the rebuilt block, %d code values through a simulated '
          'proxy pass, undo identical' % (rep['result'], len(spec.get('data', {})), len(spec.get('code', {}))))
    ok &= rep['result'] == 'PASS'
    # 4 a full code pass with every tunable changed, then undone
    exe = Exe(GOG_EXE)
    pristine = bytes(exe.d)
    vals = {n: CODE[n][0] * 1.25 + 0.5 for n in CODE}
    pool, undo = simulate_proxy(exe, vals)
    rb = all(abs(code_value(exe, n, pool) - struct.unpack('<f', struct.pack('<f', v))[0]) < 1e-6 for n, v in vals.items())
    for va, b in reversed(undo):
        exe.wr(va, b)
    ident = bytes(exe.d) == pristine
    ok &= rb and ident
    print('4 code round trip: all %d tunables changed and read back %s; undo -> exe bytes %s' % (
        len(vals), 'OK' if rb else 'FAIL', 'identical' if ident else 'DIFFER'))
    if ok:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST', 'PASS' if ok else 'FAIL (outputs kept in %s)' % tmp)
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    return {'show': cmd_show, 'export': cmd_export, 'build': cmd_build, 'selftest': cmd_selftest}[argv[1]](argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
