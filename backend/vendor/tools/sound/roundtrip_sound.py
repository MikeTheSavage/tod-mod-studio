"""Round-trip proof for the sound codecs over the whole GOG install (read only).

  A  every SOUND record (type 7) of every block: parse -> build() == shipped bytes
  B  every block holding SOUND records rebuilt through rebuild_block_sounds() with all its SOUND records
     "replaced" by themselves == shipped block (sha256)
  C  every STREAMEDSOUNDINFO record (type 8) patched in place with its own samples/rate/channels == shipped bytes,
     and every block rebuilt from the patched INFO == shipped block
  D  every sound archive entry (sounds.naz, uk_sounds.naz): packed into a STORED override zip with the shipped
     bytes, read back through the engine's OpenZip/FindFile port == the archive entry (one zip per archive, temp dir)
"""
import sys, os, json, time, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import lowprio  # noqa: F401
import todblock as tb
import todsound as ts


def main(out_json):
    t0 = time.time()
    arcs = ts.open_archives()
    a = arcs['blocks.naz']
    rep = dict(A_sound_records=0, A_fail=[], B_blocks=0, B_fail=[], C_records=0, C_blocks=0, C_fail=[],
               D_entries={}, D_fail=[])
    for bn in sorted(a.names):
        ext = os.path.splitext(bn)[1].lower()
        if ext not in tb.BLOCK_EXTS:
            continue
        raw = a.read(bn)
        b = tb.Block(raw, ext)
        info = bytes(b.info)
        srec = ts.sound_records(b)
        for k, r in srec:
            if r.build() != info[r.R:r.E]:
                rep['A_fail'].append([bn, k])
            rep['A_sound_records'] += 1
        if srec:
            nb, _ = ts.rebuild_block_sounds(b, {k: {} for k, _ in srec})
            if nb.serialize() != raw:
                rep['B_fail'].append(bn)
            rep['B_blocks'] += 1
        s8 = ts.streamed_records(b)
        if s8:
            inf = bytearray(info)
            for k, R in s8:
                d = ts.read_streamedsoundinfo(inf, R)
                ts.patch_streamedsoundinfo(inf, R, d['samples'], d['rate'], d['channels'])
                rep['C_records'] += 1
            if bytes(inf) != info:
                rep['C_fail'].append(bn)
            nb = tb.Block(raw, ext)
            nb.info = inf
            if nb.serialize() != raw:
                rep['C_fail'].append(bn + ' (block)')
            rep['C_blocks'] += 1
    with tempfile.TemporaryDirectory() as td:
        for an in ts.SOUND_ARCHIVES:
            arc = arcs[an]
            ents = [(e['name'], arc.read(e['name'])) for e in arc.entries]
            zp = os.path.join(td, an + '.zip')
            ts.write_stored_zip(zp, ents)
            try:
                rep['D_entries'][an] = ts.zip_readback(zp, ents)
            except Exception as ex:
                rep['D_fail'].append('%s: %s' % (an, ex))
    rep['seconds'] = round(time.time() - t0, 1)
    rep['pass'] = not (rep['A_fail'] or rep['B_fail'] or rep['C_fail'] or rep['D_fail'])
    json.dump(rep, open(out_json, 'w'), indent=1)
    print(json.dumps(rep, indent=1))
    return 0 if rep['pass'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'sound_roundtrip.json')))
