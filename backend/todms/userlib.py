"""The per-user editor library: prefabs, keyboard shortcuts, scatter presets, driving presets and the copy buffer.

One small JSON file in the user folder (never part of a mod, never game data). Every key has a fixed shape so a bad
file or a bad request can never put the editor into a state it cannot read back."""
import json
import os

from . import paths

FILE = 'userlib.json'
MAX_BYTES = 4 * 1024 * 1024
SHAPES = {'prefabs': list, 'shortcuts': dict, 'scatter': dict, 'clipboard': dict, 'driving': dict}


def _path():
    return os.path.join(paths.user_dir(), FILE)


def load():
    """All keys, each in its shape (a missing or unreadable file gives empty values)."""
    out = {k: t() for k, t in SHAPES.items()}
    try:
        with open(_path(), encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    if isinstance(raw, dict):
        for k, t in SHAPES.items():
            if isinstance(raw.get(k), t):
                out[k] = raw[k]
    return out


def save_key(key, value):
    if key not in SHAPES:
        raise ValueError('unknown library key')
    if not isinstance(value, SHAPES[key]):
        raise ValueError('the %s entry must be a %s' % (key, SHAPES[key].__name__))
    data = load()
    data[key] = value
    blob = json.dumps(data, indent=1)
    if len(blob.encode('utf-8')) > MAX_BYTES:
        raise ValueError('the library is too large')
    p = _path()
    with open(p + '.part', 'w', encoding='utf-8', newline='\n') as f:
        f.write(blob)
    os.replace(p + '.part', p)
    return data
