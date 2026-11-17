"""Look: sun, ambient light, fog, sky and screen tone of a map, from a preset of the shipped maps or explicit values, plus the function
that writes them into the nodes of a new map's block.

Recipe key `look`:
  {"preset": "clear_day",                       one of presets() (the shipped maps' own settings), optional
   "sun": {"color": [r, g, b], "brightness": 2.0, "azimuth": 120, "elevation": 35, "orient": [x, y, z, w]},
   "ambient": {"color": [r, g, b], "brightness": 0.6},
   "fog": {"color": [r, g, b], "near": 100, "far": 700},
   "sky": "ClearBlueSky",                       one of skies()
   "screen": {"brightness": 1.0, "saturation": 1.0, "light_bleeding": 0.2}}
`expand` turns it into the explicit `lighting` dict (every value filled in) and `write_look` / `apply_look` writes it:
  light nodes `default_global_light` (light_type 2 = sun, 1 = ambient): light_color_rgb, static_color_rgb, Brightness, orient
  the `FOG_Controller` node: fog_type, start, end, color_rgb
  the `SkyBox` node: modelres (only a sky whose model record is in the block can be named; `available` lists them)
  the `default_GFX` node: default_brightness, default_saturation, default_LightBleeding
The sun direction: the light travels along the +Z axis of the light node turned by the INVERSE of the stored orient (measured against the
baked colours of four shipped maps, bake.py / tests/test_bake.py); azimuth and elevation are turned into such an orient.
"""
import json
import math
import os

from .core import np, MapgenError, BACKEND

DATA = os.path.join(BACKEND, 'data', 'look_presets.json')
SUN_AXIS = (0.0, 0.0, 1.0)       # aim axis of the light node (bake.SUN_AXIS)

_cache = {}


def data():
    if 'd' not in _cache:
        with open(DATA, encoding='utf-8') as f:
            _cache['d'] = json.load(f)
    return _cache['d']


def skies():
    """-> {id: model path} of the shipped sky models."""
    return {s['id']: s['model'] for s in data()['skies']}


# preset id -> (label, block the settings come from, block the lights come from when that block has none)
PRESET_SOURCES = {
    'dawn': ('Dawn', 'mainmap_map01_dea_hq_us_border.map', None),
    'clear_day': ('Clear day', 'mainmap_map08_hacienda.map', None),
    'red_dust': ('Red dust', 'mainmap_map06_virgillos_farm.map', None),
    'bright_blue': ('Bright blue', 'mainmap_map07_meat_factory.map', None),
    'train_dust': ('Dusty afternoon', 'mainmap_map10_runawaytrain.map', None),
    'jungle_night': ('Jungle night', 'mainmap_map09_jungle.map', 'mainmap_map01_dea_hq_us_border.map'),
    'city_day': ('City day', 'mainmap_map08_hacienda.map', None),
}
# presets whose lights always come from another block (the sky, fog and screen tone stay those of the settings block): the city day has the sun and
# ambient colours of Downtown, so a district reads like the city around it (a cooler ambient tints every grey surface in the shade)
LIGHTS_FROM = {'city_day': 'submap01_map02_lostoros_downtown.submap'}
# presets whose lights light the player too (dynamic emission) and the static meshes (static emission), like the lights of four of the five shipped
# map blocks that have a sun. The clone source of a new map (Map10) has both off. (The blob shadow's darkness does not depend on this: it is
# darkened once per collision hull face under the player, so stacked coplanar faces make it black; see todct/hullclean.py.)
EMISSION_ON = ('city_day',)
NIGHT_DIM = 0.35        # jungle_night: the lights come from the dawn map, scaled down (derived, not shipped)


def _from_block(bid, light_bid=None, dim=1.0, lights_from=None):
    b = data()['blocks'][bid]
    lights = data()['blocks'][lights_from]['lights'] if lights_from else b['lights'] or (data()['blocks'][light_bid]['lights'] if light_bid else [])
    sun = next((l for l in lights if l['kind'] == 'directional'), None)
    amb = next((l for l in lights if l['kind'] == 'ambient'), None)
    fog = b['fog'][0] if b['fog'] else None
    sky = b['sky'][0]['model'] if b['sky'] else None
    gfx = b['gfx'][0] if b['gfx'] else None
    out = {}
    if sun:
        out['sun'] = dict(color=sun['color'], static_color=sun['static_color'], brightness=round(sun['brightness'] * dim, 4), orient=sun['orient'],
                          dynamic_emission=bool(sun.get('dynamic_emission', False)), static_emission=bool(sun.get('static_emission', False)))
    if amb:
        out['ambient'] = dict(color=amb['color'], static_color=amb['static_color'], brightness=round(amb['brightness'] * dim, 4),
                              dynamic_emission=bool(amb.get('dynamic_emission', False)), static_emission=bool(amb.get('static_emission', False)))
    if fog:
        out['fog'] = dict(type=fog['type'], near=fog['start'], far=fog['end'], color=fog['color'])
    if sky:
        out['sky'] = sky.split('/')[-3]
    if gfx:
        out['screen'] = dict(brightness=gfx['brightness'], saturation=gfx['saturation'], light_bleeding=gfx['light_bleeding'])
    return out


def presets():
    """-> {id: dict(label, source, look)} with every value filled in from the shipped blocks."""
    if 'p' not in _cache:
        p = {}
        for pid, (label, bid, lbid) in PRESET_SOURCES.items():
            look = _from_block(bid, lbid, NIGHT_DIM if pid == 'jungle_night' else 1.0, LIGHTS_FROM.get(pid))
            if pid in EMISSION_ON:
                for k in ('sun', 'ambient'):
                    if k in look:
                        look[k].update(dynamic_emission=True, static_emission=True)
            p[pid] = dict(id=pid, label=label, source=bid, look=look, derived=bool(lbid))
        _cache['p'] = p
    return _cache['p']


def aim_to_orient(azimuth, elevation):
    """The orient to store for a sun that travels towards `azimuth` (degrees clockwise from +z, seen from above) and down at `elevation`
    degrees: the block keeps the inverse of the rotation that turns the +Z aim axis onto that direction (measured on the shipped maps,
    see bake.py)."""
    x, y, z, w = _aim_rotation(azimuth, elevation)
    return [round(-x, 6) if x else 0.0, round(-y, 6) if y else 0.0, round(-z, 6) if z else 0.0, w]


def _aim_rotation(azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(elevation)
    d = np.array([math.sin(az) * math.cos(el), -math.sin(el), math.cos(az) * math.cos(el)])
    a = np.array(SUN_AXIS)
    c = float(a @ d)
    if c > 0.999999:
        return [0.0, 0.0, 0.0, 1.0]
    if c < -0.999999:
        return [1.0, 0.0, 0.0, 0.0]
    ax = np.cross(a, d)
    ax = ax / np.linalg.norm(ax)
    ang = math.acos(max(-1.0, min(1.0, c)))
    s = math.sin(ang / 2.0)
    return [round(float(ax[0] * s), 6), round(float(ax[1] * s), 6), round(float(ax[2] * s), 6), round(math.cos(ang / 2.0), 6)]


def _rgb(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 3 or any(not isinstance(x, (int, float)) or not 0.0 <= x <= 4.0 for x in v):
        raise MapgenError('%s must be three numbers between 0 and 4' % what)
    return [float(x) for x in v]


def resolve(look, out=None):
    """The explicit lighting values of a `look` key. -> dict(sun, ambient, fog, sky, screen, preset, notes)"""
    look = look or {}
    pid = look.get('preset')
    base = {}
    if pid:
        if pid not in presets():
            raise MapgenError('unknown look preset %r (%s)' % (pid, ', '.join(presets())))
        base = json.loads(json.dumps(presets()[pid]['look']))
    res = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    notes = []
    s = look.get('sun')
    if s:
        sun = res.setdefault('sun', dict(color=[1.0, 1.0, 1.0], static_color=[1.0, 1.0, 1.0], brightness=1.0, orient=[0.0, 0.0, 0.0, 1.0]))
        if s.get('color') is not None:
            sun['color'] = _rgb(s['color'], 'sun colour')
            sun['static_color'] = list(sun['color'])
        if s.get('brightness') is not None:
            sun['brightness'] = float(s['brightness'])
        if s.get('orient') is not None:
            sun['orient'] = [float(v) for v in s['orient']]
        elif s.get('azimuth') is not None or s.get('elevation') is not None:
            sun['orient'] = aim_to_orient(float(s.get('azimuth', 0.0)), float(s.get('elevation', 45.0)))
            notes.append('The sun direction follows the shipped maps; look at the shadows in game once.')
    a = look.get('ambient')
    if a:
        amb = res.setdefault('ambient', dict(color=[0.5, 0.5, 0.6], static_color=[0.5, 0.5, 0.6], brightness=0.6))
        if a.get('color') is not None:
            amb['color'] = _rgb(a['color'], 'ambient colour')
            amb['static_color'] = list(amb['color'])
        if a.get('brightness') is not None:
            amb['brightness'] = float(a['brightness'])
    f = look.get('fog')
    if f:
        fog = res.setdefault('fog', dict(type=1, near=100.0, far=700.0, color=[1.0, 1.0, 1.0]))
        if f.get('color') is not None:
            fog['color'] = _rgb(f['color'], 'fog colour')
        for k_in, k in (('near', 'near'), ('far', 'far')):
            if f.get(k_in) is not None:
                fog[k] = float(f[k_in])
        if fog['far'] <= fog['near'] or fog['near'] < 0:
            raise MapgenError('fog far must be larger than near (and near at least 0)')
    if look.get('sky'):
        if look['sky'] not in skies():
            raise MapgenError('unknown sky %r (%s)' % (look['sky'], ', '.join(skies())))
        res['sky'] = look['sky']
    sc = look.get('screen')
    if sc:
        scr = res.setdefault('screen', dict(brightness=1.0, saturation=1.0, light_bleeding=0.2))
        for k in ('brightness', 'saturation', 'light_bleeding'):
            if sc.get(k) is not None:
                scr[k] = float(sc[k])
    res['preset'] = pid
    res['notes'] = notes
    return res


# ------------------------------------------------------------------------------------------------ the writer
SKY_TYPES = ('SkyBox',)


def _same(a, b):
    """Equal as the game stores them (32-bit floats): 0.6 read back is 0.6000000238."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(b)))
    return a == b


def _type_name(d, n):
    t = d.type_of(n)
    return t or ''


def apply_look(docs, lighting, available_skies=None):
    """Write resolved lighting values into the nodes of fragment documents.

    docs: {fragment name: FragDoc} for every fragment of the new map's map and submap blocks (todms' fragment editor documents).
    lighting: the dict resolve() returns (the `lighting` key of an expanded map).
    available_skies: sky ids whose model record exists in the block; None = trust the caller, [] = keep the sky.
    -> dict(changed=[fragment names whose payload changed], applied=[plain sentences], skipped=[plain sentences]).
    After this, take each changed document's `payload()` back into the block.
    """
    applied, skipped, changed = [], [], set()

    def setp(d, frag, n, prop, value):
        before = d.get(n, prop)
        if before is not None and _same(before, value):
            return False
        d.set_prop(n, prop, value, note=False)
        changed.add(frag)
        return True

    suns = amb = fog = sky = gfx = 0
    for frag, d in docs.items():
        for n in d.created_ids():
            t = _type_name(d, n)
            if 'default_global_light' in t:
                kind = d.get(n, 'light_type')
                key = 'sun' if kind == 2 else ('ambient' if kind == 1 else None)
                spec = lighting.get(key) if key else None
                if not spec:
                    continue
                for prop, val in (('light_color_rgb', spec['color']), ('static_color_rgb', spec.get('static_color', spec['color'])),
                                  ('Brightness', spec['brightness'])):
                    setp(d, frag, n, prop, [float(x) for x in val] if isinstance(val, (list, tuple)) else float(val))
                for prop in ('dynamic_emission', 'static_emission'):
                    if spec.get(prop) is not None:
                        setp(d, frag, n, prop, bool(spec[prop]))
                if key == 'sun' and spec.get('orient'):
                    setp(d, frag, n, 'orient', [float(v) for v in spec['orient']])
                if key == 'sun':
                    suns += 1
                else:
                    amb += 1
            elif 'FOG_Controller' in t and lighting.get('fog'):
                f = lighting['fog']
                setp(d, frag, n, 'fog_type', int(f.get('type', 1)))
                setp(d, frag, n, 'start', float(f['near']))
                setp(d, frag, n, 'end', float(f['far']))
                setp(d, frag, n, 'color_rgb', [float(x) for x in f['color']])
                fog += 1
            elif t == 'SkyBox' and lighting.get('sky'):
                want = skies().get(lighting['sky'])
                have = d.get(n, 'modelres')
                if have and have.lower() == want.lower():
                    sky += 1
                elif available_skies is not None and lighting['sky'] not in available_skies:
                    skipped.append('The sky %s needs its model and pictures copied into the block first; the map keeps %s.'
                                   % (lighting['sky'], (have or '?').split('/')[-3] if have and have.count('/') >= 3 else have))
                else:
                    setp(d, frag, n, 'modelres', want)
                    sky += 1
            elif 'default_GFX' in t and lighting.get('screen'):
                s = lighting['screen']
                setp(d, frag, n, 'default_brightness', float(s['brightness']))
                setp(d, frag, n, 'default_saturation', float(s['saturation']))
                setp(d, frag, n, 'default_LightBleeding', float(s['light_bleeding']))
                gfx += 1
    if lighting.get('sun') and not suns:
        skipped.append('The block has no directional light node to write the sun into.')
    if lighting.get('ambient') and not amb:
        skipped.append('The block has no ambient light node to write the ambient light into.')
    if lighting.get('fog') and not fog:
        skipped.append('The block has no fog node to write the fog into.')
    if suns or amb:
        applied.append('%d sun and %d ambient light node(s) set' % (suns, amb))
    if fog:
        applied.append('fog set')
    if sky:
        applied.append('sky set')
    if gfx:
        applied.append('screen tone set')
    return dict(changed=sorted(changed), applied=applied, skipped=skipped)


def write_look(block_payloads, types, lighting, available_skies=None):
    """Convenience for a builder that holds fragment payloads: {fragment name: payload bytes} -> ({fragment name: new payload}, report).
    Needs the project's fragment editor (todct.tools). Only changed fragments are returned."""
    from todct import tools as TT
    k = TT.load()
    docs = {nm: k.fe.FragDoc(p, types, nm) for nm, p in block_payloads.items()}
    rep = apply_look(docs, lighting, available_skies)
    return {nm: docs[nm].payload() for nm in rep['changed']}, rep
