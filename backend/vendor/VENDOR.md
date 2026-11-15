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
