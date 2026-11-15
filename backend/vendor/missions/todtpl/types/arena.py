"""Template 'arena': survive the fight while the outer rings of the arena catch fire one after another. (Mesa index 29.)

Template: registry slot 49 = SubM_20_Down_JavPer_Kill (like 'frenzy'). 12 bandits in 3 timed waves; when the countdown runs out the nested mission end is a SUCCESS
("you survived"). Three fire rings (square rings, Chebyshev distance from the arena centre): each ring = 4 strip boxes whose actions are the stunt block's 'feedback text'
+ 'MISSION FAILED'; touching a live ring = failed. Rings are enabled by timed actions; WARN seconds before: fire particles + text.
"""
import math, sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'arena'
TITLE = 'Shrinking Arena'
SUMMARY = 'Survive a courtyard fight while three square rings of fire close in from the edge. Touching a burning ring fails the mission.'
HOST_NEEDS = ['A flat, free SQUARE area of about 80 x 80 m (the outer ring edge) around the arena centre; rings are drawn over it and fire emitters are placed on its ground.',
              'The player must be able to stand in the middle (within the innermost ring edge). Obstacles inside the rings are fine but burn with the rest.',
              'Works in any new map or existing section with a big flat square.']
LEGACY_INDEX = 29
LEGACY_ROOT = 'SubM_29_Mesa_ArenaShrink.fragment'
GIVER_NAME = 'MESA_GIVER_ARENA'
COMMON = dict(giver=(-2.0, 26.0, 6.0), name='SHRINKING ARENA',
              description='The courtyard is burning from the walls inward. Hold the middle, gun down the bandits and outlast the fire.',
              load_mid='FIRE RINGS', load_low='SURVIVE + SHOOT', pass_score=0, silver_score=300, gold_score=600)
WAVES = [('SubM_20_Down_JavPer_Kill_LEVEL01', ['Enemy_01', 'Enemy_02', 'Enemy_03', 'Enemy_04']),
         ('SubM_20_Down_JavPer_Kill_LEVEL02', ['Enemy_07', 'Enemy_08', 'Enemy_09', 'Enemy_10']),
         ('SubM_20_Down_JavPer_Kill_LEVEL04', ['@19a', '@19b', 'Enemy_20', 'Enemy_21'])]
OFFSETS = [(-2.5, -2.5), (2.5, -2.5), (-2.5, 2.5), (2.5, 2.5)]
MM010 = 'data_pc/overdose_the_game/overdose/shared/mm010_ernestocruz.mission'
MM010_FRAG = 'MM010_ErnestoCruz.fragment'
SRC_EMITTER, SRC_PARTICLE = 0x40012E, 0x40025E
STUNT = 'data_pc/overdose_the_game/overdose/shared/subm_37_down_move_kill.mission'
STUNT_FRAG = 'SubM_37_Down_Move_Kill.fragment'
BOX_H = 8.0
WARN = 8.0

PARAMS = [
    P('center', 'point', lambda h, p: [h.cx, None, h.cz], 'Arena centre', 'Centre of the arena (x, y, z). The rings are squares around it.', group='Placement'),
    P('outer_edge', 'float', lambda h, p: 40.0 * h.scale, 'Outer radius', 'Half-width in metres of the outermost ring edge (the arena\'s outer wall).', min=10.0, max=200.0, unit='m', group='Placement'),
    P('ring_edges', 'floats', lambda h, p: [28.0 * h.scale, 20.0 * h.scale, 13.0 * h.scale], 'Ring inner edges', 'Inner edge (half-width from the centre, metres) of ring 1, 2 and 3. Ring 1 burns first and is the widest; they must shrink.', min_len=3, max_len=3, group='Placement'),
    P('wave_centres', 'points', lambda h, p: [h.pt(-8, 4), h.pt(9, -4), h.pt(0, 9)], 'Wave positions', 'Centre of each of the three groups of four bandits.', min_len=3, max_len=3, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not fight are parked (disabled).', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', 'Where the template\'s Downtown walk-in boxes are parked (disabled).', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-24, -6), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move bandits that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('kills', 'int', 12, 'Kills that end it', 'Killing this many bandits also wins (12 bandits arrive).', min=1, max=12, group='Settings'),
    P('countdown', 'float', 105.0, 'Survive time', 'Seconds to survive; when the clock runs out the mission is a success.', min=20.0, max=900.0, unit='s', group='Settings'),
    P('ring_times', 'floats', [25.0, 50.0, 75.0], 'Ring times', 'Seconds after the start at which ring 1, 2, 3 turn deadly (the fire starts 8 s before).', min_len=3, max_len=3, group='Settings'),
    P('wave_delays', 'floats', [0.0, 18.0, 36.0], 'Wave delays', 'Seconds after the start at which each wave arrives.', min_len=3, max_len=3, group='Settings'),
    P('fail_delay', 'float', 1.5, 'Burn delay', 'Seconds between touching a live ring and MISSION FAILED.', min=0.0, max=10.0, unit='s', group='Settings', advanced=True),
    P('enemy_health', 'float', 0.3, 'Bandit health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.3, 'Bandit damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_kills', 'text', lambda h, p: 'Survive the fire rings or kill all %d bandits' % p['kills'], 'Objective text', 'The objective line.', group='Texts', max_len=70),
    P('text_ring', 'text', 'The outer ring is on fire! Move toward the middle!', 'Ring warning', 'Shown when a ring is about to burn.', group='Texts', max_len=60),
    P('text_survived', 'text', 'You outlasted the fire!', 'Success text', 'Shown when the clock runs out.', group='Texts', max_len=40),
    P('text_burnt', 'text', 'You touched the fire! The ring burns you down.', 'Burn text', 'Shown when a ring burns the player.', group='Texts', max_len=60),
]


def constraints(p, host):
    m = []
    e = p['ring_edges']
    if not (e[0] > e[1] > e[2] > 3.0):
        m.append(('error', 'The ring edges must shrink: ring 1 > ring 2 > ring 3 > 3 m (they are %s).' % ', '.join('%.1f' % v for v in e)))
    if e[0] >= p['outer_edge']:
        m.append(('error', 'The outer radius (%.1f m) must be bigger than the first ring edge (%.1f m).' % (p['outer_edge'], e[0])))
    t = p['ring_times']
    if not (0 < t[0] < t[1] < t[2]):
        m.append(('error', 'The ring times must go up: ring 1 before ring 2 before ring 3.'))
    if t[2] >= p['countdown']:
        m.append(('warn', 'Ring 3 burns after the clock has run out, so it never fires.'))
    c = p['center']
    if host is not None and host.arrival.get('pos'):
        a = host.arrival['pos']
        d = max(abs(a[0] - c[0]), abs(a[2] - c[2]))
        if d >= e[0]:
            m.append(('warn', 'The arrival spot lies inside ring 1 (%.0f m from the centre): the player starts in the fire zone.' % d))
    return m


def ring_boxes(a, b):
    mid = (a + b) / 2.0
    return [('N', 0.0, mid, 2 * b, b - a), ('S', 0.0, -mid, 2 * b, b - a), ('E', mid, 0.0, b - a, 2 * a), ('W', -mid, 0.0, b - a, 2 * a)]


def ring_points(a, b, step=18.0):
    mid = (a + b) / 2.0
    n = max(4, int(math.ceil(8 * mid / step)))
    per = 8 * mid
    pts = []
    for i in range(n):
        s = per * i / n
        side, t = int(s // (2 * mid)), s % (2 * mid)
        x, z = [(-mid + t, -mid), (mid, -mid + t), (mid - t, mid), (-mid, mid - t)][side]
        pts.append((x, z))
    return pts


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    N_KILLS = p['kills']

    def design(ctx):
        W = ctx.world
        chars, by_level = L.enemy_levels(ctx)
        used, taken = [], []
        start = ctx.one(name='SM20_Mission_Start_Trigger')
        en_tmpl = [a for a in ctx.find(type='Trigger_Activate_Enable_Disable') if ctx.get(a, 'TargetName', '') == WAVES[1][0]][0]
        for wi, (level, names) in enumerate(WAVES):
            ctr, delay = p['wave_centres'][wi], p['wave_delays'][wi]
            picks = [L.pick_enemy(by_level, level, nm) for nm in names]
            for k, c in enumerate(picks):
                x, z = ctr[0] + OFFSETS[k][0], ctr[2] + OFFSETS[k][1]
                xz = W.snap(x, z, margin=1.5, taken=taken, min_sep=3.0) if p['snap_to_free_ground'] else (x, z)
                taken.append(xz)
                ctx.place_enemy(c, xz, y=host.gy(xz[0], xz[1], ctr[1]) + 0.8, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
                ctx.set_weapons(c, 0)
                used.append(c)
            if delay > 0:
                ctx.add_action(en_tmpl, start, 'arena_wave%d' % wi, name='ACT_Wave%d' % (wi + 1), sets={'Delay': float(delay), 'TargetName': level})
        spares = [c for c in chars if c not in used]
        L.park_spares(ctx, spares, p['spare_region'])
        pk = p['park']
        park = (pk[0], pk[2])
        L.park_javper_boxes(ctx, park)
        ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
        ctx.set(ctx.one(name='COND_ObjectiveComplete'), 'TrigAmount', N_KILLS)
        ctx.set(ctx.one(name='Activate_Countdown'), 'Time', float(p['countdown']))
        ctx.set(ctx.one(name='Activate_MISSION_FAILED'), 'End_Mission_Result', 1)
        tr = ctx.one(name='Activate_time_ran_out_TEXT')
        ctx.set(tr, 'FeedbackText', ctx.texts['@survived']); ctx.set(tr, 'UseFeedbackText', True)
        ctx.retarget_names({'SubM_20_Pistoleros_OBJ': O('ARENA_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        tg = ctx.find(regex=r'loader_Guy')[0]
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.place_enemy(tg, (tx, tz))
        L.park_strays(ctx, (park[0] - 2.0, park[1]))
        # ---- the fire rings
        cn = p['center']
        CXr, CZr = cn[0], cn[2]
        GR = host.gy(CXr, CZr, cn[1])
        RING_EDGE, OUTER = p['ring_edges'], p['outer_edge']
        RING_T = p['ring_times']
        SP = ('ref', ctx.frag(start[2]), start[3])
        zroot = ctx.one(name='TRIG_SubM_20_Elev_indicator')
        zcond = [n for n in ctx.nodes() if n[1].startswith('Trigger_Condition') and ctx.parent_key(n) == zroot[3]][0]
        ZP = ('ref', ctx.frag(zroot[2]), ctx.parent_key(zroot))
        for ri in range(3):
            a = RING_EDGE[ri]
            b = OUTER if ri == 0 else RING_EDGE[ri - 1]
            for suf, cx, cz, w, l in ring_boxes(a, b):
                nm = 'ARENA_R%d_%s' % (ri + 1, suf)
                uid = 'arena_box_%d_%s' % (ri + 1, suf)
                ctx.B.append(ctx.NEW, uid, (ctx.NEW, ctx.frag(zroot[2]), zroot[3]), parent=ZP, name=nm,
                             pos=[CXr + cx, GR + 4.0, CZr + cz], rot=[0.0, 0.0, 0.0, 1.0],
                             sets={'width': float(w), 'height': BOX_H, 'length': float(l), 'flags': 17})
                ctx.B.append(ctx.NEW, uid + '_c', (ctx.NEW, ctx.frag(zcond[2]), zcond[3]), parent=('new', uid), name='COND_Ring_Touch', sets={'TrueOn': 1})
                ctx.B.append(ctx.NEW, uid + '_f', (STUNT, STUNT_FRAG, 0x400089), parent=('new', uid), name='ACT_Ring_FAILED', sets={'Delay': p['fail_delay']})
                ctx.B.append(ctx.NEW, uid + '_t', (STUNT, STUNT_FRAG, 0x40008A), parent=('new', uid), name='ACT_Ring_text',
                             sets={'FeedbackText': ctx.texts['@burnt']})
                ctx.add_action(en_tmpl, start, 'arena_en_%d_%s' % (ri + 1, suf), name='ACT_Ring%d_%s' % (ri + 1, suf),
                               sets={'Delay': RING_T[ri], 'TargetName': nm})
            for pi, (px, pz) in enumerate(ring_points(a, b)):
                en = 'ARENA_FIRE_R%d_%02d' % (ri + 1, pi)
                ctx.B.append(ctx.NEW, 'arena_em_%d_%d' % (ri + 1, pi), (MM010, MM010_FRAG, SRC_EMITTER), parent=SP,
                             pos=[CXr + px, GR + 0.2, CZr + pz], rot=[0.0, 0.0, 0.0, 1.0], name=en)
                ctx.add_action_from(('mm010_ernestocruz.mission', MM010_FRAG, SRC_PARTICLE), start, 'arena_pa_%d_%d' % (ri + 1, pi),
                                    name='ACT_Fire%d_%02d' % (ri + 1, pi), sets={'TargetName': en, 'Delay': max(0.1, RING_T[ri] - WARN)})
            ctx.add_action(tr, start, 'arena_txt_%d' % (ri + 1), name='ACT_RingText%d' % (ri + 1),
                           sets={'FeedbackText': ctx.texts['@ring'], 'UseFeedbackText': True, 'Delay': max(0.1, RING_T[ri] - WARN)})

    template = dict(slot=49, block='subm_20_down_javper_kill.mission', root='SubM_20_Down_JavPer_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('kills', p['text_kills']), ('ring', p['text_ring']), ('survived', p['text_survived']), ('burnt', p['text_burnt'])],
                     [{'DisplayText': '@kills', 'MaxCounter': N_KILLS, 'name': O('ARENA_OBJ_KILLS')}], design,
                     ALLOW_UNRESOLVED=['Chunk_17_StandardGarageDoor_01', 'TRIG_OpenChunk17GarageDoor', 'TRIG_CloseChunk17GarageDoor', 'Chunk18_Elevator_Door01',
                                       'Elevator_chunk18A', 'Marker_Round_sm20'])
