"""Template 'frenzy': kill N bandits before the clock runs out; they arrive in three timed waves. (Mesa index 74.)

Template: registry slot 49 = SubM_20_Down_JavPer_Kill ("PISTOLEROS"). Waves are timed (clones of the 'enable level folder' action with a Delay):
wave 1 = LEVEL01 (4 enemies, at once), wave 2 = LEVEL02 (3 enemies), wave 3 = LEVEL04 (4 enemies): 11 enemies, N kills win.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'frenzy'
TITLE = 'Kill Frenzy'
SUMMARY = 'Waves of bandits arrive one after another; kill enough of them before the clock runs out.'
HOST_NEEDS = ['Open, flat ground for three groups of 3-4 enemies (each group is placed around a centre you choose, spread over about 6 m).',
              'A free strip for the 20 spare placeholders and a "park" spot for the template\'s Downtown walk-in boxes (disabled, never seen).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 74
LEGACY_ROOT = 'SubM_74_Mesa_FrenzyKills.fragment'
GIVER_NAME = 'MESA_GIVER_FRENZY'
COMMON = dict(giver=(-24.0, -12.0, 6.0), name='KILL FRENZY', description='The bandits come in waves. Gun down six of them before the clock runs out.',
              load_mid='MULTIPLE KILLS', load_low='WAVES + PISTOLS', pass_score=200, silver_score=450, gold_score=700)
WAVES = [('SubM_20_Down_JavPer_Kill_LEVEL01', ['Enemy_01', 'Enemy_02', 'Enemy_03', 'Enemy_04']),
         ('SubM_20_Down_JavPer_Kill_LEVEL02', ['Enemy_07', 'Enemy_08', 'Enemy_09']),
         ('SubM_20_Down_JavPer_Kill_LEVEL04', ['@19a', '@19b', 'Enemy_20', 'Enemy_21'])]
OFFSETS = [(-3.0, -3.0), (3.0, -3.0), (-3.0, 3.0), (3.0, 3.0)]

PARAMS = [
    P('wave_centres', 'points', lambda h, p: [h.pt(-8, -8), h.pt(12, -6), h.pt(0, 2)], 'Wave positions', '', min_len=3, max_len=3, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', '', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', '', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-24, -6), 'Parked task giver', '', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', '', group='Placement', advanced=True),
    P('kills', 'int', 6, 'Kills needed', '', min=1, max=11, group='Settings'),
    P('countdown', 'float', 120.0, 'Time limit', '', min=10.0, max=900.0, unit='s', group='Settings'),
    P('wave_delays', 'floats', [0.0, 12.0, 24.0], 'Wave delays', '', min_len=3, max_len=3, group='Settings'),
    P('enemy_health', 'float', 0.3, 'Enemy health', '', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.1, 'Enemy damage', '', min=0.0, max=3.0, group='Settings'),
    P('harmless_early_waves', 'bool', True, 'First two waves harmless', '', group='Settings'),
    P('text_kills', 'text', lambda h, p: 'Kill %d bandits before the time runs out' % p['kills'], 'Objective text', '', group='Texts', max_len=70),
    P('text_count', 'text', '%0 out of %1 bandits killed', 'Counter text', '', group='Texts', max_len=50),
]


def constraints(p, host):
    m = []
    if p['wave_delays'][0] != 0.0:
        m.append(('error', 'The first wave must arrive at 0 seconds.'))
    if any(p['wave_delays'][i] > p['wave_delays'][i + 1] for i in range(2)):
        m.append(('error', 'The wave delays must not go down: wave 2 cannot come before wave 1.'))
    if max(p['wave_delays']) >= p['countdown']:
        m.append(('warn', 'The last wave arrives after the clock has run out.'))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    N = p['kills']

    def design(ctx):
        W = ctx.world
        chars, by_level = L.enemy_levels(ctx)
        used, taken = [], []
        start = ctx.one(name='SM20_Mission_Start_Trigger')
        for wi, (level, names) in enumerate(WAVES):
            ctr = p['wave_centres'][wi]
            delay = p['wave_delays'][wi]
            picks = [L.pick_enemy(by_level, level, nm) for nm in names]
            for k, c in enumerate(picks):
                x, z = ctr[0] + OFFSETS[k][0], ctr[2] + OFFSETS[k][1]
                xz = W.snap(x, z, margin=1.5, taken=taken, min_sep=3.0) if p['snap_to_free_ground'] else (x, z)
                taken.append(xz)
                ctx.place_enemy(c, xz, y=host.gy(xz[0], xz[1], ctr[1]) + 0.8, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'],
                                damage_modify=(0 if (wi < 2 and p['harmless_early_waves']) else None))
                ctx.set_weapons(c, 0)
                used.append(c)
            if delay > 0:
                tmpl = [a for a in ctx.find(type='Trigger_Activate_Enable_Disable') if ctx.get(a, 'TargetName', '') == level][0]
                ctx.add_action(tmpl, start, 'frenzy_wave%d' % wi, name='ACT_Wave%d' % (wi + 1), sets={'Delay': float(delay)})
        spares = [c for c in chars if c not in used]
        L.park_spares(ctx, spares, p['spare_region'])
        pk = p['park']
        park = (pk[0], pk[2])
        L.park_javper_boxes(ctx, park)
        ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
        ctx.set(ctx.one(name='COND_ObjectiveComplete'), 'TrigAmount', N)
        ctx.set(ctx.one(name='Activate_Countdown'), 'Time', float(p['countdown']))
        ctx.retarget_names({'SubM_20_Pistoleros_OBJ': O('FRENZY_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        tg = ctx.find(regex=r'loader_Guy')[0]
        gp = p['giver_npc_park']
        tx, tz = W.snap(gp[0], gp[2], margin=1.5) if p['snap_to_free_ground'] else (gp[0], gp[2])
        ctx.place_enemy(tg, (tx, tz))
        L.park_strays(ctx, (park[0] - 2.0, park[1]))

    template = dict(slot=49, block='subm_20_down_javper_kill.mission', root='SubM_20_Down_JavPer_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('kills', p['text_kills']), ('count', p['text_count'])],
                     [{'DisplayText': '@kills', 'CounterText': '@count', 'MaxCounter': N, 'name': O('FRENZY_OBJ_KILLS')}], design,
                     ALLOW_UNRESOLVED=['Chunk_17_StandardGarageDoor_01', 'TRIG_OpenChunk17GarageDoor', 'TRIG_CloseChunk17GarageDoor', 'Chunk18_Elevator_Door01',
                                       'Elevator_chunk18A', 'Marker_Round_sm20'])
