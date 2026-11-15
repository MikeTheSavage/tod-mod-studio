"""Template 'marked': one bandit of a crowd is the marked man; the game picks him at random every play. (Mesa index 52.)

Template: registry slot 64 = SubM_37_Down_Move_Kill. New nodes (all appended CLONES of nodes of the template block, every wire is by name):
  MARKED_PICK (random one of N) -> MARKED_MARK<i> (radar blip, text, enable RIGHT<i>, disable WRONG<i>); MARKED_WRONG<i>: bandit i dies -> strike +1;
  MARKED_RIGHT<i> (disabled until marked): bandit i dies -> objective 'find' completed. Success = find completed; failure = strikes completed or the clock.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'marked'
TITLE = 'Marked Man'
SUMMARY = 'One bandit in a crowd is the marked man (chosen at random each play). Kill him; every wrong kill is a strike.'
HOST_NEEDS = ['A free, flat area of about 24 x 18 m where the crowd stands (bandits are spread over it, at least 3.5 m apart).',
              'A free strip (76 x 10 m) for the spare placeholders (parked, disabled).',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 52
LEGACY_ROOT = 'SubM_52_Mesa_MarkedMan.fragment'
GIVER_NAME = 'MESA_GIVER_MARKED'
COMMON = dict(giver=(-14.0, -1.0, 6.0), name='MARKED MAN',
              description='One bandit in the crowd has a price on his head, and only the game knows which. Find the marked man by the blip on your radar and kill him. Every other bandit you kill is a strike: three strikes and it is over.',
              load_mid='ONE OF THEM', load_low='FIND THE MARKED MAN', pass_score=0, silver_score=100, gold_score=300)
HUD_NAME = 62

PARAMS = [
    P('crowd', 'rect', lambda h, p: list(h.rr(-12, -10, 12, 8)), 'Crowd area', 'Rectangle [x0, z0, x1, z1] the bandits are spread over.', group='Placement'),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 28, 38, 38)), 'Spare strip', 'Where the enemies that do not take part are parked (disabled).', group='Placement', advanced=True),
    P('cone_zone', 'point', lambda h, p: h.pt(-14, -30), 'Parked tutorial zone', 'Where the template\'s (disabled) tutorial zone and arrow stand.', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(-24, 9), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move spots that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('bandits', 'int', 5, 'Number of bandits', 'Bandits in the crowd (one of them is marked).', min=2, max=29, group='Settings'),
    P('strikes', 'int', 3, 'Strikes allowed', 'Wrong kills that fail the mission.', min=1, max=20, group='Settings'),
    P('countdown', 'float', 120.0, 'Time limit', 'Seconds on the clock.', min=20.0, max=900.0, unit='s', group='Settings'),
    P('enemy_health', 'float', 0.3, 'Bandit health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.1, 'Bandit damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_find', 'text', 'Kill the marked bandit before the time runs out', 'Objective text', 'The objective line.', group='Texts', max_len=70),
    P('text_strikes', 'text', 'Do not kill the wrong bandits', 'Strikes text', 'The strikes objective line.', group='Texts', max_len=60),
    P('text_strikes_cnt', 'text', '%0 out of %1 wrong bandits killed', 'Strikes counter text', 'The strikes counter line.', group='Texts', max_len=50),
    P('text_wrong', 'text', 'Wrong bandit! That is a strike', 'Strike text', 'Shown at every wrong kill.', group='Texts', max_len=50),
]


def constraints(p, host):
    m = []
    if p['strikes'] >= p['bandits']:
        m.append(('warn', 'The player may kill every bandit and still not reach the strike limit: strikes (%d) should be below the number of bandits (%d).' % (p['strikes'], p['bandits'])))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    n = p['bandits']

    def _clone(ctx, uid, donor, parent, name=None, sets=None, pos=None):
        par = ('new', parent) if isinstance(parent, str) else ('ref', ctx.frag(parent[2]), parent[3])
        ctx.B.append(ctx.NEW, uid, (ctx.NEW, ctx.frag(donor[2]), donor[3]), parent=par, name=name, sets=dict(sets or {}), pos=pos)

    def design(ctx):
        W = ctx.world
        by_key = {x[3]: x for x in ctx.nodes()}
        K = lambda k: by_key[k]
        chars = sorted([c for c in ctx.find(type='character_placeholder', regex=r'^Vergillio_\d+$')], key=lambda c: str(c[4]))
        fighters = [c for c in chars if int(str(c[4]).split('_')[1]) >= 3][:n]
        spares = [c for c in chars if c not in fighters]
        fp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in fighters], region=p['crowd'], min_sep=3.5)
        for c, xz in zip(fighters, fp):
            ctx.place_enemy(c, xz, health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
            ctx.set_weapons(c, 0)
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in spares], region=p['spare_region'], min_sep=1.5, margin=0.5)
        for c, xz in zip(spares, sp):
            ctx.place_enemy(c, xz)
            pk = ctx.parent_key(c)
            ctx.disable_folder([x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0])
        names = [str(c[4]) for c in fighters]
        ctx.set(ctx.one(name='ACT_SubM_37_Countdown'), 'Time', float(p['countdown']))
        for key in (0x40008c, 0x400090, 0x40009b, 0x400095):
            ctx.set(K(key), 'flags', int(ctx.get(K(key), 'flags', 0)) | 1)
        zone = ctx.one(name='Trigger_cone_disable')
        ctx.set(zone, 'flags', int(ctx.get(zone, 'flags', 0)) | 1)
        cz = p['cone_zone']
        zx, zz = W.snap(cz[0], cz[2], margin=3.0) if p['snap_to_free_ground'] else (cz[0], cz[2])
        zg = host.gy(zx, zz, cz[1])
        ctx.move(zone, (zx, zg + 2.0, zz)); ctx.resize_box(zone, 6.0, 4.1, 6.0)
        ctx.disable_folder(ctx.one(name='Marker_Round_sm01', type='Folder'))
        for a in [x for x in ctx.nodes() if x[3] == 0x400073 and x[2].endswith(ctx.old_root)]:
            ctx.move(a, (zx, zg + 6.35, zz))
        for x in ctx.find(type='Trigger_Activate_Radar'):
            ctx.set(x, 'TargetName', 'MESA_UNUSED_TARGET')
        tg = ctx.one(regex=r'^TASKGIVER_')
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5) if p['snap_to_free_ground'] else (gq[0], gq[2])
        ctx.move(tg, (tx, host.gy(tx, tz, gq[1]) + 0.8, tz))
        ctx.retarget_names({'SubM_37_PerformCombo_OBJ': O('MARKED_OBJ_FIND'), 'SubM_37_Killmany_OBJ': O('MARKED_OBJ_STRIKES')}, props=('TargetName', 'SpecificActivator'))
        c1, c2 = K(0x40009f), K(0x4000a0)
        ctx.set(c1, 'TrueOn', 2); ctx.set(c1, 'SpecificActivator', O('MARKED_OBJ_FIND')); ctx.set(c1, 'TrigAmount', 1)
        ctx.set(K(0x4000a1), 'TargetName', 'MESA_UNUSED_TARGET')
        ctx.set(K(0x4000a4), 'Delay', 4.0)
        f1, f2 = K(0x400085), K(0x400086)
        for c in (f1, f2):
            ctx.set(c, 'TrueOn', 2); ctx.set(c, 'SpecificActivator', O('MARKED_OBJ_STRIKES')); ctx.set(c, 'TrigAmount', 1)
        ctx.set(K(0x400087), 'TargetName', 'MESA_UNUSED_TARGET')
        ctx.set(K(0x400089), 'Delay', 4.0)
        ctx.set(K(0x40008a), 'UseFeedbackText', True); ctx.set(K(0x40008a), 'FeedbackText', ctx.texts['@wrong'])
        D_ROOT, D_START, D_TRIG, D_REMOTE = K(0x400076), K(0x400077), K(0x40007f), K(0x400097)
        D_OBJ, D_TEXT, D_ENDIS, D_RADAR = K(0x40009d), K(0x400083), K(0x400082), K(0x400078)
        folder = K(0x400075)
        _clone(ctx, 'marked_pick', D_ROOT, folder, name='MARKED_PICK', sets={'FireRandomActions': True, 'NumRandomActions': 1})
        _clone(ctx, 'marked_pick_c', D_START, 'marked_pick', name='MARKED_PICK_START')
        for i, nm in enumerate(names):
            u = 'marked_%d_' % i
            _clone(ctx, u + 'pick', D_TRIG, 'marked_pick', name='MARKED_PICK_A%d' % i, sets={'TargetName': 'MARKED_COND_MARK%d' % i, 'Delay': 1.5})
            _clone(ctx, u + 'mark', D_ROOT, folder, name='MARKED_MARK%d' % i)
            _clone(ctx, u + 'markc', D_REMOTE, u + 'mark', name='MARKED_COND_MARK%d' % i, sets={'SpecificActivator': 'MARKED_PICK'})
            _clone(ctx, u + 'rad', D_RADAR, u + 'mark', name='MARKED_RADAR%d' % i, sets={'TargetName': nm, 'RadarType': 3, 'MapRelation': -1})
            _clone(ctx, u + 'txt', D_TEXT, u + 'mark', name='MARKED_TXT%d' % i, sets={'UseFeedbackText': True, 'FeedbackText': ctx.texts['@find'], 'Delay': 0.5, 'StayTime': 4.0})
            _clone(ctx, u + 'on', D_ENDIS, u + 'mark', name='MARKED_ON%d' % i, sets={'TargetName': 'MARKED_RIGHT%d' % i, 'ActionType': 5})
            _clone(ctx, u + 'off', D_ENDIS, u + 'mark', name='MARKED_OFF%d' % i, sets={'TargetName': 'MARKED_WRONG%d' % i, 'ActionType': 6})
            _clone(ctx, u + 'wrong', D_ROOT, folder, name='MARKED_WRONG%d' % i)
            _clone(ctx, u + 'wrongc', D_REMOTE, u + 'wrong', name='MARKED_WRONG_DIES%d' % i, sets={'TrueOn': 3, 'ActivatorType': 4, 'SpecificActivator': nm})
            _clone(ctx, u + 'strike', D_OBJ, u + 'wrong', name='MARKED_STRIKE%d' % i, sets={'TargetName': O('MARKED_OBJ_STRIKES')})
            _clone(ctx, u + 'wtxt', D_TEXT, u + 'wrong', name='MARKED_WTXT%d' % i, sets={'UseFeedbackText': True, 'FeedbackText': ctx.texts['@wrong'], 'Delay': 0.2, 'StayTime': 3.0})
            _clone(ctx, u + 'right', D_ROOT, folder, name='MARKED_RIGHT%d' % i, sets={'flags': 1})
            _clone(ctx, u + 'rightc', D_REMOTE, u + 'right', name='MARKED_RIGHT_DIES%d' % i,
                   sets={'TrueOn': 3, 'ActivatorType': 4, 'SpecificActivator': nm, 'ShowInHUD': True, 'HUDName': HUD_NAME})
            _clone(ctx, u + 'done', D_OBJ, u + 'right', name='MARKED_DONE%d' % i, sets={'TargetName': O('MARKED_OBJ_FIND'), 'ActionType': 72})
        ctx.log.append('marked bandits: %s' % names)

    template = dict(slot=64, block='subm_37_down_move_kill.mission', root='SubM_37_Down_Move_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template,
                     [('find', p['text_find']), ('strikes', p['text_strikes']), ('strikes_cnt', p['text_strikes_cnt']), ('wrong', p['text_wrong'])],
                     [{'DisplayText': '@find', 'HasObjectivesCounter': False, 'MaxCounter': 1, 'name': O('MARKED_OBJ_FIND')},
                      {'DisplayText': '@strikes', 'CounterText': '@strikes_cnt', 'WriteOutOf': True, 'MaxCounter': p['strikes'], 'name': O('MARKED_OBJ_STRIKES')}], design,
                     ALLOW_UNRESOLVED=['MESA_UNUSED_TARGET'])
