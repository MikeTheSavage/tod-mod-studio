"""vfxlib: the particle-effect layer on top of the fragment writer (tools/fragment_writer).

Templates are the Database_Particle_ID(...) entities of overdose.main's ParticleDict.fragment; their Specific_ID is the
number placed emitters (EffectNum), triggers (Particle_system) and the game's code (DB_PARTICLEDICT_LIST[i]) use.
A template is a tree: the root (itself a ParticleSystem or GeometryEffect) and its stages (child ParticleSystem /
GeometryEffect entities, GEKeyFrame keys under a GeometryEffect).
"""
import os, sys, json, struct
HERE = os.path.dirname(os.path.abspath(__file__))
_FW_CANDIDATES = [os.environ.get('TOD_FW', ''), os.path.join(HERE, '..', 'fragment_writer'),
                  os.path.join(HERE, '..', '..', 'fw')]
for _p in _FW_CANDIDATES:
    if _p and os.path.exists(os.path.join(_p, 'todfrag.py')):
        FW = os.path.abspath(_p)
        break
else:
    raise ImportError('fragment_writer not found (set TOD_FW to tools/fragment_writer)')
sys.path.insert(0, FW)
sys.dont_write_bytecode = True
import todblock as tb   # noqa: E402
import todfrag as tf    # noqa: E402
import fragedit as fe   # noqa: E402

MAIN_ENTRY = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
DICT_FRAGMENT = 'ParticleDict.fragment'
SCENE_FRAGMENT = 'Overdose.scene'
PARTICLE_EFFECTS_MAX_NUM = 228          # exe default of common.PARTICLE_EFFECTS_MAX_NUM (FUN_0062E2F0, string "228")
STAGE_CLASSES = ('ParticleSystem', 'GeometryEffect', 'GEKeyFrame')
_T = None


def types():
    global _T
    if _T is None:
        _T = tf.Types()
    return _T


def is_template_type(t):
    return bool(t) and t.startswith('Database_Particle_ID(')


def stage_class(t):
    if not t:
        return None
    if t in STAGE_CLASSES:
        return t
    if t.startswith('Database_Particle_ID('):
        return t[len('Database_Particle_ID('):-1]
    return None


class Dict:
    """Index over one ParticleDict-like fragment (FragDoc)."""

    def __init__(self, doc):
        self.doc = doc
        T = doc.T
        self.T = T
        self.templates = []          # (specific_id, node)
        for n in doc.created_ids():
            if is_template_type(doc.type_of(n)):
                sid = doc.get(n, 'Specific_ID')
                self.templates.append((sid, n))
        self.by_id = {}
        for sid, n in self.templates:
            self.by_id.setdefault(sid, []).append(n)

    def template(self, sel):
        """sel: Specific_ID (int), template name (str) or '0x' node id."""
        d = self.doc
        if isinstance(sel, int):
            hits = self.by_id.get(sel, [])
            if not hits:
                raise fe.EditError('no template with Specific_ID %d' % sel)
            if len(hits) > 1:
                # the engine walks the dict tree in pre-order and the LAST registration wins (list set-at-index)
                order = d.subtree_all_order()
                hits = sorted(hits, key=lambda n: order.index(n))
                return hits[-1]
            return hits[0]
        if isinstance(sel, str) and sel.lower().startswith('0x'):
            return d.find(sel)
        if isinstance(sel, str) and sel.isdigit():
            return self.template(int(sel))
        hits = [n for _, n in self.templates if d.get(n, 'name') == sel]
        if len(hits) != 1:
            raise fe.EditError('template name %r matched %d templates' % (sel, len(hits)))
        return hits[0]

    def stages(self, root):
        """Pre-order list of (index, node, class) of the template tree; index 0 = the root."""
        out = []
        for i, n in enumerate(self.doc.subtree(root)):
            out.append((i, n, stage_class(self.doc.type_of(n)) or self.doc.type_of(n)))
        return out

    def stage(self, root, sel):
        st = self.stages(root)
        if sel in (None, 'root', 0):
            return root
        if isinstance(sel, int):
            for i, n, c in st:
                if i == sel:
                    return n
            raise fe.EditError('template %#x has no stage %d (has %d)' % (root, sel, len(st)))
        if isinstance(sel, str) and sel.lower().startswith('0x'):
            n = int(sel, 16)
            if n not in [x[1] for x in st]:
                raise fe.EditError('node %s is not in template %#x' % (sel, root))
            return n
        hits = [n for i, n, c in st if self.doc.get(n, 'name') == sel]
        if isinstance(sel, dict):
            hits = [n for i, n, c in st if (sel.get('name') is None or self.doc.get(n, 'name') == sel['name'])
                    and (sel.get('texture') is None or (self.doc.get(n, 'Texture') or '').lower().endswith(sel['texture'].lower()))]
            if 'index' in sel:
                hits = hits[sel['index']:sel['index'] + 1]
        if len(hits) != 1:
            raise fe.EditError('stage selector %r matched %d stages of template %#x' % (sel, len(hits), root))
        return hits[0]

    def params(self, node):
        d = self.doc
        out = {}
        for r in d.sets_of(node):
            out[self.T.name(r.prop)] = d.frag.value(r)
        return out


def _subtree_all_order(self):
    roots = [n for n in self.created_ids() if (self.get(n, fe.P_PARENT) or 0) not in set(self.created_ids())]
    out = []
    for r in roots:
        out += self.subtree(r)
    return out


fe.FragDoc.subtree_all_order = _subtree_all_order


def load_block(block=None, entry=None):
    """block: None (GOG overdose.main), an archive entry/bare name, or a block file (then entry = its archive name)."""
    if block and os.path.exists(block):
        raw = open(block, 'rb').read()
        ent = entry or MAIN_ENTRY
    else:
        arch = tb.open_naz()
        name = block or MAIN_ENTRY
        if name not in arch.names:
            hits = [n for n in arch.names if n.lower().endswith('/' + name.lower())]
            if len(hits) != 1:
                raise fe.EditError('block %r matches %d archive entries' % (name, len(hits)))
            name = hits[0]
        raw = arch.read(name)
        ent = name
    return raw, ent, os.path.splitext(ent)[1]


def fragment_doc(raw, ext, sub):
    b = tb.Block(raw, ext)
    info = bytes(b.info)
    starts = tb.record_starts(info, b.n)
    hits = []
    for k, R in enumerate(starts):
        if tb.u32(info, R) != 4:
            continue
        nm = tb.record_name(info, R)
        if sub.lower() in nm.lower():
            hits.append((k, nm))
    if len(hits) != 1:
        raise fe.EditError('fragment %r matched %d fragments' % (sub, len(hits)))
    k, nm = hits[0]
    return b, k, fe.FragDoc(b.payloads[k], types(), nm)


def block_assets(raw, ext):
    b = tb.Block(raw, ext)
    info = bytes(b.info)
    return {tb.record_name(info, R).lower(): tb.u32(info, R) for R in tb.record_starts(info, b.n)}


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]
