"""Enum tables of the mission/trigger script classes (GOG TOD.exe).

Evidence tags: 'native' = read in the decompiled handler (address given); 'names' = inferred from the authored entity
names in the shipped blocks (out/names_by_action.txt); 'count' = shipped occurrences over all shared blocks.
"""

# Trigger_Root.Method / the event a root forwards to its conditions (enter_trigger etc. set it; 0x7FDB70..0x7FDDA0).
ROOT_EVENT = {
    0: ('leave', 'native 0x7FDC00 leave_trigger(Entity)'),
    1: ('enter', 'native 0x7FDB70 enter_trigger(Entity)'),
    2: ('use', 'native 0x7FDC80 use(Entity): the player presses USE inside'),
    4: ('inside', 'native 0x7FDAF0 inside_trigger(Entity)'),
    5: ('trig', 'native 0x7FDD00 trig(Entity,integer): fired by another action (Trig_Noaction ActionType 10)'),
    11: ('enter vehicle', 'native 0x7FDDA0 enter_trigger_vehicle(Entity,Entity)'),
    12: ('leave vehicle', 'native 0x7FDE40 leave_trigger_vehicle(Entity,Entity)'),
    13: ('trig 13', 'native 0x7FDD00 trig with argument 13'),
}

# Trigger_Root.TriggerOn, predicate 0x7FD190 (+0x30 mode, +0x34 ConditionsNeeded float, +0x54 ConditionsMet)
TRIGGER_ON = {
    0: ('all conditions met (AND); empty list passes', 'native 0x7FD190'),
    1: ('any condition met (OR); empty list fails', 'native 0x7FD190'),
    2: ('at least ConditionsNeeded conditions met (count)', 'native 0x7FD190 (int)ConditionsNeeded <= met'),
}

# Trigger_Condition.TrueOn (generic class Trigger_Condition, handler 0x7F4770)
COND_TRUEON = {
    0: ('player/actor leaves the root volume', 'native 0x7FD590 Method == TrueOn; names Condition_PlayerLeave'),
    1: ('actor enters the root volume', 'native 0x7FD590; names Condition_PlayerEnter (2,528)'),
    2: ('actor presses USE inside the volume', 'native 0x7FD590; names Condition_PlayerUse'),
    3: ('ActivatorEntity dies (health - damage <= 0); optional HUD health bar (ShowInHUD/HUDName)',
        'native 0x7F5BD0 initial_frame + watch 0x7F5640 (props 0x619/0x618)'),
    4: ('actor inside the volume (repeated)', 'native 0x7FDAF0'),
    5: ('remotely triggered: another action sends trig(Actor,Method) (Trig_Noaction ActionType 10)',
        'native 0x7F0960 + 0x7FDD00; names COND_RemotelyTrigged'),
    6: ('mission start: registered in master_mission_ctrl.Trig_on_mission_load_list at init, fired with '
        '(PLAYER_NODE, 6) when the mission block has loaded; activator check skipped',
        'native 0x7F4890 (local -9 = command_add_to_trigger_true_list), 0x78A7C0 sends command_trigger_event(PLAYER,6)'),
    11: ('vehicle enter (via vehicle conditions)', 'native 0x7FD590'),
    12: ('vehicle leave', 'native 0x7FD590'),
    14: ('true at once / after IntervalTrue seconds', 'native 0x7F5640 case TrueOn 14 sleeps IntervalTrue'),
    16: ('(1 use, unknown)', 'count 1'),
}

# Trigger_Condition.ActivatorType, check 0x7F42D0 (skipped when TrueOn == 6)
ACTIVATOR_TYPE = {
    0: ('the player (actor character Sub_Type 7 = Ram)', 'native 0x7F42D0'),
    1: ('any NPC character (Sub_Type 0..6 or 8..22)', 'native 0x7F42D0'),
    2: ('actor whose member 0 == 0 (non-character / vehicle; unused in shipped data)', 'native 0x7F42D0'),
    3: ("Actor is the condition's own first child entity (entity+0x44 = first child)", 'native 0x7F42D0; names Condition_Owner, Condition_trigger_child'),
    4: ('a specific entity: Actor == ActivatorEntity (resolved from SpecificActivator name)', 'native 0x7F42D0; names Condition_HEALTH_enemy'),
    5: ('the player on foot (not a vehicle event 11/12)', 'native 0x7F42D0'),
}

# Trigger_Condition_Logical.TrueOn: events queued in master_control_trigger_ctrl.PendingLogicConditions
# (command_logic_condition(integer,Entity) 0x7863C0, consumer 0x785EC0: TrueOn == event, optional SpecificActivator)
LOGIC_TRUEON = {
    1: ('an enemy killed (kill list; deduplicated)', 'native 0x785EC0 events 1/9 dedup; names COND_n_EnemiesKilled'),
    2: ('objective completed (Objective SetStatus 2)', 'native 0x647F90 status 2 -> event 2'),
    3: ('objective set incomplete (SetStatus 0)', 'native 0x647F90 status 0 -> event 3'),
    4: ('objective SetStatus 1', 'native 0x647F90 status 1 -> event 4'),
    6: ('combo performed', 'names COND_ComboPerformed'),
    7: ('player enters a vehicle', 'names Condition_..._Enter_Truck'),
    8: ('player leaves a vehicle', 'names Condition_..._Leave'),
    9: ('enemy killed (objective kill list; deduplicated)', 'native 0x785EC0; names COND_AllEnemiesKilled'),
    10: ('AT_Enter', 'names'),
    11: ('character starts its GotoPath / runs', 'names Condition_Johnson_StartGotopath'),
    13: ('on mission', 'names Condition_on_mission (26)'),
    17: ('bomb placed on forklift', 'names'),
    19: ('combo performed (variant)', 'names'), 20: ('combo performed (variant)', 'names'),
    23: ('combo performed (variant)', 'names'), 24: ('combo missed', 'names'),
    25: ('tutorial entry activated', 'names Cond_Activate_TutNN'), 26: ('tutorial entry ended', 'names Cond_End_TutNN'),
    27: ('PC only', 'names Cond_PC_Only'),
}

# Trigger_Condition_Mission / _Mission_More TrueOn (default 7)
MISSION_COND_TRUEON = {
    7: ('mission Specific_Mission ended/completed', 'names Trigger_ENDMISSION_MM080'),
    15: ('mission triggered/started', 'names TriggerMission'),
}

# ActivateWho, target resolver 0x631940 (TargetEntity of every Trigger_Activate_*)
ACTIVATE_WHO = {
    0: ('the player (common.PLAYER_NODE)', 'native 0x631940 common+0x84'),
    1: ('no target', 'native 0x631940'),
    2: ("the trigger root's parent (the object that owns the trigger, e.g. a door)", 'native 0x631940 action.parent.parent'),
    3: ('entity named TargetName (FindNode 0x88EB60 from GetScene 0x88C570); empty name allowed only for ActionType 11/14',
        'native 0x631940'),
    4: ("the trigger root's grandparent", 'native 0x631940'),
    5: ('entity named TargetName, searched without GetScene', 'native 0x631940'),
}

# ActionType per class. (meaning, evidence)
ACTION = {
    'Trigger_Activate_Mission': {
        20: ('end the mission: command_stop_combo(true) unless gameplay is locked (RealtimeInputCtrl.'
             'InCtrlStateGameplayLock), then Command_End_Mission(End_Mission_Result) (1 = success, 0 = failure) '
             'to master_mission_ctrl', 'native 0x7E8180'),
        30: ('nothing (the body only handles 20); 3 shipped "Activate_end_mission_failed" nodes are inert',
             'native 0x7E8180'),
    },
    'Trigger_Activate_Objective': {
        72: ('objective SetStatus(2) = completed', 'native 0x7E8F60 (objective_worker_re_20260912.md)'),
        73: ('objective SetStatus(0)', 'native 0x7E8F60'),
        74: ('objective SetStatus(1)', 'native 0x7E8F60'),
        75: ('objective SetActive(true) = show/activate', 'native 0x7E8F60'),
        76: ('objective SetActive(false)', 'native 0x7E8F60'),
        77: ('objective IncreaseCounter', 'native 0x7E8F60'),
        78: ('objective DecreaseCounter', 'native 0x7E8F60'),
        79: ('show feedback text FeedbackText only (no objective target)', 'native 0x7E8F60'),
        118: ('objective ResetCounter', 'native 0x7E8F60'),
    },
    'Trigger_Activate_Enable_Disable': {
        5: ('enable target (clear NODE_DISABLE, send command_got_enable_trig; then optional move to '
            'Teleport_to_Entity); ignored during a cutscene; spawns disabled placeholders', 'native 0x7E39B0'),
        6: ('disable target (set NODE_DISABLE, command_got_disable_trig); never the player', 'native 0x7E39B0'),
        7: ('toggle enable/disable', 'native 0x7E39B0'),
        70: ('disable traffic/pedestrian system (local command -8 on the target)', 'native 0x7E39B0; names'),
        71: ('enable traffic/pedestrian system (local -9)', 'native 0x7E39B0; names'),
        109: ('clear NODE_COLL_DISABLE on target (collision on)', 'native 0x7E39B0'),
        110: ('set NODE_COLL_DISABLE on target (collision off)', 'native 0x7E39B0'),
    },
    'Trigger_Activate_Trig_Noaction_Reactivate': {
        10: ('send trig(Actor,Method) (+ vehicle_trig, command_trigger_event) to the target: fires the '
             "target root's conditions with TrueOn 5", 'native 0x7F0960'),
        11: ('no action (only the shared sound / APBonus helper 0x631E90)', 'native 0x7F0960'),
        29: ('re-arm the target trigger: command_reset to its conditions, clear Activated of its actions',
             'native 0x7F0960'),
        43: ('command_trig_ai_controlled(evil, PassiveCarAI, LookAheadDistance, LookAheadRadius): start an AI '
             'character/vehicle', 'native 0x7F0960'),
        45: ('take_a_hit(DamageGiven) on the target (damage/kill)', 'native 0x7F0960'),
        57: ('command_set_priority_target(PriorityTargetNode)', 'native 0x7F0960'),
        58: ('command_run_true', 'native'), 59: ('command_run_false', 'native'), 60: ('resume_track', 'native'),
        80: ('command_lock_vehicle', 'native'), 81: ('command_make_buddy', 'native'),
        85: ('command_set_as_safe', 'native'), 86: ('command_lock_velocity_on_exit', 'native'),
        106: ('command_instant_kill (destroy vehicle)', 'native'),
        120: ('command_jump_physics on the target movectrl', 'native 0x7F0960'),
        122: ('take_a_hit variant (kill)', 'native 0x7F0960'),
        129: ('command_unlock_vehicle', 'native'), 130: ('command_brake', 'native'),
    },
    'Trigger_Activate_Load_Unload_Save': {
        13: ('save point: master_control_save_ctrl member 22 = 0 (2 if SimulateAutosafe), '
             'command_create_save_point', 'native 0x7E6930 (local -7)'),
        21: ('stream a map/submap block: command_load_block(TargetEntity) + command_fade_from_black_after_load '
             'on master_control_load_ctrl, unless already loaded', 'native 0x7E6930'),
    },
    'Trigger_Activate_Radar': {
        18: ('command_hide_radar', 'native 0x7EDBC0'), 19: ('command_show_radar', 'native 0x7EDBC0'),
        26: ('command_add_to_radar(TargetEntity, RadarType, MapRelation)', 'native 0x7EDBC0'),
        27: ('command_remove_from_radar(TargetEntity)', 'native 0x7EDBC0'),
        131: ('command_clear_radar', 'native 0x7EDBC0'),
    },
    'Trigger_Activate_Camera': {
        32: ('cut to camera position TargetName (cinematic camera)', 'names ACT_CamPos'),
        33: ('FOV / camera change', 'names'), 34: ('camera look-at player / return', 'names'),
        35: ('slow motion on (SlowMotionFraction)', 'names ACT_Slowmotion'), 36: ('real time (end slow motion)', 'names'),
        88: ('fade / FOV camera', 'names'), 99: ('FOV camera', 'names'),
    },
    'Trigger_Activate_Player': {
        44: ('teleport the player to TargetName', 'native 0x7EAD40 branch 0x2c; names'),
        61: ('force a character into a car', 'names'), 63: ('force the player out of the vehicle', 'native branch 0x3f; names'),
        64: ('return the player to the ladder', 'names (90)'), 67: ('A1 (unknown)', 'names'),
        68: ('release the player from crouch', 'names'), 69: ('A1 (unknown)', 'names'),
        104: ('bounce the player back (world boundary)', 'native branch 0x68; names'),
        112: ('teleport the player onto the slide wire', 'native branch 0x70; names'),
        114: ('player invulnerable on', 'native branch 0x72; names'), 115: ('player invulnerable off', 'native branch 0x73'),
        116: ('teleport the player (variant)', 'native branch 0x74'), 117: ('grab the phone (public phone)', 'native 0x75; names'),
    },
    'Trigger_Activate_Countdown': {23: ('start countdown (Time, GreenTime, YellowTime)', 'names'),
                                   25: ('stop countdown', 'names')},
    'Trigger_Activate_Racing_Countdown': {82: ('start race countdown', 'names'), 83: ('add time', 'names'),
                                          84: ('disable countdown', 'names')},
    'Trigger_Activate_Weapons': {50: ('take all weapons', 'names'), 51: ('give weapon Weapon_Type + Ammo_Amount', 'names'),
                                 123: ('store weapons', 'names'), 124: ('restore weapons', 'names'),
                                 125: ('give weapon (variant)', 'names'), 126: ('remove weapon', 'names')},
    'Trigger_Activate_Door': {46: ('open', 'names'), 47: ('close', 'names'), 48: ('flip (toggle)', 'names'),
                              49: ('chain-link gate (variant)', 'names')},
    'Trigger_Activate_Lever': {15: ('lever on', 'names'), 16: ('lever off', 'names'), 17: ('lever on/off toggle', 'names')},
    'Trigger_Activate_Faction': {92: ('change faction relation (FactionToModify, RelationFaction, ChangeToRelation)', 'names'),
                                 95: ('pedestrians turn hostile', 'names'), 96: ('pedestrians back to normal', 'names')},
    'Trigger_Activate_Tutorial': {91: ('show tutorial text (pause text)', 'names')},
    'Trigger_Activate_Tutorial_Ctrl': {113: ('open the tutorial menu', 'names'), 121: ('tick a tutorial entry as completed', 'names')},
    'Trigger_Activate_Loco_Move': {119: ('remove a loco move', 'names'), 128: ('end the current loco move', 'names')},
    'Trigger_Activate_Combo': {98: ('stop / reset the combo timer', 'names')},
    'Trigger_Activate_Dummy': {111: ('reset target dummies', 'names')},
    'Trigger_Activate_Mounted_Gun': {65: ('enable a mounted gun / set its target', 'names')},
    'Trigger_Activate_Overall_Score': {97: ('add Overall_Bonus to the score', 'default value')},
}

DO_WHAT = {
    'Trigger_Activate_Sound': {0: ('play music slot (Music_slot)', 'names'), 1: ('play a sound', 'names'),
                               2: ('stop a sound', 'names'), 4: ('play loop', 'names'), 5: ('queue music', 'names'),
                               6: ('stop combo music', 'names'), 7: ('disable default taunts', 'names'),
                               8: ('enable default taunts', 'names'), 9: ('one-shot object sound', 'names')},
    'Trigger_Activate_Particle': {0: ('start particle system Particle_system at Trig_at_who', 'names'),
                                  1: ('stop particle', 'names')},
    'Trigger_Activate_Fog': {87: ('enter fog volume', 'names'), 105: ('leave fog', 'names'), 127: ('stop fog', 'names')},
    'Trigger_Activate_MiscEffect': {107: ('camera shake start', 'names'), 108: ('camera shake stop', 'names')},
    'Trigger_Activate_Color': {102: ('colour/fog start', 'names'), 103: ('colour/fog stop', 'names')},
    'Trigger_Lock_To_Mounted_Weapon': {0: ('lock the player to the gun', 'names'), 2: ('unlock', 'names')},
}


def action_meaning(cls, at):
    t = ACTION.get(cls, {})
    if at in t:
        return t[at][0]
    return None


def do_what_meaning(cls, dw):
    t = DO_WHAT.get(cls, {})
    return t[dw][0] if dw in t else None
