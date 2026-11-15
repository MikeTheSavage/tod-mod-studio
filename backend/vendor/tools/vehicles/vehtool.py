"""Vehicle data of Total Overdose (GOG build): read every tunable, write changes back as a verified override zip.

Where the data lives (docs/subsystem_vehicles.md section 3):
  type.<Type>.<prop>      the 29 database_vehicle_type rows of VehicleDict.fragment (overdose.main), list index =
                          Specific_ID; copied into the car at reset (car_move_ctrl 0x4E94C0, vehicle_ai 0x808480).
                          <prop> "pos"/"orient" = the vehicle camera position of that type.
  car.<prop>              car_move_ctrl "MoveCtrl" of VehicleSedan.fragment (overdose.main), the shell every 4-wheel
                          vehicle uses. Members not set in the fragment run on their registration default (code);
                          setting one here adds the property record (engine force, steering rate, ...).
  car.cam.<prop>          the shell's camera_system "CameraCtrl" (overwritten at reset by the type's values).
  bike.<prop>             car_move_ctrl "MoveCtrl" of VehicleDirtBike.fragment, one copy in each of 7 mission blocks;
                          an edit is written to all 7.
  traffic.<prop>          trafficsystem_admin "MasterCtrlAux/TrafficAdminCtrl" (GameplayEssentials.fragment).
  res.vehicle.<prop>, res.traffic.<prop>  the vehicle / traffic resource controllers (pool sizes, radii).
  camdict.VehicleDefaultCam.<prop>, status.<prop>, physic.<Name>.Mass, lod.<prop>   see show.

usage (Python 3.12; set MSYS_NO_PATHCONV=1 under Git Bash):
  vehtool.py show [--group G] [--derived]       every tunable with its value and where it lives (+ model numbers)
  vehtool.py export out.json                    all current values as an editable JSON
  vehtool.py build edit.json --out DIR          {"set": {name: value, ...}} -> DIR/frag_override.zip + report;
                                                every value is read back from the rebuilt blocks
  vehtool.py roundtrip                          every vehicle block round-trips; every value written back unchanged
                                                -> blocks byte-identical; every value changed, read back, restored
  vehtool.py selftest                           roundtrip + proposal build + read back
  vehtool.py sim TYPE [name=value ...]          driving-model numbers for one type (vehsim.py), optional changes

Block source: C:/GOG Games/Total Overdose/blocks.naz (read only) or TOD_NAZ. The fragment writer modules are looked
up in ../fragment_writer or FW_DIR. Nothing is written outside --out.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.environ.get('FW_DIR') or os.path.join(os.path.dirname(HERE), 'fragment_writer')
if not os.path.exists(os.path.join(FW, 'fragtool.py')):
    FW = os.path.join(HERE, 'fw')
sys.path.insert(0, FW)
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import fragtool as ft          # noqa: E402
import fragedit as fe          # noqa: E402
import todblock as tb          # noqa: E402
import vehsim                  # noqa: E402

MAIN = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
VDICT = '/data/Scripts/fragments/VehicleDict.fragment'
SEDAN = '/data/Scripts/fragments/VehicleSedan.fragment'
BIKE = '/data/scripts/fragments/VehicleDirtBike.fragment'
ESS = '/data/Scripts/fragments/GameplayEssentials.fragment'
CAMDICT = '/data/Scripts/fragments/CameraDict.fragment'
PHYS = '/data/Scripts/fragments/PhysicDict.fragment'
BIKE_BLOCKS = ['gameover_intermission', 'intermission_after_breakintosafe', 'intermission_after_bridge',
               'intermission_after_elvez', 'intermission_after_jungle', 'mm120_runawaytrain', 'subm_07_indu_mulral01_race']
BIKE_ENTRIES = ['data_pc/overdose_the_game/overdose/shared/%s.mission' % b for b in BIKE_BLOCKS]

TYPE_NAMES = ['4x4Pickup', 'BigTruck', 'BigTruckFlatnose', 'BigTruckMoralez', 'BurritoCart', 'Bus', 'Chopper',
              'Conquistador', 'Cranetruck', 'Dirtbike', 'ElCamino', 'Forklift', 'MilitaryTruck', 'ModernSedan',
              'Pickup_Truck', 'Sedan', 'StationWagon', 'Tractor', 'VanHeavy', 'VanUrban', '57Pickup', 'Door_Left_Front',
              'Truck', 'AITest', 'Pickup', 'PoliceCar', 'SedanRusty', 'Taxi', 'VanAngel']
TYPE_PROPS = ['pos', 'orient', 'Specific_ID', 'Engine_SoundID', 'Health', 'CollisionDamage', 'ExplosionDamage',
              'ExplosionRange', 'Player_Flee_time', 'spring_k', 'spring_damping', 'stiffness', 'drag_coeff', 'Mass',
              'cornering_stiffness', 'lateral_slide_speed', 'front_slide_factor', 'brake_slide_factor',
              'brake_front_slide_factor', 'slide_factor', 'control_speed', 'crash_angular_friction',
              'crash_linear_friction', 'spinning_linear_friction', 'spinning_angular_friction', 'handbrake_boost',
              'time_to_slide_factor', 'collision_mass', 'BrakeForce', 'PointValue', 'InflictorValue', 'ComboStringValue',
              'Inertial_Length', 'Inertial_Width', 'Inertial_Height', 'WheelRadius', 'MaxAngle', 'AngleEaseInSpeed',
              'MaxDistance', 'DistanceMoveOutSpeed', 'DistanceMoveInSpeed', 'DistanceZFactor', 'Vehicle_Length',
              'Vehicle_Width', 'Shadow_opacity']
TYPE_NOTES = {
    'pos': 'camera position relative to the car (m)', 'orient': 'camera orientation (quaternion x,y,z,w)',
    'Specific_ID': 'list index; placeholders select it as VehicleSubType - never change',
    'Health': 'vehicle_ai Health: destroyed when DamageTaken >= Health (x placeholder Health_modify)',
    'CollisionDamage': 'copied to vehicle_ai (+0xC0); consumer not traced', 'ExplosionDamage': 'damage of the final explosion',
    'ExplosionRange': 'explosion radius (m)', 'Player_Flee_time': 'x100 -> vehicle_ai my_Player_Flee_time',
    'spring_k': 'visual suspension spring (native UpdateSuspension 0x92C510)', 'spring_damping': 'visual suspension damping',
    'stiffness': 'visual suspension travel clamp = stiffness*0.1 m', 'drag_coeff': 'c in F - c|v|v - r v: sets top speed',
    'Mass': 'drive inertia (a = F / Mass); collisions use collision_mass', 'cornering_stiffness': 'steer x (1 - cs v/vmax): high = no steering at speed',
    'lateral_slide_speed': 'min speed (m/s) for a slide and for the handbrake spin', 'front_slide_factor': 'front follows the rear slide x this',
    'brake_slide_factor': 'cap of the brake-slide multiplier', 'brake_front_slide_factor': 'front slide share in a brake slide',
    'slide_factor': 'cap of the slide multiplier; spin-out when counter >= 2*slide_factor*time_to_slide_factor',
    'control_speed': 'slide counter rate (x0.01/step), clamped at reset', 'crash_angular_friction': 'angular friction after a crash (out of control)',
    'crash_linear_friction': 'linear friction after a crash', 'spinning_linear_friction': 'linear friction while spinning (player car)',
    'spinning_angular_friction': 'angular friction while spinning', 'handbrake_boost': 'handbrake spin boost (x2) under 2 m/s',
    'time_to_slide_factor': 'spin-out threshold factor (see slide_factor)', 'collision_mass': 'RigidBody coll_mass (0 -> 10)',
    'BrakeForce': 'brakepower (N) for V; S brakes with 1/1.5 of it', 'WheelRadius': 'native wheel_radius; ground contact = radius + 0.01 m',
    'MaxAngle': 'camera ease (copied to the car camera_system)', 'AngleEaseInSpeed': 'camera ease', 'MaxDistance': 'camera ease',
    'DistanceMoveOutSpeed': 'camera ease', 'DistanceMoveInSpeed': 'camera ease', 'DistanceZFactor': 'camera ease',
    'Inertial_Length': 'box inertia (SetBoxInertiaMatrix, x0.5 x5?)', 'Inertial_Width': 'box inertia', 'Inertial_Height': 'box inertia',
    'Vehicle_Length': 'traffic / AI length', 'Vehicle_Width': 'traffic / AI width', 'Shadow_opacity': 'blob shadow',
}
# car_move_ctrl members a designer would tune; registration defaults (code) apply when the fragment does not set them
SHELL_PROPS = {
    'max_engine_force': (12000.0, 'engine force (N) of EVERY 4-wheel car; with drag_coeff and rolling_res gives the top speed'),
    'max_reverse_force': (6000.0, 'reverse force (N)'),
    'rolling_res': (189.0, 'linear rolling resistance r (N per m/s), grounded only; x1.7 while sliding'),
    'max_turn': (0.785, 'full steering lock (rad) x key number'),
    'turn_rate': (0.174, 'steering ramp per 0.04 s step (rad); release = instant 0'),
    'slide_angle': (0.174, 'slide starts when |wheel| - |effective angle| >= this (rad)'),
    'powerslide_minimum_turnrate': (0.5, 'steering key number above which the slide grows and counts towards a spin'),
    'static_brake_resistance': (1.0, 'below this speed (m/s) braking stops the car dead'),
    'rolling_static_threshold': (1.0, 'coasting below this speed (m/s) stops the car dead'),
    'burn_out_speed': (10.0, 'burnout (V+W standing) lasts while rear speed < this x10'),
    'sideways_slide_resistance': (0.95, 'lateral slide kept per step after a brake slide'),
    'standard_sideways_slide_resistance': (0.6, 'lateral slide kept per step when the wheels are straightened'),
    'sideways_static_resistance': (0.1, 'slide ends below this lateral speed (m/s)'),
    'standard_sideways_static_resistance': (0.1, 'registered; consumer not seen in the step functions'),
    'standard_ground_clearance': (0.03, 'wheel contact tolerance used by the grounded tests'),
    'anchor_ground_clearance': (0.1, 'contact tolerance (anchor tests)'),
    'self_righting_speed': (1.8, 'upright recovery speed'),
    'wheelie_max_angle': (0.8, 'bike wheelie limit (rad)'), 'wheelie_speed': (0.5, 'bike wheelie rate'),
    'jump_minimum_time': (1.0, 'airborne time before landing logic resets (s)'),
    'cant_move_reaction_time': (5.0, 'stuck timer (s)'), 'engine_res': (0.3, 'engine sound/rpm helper'),
    'fork_speed': (10.0, 'forklift fork speed'), 'handbrake_boost': (1.0, 'overwritten at reset by the type'),
    'cornering_ref_speed': (31.4, 'overwritten at reset: computed top speed'),
}
TRAFFIC_PROPS = ['Problem_point_distance', 'Problem_point_half_angle', 'Slack', 'CornerCurve', 'MaxSpeed', 'CruiseSpeed',
                 'HalfSpeed', 'AccBrake', 'JunctionStayTime', 'JunctionChangeTime', 'fix_vehicle_requires_input',
                 'fix_vehicle_required_time', 'lights_on']
RES_PROPS = ['PlaceHolderRadius', 'PlaceHolderZAdjust', 'MaxGrowth', 'MaxAllocated', 'ResourcesToCollect',
             'MinimumCollectTime', 'SleepTime', 'PopSensitive', 'PopRangeMax', 'DynamicRadius', 'DoSpatialCheck',
             'DoOffcenterCheck', 'UseLODData']
CAM_PROPS = ['MaxAngle', 'AngleEaseInSpeed', 'MaxDistance', 'DistanceMoveOutSpeed', 'DistanceMoveInSpeed', 'DistanceZFactor']


def tunables():
    """name -> (blocks, fragment, entity selector, property, note, code default or None)"""
    T = {}
    for t in TYPE_NAMES:
        for p in TYPE_PROPS:
            T['type.%s.%s' % (t, p)] = ([MAIN], VDICT, t, p, TYPE_NOTES.get(p, ''), None)
    for p, (dflt, note) in SHELL_PROPS.items():
        T['car.%s' % p] = ([MAIN], SEDAN, 'MoveCtrl', p, note, dflt)
        T['bike.%s' % p] = (BIKE_ENTRIES, BIKE, 'MoveCtrl', p, note + ' (dirt bike)', dflt)
    for p in CAM_PROPS:
        T['car.cam.%s' % p] = ([MAIN], SEDAN, 'CameraCtrl', p, 'shell camera_system (reset copies the type values)', None)
        T['bike.cam.%s' % p] = (BIKE_ENTRIES, BIKE, 'CameraCtrl', p, 'dirt bike camera_system', None)
        T['camdict.VehicleDefaultCam.%s' % p] = ([MAIN], CAMDICT, 'VehicleDefaultCam', p, 'CameraDict vehicle type', None)
    for p in TRAFFIC_PROPS:
        T['traffic.%s' % p] = ([MAIN], ESS, 'MasterCtrlAux/TrafficAdminCtrl', p, 'trafficsystem_admin', None)
    for k, sel in (('vehicle', 'MasterCtrlAux/ResourceCtrl/VehicleResourceCtrl'),
                   ('traffic', 'MasterCtrlAux/ResourceCtrl/TrafficVehicleResourceCtrl')):
        for p in RES_PROPS:
            T['res.%s.%s' % (k, p)] = ([MAIN], ESS, sel, p, 'master_control_resource_sub_ctrl', None)
    for p in ('PC_VehicleVisionAngle', 'PC_VehicleLockAngle'):
        T['status.%s' % p] = ([MAIN], ESS, 'MasterCtrlAux/PlayerStatusCtrl', p, 'player auto-aim cone in vehicles (deg)', None)
    for p in ('Vehicle_LOD', 'Traffic_LOD', 'Placeholder_LOD'):
        T['lod.%s' % p] = ([MAIN], ESS, 'MasterCtrlAux/LODCtrl', p, 'master_control_LOD_ctrl', None)
    for n in ('Car', 'Bike', 'Truck'):
        T['physic.%s.Mass' % n] = ([MAIN], PHYS, n, 'Mass', 'PhysicDict (consumer not traced)', None)
    return T


TUN = tunables()


class Blocks:
    def __init__(self, override=None):
        self.raw = {}
        self.ext = {}
        self.override = override or {}
        self.docs = {}

    def get(self, entry):
        if entry not in self.raw:
            if entry in self.override:
                raw = self.override[entry]
                ext = os.path.splitext(entry)[1].lower()
            else:
                raw, entry2, ext = ft.load_block_bytes(entry, None)
            self.raw[entry] = raw
            self.ext[entry] = ext
        return self.raw[entry], self.ext[entry]

    def doc(self, entry, frag):
        key = (entry, frag)
        if key not in self.docs:
            raw, ext = self.get(entry)
            b = tb.Block(raw, ext)
            frs, _ = ft.fragments(b)
            k, nm = ft.pick_fragment(frs, frag)
            self.docs[key] = fe.FragDoc(b.payloads[k], ft.types(), nm)
        return self.docs[key]


def norm(v):
    return list(v) if isinstance(v, tuple) else v


def read_values(B, names=None):
    out, src = {}, {}
    for n in (names or TUN):
        blocks, frag, sel, prop, note, dflt = TUN[n]
        vals = []
        for e in blocks:
            d = B.doc(e, frag)
            node = d.find(sel)
            v = d.get(node, prop)
            vals.append(norm(v))
        v0 = vals[0]
        if any(not same(v0, v) for v in vals[1:]):
            out[n] = vals
            src[n] = 'differs per block'
        elif v0 is None and dflt is not None:
            out[n] = dflt
            src[n] = 'code default'
        else:
            out[n] = v0
            src[n] = 'data' if v0 is not None else 'unset'
    return out, src


def same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    return a == b


def fmt(v):
    if isinstance(v, float):
        return '%.6g' % v
    if isinstance(v, list):
        return '[' + ', '.join(fmt(x) for x in v) + ']'
    return json.dumps(v)


WHEELBASE = {   # model wheelbase |Wheel_Right_01 - Wheel_Right_02| (m) of the model each type uses (by name; doc 3.4)
    '4x4Pickup': 3.949, 'BigTruck': 6.391, 'BigTruckFlatnose': 4.78, 'BigTruckMoralez': 8.258, 'BurritoCart': 3.067,
    'Bus': 7.94, 'Conquistador': 4.118, 'Cranetruck': 5.076, 'ElCamino': 4.322, 'Forklift': 1.527,
    'MilitaryTruck': 5.536, 'ModernSedan': 3.747, 'Pickup_Truck': 3.897, 'Sedan': 4.117, 'StationWagon': 4.127,
    'Tractor': 3.025, 'VanHeavy': 3.949, 'VanUrban': 4.114, '57Pickup': 4.152, 'PoliceCar': 3.747, 'Taxi': 3.747,
    'SedanRusty': 4.117, 'Pickup': 3.897, 'Dirtbike': 0.648, 'Chopper': 0.648, 'Truck': 6.391, 'AITest': 4.117,
    'VanAngel': 4.114, 'Door_Left_Front': 4.0}


def type_row(vals, t):
    return {p: vals['type.%s.%s' % (t, p)] for p in TYPE_PROPS}


def shell_values(vals, which='car'):
    return {p: vals['%s.%s' % (which, p)] for p in SHELL_PROPS if not isinstance(vals['%s.%s' % (which, p)], list)}


def cmd_show(argv):
    grp = argv[argv.index('--group') + 1] if '--group' in argv else None
    B = Blocks()
    vals, src = read_values(B)
    for n, (blocks, frag, sel, prop, note, dflt) in TUN.items():
        if grp and not n.startswith(grp):
            continue
        print('  %-48s %-28s %-12s %s : %s.%s  %s' % (n, fmt(vals[n])[:28], src[n], frag.split('/')[-1], sel, prop,
                                                       ('(' + note + ')') if note else ''))
    if '--derived' in argv:
        print('\n# driving model (vehsim.py), level ground, keyboard; car shell values; see doc section 4')
        hdr = ('type', 'vmax', 'vrev', '0-50', '0-100', 'brk100m', 'steer0', 'slide', 'Rmin', 'L')
        print('  %-16s %7s %7s %6s %6s %8s %7s %7s %6s %6s' % hdr)
        shell = shell_values(vals)
        for t in TYPE_NAMES:
            p = vehsim.params(type_row(vals, t), shell, WHEELBASE.get(t, 4.0))
            d = vehsim.derived(p)
            f = lambda x, k=1.0: ('%.1f' % (x * k)) if isinstance(x, (int, float)) and x is not None else '-'
            print('  %-16s %7s %7s %6s %6s %8s %7s %7s %6s %6.2f' % (
                t, f(d['top_speed_kmh']), f(d['reverse_top_kmh']), f(d['t_0_50']), f(d['t_0_100']), f(d['brake_100_m']),
                f(d['steer_gone_kmh']), f(d['slide_onset_kmh']), f(d['min_radius_m']), p['L']))
        print('  vmax/vrev km/h; 0-50/0-100 s; brk100m = V-brake distance from 100 km/h; steer0 = km/h where the speed '
              'reduction leaves 0.1 %% of the wheel angle; slide = km/h where a full-lock slide can start; Rmin m')
    return 0


def cmd_export(argv):
    B = Blocks()
    vals, src = read_values(B)
    json.dump({'values': vals, 'source': src}, open(argv[2], 'w'), indent=1)
    print('wrote %s (%d values)' % (argv[2], len(vals)))
    return 0


def build(spec, outdir=None, base=None, verbose=True):
    """spec = {"set": {name: value}}. Returns report; raises on failure. base = {entry: bytes} to edit other blocks."""
    rep = dict(result='FAIL')
    sets = spec.get('set', {})
    for n in sets:
        if n not in TUN:
            raise KeyError('unknown tunable %s' % n)
    per_block = {}
    for n, v in sets.items():
        blocks, frag, sel, prop, note, dflt = TUN[n]
        for e in blocks:
            per_block.setdefault(e, []).append(dict(op='set', fragment=frag, entity=sel, prop=prop, value=v))
    B = Blocks(base)
    T = ft.types()
    outs = []
    rep['blocks'] = []
    for e, ops in per_block.items():
        raw, ext = B.get(e)
        r0 = ft.roundtrip_block(raw, ext, T)
        if r0['fail'] or not r0['block_identical']:
            raise RuntimeError('base block %s does not round-trip' % e)
        old, nb, docs, intended = ft.apply_ops(raw, ext, ops, T)
        newb = nb.serialize()
        ft.verify_block(old, newb, ext, docs, intended, T)
        outs.append((e, newb))
        rep['blocks'].append(dict(entry=e, ops=len(ops), base_sha256=hashlib.sha256(raw).hexdigest(),
                                  out_sha256=hashlib.sha256(newb).hexdigest(), identical_to_base=newb == raw,
                                  bytes=len(newb)))
    # read back through a fresh reader on the rebuilt blocks
    RB = Blocks(dict(outs))
    back, _ = read_values(RB, list(sets))
    bad = {}
    for n, v in sets.items():
        bv = back[n]
        if not same(v, bv):
            bad[n] = (v, bv)
    if bad:
        raise RuntimeError('read-back mismatch %s' % bad)
    rep['readback'] = back
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        for e, b in outs:
            open(os.path.join(outdir, os.path.basename(e)), 'wb').write(b)
        rep['zip'] = ft.write_zip(os.path.join(outdir, ft.ZIP_NAME), outs)
        rep['configpc_line'] = 'filesystem = ' + ', '.join([ft.ZIP_NAME] + ft.BASE_ARCHIVES)
        json.dump({'description': spec.get('description', 'vehtool edit'),
                   'blocks': [{'block': e, 'ops': per_block[e]} for e in per_block]},
                  open(os.path.join(outdir, 'frag_edit.json'), 'w'), indent=1)
    rep['result'] = 'PASS'
    rep['outs'] = outs
    if outdir:
        json.dump({k: v for k, v in rep.items() if k != 'outs'}, open(os.path.join(outdir, 'build_report.json'), 'w'),
                  indent=1, default=str)
    if verbose:
        print(json.dumps({k: rep[k] for k in rep if k in ('result', 'zip', 'configpc_line', 'blocks')}, indent=1,
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


def changed(v, n):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 1
    if isinstance(v, float):
        return v * 1.25 + 0.5
    if isinstance(v, list) and v and all(isinstance(x, float) for x in v):
        return [x * 1.25 + 0.5 for x in v]
    return v


def cmd_roundtrip(argv, quiet=False):
    T = ft.types()
    B = Blocks()
    ok = True
    entries = [MAIN] + BIKE_ENTRIES
    for e in entries:
        raw, ext = B.get(e)
        r = ft.roundtrip_block(raw, ext, T)
        good = not r['fail'] and r['block_identical']
        ok &= good
        if not quiet:
            print('1 %-62s %s' % (e.split('/')[-1], 'round-trips (every fragment, whole block)' if good else 'FAIL %s' % r['fail'][:3]))
    vals, src = read_values(B)
    setv = {n: v for n, v in vals.items() if src[n] == 'data'}
    rep = build({'set': setv}, None, verbose=False)
    ident = all(b['identical_to_base'] for b in rep['blocks'])
    ok &= ident
    print('2 %d data values written back unchanged -> %d blocks %s' % (
        len(setv), len(rep['blocks']), 'byte-identical' if ident else 'DIFFER'))
    ch = {n: changed(v, n) for n, v in setv.items() if not n.endswith('.Specific_ID')}
    unset = {n: changed(TUN[n][5], n) for n in vals if src[n] == 'code default'}
    ch.update(unset)
    rep2 = build({'set': ch}, None, verbose=False)
    base2 = dict(rep2['outs'])
    rep3 = build({'set': {n: (vals[n] if n in setv else None) for n in ch if n in setv}}, None, base=base2, verbose=False)
    restored = dict(rep3['outs'])
    print('3 %d values changed (incl. %d code-default members added to the shells) and read back: PASS; the %d shipped '
          'values restored -> %s' % (len(ch), len(unset), len(setv),
                                    'data identical except the added records' if rep3['result'] == 'PASS' else 'FAIL'))
    # a restore cannot remove added property records; check the restored blocks against base + only added sets
    T2 = Blocks(restored)
    v2, s2 = read_values(T2)
    back_ok = all(same(v2[n], vals[n]) for n in setv)
    ok &= back_ok
    print('4 restored blocks read back the shipped value of all %d data values: %s' % (len(setv), 'PASS' if back_ok else 'FAIL'))
    print('ROUNDTRIP', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def cmd_selftest(argv):
    import tempfile
    import shutil
    ok = cmd_roundtrip(argv, quiet=False) == 0
    tmp = tempfile.mkdtemp(prefix='vehtool_')
    spec = json.load(open(os.path.join(HERE, 'proposal.json')))
    rep = build(spec, tmp, verbose=False)
    ok &= rep['result'] == 'PASS'
    z = rep.get('zip') or {}
    print('5 proposal.json build: %s, %d values read back from %d rebuilt block(s), zip %d B, engine lookup %s' % (
        rep['result'], len(spec['set']), len(rep['blocks']), z.get('zip_bytes', 0),
        all(e.get('engine_lookup_ok') for e in z.get('entries', [])) and 'ok' or 'FAIL'))
    if ok:
        shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST', 'PASS' if ok else 'FAIL (outputs kept in %s)' % tmp)
    return 0 if ok else 1


def cmd_sim(argv):
    t = argv[2]
    B = Blocks()
    vals, src = read_values(B)
    for a in argv[3:]:
        k, v = a.split('=', 1)
        vals[k] = json.loads(v)
    p = vehsim.params(type_row(vals, t), shell_values(vals), WHEELBASE.get(t, 4.0))
    d = vehsim.derived(p)
    print('%s: F %.0f N, c %.3g, r %.3g, m %.0f kg, B %.0f N, cs %.3g, L %.2f m' % (t, p['F'], p['c'], p['r'], p['m'], p['B'], p['cs'], p['L']))
    for k, v in d.items():
        print('  %-20s %s' % (k, fmt(v) if v is not None else '-'))
    for v in (8, 15, 22, 28):
        r = vehsim.turn_at(p, v)
        print('  full lock at %2d m/s (%3.0f km/h): yaw %6.1f deg/s, radius %6.1f m, lateral %.2f g, angle %.1f deg, slide at %s s, spin at %s s'
              % (v, v * 3.6, r['yaw_deg_s'], r['radius'], r['lat_g'], r['effective_angle_deg'],
                 '%.2f' % r['slide_at'] if r['slide_at'] else '-', '%.2f' % r['spin_at'] if r['spin_at'] else '-'))
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    return {'show': cmd_show, 'export': cmd_export, 'build': cmd_build, 'roundtrip': cmd_roundtrip,
            'selftest': cmd_selftest, 'sim': cmd_sim}[argv[1]](argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
