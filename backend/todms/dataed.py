"""Data editors over the tools that already exist: weapons (tools/weapons), vehicles (tools/vehicles/vehtool),
loco moves and slow motion (tools/loco/locotool, data part), camera (tools/camera/camtool, data part).

Each editor has read(ws) -> {fields: [...]} for a form, and ops(ws, values) -> {entry: [fragment writer ops]} that the
builder applies to the user's base blocks (TOD HD's when it is installed) together with the level edits.
Code constants (proxy DLL settings) are listed read-only: they need the project's proxy DLLs, which this app does not
install.
"""
import os

from .game import MAIN_ENTRY, SHARED


def _full(entry):
    if '/' in entry:
        return entry
    return SHARED + entry


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------------------------------------- weapons
def _weapons_main(ws):
    import weapons as w
    import todblock as tb
    import fragtool as ft
    raw, _ = ws.read_block(MAIN_ENTRY)
    m = w.Main.__new__(w.Main)
    m.raw, m.entry, m.ext = raw, MAIN_ENTRY, '.main'
    m.b = tb.Block(raw, '.main')
    m.frs, _ = ft.fragments(m.b)
    m.T = ft.types()
    m.docs = {}
    return m


WEAPON_FIELDS = ['ClipSize', 'ReloadTime', 'FireRate', 'ManualFireRate', 'BulletsPerShot', 'ShortRangeDamage',
                 'MediumRangeDamage', 'LongRangeDamage', 'ShortRange', 'MediumRange', 'MaxRange', 'SpreadMin',
                 'SpreadMax', 'SpreadInc', 'SpreadEnemy', 'AimFocus', 'speed']


def weapons_read(ws):
    import weapons as w
    m = _weapons_main(ws)
    data = w.collect(m)
    rows = []
    for r in data['subtypes']:
        e = r['effective']
        fields = [dict(key='weapons.%s.%s' % (r['gun'], f), label=f, value=e.get(f),
                       help=(w.FIELD_INFO.get(f) or ('', ''))[0])
                  for f in WEAPON_FIELDS if f in e and _num(e.get(f))]
        if r.get('bullet') and _num(r['bullet'].get('speed')):
            fields.append(dict(key='bullets.%s.speed' % r['gun'], label='bullet speed', value=r['bullet']['speed'],
                               help='BulletManager speed (m/s)'))
        rows.append(dict(group='%s (%s)' % (r['gun'], r['name']), fields=fields))
    ps = data['player_status']
    rows.append(dict(group='Ammo carried (PlayerStatus)', fields=[
        dict(key='player_status.%s' % k, label=k, value=v) for k, v in sorted(ps.items())
        if k.startswith(('Default_max_clips', 'Default_clips')) and _num(v)]))
    bd = data['bullet_drop']
    rows.append(dict(group='Ammo dropped by enemies (BulletDrop)', fields=[
        dict(key='bullet_drop.%s' % k, label=k, value=v) for k, v in sorted(bd.items()) if _num(v)]))
    return dict(editor='weapons', groups=rows, note='Values are the effective ones the game uses; the tool converts '
                'them to the authored fields (tools/weapons/weapons.py).')


def weapons_ops(ws, values):
    import weapons as w
    spec = {}
    for key, v in values.items():
        parts = key.split('.')
        if parts[0] in ('weapons', 'bullets'):
            spec.setdefault(parts[0], {}).setdefault(parts[1], {})[parts[2]] = v
        elif parts[0] in ('player_status', 'bullet_drop', 'cheat_ctrl', 'goodies'):
            spec.setdefault(parts[0], {})[parts[1]] = v
    if not spec:
        return {}
    m = _weapons_main(ws)
    ops, notes = w.build_ops(m, spec)
    return {MAIN_ENTRY: ops}


# ---------------------------------------------------------------------------------------------- vehicles
VEH_GROUPS = [('type.', 'Vehicle types (VehicleDict)'), ('car.cam.', 'Car camera'), ('car.', 'Car handling (all cars)'),
              ('bike.', 'Dirt bike'), ('traffic.', 'Traffic'), ('res.', 'Vehicle pools'), ('status.', 'Aim in vehicles'),
              ('lod.', 'Level of detail'), ('physic.', 'Physics'), ('camdict.', 'Vehicle default camera')]


def _veh_blocks(ws):
    import vehtool as vt
    entries = set()
    for blocks, *_ in vt.TUN.values():
        entries.update(blocks)
    over = {}
    for e in entries:
        try:
            over[e] = ws.read_block(_full(e))[0]
        except KeyError:
            pass
    return vt.Blocks(over)


def vehicles_read(ws):
    import vehtool as vt
    B = _veh_blocks(ws)
    vals, src = vt.read_values(B)
    groups = {}
    for n, v in vals.items():
        if not _num(v):
            continue
        if n.endswith('.Specific_ID'):
            continue
        g = next((label for pre, label in VEH_GROUPS if n.startswith(pre)), 'Other')
        if n.startswith('type.'):
            g = 'Vehicle type: %s' % n.split('.')[1]
        groups.setdefault(g, []).append(dict(key=n, label=n.split('.')[-1], value=v, help=vt.TUN[n][4],
                                             source=src.get(n)))
    return dict(editor='vehicles', groups=[dict(group=g, fields=f) for g, f in groups.items()],
                note='tools/vehicles/vehtool.py; values that are "code default" are not in the data yet: changing '
                     'one adds the property record.')


def _sane_vehicle_value(name, v):
    """A number the car code cannot divide by or run away with: finite everywhere, and a car mass above zero."""
    if v != v or v in (float('inf'), float('-inf')):
        return False
    return not (name.endswith('.Mass') and v <= 0)


def vehicles_ops(ws, values):
    import vehtool as vt
    import fragtool as ft
    per = {}
    for n, v in values.items():
        if n not in vt.TUN:
            raise KeyError('unknown vehicle value %s' % n)
        if _num(v) and not _sane_vehicle_value(n, v):
            raise ValueError('%s = %s would break the car' % (n, v))
        blocks, frag, sel, prop, note, dflt = vt.TUN[n]
        for e in blocks:
            per.setdefault(_full(e), []).append(dict(op='set', fragment=frag, entity=sel, prop=prop, value=v))
    return per


# ---------------------------------------------------------------------------------------------- loco / slow motion
def _loco_main(ws):
    import locotool as lt
    raw, _ = ws.read_block(MAIN_ENTRY)
    m = lt.Main.__new__(lt.Main)
    m.raw, m.entry, m.ext = raw, MAIN_ENTRY, '.main'
    m.load(raw)
    return m


def loco_read(ws):
    import locotool as lt
    m = _loco_main(ws)
    tab = lt.all_data(m)
    vals = lt.data_values(m, tab)
    groups = {}
    for n, (frag, sel, prop, dflt, note) in tab.items():
        v = vals.get(n)
        if v is None:
            v = dflt
        if not (_num(v) or isinstance(v, bool)):
            continue
        g = n.split('.')[0]
        label = {'powerup': 'Loco moves and power-ups', 'stamina': 'Slow motion and stamina', 'award': 'Combo awards',
                 'combo': 'Combo system', 'move': 'Combo move points', 'goodie': 'Pickups',
                 'blur': 'Slow-motion blur', 'cheat': 'Cheats', 'rewind': 'Rewind'}.get(g, g.capitalize())
        groups.setdefault(label, []).append(dict(key=n, label='.'.join(n.split('.')[1:]), value=v, help=note))
    code = [dict(key=k, help=v[-1] if isinstance(v, tuple) else '') for k, v in list(getattr(lt, 'CODE', {}).items())[:60]]
    return dict(editor='loco', groups=[dict(group=g, fields=f) for g, f in groups.items()],
                code_only=code, note='Data values of tools/loco/locotool.py. Code constants (slow-motion scales, '
                'Tornado, ...) need the locotune proxy DLL and are not changed by this app.')


def loco_ops(ws, values):
    import locotool as lt
    m = _loco_main(ws)
    tab = lt.all_data(m)
    ops = []
    for n, v in values.items():
        if n not in tab:
            raise KeyError('unknown loco value %s' % n)
        ops.append(dict(op='set', fragment=tab[n][0], entity=tab[n][1], prop=tab[n][2], value=lt.coerce(m, tab[n], v)))
    return {MAIN_ENTRY: ops} if ops else {}


# ---------------------------------------------------------------------------------------------- camera
def _cam_blocks(ws):
    import camtool as ct
    blocks = {}
    raw, _ = ws.read_block(MAIN_ENTRY)
    blocks[ct.MAIN] = ct.Blk(ct.MAIN, data=raw, entry=MAIN_ENTRY)
    for mb in ct.DIRTBIKE_MISSIONS:
        try:
            r, _ = ws.read_block(_full(mb))
            blocks[mb] = ct.Blk(mb, data=r, entry=_full(mb))
        except KeyError:
            pass
    return blocks


def camera_read(ws):
    import camtool as ct
    blocks = _cam_blocks(ws)
    c = ct.collect(blocks=blocks)
    groups = []
    cc = c['player']['CameraCtrl']
    groups.append(dict(group='Player camera (offsets in metres)', fields=[
        dict(key='player.back', label='move back', value=0.0, help='moves the camera back along its line of sight'),
        dict(key='player.up', label='move up', value=0.0, help='raises the camera'),
        dict(key='player.pitch_deg', label='pitch (deg, empty = keep)', value=None, help='downward pitch')]))
    for t, kv in c['cameradict'].items():
        if not t:
            continue
        groups.append(dict(group='Camera type %s' % t, fields=[
            dict(key='cameradict.%s.%s' % (t, k), label=k, value=v) for k, v in kv.items() if _num(v)]))
    gc = c['gamecamera']['scene']
    groups.append(dict(group='Game camera', fields=[dict(key='gamecamera.farclip', label='far clip (m)',
                                                         value=gc.get('farclip'), help='draw distance')]))
    groups.append(dict(group='Vehicle cameras', fields=[
        dict(key='vehicles.back', label='move back (all vehicles)', value=0.0),
        dict(key='vehicles.up', label='move up (all vehicles)', value=0.0)]))
    return dict(editor='camera', groups=groups, note='tools/camera/camtool.py, data part. Field of view and near clip '
                'are set by code at start and need the camfov proxy, which this app does not install.')


def camera_ops(ws, values):
    import camtool as ct
    spec = {}
    for key, v in values.items():
        if v is None or v == '':
            continue
        p = key.split('.')
        if p[0] == 'player':
            spec.setdefault('player', {})[p[1]] = float(v)
        elif p[0] == 'cameradict':
            spec.setdefault('cameradict', {}).setdefault(p[1], {})[p[2]] = float(v)
        elif p[0] == 'gamecamera':
            spec.setdefault('gamecamera', {})[p[1]] = float(v)
        elif p[0] == 'vehicles':
            spec.setdefault('vehicles', {})[p[1]] = float(v)
    if not spec:
        return {}
    blocks = _cam_blocks(ws)
    ops, notes = ct.plan(spec, blocks)
    out = {}
    for bn, o in ops.items():
        out.setdefault(_full(blocks[bn].entry if bn in blocks else bn), []).extend(o)
    return out


EDITORS = {
    'weapons': (weapons_read, weapons_ops),
    'vehicles': (vehicles_read, vehicles_ops),
    'loco': (loco_read, loco_ops),
    'camera': (camera_read, camera_ops),
}


def all_ops(ws, data):
    """data = {editor: {key: value}} -> {entry: [ops]} (editors applied in a fixed order)."""
    out = {}
    for name in ('weapons', 'vehicles', 'loco', 'camera'):
        vals = (data or {}).get(name) or {}
        if not vals:
            continue
        for e, ops in EDITORS[name][1](ws, vals).items():
            out.setdefault(e, []).extend(ops)
    return out
