# Vendored tools

Source: the author's TOD Project game-data tools (not included), copied by `scripts/vendor_tools.py`; per-file SHA-256 and source mtimes are in `VENDOR.json`.

Tables the tools derive from the game's own `database.bin` (`property_table.json`, `command_table.json`, `save_editor/data/global_properties.json`) are not part of the copy. `backend/tod_tables.py` rebuilds them on each user's machine from that user's `blocks.naz` and checks them against the block-header checksums; the tools find them through the `TOD_TABLES_DIR` environment variable.

## Local patches (paths only, no logic changes)

- `fragment_writer/fragtool.py`: database.bin-derived property table is read from TOD_TABLES_DIR (built per user)
- `fragment_writer/fragtool.py`: command table from TOD_TABLES_DIR
- `fragment_writer/fragtool.py`: independent reader (tod_fragment_decode) from the vendored copy instead of the Drive project
- `fragment_writer/todfrag.py`: property table from TOD_TABLES_DIR
- `missions/fragtool.py`: database.bin-derived property table is read from TOD_TABLES_DIR (built per user)
- `missions/fragtool.py`: command table from TOD_TABLES_DIR
- `missions/fragtool.py`: independent reader (tod_fragment_decode) from the vendored copy instead of the Drive project
- `missions/todfrag.py`: property table from TOD_TABLES_DIR
- `text/fragtool.py`: database.bin-derived property table is read from TOD_TABLES_DIR (built per user)
- `text/fragtool.py`: command table from TOD_TABLES_DIR
- `text/fragtool.py`: independent reader (tod_fragment_decode) from the vendored copy instead of the Drive project
- `text/todfrag.py`: property table from TOD_TABLES_DIR
- `missions/classreg.py`: property table from TOD_TABLES_DIR
- `missions/classreg.py`: command table from TOD_TABLES_DIR
- `missions/skel.py`: property table from TOD_TABLES_DIR
- `missions/skel.py`: command table from TOD_TABLES_DIR
- `save_editor/kfrag.py`: global property list from TOD_TABLES_DIR
- `save_editor/kmodel.py`: global property list from TOD_TABLES_DIR
- `level_streaming/submaptool.py`: sibling tools from the vendored copy
- `limits/limtool.py`: sibling tools from the vendored copy (PROJ/tools/...)

Comments and help text in 16 of the copied files were reworded by hand (wording only, no logic); after a re-vendor, re-read the copied files' comments for mentions of other tools and reword them the same way.

## Copies from TOD HD (`backend/vendor/hd`, record `hd/HD.json`)

- `hd/tod_hd_game.py`: copied unchanged from TOD HD's `app/tod_hd_game.py` (read only source). Used for the strict asset-block reader (`Block`), `texture_patches` and `rewrite_block` (texture replacement with a verified read-back). Imported by `todms/assetedit.py` and `todms/assets_stage.py`.
- `hd/tod_hd_lighting.py` and `hd/tod_hd_scatter.py`: copied unchanged from TOD HD's `app` folder (read only source). The baked-lighting record parser, key tables, record size pass and instance ownership (`tod_hd_scatter.walk_fragment` is its fragment walker). Imported by `todms/lightfit.py` (lighting phase 2 of replaced models); private helpers (`_parse_block`, `_masked`, `_check_order`) are used as they are, nothing is patched. HD's `retarget_counts` itself is not called: it matches mesh by index and takes per-vertex colours from the same mesh only, which does not fit the importer's own sub-meshes; `lightfit` reuses its parts instead.
- Not copied: `tod_hd_models.py`, `tod_hd_vegetation.py` (Mod Studio replaces models with its own `model_edit`/`model_writer`; their M6 numbers (bbox 110 %, 0.30 m below) are re-implemented in `todct/modelimport.py` and `todms/assets_stage.py`), `tod_hd_convert.py` (needs PIL; `todct/texture.py` is the numpy encoder).

## Local logic patch (wave 3)

- `save_editor/editlib.py` `start_mission(..., submap=None)`: the submap comes from the mission award's `Mission_SubMap` (what the engine loads), not from the list entry's `Mission_start_submap` (the award's `Mission_StartMap`; the two differ for missions 5, 8, 10, 18, 20, 23). `todms/saves.py` passes the award value.
