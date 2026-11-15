"""Local patches applied to the vendored tool copy (backend/vendor/tools) after scripts/vendor_tools.py.

Every patch only changes WHERE a tool looks for its tables or sibling modules; no logic is changed. Each patch must
match exactly once or the script stops (so a changed upstream file is noticed). The list is written to VENDOR.md.
"""
import os, posixpath, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(ROOT, 'backend', 'vendor', 'tools')
TBL = "os.environ.get('TOD_TABLES_DIR') or "
# The tools path exactly as the upstream sources write it (a Windows path with backslashes). The patches that rewrite
# that path need it; when it is unset they are skipped (with a printed note) and every other patch still applies.
UPSTREAM = os.environ.get('TOD_UPSTREAM_TOOLS_PATH', '')
UPSTREAM_PROJ = posixpath.dirname(UPSTREAM.replace('\\', '/').rstrip('/')) if UPSTREAM else ''   # its parent, with /
SKIPPED = []

PATCHES = []
for fo in ('fragment_writer', 'missions', 'text'):
    for fn in ('fragtool.py',):
        PATCHES += [
            (f'{fo}/{fn}', "json.load(open(os.path.join(HERE, 'property_table.json')))",
             "json.load(open(os.path.join(" + TBL + "HERE, 'property_table.json')))", 2,
             'database.bin-derived property table is read from TOD_TABLES_DIR (built per user)'),
            (f'{fo}/{fn}', "json.load(open(os.path.join(HERE, 'command_table.json')))",
             "json.load(open(os.path.join(" + TBL + "HERE, 'command_table.json')))", 2,
             'command table from TOD_TABLES_DIR'),
        ]
        (PATCHES if UPSTREAM else SKIPPED).append(
            (f'{fo}/{fn}', "sys.path.insert(0, r'" + UPSTREAM + "')",
             "sys.path.insert(0, os.path.dirname(HERE))", 1,
             'independent reader (tod_fragment_decode) from the vendored copy instead of the Drive project'))
    PATCHES.append((f'{fo}/todfrag.py', "os.path.join(HERE, 'property_table.json')",
                    "os.path.join(" + TBL + "HERE, 'property_table.json')", 1, 'property table from TOD_TABLES_DIR'))
for fn in ('classreg.py', 'skel.py'):
    PATCHES += [(f'missions/{fn}', "os.path.join(HERE, 'property_table.json')",
                 "os.path.join(" + TBL + "HERE, 'property_table.json')", 1, 'property table from TOD_TABLES_DIR'),
                (f'missions/{fn}', "os.path.join(HERE, 'command_table.json')",
                 "os.path.join(" + TBL + "HERE, 'command_table.json')", 1, 'command table from TOD_TABLES_DIR')]
PATCHES += [
    ('save_editor/kfrag.py', "os.path.join(HERE, 'data', 'global_properties.json')",
     "os.path.join(" + TBL + "os.path.join(HERE, 'data'), 'global_properties.json')", 1,
     'global property list from TOD_TABLES_DIR'),
    ('save_editor/kmodel.py', "os.path.join(D, 'global_properties.json')",
     "os.path.join(" + TBL + "D, 'global_properties.json')", 1, 'global property list from TOD_TABLES_DIR'),
]
(PATCHES if UPSTREAM else SKIPPED).extend([
    ('level_streaming/submaptool.py', 'PROJ_TOOLS = r"' + UPSTREAM + '"',
     'PROJ_TOOLS = os.path.dirname(HERE)', 1, 'sibling tools from the vendored copy'),
    ('limits/limtool.py', "PROJ = os.environ.get('TOD_PROJECT', r'" + UPSTREAM_PROJ + "')",
     "PROJ = os.environ.get('TOD_PROJECT', os.path.dirname(os.path.dirname(HERE)))", 1,
     'sibling tools from the vendored copy (PROJ/tools/...)'),
])


def main():
    if SKIPPED:
        print('note: TOD_UPSTREAM_TOOLS_PATH is not set; skipping %d tools-path patches:' % len(SKIPPED))
        for rel, _old, _new, _count, why in SKIPPED:
            print('  - %s: %s' % (rel, why))
    done = []
    for rel, old, new, count, why in PATCHES:
        p = os.path.join(V, rel)
        s = open(p, encoding='utf-8').read()
        n = s.count(old)
        if n != count:
            sys.exit('patch %s: expected %d match(es), found %d: %s' % (rel, count, n, old))
        open(p, 'w', encoding='utf-8', newline='').write(s.replace(old, new))
        done.append((rel, why))
    # limtool expects PROJ/tools/<tool>: provide that layout by pointing PROJ at a folder that contains tools/
    lines = ['# Vendored tools', '',
             'Source: the author\'s TOD Project game-data tools (not included), copied by '
             '`scripts/vendor_tools.py`; per-file SHA-256 and source mtimes are in `VENDOR.json`.', '',
             'Tables the tools derive from the game\'s own `database.bin` (`property_table.json`, `command_table.json`, '
             '`save_editor/data/global_properties.json`) are not part of the copy. `backend/tod_tables.py` rebuilds '
             'them on each user\'s machine from that user\'s `blocks.naz` and checks them against the block-header '
             'checksums; the tools find them through the `TOD_TABLES_DIR` environment variable.', '',
             '## Local patches (paths only, no logic changes)', '']
    for rel, why in done:
        lines.append('- `%s`: %s' % (rel, why))
    open(os.path.join(os.path.dirname(V), 'VENDOR.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('applied %d patches' % len(done))


if __name__ == '__main__':
    main()
