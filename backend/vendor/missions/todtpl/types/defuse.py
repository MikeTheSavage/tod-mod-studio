"""Template 'defuse': bombs are ticking; walk to each one and press USE to defuse it. One clock for all, every defused bomb adds time; out of time = they explode. (Mesa index 15.)

Template: registry slot 35 = SubM_06_Indu_ChePoi_Race (same block as 'race', own clone). Gates 1..N are the bombs, all enabled at the start (any order), their condition
TrueOn 1 (enter) -> 2 (USE inside the sphere); each gate group carries a DEA_BOMB model (asset records copied from the DEA HQ submap). Gates N+1..9 are parked.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'defuse'
TITLE = 'Defuse the Bombs'
SUMMARY = 'Find and defuse up to four bombs (stand next to each and press USE) before one shared clock runs out.'
HOST_NEEDS = ['One free spot per bomb (2 m clearance, bombs at least 6 m apart) that the player can walk to.',
              'A parking spot for the template\'s leftover Industrial-map content (never seen).',
              'Needs the DEA HQ submap data (bomb model) installed: it is copied into the mission block.',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 15
LEGACY_ROOT = 'SubM_15_Mesa_DefuseBombs.fragment'
GIVER_NAME = 'MESA_GIVER_DEFUSE'
COMMON = dict(giver=(6.0, 10.0, 6.0), name='DEFUSE THE BOMBS',
              description='Four bombs are ticking inside the compound. Find them, stand next to each one and press USE. Every defused bomb gives you a few more seconds.',
              load_mid='TICK TICK', load_low='FIND + DEFUSE', pass_score=0, silver_score=300, gold_score=600)
DEA = 'data_pc/overdose_the_game/overdose/shared/submap02_map01_dea_hq_us_border.submap'
DEA_FRAG = 'SUBMAP02_Map01_DEA_HQ_US_Border.fragment'
BOMB_NODE = 0x3001DF
BOMB_MODEL = '/data/Models/Addons/Map01_DEA_HQ_US_Border/DEA_BOMB.model'
EXPLO = ('subm_03_rottenmeat.mission', 'SubM_03_RottenMeat.fragment', 0x4006C1)
CHAIN = ('ACT_Enable_NextChkPoint', 'ACT_AddBlip_Next_ChkPoint', 'ACT_Enable_Next_ChkPointTrigger', 'ACT_Reactivate_Next_ChkPointTrigger', 'ACT_Enable_Forklift_Trigger')
SLOW = 99999.0

PARAMS = [
    P('bombs', 'points', lambda h, p: [h.pt(0, -6), h.pt(28, -4), h.pt(28, 31), h.pt(-10, 31)], 'Bomb positions', 'Where the bombs lie (x, y, z), 1 to 4. Keep them at least 6 m apart.', min_len=1, max_len=4, group='Placement'),
    P('defuse_radius', 'float', 4.5, 'Defuse radius', 'The player must stand within this distance of a bomb and press USE.', min=1.5, max=10.0, unit='m', group='Placement'),
    P('park', 'point', lambda h, p: h.pt(60, 60, None), 'Parking spot', 'Where leftover template content is parked (disabled, never seen). y empty = ground + 1.', group='Placement', advanced=True),
    P('goodies', 'points', lambda h, p: [h.pt(0, -10), h.pt(12, 6), h.pt(-18, 8), h.pt(18, 14), h.pt(-4, 22), h.pt(-24, 26)], 'Health pickups', 'Up to six health pickups spread over the area.', max_len=6, group='Placement'),
    P('giver_npc_park', 'point', lambda h, p: h.pt(24, -5), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('start_time', 'float', 65.0, 'Start time', 'Seconds on the shared clock at the start.', min=10.0, max=900.0, unit='s', group='Settings'),
    P('add_points', 'int', 900, 'Time added per bomb', 'Racing-clock points added per defused bomb (1/100 s); the engine gives about +3 s whatever this is.', min=0, max=100000, group='Settings', advanced=True),
    P('text_defuse', 'text', lambda h, p: 'Defuse all %d bombs before the time runs out' % len(p['bombs']), 'Objective text', 'The objective line.', group='Texts', max_len=70),
    P('text_hint', 'text', 'Stand next to a bomb and press USE to defuse it', 'Hint text', 'Shown at the start.', group='Texts', max_len=70),
    P('text_boom', 'text', 'BOOM! The bombs went off', 'Explosion text', 'Shown when the time runs out.', group='Texts', max_len=50),
    P('text_count', 'text', '%0 out of %1 bombs defused', 'Counter text', 'The counter line.', group='Texts', max_len=50),
]


def constraints(p, host):
    m = []
    b = p['bombs']
    for i in range(len(b)):
        for j in range(i + 1, len(b)):
            d = ((b[i][0] - b[j][0]) ** 2 + (b[i][2] - b[j][2]) ** 2) ** 0.5
            if d < 6.0:
                m.append(('error', 'Bombs %d and %d are only %.1f m apart; keep bombs at least 6 m apart.' % (i + 1, j + 1, d)))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    NB = len(p['bombs'])

    def design(ctx):
        W = ctx.world
        L.install_assets(ctx, DEA, [BOMB_MODEL])
        G = lambda x, z, y=None: host.gy(x, z, y)
        spots = []
        for b in p['bombs']:
            spots.append(W.snap(b[0], b[2], margin=2.0, taken=spots, min_sep=6.0))
        ctx.log.append('bombs %s' % spots)
        start = ctx.one(name='TRIG_StartSubMission')
        for i, (bx, bz) in enumerate(spots, 1):
            g0 = G(bx, bz, p['bombs'][i - 1][1])
            grp = ctx.one(name='CheckPoint_%02d' % i)
            trg = ctx.one(name='TRIG_ChkPoint_%02d' % i)
            ctx.move(grp, (bx, g0 + 0.3, bz)); ctx.move(trg, (bx, g0 + 0.5, bz))
            ctx.set(trg, 'radius', p['defuse_radius'])
            ctx.set(grp, 'flags', int(ctx.get(grp, 'flags', 0)) & ~1)
            ctx.set(trg, 'flags', int(ctx.get(trg, 'flags', 0)) & ~1)
            for s in [x for x in ctx.nodes() if x[2] == trg[2] and ctx.get(x, 'parent', 0) == trg[3]]:
                if s[4] == 'COND_PlayerEnter':
                    ctx.set(s, 'TrueOn', 2)
            ctx.B.append(ctx.NEW, 'defuse_bomb_%d' % i, (DEA, DEA_FRAG, BOMB_NODE), parent=('ref', ctx.frag(grp[2]), grp[3]),
                         name='DEFUSE_BOMB_%d' % i, pos=[bx, g0 + 0.55, bz])
            if i > 1:
                ctx.add_action(ctx.one(name='ACT_AddBlip_ChkPoint01'), start, 'defuse_blip_%d' % i, sets={'TargetName': 'TRIG_ChkPoint_%02d' % i})
            ctx.add_action(ctx.one(name='ACT_Trig_EndRaceTrigger'), trg, 'defuse_end_%d' % i, name='ACT_Trig_EndRaceTrigger')
        for nm in CHAIN:
            for n in ctx.find(name=nm):
                ctx.set(n, 'TargetName', 'DEFUSE_NONE')
        cnd = ctx.one(name='COND_NoOfLaps')
        ctx.set(cnd, 'TrigAmount', NB); ctx.set(cnd, 'SpecificActivator', '')
        ctx.set(ctx.one(name='ACT_CountDown'), 'Points', int(round(p['start_time'] * 100)))
        ctx.set(ctx.one(name='ACT_AddTime'), 'Points', p['add_points'])
        ctx.retarget_names({'SubM_06_Race_OBJ': O('DEFUSE_OBJ')}, props=('TargetName', 'SpecificActivator'))
        ctx.set(ctx.one(name='COND_MissionStart'), 'SpecificActivator', '')
        for nm in ('Activate_TextEffect_Countdown_READY', 'Activate_fx_ready', 'Activate_TextEffect_Countdown_STEADY', 'Activate_fx_steady',
                   'Activate_Pause_Text', 'Activate_track_Camera', 'ACT_Cam01'):
            ctx.set(ctx.one(name=nm), 'Delay', SLOW)
        for nm, d in (('Activate_TextEffect_Countdown_GO', 1.5), ('Activate_fx_go', 1.5), ('Activate_music_racing_05', 2.0),
                      ('Activate_OBJ_SubM_06_Race_OBJ', 1.0), ('ACT_CountDown', 1.5)):
            ctx.set(ctx.one(name=nm), 'Delay', d)
        fb = [n for n in ctx.find(name='Activate_OBJ_checkpoint_cleared') if n[3] == 0x401249][0]
        pt = ctx.one(name='Activate_Pause_Text'); ctx.set(pt, 'UsePauseMode', False); ctx.set(pt, 'StayTime', 0.1)
        ctx.add_action(fb, ctx.one(name='TRIG_StartRace'), 'defuse_hint', name='ACT_Hint',
                       sets={'FeedbackText': ctx.texts['@hint'], 'Delay': 3.5, 'StayTime': 5.0})
        cd = ctx.one(name='ACT_CountDown')
        ctx.set(ctx.one(name='Activate_time_ran_out_TEXT'), 'FeedbackText', ctx.texts['@boom'])
        ctx.set(ctx.one(name='ACT_MissionFailedScreen'), 'Delay', 3.5)
        ctx.set(ctx.one(name='ACT_Disable_gates_and_triggers'), 'Delay', 3.0)
        for i in range(1, len(spots) + 1):
            ctx.add_action_from(EXPLO, cd, 'defuse_boom_%d' % i, name='ACT_Boom_%d' % i,
                                sets={'TargetName': 'DEFUSE_BOMB_%d' % i, 'Delay': 0.2 + 0.5 * (i - 1)})
        ctx.retarget_camera_cuts(names=['ACT_Cam01'])
        ctx.retarget_names({'TrafficPoints_M03S01': 'Forklift', 'TRIG_Forklift': 'Goodies'}, props=('TargetName',), classes=('Trigger_Activate_Enable_Disable',))
        pk = p['park']
        park = (pk[0], pk[2])
        py = host.gy(pk[0], pk[2], pk[1]) if pk[1] is not None else host.gy(pk[0], pk[2]) + 1.0
        for i in range(len(spots) + 1, 10):
            ctx.move(ctx.one(name='CheckPoint_%02d' % i), (park[0] - 15.0 + 2.5 * i, py, park[1] - 10.0))
            ctx.move(ctx.one(name='TRIG_ChkPoint_%02d' % i), (park[0] - 15.0 + 2.5 * i, py, park[1] - 14.0))
        wrong = ctx.one(name='TRIG_WRONG_WAY')
        ctx.move(wrong, (park[0], py, park[1])); ctx.set(wrong, 'flags', int(ctx.get(wrong, 'flags', 0)) | 1)
        ctx.move(ctx.one(name='TRIG_Forklift'), (park[0] - 10, py, park[1]))
        for nm in ('Forklift', 'Mechanic'):
            ctx.disable_folder(ctx.one(name=nm, type='Folder'))
        for k, v in enumerate(ctx.find(type='vehicle_placeholder')):
            ctx.move(v, (park[0] - 6.0 + 4.0 * k, py, park[1] + 6.0))
        ctx.place_enemy(ctx.one(name='Mech01'), (park[0] + 6.0, park[1] - 6.0), y=py)
        for k, t in enumerate(ctx.find(type='TrackPoint')):
            ctx.move(t, (park[0] + 6.0 + 1.5 * k, py, park[1] - 6.0))
        gq = p['giver_npc_park']
        ctx.place_enemy(ctx.one(name='Enabler_SM06'), (gq[0], gq[2]))
        for g, q in zip(ctx.find(type='goodie_placeholder'), p['goodies']):
            gx, gz = W.snap(q[0], q[2], margin=1.0)
            ctx.move(g, (gx, G(gx, gz, q[1]) + 1.3, gz))
        L.park_strays(ctx, (park[0] - 5.0, park[1] + 12.0))

    template = dict(slot=35, block='subm_06_indu_chepoi_race.mission', root='SubM_06_Indu_ChePoi_Race.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('defuse', p['text_defuse']), ('hint', p['text_hint']), ('boom', p['text_boom']), ('count', p['text_count'])],
                     [{'DisplayText': '@defuse', 'CounterText': '@count', 'MaxCounter': NB, 'name': O('DEFUSE_OBJ')}], design,
                     ALLOW_UNRESOLVED=['DEFUSE_NONE'])
