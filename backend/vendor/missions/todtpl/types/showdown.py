"""Template 'showdown': go to the bandit camp, kill the bandits, return to the gate. (Mesa index 71.)

Template block: the D1 variant of SubM_04_Down_SomSal_Kill (registry slot 33 = Sombrero Shootout; variant file missions/mesa/base/subm_04_d1.mission).
Ported from missions/types/showdown.py: every position is a parameter in WORLD metres.
"""
import os, re, sys
from ..tpl_core import P
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'showdown'
TITLE = 'Showdown'
SUMMARY = 'Walk to a bandit camp, shoot the gang, then return to a marked strip. Three bandits stand at positions you choose.'
HOST_NEEDS = ['Free, flat ground for the camp (about 20 x 20 m) and for the two zones.',
              'Walkable ground between the start spot and the camp; nothing else (no roads, no buildings).',
              'Works in any new map and in any existing map section that has flat ground.']
LEGACY_INDEX = 71
LEGACY_ROOT = 'SubM_71_Down_NewJob_Kill.fragment'
GIVER_NAME = 'MESA_MISSION_GIVER'
COMMON = dict(giver=(0.0, -17.0, 8.0), name='MESA SHOWDOWN',
              description='A bandit gang holds the old compound on the mesa. Fight your way in, take them out, then return to the gate.')
TEMPLATE_BLOCK_VARIANT = 'variant:d1'      # made from the player's own blocks by tpl_variant (the edit recipe is data/d1_go_kill3_return.json); the lab keeps a byte-identical copy
ENEMY_NAMES = ['SubM_04_Down_SomSal_Kill_Peter', 'SubM_04_Down_SomSal_Kill_Peter01', 'SubM_04_Down_SomSal_Kill_Brian']

PARAMS = [
    P('bandits', 'points', lambda h, p: [h.pt(0, 8), h.pt(6, 11), h.pt(-6, 11)], 'Bandit positions', 'Where the three bandits stand (x, y, z). The template has exactly three.', min_len=3, max_len=3, group='Placement'),
    P('go_zone', 'point', lambda h, p: h.pt(0, -13), 'Camp zone', 'Centre of the zone the player walks into to "reach the camp".', group='Placement'),
    P('go_width', 'float', 14.0, 'Camp zone width', 'East-west size of the camp zone.', min=4.0, max=60.0, unit='m', group='Placement'),
    P('go_length', 'float', 4.0, 'Camp zone length', 'North-south size of the camp zone.', min=2.0, max=60.0, unit='m', group='Placement'),
    P('return_zone', 'point', lambda h, p: h.pt(5, -26), 'Return zone', 'Centre of the strip the player must reach after the kills (enabled once enough bandits are dead).', group='Placement'),
    P('return_width', 'float', 50.0, 'Return zone width', 'East-west size of the return zone.', min=4.0, max=80.0, unit='m', group='Placement'),
    P('return_length', 'float', 16.0, 'Return zone length', 'North-south size of the return zone.', min=2.0, max=60.0, unit='m', group='Placement'),
    P('prop_pos', 'point', lambda h, p: h.pt(5, -25), 'Burrito prop', 'Position of the template prop that sits in the return zone (decoration).', group='Placement', advanced=True),
    P('kills_needed', 'int', 2, 'Kills needed', 'How many of the three bandits must die before the return zone opens.', min=1, max=3, group='Settings'),
    P('enemy_health', 'float', 0.3, 'Bandit health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.2, 'Bandit damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_go', 'text', 'Reach the bandit camp', 'Objective 1 text', 'First objective line.', group='Texts', max_len=60),
    P('text_back', 'text', 'Return to the gate', 'Objective 3 text', 'Last objective line.', group='Texts', max_len=60),
]


def constraints(p, host):
    m = []
    gz = p['go_zone']
    if host is not None and host.arrival.get('pos'):
        a = host.arrival['pos']
        if abs(gz[0] - a[0]) < p['go_width'] / 2 and abs(gz[2] - a[2]) < p['go_length'] / 2:
            m.append(('warn', 'The camp zone covers the arrival spot: the first objective completes at once.'))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    GY_ = lambda pt, dy: host.gy(pt[0], pt[2], pt[1]) + dy
    enemies = {nm.lower(): pt for nm, pt in zip(ENEMY_NAMES, p['bandits'])}
    zones = {0x004018D3: dict(pos=(p['go_zone'][0], GY_(p['go_zone'], 0.8), p['go_zone'][2]), size=(p['go_width'], 4, p['go_length'])),
             0x0040190F: dict(pos=(p['return_zone'][0], GY_(p['return_zone'], 0.8), p['return_zone'][2]), size=(p['return_width'], 4, p['return_length']), flags=257)}
    kills = float(p['kills_needed'])

    def design(ctx):
        cur = None
        moved = 0
        for n in ctx.nodes():
            idx, ty, f, key, name, path = n
            t = ty.split('(')[0]
            if t == 'Folder' and str(name).startswith('Enemy'):
                cur = None
            if t == 'character_placeholder' and str(name).lower() in enemies:
                pt = enemies[str(name).lower()]
                x, z = pt[0], pt[2]
                gy = GY_(pt, 0.8)
                ctx.move(n, [x, gy, z]); moved += 1
                ctx.set(n, 'Damage_mod', p['enemy_damage']); ctx.set(n, 'Health_mod', p['enemy_health'])
                cur = (x, z, gy)
            elif cur and t == 'Pathtype' and name == 'GotoPath':
                ctx.move(n, [cur[0], cur[2], cur[1]])
            elif cur and t == 'Trigger_Root' and name == 'Trigger':
                ctx.move(n, [cur[0], cur[2] + 1, cur[1]])
                ctx.resize_box(n, 14.0, 6.0, 14.0)
            elif t == 'Trigger_Root' and name == 'First_Enemy_team_KILL_Completed':
                ctx.set(n, 'ConditionsNeeded', kills)
            elif t == 'Trigger_Activate_Camera' and name == 'ACT_OpenLotJump_Cam01':
                ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
            elif t == 'Model' and name == 'SubM_04_Down_SomSal_Kill_Bur':
                pp = p['prop_pos']
                ctx.move(n, [pp[0], host.gy(pp[0], pp[2], pp[1]) + 0.4, pp[2]])
            elif t == 'Trigger_Root' and key in zones:
                z = zones[key]
                ctx.place(n, z['pos'])                          # under a NodeLogical parent: local pos (docs 20.3 #2)
                ctx.resize_box(n, *z['size'])
                if 'flags' in z:
                    ctx.set(n, 'flags', z['flags'])
        assert moved == len(enemies), 'enemy placeholders moved %d of %d' % (moved, len(enemies))

        def which(v):
            m = re.fullmatch(r'SubM_04_Sombrero_OBJ(\d?)', v, re.I)
            return O('MESA_OBJ' + (m.group(1) or '1')) if m else None
        ctx.retarget_names(which, props=('TargetName',), classes=('Trigger_Activate_Objective',), skip=('ACT_D1_Kill_OBJ_COMPLETE',))

    template = dict(slot=33, block='subm_04_down_somsal_kill.mission', root='SubM_04_Down_SomSal_Kill.fragment', block_path=TEMPLATE_BLOCK_VARIANT)
    return make_spec(MOD, p, host, inst, template, [('go', p['text_go']), ('back', p['text_back'])],
                     [{'DisplayText': '@go', 'name': O('MESA_OBJ1')}, {'MaxCounter': 2, 'name': O('MESA_OBJ2')}, {'DisplayText': '@back', 'name': O('MESA_OBJ3')}],
                     design, ALLOW_UNRESOLVED=['SM04_DoorA', 'SM04_DoorB', 'Sm04_Havoc'],
                     OUTSIDE_OK='inactive template content of the Downtown camp, never enabled; kept for byte-identity with the old builder')
