"""Copy the shared companion-tools core (todct) from the Unreal plugin into backend/todct.

  python scripts/vendor_companion.py [--check]

The canonical source (env TODCT_SRC) is the TODLevelEditor Unreal plugin's Backend/todct (collision generator,
asset replacement table, .todmod exchange), shared with the Unreal TODLevelEditor plugin so a mod made in either
editor uses the same data; it also copies the part-B tool files listed in EXTRA_TOOLS (seamless/transitions.py) into
backend/vendor/tools. Never edit backend/todct here: change the source and re-vendor. Hashes go to
backend/vendor/COMPANION.json; --check only compares.
"""
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get('TODCT_SRC', '')            # the TODLevelEditor Unreal plugin's Backend/todct
# tool files part B needs that scripts/vendor_tools.py does not copy (read only on the source)
TOOLS_SRC = os.environ.get('TOD_TOOLS', '')      # the author's TOD Project tools folder (not included)
EXTRA_TOOLS = ['seamless/transitions.py']
TOOLS_DST = os.path.join(ROOT, 'backend', 'vendor', 'tools')
DST = os.path.join(ROOT, 'backend', 'todct')
REC = os.path.join(ROOT, 'backend', 'vendor', 'COMPANION.json')


def files(d):
    return sorted(f for f in os.listdir(d) if f.endswith('.py'))


def h(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def main():
    check = '--check' in sys.argv
    if not os.path.isdir(SRC):
        print("set TODCT_SRC to the TODLevelEditor plugin's Backend/todct folder")
        return 1
    if not check and not os.path.isdir(TOOLS_SRC):
        print('set TOD_TOOLS to the TOD Project tools folder (for %s)' % ', '.join(EXTRA_TOOLS))
        return 1
    src = {f: h(os.path.join(SRC, f)) for f in files(SRC)}
    if check:
        dst = {f: h(os.path.join(DST, f)) for f in files(DST)} if os.path.isdir(DST) else {}
        diff = sorted(set(src) ^ set(dst) | {f for f in src if f in dst and src[f] != dst[f]})
        print('in step' if not diff else 'differs: %s' % ', '.join(diff))
        return 1 if diff else 0
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)
    for f in src:
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))
    extra = {}
    for rel in EXTRA_TOOLS:
        s_ = os.path.join(TOOLS_SRC, rel)
        d_ = os.path.join(TOOLS_DST, rel)
        os.makedirs(os.path.dirname(d_), exist_ok=True)
        shutil.copy2(s_, d_)
        extra[rel] = h(d_)
    json.dump(dict(source=SRC, copied=time.strftime('%Y-%m-%d %H:%M:%S'), files=src, extra_tools=extra),
              open(REC, 'w'), indent=1)
    print('vendored %d files from %s' % (len(src), SRC))
    return 0


if __name__ == '__main__':
    sys.exit(main())
