"""Read the lighting, fog, sky and screen-effect nodes of every shipped map block and save them as backend/data/look_presets.json.

  python scripts/extract_look_presets.py GAME_FOLDER [OUT.json]

Read-only: it opens the game's blocks through the workspace readers (cache and home come from TODMS_CACHE / TODMS_HOME).
The values are exactly the ones the game ships (raw property ids are named by the project's property table).
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'backend'))
for p in os.environ.get('PYTHONPATH', '').split(os.pathsep):
    if p and p not in sys.path:
        sys.path.append(p)

game = sys.argv[1]
out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'backend', 'data', 'look_presets.json')

from todms import workspace, paths   # noqa: E402

paths.ensure_cpu_guard()
ws = workspace.Workspace()
ws.set_game(game)
names = [n for n in ws.game.base().names if '/shared/' in n and n.endswith(('.map', '.submap'))]

LIGHT_KINDS = {1: 'ambient', 2: 'directional', 3: 'point'}
SKY_NAMES = {}


def r(v, k=4):
    if isinstance(v, (list, tuple)):
        return [r(x, k) for x in v]
    return round(float(v), k) if isinstance(v, float) else v


def short(entry):
    return entry.split('/')[-1]


blocks = {}
for entry in sorted(names):
    L = ws.level_json(entry)
    BL = ws.block_level(entry)
    item = dict(lights=[], sky=[], fog=[], gfx=[], fog_triggers=0)
    for x in L['entities']:
        t = x['type']
        if not any(s in t for s in ('default_global_light', 'SkyBox', 'FOG_Controller', 'default_GFX', 'Trigger_Activate_Fog')):
            continue
        if 'Trigger_Activate_Fog' in t:
            item['fog_triggers'] += 1
            continue
        nm, _ = BL._resolve(x['frag'])
        d = BL.doc(nm)
        n = int(x['node'], 16)
        g = lambda p, d=d, n=n: d.get(n, p)
        base = dict(node=x['node'], fragment=x['frag'])
        if 'default_global_light' in t:
            item['lights'].append(dict(base, kind=LIGHT_KINDS.get(g('light_type'), str(g('light_type'))), color=r(g('light_color_rgb')),
                                       static_color=r(g('static_color_rgb')), brightness=r(g('Brightness')), range=r(g('range')),
                                       orient=r(g('orient')), dynamic_emission=bool(g('dynamic_emission')), static_emission=bool(g('static_emission'))))
        elif t == 'SkyBox':
            item['sky'].append(dict(base, model=g('modelres'), opacity=r(g('opacity')), flags=g('flags')))
        elif 'FOG_Controller' in t:
            item['fog'].append(dict(base, type=g('fog_type'), start=r(g('start')), end=r(g('end')), density=r(g('density')), color=r(g('color_rgb'))))
        elif 'default_GFX' in t:
            item['gfx'].append(dict(base, brightness=r(g('default_brightness')), saturation=r(g('default_saturation')),
                                    light_bleeding=r(g('default_LightBleeding')), vignette=r(g('default_VignetteIntensity'))))
    if any(item[k] for k in ('lights', 'sky', 'fog', 'gfx')):
        blocks[short(entry)] = item
        print(short(entry), {k: len(v) if isinstance(v, list) else v for k, v in item.items()})

skies = {}
for b, it in blocks.items():
    for s in it['sky']:
        m = s['model']
        sid = m.split('/')[-3] if m.count('/') >= 3 else m
        skies.setdefault(sid, dict(id=sid, model=m, used_by=[]))['used_by'].append(b)

doc = dict(version=1, note='Shipped lighting, fog, sky and screen-effect nodes per map block, read from the game files.',
           blocks=blocks, skies=sorted(skies.values(), key=lambda s: s['id']))
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(doc, f, indent=1, sort_keys=False)
print('wrote', out_path, len(blocks), 'blocks', len(skies), 'skies')
