"""Template 'ghost': cross the armed area to the goal zone WITHOUT killing anybody. Any kill fails the mission. (Mesa index 79.)

Template: registry slot 64 = SubM_37_Down_Move_Kill. The guards stand around the lane (pistols, DontHunt, weak); TRIG_Check_Mission_Failed now waits for the logic
event 9 "enemy killed" and fails after 2.5 s; the stunt's walk-in "cone zone" is the goal zone with an objective-counter action: objective PerformCombo
(MaxCounter 1) completes -> MISSION COMPLETE.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'ghost'
TITLE = 'Ghost Run'
SUMMARY = 'Cross an area full of armed guards to a goal zone without killing anyone.'
HOST_NEEDS = ['An open lane of free, flat ground from the start spot to the goal zone with room for up to 20 guards beside it.',
              'A free strip (76 x 10 m) for the spare placeholders (parked, disabled).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 79
LEGACY_ROOT = 'SubM_79_Mesa_GhostRun1.fragment'
GIVER_NAME = 'MESA_GIVER_GHOST'
COMMON = dict(giver=(-6.0, 10.0, 6.0), name='GHOST RUN',
              description='The compound is full of armed bandits. Get across to the far wall without killing a single one of them. One kill and it is over.',
              load_mid='NO KILLS', load_low='RUN LIKE A GHOST', pass_score=0, silver_score=200, gold_score=400)
SLOW = 99999.0
_GUARDS_REL = [(-10.0, -2.0), (8.0, -1.0), (2.0, 6.0), (-14.0, 15.0), (10.0, 13.0), (-2.0, 20.0), (8.0, 27.0), (-10.0, 27.0)]

PARAMS = [
    P('goal', 'point', lambda h, p: h.pt(-2, 34), 'Goal zone', '', group='Placement'),
    P('goal_width', 'float', 8.0, 'Goal zone width', '', min=2.0, max=40.0, unit='m', group='Placement'),
    P('goal_length', 'float', 6.0, 'Goal zone length', '', min=2.0, max=40.0, unit='m', group='Placement'),
    P('guards', 'points', lambda h, p: [h.pt(x, z) for x, z in _GUARDS_REL], 'Guard positions', '1 to 20 guards', min_len=1, max_len=20, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', '', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-14, -24), 'Parked task giver', '', group='Placement', advanced=True),
    P('legacy_goal_rotation', 'bool', False, 'Keep the Mesa goal zone rotation', '', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', '', group='Placement', advanced=True),
    P('enemy_health', 'float', 0.3, 'Guard health', '', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.05, 'Guard damage', '', min=0.0, max=3.0, group='Settings'),
    P('text_go', 'text', 'Reach the goal without killing anyone', 'Objective text', '', group='Texts', max_len=60),
    P('text_intro', 'text', 'Sneak or run, but do not kill anybody!', 'Intro text', '', group='Texts', max_len=60),
    P('text_fail', 'text', 'You killed someone. A ghost leaves no bodies!', 'Failure text', '', group='Texts', max_len=60),
    P('text_done', 'text', 'Clean run!', 'Success text', '', group='Texts', max_len=40),
]


def constraints(p, host):
    m = []
    g = p['goal']
    # The player stays where he stands when he accepts (at the giver box) and a zone only fires when he ENTERS it: a goal zone that covers the
    # giver box (or the arrival spot) can never be entered from there.
    gp, gs = p['giver_pos'], p['giver_size'] / 2.0
    if abs(gp[0] - g[0]) < p['goal_width'] / 2 + gs and abs(gp[2] - g[2]) < p['goal_length'] / 2 + gs:
        m.append(('error', 'The goal zone overlaps the giver box. The player accepts the mission standing in the giver box, and a zone only counts when he walks INTO it, so the goal could never be reached. Move the goal away from the giver box.'))
    ap = (host.arrival or {}).get('pos')
    if ap and abs(ap[0] - g[0]) < p['goal_width'] / 2 and abs(ap[2] - g[2]) < p['goal_length'] / 2:
        m.append(('warn', 'The goal zone covers the arrival spot of the map; a player who arrives there is already standing in it and the goal would not count.'))
    for i, q in enumerate(p['guards']):
        if abs(q[0] - g[0]) < p['goal_width'] / 2 and abs(q[2] - g[2]) < p['goal_length'] / 2:
            m.append(('warn', 'Guard %d stands inside the goal zone.' % (i + 1)))
            break
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    NG = len(p['guards'])

    def design(ctx):
        W = ctx.world
        chars = sorted(ctx.find(type='character_placeholder', regex=r'^Vergillio_\d+$'), key=lambda n: str(n[4]))
        fighters = [c for c in chars if int(str(c[4]).split('_')[1]) >= 3][:NG]
        spares = [c for c in chars if c not in fighters]
        taken = []
        for c, pt in zip(fighters, p['guards']):
            x, z = W.snap(pt[0], pt[2], margin=1.5, taken=taken, min_sep=4.0) if p['snap_to_free_ground'] else (pt[0], pt[2])
            taken.append((x, z))
            ctx.place_enemy(c, (x, z), y=host.gy(x, z, pt[1]) + 0.8, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
            ctx.set_weapons(c, 0)
            ctx.set(c, 'DontHunt', True)
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=p['spare_region'], min_sep=1.5, margin=0.5)
        for c, xz in zip(spares, sp):
            ctx.place_enemy(c, xz)
            pk = ctx.parent_key(c)
            ctx.disable_folder([n for n in ctx.nodes() if n[2] == c[2] and n[3] == pk][0])
        tg = ctx.one(regex=r'^TASKGIVER_')
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.move(tg, (tx, host.gy(tx, tz, gq[1]) + 0.8, tz))
        ctx.retarget_names({'SubM_37_PerformCombo_OBJ': O('GHOST_OBJ_GOAL'), 'SubM_37_Killmany_OBJ': O('GHOST_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        ctx.set(ctx.one(name='ACT_SubM_37_Countdown'), 'Delay', SLOW)
        ctx.set(ctx.one(name='ACT_SubM_37_KillMany_OBJ'), 'Delay', SLOW)
        for n in ctx.find(name='COND_AllEnemiesKilled', type='Trigger_Condition_Logical'):
            ctx.set(n, 'TrigAmount', 9999)
        ctx.set(ctx.one(name='TRIG_Check_Mission_Failed'), 'TriggerOn', 1)
        cond = [n for n in ctx.find(name='COND_SubM_37_PerformCombo_OBJ_INCOMPLETE') if n[3] == 0x4000A8][0]
        ctx.set(cond, 'TrueOn', 9); ctx.set(cond, 'SpecificActivator', '')
        ctx.set([n for n in ctx.find(name='ACT_SubM_37_Mission_FAILED') if n[3] == 0x4000AA][0], 'Delay', 2.5)
        ctx.set([n for n in ctx.find(name='ACT_SubM_37_failed_text') if n[3] == 0x4000AC][0], 'FeedbackText', ctx.texts['@fail'])
        ctx.set(ctx.one(name='TRIG_Check_Mission_Complete'), 'TriggerOn', 1)
        ctx.set([n for n in ctx.find(name='ACT_SubM_37_Mission_COMPLETE') if n[3] == 0x400098][0], 'Delay', 3.0)
        done = ctx.one(name='ACT_SubM_37_PerformCombo_OBJ_COMPLETE_Feedback')
        ctx.set(done, 'FeedbackText', ctx.texts['@done']); ctx.set(done, 'Delay', 0.3)
        ctx.set(ctx.one(name='ACT_SubM_37_Feedback'), 'FeedbackText', ctx.texts['@intro'])
        zone = ctx.one(name='Trigger_cone_disable')
        gc = p['goal']
        gx, gz = gc[0], gc[2]
        gy = host.gy(gx, gz, gc[1])
        ctx.move(zone, (gx, gy + 2.0, gz), rot=None if p['legacy_goal_rotation'] else [0.0, 0.0, 0.0, 1.0]); ctx.resize_box(zone, p['goal_width'], 4.1, p['goal_length'])
        for s in [x for x in ctx.nodes() if x[2] == zone[2] and ctx.get(x, 'parent', 0) == zone[3]]:
            if s[4] == 'Activate_Pause_Text':
                ctx.set(s, 'Delay', SLOW); ctx.set(s, 'UsePauseMode', False); ctx.set(s, 'StayTime', 0.1)
                ctx.set(s, 'flags', int(ctx.get(s, 'flags', 0)) | 1)
        for a in [n for n in ctx.nodes() if n[3] == 0x400073 and n[2].endswith(ctx.old_root)]:
            ctx.move(a, (gx, gy + 6.35, gz))
        ctx.set(ctx.one(name='ACT_ShowRadarBlip'), 'TargetName', 'Trigger_cone_disable')
        ctx.add_action(ctx.one(name='ACT_SubM_37_PerformCombo_OBJ_COUNTER'), zone, 'ghost_goal', name='ACT_GhostGoal')

    template = dict(slot=64, block='subm_37_down_move_kill.mission', root='SubM_37_Down_Move_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('go', p['text_go']), ('intro', p['text_intro']), ('fail', p['text_fail']), ('done', p['text_done'])],
                     [{'DisplayText': '@go', 'CounterText': 0, 'MaxCounter': 1, 'WriteOutOf': False, 'name': O('GHOST_OBJ_GOAL')},
                      {'MaxCounter': NG, 'name': O('GHOST_OBJ_KILLS')}], design)
