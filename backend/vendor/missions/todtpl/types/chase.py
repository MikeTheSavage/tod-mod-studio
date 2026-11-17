"""Template 'chase': a smuggler's truck flees along an AI route through Downtown; stop it before the clock runs out. (Mesa index 77.)

The mission does NOT play in the host map: only the GIVER stands in the host. The award keeps the template's own map / submap / start map (Downtown), so accepting
loads Downtown, puts the player at the street start below, and MISSION COMPLETE returns the player the way every sub-mission does. The truck's route (19 AI track points,
about 330 m) is part of the template and cannot be moved: this template needs Downtown's roads, whatever host the giver is in.
Template: registry slot 34 = SubM_05_Down_TeqSal_Kill ("Tequila").
"""
import math, sys
from ..tpl_core import P
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'chase'
TITLE = 'Vehicle Chase'
SUMMARY = 'The giver stands in your map, the chase runs through Downtown: stop a fleeing truck before time runs out.'
HOST_NEEDS = ['Only the giver box needs the host: any free spot of any map or section.',
              'The chase itself is played in Downtown (it needs its drivable roads); a host map without roads cannot replace that. The mission moves the player to Downtown and back.',
              'The start point, the player\'s car and the truck are placed in Downtown coordinates, not host coordinates.']
LEGACY_INDEX = 77
LEGACY_ROOT = 'SubM_77_Down_VehChase_01.fragment'
GIVER_NAME = 'MESA_GIVER_CHASE'
COMMON = dict(giver=(28.0, 12.0, 6.0), name='VEHICLE CHASE',
              description='A smuggler is making a run for it in his truck through the streets of Downtown. Grab the car, catch him and take him out before he gets away.',
              load_mid='CATCH THE TRUCK', load_low='DRIVE + RAM + SHOOT', pass_score=300, silver_score=600, gold_score=1000,
              start_spot='TELEPORTPOINT_SubM_05_Down_TeqSal_Kill')

PARAMS = [
    P('start_pos', 'point', [65.7, 4.9, 61.9], 'Player start (Downtown)', '', group='Placement'),
    P('start_yaw', 'angle', -67.0, 'Player start direction', '', min=-180.0, max=360.0, unit='deg', group='Placement'),
    P('car_pos', 'point', [62.9, 4.9, 57.8], 'Player car (Downtown)', '', group='Placement'),
    P('car_yaw', 'angle', -67.0, 'Player car direction', '', min=-180.0, max=360.0, unit='deg', group='Placement'),
    P('countdown', 'float', 120.0, 'Time limit', '', min=20.0, max=900.0, unit='s', group='Settings'),
    P('truck_delay', 'float', 4.0, 'Truck start delay', '', min=0.0, max=60.0, unit='s', group='Settings'),
    P('truck_health', 'float', 3.0, 'Truck health', '', min=0.5, max=30.0, group='Settings'),
    P('truck_speed', 'float', 0.6, 'Truck speed', 'A normal car catches 0.6', min=0.2, max=1.5, group='Settings'),
    P('driver_damage', 'float', 0.3, 'Driver damage', '', min=0.0, max=3.0, group='Settings'),
    P('text_chase', 'text', 'Stop the escaping truck before time runs out', 'Objective text', '', group='Texts', max_len=70),
]


def constraints(p, host):
    m = [('info', 'The chase is played in Downtown, not in the host map; only the giver box is placed in the host.')]
    if p['truck_delay'] >= p['countdown']:
        m.append(('error', 'The truck would start after the clock has run out.'))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx

    def design(ctx):
        from .. import tpl_env
        E = tpl_env.get()
        nodes = {n[3]: n for n in ctx.nodes()}
        sh = E.SHARED
        SUBM29, SUBM29_FRAG = 'subm_29_down_scadea_escort.mission', 'SubM_29_Down_ScaDea_Escort.fragment'
        SUBM08, SUBM08_FRAG = 'subm_08_down_7gates01_race.mission', 'SubM_08_Down_7gates01_Race.fragment'
        start = ctx.one(name='SubM_05_Down_TeqSal_Kill_START')
        succ = ctx.one(name='MISSION_SUCCES_Cond_Car')
        ctx.retarget_names({'SubM_05_Tequila_OBJ': O('CHASE_OBJ_TRUCK'), 'SubM_05_Tequila_OBJ2': O('CHASE_OBJ_UNUSED2'), 'SubM_05_Tequila_OBJ3': O('CHASE_OBJ_UNUSED3')},
                           props=('TargetName', 'SpecificActivator'))
        rb = ctx.one(name='Activate_RADARBLIB_01')
        ctx.set(rb, 'TargetName', 'Cheater_sm05'); ctx.set(rb, 'RadarType', 8); ctx.set(rb, 'MapRelation', -1)
        ctx.set(ctx.one(name='Enable_Tequilla'), 'TargetName', 'AI_Vehicle1_sm05')
        ctx.add_action(nodes[0x40018F], start, 'chase_cartrig', name='CHASE_Truck_go', sets={'Delay': p['truck_delay']})
        ctx.B.append(ctx.NEW, 'chase_countdown', (sh + SUBM29, SUBM29_FRAG, 0x400B74), parent=('ref', ctx.frag(start[2]), start[3]), deep=True,
                     name='CHASE_Countdown', sets={'Time': p['countdown'], 'Delay': 1.0})
        ctx.add_action(nodes[0x400174], succ, 'chase_objdone', name='CHASE_OBJ_done', sets={'TargetName': O('CHASE_OBJ_TRUCK'), 'Delay': 0.0})
        ctx.add_action_from((SUBM29, SUBM29_FRAG, 0x400C81), succ, 'chase_cdstop', name='CHASE_Countdown_stop', sets={'Delay': 0.0})
        cond = ctx.one(name='Condition_AI_Vehicle1_sm05')
        ctx.set(cond, 'ShowInHUD', True); ctx.set(cond, 'HUDName', 52)
        truck = ctx.one(name='AI_Vehicle1_sm05')
        ctx.set(truck, 'Health_modify', p['truck_health'])
        ctx.set(truck, 'VehicleAISpeedMultiplier', p['truck_speed'])
        ctx.set(ctx.one(name='Cheater_sm05'), 'Damage_mod', p['driver_damage'])
        for nm in ('Sm05_Close_doors', 'Activate_objective'):
            n = ctx.one(name=nm)
            ctx.set(n, 'flags', int(ctx.get(n, 'flags', 0)) | 1)
        sy = math.radians(p['start_yaw'])
        ctx.move(ctx.one(name='TELEPORTPOINT_SubM_05_Down_Inside'), tuple(p['start_pos']), rot=[0.0, math.sin(sy / 2), 0.0, math.cos(sy / 2)])
        ctx.add_action(nodes[0x400165], start, 'chase_align', name='CHASE_Align_Player', sets={'Delay': 0.3})
        th = math.radians(p['car_yaw'])
        gameplay = ctx.one(name='SubM_05_Down_TeqSal_Kill_GAMEPLAY')
        ctx.B.append(ctx.NEW, 'chase_car', (sh + SUBM08, SUBM08_FRAG, 0x400085), parent=('ref', ctx.frag(gameplay[2]), gameplay[3]), deep=True,
                     name='CHASE_Player_Car', pos=list(p['car_pos']), rot=[0.0, math.sin(th / 2), 0.0, math.cos(th / 2)])

    template = dict(slot=34, block='subm_05_down_teqsal_kill.mission', root='SubM_05_Down_TeqSal_Kill.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('chase', p['text_chase'])],
                     [{'DisplayText': '@chase', 'MaxCounter': 0, 'name': O('CHASE_OBJ_TRUCK')}, {'name': O('CHASE_OBJ_UNUSED2')}, {'name': O('CHASE_OBJ_UNUSED3')}], design,
                     AWARD_SETS={'Mission_Map': 1, 'Mission_SubMap': 3, 'Mission_StartMap': 3},
                     ALLOW_UNRESOLVED=['coke_SM05', 'TrafficPoints_M02S02', 'SubM_05_Down_TeqSal_Kill_DrugPickup_Activate_Runner', 'SubM_05_Down_TeqSal_Kill_Tequila',
                                       'SubM_05_Down_TeqSal_Kill_Door_A_Close', 'SubM_05_Down_TeqSal_Kill_Door_A', 'SubM_05_Down_TeqSal_Kill_Door_A_Open',
                                       'SubM_05_Down_TeqSal_Kill_Door_B', 'SubM_05_Down_TeqSal_Kill_StandardGarageDoor_01_Lever_Vertical',
                                       'SubM_05_Down_TeqSal_Kill_StandardGarageDoor_01_Lever_Vertical_Trigger'],
                     OUTSIDE_OK='the chase is played on the Downtown streets (template positions are untouched), not in the host map')
