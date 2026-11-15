"""Template 'combo': kill the bandits one after another without ever letting the combo run out. (Mesa index 43.)

Template: registry slot 64 = SubM_37_Down_Move_Kill. The PerformCombo objective counts KILLS (COND_ComboPerformed listens on logic event 9); a new root COMBO_BROKEN_TRIG
(clone of TRIG_ComboPerformed, disabled at start) with the tutorial's 'combo missed' condition (event 24) fails the mission; it is armed by the first kill and disarmed when
the mission is won. N fighters are packed into a small area so the next kill is always near.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'combo'
TITLE = 'Unbroken Combo'
SUMMARY = 'Kill a group of bandits in one unbroken combo. If the combo timer runs out between kills, the job is over.'
HOST_NEEDS = ['A small free, flat area (about 20 x 18 m) where the bandits are packed together; open ground around it.',
              'A free strip (76 x 10 m) for the 26+ spare placeholders (parked, disabled).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 43
LEGACY_ROOT = 'SubM_43_Mesa_ComboChan.fragment'
GIVER_NAME = 'MESA_GIVER_COMBO'
COMMON = dict(giver=(-34.0, -26.0, 6.0), name='UNBROKEN COMBO',
              description='Bandits hold the courtyard. Gun down all of them without ever letting your combo run out: one missed combo and the job is over.',
              load_mid='KEEP THE COMBO', load_low='KILL FAST', pass_score=40, silver_score=400, gold_score=800)
TUT = 'data_pc/overdose_the_game/overdose/shared/tutorial_01.mission'
TUT_FRAG = 'Tut27_ComboTimer.fragment'
COND_MISSED = 0x102923

PARAMS = [
    P('arena', 'rect', lambda h, p: list(h.rr(-10, -10, 10, 8)), 'Bandit area', 'Rectangle [x0, z0, x1, z1] the bandits are packed into.', group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not fight are parked (disabled).', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 60, None), 'Parking spot', 'Where the template\'s tutorial zone and its marker are parked (disabled). y empty = ground + 1.', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-24, 9), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move the parked task giver off obstacles.', group='Placement', advanced=True),
    P('enemies', 'int', 4, 'Number of bandits', 'Bandits to kill in one combo.', min=2, max=29, group='Settings'),
    P('countdown', 'float', 150.0, 'Overall time limit', 'Seconds on the clock (a generous overall limit).', min=20.0, max=900.0, unit='s', group='Settings'),
    P('broken_delay', 'float', 2.0, 'Combo grace', 'Seconds between "combo missed" and the failure text.', min=0.0, max=10.0, unit='s', group='Settings', advanced=True),
    P('enemy_health', 'float', 0.3, 'Bandit health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.2, 'Bandit damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_combo', 'text', lambda h, p: 'Kill %d bandits without breaking your combo' % p['enemies'], 'Objective text', 'The objective line.', group='Texts', max_len=70),
    P('text_broken', 'text', 'You broke your combo! The job is over.', 'Failure text', 'Shown when the combo runs out.', group='Texts', max_len=60),
    P('text_won', 'text', 'Every bandit down in one unbroken combo!', 'Success text', 'Shown when the last bandit falls.', group='Texts', max_len=60),
]


def constraints(p, host):
    m = []
    if p['pass_score'] > 12 * p['enemies']:
        m.append(('warn', 'A kill scores about 10-25 points: %d bandits pay about %d, the pass score is %d.' % (p['enemies'], 10 * p['enemies'], p['pass_score'])))
    a = p['arena']
    if (a[2] - a[0]) * (a[3] - a[1]) < 4.0 * p['enemies'] * p['enemies']:
        m.append(('warn', 'The bandit area is small for %d bandits (they are kept 5 m apart where possible).' % p['enemies']))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    N = p['enemies']

    def design(ctx):
        W = ctx.world
        chars = sorted([n for n in ctx.find(type='character_placeholder', regex=r'^Vergillio_\d+$')], key=lambda n: str(n[4]))
        assert len(chars) == 31, len(chars)
        fighters = [c for c in chars if int(str(c[4]).split('_')[1]) >= 3][:N]
        spares = [c for c in chars if c not in fighters]
        fp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in fighters], region=p['arena'], min_sep=5.0)
        for c, xz in zip(fighters, fp):
            ctx.place_enemy(c, xz, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
            ctx.set_weapons(c, 0)
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=p['spare_region'], min_sep=1.5, margin=0.5)
        for c, xz in zip(spares, sp):
            ctx.place_enemy(c, xz)
            pk = ctx.parent_key(c)
            folder = [x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0]
            ctx.disable_folder(folder)
        for n in ctx.find(name='COND_AllEnemiesKilled', type='Trigger_Condition_Logical'):
            ctx.set(n, 'TrigAmount', N)
        ctx.set(ctx.one(name='ACT_SubM_37_Countdown'), 'Time', float(p['countdown']))

        def byk(key):
            return [n for n in ctx.nodes() if n[3] == key and n[2].endswith(ctx.old_root)][0]
        ctx.set(byk(0x400091), 'TrueOn', 9)
        ctx.retarget_names({'SubM_37_PerformCombo_OBJ': O('COMBO_OBJ_CHAIN'), 'SubM_37_Killmany_OBJ': O('COMBO_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        ctx.set(byk(0x40009E), 'TriggerOn', 1)
        ctx.set(byk(0x4000A0), 'SpecificActivator', O('COMBO_OBJ_KILLS'))
        ctx.set(byk(0x400084), 'flags', int(ctx.get(byk(0x400084), 'flags', 0)) | 1)
        zone = ctx.one(name='Trigger_cone_disable')
        pk = p['park']
        py = host.gy(pk[0], pk[2], pk[1]) if pk[1] is not None else host.gy(pk[0], pk[2]) + 1.0
        ctx.move(zone, (pk[0], py, pk[2])); ctx.set(zone, 'flags', int(ctx.get(zone, 'flags', 0)) | 1)
        for a in [n for n in ctx.nodes() if n[3] == 0x400073 and n[2].endswith(ctx.old_root)]:
            ctx.move(a, (pk[0], py + 5.35, pk[2]))
        ctx.set(ctx.one(name='ACT_ShowRadarBlip'), 'TargetName', str(fighters[0][4]))
        tg = ctx.one(regex=r'^TASKGIVER_')
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.move(tg, (tx, host.gy(tx, tz, gq[1]) + 0.8, tz))
        root_src = byk(0x400090)
        ctx.B.append(ctx.NEW, 'combo_root', (ctx.NEW, ctx.frag(root_src[2]), root_src[3]), parent=('ref', ctx.frag(root_src[2]), ctx.parent_key(root_src)),
                     name='COMBO_BROKEN_TRIG', sets={'flags': 1, 'Reactivate': False, 'TriggerOn': 0})
        ctx.B.append(ctx.NEW, 'combo_cond', (TUT, TUT_FRAG, COND_MISSED), parent=('new', 'combo_root'), name='COND_ComboMissed',
                     sets={'TrigAmount': 1, 'flags': 16})
        root = ('new', 'combo_root')

        def add(uid, template_key, name, sets):
            t = byk(template_key)
            ctx.B.append(ctx.NEW, uid, (ctx.NEW, ctx.frag(t[2]), t[3]), parent=root, name=name, sets=sets)
        bd = p['broken_delay']
        add('combo_fail', 0x400089, 'ACT_Combo_Mission_FAILED', {'Delay': bd + 3.0})
        add('combo_text', 0x40008A, 'ACT_Combo_broken_text', {'FeedbackText': ctx.texts['@broken'], 'Delay': bd})
        add('combo_stop', 0x400088, 'ACT_Combo_Countdown_STOP', {})
        add('combo_dis', 0x40009A, 'ACT_Combo_Enemies_Disable', {'Delay': bd + 2.5})
        kill_root = byk(0x40009B)
        ctx.add_action(byk(0x40008F), kill_root, 'combo_arm', name='ACT_Combo_ARM', sets={'ActionType': 5, 'TargetName': 'COMBO_BROKEN_TRIG'})
        win_root = byk(0x40009E)
        ctx.add_action(byk(0x40008A), win_root, 'combo_wintext', name='ACT_Combo_win_text', sets={'FeedbackText': ctx.texts['@won'], 'UseFeedbackText': True})
        ctx.add_action(byk(0x40008F), win_root, 'combo_disarm', name='ACT_Combo_DISARM', sets={'TargetName': 'COMBO_BROKEN_TRIG'})
        ctx.add_action(byk(0x40008F), win_root, 'combo_nofail', name='ACT_Combo_NOFAIL', sets={'TargetName': 'TRIG_Check_Mission_Failed'})
        ctx.add_action(byk(0x40008F), byk(0x400095), 'combo_disarm2', name='ACT_Combo_DISARM2', sets={'TargetName': 'COMBO_BROKEN_TRIG'})

    template = dict(slot=64, block='subm_37_down_move_kill.mission', root='SubM_37_Down_Move_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('combo', p['text_combo']), ('broken', p['text_broken']), ('won', p['text_won'])],
                     [{'DisplayText': '@combo', 'MaxCounter': N, 'CounterText': 247, 'name': O('COMBO_OBJ_CHAIN')},
                      {'MaxCounter': N, 'name': O('COMBO_OBJ_KILLS')}], design)
