"""The shared name table: readable names for the game's characters, behaviours, sides, vehicles, weapons and pickups.

The game itself only knows numbers (a character `Model`, a `FactionID`, a `VehicleSubType` ...) and file names. The editor shows the
names below instead; the number or file name stays in the tooltip, and every picker accepts both when searching.
Served to the UI by `GET /api/names`, so there is one table for the whole app.
"""
import re

# ---------------------------------------------------------------------------------------------- characters (the `Model` number)
# model number -> (readable name, group). Group: 'enemy' = placed as an enemy somewhere in the shipped data, 'ally' = placed as a friend or
# neutral person, 'cast' = a story character the game never places as a free placeholder, 'player' = Ram. The numbers 7, 8, 17, 19, 25 and
# 26 have a table row in the game but no mesh in any block, so they cannot be placed.
CHARACTERS = {
    0: ('Cartel thug (long shirt)', 'enemy'),
    1: ('Cartel thug (short shirt)', 'enemy'),
    2: ('Virgillio thug (small)', 'enemy'),
    3: ('Virgillio thug (tall)', 'enemy'),
    4: ('Angel', 'ally'),
    5: ('Border police', 'enemy'),
    6: ('Cezar Morales', 'enemy'),
    7: ('DEA agent Johnson', 'none'),
    8: ('DEA agent Pierson', 'none'),
    9: ('DEA task force', 'enemy'),
    10: ('Ernesto Cruz', 'cast'),
    11: ('Hooker', 'ally'),
    12: ('Agent Johnson', 'enemy'),
    13: ('Marco', 'ally'),
    14: ('Mendez', 'enemy'),
    15: ('Soldier', 'enemy'),
    16: ('Montanez', 'enemy'),
    17: ('Muerte', 'none'),
    18: ('Action Tommy', 'cast'),
    19: ('Trust', 'none'),
    20: ('Ram', 'player'),
    21: ('Elvez', 'enemy'),
    22: ('Elvez guard', 'enemy'),
    23: ('Pedestrian', 'enemy'),
    24: ('Mexican police', 'enemy'),
    25: ('Unused model 25', 'none'),
    26: ('Andreasen', 'none'),
    27: ('Gangster', 'enemy'),
    28: ('Girl', 'cast'),
    29: ('Old lady', 'enemy'),
    30: ('DEA outlaw', 'enemy'),
    31: ('Virgillio boss', 'enemy'),
}

# a pedestrian wears a texture set: these are the sets the game puts on the shared pedestrian body
PEDESTRIAN_LOOKS = {0: 'Civilian', 1: 'Civilian (alt)', 10: 'Police', 12: 'Police (alt)', 13: 'Police (dark)', 18: 'Skeleton'}

# ---------------------------------------------------------------------------------------------- behaviours (AISubType = the game's character types)
AI = {
    0: 'Mixed fighter', 1: 'Takes cover', 2: 'Strafes', 3: 'Stands and shoots', 4: 'Marco', 5: 'Morales', 6: 'Joe Virgillio',
    7: 'Player', 8: 'Mission giver', 9: 'Civilian', 10: 'Virgillio fighter (tall)', 11: 'Virgillio fighter (small)',
    12: 'Cartel fighter (long shirt)', 13: 'Cartel fighter (short shirt)', 14: 'Bikini babe fighter', 15: 'Border police fighter',
    16: 'Soldier fighter', 17: 'DEA fighter', 18: 'DEA battle suit fighter', 19: 'Bull fighter', 20: 'Elvez', 21: 'Bikini boss',
    22: 'Montanez',
}

# ---------------------------------------------------------------------------------------------- sides (FactionID)
FACTIONS = {
    0: 'Ram', 1: 'Morales', 2: 'Explosives', 3: 'Unknown', 4: 'Virgillio', 5: 'Mission target', 6: 'Civilian', 7: 'Animal',
    8: 'Mission giver', 9: 'Enemy', 10: 'Friend', 11: 'Neutral', 12: 'Johnson target', 13: 'Wrestler', 14: 'Police',
    15: 'Bad driver', 16: 'Gang', 17: 'Unused', 18: 'Mexican buddy',
}
SIDES_OFFERED = (9, 10, 11, 6, 14)               # the choices of the side picker (the others are mission machinery)

# ---------------------------------------------------------------------------------------------- weapons (WeaponSubType)
WEAPONS = {
    0: 'Beretta pistol', 1: 'Magnum', 2: 'Marlin rifle', 3: 'Winchester rifle', 4: 'Benelli shotgun', 5: 'Sawed-off shotgun',
    6: 'Mac-10', 7: 'MP5', 8: 'AK-47', 9: 'M16', 10: 'Gatling gun', 11: 'Hand grenade', 12: 'Grenade launcher',
    13: 'Rocket launcher', 14: 'Machete', 15: 'Golden gun', 16: 'Mariachi guitar', 17: 'Piñata', 18: 'Molotov cocktail',
    19: 'Dynamite',
}

# ---------------------------------------------------------------------------------------------- pickups (GoodieSubType)
GOODIES = {
    0: 'Health (medium)', 1: 'Health (large)', 2: 'Health upgrade', 3: 'Combo time extension', 4: 'Armour', 5: 'Race bonus (medium)',
    6: 'Race bonus (large)', 7: 'Medkit', 8: 'Rewind', 9: 'Golden gun', 10: 'Loco move', 11: 'Ram move', 12: 'Sombrero',
    13: 'Time stop', 14: 'Wrestler', 15: 'Mariachi', 16: 'Piñata', 17: 'Tequila', 18: 'Stamina upgrade', 19: 'Weapon upgrade',
    20: 'Score bonus (small)', 21: 'Score bonus (large)',
}

# ---------------------------------------------------------------------------------------------- vehicles (VehicleSubType, names from VehicleDict)
VEHICLES = {
    0: 'Sedan', 1: 'Dirt bike', 2: 'Forklift', 3: 'Pickup', 4: 'El Camino', 5: 'Test car', 6: 'Truck', 7: 'Door (left front)',
    8: 'Pickup truck', 9: "'57 pickup", 10: 'Heavy van', 11: '4x4 pickup', 12: 'Big truck', 14: 'Urban van', 15: 'Taxi',
    16: 'Police car', 17: 'Station wagon', 18: 'Modern sedan', 19: 'Conquistador', 20: 'Angel van', 21: 'Big truck (flat nose)',
    22: 'Big truck (Morales)', 23: 'Rusty sedan', 25: 'Tractor', 26: 'Burrito cart', 27: 'Crane truck', 28: 'Bus', 29: 'Helicopter',
    30: 'Military truck',
}

# readable names for the vehicle / goodie / weapon names the tools report (the app reads them from the game, then looks them up here)
_RAW_FIX = {
    '4x4pickup': '4x4 pickup', 'bigtruck': 'Big truck', 'bigtruckflatnose': 'Big truck (flat nose)', 'bigtruckmoralez': 'Big truck (Morales)',
    'burritocart': 'Burrito cart', 'burritowagon': 'Burrito wagon', 'cranetruck': 'Crane truck', 'dirtbike': 'Dirt bike',
    'elcamino': 'El Camino', 'modernsedan': 'Modern sedan', 'militarytruck': 'Military truck', 'pickup_truck': 'Pickup truck',
    'policecar': 'Police car', 'sedanrusty': 'Rusty sedan', 'stationwagon': 'Station wagon', 'vanheavy': 'Heavy van',
    'vanurban': 'Urban van', 'vanangel': 'Angel van', '57pickup': "'57 pickup", 'aitest': 'Test car', 'door_left_front': 'Door (left front)',
}


def pretty(raw):
    """A readable form of an internal name ('Medium_Health' -> 'Medium health')."""
    s = str(raw or '')
    k = s.lower()
    if k in _RAW_FIX:
        return _RAW_FIX[k]
    s = re.sub(r'\s*->.*$', '', s)
    s = s.replace('_', ' ')
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:1].upper() + s[1:].lower() if s else s


def character_name(n):
    try:
        return CHARACTERS[int(n)][0]
    except (KeyError, TypeError, ValueError):
        return 'Character %s' % n


def look_name(model, texture_set):
    """A texture set of a model as a short readable word ('Look 3'); the shared pedestrian body has real names for its sets."""
    t = int(texture_set or 0)
    if int(model) == 23 and t in PEDESTRIAN_LOOKS:
        return PEDESTRIAN_LOOKS[t]
    return 'Look %d' % (t + 1)


# ---------------------------------------------------------------------------------------------- model files -> readable names
# Model files of the characters, by file name stem, so a list that only has a file name can show a name too.
def model_file_names():
    from . import characters
    out = {}
    for row in characters.table():
        for p in row['paths']:
            out[p.rsplit('/', 1)[-1].rsplit('.', 1)[0].lower()] = row['name']
    return out


def file_name(path):
    """Readable name for a character / vehicle / weapon model file name, or None when the file is none of those."""
    s = str(path or '').replace('\\', '/').lower()
    stem = s.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    if '/characters/' in s or s.startswith('characters/'):
        return model_file_names().get(stem)
    if '/vehicles' in s:
        folder = s.rsplit('/', 2)[-2] if s.count('/') >= 2 else stem
        for v in VEHICLES.values():
            if re.sub(r'[^a-z0-9]', '', v.lower()) == re.sub(r'[^a-z0-9]', '', folder):
                return v
        return pretty(folder)
    if '/weapons/' in s:
        return pretty(re.sub(r'^weapon_', '', stem))
    return None


def all_names():
    """Everything the UI needs for pickers and lists, in one answer."""
    from . import characters
    return dict(
        characters=characters.table(),
        ai={str(k): v for k, v in AI.items()},
        factions={str(k): v for k, v in FACTIONS.items()},
        sides=list(SIDES_OFFERED),
        weapons={str(k): v for k, v in WEAPONS.items()},
        goodies={str(k): v for k, v in GOODIES.items()},
        vehicles={str(k): v for k, v in VEHICLES.items()},
        looks={str(k): v for k, v in PEDESTRIAN_LOOKS.items()},
    )
