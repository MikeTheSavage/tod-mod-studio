"""Template 'race': a timed on-foot run through nine checkpoints (one lap). (Mesa index 73.)

Template: registry slot 35 = SubM_06_Indu_ChePoi_Race ("JUNKYARD RACE"). TRIG_ChkPoint_NN (sphere, one condition: the player enters, no vehicle needed) ->
counter +1, add time, next gate; CP09 ends the race after TrigAmount laps (here 1). Start clock 'Points' in 1/100 s; the add-time action gives about +3 s per gate
whatever its Points are (measured), so the start time carries the tuning.
"""
import math, sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'race'
TITLE = 'Checkpoint Run'
SUMMARY = 'A timed on-foot run through nine checkpoints; every checkpoint adds time.'
HOST_NEEDS = ['Nine checkpoints you place (ground or deck); the player must be able to walk from each to the next in a straight leg.',
              'A free spot for the leftover Industrial-map props (a "park" point, never seen).',
              'Works in any new map or existing section; decks and ramps must come from the host map itself (give the gate its own y).']
LEGACY_INDEX = 73
LEGACY_ROOT = 'SubM_73_Mesa_ChkPointRun.fragment'
GIVER_NAME = 'MESA_GIVER_RACE'
COMMON = dict(giver=(24.0, -26.0, 8.0), name='CHECKPOINT RUN',
              description='Run through all nine checkpoints around the compound, up the ramp and along the walkway, before the clock runs out. Every checkpoint adds time.',
              load_mid='ON FOOT', load_low='RUN + CLIMB + RUN', pass_score=0, silver_score=300, gold_score=600)

_GATES_REL = [(35.0, -35.0), (35.0, -18.0), (35.0, 22.0), (35.0, -10.0), (34.0, -36.0), (-32.0, -33.0), (-33.0, 32.0), (-6.0, 32.0), (-6.0, -22.0)]

PARAMS = [
    P('gates', 'points', lambda h, p: [h.pt(x, z, None) for x, z in _GATES_REL], 'Checkpoints', '', min_len=9, max_len=9, group='Placement'),
    P('gate_radii', 'floats', [6.0] * 9, 'Checkpoint radius', '', min_len=9, max_len=9, group='Placement'),
    P('park', 'point', lambda h, p: h.pt(60, 60, None), 'Parking spot', '', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(24, -5), 'Parked task giver', '', group='Placement', advanced=True),
    P('goodie_start', 'point', lambda h, p: h.pt(23, -30), 'Goodie trail start', '', group='Placement', advanced=True),
    P('deck_rect', 'rect', lambda h, p: list(h.rr(32, -24, 38, 29)), 'Deck rectangle', '', group='Placement', advanced=True),
    P('deck_height', 'float', 4.2, 'Deck goodie height', '', min=0.0, max=20.0, unit='m', group='Placement', advanced=True),
    P('start_time', 'float', 100.0, 'Start time', '', min=10.0, max=900.0, unit='s', group='Settings'),
    P('add_points', 'int', 900, 'Time added per checkpoint', '', min=0, max=100000, group='Settings', advanced=True),
    P('text_run', 'text', lambda h, p: 'Clear all %d checkpoints before the time runs out' % len(p['gates']), 'Objective text', '', group='Texts', max_len=70),
]


def constraints(p, host):
    m = []
    g = p['gates']
    for i in range(9):
        a, b = g[i], g[(i + 1) % 9]
        d = math.hypot(a[0] - b[0], a[2] - b[2])
        if d < 6.0:
            m.append(('warn', 'Checkpoints %d and %d are only %.1f m apart; the player may trigger both at once.' % (i + 1, (i + 1) % 9 + 1, d)))
    total = sum(math.hypot(g[i][0] - g[(i + 1) % 9][0], g[i][2] - g[(i + 1) % 9][2]) for i in range(8))
    need = total / 5.3
    allowed = p['start_time'] + 8 * 3.0
    if need > allowed:
        m.append(('warn', 'The route is about %.0f m: at running speed that needs about %.0f s but the clock allows %.0f s. Raise the start time.' % (total, need, allowed)))
    for pt in g:
        if host is not None and not host.inside(pt[0], pt[2], 0.0):
            m.append(('warn', 'A checkpoint at (%.0f, %.0f) is outside the play area of the host.' % (pt[0], pt[2])))
            break
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    gates, radii = p['gates'], p['gate_radii']

    def yaw_quat(theta):
        return (0.0, math.sin(theta / 2.0), 0.0, math.cos(theta / 2.0))

    def design(ctx):
        W = ctx.world
        pts = [(g[0], host.gy(g[0], g[2], g[1]) + 0.3, g[2]) for g in gates]
        for i in range(len(gates)):
            nn = i + 1
            grp = ctx.one(name='CheckPoint_%02d' % nn)
            trg = ctx.one(name='TRIG_ChkPoint_%02d' % nn)
            pp = pts[i]
            nx = pts[(i + 1) % len(pts)]
            theta = math.atan2(nx[0] - pp[0], nx[2] - pp[2])
            ctx.move(grp, pp, rot=yaw_quat(theta))
            ctx.move(trg, pp)
            ctx.set(trg, 'radius', float(radii[i]))
        ctx.set(ctx.one(name='COND_NoOfLaps'), 'TrigAmount', 1)
        ctx.set(ctx.one(name='ACT_CountDown'), 'Points', int(round(p['start_time'] * 100)))
        ctx.set(ctx.one(name='ACT_AddTime'), 'Points', p['add_points'])
        ctx.retarget_names({'SubM_06_Race_OBJ': O('RACE_OBJ_GATES')}, props=('TargetName', 'SpecificActivator'))
        ctx.set(ctx.one(name='COND_MissionStart'), 'SpecificActivator', '')
        pt = ctx.one(name='Activate_Pause_Text')
        ctx.set(pt, 'Delay', 0.5); ctx.set(pt, 'UsePauseMode', False); ctx.set(pt, 'StayTime', 4.0)
        ctx.retarget_camera_cuts(names=['ACT_Cam01'])
        ctx.retarget_names({'TrafficPoints_M03S01': 'Forklift', 'TRIG_Forklift': 'Goodies'}, props=('TargetName',),
                           classes=('Trigger_Activate_Enable_Disable',))
        pk = p['park']
        park = (pk[0], pk[2])
        py = host.gy(pk[0], pk[2], pk[1]) if pk[1] is not None else host.gy(pk[0], pk[2]) + 1.0
        wrong = ctx.one(name='TRIG_WRONG_WAY')
        ctx.move(wrong, (park[0], py, park[1]))
        ctx.set(wrong, 'flags', int(ctx.get(wrong, 'flags', 0)) | 1)
        fk = ctx.one(name='TRIG_Forklift')
        ctx.move(fk, (park[0] - 10, py, park[1]))
        for nm in ('Forklift', 'Mechanic'):
            ctx.disable_folder(ctx.one(name=nm, type='Folder'))
        for k, v in enumerate(ctx.find(type='vehicle_placeholder')):
            ctx.move(v, (park[0] - 6.0 + 4.0 * k, py, park[1] + 6.0))
        ch = ctx.one(name='Mech01')
        ctx.place_enemy(ch, (park[0] + 6.0, park[1] - 6.0), y=py)
        tps = ctx.find(type='TrackPoint')
        for k, t in enumerate(tps):
            ctx.move(t, (park[0] + 6.0 + 1.5 * k, py, park[1] - 6.0))
        tg = ctx.one(name='Enabler_SM06')
        gp = p['giver_npc_park']
        ctx.place_enemy(tg, (gp[0], gp[2]))
        goodies = ctx.find(type='goodie_placeholder')
        gs = p['goodie_start']
        s3 = (gs[0], host.gy(gs[0], gs[2], gs[1]) + 0.8, gs[2])
        legs = [(s3, pts[0])] + [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        dr = p['deck_rect']
        for k, g in enumerate(goodies):
            a, b = legs[k % len(legs)]
            t = 0.5 if k < len(legs) else 0.25
            x, z = a[0] + (b[0] - a[0]) * t, a[2] + (b[2] - a[2]) * t
            on_deck = dr[2] > dr[0] and dr[0] < x < dr[2] and dr[1] < z < dr[3]
            gy0 = host.gy(x, z)
            ctx.move(g, (x, (gy0 + p['deck_height']) if on_deck else (gy0 + 1.3), z))
        L.park_strays(ctx, (park[0] - 5.0, park[1] + 12.0))

    template = dict(slot=35, block='subm_06_indu_chepoi_race.mission', root='SubM_06_Indu_ChePoi_Race.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('run', p['text_run'])],
                     [{'DisplayText': '@run', 'MaxCounter': len(gates), 'name': O('RACE_OBJ_GATES')}], design)
