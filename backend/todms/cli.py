"""Command line entry points besides the window: what the uninstaller calls, and the files the shell hands to the program.

  TODModStudio.exe --restore-vanilla [--remove-backups]    put the game back to its own files (and delete the backups), no window
  TODModStudio.exe "C:\path\Mod.todmod" ...                 open the program and offer to add the file(s)
"""
import json
import os
import sys

from . import paths

OPEN_EXT = ('.todmod', '.todcollection', '.todpiece')


def open_files(argv):
    """The mod files named on the command line (existing files with a known extension; anything else is ignored)."""
    out = []
    for a in argv or []:
        a = str(a).strip('"')
        if a.lower().endswith(OPEN_EXT) and os.path.isfile(a):
            out.append(os.path.abspath(a))
    return out


def remove_backups(ws=None):
    """Mod Studio's own restore points and copies of configpc.txt, and the save snapshots it made. The game's saves are never touched."""
    import shutil
    from . import restore, snapshots
    n = 0
    for d in (restore.root(), snapshots.root()):
        for name in os.listdir(d):
            shutil.rmtree(os.path.join(d, name), ignore_errors=True)
            n += 1
    if ws is not None and ws.game is not None:
        for name in os.listdir(ws.game.folder):
            if name.startswith('configpc.txt.todms_'):
                try:
                    os.remove(os.path.join(ws.game.folder, name))
                    n += 1
                except OSError:
                    pass
    return n


def restore_vanilla(remove=False, out=None):
    """-> dict(ok, ...). Never raises: the uninstaller must be able to go on whatever happens here."""
    res = dict(ok=True, restored=False, removed_backups=0)
    try:
        paths.setup_tools()
        from .workspace import Workspace
        from . import game as gm, restore
        ws = Workspace()
        if ws.game is None:
            res['skipped'] = 'no game folder is set'
        elif gm.game_running(ws.game.folder):
            res.update(ok=False, error='Total Overdose is running: close it first.')
            return _done(res, out)
        else:
            r = restore.restore_vanilla(ws)
            res.update(restored=True, left=r.get('left', []))
        if remove:
            res['removed_backups'] = remove_backups(ws)
    except Exception as e:
        res.update(ok=False, error=str(e))
    return _done(res, out)


def _done(res, out):
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=1)
    return res


def main(argv):
    """-> an exit code when the arguments were a command line job, None for the normal window."""
    if '--restore-vanilla' in argv:
        out = argv[argv.index('--result') + 1] if '--result' in argv else None
        r = restore_vanilla('--remove-backups' in argv, out)
        if sys.stdout:
            print(json.dumps(r))
        return 0 if r['ok'] else 1
    return None
