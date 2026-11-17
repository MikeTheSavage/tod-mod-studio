"""TOD collision surfaces: the face material (index into facecoll.mat) and the SurfacePropFields word of a shape
(docs/subsystem_collision.md 3.3 / 3.5 / 11.4). Used by the surface pickers.

Word bits: 10 Solid, 11 BulletProof, 12 Opaque, 13 CameraBlock, 14 (set on almost all shipped shapes),
23 Trigger, 24 NavBlock, 25 Physics (set in the default word), 26 ActivateTriggers.
"""

FACE_MATERIALS = ["AllRound", "Metal", "Concrete", "Wood", "Dirt", "Stone", "Glass", "Bush", "Wirefence", "Grass",
                  "Asphalt", "Water", "Cloth", "SolidGlass", "BrokenWindow_Elvez", "BrokenWindow_Burgerbar",
                  "BrokenWindow_Shoppingmall", "BrokenWindow_Virgillo", "Default_no_decal"]
NO_MATERIAL = 255

# footstep sounds the game picks from the ground face material (tools/sound/sound_tool.py FOOTSTEPS)
FOOTSTEP = {"Concrete": "concrete", "Asphalt": "concrete", "Metal": "metal", "Wirefence": "metal", "Dirt": "dirt",
            "Bush": "grass", "Grass": "grass", "Wood": "wood", "Water": "water"}

FLAG_BITS = {"Solid": 10, "BulletProof": 11, "Opaque": 12, "CameraBlock": 13, "Bit14": 14, "Trigger": 23,
             "NavBlock": 24, "Physics": 25, "ActivateTriggers": 26}
EDITABLE_FLAGS = ["Solid", "BulletProof", "Opaque", "CameraBlock", "NavBlock"]

DEFAULT_WORD = 0x02007C00

# presets: name -> (word, tested in game?, what it does)
PRESETS = [
    ("solid", 0x02007C00, True, "Solid wall or floor: stops Ram, NPCs, bullets and the camera (the shipped default)"),
    ("thin", 0x02007400, True, "Thin (fences, foliage cards): solid and blocks the camera, bullets pass "
                              "(collmat thin_material_*)"),
    ("solid_nav", 0x03007C00, False, "Solid and NavBlock: NPC obstacle probes (mask 0x21) also avoid it"),
    ("player_blocker", 0x02006C00, False, "Invisible blocker: solid, bullet-proof, camera-blocking, not opaque "
                                          "(does not hide the sun flare; untested in game)"),
    ("player_only", 0x02006400, False, "Player-only blocker: bullets and aim lines pass (untested in game)"),
    ("camera_only", 0x02006000, False, "Camera only: pushes the camera, nothing else collides (untested in game)"),
]
PRESET_WORDS = {p[0]: p[1] for p in PRESETS}

# a sensible face material by keyword of the source mesh / material name
KEYWORDS = [("stone", "Stone"), ("rock", "Stone"), ("ruin", "Stone"), ("temple", "Stone"), ("maya", "Stone"),
            ("brick", "Concrete"), ("concrete", "Concrete"), ("cement", "Concrete"), ("wall", "Concrete"),
            ("wood", "Wood"), ("plank", "Wood"), ("log", "Wood"), ("crate", "Wood"), ("tree", "Wood"),
            ("metal", "Metal"), ("steel", "Metal"), ("iron", "Metal"), ("pipe", "Metal"), ("fence", "Wirefence"),
            ("dirt", "Dirt"), ("mud", "Dirt"), ("ground", "Dirt"), ("terrain", "Dirt"), ("grass", "Grass"),
            ("bush", "Bush"), ("leaf", "Bush"), ("foliage", "Bush"), ("plant", "Bush"), ("road", "Asphalt"),
            ("asphalt", "Asphalt"), ("glass", "Glass"), ("water", "Water"), ("cloth", "Cloth"), ("tent", "Cloth")]


def material_index(m):
    """Name or index -> facecoll.mat index (255 = none)."""
    if m is None:
        return NO_MATERIAL
    if isinstance(m, int):
        if m == NO_MATERIAL or 0 <= m < len(FACE_MATERIALS):
            return m
        raise ValueError('face material index %d out of range' % m)
    s = str(m).strip()
    if s.isdigit():
        return material_index(int(s))
    for i, n in enumerate(FACE_MATERIALS):
        if n.lower() == s.lower():
            return i
    if s.lower() in ('none', ''):
        return NO_MATERIAL
    raise ValueError('unknown face material %r (one of %s)' % (m, ', '.join(FACE_MATERIALS)))


def material_name(i):
    return FACE_MATERIALS[i] if 0 <= i < len(FACE_MATERIALS) else 'none'


def guess_material(*names):
    s = ' '.join(n for n in names if n).lower()
    for k, m in KEYWORDS:
        if k in s:
            return m
    return 'Stone'


def parse_word(w):
    if isinstance(w, str):
        s = w.strip()
        if s in PRESET_WORDS:
            return PRESET_WORDS[s]
        return int(s, 16) if s.lower().startswith('0x') else int(s)
    return int(w)


def word_from_flags(flags, base=DEFAULT_WORD):
    """flags: {name: bool} for the editable flags; other bits come from base."""
    w = int(base)
    for name, on in flags.items():
        bit = 1 << FLAG_BITS[name]
        w = (w | bit) if on else (w & ~bit)
    return w


def flags_of(word):
    word = parse_word(word)
    return {n: bool(word >> b & 1) for n, b in FLAG_BITS.items()}


def describe(word):
    word = parse_word(word)
    for name, w, tested, text in PRESETS:
        if w == word:
            return '%s (0x%08X)%s' % (name, word, '' if tested else ', untested in game')
    on = [n for n, b in FLAG_BITS.items() if word >> b & 1 and n in EDITABLE_FLAGS]
    return 'custom 0x%08X: %s' % (word, ', '.join(on) or 'no collision flags')


def surface_class(word):
    """Colour class of the collision layer (the same as Mod Studio's and the collision lab's export)."""
    f = flags_of(word)
    if f['Solid'] and f['BulletProof']:
        return 'solid'
    if f['Solid']:
        return 'thin'
    if f['CameraBlock'] or f['NavBlock']:
        return 'blocker'
    return 'other'


CLASS_COLOURS = {'solid': (1.0, 0.55, 0.1), 'thin': (1.0, 0.85, 0.2), 'blocker': (0.3, 0.55, 1.0),
                 'other': (0.7, 0.7, 0.7), 'new': (0.1, 0.95, 0.45)}


def catalog():
    """Everything a picker needs (JSON)."""
    return dict(face_materials=FACE_MATERIALS, presets=[dict(name=n, word='0x%08X' % w, tested=t, text=x)
                                                       for n, w, t, x in PRESETS],
                flags=EDITABLE_FLAGS, default_word='0x%08X' % DEFAULT_WORD, footsteps=FOOTSTEP)
