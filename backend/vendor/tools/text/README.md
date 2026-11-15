# tools/text: TOD text and localisation

Read every string of every language, change and add strings, and package them the way TOD.exe loads them.
Format, engine functions, limits and in-game tests: `docs/subsystem_text.md`.

```
set PY=C:\Path\To\Python312\python.exe
%PY% textool.py list --langs uk,fr                 TEXT assets per language block
%PY% textool.py export -o OUTDIR                   strings_<lang>.tsv / .json for uk de fr es it (id = file#ordinal)
%PY% textool.py roundtrip                          75 assets / 10 blocks byte-identical, new-tree encode decodes back
%PY% textool.py find "paused"                      ids of strings containing a text
%PY% textool.py glyphs --lang de                   characters the fonts cannot draw
%PY% textool.py refs -o refs.csv                   every fragment property that stores a string ordinal (about 5 min)
%PY% textool.py names -o names.csv                 missions, weapons, stunts, power-ups, vehicles, taxi points
%PY% textool.py subtitles -o subs.csv              every subtitle line with on/off times and its uk_Dialog id
%PY% textool.py exe-strings                        the RT_STRING error dialogs in TOD.exe
%PY% textool.py edit edits\P1_markers.json --out OUTDIR [--deploy TESTGAME]
```

Edit file: see the docstring of `textool.py` and `edits/`. Operations per entry: `value`, `prefix`, `suffix`, `key`
(with `ordinal`), lookup by `key`, `ordinal` as a list, `append`; `langs` picks the language blocks;
`fragment_ops` (fragment writer ops on a shared block) points fragments at new ordinals.

Output of `edit`: the rebuilt block(s), `text_override.zip` (STORED), `configpc_line.txt`
(`filesystem = text_override.zip, blocks.naz, sounds.naz, videos00.naz, videos01.naz`), `report.json`.
Nothing is written unless every check passes. `--deploy` copies only the zip, refuses the GOG folder
and refuses while TOD.exe runs.

Files: `textool.py` (CLI), `texlib.py` (TEXT codec), `fontlib.py` (glyph tables), `peres.py` (exe string table),
`todblock.py` (archives and blocks), `fragtool.py` + `fragedit.py` + `todfrag.py` + `*.json` (fragment writer,
copied from `tools/fragment_writer`), `lowprio.py` (below-normal priority).
The tool reads `C:\GOG Games\Total Overdose\blocks.naz` read-only (or `--naz FILE`, or env `TOD_NAZ`).
