"""Vendor the new-map recipe and its local Python dependency closure; --check compares without writing.

TOD_NEWMAP_SRC overrides the read-only recipe tools directory. Identical modules already shipped in
vendor/tools are reused. Different modules are copied verbatim under vendor/newmap.

ONE submaptool: the recipe's copy (it has clone_of_file, which new-geometry maps and the mission templates need) is the
only vendored submaptool. It replaces vendor/tools/level_streaming/submaptool.py with the same one-line path patch that
scripts/patch_vendor.py applies. Re-vendoring order: vendor_tools.py, patch_vendor.py, vendor_newmap.py, vendor_missions.py.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get('TOD_NEWMAP_SRC', '') or '/no-newmap-source')
DST = ROOT / 'backend/vendor/newmap'
TOOLS = ROOT / 'backend/vendor/tools'
REC = ROOT / 'backend/vendor/NEWMAP.json'
SUBMAPTOOL = 'level_streaming/submaptool.py'
# the tools path exactly as the upstream sources write it; unset: the path patch is skipped
UPSTREAM = os.environ.get('TOD_UPSTREAM_TOOLS_PATH', '')
PATH_PATCH = ('PROJ_TOOLS = r"' + UPSTREAM + '"', 'PROJ_TOOLS = os.path.dirname(HERE)') if UPSTREAM else None


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wanted_bytes(rel, p):
    data = p.read_bytes()
    if rel == SUBMAPTOOL and PATH_PATCH:
        old, new = (x.encode() for x in PATH_PATCH)
        if data.count(old) != 1:
            raise SystemExit('submaptool: the sibling-tools path line changed upstream')
        data = data.replace(old, new)
    return data


# Mod Studio owns make_new_map.py since wave 3 (backend/todms/newmap_recipe): it is walked for its imports but not vendored.
# fragment_writer/todblock.py carries the record-scan guard (a name pointer must start a string) in every vendored copy of the block reader.
FORKED = ('make_new_map.py', 'fragment_writer/todblock.py')


def dependencies():
    search = [SRC, SRC / 'level_streaming', SRC / 'fragment_writer', SRC / 'save_editor']
    pending, found = [SRC / 'make_new_map.py'], {}
    while pending:
        p = pending.pop()
        rel = p.relative_to(SRC).as_posix()
        if rel in found:
            continue
        found[rel] = p
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8-sig'))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for name in names:
                for folder in search:
                    candidate = folder / (name.split('.')[0] + '.py')
                    if candidate.is_file():
                        pending.append(candidate)
                        break
    return {k: v for k, v in found.items() if k not in FORKED}


def main():
    check = '--check' in sys.argv
    found = dependencies()
    records = {}
    for rel, p in sorted(found.items()):
        shared = TOOLS / rel
        data = wanted_bytes(rel, p)
        sha = hashlib.sha256(data).hexdigest()
        reuse = shared.is_file() and digest(shared) == sha
        dest = shared if (reuse or rel == SUBMAPTOOL) else DST / rel
        records[rel] = dict(sha256=sha, destination=dest.relative_to(ROOT / 'backend').as_posix())
        if not check:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not reuse:
                dest.write_bytes(data)
    if check:
        old = json.loads(REC.read_text())
        bad = [rel for rel, r in records.items() if not (ROOT / 'backend' / r['destination']).is_file()
               or digest(ROOT / 'backend' / r['destination']) != r['sha256']]
        if records != old['files']:
            bad.append('source/dependency list')
        print('differs: ' + ', '.join(bad) if bad else 'new-map recipe in step')
        return int(bool(bad))
    REC.write_text(json.dumps(dict(source=str(SRC), files=records), indent=1) + '\n')
    print('vendored new-map recipe: %d modules' % len(records))
    return 0


if __name__ == '__main__':
    sys.exit(main())
