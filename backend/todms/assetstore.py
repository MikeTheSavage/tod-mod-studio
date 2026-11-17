"""The asset store: the files a recipe's models and textures point at (scene blobs of imported models, source images of textures).

Content addressed: <user dir>/assets/<sha>.bin. A recipe holds only the sha, so it stays small and several mods can share one file.
Exporting a .todmod embeds the files it uses (zlib, base64) under "blobs"; importing writes them back into the store.
"""
import base64
import hashlib
import json
import os
import zlib

from . import paths


def store_dir():
    d = os.path.join(paths.user_dir(), 'assets')
    os.makedirs(d, exist_ok=True)
    return d


def sha_of(data):
    return hashlib.sha256(data).hexdigest()[:32]


def path_of(sha):
    return os.path.join(store_dir(), sha + '.bin')


def put(data):
    sha = sha_of(data)
    p = path_of(sha)
    if not os.path.exists(p):
        with open(p + '.part', 'wb') as f:
            f.write(data)
        os.replace(p + '.part', p)
    return sha


def get(sha):
    try:
        with open(path_of(sha), 'rb') as f:
            return f.read()
    except OSError:
        raise KeyError('the file %s of this mod is missing from the asset store' % sha)


def has(sha):
    return os.path.exists(path_of(sha))


def shas_of(mod):
    from todct import assetops
    return assetops.blob_shas(mod.get('models'), mod.get('textures'))


def embed(mod):
    """-> {sha: base64(zlib(bytes))} for every file the recipe uses (missing files are left out)."""
    out = {}
    for s in shas_of(mod):
        if has(s):
            out[s] = base64.b64encode(zlib.compress(get(s), 6)).decode('ascii')
    return out


def unpack(blobs):
    n = 0
    for s, b in (blobs or {}).items():
        data = zlib.decompress(base64.b64decode(b))
        if sha_of(data) != s:
            raise ValueError('a file inside the mod does not match its name')
        put(data)
        n += 1
    return n


def missing(mod):
    return [s for s in shas_of(mod) if not has(s)]
