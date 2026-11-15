"""Inventory every sound in sounds.naz / uk_sounds.naz (Ogg Vorbis header facts) and every SOUND (7) /
STREAMEDSOUNDINFO (8) record in blocks.naz; cross-check the block metadata against the ogg files.
Usage: inventory.py [OUT_DIR] -> ogg_inventory.json + block_sound_records.json (about 60 s, page CRCs checked)."""
import sys, os, json, collections, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
import lowprio  # noqa: F401  (BELOW_NORMAL priority)
import todblock as tb
import ogginfo
GOG = r"C:\GOG Games\Total Overdose"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()


def ogg_inventory():
    rows = []
    for arc in ('sounds.naz', 'uk_sounds.naz'):
        a = tb.Archive(os.path.join(GOG, arc))
        with open(a.path, 'rb') as f:
            for e in a.entries:
                f.seek(e['data_off'])
                d = f.read(e['size'])
                r = dict(archive=arc, name=e['name'], bytes=e['size'], data_off=e['data_off'])
                if e['name'].endswith('.ogg'):
                    try:
                        r.update(ogginfo.info(d))
                        r['seconds'] = round(r['samples'] / r['rate'], 3) if r['rate'] else 0
                    except Exception as ex:
                        r['error'] = str(ex)
                elif e['name'].endswith('.wav'):
                    r['riff'] = d[:4].decode('latin-1')
                    r['fmt'] = list(struct.unpack_from('<HHIIHH', d, 20))
                rows.append(r)
    return rows


def soundfile_struct(info, o):
    """SoundFile (60 bytes) serialized at o."""
    w = struct.unpack_from('<IIIfIIIIII', info, o)
    slen, srel, scap = struct.unpack_from('<III', info, o + 0x28)
    name_off = (o + 0x2C + (srel & ~3)) & 0xFFFFFFFF
    e = info.find(b'\0', name_off)
    return dict(f0=w[0], pcm_bytes_a=w[1], samples=w[2], bytes_per_sample=w[3], avg_bytes_per_sec=w[4],
                block_align=w[5], rate=w[6], pcm_bytes=w[7], format=w[8], flags=w[9],
                channels=(w[9] >> 5) & 0x3FFFFFF, file=info[name_off:e].decode('latin-1'),
                name_len=slen, name_cap=scap, wav_ptr=struct.unpack_from('<I', info, o + 0x34)[0],
                tail=struct.unpack_from('<I', info, o + 0x38)[0])


def block_records():
    a = tb.Archive(os.path.join(GOG, 'blocks.naz'))
    s8 = []
    s7 = []
    for e in a.entries:
        n = e['name']
        if os.path.splitext(n)[1] not in tb.BLOCK_EXTS:
            continue
        b = tb.load_block(a, n)
        st = tb.record_starts(b.info, b.n)
        for k, R in enumerate(st):
            t = tb.u32(b.info, R)
            if t == 8:
                rel = tb.u32(b.info, R + 0x20)
                o = (R + 0x20 + rel) & 0xFFFFFFFF
                d = soundfile_struct(b.info, o)
                d.update(block=n, rec=k, asset=tb.record_name(b.info, R), sf_off=o - R)
                s8.append(d)
            elif t == 7:
                rel = tb.u32(b.info, R + 0x20)
                o = (R + 0x20 + rel) & 0xFFFFFFFF
                v = struct.unpack_from('<IIBBBBIIIfI', b.info, o)
                s7.append(dict(block=n, rec=k, asset=tb.record_name(b.info, R), sb_off=o - R, w0=v[0], rate=v[1],
                               channels=v[2], b9=v[3], b10=v[4], b11=v[5], chunks=v[6], pcm_bytes=v[7], f20=v[8],
                               width=v[9], f28=v[10]))
    return s7, s8


if __name__ == '__main__':
    rows = ogg_inventory()
    json.dump(rows, open(os.path.join(OUT, 'ogg_inventory.json'), 'w'), indent=0)
    s7, s8 = block_records()
    json.dump(dict(sound=s7, streamedsoundinfo=s8), open(os.path.join(OUT, 'block_sound_records.json'), 'w'), indent=0)
    oggs = [r for r in rows if r['name'].endswith('.ogg')]
    print('oggs', len(oggs), 'errors', sum(1 for r in oggs if 'error' in r))
    print('rate/ch', collections.Counter((r.get('rate'), r.get('channels')) for r in oggs))
    print('vendor', collections.Counter(r.get('vendor') for r in oggs))
    print('comments keys', collections.Counter(k for r in oggs for k in r.get('comments', {})))
    print('bad crc pages', sum(r.get('bad_crc_pages', 0) for r in oggs),
          'multi-stream', sum(1 for r in oggs if r.get('streams', 1) != 1))
    print('nominal bitrates', collections.Counter(r.get('bitrate_nominal') for r in oggs).most_common(10))
    print('total seconds', round(sum(r.get('seconds', 0) for r in oggs), 1))
    byname = {r['name']: r for r in oggs}
    miss = collections.Counter()
    mism = []
    ok = 0
    for d in s8:
        fn = d['file'][1:].lower() if d['file'].startswith('/') else d['file'].lower()
        r = byname.get(fn)
        if not r:
            miss[fn] += 1
            continue
        if (r['samples'], r['rate'], r['channels']) == (d['samples'], d['rate'], d['channels']) and \
                d['pcm_bytes'] == d['samples'] * d['channels'] * 2:
            ok += 1
        else:
            mism.append((d['block'], d['asset'], (d['samples'], d['rate'], d['channels'], d['pcm_bytes']),
                         (r['samples'], r['rate'], r['channels'])))
    print('type8 records', len(s8), 'match ogg header', ok, 'mismatch', len(mism), 'missing file',
          sum(miss.values()), 'unique missing', len(miss))
    for m in mism[:15]:
        print('  MISMATCH', m)
    for m in list(miss)[:30]:
        print('  MISSING', m, miss[m])
    print('soundfile f0', collections.Counter(d['f0'] for d in s8).most_common(3),
          'format', collections.Counter(d['format'] for d in s8),
          'flags', collections.Counter(hex(d['flags']) for d in s8),
          'bps', collections.Counter(d['bytes_per_sample'] for d in s8),
          'wav_ptr', collections.Counter(hex(d['wav_ptr']) for d in s8).most_common(3),
          'tail', collections.Counter(hex(d['tail']) for d in s8).most_common(3),
          'pcm_a==pcm', sum(1 for d in s8 if d['pcm_bytes_a'] == d['pcm_bytes']))
    print('type7', len(s7), collections.Counter((d['rate'], d['channels'], d['width']) for d in s7))
    print('type7 misc', collections.Counter((d['w0'], d['b9'], d['b10'], d['b11'], d['f20'], d['f28']) for d in s7).most_common(8))
