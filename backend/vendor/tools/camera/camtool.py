"""TOD camera tool: read, report and write back the camera data of Total Overdose (GOG build), and the
camera code constants the camfov proxy can change.

  python camtool.py show [--code] [--triggers]      every camera value (data; --code: code constants, shipped-byte check)
  python camtool.py export -o camera.json [--triggers]
  python camtool.py fov [--res 1920x1080] [--fov 64] [--ratioxy 1] [--target-hfov 90]   the field-of-view arithmetic
  python camtool.py build <camedit.json> --out DIR [--deploy TESTGAME]   frag_override.zip (+ camfov.ini)
  python camtool.py selftest [--out DIR]

Data lives in fragments (the fragment writer tools/fragment_writer does the byte work and the checks):
  overdose.main   CharacterPlayerControlled.fragment  player rig: Animation/CameraCtrl (camera_system) + CameraPos ...
                  CameraDict.fragment                 CharacterCombatCam / CharacterNormalCam / VehicleDefaultCam
                  Overdose.scene                      GameCamera (camera_root(Camera)): fov, nearclip, farclip
                  GameCamera.fragment                 DummyCamCtrl, MoveCtrl (camera_move_ctrl), AICtrl, CamProbe
                  VehicleDict.fragment                29 database_vehicle_type: pos/orient = camera position per vehicle type
                  VehicleSedan.fragment, PKS_HighMounted.fragment   vehicle / mounted-gun rigs
  *.mission       VehicleDirtBike.fragment (7 missions)  dirt bike rig
  all blocks      Trigger_Activate_Camera (811): FOVFrom / FOVTo / FOVChangeTime ...
Code (TOD.exe, read only here): see CODE below and docs/subsystem_camera.md.

camedit.json (every key optional):
{ "description": "...",
  "player":   {"back": 0.75, "up": 0.0, "right": null, "pitch_deg": null, "pos": null},
  "cameradict": {"CharacterCombatCam": {"MaxAngle": 2.0, "AngleEaseInSpeed": 7.5, "MaxDistance": 0.5,
                                         "DistanceMoveOutSpeed": 1.5, "DistanceMoveInSpeed": 2.0, "DistanceZFactor": 0.5}},
  "player_ease": {"MaxAngle": 0.25, ...},          (CameraCtrl start values; replaced by CameraDict type 0 in play)
  "vehicles": {"back": 1.0, "up": 0.0, "scale": null, "types": {"Sedan": {"back": 2.0, "AngleEaseInSpeed": 4}},
               "rigs": true},                       (rigs: VehicleSedan / VehicleDirtBike rigs get the same back/up)
  "mounted":  {"back": 0.5, "up": 0.0},             (PKS_HighMounted mounted machine gun)
  "gamecamera": {"farclip": 1000.0},                 (fov and nearclip are overwritten by code at start: use the proxy)
  "raw": [{"block": "...", "ops": [fragment_writer ops]}],
  "proxy": {"fov": 64, "fov_scope": 0, "cull_fix": 1, "log": 1, "chain": ""}   -> camfov.ini for proxy/dinput8.dll }
"back" moves a camera node backwards along its own line of sight (the character keeps its place on screen and gets
smaller), "up" raises it, "pitch_deg" sets the downward pitch (degrees) before "back" is applied.
"""
import argparse, json, math, os, struct, sys, hashlib, shutil, types as _types
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.environ.get('TOD_FW') or next((p for p in (os.path.join(HERE, '..', 'fragment_writer'),)
                                       if os.path.exists(os.path.join(p, 'fragtool.py'))), None)
if FW is None:
    sys.exit('tools/fragment_writer not found (set TOD_FW)')
sys.path.insert(0, os.path.abspath(FW))
import todblock as tb          # noqa: E402
import todfrag as tf           # noqa: E402
import fragedit as fe          # noqa: E402
import fragtool as ft          # noqa: E402

EXE = os.environ.get('TOD_EXE', r'C:/GOG Games/Total Overdose/TOD.exe')       # read only
EXE_MD5 = 'd9beb351b3c78ee9f14a766a368f3ff9'
MAIN = 'overdose.main'
EASE = ['MaxAngle', 'AngleEaseInSpeed', 'MaxDistance', 'DistanceMoveOutSpeed', 'DistanceMoveInSpeed', 'DistanceZFactor']
PLAYER_FRAG = 'CharacterPlayerControlled.fragment'
PLAYER_NODES = ['CameraPos', 'AdjustedPivot', 'CameraLookAt', 'VertigoPivot', 'DockCraneCamPos', 'RamMoveCamPos',
                'SombreroMoveCamPos', 'CameraExitVehicleSedanPos']
DIRTBIKE_MISSIONS = ['gameover_intermission.mission', 'intermission_after_breakintosafe.mission',
                     'intermission_after_bridge.mission', 'intermission_after_elvez.mission',
                     'intermission_after_jungle.mission', 'mm120_runawaytrain.mission', 'subm_07_indu_mulral01_race.mission']

# ------------------------------------------------------------------ code constants (GOG TOD.exe VAs; read only here)
# kind: imm = push imm32 float (bytes 68 xx xx xx xx); mem = instruction reads a float at an .rdata address (shared
# constant: a change must redirect the operand, never write the constant); site = hook site of the camfov proxy.
CODE = [
 # name, va, shipped bytes, kind, operand offset, meaning
 ('fov_start', 0x4B8AFE, '6800008042', 'imm', 1, 'camera_root initialize_local: GameCamera fov = 64 (data fov 70 is overwritten)'),
 ('fov_load', 0x7477E7, '6800008042', 'imm', 1, 'master_control_load_ctrl state: fov = 64 after a load'),
 ('near_start', 0x4B8B0A, '680000003e', 'imm', 1, 'camera_root initialize_local: nearclip = 0.125'),
 ('near_clear', 0x4B76E3, '680000803f', 'imm', 1, 'camera_move_ctrl: nearclip = 1.0 once no collision for CollisionTimer'),
 ('near_close', 0x4B4C01, 'f30f100548369b00', 'mem', 4, 'camera_move_ctrl FUN_004B4BA0: nearclip = 0.125 when the probe hits'),
 ('line_close', 0x4B4BDA, 'f30f100548369b00', 'mem', 4, 'camera probe line thickness 0.125 while close (same constant)'),
 ('line_far', 0x4B763D, 'f30f10057c399b00', 'mem', 4, 'camera probe line thickness 0.75 in far-detection mode'),
 ('coll_timer', 0x4B756F, 'f30f100598379b00', 'mem', 4, 'CollisionTimer reload 3.0 s (also 0x4B76B2)'),
 ('probe_interval', 0x4B4B5C, 'f30f1005903b9b00', 'mem', 4, 'CamProbe Update every 0.2 s'),
 ('probe_from_up', 0x4B4E8B, 'f30f1005c8379b00', 'mem', 4, 'probe line starts 0.5 x up-vector above the pivot target'),
 ('settype_moveout', 0x4CE1CF, 'f30f1005ec749b00', 'mem', 4, 'set_camera_type forces DistanceMoveOutSpeed = 0.3'),
 ('slope_pitch', 0x4CA4E3, 'f30f5905d8e79b00', 'mem', 4, 'camera pitch = 0.55 x local z of the smoothed ground normal'),
 ('center_y_min', 0x4CB723, 'f30f100dc0be9b00', 'mem', 4, 'lag offset y clamp -0.2'),
 ('center_y_max', 0x4CB791, 'f30f100d903b9b00', 'mem', 4, 'lag offset y clamp +0.2'),
 ('maxangle_pi', 0x4CAB86, 'f30f100d9ce79b00', 'mem', 4, 'MaxAngle unit = pi rad (clamp at MaxAngle*pi*1.001)'),
 ('ease_free_x2', 0x4CB284, 'f30f59053c369b00', 'mem', 4, 'ease rate x2 when MaxAngleActive is off'),
 ('layer_fov_15', 0x87DE8C, '6800008c42', 'imm', 1, 'render layers 0x15/0x16/0x1B: fixed fov 70, near 0.1, far 100'),
 ('cull_vert_075', 0x87E009, 'd80d7c399b00', 'mem', 2, 'cull frustum: vfov = 2 atan(0.75 tan(fov/2))'),
 ('cull_aspect_wide', 0x87E046, 'f30f100550c99c00', 'mem', 4, 'cull frustum aspect 16/9 when the widescreen flag 0xA39F12 is set'),
 ('cull_aspect_43', 0x87E050, 'f30f1005ec389b00', 'mem', 4, 'cull frustum aspect 4/3 otherwise (every PC resolution)'),
 ('proj_vert_075', 0x44E5FD, 'd80d7c399b00', 'mem', 2, 'D3D projection: vfov = 2 atan(0.75 tan(fov/2))'),
 ('proj_aspect_wide', 0x44E631, '68398ee33f', 'imm', 1, 'D3D projection aspect 16/9 when the widescreen flag is set (else w/h/ratioxy)'),
 ('rammove_fov_base', 0x525641, '0f2e0550f29b00', 'mem', 3, 'Ram move: if fov == 64 -> change_fov(69, 1 s)'),
 ('rammove_fov_69', 0x52564E, 'f30f100558f29b00', 'mem', 4, 'Ram move first step fov 69'),
 ('rammove_fov_104', 0x525910, 'f30f100554f29b00', 'mem', 4, 'Ram move: if fov == 69 -> change_fov(104, 1 s)'),
 ('hook_cam_entry', 0x87DE40, '81ecf0000000', 'site', 0, 'camfov: Camera update entry (sub esp,0xF0)'),
 ('hook_fov_view', 0x87DE5F, '8b86b4000000', 'site', 0, 'camfov: fov pushed to the view (mov eax,[esi+0xB4])'),
 ('hook_fov_cull', 0x87DFE2, 'f30f1086b4000000', 'site', 0, 'camfov: fov read for the cull frustum (movss xmm0,[esi+0xB4])'),
]
RDATA = (0x9B3000, 0x5B3000)          # VA, file offset
TEXT = (0x401000, 0x1000)


def va_off(va):
    if va >= 0x9B3000:
        return va - RDATA[0] + RDATA[1]
    return va - TEXT[0] + TEXT[1]


def exe_bytes():
    d = open(EXE, 'rb').read()
    return d


def read_code(d=None):
    d = d or exe_bytes()
    out = []
    for name, va, orig, kind, opo, what in CODE:
        o = va_off(va)
        cur = d[o:o + len(orig) // 2].hex()
        val = None
        if kind == 'imm':
            val = struct.unpack('<f', d[o + opo:o + opo + 4])[0]
        elif kind == 'mem':
            addr = struct.unpack('<I', d[o + opo:o + opo + 4])[0]
            val = struct.unpack('<f', d[va_off(addr):va_off(addr) + 4])[0]
        out.append(dict(name=name, va='0x%08X' % va, kind=kind, value=val, shipped=cur == orig, what=what))
    return out


# ------------------------------------------------------------------ geometry
def fwd_of(q):
    """camera line of sight of a node with stored quaternion q (stored form is the conjugate, project convention)."""
    return fe.qrot(fe.qconj(fe.qnorm(tuple(q))), (0.0, 0.0, 1.0))


def pitch_down(q):
    f = fwd_of(q)
    return math.degrees(math.asin(max(-1.0, min(1.0, -f[1]))))


def q_pitch(deg):
    """stored quaternion of a node pitched deg downwards (vanilla player: 10 deg -> (-0.0872, 0, 0, 0.9962))."""
    h = math.radians(deg) / 2.0
    return [-math.sin(h), 0.0, 0.0, math.cos(h)]


def moved(pos, orient, back=0.0, up=0.0, right=None, pitch_deg=None):
    q = list(orient)
    if pitch_deg is not None:
        q = q_pitch(pitch_deg)
    f = fwd_of(q)
    p = [pos[i] - back * f[i] for i in range(3)]
    p[1] += up
    if right is not None:
        p[0] = right
    return p, q


def geo(pos, orient):
    return dict(pos=[round(x, 6) for x in pos], orient=[round(x, 6) for x in orient], back=round(-pos[2], 4),
                up=round(pos[1], 4), right=round(pos[0], 4), pitch_down_deg=round(pitch_down(orient), 3))


# ------------------------------------------------------------------ data access
_T = None
def T():
    global _T
    if _T is None:
        _T = tf.Types()
    return _T


class Blk:
    def __init__(self, name, data=None, entry=None):
        if data is None:
            data, entry, ext = ft.load_block_bytes(name)
        else:
            ext = os.path.splitext(entry)[1]
        self.raw, self.entry, self.ext = data, entry, ext
        self.b = tb.Block(data, ext)
        self.frs, _ = ft.fragments(self.b)
        self.docs = {}

    def doc(self, sub):
        k, nm = ft.pick_fragment(self.frs, sub)
        if k not in self.docs:
            self.docs[k] = fe.FragDoc(self.b.payloads[k], T(), nm)
        return self.docs[k]


def node_info(d, n, props=()):
    pos = d.get(n, 'pos') or [0.0, 0.0, 0.0]
    q = d.get(n, 'orient') or [0.0, 0.0, 0.0, 1.0]
    r = dict(node='0x%08X' % n, path=d.path_of(n), type=d.type_of(n))
    r.update(geo(pos, q))
    for p in props:
        v = d.get(n, p)
        if v is not None:
            r[p] = v
    return r


def collect(triggers=False, blocks=None):
    blocks = {} if blocks is None else blocks
    def blk(name):
        if name not in blocks:
            blocks[name] = Blk(name)
        return blocks[name]
    m = blk(MAIN)
    out = dict(block_sha256=hashlib.sha256(m.raw).hexdigest())
    d = m.doc(PLAYER_FRAG)
    cc = d.find('Animation/CameraCtrl')
    out['player'] = dict(fragment=PLAYER_FRAG, CameraCtrl=node_info(d, cc, EASE),
                         nodes={nm: node_info(d, d.find('Animation/CameraCtrl/' + nm)) for nm in PLAYER_NODES
                                if nm not in ('AdjustedPivot',)})
    out['player']['nodes']['AdjustedPivot'] = node_info(d, d.find('Animation/CameraCtrl/AdjustedPivot'))
    anim = d.find('Animation')
    out['player']['Animation_pos'] = d.get(anim, 'pos')
    d = m.doc('CameraDict.fragment')
    out['cameradict'] = {d.get(n, 'name'): {p: d.get(n, p) for p in EASE} for n in d.created_ids()}
    d = m.doc('Overdose.scene')
    gc = d.find({'name': 'GameCamera'})
    out['gamecamera'] = dict(scene={p: d.get(gc, p) for p in ('fov', 'nearclip', 'farclip', 'offset', 'dynlightcullrange',
                                                              'glare_delta_Sat', 'glare_delta_Bright', 'glare_start_cos_angle',
                                                              'overburn_delta_Sat', 'overburn_delta_bright', 'overburn_start_cos_angle')})
    d = m.doc('GameCamera.fragment')
    out['gamecamera']['nodes'] = [node_info(d, n, EASE + ['DefaultFadeDistance', 'radius', 'usermask', 'dynamicmask'])
                                  for n in d.created_ids()]
    d = m.doc('VehicleDict.fragment')
    vt = {}
    for n in d.created_ids():
        if 'vehicle_type' in (d.type_of(n) or ''):
            vt[d.get(n, 'name')] = node_info(d, n, EASE + ['Vehicle_Length'])
    out['vehicle_types'] = vt
    rigs = []
    for bn, fr, root in [(MAIN, 'VehicleSedan.fragment', 'CameraCtrl'), (MAIN, 'PKS_HighMounted.fragment', None)] + \
                        [(mb, 'VehicleDirtBike.fragment', 'CameraCtrl') for mb in DIRTBIKE_MISSIONS]:
        b = blk(bn)
        d = b.doc(fr)
        for n in d.created_ids():
            t = d.type_of(n) or ''
            nm = d.get(n, 'name') or ''
            if t.startswith('camera_system') or nm in ('CameraPos', 'AdjustedPivot', 'CameraLookAt', 'CollisionAdjustedPivot'):
                r = node_info(d, n, EASE)
                r.update(block=bn, fragment=fr)
                rigs.append(r)
    out['rigs'] = rigs
    if triggers:
        out['triggers'] = trigger_census()
    return out


def trigger_census():
    a = ft.archive()
    rows, n = [], 0
    for name in sorted(a.names):
        if not name.lower().endswith(('.main', '.map', '.submap', '.mission', '.playerdata')):
            continue
        b = tb.Block(a.read(name), os.path.splitext(name)[1])
        info = bytes(b.info)
        for k, R in enumerate(tb.record_starts(info, b.n)):
            if tb.u32(info, R) != 4:
                continue
            fr = tf.Fragment(b.payloads[k], T())
            for nid, e in fr.entities().items():
                if not (e['type'] or '').startswith('Trigger_Activate_Camera'):
                    continue
                n += 1
                p = {T().name(r.prop): fr.value(r) for r in e['sets']}
                keep = {kk: p.get(kk) for kk in ('name', 'FOVFrom', 'FOVTo', 'FOVChangeTime', 'VertigoEffect', 'LookAt',
                                                 'TargetName', 'LookAtTargetName', 'TotalTransitionTime',
                                                 'TransitionEaseInTime', 'TransitionEaseOutTime', 'SlowMotionFraction')}
                if keep['FOVFrom'] not in (None, 64.0) or keep['FOVTo'] not in (None, 64.0):
                    rows.append(dict(block=name.split('/')[-1], fragment=tb.record_name(info, R).split('/')[-1],
                                     node='0x%08X' % nid, **keep))
    return dict(count=n, non_default_fov=rows)


# ------------------------------------------------------------------ FOV arithmetic
def fov_table(fov=64.0, w=1920, h=1080, ratioxy=1.0, widescreen_flag=False):
    vfov = 2 * math.degrees(math.atan(0.75 * math.tan(math.radians(fov) / 2)))
    aspect = 16 / 9 if widescreen_flag else (w / h) / ratioxy
    hfov = 2 * math.degrees(math.atan(aspect * math.tan(math.radians(vfov) / 2)))
    cull_aspect = 16 / 9 if widescreen_flag else 4 / 3
    cull_h = 2 * math.degrees(math.atan(cull_aspect * math.tan(math.radians(vfov) / 2)))
    return dict(fov_setting=fov, vertical=round(vfov, 3), aspect=round(aspect, 5), horizontal=round(hfov, 3),
                cull_horizontal_vanilla=round(cull_h, 3), uncovered_each_side_deg=round(max(0, hfov - cull_h) / 2, 3))


def remap(fov, target, base=64.0):
    """camfov tangent scaling: base -> target, every other fov keeps its ratio of tangents to the base."""
    k = math.tan(math.radians(target) / 2) / math.tan(math.radians(base) / 2)
    return 2 * math.degrees(math.atan(k * math.tan(math.radians(fov) / 2)))


def fov_for_hfov(hfov, w, h, ratioxy=1.0):
    a = (w / h) / ratioxy
    v = 2 * math.atan(math.tan(math.radians(hfov) / 2) / a)
    return 2 * math.degrees(math.atan(math.tan(v / 2) / 0.75))


# ------------------------------------------------------------------ edit -> fragment_writer ops
def r6(v):
    return [tf.f32(x) + 0.0 for x in v]


def node_ops(d, frag, sel, back=0.0, up=0.0, right=None, pitch_deg=None, pos=None):
    n = d.find(sel)
    p0 = d.get(n, 'pos') or [0.0, 0.0, 0.0]
    q0 = d.get(n, 'orient') or [0.0, 0.0, 0.0, 1.0]
    if pos is not None:
        p, q = list(pos), (q_pitch(pitch_deg) if pitch_deg is not None else list(q0))
    else:
        p, q = moved(p0, q0, back, up, right, pitch_deg)
    ops = [dict(op='set', fragment=frag, entity='0x%08X' % n, prop='pos', value=r6(p))]
    if pitch_deg is not None:
        ops.append(dict(op='set', fragment=frag, entity='0x%08X' % n, prop='orient', value=r6(fe.qnorm(q))))
    return ops, dict(node='0x%08X' % n, path=d.path_of(n), old=geo(p0, q0), new=geo(r6(p), q))


def plan(spec, blocks=None):
    """camedit.json -> {block: [ops]} and a human-readable list of changes."""
    blocks = {} if blocks is None else blocks
    def blk(name):
        if name not in blocks:
            blocks[name] = Blk(name)
        return blocks[name]
    ops, notes = {}, []
    def add(bn, o):
        ops.setdefault(bn, []).extend(o)
    m = blk(MAIN)
    pl = spec.get('player')
    if pl:
        d = m.doc(PLAYER_FRAG)
        for nm in ('CameraPos', 'AdjustedPivot'):
            o, note = node_ops(d, PLAYER_FRAG, 'Animation/CameraCtrl/' + nm, pl.get('back', 0.0), pl.get('up', 0.0),
                               pl.get('right'), pl.get('pitch_deg'), pl.get('pos'))
            add(MAIN, o); notes.append(note)
    if spec.get('player_ease'):
        d = m.doc(PLAYER_FRAG)
        for k, v in spec['player_ease'].items():
            if k not in EASE: raise ValueError('player_ease: unknown %s' % k)
            add(MAIN, [dict(op='set', fragment=PLAYER_FRAG, entity='Animation/CameraCtrl', prop=k, value=float(v))])
            notes.append(dict(path='Animation/CameraCtrl', prop=k, old=d.get(d.find('Animation/CameraCtrl'), k), new=v))
    for t, kv in (spec.get('cameradict') or {}).items():
        d = m.doc('CameraDict.fragment')
        n = d.find({'name': t})
        for k, v in kv.items():
            if k not in EASE: raise ValueError('cameradict: unknown %s' % k)
            add(MAIN, [dict(op='set', fragment='CameraDict.fragment', entity='0x%08X' % n, prop=k, value=float(v))])
            notes.append(dict(path='CameraDict/' + t, prop=k, old=d.get(n, k), new=v))
    gc = spec.get('gamecamera')
    if gc:
        d = m.doc('Overdose.scene')
        n = d.find({'name': 'GameCamera'})
        for k, v in gc.items():
            if k not in ('farclip', 'nearclip', 'fov', 'dynlightcullrange'): raise ValueError('gamecamera: unknown %s' % k)
            add(MAIN, [dict(op='set', fragment='Overdose.scene', entity='0x%08X' % n, prop=k, value=float(v))])
            notes.append(dict(path='Overdose.scene/GameCamera', prop=k, old=d.get(n, k), new=v,
                              note='overwritten by code at start (use the proxy)' if k in ('fov', 'nearclip') else ''))
    vh = spec.get('vehicles')
    if vh:
        d = m.doc('VehicleDict.fragment')
        per = vh.get('types', {})
        for n in d.created_ids():
            if 'vehicle_type' not in (d.type_of(n) or ''): continue
            nm = d.get(n, 'name')
            s = dict(back=vh.get('back', 0.0), up=vh.get('up', 0.0), scale=vh.get('scale'))
            s.update({k: v for k, v in per.get(nm, {}).items() if k in ('back', 'up', 'scale', 'pos', 'pitch_deg')})
            p0, q0 = d.get(n, 'pos'), d.get(n, 'orient')
            if s.get('pos') is not None:
                p, q = list(s['pos']), q0
            else:
                p, q = moved(p0, q0, s['back'], s['up'], None, s.get('pitch_deg'))
                if s.get('scale'): p = [x * s['scale'] for x in p]
            if [tf.f32(x) for x in p] != [tf.f32(x) for x in p0] or s.get('pitch_deg') is not None:
                add(MAIN, [dict(op='set', fragment='VehicleDict.fragment', entity='0x%08X' % n, prop='pos', value=r6(p))])
                if s.get('pitch_deg') is not None:
                    add(MAIN, [dict(op='set', fragment='VehicleDict.fragment', entity='0x%08X' % n, prop='orient',
                                    value=r6(fe.qnorm(q)))])
                notes.append(dict(path='VehicleDict/' + nm, old=geo(p0, q0), new=geo(r6(p), q)))
            for k, v in per.get(nm, {}).items():
                if k in EASE:
                    add(MAIN, [dict(op='set', fragment='VehicleDict.fragment', entity='0x%08X' % n, prop=k, value=float(v))])
                    notes.append(dict(path='VehicleDict/' + nm, prop=k, old=d.get(n, k), new=v))
        if vh.get('rigs', True) and (vh.get('back') or vh.get('up')):
            for bn, fr in [(MAIN, 'VehicleSedan.fragment')] + [(mb, 'VehicleDirtBike.fragment') for mb in DIRTBIKE_MISSIONS]:
                d = blk(bn).doc(fr)
                for nm in ('CameraPos', 'AdjustedPivot'):
                    o, note = node_ops(d, fr, 'CameraCtrl/' + nm, vh.get('back', 0.0), vh.get('up', 0.0))
                    add(bn, o); note['block'] = bn; notes.append(note)
    mt = spec.get('mounted')
    if mt:
        d = m.doc('PKS_HighMounted.fragment')
        for n in d.created_ids():
            if d.get(n, 'name') in ('CameraPos', 'AdjustedPivot'):
                o, note = node_ops(d, 'PKS_HighMounted.fragment', '0x%08X' % n, mt.get('back', 0.0), mt.get('up', 0.0),
                                   None, mt.get('pitch_deg'))
                add(MAIN, o); notes.append(note)
    for rb in spec.get('raw', []):
        add(rb['block'], rb['ops'])
        notes.append(dict(raw=rb['block'], ops=len(rb['ops'])))
    return ops, notes


def proxy_ini(p):
    lines = ['; camfov.ini - read by proxy/dinput8.dll (camfov) next to TOD.exe. Remove a line to keep the vanilla behaviour.',
             '; fov       = the field of view the game\'s 64 becomes (degrees, 30..120); every other game fov keeps its',
             ';             tangent ratio to 64 (triggers, Ram move 69/104, rewind effect, cut-scene shots if fov_scope=1)',
             '; fov_scope = 0 gameplay camera only (GameCamera), 1 every Camera entity',
             '; cull_fix  = 1: the culling frustum uses the real picture aspect (width/height/ratioxy) instead of 4:3',
             '; log       = 1: tod_camfov.log gets the patch report and, at exit, the fov values seen',
             '; chain     = another proxy dll to load first (e.g. movefeel.dll), empty = none']
    for k in ('fov', 'fov_scope', 'cull_fix', 'log', 'chain'):
        if k in p and p[k] is not None and p[k] != '':
            lines.append('%s = %s' % (k, p[k]))
    return '\n'.join(lines) + '\n'


def cmd_build(a):
    spec = json.load(open(a.edit))
    os.makedirs(a.out, exist_ok=True)
    blocks = {}
    ops, notes = plan(spec, blocks)
    fspec = dict(description='camtool: ' + spec.get('description', os.path.basename(a.edit)),
                 blocks=[dict(block=bn, ops=o) for bn, o in ops.items()])
    fe_path = os.path.join(a.out, 'fragedit.json')
    json.dump(fspec, open(fe_path, 'w'), indent=1)
    json.dump(notes, open(os.path.join(a.out, 'camera_changes.json'), 'w'), indent=1, default=str)
    rc = 0
    if ops:
        rc = ft.cmd_edit(argparse.Namespace(edit=fe_path, out=a.out, deploy=a.deploy))
    if spec.get('proxy'):
        open(os.path.join(a.out, 'camfov.ini'), 'w').write(proxy_ini(spec['proxy']))
        print('wrote', os.path.join(a.out, 'camfov.ini'))
    # read the written blocks back and confirm every planned value
    if ops and rc == 0:
        bad = 0
        for bn, o in ops.items():
            src = Blk(bn)
            path = os.path.join(a.out, os.path.basename(src.entry))
            nb = Blk(bn, open(path, 'rb').read(), src.entry)
            for op in o:
                if op['op'] != 'set': continue
                d = nb.doc(op['fragment'])
                got = d.get(d.find(op['entity']), op['prop'])
                want = op['value']
                ok = (all(abs(x - y) < 1e-6 for x, y in zip(got, want)) if isinstance(want, list) else abs(got - want) < 1e-6)
                bad += not ok
        print('read-back of %d planned sets: %s' % (sum(len(o) for o in ops.values()), 'OK' if not bad else '%d MISMATCH' % bad))
        rc = rc or (1 if bad else 0)
    return rc


# ------------------------------------------------------------------ show / export
def fmtv(v):
    if isinstance(v, float): return '%.6g' % v
    if isinstance(v, (list, tuple)): return '(' + ', '.join('%.4g' % x for x in v) + ')'
    return str(v)


def cmd_show(a):
    c = collect(a.triggers)
    p = c['player']
    print('== player rig (overdose.main %s), character Animation node at %s' % (p['fragment'], fmtv(p['Animation_pos'])))
    cc = p['CameraCtrl']
    print('  CameraCtrl (camera_system) pos %s  start values: %s' % (fmtv(cc['pos']), '  '.join('%s=%s' % (k, fmtv(cc.get(k))) for k in EASE)))
    for nm, r in p['nodes'].items():
        print('  %-26s pos %-26s pitch %6.2f deg down  back %.3f up %.3f right %.3f' % (nm, fmtv(r['pos']), r['pitch_down_deg'], r['back'], r['up'], r['right']))
    print('== CameraDict (type index = order; the controlled player uses type 0 = CharacterCombatCam)')
    for t, kv in c['cameradict'].items():
        print('  %-20s %s' % (t, '  '.join('%s=%s' % (k, fmtv(v)) for k, v in kv.items())))
    print('== GameCamera (Overdose.scene): ' + '  '.join('%s=%s' % (k, fmtv(v)) for k, v in c['gamecamera']['scene'].items()))
    for r in c['gamecamera']['nodes']:
        extra = '  '.join('%s=%s' % (k, fmtv(r[k])) for k in EASE + ['DefaultFadeDistance', 'radius', 'usermask'] if k in r)
        print('  %-48s %-28s pos %s %s' % (r['path'], r['type'], fmtv(r['pos']), extra))
    print('== vehicle types (VehicleDict): pos/orient = camera position relative to the vehicle')
    for nm, r in c['vehicle_types'].items():
        print('  %-16s back %7.3f up %6.3f pitch %6.2f  %s' % (nm, r['back'], r['up'], r['pitch_down_deg'],
                                                           '  '.join('%s=%s' % (k, fmtv(r.get(k))) for k in EASE)))
    print('== rigs')
    for r in c['rigs']:
        print('  %-36s %-26s %-40s pos %s pitch %.2f %s' % (r['block'], r['fragment'], r['path'], fmtv(r['pos']), r['pitch_down_deg'],
                                                           '  '.join('%s=%s' % (k, fmtv(r[k])) for k in EASE if k in r)))
    if a.triggers:
        t = c['triggers']
        print('== Trigger_Activate_Camera: %d in all blocks, %d with a fov other than 64' % (t['count'], len(t['non_default_fov'])))
        for r in t['non_default_fov']:
            print('  %-44s %-40s FOV %s -> %s in %s s' % (r['block'], r['name'], r['FOVFrom'], r['FOVTo'], r['FOVChangeTime']))
    if a.code:
        print('== code constants (%s)' % EXE)
        for r in read_code():
            print('  %-18s %s %-4s %-10s %s %s' % (r['name'], r['va'], r['kind'], fmtv(r['value']) if r['value'] is not None else '',
                                                  'shipped' if r['shipped'] else 'BYTES DIFFER', r['what']))
    return 0


def cmd_export(a):
    c = collect(a.triggers)
    c['code'] = read_code()
    json.dump(c, open(a.o, 'w'), indent=1, default=str)
    print('wrote', a.o)
    return 0


def cmd_fov(a):
    w, h = (int(x) for x in a.res.lower().split('x'))
    print(json.dumps(dict(vanilla=fov_table(a.fov, w, h, a.ratioxy, a.widescreen_flag)), indent=1))
    if a.target_hfov:
        f = fov_for_hfov(a.target_hfov, w, h, a.ratioxy)
        print('fov setting for %.1f deg across %dx%d: %.3f (proxy: fov = %.2f)' % (a.target_hfov, w, h, f, f))
    for res in ((1024, 768), (1920, 1080), (2560, 1080), (3440, 1440), (5760, 1080)):
        r = fov_table(a.fov, res[0], res[1], a.ratioxy, False)
        print('  %4dx%-4d aspect %.3f: vertical %.2f, horizontal %.2f, vanilla cull %.2f -> %.2f deg uncovered each side'
              % (res[0], res[1], r['aspect'], r['vertical'], r['horizontal'], r['cull_horizontal_vanilla'], r['uncovered_each_side_deg']))
    return 0


# ------------------------------------------------------------------ selftest
def cmd_selftest(a):
    out = a.out or os.path.join(HERE, '_selftest')
    os.makedirs(out, exist_ok=True)
    ok = True
    # 1 identity: every collected camera value written back unchanged -> blocks byte-identical
    blocks = {}
    c = collect(False, blocks)
    idops = {}
    def ident(bn, frag, node, props):
        d = blocks[bn].doc(frag)
        n = d.find(node)
        for pr in props:
            v = d.get(n, pr)
            if v is not None:
                idops.setdefault(bn, []).append(dict(op='set', fragment=frag, entity='0x%08X' % n, prop=pr, value=v))
    ident(MAIN, PLAYER_FRAG, 'Animation/CameraCtrl', EASE + ['pos', 'orient'])
    for nm in PLAYER_NODES:
        ident(MAIN, PLAYER_FRAG, 'Animation/CameraCtrl/' + nm, ['pos', 'orient'])
    for t in c['cameradict']:
        ident(MAIN, 'CameraDict.fragment', {'name': t}, EASE)
    ident(MAIN, 'Overdose.scene', {'name': 'GameCamera'}, ['fov', 'nearclip', 'farclip'])
    for r in c['gamecamera']['nodes']:
        ident(MAIN, 'GameCamera.fragment', r['node'], EASE + ['pos', 'orient', 'DefaultFadeDistance'])
    for nm, r in c['vehicle_types'].items():
        ident(MAIN, 'VehicleDict.fragment', r['node'], EASE + ['pos', 'orient'])
    for r in c['rigs']:
        ident(r['block'], r['fragment'], r['node'], EASE + ['pos', 'orient'])
    nvals = sum(len(v) for v in idops.values())
    for bn, o in idops.items():
        b = blocks[bn]
        old, nb, docs, intended = ft.apply_ops(b.raw, b.ext, o, T())
        same = nb.serialize() == b.raw
        changed = sum(1 for d in docs.values() if d.log)
        print('identity %-40s %4d values -> block %s (%d fragments logged a change)' % (bn, len(o), 'IDENTICAL' if same else 'DIFFERS', changed))
        ok &= same and changed == 0
    print('identity total: %d values over %d blocks' % (nvals, len(idops)))
    # 2 a real edit through the full fragment-writer verification, read back
    spec = dict(description='selftest', player=dict(back=0.75), cameradict=dict(CharacterCombatCam=dict(MaxAngle=0.1)),
                vehicles=dict(back=1.0, types=dict(Sedan=dict(AngleEaseInSpeed=5.0))), mounted=dict(back=0.3),
                gamecamera=dict(farclip=1200.0), proxy=dict(fov=72, fov_scope=0, cull_fix=1, log=1))
    sp = os.path.join(out, 'selftest_edit.json')
    json.dump(spec, open(sp, 'w'), indent=1)
    rc = cmd_build(argparse.Namespace(edit=sp, out=os.path.join(out, 'build'), deploy=None))
    print('edit build + verify + read-back:', 'PASS' if rc == 0 else 'FAIL')
    ok &= rc == 0
    # 3 code: shipped bytes, simulated proxy redirects on a copy, undo -> identical
    d0 = exe_bytes()
    md5 = hashlib.md5(d0).hexdigest()
    print('exe md5', md5, 'OK' if md5 == EXE_MD5 else 'UNEXPECTED (other exe version: the proxy will skip changed sites)')
    rows = read_code(d0)
    allship = all(r['shipped'] for r in rows)
    print('code sites: %d, shipped bytes %s' % (len(rows), 'all match' if allship else 'MISMATCH'))
    ok &= allship and md5 == EXE_MD5
    d1 = bytearray(d0)
    for name, va, orig, kind, opo, what in CODE:
        o = va_off(va)
        if kind == 'imm':
            d1[o + opo:o + opo + 4] = struct.pack('<f', 1.2345)
        elif kind == 'mem':
            d1[o + opo:o + opo + 4] = struct.pack('<I', 0x10001000)
    changed = sum(1 for i in range(len(d0)) if d0[i] != d1[i]) if False else sum(a != b for a, b in zip(d0, d1))
    for name, va, orig, kind, opo, what in CODE:
        o = va_off(va)
        d1[o:o + len(orig) // 2] = bytes.fromhex(orig)
    print('simulated patch of every imm/mem site: %d bytes changed, undo -> %s' % (changed, 'IDENTICAL' if bytes(d1) == d0 else 'DIFFERS'))
    ok &= bytes(d1) == d0
    # 4 fov arithmetic
    t = fov_table(64, 1920, 1080)
    chk = abs(t['vertical'] - 50.22) < 0.01 and abs(remap(64, 72) - 72) < 1e-9 and remap(95, 72) > 95 and remap(25, 72) > 25
    print('fov arithmetic: 64 -> vertical %.3f, 16:9 horizontal %.3f, cull %.3f; remap(64->72) exact: %s' %
          (t['vertical'], t['horizontal'], t['cull_horizontal_vanilla'], 'OK' if chk else 'FAIL'))
    ok &= chk
    print('SELFTEST', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('show'); p.add_argument('--code', action='store_true'); p.add_argument('--triggers', action='store_true')
    p = sp.add_parser('export'); p.add_argument('-o', required=True); p.add_argument('--triggers', action='store_true')
    p = sp.add_parser('fov'); p.add_argument('--res', default='1920x1080'); p.add_argument('--fov', type=float, default=64.0)
    p.add_argument('--ratioxy', type=float, default=1.0); p.add_argument('--widescreen-flag', action='store_true')
    p.add_argument('--target-hfov', type=float)
    p = sp.add_parser('build'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    p = sp.add_parser('selftest'); p.add_argument('--out')
    a = ap.parse_args()
    try:
        import lowprio  # noqa: F401
    except Exception:
        pass
    return {'show': cmd_show, 'export': cmd_export, 'fov': cmd_fov, 'build': cmd_build, 'selftest': cmd_selftest}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
