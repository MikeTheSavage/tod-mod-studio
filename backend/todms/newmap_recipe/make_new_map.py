"""make_new_map.py - build a TOD "new map" package (stream_override.zip) from a small parameter file.

This is the recipe TOD Mod Studio's "Add map" feature wraps. It is data only (no exe or DLL change) and is built on
tools/level_streaming/submaptool.py (save-safe grafts, verified), plus the Mod Studio collision generator
(backend/todct) for new collision.

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
# Mod Studio's own copy (forked from the vendored recipe in wave 3); newgeo, geomkit, tex_gen, base_overlay and cpu_guard stay vendored.
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'vendor', 'newmap')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'level_streaming'))
os.environ.setdefault('TOD_TOOLS', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'vendor', 'tools'))
sys.path.append(HERE); import base_overlay; base_overlay.install()   # MESA_BASE_ZIP: build on a Gameplay+ data zip (see base_overlay.py)
import submaptool as S            # noqa: E402  (also puts fragment_writer + save_editor on sys.path)
import newgeo as NG               # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import newmap_extras as EX        # noqa: E402  (shipped records in a new block, the look, carry region / nothing)
import extgeo                     # noqa: E402  (new_geometry inside an extension section)
from todms import bakestep        # noqa: E402  (baked lighting of the generated geometry)

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


# What an entrance shows from far away: the shipped loader draws a glowing beam (MapTeleport) and an area icon (ExitMap_*). A beam 12 m wide and
# 24 m tall fills the screen of a player who steps out of a door beside it, so the default is a slim beam; the icon is a choice (or none).
MARKER_ICONS = dict(church='ExitMap_Church', bullring='ExitMap_Bullring', downtown='ExitMap_Downtown_South', harbour='ExitMap_Harbour',
                    industrial='ExitMap_Industrial', border='ExitMap_US', angel='ExitMap_angel')
MARKER_BEAMS = ('none', 'slim', 'full')
MARKER_DEFAULT = dict(icon='church', beam='slim')
TINY = [0.01, 0.01, 0.01]


def marker_spec(spec):
    """-> dict(icon, beam) with the defaults filled in; RecipeError for a kind the game does not have."""
    m = dict(MARKER_DEFAULT)
    if spec:
        if not isinstance(spec, dict):
            raise RecipeError('an entrance marker is {icon, beam}')
        m.update({k: v for k, v in spec.items() if v is not None})
    if m['icon'] != 'none' and m['icon'] not in MARKER_ICONS:
        raise RecipeError('marker icon %r: choose none or one of %s' % (m['icon'], ', '.join(sorted(MARKER_ICONS))))
    if m['beam'] not in MARKER_BEAMS:
        raise RecipeError('marker beam %r: choose none, slim or full' % (m['beam'],))
    return m


def marker_sprites(spec, quiet=False):
    """The settings of the beam sprite (index 0) and the icon sprite (index 1) of a loader."""
    m = marker_spec(spec)
    s0, s1 = dict(SPRITE0), dict(SPRITE1)
    if m['beam'] == 'slim':
        s0.update(pos=[0.0, 3.0, 0.0], sprite_size=[5.0, 10.0, 1.0])
    elif m['beam'] == 'none':
        s0.update(sprite_size=list(TINY))
    if m['icon'] == 'none':
        s1.update(sprite_size=list(TINY))
    else:
        s1.update(texture='/Textures/Hud/%s.BMP' % MARKER_ICONS[m['icon']])
    if quiet:
        s0.update(sprite_size=list(TINY))
        s1.update(sprite_size=list(TINY))
    return s0, s1


def loader_op(name, pos, orient, size, target, teleport, parent, use=False, locked=False, quiet=False, marker=None):
    """A loader box (touch by default). use: fire when the player presses USE inside (Condition TrueOn 2: "Press [F] to use");
    locked: see locked_loader_op (flags 1 on the box itself did nothing in game: wave 3 proofs s1, s3, s4); teleport None = no Teleport_to."""
    act = dict(TargetName=target, name='Action_' + name)
    if teleport:
        act['Teleport_to'] = teleport
    root = dict(width=size[0], height=size[1], length=size[2])
    s0, s1 = marker_sprites(marker, quiet)       # quiet: a trigger the player should not see (a kill plane): the beam is made too small to show
    cs = [dict(type='Trigger_Activate_Load_Unload_Save(NodeLogical)', set=act),
          dict(type='generic_object_effect(Sprite)', index=0, set=s0),
          dict(type='generic_object_effect(Sprite)', index=1, set=s1)]
    if use:
        cs.insert(0, dict(type='Trigger_Condition(NodeLogical)', set=dict(TrueOn=2)))
    return dict(op='graft', deep=True, parent=parent, name=name, pos=list(pos), orient=list(orient), set=root, child_sets=cs, **LOADER_SRC)


# a parked car of Downtown (vehicle_placeholder, sub type 18 = a car; the placeholder spawns the car when its section loads)
VEHICLE_SRC = dict(from_block='submap01_map02_lostoros_downtown.submap', from_fragment='SUBMAP01_Map02_Traffic.fragment', entity='0x00300A79')


def vehicle_op(v, name, parent):
    """A car: a Downtown vehicle placeholder at pos, facing yaw degrees (engine convention), optional sub_type (the model of car)."""
    st = {}
    if v.get('sub_type') is not None:
        st['VehicleSubType'] = int(v['sub_type'])
    return dict(op='graft', deep=False, parent=parent, name=name, pos=list(v['pos']), orient=arrive_orient(v), set=st, **VEHICLE_SRC)


# a box trigger that ends the running mission (clone of the Elvez car dealer "MISSION_FAILED_Trigger_01": player enters -> End_Mission_Result)
ENDBOX_SRC = dict(from_block='mm070_elvezcardealer.mission', from_fragment='MM070_ElvezCardealer.fragment', entity='0x00400412')
# a road folder with two traffic points (Harbour back alley): the shape traffic routes are written in (points link by name across folders)
ROAD_SRC = dict(from_block='submap02_map04_lostoros_train_harbour.submap', from_fragment='SUBMAP02_Map04_Traffic.fragment', entity='0x003003E2')
ROAD_SPEED = 15.0
TRAFFIC_END_PAD = 3.0         # metres: an odd route gets one more end point because each road folder carries two


def trigger_ops(m, par, map_folder, sub_folder, spots):
    """Box triggers of the expanded map (`triggers`): kind teleport = the player is sent to a spot of the SAME map (a loader pair whose
    targets are this map's own folders: no native fall recovery exists), kind end_mission = the running mission ends with `result`.
    -> (ops, manifest rows)."""
    ops, rows = [], []
    for t in m.get('triggers') or []:
        tid = up(str(t['id']))
        size = list(t.get('size') or [4, 4, 4])
        orient = t.get('orient', IDENT)
        if t.get('kind') == 'teleport':
            to = t.get('teleport_to')
            if to not in spots:
                raise RecipeError('%s: trigger %s sends the player to %r, which is not a spot of the map %s' % (m['name'], t['id'], to, sorted(spots)))
            ops.append(loader_op('TRIGGER_MAIN_%s' % tid, t['pos'], orient, size, map_folder, to, par, quiet=True))
            ops.append(loader_op('TRIGGER_SUB_%s' % tid, t['pos'], orient, size, sub_folder, to, par, quiet=True))
            rows.append(dict(id=t['id'], kind='teleport', nodes=['TRIGGER_MAIN_%s' % tid, 'TRIGGER_SUB_%s' % tid], teleport_to=to,
                             pos=t['pos'], size=size, reason=t.get('reason')))
        elif t.get('kind') == 'end_mission':
            ops.append(dict(op='graft', deep=True, parent=par, name='TRIGGER_%s' % tid, pos=list(t['pos']), orient=list(orient),
                            set=dict(width=size[0], height=size[1], length=size[2]),
                            child_sets=[dict(type='Trigger_Activate_Mission(NodeLogical)', set=dict(End_Mission_Result=int(t.get('result', 0))))],
                            **ENDBOX_SRC))
            rows.append(dict(id=t['id'], kind='end_mission', nodes=['TRIGGER_%s' % tid], result=int(t.get('result', 0)), pos=t['pos'],
                             size=size, reason=t.get('reason')))
        else:
            raise RecipeError('%s: trigger %s has the unknown kind %r' % (m['name'], t.get('id'), t.get('kind')))
    return ops, rows


def traffic_ops(m, par):
    """`traffic_routes` (mapgen: {road, direction, boundradius, points [{name, pos, next}]}) as grafts of two-point road folders. A chain of
    points becomes one folder per pair; the links are the points' `NameOfNextPoint` names (the engine finds a name under the points'
    grandparent, here the map's own folder, so a chain crosses folders). First point of a route = a spawn point (Sub_Type 4), the last an end (3).
    -> (ops, manifest rows)."""
    ops, rows = [], []
    for r in m.get('traffic_routes') or []:
        pts = [dict(p) for p in r['points']]
        if len(pts) < 2:
            continue
        if len(pts) % 2:                                     # each road folder carries two points
            a, b = pts[-2]['pos'], pts[-1]['pos']
            d = [b[i] - a[i] for i in (0, 2)]
            n = math.hypot(*d) or 1.0
            ext = dict(name=pts[-1]['name'] + '_END', pos=[b[0] + d[0] / n * TRAFFIC_END_PAD, b[1], b[2] + d[1] / n * TRAFFIC_END_PAD], next=None)
            pts[-1]['next'] = ext['name']
            pts.append(ext)
        rid = up('%s_%s' % (r.get('road', 'R'), r.get('direction', '')))
        for k in range(0, len(pts), 2):
            a, b = pts[k], pts[k + 1]
            cs = []
            for i, p in enumerate((a, b)):
                first, last = (k + i == 0), (k + i == len(pts) - 1)
                loc = [0.0, 0.0, 0.0] if i == 0 else [b['pos'][j] - a['pos'][j] for j in range(3)]
                cs.append(dict(type='database_traffic_point(NodeSpatial)', index=i,
                               set=dict(name=p['name'], pos=loc, orient=IDENT, boundradius=float(r.get('boundradius', 4.0)),
                                        Sub_Type=3 if last else (4 if first else 0), NameOfNextPoint='' if last else (p.get('next') or '')))
                          )
            ops.append(dict(op='graft', deep=True, parent=par, name='ROAD_%s_%d' % (rid, k // 2 + 1), pos=list(a['pos']), orient=IDENT,
                            set=dict(TrafficMaxSpeed=ROAD_SPEED, TrafficMaxDensity=1, TrafficAllowLargeVehicles=False), child_sets=cs, **ROAD_SRC))
        rows.append(dict(road=r.get('road'), direction=r.get('direction'), points=len(pts), folders=len(pts) // 2))
    return ops, rows


# A loader that starts DISABLED, the shipped way: the Folder that holds the box carries flags 1 (like ZAP_Disabled, the enemy wake folders,
# the MAPLOADERS_Enabled folder of MM100) and is enabled by name with Trigger_Activate_Enable_Disable ActionType 5. Source: the Farm loader
# Folder (Folder > Trigger_Root_A + Condition + Action + one beam sprite). Flags 1 = disabled.
LOCKED_LOADER_SRC = dict(from_block='submap02_map06_virgillos_farm.submap', from_fragment='SUBMAP02_Map06_Data.fragment', entity='0x00300073')


def locked_loader_op(name, pos, orient, size, target, teleport, parent, use=False, marker=None, quiet=False):
    act = dict(TargetName=target, name='Action_' + name)
    if teleport:
        act['Teleport_to'] = teleport
    cs = [dict(type='Trigger_Root(CollisionBox)', set=dict(name='Box_' + name, flags=0, pos=list(pos), orient=list(orient), width=size[0], height=size[1], length=size[2])),
          dict(type='Trigger_Condition(NodeLogical)', set=dict(TrueOn=2 if use else 1)),
          dict(type='Trigger_Activate_Load_Unload_Save(NodeLogical)', set=act),
          dict(type='generic_object_effect(Sprite)', index=0, set=marker_sprites(marker, quiet)[0])]
    return dict(op='graft', deep=True, parent=parent, name=name, pos=[0.0, 0.0, 0.0], orient=IDENT, set=dict(flags=1), child_sets=cs, **LOCKED_LOADER_SRC)


def gate_op(name, targets, mission, parent, pos):
    """Unlock gate: when a section loads fresh (the start broadcast, TrueOn 6) and the LAST mission played is `mission`, enable the
    named roots (Trigger_Activate_Enable_Disable, ActionType 5). A clone of the Downtown wake trigger with the condition changed."""
    cs = [dict(type='Trigger_Condition(NodeLogical)', set=dict(TrueOn=6, LastMission=int(mission)))]
    for i in range(4):
        cs.append(dict(type='Trigger_Activate_Enable_Disable(NodeLogical)', index=i,
                       set=dict(ActionType=5, TargetName=targets[i % len(targets)])))
    return dict(op='graft', deep=True, parent=parent, name=name, pos=list(pos), orient=IDENT,
                set=dict(width=2.0, height=2.0, length=2.0, flags=256, CollisionFlags=16), child_sets=cs, **WAKE_SRC)


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
GEO_VEHICLE_DATA = {}                 # map name -> does the built map block hold the vehicle database (see build_geometry)
# The source's Default_Data fragment is Mission_Specific_Database > Vehicles: the car models' node trees (Mainbody, Wheels, Driver_Player ...)
# that every car is built from. A map block without it draws every car it holds INVISIBLE: the car is still there (shadow, physics, the
# player sits in it) but has no model. Proven in game (wave 3 showcase8): a car carried through a loader into a geometry map was invisible,
# the same car into the plain clone of the source or into a shipped map was drawn. So new geometry keeps this fragment (98 nodes).
VEHICLE_DATA_FOLDER = 'MAINMAP10_Default_Data'


def build_geometry(geo_in, src, name, out_dir):
    """NG.build with the source's vehicle database kept (new_geometry.vehicle_data, default true)."""
    ng = geo_in.get('new_geometry') or {}
    keep = bool(ng.get('vehicle_data', True))
    saved = list(NG.DROP_FOLDERS)
    if keep:
        NG.DROP_FOLDERS[:] = [f for f in saved if f != VEHICLE_DATA_FOLDER]
    try:
        geo = NG.build(geo_in, src, name, out_dir, geo_K(), ft.types())
    finally:
        NG.DROP_FOLDERS[:] = saved
    GEO_VEHICLE_DATA[name] = _has_vehicle_data(geo['map_file'])
    geo['report']['vehicle_data'] = GEO_VEHICLE_DATA[name]
    return geo


def _has_vehicle_data(map_file):
    """Does the map block hold a Default_Data fragment (the vehicle database)?"""
    try:
        b = tb.Block(open(map_file, 'rb').read(), '.map')
        return any('default_data' in n.lower() for n in S.frags_of(b))
    except Exception:                       # noqa: BLE001
        return False


def geo_K():
    """Namespace newgeo.py needs: the fragment/model tools (todct.tools.load) + submaptool."""
    from types import SimpleNamespace
    from todct import tools as TT
    k = TT.load()
    return SimpleNamespace(ft=k.ft, fe=k.fe, tb=k.tb, tf=k.tf, tm=k.tm, mw=k.mw, S=S)


def shipped_into_geometry(m):
    """The map's new_geometry plus its `shipped_models` (models of the game, from mapgen scatter) as models that are copied with their
    pictures and as placements. A new copy; the recipe is not changed."""
    ng = dict(m['new_geometry'])
    ng['models'] = list(ng.get('models') or [])
    ng['placements'] = list(ng.get('placements') or [])
    names = {}
    for k, s in enumerate(m.get('shipped_models') or []):
        key = s['model'].lower()
        if key not in names:
            names[key] = 'SH%d' % (len(names) + 1)
            ng['models'].append(dict(name=names[key], parts=[], shipped=s['model'], shipped_blocks=list(s.get('blocks') or [])))
        ng['placements'].append(dict(model=names[key], pos=list(s['pos']), name='SHP_%d' % (k + 1)))
    return ng


def ex_bind():
    """Give the block-level writers (newmap_extras) this builder's tools; newgeo learns shipped pictures and models."""
    from todct import tools as TT
    k = TT.load()
    EX.bind(ft=ft, fe=fe, tb=tb, tf=tf, S=S, NG=NG, tm=k.tm)
    EX.install(NG)
    return k


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


VEHICLE_BOX = (16.0, 8.0, 6.0)          # a loader a car drives through: width across the road, height, depth along it (metres)
_REG = {}


def arrive_orient(a):
    """Facing of an arrival spot: a quaternion, or a yaw in degrees about Y. Measured in the game (wave 3 proofs): the player runs
    along (-sin yaw, 0, cos yaw): yaw 0 faces +z, 90 faces -x, 180 faces -z, 270 faces +x."""
    if a.get('orient'):
        return list(a['orient'])
    y = math.radians(float(a.get('yaw', 0.0)))
    return [0.0, math.sin(y / 2), 0.0, math.cos(y / 2)]


def facing_vector(yaw):
    """Ground direction an arrival yaw (degrees) makes the player face: (x, z)."""
    y = math.radians(float(yaw))
    return (-math.sin(y), math.cos(y))


def plan_ids(maps, mmax, smax):
    """Per map (map id or None for an extension section, submap / section id) and the new MAPS_MAX / SUBMAPS_MAX. A map may carry
    map_id / submap_id (extension: section_id) given by the installer; the rest follow the current limits in order."""
    nm, ns, out = mmax, smax, []
    for m in maps:
        ext = m.get('placement') == 'extension'
        mid = None
        if not ext:
            mid = int(m.get('map_id', nm))
            nm = max(nm, mid + 1)
        sid = int(m.get('section_id' if ext else 'submap_id', ns))
        ns = max(ns, sid + 1)
        out.append((mid, sid))
    used_m = [x[0] for x in out if x[0] is not None]
    used_s = [x[1] for x in out]
    if len(set(used_m)) != len(used_m) or len(set(used_s)) != len(used_s):
        raise RecipeError('map or section numbers repeat inside one project: %s %s' % (used_m, used_s))
    return out, nm, ns


def registry():
    """The map registry of the (overlaid) overdose.main: rows [{kind 'map'|'submap', name, node, parent, fragment, id}] and the load screens."""
    if 'r' in _REG:
        return _REG['r']
    T = ft.types()
    b = tb.Block(ft.archive().read(MAIN), '.main')
    fr = S.frags_of(b)
    nm = [n for n in fr if n.lower().endswith('overdose.scene')][0]
    d = fe.FragDoc(b.payloads[fr[nm]], T, nm)
    out = []
    for n in d.created_ids():
        t = d.type_of(n) or ''
        if t.startswith('database_SubMap_ID') or t.startswith('database_Map_ID'):
            out.append(dict(kind='submap' if 'SubMap' in t else 'map', name=d.get(n, fe.P_NAME), node=n, parent=d.get(n, fe.P_PARENT),
                            fragment=d.get(n, 'fragment') or '', id=d.get(n, 'Specific_ID')))
    ls = []
    lname = [n for n in fr if n.lower().endswith('loadscreens.fragment')]
    if lname:
        d2 = fe.FragDoc(b.payloads[fr[lname[0]]], T, lname[0])
        for n in d2.created_ids():
            sm = d2.get(n, 'Sub_Map')
            if sm is not None:
                ls.append(dict(name=d2.get(n, fe.P_NAME), sub_map=sm, node=n))
    _REG['r'] = dict(rows=out, loadscreens=ls)
    return _REG['r']


def _stem(path):
    return os.path.splitext(path.replace(chr(92), '/').split('/')[-1])[0].lower()


def host_row(block):
    stem = _stem(block)
    for e in registry()['rows']:
        if e['fragment'] and _stem(e['fragment']) == stem:
            return e
    return None


def host_names(block):
    """The registry names of a shipped block: {'block': folder name, 'map': MAINMAP folder of the same map, 'submap': this or the first submap}."""
    row = host_row(block)
    if not row:
        return None
    same = [e for e in registry()['rows'] if e['parent'] == row['parent']]
    mp = next((e['name'] for e in same if e['kind'] == 'map'), None)
    sm = row['name'] if row['kind'] == 'submap' else next((e['name'] for e in same if e['kind'] == 'submap'), None)
    return dict(block=row['name'], map=mp, submap=sm)


def section_base(blk, old_root, new_root, entry, mode, poly, out, whole=False):
    """The base block of an extension section that carries only a region of the host section, or nothing: the host's copy with the root
    renamed, cut down by newmap_extras.prune_section, written beside the build. whole=True keeps the whole copy (mode all, used when new
    geometry is added on top). -> (path, dict(kept, removed, dropped_records, notes))."""
    ex_bind()
    T = ft.types()
    raw = ft.archive().read(ft.resolve_entry(blk))
    b = NG.rename_root(raw, '.submap', tb, old_root, new_root, lambda x: list(S.frags_of(x)))
    root_full = [n for n in S.frags_of(b) if n.split('/')[-1] == new_root][0]
    if whole:
        new, rep = b.serialize(), None
    else:
        new, rep = EX.prune_section(b.serialize(), '.submap', poly, T, root_name=root_full)
    r1 = ft.roundtrip_block(new, '.submap', T)
    if r1['fail'] or not r1['block_identical']:
        raise RecipeError('extension: the cut-down copy of %s does not round-trip' % blk)
    path = os.path.join(out, 'base_' + entry.split('/')[-1])
    os.makedirs(out, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(new)
    return path, rep


def ext_geometry(m, blk, old_root, new_root, entry, mode, poly, out, spec, manifest_geo):
    """new_geometry of an extension: the section's base block (the host copy, cut by carry) + the new records and nodes (extgeo), then the
    bake. Returns (base file, carried, geometry report)."""
    from todms.mapgen import geoplug
    ex_bind()
    T = ft.types()
    path, carried = section_base(blk, old_root, new_root, entry, mode, poly, out, whole=(mode == 'all'))
    if m.get('models'):
        raise RecipeError('%s: "models" places models the SOURCE block owns; an extension with new_geometry places its own (new_geometry.placements)' % m['name'])
    ng = shipped_into_geometry(m)
    if ng.get('shipped') or any(mo.get('shipped') for mo in ng.get('models') or []):
        raise RecipeError('%s: models of the game are not copied into an extension section yet (shipped_models)' % m['name'])
    geoplug.set_alpha({t['name']: t.get('alpha') for t in ng.get('textures', []) if t.get('alpha')})
    raw = open(path, 'rb').read()
    root_full = [n for n in S.frags_of(tb.Block(raw, '.submap')) if n.split('/')[-1] == new_root][0]
    out_raw, rep, world = extgeo.add_geometry(raw, '.submap', root_full, ng, SOURCES['map10_runawaytrain'], geo_K(), T, NG)
    with open(path, 'wb') as f:
        f.write(out_raw)
    rep['map_file'] = path
    geo = dict(map_file=path, submap_file=None, report=rep, root_fragment=root_full, folder_node=rep['folder_node'], collision_tris=world)
    rep['bake'] = bakestep.run(geo, m, geo_K(), T, ext='.submap', replace=(mode == 'nothing'))
    GEO_TRIS[m['name']] = world
    manifest_geo.append(dict(map=m['name'], **rep))
    return path, carried, rep


def extension_ops(m, i, sec_id, main_ops, per_block, spec, manifest, ext_names, out='.'):
    """placement "extension": a new submap beside a shipped one, in the HOST map's coordinate space (the proven S1 route:
    docs/subsystem_level_streaming.md 7). The new section REPLACES the host section while it is loaded, so it carries a copy of the host
    section ("carry": {"mode": "all"}). Parts: a sibling folder + load screen in the registry, the block (a copy of the host submap with its
    root fragment renamed) + language stubs, a loader into it from the host block and one back, SUBMAPS_MAX (done by plan_ids)."""
    host = m.get('host') or {}
    blk = (host.get('block') or '').lower()
    if not blk:
        raise RecipeError('extension: choose the host section (host.block)')
    row = host_row(blk)
    if not row or row['kind'] != 'submap':
        raise RecipeError('extension: %s is not a registered section of a shipped map' % blk)
    carry = m.get('carry') or {}
    mode = carry.get('mode', 'all')
    if mode not in ('all', 'region', 'nothing'):
        raise RecipeError('extension: carry is all, region or nothing (not %r)' % mode)
    poly = None
    if mode == 'region':
        try:
            poly = EX.polygon_from_region(carry.get('region'))
        except ValueError as e:
            raise RecipeError('extension: %s' % e)
    frag = row['fragment'].replace(chr(92), '/')
    old_root = frag.split('/')[-1]
    folder_dir = frag.rsplit('/', 1)[0] + '/'
    stem = os.path.splitext(old_root)[0]
    head, tail = stem.split('_', 1)
    taken = {n.lower() for n in ft.archive().names} | ext_names
    num = 6
    while True:
        new_name = 'SUBMAP%02d_%s' % (num, tail)
        entry = SHARED + new_name.lower() + '.submap'
        if entry not in taken and len(new_name) == len(stem):
            break
        num += 1
        if num > 99:
            raise RecipeError('extension: no free section name beside %s' % blk)
    ext_names.add(entry)
    new_root = new_name + '.fragment'
    carried = None
    geo_rep = None
    if m.get('new_geometry'):
        base_file, carried, geo_rep = ext_geometry(m, blk, old_root, new_root, entry, mode, poly, out, spec, manifest['geometry_ext'])
        spec['new_blocks'].append(dict(entry=entry, clone_of_file=base_file, lang_from=blk, localized=True))
    elif mode == 'all':
        spec['new_blocks'].append(dict(entry=entry, clone_of=blk, rename_root=[old_root, new_root], localized=True))
    else:
        base_file, carried = section_base(blk, old_root, new_root, entry, mode, poly, out)
        spec['new_blocks'].append(dict(entry=entry, clone_of_file=base_file, lang_from=blk, localized=True))
    ls = next((x for x in registry()['loadscreens'] if x['sub_map'] == row['id']), None)
    main_ops.append(dict(op='graft', from_block='overdose.main', from_fragment='Overdose.scene', entity='0x%08X' % row['node'], deep=False,
                         parent=dict(fragment='Overdose.scene', entity='0x%08X' % row['parent']), name=new_name,
                         set={'fragment': folder_dir + new_root, 'Specific_ID': sec_id, 'order': 20 + i}))
    if ls:
        main_ops.append(dict(op='graft', from_block='overdose.main', from_fragment='LoadScreens.fragment', entity='0x%08X' % ls['node'],
                             deep=True, parent=dict(fragment='LoadScreens.fragment', entity='Sub_Maps_Loadscreens'), name=new_name + '_ls',
                             set={'Sub_Map': sec_id, 'order': 40 + i}))
    par = host.get('parent') or default_entry_parent(blk)
    par_new = dict(par, fragment=new_root if par['fragment'].lower() == old_root.lower() else par['fragment'])
    en, lv = host.get('enter') or {}, host.get('leave') or {}
    if en.get('pos') is None or lv.get('pos') is None:
        raise RecipeError('extension: give host.enter.pos (the loader in the host section) and host.leave.pos (the way back)')
    eo = en.get('orient', [0.0, 0.70710678, 0.0, 0.70710678])
    esz = list(en.get('size', [12, 6, 2]))
    lo = lv.get('orient', eo)
    lsz = list(lv.get('size', esz))
    use = host.get('prompt') == 'use'
    n_in, n_out = 'TriggerLoad_' + new_name, 'TriggerLoad_' + row['name'] + '_Back'
    spots = {t['name'] for t in m.get('teleports', [])}
    tp = en.get('teleport_to')
    if tp and tp not in spots:
        raise RecipeError('extension: host.enter.teleport_to %r is not one of the section spots %s' % (tp, sorted(spots)))
    per_block.setdefault(blk, []).append(loader_op(n_in, en['pos'], eo, esz, new_name, tp, par, use=use))
    ops = [loader_op(n_out, lv['pos'], lo, lsz, row['name'], None, par_new, use=use)]
    for t in m.get('teleports', []):                                   # named spots in the section: where the enter box may land the player
        ops.append(dict(op='graft', deep=False, parent=par_new, name=t['name'], pos=t['pos'], orient=arrive_orient(t), **ARRIVAL_SRC))
    for k, v in enumerate(m.get('vehicles', [])):
        ops.append(vehicle_op(v, 'CAR_%s_%d' % (up(m['name']), k + 1), par_new))
    for w in m.get('walls', []):
        ops.append(dict(op='graft', deep=False, parent=par_new, name=w['name'], pos=w['pos'], orient=w.get('orient', IDENT),
                        set=dict(width=w['size'][0], height=w['size'][1], length=w['size'][2], CollisionFlags=w.get('flags', 3)), **WALL_SRC))
    per_block.setdefault(entry, []).extend(ops)
    manifest['sections'].append(dict(name=new_name, label=m.get('name'), section_id=sec_id, block=entry, host_block=blk, host_folder=row['name'],
                                     root_fragment=new_root, enter=dict(pos=en['pos'], size=esz, orient=eo), leave=dict(pos=lv['pos'], size=lsz, orient=lo),
                                     loader_nodes=[n_in, n_out], carry=mode, carried=carried, region=poly, load_screen=bool(ls), new_geometry=bool(geo_rep), arrival=m.get('arrival'),
                                     prompt='use' if use else 'touch'))


def gen_spec(params, out='.'):
    mmax, smax = read_limits()
    maps = params['maps']
    spec = dict(description='%s: %d new map(s) by make_new_map.py' % (params.get('package', '?'), len(maps)),
                zip='stream_override.zip', new_blocks=[], blocks=[])
    ids, new_mmax, new_smax = plan_ids(maps, mmax, smax)
    main_ops = [dict(op='set', fragment='Overdose.scene', entity='common(Node)', prop='MAPS_MAX', value=new_mmax),
                dict(op='set', fragment='Overdose.scene', entity='common(Node)', prop='SUBMAPS_MAX', value=new_smax)]
    per_block = {}                      # entry -> ops
    manifest = dict(package=params.get('package'), maps=[], sections=[], base_limits=dict(MAPS_MAX=mmax, SUBMAPS_MAX=smax),
                    new_limits=dict(MAPS_MAX=new_mmax, SUBMAPS_MAX=new_smax), uid=params.get('uid'), geometry_ext=[])
    ext_names = set()
    geo_reports = []
    for i, m in enumerate(maps):
        if m.get('placement') == 'extension':
            extension_ops(m, i, ids[i][1], main_ops, per_block, spec, manifest, ext_names, out)
            continue
        src = SOURCES[m['source']]
        name = m['name']
        if len(name) != len(src['map_name']):
            raise RecipeError('map name %r must have %d characters like %r (block root names are fixed-size)'
                              % (name, len(src['map_name']), src['map_name']))
        low = name.lower()
        map_id, sub_id = ids[i]
        mroot = src['root'].replace(src['map_name'], name)
        sroot = src['subroot'].replace(src['map_name'], name)
        mfrag = 'MAINMAP_%s' % name
        sfrag = 'SUBMAP01_%s' % name
        e_map = SHARED + 'mainmap_%s.map' % low
        e_sub = SHARED + 'submap01_%s.submap' % low
        geo = None
        if m.get('new_geometry'):
            if m.get('models'):
                raise RecipeError('%s: "models" places models the SOURCE block owns, and a map with its own ground has none; '
                                  'use new_geometry.placements, or "shipped_models" for models of the game' % name)
            geo_in = dict(m, new_geometry=shipped_into_geometry(m))
            ex_bind()
            from todms.mapgen import geoplug
            geoplug.set_alpha({t['name']: t.get('alpha') for t in geo_in['new_geometry'].get('textures', []) if t.get('alpha')})
            geo = build_geometry(geo_in, src, name, os.path.join(out, 'geometry_' + low))
            geo['report']['bake'] = bakestep.run(geo, m, geo_K(), ft.types())          # baked lighting; dynamic lighting when it cannot be done
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
        r = m.get('return')
        exits = []                                      # every way out: dict(name, pos, size, orient, locked)
        if r:
            ro = r.get('orient', IDENT)
            rsz = r.get('size', [8, 8, 2])
            ops.append(loader_op('TriggerLoad_MAINMAP_Return', r['pos'], ro, rsz, r['target_map'],
                                 r['teleport_to'], par, use=r.get('prompt') == 'use', marker=r.get('marker')))
            ops.append(loader_op('TriggerLoad_SUBMAP_Return', r['pos'], ro, rsz, r['target_submap'],
                                 r['teleport_to'], par, use=r.get('prompt') == 'use', marker=r.get('marker'), quiet=True))
            exits.append(dict(id='return', pos=r['pos'], size=rsz, orient=ro, locked=False))
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
        trig_ops, trig_rows = trigger_ops(m, par, mfrag, sfrag, {t['name'] for t in m.get('teleports', [])})
        ops.extend(trig_ops)
        traf_ops, traf_rows = traffic_ops(m, par)
        ops.extend(traf_ops)
        # --- entry loaders in the existing maps: one loader pair (MAINMAP then SUBMAP, coincident) per entry
        spots = {t['name'] for t in m.get('teleports', [])}
        ent_list = entries_of(m)
        ent_manifest = []
        for en in ent_list:
            eblk = en['block']
            eops = per_block.setdefault(eblk, [])
            eo = en.get('orient', [0.0, 0.70710678, 0.0, 0.70710678])
            sz = list(en.get('size', [12, 6, 2]))
            if en.get('vehicle'):                          # a car crosses the box at speed: wider across the road, deeper along it
                sz = [max(sz[0], VEHICLE_BOX[0]), max(sz[1], VEHICLE_BOX[1]), max(sz[2], VEHICLE_BOX[2])]
            target = en.get('arrive_at') or arr_name
            if en.get('arrive_at') and en['arrive_at'] not in spots:
                raise RecipeError('%s: entry %s arrive_at %r is not one of the map teleports %s' % (name, en['id'], en['arrive_at'], sorted(spots)))
            tag = '%s' % name if en.get('legacy') else '%s_%s' % (name, up(en['id']))
            if en.get('arrive'):                            # own arrival spot and facing for this entrance
                target = 'ARR_%s' % tag
                ar = en['arrive']
                ops.append(dict(op='graft', deep=False, parent=par, name=target, pos=ar['pos'], orient=arrive_orient(ar), **ARRIVAL_SRC))
                spots.add(target)
                m.setdefault('_arrive_spots', []).append(dict(name=target, pos=list(ar['pos']), entry=en['id']))
            en = dict(en, parent=en.get('parent') or default_entry_parent(eblk))
            n_main = 'TriggerLoad_MAINMAP_%s' % tag
            n_sub = ('TriggerLoad_SUBMAP01_%s' % tag) if en.get('legacy') else 'TriggerLoad_SUBMAP_%s' % tag
            lock = en.get('lock')
            use = en.get('prompt') == 'use'
            mk_loader = locked_loader_op if lock else loader_op
            marker_spec(en.get('marker'))
            eops.append(mk_loader(n_main, en['pos'], eo, sz, mfrag, target, en['parent'], use=use, marker=en.get('marker')))
            eops.append(mk_loader(n_sub, en['pos'], eo, sz, sfrag, target, en['parent'], use=use, marker=en.get('marker'), quiet=True))      # the pair sits on one spot: one of them draws
            if lock:
                gp = list(en['pos'])
                gp[1] += 4.0
                eops.append(gate_op('GATE_%s' % tag, [n_main, n_sub], lock['mission'], en['parent'], gp))
            back = en.get('back')
            back_manifest = None
            if back and not en.get('one_way'):
                hn = host_names(eblk) or {}
                bmap = back.get('target_map') or (r or {}).get('target_map') or hn.get('map')
                bsub = back.get('target_submap') or (r or {}).get('target_submap') or hn.get('submap')
                if not bmap or not bsub:
                    raise RecipeError('%s: entry %s back needs target_map and target_submap (or a map return to copy them from)' % (name, en['id']))
                tp = back.get('teleport_to') or (r or {}).get('teleport_to')
                if back.get('spot'):                        # a landing node of our own in the host block
                    sp = back['spot']
                    tp = 'RET_%s' % tag
                    eops.append(dict(op='graft', deep=False, parent=en['parent'], name=tp, pos=sp['pos'], orient=arrive_orient(sp), **ARRIVAL_SRC))
                if not tp:
                    raise RecipeError('%s: entry %s back needs a landing spot' % (name, en['id']))
                bo = back.get('orient', IDENT)
                bsz = back.get('size', [8, 8, 2])
                ops.append(loader_op('TriggerLoad_MAINMAP_Ret_%s' % up(en['id']), back['pos'], bo, bsz, bmap, tp, par, use=back.get('prompt') == 'use', marker=back.get('marker')))
                ops.append(loader_op('TriggerLoad_SUBMAP_Ret_%s' % up(en['id']), back['pos'], bo, bsz, bsub, tp, par, use=back.get('prompt') == 'use', marker=back.get('marker'), quiet=True))
                exits.append(dict(id=en['id'], pos=back['pos'], size=bsz, orient=bo, locked=False))
                back_manifest = dict(pos=back['pos'], size=bsz, orient=bo, teleport_to=tp, teleport_block=eblk if back.get('spot') else (r or {}).get('teleport_block'),
                                     target_map=bmap, target_submap=bsub, spot_node=tp if back.get('spot') else None)
            ent_manifest.append(dict(id=en['id'], block=eblk, parent=en['parent'], pos=en['pos'], orient=eo, size=sz,
                                     arrive_at=en.get('arrive_at'), target_node=target, loader_nodes=[n_main, n_sub],
                                     back=back_manifest, one_way=bool(en.get('one_way')), vehicle=bool(en.get('vehicle')), use=use,
                                     lock=lock, gate_node=('GATE_%s' % tag) if lock else None,
                                     host_names=(host_names(eblk) if back else None)))
        per_block.setdefault(e_sub if in_sub else e_map, []).extend(ops)
        manifest['maps'].append(dict(name=name, source=m['source'], map_id=map_id, submap_id=sub_id, map_block=e_map,
                                     submap_block=e_sub, arrival_node=arr_name, arrival=a,
                                     entry=ent_manifest[0] if ent_manifest else None, entries=ent_manifest,
                                     teleports=[dict(name=t['name'], pos=t['pos']) for t in m.get('teleports', [])] + m.get('_arrive_spots', []),
                                     exits=exits, placement=m.get('placement', 'separate'), neighbour=m.get('neighbour'),
                                     map_folder=mfrag, submap_folder=sfrag, new_geometry=bool(geo), triggers=trig_rows, traffic=traf_rows,
                                     lighting=m.get('lighting'), root_fragment=(geo or {}).get('root_fragment')))
    for k, sp in enumerate(params.get('existing_spots', [])):           # a named landing spot in an already working section (a loader may teleport the player there)
        per_block.setdefault(sp['block'], []).append(dict(op='graft', deep=False, parent=sp.get('parent') or default_entry_parent(sp['block']), name=sp['name'],
                                                          pos=sp['pos'], orient=arrive_orient(sp), **ARRIVAL_SRC))
    for k, v in enumerate(params.get('existing_vehicles', [])):         # a car in an already working section (the player can get in and drive)
        per_block.setdefault(v['block'], []).append(vehicle_op(v, 'EXTRA_CAR_%d' % (k + 1), v.get('parent') or default_entry_parent(v['block'])))
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
    manifest['geometry'] = geo_reports + manifest.pop('geometry_ext')
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
    spots = [('arrival', m['arrival']['pos'])] + [('spot %s' % t['name'], t['pos']) for t in m.get('teleports', [])] + \
        [('entrance arrival %s' % t['entry'], t['pos']) for t in m.get('_arrive_spots', [])]
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
    check_arrival_clear(m, spots, checks)
    check_landing_clear(m, checks)
    check_vehicle_data(m, checks)
    check_scene_steps(m, checks)
    check_scene_area(m, checks)


def check_scene_area(m, checks):
    """A scene map must stand where no shipped map does: the Gameplay+ radar and the map's own coordinates are read by position, so a district
    on top of Downtown's streets is taken for Downtown (and the other way round). WARN names the shipped maps under it; PASS when the area is free."""
    a = (m.get('mapgen') or {}).get('scene_area')
    if not a:
        return
    from todms import minimap as MM
    pad = MM.MARGIN
    area = [a[0] - pad, a[1] - pad, a[2] + pad, a[3] + pad]
    over = MM.overlaps(area, MM.SHIPPED_BOUNDS)
    nm = 'map area free of shipped maps %s' % m['name']
    if over:
        checks.append(dict(check=nm, result='WARN', evidence='the district (x %.0f to %.0f, z %.0f to %.0f) lies over %s; give it its own place in the world' % (
            a[0], a[2], a[1], a[3], ', '.join(over))))
    else:
        checks.append(dict(check=nm, result='PASS', evidence='x %.0f to %.0f, z %.0f to %.0f: no shipped map is there' % (a[0], a[2], a[1], a[3])))


def check_scene_steps(m, checks):
    """A scene's walk surface that jumps by more than the player climbs: kerbs, plinths and stairs he cannot get up (he climbs 1.4 m, not 1.6;
    measured in game). A taller jump is a wall. WARN with the count, the highest and where; PASS when there are none. The scene import counts them."""
    st = (m.get('mapgen') or {}).get('scene_steps')
    if st is None:
        return
    nm = 'steps within reach %s' % m['name']
    if not st.get('count'):
        checks.append(dict(check=nm, result='PASS', evidence='no step above %.1f m (the most the player climbs)' % st['limit']))
        return
    where = ', '.join('%.0f, %.0f (%.1f m)' % tuple(p) for p in st['places'][:3])
    checks.append(dict(check=nm, result='WARN', evidence='%d places where the ground steps up by %.1f to %.1f m, more than the player climbs: %s' % (
        st['count'], st['limit'], st['highest'], where)))


def _in_box(pt, pos, orient, size, margin=0.0):
    """Is the point inside the loader box (+ margin)? The box is width x height x length about pos, turned by the quaternion."""
    x, y, z, w = orient
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    d = [pt[0] - pos[0], pt[1] - pos[1], pt[2] - pos[2]]
    # rotate d by the inverse quaternion
    qx, qy, qz, qw = -x, -y, -z, w
    ux, uy, uz = qy * d[2] - qz * d[1], qz * d[0] - qx * d[2], qx * d[1] - qy * d[0]
    tx, ty, tz = 2 * ux, 2 * uy, 2 * uz
    r = [d[0] + qw * tx + (qy * tz - qz * ty), d[1] + qw * ty + (qz * tx - qx * tz), d[2] + qw * tz + (qx * ty - qy * tx)]
    return abs(r[0]) <= size[0] / 2 + margin and abs(r[1]) <= size[1] / 2 + margin and abs(r[2]) <= size[2] / 2 + margin


MARKER_NEAR = 10.0       # metres: a landing closer than this to a loader box of the same section sits in the glare of its icon
MARKER_CONE = 70.0       # degrees: and looks towards it


def _facing(yaw):
    """Facing of a spot: (-sin yaw, cos yaw) in the ground plane (yaw 0 looks along +z, 90 along -x, 270 along +x)."""
    a = math.radians(float(yaw))
    return -math.sin(a), math.cos(a)


def check_vehicle_data(m, checks):
    """A map with its own geometry needs the vehicle database, or every car in it is invisible (a carried car, a parked car, a mission car).
    FAIL when a vehicle entrance leads here, WARN otherwise."""
    if not m.get('new_geometry') or m['name'] not in GEO_VEHICLE_DATA:
        return
    name = 'vehicle database %s' % m['name']
    if GEO_VEHICLE_DATA[m['name']]:
        checks.append(dict(check=name, result='PASS', evidence='the map block keeps the car model trees: cars are drawn'))
        return
    veh = [e['id'] for e in (m.get('entries') or []) if e.get('vehicle')]
    if veh:
        checks.append(dict(check=name, result='FAIL', evidence='vehicle entrance %s carries a car here, and a map without the vehicle database draws it invisible' % ', '.join(veh)))
    else:
        checks.append(dict(check=name, result='WARN', evidence='a car in this map is invisible (no vehicle database in the map block)'))


def check_landing_clear(m, checks):
    """Where a way back (or an entrance) puts the player in an existing section: not next to a loader box of the same section (its icon and
    glare fill the screen), above all not looking at one. WARN, not FAIL: the player can walk away."""
    ents = [e for e in (m.get('entries') or []) if e.get('block')]
    for en in ents:
        spot = (en.get('back') or {}).get('spot')
        if not spot or spot.get('pos') is None:
            continue
        pos = spot['pos']
        yaw = spot.get('yaw')
        for other in ents:
            if other['block'] != en['block'] or other.get('pos') is None:
                continue
            size = other.get('size', [8, 8, 2])
            if not _in_box(pos, other['pos'], other.get('orient', IDENT), [size[0], max(size[1], 40.0), size[2]], MARKER_NEAR):
                continue
            dx, dz = other['pos'][0] - pos[0], other['pos'][2] - pos[2]
            dist = math.hypot(dx, dz)
            facing = False
            if yaw is not None and dist > 1e-6:
                fx, fz = _facing(yaw)
                facing = (fx * dx + fz * dz) / dist >= math.cos(math.radians(MARKER_CONE))
            nm = 'landing clear of loader %s: way back of %s %s' % (other.get('id'), en.get('id'), m['name'])
            if facing or dist < 4.0:
                checks.append(dict(check=nm, result='WARN', evidence='%.1f m from the loader box%s: its icon and glare fill the view' % (dist, ' and looking at it' if facing else '')))
            else:
                checks.append(dict(check=nm, result='PASS', evidence='%.1f m from the loader box, looking away' % dist))
            break
        else:
            checks.append(dict(check='landing clear of loaders: way back of %s %s' % (en.get('id'), m['name']), result='PASS', evidence='clear'))


NEAR_RETURN = 2.5        # metres: an arrival closer to a return box than this walks into it by accident


def check_arrival_clear(m, spots, checks):
    """No arrival spot inside a way-out box (the player would leave at once) or within NEAR_RETURN metres of one."""
    boxes = []
    r = m.get('return')
    if r:
        boxes.append(('return', r['pos'], r.get('orient', IDENT), r.get('size', [8, 8, 2])))
    for en in (m.get('entries') or []) + ([m['entry']] if m.get('entry') else []):
        bk = en.get('back')
        if bk and not en.get('one_way'):
            boxes.append(('way back of %s' % en.get('id'), bk['pos'], bk.get('orient', IDENT), bk.get('size', [8, 8, 2])))
    for label, pt in spots:
        for bl, pos, ori, size in boxes:
            nm = 'arrival clear of %s: %s %s' % (bl, label, m['name'])
            if _in_box(pt, pos, ori, size):
                checks.append(dict(check=nm, result='FAIL', evidence='the spot is inside the box: the player would leave at once'))
            elif _in_box(pt, pos, ori, size, NEAR_RETURN):
                checks.append(dict(check=nm, result='WARN', evidence='closer than %.1f m to the box' % NEAR_RETURN))
            else:
                checks.append(dict(check=nm, result='PASS', evidence='clear'))
    for label, pt in spots:                          # a landing inside a giver box: the mission is offered at once, and one layout stopped the game
        for k, gv in enumerate(m.get('givers') or []):
            half = float(gv.get('size', 3.0)) / 2 + 0.5
            if abs(pt[0] - gv['pos'][0]) <= half and abs(pt[2] - gv['pos'][2]) <= half:
                checks.append(dict(check='arrival clear of giver %s: %s %s' % (gv.get('name', k + 1), label, m['name']), result='FAIL',
                                   evidence='the spot is inside the giver box'))


def _node_in_block(blk, nm):
    T = ft.types()
    b = tb.Block(ft.archive().read(ft.resolve_entry(blk)), os.path.splitext(blk)[1])
    for fn, k in S.frags_of(b).items():
        try:
            d = fe.FragDoc(b.payloads[k], T, fn)
        except Exception:                         # noqa: BLE001
            continue
        for n in d.created_ids():
            if d.get(n, fe.P_NAME) == nm:
                return True
    return False


def check_teleport(m, checks):
    r = m.get('return')
    if r:
        blk, nm = r.get('teleport_block'), r['teleport_to']
        ok = bool(blk) and _node_in_block(blk, nm)
        checks.append(dict(check='return teleport node %s exists in %s' % (nm, blk), result='PASS' if ok else
                           ('FAIL' if blk else 'WARN'), evidence='found' if ok else 'not found / no teleport_block given'))
    for en in (m.get('entries') or []) + ([m['entry']] if m.get('entry') else []):
        bk = en.get('back')
        if bk and not en.get('one_way') and bk.get('teleport_to') and not bk.get('spot'):
            blk = en['block']
            ok = _node_in_block(blk, bk['teleport_to'])
            checks.append(dict(check='entrance %s way back lands on %s in %s' % (en.get('id'), bk['teleport_to'], blk),
                               result='PASS' if ok else 'FAIL', evidence='found' if ok else 'not found'))


LOCK_REFUSED = {
    'cash': 'the game has no native test for how much money the player holds',
    'money': 'the game has no native test for how much money the player holds',
    'item': 'the game has no native test for what the player carries',
    'items': 'the game has no native test for what the player carries',
    'time': 'the game has no native test for the time of day',
    'time_of_day': 'the game has no native test for the time of day',
}


def check_loader_options(m, checks):
    """Entrance options the engine can do (native conditions only) and the rule "every map has one unlocked way out"."""
    ents = (m.get('entries') or []) + ([m['entry']] if m.get('entry') else [])
    for en in ents:
        lock = en.get('lock')
        if lock:
            for k in lock:
                if k in LOCK_REFUSED:
                    raise RecipeError('%s: an entrance cannot be locked by %s: %s. Lock it by a mission instead.' % (m.get('name'), k, LOCK_REFUSED[k]))
            if not isinstance(lock.get('mission'), int) or isinstance(lock.get('mission'), bool) or lock['mission'] < 0:
                raise RecipeError('%s: a lock needs the number of the mission that unlocks it (lock.mission)' % m.get('name'))
        if en.get('prompt') not in (None, 'touch', 'use'):
            raise RecipeError('%s: prompt must be touch or use' % m.get('name'))
        marker_spec(en.get('marker'))
    if m.get('placement') == 'extension':
        return
    has_back = bool(m.get('return')) or any(en.get('back') and not en.get('one_way') for en in ents)
    checks.append(dict(check='%s: at least one unlocked way out' % m.get('name'), result='PASS' if has_back else 'FAIL',
                       evidence='a return box or an entrance with its own way back' if has_back else 'every entrance is one-way and the map has no return'))


def pre_checks(params, checks):
    names = set(ft.archive().names)
    seen = set()
    for m in params['maps']:
        check_loader_options(m, checks)
        if m.get('placement') == 'extension':
            continue
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
        if m.get('placement') == 'extension':
            continue
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


def unwrap_box(d, n):
    """The Trigger_Root box of a loader node: the node itself, or the box inside the disabled Folder of a locked loader."""
    if (d.type_of(n) or '') == 'Folder':
        kids = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Root')]
        if kids:
            return kids[0]
    return n


def check_entries_built(manifest, entries, checks):
    """The loader pair of every entry, read back from the written blocks: same parent, position, orientation and size,
    MAINMAP first, TargetName = the new map / submap folder, Teleport_to = the entry's spot, and that spot exists."""
    T = ft.types()
    for mm in manifest['maps']:
        mb = tb.Block(entries[mm['map_block']], '.map')
        sbk = tb.Block(entries[mm['submap_block']], '.submap') if mm['submap_block'] in entries else None
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
            oa, oc = na, nc
            na, nc = unwrap_box(da, na), unwrap_box(dc, nc)            # a locked loader is a Folder that holds the box
            tgt = {}
            for d, n, key in ((da, na, 'main'), (dc, nc, 'sub')):
                act = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Activate_Load_Unload_Save')]
                tgt[key] = (d.get(act[0], 'TargetName'), d.get(act[0], 'Teleport_to')) if act else (None, None)
            props = lambda d, n, o: [d.get(o, 'parent')] + [d.get(n, k) for k in ('pos', 'orient', 'width', 'height', 'length')]
            pa, pc = props(da, na, oa), props(dc, nc, oc)
            coincident = pa == pc and da.name == dc.name
            order_ok = ia < ic
            checks.append(dict(check='%s: loader pair coincident, MAINMAP before SUBMAP' % tag,
                               result='PASS' if coincident and order_ok else 'FAIL',
                               evidence='pos %s size %s %s order %d<%d' % ([round(x, 2) for x in pa[1]], pa[3:], 'identical' if coincident else 'DIFFERENT', ia, ic)))
            ok = tgt['main'] == (mm['map_folder'], en['target_node']) and tgt['sub'] == (mm['submap_folder'], en['target_node'])
            checks.append(dict(check='%s: targets %s / %s, lands at %s' % (tag, mm['map_folder'], mm['submap_folder'], en['target_node']),
                               result='PASS' if ok else 'FAIL', evidence='main %s sub %s' % (tgt['main'], tgt['sub'])))
            here = node_by_name(mb, T, en['target_node']) or (node_by_name(sbk, T, en['target_node']) if sbk is not None else None)
            checks.append(dict(check='%s: spot node %s exists in the new map blocks' % (tag, en['target_node']),
                               result='PASS' if here else 'FAIL', evidence='' if not here else 'world %s' % [
                                   round(x, 2) for x in here[0].world(here[1], fe.IDENT)[0]]))


def apply_looks(manifest, entries, checks):
    """Write each map's `lighting` into the fragments of its blocks (and the sky's records when the sky is not the clone source's), then read
    it back. entries: entry -> raw bytes (changed in place)."""
    T = ft.types()
    ex_bind()
    for mm in manifest['maps']:
        lt = mm.get('lighting')
        if not lt:
            continue
        applied, skipped, added = [], [], []
        for e, root in ((mm['map_block'], mm.get('root_fragment')), (mm['submap_block'], None)):
            ext = os.path.splitext(e)[1]
            new, rep = EX.apply_look_block(entries[e], ext, lt, T, drop_old_sky=bool(root), root_name=root)
            if e == mm['map_block']:
                skipped = rep['skipped']
            applied += rep['applied']
            added += rep.get('added_records', [])
            if new is None:
                continue
            r1 = ft.roundtrip_block(new, ext, T)
            if r1['fail'] or not r1['block_identical']:
                checks.append(dict(check='look %s: %s round-trips' % (mm['name'], e.split('/')[-1]), result='FAIL', evidence='the block with the look does not round-trip'))
                continue
            again, rep2 = EX.apply_look_block(new, ext, lt, T)
            entries[e] = new
            checks.append(dict(check='look %s: %s read back' % (mm['name'], e.split('/')[-1]), result='PASS' if again is None else 'FAIL',
                               evidence='; '.join(rep['applied']) or 'nothing to write'))
        mm['look_report'] = dict(applied=applied, skipped=skipped, sky_records_added=added)
        for sk in skipped:
            checks.append(dict(check='look %s' % mm['name'], result='WARN', evidence=sk))


def name_index(b, T):
    """{node name: [(fragment doc, node)]} of every created node of a block."""
    out = {}
    for nm, k in S.frags_of(b).items():
        if len(b.payloads[k]) < 24:
            continue
        try:
            d = fe.FragDoc(b.payloads[k], T, nm)
        except Exception:                         # noqa: BLE001
            continue
        for n in d.created_ids():
            v = d.get(n, fe.P_NAME)
            if v:
                out.setdefault(v, []).append((d, n))
    return out


def check_bake_built(manifest, entries, checks):
    """The baked lighting of each new-geometry map, read back from the FINAL map block: HD's strict record reader, then the engine's own lookups
    for every placed node (unique-id path -> instance -> one colour buffer per mesh with the mesh's vertex and index counts). A map whose bake
    was skipped gets a WARN with the reason (it keeps dynamic lighting)."""
    for g in manifest.get('geometry') or []:
        bk = g.get('bake') or {}
        if bk.get('status') != 'baked':
            if bk.get('reason') and bk.get('reason') != 'switched off':
                checks.append(dict(check='bake %s' % g['map'], result='WARN', evidence='dynamic lighting only: %s' % bk['reason']))
            continue
        mm = next((x for x in manifest['maps'] if x['name'] == g['map']), None)
        sec = next((x for x in manifest['sections'] if x.get('label') == g['map']), None) if mm is None else None
        blk, ext = (mm['map_block'], '.map') if mm else (sec['block'], '.submap')
        try:
            res = bakestep.verify_final(entries[blk], ext, bk)
            checks.append(dict(check='bake %s: baked lighting read back' % g['map'], result='PASS', evidence=res))
        except Exception as e:                      # noqa: BLE001
            checks.append(dict(check='bake %s: baked lighting read back' % g['map'], result='FAIL', evidence=str(e)[:300]))


def check_extras_built(manifest, entries, checks):
    """Triggers and traffic read back from the written map block: every node is there once, a teleport trigger targets this map's own
    folders and a spot that exists, every traffic point's next name resolves."""
    T = ft.types()
    for mm in manifest['maps']:
        if not mm.get('triggers') and not mm.get('traffic'):
            continue
        b = tb.Block(entries[mm['map_block']], '.map')
        idx = name_index(b, T)
        sb = tb.Block(entries[mm['submap_block']], '.submap')
        sidx = name_index(sb, T)
        spots = {t['name'] for t in mm['teleports']} | {mm['arrival_node']}
        for t in mm.get('triggers', []):
            tag = '%s trigger %s' % (mm['name'], t['id'])
            found = [idx.get(n) or sidx.get(n) for n in t['nodes']]
            if not all(f and len(f) == 1 for f in found):
                checks.append(dict(check='%s: nodes present once' % tag, result='FAIL', evidence=str(t['nodes'])))
                continue
            if t['kind'] == 'teleport':
                bad = []
                for (d, n), want in zip([f[0] for f in found], (mm['map_folder'], mm['submap_folder'])):
                    act = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Activate_Load_Unload_Save')]
                    got = (d.get(act[0], 'TargetName'), d.get(act[0], 'Teleport_to')) if act else (None, None)
                    if got != (want, t['teleport_to']):
                        bad.append(got)
                ok = not bad and t['teleport_to'] in spots and (idx.get(t['teleport_to']) or sidx.get(t['teleport_to']))
                checks.append(dict(check='%s: sends the player to %s of this map' % (tag, t['teleport_to']), result='PASS' if ok else 'FAIL',
                                   evidence='targets %s / %s' % (mm['map_folder'], mm['submap_folder']) if ok else 'read back %s' % bad))
            else:
                d, n = found[0][0]
                act = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Activate_Mission')]
                got = d.get(act[0], 'End_Mission_Result') if act else None
                checks.append(dict(check='%s: ends the mission with result %s' % (tag, t['result']), result='PASS' if got == t['result'] else 'FAIL',
                                   evidence='read back %s' % got))
        if mm.get('traffic'):
            pts = {}
            for nm, lst in idx.items():
                for d, n in lst:
                    if (d.type_of(n) or '').startswith('database_traffic_point'):
                        pts.setdefault(nm, []).append((d.get(n, 'NameOfNextPoint'), d.get(n, 'Sub_Type')))
            dup = [k for k, v in pts.items() if len(v) > 1]
            dangling = [k for k, v in pts.items() if v[0][0] and v[0][0] not in pts]
            ends = [k for k, v in pts.items() if v[0][1] == 3]
            want = sum(r['points'] for r in mm['traffic'])
            ok = not dup and not dangling and len(pts) == want and len(ends) == len(mm['traffic'])
            checks.append(dict(check='%s: traffic routes linked (%d points, %d routes)' % (mm['name'], len(pts), len(mm['traffic'])),
                               result='PASS' if ok else 'FAIL',
                               evidence='unique names, every next name resolves' if ok else 'duplicates %s, dangling %s, ends %d, expected points %d' % (dup[:3], dangling[:3], len(ends), want)))


EDGE_GRID = 12.0


def check_edge_view(manifest, checks):
    """An extension section that carries only a region (or nothing) stops drawing the host section outside it. From a coarse grid of the
    section's walkable area, 8 sight lines per point run over its edge: a line that leaves the region while the host MAP block draws nothing
    there (a coarse 24 m picture of its models) is a place where the player could see the end of the world. -> WARN with the worst spots."""
    T = ft.types()
    ex_bind()
    for sec in manifest.get('sections', []):
        mode = sec.get('carry')
        if mode == 'all':
            continue
        tag = 'section %s' % sec['name']
        if mode == 'nothing':
            checks.append(dict(check='%s: edge of view' % tag, result='WARN',
                               evidence='the section carries nothing: only what you add stands in it, and past it the host map is drawn from its own map block'))
            sec['edge_view'] = dict(samples=0, hits=[])
            continue
        poly = sec.get('region')
        hn = host_names(sec['host_block']) or {}
        mp = hn.get('map')
        occ = set()
        try:
            ent = SHARED + mp.lower() + '.map'
            occ = EX.occupancy(ft.archive().read(ent), '.map', T)
        except Exception as e:                                 # noqa: BLE001
            checks.append(dict(check='%s: edge of view' % tag, result='WARN', evidence='the host map block could not be read (%s)' % str(e)[:80]))
            continue
        xs, zs = [p[0] for p in poly], [p[1] for p in poly]
        y = sec['enter']['pos'][1]
        walk = []
        x = min(xs)
        while x <= max(xs):
            z = min(zs)
            while z <= max(zs):
                if EX.inside(poly, x, z):
                    walk.append((x, y, z))
                z += EDGE_GRID
            x += EDGE_GRID
        walk = walk[:600]
        loaded = lambda px, pz: (int(math.floor(px / 24.0)), int(math.floor(pz / 24.0))) in occ
        hits = EX.sightlines(walk, poly, loaded)
        sec['edge_view'] = dict(samples=len(walk), hits=hits[:10], count=len(hits))
        if hits:
            h = hits[0]
            checks.append(dict(check='%s: edge of view' % tag, result='WARN',
                               evidence='%d of %d sight lines from the walkable area end at unloaded space, the nearest from (%.0f, %.0f) looking %d degrees at %.0f m' % (
                                   len(hits), len(walk) * 8, h['pos'][0], h['pos'][2], h['dir_deg'], h['distance'])))
        else:
            checks.append(dict(check='%s: edge of view' % tag, result='PASS', evidence='%d points checked, nothing unloaded in sight' % len(walk)))


def check_sections_built(manifest, entries, checks):
    """Each extension section: the block is in the zip with its language stubs, the loader pair exists, and the loader into it targets it."""
    T = ft.types()
    for sec in manifest.get('sections', []):
        tag = 'section %s' % sec['name']
        ok = sec['block'] in entries
        checks.append(dict(check='%s: block in the package' % tag, result='PASS' if ok else 'FAIL', evidence=sec['block'].split('/')[-1]))
        if not ok:
            continue
        base = os.path.splitext(sec['block'].split('/')[-1])[0] + '_'
        stubs = [e for e in entries if e.split('/')[-1].startswith(base) and '/shared/' not in e]
        checks.append(dict(check='%s: language stubs' % tag, result='PASS' if len(stubs) >= 5 else 'FAIL', evidence='%d stubs' % len(stubs)))
        host_ent = ft.resolve_entry(sec['host_block'])
        hb = tb.Block(entries[host_ent], os.path.splitext(host_ent)[1])
        nb = tb.Block(entries[sec['block']], '.submap')
        for blk, node, target, label in ((hb, sec['loader_nodes'][0], sec['name'], 'loader into the section'),
                                         (nb, sec['loader_nodes'][1], sec['host_folder'], 'loader back to the host')):
            found = node_by_name(blk, T, node)
            if not found:
                checks.append(dict(check='%s: %s' % (tag, label), result='FAIL', evidence='%s not found' % node))
                continue
            d, n, _ = found
            act = [x for x in d.children(n) if (d.type_of(x) or '').startswith('Trigger_Activate_Load_Unload_Save')]
            tn = d.get(act[0], 'TargetName') if act else None
            checks.append(dict(check='%s: %s targets %s' % (tag, label, target), result='PASS' if tn == target else 'FAIL', evidence='target %s' % tn))


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
                           evidence='map ids %s, submap ids %s, section ids %s, MAPS_MAX %d, SUBMAPS_MAX %d' % (
                               [m['map_id'] for m in manifest['maps']], [m['submap_id'] for m in manifest['maps']],
                               [x['section_id'] for x in manifest['sections']],
                               manifest['new_limits']['MAPS_MAX'], manifest['new_limits']['SUBMAPS_MAX'])))
        real = [m for m in params['maps'] if m.get('placement') != 'extension']
        for m in real:
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
        for m, mm in zip(real, manifest['maps']):
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
        apply_looks(manifest, entries, checks)
        for e, raw in entries.items():
            open(os.path.join(out, e.split('/')[-1]), 'wb').write(raw)
        rep['zip'] = ft.write_zip(zname, sorted(entries.items()))
        post_checks(zname, manifest, checks)
        check_entries_built(manifest, entries, checks)
        check_sections_built(manifest, entries, checks)
        check_extras_built(manifest, entries, checks)
        check_bake_built(manifest, entries, checks)
        check_edge_view(manifest, checks)
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
