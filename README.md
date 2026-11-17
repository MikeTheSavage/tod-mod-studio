# TOD Mod Studio

A level and data editor for Total Overdose (2005). It runs on its own: you do not need Python or anything
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
Settings > Apps. Running a newer Setup updates the program and keeps your mods and settings. Setup also registers `.todmod`,
`.todcollection` and `.todpiece` for your user (no administrator rights): a double click opens Mod Studio and offers to add the file.
Silent use: `Setup.exe --silent [--dir D] [--desktop] [--no-startmenu]`,
`"Uninstall TOD Mod Studio.exe" --uninstall --silent [--restore-game] [--remove-backups] [--purge]`. The uninstaller window offers to put
the game back to its original files first (the same restore as **Restore to original**; it is skipped if you untick it, and the uninstall
stops if the game is running), to delete the backups Mod Studio made, and to delete your library and settings.

Without the installer: unzip `TODModStudio-win64.zip` anywhere and run `TODModStudio.exe`.

**Portable mode.** Put an empty file called `portable.txt` next to `TODModStudio.exe` (inside the unzipped `TODModStudio` folder) and the
mod library, settings, backups and cache are kept in a `data` folder beside it, so the whole folder can be carried on a stick. Packaging
step (not done by the build scripts): after `scripts\build_exe.py`, copy `dist\TODModStudio` to a new folder, add `portable.txt`, and zip
it. Without the file the program keeps its data in `%APPDATA%\TODModStudio` and `%LOCALAPPDATA%\TODModStudio` as before.

Windows 10 and 11 have the WebView2 runtime the window needs; on an old system, install "Microsoft Edge WebView2
Runtime" first (Setup warns when it is missing).

## Finding your way around

The window has a 44 px top bar (area title, the screens of the area, the mod's name with its unsaved-change count, **Save mod** and **New**),
a 64 px rail on the left with the areas, and a 28 px status bar (game folder, game running, what is installed, job progress, free mission slots).
The twelve old tabs are grouped like this:

| Area | Screens |
|---|---|
| Home | What do you want to do? (continue where you left off, start something) |
| World | Level editor, Routes, Sections, Collision, Mission logic |
| Create | Mission templates, New maps |
| Tune | Game data |
| Play | Mods and install, Test saves |
| Assets, Settings (bottom of the rail) | Asset catalogue, Settings (including the Dark / Light theme, remembered in the browser storage of the window) |

Everything that goes into the game uses one **Into the game** bar (Check, Build, Install, and a remove button that asks first). The look is
dark by default; the light theme is a switch in Settings. Both are CSS variables (`frontend/src/styles.css`), the same tokens as the approved design in
the design mock-ups. The side panels use two widths: 248 / 320 px, and 200 / 272 px below 1280 px window width (the layout is checked at 1600x960 and 1100x700).

## First run

1. The welcome screen asks for your Total Overdose folder: the one with `TOD.exe` and `blocks.naz` (GOG: `C:\GOG Games\Total Overdose`).
2. The app checks the game (it reads the game's own property tables and checks them against the game's checksums),
   lists the maps, sections and missions and extracts every map into its cache
   (`%LOCALAPPDATA%\TODModStudio\cache`, a few hundred MB) in the **One-time setup** step; you can continue while it runs, its progress stays in the
   status bar. Missions are extracted the first time you open them.
3. If TOD HD is installed in that folder, the app sees it and builds your mods on top of TOD HD's blocks.

## Making a level mod

1. **World > Level editor**: use the **Map**, **Section** and **Missions** menus in the top bar (a map or section opens at once; for missions,
   tick them and press **Open with these**) to get the mission objects (enemies, pickups, vehicles, routes).
2. Navigate: left drag orbits, right drag pans, the wheel zooms, W A S D Q E fly (Shift is faster), F frames the
   selected object.
3. Click an object (in the view or in the **Objects** list on the left, which has chips, a search box and an **Edit list**). The gizmo moves it (G), rotates it (R) or, for boxes,
   resizes it (T); **Select** shows no gizmo. The panel on the right edits its name, position, turn, size and pickup / weapon / vehicle
   type; **Advanced** holds the collision flags and, under **Show every property**, every value the object carries.
4. **+ Add** puts a new pickup, weapon, enemy, vehicle, trigger box, invisible wall, nav blocker or route point at the
   point in the middle of the view. **Duplicate** (Ctrl+D) copies the selected object, **Delete** removes it.
   Undo and redo: Ctrl+Z and Ctrl+Y.
5. **Layers** (a menu) switches object kinds on and off, the level meshes, and the collision of the level (model hulls,
   coloured by surface: orange solid and bullet-proof, yellow solid, blue camera / nav blockers).
6. **Check** (with a count of warnings and problems) builds the mod in a temporary folder and runs the checker: objects per section (the save format allows
   32,767), memory, box sizes, save safety, missing references, and placed cars (only 4 are drivable at once).

### Old saves keep working

Total Overdose saves address objects by the order the game creates them. The app therefore:

* appends new objects after every existing object of a block (it says which blocks can take new objects; a section
  whose last part is a shared prefab cannot, so walls go into the map layer, which is loaded with every section),
* by default "deletes" an object by retiring it: it stays, 5 km below the world, with its collision switched off
  (switch this in **Settings** if you really want it removed; removing breaks saves made in that section, and the
  checker says so).

## Game data

The **New maps** screen (Create) saves map projects, places teleport entry boxes and named arrival spots, checks and builds the map package, and installs or removes it with a config backup. See **Adding a new map and its teleport spots** in the guide.

The **Game data** screen (Tune) edits values the game keeps in its data: weapons (damage, clip size, fire rate, ranges, ammo),
vehicles (handling, health, cameras, traffic), loco moves and slow motion (power-up maxima, stamina costs, combo
awards) and the camera (player and vehicle camera position, camera types, draw distance). It shows weapons and vehicles as a table (one row each) with an inspector of sliders on the right (wide windows), a **Find** box and an **Only changed** filter.
Changed values belong to the current mod. Values that live in the game's code (field of view, slow-motion time scales) need proxy DLLs and are
listed, not edited.

## Saving, installing and sharing

* **Save mod** keeps the current mod in your library (`%APPDATA%\TODModStudio\mods`).
* **Play > Mods and install**, **Save, check and build**: builds the override zip of the current mod and shows the checks. The list has switches, drag-to-reorder and a
  menu per mod; **In the game now** on the right lists installed mods, new maps and mission packages (each with a **Remove**).
* **Install enabled mods into the game** (the Into the game bar): every enabled mod, top to bottom, is built into one `todms_mods.zip` in
  the game folder and put first on the `filesystem =` line of `configpc.txt` (backup: `configpc.txt.todms_backup`).
  `blocks.naz` is never changed. **Remove all mods** (after a confirmation dialog) deletes the zip and restores the line. Close the game first.
* **Share** writes a `.todmod` file (the recipe only, no game data) for the selected mod, a `.todcollection` for the switched-on mods
  with their order, or a `.todpiece` for one prefab, route set, tuning preset or mission. **Import** adds any of them to your library;
  every file is checked first (see Sharing recipes) and is built from your own game when you install it.
* **Load order.** The list is the load order: a mod lower in the list wins when two mods set the same thing. Different values in the same
  file (two mods that tune different weapon values, or move different objects) both apply. **Conflicts** (above the list) shows every
  clash with the values and the winner, and the install asks before it goes ahead.
* **Profiles.** The profile menu keeps named lists of switched-on mods with their order. Switching copies your saves first and rebuilds the
  game from the other list.
* **Needs.** A mod can need Gameplay+ (or the original game only), a lowest Mod Studio version, or other mods by version. The install
  refuses a mod whose needs are not met and says which.
* **Mod page.** Version, credits, licence, whether others may reuse or edit it, what it needs, a changelog and up to six pictures (the
  **Capture** button in the level editor takes one of the 3D view). Importing a newer version of a mod you have updates it in place and
  keeps its place in the list.
* **Community.** The Community view reads a list from the address you set in Settings. Nothing goes online until you turn on **Allow
  online features** and type an address (both empty by default; no host is built in). A download is only added when its fingerprint
  matches, and it passes the same safety check as any file.
* **Updates.** With online features on and an update address set, **Check now** (or the start-up check, off by default) shows the new
  version and what changed; the download is checked against its fingerprint and the setup runs only after you confirm.
* **Report a problem** (Settings) writes the support bundle and a text file of your words into a folder for you to send yourself. Nothing
  is sent.

## Collision (new geometry that the game collides with)

The **Collision** screen turns a mesh of your own (.glb, .gltf or .obj) into Total Overdose collision. Use it for a
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

## Routes (enemy paths, pedestrians, traffic, nav blockers)

The Routes screen draws a map's navigation data in 3D: enemy GotoPaths (orange) and patrols (pink), vehicle tracks
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

The Mission logic screen shows a mission's triggers as cards: what makes each one fire (IF rows: the event and who causes
it) and what it does (DO rows: the action, its target and delay). Lines run from an action to the trigger it acts on.
Drag to pan, scroll to zoom; **Edited** shows only the triggers your mod changes.

- Click a card, an IF row or a DO row, then **Set** a value (event code, activator, action type, target, delay,
  re-arm).
- **Rewire to another trigger**: the action is then fired by the trigger you click next (same mission fragment).
- **Retarget**: the entity the action acts on. **Disable trigger**: it never fires until something enables it.
- **New trigger from a template**: go to a point, kill N enemies, timer, spawn a group, camera cut, objective text.
- **Check** builds the mission and runs the mission tool's lint before and after; only new problems are reported.

## Sections (loading zones between map sections)

The Sections screen draws the loading zones of a group of sections from above, with arrows to the other side's zone.
Seven shipped zones teleport the player (the Downtown-Harbour bridge, the Downtown-Industrial tunnel, the farm pass)
because their boxes stand in the wrong order for walking. **Fix teleport** empties both teleports and moves the box
past the other one (default gap 23 m), so the player keeps walking through the border. **Check** builds both
sections and classifies the zones again with the seamless-transition tool (they must read WALK). The split planner
only measures what a cut would divide; **Add section** records a new section (a copy of an existing one, registered
with the map, with a loading zone on each side) and checks it.

The route, mission and section edits are part of the mod (recipe version 3) and build into the same override zip as
everything else.

## Models (read only)

The **Asset catalogue** screen lists every Total Overdose model of your game:
- its maps and how often each map places it;
- the collision it carries;
- a thumbnail rendered from the game's own mesh (**Thumbnails for this page**).

## Sharing recipes

A `.todmod` is a recipe: a list of your changes, never game files. Mod Studio builds and installs it from your own
game. Recipes with collision sets are format version 2; with route, mission or section edits, version 3. A Mod Studio
build older than the recipe imports it but ignores the newer sections, so share it with players who have this build or
newer. Recipes written by older builds import as before; any model-replacement rows in them are ignored.

Older recipes are upgraded when they are opened: a backup copy of the file goes to `migration_backups` in your data folder first, and the
file you opened is never changed. A recipe from a newer Mod Studio is refused with a plain message.

**Safety check.** A mod file holds recipes and pictures, never code. Before anything is added the file is checked and refused if it holds
a program or script, a path that points outside the game data, an entry mods do not have, an embedded file that is not a picture or model
scene (or is much larger than it says), or a package with anything but the mod and its pictures. A file from a download site may also be
a zip with `mod.json` and `screenshots`; the same rules apply.

**Supported games.** Settings says which game it found: the GOG build in English is fully supported; other builds and languages are
data-only (new text is written for English only) and untested.

## Mission templates

The **Mission templates** screen (Create) turns 17 kinds of mission (showdown, ghost run, race, hold the zone, ...) into something you place on your own map.
Pick a kind on the card page, choose a host (a New maps project, or a section of an existing map such as Downtown), drop the mission giver box and each
point on the top view, adjust the numbers (every setting has a help line and its range), then **Check**, **Build** and **Install into the game** in the Into the game bar. Open the sample
**Mesa Compound** (all 17 kinds; it uses all 17 slots) or the small yard sample to see the whole flow.

- One game install can have at most **17 new missions**, shared by everything you install. The status bar shows "N of 17 new mission slots left".
- All missions of one install are built together into ONE package, `todms_missions.zip`, first on the `filesystem =` line. The build runs on the
  archives the game really loads, so it works on top of Gameplay+ or TOD HD. The game reads at most 8 archives; the page refuses (with the count) when an install would pass 8.
- A new-map host is built into the mission package. Installing missions takes out a New maps package of the same map (it would be the same blocks twice); installing that package again is refused while the missions are installed.
- **Test saves > Update a save for new missions** makes an updated COPY of a save (never in place, never automatic). Saves made before the install do not know the new missions: without the update, pressing the use key at a new giver closes the game. For a giver in an EXISTING section (Downtown, ...) the update also adds the box's script thread when the save holds that section; a save that does not hold it (end-of-game saves, saves at a mission start) shows the box only after the section has been reloaded once (any mission start or end, or a trip through a map loader). The page lists those cases after the update.
- The mission library is vendored (`scripts/vendor_missions.py [--check]`, hashes in `backend/vendor/MISSIONS.json`); it needs the new-map recipe vendor (`scripts/vendor_newmap.py`), which also supplies the single vendored submaptool and the CPU guard. Code: `backend/todms/missions_tpl.py`, `frontend/src/MissionTemplates.jsx`, tests `backend/tests/test_missions_tpl.py`.

## Test saves

**Start a test save here** (in the object panel) or the **Test saves** screen (Play): pick one of your saves, a spot and options (full
health, all weapons). The app writes a new save file and can install it as a slot of your choice; the slot it replaces
is backed up first.

## What it builds on

The app drives the TOD Project's game-data tools (fragment writer, level streaming, collision, model writer,
navigation, missions, weapons, vehicles, loco, camera, save editor), copied into the app with their source and versions
recorded (`backend/vendor/VENDOR.md`), and the companion-tools core (`backend/todct`, edited here like the rest of `backend/todms`). Every build is verified by the tools' own checks before anything is written: the
untouched data stays byte-identical, only the intended values change, no references dangle, old save indices are
unchanged, and the zip is read back the way the game reads it.

## Third-party components

* IBM Plex Sans and IBM Plex Mono (the interface fonts), Copyright 2019 IBM Corp., licensed under the SIL Open Font License 1.1. The font files are bundled
  (`frontend/src/fonts`, npm packages `@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono` 5.x) so the app works offline and never loads fonts from the web.
  The licence texts are in `frontend/src/fonts/OFL-ibm-plex-sans.txt` and `OFL-ibm-plex-mono.txt`, and ship with the app in `licenses/` next to the web files.
* React, three.js, @react-three/fiber and @react-three/drei (MIT), bundled into the web UI; pywebview (BSD) and PyInstaller (GPL with the bootloader exception) for the window and
  the packaged program.

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
