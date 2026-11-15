"""Template 'stunt': kill enemies with special moves (SHOOT DODGE kills) before the countdown runs out. (Mesa index 72.)

Template: registry slot 64 = SubM_37_Down_Move_Kill ("A WALK IN THE PARK"). N of the 31 enemies fight (the others stay in disabled folders parked in the
spare strip), COND_AllEnemiesKilled TrigAmount N, Killmany MaxCounter N, PerformCombo MaxCounter = combos.
"""
import sys
from ..tpl_core import P
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'stunt'
TITLE = 'Stunt Kills'
SUMMARY = 'A mob of enemies fills an area; the player must finish a number of them with SHOOT DODGE kills before the clock runs out.'
HOST_NEEDS = ['A free, flat arena of about 50 x 25 m for the enemies (they are fitted into the rectangle you give).',
              'A free strip (about 76 x 10 m) for the 25+ spare enemy placeholders that do not fight (parked in disabled folders, never seen).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 72
LEGACY_ROOT = 'SubM_72_Mesa_StuntKill.fragment'
GIVER_NAME = 'MESA_GIVER_STUNT'
COMMON = dict(giver=(-24.0, 4.0, 6.0), name='STUNT KILLS',
              description='A mob of bandits has taken over the compound courtyard. Show some style: finish them with SHOOT DODGE kills before the clock runs out.',
              load_mid='SHOOT DODGE KILLS', load_low='SHOOT DODGE + KILL', pass_score=200, silver_score=400, gold_score=600)

PARAMS = [
    P('arena', 'rect', lambda h, p: list(h.rr(-26, -14, 26, 10)), 'Fight area', 'Rectangle [x0, z0, x1, z1] the fighting enemies are spread over.', group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not fight are parked (disabled, never seen).', group='Placement', advanced=True),
    P('cone_zone', 'point', lambda h, p: h.pt(-14, -30), 'Tutorial zone', 'The walk-in zone that shows the SHOOT DODGE help text (also the radar blip).', group='Placement'),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-24, 9), 'Parked task giver', 'Where the template task-giver character is parked (not part of the play).', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move spots that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('enemies', 'int', 6, 'Number of enemies', 'Enemies that fight (template: 31).', min=1, max=29, group='Settings'),
    P('combos', 'int', 3, 'SHOOT DODGE kills needed', 'Kills with the special move the player must score.', min=1, max=29, group='Settings'),
    P('countdown', 'float', None, 'Time limit', 'Seconds on the clock. Empty = the template value (100 s).', min=10.0, max=900.0, unit='s', group='Settings'),
    P('enemy_health', 'float', 0.2, 'Enemy health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.05, 'Enemy damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('harmless_gunfire', 'bool', True, 'Harmless gunfire', 'The enemies shoot but do no damage: the challenge is style, not survival.', group='Settings'),
    P('text_combo', 'text', lambda h, p: 'Do %d SHOOT DODGE kills before the time runs out' % p['combos'], 'Objective text', 'The objective line.', group='Texts', max_len=70),
]


def constraints(p, host):
    m = []
    if p['combos'] > p['enemies']:
        m.append(('error', 'The player must score %d SHOOT DODGE kills but only %d enemies fight: raise the enemies or lower the kills.' % (p['combos'], p['enemies'])))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    N, COMBOS = p['enemies'], p['combos']

    def design(ctx):
        W = ctx.world
        chars = sorted([n for n in ctx.find(type='character_placeholder', regex=r'^Vergillio_\d+$')], key=lambda n: str(n[4]))
        assert len(chars) == 31, len(chars)
        fighters = [c for c in chars if int(str(c[4]).split('_')[1]) >= 3][:N]
        spares = [c for c in chars if c not in fighters]
        fp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in fighters], region=p['arena'], min_sep=4.0)
        for c, xz in zip(fighters, fp):
            ctx.place_enemy(c, xz, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'], damage_modify=0 if p['harmless_gunfire'] else None)
            ctx.set_weapons(c, 0)
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=p['spare_region'], min_sep=1.5, margin=0.5)
        for c, xz in zip(spares, sp):
            ctx.place_enemy(c, xz)
            pk = ctx.parent_key(c)
            folder = [x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0]
            ctx.disable_folder(folder)
        for n in ctx.find(name='COND_AllEnemiesKilled', type='Trigger_Condition_Logical'):
            ctx.set(n, 'TrigAmount', N)
        if p['countdown'] is not None:
            ctx.set(ctx.one(name='ACT_SubM_37_Countdown'), 'Time', float(p['countdown']))
        ctx.retarget_names({'SubM_37_PerformCombo_OBJ': O('STUNT_OBJ_COMBO'), 'SubM_37_Killmany_OBJ': O('STUNT_OBJ_KILLS')},
                           props=('TargetName', 'SpecificActivator'))
        zone = ctx.one(name='Trigger_cone_disable')
        cz = p['cone_zone']
        zx, zz = W.snap(cz[0], cz[2], margin=3.0) if p['snap_to_free_ground'] else (cz[0], cz[2])
        ctx.move(zone, (zx, host.gy(zx, zz, cz[1]) + 2.0, zz)); ctx.resize_box(zone, 6.0, 4.1, 6.0)
        for a in [n for n in ctx.nodes() if n[3] == 0x400073 and n[2].endswith(ctx.old_root)]:
            ctx.move(a, (zx, host.gy(zx, zz, cz[1]) + 6.35, zz))
        ctx.set(ctx.one(name='ACT_ShowRadarBlip'), 'TargetName', 'Trigger_cone_disable')
        tg = ctx.one(regex=r'^TASKGIVER_')
        gp = p['giver_npc_park']
        tx, tz = W.snap(gp[0], gp[2], margin=1.5) if p['snap_to_free_ground'] else (gp[0], gp[2])
        ctx.move(tg, (tx, host.gy(tx, tz, gp[1]) + 0.8, tz))

    template = dict(slot=64, block='subm_37_down_move_kill.mission', root='SubM_37_Down_Move_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('combo', p['text_combo'])],
                     [{'DisplayText': '@combo', 'MaxCounter': COMBOS, 'name': O('STUNT_OBJ_COMBO')}, {'MaxCounter': N, 'name': O('STUNT_OBJ_KILLS')}], design)
