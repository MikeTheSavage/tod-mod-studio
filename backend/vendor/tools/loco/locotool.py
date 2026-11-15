"""Loco moves, slow motion, combos and rewind of Total Overdose (GOG build): read every tunable, write changes back.

Two kinds (docs/subsystem_loco_slowmo.md section 9):
  data  values stored in overdose.main fragments: power-up maxima / start charges, slow-motion stamina cost, rewind health,
        golden-gun and mariachi aim cones (GameplayEssentials PlayerStatusCtrl), slow-motion blur (TimeCtrl), pickup
        amounts and god time (GoodiesDict), combo timer and music thresholds (ComboSystem), the kill thresholds and
        goodies of combo awards (ComboAwardDict), points of each combo move (ComboMoveDict), enemy-state points
        (ComboEnemyStateDict), unique combo moves (bonus and goodie award, UniqueComboMovesDict), cheat grants
        (CheatCtrl). Read with the fragment writer's codec; written as loco_override.zip (byte-exact rebuild of
        overdose.main, verified; list it first on configpc.txt's "filesystem =" line).
  code  constant operands in TOD.exe (slow-motion scales and ramps, the Tornado's time scale, radius, damage and pacing,
        Time Stop, Mariachi and El Toro durations, buddy lifetime, golden-bullet camera, rewind length and speed,
        power-up menu freeze, ...). Written as loco_patch.json (same format as frametiming_patch.json) and
        locotune.ini for the locotune dinput8 proxy (tools/loco/proxy). memf = the instruction's 32-bit address operand
        is pointed at a private float (the shared .rdata constant is never changed); imm8 / imm32 / immf = immediate.
        TOD.exe is never modified on disk.

usage (Python 3.12, stdlib only; set MSYS_NO_PATHCONV=1 under Git Bash; runs at below-normal priority):
  locotool.py show [--all]                every tunable: value, where it lives, what it does (--all: also the
                                          per-award / per-move tables)
  locotool.py export OUT.json             current values as an editable {"data": {...}, "code": {...}}
  locotool.py build EDIT.json --out DIR   -> DIR/loco_override.zip + overdose.main (data), DIR/loco_patch.json and
                                          DIR/locotune.ini (code), DIR/build_report.json; every value read back
  locotool.py combos                      combo tables: kill awards (goodies), move points, enemy states, unique moves
  locotool.py census [-o OUT.tsv]         every block: goodie pickups, Trigger_Activate_Loco_Move / _Combo /
                                          _Overall_Score, slow-motion camera triggers
  locotool.py gen-proxy DIR               write DIR/locotune_sites.h (the proxy's site table) from this file
  locotool.py selftest                    round trips (see doc section 10)

EDIT.json: {"description": "...", "data": {"powerup.max.Loco_Moves": 5, "award.6_Kills_Special_Move.KillsNeeded": 4},
            "code": {"slowmo.dive_scale": 0.25, "tornado.radius": 45}}
The fragment writer is looked up in FW_DIR, ../fragment_writer (sibling of this folder) or ../fw.
Block source: the GOG archive C:/GOG Games/Total Overdose/blocks.naz (read only) or TOD_NAZ; exe: TOD_EXE or the GOG
TOD.exe (read only).
"""
import hashlib
import json
import os
import struct
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
for _c in (os.environ.get('FW_DIR', ''), os.path.join(os.path.dirname(HERE), 'fragment_writer'),
           os.path.join(HERE, '..', 'fw')):
    if _c and os.path.exists(os.path.join(_c, 'fragtool.py')):
        sys.path.insert(0, os.path.abspath(_c))
        break
try:
    import lowprio  # noqa: F401  (fragment writer helper: below-normal priority on Windows)
except Exception:
    pass
import fragtool as ft          # noqa: E402
import todblock as tb          # noqa: E402
import todfrag as tf           # noqa: E402
import fragedit as fe          # noqa: E402

EXE = os.environ.get('TOD_EXE', r'C:/GOG Games/Total Overdose/TOD.exe')   # read only
EXE_MD5 = 'd9beb351b3c78ee9f14a766a368f3ff9'
MAIN = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
ZIP_NAME = 'loco_override.zip'
ESS = '/data/Scripts/fragments/GameplayEssentials.fragment'
GOOD = '/data/Scripts/fragments/GoodiesDict.fragment'
COMBO = '/data/Scripts/fragments/ComboSystem.fragment'
AWARD = '/data/Scripts/fragments/ComboAwardDict.fragment'
MOVES = '/data/Scripts/fragments/ComboMoveDict.fragment'
ESTATE = '/data/Scripts/fragments/ComboEnemyStateDict.fragment'
UNIQUE = '/data/Scripts/fragments/UniqueComboMovesDict.fragment'
PS, TC, CH, GD, CC = '0x0010031C', '0x0010032B', '0x00100321', '0x00100B2E', '0x00100232'

SLOTS = ['None', 'Rewinds', 'Golden_Bullets', 'Loco_Moves', 'Ram_Moves', 'Medkits', 'Sombreros', 'Time_Stops',
         'Mex_Wrestlers', 'El_Mariachis', 'Pinatas', 'Tequillas']
MOVE_NAMES = {1: 'Rewind', 2: 'Golden Gun', 3: 'Tornado (Loco_Moves, dual Mac10 spin)', 4: 'El Toro (Ram_Moves charge)',
              5: 'Medkit (not usable)', 6: 'Sombrero (Crazy Mexican buddy)', 7: 'Time Stop (disabled: max forced 0)',
              8: 'Mexican Wrestler buddy', 9: 'El Mariachi (guitar-case gun)', 10: 'Pinata', 11: 'Tequila (no effect found)'}
GOODIES = {0: 'Medium_Health', 1: 'Large_Health', 2: 'PermHealthUpgrade', 3: 'ComboTimeMultiplier', 4: 'GodMode',
           5: 'race bonus (medium?)', 6: 'race bonus (large?)', 7: 'MedKit -> slot 5', 8: 'Rewind -> slot 1',
           9: 'Golden_Gun -> slot 2', 10: 'Loco_Move -> slot 3', 11: 'Ram_Move -> slot 4', 12: 'Sombrero -> slot 6',
           13: 'Time_Stop -> slot 7', 14: 'Wrestler -> slot 8', 15: 'Mariachi -> slot 9', 16: 'Pinata -> slot 10',
           17: 'Tequila -> slot 11', 18: 'PermStaminaUpgrade', 19: 'PermWeaponUpgrade', 20: 'SmallOverallBonus',
           21: 'LargeOverallBonus'}

# ------------------------------------------------------------------------------------------- data tunables (static)
# name: (fragment, entity, property, registration default, note)
DATA = {}
for _i, _s in enumerate(SLOTS[1:], 1):
    DATA['powerup.max.%s' % _s] = (ESS, PS, 'Default_Max_%s' % _s, None,
                                   'most charges of slot %d %s%s' % (_i, MOVE_NAMES[_i],
                                   ' (IGNORED: the inventory init 0x5BD1E0 forces max 0 for slots 5 and 7)' if _i in (5, 7) else ''))
    DATA['powerup.start.%s' % _s] = (ESS, PS, 'Default_%s' % _s, None, 'charges of slot %d at a new game' % _i)
DATA.update({
    'stamina.slowmo_cost_per_s': (ESS, PS, 'StaminaCostShootdodge', 110.0,
                                  'stamina used per REAL second of automatic slow motion (0x784820; MaxStamina 1000)'),
    'stamina.gain_standing': (ESS, PS, 'StaminaGainStanding', 70.0, 'stamina regained per second standing'),
    'stamina.gain_running': (ESS, PS, 'StaminaGainRunning', 25.0, 'stamina regained per second running'),
    'stamina.cost_sprinting': (ESS, PS, 'StaminaCostSprinting', 45.0, 'sprint cost per second (shipped -80 = free)'),
    'rewind.health_after': (ESS, PS, 'HealthAfterRewind', 500.0, 'health given back by a rewind when lower (0x7675C0)'),
    'hat.possession_time': (ESS, PS, 'HatPossesionTime', 20.0, 'hat bonus timer'),
    'golden.vision_angle': (ESS, PS, 'PC_GoldenGunVisionAngle', 20.0, 'auto-aim vision cone with the golden gun (deg)'),
    'golden.lock_angle': (ESS, PS, 'PC_GoldenGunLockAngle', 20.0, 'auto-aim lock cone with the golden gun (deg)'),
    'mariachi.shoot_angle': (ESS, PS, 'MariachiShootAngle', 0.0, 'mariachi guitar-case gun shoot cone (deg)'),
    'mariachi.vision_angle': (ESS, PS, 'MariachiVisionAngle', 0.0, 'mariachi vision cone (deg)'),
    'mariachi.turn_speed': (ESS, PS, 'MariachiTurnSpeed', 0.4, 'mariachi turn speed'),
    'timectrl.normal_motion_blur': (ESS, TC, 'normal_motion_blur', 0.15, 'GFX motion blur at normal time'),
    'timectrl.slomo_motion_blur': (ESS, TC, 'slomo_motion_blur', 1.0, 'GFX motion blur in slow motion (scale < 0.5)'),
    'combo.time_limit': (COMBO, CC, 'ComboTimeLimit', None, 'seconds of GAME time a combo lasts without a new kill'),
    'combo.fast_kill_time_limit': (COMBO, CC, 'FastKillTimeLimit', None, 'fast-kill window (0 in the data)'),
    'combo.sound_level1': (COMBO, CC, 'Combo_Sound_Level1', 2, 'combo music level thresholds (see subsystem_sound_music)'),
    'combo.sound_level2': (COMBO, CC, 'Combo_Sound_Level2', 3, ''),
    'combo.sound_level3': (COMBO, CC, 'Combo_Sound_Level3', 4, ''),
    'combo.sound_level4': (COMBO, CC, 'Combo_Sound_Level4', 5, ''),
})
for _p, _n in (('MediumHealth', 'health given by goodie 0'), ('LargeHealth', 'health given by goodie 1'),
               ('ComboTimeMultiplier', 'goodie 3'), ('GodTime', 'seconds of god mode (goodie 4)'),
               ('MedKitNum', 'charges per MedKit pickup'), ('RewindNum', 'charges per Rewind pickup'),
               ('GoldenGunNum', 'charges per Golden Gun pickup'), ('LocoMoveNum', 'charges per Loco Move pickup'),
               ('RamMoveNum', 'charges per Ram Move pickup'), ('SombreroMoveNum', 'charges per Sombrero pickup'),
               ('TimeStopNum', 'charges per Time Stop pickup'), ('MexWrestlerNum', 'charges per Wrestler pickup'),
               ('ElMariachiNum', 'charges per Mariachi pickup'), ('PinataNum', 'charges per Pinata pickup'),
               ('TequillaNum', 'charges per Tequila pickup'), ('SmallOverallBonus', 'score of goodie 20'),
               ('LargeOverallBonus', 'score of goodie 21')):
    DATA['goodies.%s' % _p] = (GOOD, GD, _p, None, _n + ' (a grant that would exceed the slot maximum is rejected whole)'
                               if _p.endswith('Num') else _n)
for _p in ('AddRewinds', 'AddGoldenBullets', 'AddLocoMoves', 'AddRamMoves', 'AddMedkits', 'AddSombreros', 'AddTimeStops',
           'AddMexWrestlers', 'AddElMariachis', 'AddPinatas'):
    DATA['cheat.%s' % _p] = (ESS, CH, _p, None, 'cheat grant (master_control_cheat_ctrl)')

# ------------------------------------------------------------------------------------------- code tunables
# name: (vanilla, [(va, kind, opoff)], note).  Addresses: docs/subsystem_loco_slowmo.md section 9.2.
CODE = {
    # automatic slow motion (dives, wall moves, slide wire): master_control_time_ctrl 0x785170 / 0x784820
    'slowmo.dive_scale': (0.11, [(0x7848A8, 'memf', 4)],
                          'side / forward dive (MoveState 0x24): time scale = WorldTime x this'),
    'slowmo.wallbounce_scale': (0.07, [(0x78489E, 'memf', 4)], 'MoveState 0x24 while Combo_Ctrl.IsDoingWallBounce'),
    'slowmo.other_scale': (0.1375, [(0x7848DF, 'memf', 4)],
                           'back / diagonal dives (MoveState 29/31/32), slide wire (17), other states'),
    'slowmo.ramp_in': (0.2, [(0x784921, 'memf', 4)], 'seconds (real) to ramp into automatic slow motion'),
    'slowmo.ramp_out': (0.1, [(0x7851F8, 'memf', 4)], 'seconds (real) back to normal when the watcher (re)starts'),
    'slowmo.wire_see_angle': (120.0, [(0x785368, 'memf', 4)], 'slide wire: enemies must be visible in this cone (deg)'),
    'slowmo.wire_see_range': (25.0, [(0x785387, 'memf', 4)], 'slide wire: ... and within this range (m)'),
    'slowmo.hear_range': (20.0, [(0x7853ED, 'memf', 4)], 'dives etc.: an enemy must be within this hearing range (m)'),
    'slowmo.start_stamina': (50.0, [(0x78546F, 'memf', 4)], 'stamina that must be available to start slow motion'),
    'slowmo.keep_stamina': (1.0, [(0x784A24, 'memf', 4)], 'stamina requested every frame to stay in slow motion'),
    'slowmo.bullet_threshold': (0.5, [(0x7842F1, 'memf', 4), (0x784320, 'memf', 3), (0x78433B, 'memf', 4)],
                                'time scale where bullets swap to the slow-motion model and the blur changes'),
    'slowmo.blur_fade': (0.1, [(0x784432, 'memf', 4), (0x784584, 'memf', 4)], 'Set_Motionblur fade time (s)'),
    'time.force_normal_ramp': (0.1, [(0x78560C, 'memf', 4)], 'force_normal_time in auto mode: seconds back to normal'),
    'time.trigger_realtime_ramp': (0.1, [(0x784EB6, 'memf', 4)], 'command_trigger_realtime: seconds back to normal'),
    'explosion.scale': (0.01, [(0x78502E, 'memf', 4)], 'explosion time freeze: time scale'),
    'explosion.ramp_in': (0.15, [(0x785057, 'memf', 4)], 'explosion freeze: seconds (real) to the low point'),
    'explosion.ramp_out': (1.15, [(0x7850F8, 'memf', 4)], 'explosion freeze: seconds (real) back to normal'),
    # Tornado (slot 3, Combat_Move_ctrl state 0x5342C0)
    'tornado.time_scale': (0.01, [(0x535165, 'memf', 4)], 'world time scale during the Tornado'),
    'tornado.time_ramp': (0.3, [(0x53518A, 'memf', 4)], 'seconds (real) to reach it'),
    'tornado.start_wait': (0.3, [(0x535201, 'memf', 4)], 'real-time wait before the spin starts'),
    'tornado.anim_mult_start': (100.0, [(0x535252, 'memf', 4)], 'animation-layer speed multiplier at the start (compensates 0.01)'),
    'tornado.anim_mult_fire': (25.0, [(0x527026, 'memf', 4), (0x527056, 'immf', 1)], 'layer multiplier from the event_shoot_start marker'),
    'tornado.radius': (30.0, [(0x5347D3, 'memf', 4)], 'target query radius (m)'),
    'tornado.damage': (300.0, [(0x538065, 'memf', 4)], 'take_a_hit damage per target'),
    'tornado.target_interval': (0.66, [(0x5384B6, 'memf', 4)], 'real seconds between targets'),
    # Time Stop (slot 7, 0x5C0420) - unreachable with the shipped maximum 0
    'timestop.world_time': (0.01, [(0x5C049C, 'memf', 4)], 'WorldTime during Time Stop'),
    'timestop.duration': (15.0, [(0x5C0486, 'memf', 4)], 'seconds (real)'),
    'timestop.player_factor': (100.0, [(0x5C047A, 'memf', 4)], "player layer multiplier = PLAYER_SPEED_MULT x this"),
    # Mariachi, El Toro, HUD, buddies
    'mariachi.duration': (15.0, [(0x5BF7E5, 'memf', 4)], 'seconds (game) of the guitar-case gun; god mode for the same time'),
    'powerup.hud_effect_time': (60.0, [(0x5BF390, 'memf', 4), (0x5C0FA8, 'memf', 4)], 'HUD power-up effect length passed to start_effect'),
    'ram.god_time': (20.0, [(0x5268AF, 'memf', 4)], 'El Toro: seconds of god mode'),
    'ram.countdown': (20.0, [(0x52580D, 'memf', 4)], 'El Toro: HUD countdown (s)'),
    'ram.fov_mid': (69.0, [(0x52564E, 'memf', 4), (0x525903, 'memf', 3)], 'El Toro: first fov step (set, and the check before the second)'),
    'ram.fov_wide': (104.0, [(0x525910, 'memf', 4)], 'El Toro: wide fov after 1 s'),
    'ram.cam_blend': (0.25, [(0x5255BE, 'memf', 4)], 'El Toro: camera transition times (s)'),
    'ram.cam_blend_b': (0.5, [(0x5255F4, 'memf', 4)], 'El Toro: camera transition time 3 (s)'),
    'ram.cam_speed_a': (8.0, [(0x525698, 'memf', 4)], 'El Toro: camera move_speed 1 and 3'),
    'ram.cam_speed_b': (10.0, [(0x5256A0, 'memf', 4)], 'El Toro: camera move_speed 2'),
    'ram.blur_factor': (0.75, [(0x52571F, 'memf', 4)], 'El Toro: motion blur = slomo_motion_blur x this'),
    'buddy.lifetime': (25.0, [(0x5BE6C4, 'memf', 4)], 'Wrestler / Crazy Mexican buddy: seconds before it is removed'),
    'buddy.scan_first': (2.5, [(0x5BE755, 'memf', 4)], 'buddy: first enemy scan after (s)'),
    'buddy.scan_radius_first': (20.0, [(0x5BE7AB, 'memf', 4)], 'buddy: first scan radius (m)'),
    'buddy.scan_interval': (7.0, [(0x5BECA9, 'memf', 4)], 'buddy: later scans every (s)'),
    'buddy.scan_radius': (30.0, [(0x5BECE0, 'memf', 4)], 'buddy: later scan radius (m)'),
    # golden bullet camera (weapon_effects_ctrl 0x83D670)
    'golden.cam_time_scale': (0.01, [(0x83E73D, 'memf', 4)], 'golden bullet camera: time scale and its ramp (both args)'),
    'golden.cam_restore_ramp': (0.01, [(0x83F10D, 'memf', 4)], 'golden bullet camera: ramp back to 1.0'),
    'golden.cam_time': (0.5, [(0x83D6C6, 'memf', 4)], 'golden bullet camera: seconds (real) on the bullet'),
    # rewind (master_control_realtime_input_ctrl 0x759DC0)
    'rewind.max_seconds': (8.0, [(0x759F2E, 'memf', 4)], 'longest rewind (s of recorded game time)'),
    'rewind.start_speed': (0.1, [(0x75A33B, 'memf', 4)], 'rewind playback multiplier at the start'),
    'rewind.speed_gain': (4.0, [(0x75A988, 'memf', 4), (0x75B020, 'memf', 4)], 'playback multiplier = elapsed x this'),
    'rewind.fov': (110.0, [(0x759E23, 'memf', 4)], 'camera fov during the rewind effect'),
    'rewind.god_time': (4.0, [(0x75B660, 'memf', 4)], 'seconds of invulnerability after a rewind (elder god mode)'),
    # player death (master_control_realtime_input_ctrl state 0x75BD00)
    'death.slowmo_with_rewind': (0.3, [(0x75BE18, 'memf', 4)], 'death slow motion when a rewind is available'),
    'death.slowmo_no_rewind': (0.6, [(0x75BE95, 'memf', 4)], 'death slow motion without a rewind'),
    'death.slowmo_ramp': (0.5, [(0x75BE31, 'memf', 4), (0x75BEAE, 'memf', 4)], 'death slow motion ramp (s, real)'),
    'death.rewind_window': (15.0, [(0x75CF98, 'memf', 4)], 'seconds (real) the rewind prompt waits for the rewind key'),
    # power-up selection menu (master_control_select_powerup_ctrl 0x781750)
    'menu.slow_floor': (0.2, [(0x781818, 'memf', 4)], 'power-up menu: first time scale step'),
    'menu.slow_ramp': (0.3, [(0x78187B, 'memf', 4)], 'power-up menu: seconds to it'),
    'menu.freeze_ramp': (0.2, [(0x781AB7, 'memf', 4)], 'power-up menu: seconds to full stop (0)'),
    'menu.pitch_fall_a': (1.3, [(0x781990, 'memf', 4)], 'menu: sound pitch factor falls this much per real second'),
    'menu.pitch_fall_b': (1.2, [(0x781B8E, 'memf', 4)], 'menu: second pitch fall rate'),
    'menu.exit_ramp': (0.1, [(0x781CD9, 'memf', 4), (0x7821F8, 'memf', 4)], 'menu: seconds back to the old time scale'),
}


# ------------------------------------------------------------------------------------------- exe access
class Exe:
    def __init__(self, path=EXE):
        self.path = path
        self.d = bytearray(open(path, 'rb').read())
        pe = struct.unpack_from('<I', self.d, 0x3C)[0]
        nsec = struct.unpack_from('<H', self.d, pe + 6)[0]
        opt = struct.unpack_from('<H', self.d, pe + 20)[0]
        self.base = struct.unpack_from('<I', self.d, pe + 24 + 28)[0]
        self.secs = []
        for i in range(nsec):
            o = pe + 24 + opt + 40 * i
            vs, va, rs, ro = struct.unpack_from('<IIII', self.d, o + 8)
            self.secs.append((self.base + va, vs, ro, rs))

    def off(self, va):
        for sva, vs, ro, rs in self.secs:
            if sva <= va < sva + max(vs, rs) and va - sva < rs:
                return ro + va - sva
        raise ValueError('va %x not in file' % va)

    def rd(self, va, n):
        o = self.off(va)
        return bytes(self.d[o:o + n])

    def wr(self, va, b):
        o = self.off(va)
        self.d[o:o + len(b)] = b

    def md5(self):
        return hashlib.md5(bytes(self.d)).hexdigest()


def site_value(exe, va, kind, opoff, pool=None):
    if kind == 'memf':
        a = struct.unpack('<I', exe.rd(va + opoff, 4))[0]
        if pool is not None and a in pool:
            return pool[a]
        return struct.unpack('<f', exe.rd(a, 4))[0]
    if kind == 'immf':
        return struct.unpack('<f', exe.rd(va + opoff, 4))[0]
    if kind == 'imm8':
        return exe.rd(va + opoff, 1)[0]
    if kind == 'imm32':
        return struct.unpack('<i', exe.rd(va + opoff, 4))[0]
    raise ValueError(kind)


def code_value(exe, name, pool=None):
    vals = [site_value(exe, va, k, o, pool) for va, k, o in CODE[name][1]]
    if any(abs(float(v) - float(vals[0])) > 1e-6 * max(1.0, abs(float(vals[0]))) for v in vals):
        raise ValueError('%s: sites disagree %s' % (name, vals))
    return vals[0]


def same(a, b):
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))


def shipped_ok(exe, name):
    van = CODE[name][0]
    return all(same(site_value(exe, va, k, o), van) for va, k, o in CODE[name][1])


def site_bytes(exe, va, kind, opoff):
    n = opoff + (1 if kind == 'imm8' else 4)
    return exe.rd(va, n).hex()


def simulate_proxy(exe, values):
    """apply code values to an in-memory exe the way the proxy does; returns (pool, undo)."""
    pool, undo, nxt = {}, [], 0x7F000000
    for name, v in values.items():
        if not shipped_ok(exe, name):
            raise ValueError('%s: shipped bytes differ from the table' % name)
        slot = nxt
        nxt += 4
        for va, kind, opoff in CODE[name][1]:
            if kind == 'memf':
                pool[slot] = struct.unpack('<f', struct.pack('<f', float(v)))[0]
                undo.append((va + opoff, exe.rd(va + opoff, 4)))
                exe.wr(va + opoff, struct.pack('<I', slot))
            elif kind == 'immf':
                undo.append((va + opoff, exe.rd(va + opoff, 4)))
                exe.wr(va + opoff, struct.pack('<f', float(v)))
            elif kind == 'imm8':
                if not 0 <= int(v) <= 255:
                    raise ValueError('%s: imm8 out of range' % name)
                undo.append((va + opoff, exe.rd(va + opoff, 1)))
                exe.wr(va + opoff, bytes([int(v)]))
            else:
                undo.append((va + opoff, exe.rd(va + opoff, 4)))
                exe.wr(va + opoff, struct.pack('<i', int(v)))
    return pool, undo


# ------------------------------------------------------------------------------------------- data access
class Main:
    def __init__(self, block=None, entry=None):
        self.raw, self.entry, self.ext = ft.load_block_bytes(block or MAIN, entry)
        self.load(self.raw)

    def load(self, raw):
        self.b = tb.Block(raw, self.ext)
        self.frs, _ = ft.fragments(self.b)
        self.T = ft.types()
        self.docs = {}

    def doc(self, frag):
        if frag not in self.docs:
            k, nm = ft.pick_fragment(self.frs, frag)
            self.docs[frag] = fe.FragDoc(self.b.payloads[k], self.T, nm)
        return self.docs[frag]


def dynamic_data(m):
    """per-entity tables: name -> (fragment, entity, property, default, note)"""
    out = {}
    d = m.doc(AWARD)
    for n in d.created_ids():
        ty = d.type_of(n) or ''
        nm = d.get(n, 'name')
        if ty.startswith('database_combo_award'):
            out['award.%s.KillsNeeded' % nm] = (AWARD, '0x%08X' % n, 'KillsNeeded', None, 'kills in one combo for this award')
            out['award.%s.ComboBonus' % nm] = (AWARD, '0x%08X' % n, 'ComboBonus', None, 'bonus points of the award')
        elif ty.startswith('database_goodie_ID'):
            par = d.get(d.get(n, 'parent') or 0, 'name')
            out['award.%s/%s.goodie' % (par, nm)] = (AWARD, '0x%08X' % n, 'Specific_ID', None,
                                                     'goodie id given (one child is chosen); see GOODIES')
    d = m.doc(MOVES)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_combo_type'):
            nm = d.get(n, 'name')
            for f in ('FirstAward', 'SecondAward', 'ThirdAward', 'FourthAward', 'FifthAward'):
                out['move.%s.%s' % (nm, f)] = (MOVES, '0x%08X' % n, f, None, 'points for the 1st..5th use of the move in a combo')
    d = m.doc(ESTATE)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_combo_enemy_state'):
            out['enemystate.%s.PointValue' % d.get(n, 'name')] = (ESTATE, '0x%08X' % n, 'PointValue', None, 'kill points by enemy state')
    d = m.doc(UNIQUE)
    seen = {}
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_unique_combo_move'):
            nm = d.get(n, 'name')
            seen[nm] = seen.get(nm, 0) + 1
            key = nm if seen[nm] == 1 else '%s#%d' % (nm, seen[nm])
            out['unique.%s.MoveBonus' % key] = (UNIQUE, '0x%08X' % n, 'MoveBonus', None, 'bonus points of the unique move')
            out['unique.%s.GoodieAward' % key] = (UNIQUE, '0x%08X' % n, 'GoodieAward', None,
                                                  'goodie id awarded when performed (-1 none; 0x623F20 -> award_combo_goodie)')
    return out


def all_data(m):
    d = dict(DATA)
    d.update(dynamic_data(m))
    return d


def data_values(m, table=None):
    table = table or all_data(m)
    out = {}
    for name, (frag, sel, prop, default, _) in table.items():
        d = m.doc(frag)
        n = d.find(sel)
        out[name] = d.get(n, prop)
    return out


def ptype(m, frag, sel, prop):
    return m.T.ptype(m.T.index(prop))


def coerce(m, spec, v):
    frag, sel, prop = spec[:3]
    t = ptype(m, frag, sel, prop)
    if t == 'integer':
        return int(v)
    if t == 'truth':
        return bool(v)
    return float(v)


# ------------------------------------------------------------------------------------------- commands
def fmt(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return '%.6g' % v
    return str(v)


def cmd_show(argv):
    m = Main()
    exe = Exe()
    print('block %s sha256 %s' % (m.entry, hashlib.sha256(m.raw).hexdigest()[:16]))
    print('exe %s md5 %s%s' % (exe.path, exe.md5(), '' if exe.md5() == EXE_MD5 else '  (NOT the GOG build)'))
    table = all_data(m) if '--all' in argv else DATA
    vals = data_values(m, table)
    print('\n# data (overdose.main fragments; written through loco_override.zip)')
    for name, (frag, sel, prop, default, note) in table.items():
        v = vals[name]
        vs = fmt(v) if v is not None else '(unset: %s)' % fmt(default)
        print('  %-44s %-12s %s %s.%s  %s' % (name, vs, frag.split('/')[-1].replace('.fragment', ''), sel, prop, note))
    if '--all' not in argv:
        print('  (+ %d per-award / per-move / unique-move values: show --all, or combos)' % (len(all_data(m)) - len(DATA)))
    print('\n# code (TOD.exe; written through loco_patch.json / locotune.ini by the locotune proxy or the recompile)')
    for name, (van, sites, note) in CODE.items():
        ok = shipped_ok(exe, name)
        v = code_value(exe, name) if ok else float('nan')
        print('  %-28s %-9s %s  %-28s %s' % (name, fmt(v), 'ok' if ok else 'BYTES DIFFER',
                                             ','.join('%06X' % s[0] for s in sites), note))
    return 0


def cmd_export(argv):
    m = Main()
    exe = Exe()
    dv = data_values(m)
    tab = all_data(m)
    out = dict(data={n: (v if v is not None else tab[n][3]) for n, v in dv.items()},
               code={n: code_value(exe, n) for n in CODE})
    json.dump(out, open(argv[2], 'w'), indent=1)
    print('wrote %s (%d data, %d code values)' % (argv[2], len(out['data']), len(out['code'])))
    return 0


def build(spec, outdir, verbose=True):
    os.makedirs(outdir, exist_ok=True)
    rep = dict(spec=spec, result='FAIL')
    data = spec.get('data', {}) or {}
    code = spec.get('code', {}) or {}
    for n in code:
        if n not in CODE:
            raise KeyError('unknown code tunable %s' % n)
    if data:
        m = Main(spec.get('block'), spec.get('entry'))
        tab = all_data(m)
        for n in data:
            if n not in tab:
                raise KeyError('unknown data tunable %s' % n)
        T = m.T
        r0 = ft.roundtrip_block(m.raw, m.ext, T)
        if r0['fail'] or not r0['block_identical']:
            raise RuntimeError('base block does not round-trip')
        ops = [dict(op='set', fragment=tab[n][0], entity=tab[n][1], prop=tab[n][2], value=coerce(m, tab[n], v))
               for n, v in data.items()]
        old, nb, docs, intended = ft.apply_ops(m.raw, m.ext, ops, T)
        newb = nb.serialize()
        ft.verify_block(old, newb, m.ext, docs, intended, T)
        m2 = Main.__new__(Main)
        m2.raw, m2.entry, m2.ext = newb, m.entry, m.ext
        m2.load(newb)
        back = data_values(m2, {n: tab[n] for n in data})
        bad = {n: (v, back[n]) for n, v in data.items() if not same(coerce(m, tab[n], v), back[n])}
        if bad:
            raise RuntimeError('read-back mismatch %s' % bad)
        open(os.path.join(outdir, os.path.basename(m.entry)), 'wb').write(newb)
        rep['zip'] = ft.write_zip(os.path.join(outdir, ZIP_NAME), [(m.entry, newb)])
        rep['block'] = dict(entry=m.entry, base_sha256=hashlib.sha256(m.raw).hexdigest(),
                            out_sha256=hashlib.sha256(newb).hexdigest(), identical_to_base=(newb == m.raw),
                            readback=back)
        json.dump({'description': spec.get('description', 'locotool data changes'),
                   'blocks': [{'block': MAIN, 'ops': ops}]}, open(os.path.join(outdir, 'frag_edit.json'), 'w'), indent=1)
        rep['configpc_line'] = 'filesystem = ' + ', '.join([ZIP_NAME] + ft.BASE_ARCHIVES)
    if code:
        exe = Exe()
        pristine = bytes(exe.d)
        pool, undo = simulate_proxy(exe, code)
        back = {n: code_value(exe, n, pool) for n in code}
        bad = {n: (v, back[n]) for n, v in code.items() if not same(v, back[n])}
        for va, b in reversed(undo):
            exe.wr(va, b)
        if bad or bytes(exe.d) != pristine:
            raise RuntimeError('code read-back mismatch %s or undo not identical' % bad)
        exe2 = Exe()
        entries = []
        for n, v in code.items():
            for va, kind, opoff in CODE[n][1]:
                entries.append(dict(name=n, va='0x%06X' % va, kind=kind, opoff=opoff,
                                    shipped_bytes=site_bytes(exe2, va, kind, opoff), vanilla=CODE[n][0], value=v))
        json.dump(dict(exe_md5=EXE_MD5, note='memf: point the 32-bit operand at va+opoff to a private float = value; '
                       'immf: write the float at va+opoff; imm8/imm32: write the integer. Check shipped_bytes first; '
                       'never change the shared constant.', patches=entries),
                  open(os.path.join(outdir, 'loco_patch.json'), 'w'), indent=1)
        with open(os.path.join(outdir, 'locotune.ini'), 'w', newline='\n') as f:
            f.write('# locotune.ini - written by tools/loco/locotool.py; put next to TOD.exe with the locotune dinput8.dll\n')
            for n, v in code.items():
                f.write('%s = %s    # vanilla %s: %s\n' % (n, fmt(v), fmt(CODE[n][0]), CODE[n][2]))
        rep['code_readback'] = back
    rep['result'] = 'PASS'
    json.dump(rep, open(os.path.join(outdir, 'build_report.json'), 'w'), indent=1, default=str)
    if verbose:
        print(json.dumps({k: rep[k] for k in rep if k in ('result', 'zip', 'configpc_line', 'code_readback')}, indent=1,
                         default=str))
    return rep


def cmd_build(argv):
    spec = json.load(open(argv[2]))
    out = argv[argv.index('--out') + 1]
    try:
        build(spec, out)
    except Exception as e:  # noqa: BLE001
        print('FAIL: %s' % e)
        return 1
    return 0


def combos(m):
    rows = dict(awards=[], moves=[], enemy_states=[], unique=[])
    d = m.doc(AWARD)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_combo_award'):
            kids = [c for c in d.children(n) if (d.type_of(c) or '').startswith('database_goodie_ID')]
            rows['awards'].append(dict(name=d.get(n, 'name'), KillsNeeded=d.get(n, 'KillsNeeded'),
                                       ComboBonus=d.get(n, 'ComboBonus'), AwardString=d.get(n, 'AwardString'),
                                       goodies=[(d.get(c, 'name'), d.get(c, 'Specific_ID')) for c in kids]))
    rows['awards'].sort(key=lambda r: r['KillsNeeded'] or 0)
    d = m.doc(MOVES)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_combo_type'):
            rows['moves'].append(dict(name=d.get(n, 'name'), id=d.get(n, 'Specific_ID'),
                                      points=[d.get(n, f) for f in ('FirstAward', 'SecondAward', 'ThirdAward', 'FourthAward', 'FifthAward')]))
    d = m.doc(ESTATE)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_combo_enemy_state'):
            rows['enemy_states'].append(dict(name=d.get(n, 'name'), id=d.get(n, 'Specific_ID'), points=d.get(n, 'PointValue')))
    d = m.doc(UNIQUE)
    for n in d.created_ids():
        if (d.type_of(n) or '').startswith('database_unique_combo_move'):
            subs = [d.get(c, 'name') for c in d.children(n)]
            rows['unique'].append(dict(name=d.get(n, 'name'), bonus=d.get(n, 'MoveBonus'), goodie=d.get(n, 'GoodieAward'),
                                       sound=d.get(n, 'MoveSound'), parts=subs))
    return rows


def cmd_combos(argv):
    m = Main()
    r = combos(m)
    print('# combo awards (HUD_combo_reaction_sign, kills in one combo -> one goodie of the list)')
    for a in r['awards']:
        print('  %3s kills  %-26s bonus %s  -> %s' % (a['KillsNeeded'], a['name'], a['ComboBonus'],
              ', '.join('%s(%s: %s)' % (g[0], g[1], GOODIES.get(g[1], '?')) for g in a['goodies'])))
    print('\n# combo moves (points for the 1st..5th use in one combo)')
    for a in r['moves']:
        print('  %-18s id %2s  %s' % (a['name'], a['id'], '/'.join(str(p) for p in a['points'])))
    print('\n# enemy states'); [print('  %-12s id %s  %s points' % (a['name'], a['id'], a['points'])) for a in r['enemy_states']]
    print('\n# unique combo moves')
    for a in r['unique']:
        print('  %-28s bonus %4s goodie %3s  %s' % (a['name'], a['bonus'], a['goodie'], ' + '.join(a['parts'])))
    if len(argv) > 2:
        json.dump(r, open(argv[2], 'w'), indent=1)
    return 0


CENSUS_TYPES = ('goodie_placeholder', 'Goodie_Default', 'Trigger_Activate_Loco_Move', 'Trigger_Activate_Combo',
                'Trigger_Activate_Overall_Score', 'Trigger_Activate_Camera')
CENSUS_PROPS = {'goodie_placeholder': ['GoodieSubType', 'Respawnable', 'RespawnTime', 'OneshotGoodieIndex'], 'Goodie_Default': ['Sub_Type', 'GoodieType'],
                'Trigger_Activate_Loco_Move': ['ActionType', 'TargetMove', 'RemoveFromInventory', 'Delay'],
                'Trigger_Activate_Combo': ['ActionType', 'BreakOffCounting', 'Delay'],
                'Trigger_Activate_Overall_Score': ['ActionType', 'Overall_Bonus'],
                'Trigger_Activate_Camera': ['ActionType', 'SlowMotionFraction', 'SlowMotionChangeTime', 'No_Blur_In_SlowMo', 'ActivationTime', 'TargetName']}


def cmd_census(argv):
    T = ft.types()
    arch = ft.archive()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS)
    rows, nfr = [], 0
    keys = [t.encode() for t in CENSUS_TYPES]
    for bn in names:
        raw = arch.read(bn)
        b = tb.Block(raw, os.path.splitext(bn)[1])
        frs, _ = ft.fragments(b)
        for k, nm in frs:
            p = b.payloads[k]
            if not any(x in p for x in keys):
                continue
            nfr += 1
            d = fe.FragDoc(p, T, nm)
            for n in d.created_ids():
                ty = d.type_of(n) or ''
                base = ty.split('(')[0]
                if base not in CENSUS_PROPS:
                    continue
                vals = {}
                for f in CENSUS_PROPS[base]:
                    try:
                        vals[f] = d.get(n, f)
                    except Exception:
                        vals[f] = None
                if base == 'Trigger_Activate_Camera' and vals.get('ActionType') not in (35, 36):
                    continue
                pos = d.get(n, 'pos')
                rows.append(dict(block=bn.split('/')[-1], fragment=nm.split('/')[-1], node='0x%08X' % n, type=base,
                                 name=d.get(n, 'name'), pos=pos, **vals))
    summ = {}
    for r in rows:
        if r['type'] == 'goodie_placeholder':
            key = 'goodie %02d %s' % (r.get('GoodieSubType') if r.get('GoodieSubType') is not None else -1, GOODIES.get(r.get('GoodieSubType'), '?'))
        elif r['type'] == 'Trigger_Activate_Camera':
            key = 'camera action %s' % r.get('ActionType')
        elif r['type'] == 'Trigger_Activate_Loco_Move':
            key = 'loco trigger action %s move %s' % (r.get('ActionType'), r.get('TargetMove'))
        else:
            key = '%s action %s' % (r['type'], r.get('ActionType'))
        summ[key] = summ.get(key, 0) + 1
    out = dict(blocks=len(names), fragments_scanned=nfr, entities=len(rows), summary=dict(sorted(summ.items())))
    print(json.dumps(out, indent=1))
    if '-o' in argv:
        path = argv[argv.index('-o') + 1]
        cols = ['block', 'fragment', 'node', 'type', 'name', 'pos'] + sorted({f for v in CENSUS_PROPS.values() for f in v})
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\t'.join(cols) + '\n')
            for r in rows:
                f.write('\t'.join('' if r.get(c) is None else (','.join('%.2f' % x for x in r[c]) if isinstance(r.get(c), list)
                                                               else str(r[c])) for c in cols) + '\n')
        json.dump(out, open(os.path.splitext(path)[0] + '_summary.json', 'w'), indent=1)
    return 0


def gen_proxy_header():
    lines = ['// locotune_sites.h - generated by tools/loco/locotool.py gen-proxy; do not edit by hand.',
             '// {name, vanilla, {{va, shipped bytes (hex), operand offset, kind}...}, n}', '']
    exe = Exe()
    for n, (van, sites, note) in CODE.items():
        ss = ','.join('{0x%08X,"%s",%d,%s}' % (va, site_bytes(exe, va, k, o), o, {'memf': 'MEMF', 'immf': 'IMMF',
                                                                                  'imm8': 'IMM8', 'imm32': 'IMM32'}[k])
                      for va, k, o in sites)
        lines.append(' {"%s", %sf, {%s}, %d},   // %s' % (n, repr(float(van)), ss, len(sites), note.replace('*/', '')))
    return '\n'.join(lines) + '\n'


def cmd_gen_proxy(argv):
    path = os.path.join(argv[2], 'locotune_sites.h')
    open(path, 'w', newline='\n').write(gen_proxy_header())
    print('wrote %s (%d tunables, %d sites)' % (path, len(CODE), sum(len(v[1]) for v in CODE.values())))
    return 0


def perturb(v, t):
    if t == 'truth':
        return not v
    if t == 'integer':
        return (v or 0) + 3
    return (v or 0.0) * 1.5 + 0.25


def cmd_selftest(argv):
    import tempfile
    ok = True
    m = Main()
    T = m.T
    r0 = ft.roundtrip_block(m.raw, m.ext, T)
    print('1 block round trip: %d fragments, %d records, failures %d, block identical %s' % (
        r0['fragments'], r0['records'], len(r0['fail']), r0['block_identical']))
    ok &= r0['block_identical'] and not r0['fail']
    tab = all_data(m)
    vals = data_values(m, tab)
    setv = {n: v for n, v in vals.items() if v is not None}
    unset = [n for n, v in vals.items() if v is None]
    # 2: every set value re-encodes to its own bytes
    bad = 0
    for n in setv:
        frag, sel, prop = tab[n][:3]
        d = m.doc(frag)
        node = d.find(sel)
        pi = T.index(prop)
        recs = [r for r in d.sets_of(node) if r.prop == pi]
        t = T.parse(T.ptype(pi))
        for r in recs:
            if tf.encode_value(tf.decode_value(r.raw, 0, t), t) != r.raw:
                bad += 1
    print('2 data values: %d set (%d static, %d per-entity), %d unset; re-encode identical %d/%d' % (
        len(setv), len([n for n in setv if n in DATA]), len([n for n in setv if n not in DATA]), len(unset),
        len(setv) - bad, len(setv)))
    ok &= bad == 0
    # 3: change every set value at once, verify the block, read back; then write the originals back -> identical bytes
    ops = [dict(op='set', fragment=tab[n][0], entity=tab[n][1], prop=tab[n][2],
                value=coerce(m, tab[n], perturb(v, ptype(m, *tab[n][:3])))) for n, v in setv.items()]
    old, nb, docs, intended = ft.apply_ops(m.raw, m.ext, ops, T)
    newb = nb.serialize()
    ft.verify_block(old, newb, m.ext, docs, intended, T)
    m2 = Main.__new__(Main)
    m2.raw, m2.entry, m2.ext = newb, m.entry, m.ext
    m2.load(newb)
    back = data_values(m2, {n: tab[n] for n in setv})
    good = sum(1 for o in ops for n in [None] if True)  # placeholder count
    good = 0
    for o, (n, v) in zip(ops, setv.items()):
        if same(o['value'], back[n]):
            good += 1
    ops2 = [dict(op='set', fragment=tab[n][0], entity=tab[n][1], prop=tab[n][2], value=v) for n, v in setv.items()]
    old2, nb2, docs2, intended2 = ft.apply_ops(newb, m.ext, ops2, T)
    restored = nb2.serialize()
    print('3 data write/read-back: %d/%d changed values read back; block differs %s; originals written back -> '
          'byte-identical %s' % (good, len(ops), newb != m.raw, restored == m.raw))
    ok &= good == len(ops) and newb != m.raw and restored == m.raw
    # 4: an unset value can be added (registration default case) and reads back
    if unset:
        n = unset[0]
        v = coerce(m, tab[n], 1)
        old3, nb3, docs3, int3 = ft.apply_ops(m.raw, m.ext, [dict(op='set', fragment=tab[n][0], entity=tab[n][1],
                                                                  prop=tab[n][2], value=v)], T)
        b3 = nb3.serialize()
        ft.verify_block(old3, b3, m.ext, docs3, int3, T)
        m3 = Main.__new__(Main)
        m3.raw, m3.entry, m3.ext = b3, m.entry, m.ext
        m3.load(b3)
        got = data_values(m3, {n: tab[n]})[n]
        print('4 unset value %s added as a new record: reads back %s (%s)' % (n, got, same(got, v)))
        ok &= same(got, v)
    # 5: code table matches the shipped exe; every site patched and read back; undo -> identical
    exe = Exe()
    md5ok = exe.md5() == EXE_MD5
    shipped = sum(1 for n in CODE if shipped_ok(exe, n))
    print('5 code: exe md5 %s (%s); %d/%d tunables (%d sites) hold their vanilla values' % (
        exe.md5(), 'GOG build' if md5ok else 'NOT the GOG build', shipped, len(CODE), sum(len(v[1]) for v in CODE.values())))
    ok &= md5ok and shipped == len(CODE)
    pristine = bytes(exe.d)
    newv = {n: (CODE[n][0] * 1.5 + 0.125) for n in CODE}
    pool, undo = simulate_proxy(exe, newv)
    backc = {n: code_value(exe, n, pool) for n in CODE}
    cgood = sum(1 for n in CODE if same(newv[n], backc[n]))
    for va, b in reversed(undo):
        exe.wr(va, b)
    print('6 code round trip: %d/%d patched values read back; undo -> exe bytes identical %s' % (
        cgood, len(CODE), bytes(exe.d) == pristine))
    ok &= cgood == len(CODE) and bytes(exe.d) == pristine
    # 7: example builds
    tmp = tempfile.mkdtemp(prefix='locotool_')
    ex = os.path.join(HERE, 'edits')
    built = []
    if os.path.isdir(ex):
        for fn in sorted(os.listdir(ex)):
            if fn.endswith('.json'):
                rep = build(json.load(open(os.path.join(ex, fn))), os.path.join(tmp, fn[:-5]), verbose=False)
                built.append((fn, rep['result']))
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)            # the example packages are ~28 MB each
    print('7 example builds: %s' % (', '.join('%s %s' % b for b in built) or 'none'))
    ok &= all(r == 'PASS' for _, r in built)
    # 8: the proxy header in proxy/ matches this table
    hp = os.path.join(HERE, 'proxy', 'locotune_sites.h')
    if os.path.exists(hp):
        same_h = open(hp).read() == gen_proxy_header()
        print('8 proxy/locotune_sites.h matches the code table: %s' % same_h)
        ok &= same_h
    print('selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmds = {'show': cmd_show, 'export': cmd_export, 'build': cmd_build, 'combos': cmd_combos, 'census': cmd_census,
            'gen-proxy': cmd_gen_proxy, 'selftest': cmd_selftest}
    if argv[1] not in cmds:
        print('unknown command %s' % argv[1])
        return 2
    return cmds[argv[1]](argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
