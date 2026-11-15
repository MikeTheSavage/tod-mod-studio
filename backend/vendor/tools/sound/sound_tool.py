"""TOD (GOG) sound and music tool: catalogue, export for listening, replace a streamed sound/music track or an in-block
sound, and package the result as an override zip. Read-only on the game folder; deploys only to a TEST copy.

  python sound_tool.py catalog  --out DIR                          sound_catalog.json + .csv (every ogg and in-block
                                                                  sound, its format, who references it, SoundSlot use)
  python sound_tool.py export   --out DIR [--match TEXT] [--kind ogg|pcm|all] [--decode]
                                  oggs are copied out as .ogg (play in VLC/foobar/Audacity); in-block sounds as .wav;
                                  --decode also writes a .wav per ogg through Blender's Audaspace (heavy: one run)
  python sound_tool.py roundtrip                                   codec proof over the whole install (report in cwd)
  python sound_tool.py replace  --out DIR [--stream KEY=FILE ...] [--sound NAME=FILE.wav ...]
                                [--langs uk,de,...] [--base-block ENTRY=FILE ...] [--deploy TESTGAME] [--naz-out DIR]

replace
  --stream KEY=FILE   KEY = archive path of a streamed sound, e.g. "data/sounds/mission/submission/mainmenu_music_loop.ogg"
                      (case-insensitive; a unique substring is accepted). FILE = a Vorbis .ogg (used byte for byte) or a
                      16-bit .wav (encoded to Vorbis by Blender: 44.1 kHz mono 80 kbps, stereo 112 kbps, 22.05 kHz 40 kbps,
                      like the shipped files). Every STREAMEDSOUNDINFO record that names KEY, in every block of the
                      chosen languages, gets the new sample count / rate / channels (the engine never re-reads the ogg
                      header and decodes exactly that many bytes: a too-high count hangs the stream thread, a too-low
                      count cuts and mis-loops the track).
  --sound NAME=FILE   NAME = an in-block SOUND asset (e.g. "/data/Sounds/Characters/Default/Movement/stepgrass1.wav",
                      case-insensitive, unique substring accepted). FILE = 16-bit mono .wav at 11025, 22050 or 44100 Hz.
                      The record is rebuilt with the new PCM in overdose_<lang>.main for each chosen language.
  --langs             default: all languages whose blocks reference the item (de es fr it uk); the GOG game is English
                      and loads the uk blocks, so "--langs uk" makes a much smaller zip.
  --base-block        start a block from this file instead of blocks.naz (e.g. one already rebuilt by another tool)
  Output in DIR: sound_override.zip (STORED; the new oggs + rebuilt blocks), the rebuilt blocks, configpc_line.txt,
  report.json with every check. Nothing is written unless every check passes.
  --naz-out DIR       the archive route instead of the zip: rebuilt copies of sounds.naz / uk_sounds.naz / blocks.naz
                      (only those holding a replaced entry), every entry re-read; heavy (up to 474 MB per archive).
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import lowprio  # noqa: F401  (BELOW_NORMAL priority)
import todblock as tb
import todsound as ts
import ogginfo

ZIP_NAME = 'sound_override.zip'
BASE_ARCHIVES = ['blocks.naz', 'sounds.naz', 'videos00.naz', 'videos01.naz']
FORBIDDEN_DEPLOY = [os.path.normcase(os.path.abspath(p)) for p in
                    (ts.GOG,)]
LANGS = ('de', 'es', 'fr', 'it', 'uk')
BITRATE = {(44100, 1): 80000, (44100, 2): 112001, (22050, 1): 40222}
LAUNCHER = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\blender-launcher.exe")


class Fail(Exception):
    pass


def frag_codec():
    """The project's fragment codec (tools/fragment_writer), for SoundSlot look-ups in catalog."""
    for p in (os.environ.get('TOD_FRAG'), os.path.join(HERE, '..', 'fragment_writer'), os.path.join(HERE, '..', 'frag')):
        if p and os.path.exists(os.path.join(p, 'todfrag.py')):
            sys.path.insert(0, os.path.abspath(p))
            import todfrag
            return todfrag
    return None


def block_lang(name):
    """'data_pc/overdose_the_game/overdose/uk/x.main' -> 'uk' ('shared' for the shared blocks)."""
    parts = name.split('/')
    return parts[3] if len(parts) > 4 else ''


# ------------------------------------------------------------------ Blender (Audaspace) codec
def run_blender(jobs, workdir, timeout=900):
    if not os.path.exists(LAUNCHER):
        raise Fail('Blender (Store app) not found: %s; give an .ogg instead of a .wav' % LAUNCHER)
    os.makedirs(workdir, exist_ok=True)
    jp = os.path.join(workdir, 'aud_jobs.json')
    rp = os.path.join(workdir, 'aud_result.json')
    json.dump(jobs, open(jp, 'w'), indent=1)
    if os.path.exists(rp):
        os.remove(rp)
    t0 = time.time()
    with open(os.path.join(workdir, 'aud_blender.log'), 'wb') as log:
        subprocess.run([LAUNCHER, '-b', '--factory-startup', '--python-exit-code', '1', '--python',
                        os.path.join(HERE, 'blender_aud_codec.py'), '--', '--result', rp, '--jobs', jp],
                       stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                       creationflags=0x00004000 if os.name == 'nt' else 0,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    size, stable = -1, None
    while time.time() - t0 < timeout:          # the Store launcher can return before Blender has finished
        if os.path.exists(rp):
            s = os.path.getsize(rp)
            if s == size and s > 0:
                if stable and time.time() - stable > 1.0:
                    break
                stable = stable or time.time()
            else:
                size, stable = s, None
        time.sleep(0.25)
    if not os.path.exists(rp):
        raise Fail('Blender produced no result (see aud_blender.log)')
    d = json.load(open(rp))
    if not d.get('ok'):
        raise Fail('Blender codec failed:\n' + d.get('tb', ''))
    return d


# ------------------------------------------------------------------ catalogue
FOOTSTEPS = [  # anim_event_soundtrig_foot (FUN_005EDF40): ground face material -> Database_Sound_ID Specific_ID L/R
    (('Concrete', 'Asphalt'), (2, 10), (7, 8)), (('Metal', 'Wirefence'), (1, 8), (9, 10)), (('Dirt',), (4,), (5, 6)),
    (('Bush', 'Grass'), (7, 9), (133, 133)), (('Wood',), (3,), (131, 132)), (('Water',), (11,), (87, 88)),
    (('AllRound', 'Stone', 'Glass', 'Cloth', 'SolidGlass', 'BrokenWindow_*', 'Default_no_decal'), (0, 5, 6, 12, 13, 14, 15, 16, 17, 18), (7, 8)),
]


def catalog(out_dir):
    arcs = ts.open_archives()
    rows = []
    refs = {}
    pcm = []
    a = arcs['blocks.naz']
    for bn in sorted(a.names):
        ext = os.path.splitext(bn)[1].lower()
        if ext not in tb.BLOCK_EXTS:
            continue
        b = tb.Block(a.read(bn), ext)
        info = bytes(b.info)
        for k, R in ts.streamed_records(b):
            d = ts.read_streamedsoundinfo(info, R)
            refs.setdefault(ts.file_key(d['file']), []).append(dict(block=bn, record=k, samples=d['samples'],
                                                                     rate=d['rate'], channels=d['channels']))
        for k, r in ts.sound_records(b):
            pcm.append(dict(name=r.name, block=bn, record=k, rate=r.rate, channels=r.channels, samples=r.samples,
                            seconds=round(r.samples / r.rate, 3), lang=block_lang(bn)))
    slots = soundslot_index()
    for an in ts.SOUND_ARCHIVES:
        arc = arcs[an]
        with open(arc.path, 'rb') as f:
            for e in arc.entries:
                f.seek(e['data_off'])
                d = f.read(e['size'])
                r = dict(archive=an, key=e['name'], bytes=e['size'])
                if e['name'].endswith('.ogg'):
                    i = ogginfo.info(d, check_crc=False)
                    r.update(rate=i['rate'], channels=i['channels'], samples=i['samples'],
                             seconds=round(i['samples'] / i['rate'], 3), kbps=round(i['bitrate_nominal'] / 1000))
                rr = refs.get(e['name'], [])
                r['blocks'] = sorted({x['block'] for x in rr})
                r['metadata_matches'] = all((x['samples'], x['rate'], x['channels']) ==
                                            (r.get('samples'), r.get('rate'), r.get('channels')) for x in rr)
                r['soundslots'] = slots.get(e['name'][:-4] if e['name'].endswith('.ogg') else e['name'], [])[:20]
                rows.append(r)
    for p in pcm:
        p['soundslots'] = slots.get(p['name'].lower().lstrip('/')[:-4], [])[:20]
    os.makedirs(out_dir, exist_ok=True)
    doc = dict(streamed=rows, in_block_sounds=pcm,
               missing_files=sorted(k for k in refs if not any(r['key'] == k for r in rows)),
               footsteps=[dict(materials=m, facecoll_ids=ids, specific_ids=sid) for m, ids, sid in FOOTSTEPS])
    json.dump(doc, open(os.path.join(out_dir, 'sound_catalog.json'), 'w'), indent=1)
    with open(os.path.join(out_dir, 'sound_catalog.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['kind', 'archive_or_block', 'name', 'rate', 'channels', 'samples', 'seconds', 'kbps', 'n_blocks',
                    'soundslots'])
        for r in rows:
            w.writerow(['stream', r['archive'], r['key'], r.get('rate'), r.get('channels'), r.get('samples'),
                        r.get('seconds'), r.get('kbps'), len(r['blocks']), ' | '.join(r['soundslots'])])
        for p in pcm:
            w.writerow(['sound', p['block'], p['name'], p['rate'], p['channels'], p['samples'], p['seconds'], '',
                        '', ' | '.join(p['soundslots'])])
    print('catalog: %d streamed files (%d referenced by no block), %d in-block sounds, %d referenced files missing '
          '(non-English dialogue not shipped by GOG) -> %s' % (len(rows), sum(1 for r in rows if not r['blocks']),
                                                              len(pcm), len(doc['missing_files']), out_dir))
    return doc


def soundslot_index():
    """{'data/sounds/x' (no extension): ['block :: SoundSlot path (type)']} from every fragment of every block."""
    tf = frag_codec()
    if tf is None:
        return {}
    T = tf.Types()
    want = {T.index('sound'): 'sound', T.index('streaming_sound'): 'streaming_sound'}
    name_idx = T.index('name')
    a = tb.Archive(os.path.join(ts.GOG, 'blocks.naz'))
    out = {}
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
            fr = tf.Fragment(b.payloads[k], T)
            for node, e in fr.entities().items():
                nm, paths = None, []
                for r in e['sets']:
                    if r.prop == name_idx:
                        nm = fr.value(r)
                    elif r.prop in want:
                        v = fr.value(r)
                        if v:
                            paths.append(v)
                for p in paths:
                    key = ('data' + p.replace('\\', '/')).lower()
                    key = key[:-4] if key.endswith('.wav') else key
                    out.setdefault(key, []).append('%s :: %s (%s)' % (bn.split('/')[-1], nm, e['type']))
    return out


# ------------------------------------------------------------------ export
def export(out_dir, match=None, kind='all', decode=False):
    arcs = ts.open_archives()
    n = 0
    jobs = []
    m = match.lower() if match else None
    if kind in ('ogg', 'all'):
        for an in ts.SOUND_ARCHIVES:
            arc = arcs[an]
            for e in arc.entries:
                if m and m not in e['name']:
                    continue
                dst = os.path.join(out_dir, an.split('.')[0], *e['name'].split('/'))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(arc.read(e['name']))
                n += 1
                if decode and dst.endswith('.ogg'):
                    jobs.append({'op': 'decode', 'in': dst, 'out': dst[:-4] + '.wav'})
    if kind in ('pcm', 'all'):
        a = arcs['blocks.naz']
        for bn in sorted(a.names):
            if not (bn.endswith('.main')):
                continue
            b = tb.Block(a.read(bn), '.main')
            for k, r in ts.sound_records(b):
                if m and m not in r.name.lower():
                    continue
                dst = os.path.join(out_dir, 'in_block', block_lang(bn), *r.name.lstrip('/').split('/'))
                ts.write_wav(dst, r.rate, r.channels, r.pcm)
                n += 1
    if jobs:
        run_blender(jobs, os.path.join(out_dir, '_blender'))
    print('exported %d files (%d decoded to wav) -> %s' % (n, len(jobs), out_dir))
    return n


# ------------------------------------------------------------------ replace
def resolve_key(arcs, key):
    k = key.replace('\\', '/').lower().lstrip('/')
    names = [n for an in ts.SOUND_ARCHIVES for n in arcs[an].names]
    if k in names:
        return k
    hits = [n for n in names if k in n]
    if len(hits) != 1:
        raise Fail('stream %r matches %d archive entries: %s' % (key, len(hits), hits[:8]))
    return hits[0]


def prepare_stream(src, workdir, ref_fmt):
    """-> (ogg bytes, info). A .wav is encoded with Blender in the shipped bitrate class."""
    if src.lower().endswith('.wav'):
        rate, ch, _ = ts.read_wav(src)
        if (rate, ch) not in BITRATE:
            raise Fail('%s: %d Hz %d ch; the shipped formats are 44100 mono/stereo and 22050 mono' % (src, rate, ch))
        out = os.path.join(workdir, os.path.splitext(os.path.basename(src))[0] + '.ogg')
        run_blender([{'op': 'encode', 'in': os.path.abspath(src), 'out': os.path.abspath(out), 'rate': rate,
                      'channels': ch, 'bitrate': BITRATE[(rate, ch)]}], workdir)
        src = out
    data = open(src, 'rb').read()
    i = ogginfo.info(data)
    if i['streams'] != 1 or i['bad_crc_pages'] or i['eos_pages'] != 1 or i['samples'] <= 0:
        raise Fail('%s is not a single, intact Vorbis stream (%s)' % (src, i))
    if (i['rate'], i['channels']) not in BITRATE:
        raise Fail('%s: %d Hz %d ch is not a shipped format' % (src, i['rate'], i['channels']))
    return data, i


def resolve_sound(block, name):
    recs = ts.sound_records(block)
    n = name.lower()
    exact = [(k, r) for k, r in recs if r.name.lower() == n]
    hits = exact or [(k, r) for k, r in recs if n in r.name.lower()]
    if len(hits) != 1:
        raise Fail('sound %r matches %d SOUND records: %s' % (name, len(hits), [r.name for _, r in hits][:8]))
    return hits[0]


def replace(out_dir, streams, sounds, langs, base_blocks, deploy_dir=None, naz_out=None):
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, '_work')
    arcs = ts.open_archives()
    a = arcs['blocks.naz']
    rep = dict(streams=[], sounds=[], blocks={}, langs=sorted(langs))
    blocks = {}          # entry -> [original bytes, Block being edited, list of edits]

    def get_block(entry):
        if entry not in blocks:
            raw = open(base_blocks[entry], 'rb').read() if entry in base_blocks else a.read(entry)
            b = tb.Block(raw, os.path.splitext(entry)[1])
            if b.serialize() != raw:                                   # check 1: exact round trip of the base
                raise Fail('base block %s does not round-trip' % entry)
            blocks[entry] = [raw, b, []]
        return blocks[entry]

    entries = []
    # ---- streamed sounds
    want = {}
    for spec in streams:
        key, _, src = spec.partition('=')
        k = resolve_key(arcs, key)
        an, orig = ts.find_sound(arcs, k)
        data, i = prepare_stream(src, work, None)
        want[k] = (data, i, an, orig, src)
    if want:
        for bn in sorted(a.names):
            ext = os.path.splitext(bn)[1].lower()
            if ext not in tb.BLOCK_EXTS or (block_lang(bn) in LANGS and block_lang(bn) not in langs):
                continue
            info = bytes(a.read(bn)) if bn not in blocks else None
            b = tb.Block(info, ext) if info is not None else blocks[bn][1]
            hits = [(kk, R) for kk, R in ts.streamed_records(b)
                    if ts.file_key(ts.read_streamedsoundinfo(b.info, R)['file']) in want]
            if not hits:
                continue
            raw, eb, edits = get_block(bn)
            for kk, R in hits:
                old = ts.read_streamedsoundinfo(eb.info, R)
                data, i, an, orig, src = want[ts.file_key(old['file'])]
                ts.patch_streamedsoundinfo(eb.info, R, i['samples'], i['rate'], i['channels'])
                new = ts.read_streamedsoundinfo(eb.info, R)
                if (new['samples'], new['rate'], new['channels'], new['pcm_bytes']) != \
                        (i['samples'], i['rate'], i['channels'], i['samples'] * i['channels'] * 2):
                    raise Fail('patched record %d of %s does not read back' % (kk, bn))
                edits.append(dict(kind='streamedsoundinfo', record=kk, asset=old['asset'],
                                  old=[old['samples'], old['rate'], old['channels']],
                                  new=[i['samples'], i['rate'], i['channels']], R=R))
        for k, (data, i, an, orig, src) in want.items():
            entries.append((k, data))
            nrec = sum(1 for v in blocks.values() for e in v[2] if e['kind'] == 'streamedsoundinfo'
                       and ts.file_key(ts.read_streamedsoundinfo(v[1].info, e['R'])['file']) == k)
            if nrec == 0:
                raise Fail('no block of the chosen languages names %s' % k)
            o = ogginfo.info(orig, check_crc=False)
            rep['streams'].append(dict(key=k, source=src, archive=an, bytes=len(data), sha256=ts.sha(data),
                                       old=[o['samples'], o['rate'], o['channels']],
                                       new=[i['samples'], i['rate'], i['channels']], seconds=round(i['samples'] / i['rate'], 3),
                                       records_patched=nrec))
    # ---- in-block sounds
    for spec in sounds:
        name, _, src = spec.partition('=')
        rate, ch, pcm = ts.read_wav(src)
        if ch != 1 or rate not in (11025, 22050, 44100):
            raise Fail('%s: %d Hz %d ch; in-block sounds are mono at 11025/22050/44100 Hz' % (src, rate, ch))
        done = 0
        for lg in sorted(langs):
            entry = 'data_pc/overdose_the_game/overdose/%s/overdose_%s.main' % (lg, lg)
            if entry not in a.names:
                continue
            raw, eb, edits = get_block(entry)
            k, r = resolve_sound(eb, name)
            edits.append(dict(kind='sound', record=k, asset=r.name, old=[r.samples, r.rate, r.channels],
                              new=[len(pcm) // 2, rate, 1], pcm=pcm, rate=rate))
            done += 1
        if not done:
            raise Fail('no overdose_<lang>.main for languages %s' % sorted(langs))
        rep['sounds'].append(dict(name=name, source=src, rate=rate, samples=len(pcm) // 2, sha256_pcm=ts.sha(pcm),
                                  seconds=round(len(pcm) / 2 / rate, 3), languages=done))
    # ---- rebuild + verify every edited block
    for entry, (raw, eb, edits) in sorted(blocks.items()):
        old = tb.Block(raw, os.path.splitext(entry)[1])
        snd = {e['record']: dict(pcm=e['pcm'], rate=e['rate'], channels=1) for e in edits if e['kind'] == 'sound'}
        if snd:
            nb, layout = ts.rebuild_block_sounds(eb, snd)
        else:
            nb, layout = eb, None
        out = nb.serialize()
        r = verify_block(entry, old, out, edits, layout)
        rep['blocks'][entry] = r
        p = os.path.join(out_dir, entry.split('/')[-1])
        with open(p + '.part', 'wb') as f:
            f.write(out)
        os.replace(p + '.part', p)
        entries.append((entry, out))
    if not entries:
        raise Fail('nothing to replace')
    zp = os.path.join(out_dir, ZIP_NAME)
    ts.write_stored_zip(zp, entries, mtime_from=os.path.join(ts.GOG, 'blocks.naz'))
    rep['zip'] = dict(path=zp, entries=[n for n, _ in entries], bytes=os.path.getsize(zp),
                      readback_entries=ts.zip_readback(zp, entries))
    line = 'filesystem = ' + ', '.join([ZIP_NAME] + BASE_ARCHIVES)
    open(os.path.join(out_dir, 'configpc_line.txt'), 'w').write(line + '\n')
    rep['configpc_line'] = line
    if naz_out:
        rep['naz_out'] = write_naz_copies(naz_out, entries)
    if deploy_dir:
        rep['deploy'] = deploy(deploy_dir, zp)
    for v in rep['blocks'].values():
        for e in v.get('edits', []):
            e.pop('pcm', None)
    json.dump(rep, open(os.path.join(out_dir, 'report.json'), 'w'), indent=1)
    return rep


def write_naz_copies(dst_dir, entries):
    """The archive route: full copies of every .naz that holds a replaced entry, rewritten with
    todsound.naz_stream() and re-read through the engine's OpenZip/FindFile port. Heavy (blocks.naz 474 MB,
    sounds.naz 237 MB). Never written in place; never into the game folder or a hard-linked test copy."""
    d = os.path.normcase(os.path.abspath(dst_dir))
    if any(d == f or d.startswith(f + os.sep) for f in FORBIDDEN_DEPLOY) or             os.path.exists(os.path.join(dst_dir, 'TOD.exe')):
        raise Fail('refusing to write archive copies into a game folder: %s' % dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    arcs = ts.open_archives()
    out = {}
    for an, arc in arcs.items():
        mine = {n: b for n, b in entries if n in arc.names}
        if not mine:
            continue
        p = os.path.join(dst_dir, an)
        if os.path.exists(p) and os.stat(p).st_nlink > 1:
            raise Fail('%s is a hard link; writing it would change the original' % p)
        h = ts.naz_stream(arc.path, mine, p)
        chk = tb.Archive(p)
        for e in arc.entries:
            got = chk.read(e['name'])
            if got != (mine[e['name']] if e['name'] in mine else arc.read(e['name'])):
                raise Fail('%s: entry %s does not read back' % (p, e['name']))
        out[an] = dict(path=p, sha256=h, bytes=os.path.getsize(p), replaced=sorted(mine))
    return out


def verify_block(entry, old, out, edits, layout):
    """Strict checks on a rebuilt block; raises Fail on any surprise."""
    ext = os.path.splitext(entry)[1]
    chk = tb.Block(out, ext)
    oi, ni = bytes(old.info), bytes(chk.info)
    os_, ns = tb.record_starts(oi, old.n), tb.record_starts(ni, chk.n)
    if chk.n != old.n or len(ns) != len(os_):
        raise Fail('%s: record count changed' % entry)
    if (chk.timestamp, chk.prop_ck, chk.cmd_ck, chk.prefix) != (old.timestamp, old.prop_ck, old.cmd_ck, old.prefix):
        raise Fail('%s: header changed' % entry)
    if [bytes(p) for p in chk.payloads] != [bytes(p) for p in old.payloads]:
        raise Fail('%s: a payload changed' % entry)
    oe, ne = os_[1:] + [len(oi)], ns[1:] + [len(ni)]
    by_rec = {}
    for e in edits:
        by_rec.setdefault(e['record'], []).append(e)
    same = 0
    for k in range(old.n):
        a_, b_ = oi[os_[k]:oe[k]], ni[ns[k]:ne[k]]
        if k not in by_rec:
            if a_ != b_:
                raise Fail('%s: untouched record %d changed' % (entry, k))
            same += 1
            continue
        for e in by_rec[k]:
            if e['kind'] == 'streamedsoundinfo':
                d = ts.read_streamedsoundinfo(ni, ns[k])
                if [d['samples'], d['rate'], d['channels']] != e['new'] or len(a_) != len(b_):
                    raise Fail('%s: record %d does not hold the new stream metadata' % (entry, k))
                diff = [i for i in range(len(a_)) if a_[i] != b_[i]]
                F = d['F'] - ns[k]
                allowed = set(range(F + 4, F + 0x0C)) | set(range(F + 0x18, F + 0x20)) | set(range(F + 0x24, F + 0x28))
                if any(i not in allowed for i in diff):
                    raise Fail('%s: record %d changed outside the metadata words' % (entry, k))
            else:
                r = ts.SoundRecord(ni, ns[k], ne[k])
                if r.pcm != e['pcm'] or r.rate != e['rate'] or r.channels != 1 or r.name != e['asset']:
                    raise Fail('%s: SOUND record %d does not read back' % (entry, k))
                ro = ts.SoundRecord(oi, os_[k], oe[k])
                if r.head != ro.head or bytes(r.struct[0x2C:]) != bytes(ro.struct[0x2C:]) or r.lname != ro.lname:
                    raise Fail('%s: SOUND record %d changed outside PCM/format' % (entry, k))
    return dict(records=chk.n, untouched_identical=same, edits=edits, info_growth=len(ni) - len(oi),
                sha256=ts.sha(out), bytes=len(out))


def game_running():
    try:
        o = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=30).stdout.lower()
        return 'tod.exe' in o or 'totaloverdose.exe' in o
    except Exception:
        return True


def deploy(game_dir, zip_path):
    gd = os.path.normcase(os.path.abspath(game_dir))
    if any(gd == f or gd.startswith(f + os.sep) for f in FORBIDDEN_DEPLOY):
        raise Fail('refusing to deploy into %s (only a private test copy is allowed)' % game_dir)
    if not os.path.exists(os.path.join(game_dir, 'TOD.exe')):
        raise Fail('no TOD.exe in ' + game_dir)
    if game_running():
        raise Fail('TOD.exe / TotalOverdose.exe is running; not touching any game folder now')
    shutil.copy2(zip_path, os.path.join(game_dir, ZIP_NAME))
    cfg = os.path.join(game_dir, 'configpc.txt')
    old = open(cfg, 'rb').read() if os.path.exists(cfg) else b''
    if old.startswith(b'\xef\xbb\xbf') or b'\0' in old:
        raise Fail('configpc.txt in the test folder is not plain ASCII')
    lines = [ln for ln in old.replace(b'\r\n', b'\n').split(b'\n') if ln.strip()
             and not ln.strip().lower().startswith(b'filesystem') and not ln.startswith(b'# sound tool')
             and not ln.strip().lower().startswith(b'logdumpfile')]
    lines = [b'# sound tool test override (delete this line, the filesystem/logdumpfile lines and '
             b'sound_override.zip to undo)'] + lines
    lines.append(b'logdumpfile = tod_sound_log.txt')
    lines.append(('filesystem = ' + ', '.join([ZIP_NAME] + BASE_ARCHIVES)).encode('ascii'))
    raw = b'\r\n'.join(lines) + b'\r\n'
    with open(cfg, 'wb') as f:
        f.write(raw)
    return {'deployed_to': game_dir, 'configpc': raw.decode('ascii')}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('catalog')
    c.add_argument('--out', required=True)
    e = sub.add_parser('export')
    e.add_argument('--out', required=True)
    e.add_argument('--match')
    e.add_argument('--kind', choices=('ogg', 'pcm', 'all'), default='all')
    e.add_argument('--decode', action='store_true')
    sub.add_parser('roundtrip')
    r = sub.add_parser('replace')
    r.add_argument('--out', required=True)
    r.add_argument('--stream', action='append', default=[])
    r.add_argument('--sound', action='append', default=[])
    r.add_argument('--langs', default=','.join(LANGS))
    r.add_argument('--base-block', action='append', default=[])
    r.add_argument('--deploy')
    r.add_argument('--naz-out', help='also write rebuilt copies of the touched .naz archives here (heavy)')
    a = ap.parse_args()
    try:
        if a.cmd == 'catalog':
            catalog(a.out)
        elif a.cmd == 'export':
            export(a.out, a.match, a.kind, a.decode)
        elif a.cmd == 'roundtrip':
            import roundtrip_sound
            return roundtrip_sound.main(os.path.join(os.getcwd(), 'sound_roundtrip.json'))
        else:
            langs = {x.strip().lower() for x in a.langs.split(',') if x.strip()}
            bb = dict(x.split('=', 1) for x in a.base_block)
            rep = replace(a.out, a.stream, a.sound, langs, bb, a.deploy, a.naz_out)
            print(json.dumps({k: rep[k] for k in ('streams', 'sounds', 'zip', 'configpc_line')}, indent=1))
            for k, v in rep['blocks'].items():
                print('  %s: %d records, %d untouched identical, info %+d B, sha256 %s' %
                      (k, v['records'], v['untouched_identical'], v['info_growth'], v['sha256'][:16]))
    except Fail as ex:
        print('FAIL: %s' % ex)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
