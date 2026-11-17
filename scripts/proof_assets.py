"""End-to-end proof of model import / replace and the texture editor on a private hard-linked game copy (never launches the game).

  python -I scripts/proof_assets.py GAME_COPY WORK_DIR

Builds a mod with one imported model placed in a level, one replaced prop and one replaced texture, installs it through the pack
(todms_pack.zip + configpc.txt), then reads the installed archive back: every other record of every block is byte-identical to blocks.naz,
the written model and texture records decode to what was planned, the placed copy is in the level, and the baked lighting of the replaced prop is found again under its new counts. Writes WORK_DIR/proof.json.
"""
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, os.path.join(ROOT, 'backend', 'tests'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)

game, work = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
os.environ['TODMS_HOME'] = os.path.join(work, 'home')
os.environ['TODMS_CACHE'] = os.path.join(work, 'cache')
os.environ['TODMS_SAVES'] = os.path.join(work, 'saves')

import glbfix                                                   # noqa: E402
from todms import workspace, mods, imports, assetedit, assetindex, assets_stage, game as G, paths   # noqa: E402
from todct import texture as TX                                 # noqa: E402

paths.ensure_cpu_guard()
PROP = '/data/models/addons/weaponammocrate/weaponammocratewoodopen.model'
TEX = '/data/textures/materials/final_ingame_textures/waste_bin.bmp'
TRAINING = 'submap05_map02_lostoros_downtown_training.submap'
log = []


def say(*a):
    s = ' '.join(str(x) for x in a)
    log.append(s)
    print(s, flush=True)


ws = workspace.Workspace()
ws.set_game(game)
say('game', ws.game.folder, 'chain', ws.game.chain())
assetindex.build(ws)
doc = assetindex.load(ws)

# ---- the three changes
barrel = glbfix.write_barrel_glb(os.path.join(work, 'barrel.glb'))
crate = glbfix.write_box_glb(os.path.join(work, 'crate.glb'), size=(1.5, 0.6, 1.5), centre=(0, 0.3, 0))
pic = os.path.join(work, 'green.png')
open(pic, 'wb').write(glbfix.checker_png(64, (30, 160, 60), (10, 60, 20)))


def entry(path, **kw):
    a = imports.analyze(path)
    return imports.entry(ws, dict(sha=a['sha'], file=os.path.basename(path), **kw))['entry']


new = entry(barrel, mode='new', name='Proof barrel', params=dict(max_tex=128))
rep_ = entry(crate, mode='replace', target=PROP, name='Proof crate', params=dict(origin='match', max_tex=64))
up = imports.upload(pic)
r = doc['textures'][TEX]
tex = dict(id='tproof', target=TEX, source=dict(sha=up['sha'], file='green.png'), crop=None, w=r['w'], h=r['h'], fmt=r['fmt'], edits=dict(brightness=0.05))

entry_blk = next(e for e in ws.game.base().names if e.endswith(TRAINING))
L = ws.level_json(entry_blk)
tpl = next(x for x in L['entities'] if x['cat'] == 'model' and x['ed'] and x['type'] == 'Model')
pos = [tpl['pos'][0] + 2.0, tpl['pos'][1], tpl['pos'][2]]
add = dict(op='add', uid='n1', entry=entry_blk, template=dict(entry=entry_blk, frag=tpl['frag'], node=tpl['node']), name='TODMS_proof_barrel', pos=pos,
           rot=[0, 0, 0, 1], set=dict(modelres=new['path'][5:]), view=dict(type='Model', cat='model', kindLabel='Model', name='Proof barrel'))
mod = mods.save_mod(dict(name='Proof assets', level=[add], data={}, models=[new, rep_], textures=[tex]))
say('mod', mod['id'], 'version', mod['version'])
mods.set_state(enabled=[mod['id']])

# ---- install through the pack
res = mods.install(ws, progress=lambda *a: None)
say('installed', res['zip'], res['configpc_line'])
folder = ws.game.folder
pack = os.path.join(folder, G.PACK_ZIP)
assert os.path.exists(pack)
z = zipfile.ZipFile(pack)
names = z.namelist()
say('pack entries', [n.split('/')[-1] for n in names], os.path.getsize(pack), 'bytes')

# ---- read it back
k = assetedit.K()
G_ = assetedit.hd()
out = dict(entries={})
base = ws.game.base()
for n in names:
    new_raw = z.read(n)
    old_raw = base.read(n)
    ext = os.path.splitext(n)[1]
    ra = assetedit.Records(k.tb, k.tb.Block(old_raw, ext))
    rb = assetedit.Records(k.tb, k.tb.Block(new_raw, ext))
    differ = [a['name'] for a, b in zip(ra.items, rb.items) if a['rec'] != b['rec'] or a['payload'] != b['payload']]
    appended = [it['name'] for it in rb.items[len(ra.items):]]
    G_.Block(new_raw, ext)                                                      # strict reader
    out['entries'][n.split('/')[-1]] = dict(records_before=len(ra.items), records_after=len(rb.items), identical=len(ra.items) - len(differ),
                                            changed=differ, appended=appended, max_asset=k.tb.Block(new_raw, ext).max_asset)
    say(n.split('/')[-1], 'records', len(ra.items), '->', len(rb.items), 'identical', len(ra.items) - len(differ), 'changed',
        [d.split('/')[-1] for d in differ], 'added', [d.split('/')[-1] for d in appended])
    # the level fragment that places the replaced prop (statically_lit off) and the added node's fragment change on purpose
    ok = all(d.lower() in (PROP, TEX) or d.lower().startswith('/data/models/todms/') or d.lower().endswith(('.fragment', '.lighting')) for d in differ + appended)
    assert ok, 'an unexpected record changed'

# the imported model is in the level, the replaced prop is new geometry, the texture decodes to the planned picture
from todms import level as lv, extract                                          # noqa: E402
raw = z.read(next(n for n in names if n.endswith(TRAINING)))
L2 = lv.BlockLevel(entry_blk, raw, ws.T, ws.main_lookup)
placed = []
for i in L2.instances:
    d = L2.doc(i.frag)
    try:
        mr = d.get(i.node, 'modelres')
    except KeyError:
        continue
    if mr and mr.lower() == new['path'][5:].lower():
        placed.append(dict(lit=d.get(i.node, 'statically_lit'), pos=[round(x, 3) for x in d.world(i.node, i.owner)[0]]))
say('placed copies of the imported model', placed)
assert len(placed) == 1 and not placed[0]['lit']
ba = extract.BlockAssets(raw, '.submap')
glb, meta = ba.model_glb(new['path'].lower())
say('imported model reads back: render triangles', meta['render_tris'], 'textures', meta['textures'])
for n in names:
    if not n.endswith(('.map', '.submap')):
        continue
    ext = os.path.splitext(n)[1]
    ba2 = extract.BlockAssets(z.read(n), ext)
    if PROP in ba2.models:
        glb, meta = ba2.model_glb(PROP)
        say(n.split('/')[-1], 'replaced prop: render triangles', meta['render_tris'], 'textures', meta['textures'])
        assert meta['render_tris'] == 12
# baked lighting of the replaced prop, read back from the installed pack: every placed copy still has its flag and its lighting entry is
# found by the engine's own search under the NEW vertex and index counts (the old counts no longer hit)
from todms import lightfit                                                      # noqa: E402
HL = lightfit.hl()
fitted = 0
for n in names:
    if not n.endswith(('.map', '.submap')):
        continue
    ext = os.path.splitext(n)[1]
    data = z.read(n)
    if PROP not in extract.BlockAssets(data, ext).models:
        continue
    geo_new = lightfit.model_geometry(HL, data, ext, PROP)
    geo_old = lightfit.model_geometry(HL, base.read(n), ext, PROP)
    nv, ni = geo_new['pivots'][0][0]
    L3 = lv.BlockLevel(n, data, ws.T, ws.main_lookup)
    uids = set()
    for i in L3.instances:
        d = L3.doc(i.frag)
        try:
            mr = d.get(i.node, 'modelres')
        except KeyError:
            continue
        if mr and lv.norm_model(mr) == PROP:
            assert d.get(i.node, 'statically_lit') is True, 'a placed copy lost its baked-lighting flag'
            uids.add((d.get(i.node, 'unique_id0'), d.get(i.node, 'unique_id1')))
    recs = HL.lighting_records(data, ext)
    owners = HL.instance_owners(data, ext)
    hit = set()
    for rec in recs:
        for inst, models in owners['records'][rec['index']].items():
            if models != (HL.model_key(PROP),):
                continue
            e = HL.engine_lookup(rec, inst, 0, 0, nv, ni, True)
            if e < 0:
                e = HL.engine_lookup(rec, inst, 0, 0, nv, ni, False)
            assert e >= 0, 'instance %d: the new counts do not find a lighting entry' % inst
            assert HL.engine_lookup(rec, inst, 0, 0, geo_old['pivots'][0][0][0], geo_old['pivots'][0][0][1], True) < 0
            hit.add(inst)
    say(n.split('/')[-1], 'baked lighting fitted: %d instances found under the new counts (%d, %d), %d placed copies, flags kept' % (len(hit), nv, ni, len(uids)))
    assert hit and len(uids) >= 1
    fitted += len(hit)
assert fitted > 0
out['lighting_instances_fitted'] = fitted
want, cut = assets_stage.render_texture(ws, tex)
for n in names:
    ext = os.path.splitext(n)[1]
    blk = G_.Block(z.read(n), ext)
    for rec in blk.textures():
        if rec['name'].lower() == TEX:
            got = TX.decode_payload(blk.payloads[rec['index']], G_.FMT_NAME[rec['fmt']], rec['w'], rec['h'])
            say(n.split('/')[-1], 'texture', rec['w'], rec['h'], G_.FMT_NAME[rec['fmt']], 'psnr vs plan', TX.psnr(want, got))
            assert TX.psnr(want, got) > 30
# the game's own blocks are untouched and the line lists the pack first
cfg = G.read_configpc(folder)
say('configpc', G.filesystem_line(cfg))
assert G.filesystem_line(cfg)[0] == G.PACK_ZIP
json.dump(dict(log=log, out=out, placed=placed), open(os.path.join(work, 'proof.json'), 'w'), indent=1)
say('PASS')
