r"""Mine the character model table from a game folder (read only): which block carries which character model, the
resource node that registers it, and how the shipped placeholders use each model (behaviour, side, texture set).
Writes backend/todms/data/characters_mined.json; run after a game data change only (the retail data never changes).
Usage: python scripts/mine_characters.py GAME_FOLDER
"""
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
os.environ.setdefault('TODMS_HOME', os.path.join(os.environ.get('TEMP', '.'), 'mine_home'))
os.environ.setdefault('TODMS_CACHE', os.environ['TODMS_HOME'])
from todms import workspace, paths  # noqa: E402

paths.ensure_cpu_guard()


def main(game):
    ws = workspace.Workspace()
    ws.set_game(game)
    import todblock as tb
    import fragtool as ft
    import fragedit as fe
    ents = sorted(n for n in ws.game.names() if n.lower().endswith(('.mission', '.submap', '.map', '.main')))
    models = collections.defaultdict(lambda: dict(paths=set(), blocks={}, uses=collections.Counter(), textures=collections.Counter()))
    for e in ents:
        try:
            raw, _ = ws.read_block(e)
            ext = os.path.splitext(e)[1]
            b = tb.Block(raw, ext)
            frs, _ = ft.fragments(b)
        except Exception as ex:
            print('skip', e, ex)
            continue
        short = e.split('/')[-1]
        for k, nm in frs:
            try:
                d = fe.FragDoc(b.payloads[k], ws.T, nm)
            except Exception:
                continue
            for n in d.created_ids():
                t = d.type_of(n) or ''
                if t.startswith('database_model_resource') and d.get(n, 'Sub_Type') == 1 and d.get(n, 'Character_Model') is not None:
                    N = int(d.get(n, 'Character_Model'))
                    mp = str(d.get(n, 'modelres') or '').lower()
                    models[N]['paths'].add(mp)
                    models[N]['blocks'][short] = dict(entry=e, frag=nm.replace(chr(92), '/').split('/')[-1], node='0x%08X' % n, path=mp)
                elif t.startswith('character_placeholder'):
                    m, ai, fc = d.get(n, 'Model'), d.get(n, 'AISubType'), d.get(n, 'FactionID')
                    if m is not None:
                        models[int(m)]['uses']['%s|%s' % (ai, fc)] += 1
                        models[int(m)]['textures'][str(d.get(n, 'Real_Active_Texture_Set') or 0)] += 1
    out = {}
    for N, v in sorted(models.items()):
        out[str(N)] = dict(paths=sorted(v['paths']), blocks=v['blocks'], uses=dict(v['uses'].most_common()), textures=dict(v['textures'].most_common()))
    p = os.path.join(ROOT, 'backend', 'todms', 'data', 'characters_mined.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', newline='\n') as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write('\n')
    print('models', len(out), 'blocks scanned', len(ents))


if __name__ == '__main__':
    main(sys.argv[1])
