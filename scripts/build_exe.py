"""Package TOD Mod Studio as dist/TODModStudio/TODModStudio.exe (PyInstaller one-folder build).

  .venv\Scripts\python scripts\build_exe.py

Needs the UI built first (frontend: npm run build -> backend/web). The vendored tools travel as plain .py files under
_internal/vendor (they are imported from there at run time); backend/data and backend/web likewise. The companion core
(backend/todct, vendored from the Unreal plugin) is bundled as a package; numpy is bundled for the model writer the
collision generator uses (numpy must be importable in .venv).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'backend')
GUIDE = 'TOD Mod Studio Guide.html'


def main():
    if not os.path.exists(os.path.join(B, 'web', 'index.html')):
        sys.exit('build the UI first: cd frontend && npm run build')
    for d in ('build', 'dist'):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    sep = ';'
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
            '--name', 'TODModStudio', '--distpath', os.path.join(ROOT, 'dist'),
            '--workpath', os.path.join(ROOT, 'build'), '--specpath', os.path.join(ROOT, 'build'),
            '--paths', B, '--hidden-import', 'todms._stdlib',
            '--collect-submodules', 'todms', '--collect-submodules', 'todct', '--hidden-import', 'numpy',
            '--add-data', os.path.join(B, 'vendor') + sep + 'vendor',
            '--add-data', os.path.join(B, 'data') + sep + 'data',
            '--add-data', os.path.join(B, 'web') + sep + 'web',
            '--exclude-module', 'PIL', '--exclude-module', 'tkinter',      # numpy is needed: model writer (collision)
            os.path.join(B, 'main.py')]
    print(' '.join(args))
    subprocess.check_call(args, cwd=ROOT)
    exe = os.path.join(ROOT, 'dist', 'TODModStudio', 'TODModStudio.exe')
    shutil.copy2(os.path.join(ROOT, 'README.md'), os.path.join(ROOT, 'dist', 'TODModStudio', 'README.md'))
    shutil.copy2(os.path.join(ROOT, 'guide', GUIDE), os.path.join(ROOT, 'dist', 'TODModStudio', GUIDE))   # plain-language guide
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.dirname(exe)) for f in fs)
    print('built %s (%d bytes exe, %.1f MB folder)' % (exe, os.path.getsize(exe), total / 1e6))


if __name__ == '__main__':
    main()
