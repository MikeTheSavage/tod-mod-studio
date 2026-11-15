"""TOD Mod Studio Setup: a small per-user Windows installer (no admin rights needed).

Installs the packaged app (payload.zip, embedded by scripts/build_setup.py) into a folder of the user's choice (default
%LOCALAPPDATA%\\Programs\\TOD Mod Studio), adds a Start-menu shortcut and optionally a desktop shortcut, and registers
an uninstaller under Settings > Apps (HKCU, so no admin). The same exe, copied into the install folder as
'Uninstall TOD Mod Studio.exe', is the uninstaller.

The app's own data (mod library, settings: %APPDATA%\\TODModStudio; extracted cache: %LOCALAPPDATA%\\TODModStudio) is
outside the install folder and is kept on update and, unless the user ticks the box, on uninstall.

  Setup.exe                          the window
  Setup.exe --silent [--dir D] [--desktop] [--no-startmenu]
  Setup.exe --uninstall [--silent] [--purge]
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
import winreg

APP = 'TOD Mod Studio'
EXE = 'TODModStudio.exe'
KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\TODModStudio'
UNINSTALLER = 'Uninstall TOD Mod Studio.exe'
GUIDE = 'TOD Mod Studio Guide.html'
WEBVIEW2_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'
NO_WINDOW = 0x08000000


def res(name):
    return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), name)


def info():
    try:
        return json.load(open(res('setup_info.json'), encoding='utf-8'))
    except OSError:
        return dict(version='dev')


def default_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'Programs', APP)


def start_menu_lnk(name=APP):
    return os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\Start Menu\Programs', name + '.lnk')


def desktop_lnk():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
        d = os.path.expandvars(winreg.QueryValueEx(k, 'Desktop')[0])
    except OSError:
        d = os.path.join(os.path.expanduser('~'), 'Desktop')
    return os.path.join(d, APP + '.lnk')


def webview2_ok():
    guid = r'{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\\' + guid),
                       (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\\' + guid),
                       (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\EdgeUpdate\Clients\\' + guid)):
        try:
            v = winreg.QueryValueEx(winreg.OpenKey(hive, path), 'pv')[0]
            if v and v != '0.0.0.0':
                return True
        except OSError:
            pass
    return False


def make_lnk(lnk, target, workdir, icon=True):
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TODMS_LNK);$s.TargetPath=$env:TODMS_TGT;"
          "$s.WorkingDirectory=$env:TODMS_WD;" + ("$s.IconLocation=$env:TODMS_TGT+',0';" if icon else '') + "$s.Save()")
    env = dict(os.environ, TODMS_LNK=lnk, TODMS_TGT=target, TODMS_WD=workdir)
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], env=env, check=True,
                   creationflags=NO_WINDOW, capture_output=True)


def installed_dir():
    try:
        return winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY), 'InstallLocation')[0]
    except OSError:
        return None


def app_running():
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + EXE, '/NH'], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return EXE.lower() in r.stdout.lower()


def install(dest, startmenu=True, desktop=False, log=print):
    dest = os.path.abspath(dest)
    if app_running():
        raise RuntimeError('TOD Mod Studio is running. Close it first, then install again.')
    os.makedirs(dest, exist_ok=True)
    for old in ('_internal', EXE):                      # an update replaces the program files; user data lives elsewhere
        p = os.path.join(dest, old)
        if os.path.isdir(p):
            log('Removing the old version...')
            shutil.rmtree(p)
        elif os.path.isfile(p):
            os.remove(p)
    with zipfile.ZipFile(res('payload.zip')) as z:
        names = z.namelist()
        for i, n in enumerate(names):
            z.extract(n, dest)
            if i % 25 == 0:
                log('Copying files... %d%%' % (100 * i // len(names)))
    exe = os.path.join(dest, EXE)
    if not os.path.isfile(exe):
        raise RuntimeError('the copied program is incomplete (%s missing)' % EXE)
    me = sys.executable if getattr(sys, 'frozen', False) else None
    if me and os.path.normcase(me) != os.path.normcase(os.path.join(dest, UNINSTALLER)):
        shutil.copy2(me, os.path.join(dest, UNINSTALLER))
    log('Creating shortcuts...')
    if startmenu:
        make_lnk(start_menu_lnk(), exe, dest)
        if os.path.isfile(os.path.join(dest, GUIDE)):
            make_lnk(start_menu_lnk(APP + ' Guide'), os.path.join(dest, GUIDE), dest, icon=False)
    if desktop:
        make_lnk(desktop_lnk(), exe, dest)
    size_kb = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(dest) for f in fs) // 1024
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY)
    unin = '"%s" --uninstall' % os.path.join(dest, UNINSTALLER)
    for name, val in (('DisplayName', APP), ('DisplayVersion', info().get('version', '')), ('Publisher', APP),
                      ('InstallLocation', dest), ('DisplayIcon', exe + ',0'), ('UninstallString', unin),
                      ('QuietUninstallString', unin + ' --silent')):
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    for name, val in (('EstimatedSize', size_kb), ('NoModify', 1), ('NoRepair', 1)):
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)
    log('Done.')
    return exe


def uninstall(purge=False, log=print):
    dest = installed_dir() or os.path.dirname(os.path.abspath(sys.executable))
    if app_running():
        raise RuntimeError('TOD Mod Studio is running. Close it first, then uninstall again.')
    for lnk in (start_menu_lnk(), start_menu_lnk(APP + ' Guide'), desktop_lnk()):
        if os.path.exists(lnk):
            os.remove(lnk)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
    except OSError:
        pass
    if purge:
        for d in (os.path.join(os.environ.get('APPDATA', ''), 'TODModStudio'),
                  os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TODModStudio')):
            shutil.rmtree(d, ignore_errors=True)
    for old in ('_internal', EXE, 'README.md', GUIDE):
        p = os.path.join(dest, old)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
    # this exe is running from the folder: a detached cmd removes it (and the folder, if empty) once we exit
    me = os.path.join(dest, UNINSTALLER)
    subprocess.Popen('cmd /c ping -n 3 127.0.0.1 >nul & del /f /q "%s" & rmdir "%s"' % (me, dest),
                     creationflags=NO_WINDOW | 0x00000008, close_fds=True)
    log('Removed.')


# ------------------------------------------------------------------------------------------------ the window

def gui(mode):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title(APP + (' Setup' if mode == 'install' else ' - Uninstall'))
    root.resizable(False, False)
    f = ttk.Frame(root, padding=18)
    f.grid()
    v = info().get('version', '')
    status = tk.StringVar()

    def run_bg(fn, done):
        def work():
            try:
                r = fn()
                root.after(0, lambda: done(r, None))
            except Exception as e:                       # noqa: BLE001
                root.after(0, lambda e=e: done(None, e))
        threading.Thread(target=work, daemon=True).start()

    def say(msg):
        root.after(0, lambda: status.set(msg))

    if mode == 'install':
        ttk.Label(f, text=APP, font=('Segoe UI', 16, 'bold')).grid(sticky='w')
        ttk.Label(f, text='Version %s. A level editor and mod manager for Total Overdose.\n'
                          'It reads your own installed copy of the game; no game files are included.' % v,
                  justify='left').grid(sticky='w', pady=(2, 12))
        ttk.Label(f, text='Install folder').grid(sticky='w')
        row = ttk.Frame(f)
        row.grid(sticky='we')
        dest = tk.StringVar(value=installed_dir() or default_dir())
        ttk.Entry(row, textvariable=dest, width=56).grid(row=0, column=0)
        def browse():
            d = filedialog.askdirectory(initialdir=os.path.dirname(dest.get()))
            if d:
                dest.set(os.path.normpath(d if os.path.basename(d) == APP else os.path.join(d, APP)))
        ttk.Button(row, text='Browse...', command=browse).grid(row=0, column=1, padx=(6, 0))
        sm, dt, launch = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text='Start menu shortcut', variable=sm).grid(sticky='w', pady=(10, 0))
        ttk.Checkbutton(f, text='Desktop shortcut', variable=dt).grid(sticky='w')
        ttk.Checkbutton(f, text='Start TOD Mod Studio when Setup finishes', variable=launch).grid(sticky='w')
        if not webview2_ok():
            ttk.Label(f, text='Note: this PC is missing the Microsoft Edge WebView2 Runtime the app window needs.\n'
                              'Setup can continue; install the runtime from Microsoft before you start the app.',
                      foreground='#a03000', justify='left').grid(sticky='w', pady=(10, 0))
        ttk.Label(f, textvariable=status).grid(sticky='w', pady=(12, 0))
        btns = ttk.Frame(f)
        btns.grid(sticky='e', pady=(8, 0))
        go = ttk.Button(btns, text='Install')
        go.grid(row=0, column=0)
        ttk.Button(btns, text='Cancel', command=root.destroy).grid(row=0, column=1, padx=(6, 0))

        def done(exe, err):
            if err:
                go.state(['!disabled'])
                status.set('')
                messagebox.showerror(APP, 'Install failed: %s' % err)
                return
            if not webview2_ok() and messagebox.askyesno(APP, 'Installed. Open the WebView2 Runtime download page now?'):
                os.startfile(WEBVIEW2_URL)
            elif launch.get():
                subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
            else:
                messagebox.showinfo(APP, 'Installed. Start it from the Start menu: %s.' % APP)
            root.destroy()

        def start():
            go.state(['disabled'])
            run_bg(lambda: install(dest.get(), sm.get(), dt.get(), say), done)
        go.configure(command=start)
    else:
        ttk.Label(f, text='Remove %s from this PC?' % APP, font=('Segoe UI', 12, 'bold')).grid(sticky='w')
        purge = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Also delete my mod library, settings and the extracted game cache', variable=purge
                        ).grid(sticky='w', pady=(10, 0))
        ttk.Label(f, text='Mods already installed into the game stay until you remove them in the app (Mods tab).',
                  justify='left').grid(sticky='w', pady=(6, 0))
        ttk.Label(f, textvariable=status).grid(sticky='w', pady=(10, 0))
        btns = ttk.Frame(f)
        btns.grid(sticky='e', pady=(8, 0))
        go = ttk.Button(btns, text='Uninstall')
        go.grid(row=0, column=0)
        ttk.Button(btns, text='Cancel', command=root.destroy).grid(row=0, column=1, padx=(6, 0))

        def done(_, err):
            if err:
                go.state(['!disabled'])
                messagebox.showerror(APP, 'Uninstall failed: %s' % err)
                return
            messagebox.showinfo(APP, '%s was removed.' % APP)
            root.destroy()
        go.configure(command=lambda: (go.state(['disabled']), run_bg(lambda: uninstall(purge.get(), say), done)))
    root.mainloop()


def main(argv):
    uninst = '--uninstall' in argv or os.path.basename(sys.executable).lower().startswith('uninstall')
    if '--silent' in argv:
        if uninst:
            uninstall('--purge' in argv)
        else:
            d = argv[argv.index('--dir') + 1] if '--dir' in argv else (installed_dir() or default_dir())
            install(d, '--no-startmenu' not in argv, '--desktop' in argv)
        return 0
    gui('uninstall' if uninst else 'install')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
