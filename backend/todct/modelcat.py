"""Categories of the game's models, from the model path and name. One table, first match wins.

A rule is (id, label, [regex ...]); every regex is tried (search) against the lower-case path without "/data/" and without
".model", e.g. "models/addons/vegetation/veg_bush_brightgreen_large". Put the narrow rules before the broad ones.
"""
import re

# id, label, patterns
RULES = [
    ('animals', 'Animals', [r'^animals/']),
    ('characters', 'Characters', [r'^characters/', r'^models/templates/default_rig']),
    ('vehicles', 'Vehicles', [r'^models/vehicles', r'carwreck', r'speedboat', r'(^|/)(boat|bigcargoship|van_bomb)$',
                              r'(^|/)airplane_', r'(^|/)(empty_freight_wagon|trainengine)$']),
    ('weapons', 'Weapons', [r'^models/collectables/weapons', r'weaponflash', r'^mockupmodels/collectables', r'(^|/)weapon_']),
    ('pickups', 'Pickups', [r'^models/collectables', r'(^|/)pickup', r'(^|/)keys/key$']),
    ('props', 'Props and accessories', [r'trash']),
    ('vegetation', 'Vegetation', [r'/vegetation/', r'/surround', r'(^|/)(veg|sur|add_plant|prop_plant)_?', r'hemp_', r'cactus',
                                  r'(^|/)(hay|haybale|hedge)', r'(tree|bush|grass)']),
    ('terrain', 'Terrain and sky', [r'^textures/skybox', r'skyhorison', r'skyline', r'terrainandroads|terrainanroads', r'(^|/)ter_', r'terrain_',
                                    r'coastline', r'(^|/)lod_', r'load_chunks', r'(^|/)roads_', r'ship_horizon', r'(^|/)(canyon|beachhead)$']),
    ('effects', 'Effects, debris and wires', [r'^models/props/effect', r'_glow\d*$', r'light(cone|ball|chain)', r'wires?(_|$)', r'(^|/)(telphone|virgillo)wires',
                                              r'shadowmap', r'cone_marker', r'(^|/)cutsequence/']),
    ('signs', 'Signs', [r'sign', r'poster', r'billboard']),
    ('buildings', 'Buildings', [r'chunk', r'(^|[/_])(shed|barn|mansion|temple|factory|tower|shack|workshack)', r'house($|[/_0-9])',
                                r'station', r'mobile_?home', r'interior', r'(^|[/_])bui_', r'elevatorshaft', r'scaffold', r'outer(_|$)', r'conveyer',
                                r'catwalk', r'arena(?!blocking)', r'machine0', r'plant($|/)', r'water_?tank']),
    ('doors', 'Doors, gates and fences', [r'door', r'gate', r'fence', r'roadblock', r'barrier', r'(^|/)(wall|walls)/', r'blockingwall']),
    ('destructibles', 'Destructibles', [r'havocobjects', r'(^|/)gib', r'breakable', r'testdummy|targetdummy|test_dummy', r'destroyable']),
    ('crates', 'Crates and containers', [r'crate', r'container', r'pallet', r'boxes', r'(^|/)box', r'cokepack|packcoke', r'barrel', r'junkyard',
                                         r'pile', r'weaponammo', r'drum']),
    ('interior', 'Furniture and interior', [r'office', r'(^|/)(bed|chairs?|tables?|shelves|shelf|locker|tvs|itequipment)', r'couch|toilet|sodamachine|cashregister',
                                            r'ghettoblaster|cigaret|fusebox|meterbox|workbench|kingsize|bust|pot$|whiskey|bottle|waterstand',
                                            r'switch|buttonsandlevers|lever', r'(^|/)(add_)?(bed|chair|table|tv|lazboy)']),
    ('street', 'Street and outdoors', [r'street', r'telepole|telephone|wirepole|wallattacher', r'hydrant', r'(^|/)(bins|wastebin)', r'dumpster', r'bench',
                                       r'traffic', r'publicphone|handset', r'curb', r'lamp', r'antenna|tvdish', r'airvent|airconditioner',
                                       r'pressuretank', r'parasol|sunbed', r'rubbish', r'roofdebris', r'flag', r'burritostand|candystand|souvenirstand',
                                       r'stairsandladders|ladder|escalator', r'jumps?(/|$)|addjump', r'trainsign', r'gaspump|neonline']),
    ('props', 'Props and accessories', []),
]
FALLBACK = 'props'
_COMPILED = [(i, l, [re.compile(p) for p in ps]) for i, l, ps in RULES]
LABEL = {}
for _i, _l, _ in RULES:
    LABEL.setdefault(_i, _l)
ORDER = [i for i in dict.fromkeys(i for i, _, _ in RULES) if i != FALLBACK] + [FALLBACK]


def clean(path):
    p = (path or '').replace('\\', '/').lower()
    if p.startswith('/data/'):
        p = p[6:]
    elif p.startswith('data/'):
        p = p[5:]
    p = p.lstrip('/')
    return p[:-6] if p.endswith('.model') else p


def category(path):
    """Category id of a model path."""
    p = clean(path)
    for i, _, ps in _COMPILED:
        for r in ps:
            if r.search(p):
                return i
    return FALLBACK


def area(path):
    """The map folder a model sits in ('map02_lostoros_downtown', 'tutorial_map_01'), or '' for shared ones."""
    m = re.search(r'(?:^|/)(map\d+[a-z_0-9]*|tutorial_map_\d+)(?:/|$)', clean(path))
    return m.group(1) if m else ''


def table():
    """For the screen: [{id, label}] in display order."""
    return [dict(id=i, label=LABEL[i]) for i in ORDER]


GENERIC = {'vehicle', 'textured', 'default', 'model', 'chunk', 'skybox'}


def label(path):
    """A readable name: the file name, or its folder when the file name says nothing ("vehicle" -> "Sedan Modernstandard")."""
    parts = clean(path).split('/')
    leaf = parts[-1]
    if leaf in GENERIC and len(parts) > 1:
        leaf = parts[-2] if parts[-2] not in GENERIC else (parts[-3] if len(parts) > 2 else leaf)
    leaf = re.sub(r'^(add|veg|sur|prop|hvc)_+', '', leaf)
    return re.sub(r'\s+', ' ', leaf.replace('_', ' ')).strip().title() or leaf
