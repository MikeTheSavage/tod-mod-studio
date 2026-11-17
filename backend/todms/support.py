"""The support bundle: one zip with what a person helping needs, and nothing personal (ideas 62, 97, 98). Never saves, never game data.
The user's folder name is replaced by %USERPROFILE% in every text file. Nothing is sent anywhere."""
import datetime
import json
import os
import platform
import re
import sys
import zipfile

from . import game as gm, mods, paths, testgame

USER_RE = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/"\s:*?<>|]+', re.I)
MAX_LOG = 400000


def scrub(text):
    """Replace the user folder (and any other drive:/Users/name folder) with %USERPROFILE%, in plain and JSON-escaped spellings."""
    home = os.path.expanduser('~')
    forms = {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}
    for f in sorted(forms, key=len, reverse=True):
        if f:
            text = re.sub(re.escape(f), lambda m: '%USERPROFILE%', text, flags=re.I)
    text = USER_RE.sub('%USERPROFILE%', text)
    user = os.environ.get('USERNAME') or os.path.basename(home)
    if user and len(user) > 2:
        text = re.sub(r'(?i)(?<![\w])' + re.escape(user) + r'(?![\w])', '<user>', text)
    return text


def _version():
    for p in (os.path.join(paths.BACKEND, 'VERSION'), os.path.join(os.path.dirname(paths.BACKEND), 'VERSION')):
        try:
            return open(p).read().strip()
        except OSError:
            pass
    return 'unknown'


def collect(ws, extra=None):
    """-> dict(name -> text) of everything that goes into the bundle (already scrubbed)."""
    files = {}
    info = ['TOD Mod Studio %s' % _version(), 'Windows: %s' % platform.platform(), 'Machine: %s' % platform.machine(),
            'Python: %s' % sys.version.split()[0], 'Created: %s' % datetime.datetime.now().isoformat(timespec='seconds')]
    g = ws.game
    if g:
        info += ['', 'Game: TOD.exe md5 %s (%s)' % (g.exe_md5, 'GOG build' if g.is_gog_exe else 'not the GOG build'),
                 'TOD HD: %s' % ('yes' if g.has_hd() else 'no'),
                 'Gameplay+: %s' % ('yes' if any(os.path.exists(os.path.join(g.folder, n)) for n in ('TODGameplay.dll', 'todgameplay.dll')) else 'no'),
                 'Archives: ' + ', '.join('%s %d' % (n, os.path.getsize(os.path.join(g.folder, n))) for n in g.chain('effective')
                                         if os.path.exists(os.path.join(g.folder, n)))]
        files['configpc.txt'] = '\n'.join(gm.read_configpc(g.folder)) + '\n'
        for n in ('todms_pack.json', 'todms_newmaps.json', 'todms_missions.json'):
            p = os.path.join(g.folder, n)
            if os.path.exists(p):
                try:
                    with open(p, encoding='utf-8-sig') as f:
                        j = json.load(f)
                    if n == 'todms_pack.json':
                        j = {k: v for k, v in j.items() if k != 'owner'}
                    elif n == 'todms_newmaps.json':
                        j = {k: {kk: vv for kk, vv in v.items() if kk != 'params'} for k, v in j.items()}
                    elif n == 'todms_missions.json':
                        j = {k: ({pk: {kk: vv for kk, vv in pv.items() if kk != 'project'} for pk, pv in v.items()} if k == 'projects' else v)
                             for k, v in j.items() if k not in ('migrate_entries', 'thread_keys')}
                    files[n] = json.dumps(j, indent=1)
                except Exception:
                    pass
    ml = []
    for m in mods.list_mods():
        ml.append('%d. %s%s - %d level changes, %d game data values' % (len(ml) + 1, m['name'], '' if m['enabled'] else ' (off)', m['level_ops'], m['data_values']))
    files['mods.txt'] = '\n'.join(ml) + '\n' if ml else 'No mods in the library.\n'
    st = testgame.current()
    if st:
        run = {k: v for k, v in st.items() if k not in ('saves',)}
        files['last_test_run.json'] = json.dumps(run, indent=1, default=str)
        lg = st.get('log_kept') or st.get('log')
        if lg and os.path.exists(lg):
            with open(lg, 'rb') as f:
                data = f.read()[-MAX_LOG:].decode('latin-1')
            files['engine_log_tail.txt'] = data
    for k, v in (extra or {}).items():
        files[k] = v if isinstance(v, str) else json.dumps(v, indent=1)
    files['info.txt'] = '\n'.join(info) + '\n'
    return {k: scrub(v) for k, v in files.items()}


def build(ws, extra=None, out=None):
    files = collect(ws, extra)
    d = out or os.path.join(paths.user_dir(), 'support')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'todms_support_%s.zip' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, t in files.items():
            z.writestr(n, t)
    return dict(path=p, files=sorted(files), bytes=os.path.getsize(p))




def report_problem(ws, what, steps='', out=None):
    """A problem report for the person to send themselves: the support bundle plus one plain text file with their words. Nothing is sent
    anywhere and nothing is collected. -> dict(folder, bundle, text)."""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    d = out or os.path.join(paths.user_dir(), 'reports', stamp)
    os.makedirs(d, exist_ok=True)
    what, steps = scrub(str(what or '').strip()[:6000]), scrub(str(steps or '').strip()[:6000])
    words = what + ('\n\nWhat I did before:\n' + steps if steps else '') + '\n'
    b = build(ws, extra={'what_happened.txt': words}, out=d)
    txt = os.path.join(d, 'report_%s.txt' % stamp)
    with open(txt, 'w', encoding='utf-8') as f:
        f.write('TOD Mod Studio %s - problem report\n\nWhat happened:\n%s\n\nWhat I did before:\n%s\n\n' % (_version(), what or '-', steps or '-'))
        f.write('The zip next to this file holds the version, a list of my mods, the game setup and the last test log, with my user name '
                'removed. It holds no saves and no game files.\nNothing was sent anywhere: send both files yourself.\n')
    return dict(folder=d, bundle=b['path'], text=txt)
