"""Wrap the packaged app (dist/TODModStudio, from scripts/build_exe.py) into one installer:
dist/TODModStudio-Setup-<version>.exe (per-user, no admin; Start menu, Settings > Apps uninstall).

  .venv\Scripts\python scripts\build_setup.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPDIR = os.path.join(ROOT, 'dist', 'TODModStudio')
WORK = os.path.join(ROOT, 'build', 'setup')


def main():
    if not os.path.isfile(os.path.join(APPDIR, 'TODModStudio.exe')):
        sys.exit('build the app first: scripts/build_exe.py')
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    n = subprocess.check_output(['git', 'rev-list', '--count', 'HEAD'], cwd=ROOT, text=True).strip()
    h = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()
    vf = os.path.join(ROOT, 'VERSION')           # a VERSION file (one line) wins over the commit count
    version = open(vf).read().strip() if os.path.exists(vf) else '1.0.%s' % n
    json.dump(dict(version=version, commit=h, built=datetime.date.today().isoformat()),
              open(os.path.join(WORK, 'setup_info.json'), 'w'))
    payload = os.path.join(WORK, 'payload.zip')
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dp, _, fs in os.walk(APPDIR):
            for f in fs:
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, APPDIR))
    name = 'TODModStudio-Setup-%s' % version
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed', '--name', name,
            '--icon', os.path.join(APPDIR, 'TODModStudio.exe'),
            '--distpath', os.path.join(ROOT, 'dist'), '--workpath', os.path.join(WORK, 'pyi'), '--specpath', WORK,
            '--add-data', payload + ';.', '--add-data', os.path.join(WORK, 'setup_info.json') + ';.',
            '--exclude-module', 'numpy', os.path.join(ROOT, 'scripts', 'setup_main.py')]
    subprocess.check_call(args, cwd=ROOT)
    out = os.path.join(ROOT, 'dist', name + '.exe')
    print('built %s (%.1f MB, payload %.1f MB, version %s @ %s)' % (out, os.path.getsize(out) / 1e6,
                                                                   os.path.getsize(payload) / 1e6, version, h))


if __name__ == '__main__':
    main()
