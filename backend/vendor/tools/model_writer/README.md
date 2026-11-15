# tools/model_writer

TOD (Kapow) MODEL records read and written byte for byte, prop collision edits and whole new models.
Doc: `docs/subsystem_model_writer.md`. The lab with the builds and pictures is the author's (not included).
Python 3.12 (run with `-I`), numpy, PIL.
Read-only on `C:\GOG Games\Total Overdose\blocks.naz` (default `--naz`).

| File | Use |
|---|---|
| `todmodel.py` | codec: `decode(info, R, E)`, `encode(tree)`, `pointer_fields(record)` |
| `model_writer.py` | spec layer + writer with derived bounds; mesh, skin and collision helpers |
| `model_edit.py` | edit a model in blocks (edit JSON) and package `model_override.zip` (nothing is deployed) |
| `model_info.py` | pivot walker report (`--layout` = every allocation) |
| `placed.py` | placed models near a world point |
| `render_model.py`, `test_area.py` | proof pictures |
| `model_roundtrip.py` | 2,718/2,718 records byte-identical |
| `model_roundtrip_strict.py` | zero-pad re-encode: same layout and semantics |
| `writer_roundtrip.py` | rebuild every model from its semantic description |
| `edit_stress.py` | 7,362 synthetic collision edits checked |
| `edits/*.json` | the four in-game test edits (tree on the Map02 plaza) |
| `todblock.py`, `todcoll.py`, `export_map.py`, `near.py`, `proj/` | copies from `tools/collision` |

Quick start:

```
python -I model_info.py <block file> VEG_Tree_Scruffy_Small --layout
python -I model_edit.py --edit edits/a_tree_trunk_removed.json --out <out dir>
```
