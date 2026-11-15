"""Template 'endurance': a score attack. Waves of bandits keep coming until the clock runs out (or the player dies); the mission's points are the score. (Mesa index 57.)

Template: registry slot 49 = SubM_20_Down_JavPer_Kill (like frenzy). A folder is spawned by an Enable_Disable action (5); a cleared wave comes back by DISABLE (6) then ENABLE of
the same folder. Waves are timed (every `step` s): tier 1 LEVEL01, tier 2 LEVEL02, tier 3 LEVEL04, tier 4 LEVEL05, then the same four again; from wave 9 on two folders at once.
When the time is up the template's time-out action ends the mission with result 1 (MISSION COMPLETE + result screen) instead of the template's failure.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'endurance'
TITLE = 'Endurance'
SUMMARY = 'A score attack: waves of bandits keep coming, stronger every tier, until the clock runs out. Points are the score.'
HOST_NEEDS = ['Open, flat ground for four groups of 3-4 bandits (each around a centre you choose); the player must be able to fight in the middle.',
              'A parking spot for the template\'s Downtown walk-in boxes and a spare strip (disabled, never seen).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 57
LEGACY_ROOT = 'SubM_57_Mesa_EnduranceRn.fragment'
GIVER_NAME = 'MESA_GIVER_ENDURANCE'
COMMON = dict(giver=(-26.0, 32.0, 6.0), name='ENDURANCE',
              description='The bandits do not stop coming. Hold the courtyard until time runs out and rack up as many points as you can: kills, combos, loco moves.',
              load_mid='ENDLESS WAVES', load_low='SURVIVE + SCORE', pass_score=400, silver_score=2500, gold_score=6000)
LEVELS = [('SubM_20_Down_JavPer_Kill_LEVEL01', ['Enemy_01', 'Enemy_02', 'Enemy_03', 'Enemy_04']),
          ('SubM_20_Down_JavPer_Kill_LEVEL02', ['Enemy_07', 'Enemy_08', 'Enemy_09']),
          ('SubM_20_Down_JavPer_Kill_LEVEL04', ['@19a', '@19b', 'Enemy_20', 'Enemy_21']),
          ('SubM_20_Down_JavPer_Kill_LEVEL05', ['Enemy_25', 'Enemy_26', 'Enemy_27', 'Enemy_28'])]
CYCLE = ['SubM_20_Down_JavPer_Kill_LEVEL02', 'SubM_20_Down_JavPer_Kill_LEVEL04', 'SubM_20_Down_JavPer_Kill_LEVEL05', 'SubM_20_Down_JavPer_Kill_LEVEL01']
L01 = 'SubM_20_Down_JavPer_Kill_LEVEL01'
OFFSETS = [(-3.0, -3.0), (3.0, -3.0), (-3.0, 3.0), (3.0, 3.0)]

PARAMS = [
    P('tier_centres', 'points', lambda h, p: [h.pt(-14, 4), h.pt(26, 6), h.pt(-2, 26), h.pt(8, 12)], 'Tier positions', 'Centre of the bandit group of tier 1, 2, 3 and 4 (x, y, z).', min_len=4, max_len=4, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not fight are parked (disabled).', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', 'Where the template\'s Downtown walk-in boxes are parked (disabled).', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-26, 26), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move bandits that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('step', 'float', 20.0, 'Wave interval', 'Seconds between waves.', min=5.0, max=120.0, unit='s', group='Settings'),
    P('waves', 'int', 12, 'Number of waves', 'How many waves arrive (from wave 9 on two folders arrive at once).', min=2, max=40, group='Settings'),
    P('countdown', 'float', lambda h, p: p['step'] * (p['waves'] - 1) + 40.0, 'Time limit', 'Seconds on the clock (default: all waves plus 40 s).', min=20.0, max=3600.0, unit='s', group='Settings'),
    P('tier_health', 'floats', [0.3, 0.4, 0.6, 0.9], 'Tier health', 'Health multiplier of tier 1..4.', min_len=4, max_len=4, group='Settings'),
    P('tier_damage', 'floats', [0.2, 0.3, 0.4, 0.5], 'Tier damage', 'Damage multiplier of tier 1..4.', min_len=4, max_len=4, group='Settings'),
    P('tier_weapons', 'floats', [0.0, 0.0, 5.0, 5.0], 'Tier weapons', 'Weapon sub-type of tier 1..4 (0 = pistol, 5 = shotgun).', min_len=4, max_len=4, group='Settings', advanced=True),
    P('text_survive', 'text', 'Survive the waves and score as much as you can', 'Objective text', 'The objective line.', group='Texts', max_len=70),
    P('text_timeup', 'text', 'TIME IS UP! Your score is final', 'Time-up text', 'Shown when the clock runs out.', group='Texts', max_len=50),
    P('text_count', 'text', '%0 bandits down', 'Counter text', 'The counter line.', group='Texts', max_len=40),
]


def constraints(p, host):
    m = []
    if p['countdown'] < p['step'] * 2:
        m.append(('error', 'The clock (%g s) ends before the second wave (%g s).' % (p['countdown'], p['step'] * 2)))
    elif p['countdown'] < p['step'] * (p['waves'] - 1):
        m.append(('warn', 'The clock ends before the last wave arrives; only waves up to %d will come.' % (int(p['countdown'] // p['step']) + 1)))
    if p['pass_score'] > 40 * 10:
        m.append(('info', 'Pass score %d: tier-1 bandits pay about 10 points each; check a player can reach it.' % p['pass_score']))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    STEP, N_WAVES = p['step'], p['waves']

    def design(ctx):
        W = ctx.world
        chars, by_level = L.enemy_levels(ctx)
        used, taken = [], []
        start = ctx.one(name='SM20_Mission_Start_Trigger')
        for ti, (level, names) in enumerate(LEVELS):
            ctr = p['tier_centres'][ti]
            picks = [L.pick_enemy(by_level, level, nm) for nm in names]
            for k, c in enumerate(picks):
                x, z = ctr[0] + OFFSETS[k][0], ctr[2] + OFFSETS[k][1]
                xz = W.snap(x, z, margin=1.5, taken=taken, min_sep=3.0) if p['snap_to_free_ground'] else (x, z)
                taken.append(xz)
                ctx.place_enemy(c, xz, y=host.gy(xz[0], xz[1], ctr[1]) + 0.8, health_mod=p['tier_health'][ti], damage_mod=p['tier_damage'][ti])
                ctx.set_weapons(c, int(p['tier_weapons'][ti]))
                used.append(c)
        en_t = [a for a in ctx.find(type='Trigger_Activate_Enable_Disable') if ctx.get(a, 'TargetName', '') == 'SubM_20_Down_JavPer_Kill_LEVEL02'][0]
        dis_t = ctx.find(name='Disable_gate_triggers', type='Trigger_Activate_Enable_Disable')[0]
        seen = {L01}
        sched = []
        for i in range(1, N_WAVES):
            t = STEP * i
            lv = [CYCLE[(i - 1) % 4]]
            if i >= 8:
                lv.append(CYCLE[(i + 1) % 4])
            for level in lv:
                if level in seen:
                    ctx.add_action(dis_t, start, 'endure_d%d_%s' % (i, level[-2:]), name='ACT_Wave%d_Off_%s' % (i + 1, level[-2:]),
                                   sets={'TargetName': level, 'Delay': float(t - 0.5)})
                ctx.add_action(en_t, start, 'endure_e%d_%s' % (i, level[-2:]), name='ACT_Wave%d_On_%s' % (i + 1, level[-2:]),
                               sets={'TargetName': level, 'Delay': float(t)})
                seen.add(level)
                sched.append((t, level[-2:]))
        ctx.log.append('endurance timeline: %s' % sched)
        spares = [c for c in chars if c not in used]
        L.park_spares(ctx, spares, p['spare_region'])
        pk = p['park']
        park = (pk[0], pk[2])
        L.park_javper_boxes(ctx, park)
        ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
        ctx.set(ctx.one(name='COND_ObjectiveComplete'), 'TrigAmount', 9999)
        ctx.set(ctx.one(name='Activate_Countdown'), 'Time', float(p['countdown']))
        ctx.set(ctx.one(name='Activate_MISSION_FAILED'), 'End_Mission_Result', 1)
        ctx.set(ctx.one(name='Activate_time_ran_out_TEXT'), 'FeedbackText', ctx.texts['@timeup'])
        ctx.set(ctx.one(name='Activate_time_ran_out_TEXT'), 'UseFeedbackText', True)
        ctx.retarget_names({'SubM_20_Pistoleros_OBJ': O('ENDURE_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        tg = ctx.find(regex=r'loader_Guy')[0]
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.place_enemy(tg, (tx, tz))
        L.park_strays(ctx, (park[0] - 2.0, park[1]))

    template = dict(slot=49, block='subm_20_down_javper_kill.mission', root='SubM_20_Down_JavPer_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('survive', p['text_survive']), ('timeup', p['text_timeup']), ('count', p['text_count'])],
                     [{'DisplayText': '@survive', 'CounterText': '@count', 'MaxCounter': 999, 'name': O('ENDURE_OBJ_KILLS')}], design,
                     ALLOW_UNRESOLVED=['Chunk_17_StandardGarageDoor_01', 'TRIG_OpenChunk17GarageDoor', 'TRIG_CloseChunk17GarageDoor', 'Chunk18_Elevator_Door01',
                                       'Elevator_chunk18A', 'Marker_Round_sm20'])
