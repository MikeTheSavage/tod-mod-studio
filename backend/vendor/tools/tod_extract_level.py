#!/usr/bin/env python3
"""
TOD level-layout extractor (driver).

Given a .submap / .mission / .map block, this:
  1. runs restools `<type> <path> dumpdata` to dump every FRAGMENT's raw bytes,
  2. decodes each fragment into its entity graph (via tod_fragment_decode),
  3. merges them into one level JSON (entities with type, parent, transform, props),
  4. cleans up the files restools dumped into the game folder.

restools chdir's into the input folder and writes dumps there (basename only), so we
snapshot the folder, collect the new files, then remove them afterwards.

Usage:
  py tod_extract_level.py <block_base_path_without_ext> <type> [-o out.json]
      type in {submap, mission, map, asset, playerdata}
  (properties.dump is auto-located next to database.bin under .../scripts/stable/)
"""
import sys, os, json, subprocess, argparse, glob, re, time
import tod_fragment_decode as frag

THIS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RESTOOLS = os.path.join(os.path.dirname(THIS), 'restools.exe')

def find_properties_dump(block_path):
    # walk up to the install root, look for scripts/stable/properties.dump
    d = os.path.dirname(os.path.abspath(block_path))
    for _ in range(12):
        cand = os.path.join(d, 'scripts', 'stable', 'properties.dump')
        if os.path.isfile(cand):
            return cand
        for hit in glob.glob(os.path.join(d, '**', 'properties.dump'), recursive=False):
            return hit
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('block', help='block base path WITHOUT extension (restools convention)')
    ap.add_argument('type', choices=['submap', 'mission', 'map', 'asset', 'playerdata'])
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--restools', default=DEFAULT_RESTOOLS)
    ap.add_argument('--properties', default=None)
    ap.add_argument('--no-properties', action='store_true',
                    help="emit builtin#N property keys (skip name resolution). The UE populator is validated "
                         "against builtin#N (builtin#38=model, #15=name, #415/#417=light, #241/#242/#69=collision); "
                         "name resolution via properties.dump is unreliable for some types (e.g. Light color/radius "
                         "get mis-labeled), so the import pipeline standardizes on builtin#N.")
    ap.add_argument('--keep-dumps', action='store_true', help='do not delete dumped files')
    ap.add_argument('--timeout', type=float, default=None,
                    help='kill restools after N seconds (some maps hang restools); decode fragments dumped so far')
    args = ap.parse_args()

    folder = os.path.dirname(os.path.abspath(args.block))
    props_path = None if args.no_properties else (args.properties or find_properties_dump(args.block))
    props = frag.load_properties(props_path, 711) if props_path else {}
    if not props_path and not args.no_properties:
        print('WARNING: properties.dump not found; named properties will be unresolved.')

    start = time.time() - 2  # tolerate clock skew
    print('running restools %s ... (timeout=%s)' % (args.type, args.timeout))
    try:
        proc = subprocess.run([args.restools, args.type, args.block, 'dumpdata'],
                              capture_output=True, text=True, timeout=args.timeout)
        log = (proc.stdout or '') + (proc.stderr or '')
    except subprocess.TimeoutExpired as e:
        # some maps (e.g. map02 downtown) hang restools mid-parse; it never exits. Decode whatever
        # FRAGMENT files were dumped before the timeout rather than blocking forever.
        log = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or '')) + \
              (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ''))
        print('WARNING: restools timed out after %ss and was killed; decoding fragments dumped so far' % args.timeout)

    # fragment basenames come from the log: a "Type: FRAGMENT" block followed by its Path.
    frag_files, pending = [], False
    for line in log.splitlines():
        s = line.strip()
        if s == 'Type:\tFRAGMENT' or s.replace(' ', '') == 'Type:FRAGMENT':
            pending = True
        elif pending and s.startswith('Path:'):
            m = re.search(r'"([^"]+)"', s)
            if m:
                frag_files.append(os.path.basename(m.group(1).replace('\\', '/')))
            pending = False
    # de-dup, preserve order
    seen = set(); frag_files = [f for f in frag_files if not (f in seen or seen.add(f))]
    print('restools reported %d fragments' % len(frag_files))
    # files restools actually wrote this run (mtime-based), for cleanup
    new_files = [f for f in os.listdir(folder)
                 if os.path.getmtime(os.path.join(folder, f)) >= start]

    level = {'block': os.path.basename(args.block), 'type': args.type,
             'fragments': [], 'totals': {'entities': 0}}
    try:
        for ff in frag_files:
            path = os.path.join(folder, ff)
            with open(path, 'rb') as fh:
                blob = fh.read()
            ops, stats = frag.decode_fragment(blob, props)
            entities = frag.build_entities(ops)
            level['fragments'].append({'name': ff, 'stats': stats,
                                       'entityCount': len(entities),
                                       'entities': entities})
            level['totals']['entities'] += len(entities)
            print('  %-52s %5d entities  resyncs=%d' % (ff, len(entities), stats['resyncs']))
    finally:
        if not args.keep_dumps:
            removed = 0
            for f in new_files:
                try:
                    os.remove(os.path.join(folder, f)); removed += 1
                except OSError:
                    pass
            print('cleaned up %d dumped files from game folder' % removed)

    out = args.out or os.path.join(THIS, 'out', os.path.basename(args.block) + '.level.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(level, fh, indent=1)
    print('wrote %s  (%d fragments, %d entities)' %
          (out, len(level['fragments']), level['totals']['entities']))

if __name__ == '__main__':
    main()
