"""Test saves (tools/save_editor): copy one of the player's save slots, put Ram at a chosen spot (optionally restart a
mission, heal, give weapons) and write the result as a new slot file. The app never edits a slot in place: the new
file goes to the app's folder, and installing it into the game's save folder backs up any slot it replaces."""
import datetime
import os
import shutil

from . import paths


def saves_dir():
    return os.path.join(os.path.expanduser('~'), 'Documents', 'Total Overdose', 'savegames')


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


def make(ws, source, pos=None, yaw=None, heal=False, weapons=False, start_mission=None, name=None):
    savefile, editlib = _modules(ws)
    s = editlib.Save(savefile.decode(open(source, 'rb').read()))
    log = []
    if start_mission is not None:
        r = editlib.start_mission(s, int(start_mission), player_at_teleport=pos is None)
        log.append(['start_mission', {k: v for k, v in r.items() if k not in ('moved', 'blocks')}])
    if pos is not None:
        log.append(['move_player', s.move_player([float(x) for x in pos], None if yaw is None else float(yaw))])
    if heal:
        log.append(['heal', s.heal()])
    if weapons:
        s.give_weapons('all', 'max')
        log.append(['give_weapons', 'all'])
    b = savefile.encode(s.j)
    j2 = savefile.decode(b)
    ok = all(j2['checks'].values()) and not j2['parse_problems']
    if not ok:
        raise RuntimeError('the rebuilt save does not decode cleanly: %s' % j2['checks'])
    fn = name or 'TestSave_%s' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    p = os.path.join(out_dir(), fn)
    open(p, 'wb').write(b)
    return dict(path=p, bytes=len(b), log=log, checks=j2['checks'], player=editlib.Save(j2).player_pos())


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
