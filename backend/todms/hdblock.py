"""TOD HD's strict block reader with one guard against a false record start.

The reader finds the records of a block by scanning every 16-aligned offset for a header shape (type <= 10, the fill word 0xBAADF00D at +12,
a name pointer that lands on a '/'). In a block that carries a baked-lighting record this can match by chance inside the record: its index
copies sit next to the fill words, and a pointer made of two indices may land on the '/' inside a longer texture path. The reader then
counts one record too many and refuses a block that is fine. A real name starts a string, so a pointer that lands in the middle of one (the
byte before it is a printable character) is not a start, and a name is a path of at least a few characters (a pointer at a lone "/" is not). The guard is only used after the plain scan has failed, so every block that read
before reads the same way.
"""
import os
import sys
import threading

from . import paths

_LOCK = threading.Lock()
MIN_NAME = 6            # shortest real record name ("/a.bmp"); a lone "/" that a chance header points at is no name


def _hd():
    p = os.path.join(paths.BACKEND, 'vendor', 'hd')
    if p not in sys.path:
        sys.path.append(p)
    import tod_hd_game
    return tod_hd_game


def Block(raw, ext):
    G = _hd()

    class _Block(G.Block):
        def _records(self):
            try:
                return super()._records()
            except G.GameDataError as e:
                if 'record scan found' not in str(e):
                    raise
            orig = G.cstring
            info = self.info

            def guarded(buf, off, *a, **k):
                if buf is info and off > 0 and 32 <= buf[off - 1] < 127:
                    raise G.GameDataError('a name must start a string')
                res = orig(buf, off, *a, **k)
                if buf is info and len(res) < MIN_NAME:
                    raise G.GameDataError('a name is a path, not a stray "/"')
                return res
            with _LOCK:
                G.cstring = guarded
                try:
                    return super()._records()
                finally:
                    G.cstring = orig
    return _Block(raw, ext)
