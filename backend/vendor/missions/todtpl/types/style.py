"""Template 'style': a timed score attack where the points come from STYLE. (Mesa index 61.)

Template slot 49 like frenzy / endurance. Four timed waves of bandits (15 in all); goodies that multiply what you do lie around (ComboTimeMultiplier 3, score bonus 20 / 21,
Golden Gun 9, Tornado 10); milestones pay a bonus (APBonus of a kill-count / combo-count condition) and show a text. When the clock runs out the template's time-out action ends the
mission with result 1: MISSION COMPLETE with the score (pass = a low score; the only failure is the player's death).
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'style'
TITLE = 'Style Run'
SUMMARY = 'A timed score attack: chain kills, keep the combo alive, grab goodies and use loco moves.'
HOST_NEEDS = ['Open, flat ground for four groups of 3-4 bandits and up to nine goodie spots (3 m apart).',
              'A parking spot for the template\'s Downtown walk-in boxes and a spare strip (disabled, never seen).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 61
LEGACY_ROOT = 'SubM_61_Mesa_StyleRun_01.fragment'
GIVER_NAME = 'MESA_GIVER_STYLE'
COMMON = dict(giver=(26.0, -16.0, 6.0), name='STYLE RUN',
              description='Ninety seconds. Chain kills, keep the combo alive, grab the goodies and use your loco moves. Style is the score.',
              load_mid='STYLE POINTS', load_low='CHAINS + COMBOS', pass_score=300, silver_score=1500, gold_score=3000)
WAVES = [('SubM_20_Down_JavPer_Kill_LEVEL01', ['Enemy_01', 'Enemy_02', 'Enemy_03', 'Enemy_04']),
         ('SubM_20_Down_JavPer_Kill_LEVEL02', ['Enemy_07', 'Enemy_08', 'Enemy_09']),
         ('SubM_20_Down_JavPer_Kill_LEVEL04', ['@19a', '@19b', 'Enemy_20', 'Enemy_21']),
         ('SubM_20_Down_JavPer_Kill_LEVEL05', ['Enemy_25', 'Enemy_26', 'Enemy_27', 'Enemy_28'])]
OFFSETS = [(-3.0, -3.0), (3.0, -3.0), (-3.0, 3.0), (3.0, 3.0)]
GOODIE_SRC = ('submap01_map02_lostoros_downtown.submap', 'SUBMAP01_Map02_Goodies.fragment', '0x00301195')
MILE_KEYS = ['nice', 'slick', 'legend']
GOODIE_TYPES = [3, 3, 3, 20, 20, 20, 21, 9, 10]
_GOODIES_REL = [(-6.0, -8.0), (12.0, 4.0), (-12.0, 14.0), (6.0, -8.0), (-20.0, 0.0), (20.0, -12.0), (0.0, 6.0), (-28.0, 12.0), (28.0, -8.0)]

PARAMS = [
    P('wave_centres', 'points', lambda h, p: [h.pt(-14, 4), h.pt(26, 6), h.pt(-2, 26), h.pt(8, 12)], 'Wave positions', '', min_len=4, max_len=4, group='Placement'),
    P('goodies', 'points', lambda h, p: [h.pt(x, z) for x, z in _GOODIES_REL], 'Goodie positions', '', min_len=1, max_len=9, group='Placement'),
    P('goodie_types', 'floats', [float(t) for t in GOODIE_TYPES], 'Goodie types', '', min_len=1, max_len=9, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', '', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', '', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(26, -22), 'Parked task giver', '', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', '', group='Placement', advanced=True),
    P('countdown', 'float', 90.0, 'Time limit', '', min=20.0, max=900.0, unit='s', group='Settings'),
    P('wave_delays', 'floats', [0.0, 10.0, 20.0, 30.0], 'Wave delays', '', min_len=4, max_len=4, group='Settings'),
    P('goodie_respawn', 'float', 25.0, 'Goodie respawn', '', min=5.0, max=300.0, unit='s', group='Settings'),
    P('kill_counts', 'floats', [5.0, 10.0, 15.0], 'Kill milestones', '', min_len=3, max_len=3, group='Settings'),
    P('kill_bonuses', 'floats', [200.0, 400.0, 800.0], 'Kill milestone bonus', '', min_len=3, max_len=3, group='Settings'),
    P('combo_counts', 'floats', [1.0, 4.0], 'Combo milestones', '', min_len=2, max_len=2, group='Settings'),
    P('combo_bonuses', 'floats', [300.0, 600.0], 'Combo milestone bonus', '', min_len=2, max_len=2, group='Settings'),
    P('enemy_health', 'float', 0.3, 'Bandit health', '', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.25, 'Bandit damage', '', min=0.0, max=3.0, group='Settings'),
    P('text_style', 'text', 'Score as many STYLE points as you can before time runs out', 'Objective text', '', group='Texts', max_len=70),
    P('text_nice', 'text', 'NICE! STYLE BONUS', 'NICE text', '', group='Texts', max_len=40),
    P('text_slick', 'text', 'SLICK! STYLE BONUS', 'SLICK text', '', group='Texts', max_len=40),
    P('text_legend', 'text', 'LEGEND! BIG STYLE BONUS', 'LEGEND text', '', group='Texts', max_len=40),
    P('text_count', 'text', '%0 kills in style', 'Counter text', '', group='Texts', max_len=40),
]


def constraints(p, host):
    m = []
    if len(p['goodies']) != len(p['goodie_types']):
        m.append(('error', 'There are %d goodie positions but %d goodie types: give one type per position.' % (len(p['goodies']), len(p['goodie_types']))))
    if p['wave_delays'][0] != 0.0:
        m.append(('error', 'The first wave must arrive at 0 seconds.'))
    if any(p['wave_delays'][i] > p['wave_delays'][i + 1] for i in range(3)):
        m.append(('error', 'The wave delays must not go down.'))
    if p['kill_counts'] != sorted(p['kill_counts']) or p['combo_counts'] != sorted(p['combo_counts']):
        m.append(('warn', 'The milestone counts should go up (NICE, then SLICK, then LEGEND).'))
    if p['kill_counts'][2] > 15:
        m.append(('warn', 'Only 15 bandits arrive: a kill milestone of %d can never be reached.' % p['kill_counts'][2]))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    MILESTONES = [(9, int(p['kill_counts'][i]), int(p['kill_bonuses'][i]), MILE_KEYS[i]) for i in range(3)] + \
                 [(6, int(p['combo_counts'][i]), int(p['combo_bonuses'][i]), MILE_KEYS[i]) for i in range(2)]

    def design(ctx):
        W = ctx.world
        chars, by_level = L.enemy_levels(ctx)
        used, taken = [], []
        start = ctx.one(name='SM20_Mission_Start_Trigger')
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
                tmpl = [a for a in ctx.find(type='Trigger_Activate_Enable_Disable') if ctx.get(a, 'TargetName', '') == level][0]
                ctx.add_action(tmpl, start, 'style_wave%d' % wi, name='ACT_Wave%d' % (wi + 1), sets={'Delay': float(delay)})
        spares = [c for c in chars if c not in used]
        L.park_spares(ctx, spares, p['spare_region'])
        pk = p['park']
        park = (pk[0], pk[2])
        L.park_javper_boxes(ctx, park)
        ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
        ctx.set(ctx.one(name='COND_ObjectiveComplete'), 'TrigAmount', 9999)
        ctx.set(ctx.one(name='Activate_Countdown'), 'Time', float(p['countdown']))
        ctx.set(ctx.one(name='Activate_MISSION_FAILED'), 'End_Mission_Result', 1)
        ctx.retarget_names({'SubM_20_Pistoleros_OBJ': O('STYLE_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        gp = ctx.one(name='SubM_20_Down_JavPer_Kill_GAMEPLAY')
        gtaken = list(taken)
        for k, (q, sub) in enumerate(zip(p['goodies'], p['goodie_types'])):
            sub = int(sub)
            x, z = W.snap(q[0], q[2], margin=1.5, taken=gtaken, min_sep=3.0) if p['snap_to_free_ground'] else (q[0], q[2])
            gtaken.append((x, z))
            ctx.add_action_from(GOODIE_SRC, gp, 'style_goodie%d' % k, name='STYLE_GOODIE_%d_%d' % (k, sub),
                                sets={'GoodieSubType': sub, 'Respawnable': True, 'RespawnTime': p['goodie_respawn'], 'pos': [x, host.gy(x, z, q[1]) + 0.9, z]})
        tmpl_root = ctx.one(name='TRIG_AnEnemyKilled')
        cond_t = [n[1] for n in ctx.find(name='COND_AnEnemyKilled')][0]
        act_t = [n[1] for n in ctx.find(name='ACT_SubM_20_Pistoleros_COUNTER')][0]
        for k, (ev, cnt, bonus, key) in enumerate(MILESTONES):
            text = ctx.texts.get('@' + key)
            sets_act = dict(ActionType=79, UseFeedbackText=True, StayTime=3.0, TargetName='')
            if text is not None:
                sets_act['FeedbackText'] = text
            ctx.B.append(ctx.NEW, 'style_mile%d' % k, (ctx.NEW, ctx.frag(tmpl_root[2]), tmpl_root[3]),
                         parent=('ref', ctx.frag(tmpl_root[2]), ctx.parent_key(tmpl_root)), name='STYLE_MILESTONE_%s' % key, deep=True,
                         sets={'Reactivate': False},
                         child_sets=[dict(type=cond_t, set=dict(TrueOn=ev, TrigAmount=cnt, APBonus=bonus)),
                                     dict(type=act_t, set=sets_act)])
        ctx.log.append('style: %d goodies, %d milestones' % (len(p['goodies']), len(MILESTONES)))
        tg = ctx.find(regex=r'loader_Guy')[0]
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.place_enemy(tg, (tx, tz))
        L.park_strays(ctx, (park[0] - 2.0, park[1]))

    template = dict(slot=49, block='subm_20_down_javper_kill.mission', root='SubM_20_Down_JavPer_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('style', p['text_style']), ('nice', p['text_nice']), ('slick', p['text_slick']), ('legend', p['text_legend']), ('count', p['text_count'])],
                     [{'DisplayText': '@style', 'CounterText': '@count', 'MaxCounter': 999, 'name': O('STYLE_OBJ_KILLS')}], design,
                     ALLOW_UNRESOLVED=['Chunk_17_StandardGarageDoor_01', 'TRIG_OpenChunk17GarageDoor', 'TRIG_CloseChunk17GarageDoor', 'Chunk18_Elevator_Door01',
                                       'Elevator_chunk18A', 'Marker_Round_sm20'])
