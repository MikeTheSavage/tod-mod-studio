"""Archive writer proof: every GOG .naz re-serialized by todsound.naz_stream() hashes identical to the shipped file
(nothing written). With --replace-test NEW.ogg it also writes a sounds.naz copy (237 MB, into --tmp DIR, default the
system temp folder) with mainmenu_music_loop.ogg replaced, re-reads all entries through the engine's OpenZip/FindFile
port, and deletes the copy unless --keep. Report: naz_roundtrip.json in the current folder."""
import sys, os, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import lowprio  # noqa: F401
import todblock as tb
import todsound as ts


def main():
    rep = {}
    t0 = time.time()
    for n in ('sounds.naz', 'uk_sounds.naz', 'blocks.naz'):
        p = os.path.join(ts.GOG, n)
        rep[n] = dict(shipped=ts.file_sha256(p), rewritten=ts.naz_stream(p))
        rep[n]['identical'] = rep[n]['shipped'] == rep[n]['rewritten']
        print(n, rep[n]['identical'], round(time.time() - t0, 1), 's', flush=True)
    if '--replace-test' in sys.argv:
        key = 'data/sounds/mission/submission/mainmenu_music_loop.ogg'
        new = open(sys.argv[sys.argv.index('--replace-test') + 1], 'rb').read()
        import tempfile
        tmp = sys.argv[sys.argv.index('--tmp') + 1] if '--tmp' in sys.argv else tempfile.gettempdir()
        out = os.path.join(tmp, 'naz_test', 'sounds.naz')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        ts.naz_stream(os.path.join(ts.GOG, 'sounds.naz'), {key: new}, out)
        a0 = tb.Archive(os.path.join(ts.GOG, 'sounds.naz'))
        a1 = tb.Archive(out)
        same = diff = 0
        for e in a0.entries:
            d1 = a1.read(e['name'])
            if e['name'] == key:
                ok = d1 == new and a1.find('/' + key) is not None
                rep['replaced_reads_back'] = ok
            elif d1 == a0.read(e['name']):
                same += 1
            else:
                diff += 1
        rep['replace_test'] = dict(entries=len(a0.entries), untouched_identical=same, untouched_different=diff,
                                   new_size=os.path.getsize(out), old_size=a0.fsize)
        if '--keep' not in sys.argv:
            os.remove(out)
            rep['replace_test']['copy_deleted'] = True
    rep['seconds'] = round(time.time() - t0, 1)
    json.dump(rep, open(os.path.join(os.getcwd(), 'naz_roundtrip.json'), 'w'), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    main()
