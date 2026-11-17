"""End-to-end proof of mod compatibility on a private hard-linked game copy (never launches the game).

  python -I scripts/proof_mods.py GAME_COPY WORK_DIR

Two mods edit different weapon values of overdose.main: both apply. A third sets the same value as the first: the later one in the load
order wins, and swapping the order swaps the winner. A profile switch rebuilds the pack from the other list (a save copy is made first).
A mod that needs Gameplay+ is refused with a plain message. Every step is installed into GAME_COPY through the pack and read back from
todms_pack.zip. Writes WORK_DIR/proof_mods.json.
"""
import json
import os
import sys
import zipfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)

game, work = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
os.environ.setdefault('TODMS_HOME', os.path.join(work, 'home'))
os.environ.setdefault('TODMS_CACHE', os.path.join(work, 'cache'))
os.environ.setdefault('TODMS_SAVES', os.path.join(work, 'saves'))
os.makedirs(os.environ['TODMS_SAVES'], exist_ok=True)
with open(os.path.join(os.environ['TODMS_SAVES'], 'slot1'), 'wb') as f:
    f.write(b'proof save')

from todms import workspace, mods, dataed, compat, profiles, snapshots, game as G, paths   # noqa: E402

paths.ensure_cpu_guard()
log = {}


def say(*a):
    print(*a, flush=True)


ws = workspace.Workspace()
ws.set_game(game)
say('game', ws.game.folder)


def pack_values():
    z = zipfile.ZipFile(os.path.join(game, G.PACK_ZIP))
    raw = z.read(G.MAIN_ENTRY)
    d = dataed.weapons_read(SimpleNamespace(read_block=lambda e: (raw, 'pack')))
    return {f['key']: f['value'] for g in d['groups'] for f in g['fields']}


base = dataed.weapons_read(ws)
fields = {f['label']: f for g in base['groups'] for f in g['fields'] if f['key'].startswith('weapons.')}
gun = next(f['key'].split('.')[1] for g in base['groups'] for f in g['fields'] if f['label'] == 'ClipSize' and f['key'].startswith('weapons.'))
CLIP, RELOAD = 'weapons.%s.ClipSize' % gun, 'weapons.%s.ReloadTime' % gun
clip0 = next(f['value'] for g in base['groups'] for f in g['fields'] if f['key'] == CLIP)
rel0 = next(f['value'] for g in base['groups'] for f in g['fields'] if f['key'] == RELOAD)
say('weapon', gun, 'clip', clip0, 'reload', rel0)


def mk(name, data, **kw):
    m = dict(format='todms-mod', version=1, name=name, author='proof', description='', level=[], data={'weapons': data}, view=None, **kw)
    return mods.save_mod(m)['id']


A = mk('Big clip', {CLIP: 77})
B = mk('Slow reload', {RELOAD: round(rel0 + 1.0, 3)})
C = mk('Small clip', {CLIP: 33})
D = mk('Needs Gameplay+', {CLIP: 12}, requires=dict(gameplay_plus=True))

# ---- 1. A and B both edit overdose.main: both apply
mods.set_state([A, B, C, D], [A, B])
cf = mods.conflict_report()
log['conflicts_AB'] = cf['counts']
mods.install(ws)
v = pack_values()
log['AB'] = {CLIP: v[CLIP], RELOAD: v[RELOAD]}
assert v[CLIP] == 77 and abs(v[RELOAD] - (rel0 + 1.0)) < 1e-3, v
say('A+B both apply:', log['AB'], 'clashes:', cf['counts'])

# ---- 2. C sets the same value as A: the later mod in the list wins
mods.set_state([A, B, C, D], [A, B, C])
cf = mods.conflict_report()
log['conflicts_ABC'] = dict(cf['counts'], first=cf['clashes'][0]['label'], winner=cf['clashes'][0]['winner'] == C)
mods.install(ws)
v = pack_values()
log['ABC'] = {CLIP: v[CLIP], RELOAD: v[RELOAD]}
assert v[CLIP] == 33 and abs(v[RELOAD] - (rel0 + 1.0)) < 1e-3, v
say('A,B,C: C wins the clip:', log['ABC'])

# ---- 3. swapping the order swaps the winner
mods.set_state([C, A, B, D], [C, A, B])
cf = mods.conflict_report()
log['swap_winner'] = cf['clashes'][0]['winner'] == A
mods.install(ws)
v = pack_values()
log['CAB'] = {CLIP: v[CLIP], RELOAD: v[RELOAD]}
assert v[CLIP] == 77, v
say('C,A,B: A wins the clip:', log['CAB'])

# ---- 4. a mod that needs Gameplay+ is refused before anything is written
mods.set_state([C, A, B, D], [C, A, B, D])
before = open(os.path.join(game, 'configpc.txt'), 'rb').read()
try:
    mods.install(ws)
    raise SystemExit('the dependency check did not refuse')
except ValueError as e:
    log['refusal'] = str(e)
    say('refused:', e)
assert open(os.path.join(game, 'configpc.txt'), 'rb').read() == before

# ---- 5. profiles: Main = [C, A, B], Alt = [B, C]
mods.set_state([C, A, B, D], [C, A, B])
profiles.listing()
profiles.create('Alt')
profiles.switch(ws, 'Alt', rebuild=False)
mods.set_state([B, C, A, D], [B, C])
profiles.switch(ws, 'Main', rebuild=False)
open(os.path.join(os.environ['TODMS_SAVES'], 'slot1'), 'wb').write(b'proof save, played on')
r = profiles.switch(ws, 'Alt')
v = pack_values()
log['alt'] = dict(active=profiles.listing()['active'], values={CLIP: v[CLIP], RELOAD: v[RELOAD]}, snapshot=bool(r['snapshot']))
assert v[CLIP] == 33 and abs(v[RELOAD] - (rel0 + 1.0)) < 1e-3, v
say('profile Alt:', log['alt'])
profiles.switch(ws, 'Main')
v = pack_values()
log['main'] = dict(active=profiles.listing()['active'], values={CLIP: v[CLIP], RELOAD: v[RELOAD]})
assert v[CLIP] == 77, v
say('profile Main:', log['main'])
log['snapshots'] = [s['label'] for s in snapshots.list_snapshots()]
log['variant'] = compat.variant(ws.game)
json.dump(log, open(os.path.join(work, 'proof_mods.json'), 'w'), indent=1, default=str)
say('OK', json.dumps(log['variant']))
