# TOD Mod Studio

A level and data editor for Total Overdose (2005). It runs on its own: you do not need Unreal, Python or anything
else. It opens your own installed copy of the game, shows the levels in 3D with their real meshes and textures, lets
you move, add and remove gameplay objects and change game values, and writes the result as a mod the unmodified game
loads.

The app never contains or ships the game's files or art. Everything it shows is read from your own installation into
a local cache on your computer, and a mod you share is a small recipe file that each player builds from their own
game.

## Install

Download `TOD Mod Studio <version>.zip` from the
[latest release](https://github.com/MikeTheSavage/tod-mod-studio/releases/latest), unzip it and run
`TODModStudio-Setup-<version>.exe` (per user, no administrator rights): it installs to
`%LOCALAPPDATA%\Programs\TOD Mod Studio` (or a folder you pick), adds Start-menu entries for the app and for the
plain-language guide (`TOD Mod Studio Guide.html`), optionally a desktop shortcut, and an uninstaller under
Settings > Apps. Running a newer Setup updates the program and keeps your mods and settings. Silent use:
`Setup.exe --silent [--dir D] [--desktop] [--no-startmenu]`, `"Uninstall TOD Mod Studio.exe" --uninstall --silent [--purge]`.

Without the installer: unzip `TODModStudio-win64.zip` anywhere and run `TODModStudio.exe`.

Windows 10 and 11 have the WebView2 runtime the window needs; on an old system, install "Microsoft Edge WebView2
Runtime" first (Setup warns when it is missing).

## First run

1. Pick your Total Overdose folder: the one with `TOD.exe` and `blocks.naz` (GOG: `C:\GOG Games\Total Overdose`).
2. The app checks the game (it reads the game's own property tables and checks them against the game's checksums),
   lists the maps, sections and missions and extracts every map into its cache
   (`%LOCALAPPDATA%\TODModStudio\cache`, a few hundred MB). Missions are extracted the first time you open them.
3. If TOD HD is installed in that folder, the app sees it and builds your mods on top of TOD HD's blocks.

## Making a level mod

1. **Level editor** tab: pick a map, a section and, if you want the mission objects (enemies, pickups, vehicles,
   routes), one or more missions. Click **Open**.
2. Navigate: left drag orbits, right drag pans, the wheel zooms, W A S D Q E fly (Shift is faster), F frames the
   selected object.
3. Click an object (in the view or in the **Objects** list). The gizmo moves it (G), rotates it (R) or, for boxes,
   resizes it (T). The panel on the right edits its position, turn, size, collision flags, pickup / weapon / vehicle
   type, name and, under **All properties**, every value the object carries.
4. **Add** puts a new pickup, weapon, enemy, vehicle, trigger box, invisible wall, nav blocker or route point at the
   point in the middle of the view. **Duplicate** (Ctrl+D) copies the selected object, **Delete** removes it.
   Undo and redo: Ctrl+Z and Ctrl+Y.
5. **Layers** switches object kinds on and off, the level meshes, and the collision of the level (model hulls,
   coloured by surface: orange solid and bullet-proof, yellow solid, blue camera / nav blockers).
6. **Check** builds the mod in a temporary folder and runs the checker: objects per section (the save format allows
   32,767), memory, box sizes, save safety, missing references, and placed cars (only 4 are drivable at once).

### Old saves keep working

Total Overdose saves address objects by the order the game creates them. The app therefore:

* appends new objects after every existing object of a block (it says which blocks can take new objects; a section
  whose last part is a shared prefab cannot, so walls go into the map layer, which is loaded with every section),
* by default "deletes" an object by retiring it: it stays, 5 km below the world, with its collision switched off
  (switch this in **Settings** if you really want it removed; removing breaks saves made in that section, and the
  checker says so).

These are the same export rules as the project's Unreal editor plugin (TODLevelEditor), so a level changed in either
tool is written the same way.

## Game data

The **New maps** tab saves map projects, places teleport entry boxes and named arrival spots, checks and builds the map package, and installs or removes it with a config backup. See **Adding a new map and its teleport spots** in the guide.

The **Game data** tab edits values the game keeps in its data: weapons (damage, clip size, fire rate, ranges, ammo),
vehicles (handling, health, cameras, traffic), loco moves and slow motion (power-up maxima, stamina costs, combo
awards) and the camera (player and vehicle camera position, camera types, draw distance). Changed values belong to
the current mod. Values that live in the game's code (field of view, slow-motion time scales) need proxy DLLs and are
listed, not edited.

## Saving, installing and sharing

* **Save mod** keeps the current mod in your library (`%APPDATA%\TODModStudio\mods`).
* **Mods** tab, **Save, check and build**: builds the override zip of the current mod and shows the checks.
* **Install enabled mods into the game**: every enabled mod, top to bottom, is built into one `todms_mods.zip` in
  the game folder and put first on the `filesystem =` line of `configpc.txt` (backup: `configpc.txt.todms_backup`).
  `blocks.naz` is never changed. **Remove all mods** deletes the zip and restores the line. Close the game first.
* **Share** writes a `.todmod` file (the recipe only, no game data). **Import** adds one to your library; it is built
  from your own game when you install it.

## Collision (new geometry that the game collides with)

The **Collision** tab turns a mesh of your own (.glb, .gltf or .obj) into Total Overdose collision. Use it for a
ruin wall, a ramp, rocks, or a new building.

1. **Pick a mesh file**. The file's size is shown.
2. Pick the map and the position in game coordinates. The Level editor's object panel shows the positions of
   objects; the ground height is the y of an object standing on the ground. Then set the turn and the scale.
3. Pick a **method**:
   - **Solid parts**, for closed meshes. A wall with a doorway gives two piers and a lintel, with the doorway open.
   - **Surface patches**, for open meshes and terrain.
   - **One convex hull**.
4. Pick a **surface material**. It sets the footstep sounds and bullet decals.
5. Pick a **collision** type:
   - solid stops Ram, people, bullets and the camera;
   - thin lets bullets pass;
   - the other types are untested in the game.
6. **Visual only** marks scenery without collision.

**Generate collision** splits the mesh into convex pieces. A piece has at most 255 vertices, the game's limit. The
pieces become a collision set of the current mod. **Check (build + verify)** builds them and runs the checks.
Building the mod writes them into the static collision of a model of that map, normally the terrain under them:
- the model's own checks pass: every other part of the block is unchanged and every model reads back;
- the model's bounding sphere grows when needed (the game only finds collision inside it);
- every piece is read back where you put it.

The Level editor shows the sets in green under Layers → **New collision**. **Frame the new collision** moves the
camera to them.

The Unreal TOD Level Editor plugin has the same generator (with Unreal's own decomposition as an extra method). The
two tools share their code, so a collision set built from a mod made in either one gives the same bytes.

## Routes (enemy paths, pedestrians, traffic, nav blockers)

The Routes tab draws a map's navigation data in 3D: enemy GotoPaths (orange) and patrols (pink), vehicle tracks
(brown), pedestrian SignPosts (green), traffic points (blue), NavBlock boxes (magenta) and Neighborhood circles
(purple). Arrows show the direction of travel; new points are bright green.

- Click a point to select it and drag the arrows to move it, or type a position. Shift-click a second SignPost to
  link or unlink the two (both ends are always changed together).
- **Insert after** puts a new point halfway to the next one, **Append** adds one after the last, **Remove** takes a
  point off its route, **Move up / down** changes the order in which it is walked.
- **Set a value**: TrackPoint speed, AI vehicle target speed (km/h), arrival slack (m), traffic lane radius (m),
  Neighborhood radius (m), NavBlock size and flags.
- **New NavBlock**: a box that NPC bodies and their avoidance steer around; Ram, bullets and the camera pass through.
- **Validate** lists dangling links, one-way pedestrian links, routes that run through your new collision (Collision
  tab), legs too steep to walk and points no spawn point can reach. **Check** builds the edit and reads it back with
  the route tool (navtool).

New points stay save-safe: they are added after every existing object of their block and linked to their route by
the object's creation number, the same way the game finds objects when it loads a save. A removed point is detached
from its route, never deleted. A section that ends with a shared prefab (the jungle sections) cannot take new
points; the mission blocks can.

## Missions (trigger graph)

The Missions tab shows a mission's triggers as cards: what makes each one fire (IF rows: the event and who causes
it) and what it does (DO rows: the action, its target and delay). Lines run from an action to the trigger it acts on.
Drag to pan, scroll to zoom; **Edited** shows only the triggers your mod changes.

- Click a card, an IF row or a DO row, then **Set** a value (event code, activator, action type, target, delay,
  re-arm).
- **Rewire to another trigger**: the action is then fired by the trigger you click next (same mission fragment).
- **Retarget**: the entity the action acts on. **Disable trigger**: it never fires until something enables it.
- **New trigger from a template**: go to a point, kill N enemies, timer, spawn a group, camera cut, objective text.
- **Check** builds the mission and runs the mission tool's lint before and after; only new problems are reported.

## Sections (loading zones between map sections)

The Sections tab draws the loading zones of a group of sections from above, with arrows to the other side's zone.
Seven shipped zones teleport the player (the Downtown-Harbour bridge, the Downtown-Industrial tunnel, the farm pass)
because their boxes stand in the wrong order for walking. **Fix teleport** empties both teleports and moves the box
past the other one (default gap 23 m), so the player keeps walking through the border. **Check** builds both
sections and classifies the zones again with the seamless-transition tool (they must read WALK). The split planner
only measures what a cut would divide; **Add section** records a new section (a copy of an existing one, registered
with the map, with a loading zone on each side) and checks it.

The route, mission and section edits are part of the mod (recipe version 3) and build into the same override zip as
everything else. The Unreal TOD Level Editor plugin has the same three tools and writes the same bytes.

## Assets (read only)

The **Assets** tab lists every Total Overdose model of your game:
- its maps and how often each map places it;
- the collision it carries;
- a thumbnail rendered from the game's own mesh (**Thumbnails for this page**);
- the Unreal replacement assigned in the Unreal plugin (Asset Replacements), its marker ("visual only" or "needs
  collision change") and its candidates.

The Unreal columns come from the current mod (a `.todmod` made in Unreal carries its rows). They can also come from an
Unreal project's `Config/TODBridge` folder, which you set under **Settings**. Mod Studio does not render Unreal assets:
the replacement pictures are the PNG files the Unreal plugin exports.

## Mods made in Unreal

A `.todmod` exported by the Unreal TOD Level Editor plugin (**Export as .todmod**) imports like any other mod and
shows "from Unreal" in the library. It carries:
- its level changes;
- its collision sets;
- its Unreal asset rows.

Mod Studio builds and installs it from your own game. The Unreal plugin opens Mod Studio's `.todmod` files as edits
(**Open .todmod as edits**). Recipes with collision sets or asset rows are format version 2. A Mod Studio build older than this one
imports them but ignores those sections, so share them with players who have this build or newer.

## Mission templates

The **Mission templates** tab turns 17 kinds of mission (showdown, ghost run, race, hold the zone, ...) into something you place on your own map.
Pick a kind, choose a host (a New maps project, or a section of an existing map such as Downtown), drop the mission giver box and each
point on the top view, adjust the numbers (every setting has a help line and its range), then **Check**, **Build** and **Install**. Open the sample
**Mesa Compound** (all 17 kinds; it uses all 17 slots) or the small yard sample to see the whole flow.

- One game install can have at most **17 new missions**, shared by everything you install. The page shows "N of 17 new mission slots left".
- All missions of one install are built together into ONE package, `todms_missions.zip`, first on the `filesystem =` line. The build runs on the
  archives the game really loads, so it works on top of Gameplay+ or TOD HD. The game reads at most 8 archives; the page refuses (with the count) when an install would pass 8.
- A new-map host is built into the mission package. Installing missions takes out a New maps package of the same map (it would be the same blocks twice); installing that package again is refused while the missions are installed.
- **Test save > Update a save for new missions** makes an updated COPY of a save (never in place, never automatic). Saves made before the install do not know the new missions: without the update, pressing the use key at a new giver closes the game. For a giver in an EXISTING section (Downtown, ...) the update also adds the box's script thread when the save holds that section; a save that does not hold it (end-of-game saves, saves at a mission start) shows the box only after the section has been reloaded once (any mission start or end, or a trip through a map loader). The page lists those cases after the update.
- The mission library is vendored (`scripts/vendor_missions.py [--check]`, hashes in `backend/vendor/MISSIONS.json`); it needs the new-map recipe vendor (`scripts/vendor_newmap.py`), which also supplies the single vendored submaptool and the CPU guard. Code: `backend/todms/missions_tpl.py`, `frontend/src/MissionTemplates.jsx`, tests `backend/tests/test_missions_tpl.py`.

## Test saves

**Test save here** (in the object panel) or the **Test save** tab: pick one of your saves, a spot and options (full
health, all weapons). The app writes a new save file and can install it as a slot of your choice; the slot it replaces
is backed up first.

## What it builds on

The app drives the TOD Project's game-data tools (fragment writer, level streaming, collision, model writer,
navigation, missions, weapons, vehicles, loco, camera, save editor), copied into the app with their source and versions
recorded (`backend/vendor/VENDOR.md`), and the companion-tools core shared with the Unreal plugin (`backend/todct`,
copied by `scripts/vendor_companion.py`, hashes in `backend/vendor/COMPANION.json`). Every build is verified by the tools' own checks before anything is written: the
untouched data stays byte-identical, only the intended values change, no references dangle, old save indices are
unchanged, and the zip is read back the way the game reads it.

## Building the app from source

```
cd frontend && npm install && npm run build          (UI into backend/web)
python -m venv .venv --system-site-packages
.venv\Scripts\pip install pyinstaller pywebview numpy        (numpy: the model writer the collision generator uses)
.venv\Scripts\python scripts\build_exe.py            (dist\TODModStudio\TODModStudio.exe)
.venv\Scripts\python scripts\build_setup.py          (dist\TODModStudio-Setup-<version>.exe, wraps the folder above)
```

Development: `python backend/main.py --server` and open http://127.0.0.1:8765 (or `npm run dev` in `frontend`).

## Licence

TOD Mod Studio's own code is licensed under the [GNU GPL v3](LICENSE). The app and its installer bundle third-party
software under its own licences (Python, numpy, pywebview, bottle, pythonnet, PyInstaller's bootloader, React,
three.js, react-three-fiber and drei); the list ships as `THIRD_PARTY_NOTICES.txt` in the release.
