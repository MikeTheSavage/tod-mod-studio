"""The user's installed game: archives, configpc.txt, the base block chain, TOD HD detection.

Read only, except configpc.txt and our own mod zip, which only mods.py writes (with a backup).
"""
import hashlib
import os
import re
import subprocess

from . import paths

GOG_EXE_MD5 = 'd9beb351b3c78ee9f14a766a368f3ff9'
MOD_ZIP = 'todms_mods.zip'
MISSIONS_ZIP = 'todms_missions.zip'      # mission templates package (missions_tpl.py)
DEFAULT_FS = ['blocks.naz', 'sounds.naz', 'videos00.naz', 'videos01.naz']
SHARED = 'data_pc/overdose_the_game/overdose/shared/'
MAIN_ENTRY = SHARED + 'overdose.main'


def md5_file(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_configpc(folder):
    p = os.path.join(folder, 'configpc.txt')
    if not os.path.exists(p):
        return []
    return open(p, 'r', encoding='latin-1').read().splitlines()


def filesystem_line(lines):
    """The archives named on the last 'filesystem =' line, or None."""
    fs = None
    for ln in lines:
        m = re.match(r'\s*filesystem\s*=\s*(.*)$', ln, re.I)
        if m:
            fs = [x.strip() for x in m.group(1).split(',') if x.strip()]
    return fs


def game_running(folder=None):
    """True when TOD.exe / TotalOverdose.exe runs (from `folder`, when given; a process whose path cannot be read
    counts as running there)."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                             creationflags=flags).stdout.lower()
    except Exception:
        return False
    if '"tod.exe"' not in out and '"totaloverdose.exe"' not in out:
        return False
    if folder is None:
        return True
    try:
        ps = subprocess.run(['powershell', '-NoProfile', '-Command',
                             'Get-Process TOD,TotalOverdose -ErrorAction SilentlyContinue | ForEach-Object { "P:" + $_.Path }'],
                            capture_output=True, text=True, creationflags=flags, timeout=30).stdout
    except Exception:
        return True
    want = os.path.normcase(os.path.abspath(folder))
    for ln in ps.splitlines():
        if not ln.startswith('P:'):
            continue
        p = ln[2:].strip()
        if not p or os.path.normcase(os.path.dirname(os.path.abspath(p))) == want:
            return True
    return False


class Game:
    def __init__(self, folder):
        self.folder = os.path.abspath(folder)
        self.naz = os.path.join(self.folder, 'blocks.naz')
        if not os.path.exists(self.naz):
            raise ValueError('no blocks.naz in %s: pick the folder that holds TOD.exe and blocks.naz' % self.folder)
        paths.setup_tools(self.naz)
        import todblock as tb
        self._tb = tb
        self._arch = {}
        exe = os.path.join(self.folder, 'TOD.exe')
        self.exe_md5 = md5_file(exe) if os.path.exists(exe) else None
        self.is_gog_exe = self.exe_md5 == GOG_EXE_MD5

    # ---------------------------------------------------------------- archives
    def archive(self, name):
        if name not in self._arch:
            self._arch[name] = self._tb.Archive(os.path.join(self.folder, name))
        return self._arch[name]

    def base(self):
        return self.archive('blocks.naz')

    def chain(self, mode='effective'):
        """Archives the engine searches for blocks, in order, without our own mod zip.
        mode 'vanilla': blocks.naz only; 'effective': the configpc.txt filesystem line (TOD HD's zips included)."""
        if mode == 'vanilla':
            return ['blocks.naz']
        fs = filesystem_line(read_configpc(self.folder)) or DEFAULT_FS
        out = []
        for a in fs:
            if a.lower() in (MOD_ZIP, MISSIONS_ZIP) or a.lower().startswith('todms_newmap_') or not a.lower().endswith(('.zip', '.naz')):
                continue
            if a.lower() in ('sounds.naz', 'videos00.naz', 'videos01.naz', 'uk_sounds.naz'):
                continue
            if os.path.exists(os.path.join(self.folder, a)):
                out.append(a)
        if 'blocks.naz' not in [x.lower() for x in out]:
            out.append('blocks.naz')
        return out

    def hd_zips(self):
        return [a for a in self.chain('effective') if a.lower().startswith('hd_override')]

    def has_hd(self):
        return bool(self.hd_zips())

    def find_block(self, entry, mode='effective'):
        """-> (archive name, size) of the block the engine would load."""
        for a in self.chain(mode):
            arc = self.archive(a)
            if entry in arc.names:
                return a, arc.names[entry][1]
        raise KeyError(entry)

    def read_block(self, entry, mode='effective'):
        a, _ = self.find_block(entry, mode)
        return self.archive(a).read(entry), a

    def names(self):
        return self.base().names

    def info(self):
        return dict(folder=self.folder, exe_md5=self.exe_md5, gog_exe=self.is_gog_exe,
                    chain=self.chain('effective'), tod_hd=self.has_hd(), hd_zips=self.hd_zips(),
                    filesystem_line=filesystem_line(read_configpc(self.folder)))
