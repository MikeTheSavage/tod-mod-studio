"""Census of every sound-related entity in every fragment of every block of blocks.naz (read only).

Collects: entities whose type mentions Sound/Music/Speak/Subtitle/Trigger_Activate_Sound/Soundtrigger, and every set
record of a sound-related property (sound, streaming_sound, Music_slot, Combo_Music, In_Mission_Combo_Music,
Loop_Sound, Rand1_Sound, Rand2_Sound, ...). Usage: sound_census.py [OUT_DIR] -> OUT_DIR/sound_census.json + summary.
"""
import sys, os, json, collections, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _p in (os.environ.get('TOD_FRAG'), os.path.join(HERE, '..', 'fragment_writer'), os.path.join(HERE, '..', 'frag')):
    if _p and os.path.exists(os.path.join(_p, 'todfrag.py')):
        sys.path.insert(0, os.path.abspath(_p))
        break
sys.dont_write_bytecode = True
import lowprio  # noqa: F401
import todblock as tb
import todfrag as tf

NAZ = r"C:\GOG Games\Total Overdose\blocks.naz"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
TYPE_RE = re.compile(r'sound|music|speak|subtit|emitter', re.I)
PROPS = ['sound', 'streaming_sound', 'Music_slot', 'Queue_Music', 'Allow_Combo_to_stop_Music', 'Music_entity',
         'Combo_Music', 'In_Mission_Combo_Music', 'Disable_Combo_Music', 'Loop_Sound', 'Rand1_Sound', 'Rand2_Sound',
         'Sound_Trigger_Type', 'Loop_Vol', 'Loop_Crossfade', 'Rand1_Vol', 'Rand2_Vol', 'Rand1_Min_Pause',
         'Rand1_Max_Pause', 'Rand2_Min_Pause', 'Rand2_Max_Pause', 'no_sounds', 'TextIndex_SOUND',
         'default_fx_volume', 'default_ambience_volume', 'default_music_volume', 'default_speaks_volume',
         'Setting_music', 'Setting_speak', 'MusicValue', 'SpeakValue', 'Engine_SoundID', 'Door_Open_Sound',
         'Combo_Sound_Level1', 'Combo_Sound_Level2', 'Combo_Sound_Level3', 'Combo_Sound_Level4', 'TauntID', 'MoveSound',
         'ActivationSound', 'SpeakType', 'Specific_ID', 'Sub_Type']


def main():
    T = tf.Types()
    want = {}
    for nm in PROPS:
        try:
            want[T.index(nm)] = nm
        except Exception:
            pass
    name_idx = T.index('name')
    a = tb.Archive(NAZ)
    ents = []
    propvals = collections.defaultdict(collections.Counter)
    for bn in sorted(a.names):
        ext = os.path.splitext(bn)[1].lower()
        if ext not in tb.BLOCK_EXTS:
            continue
        b = tb.Block(a.read(bn), ext)
        info = bytes(b.info)
        st = tb.record_starts(info, b.n)
        for k, R in enumerate(st):
            if tb.u32(info, R) != 4 or len(b.payloads[k]) <= 0x18:
                continue
            fname = tb.record_name(info, R)
            fr = tf.Fragment(b.payloads[k], T)
            for node, e in fr.entities().items():
                vals = {}
                nm = None
                for r in e['sets']:
                    if r.prop == name_idx:
                        nm = fr.value(r)
                    if r.prop in want:
                        vals[want[r.prop]] = fr.value(r)
                ty = e['type'] or ''
                if TYPE_RE.search(ty) or vals:
                    ents.append(dict(block=bn, fragment=fname, node='0x%08X' % node, type=ty, name=nm, props=vals))
                    for kk, v in vals.items():
                        propvals[kk][json.dumps(v)] += 1
    json.dump(ents, open(os.path.join(OUT, 'sound_census.json'), 'w'), indent=0)
    print('entities', len(ents))
    tc = collections.Counter(e['type'] for e in ents)
    for t, c in tc.most_common(60):
        print('  %6d %s' % (c, t))
    for kk in PROPS:
        if kk in propvals:
            c = propvals[kk]
            print('%-28s %6d values, %4d distinct: %s' % (kk, sum(c.values()), len(c), c.most_common(8)))


if __name__ == '__main__':
    main()
