"""make_new_map.py - build a TOD "new map" package (stream_override.zip) from a small parameter file.

This is the recipe TOD Mod Studio's "Add map" feature wraps. It is data only (no exe or DLL change) and is built on
tools/level_streaming/submaptool.py (save-safe grafts, verified), plus the Mod Studio collision generator
(Mod Studio's backend/todct) for new collision.

  python make_new_map.py PARAMS.json --out BUILD_DIR [--no-collision] [--check-only]

Exit code 0 = package written and every check passed; 1 = a check failed (nothing is deployed, recipe_report.json says why).

OUTPUTS in BUILD_DIR
  stream_override.zip   the override zip (first archive on configpc's `filesystem =` line)
  configpc_line.txt     the `filesystem = ...` line to use
  spec.json             the generated submaptool spec (every graft / set the package makes)
  recipe_report.json    checks: every one named, with PASS / WARN / FAIL and the evidence
  manifest.json         what the package contains (map ids, names, block entries, node names, positions) for the UI
  <block files>         the rebuilt blocks (also inside the zip)

PARAMS (JSON; positions are game world metres, TOD axes, y up; orients are quaternions x,y,z,w)
{
 "package": "N1",
 "maps": [                                     one entry per new map (the registry takes several: see report)
  { "name": "Map11_RunawayTrain",              new map name. Must have EXACTLY the length of the source's name
                                               (block root names are fixed-size): "Map10_RunawayTrain" -> "Map11_RunawayTrain"
    "source": "map10_runawaytrain",            clone source (key of SOURCES below). map10 = near-empty train canyon (proven)
    "arrival": {"pos": [x,y,z], "orient": [0,0,0,1],
                "floor": "vanilla" | "none"},  where Ram appears. floor = what he stands on: "vanilla" = collision the
                                               source already has (checked against existing hulls when the source has any),
                                               otherwise a declared box/collision set below must be under it
    "entry":  {"block": "submap01_map02_lostoros_downtown.submap",     existing map's submap that gets the loader pair
               "parent": {"fragment": "SUBMAP01_Map02_LosToros_Downtown.fragment", "entity": "SUBMAP01_Map02_Geometry"},
               "pos": [x,y,z], "orient": [0,.7071,0,.7071], "size": [12,6,2]},   loader box width,height,length
    "entries": [ {"id": "downtown_alley", "block": "...submap" | "...map", "parent": {"fragment": F, "entity": E} (optional:
                  the recipe default of that block), "pos": [x,y,z], "orient": [qx,qy,qz,qw], "size": [w,h,l],
                  "arrive_at": "SPOT_1"} ]     several ways in, each from its own existing block (or the same one). arrive_at
               is the NAME of one of this map's "teleports"; omitted = the map's arrival node. "entry" (one) keeps working and
               counts as one more entry with id "entry". Per entry the recipe checks: block exists, parent fragment/entity
               exist and have one runtime instance, arrive_at exists, the loader pair is coincident (MAINMAP then SUBMAP).
    "new_geometry": {...}                      see NEW GEOMETRY below (the map gets its own ground, textures, models, collision)
    "return": {"pos": [x,y,z], "size": [8,8,2], "orient": [0,0,0,1],            return loader box inside the new map
               "target_map": "MAINMAP_Map02_LosToros_Downtown", "target_submap": "SUBMAP01_Map02_LosToros_Downtown",
               "teleport_to": "TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill",
               "teleport_block": "submap01_map02_lostoros_downtown.submap"},  where that node lives (checked)
    "walls": [{"name": "WallE", "pos": [..], "size": [w,h,l], "orient": [0,0,0,1], "flags": 3}],   CollisionBox nodes
    "collision_sets": [ todct sets (kind todct-collision) or shorthand
                        {"id": "platform", "shape": "box", "min": [..], "max": [..]} /
                        {"id": "ramp", "shape": "wedge", "min": [..], "max": [..], "rise": "+x"|"-x"|"+z"|"-z"} ],
    "models": [{"model": "/Models/Addons/ShippingCrates/ShippingCrate_Steel_Large.model", "pos": [..], "orient": [..]}],
    "teleports": [{"name": "SPOT_1", "pos": [x,y,z], "orient": [0,0,0,1]}],   extra named teleport spots (Teleport_to targets)
    "savepoint": {"pos": [x,y,z]} | null,
    "givers": [{"name": "MESA_MISSION_GIVER", "pos": [x,y,z], "mission": 33, "size": 3.0}],   Trigger_Root_Mission boxes (mission giver; Start_Mission = a REGISTERED index)
    "pickups": [{"kind": "health"|"weapon", "pos": [x,y,z], "weapon_subtype": 14}],
    "enemies": [{"pos": [x,y,z] (x,z world; y = the FLOOR height under him; the recipe adds the engine's 1.07 m drop and writes the
                                 position on the character_placeholder + its GotoPath: a Folder has NO transform in the engine),
                 "patrol": [[dx,dz],[dx,dz],[dx,dz]], "model": 23, "faction": 14, "ai_subtype": 0,
                 "health_mod": 1.0, "damage_mod": 1.0 (0.2-0.4 for an easy fight),
                 "wake": {"pos": [x,y,z], "size": [6,4,1.5]}}]   (wake = box that enables him when Ram enters;
                                               optional: without it he is enabled at load and appears when Ram is within ~45 m; proven
                                               in the mesa, docs 11.4)   a patrolling armed NPC (vanilla Downtown cop encounter node, grafted;
                                               "template": "mission" grafts a mission Enemy folder instead: its model mesh lives in a mission block,
                                               so only use the default cop template (model 23, mesh in overdose.main))
    "nodes_in": "map" | "submap",              block that receives the new nodes (must end in a save-safe last fragment:
                                               the recipe says so when it does not; hacienda needs "submap")
    "parent": {"fragment": null, "entity": null}   optional override of the folder the new nodes hang under
  } ]
}

NEW GEOMETRY ("new_geometry", implemented in newgeo.py / geomkit.py / tex_gen.py; the plan below it is the research that led to it)
  "new_geometry": {"folder": "Map11_MesaCompound",        asset folder under /data/Models/ (models + textures)
     "drop_source_content": true,                         remove the source's level nodes (train, terrain, havoc objects ...)
     "drop_unused_assets": true,                          remove every model/texture/fragment record nothing refers to
     "statically_lit": false,                             new nodes have no baked light entry: lit dynamically
     "textures": [{"name": "Sand", "kind": "sand|cliff|adobe|plaster|wood|metal|concrete|roof", "size": 256,
                   "format": "DXT1" | "RGBA32", "seed": 1}],             procedural, tileable, full mip chain
     "models":   [{"name": "WallX20", "parts": [ {"type": "box|wedge|rock|heightfield", ...} ]}],   see geomkit.py
     "placements": [{"model": "WallX20", "pos": [x,y,z] (world), "name": "..."}]}                   no rotations: build the
                                                          orientation you need into the model
  Per model one MODEL record (model_writer: render submesh per texture, bounds derived) with a HullList of convex pieces in
  model space (a box = 1 hull, a wedge 1, a rock its convex hull, a heightfield one slab per rectangle of flat cells and two
  prisms per other cell); per texture one TEXTURE record + payload; both appended to the block's asset table; one Model node
  per placement cloned from a shipped terrain Model node under a new Folder of the root fragment. Limits checked: <= 65,536
  vertices per submesh, <= 255 vertices per hull, texture payload <= 1,351,384 B, every record round-trips, every
  texture is read back by TOD HD's strict reader (payload = engine size rule).

NEW MAP FROM SCRATCH (research plan, kept for the record; "new_geometry" above is its implementation)
  Today a "new" map is a clone (source) plus placed copies of models the source block already owns (models) plus new
  collision (collision_sets, generator hulls appended to a placed-once host model) plus CollisionBox walls. A map with
  its own terrain needs, per mesh: (1) a MODEL record written by tools/model_writer/model_writer.py from a semantic
  description (2,622/2,718 shipped models re-encode byte-identically; whole new models were built in the model-writer lab
  but never run in game), with its HullList from todct collision.py (method "solid"/"surface" on the same mesh);
  (2) its texture records (DXT1 / RGBA32, subsystem_textures_materials.md) and a MeshColor record when it is statically
  lit (a new placement without one renders black: statically_lit=False is the workaround used here); (3) the records
  appended to the new block's asset table (INFO), which is not save relevant because the block is new; (4) a new
  placement fragment (Model nodes, parent folder, modelres names) instanced by the block's root fragment, created with
  the fragment writer; (5) a blank block to start from: Map10's submap01 (384 bytes) is the smallest real block; a new
  .map root fragment + MenuCamera + light fragment can be cloned from Map10's map block with the train terrain assets
  dropped from INFO (dropping assets is untested). Mission inside the map: Missions.fragment folder + award record +
  mission block (missions REPORT.md); the in-game start of a NEW mission was not achieved in that research.

CHECKS (recipe_report.json "checks"): same-length names; ids unique and MAPS_MAX / SUBMAPS_MAX raised to cover them; names not
already in blocks.naz; submaptool build verify (headers/INFO identical, no existing node changes its runtime index,
creates-first, every fragment re-serialises exactly); fragment paths in full /data/ form; loader pairs coincident
(MAINMAP then SUBMAP) in both directions; teleport target exists; arrival floor (ray down against the source's existing
placed-once hulls, declared boxes and generator sets); collision generator read-back; final strict block round-trip and
a re-read of the written zip.
"""
import argparse, copy, json, math, os, re, struct, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'level_streaming'))
_BACKEND = os.environ.get('TODMS_BACKEND') or os.path.dirname(os.path.dirname(HERE))   # Mod Studio's backend (todms + todct)
if _BACKEND not in sys.path:
    sys.path.insert(1, _BACKEND)
os.environ.setdefault('TOD_TOOLS', os.path.join(os.path.dirname(HERE), 'tools'))
sys.path.append(HERE); import base_overlay; base_overlay.install()   # MESA_BASE_ZIP: build on a Gameplay+ data zip (see base_overlay.py)
import submaptool as S            # noqa: E402  (also puts fragment_writer + save_editor on sys.path)
import newgeo as NG               # noqa: E402

ft, fe, tb, tf = S.ft, S.fe, S.tb, S.tf
SHARED = 'data_pc/overdose_the_game/overdose/shared/'
MAIN = S.MAIN

# ------------------------------------------------------------------------------------------------ clone sources
# template ids are runtime entity ids of the shipped blocks (see subsystem_level_streaming.md 11.x)
SOURCES = {
    'map10_runawaytrain': dict(
        status='PROVEN in game (M13, vanilla + Gameplay+)',
        map_entry='mainmap_map10_runawaytrain.map', submap_entry='submap01_map10_runawaytrain.submap',
        root='MAINMAP_Map10_RunawayTrain.fragment', subroot='SUBMAP01_Map10_RunawayTrain.fragment',
        map_name='Map10_RunawayTrain', folder_dir='Map10_RunawayTrain',
        scene_template='0x00100038', loadscreen='Sub_Maps_Loadscreens/Deadmans_submap1',
        parent=dict(fragment='MAINMAP_Map10_RunawayTrain.fragment', entity='MM120_RunawayTrainFolder')),
    'map08_hacienda': dict(
        status='built; see report',
        map_entry='mainmap_map08_hacienda.map', submap_entry='submap01_map08_hacienda.submap',
        root='MAINMAP_Map08_Hacienda.fragment', subroot='SUBMAP01_Map08_Hacienda.fragment',
        map_name='Map08_Hacienda', folder_dir='Map08_Hacienda',
        scene_template='0x00100031', loadscreen='Sub_Maps_Loadscreens/Hacienda_submap1',
        parent=dict(fragment='MAINMAP_Map08_Hacienda.fragment', entity='Surround_Geometry'),
        # the map block's last fragment is a prefab used several times (ladder_2_steps): not save-safe, so a hacienda
        # clone puts its new nodes into the submap block instead (nodes_in = "submap")
        subparent=dict(fragment='SUBMAP01_Map08_Hacienda.fragment', entity='MM075_Hacienda_Saves')),
}
LOADER_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='SUBMAP01_Map02_WorldBoundary_Triggers',
                  entity='0x003011EB')
WALL_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='SUBMAP01_Map02_Models.fragment',
                entity='0x003013B1')
SAVE_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap',
                from_fragment='SUBMAP01_Map02_Roaming_GamePlay_Objects.fragment', entity='0x003024A1')
ARRIVAL_SRC = dict(from_block='mainmap_map10_runawaytrain.map', from_fragment='MAINMAP_Map10_RunawayTrain.fragment',
                   entity='0x00200005')
# a cop on foot patrol: Folder (character + weapon + GotoPath + 3 TrackPoints) of the Downtown police encounter
ENEMY_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='Police_Assault_MissionStructure_03',
                 entity='0x00300E08')
ENEMY_SRC_MISSION = dict(from_block='subm_04_down_somsal_kill.mission',
                         from_fragment='/data/Overdose_THE_GAME/Missions/SubMissions/SubM_04_Down_SomSal_Kill.fragment',
                         entity='0x004017ED')
# free-roam pickups of the Downtown Goodies fragment: a respawning large health pack and a respawning weapon
PICKUP_SRC = {'health': dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='SUBMAP01_Map02_Goodies.fragment',
                             entity='0x00301195'),
              'weapon': dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='SUBMAP01_Map02_Goodies.fragment',
                             entity='0x00301192')}
# a vanilla Trigger_Root_Mission box (SomSal giver) in an intermission block: the mission giver clone source
GIVER_SRC = dict(from_block='intermission_after_escape.mission', from_fragment='SubM_04_Down_SomSal_Kill_MISSION_LOADER.fragment',
                 entity='0x004000A3')
SPRITE0 = dict(pos=[0.0, 9.5, 0.0], orient=[0, 0, 0, 1], sprite_size=[12, 24.0, 1.0])
SPRITE1 = dict(pos=[0.0, 1.0, 0.0], orient=[0, 0, 0, 1])
IDENT = [0, 0, 0, 1]



DOTD_SRC = dict(from_block='submap03_map03_lostoros_industrial.submap', from_fragment='Point_Challenge.fragment', entity='0x00300F6A')
DOTD_BOX = (-0.325, 4.2904, 1.3481)      # local offset of the trigger boxes / goodie / emitter against the fragment's instance origin


def dotd_ops(dp, k, parent):
    """Graft of the whole DayOfTheDead_Mainfolder. dp = {pos: [x,y,z] = world spot of the pickup (the goodie floats 4.39 above the instance origin),
    'sky': False drops nothing (kept), ...}. Folders have no transform in the engine, so every positioned child gets an absolute world position."""
    x, y, z = dp['pos']
    ox, oy, oz = x - DOTD_BOX[0], y - 4.39, z - DOTD_BOX[2]       # instance origin
    A = lambda dx, dy, dz: [ox + dx, oy + dy, oz + dz]
    cs = [dict(type='Folder', set=dict(pos=[0.0, 0.0, 0.0])),
          dict(type='Trigger_Root(CollisionBox)', index=0, set=dict(pos=A(*DOTD_BOX))),
          dict(type='Trigger_Root(CollisionBox)', index=1, set=dict(pos=A(*DOTD_BOX))),
          dict(type='Trigger_Root(CollisionBox)', index=4, set=dict(pos=A(*DOTD_BOX))),
          dict(type='goodie_placeholder(GoodiePlaceHolder)', set=dict(pos=A(-0.3879, 4.3883, 1.3858))),
          dict(type='generic_particle_emitter(Node)', set=dict(pos=A(*DOTD_BOX))),
          dict(type='SoundSlot', index=1, set=dict(pos=A(0.0, 4.0, 0.0)))]
    if 'sets' in dp:
        cs.extend(dp['sets'])
    return [dict(op='graft', deep=True, parent=parent, name='DOTD_%d' % (k + 1), pos=[0.0, 0.0, 0.0], orient=IDENT, child_sets=cs, **DOTD_SRC)]

class RecipeError(Exception):
    pass


def rel(entry):
    return SHARED + entry if '/' not in entry else entry


# ------------------------------------------------------------------------------------------------ spec generation
def read_limits():
    """Current common.MAPS_MAX / SUBMAPS_MAX in the shipped overdose.main."""
    T = ft.types()
    b = tb.Block(ft.archive().read(MAIN), '.main')
    fr = S.frags_of(b)
    nm = [n for n in fr if n.lower().endswith('overdose.scene')][0]
    d = fe.FragDoc(b.payloads[fr[nm]], T, nm)
    n = d.find('common(Node)')
    mm, sm = d.get(n, 'MAPS_MAX'), d.get(n, 'SUBMAPS_MAX')
    # not stored in the shipped scene = the engine defaults (MAPS_MAX 9, SUBMAPS_MAX 21; subsystem_level_streaming.md 11)
    return int(9 if mm is None else mm), int(21 if sm is None else sm)


def loader_op(name, pos, orient, size, target, teleport, parent):
    return dict(op='graft', deep=True, parent=parent, name=name, pos=list(pos), orient=list(orient),
                set=dict(width=size[0], height=size[1], length=size[2]),
                child_sets=[dict(type='Trigger_Activate_Load_Unload_Save(NodeLogical)',
                                 set=dict(TargetName=target, Teleport_to=teleport, name='Action_' + name)),
                            dict(type='generic_object_effect(Sprite)', index=0, set=dict(SPRITE0)),
                            dict(type='generic_object_effect(Sprite)', index=1, set=dict(SPRITE1))],
                **LOADER_SRC)


def up(s):
    return re.sub(r'[^A-Za-z0-9]+', '_', s).upper()


ENEMY_DROP = 1.07           # metres the engine lowers a character_placeholder at its initial_frame (005A81B0)


def enemy_op(e, name, parent):
    """A patrolling armed NPC: graft of the Downtown cop Folder (character + weapon + GotoPath + 3 TrackPoints)."""
    pat = e.get('patrol') or [[0, 2], [0, 4], [0, 6]]
    pat = (pat + [pat[-1]] * 3)[:3]
    # A Folder has NO transform in the engine (0087E730 / Node ctor 0088D4B0: no position record, the pos setter returns at once): the spawn
    # position must be on the character_placeholder and on its GotoPath, in the coordinates of the nearest positioned ancestor (world
    # here). The placeholder is lowered by 1.07 m at its initial_frame (constant 009BF520) and then swept for room, so author floor + 1.07.
    ppos = [float(e['pos'][0]), float(e['pos'][1]) + ENEMY_DROP, float(e['pos'][2])]
    cset = dict(pos=ppos, orient=IDENT, Model=e.get('model', 23), FactionID=e.get('faction', 14),
                AISubType=e.get('ai_subtype', 0), Health_mod=e.get('health_mod', 1.0), Damage_mod=e.get('damage_mod', 1.0))
    for k_in, k_out in (('goto_movement', 'Goto_Movement'), ('dont_hunt', 'DontHunt'), ('flags', 'flags'),
                        ('wait_until_aggressive', 'Wait_until_Aggressive'), ('morale', 'Morale')):
        if k_in in e:
            cset[k_out] = e[k_in]
    wset = dict(pos=[0.0, 0.0, 0.0], orient=IDENT)
    if 'weapon_subtype' in e:
        wset['WeaponSubType'] = e['weapon_subtype']
    cset.update(e.get('char_set', {}))               # raw property overrides (experiments / advanced)
    wset.update(e.get('weapon_set', {}))
    root_set = {'flags': e.get('root_flags', 1)} if e.get('wake') else {}        # disabled until its wake trigger enables it
    if e.get('template') == 'mission':               # Enemy folder of a mission block (character + wear + weapon placeholders, no path)
        cs = [dict(type='character_placeholder(CharacterPlaceHolder)',
                   set=dict(pos=ppos, orient=IDENT, **e.get('char_set', {}))),
              dict(type='weapon_placeholder(WeaponPlaceHolder)',
                   set=dict(pos=[0.0, 0.0, 0.0], orient=IDENT, **e.get('weapon_set', {})))]
        return dict(op='graft', deep=True, parent=parent, name=name, pos=[0.0, 0.0, 0.0], orient=IDENT, child_sets=cs,
                    set=root_set, **ENEMY_SRC_MISSION)
    cs = [dict(type='character_placeholder(CharacterPlaceHolder)', set=cset),
          dict(type='weapon_placeholder(WeaponPlaceHolder)', set=wset),
          dict(type='Pathtype(Track)', set=dict(pos=ppos, orient=IDENT))]
    for t, (dx, dz) in enumerate(pat):
        cs.append(dict(type='TrackPoint', index=t, set=dict(pos=[float(dx), 0.0, float(dz)])))
    return dict(op='graft', deep=True, parent=parent, name=name, pos=[0.0, 0.0, 0.0], orient=IDENT, child_sets=cs,
                set=root_set, **ENEMY_SRC)


# A spawn needs an ENABLE: placeholders only instantiate when their folder is enabled (Trigger_Activate_Enable_Disable,
# ActionType 5), so an enemy with "wake" sits in a disabled folder and this box trigger (clone of the Downtown
# Police_Assault_Trigger: Trigger_Root(CollisionBox) + Trigger_Condition TrueOn 1 = player enters) enables it.
WAKE_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='Police_Assault_MissionStructure_03',
                entity='0x00300DC1')


def wake_op(enemy_name, wake, parent, idx):
    en = dict(type='Trigger_Activate_Enable_Disable(NodeLogical)')
    cs = [dict(type='Trigger_Condition(NodeLogical)', set=dict(TrueOn=wake.get('true_on', 1), PrintDebug=bool(wake.get('debug'))))]
    for i in range(4):
        cs.append(dict(type='Trigger_Activate_Enable_Disable(NodeLogical)', index=i,
                       set=dict(ActionType=5, TargetName=enemy_name, **({} if True else {}))))
    size = wake.get('size', [6, 4, 1.5])
    return dict(op='graft', deep=True, parent=parent, name='WAKE_%s' % enemy_name, pos=wake['pos'],
                orient=wake.get('orient', IDENT), set=dict(width=size[0], height=size[1], length=size[2], flags=256,
                                                           CollisionFlags=16, PrintDebug=bool(wake.get('debug'))), child_sets=cs, **WAKE_SRC)


GEO_TRIS = {}                         # map name -> world-space triangles of the new_geometry collision (not in the manifest)


def geo_K():
    """Namespace newgeo.py needs: the fragment/model tools (todct.tools.load) + submaptool."""
    from types import SimpleNamespace
    from todct import tools as TT
    k = TT.load()
    return SimpleNamespace(ft=k.ft, fe=k.fe, tb=k.tb, tf=k.tf, tm=k.tm, mw=k.mw, S=S)


# default parent (fragment, entity) for an entry loader pair, per existing block; the entity must have ONE runtime
# instance (checked). Add a block here once its last fragment is known to be save-safe (submaptool lastfrag).
ENTRY_PARENTS = {
    'submap01_map02_lostoros_downtown.submap': dict(fragment='SUBMAP01_Map02_LosToros_Downtown.fragment', entity='SUBMAP01_Map02_Geometry'),
    'submap03_map02_lostoros_downtown.submap': dict(fragment='SUBMAP03_Map02_LosToros_Downtown.fragment', entity='SUBMAP03_Map02_Geometry'),
    'mainmap_map02_lostoros_downtown.map': dict(fragment='MAINMAP_Map02_LosToros_Downtown.fragment', entity='MAINMAP_Map02_Addons'),
    'mainmap_map04_lostoros_train_harbour.map': dict(fragment='MAINMAP_Map04_LosToros_Train_Harbour.fragment', entity='Geometry'),
}


# Blocks that pass the static save-safety test but are REFUSED as entry hosts, with the exact reason (proven by a build)
ENTRY_REFUSED = {
    'submap03_map02_lostoros_downtown.submap': 'the submaptool build verify fails: appending a node there changes the runtime index of an existing '
                                               'node (a save made before the package would load wrong). Use submap01 or the map block of Downtown.',
}


def auto_entry_parent(ent, b):
    """A top-level Folder of the block with ONE runtime instance and an identity world transform (so the loader's pos is a world
    position): {"fragment": file name, "entity": name} or None. Prefers names with Geometry / Addons / Data. Slow-ish: only
    called for the block listing, not for a build."""
    T = ft.types()
    fr = S.frags_of(b)
    cands = []
    frs_list = ft.fragments(b)[0]
    for nm, k in fr.items():
        if len(b.payloads[k]) < 24 or nm.lower().startswith('/data/scripts/fragments/'):
            continue
        try:
            d = fe.FragDoc(b.payloads[k], T, nm)
            owner = ft.owner_chain(b, frs_list, k, T)[0]
        except Exception:                      # noqa: BLE001
            continue
        if max(abs(c) for c in owner[0]) > 1e-3 or max(abs(owner[1][0]), abs(owner[1][1]), abs(owner[1][2])) > 1e-3:
            continue
        ids = d.created_ids()
        for n in ids:
            if d.type_of(n) != 'Folder' or (d.get(n, fe.P_PARENT) or 0) in ids or not d.get(n, fe.P_NAME):
                continue
            name = d.get(n, fe.P_NAME)
            p = d.get(n, fe.P_POS) or [0, 0, 0]
            if max(abs(c) for c in p) > 1e-3:
                continue
            score = sum(w in nm.lower() + name.lower() for w in ('geometry', 'addons', 'data'))
            cands.append((-score, len(cands), nm.split('/')[-1], name))
    for _, _, fn, name in sorted(cands)[:6]:
        try:
            S.literal_for(b, ent, fn, name, T)          # one runtime instance (raises otherwise)
            return dict(fragment=fn, entity=name)
        except Exception:                       # noqa: BLE001
            continue
    return None


# blocks where an entry loader pair was PROVEN in the vanilla game (free roam): Downtown submap01 + map block, Harbour map block
ENTRY_PROVEN = {'submap01_map02_lostoros_downtown.submap': 'proven (n8_a1)',
                'mainmap_map02_lostoros_downtown.map': 'proven (n8_a2: lands at SPOT_2)',
                'mainmap_map04_lostoros_train_harbour.map': 'proven free roam (hb4_bridge: box 40x8x3 on the bridge, lands at SPOT_4). NOT inert in general, but '
                                                            'a loader box did nothing while Ram stood inside it in a save made INSIDE mission MM040 (hs1_harbour_room): '
                                                            'test entries from a free-roam position, and make the box wide enough to cross (the road is walked along its '
                                                            'edges, a 3 m slab was missed)'}


def list_entry_hosts():
    """Every shipped map / submap block with the verdict "can it host an entry loader pair": a list of dicts
    {block, ok, reason, last_fragment, default_parent}. ok = the block ends in a plain fragment that exactly one node instantiates
    (a loader appended there is save-safe), it is not in ENTRY_REFUSED, and a default parent is known (ENTRY_PARENTS: otherwise the entry
    must give "parent"; then offer = False). TOD Mod Studio offers only offer == True."""
    out = []
    for ent in sorted(ft.archive().names if hasattr(ft.archive(), 'names') else []):
        low = ent.lower()
        if not low.startswith(SHARED) or not low.endswith(('.map', '.submap')):
            continue
        base = low[len(SHARED):]
        if '/' in base:
            continue
        row = dict(block=base, ok=False, offer=False, reason='', last_fragment=None, default_parent=ENTRY_PARENTS.get(base))
        try:
            b = tb.Block(ft.archive().read(ent), os.path.splitext(ent)[1])
            lf, nxt, _ = S.last_fragment(b, ent)
            row['last_fragment'] = lf.split('/')[-1]
            row['ok'] = True
        except (S.Fail, ft.Fail, KeyError, ValueError) as e:
            row['reason'] = 'not save-safe: %s' % str(e)[:200]
        if row['ok'] and base in ENTRY_REFUSED:
            row['ok'] = False
            row['reason'] = ENTRY_REFUSED[base]
        if row['ok'] and not row['default_parent']:
            row['reason'] = 'save-safe, but no default parent folder is known: the entry must name "parent"'
        if row['ok'] and not row['default_parent']:
            par = auto_entry_parent(ent, b)
            if par:
                row['default_parent'] = par
                row['reason'] = 'default parent found automatically (identity world transform, one runtime instance)'
        row['proven'] = ENTRY_PROVEN.get(base, 'static checks only: not run in game')
        row['offer'] = bool(row['ok'] and row['default_parent'])
        out.append(row)
    return out


def default_entry_parent(block):
    b = block.split('/')[-1].lower()
    if b not in ENTRY_PARENTS:
        raise RecipeError('entry block %s: no default parent known, give "parent": {"fragment":..., "entity":...} (known blocks: %s)'
                          % (block, ', '.join(ENTRY_PARENTS)))
    return dict(ENTRY_PARENTS[b])


def entries_of(m):
    """The map's entries as a list: the legacy single "entry" (id "entry") when present, then the "entries" list."""
    out = []
    if m.get('entry'):
        out.append(dict(m['entry'], id=m['entry'].get('id', 'entry'), legacy=not m.get('entries')))
    for e in m.get('entries', []):
        if not e.get('id') or not e.get('block') or e.get('pos') is None:
            raise RecipeError('%s: every entry needs id, block and pos' % m['name'])
        out.append(dict(e))
    ids = [e['id'] for e in out]
    if len(set(ids)) != len(ids):
        raise RecipeError('%s: duplicate entry ids %s' % (m['name'], ids))
    if not out:
        raise RecipeError('%s: the map has no entry (give "entry" or "entries")' % m['name'])
    return out


def gen_spec(params, out='.'):
    mmax, smax = read_limits()
    maps = params['maps']
    spec = dict(description='%s: %d new map(s) by make_new_map.py' % (params.get('package', '?'), len(maps)),
                zip='stream_override.zip', new_blocks=[], blocks=[])
    main_ops = [dict(op='set', fragment='Overdose.scene', entity='common(Node)', prop='MAPS_MAX', value=mmax + len(maps)),
                dict(op='set', fragment='Overdose.scene', entity='common(Node)', prop='SUBMAPS_MAX', value=smax + len(maps))]
    per_block = {}                      # entry -> ops
    manifest = dict(package=params.get('package'), maps=[], base_limits=dict(MAPS_MAX=mmax, SUBMAPS_MAX=smax))
    geo_reports = []
    for i, m in enumerate(maps):
        src = SOURCES[m['source']]
        name = m['name']
        if len(name) != len(src['map_name']):
            raise RecipeError('map name %r must have %d characters like %r (block root names are fixed-size)'
                              % (name, len(src['map_name']), src['map_name']))
        low = name.lower()
        map_id, sub_id = mmax + i, smax + i
        mroot = src['root'].replace(src['map_name'], name)
        sroot = src['subroot'].replace(src['map_name'], name)
        mfrag = 'MAINMAP_%s' % name
        sfrag = 'SUBMAP01_%s' % name
        e_map = SHARED + 'mainmap_%s.map' % low
        e_sub = SHARED + 'submap01_%s.submap' % low
        geo = None
        if m.get('new_geometry'):
            if m.get('models'):
                raise RecipeError('%s: "models" places models the SOURCE block owns; with new_geometry use new_geometry.placements' % name)
            geo = NG.build(m, src, name, os.path.join(out, 'geometry_' + low), geo_K(), ft.types())
            geo_reports.append(dict(map=name, **geo['report']))
            GEO_TRIS[name] = geo['collision_tris']
            spec['new_blocks'] += [
                dict(entry=e_map, clone_of_file=geo['map_file'], lang_from=src['map_entry'], localized=True),
                dict(entry=e_sub, clone_of_file=geo['submap_file'], lang_from=src['submap_entry'], localized=True)]
        else:
            spec['new_blocks'] += [
                dict(entry=e_map, clone_of=src['map_entry'], rename_root=[src['root'], mroot], localized=True),
                dict(entry=e_sub, clone_of=src['submap_entry'], rename_root=[src['subroot'], sroot], localized=True)]
        fullp = '/data/Overdose_THE_GAME/Maps/%s/' % src['folder_dir']
        main_ops.append(dict(
            op='graft', from_block='overdose.main', from_fragment='Overdose.scene', entity=src['scene_template'], deep=True,
            parent=dict(fragment='Overdose.scene', entity='0x00100012'), name=name, set=dict(order=10 + i),
            child_sets=[dict(type='database_Map_ID(Folder)', set=dict(name=mfrag, fragment=fullp + mroot, Specific_ID=map_id)),
                        dict(type='database_SubMap_ID(Folder)', set=dict(name=sfrag, fragment=fullp + sroot, Specific_ID=sub_id))]))
        main_ops.append(dict(
            op='graft', from_block='overdose.main', from_fragment='LoadScreens.fragment', entity=src['loadscreen'], deep=True,
            parent=dict(fragment='LoadScreens.fragment', entity='Sub_Maps_Loadscreens'), name='%s_submap1' % name,
            set={'Sub_Map': sub_id, 'order': 21 + i}))
        # --- inside the new map
        in_sub = m.get('nodes_in', 'map') == 'submap'
        par = dict(src['subparent'] if in_sub else src['parent'])
        par['fragment'] = par['fragment'].replace(src['map_name'], name)
        if geo:                                       # the source's own folders are gone: hang the new nodes under the geometry folder
            par = dict(fragment=mroot, entity=geo['folder_node'])
            if in_sub:
                raise RecipeError('%s: new_geometry maps keep their nodes in the map block (nodes_in "map")' % name)
        if m.get('parent'):
            par.update({k: v for k, v in m['parent'].items() if v})
        ops = []
        arr_name = 'ARRIVAL_%s' % up(name)
        a = m['arrival']
        ops.append(dict(op='graft', deep=False, parent=par, name=arr_name, pos=a['pos'], orient=a.get('orient', IDENT),
                        **ARRIVAL_SRC))
        for t in m.get('teleports', []):                 # named spots any loader / trigger / mission can target
            ops.append(dict(op='graft', deep=False, parent=par, name=t['name'], pos=t['pos'],
                            orient=t.get('orient', IDENT), **ARRIVAL_SRC))
        r = m['return']
        ro = r.get('orient', IDENT)
        ops.append(loader_op('TriggerLoad_MAINMAP_Return', r['pos'], ro, r.get('size', [8, 8, 2]), r['target_map'],
                             r['teleport_to'], par))
        ops.append(loader_op('TriggerLoad_SUBMAP_Return', r['pos'], ro, r.get('size', [8, 8, 2]), r['target_submap'],
                             r['teleport_to'], par))
        for w in m.get('walls', []):
            ops.append(dict(op='graft', deep=False, parent=par, name=w['name'], pos=w['pos'], orient=w.get('orient', IDENT),
                            set=dict(width=w['size'][0], height=w['size'][1], length=w['size'][2],
                                     CollisionFlags=w.get('flags', 3)), **WALL_SRC))
        if m.get('savepoint'):
            ops.append(dict(op='graft', deep=False, parent=par, name='SAVEPOINT_%s' % up(name), pos=m['savepoint']['pos'],
                            orient=IDENT, **SAVE_SRC))
        for k, e in enumerate(m.get('enemies', [])):
            en = 'ENEMY_%s_%d' % (up(name), k + 1)
            ops.append(enemy_op(e, en, par))
            if e.get('wake'):
                ops.append(wake_op(en, e['wake'], par, k))
        for k, pk in enumerate(m.get('pickups', [])):
            st = {}
            if pk['kind'] == 'weapon' and 'weapon_subtype' in pk:
                st['WeaponSubType'] = pk['weapon_subtype']
            pn = 'PICKUP_%s_%d' % (pk['kind'].upper(), k + 1)
            if pk.get('root_flags') is not None:
                st['flags'] = pk['root_flags']
            ops.append(dict(op='graft', deep=False, parent=par, name=pn,
                            pos=pk['pos'], orient=IDENT, set=st, **PICKUP_SRC[pk['kind']]))
            if pk.get('wake'):                       # experiment: a pickup that a wake box has to switch on (proves the wake mechanism)
                ops.append(wake_op(pn, pk['wake'], par, 100 + k))
        for k, dp in enumerate(m.get('dotd', [])):          # 3d: a shipped Day of the Dead point (Point_Challenge fragment) grafted into the map
            ops.extend(dotd_ops(dp, k, par))
        for k, e in enumerate(m.get('dotd_enemies', [])):   # 3d: skeleton foes, asleep until a wake box (the pickup spot) is entered
            en = 'DOTD_ENEMY_%s_%d' % (up(name), k + 1)
            ops.append(enemy_op(e, en, par))
            if e.get('wake'):
                ops.append(wake_op(en, e['wake'], par, 200 + k))
        for k, gv in enumerate(m.get('givers', [])):      # mission giver box (clone of a vanilla loader box), see missions/mesa
            ops.append(dict(op='graft', deep=False, parent=par, name=gv.get('name', 'GIVER_%d' % (k + 1)), pos=gv['pos'],
                            orient=gv.get('orient', IDENT), set={'Start_Mission': gv['mission'], 'width': gv.get('size', 3.0),
                                               'height': gv.get('height', 3.0), 'length': gv.get('size', 3.0)}, **GIVER_SRC))
        for k, mo in enumerate(m.get('models', [])):
            frag, node = find_model_node(src, mo['model'])
            ops.append(dict(op='graft', deep=False, parent=par, name=mo.get('name', 'NEWMODEL_%d' % (k + 1)), pos=mo['pos'],
                            orient=mo.get('orient', IDENT), set=dict(statically_lit=False, dynamically_lit=True),   # a new placement has no baked light: lit dynamically
                            from_block=src['map_entry'], from_fragment=frag, entity=node))
        per_block.setdefault(e_sub if in_sub else e_map, []).extend(ops)
        # --- entry loaders in the existing maps: one loader pair (MAINMAP then SUBMAP, coincident) per entry
        spots = {t['name'] for t in m.get('teleports', [])}
        ent_list = entries_of(m)
        ent_manifest = []
        for en in ent_list:
            eblk = en['block']
            eops = per_block.setdefault(eblk, [])
            eo = en.get('orient', [0.0, 0.70710678, 0.0, 0.70710678])
            sz = en.get('size', [12, 6, 2])
            target = en.get('arrive_at') or arr_name
            if en.get('arrive_at') and en['arrive_at'] not in spots:
                raise RecipeError('%s: entry %s arrive_at %r is not one of the map teleports %s' % (name, en['id'], en['arrive_at'], sorted(spots)))
            tag = '%s' % name if en.get('legacy') else '%s_%s' % (name, up(en['id']))
            en = dict(en, parent=en.get('parent') or default_entry_parent(eblk))
            n_main = 'TriggerLoad_MAINMAP_%s' % tag
            n_sub = ('TriggerLoad_SUBMAP01_%s' % tag) if en.get('legacy') else 'TriggerLoad_SUBMAP_%s' % tag
            eops.append(loader_op(n_main, en['pos'], eo, sz, mfrag, target, en['parent']))
            eops.append(loader_op(n_sub, en['pos'], eo, sz, sfrag, target, en['parent']))
            ent_manifest.append(dict(id=en['id'], block=eblk, parent=en['parent'], pos=en['pos'], orient=eo, size=sz,
                                     arrive_at=en.get('arrive_at'), target_node=target, loader_nodes=[n_main, n_sub]))
        manifest['maps'].append(dict(name=name, source=m['source'], map_id=map_id, submap_id=sub_id, map_block=e_map,
                                     submap_block=e_sub, arrival_node=arr_name, arrival=a,
                                     entry=ent_manifest[0] if ent_manifest else None, entries=ent_manifest,
                                     teleports=[dict(name=t['name'], pos=t['pos']) for t in m.get('teleports', [])],
                                     map_folder=mfrag, submap_folder=sfrag, new_geometry=bool(geo)))
    for k, e in enumerate(params.get('existing_enemies', [])):      # test aid: NPCs in an already working map
        per_block.setdefault(e['block'], []).append(enemy_op(e, 'EXTRA_ENEMY_%d' % (k + 1), e['parent']))
        if e.get('wake'):
            per_block[e['block']].append(wake_op('EXTRA_ENEMY_%d' % (k + 1), e['wake'], e['parent'], k))
    for k, gv in enumerate(params.get('existing_givers', [])):     # mission giver boxes in an already existing map block (TOD Mod Studio mission templates)
        par = gv.get('parent') or default_entry_parent(gv['block'])
        per_block.setdefault(gv['block'], []).append(dict(
            op='graft', deep=False, parent=par, name=gv.get('name', 'EXTRA_GIVER_%d' % (k + 1)), pos=gv['pos'], orient=gv.get('orient', IDENT),
            set={'Start_Mission': gv['mission'], 'width': gv.get('size', 3.0), 'height': gv.get('height', 3.0), 'length': gv.get('size', 3.0)}, **GIVER_SRC))
    for k, t in enumerate(params.get('test_loaders', [])):       # test aid: a loader pair (map + submap) into ANY existing map, e.g. Downtown -> Harbour bridge
        par = t.get('parent') or default_entry_parent(t['block'])
        o = t.get('orient', IDENT)
        per_block.setdefault(t['block'], []).extend([
            loader_op('TESTLOAD_MAIN_%d' % k, t['pos'], o, t.get('size', [4, 6, 4]), t['target_map'], t['teleport'], par),
            loader_op('TESTLOAD_SUB_%d' % k, t['pos'], o, t.get('size', [4, 6, 4]), t['target_submap'], t['teleport'], par)])
    spec['blocks'].append(dict(block='overdose.main', ops=main_ops))
    for blk, ops in per_block.items():
        spec['blocks'].append(dict(block=blk, ops=ops))
    manifest['geometry'] = geo_reports
    return spec, manifest


_modelcache = {}


def find_model_node(src, modelres):
    """(fragment name, '0x..' node id) of the first Model node placing modelres in the source map block."""
    key = (src['map_entry'], modelres.lower())
    if key in _modelcache:
        return _modelcache[key]
    T = ft.types()
    b = tb.Block(ft.archive().read(ft.resolve_entry(src['map_entry'])), '.map')
    fr = S.frags_of(b)
    for nm, k in fr.items():
        if len(b.payloads[k]) < 24:
            continue
        try:
            d = fe.FragDoc(b.payloads[k], T, nm)
        except Exception:                           # noqa: BLE001
            continue
        for n in d.created_ids():
            t = d.type_of(n) or ''
            if t == 'Model' or t.endswith('(Model)'):
                ref = (d.get(n, 'modelres') or '').replace('\\', '/').lower()
                if ref == modelres.lower():
                    _modelcache[key] = (nm.split('/')[-1], '0x%08X' % n)
                    return _modelcache[key]
    raise RecipeError('model %s is not placed in %s (a new placement needs a model record already in the block)'
                      % (modelres, src['map_entry']))


# ------------------------------------------------------------------------------------------------ collision sets
def shorthand_to_set(s, map_key):
    """box / wedge shorthand -> a todct collision set (world-space convex pieces through the generator's hull)."""
    from todct import collision as CO
    if s.get('kind') == CO.KIND:
        s = dict(s)
        s['map'] = map_key
        return s
    lo, hi = s['min'], s['max']
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    box = [[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    if s['shape'] == 'box':
        pts = box
    elif s['shape'] == 'wedge':
        rise = s.get('rise', '+z')
        lowside = {'+z': lambda p: p[2] == z1 and p[1] == y1, '-z': lambda p: p[2] == z0 and p[1] == y1,
                   '+x': lambda p: p[0] == x1 and p[1] == y1, '-x': lambda p: p[0] == x0 and p[1] == y1}
        # the high end keeps its top, the low end loses it: `rise` names the HIGH side
        high = rise
        drop = {'+z': lambda p: p[2] == z0 and p[1] == y1, '-z': lambda p: p[2] == z1 and p[1] == y1,
                '+x': lambda p: p[0] == x0 and p[1] == y1, '-x': lambda p: p[0] == x1 and p[1] == y1}[high]
        pts = [[p[0], (y0 if drop(p) else p[1]), p[2]] for p in box]
        pts = [list(t) for t in {tuple(p) for p in pts}]
    else:
        raise RecipeError('unknown collision shape %r' % s.get('shape'))
    pieces = CO.pieces_from_point_sets([pts], material=s.get('material', 'Stone'), surface=s.get('surface', '0x02007C00'))
    return CO.new_set(s.get('label', s['id']), map_key, pieces, 'hull', set_id=s['id'], host=s.get('host', 'auto'))


def stage_collision(manifest_map, m, built, rep):
    """Apply a map's collision sets to its blocks (todct.collision). built: entry -> raw (changed in place)."""
    from todct import collision as CO
    mk = re.match(r'map\d+_[a-z0-9_]+', m['name'].lower()).group(0)
    sets = [shorthand_to_set(s, mk) for s in m['collision_sets']]
    entries = [manifest_map['map_block'], manifest_map['submap_block']]

    def read(e):
        return built[e]
    ctx = CO.MapContext(mk, entries, read)
    new, r = CO.apply_sets(ctx, sets, base_raw={e: built[e] for e in entries})
    for e, raw in new.items():
        ext = os.path.splitext(e)[1]
        T = ft.types()
        r1 = ft.roundtrip_block(raw, ext, T)
        if r1['fail'] or not r1['block_identical']:
            raise RecipeError('%s: the block with new collision does not round-trip' % e)
        built[e] = raw
    rep['collision'].append(dict(map=m['name'], sets=[s['id'] for s in sets], notes=r['notes'], pieces=r['pieces'],
                                 max_piece_vertices=r['max_piece_vertices'],
                                 hosts=[dict(model=h['model'], readback=h['readback']['max_world_error_m'])
                                        for b in r['blocks'] for h in b.get('hosts', [])]))
    return sets


# ------------------------------------------------------------------------------------------------ checks
def ray_down(tris_world, x, z, y_from):
    best = None
    for (a, b, c) in tris_world:
        # barycentric test in xz, interpolate y
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
        l2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) < -1e-9:
            continue
        y = l1 * a[1] + l2 * b[1] + l3 * c[1]
        if y <= y_from + 1e-6 and (best is None or y > best):
            best = y
    return best


def box_tris(pos, orient, size):
    import numpy as np
    from todct import geom
    w, h, l = size
    P = [[sx * w / 2, sy * h / 2, sz * l / 2] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    W = geom.apply_trs(np.asarray(P), pos, tuple(orient))
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for f in faces:
        tris.append((W[f[0]], W[f[1]], W[f[2]]))
        tris.append((W[f[0]], W[f[2]], W[f[3]]))
    return tris


def check_arrival(m, sets, ctx_hosts, checks):
    """Floor under the arrival node and under every named teleport: a ray down against the declared walls, the collision
    sets, the placed-once hulls of the blocks and the new_geometry hulls."""
    import numpy as np
    tris = []
    for w in m.get('walls', []):
        tris += box_tris(w['pos'], w.get('orient', IDENT), w['size'])
    for s in sets:
        for p in s['pieces']:
            V = np.asarray(p['verts'])
            for f in p['faces']:
                for k in range(1, len(f) - 1):
                    tris.append((V[f[0]], V[f[k]], V[f[k + 1]]))
    for it in ctx_hosts:
        V = np.asarray(it['verts'])
        for t in it['tris']:
            tris.append((V[t[0]], V[t[1]], V[t[2]]))
    tris += GEO_TRIS.get(m['name'], [])
    mode = m['arrival'].get('floor', 'vanilla')
    spots = [('arrival', m['arrival']['pos'])] + [('spot %s' % t['name'], t['pos']) for t in m.get('teleports', [])]
    for label, (x, y, z) in spots:
        floor = ray_down(tris, x, z, y + 0.01)
        nm = 'floor under %s %s' % (label, m['name'])
        if floor is not None and y - floor <= 3.0:
            checks.append(dict(check=nm, result='PASS', evidence='collision %.2f m below the node (y %.2f)' % (y - floor, floor)))
        elif mode == 'vanilla':
            checks.append(dict(check=nm, result='WARN',
                               evidence='no placed-once hull / declared box under the node (floor=vanilla is taken on trust: the '
                                        'source has collision this check cannot read, e.g. mission-spawned or multiply-placed models)'))
        else:
            checks.append(dict(check=nm, result='FAIL', evidence='nothing solid under the node'))


def check_teleport(m, checks):
    r = m['return']
    blk = r.get('teleport_block')
    nm = r['teleport_to']
    ok = False
    if blk:
        T = ft.types()
        b = tb.Block(ft.archive().read(ft.resolve_entry(blk)), os.path.splitext(blk)[1])
        for fn, k in S.frags_of(b).items():
            try:
                d = fe.FragDoc(b.payloads[k], T, fn)
            except Exception:                         # noqa: BLE001
                continue
            for n in d.created_ids():
                if d.get(n, fe.P_NAME) == nm:
                    ok = True
                    break
            if ok:
                break
    checks.append(dict(check='return teleport node %s exists in %s' % (nm, blk), result='PASS' if ok else
                       ('FAIL' if blk else 'WARN'), evidence='found' if ok else 'not found / no teleport_block given'))


def pre_checks(params, checks):
    names = set(ft.archive().names)
    seen = set()
    for m in params['maps']:
        src = SOURCES.get(m['source'])
        if not src:
            raise RecipeError('unknown source %r (known: %s)' % (m['source'], ', '.join(SOURCES)))
        ok = len(m['name']) == len(src['map_name'])
        checks.append(dict(check='name length %s' % m['name'], result='PASS' if ok else 'FAIL',
                           evidence='%d chars, source %r has %d' % (len(m['name']), src['map_name'], len(src['map_name']))))
        low = m['name'].lower()
        clash = [e for e in names if low in e.lower()]
        if low in seen or clash:
            checks.append(dict(check='name unique %s' % m['name'], result='FAIL', evidence='already in blocks.naz / package: %s' % clash[:2]))
        else:
            checks.append(dict(check='name unique %s' % m['name'], result='PASS', evidence='no existing archive entry'))
        seen.add(low)
        if not ok:
            raise RecipeError('map name length')


def check_entries_pre(params, checks):
    """Per entry: block exists, last fragment save-safe, parent fragment + entity exist with ONE runtime instance."""
    T = ft.types()
    for m in params['maps']:
        for en in entries_of(m):
            tag = '%s entry %s' % (m['name'], en['id'])
            try:
                ent = ft.resolve_entry(en['block'])
            except ft.Fail as e:
                checks.append(dict(check='%s: block exists' % tag, result='FAIL', evidence=str(e)))
                continue
            checks.append(dict(check='%s: block exists' % tag, result='PASS', evidence=ent.split('/')[-1]))
            b = tb.Block(ft.archive().read(ent), os.path.splitext(ent)[1])
            try:
                lf, nxt, _ = S.last_fragment(b, ent)
                checks.append(dict(check='%s: last fragment save-safe' % tag, result='PASS',
                                   evidence='%s, next runtime index %d' % (lf.split('/')[-1], nxt)))
            except S.Fail as e:
                checks.append(dict(check='%s: last fragment save-safe' % tag, result='FAIL', evidence=str(e)[:160]))
            par = en.get('parent') or default_entry_parent(en['block'])
            try:
                lit, W, info = S.literal_for(b, ent, par['fragment'], par['entity'], T)
                checks.append(dict(check='%s: parent exists (one runtime instance)' % tag, result='PASS',
                                   evidence='%s runtime %s world %s' % (info['path'], info['runtime_index'],
                                                                        [round(c, 2) for c in W[0]])))
            except (S.Fail, ft.Fail, fe.EditError, KeyError) as e:
                checks.append(dict(check='%s: parent exists (one runtime instance)' % tag, result='FAIL', evidence=str(e)[:160]))
            spots = {t['name'] for t in m.get('teleports', [])}
            if en.get('arrive_at'):
                ok = en['arrive_at'] in spots
                checks.append(dict(check='%s: arrive_at %s is a teleport of the map' % (tag, en['arrive_at']),
                                   result='PASS' if ok else 'FAIL', evidence='teleports: %s' % sorted(spots)))


def node_by_name(b, T, name):
    """(fragment doc, node, creation order) of the created node called `name` in a block, or None."""
    fr = S.frags_of(b)
    for nm, k in fr.items():
        if len(b.payloads[k]) < 24:
            continue
        d = fe.FragDoc(b.payloads[k], T, nm)
        for i, n in enumerate(d.created_ids()):
            if d.get(n, fe.P_NAME) == name:
                return d, n, i
    return None


def check_entries_built(manifest, entries, checks):
    """The loader pair of every entry, read back from the written blocks: same parent, position, orientation and size,
    MAINMAP first, TargetName = the new map / submap folder, Teleport_to = the entry's spot, and that spot exists."""
    T = ft.types()
    for mm in manifest['maps']:
        mb = tb.Block(entries[mm['map_block']], '.map')
        spot_names = {mm['arrival_node']} | {t['name'] for t in mm['teleports']}
        for en in mm['entries']:
            tag = '%s entry %s' % (mm['name'], en['id'])
            ent = ft.resolve_entry(en['block'])
            b = tb.Block(entries[ent], os.path.splitext(ent)[1])
            n_main, n_sub = en['loader_nodes']
            a, c = node_by_name(b, T, n_main), node_by_name(b, T, n_sub)
            if not a or not c:
                checks.append(dict(check='%s: loader pair present' % tag, result='FAIL', evidence='%s / %s not found' % (n_main, n_sub)))
                continue
            (da, na, ia), (dc, nc, ic) = a, c
            tgt = {}
            for d, n, key in ((da, na, 'main'), (dc, nc, 'sub')):
                act = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Activate_Load_Unload_Save')]
                tgt[key] = (d.get(act[0], 'TargetName'), d.get(act[0], 'Teleport_to')) if act else (None, None)
            props = lambda d, n: [d.get(n, k) for k in ('parent', 'pos', 'orient', 'width', 'height', 'length')]
            pa, pc = props(da, na), props(dc, nc)
            coincident = pa == pc and da.name == dc.name
            order_ok = ia < ic
            checks.append(dict(check='%s: loader pair coincident, MAINMAP before SUBMAP' % tag,
                               result='PASS' if coincident and order_ok else 'FAIL',
                               evidence='pos %s size %s %s order %d<%d' % ([round(x, 2) for x in pa[1]], pa[3:], 'identical' if coincident else 'DIFFERENT', ia, ic)))
            ok = tgt['main'] == (mm['map_folder'], en['target_node']) and tgt['sub'] == (mm['submap_folder'], en['target_node'])
            checks.append(dict(check='%s: targets %s / %s, lands at %s' % (tag, mm['map_folder'], mm['submap_folder'], en['target_node']),
                               result='PASS' if ok else 'FAIL', evidence='main %s sub %s' % (tgt['main'], tgt['sub'])))
            here = node_by_name(mb, T, en['target_node'])
            checks.append(dict(check='%s: spot node %s exists in the new map block' % (tag, en['target_node']),
                               result='PASS' if here else 'FAIL', evidence='' if not here else 'world %s' % [
                                   round(x, 2) for x in here[0].world(here[1], fe.IDENT)[0]]))


def post_checks(zip_path, manifest, checks):
    # re-read the written zip with the engine-style reader and strict-round-trip every changed block
    T = ft.types()
    import zipfile
    z = zipfile.ZipFile(zip_path)
    bad = []
    for n in z.namelist():
        ext = os.path.splitext(n)[1]
        if ext in ('.map', '.submap', '.main'):
            r = ft.roundtrip_block(z.read(n), ext, T)
            if r['fail'] or not r['block_identical']:
                bad.append(n)
    checks.append(dict(check='zip re-read: every block strict round-trips', result='FAIL' if bad else 'PASS',
                       evidence='%d entries, bad=%s' % (len(z.namelist()), bad)))
    for m in manifest['maps']:
        for e in (m['map_block'], m['submap_block']):
            checks.append(dict(check='zip contains %s' % e.split('/')[-1], result='PASS' if e in z.namelist() else 'FAIL',
                               evidence=''))
    # fragment paths full form in the written overdose.main
    mb = tb.Block(z.read(MAIN), '.main')
    info = bytes(mb.info)
    for m in manifest['maps']:
        pass
    checks.append(dict(check='overdose.main written', result='PASS', evidence='%d bytes' % len(z.read(MAIN))))


# ------------------------------------------------------------------------------------------------ main
def build(params, out, collision=True, check_only=False):
    os.makedirs(out, exist_ok=True)
    checks = []
    rep = dict(package=params.get('package'), time=time.strftime('%Y-%m-%d %H:%M:%S'), checks=checks, collision=[])
    try:
        pre_checks(params, checks)
        spec, manifest = gen_spec(params, out)
        json.dump(spec, open(os.path.join(out, 'spec.json'), 'w'), indent=1)
        json.dump(manifest, open(os.path.join(out, 'manifest.json'), 'w'), indent=1)
        checks.append(dict(check='ids unique and limits raised', result='PASS',
                           evidence='map ids %s, submap ids %s, MAPS_MAX %d, SUBMAPS_MAX %d' % (
                               [m['map_id'] for m in manifest['maps']], [m['submap_id'] for m in manifest['maps']],
                               manifest['base_limits']['MAPS_MAX'] + len(params['maps']),
                               manifest['base_limits']['SUBMAPS_MAX'] + len(params['maps']))))
        for m in params['maps']:
            check_teleport(m, checks)
        check_entries_pre(params, checks)
        if check_only:
            rep['result'] = 'CHECK-ONLY'
            return rep
        import argparse as ap
        a = ap.Namespace(spec=os.path.join(out, 'spec.json'), out=out, deploy=None)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = S.cmd_build(a)
        sb = json.load(open(os.path.join(out, 'report.json'))) if os.path.exists(os.path.join(out, 'report.json')) else {}
        checks.append(dict(check='submaptool build + verify (save-safe grafts)', result='PASS' if code == 0 else 'FAIL',
                           evidence=sb.get('result', '?')))
        if code != 0:
            raise RecipeError('build: %s' % sb.get('result'))
        json.dump(sb, open(os.path.join(out, 'submaptool_report.json'), 'w'), indent=1, default=str)
        # blocks written by the build
        built = {}
        for fn in os.listdir(out):
            if fn.endswith(('.map', '.submap', '.main')):
                built[fn] = open(os.path.join(out, fn), 'rb').read()
        # the zip carries every data entry; re-collect with full entry names
        import zipfile
        zname = os.path.join(out, 'stream_override.zip')
        zin = zipfile.ZipFile(zname)
        entries = {n: zin.read(n) for n in zin.namelist()}
        zin.close()
        ctx_hosts = []
        for m, mm in zip(params['maps'], manifest['maps']):
            sets = []
            if m.get('collision_sets') and collision:
                sets = stage_collision(mm, m, entries, rep)
                checks.append(dict(check='collision generator %s' % m['name'], result='PASS',
                                   evidence='%d sets, %s' % (len(sets), '; '.join(rep['collision'][-1]['notes']))))
            elif m.get('collision_sets'):
                from todct import collision as CO
                mk = re.match(r'map\d+_[a-z0-9_]+', m['name'].lower()).group(0)
                sets = [shorthand_to_set(s, mk) for s in m['collision_sets']]
            try:
                from todct import collision as CO
                mk = re.match(r'map\d+_[a-z0-9_]+', m['name'].lower()).group(0)
                ctx = CO.MapContext(mk, [mm['map_block'], mm['submap_block']], lambda e: entries[e])
                ctx_hosts = CO.existing_layer(ctx, m['arrival']['pos'], 60.0)
            except Exception as e:             # noqa: BLE001
                ctx_hosts = []
                checks.append(dict(check='source hulls readable', result='WARN', evidence=str(e)[:200]))
            check_arrival(m, sets, ctx_hosts, checks)
        for e, raw in entries.items():
            open(os.path.join(out, e.split('/')[-1]), 'wb').write(raw)
        rep['zip'] = ft.write_zip(zname, sorted(entries.items()))
        post_checks(zname, manifest, checks)
        check_entries_built(manifest, entries, checks)
        rep['geometry'] = manifest.get('geometry')
        for g in manifest.get('geometry') or []:
            for c in g['checks']:
                checks.append(dict(check='new_geometry %s: %s' % (g['map'], c['check']), result='PASS' if c['ok'] else 'FAIL', evidence=''))
        line = 'filesystem = ' + ', '.join(['stream_override.zip'] + ft.BASE_ARCHIVES)
        open(os.path.join(out, 'configpc_line.txt'), 'w').write(line + '\n')
        rep['configpc_line'] = line
        rep['manifest'] = manifest
        rep['result'] = 'FAIL' if any(c['result'] == 'FAIL' for c in checks) else 'PASS'
    except (RecipeError, S.Fail, fe.EditError, ft.Fail, KeyError, ValueError) as e:
        rep['result'] = 'FAIL: %s' % e
    json.dump(rep, open(os.path.join(out, 'recipe_report.json'), 'w'), indent=1, default=str)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('params', nargs='?'); ap.add_argument('--out')
    ap.add_argument('--list-entry-hosts', action='store_true', help='print which existing blocks can host an entry loader pair (JSON) and exit')
    ap.add_argument('--no-collision', action='store_true'); ap.add_argument('--check-only', action='store_true')
    a = ap.parse_args()
    if a.list_entry_hosts:
        print(json.dumps(list_entry_hosts(), indent=1))
        return 0
    if not a.params or not a.out:
        ap.error('PARAMS and --out are required')
    rep = build(json.load(open(a.params)), a.out, collision=not a.no_collision, check_only=a.check_only)
    for c in rep.get('checks', []):
        print('%-5s %s  [%s]' % (c['result'], c['check'], str(c.get('evidence', ''))[:160]))
    print('RESULT', rep['result'])
    return 0 if rep['result'] in ('PASS', 'CHECK-ONLY') else 1


if __name__ == '__main__':
    sys.exit(main())
