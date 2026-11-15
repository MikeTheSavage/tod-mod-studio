"""tpl_core.py - the template data model: parameter schema, parameter resolution + validation, the mission index pool, text-row allocation.

A TEMPLATE is a module in templates/types/ with
    NAME, TITLE, SUMMARY, HOST_NEEDS            what it is and what it needs from its host (plain English, shown in the UI)
    LEGACY_INDEX                                the index the Mesa package used (new_root / names stay byte-identical there)
    COMMON                                      defaults of the common parameters (giver, name, description, loading lines, medal scores)
    PARAMS                                      type specific parameters (list of P)
    make(p, host, inst) -> Spec                 turns resolved parameters into what the builder needs
    constraints(p, host) -> [(level, message)]  type specific rules the schema cannot express (level 'error' | 'warn')
Every parameter is declared once: key, kind, default, range or choices, label, help line. Positions are WORLD metres (x, y, z) with y = None
meaning "the host's ground height at x, z"; a point's y is the GROUND height (the template adds the entity's own offset).
"""
import copy, math, struct, sys
sys.dont_write_bytecode = True

KINDS = ('float', 'int', 'bool', 'text', 'choice', 'point', 'points', 'rect', 'rects', 'angle', 'floats', 'texts')


class P:
    """one parameter. default: a literal or callable(host, p) -> value (p = the parameters resolved so far)."""

    def __init__(self, key, kind, default, label, help='', min=None, max=None, choices=None, group='Settings', unit='', min_len=None, max_len=None, advanced=False):
        assert kind in KINDS, kind
        self.key, self.kind, self.default, self.label, self.help = key, kind, default, label, help
        self.min, self.max, self.choices, self.group, self.unit = min, max, choices, group, unit
        self.min_len, self.max_len, self.advanced = min_len, max_len, advanced

    def default_for(self, host, p):
        d = self.default
        return d(host, p) if callable(d) else copy.deepcopy(d)

    def describe(self, host=None, p=None):
        d = dict(key=self.key, kind=self.kind, label=self.label, help=self.help, group=self.group, unit=self.unit, advanced=self.advanced)
        for k in ('min', 'max', 'choices', 'min_len', 'max_len'):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if host is not None:
            try:
                d['default'] = self.default_for(host, p or {})
            except Exception:                                   # noqa: BLE001
                d['default'] = None
        return d


class Spec:
    """what the builder needs of one mission instance (filled by a template's make())"""

    def __init__(self, **kw):
        self.ALLOW_UNRESOLVED = []
        self.OUTSIDE_OK = None
        self.AWARD_SETS = {}
        self.AWARD_SCORES = {}
        self.PASS_SCORE = 0
        self.START_SPOT = None
        self.FOLDER_NAME = None
        self.warnings = []
        self.__dict__.update(kw)


class ParamError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ common parameters
def common_params(c):
    """the parameters every template has. c = the template's COMMON dict:
        giver (rx, rz, size) in Mesa units, giver_height, name, description, load_mid, load_low, pass_score, silver_score, gold_score"""
    gx, gz, gs = c['giver']
    return [
        P('giver_pos', 'point', lambda h, p: h.pt(gx, gz, None), 'Mission giver position', 'Where the walk-in box stands (x, y, z; y empty = ground). The player presses USE inside it to be offered the mission.', group='Placement'),
        P('giver_yaw', 'angle', 0.0, 'Mission giver box direction', 'Turns the walk-in box (degrees, 0 = north). Only matters for a box that is not square.', min=-180.0, max=360.0, unit='deg', group='Placement'),
        P('giver_size', 'float', gs, 'Mission giver box size', 'Edge length of the walk-in box in metres. Boxes of different missions must stay at least 3 m apart (4 m is better).', min=2.0, max=16.0, unit='m', group='Placement'),
        P('giver_height', 'float', c.get('giver_height', 4.0), 'Mission giver box height', 'Height of the walk-in box in metres.', min=2.0, max=12.0, unit='m', group='Placement', advanced=True),
        P('start_spot', 'choice', c.get('start_spot') or (lambda h, p: h.start_spot), 'Start spot', 'The teleport spot of the host map the player is put at when the mission starts (default: the map arrival).', choices=(None if c.get('start_spot') else (lambda h: h.spots)), group='Placement', advanced=bool(c.get('start_spot'))),
        P('name', 'text', c['name'], 'Mission name', 'Shown in the offer screen, the loading screen and the result screen.', group='Texts', max_len=40),
        P('description', 'text', c['description'], 'Mission description', 'The paragraph of the offer screen.', group='Texts', max_len=300),
        P('load_mid', 'text', c.get('load_mid', ''), 'Loading screen line 1', 'Big line of the loading screen (empty = the mission name).', group='Texts', max_len=40),
        P('load_low', 'text', c.get('load_low', ' '), 'Loading screen line 2', 'Small line of the loading screen.', group='Texts', max_len=40),
        P('pass_score', 'int', c.get('pass_score', 0), 'Pass score', 'Action points needed to PASS (bronze medal row). A pass score the mission cannot pay turns success into "YOU NEED AT LEAST N POINTS": the template checks it.', min=0, max=100000, unit='pts', group='Scores'),
        P('silver_score', 'int', c.get('silver_score'), 'Silver score', 'Action points for the second medal row. Empty = keep the template value.', min=0, max=100000, unit='pts', group='Scores'),
        P('gold_score', 'int', c.get('gold_score'), 'Gold score', 'Action points for the first (top) medal row. Empty = keep the template value.', min=0, max=100000, unit='pts', group='Scores'),
    ]


COMMON_KEYS = ('giver_pos', 'giver_yaw', 'giver_size', 'giver_height', 'start_spot', 'name', 'description', 'load_mid', 'load_low', 'pass_score', 'silver_score', 'gold_score')


def full_schema(mod):
    return common_params(mod.COMMON) + list(mod.PARAMS)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _norm_point(v, key):
    if not isinstance(v, (list, tuple)) or len(v) not in (2, 3):
        raise ParamError('%s: a point is [x, y, z] (y may be null) or [x, z]' % key)
    if len(v) == 2:
        v = [v[0], None, v[1]]
    if not (_is_num(v[0]) and _is_num(v[2]) and (v[1] is None or _is_num(v[1]))):
        raise ParamError('%s: point coordinates must be numbers (y may be null)' % key)
    return [float(v[0]), None if v[1] is None else float(v[1]), float(v[2])]


def resolve(mod, params, host):
    """Fill defaults, coerce types and check ranges. Returns (p, messages) - messages = [(level, text)] in plain English; level 'error' blocks a build.
    Unknown keys are errors (a typo must not silently do nothing)."""
    schema = full_schema(mod)
    by = {s.key: s for s in schema}
    msgs = []
    params = dict(params or {})
    for k in params:
        if k not in by:
            msgs.append(('error', 'Unknown setting "%s" for a %s mission (known: %s).' % (k, mod.NAME, ', '.join(sorted(by)))))
    p = {}
    for s in schema:
        given = s.key in params and params[s.key] is not None
        v = params[s.key] if given else s.default_for(host, p)
        try:
            v = _coerce(s, v, host)
            _range(s, v, host, msgs)
        except ParamError as e:
            msgs.append(('error', str(e)))
        p[s.key] = v
    return p, msgs


def _coerce(s, v, host):
    k = s.kind
    if v is None and s.default is None:
        return None                                   # optional setting left empty (e.g. 'keep the template medal score')
    if k == 'float':
        if not _is_num(v):
            raise ParamError('%s must be a number' % s.label)
        return float(v)
    if k == 'int':
        if not _is_num(v) or int(v) != v:
            raise ParamError('%s must be a whole number' % s.label)
        return int(v)
    if k == 'angle':
        if not _is_num(v):
            raise ParamError('%s must be a number (degrees)' % s.label)
        return float(v)
    if k == 'bool':
        if not isinstance(v, bool):
            raise ParamError('%s must be true or false' % s.label)
        return v
    if k == 'text':
        if not isinstance(v, str):
            raise ParamError('%s must be text' % s.label)
        return v
    if k == 'choice':
        return v
    if k == 'point':
        return _norm_point(v, s.label)
    if k == 'points':
        if not isinstance(v, (list, tuple)):
            raise ParamError('%s must be a list of points' % s.label)
        return [_norm_point(x, s.label) for x in v]
    if k == 'rects':
        if not isinstance(v, (list, tuple)) or not all(isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(x) for x in r) for r in v):
            raise ParamError('%s must be a list of rectangles [x0, z0, x1, z1]' % s.label)
        return [[float(x) for x in r] for r in v]
    if k == 'floats':
        if not isinstance(v, (list, tuple)) or not all(_is_num(x) for x in v):
            raise ParamError('%s must be a list of numbers' % s.label)
        return [float(x) for x in v]
    if k == 'texts':
        if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) for x in v):
            raise ParamError('%s must be a list of texts' % s.label)
        return list(v)
    if k == 'rect':
        if not isinstance(v, (list, tuple)) or len(v) != 4 or not all(_is_num(x) for x in v):
            raise ParamError('%s must be a rectangle [x0, z0, x1, z1]' % s.label)
        return [float(x) for x in v]
    raise ParamError('bad kind %s' % k)


def _range(s, v, host, msgs):
    if v is None:
        return
    if s.kind in ('float', 'int', 'angle'):
        if s.min is not None and v < s.min:
            raise ParamError('%s is %g; it must be at least %g%s.' % (s.label, v, s.min, (' ' + s.unit) if s.unit else ''))
        if s.max is not None and v > s.max:
            raise ParamError('%s is %g; it must be at most %g%s.' % (s.label, v, s.max, (' ' + s.unit) if s.unit else ''))
    elif s.kind == 'text':
        if s.max_len is not None and len(v) > s.max_len:
            raise ParamError('%s is %d characters; at most %d fit.' % (s.label, len(v), s.max_len))
        if '\n' in v and s.key != 'description':
            raise ParamError('%s must be one line.' % s.label)
    elif s.kind == 'choice':
        ch = s.choices(host) if callable(s.choices) else s.choices
        if ch and v not in ch:
            raise ParamError('%s "%s" is not one of: %s.' % (s.label, v, ', '.join(map(str, ch))))
    elif s.kind in ('points', 'floats', 'texts', 'rects'):
        if s.min_len is not None and len(v) < s.min_len:
            raise ParamError('%s needs at least %d points (has %d).' % (s.label, s.min_len, len(v)))
        if s.max_len is not None and len(v) > s.max_len:
            raise ParamError('%s allows at most %d points (has %d).' % (s.label, s.max_len, len(v)))


def schema_json(mod, host=None):
    """the parameter schema of a template as plain data (for the UI); with a host the defaults are laid out on that host"""
    p = {}
    out = []
    for s in full_schema(mod):
        d = s.describe(host, p)
        if s.kind == 'choice' and callable(s.choices):
            d['choices'] = s.choices(host) if host is not None else None
        out.append(d)
        if host is not None:
            try:
                p[s.key] = d.get('default')
            except Exception:                                   # noqa: BLE001
                pass
    return dict(name=mod.NAME, title=mod.TITLE, summary=mod.SUMMARY, host_needs=list(mod.HOST_NEEDS), params=out)


# ------------------------------------------------------------------------------------------------ the mission index pool
REG_FRAGMENTS = ('Missions.fragment', 'MissionDict.fragment')
SPECIFIC_MISSION_MAX_NUM = 81          # common.DB_MISSIONDICT_LIST holds indices 0..80 (docs/subsystem_mission_scripting.md 19.4); a FIXED cap


def registered_indices(base_chain=None, E=None):
    """mission indices that already have a registry folder or award record in the base game's overdose.main (Missions.fragment / MissionDict.fragment)"""
    from . import tpl_env
    E = E or tpl_env.get()
    if base_chain is not None:
        tpl_env.set_chain(base_chain)
    main = E.MAIN
    bi = E.BE.BlockInfo(main, E.read(main))
    T = E.ft.types()
    used = set()
    for k, nm in bi.frs:
        if nm.split('/')[-1] not in REG_FRAGMENTS:
            continue
        d = bi.doc(nm)
        creates = {r.node: r.raw for r in d.records if r.op == 'create'}
        for r in d.records:
            if r.prop is not None and T.name(r.prop) == 'Mission':
                i = struct.unpack('<i', r.raw[:4])[0]
                ty = creates.get(r.node, b'')
                if b'database_Mission_ID' in ty or b'database_mission_award' in ty:
                    used.add(i)
    return used


_POOL_CACHE = {}


def pool(base_chain=None):
    """The FIXED pool of free mission indices of a game install: every index 0..80 without a registry record in the base game's overdose.main
    (vanilla and Gameplay+ alike: 15, 29, 43, 51, 52, 53, 57, 61, 71..79 = 17). The engine's SPECIFIC_MISSION_MAX_NUM = 81 is not raised."""
    from . import tpl_env
    if base_chain is not None:
        key = (tuple(map(str, base_chain)), tpl_env.get().overlay.active_key())
    else:
        key = None
    reg = registered_indices(base_chain)
    return sorted(set(range(SPECIFIC_MISSION_MAX_NUM)) - reg)


def _used_map(used):
    """used = iterable of indices | {project name: [indices]} -> {index: [project names]}"""
    m = {}
    if isinstance(used, dict):
        for name, idxs in used.items():
            for i in idxs:
                m.setdefault(int(i), []).append(str(name))
    else:
        for i in used or ():
            m.setdefault(int(i), []).append('another project')
    return m


def free_indices(base_chain=None, used=()):
    """free_indices(base) = the pool minus the indices already used by installed or other projects.
    base_chain: the game's archive chain (see build()); None = whatever the tools read now. used: iterable of indices, or {project: [indices]}."""
    um = _used_map(used)
    return [i for i in pool(base_chain) if i not in um]


def pool_message(base_chain, used, wanted):
    """plain-language refusal when `wanted` new missions do not fit, else None"""
    full = pool(base_chain)
    um = _used_map(used)
    free = [i for i in full if i not in um]
    if wanted <= len(free):
        return None
    taken = sorted({n for i, ns in um.items() if i in full for n in ns})
    n_used = len([i for i in um if i in full])
    return ('This game install can have at most %d new missions; %d are already used%s. This project needs %d but only %d %s left.'
            % (len(full), n_used, (' by ' + ', '.join(taken)) if taken else '', wanted, len(free), 'slot is' if len(free) == 1 else 'slots are'))


# ------------------------------------------------------------------------------------------------ text rows
MISSION_TEXT0, OBJECTIVE_TEXT0 = 321, 345      # blank uk_Mission / uk_Objective ordinals (321.. and 345..382 are empty strings in the shipped file)
MISSION_TEXT_MAX, OBJECTIVE_TEXT_MAX = 693, 1023
LOAD_TEXT0 = 500                                # uk_Mission rows for the loading screen's mid / low lines


def alloc_texts(spec, rank, obj_next):
    """key -> ordinal for one mission. Mission rows are a pure function of the index's RANK in the pool: name block 321 + 4 * rank (name, description,
    real name, teaser), loading lines 500 + 2 * rank. Objective rows (their count differs per template) are sequential from `obj_next` in
    index order (rows above 351 are appended by the text tool)."""
    m0 = MISSION_TEXT0 + 4 * rank
    t = {'name': m0, 'description': m0 + 1, 'real_name': m0 + 2, 'teaser': m0 + 3, 'load_mid': LOAD_TEXT0 + 2 * rank, 'load_low': LOAD_TEXT0 + 2 * rank + 1}
    objs = spec.TEXT['objectives']
    if len(objs) > 8:
        raise ParamError('%s: at most 8 objective texts per mission' % spec.NAME)
    for i, (key, _txt) in enumerate(objs):
        t['@' + key] = obj_next + i
    if m0 + 3 >= LOAD_TEXT0 or t['load_low'] > MISSION_TEXT_MAX or obj_next + len(objs) - 1 > OBJECTIVE_TEXT_MAX:
        raise ParamError('%s: text rows out of the blank range' % spec.NAME)
    return t
