"""The app state: settings, the chosen game, the local cache of levels / meshes / textures, background jobs."""
import collections
import hashlib
import json
import os
import threading
import time
import traceback
import uuid

from . import paths, ledger

SETTINGS_FILE = 'settings.json'
LEVEL_VERSION = 5          # bump when the level JSON layout changes (old cache entries are rebuilt)
ASSET_VERSION = 2


def _h(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def _stem(entry):
    return os.path.splitext(entry.split('/')[-1])[0]


class Jobs:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()          # one heavy job at a time (the vendored tools are not thread safe)

    def start(self, kind, fn, *args, **kw):
        jid = uuid.uuid4().hex[:10]
        job = dict(id=jid, kind=kind, status='queued', done=0, total=0, message='', result=None, error=None,
                   started=time.time())
        self.jobs[jid] = job

        def progress(msg=None, done=None, total=None):
            if msg is not None:
                job['message'] = msg
            if done is not None:
                job['done'] = done
            if total is not None:
                job['total'] = total

        def run():
            with self.lock:
                job['status'] = 'running'
                try:
                    job['result'] = fn(*args, progress=progress, **kw)
                    job['status'] = 'done'
                except Exception as e:
                    job['status'] = 'failed'
                    job['error'] = str(e)
                    job['trace'] = traceback.format_exc()
                job['ended'] = time.time()
        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, jid):
        return self.jobs.get(jid)

    def run_sync(self, fn, *args, **kw):
        with self.lock:
            return fn(*args, progress=lambda *a, **k: None, **kw)


class Workspace:
    def __init__(self):
        self.settings = self._load_settings()
        self.game = None
        self.catalog = None
        self.jobs = Jobs()
        self._assets = collections.OrderedDict()
        self._levels = {}
        self._main_frags = None
        self.T = None
        folder = self.settings.get('game_folder')
        if folder and os.path.exists(os.path.join(folder, 'blocks.naz')):
            try:
                self._open_game(folder)
            except Exception as e:
                self.settings['last_error'] = str(e)

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        p = os.path.join(paths.user_dir(), SETTINGS_FILE)
        try:
            return json.load(open(p))
        except Exception:
            return {}

    def save_settings(self):
        p = os.path.join(paths.user_dir(), SETTINGS_FILE)
        json.dump(self.settings, open(p + '.part', 'w'), indent=1)
        os.replace(p + '.part', p)

    @property
    def base_mode(self):
        """'effective': build on the archives configpc.txt lists (TOD HD's blocks when installed); 'vanilla':
        blocks.naz only."""
        return 'effective' if self.settings.get('build_on_installed', True) else 'vanilla'

    # ------------------------------------------------------------------ game
    def _open_game(self, folder):
        from . import game as gm
        g = gm.Game(folder)
        self.game = g
        self._rebind_tools(g.naz)
        from . import tables
        import todblock as tb
        gid = '%s|%d' % (g.naz, os.path.getsize(g.naz))
        if not tables.ready() or self.settings.get('tables_for') != gid:
            b = tb.Block(g.base().read(gm.MAIN_ENTRY), '.main')
            tables.build(g.base(), b.prop_ck, b.cmd_ck)
            self.settings['tables_for'] = gid
        import fragtool as ft
        ft.TYPES = None
        self.T = ft.types()
        catp = os.path.join(paths.cache_dir(), 'catalog_%s.json' % _h(gid))
        if os.path.exists(catp):
            self.catalog = json.load(open(catp))
        else:
            from . import catalog
            self.catalog = catalog.build(g)
            json.dump(self.catalog, open(catp, 'w'), indent=0)
        self._assets.clear()
        self._levels.clear()
        self._main_frags = None

    def _rebind_tools(self, naz):
        paths.setup_tools(naz)
        import fragtool as ft
        ft.GOG_NAZ = naz
        ft._arch = None
        try:
            import submaptool
            submaptool._main_frags = None
        except Exception:
            pass

    def set_game(self, folder, progress=None):
        folder = os.path.abspath(folder)
        if progress:
            progress('checking the game folder')
        self._open_game(folder)
        self.settings['game_folder'] = folder
        self.settings.pop('last_error', None)
        self.save_settings()
        return self.status()

    @staticmethod
    def missing_parts():
        """Libraries the picture steps need (the minimap and the plan are drawn with PIL): the ones that cannot be imported, for the startup self-check."""
        out = []
        for mod in ('PIL', 'numpy'):
            try:
                __import__(mod)
            except Exception:
                out.append(mod)
        return out

    def status(self):
        g = self.game
        return dict(ready=g is not None, missing=self.missing_parts(), settings={k: v for k, v in self.settings.items() if k != 'tables_for'},
                    game=g.info() if g else None, base_mode=self.base_mode, cache=paths.cache_dir(),
                    user_dir=paths.user_dir(), maps=len(self.catalog['maps']) if self.catalog else 0)

    # ------------------------------------------------------------------ blocks
    def block_key(self, entry):
        arc, size = self.game.find_block(entry, self.base_mode)
        return '%s-%s' % (_stem(entry), _h('%s|%s|%d' % (arc, entry, size))[:8])

    def read_block(self, entry):
        return self.game.read_block(entry, self.base_mode)

    def main_lookup(self, short):
        if self._main_frags is None:
            import todblock as tb
            import fragtool as ft
            from .game import MAIN_ENTRY
            raw, _ = self.read_block(MAIN_ENTRY)
            b = tb.Block(raw, '.main')
            frs, _ = ft.fragments(b)
            self._main_frags = {nm.replace('\\', '/').split('/')[-1].lower(): (nm, b.payloads[k]) for k, nm in frs}
        return self._main_frags.get(short)

    def block_level(self, entry):
        """In-memory BlockLevel (re-used for props and the builder)."""
        key = self.block_key(entry)
        if key not in self._levels:
            from . import level
            raw, _ = self.read_block(entry)
            self._levels.clear() if len(self._levels) > 6 else None
            self._levels[key] = level.BlockLevel(entry, raw, self.T, self.main_lookup)
        return self._levels[key]

    def assets(self, entry):
        key = self.block_key(entry)
        if key not in self._assets:
            from . import extract
            raw, _ = self.read_block(entry)
            self._assets[key] = extract.BlockAssets(raw, os.path.splitext(entry)[1])
            while len(self._assets) > getattr(self, '_assets_cap', 4):
                self._assets.popitem(last=False)
        else:
            self._assets.move_to_end(key)
        return self._assets[key]

    def block_dir(self, key):
        d = os.path.join(paths.cache_dir(), 'blocks', key)
        os.makedirs(d, exist_ok=True)
        return d

    # ------------------------------------------------------------------ level json
    def level_json(self, entry, progress=None):
        key = self.block_key(entry)
        p = os.path.join(self.block_dir(key), 'level.json')
        if os.path.exists(p):
            try:
                j = json.load(open(p))
                if j.get('version') == LEVEL_VERSION:
                    return j
            except Exception:
                pass
        if progress:
            progress('reading %s' % entry.split('/')[-1])
        L = self.block_level(entry)
        ents, links = L.entities(key)
        try:
            import submaptool as st
            import todblock as tb
            lf, nxt, _ = st.last_fragment(L.b, entry)
        except Exception as e:
            lf, nxt = None, None
        j = dict(version=LEVEL_VERSION, key=key, entry=entry, kind=os.path.splitext(entry)[1][1:],
                 title=_stem(entry), entities=ents, links=links, models=dict(L.models_used()),
                 nodes=len(L.instances), next_runtime=L.next_runtime, last_fragment=lf,
                 info_bytes=len(L.b.info), block_bytes=len(L.b.prefix) + 24 + len(L.b.info) + 4 * L.b.n + sum(L.b.sizes),
                 fragments=[dict(k=k, name=nm, inst=L.inst_count.get(nm, 0)) for k, nm in L.frs])
        json.dump(j, open(p, 'w'), separators=(',', ':'))
        return j

    # ------------------------------------------------------------------ meshes and textures
    def _asset_index(self, key):
        p = os.path.join(self.block_dir(key), 'assets.json')
        try:
            j = json.load(open(p))
            if j.get('version') == ASSET_VERSION:
                return j
        except Exception:
            pass
        return dict(version=ASSET_VERSION, models={}, textures={})

    def _save_index(self, key, j):
        p = os.path.join(self.block_dir(key), 'assets.json')
        json.dump(j, open(p + '.part', 'w'), separators=(',', ':'))
        os.replace(p + '.part', p)

    def model_table(self, model_names, context_entries, progress=None):
        """Extract (once) every named model from the first block of context_entries that holds it, plus its textures
        (from the same block, else the other context blocks). Returns {model: {url, bound, coll, textures}}."""
        from .game import MAIN_ENTRY
        ctx = list(dict.fromkeys(list(context_entries) + [MAIN_ENTRY]))
        self._assets_cap = max(4, len(ctx) + 1)       # a whole map has many blocks in play: do not re-read them per texture
        assets = [(e, self.block_key(e)) for e in ctx]
        idx = {k: self._asset_index(k) for _, k in assets}
        dirty = set()
        out = {}
        names = sorted(model_names)
        for i, name in enumerate(names):
            if progress and i % 10 == 0:
                progress('meshes %d / %d' % (i, len(names)), i, len(names))
            src = None
            for e, k in assets:
                if name in idx[k]['models']:
                    src = (e, k)
                    break
            if src is None:
                for e, k in assets:
                    if name in self.assets(e).models:
                        glb, meta = self.assets(e).model_glb(name)
                        rec = dict(meta=meta, file=None)
                        if glb:
                            fn = 'm_%s.glb' % _h(name)
                            open(os.path.join(self.block_dir(k), fn), 'wb').write(glb)
                            rec['file'] = fn
                        idx[k]['models'][name] = rec
                        dirty.add(k)
                        src = (e, k)
                        break
            if src is None:
                out[name] = dict(missing=True)
                continue
            e, k = src
            rec = idx[k]['models'][name]
            if not rec.get('file'):
                out[name] = dict(missing=True, reason='no geometry')
                continue
            texs = {}
            for t in rec['meta'].get('textures', []):
                texs[t] = self._texture(t, [(e, k)] + [a for a in assets if a[1] != k], idx, dirty)
            out[name] = dict(url='/cache/blocks/%s/%s' % (k, rec['file']), bound=rec['meta'].get('bound'),
                             coll=rec['meta'].get('coll_tris', 0), tris=rec['meta'].get('render_tris', 0),
                             hulls=rec['meta'].get('hulls', 0), textures=texs)
        for k in dirty:
            self._save_index(k, idx[k])
        self._assets_cap = 4
        while len(self._assets) > 4:
            self._assets.popitem(last=False)
        return out

    def _texture(self, name, order, idx, dirty):
        for e, k in order:
            rec = idx[k]['textures'].get(name)
            if rec is not None:
                if rec.get('file'):
                    return dict(url='/cache/blocks/%s/%s' % (k, rec['file']), alpha=rec['alpha'])
                continue
            if name in self.assets(e).textures:
                r = self.assets(e).texture_dds(name)
                if r is None:
                    idx[k]['textures'][name] = dict(file=None, alpha=False)
                    dirty.add(k)
                    continue
                fn = 't_%s.dds' % _h(name)
                open(os.path.join(self.block_dir(k), fn), 'wb').write(r[0])
                idx[k]['textures'][name] = dict(file=fn, alpha=r[1]['alpha'], fmt=r[1]['fmt'], w=r[1]['w'], h=r[1]['h'])
                dirty.add(k)
                return dict(url='/cache/blocks/%s/%s' % (k, fn), alpha=r[1]['alpha'])
        return None

    # ------------------------------------------------------------------ open a level (job)
    def open_level(self, map_id, section=None, missions=(), progress=None, sections=None):
        """map block + sections + any missions, as the engine has them resident together.
        sections: a list of section entries, or '*' for every section of the map (the whole map)."""
        m = next(x for x in self.catalog['maps'] if x['id'] == map_id)
        entries = [m['map_block']]
        if sections == '*':
            sections = [s['entry'] for s in m['sections']]
        for s in ([section] if section else []) + list(sections or []):
            if s and s not in entries:
                entries.append(s)
        entries += [x for x in missions if x]
        levels = []
        for i, e in enumerate(entries):
            if progress:
                progress('reading %s' % e.split('/')[-1], i, len(entries))
            levels.append(self.level_json(e))
            ledger.remember(self, e, levels[-1])
        names = set()
        for L in levels:
            names |= set(L['models'])
        ctx = [e for e in entries]
        models = self.model_table(names, ctx, progress)
        return dict(map=map_id, entries=entries, levels=levels, models=models)

    # Models that live in a mission or section block rather than the shared one (found with the asset census).
    MODEL_HOME = {
        '/data/characters/gangster/gangster.model': 'subm_38_down_move_kill.mission',
        '/data/characters/mexican_police/mexican_police.model': 'mm080_highwaybridge.mission',
        '/data/characters/military/soldier.model': 'mm092_escapejungle.mission',
        '/data/models/vehicles/dirtbike/bike.model': 'subm_07_indu_mulral01_race.mission',
        '/data/models/vehicles/pickup4x4/vehicle.model': 'intermission_after_bridge.mission',
        '/data/models/vehicles/stationwagon/vehicle.model': 'subm_07_indu_mulral01_race.mission',
        '/data/models/vehicles/bigtruck/vehicle.model': 'subm_12_indu_mulral02_race.mission',
        '/data/models/vehicles/van_urban/vehicle.model': 'subm_17_down_coldeb02_killsteal.mission',
        '/data/models/vehicles/forklift/vehicle.model': 'subm_41_harb_move_kill.mission',
        '/data/models/vehicles/sedan_74_standard/vehicle.model': 'subm_08_down_7gates01_race.mission',
        '/data/models/vehicles/pickuptruck/vehicle.model': 'subm_40_harb_move_kill.mission',
        '/data/models/vehicles/conquistador/vehicle.model': 'subm_33_harb_mulral04_race.mission',
        '/data/models/vehicles/elcamino_lostorosrose/vehicle.model': 'submap01_map07_meat_factory.submap',
        '/data/models/vehicles/sedan_modernstandard/vehicle.model': 'submap03_map03_lostoros_industrial.submap',
    }

    def home_entry(self, n):
        """The block that holds the mesh of model path n (a model that lives in a mission or section block, else the shared one)."""
        from .game import MAIN_ENTRY
        by_base = {MAIN_ENTRY.split('/')[-1]: MAIN_ENTRY}
        for m in self.catalog['maps']:
            by_base[m['map_block'].split('/')[-1]] = m['map_block']
            for s in m['sections'] + m['missions']:
                if s.get('entry'):
                    by_base[s['entry'].split('/')[-1]] = s['entry']
        n = (n or '').lower()
        base = self.MODEL_HOME.get(n)
        home = by_base.get(base) if base else MAIN_ENTRY
        if not base:                                  # a model that lives in some other block: the asset index knows which
            try:
                from . import assetindex
                doc = assetindex.load(self)
                r = doc and doc['models'].get(n)
                if r and r['blocks'] and MAIN_ENTRY not in r['blocks']:
                    home = r['blocks'][0]
            except Exception:
                pass
        if base and not home:
            import fragtool as ft
            home = next((x for x in ft.archive().names if x.lower().endswith('/' + base)), MAIN_ENTRY)
        return home

    def find_models(self, names):
        """Meshes for model paths that may not be in the open blocks (the live preview of added objects).
        Returns the same record shape as model_table."""
        out = {}
        for n in names:
            n = (n or '').lower()
            try:
                out.update(self.model_table({n}, [self.home_entry(n)]))
            except Exception as ex:
                out[n] = dict(missing=True, reason=str(ex))
        return out

    def prepare_all(self, progress=None):
        """First-run cache: every map block and section (missions are extracted when first opened)."""
        todo = []
        for m in self.catalog['maps']:
            todo.append((m['id'], m['map_block'], [m['map_block']]))
            for s in m['sections']:
                todo.append((m['id'], s['entry'], [s['entry'], m['map_block']]))
        for i, (mid, e, ctx) in enumerate(todo):
            if progress:
                progress('%s: %s' % (mid, e.split('/')[-1]), i, len(todo))
            L = self.level_json(e)
            self.model_table(set(L['models']), ctx)
        self.settings['cache_prepared'] = True
        self.save_settings()
        return dict(blocks=len(todo))
