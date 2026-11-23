"""Print the absolute values every built-in driving preset writes, for every shipped vehicle and the car-wide fields.

  python scripts/print_driving_presets.py [--values vehvals.json] [--preset drift] [--out values.json]

Reads backend/data/driving_presets.json (the one source the editor and other tools share). The shipped values come from the
user's own game through the Vehicles data editor (a game folder must be set), or from a JSON of {key: [value, source]} /
{key: value} given with --values. Output: {preset id: {"type.<Vehicle>.<field>": number, "car.<field>": number}} for the target
"All cars"; a key missing from a preset's output keeps the game's value. Same rules as frontend/src/tune/presets.js
(planApply): mul / add act on the shipped value, set is absolute, a zero value stays zero under mul / add, results are
clamped to the field range, a value equal to the shipped one is left out."""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), 'backend', 'data', 'driving_presets.json')


def load():
    with open(DATA, encoding='utf-8') as f:
        d = json.load(f)
    assert d.get('format') == 'todms-driving-preset' and d.get('version') == 1
    return d


def _r6(n):
    return round(n * 1e6) / 1e6


def plan_all(d, preset, shipped):
    """-> {key: value} the preset writes for every vehicle of every class and the shared car fields."""
    out = {}
    rows = [r for rows in d['classes'].values() for r in rows]
    for row in rows:
        for prop, spec in (preset.get('type') or {}).items():
            f = d['fields']['type'].get(prop)
            key = 'type.%s.%s' % (row, prop)
            base = shipped.get(key)
            if f is None or not isinstance(base, (int, float)):
                continue
            if 'set' in spec:
                v = spec['set']
            elif 'mul' in spec:
                v = base * spec['mul']
            elif 'add' in spec:
                v = base + spec['add']
            else:
                continue
            if base == 0 and 'set' not in spec:
                continue
            v = _r6(min(f['hi'], max(f['lo'], v)))
            if abs(v - base) >= 1e-9:
                out[key] = v
    for prop, spec in (preset.get('car') or {}).items():
        f = d['fields']['car'].get(prop)
        if f is None or 'set' not in spec:
            continue
        v = _r6(min(f['hi'], max(f['lo'], spec['set'])))
        base = shipped.get('car.' + prop)
        if not (isinstance(base, (int, float)) and abs(v - base) < 1e-9):
            out['car.' + prop] = v
    return out


def shipped_from_game():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'backend'))
    from todms import workspace, paths, dataed
    paths.ensure_cpu_guard()
    ws = workspace.Workspace()
    g = ws.settings.get('game_folder') if hasattr(ws, 'settings') else None
    if g:
        ws.set_game(g)
    res = dataed.vehicles_read(ws)
    return {f['key']: f['value'] for grp in res['groups'] for f in grp['fields'] if isinstance(f['value'], (int, float))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--values'); ap.add_argument('--preset'); ap.add_argument('--out')
    a = ap.parse_args()
    d = load()
    if a.values:
        raw = json.load(open(a.values, encoding='utf-8'))
        shipped = {k: (v[0] if isinstance(v, list) else v) for k, v in raw.items()}
    else:
        shipped = shipped_from_game()
    res = {}
    for p in d['presets']:
        if p.get('restore') or (a.preset and p['id'] != a.preset):
            continue
        res[p['id']] = plan_all(d, p, shipped)
    text = json.dumps(res, indent=1) + '\n'
    if a.out:
        open(a.out, 'w', encoding='utf-8', newline='\n').write(text)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
