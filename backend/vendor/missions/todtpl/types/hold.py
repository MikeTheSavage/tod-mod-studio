"""Template 'hold': stand inside the marked zone for N seconds while three waves of bandits attack. (Mesa index 78.)

Leaving the zone pauses the progress (it is a counter, nothing resets); going back in continues.
Template: registry slot 64 = SubM_37_Down_Move_Kill. The stunt's walk-in "cone zone" IS the hold zone: entering enables a 1 s tick loop (three ping-pong roots HOLD_LOOP,
HOLD_LOOP2, HOLD_LOOP3), leaving disables it. Objective PerformCombo = the hold counter (MaxCounter = seconds, AutoCompleteOnMax) completes the mission.
Waves: 9 of the 31 Vergillios fight, three at the start, three after wave_delays[1], three after wave_delays[2].
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'hold'
TITLE = 'Hold the Zone'
SUMMARY = 'Stand inside a marked zone for a set time while three waves of bandits attack. Leaving the zone pauses the clock.'
HOST_NEEDS = ['A free, flat square of at least 10 x 10 m for the zone; open ground within 25 m for nine attackers in three waves.',
              'A free strip (76 x 10 m) for the 22 spare placeholders (parked, disabled).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 78
LEGACY_ROOT = 'SubM_78_Mesa_HoldZone1.fragment'
GIVER_NAME = 'MESA_GIVER_HOLD'
COMMON = dict(giver=(14.0, -18.0, 6.0), name='HOLD THE ZONE',
              description='Bandits want the marked ground in the compound. Stand in the zone and hold it for a full minute while they attack in waves. Step out and the clock stops, step back in and it runs on.',
              load_mid='STAND YOUR GROUND', load_low='HOLD THE ZONE', pass_score=0, silver_score=200, gold_score=400)
MIN_SECONDS = 5
SLOW = 99999.0
NPP = 3
_WAVES_REL = [(-12.0, 4.0), (18.0, 4.0), (4.0, 14.0), (-12.0, -14.0), (20.0, -14.0), (6.0, -22.0), (-8.0, 12.0), (14.0, 12.0), (22.0, -2.0)]

PARAMS = [
    P('zone', 'point', lambda h, p: h.pt(4, -4), 'Hold zone', 'Centre of the zone the player must stand in.', group='Placement'),
    P('zone_size', 'float', 10.0, 'Zone size', 'Edge length of the square hold zone.', min=4.0, max=40.0, unit='m', group='Placement'),
    P('attackers', 'points', lambda h, p: [h.pt(x, z) for x, z in _WAVES_REL], 'Attacker positions', 'Nine attackers: the first three are wave 1, the next three wave 2, the last three wave 3 (x, y, z).', min_len=9, max_len=9, group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not fight are parked (disabled).', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(14, -24), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move attackers that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('seconds', 'int', 60, 'Seconds to hold', 'Seconds the player must spend inside the zone (one tick per second inside). At least %d.' % MIN_SECONDS, min=MIN_SECONDS, max=600, unit='s', group='Settings'),
    P('wave_delays', 'floats', [0.0, 20.0, 40.0], 'Wave delays', 'Seconds after the start at which each wave of three arrives (the three of a wave are 1.5 s apart).', min_len=3, max_len=3, group='Settings'),
    P('enemy_health', 'float', 0.3, 'Attacker health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.01, 'Attacker damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_hold', 'text', lambda h, p: 'Hold the zone for %d seconds' % p['seconds'], 'Objective text', 'The objective line.', group='Texts', max_len=60),
    P('text_count', 'text', '%0 out of %1 seconds held', 'Counter text', 'The counter line (%0 = seconds held, %1 = needed).', group='Texts', max_len=50),
    P('text_leave', 'text', 'You left the zone. Get back in to keep holding!', 'Leave warning', 'Shown when the player steps out of the zone.', group='Texts', max_len=60),
    P('text_done', 'text', 'Zone held!', 'Success text', 'Shown when the zone is held.', group='Texts', max_len=40),
]


def constraints(p, host):
    m = []
    if p['wave_delays'][0] != 0.0:
        m.append(('error', 'The first wave must arrive at 0 seconds.'))
    if any(p['wave_delays'][i] > p['wave_delays'][i + 1] for i in range(2)):
        m.append(('error', 'The wave delays must not go down.'))
    if p['wave_delays'][2] + 3.0 > p['seconds']:
        m.append(('warn', 'The last wave arrives after the zone could already be held; make the hold longer or the waves earlier.'))
    z, hf = p['zone'], p['zone_size'] / 2
    for i, a in enumerate(p['attackers']):
        if abs(a[0] - z[0]) < hf + 1.5 and abs(a[2] - z[2]) < hf + 1.5:
            m.append(('warn', 'Attacker %d starts inside or right next to the hold zone.' % (i + 1)))
            break
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    SECONDS = p['seconds']

    def design(ctx):
        from .. import tpl_env
        E = tpl_env.get()
        W = ctx.world
        zc = p['zone']
        zx, zz = zc[0], zc[2]
        zy = host.gy(zx, zz, zc[1])
        ZS = p['zone_size']
        chars = sorted(ctx.find(type='character_placeholder', regex=r'^Vergillio_\d+$'), key=lambda n: str(n[4]))
        fighters = [c for c in chars if int(str(c[4]).split('_')[1]) >= 3][:9]
        spares = [c for c in chars if c not in fighters]
        taken = []
        k = 0
        enable = ctx.one(name='ACT_Enable_Enemies')
        for wi in range(3):
            for wj in range(3):
                pt = p['attackers'][3 * wi + wj]
                c = fighters[k]; k += 1
                x, z = W.snap(pt[0], pt[2], margin=1.5, taken=taken, min_sep=4.0) if p['snap_to_free_ground'] else (pt[0], pt[2])
                taken.append((x, z))
                ctx.place_enemy(c, (x, z), y=host.gy(x, z, pt[1]) + 0.8, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
                ctx.set_weapons(c, 0)
                pk = ctx.parent_key(c)
                folder = [n for n in ctx.nodes() if n[2] == c[2] and n[3] == pk][0]
                if wi > 0:
                    fname = O('HOLD_W%d_%d' % (wi + 1, wj + 1))
                    ctx.set(folder, 'name', fname)
                    ctx.disable_folder(folder)
                    ctx.add_action(enable, ctx.one(name='TRIG_Start'), 'hold_wave_%d_%d' % (wi + 1, wj + 1), name='ACT_Wave_%d_%d' % (wi + 1, wj + 1),
                                   sets={'TargetName': fname, 'Delay': p['wave_delays'][wi] + 1.5 * wj})
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=p['spare_region'], min_sep=1.5, margin=0.5)
        for c, xz in zip(spares, sp):
            ctx.place_enemy(c, xz)
            pk = ctx.parent_key(c)
            ctx.disable_folder([n for n in ctx.nodes() if n[2] == c[2] and n[3] == pk][0])
        tg = ctx.one(regex=r'^TASKGIVER_')
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.move(tg, (tx, host.gy(tx, tz, gq[1]) + 0.8, tz))
        ctx.retarget_names({'SubM_37_PerformCombo_OBJ': O('HOLD_OBJ_HOLD'), 'SubM_37_Killmany_OBJ': O('HOLD_OBJ_KILLS')}, props=('TargetName', 'SpecificActivator'))
        ctx.set(ctx.one(name='ACT_SubM_37_Countdown'), 'Delay', SLOW)
        ctx.set(ctx.one(name='ACT_SubM_37_KillMany_OBJ'), 'Delay', SLOW)
        for n in ctx.find(name='COND_AllEnemiesKilled', type='Trigger_Condition_Logical'):
            ctx.set(n, 'TrigAmount', 9999)
        ctx.set(ctx.one(name='TRIG_Check_Mission_Complete'), 'TriggerOn', 1)
        ctx.set([n for n in ctx.find(name='ACT_SubM_37_Mission_COMPLETE') if n[3] == 0x400098][0], 'Delay', 3.0)
        done = ctx.one(name='ACT_SubM_37_PerformCombo_OBJ_COMPLETE_Feedback')
        ctx.set(done, 'FeedbackText', ctx.texts['@done']); ctx.set(done, 'Delay', 0.3)
        ctx.set(ctx.one(name='ACT_SubM_37_Feedback'), 'Delay', SLOW)
        zone = ctx.one(name='Trigger_cone_disable')
        ctx.move(zone, (zx, zy + 2.0, zz)); ctx.resize_box(zone, ZS, 4.1, ZS)
        ctx.set(zone, 'Reactivate', True); ctx.set(zone, 'ReactivateDelay', 0.5)
        for s in L_kids(ctx, zone):
            if s[4] == 'Trigger_enter':
                pass
            elif s[4] == 'Disable_cone':
                ctx.set(s, 'TargetName', 'HOLD_NONE')
            elif s[4] == 'ACT_RemRadarBlip':
                ctx.set(s, 'TargetName', 'HOLD_NONE')
            elif s[4] == 'Activate_Pause_Text':
                ctx.set(s, 'Delay', SLOW); ctx.set(s, 'UsePauseMode', False); ctx.set(s, 'StayTime', 0.1)
                ctx.set(s, 'flags', int(ctx.get(s, 'flags', 0)) | 1)
        for a in [n for n in ctx.nodes() if n[3] == 0x400073 and n[2].endswith(ctx.old_root)]:
            ctx.move(a, (zx, zy + 6.35, zz))
        ctx.set(ctx.one(name='ACT_ShowRadarBlip'), 'TargetName', 'Trigger_cone_disable')
        NEWF = ctx.NEW
        fl = lambda n: ctx.frag(n[2])
        RACE = lambda kk: (E.SHARED + 'subm_06_indu_chepoi_race.mission', 'SubM_06_Indu_ChePoi_Race.fragment', kk)
        trig_act = ctx.one(name='ACT_Trig_SubM37_CountdownComplete1')
        tick = ctx.one(name='ACT_SubM_37_PerformCombo_OBJ_COUNTER')
        enab = ctx.one(name='ACT_Enable_Enemies')
        disab = [n for n in ctx.find(name='ACT_SubM_37_Enemies_Disable') if n[3] == 0x40008B][0]
        folder_new = ctx.one(name='new', type='Folder')
        names = ['HOLD_LOOP'] + ['HOLD_LOOP%d' % (i + 1) for i in range(1, NPP)]
        for i, nm in enumerate(names):
            uid = 'hold_pp%d' % i
            nxt = names[(i + 1) % NPP]
            ctx.B.append(NEWF, uid, RACE(0x401243), parent=('ref', fl(folder_new), folder_new[3]), deep=False, name=nm,
                         sets={'Reactivate': True, 'ReactivateDelay': 0.1, 'TriggerOn': 1})
            ctx.B.append(NEWF, uid + '_cA', RACE(0x401244), parent=('new', uid), name=nm + '_COND')
            for at in (1, 2, 3, 5):
                ctx.B.append(NEWF, uid + '_cT%d' % at, RACE(0x401244), parent=('new', uid), name=nm + '_COND_T%d' % at, sets={'ActivatorType': at})
            if i == 0:
                ctx.B.append(NEWF, uid + '_tick', (NEWF, fl(tick), tick[3]), parent=('new', uid), name='ACT_HoldTick')
            ctx.B.append(NEWF, uid + '_next', (NEWF, fl(trig_act), trig_act[3]), parent=('new', uid), name='ACT_HoldNext%d' % i,
                         sets={'TargetName': nxt, 'Delay': round(1.0 / NPP, 3)})
            ctx.B.append(NEWF, uid + '_on', (NEWF, fl(enab), enab[3]), parent=('ref', fl(zone), zone[3]), name='ACT_HoldOn%d' % i, sets={'TargetName': nm, 'Delay': 0.0})
        ctx.B.append(NEWF, 'hold_zone_first', (NEWF, fl(trig_act), trig_act[3]), parent=('ref', fl(zone), zone[3]), name='ACT_HoldFirst',
                     sets={'TargetName': 'HOLD_LOOP', 'Delay': 0.3})
        LOOP_NAMES = names
        wake = ctx.one(name='Trigger', type='Trigger_Root(CollisionBox)')
        folder_new = ctx.one(name='new', type='Folder')
        ctx.B.append(ctx.NEW, 'hold_leave', (ctx.NEW, ctx.frag(wake[2]), wake[3]), parent=('ref', ctx.frag(folder_new[2]), folder_new[3]), deep=True,
                     name='HOLD_LEAVE_ZONE', pos=[zx, zy + 2.0, zz], rot=[0.0, 0.0, 0.0, 1.0],
                     sets={'width': float(ZS), 'height': 4.1, 'length': float(ZS), 'Reactivate': True, 'ReactivateDelay': 5.0, 'flags': 256},
                     child_sets=[{'type': 'Trigger_Condition(NodeLogical)', 'set': {'TrueOn': 0}},
                                 {'type': 'Trigger_Activate_Trig_Noaction_Reactivate(NodeLogical)', 'set': {'TargetName': 'HOLD_NONE', 'ActivateWho': 3}}])
        fb = [n for n in ctx.find(name='ACT_SubM_37_failed_text') if n[3] == 0x4000AC][0]
        ctx.B.append(ctx.NEW, 'hold_leave_text', (ctx.NEW, ctx.frag(fb[2]), 0x4000AC), parent=('new', 'hold_leave'), name='ACT_LeaveText',
                     sets={'FeedbackText': ctx.texts['@leave'], 'UseFeedbackText': True})
        for i, nm in enumerate(LOOP_NAMES):
            ctx.B.append(NEWF, 'hold_leave_off%d' % i, (NEWF, fl(disab), disab[3]), parent=('new', 'hold_leave'), name='ACT_HoldOff%d' % i, sets={'TargetName': nm})

    template = dict(slot=64, block='subm_37_down_move_kill.mission', root='SubM_37_Down_Move_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('hold', p['text_hold']), ('count', p['text_count']), ('leave', p['text_leave']), ('done', p['text_done'])],
                     [{'DisplayText': '@hold', 'CounterText': '@count', 'MaxCounter': SECONDS, 'name': O('HOLD_OBJ_HOLD')}, {'MaxCounter': 9, 'name': O('HOLD_OBJ_KILLS')}], design,
                     ALLOW_UNRESOLVED=['HOLD_NONE'])


def L_kids(ctx, n):
    return [x for x in ctx.nodes() if x[2] == n[2] and ctx.get(x, 'parent', 0) == n[3]]
