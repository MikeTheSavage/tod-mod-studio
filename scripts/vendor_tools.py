"""Copy the project's game-data tools into backend/vendor/tools (read only on the source).

  python scripts/vendor_tools.py [--src TOOLS_DIR]      (default: env TOD_PROJECT_TOOLS)

Copies only code and the tool tables the code loads; skips research folders (evidence, analysis, re, out, examples,
edits, proxy sources), caches and Drive metadata. Writes backend/vendor/VENDOR.json with the source path, the copy
time and the SHA-256 and source mtime of every file, so a later re-vendor can be diffed.
Tables that the tools derive from the game's own database.bin are NOT kept in the copy: tod_tables.py rebuilds them
on the user's machine from the user's blocks.naz (see backend/tod_tables.py).
"""
import argparse, datetime, hashlib, json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, 'backend', 'vendor', 'tools')
FOLDERS = ['fragment_writer', 'model_writer', 'collision', 'navigation', 'missions', 'level_streaming', 'save_editor',
           'limits', 'weapons', 'vehicles', 'loco', 'camera', 'movement', 'sound', 'text', 'vfx', 'memory_pools']
TOP = ['tod_model_extract.py', 'tod_model_to_gltf.py', 'tod_static_textured.py', 'tod_dds.py', 'tod_texture_extract.py',
       'tod_char_anim_extract.py', 'tod_anim_extract.py', 'tod_anim_remap.py', 'tod_fragment_decode.py',
       'tod_block_fragment_recover.py', 'tod_validated_texture_aliases.py', 'tod_extract_level.py']
SKIP_DIRS = {'__pycache__', 'evidence', 'analysis', 're', 'out', 'examples', 'edits', 'proxy', 'ingame_proxy', 'extract'}
SKIP_FILES = {'desktop.ini'}
KEEP_EXT = {'.py', '.json', '.tsv', '.md', '.ini', '.txt'}
# tables derived from database.bin (rebuilt per user) or bulky research output: not shipped
DROP = {'fragment_writer/property_table.json', 'fragment_writer/command_table.json',
        'missions/property_table.json', 'missions/command_table.json',
        'text/property_table.json', 'text/command_table.json',
        'save_editor/data/global_properties.json',
        'fragment_writer/regcalls.json',             # proof input (decompile scan), not needed at run time
        'limits/selftest_20261020.txt',
        'level_streaming/data/census.json', 'level_streaming/data/graph.json',
        'level_streaming/data/census_maps_submaps.json'}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.environ.get('TOD_PROJECT_TOOLS', ''),
                    help="the author's TOD Project tools folder (not included); default: env TOD_PROJECT_TOOLS")
    a = ap.parse_args()
    if not a.src or not os.path.isdir(a.src):
        ap.error('--src (or env TOD_PROJECT_TOOLS) must name the TOD Project tools folder')
    if os.path.exists(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)
    files = {}
    def take(rel):
        s = os.path.join(a.src, rel)
        d = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        files[rel.replace('\\', '/')] = dict(sha256=sha(d), bytes=os.path.getsize(d),
                                            source_mtime=datetime.datetime.fromtimestamp(os.path.getmtime(s)).isoformat(timespec='seconds'))
    for f in TOP:
        take(f)
    for fo in FOLDERS:
        for dp, dns, fns in os.walk(os.path.join(a.src, fo)):
            dns[:] = [x for x in dns if x not in SKIP_DIRS]
            for fn in fns:
                rel = os.path.relpath(os.path.join(dp, fn), a.src).replace('\\', '/')
                if fn in SKIP_FILES or os.path.splitext(fn)[1].lower() not in KEEP_EXT or rel in DROP:
                    continue
                take(rel)
    meta = dict(source=a.src, copied=datetime.datetime.now().isoformat(timespec='seconds'),
                note='Vendored copy of the TOD Project game-data tools. Local patches are listed in VENDOR.md; '
                     'database.bin-derived tables are rebuilt per user by backend/tod_tables.py.',
                dropped=sorted(DROP), files=files)
    json.dump(meta, open(os.path.join(os.path.dirname(DST), 'VENDOR.json'), 'w'), indent=1)
    print('vendored %d files, %.1f KB' % (len(files), sum(v['bytes'] for v in files.values()) / 1024))


if __name__ == '__main__':
    sys.exit(main())
