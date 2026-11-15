"""migrate_save.py - migrate a COPY of a save so it can start several NEW mission indices (data only; never in place).

  python -I migrate_save.py SRC_SAVE OUT_SAVE --entry IDX:AWARD_RUNTIME_HEX:TEMPLATE_SLOT [--entry ...] [--thread BLOCK:HEXIDX ...]

For every --entry: Mission_List[IDX] = a copy of Mission_List[TEMPLATE_SLOT] with progress reset, open, its Mission_Entity / ObjectiveList /
MissionConditions re-pointed at the new award (the deep-cloned award keeps the template award's child layout, so every entity reference is
template ref - template award + new award), and common.DB_MISSIONDICT_LIST[IDX] = the new award (docs 19.4: a loaded save restores its own
copy of that list, None at every index that was free when the save was made; accepting such an index would crash).
Same result as work/mk_saves2.py for one entry cloned from slot 33. --thread: script-thread records for appended giver boxes in an
OLD save (docs 19.5); not needed for givers inside the new map.
Refuses an OUT path equal to SRC and any path inside the user's real save folder.
"""
import argparse, json, os, sys
sys.dont_write_bytecode = True
_SAVE_EDITOR = os.path.join(os.environ.get("TOD_TOOLS") or
                            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"), "save_editor")
if _SAVE_EDITOR not in sys.path:
    sys.path.insert(0, _SAVE_EDITOR)
os.environ.setdefault("TOD_GAME_DIR", r"C:\GOG Games\Total Overdose")
import savefile, editlib

DB_MODE = os.environ.get('MIGRATE_DB_MODE', 'skip')
USER_SAVES = os.path.normcase(os.path.join(os.path.expanduser("~"), "Documents", "Total Overdose", "savegames"))


def ref_int(r):
    return int(r[2:], 16)


def ref_str(v):
    return "E1%05x" % v


def migrate(src, out, entries, threads=()):
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(src)):
        raise SystemExit('refusing to write over the source save')
    if os.path.normcase(os.path.abspath(out)).startswith(USER_SAVES):
        raise SystemExit("refusing to write into the user's save folder")
    s = editlib.Save(savefile.decode(open(src, "rb").read()))
    mc = s.mission_ctrl()
    ml = s.get(mc, "Mission_List")
    rec = [r for r in s.records() if r.get('name') == 'DB_MISSIONDICT_LIST']
    assert len(rec) <= 1
    node = rec[0]['n'] if rec else None
    lst = list(rec[0]['v']) if rec else None
    if not rec:
        print('NOTE: this save has no DB_MISSIONDICT_LIST record (db_mode=%s)' % DB_MODE)
    for idx, aw, slot in entries:
        t = ml[slot]
        tref = ref_int(t['Mission_Entity'])
        e = json.loads(json.dumps(t))
        e.update({"Mission_Valid": True, "Mission_type": 1, "Award_achived": 1, "Mission_Entity": ref_str(aw),
                  "Mission_complete": False, "Mission_open": True, "Highest_Score": -1, "Current_Score": 0, "L_Combo": 0.0,
                  "Best_Move": 0, "FollowUpMission": -1,
                  "MissionConditions": [ref_str(ref_int(c) - tref + aw) for c in t['MissionConditions']],
                  "ObjectiveList": [ref_str(ref_int(o) - tref + aw) for o in t['ObjectiveList']]})
        ml[idx] = e
        if lst is not None:
            assert lst[idx] is None, 'DB_MISSIONDICT_LIST[%d] is already %r (not a free index in this save)' % (idx, lst[idx])
            lst[idx] = ref_str(aw)
    s.set(mc, "Mission_List", ml)
    if lst is not None:
        s.set(node, 'DB_MISSIONDICT_LIST', lst)
    if threads:
        ref = [k for k in s.find_nodes('Trigger_Root_Mission.*', block=4) if any(r.get('thread') for r in s.node_records(k))][0]
        tmpl = [r for r in s.node_records(ref) if 'thread' in r][0]
        recs = s.j['records']
        for k in threads:
            b, i = savefile.parse_key(k)
            assert not s.node_records(k), k
            pos = len(recs)
            for n, r in enumerate(recs):
                if 'n' in r and savefile.parse_key(r['n']) > (b, i):
                    pos = n; break
            recs.insert(pos, {'n': k, 'p': 0, 'thread': 1, 'raw': list(tmpl['raw'])})
    open(out, "wb").write(savefile.encode(s.j))
    s2 = editlib.Save(savefile.decode(open(out, "rb").read()))
    got = [r['v'] for r in s2.records() if r.get('name') == 'DB_MISSIONDICT_LIST']
    got = got[0] if got else ['(no record)'] * 100
    ml2 = s2.get(s2.mission_ctrl(), "Mission_List")
    for idx, aw, slot in entries:
        print('migrated index %d: DB list %s, Mission_List entity %s open=%s' % (idx, got[idx], ml2[idx]['Mission_Entity'], ml2[idx]['Mission_open']))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--entry', action='append', required=True, help='IDX:AWARD_RUNTIME_HEX:TEMPLATE_SLOT')
    ap.add_argument('--thread', action='append', default=[])
    a = ap.parse_args()
    ents = []
    for e in a.entry:
        i, aw, sl = e.split(':')
        ents.append((int(i), int(aw, 16), int(sl)))
    migrate(a.src, a.out, ents, a.thread)
