"""base_overlay.py - make the tool chain build on a Gameplay+ (or other) data zip instead of the shipped blocks.

Two ways to switch it on:
  * env (old way, unchanged): MESA_BASE_ZIP = a data zip, optional MESA_BASE_ENTRIES = ';'-list of entry names. install() at import.
  * in process (new): configure(chain, entries=None) with an ordered list of archive paths (the game's filesystem chain, first wins).
    Every read of an entry that is in one of the ZIPS of the chain AND in `entries` (default: DEFAULT_ENTRIES = overdose.main, the Downtown submap01
    and the uk text block) returns the first such zip's bytes instead of blocks.naz's. Everything else stays vanilla, so the mission templates the
    builder clones keep their proven vanilla content. Non-zip chain items (blocks.naz ...) are ignored here (the tools read blocks.naz themselves).
    configure(None) or configure([]) switches the overlay off again. Re-pointable any number of times in one process.

install() patches todblock.Archive.read in every copy of the todblock module (the tool chain vendors several), including copies
imported later (a meta-path hook). The patched read consults the CURRENT configuration on every call.
"""
import importlib.abc, importlib.machinery, os, sys, zipfile

SHARED = 'data_pc/overdose_the_game/overdose/shared/'
DEFAULT_ENTRIES = (SHARED + 'overdose.main', SHARED + 'submap01_map02_lostoros_downtown.submap',
                   'data_pc/overdose_the_game/overdose/uk/overdose_uk.main')
_DONE = False
_STATE = dict(zips=[], entries=set(), cache={}, key=None)     # zips: [(path, ZipFile)], entries: names the overlay may serve


def configure(chain=None, entries=None):
    """chain: ordered archive paths (only .zip items matter) or None/[] = overlay off. entries: names to serve (default DEFAULT_ENTRIES).
    Returns the list of entry names that will be served from a zip."""
    for _p, z in _STATE['zips']:
        try:
            z.close()
        except Exception:                                     # noqa: BLE001
            pass
    zips = []
    for p in (chain or []):
        if str(p).lower().endswith('.zip') and os.path.exists(p):
            zips.append((os.path.abspath(p), zipfile.ZipFile(p)))
    ents = set(entries) if entries else set(DEFAULT_ENTRIES)
    _STATE.update(zips=zips, entries=ents, cache={}, key=(tuple(p for p, _ in zips), tuple(sorted(ents))))
    if zips:
        _ensure_hooks()
    served = [e for e in sorted(ents) if any(e in z.namelist() for _p, z in zips)]
    return served


def active_key():
    return _STATE['key']


def _serve(name):
    if name not in _STATE['entries']:
        return None
    if name in _STATE['cache']:
        return _STATE['cache'][name]
    for _p, z in _STATE['zips']:
        try:
            data = z.read(name)
        except KeyError:
            continue
        _STATE['cache'][name] = data
        return data
    return None


def _patch(mod):
    A = getattr(mod, 'Archive', None)
    if A is None or getattr(A, '_mesa_overlay', False):
        return
    orig = A.read

    def read(self, name):
        if _STATE['zips'] and os.path.basename(self.path).lower() == 'blocks.naz':
            d = _serve(name)
            if d is not None:
                return d
        return orig(self, name)
    A.read = read
    A._mesa_overlay = True


class _Hook(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split('.')[-1] != 'todblock' or getattr(self, '_busy', False):
            return None
        self._busy = True
        try:
            spec = importlib.machinery.PathFinder.find_spec(name, path)
        finally:
            self._busy = False
        if spec is None or spec.loader is None:
            return None
        loader = spec.loader
        orig_exec = loader.exec_module

        def exec_module(module):
            orig_exec(module)
            _patch(module)
        loader.exec_module = exec_module
        return spec


def _ensure_hooks():
    global _DONE
    if _DONE:
        for n, m in list(sys.modules.items()):                # copies imported since the last call
            if n.split('.')[-1] == 'todblock':
                _patch(m)
        return
    _DONE = True
    for n, m in list(sys.modules.items()):
        if n.split('.')[-1] == 'todblock':
            _patch(m)
    sys.meta_path.insert(0, _Hook())


def install():
    """env switch (MESA_BASE_ZIP / MESA_BASE_ENTRIES); no-op without the variable"""
    if not os.environ.get('MESA_BASE_ZIP'):
        return
    ents = [e for e in os.environ.get('MESA_BASE_ENTRIES', '').split(';') if e]
    configure([os.environ['MESA_BASE_ZIP']], ents or None)
