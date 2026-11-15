"""TOD particle-effect tool (GOG build): read, check and write effect templates and emitters.
Doc: docs/subsystem_vfx.md sections 9-17. Needs tools/fragment_writer (TOD_FW, default ../fragment_writer); `kept`
runs the GOG TOD.exe's own setter stubs (TOD_EXE, read only; capstone). re/ holds the research scripts (they need
TOD_REF = a folder with the GOG Ghidra FullDump decomp.c / funcs.tsv / calls.tsv / strings.tsv).

  python vfxtool.py list [--block B] [--filter TEXT]          templates: Specific_ID, name, stages, textures
  python vfxtool.py show <id|name> [--block B] [--kept]        every stage with named parameters
                                                              (--kept: also the value the engine keeps after its own
                                                               load-time packing, from the exe's setter stubs)
  python vfxtool.py uses <id|name>                             who spawns it: game code sites + placed data refs
  python vfxtool.py kept <Param> <value> [--class C]           engine-kept value of one parameter value
  python vfxtool.py free-ids [--block B]                       Specific_IDs < 228 with no template and no reference
  python vfxtool.py roundtrip [--block B] [--all-fx]           byte-identical proof (fragments, blocks, VFX re-set)
  python vfxtool.py edit <vfx_edit.json> --out DIR [--deploy TESTGAME]
  python vfxtool.py selftest [--out DIR]
  python vfxtool.py hdpatch <vfx_edit.json> -o patches.json    same-length subset as TOD HD entity patches

<block> defaults to the GOG overdose.main inside blocks.naz (read only). A block file on disk (a TOD HD block, a
clip_replace / coll_replace / fragtool output) can be given with "block" + "entry" in the edit file, or --block FILE.

vfx_edit.json:
{ "description": "...",
  "blocks": [ { "block": "overdose.main" | "<file>", "entry": "<archive entry when block is a file>",
                "ops": [
     {"op": "set_param",   "template": 188, "stage": 1 | "root" | "Eksplotion_FIRE02" | "0x00101..." |
                           {"texture": "Explosion03.bmp"} , "param": "Size", "value": 6.0},
     {"op": "scale_param", "template": 188, "stage": "*" | sel, "param": "LifeTime", "factor": 2.0,
                           "min": 0.0, "max": 80.0},
     {"op": "set_texture", "template": 188, "stage": sel, "texture": "/Textures/Sprites/Explosion04.bmp"},
     {"op": "set_color",   "template": 188, "stage": sel, "rgb": [0.2, 1.0, 0.2]},
     {"op": "add_template","source": 11, "id": 19, "name": "Fire_Big_Green", "set": {"<stage sel>": {"Param": v}}},
     {"op": "epic",        "template": 188, "fireball": 1.5, "life": 2.0, "smoke_life": 2.2, "rise": 2.5},
     {"op": "point_emitter", "fragment": F, "entity": SEL, "template": 19},          (map / submap / mission blocks)
     {"op": "raise_max",   "value": 240}                                            (unverified, see doc)
  ] } ] }

Every edit is compiled to fragment-writer operations (set / clone) and verified by tools/fragment_writer
(fragtool.verify_block: base block round-trips, only the intended records change, no dangling references, the
independent reader walks the result, the zip is read back through the engine's OpenZip/FindFile port).
Output: the rebuilt block(s), frag_override.zip (rename freely), configpc_line.txt, report.json, vfx_report.json.
"""
import argparse, json, os, sys, copy, hashlib, tempfile
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vfxlib as vl     # noqa: E402
tb, tf, fe = vl.tb, vl.tf, vl.fe
import fragtool as ft   # noqa: E402

PACK = json.load(open(os.path.join(HERE, 'param_packing.json')))
SPRITE_TEX = ('explosion01', 'explosion03', 'explosion04')


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ engine-kept values (exe setter stubs)
_emu = None


def kept(param, value, cls='ParticleSystem'):
    """Value the engine keeps for `param` = getter(setter(value)) run on the exe's own bytes (emu.py)."""
    global _emu
    row = PACK['classes'].get(cls, {}).get(param)
    if row is None or row['type'] not in ('number', 'integer', 'truth'):
        return None
    if _emu is None:
        try:
            import emu as _e   # noqa
            _emu = _e
        except Exception:
            return None
    e = _emu.Emu()
    e.hooks[0x951640] = lambda m: _emu.ftol(m.st.pop(0))
    e.hooks[0x4250C0] = lambda m: None
    e.hooks[0x46C470] = lambda m: None
    e.indirect_args = 1
    def d12(m): m.st.insert(0, _emu.dec12(m.arg(0), _emu.u2f(m.arg(1))))
    def d8(m): m.st.insert(0, _emu.dec8(m.arg(0), _emu.u2f(m.arg(1))))
    def d12s(m): m.st.insert(0, _emu.dec12s(m.arg(0), _emu.u2f(m.arg(1))))
    e.hooks[0x424D60] = d12
    e.hooks[0x424CB0] = d8
    e.hooks[0x424C10] = d12s
    a = _emu.f2u(float(value)) if row['type'] == 'number' else int(value) & 0xffffffff
    e.push(a)
    e.push(_emu.RET)
    e.run(int(row['setter'], 16))
    e.st = []
    e.r['esp'] = _emu.STK - 0x100
    e.r['ecx'] = _emu.OBJ
    e.push(_emu.RET)
    e.run(int(row['getter'], 16))
    if e.st:
        return e.st[0]
    v = e.r['eax']
    return v - (1 << 32) if v >> 31 else v


# ------------------------------------------------------------------ reading
def open_dict(block=None, entry=None):
    raw, ent, ext = vl.load_block(block, entry)
    b, k, doc = vl.fragment_doc(raw, ext, vl.DICT_FRAGMENT)
    return raw, ent, ext, doc, vl.Dict(doc)


def tex_of(doc, n):
    t = doc.get(n, 'Texture')
    return t.split('/')[-1] if t else ''


def cmd_list(a):
    raw, ent, ext, doc, D = open_dict(a.block, a.entry)
    rows = []
    for sid, n in sorted(D.templates, key=lambda x: (x[0] if x[0] is not None else -1, x[1])):
        name = doc.get(n, 'name') or ''
        st = D.stages(n)
        tex = sorted({tex_of(doc, s) for _, s, _ in st} - {''})
        line = '%4s  0x%08X  %-40s %2d stages  %s' % (sid, n, name[:40], len(st), ', '.join(tex))
        if a.filter and a.filter.lower() not in line.lower():
            continue
        rows.append(line)
    print('\n'.join(rows))
    print('%d templates (%d listed) in %s %s' % (len(D.templates), len(rows), ent, vl.DICT_FRAGMENT))


def cmd_show(a):
    raw, ent, ext, doc, D = open_dict(a.block, a.entry)
    root = D.template(int(a.template) if a.template.isdigit() else a.template)
    print('template %s  Specific_ID %s  node 0x%08X  path %s' % (doc.get(root, 'name'), doc.get(root, 'Specific_ID'),
                                                               root, doc.path_of(root)))
    for i, n, c in D.stages(root):
        p = D.params(n)
        print('\n[%d] 0x%08X %s  %s' % (i, n, doc.type_of(n), p.get('name', '')))
        for k, v in p.items():
            if k in ('parent', 'order', 'name', 'unique_id0', 'unique_id1'):
                continue
            extra = ''
            if a.kept and isinstance(v, (int, float)) and not isinstance(v, bool):
                kv = kept(k, v, c if c in PACK['classes'] else 'ParticleSystem')
                if kv is not None and (abs(kv - v) > max(1e-3, abs(v) * 0.02)):
                    extra = '   (engine keeps %.6g)' % kv
            print('    %-22s %s%s' % (k, json.dumps(v), extra))


def load_sites():
    return json.load(open(os.path.join(HERE, 'code_sites.json')))['sites']


def load_refs():
    return json.load(open(os.path.join(HERE, 'data_refs.json')))['refs']


def cmd_uses(a):
    raw, ent, ext, doc, D = open_dict(a.block, a.entry)
    root = D.template(int(a.template) if a.template.isdigit() else a.template)
    sid = doc.get(root, 'Specific_ID')
    print('template %s = Specific_ID %s' % (doc.get(root, 'name'), sid))
    cs = [s for s in load_sites() if s['index'] == sid]
    print('\ncode (DB_PARTICLEDICT_LIST[%s] read with a constant index): %d sites' % (sid, len(cs)))
    for s in cs:
        print('  %s  in %s  class %-30s %s' % (s['site'], s['func'], s.get('class'), s.get('cmd')))
    rs = [r for r in load_refs() if r['prop'] in ('Particle_system', 'EffectNum', 'Default_particle_effect') and r['value'] == sid]
    print('\nplaced data (EffectNum / Particle_system / Default_particle_effect = %s): %d' % (sid, len(rs)))
    by = {}
    for r in rs:
        by.setdefault((r['block'], r['class'], r['prop']), []).append(r)
    for k, v in sorted(by.items()):
        print('  %-48s %-40s %-16s x%d  e.g. %s %s' % (k[0], k[1], k[2], len(v), v[0]['node'], v[0]['name']))
    if not cs and not rs:
        print('\nNOTHING in the shipped code or data spawns this template (variable-index sites read it only through '
              'data refs listed above).')


def cmd_kept(a):
    v = kept(a.param, float(a.value) if '.' in a.value or 'e' in a.value.lower() else int(a.value), a.cls)
    print('%s %s -> engine keeps %r' % (a.param, a.value, v))
    row = PACK['classes'].get(a.cls, {}).get(a.param)
    if row:
        print(json.dumps({k: row[k] for k in row if k != 'samples'}))


def free_ids(doc, D):
    used = {sid for sid, _ in D.templates}
    code = {s['index'] for s in load_sites() if isinstance(s['index'], int)}
    data = {r['value'] for r in load_refs() if r['prop'] in ('Particle_system', 'EffectNum', 'Default_particle_effect')}
    return [i for i in range(vl.PARTICLE_EFFECTS_MAX_NUM) if i not in used and i not in code and i not in data]


def cmd_free(a):
    raw, ent, ext, doc, D = open_dict(a.block, a.entry)
    print('free Specific_IDs (no template, no code site, no placed reference, < PARTICLE_EFFECTS_MAX_NUM 228):',
          free_ids(doc, D))


# ------------------------------------------------------------------ compiling VFX ops to fragment-writer ops
class Compiler:
    def __init__(self, raw, ext, entry):
        self.raw, self.ext, self.entry = raw, ext, entry
        self.T = vl.types()
        self.is_main = entry.lower().endswith('overdose.main')
        self.ops = []            # fragment-writer ops for this block
        self.notes = []
        self.assets = vl.block_assets(raw, ext)
        if self.is_main:
            b, k, doc = vl.fragment_doc(raw, ext, vl.DICT_FRAGMENT)
            self.doc, self.D = doc, vl.Dict(doc)
        else:
            self.doc = self.D = None
        self.pending_templates = {}     # id -> name of templates added in this edit

    def need_dict(self, op):
        if not self.is_main:
            raise fe.EditError('op %s needs overdose.main (ParticleDict.fragment)' % op['op'])

    def stage_nodes(self, op):
        root = self.D.template(op['template'])
        sel = op.get('stage', 'root')
        if sel == '*':
            return root, [n for i, n, c in self.D.stages(root) if c == 'ParticleSystem']
        if isinstance(sel, list):
            return root, [self.D.stage(root, s) for s in sel]
        return root, [self.D.stage(root, sel)]

    def set(self, node, prop, value, fragment=vl.DICT_FRAGMENT):
        self.ops.append({'op': 'set', 'fragment': fragment, 'entity': '0x%08X' % node, 'prop': prop, 'value': value})

    def note_kept(self, prop, value, cls='ParticleSystem'):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        kv = kept(prop, value, cls)
        if kv is not None and abs(kv - value) > max(1e-3, abs(value) * 0.02):
            self.notes.append('%s %r: the engine keeps %.6g (its load-time packing clamps/rounds it)' % (prop, value, kv))

    def compile(self, op):
        k = op['op']
        if k == 'set_param':
            self.need_dict(op)
            root, nodes = self.stage_nodes(op)
            for n in nodes:
                self.set(n, op['param'], op['value'])
                self.note_kept(op['param'], op['value'], vl.stage_class(self.doc.type_of(n)) or 'ParticleSystem')
        elif k == 'scale_param':
            self.need_dict(op)
            root, nodes = self.stage_nodes(op)
            for n in nodes:
                v = self.doc.get(n, op['param'])
                if v is None:
                    continue
                nv = v * op['factor']
                if 'min' in op: nv = max(op['min'], nv)
                if 'max' in op: nv = min(op['max'], nv)
                nv = int(round(nv)) if isinstance(v, int) and not isinstance(v, bool) else vl.f32(nv)
                self.set(n, op['param'], nv)
                self.note_kept(op['param'], nv)
        elif k == 'set_texture':
            self.need_dict(op)
            tex = op['texture']
            if not tex.startswith('/'):
                tex = '/Textures/Sprites/' + tex
            if ('/data' + tex).lower() not in self.assets and not op.get('allow_missing'):
                raise fe.EditError('texture %s is not an asset of %s (add it with a texture tool first, or set '
                                   'allow_missing)' % (tex, self.entry))
            root, nodes = self.stage_nodes(op)
            for n in nodes:
                self.set(n, 'Texture', tex)
        elif k == 'set_color':
            self.need_dict(op)
            root, nodes = self.stage_nodes(op)
            for n in nodes:
                self.set(n, 'ColorVector', [vl.f32(x) for x in op['rgb']])
        elif k == 'add_template':
            self.need_dict(op)
            src = self.D.template(op['source'])
            nid = op['id']
            if nid >= op.get('max', vl.PARTICLE_EFFECTS_MAX_NUM):
                raise fe.EditError('Specific_ID %d >= PARTICLE_EFFECTS_MAX_NUM (%d): the engine writes '
                                   'DB_PARTICLEDICT_LIST[id] without a bounds check (FUN_008712F0 op 0xB) -> heap '
                                   'overwrite. Use a free id (vfxtool free-ids) or raise_max first.'
                                   % (nid, op.get('max', vl.PARTICLE_EFFECTS_MAX_NUM)))
            if nid in self.D.by_id and not op.get('replace_existing'):
                raise fe.EditError('Specific_ID %d already has a template (%s)' % (nid, [hex(x) for x in self.D.by_id[nid]]))
            fw_op = {'op': 'clone', 'fragment': vl.DICT_FRAGMENT, 'entity': '0x%08X' % src, 'deep': True,
                     'name': op['name'], 'set': {'Specific_ID': nid}}
            self.ops.append(fw_op)
            self.pending_templates[nid] = op['name']
            # per-stage sets on the clone are applied after the clone by stage index (see apply_clone_sets)
            if op.get('set'):
                fw_op['_stage_sets'] = op['set']
                fw_op['_source_stages'] = [n for i, n, c in self.D.stages(src)]
        elif k == 'epic':
            self.need_dict(op)
            self.epic(op)
        elif k == 'point_emitter':
            frag = op['fragment']
            b, kk, doc = vl.fragment_doc(self.raw, self.ext, frag)
            n = doc.find(op['entity'])
            t = doc.type_of(n) or ''
            if t.startswith('generic_particle_emitter'):
                prop = 'EffectNum'
            elif t.startswith('Trigger_Activate_Particle') or t.startswith('cutscene_particle'):
                prop = 'Particle_system'
            elif t.startswith('destructable_object_placeholder'):
                prop = 'Default_particle_effect'
            else:
                raise fe.EditError('entity %s is a %s, not an emitter/trigger with a template number' % (op['entity'], t))
            self.ops.append({'op': 'set', 'fragment': frag, 'entity': '0x%08X' % n, 'prop': prop, 'value': op['template']})
        elif k == 'raise_max':
            if not self.is_main:
                raise fe.EditError('raise_max needs overdose.main')
            b, kk, doc = vl.fragment_doc(self.raw, self.ext, vl.SCENE_FRAGMENT)
            hits = [n for n in doc.created_ids() if doc.type_of(n) == 'common(Node)']
            if len(hits) != 1:
                raise fe.EditError('common(Node) not found once in Overdose.scene')
            self.ops.append({'op': 'set', 'fragment': vl.SCENE_FRAGMENT, 'entity': '0x%08X' % hits[0],
                             'prop': 'PARTICLE_EFFECTS_MAX_NUM', 'value': int(op['value'])})
            self.notes.append('raise_max: PARTICLE_EFFECTS_MAX_NUM set on common(Node); UNVERIFIED in game (the DB '
                              'list is sized from it in FUN_00720C80; the order against the fragment load is inferred)')
        else:
            raise fe.EditError('unknown vfx op %r' % k)

    def epic(self, op):
        """The TOD HD explosion2 recipe (KEEP.md 43.2, epic_patches.py), applied to any template by role."""
        root = self.D.template(op['template'])
        fb, life = op.get('fireball', 1.5), op.get('life', 2.0)
        for i, n, c in self.D.stages(root):
            if c != 'ParticleSystem' or n == root:
                continue
            tex = tex_of(self.doc, n).lower()
            g = lambda p, d=0.0: self.doc.get(n, p) if self.doc.get(n, p) is not None else d
            L, S, br = g('LifeTime'), g('Size'), g('BirthRate')
            if any(tex.startswith(x) for x in SPRITE_TEX) and L >= 0.2 and S >= 1.0:          # fireball
                self.set(n, 'Size', vl.f32(S * fb))
                self.set(n, 'LifeTime', vl.f32(L * life))
                self.set(n, 'FadeOutTime', vl.f32(min(10.0, g('FadeOutTime') * life)))
                if g('Speed'):
                    self.set(n, 'Speed', vl.f32(g('Speed') * 0.5))
                mp = int(g('MaxParticles', 0))
                if mp:
                    self.set(n, 'MaxParticles', max(mp, min(14, int(round(mp * 1.3)))))
            elif (tex.startswith('explosion03') or tex.startswith('fire')) and L < 0.2 and S < 20:   # flash
                self.set(n, 'Size', vl.f32(S * 1.6))
                self.set(n, 'LifeTime', vl.f32(L * 1.5))
                self.set(n, 'FadeOutTime', vl.f32(g('FadeOutTime') * 1.5))
            elif tex.startswith('smoke'):                                                          # smoke
                sl = op.get('smoke_life', 2.2)
                self.set(n, 'LifeTime', vl.f32(max(2.5, min(3.5, L * sl))) if L * sl < 3.5 else vl.f32(L))
                self.set(n, 'FadeOutTime', vl.f32(min(10.0, g('FadeOutTime') * sl)))
                self.set(n, 'Size', vl.f32(S * (1.6 if S < 3 else 1.35)))
                mp = int(g('MaxParticles', 0))
                if 0 < mp <= 5:
                    self.set(n, 'MaxParticles', mp + 2); mp += 2
                el = g('EmitterLifeTime')
                if br == 0 and mp:
                    el2 = max(1.0, el)
                    self.set(n, 'EmitterLifeTime', vl.f32(el2))
                    self.set(n, 'BirthRate', vl.f32(el2 / mp))
                if g('ParticleGravity') < op.get('rise', 2.5):
                    self.set(n, 'ParticleGravity', vl.f32(op.get('rise', 2.5)))
                if g('Speed'):
                    self.set(n, 'Speed', vl.f32(g('Speed') * 0.8))


def split_stage_sets(ops):
    """add_template 'set' maps (stage selector -> {param: value}) target the CLONE's stages. The fragment writer's
    verifier allows only the root's own sets on a clone, so those sets run as a second verified pass on the first
    pass's output block (pass A: clones and every other op; pass B: plain sets on the now existing clone nodes)."""
    a_ops, deferred = [], []
    for op in ops:
        if op.get('_stage_sets'):
            a_ops.append({k: v for k, v in op.items() if not k.startswith('_')})
            deferred.append((op['set']['Specific_ID'], op['_stage_sets']))
        else:
            a_ops.append(op)
    return a_ops, deferred


def run_fragtool(spec, out, deploy=None):
    os.makedirs(out, exist_ok=True)
    fe_path = os.path.join(out, 'fragtool_edit.json')
    json.dump(spec, open(fe_path, 'w'), indent=1)
    rc = ft.cmd_edit(argparse.Namespace(edit=fe_path, out=out, deploy=deploy))
    return rc, json.load(open(os.path.join(out, 'report.json')))


def cmd_edit(a, spec=None):
    spec = spec or json.load(open(a.edit))
    os.makedirs(a.out, exist_ok=True)
    T = vl.types()
    pass_a = {'description': spec.get('description', ''), 'blocks': []}
    deferred_by_entry = {}
    vrep = {'edit': spec, 'blocks': []}
    try:
        for bs in spec['blocks']:
            raw, ent, ext = vl.load_block(bs.get('block'), bs.get('entry'))
            C = Compiler(raw, ext, ent)
            for op in bs['ops']:
                C.compile(op)
            ops, deferred = split_stage_sets(C.ops)
            fb = {'block': bs.get('block') or vl.MAIN_ENTRY, 'ops': ops}
            if bs.get('block') and os.path.exists(bs['block']):
                fb['entry'] = ent
            pass_a['blocks'].append(fb)
            deferred_by_entry[ent] = deferred
            vrep['blocks'].append({'entry': ent, 'notes': C.notes, 'fragment_writer_ops': len(ops),
                                   'new_templates': C.pending_templates, 'deferred_stage_sets': len(deferred)})
    except fe.EditError as e:
        vrep['result'] = 'FAIL: %s' % e
        json.dump(vrep, open(os.path.join(a.out, 'vfx_report.json'), 'w'), indent=1, default=str)
        print(vrep['result'])
        return 1
    if not any(deferred_by_entry.values()):
        rc, rep = run_fragtool(pass_a, a.out, getattr(a, 'deploy', None))
    else:
        rc, rep = run_fragtool(pass_a, os.path.join(a.out, 'pass_a'))
        if rc == 0:
            pass_b = {'description': 'stage sets on added templates', 'blocks': []}
            try:
                for bl in rep['blocks']:
                    ent = bl['entry']
                    ops = []
                    if deferred_by_entry.get(ent):
                        raw2 = open(bl['out'], 'rb').read()
                        b, k, doc = vl.fragment_doc(raw2, os.path.splitext(ent)[1], vl.DICT_FRAGMENT)
                        D = vl.Dict(doc)
                        for sid, sets in deferred_by_entry[ent]:
                            root = D.template(sid)
                            for sel, pv in sets.items():
                                if isinstance(sel, str) and sel.isdigit():
                                    sel = int(sel)
                                n = D.stage(root, sel)
                                for p, v in pv.items():
                                    ops.append({'op': 'set', 'fragment': vl.DICT_FRAGMENT, 'entity': '0x%08X' % n,
                                                'prop': p, 'value': v})
                    pass_b['blocks'].append({'block': bl['out'], 'entry': ent, 'ops': ops})
            except fe.EditError as e:
                print('FAIL: %s' % e)
                return 1
            rc, rep = run_fragtool(pass_b, a.out, getattr(a, 'deploy', None))
    vrep['result'] = rep['result']
    if rep['result'] == 'PASS':
        for bl, vb in zip(rep['blocks'], vrep['blocks']):
            if not bl['entry'].lower().endswith('overdose.main'):
                continue
            raw2 = open(bl['out'], 'rb').read()
            b, k, doc = vl.fragment_doc(raw2, '.main', vl.DICT_FRAGMENT)
            D = vl.Dict(doc)
            vb['readback'] = {}
            for nid, name in vb['new_templates'].items():
                root = D.template(int(nid))
                vb['readback'][str(nid)] = {'name': doc.get(root, 'name'), 'node': '0x%08X' % root,
                                            'stages': len(D.stages(root))}
            vb['out_sha256'] = bl['out_sha256']
    json.dump(vrep, open(os.path.join(a.out, 'vfx_report.json'), 'w'), indent=1, default=str)
    for vb in vrep['blocks']:
        for n in vb['notes']:
            print('note:', n)
        if vb.get('readback'):
            print('readback:', json.dumps(vb['readback']))
    print('VFX EDIT', vrep['result'])
    return rc


def cmd_hdpatch(a):
    """Same-length subset of a vfx edit as TOD HD entity patches ({block: [{fragment, node, prop, new, expect, why}]},
    the shape of TOD HD's work/install_combined/entity_patches_batch4.json): one u32 word per patch, expect = the
    shipped word. Refuses ops that are not plain one-word sets of an existing record (clones, strings, vectors)."""
    spec = json.load(open(a.edit))
    T = vl.types()
    out = {}
    for bs in spec['blocks']:
        raw, ent, ext = vl.load_block(bs.get('block'), bs.get('entry'))
        C = Compiler(raw, ext, ent)
        for op in bs['ops']:
            C.compile(op)
        lst = out.setdefault(ent.split('/')[-1], [])
        for op in C.ops:
            if op['op'] != 'set':
                raise fe.EditError('hdpatch: %s is not a one-word set (TOD HD entity patches cannot add records)' % op['op'])
            b, k, doc = vl.fragment_doc(raw, ext, op['fragment'])
            n = doc.find(op['entity'])
            pidx = T.index(op['prop'])
            t = T.parse(T.ptype(pidx))
            hits = [r for r in doc.records if r.op == tf.SET and r.node == n and r.prop == pidx]
            if not hits or len(hits[-1].raw) != 4:
                raise fe.EditError('hdpatch: %s of %s is not an existing one-word record' % (op['prop'], op['entity']))
            new = tf.encode_value(float(op['value']) if t == ('simple', 'number') else op['value'], t)
            if len(new) != 4:
                raise fe.EditError('hdpatch: %s value is not one word' % op['prop'])
            frag = op['fragment'] if op['fragment'].endswith('.fragment') else doc.name.split('/')[-1]
            if new == hits[-1].raw[:4]:
                continue
            lst.append({'fragment': doc.name.split('/')[-1], 'node': n, 'prop': pidx,
                        'new': struct_u32(new), 'expect': struct_u32(hits[-1].raw),
                        'why': 'vfxtool %s: %s %s -> %r' % (os.path.basename(a.edit), op['entity'], op['prop'], op['value'])})
    json.dump(out, open(a.o, 'w'), indent=1)
    print('wrote', a.o, {k: len(v) for k, v in out.items()})
    return 0


def struct_u32(b):
    return int.from_bytes(b[:4], 'little')


# ------------------------------------------------------------------ round trip
def vfx_reset_roundtrip(raw, ext):
    """Set every parameter of every ParticleDict entity to its own decoded value through FragDoc.set_prop
    (the same path edits use) and rebuild: the block must come out byte-identical."""
    T = vl.types()
    b, k, doc = vl.fragment_doc(raw, ext, vl.DICT_FRAGMENT)
    n_sets = 0
    changed = 0
    # FragDoc.set_prop keeps a record's original bytes when mask_string_padding(old raw) == encode(new value);
    # check that condition for every record directly (same test, without the per-call list scan), then rebuild
    # the fragment through the editor's rechunk + serialize path.
    for r in doc.records:
        if r.op != tf.SET:
            continue
        t = T.parse(T.ptype(r.prop))
        v = tf.decode_value(r.raw, 0, t)
        if tf.mask_string_padding(r.raw, 0, t) != tf.encode_value(v, t):
            changed += 1
        n_sets += 1
    doc.modified = True                      # force the rebuild path (rechunk + serialize) as an edit would
    nb = tb.Block(raw, ext)
    nb.payloads[k] = doc.payload()
    out = nb.serialize()
    return n_sets, changed != 0, out == raw


def cmd_roundtrip(a):
    T = vl.types()
    raw, ent, ext = vl.load_block(a.block, a.entry)
    r = ft.roundtrip_block(raw, ext, T)
    print(ent, json.dumps({k: v for k, v in r.items()}))
    n, mod, same = vfx_reset_roundtrip(raw, ext) if ent.lower().endswith('.main') else (0, False, True)
    print('ParticleDict re-set of every value: %d sets, modified=%s, block identical=%s' % (n, mod, same))
    ok = not r['fail'] and r['block_identical'] and same
    if a.all_fx:
        refs = load_refs()
        blocks = sorted({x['block'] for x in refs})
        arch = tb.open_naz()
        bad = 0
        for bn in blocks:
            name = [nm for nm in arch.names if nm.lower().endswith('/' + bn.lower())][0]
            rr = ft.roundtrip_block(arch.read(name), os.path.splitext(name)[1], T)
            bad += bool(rr['fail'] or not rr['block_identical'])
        print('blocks holding effect references: %d, not identical: %d' % (len(blocks), bad))
        ok = ok and bad == 0
    print('ROUNDTRIP', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


# ------------------------------------------------------------------ selftest
def cmd_selftest(a):
    out = a.out or os.path.join(tempfile.gettempdir(), 'vfx_selftest')
    os.makedirs(out, exist_ok=True)
    res = {}
    raw, ent, ext = vl.load_block(None)
    T = vl.types()
    r = ft.roundtrip_block(raw, ext, T)
    res['overdose.main fragment round trip'] = not r['fail'] and r['block_identical']
    n, mod, same = vfx_reset_roundtrip(raw, ext)
    res['ParticleDict re-set %d values -> identical' % n] = same and not mod
    # kept(): the emulated setter/getter agree with the formula ports for a few known values
    res['kept LifeTime 100 -> 80 (clamp)'] = abs(kept('LifeTime', 100.0) - 80.0) < 0.1
    res['kept FadeInTime 10 -> 5 (clamp)'] = abs(kept('FadeInTime', 10.0) - 5.0) < 0.05
    res['kept MaxParticles 7 -> 7'] = kept('MaxParticles', 7) == 7
    # one edit of each kind on overdose.main
    spec = {'description': 'selftest', 'blocks': [{'block': 'overdose.main', 'ops': [
        {'op': 'set_param', 'template': 188, 'stage': 1, 'param': 'Size', 'value': 7.5},
        {'op': 'scale_param', 'template': 188, 'stage': '*', 'param': 'LifeTime', 'factor': 2.0, 'max': 80.0},
        {'op': 'set_texture', 'template': 188, 'stage': 1, 'texture': 'Explosion04.bmp'},
        {'op': 'set_color', 'template': 188, 'stage': 1, 'rgb': [0.3, 1.0, 0.3]},
        {'op': 'add_template', 'source': 11, 'id': 19, 'name': 'Fire_Big_Selftest', 'set': {'1': {'ColorVector': [0.2, 0.4, 1.0]}}},
    ]}]}
    ns = argparse.Namespace(out=os.path.join(out, 'edit_main'), deploy=None)
    rc = cmd_edit(ns, spec)
    res['edit overdose.main (set/scale/texture/color/add_template) verified'] = rc == 0
    if rc == 0:
        raw2 = open(os.path.join(out, 'edit_main', 'overdose.main'), 'rb').read()
        b, k, doc = vl.fragment_doc(raw2, '.main', vl.DICT_FRAGMENT)
        D = vl.Dict(doc)
        r188 = D.template(188)
        s1 = D.stage(r188, 1)
        res['readback 188 stage 1 Size 7.5'] = abs(doc.get(s1, 'Size') - 7.5) < 1e-6
        res['readback 188 stage 1 texture'] = doc.get(s1, 'Texture') == '/Textures/Sprites/Explosion04.bmp'
        n19 = D.template(19)
        res['readback new template 19 registered under ParticleDict'] = doc.get(n19, 'name') == 'Fire_Big_Selftest' \
            and len(D.stages(n19)) == len(D.stages(D.template(11)))
        res['new template 19 stage 1 colour'] = [round(x, 3) for x in doc.get(D.stage(n19, 1), 'ColorVector')] == [0.2, 0.4, 1.0]
    # point a placed emitter in a map block at the new id
    refs = [x for x in load_refs() if x['prop'] == 'EffectNum' and x['block'].startswith('submap01_map02')]
    if refs:
        x = refs[0]
        spec2 = {'blocks': [{'block': x['block'], 'ops': [{'op': 'point_emitter', 'fragment': x['fragment'],
                                                           'entity': x['node'], 'template': 19}]}]}
        rc2 = cmd_edit(argparse.Namespace(out=os.path.join(out, 'edit_map'), deploy=None), spec2)
        res['point_emitter in %s verified' % x['block']] = rc2 == 0
    # refusals
    try:
        Compiler(raw, ext, ent).compile({'op': 'add_template', 'source': 11, 'id': 228, 'name': 'x'})
        res['refuses id 228'] = False
    except fe.EditError:
        res['refuses id 228'] = True
    try:
        Compiler(raw, ext, ent).compile({'op': 'set_texture', 'template': 188, 'stage': 1, 'texture': 'NoSuch.bmp'})
        res['refuses missing texture'] = False
    except fe.EditError:
        res['refuses missing texture'] = True
    ok = all(res.values())
    for k2, v in res.items():
        print('%-70s %s' % (k2, 'ok' if v else 'FAIL'))
    print('SELFTEST', 'PASS' if ok else 'FAIL')
    json.dump(res, open(os.path.join(out, 'selftest.json'), 'w'), indent=1)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    def blk(p):
        p.add_argument('--block'); p.add_argument('--entry')
    p = sp.add_parser('list'); blk(p); p.add_argument('--filter')
    p = sp.add_parser('show'); blk(p); p.add_argument('template'); p.add_argument('--kept', action='store_true')
    p = sp.add_parser('uses'); blk(p); p.add_argument('template')
    p = sp.add_parser('kept'); p.add_argument('param'); p.add_argument('value'); p.add_argument('--class', dest='cls', default='ParticleSystem')
    p = sp.add_parser('free-ids'); blk(p)
    p = sp.add_parser('roundtrip'); blk(p); p.add_argument('--all-fx', action='store_true')
    p = sp.add_parser('edit'); p.add_argument('edit'); p.add_argument('--out', required=True); p.add_argument('--deploy')
    p = sp.add_parser('selftest'); p.add_argument('--out')
    p = sp.add_parser('hdpatch'); p.add_argument('edit'); p.add_argument('-o', required=True)
    a = ap.parse_args()
    try:
        import lowprio  # noqa: F401
    except Exception:
        pass
    return {'list': cmd_list, 'show': cmd_show, 'uses': cmd_uses, 'kept': cmd_kept, 'free-ids': cmd_free,
            'roundtrip': cmd_roundtrip, 'edit': cmd_edit, 'selftest': cmd_selftest, 'hdpatch': cmd_hdpatch}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
