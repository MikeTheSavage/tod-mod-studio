"""Test saves (tools/save_editor): copy one of the player's save slots, put Ram at a chosen spot (optionally restart a
mission, heal, give weapons) and write the result as a new slot file. The app never edits a slot in place: the new
file goes to the app's folder, and installing it into the game's save folder backs up any slot it replaces."""
import datetime
import os
import shutil

from . import paths


def saves_dir():
    """The game's save folder. TODMS_SAVES overrides it (tests and the proof environment never touch the real saves)."""
    return os.environ.get('TODMS_SAVES') or os.path.join(os.path.expanduser('~'), 'Documents', 'Total Overdose', 'savegames')


def out_dir():
    d = os.path.join(paths.user_dir(), 'saves')
    os.makedirs(d, exist_ok=True)
    return d


def _modules(ws):
    os.environ['TOD_GAME_DIR'] = ws.game.folder
    import sys
    se = os.path.join(paths.VENDOR, 'save_editor')
    if se not in sys.path:
        sys.path.append(se)
    import savefile
    import editlib
    savefile.GAME_DIR = ws.game.folder
    return savefile, editlib


def list_slots(ws, folder=None):
    folder = folder or saves_dir()
    out = []
    if not os.path.isdir(folder):
        return dict(folder=folder, slots=[])
    savefile, editlib = _modules(ws)
    for fn in sorted(os.listdir(folder)):
        p = os.path.join(folder, fn)
        if not fn.lower().startswith('slot') or os.path.getsize(p) != 0x50000 or fn.lower() == 'slot11':
            continue
        rec = dict(name=fn, path=p, modified=datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(
            timespec='seconds'))
        try:
            s = editlib.Save(savefile.decode(open(p, 'rb').read()))
            sm = editlib.summary(s)
            rec['summary'] = {k: v for k, v in sm.items() if k not in ('weapons', 'powerups', 'missions')}
            rec['pos'] = s.player_pos()
        except Exception as e:
            rec['error'] = str(e)[:200]
        out.append(rec)
    return dict(folder=folder, slots=out)


CHEATS = (('god', 'GodModeOn'), ('ammo', 'UnlimitedAmmo'))


def missions(ws, source):
    """The valid missions of a save, for a "start this mission" list: [{i, name, type}]."""
    savefile, editlib = _modules(ws)
    s = editlib.Save(savefile.decode(open(source, 'rb').read()))
    return [dict(i=m['i'], name=m['name'], type=m['type']) for m in editlib.summary(s)['missions']]


_AWARDS = {}


def award_submaps(ws):
    """{mission index: Mission_SubMap} from the game's mission awards: the submap the engine loads when the mission starts.
    (The mission list in a save holds the award's Mission_StartMap instead, which differs for missions 5, 8, 10, 18, 20 and 23.)"""
    from . import newmap
    key = (ws.game.base(), getattr(ws.game, 'naz', None))
    if key in _AWARDS:
        return _AWARDS[key]
    r = newmap.load_recipe()
    ft, fe, tb, S = r.ft, r.fe, r.tb, r.S
    old = (ft._arch, ft.GOG_NAZ)
    out = {}
    try:
        ft._arch, ft.GOG_NAZ = ws.game.base(), ws.game.naz
        T = ft.types()
        b = tb.Block(ft.archive().read(r.MAIN), '.main')
        for nm, k in S.frags_of(b).items():
            if 'missiondict' not in nm.lower():
                continue
            d = fe.FragDoc(b.payloads[k], T, nm)
            for n in d.created_ids():
                if (d.type_of(n) or '').startswith('database_mission_award'):
                    m, sub = d.get(n, 'Mission'), d.get(n, 'Mission_SubMap')
                    if m is not None and sub is not None:
                        out[int(m)] = int(sub)
    finally:
        ft._arch, ft.GOG_NAZ = old
    _AWARDS[key] = out
    return out


# A save made by start_mission loads its blocks but the game then fails on the first script read (fault 0xC0000005 at 0x489E50, or a
# hang), also from a save with a map loaded (M0 q9 runs, 2026-11-15). Such saves are for inspection only.
START_MISSION_PLAYABLE = False
START_MISSION_NOTE = 'A save that starts a mission cannot be played yet: the game stops on it. Walk to the mission giver instead.'


def make(ws, source, pos=None, yaw=None, heal=False, weapons=False, start_mission=None, name=None, god=False, ammo=False, unlock=None,
         dest=None):
    """A new save file from a copy of `source`. god / ammo write the game's own cheat flags (master_control_cheat_ctrl), unlock 'open' opens
    every mission. The slots do not keep a mission's script step, so the furthest a save can start a mission is its beginning."""
    savefile, editlib = _modules(ws)
    s = editlib.Save(savefile.decode(open(source, 'rb').read()))
    log = []
    if start_mission is not None:
        try:
            sub = award_submaps(ws).get(int(start_mission))
        except Exception:                               # noqa: BLE001  (an unreadable award table keeps the old source)
            sub = None
        r = editlib.start_mission(s, int(start_mission), player_at_teleport=pos is None, submap=sub)
        log.append(['start_mission', {k: v for k, v in r.items() if k not in ('moved', 'blocks')}])
        log.append(['not_playable', START_MISSION_NOTE])
    if pos is not None:
        log.append(['move_player', s.move_player([float(x) for x in pos], None if yaw is None else float(yaw))])
    if heal:
        log.append(['heal', s.heal()])
    if weapons:
        s.give_weapons('all', 'max')
        log.append(['give_weapons', 'all'])
    if unlock in ('open', 'complete'):
        log.append(['unlock', s.unlock(unlock)])
    notes = []
    for want, prop in ((god, 'GodModeOn'), (ammo, 'UnlimitedAmmo')):
        if not want:
            continue
        try:
            k = s.node1(r'master_control_cheat_ctrl\(NodeLogical\)')
            log.append(['cheat', prop, s.set(k, prop, True)])
        except (KeyError, ValueError) as e:
            notes.append('%s could not be written into this save: %s' % (prop, e))
    b = savefile.encode(s.j)
    j2 = savefile.decode(b)
    ok = all(j2['checks'].values()) and not j2['parse_problems']
    if not ok:
        raise RuntimeError('the rebuilt save does not decode cleanly: %s' % j2['checks'])
    fn = name or 'TestSave_%s' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    d = dest or out_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, fn)
    open(p, 'wb').write(b)
    return dict(path=p, bytes=len(b), log=log, notes=notes, checks=j2['checks'], player=editlib.Save(j2).player_pos())


def install(ws, made, slot_name, folder=None):
    """Copy a made save into the game's save folder as slot_name (e.g. Slot09); an existing slot is backed up."""
    if not slot_name.lower().startswith('slot') or slot_name.lower() == 'slot11':
        raise ValueError('pick a save slot name like Slot09 (Slot11 holds the settings)')
    folder = folder or saves_dir()
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, slot_name)
    bak = None
    if os.path.exists(dst):
        bak = os.path.join(out_dir(), 'backup_%s_%s' % (slot_name, datetime.datetime.now().strftime('%Y%m%d_%H%M%S')))
        shutil.copy2(dst, bak)
    shutil.copy2(made, dst)
    return dict(installed=dst, backup=bak)


def migrate_missions(ws, source, install_as=None, folder=None, progress=None):
    """Update a COPY of a save so every mission installed through the mission templates can be started (without it, pressing
    the use key at a new mission giver closes the game). Never touches the source; installing the copy backs up the slot it replaces."""
    from . import missions_tpl
    rec = missions_tpl.installed(ws.game.folder)
    if not rec.get('migrate_entries'):
        raise ValueError('No mission templates are installed in this game folder, so there is nothing to update a save for.')
    savefile, editlib = _modules(ws)
    import json
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out = os.path.join(out_dir(), 'Updated_%s_%s' % (os.path.basename(source), stamp))
    manifest = out + '.manifest.json'
    json.dump(dict(migrate_entries=rec['migrate_entries'], thread_keys=rec.get('thread_keys', [])), open(manifest, 'w'))
    if os.path.abspath(out) == os.path.abspath(source):
        raise ValueError('The updated copy would overwrite the save it was made from')
    with missions_tpl.session(ws) as L:
        th = L.migrate_save_copy(manifest, source, out,
                                 migrate_py=os.path.join(paths.BACKEND, 'vendor', 'missions', 'migrate_save.py')) or {}
    r = dict(path=out, missions=len(rec['migrate_entries']), givers_patched=len(th.get('patched', [])), notes=[])
    for s in th.get('skipped', []):
        r['notes'].append('The giver box of mission %s in %s will not offer from this save until that section is reloaded once '
                          '(start or finish any mission, or walk through a map loader): %s.' % (s.get('mission'), s.get('block'), s.get('reason')))
    if install_as:
        r['install'] = install(ws, out, install_as, folder)
    return r
