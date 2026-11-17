"""Community pack and updates: the only code in Mod Studio that can reach a network, and it does nothing until the person has switched
"Online features" on AND typed an address. Both addresses are empty by default; no host is built in.

  catalogue   a JSON file at the address in Settings:
              {"format": "todms-catalogue", "name": "...", "mods": [{"id", "name", "author", "version", "description", "url", "sha256",
               "size", "kind": "mod" | "collection"}]}        (a url may be relative to the catalogue's own address)
  updates     {"version": "1.0.11", "url": "...setup.exe", "sha256": "...", "changes": ["...", ...]}

https:// and file:// addresses work, and http:// to this computer. A download is accepted only when its SHA-256 matches the entry; the file then
goes through modfile's safety check like any other. Updating runs the new setup only when the caller says the person confirmed.
"""
import hashlib
import json
import os
import subprocess
import urllib.parse
import urllib.request

from . import compat, modfile, mods, paths

TIMEOUT = 15
MAX_CATALOGUE = 8 * 1024 * 1024
MAX_UPDATE = 600 * 1024 * 1024


class Offline(ValueError):
    pass


def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme in ('https', 'file'):
        return url
    if u.scheme == 'http' and (u.hostname or '') in ('127.0.0.1', 'localhost', '::1'):
        return url
    raise ValueError('Only https addresses are accepted (or a file on this computer).')


def _address(settings, key):
    if not settings.get('online'):
        raise Offline('Online features are off. Turn them on in Settings first.')
    url = str(settings.get(key) or '').strip()
    if not url:
        raise Offline('No address is set in Settings.')
    return _check_url(url)


def fetch(url, limit):
    _check_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': 'TODModStudio'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(limit + 1)
    except (OSError, ValueError) as e:
        raise ValueError('Could not reach %s (%s).' % (_host(url), str(getattr(e, 'reason', e))[:80]))
    if len(data) > limit:
        raise ValueError('The download is larger than allowed.')
    return data


def _host(url):
    u = urllib.parse.urlparse(url)
    return u.hostname or 'the file'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------------------------------ catalogue
def catalogue(settings):
    """-> dict(name, rows=[...]) with each row's state against the library: new, installed, update (a newer version is offered)."""
    base = _address(settings, 'community_url')
    try:
        doc = json.loads(fetch(base, MAX_CATALOGUE).decode('utf-8-sig'))
    except ValueError as e:
        if 'Could not reach' in str(e) or 'larger' in str(e):
            raise
        raise ValueError('The catalogue is not in the expected form.')
    if not isinstance(doc, dict) or doc.get('format') != 'todms-catalogue' or not isinstance(doc.get('mods'), list):
        raise ValueError('The catalogue is not in the expected form.')
    lib = {m['id']: m for m in mods.list_mods()}
    rows = []
    for e in doc['mods'][:1000]:
        if not isinstance(e, dict) or not e.get('url') or not e.get('id'):
            continue
        have = lib.get(e['id'])
        state = 'new'
        if have:
            state = 'update' if compat.vcmp(e.get('version') or '0', have.get('version') or '0') > 0 else 'installed'
        try:
            url = _check_url(urllib.parse.urljoin(base, str(e['url'])))
        except ValueError:
            continue
        rows.append(dict(id=str(e['id'])[:64], name=str(e.get('name') or e['id'])[:80], author=str(e.get('author') or '')[:80],
                         version=str(e.get('version') or '')[:24], description=str(e.get('description') or '')[:400], url=url,
                         sha256=str(e.get('sha256') or '').lower(), size=int(e.get('size') or 0) if str(e.get('size') or '0').isdigit() else 0,
                         kind=e.get('kind') if e.get('kind') in ('mod', 'collection') else 'mod', state=state,
                         have=have.get('version') if have else None))
    return dict(name=str(doc.get('name') or '')[:80], rows=rows, url=base)


def get_entry(settings, entry_id, game=None):
    """Download one catalogue entry, check its fingerprint and the file itself, add it to the library. -> modshare.import result."""
    from . import modshare
    cat = catalogue(settings)
    row = next((r for r in cat['rows'] if r['id'] == entry_id), None)
    if not row:
        raise ValueError('That entry is not in the catalogue any more.')
    if not row['sha256']:
        raise ValueError('This entry has no fingerprint, so it is not downloaded.')
    data = fetch(row['url'], modfile.MAX_FILE)
    if sha256(data) != row['sha256']:
        raise ValueError('The download does not match its fingerprint. Nothing was added.')
    return modshare.import_bytes(data, game)


# ------------------------------------------------------------------------------------------------ updates
def check_update(settings, current=None):
    """-> dict(available, current, version, changes, url, sha256). Reads only; never downloads the installer."""
    base = _address(settings, 'update_url')
    try:
        doc = json.loads(fetch(base, MAX_CATALOGUE).decode('utf-8-sig'))
    except ValueError as e:
        if 'Could not reach' in str(e):
            raise
        raise ValueError('The update information is not in the expected form.')
    if not isinstance(doc, dict) or not doc.get('version') or not doc.get('url'):
        raise ValueError('The update information is not in the expected form.')
    cur = current or compat.app_version()
    ch = doc.get('changes') or []
    if isinstance(ch, str):
        ch = [ch]
    return dict(available=compat.vcmp(doc['version'], cur) > 0, current=cur, version=str(doc['version'])[:24],
                changes=[str(c)[:300] for c in ch][:40], url=_check_url(urllib.parse.urljoin(base, str(doc['url']))),
                sha256=str(doc.get('sha256') or '').lower())


def download_update(settings, current=None):
    """Download the new setup into the cache and check its fingerprint. Nothing is run. -> dict(path, version)."""
    info = check_update(settings, current)
    if not info['sha256']:
        raise ValueError('The update has no fingerprint, so it is not downloaded.')
    data = fetch(info['url'], MAX_UPDATE)
    if sha256(data) != info['sha256']:
        raise ValueError('The download does not match its fingerprint. Nothing was installed.')
    if data[:2] != b'MZ':
        raise ValueError('The download is not a Windows setup program.')
    d = os.path.join(paths.cache_dir(), 'updates')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'TODModStudio-Setup-%s.exe' % ''.join(c for c in info['version'] if c.isalnum() or c in '.-'))
    with open(p + '.part', 'wb') as f:
        f.write(data)
    os.replace(p + '.part', p)
    return dict(path=p, version=info['version'], sha256=info['sha256'])


def run_update(path, confirmed, launch=True):
    """Start the downloaded setup (silently, per user) once this program has closed. Only with the person's confirmation."""
    if not confirmed:
        raise ValueError('The update needs the person to confirm first.')
    if not os.path.isfile(path) or os.path.dirname(os.path.abspath(path)) != os.path.abspath(os.path.join(paths.cache_dir(), 'updates')):
        raise ValueError('That is not a downloaded update.')
    cmd = 'cmd /c ping -n 4 127.0.0.1 >nul & "%s" --silent' % path
    if launch:
        subprocess.Popen(cmd, creationflags=0x08000000 | 0x00000008, close_fds=True)
    return dict(started=bool(launch), command=cmd)
