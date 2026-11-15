r"""Vendor the mission template library; --check compares without writing.

Source (read only, never edited from here): the author's new_content/missions/templates work folder, not included (env TOD_MISSIONS_SRC).
Copies the package (tpl_*.py + types/*.py) as backend/vendor/missions/todtpl, the save migrator and the sample projects, and
records SHA-256 hashes in backend/vendor/MISSIONS.json. The library's tool chain is NOT copied here: it runs on Mod Studio's own
vendored tools (text tool and mission linter in vendor/tools) and on the new-map recipe (scripts/vendor_newmap.py, which also
supplies base_overlay.py and cpu_guard.py). Order after a source change: vendor_newmap.py, vendor_missions.py.
If a library fix is needed, make it in the source folders, run the library tests, then re-vendor.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ENV = os.environ.get('TOD_MISSIONS_SRC', '')
SRC = Path(SRC_ENV)
DST = ROOT / 'backend/vendor/missions'
REC = ROOT / 'backend/vendor/MISSIONS.json'


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wanted():
    """{relative destination under backend/vendor/missions: source path}"""
    out = {}
    for p in sorted(SRC.glob('*.py')):
        if p.name in ('build_cli.py',):
            continue
        out['todtpl/' + p.name] = p
    for p in sorted((SRC / 'types').glob('*.py')):
        out['todtpl/types/' + p.name] = p
    for p in sorted((SRC / 'data').glob('*.json')):          # edit recipes (no game bytes): the shipped-block variants are made from the player's own blocks
        out['todtpl/data/' + p.name] = p
    out['migrate_save.py'] = SRC.parent / 'types' / 'migrate_save.py'
    for name in ('mesa_compound.json', 'second_map_ghost_showdown.json', 'second_map_params.json', 'existing_host_downtown.json'):
        out['samples/' + name] = SRC / 'samples' / name
    out['samples/mesa_map.json'] = SRC.parent.parent / 'maps' / 'params' / 'N11_final.json'
    return out


def main():
    check = '--check' in sys.argv
    if not SRC_ENV or not SRC.is_dir():
        print('set TOD_MISSIONS_SRC to the mission template library folder')
        return 1
    files = wanted()
    missing = [str(s) for s in files.values() if not s.is_file()]
    if missing:
        print('missing source files: ' + ', '.join(missing))
        return 1
    records = {rel: dict(sha256=digest(src)) for rel, src in sorted(files.items())}
    if check:
        old = json.loads(REC.read_text())
        bad = [rel for rel, r in records.items() if not (DST / rel).is_file() or digest(DST / rel) != r['sha256']]
        if records != old['files']:
            bad.append('source file list')
        extra = [p.relative_to(DST).as_posix() for p in DST.rglob('*') if p.is_file() and p.relative_to(DST).as_posix() not in records
                 and '__pycache__' not in p.parts]
        bad += ['unexpected ' + e for e in extra]
        print('differs: ' + ', '.join(bad) if bad else 'mission template library in step')
        return int(bool(bad))
    if DST.exists():
        shutil.rmtree(DST)
    for rel, src in files.items():
        (DST / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, DST / rel)
    REC.write_text(json.dumps(dict(source=str(SRC), files=records), indent=1) + '\n')
    print('vendored mission template library: %d files' % len(records))
    return 0


if __name__ == '__main__':
    sys.exit(main())
