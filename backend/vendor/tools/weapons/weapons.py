"""Total Overdose weapons data (GOG build): read, tabulate, round-trip and write back every weapon value.

  python weapons.py table   [--block FILE --entry E] [--format md|tsv|json] [-o OUT]
  python weapons.py fields  [-o OUT]                 every editable field: fragment, entity, meaning, engine consumer
  python weapons.py roundtrip [--block FILE --entry E] byte-identical proof (parse/serialize, re-encode, write/restore)
  python weapons.py census  [-o OUT.tsv] [--blocks substr ...]   who carries which weapon (all weapon_placeholders)
  python weapons.py edit EDIT.json --out DIR [--deploy TESTGAME]   rebuild overdose.main + weapon_override.zip

Where the data lives: block overdose.main (blocks.naz entry data_pc/overdose_the_game/overdose/shared/overdose.main),
fragments WeaponDict, MountedWeaponDict and GameplayEssentials (PlayerStatusCtrl, BulletDrop, CheatCtrl) plus
GoodiesDict. Placed enemies pick a weapon through weapon_placeholder entities in mission/submap blocks (census).

EDIT.json (keys are optional):
{ "description": "...",
  "block": "overdose.main",                 or a block file on disk + "entry" (e.g. a clip_replace / TOD HD block)
  "weapons": { "Beretta": {"ClipSize": 25, "ReloadTime": 3.0, "ShortRangeDamage": 300} },
  "bullets": { "Beretta": {"speed": 140, "impulse_multiplier": 2.0} },
  "mounted": { "AntiAirChainGun": {"FireRate": 1200} },
  "player_status": { "Default_max_clips_Beretta": 9 },
  "bullet_drop": { "GunLight": 5, "VeryManyDropTo": 300 },
  "goodies": { "GoldenGunNum": 2 } }
Weapon selectors: the WeaponDict name (Gun_Light), the gun (Beretta) or the list index (0). Field names: the runtime
(effective) name, e.g. ClipSize, is converted to the authored *_m value (effective - parent database_weapon_type
value, all parents are 0 in the shipped data); an authored name (Clipsize_m) is written as given. MaxRange also
becomes the BulletManager's range at load (FUN_00658170), see `fields`.
The edit goes through the fragment writer (tools/fragment_writer/fragtool.py): every edit is verified (only the
requested records change, block header/INFO/other payloads identical, engine zip lookup) before anything is written.
Python 3.12, stdlib only. Runs at below-normal priority.
"""
import argparse, json, os, struct, sys, zipfile, hashlib
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.environ.get('TOD_FRAGWRITER', ''), os.path.join(HERE, '..', 'fragment_writer'),
             os.path.join(HERE, '..', 'fw')):
    if cand and os.path.exists(os.path.join(cand, 'fragtool.py')):
        sys.path.insert(0, os.path.abspath(cand))
        break
import fragtool as ft          # noqa: E402
import todfrag as tf           # noqa: E402
import todblock as tb          # noqa: E402
import fragedit as fe          # noqa: E402

MAIN = 'overdose.main'
F_WEAPON = '/data/Scripts/fragments/WeaponDict.fragment'
F_MOUNTED = '/data/Scripts/fragments/MountedWeaponDict.fragment'
F_ESSENT = '/data/Scripts/fragments/GameplayEssentials.fragment'
F_GOODIES = '/data/Scripts/fragments/GoodiesDict.fragment'
ZIP_NAME = 'weapon_override.zip'

# list index (Specific_ID) -> gun. Proven by FUN_006150E0 (MaxAmmoList[index] = Default_max_clips_<gun> x ClipSize),
# FUN_00647120 (DefaultDropType[index] = BulletDrop.<class>) and FUN_00612630 (Dual_<gun> by index).
GUNS = {0: 'Beretta', 1: 'Magnum', 2: 'Marlin', 3: 'Winchester', 4: 'Benelli', 5: 'Hudson', 6: 'Mac10', 7: 'MP5',
        8: 'AK47', 9: 'M16', 10: 'Gatling', 11: 'HandGrenade', 12: 'GrenadeLauncher', 13: 'RocketLauncher',
        14: 'Machete', 15: 'GoldenGun', 16: 'MariachiGuitar', 17: 'Pinata', 18: 'Molotov', 19: 'Dynamite'}
MAXCLIP_FIELD = {0: 'Beretta', 1: 'Magnum', 2: 'Marlin', 3: 'Winchester', 4: 'Benelli', 5: 'Hudson', 6: 'Mac10',
                 7: 'MP5', 8: 'AK47', 9: 'M16', 10: 'Gatling', 11: 'HandGrenade', 12: 'GrenadeLauncher',
                 13: 'RocketLauncher', 18: 'Molotov', 19: 'Dynamite'}
DEFCLIP_FIELD = {0: 'Beretta', 1: 'Magnum', 2: 'Marlin', 3: 'Winchester', 4: 'Benelli', 5: 'Hudson', 6: 'Mac10',
                 7: 'MP5', 8: 'AK47', 9: 'M16', 10: 'Gatlin', 11: 'HandGrenade', 12: 'GrenadeLauncher',
                 13: 'RocketLauncher', 14: 'machete'}
DROP_FIELD = {0: 'GunLight', 1: 'GunHeavy', 2: 'RifleHeavy', 3: 'RifleLight', 4: 'ShotgunCombat',
              5: 'ShotgunSawedOff', 6: 'SmgLight', 7: 'SmgHeavy', 8: 'AutomaticLight', 9: 'AutomaticHeavy',
              10: 'AutomaticSuper', 18: 'MolotovCocktail', 19: 'Dynamite', 11: 'HandGrenade', 12: 'GrenadeLauncher',
              13: 'RocketLauncher', 14: 'MeleeWeapons'}
DUAL_FIELD = {0: 'Dual_Beretta', 1: 'Dual_Magnum', 6: 'Dual_Mac10', 5: 'Dual_Shotgun', 3: 'Dual_Winchester',
              16: 'Dual_Mariachi_Guitar'}
DROP_BANDS = {1: ('VeryFewDropFrom', 'VeryFewDropTo'), 2: ('FewDropFrom', 'FewDropTo'),
              3: ('AverageDropFrom', 'AverageDropTo'), 4: ('ManyDropFrom', 'ManyDropTo'),
              5: ('VeryManyDropFrom', 'VeryManyDropTo')}
DROP_NAMES = {1: 'VeryFew', 2: 'Few', 3: 'Average', 4: 'Many', 5: 'VeryMany'}

# effective (runtime) field -> (authored subtype field, parent database_weapon_type field). FUN_00658170 adds them.
EFFECTIVE = {
    'speed': ('Speed_m', 'speed'), 'BulletsPerShot': ('BulletsPerShot_m', 'BulletsPerShot'),
    'ClipSize': ('Clipsize_m', 'ClipSize'), 'SpreadMin': ('SpreadMin_m', 'SpreadMin'),
    'SpreadMax': ('SpreadMax_m', 'SpreadMax'), 'SpreadInc': ('SpreadInc_m', 'SpreadInc'),
    'SpreadEnemy': ('SpreadEnemy_m', 'SpreadEnemy'), 'ReloadTime': ('ReloadTime_m', 'ReloadTime'),
    'AimFocus': ('AimFocus_m', 'AimFocus'), 'ShortRangeDamage': ('ShortRangeDamage_m', 'ShortRangeDamage'),
    'MediumRangeDamage': ('MediumRangeDamage_m', 'MediumRangeDamage'),
    'LongRangeDamage': ('LongRangeDamage_m', 'LongRangeDamage'), 'ShortRange': ('ShortRange_m', 'ShortRange'),
    'MediumRange': ('MediumRange_m', 'MediumRange'), 'LongRange': ('LongRange_m', 'LongRange'),
    'MaxRange': ('MaxRange_m', 'maxrange'), 'AimLowThreshold': ('AimLowThreshold_m', 'AimLowThreshold'),
    'AimHighThreshold': ('AimHighThreshold_m', 'AimHighThreshold'),
    'ManualFireRate': ('ManualFireRate_m', 'ManualFireRate'), 'FireRate': ('FireRate_m', 'FireRate'),
    'FlashRate': ('FlashRate_m', 'FlashRate'), 'FlashStayTime': ('FlashStayTime_m', 'FlashStayTime'),
    'ParticleRate': ('ParticleRate_m', 'ParticleRate'), 'ParticleStayTime': ('ParticleStayTime_m', 'ParticleStayTime'),
    'SoundRate': ('SoundRate_m', 'SoundRate'),
    'VisibleBulletPercentage': ('VisibleBulletPercentage_m', 'VisibleBulletPercentage'),
    'PointValue': ('PointValue_m', 'PointValue'), 'InflictorValue': ('InflictorValue_m', 'InflictorValue'),
    'PrimRangeThreshold': ('PrimRangeThreshold_m', 'PrimRangeThreshold'),
    'BackUpRangeThreshold': ('BackUpRangeThreshold_m', 'BackUpRangeThreshold')}
DIRECT = ['Specific_ID', 'priority', 'damage_type', 'BurstFire', 'Dual', 'AllowedOnWire', 'AllowedInForkLift',
          'AllowedInCar', 'AllowedOnBike', 'SecFireMode', 'ComboStringValue', 'MinBurstTime', 'MaxBurstTime',
          'MinPauseTime', 'MaxPauseTime', 'DefaultBackUpWeapon', 'DesiredRange', 'PopupText']

# field -> (meaning, engine consumer) ; GOG TOD.exe addresses (md5 d9beb351b3c78ee9f14a766a368f3ff9)
FIELD_INFO = {
    'ShortRangeDamage': ('damage of one bullet/pellet when the aim point is within ShortRange', 'FUN_00834840 picks the band from |TargetPos - weapon| at the shot; result -> weapon_effects CurrentDamage +0x74 -> shoot arg -> bullet +0x64 -> take_a_hit (0x8C9940)'),
    'MediumRangeDamage': ('damage within MediumRange', 'FUN_00834840'),
    'LongRangeDamage': ('damage within LongRange; beyond LongRange the damage is 0', 'FUN_00834840'),
    'ShortRange': ('band limit, metres (compared squared)', 'FUN_00834840'),
    'MediumRange': ('band limit, metres', 'FUN_00834840'),
    'LongRange': ('band limit, metres; also the AI engagement range', 'FUN_00834840'),
    'MaxRange': ('bullet travel limit, metres: written into the BulletManager range at load', 'FUN_00658170 (0x658769 set property range on the Bullet entity); bullet update 0x8C9440 subtracts |v|*dt from it'),
    'FireRate': ('automatic cadence, rounds per minute (fire loop period = 60/FireRate s)', 'FUN_006668B0 -> weapon_effects FireTime; fire loop 0x83A9C0 (CurrentFireTime += dt; shot when > FireTime)'),
    'ManualFireRate': ('tap cadence, rounds per minute (60/x s)', 'FUN_006668B0 -> weapon_effects ManualFireTime'),
    'BulletsPerShot': ('pellets per shot (shotguns 10); each pellet is a separate bullet with its own random spread and the full band damage', 'shoot handler FUN_008CA120 loop count'),
    'ClipSize': ('magazine size', 'FUN_00658170 (+0x2C); FUN_006668B0 Bullets/ClipSize; reload transfer FUN_00612740; MaxAmmoList = Default_max_clips x ClipSize (FUN_006150E0)'),
    'ReloadTime': ('reload duration in seconds (the reload animation is driven to it)', 'reload coroutine FUN_0061A6F0: ActionCtrl reload(number) 0x58E with ReloadTime, completion 0x58D'),
    'SpreadMin': ('player: spread (degrees) when the trigger is pressed', 'fire loop state 0 (0x83A9C0): CurrentSpread = SpreadMin'),
    'SpreadMax': ('player: spread cap, degrees', 'fire loop: clamp'),
    'SpreadInc': ('player: spread growth, degrees per second of holding the trigger', 'fire loop: CurrentSpread += SpreadInc * dt (player dt = real time x 0.95)'),
    'SpreadEnemy': ('AI owners: fixed spread, degrees (never grows)', 'fire loop state 0: owner != player -> CurrentSpread = SpreadEnemy'),
    'speed': ('subtype bullet speed (Speed_m). Not read by the bullet: the BulletManager speed is used', 'only FUN_00658170 copies it'),
    'AimFocus': ('copied to default_weapon +0x78; no reader found in the fire path', 'FUN_006668B0'),
    'AimLowThreshold': ('stored squared on the weapon (AimLowVal)', 'FUN_006668B0; consumer not traced'),
    'AimHighThreshold': ('stored squared (AimHighVal)', 'FUN_006668B0; consumer not traced'),
    'VisibleBulletPercentage': ('100 = every bullet drawn; NumInvisibleBullets = int(100 / x)', 'FUN_006668B0; fire loop draws one bullet mesh every N shots'),
    'FlashRate': ('muzzle flash cadence, per minute', 'FUN_006668B0 (60/x)'),
    'FlashStayTime': ('muzzle flash time, s', 'FUN_006668B0'),
    'ParticleRate': ('muzzle particle cadence, per minute (0 -> 0.1 s)', 'FUN_006668B0'),
    'ParticleStayTime': ('muzzle particle time, s', 'FUN_006668B0'),
    'SoundRate': ('fire sound cadence, per minute', 'FUN_006668B0'),
    'MinBurstTime': ('AI burst length min, s', 'default_weapon init FUN_006668B0 -> AI'),
    'MaxBurstTime': ('AI burst length max, s', 'FUN_006668B0'),
    'MinPauseTime': ('AI pause between bursts min, s', 'FUN_006668B0'),
    'MaxPauseTime': ('AI pause max, s', 'FUN_006668B0'),
    'Dual': ('capability: two of this gun can be held (player also needs PlayerStatus Dual_<gun>)', 'FUN_00612630, pickup FUN_00613040 (splits the loaded rounds half/half)'),
    'damage_type': ('0 bullet, 1 shell/explosive, 2 melee (DamageModDict class)', 'shoot arg -> bullet +0x60 -> take_a_hit damtype'),
    'BurstFire': ('weapon fires in bursts (AI)', 'FUN_006668B0'),
    'Specific_ID': ('list index (DB_WEAPONDICT_LIST key); never change', 'cache loader 0x719070'),
    'DefaultBackUpWeapon': ('AI backup weapon index', 'AI'),
    'PrimRangeThreshold': ('AI: switch to primary beyond this distance, m', 'AI'),
    'BackUpRangeThreshold': ('AI: switch to backup within this distance, m', 'AI'),
    'DesiredRange': ('AI desired range enum', 'AI'),
    'priority': ('weapon priority (best-weapon switch)', 'weapon switching'),
}
BULLET_INFO = {
    'speed': ('bullet speed, m/s (velocity = dir * speed * speed multiplier)', 'FUN_008CA120 reads Bullet +0x100'),
    'range': ('travel limit, m; OVERWRITTEN at load by the subtype MaxRange', 'Bullet +0x104; FUN_00658170'),
    'damage_type': ('BulletManager damage class (the shot passes the subtype damage_type)', '-'),
    'impulse_multiplier': ('scales the hit impulse (direction x this)', 'bullet update 0x8C961B (Bullet +0x10C)'),
}


def lowprio():
    try:
        import lowprio as _  # noqa: F401  (fragment_writer helper: below-normal priority)
    except Exception:
        pass


# --------------------------------------------------------------------------------------------- reading
class Main:
    """overdose.main (or a given block file) with the weapon fragments decoded."""

    def __init__(self, block=None, entry=None):
        self.raw, self.entry, self.ext = ft.load_block_bytes(block or MAIN, entry)
        self.b = tb.Block(self.raw, self.ext)
        self.frs, _ = ft.fragments(self.b)
        self.T = ft.types()
        self.docs = {}

    def doc(self, name):
        if name not in self.docs:
            k, nm = ft.pick_fragment(self.frs, name)
            self.docs[name] = (k, fe.FragDoc(self.b.payloads[k], self.T, nm))
        return self.docs[name][1]

    def props(self, d, n):
        out = {}
        for r in d.sets_of(n):
            out[self.T.name(r.prop)] = (r.prop, d.frag.value(r))
        return out

    def entities(self, d, typ):
        return [n for n in d.created_ids() if d.type_of(n) == typ]


def collect(m):
    d = m.doc(F_WEAPON)
    types = {n: m.props(d, n) for n in m.entities(d, 'database_weapon_type(NodeLogical)')}
    rows = []
    for n in m.entities(d, 'database_weapon_subtype(NodeLogical)'):
        p = m.props(d, n)
        par = d.get(n, 'parent') or 0
        pp = types.get(par, {})
        sid = p['Specific_ID'][1]
        row = dict(node='0x%08X' % n, name=d.get(n, 'name'), index=sid, gun=GUNS.get(sid, '?'),
                   weapon_class=pp.get('name', (0, ''))[1] if 'name' in pp else d.get(par, 'name'),
                   class_id=pp.get('Class', (0, None))[1], authored={}, parent={}, effective={})
        for k, (pid, v) in p.items():
            row['authored'][k] = v
        for eff, (am, pn) in EFFECTIVE.items():
            a = p.get(am, (0, 0))[1]
            b = pp.get(pn, (0, 0))[1]
            row['parent'][eff] = b
            row['effective'][eff] = (a or 0) + (b or 0)
        for k in DIRECT:
            if k in p:
                row['effective'][k] = p[k][1]
        # BulletManager child
        bm = [c for c in d.children(n) if d.type_of(c) == 'Bullet_Manager(Bullet)']
        if bm:
            bp = m.props(d, bm[0])
            row['bullet'] = dict(node='0x%08X' % bm[0], speed=bp.get('speed', (0, None))[1],
                                 range_authored=bp.get('range', (0, None))[1],
                                 range_runtime=row['effective']['MaxRange'] if sid not in (17,) and row['class_id'] != 6 else bp.get('range', (0, None))[1],
                                 damage_type=bp.get('damage_type', (0, None))[1],
                                 impulse_multiplier=bp.get('impulse_multiplier', (0, None))[1],
                                 model=bp.get('modelres', (0, None))[1])
        rows.append(row)
    rows.sort(key=lambda r: r['index'])
    # mounted weapons
    dm = m.doc(F_MOUNTED)
    mounted = []
    for n in m.entities(dm, 'database_mounted_weapon_type(NodeLogical)'):
        p = {k: v for k, (pid, v) in m.props(dm, n).items()}
        bm = [c for c in dm.children(n) if dm.type_of(c) == 'Bullet_Manager(Bullet)']
        bp = {k: v for k, (pid, v) in m.props(dm, bm[0]).items()} if bm else {}
        mounted.append(dict(node='0x%08X' % n, name=p.get('name'), values={k: v for k, v in p.items() if k not in fe_base()},
                            bullet=dict(speed=bp.get('speed'), range=bp.get('range'), impulse_multiplier=bp.get('impulse_multiplier'))))
    de = m.doc(F_ESSENT)
    ps = de.find({'name': 'PlayerStatusCtrl'})
    bd = de.find({'name': 'BulletDrop'})
    ch = de.find({'name': 'CheatCtrl'})
    psv = {k: v for k, (pid, v) in m.props(de, ps).items() if k not in fe_base()}
    bdv = {k: v for k, (pid, v) in m.props(de, bd).items() if k not in fe_base()}
    chv = {k: v for k, (pid, v) in m.props(de, ch).items() if k not in fe_base()}
    dg = m.doc(F_GOODIES)
    gd = m.entities(dg, 'database_goodie_type(Node)')
    gv = {k: v for k, (pid, v) in m.props(dg, gd[0]).items() if k not in fe_base()} if gd else {}
    # derived player-side numbers
    for r in rows:
        e = r['effective']
        i = r['index']
        der = {}
        fr, mr = e.get('FireRate') or 0, e.get('ManualFireRate') or 0
        der['auto_shot_interval_s'] = round(60.0 / fr, 4) if fr else None
        der['manual_shot_interval_s'] = round(60.0 / mr, 4) if mr else None
        pel = max(1, e.get('BulletsPerShot') or 0)
        der['damage_per_shot_short'] = (e.get('ShortRangeDamage') or 0) * pel
        der['dps_auto_short'] = round((e.get('ShortRangeDamage') or 0) * pel * fr / 60.0, 1) if fr else None
        clip = e.get('ClipSize') or 0
        der['magazine_empty_s_auto'] = round(clip * 60.0 / fr, 2) if fr and clip else None
        if e.get('SpreadInc'):
            der['spread_full_after_s'] = round(((e.get('SpreadMax') or 0) - (e.get('SpreadMin') or 0)) / e['SpreadInc'], 2)
        mc = psv.get('Default_max_clips_%s' % MAXCLIP_FIELD[i]) if i in MAXCLIP_FIELD else (1 if i in (14, 15, 16, 17) else None)
        der['max_clips'] = mc
        der['max_reserve'] = (1 if i in (14, 15, 16, 17) else mc * clip) if mc is not None else None
        dc = psv.get('Default_clips_%s' % DEFCLIP_FIELD[i]) if i in DEFCLIP_FIELD else None
        der['start_clips'] = dc
        if dc:
            der['start_loaded_reserve'] = [clip, (dc - 1) * clip]
        der['dual_unlocked_at_start'] = psv.get(DUAL_FIELD[i]) if i in DUAL_FIELD else None
        if i in DROP_FIELD:
            lvl = bdv.get(DROP_FIELD[i])
            mx = clip * (2 if i == 5 else 5 if i in (11, 12, 13, 17, 18, 19) else 1)
            lo, hi = DROP_BANDS.get(lvl, (None, None))
            der['drop_level'] = '%s (%s)' % (lvl, DROP_NAMES.get(lvl))
            der['max_bullets_to_drop'] = mx
            if lo:
                a, b = bdv[lo], bdv[hi]
                der['drop_rounds'] = [max(1, int(a * 0.01 * mx)), max(1, int(b * 0.01 * mx))]
        r['derived'] = der
    return dict(block=m.entry, block_sha256=hashlib.sha256(m.raw).hexdigest(), subtypes=rows, mounted=mounted,
                player_status=psv, bullet_drop=bdv, cheat_ctrl=chv, goodies=gv,
                weapon_types={('0x%08X' % n): {k: v for k, (pid, v) in t.items() if k not in fe_base()}
                              for n, t in {n: m.props(d, n) for n in m.entities(d, 'database_weapon_type(NodeLogical)')}.items()})


_BASE = None
def fe_base():
    global _BASE
    if _BASE is None:
        _BASE = {"script_priority", "order", "renderordergroup", "parent", "disable_on_cutscene", "flags", "pos",
                 "orient", "use_aux_quadtree", "lod_threshold", "fade_threshold", "slow_fade", "traverse_distance",
                 "unique_id0", "unique_id1", "UserType", "name"}
    return _BASE


def fmt(v):
    if isinstance(v, float):
        s = ('%.4f' % v).rstrip('0').rstrip('.')
        return s if s not in ('-0', '') else '0'
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if v is None:
        return '-'
    if isinstance(v, list):
        return '-'.join(fmt(x) for x in v)
    return str(v)


TABLE_COLS = [('index', 'idx'), ('gun', 'gun'), ('name', 'WeaponDict name'), ('weapon_class', 'class'),
              ('E:ShortRangeDamage', 'dmg S'), ('E:MediumRangeDamage', 'dmg M'), ('E:LongRangeDamage', 'dmg L'),
              ('E:ShortRange', 'S m'), ('E:MediumRange', 'M m'), ('E:LongRange', 'L m'), ('E:MaxRange', 'max m'),
              ('E:BulletsPerShot', 'pellets'), ('E:FireRate', 'rpm auto'), ('E:ManualFireRate', 'rpm tap'),
              ('E:ClipSize', 'clip'), ('E:ReloadTime', 'reload s'), ('E:SpreadMin', 'spread min'),
              ('E:SpreadMax', 'spread max'), ('E:SpreadInc', 'spread +/s'), ('E:SpreadEnemy', 'spread AI'),
              ('B:speed', 'bullet m/s'), ('E:damage_type', 'dmg type'), ('E:Dual', 'dual'),
              ('D:max_clips', 'max clips'), ('D:max_reserve', 'max reserve'), ('D:drop_level', 'drop level'),
              ('D:drop_rounds', 'drop rounds'), ('E:MinBurstTime', 'AI burst min'), ('E:MaxBurstTime', 'AI burst max'),
              ('E:MinPauseTime', 'AI pause min'), ('E:MaxPauseTime', 'AI pause max'),
              ('E:VisibleBulletPercentage', 'visible %'), ('D:dps_auto_short', 'DPS S (auto)')]


def cell(r, key):
    if key.startswith('E:'):
        return r['effective'].get(key[2:])
    if key.startswith('B:'):
        return (r.get('bullet') or {}).get(key[2:])
    if key.startswith('D:'):
        return r['derived'].get(key[2:])
    return r.get(key)


def cmd_table(a):
    m = Main(a.block, a.entry)
    data = collect(m)
    if a.format == 'json':
        text = json.dumps(data, indent=1, default=str)
    else:
        sep = '\t' if a.format == 'tsv' else ' | '
        lines = []
        hdr = [h for _, h in TABLE_COLS]
        if a.format == 'md':
            lines.append('| ' + ' | '.join(hdr) + ' |')
            lines.append('|' + '---|' * len(hdr))
        else:
            lines.append(sep.join(hdr))
        for r in data['subtypes']:
            vals = [fmt(cell(r, k)) for k, _ in TABLE_COLS]
            lines.append(('| ' + ' | '.join(vals) + ' |') if a.format == 'md' else sep.join(vals))
        if a.format == 'md':
            lines.append('')
            lines.append('Mounted weapons:')
            lines.append('')
            mk = ['speed', 'BulletsPerShot', 'SpreadMin', 'Health', 'damage_type', 'ShortRangeDamage',
                  'MediumRangeDamage', 'LongRangeDamage', 'ShortRange', 'MediumRange', 'LongRange', 'maxrange',
                  'FireRate', 'Min_Accel', 'Max_Accel', 'Accel_Inc', 'ShootAngle']
            lines.append('| name | ' + ' | '.join(mk) + ' | bullet speed | bullet range |')
            lines.append('|' + '---|' * (len(mk) + 3))
            for mw in data['mounted']:
                lines.append('| %s | %s | %s | %s |' % (mw['name'], ' | '.join(fmt(mw['values'].get(k)) for k in mk),
                                                        fmt(mw['bullet']['speed']), fmt(mw['bullet']['range'])))
        text = '\n'.join(lines) + '\n'
    if a.o:
        open(a.o, 'w', encoding='utf-8', newline='\n').write(text)
        print('wrote', a.o)
    else:
        sys.stdout.write(text)


def cmd_fields(a):
    lines = ['# Weapon fields: where each lives and what reads it (GOG TOD.exe addresses)', '',
             'WeaponDict.fragment (overdose.main), entity type database_weapon_subtype, one per weapon. Edit the',
             'effective name (the tool writes the authored *_m field = value - parent).', '',
             '| effective field | authored field | meaning | engine consumer |', '|---|---|---|---|']
    for eff, (am, pn) in EFFECTIVE.items():
        mi, co = FIELD_INFO.get(eff, ('', ''))
        lines.append('| %s | %s | %s | %s |' % (eff, am, mi, co))
    for k in DIRECT:
        mi, co = FIELD_INFO.get(k, ('', ''))
        lines.append('| %s | %s | %s | %s |' % (k, k, mi, co))
    lines += ['', 'BulletManager child of each subtype (Bullet_Manager(Bullet)):', '', '| field | meaning | consumer |',
              '|---|---|---|']
    for k, (mi, co) in BULLET_INFO.items():
        lines.append('| %s | %s | %s |' % (k, mi, co))
    text = '\n'.join(lines) + '\n'
    if a.o:
        open(a.o, 'w', encoding='utf-8', newline='\n').write(text)
        print('wrote', a.o)
    else:
        sys.stdout.write(text)


# --------------------------------------------------------------------------------------------- round trip
def weapon_value_records(m):
    """(fragment name, record) for every value the edit command can touch."""
    out = []
    d = m.doc(F_WEAPON)
    keep = set(DIRECT) | {am for am, _ in EFFECTIVE.values()} | {pn for _, pn in EFFECTIVE.values()} | \
        set(BULLET_INFO) | {'Class'}
    for n in d.created_ids():
        ty = d.type_of(n)
        if ty in ('database_weapon_subtype(NodeLogical)', 'database_weapon_type(NodeLogical)', 'Bullet_Manager(Bullet)'):
            for r in d.sets_of(n):
                if m.T.name(r.prop) in keep:
                    out.append((F_WEAPON, n, r))
    dm = m.doc(F_MOUNTED)
    for n in dm.created_ids():
        if dm.type_of(n) in ('database_mounted_weapon_type(NodeLogical)', 'Bullet_Manager(Bullet)'):
            for r in dm.sets_of(n):
                if m.T.name(r.prop) not in fe_base() and m.T.ptype(r.prop) in ('number', 'integer', 'truth'):
                    out.append((F_MOUNTED, n, r))
    de = m.doc(F_ESSENT)
    for nm in ('PlayerStatusCtrl', 'BulletDrop', 'CheatCtrl'):
        n = de.find({'name': nm})
        for r in de.sets_of(n):
            if m.T.name(r.prop) not in fe_base() and m.T.ptype(r.prop) in ('number', 'integer', 'truth'):
                out.append((F_ESSENT, n, r))
    dg = m.doc(F_GOODIES)
    for n in dg.created_ids():
        for r in dg.sets_of(n):
            if m.T.name(r.prop) not in fe_base() and m.T.ptype(r.prop) in ('number', 'integer', 'truth'):
                out.append((F_GOODIES, n, r))
    return out


def perturb(v, t):
    if t == 'truth':
        return not v
    if t == 'integer':
        return (v or 0) + 7
    return (v or 0.0) * 1.5 + 0.25


def cmd_roundtrip(a):
    lowprio()
    m = Main(a.block, a.entry)
    T = m.T
    rep = dict(block=m.entry, block_sha256=hashlib.sha256(m.raw).hexdigest())
    r0 = ft.roundtrip_block(m.raw, m.ext, T)
    rep['1_whole_block'] = dict(fragments=r0['fragments'], records=r0['records'], failures=len(r0['fail']),
                                block_identical=r0['block_identical'])
    recs = weapon_value_records(m)
    rep['2_values'] = len(recs)
    # 2: decode every value and encode it again
    bad = 0
    for fname, n, r in recs:
        t = T.parse(T.ptype(r.prop))
        if tf.encode_value(tf.decode_value(r.raw, 0, t), t) != r.raw:
            bad += 1
    rep['3_reencode_identical'] = len(recs) - bad
    # 3: write every value to a different value through the editor, check it reads back, then restore -> identical
    frags = sorted({f for f, _, _ in recs})
    changed_ok, restored = 0, {}
    for fname in frags:
        k, nm = ft.pick_fragment(m.frs, fname)
        orig = m.b.payloads[k]
        d = fe.FragDoc(orig, T, nm)
        mine = [(n, r) for f, n, r in recs if f == fname]
        olds = []
        for n, r in mine:
            old = d.frag.value(r)
            new = perturb(old, T.ptype(r.prop))
            d.set_prop(n, '#%d' % r.prop, new, note=False)
            olds.append((n, r.prop, old, new))
        p1 = d.payload()
        d2 = fe.FragDoc(p1, T, nm)
        for n, pid, old, new in olds:
            got = d2.get(n, '#%d' % pid)
            exp = tf.decode_value(tf.encode_value(new, T.parse(T.ptype(pid))), 0, T.parse(T.ptype(pid)))
            if got == exp:
                changed_ok += 1
        for n, pid, old, new in olds:
            d2.set_prop(n, '#%d' % pid, old, note=False)
        p2 = d2.payload()
        restored[nm.split('/')[-1]] = dict(values=len(mine), changed_bytes_differ=(p1 != orig), restored_identical=(p2 == orig),
                                           payload=len(orig))
    rep['4_write_readback'] = changed_ok
    rep['5_restore_identical'] = restored
    nb = tb.Block(m.raw, m.ext)
    rep['6_block_rebuild_identical'] = nb.serialize() == m.raw
    ok = (r0['block_identical'] and not r0['fail'] and bad == 0 and changed_ok == len(recs)
          and all(x['restored_identical'] and x['changed_bytes_differ'] for x in restored.values()))
    rep['result'] = 'PASS' if ok else 'FAIL'
    print(json.dumps(rep, indent=1))
    if a.o:
        json.dump(rep, open(a.o, 'w'), indent=1)
    return 0 if ok else 1


# --------------------------------------------------------------------------------------------- census
def cmd_census(a):
    lowprio()
    T = ft.types()
    arch = ft.archive()
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in tb.BLOCK_EXTS)
    if a.blocks:
        names = [n for n in names if any(s.lower() in n.lower() for s in a.blocks)]
    rows = []
    for bn in names:
        raw = arch.read(bn)
        b = tb.Block(raw, os.path.splitext(bn)[1])
        frs, _ = ft.fragments(b)
        for k, nm in frs:
            p = b.payloads[k]
            if b'WeaponPlaceHolder' not in p:
                continue
            d = fe.FragDoc(p, T, nm)
            kids = {}
            for c in d.created_ids():
                kids.setdefault(d.get(c, 'parent') or 0, []).append(c)
            for n in d.created_ids():
                ty = d.type_of(n) or ''
                if 'WeaponPlaceHolder' not in ty:
                    continue
                par = d.get(n, 'parent') or 0
                pty = d.type_of(par) if par else ''
                g = lambda prop, node=n: d.get(node, prop)
                # the enemy that carries it: the parent itself, or (usual layout, one folder per enemy holding
                # character_placeholder + weapon_placeholder(s) + GotoPath) the CharacterPlaceHolder sibling
                char = par if (pty and 'CharacterPlaceHolder' in pty) else None
                if char is None and par:
                    sib = [c for c in kids.get(par, []) if 'CharacterPlaceHolder' in (d.type_of(c) or '')]
                    char = sib[0] if sib else None
                row = dict(block=bn.split('/')[-1], fragment=nm.split('/')[-1], node='0x%08X' % n,
                           name=d.get(n, 'name'), WeaponSubType=g('WeaponSubType'),
                           MeleeWeaponSubType=g('MeleeWeaponSubType'), BulletDrop=g('BulletDrop'),
                           Respawnable=g('Respawnable'), RespawnTime=g('RespawnTime'),
                           parent_type=pty, parent_name=d.get(par, 'name') if par else '',
                           character=d.get(char, 'name') if char else '', on_character=char is not None)
                if char:
                    for f in ('Model', 'Use_AISubType_Data', 'AISubType', 'HeadShot_Damage', 'Health_modify',
                              'Damage_modify', 'FactionID', 'BackUpWeapon'):
                        try:
                            row[f] = d.get(char, f)
                        except KeyError:
                            row[f] = None
                rows.append(row)
    cols = ['block', 'fragment', 'node', 'name', 'WeaponSubType', 'gun', 'MeleeWeaponSubType', 'BulletDrop',
            'Respawnable', 'RespawnTime', 'parent_type', 'parent_name', 'character', 'Model', 'Use_AISubType_Data',
            'AISubType', 'HeadShot_Damage', 'Health_modify', 'Damage_modify', 'FactionID', 'BackUpWeapon']
    for r in rows:
        r['gun'] = GUNS.get(r['WeaponSubType'], '?') if r['WeaponSubType'] is not None else ''
    out = ['\t'.join(cols)] + ['\t'.join(fmt(r.get(c)) if r.get(c) is not None else '' for c in cols) for r in rows]
    if a.o:
        open(a.o, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    summ = {}
    for r in rows:
        key = r['gun'] or 'none'
        s = summ.setdefault(key, dict(placeholders=0, on_characters=0, standalone=0, respawnable=0, headshot_instant=0))
        s['placeholders'] += 1
        if r['on_character']:
            s['on_characters'] += 1
            if r.get('HeadShot_Damage') == 3:
                s['headshot_instant'] += 1
        else:
            s['standalone'] += 1
        if r['Respawnable']:
            s['respawnable'] += 1
    res = dict(blocks=len(names), weapon_placeholders=len(rows), by_gun=summ,
               bulletdrop_values=sorted({str(r['BulletDrop']) for r in rows}),
               headshot_values={str(h): sum(1 for r in rows if r.get('HeadShot_Damage') == h)
                                for h in sorted({r.get('HeadShot_Damage') for r in rows if 'HeadShot_Damage' in r},
                                                key=lambda x: (x is None, x))})
    print(json.dumps(res, indent=1))
    if a.o:
        json.dump(res, open(os.path.splitext(a.o)[0] + '_summary.json', 'w'), indent=1)


# --------------------------------------------------------------------------------------------- edit
def resolve_weapon(m, sel):
    d = m.doc(F_WEAPON)
    subs = m.entities(d, 'database_weapon_subtype(NodeLogical)')
    by = {}
    for n in subs:
        sid = d.get(n, 'Specific_ID')
        by[str(sid)] = n
        by[(d.get(n, 'name') or '').lower()] = n
        if sid in GUNS:
            by[GUNS[sid].lower()] = n
    key = str(sel).lower()
    if key not in by:
        raise ft.Fail('unknown weapon %r (use a WeaponDict name, a gun name or the index)' % sel)
    return by[key]


def prop_index(d, n, field, T):
    """Index of the property record the entity already carries (by name), else the table index."""
    for r in d.sets_of(n):
        if T.name(r.prop).lower() == field.lower():
            return r.prop
    return T.index(field)


def build_ops(m, spec):
    T = m.T
    ops, notes = [], []
    d = m.doc(F_WEAPON)
    for sel, fields in (spec.get('weapons') or {}).items():
        n = resolve_weapon(m, sel)
        par = d.get(n, 'parent') or 0
        for f, v in fields.items():
            if f in EFFECTIVE:
                am, pn = EFFECTIVE[f]
                pidx = prop_index(d, par, pn, T) if par else None
                pv = (d.get(par, '#%d' % pidx) if pidx is not None else 0) or 0
                val = v - pv
                notes.append('%s.%s = %s (writes %s = %s, parent %s = %s)' % (sel, f, v, am, val, pn, pv))
                f2 = am
            else:
                val, f2 = v, f
            pi = prop_index(d, n, f2, T)
            if T.ptype(pi) == 'integer':
                val = int(val)
            ops.append(dict(op='set', fragment=F_WEAPON, entity='0x%08X' % n, prop='#%d' % pi, value=val))
            if f in ('MaxRange', 'MaxRange_m'):
                notes.append('%s: MaxRange also becomes the BulletManager range at load (FUN_00658170)' % sel)
    for sel, fields in (spec.get('bullets') or {}).items():
        n = resolve_weapon(m, sel)
        bm = [c for c in d.children(n) if d.type_of(c) == 'Bullet_Manager(Bullet)']
        if not bm:
            raise ft.Fail('%s has no BulletManager' % sel)
        for f, v in fields.items():
            if f == 'range':
                notes.append('%s: BulletManager range is overwritten at load by MaxRange; edit weapons.%s.MaxRange' % (sel, sel))
            pi = prop_index(d, bm[0], f, T)
            ops.append(dict(op='set', fragment=F_WEAPON, entity='0x%08X' % bm[0], prop='#%d' % pi,
                            value=int(v) if T.ptype(pi) == 'integer' else v))
    dm = m.doc(F_MOUNTED)
    for sel, fields in (spec.get('mounted') or {}).items():
        n = dm.find({'name': sel})
        for f, v in fields.items():
            pi = prop_index(dm, n, f, T)
            ops.append(dict(op='set', fragment=F_MOUNTED, entity='0x%08X' % n, prop='#%d' % pi,
                            value=int(v) if T.ptype(pi) == 'integer' else v))
    de = m.doc(F_ESSENT)
    for key, ent in (('player_status', 'PlayerStatusCtrl'), ('bullet_drop', 'BulletDrop'), ('cheat_ctrl', 'CheatCtrl')):
        if spec.get(key):
            n = de.find({'name': ent})
            for f, v in spec[key].items():
                pi = prop_index(de, n, f, T)
                ty = T.ptype(pi)
                ops.append(dict(op='set', fragment=F_ESSENT, entity='0x%08X' % n, prop='#%d' % pi,
                                value=int(v) if ty == 'integer' else bool(v) if ty == 'truth' else v))
    if spec.get('goodies'):
        dg = m.doc(F_GOODIES)
        n = m.entities(dg, 'database_goodie_type(Node)')[0]
        for f, v in spec['goodies'].items():
            pi = prop_index(dg, n, f, T)
            ops.append(dict(op='set', fragment=F_GOODIES, entity='0x%08X' % n, prop='#%d' % pi, value=v))
    return ops, notes


def cmd_edit(a):
    lowprio()
    spec = json.load(open(a.edit))
    block = spec.get('block', MAIN)
    m = Main(block, spec.get('entry'))
    ops, notes = build_ops(m, spec)
    fspec = dict(description=spec.get('description', ''), blocks=[dict(block=block, ops=ops)])
    if spec.get('entry'):
        fspec['blocks'][0]['entry'] = spec['entry']
    os.makedirs(a.out, exist_ok=True)
    fe_path = os.path.join(a.out, 'fragtool_edit.json')
    json.dump(fspec, open(fe_path, 'w'), indent=1)
    ft.ZIP_NAME = ZIP_NAME
    ns = argparse.Namespace(edit=fe_path, out=a.out, deploy=a.deploy)
    rc = ft.cmd_edit(ns)
    rep = json.load(open(os.path.join(a.out, 'report.json')))
    # independent check: decode the rebuilt block with this tool and compare the requested effective values
    if rep.get('result') == 'PASS':
        outblk = rep['blocks'][0]['out']
        m2 = Main(outblk, rep['blocks'][0]['entry'])
        data2 = collect(m2)
        got = {}
        for sel, fields in (spec.get('weapons') or {}).items():
            n = resolve_weapon(m2, sel)
            row = [r for r in data2['subtypes'] if r['node'] == '0x%08X' % n][0]
            for f, v in fields.items():
                gv = row['effective'].get(f, row['authored'].get(f))
                got['%s.%s' % (sel, f)] = dict(want=v, got=gv, ok=abs((gv or 0) - v) < 1e-4 if isinstance(v, (int, float)) and not isinstance(v, bool) else gv == v)
        for sel, fields in (spec.get('bullets') or {}).items():
            n = resolve_weapon(m2, sel)
            row = [r for r in data2['subtypes'] if r['node'] == '0x%08X' % n][0]
            for f, v in fields.items():
                gv = (row.get('bullet') or {}).get('range_authored' if f == 'range' else f)
                got['bullets.%s.%s' % (sel, f)] = dict(want=v, got=gv, ok=gv is not None and abs(gv - v) < 1e-4)
        for key, table in (('player_status', 'player_status'), ('bullet_drop', 'bullet_drop'),
                           ('cheat_ctrl', 'cheat_ctrl'), ('goodies', 'goodies')):
            for f, v in (spec.get(key) or {}).items():
                gv = data2[table].get(f)
                ok = (gv == v) if isinstance(v, bool) or isinstance(gv, bool) else (gv is not None and abs(gv - v) < 1e-4)
                got['%s.%s' % (key, f)] = dict(want=v, got=gv, ok=ok)
        rep['readback'] = got
        rep['notes'] = notes
        rep['readback_ok'] = all(x['ok'] for x in got.values())
        json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, default=str)
        print(json.dumps(dict(readback=got, notes=notes), indent=1, default=str))
        if not rep['readback_ok']:
            return 1
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('table'); p.add_argument('--block'); p.add_argument('--entry')
    p.add_argument('--format', default='md', choices=['md', 'tsv', 'json']); p.add_argument('-o')
    p = sp.add_parser('fields'); p.add_argument('-o')
    p = sp.add_parser('roundtrip'); p.add_argument('--block'); p.add_argument('--entry'); p.add_argument('-o')
    p = sp.add_parser('census'); p.add_argument('-o'); p.add_argument('--blocks', nargs='*')
    p = sp.add_parser('edit'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    a = ap.parse_args()
    try:
        return {'table': cmd_table, 'fields': cmd_fields, 'roundtrip': cmd_roundtrip, 'census': cmd_census,
                'edit': cmd_edit}[a.cmd](a) or 0
    except ft.Fail as e:
        print('FAIL:', e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
