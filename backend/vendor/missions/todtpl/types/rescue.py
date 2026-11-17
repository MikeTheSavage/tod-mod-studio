"""Template 'rescue': a hostage is held with guards; kill the guards and free him. (Mesa index 76.)

Template: registry slot 56 = SubM_27_Down_FreVir_Escort. Ported in the PROVEN 'free' mode (the hostage is FREED when the guards are dead; MISSION COMPLETE then).
The escorting variant (hostage walks to a destination) did not work in the Mesa and is not offered. The hostage path is still laid along `route` (decoration:
the template's path has 45 track points) and the guards are placed around the hostage.
"""
import math, sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'rescue'
TITLE = 'Rescue'
SUMMARY = 'A hostage is held by three guards.'
HOST_NEEDS = ['A spot for the hostage with room for three guards around it (a building interior works if the player can enter it).',
              'A camera zone and an "enable guards" zone near the entrance; a parking strip for the rest.',
              'Works in any new map or existing section. The hostage does not walk anywhere (free mode).']
LEGACY_INDEX = 76
LEGACY_ROOT = 'SubM_76_Mesa_RescueHostage.fragment'
GIVER_NAME = 'MESA_GIVER_RESCUE'
COMMON = dict(giver=(-14.0, -16.0, 8.0), name='RESCUE',
              description='Bandits hold a prisoner in the old house. Get in, kill the guards and set him free.',
              pass_score=30, silver_score=60, gold_score=120)
GUARD_KEYS = [0x401D28, 0x401D35, 0x401D31]          # Peter02, Peter05, Peter04: unique names, pistols
PAYOUT = [10, 29, 48]                                 # points of 1, 2, 3 guard kills (10 + 19 + 19)

_ROUTE_REL = [(-22.0, 19.0), (-24.5, 14.0), (-24.5, 9.0), (-20.0, 3.0), (-16.0, -2.0), (-18.0, -8.0), (-14.0, -12.0), (-8.0, -20.0),
              (-4.0, -26.0), (-1.0, -31.0), (0.0, -33.0)]

PARAMS = [
    P('hostage', 'point', lambda h, p: h.pt(-22, 19), 'Hostage position', '', group='Placement'),
    P('guards', 'points', lambda h, p: [h.pt(-27.5, 16), h.pt(-17.5, 16), h.pt(-22, 14)], 'Guard positions', '', min_len=3, max_len=3, group='Placement'),
    P('camera_zone', 'point', lambda h, p: h.pt(-24.5, 8), 'Camera zone', '', group='Placement'),
    P('enable_zone', 'point', lambda h, p: h.pt(-22, 16), 'Guard zone', '', group='Placement'),
    P('route', 'points', lambda h, p: [h.pt(x, z) for x, z in _ROUTE_REL], 'Hostage path', '', min_len=2, group='Placement', advanced=True),
    P('destination_npc', 'point', lambda h, p: h.pt(6, -33), 'Destination contact', '', group='Placement', advanced=True),
    P('marker_pos', 'point', lambda h, p: h.pt(0, -30), 'Task giver marker', '', group='Placement', advanced=True),
    P('vehicle_park', 'point', lambda h, p: h.pt(30, 36), 'Vehicle parking', '', group='Placement', advanced=True),
    P('zone_park', 'point', lambda h, p: h.pt(-36, 36), 'Zone parking', '', group='Placement', advanced=True),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 33, 38, 38.5)), 'Spare strip', '', group='Placement', advanced=True),
    P('guards_to_kill', 'int', 3, 'Guards to kill', '', min=1, max=3, group='Settings'),
    P('enemy_health', 'float', 0.3, 'Guard health', '', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.03, 'Guard damage', '', min=0.0, max=3.0, group='Settings'),
    P('text_find', 'text', 'Find the hostage in the house', 'Objective 1 text', '', group='Texts', max_len=70),
    P('text_escort', 'text', 'Kill the guards and free the hostage', 'Objective 2 text', '', group='Texts', max_len=70),
]


def constraints(p, host):
    m = []
    k = p['guards_to_kill']
    if p['pass_score'] > PAYOUT[k - 1]:
        m.append(('error', 'Killing %d guard%s pays about %d points but the pass score is %d: the mission would end in "YOU NEED AT LEAST %d POINTS". Lower the pass score or raise the kills.' % (k, '' if k == 1 else 's', PAYOUT[k - 1], p['pass_score'], p['pass_score'])))
    return m


def route_points(route, n):
    seg = [math.dist((route[i][0], route[i][2]), (route[i + 1][0], route[i + 1][2])) for i in range(len(route) - 1)]
    tot = sum(seg)
    out = []
    for k in range(n):
        d = tot * k / (n - 1)
        i = 0
        while i < len(seg) - 1 and d > seg[i]:
            d -= seg[i]; i += 1
        t = min(1.0, d / seg[i])
        out.append((route[i][0] + (route[i + 1][0] - route[i][0]) * t, route[i][2] + (route[i + 1][2] - route[i][2]) * t))
    return out


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    guards = dict(zip(GUARD_KEYS, p['guards']))

    def design(ctx):
        from .. import tpl_env
        E = tpl_env.get()
        W = ctx.world
        G = lambda pt, dy=0.0: host.gy(pt[0], pt[2], pt[1]) + dy
        hs = p['hostage']
        hy = G(hs, 0.8)
        real = ctx.one(name='SubM_27_Down_FreVir_Escort_American_TOURIST01')
        fake = ctx.one(name='Fake_vergillio')
        for c in (real, fake):
            ctx.move(c, (hs[0], hy, hs[2]))
            for s in ctx.siblings(c):
                if s[1].startswith(('weapon_placeholder', 'wear_placeholder')):
                    ctx.move(s, (hs[0], hy, hs[2]))
        path = [n for n in ctx.nodes() if n[3] == 0x401C66][0]
        tps = [n for n in ctx.nodes() if n[2] == path[2] and ctx.parent_key(n) == path[3] and n[1].startswith('TrackPoint')]
        pts = route_points(p['route'], len(tps))
        for n, q in zip(tps, pts):
            ctx.move(n, (q[0], host.gy(q[0], q[1]) + 0.6, q[1]))
        ctx.log.append('hostage path: %d track points laid along %d route corners' % (len(tps), len(p['route'])))
        chars = [c for c in ctx.find(type='character_placeholder') if c not in (real, fake)]
        enabler = [c for c in chars if str(c[4]).endswith('Enabler_Guy')][0]
        chars = [c for c in chars if c is not enabler]
        keep = [c for c in chars if c[3] in guards]
        spare = [c for c in chars if c[3] not in guards]
        assert len(keep) == len(guards)
        kept_folders = {ctx.parent_key(c) for c in keep}
        for c in keep:
            g = guards[c[3]]
            ctx.place_enemy(c, (g[0], g[2]), y=G(g, 0.8), health_mod=p['enemy_health'], damage_mod=p['enemy_damage'], damage_modify=None)
            ctx.set(c, 'MissionObjectiveKill', True)
        vp = p['vehicle_park']
        vy = G(vp)
        veh_kids = set()
        for v in ctx.find(type='vehicle_placeholder'):
            vpos = ctx._pos_of(v)
            vx, vz = W.snap(vp[0] + 3.0 * (v[0] % 5), vp[2], margin=0.5)
            d = (vx - vpos[0], vy + 0.6 - vpos[1], vz - vpos[2])
            for c in [c for c in spare if any(a_[3] == v[3] and a_[2] == v[2] for a_ in ctx.chain(c))]:
                ctx.place_enemy(c, (vp[0] - 10.0 - d[0], vp[2] - d[2]), y=(vy + 0.8) - d[1])
                veh_kids.add(c[3])
            ctx.move(v, (vx, vy + 0.6, vz))
        rest = [c for c in spare if c[3] not in veh_kids]
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in rest], region=p['spare_region'], min_sep=0.9, margin=0.3)
        for c, xz in zip(rest, sp):
            ctx.place_enemy(c, xz, damage_modify=None)
        for c in spare:
            pk = ctx.parent_key(c)
            if pk in kept_folders:
                raise RuntimeError('spare enemy shares a folder with a guard')
            folder = [x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0]
            ctx.disable_folder(folder)
        dn = p['destination_npc']
        ctx.move(enabler, (dn[0], G(dn, 0.8), dn[2]))
        for n in ctx.find(name='All_Enemies_Kill_Completed', type='Trigger_Root'):
            if abs(float(ctx.get(n, 'ConditionsNeeded', 0)) - 4.0) < 0.01:
                ctx.set(n, 'ConditionsNeeded', 3.0)
        dead = 'MESA_UNUSED_TARGET'
        ctx.retarget_names({'Enemies_AT_Backup': dead, 'Enemies_Return': dead, 'SubM_27_Down_FreVir_Escort_Second_Enemy_Team': dead,
                            'Trigger_Car1': dead, 'SubM_27_Down_MexSho_GunKill_Pick_Up': dead, 'SubM_27_Down_MexSho_GunKill_AI_Vehicle3': dead},
                           props=('TargetName',), classes=('Trigger_Activate_Enable_Disable', 'Trigger_Activate_Trig_Noaction_Reactivate'))
        for n in ctx.find(name='Enable_AT_enemies', type='Trigger_Activate_Enable_Disable'):
            if int(ctx.get(n, 'ActionType', 5)) == 6:
                ctx.set(n, 'TargetName', dead)
        S37, F37 = E.SHARED + 'subm_37_down_move_kill.mission', 'SubM_37_Down_Move_Kill.fragment'
        hostn = ctx.one(name='SubM_27_Down_FreVir_Escort_TRIGGERS_and_CONDITIONS')
        txt = [n for n in ctx.nodes() if n[4] == 'Activate_TextEffect_FINISH'][0]
        ctx.B.append(ctx.NEW, 'rescue_kill_root', (S37, F37, 0x40009B), parent=('ref', ctx.new_root, hostn[3]), name='RESCUE_Guards_Dead', sets={'Reactivate': False})
        ctx.B.append(ctx.NEW, 'rescue_kill_cond', (S37, F37, 0x40009C), parent=('new', 'rescue_kill_root'), name='RESCUE_COND_3_kills', sets={'TrigAmount': p['guards_to_kill']})
        ctx.B.append(ctx.NEW, 'rescue_kill_end', (S37, F37, 0x4000A4), parent=('new', 'rescue_kill_root'), name='RESCUE_Mission_COMPLETE', sets={'Delay': 3.0})
        ctx.B.append(ctx.NEW, 'rescue_kill_text', (ctx.NEW, ctx.frag(txt[2]), txt[3]), parent=('new', 'rescue_kill_root'), name='RESCUE_FINISH_text')
        cz_, az_ = p['camera_zone'], p['enable_zone']
        cz = ctx.one(name='Camera_Activate_TRIGGER')
        ctx.place(cz, (cz_[0], G(cz_, 0.8), cz_[2])); ctx.resize_box(cz, 8.0, 4.0, 6.0)
        az = ctx.one(name='Enable_AT', type='Trigger_Root')
        ctx.place(az, (az_[0], G(az_, 0.8), az_[2])); ctx.resize_box(az, 8.0, 4.0, 4.0)
        zp = p['zone_park']
        park = [(zp[0] + 3.0 * i, G(zp, 0.8), zp[2]) for i in range(12)]
        pi = 0
        for nm in ('Activae_Enable_Enemies', 'Trigger_Car1', 'Camera_Activate_TRIGGERB'):
            z = ctx.one(name=nm, type='Trigger_Root')
            ctx.place(z, park[pi]); ctx.resize_box(z, 2.0, 2.0, 2.0); pi += 1
        ctx.move(ctx.one(name='Marker_Round', type='generic_object_effect(Sprite)'), (cz_[0], G(cz_, 0.15), cz_[2]))
        ctx.move(ctx.one(name='Marker_Cone_', type='generic_object_effect(Model)'), (cz_[0], G(cz_, 3.0), cz_[2]))
        mk = p['marker_pos']
        ctx.move(ctx.one(name='SubM_27_Taskgiver_Marker'), (mk[0], G(mk, 0.2), mk[2]))
        ctx.retarget_names({'SubM_27_FreeVirgillio_OBJ': O('RESCUE_OBJ_FREE'), 'SubM_27_FreeVirgillio_OBJ2': O('RESCUE_OBJ_ESCORT')},
                           props=('TargetName', 'SpecificActivator'))
        ctx.retarget_camera_cuts()
        k = 0
        bd = host.bounds
        for n in ctx.find(type='TrackPoint'):
            q = ctx._pos_of(n)
            if not (bd[0] <= q[0] <= bd[2] and bd[1] <= q[2] <= bd[3]):
                ctx.move(n, (host.cx + 2.0 * (k % 5), host.gy(host.cx, host.cz + 30.0) + 6.0 + (k // 5), host.cz + 30.0)); k += 1
        ctx.log.append('far track points moved: %d' % k)

    template = dict(slot=56, block='subm_27_down_frevir_escort.mission', root='SubM_27_Down_FreVir_Escort.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('find', p['text_find']), ('escort', p['text_escort'])],
                     [{'DisplayText': '@find', 'name': O('RESCUE_OBJ_FREE')}, {'DisplayText': '@escort', 'name': O('RESCUE_OBJ_ESCORT')}], design,
                     ALLOW_UNRESOLVED=['MESA_UNUSED_TARGET', 'Condition_SubM_27_Down_FreVir_Escort_Trigger_MISSION_COMPLETED',
                                       'Door_A_SubM_33_Down_Kill_Kill', 'ElMachoBar_FrontDoor_Street', 'Trigger_door_close_a_smm33', 'TrafficPoints_M02S02'])
