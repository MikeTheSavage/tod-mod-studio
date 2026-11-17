"""Template 'capture': take three flag points by standing in them; every capture sends a counter-attack wave. (Mesa index 53.)

Template: registry slot 49 = SubM_20_Down_JavPer_Kill (the frenzy template). The hold-in-zone trio is the shipped Meat Factory 'killer' pattern rebuilt from clones of nodes of
this block: CAP_ENTER<i> (enable CAP_HOLD<i>), CAP_LEAVE<i> (disable it), CAP_HOLD<i> (disabled at start, TrueOn 14 IntervalTrue = hold seconds -> objective +1, text, wave, off).
Failure: the countdown or the player's death. No kill counting.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'capture'
TITLE = 'Capture Points'
SUMMARY = 'Take three flag points by standing in each one until it is yours; every capture sends a counter-attack.'
HOST_NEEDS = ['Three flag spots of free, flat ground, at least 10 m apart (an 8 m box each plus room for 3-4 bandits 6 m around it).',
              'A parking spot for the template\'s Downtown walk-in boxes and a spare strip (disabled, never seen).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 53
LEGACY_ROOT = 'SubM_53_Mesa_CapPoints01.fragment'
GIVER_NAME = 'MESA_GIVER_CAPTURE'
COMMON = dict(giver=(12.0, -2.0, 6.0), name='CAPTURE POINTS',
              description='Three flag points hold the compound. Stand in each one until it is yours. Every point you take sends a counter-attack at the others. Take all three before the clock runs out.',
              load_mid='TAKE THE GROUND', load_low='HOLD THREE POINTS', pass_score=0, silver_score=200, gold_score=400)
WAVES = [('SubM_20_Down_JavPer_Kill_LEVEL02', ['Enemy_07', 'Enemy_08', 'Enemy_09'], [1, 1, 2]),
         ('SubM_20_Down_JavPer_Kill_LEVEL04', ['@19a', '@19b', 'Enemy_20', 'Enemy_21'], [0, 0, 2, 2]),
         ('SubM_20_Down_JavPer_Kill_LEVEL05', ['Enemy_25', 'Enemy_26', 'Enemy_27', 'Enemy_28'], [0, 0, 1, 1])]
GUARDS = ['Enemy_01', 'Enemy_02', 'Enemy_03', 'Enemy_04']
GUARD_AT = [0, 0, 1, 1]
RING = [(6.0, 0.0), (-6.0, 0.0), (0.0, 6.0), (0.0, -6.0)]
MIN_HOLD = 2.0

PARAMS = [
    P('points', 'points', lambda h, p: [h.pt(-30, 30), h.pt(20, 32), h.pt(-24, -32)], 'Capture points', 'Clear ground around each', min_len=3, max_len=3, group='Placement'),
    P('zone_size', 'float', 8.0, 'Capture box size', '', min=4.0, max=20.0, unit='m', group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', '', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', '', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(12, 5), 'Parked task giver', '', group='Placement', advanced=True),
    P('hold_seconds', 'float', 4.0, 'Seconds to capture', 'Seconds the player must stay inside a capture box to take the point. At least %g.' % MIN_HOLD, min=MIN_HOLD, max=120.0, unit='s', group='Settings'),
    P('countdown', 'float', 120.0, 'Time limit', '', min=20.0, max=900.0, unit='s', group='Settings'),
    P('enemy_health', 'float', 0.3, 'Bandit health', '', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.1, 'Bandit damage', '', min=0.0, max=3.0, group='Settings'),
    P('text_cap', 'text', 'Capture all three points before the time runs out', 'Objective text', '', group='Texts', max_len=70),
    P('text_cap_cnt', 'text', '%0 out of %1 points captured', 'Counter text', '', group='Texts', max_len=50),
    P('text_held', 'text', 'Hold the point until it is captured', 'Hold hint', '', group='Texts', max_len=50),
    P('text_captured', 'text', 'POINT CAPTURED! Counter-attack incoming', 'Capture text', '', group='Texts', max_len=50),
]


def constraints(p, host):
    m = []
    pts = p['points']
    for i in range(3):
        for j in range(i + 1, 3):
            d = ((pts[i][0] - pts[j][0]) ** 2 + (pts[i][2] - pts[j][2]) ** 2) ** 0.5
            if d < 10.0:
                m.append(('error', 'Capture points %d and %d are only %.1f m apart; keep them at least 10 m apart.' % (i + 1, j + 1, d)))
    if 3 * p['hold_seconds'] + 20.0 > p['countdown']:
        m.append(('warn', 'Three captures of %g s plus walking may not fit in %g s.' % (p['hold_seconds'], p['countdown'])))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx

    def design(ctx):
        W = ctx.world
        K = {x[3]: x for x in ctx.nodes()}.__getitem__
        chars, by_level = L.enemy_levels(ctx)
        pts, taken = [], []
        for q in p['points']:
            pt = W.snap(q[0], q[2], margin=5.0, taken=taken, min_sep=10.0)
            pts.append(pt); taken.append(pt)
        ctx.log.append('capture points %s' % pts)
        used, ring_n = [], [0, 0, 0]

        def stand(c, pi):
            k = ring_n[pi]; ring_n[pi] += 1
            ox, oz = RING[k % 4]
            xz = W.snap(pts[pi][0] + ox, pts[pi][1] + oz, margin=1.5, taken=taken, min_sep=2.5)
            taken.append(xz)
            ctx.place_enemy(c, xz, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
            ctx.set_weapons(c, 0)
            used.append(c)
        for nm, pi in zip(GUARDS, GUARD_AT):
            stand(L.pick_enemy(by_level, 'SubM_20_Down_JavPer_Kill_LEVEL01', nm), pi)
        for level, names, at in WAVES:
            for nm, pi in zip(names, at):
                stand(L.pick_enemy(by_level, level, nm), pi)
        spares = [c for c in chars if c not in used]
        L.park_spares(ctx, spares, p['spare_region'])
        pk = p['park']
        park = (pk[0], pk[2])
        L.park_javper_boxes(ctx, park)
        ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
        py = host.gy(park[0], park[1]) + 1.0
        for k, n in enumerate([K(0x400594), K(0x400595), K(0x400596)]):
            ctx.move(n, (park[0] + 4.0 + 3.0 * k, py, park[1] + 1.0))
            ctx.set(n, 'flags', int(ctx.get(n, 'flags', 0)) | 1)
        ctx.set(ctx.one(name='Activate_Countdown'), 'Time', float(p['countdown']))
        ctx.retarget_names({'SubM_20_Pistoleros_OBJ': O('CAPTURE_OBJ_POINTS')}, props=('TargetName', 'SpecificActivator'))
        ac = K(0x401836)
        ctx.set(ac, 'TrueOn', 2); ctx.set(ac, 'SpecificActivator', O('CAPTURE_OBJ_POINTS')); ctx.set(ac, 'TrigAmount', 1)
        ctx.set(K(0x40183f), 'flags', int(ctx.get(K(0x40183f), 'flags', 0)) | 1)
        ctx.set(K(0x40183d), 'Delay', 5.0)
        tg = ctx.find(regex=r'loader_Guy')[0]
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5)
        ctx.place_enemy(tg, (tx, tz))
        D_BOX, D_COND, D_ENDIS = K(0x401809), K(0x40180a), K(0x40180b)
        D_OBJ, D_TEXT, D_RADAR = K(0x401841), K(0x40058f), K(0x400582)
        D_SPR, D_CONE, D_TRIG = K(0x400595), K(0x400594), K(0x4005e4)
        ms, objs, start = K(0x4017fe), K(0x400593), K(0x400580)

        def _clone(uid, donor, parent, name=None, sets=None, pos=None):
            par = ('new', parent) if isinstance(parent, str) else ('ref', ctx.frag(parent[2]), parent[3])
            ctx.B.append(ctx.NEW, uid, (ctx.NEW, ctx.frag(donor[2]), donor[3]), parent=par, name=name, sets=dict(sets or {}), pos=pos)
        _clone('cap_hint', D_TEXT, start, name='CAP_HINT', sets={'UseFeedbackText': True, 'FeedbackText': ctx.texts['@held'], 'Delay': 4.0, 'StayTime': 4.0})
        lvl_tmpl = {}
        for a in ctx.find(type='Trigger_Activate_Enable_Disable'):
            t = ctx.get(a, 'TargetName', '')
            if t.startswith('SubM_20_Down_JavPer_Kill_LEVEL') and t not in lvl_tmpl:
                lvl_tmpl[t] = a
        ZONE = p['zone_size']
        size = dict(width=ZONE, height=4.5, length=ZONE)
        HOLD = p['hold_seconds']
        for i, (px, pz) in enumerate(pts):
            u = 'cap%d_' % i
            g0 = host.gy(px, pz, p['points'][i][1])
            pos = [px, g0 + 2.0, pz]
            _clone(u + 'spr', D_SPR, objs, name='CAP_RING%d' % i, sets={'flags': 256, 'sprite_size': [9.0, 9.0, 1.0], 'opacity': 0.6}, pos=[px, g0 + 0.15, pz])
            _clone(u + 'cone', D_CONE, objs, name='CAP_CONE%d' % i, sets={'flags': 2050}, pos=[px, g0 + 1.2, pz])
            _clone(u + 'enter', D_BOX, ms, name='CAP_ENTER%d' % i, sets=dict(size, flags=256, Reactivate=False), pos=pos)
            _clone(u + 'enterc', D_COND, u + 'enter', name='CAP_ENTER_C%d' % i, sets={'TrueOn': 1})
            _clone(u + 'enter_on', D_ENDIS, u + 'enter', name='CAP_ENTER_ON%d' % i, sets={'ActionType': 5, 'TargetName': 'CAP_HOLD%d' % i})
            _clone(u + 'leave', D_BOX, ms, name='CAP_LEAVE%d' % i, sets=dict(size, flags=256, Reactivate=True, ReactivateDelay=0.5), pos=pos)
            _clone(u + 'leavec', D_COND, u + 'leave', name='CAP_LEAVE_C%d' % i, sets={'TrueOn': 0})
            _clone(u + 'leave_off', D_ENDIS, u + 'leave', name='CAP_LEAVE_OFF%d' % i, sets={'ActionType': 6, 'TargetName': 'CAP_HOLD%d' % i})
            _clone(u + 'hold', D_BOX, ms, name='CAP_HOLD%d' % i, sets=dict(size, flags=257, Reactivate=True, ReactivateDelay=0.5), pos=pos)
            _clone(u + 'leave_rearm', D_TRIG, u + 'leave', name='CAP_LEAVE_REARM%d' % i, sets={'ActionType': 29, 'ActivateWho': 3, 'TargetName': 'CAP_ENTER%d' % i, 'Delay': 0.3})
            _clone(u + 'holdc', D_COND, u + 'hold', name='CAP_HOLD_C%d' % i, sets={'TrueOn': 14, 'IntervalTrue': HOLD})
            _clone(u + 'cnt', D_OBJ, u + 'hold', name='CAP_COUNT%d' % i, sets={'TargetName': O('CAPTURE_OBJ_POINTS')})
            _clone(u + 'tx', D_TEXT, u + 'hold', name='CAP_TXT%d' % i, sets={'UseFeedbackText': True, 'FeedbackText': ctx.texts['@captured'], 'Delay': 0.4, 'StayTime': 4.0})
            level = WAVES[i][0]
            _clone(u + 'wave', lvl_tmpl[level], u + 'hold', name='CAP_WAVE%d' % i, sets={'Delay': 1.0})
            _clone(u + 'rad_off', D_RADAR, u + 'hold', name='CAP_RADAR_OFF%d' % i, sets={'ActionType': 27, 'TargetName': 'CAP_ENTER%d' % i, 'RadarType': 2, 'MapRelation': -1})
            for what, nm in (('spr', 'CAP_RING%d' % i), ('cone', 'CAP_CONE%d' % i), ('e', 'CAP_ENTER%d' % i), ('l', 'CAP_LEAVE%d' % i), ('h', 'CAP_HOLD%d' % i)):
                _clone(u + 'off_' + what, D_ENDIS, u + 'hold', name='CAP_OFF_%s%d' % (what.upper(), i),
                       sets={'ActionType': 6, 'TargetName': nm, 'Delay': 0.8 if what == 'h' else 0.2})
            _clone(u + 'rad_on', D_RADAR, start, name='CAP_RADAR_ON%d' % i, sets={'TargetName': 'CAP_ENTER%d' % i, 'RadarType': 2, 'MapRelation': -1, 'Delay': 1.0})
        L.park_strays(ctx, (park[0] - 2.0, park[1]))

    template = dict(slot=49, block='subm_20_down_javper_kill.mission', root='SubM_20_Down_JavPer_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('cap', p['text_cap']), ('cap_cnt', p['text_cap_cnt']), ('held', p['text_held']), ('captured', p['text_captured'])],
                     [{'DisplayText': '@cap', 'CounterText': '@cap_cnt', 'WriteOutOf': True, 'MaxCounter': 3, 'name': O('CAPTURE_OBJ_POINTS')}], design,
                     ALLOW_UNRESOLVED=['Chunk_17_StandardGarageDoor_01', 'TRIG_OpenChunk17GarageDoor', 'TRIG_CloseChunk17GarageDoor', 'Chunk18_Elevator_Door01',
                                       'Elevator_chunk18A', 'Marker_Round_sm20'])
