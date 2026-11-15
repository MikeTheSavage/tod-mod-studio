"""TOD (GOG) sound data: codecs for the two sound asset records in blocks and helpers for the sound archives.

Records (asset type at record+0, name at +0x28, record 16-aligned in the block's INFO buffer, payload size 0):

SOUND (type 7, the in-block PCM bank of overdose_<lang>.main, 188 per language; 1 in overdoseintro_<lang>.main)
  R+0x00..   0x28-byte asset header + name + NUL + 0xAB fill up to S (16-aligned)
  R+0x20     self-relative pointer to S
  S+0x00 u32 0            S+0x04 u32 rate        S+0x08 u8 channels, u8 0, u8 1, u8 1
  S+0x0C u32 samples      S+0x10 u32 PCM bytes   S+0x14 u32 0      S+0x18 f32 bytes/sample (2.0)
  S+0x1C u32 0xC5000000   S+0x20 u32 0           S+0x24 rel -> PCM (= S+0x50)
  S+0x28 rel -> String at the next 4-byte boundary after the PCM   S+0x2C..S+0x4F constant words (kept)
  S+0x50     PCM, signed 16-bit little endian, mono; zero bytes up to a 4-byte boundary
  then       String {u32 len, u32 rel 0x0C -> chars, u32 cap, u32 0xBAADF00D}, lower-case name, NUL, zero pad
             to the next 16-byte boundary of the INFO buffer.

STREAMEDSOUNDINFO (type 8, one per streamed .ogg per block that can play it)
  R+0x20     self-relative pointer to F (a serialized SoundFile, 60 bytes, normally R+0x70)
  F+0x00 0xBAADF00D  F+0x04 PCM bytes  F+0x08 samples  F+0x0C f32 2.0  F+0x10 0  F+0x14 0  F+0x18 rate
  F+0x1C PCM bytes   F+0x20 format 1 (ogg)  F+0x24 flags: bit31 opened, bits 5..30 channels, bits 0,1,4 set
  F+0x28 String {len, rel -> chars, cap, tagged null}  F+0x38 StreamedWAV* (0 on disk)   F+0x3C chars of the .ogg path
  The engine copies these numbers into the stream object at load (FUN_00445710 -> FUN_00445370(0) -> FUN_00445080)
  and never re-reads the ogg header; FUN_0040F810 decodes exactly 'PCM bytes' per pass. They must equal the ogg.
"""
import os
import struct
import zipfile
import hashlib

import todblock as tb

GOG = r"C:\GOG Games\Total Overdose"
SOUND_ARCHIVES = ('sounds.naz', 'uk_sounds.naz')
BAADF00D = 0xBAADF00D


def sha(b):
    return hashlib.sha256(b).hexdigest()


def a16(x):
    return (x + 15) & ~15


# ------------------------------------------------------------------ SOUND (type 7)
class SoundRecord:
    """One SOUND record parsed into its parts; build() reproduces the record bytes exactly."""

    def __init__(self, info, R, E):
        self.R, self.E = R, E
        rel = tb.u32(info, R + 0x20)
        S = (R + 0x20 + rel) & 0xFFFFFFFF
        if S % 16 or not (R + 0x28 < S < E):
            raise ValueError('SOUND struct pointer odd at 0x%x' % R)
        self.head = bytes(info[R:S])                    # asset header + name + fill (verbatim)
        st = bytes(info[S:S + 0x50])
        self.struct = bytearray(st)
        self.rate = tb.u32(st, 4)
        self.channels = st[8]
        self.samples = tb.u32(st, 0xC)
        self.pcm_bytes = tb.u32(st, 0x10)
        self.width = struct.unpack_from('<f', st, 0x18)[0]
        pcm_rel = tb.u32(st, 0x24)
        str_rel = tb.u32(st, 0x28)
        if S + 0x24 + pcm_rel != S + 0x50:
            raise ValueError('PCM not right after the struct at 0x%x' % R)
        P = S + 0x50
        Q = S + 0x28 + (str_rel & ~3)
        if str_rel & 3 or Q != (P + self.pcm_bytes + 3) & ~3:
            raise ValueError('String not at the next 4-byte boundary after the PCM at 0x%x' % R)
        if self.pcm_bytes != self.samples * self.channels * 2 or self.width != 2.0:
            raise ValueError('PCM size does not match samples at 0x%x' % R)
        self.pcm = bytes(info[P:P + self.pcm_bytes])
        self.gap = bytes(info[P + self.pcm_bytes:Q])
        if self.gap.strip(b'\0'):
            raise ValueError('non-zero bytes between PCM and String at 0x%x' % R)
        slen, srel, scap, stag = struct.unpack_from('<IIII', info, Q)
        if srel != 0x0C:
            raise ValueError('name String layout odd at 0x%x' % R)
        self.str_words = (slen, scap, stag)
        self.lname = bytes(info[Q + 0x10:Q + 0x10 + slen])
        if info[Q + 0x10 + slen] != 0:
            raise ValueError('name String not NUL-terminated at 0x%x' % R)
        self.tail_pad = bytes(info[Q + 0x11 + slen:E])
        self.name = tb.record_name(info, R)

    def build(self, R=None, pcm=None, rate=None, channels=None):
        """Record bytes for start offset R (16-aligned; only the trailing pad depends on it)."""
        R = self.R if R is None else R
        pcm = self.pcm if pcm is None else pcm
        rate = self.rate if rate is None else rate
        channels = self.channels if channels is None else channels
        if len(pcm) % (2 * channels):
            raise ValueError('PCM length not a whole number of frames')
        st = bytearray(self.struct)
        struct.pack_into('<I', st, 4, rate)
        st[8] = channels
        struct.pack_into('<II', st, 0xC, len(pcm) // (2 * channels), len(pcm))
        gap = (-len(pcm)) % 4
        struct.pack_into('<I', st, 0x28, len(pcm) + gap + 0x28)
        slen, scap, stag = self.str_words
        out = (bytearray(self.head) + st + pcm + b'\0' * gap + struct.pack('<IIII', slen, 0x0C, scap, stag) +
               self.lname + b'\0')
        end = a16(R + len(out))
        npad = end - R - len(out)
        # the original exporter left stale bytes in some pads (e.g. 0D F0 AD BA); keep them when the length fits
        out += self.tail_pad if npad == len(self.tail_pad) else b'\0' * npad
        return bytes(out)


def sound_records(block):
    """[(index, SoundRecord)] for every SOUND record of a parsed tb.Block."""
    info = bytes(block.info)
    st = tb.record_starts(info, block.n)
    ends = st[1:] + [len(info)]
    out = []
    for k, (R, E) in enumerate(zip(st, ends)):
        if tb.u32(info, R) == 7:
            out.append((k, SoundRecord(info, R, E)))
    return out


def rebuild_block_sounds(block, replace):
    """New tb.Block with SOUND records replaced. replace: {record index: dict(pcm=bytes, rate=int, channels=int)}.
    Every other record is copied byte for byte (shifted)."""
    info = bytes(block.info)
    st = tb.record_starts(info, block.n)
    ends = st[1:] + [len(info)]
    new = bytearray()
    layout = []
    for k, (R, E) in enumerate(zip(st, ends)):
        if k in replace:
            rec = SoundRecord(info, R, E).build(R=len(new), **replace[k])
        else:
            rec = info[R:E]
            if len(new) % 16:
                raise ValueError('record %d would start unaligned' % k)
        layout.append((k, len(new), len(new) + len(rec)))
        new += rec
    nb = tb.Block(block.serialize(), block.ext)
    nb.info = bytearray(new)
    return nb, layout


# ------------------------------------------------------------------ STREAMEDSOUNDINFO (type 8)
def soundfile_offset(info, R):
    return (R + 0x20 + tb.u32(info, R + 0x20)) & 0xFFFFFFFF


def read_streamedsoundinfo(info, R):
    F = soundfile_offset(info, R)
    w = struct.unpack_from('<IIIfIIIIII', info, F)
    slen, srel = struct.unpack_from('<II', info, F + 0x28)
    n0 = F + 0x2C + (srel & ~3)
    e = bytes(info).find(b'\0', n0)
    return dict(F=F, tag=w[0], pcm_bytes_a=w[1], samples=w[2], width=w[3], rate=w[6], pcm_bytes=w[7], format=w[8],
                flags=w[9], channels=(w[9] >> 5) & 0x3FFFFFF, file=bytes(info[n0:e]).decode('latin-1'),
                asset=tb.record_name(info, R))


def patch_streamedsoundinfo(info, R, samples, rate, channels):
    """Write samples / rate / channels (and the two PCM byte counts) into a type-8 record in place."""
    F = soundfile_offset(info, R)
    pcm = samples * channels * 2
    struct.pack_into('<II', info, F + 4, pcm, samples)
    struct.pack_into('<I', info, F + 0x18, rate)
    struct.pack_into('<I', info, F + 0x1C, pcm)
    fl = tb.u32(info, F + 0x24)
    fl = (fl & ~(0x3FFFFFF << 5)) | ((channels & 0x3FFFFFF) << 5)
    struct.pack_into('<I', info, F + 0x24, fl)


def streamed_records(block):
    info = bytes(block.info)
    st = tb.record_starts(info, block.n)
    return [(k, R) for k, R in enumerate(st) if tb.u32(info, R) == 8]


def file_key(path):
    """Archive key for a SoundFile path ('/data/Sounds/x.ogg' -> 'data/sounds/x.ogg')."""
    p = path.replace('\\', '/')
    if p.startswith('/'):
        p = p[1:]
    return p.lower()


# ------------------------------------------------------------------ archives
def open_archives(game_dir=GOG):
    return {n: tb.Archive(os.path.join(game_dir, n)) for n in ('blocks.naz',) + SOUND_ARCHIVES}


def find_sound(archives, key):
    """(archive name, bytes) of a sound entry; sounds.naz is searched before uk_sounds.naz."""
    for n in SOUND_ARCHIVES:
        a = archives[n]
        if key in a.names:
            return n, a.read(key)
    raise KeyError(key)


def naz_stream(src, replace=None, out=None, chunk=1 << 22):
    """Re-serialize a .naz archive (the engine's zip variant) entry by entry; replace = {entry name: new bytes}.

    Layout (true for all GOG archives): per entry in central-directory order a local header blob of
    0x1E + nlen + xlen bytes (random filler, never read), the data, 12 trailing bytes; then the central directory
    (fields at -8: csize +0x0C, size +0x10, lhoff +0x22 of each entry), then the 22-byte EOCD (cd size +12,
    cd offset +16). Writes to `out` if given (never in place) and returns the sha256 of the produced bytes.
    With replace empty the output is byte-identical to the input."""
    replace = replace or {}
    a = tb.Archive(src)
    if not a.naz:
        raise ValueError('%s is not a naz archive' % src)
    if out and os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(src)):
        raise ValueError('refusing to rewrite an archive in place')
    unknown = set(replace) - set(e['name'] for e in a.entries)
    if unknown:
        raise KeyError('not in %s: %s' % (src, sorted(unknown)))
    h = hashlib.sha256()
    fo = open(out + '.part', 'wb') if out else None

    def emit(b):
        h.update(b)
        if fo:
            fo.write(b)
    cd = bytearray(a.cd)
    pos = 0
    with open(src, 'rb') as f:
        for e in a.entries:
            hdr = e['data_off'] - e['lhoff']
            f.seek(e['lhoff'])
            lh = f.read(hdr)
            if e['name'] in replace:
                data = replace[e['name']]
                f.seek(e['data_off'] + e['size'])
                emit(lh)
                emit(data)
                size = len(data)
            else:
                emit(lh)
                left = e['size']
                f.seek(e['data_off'])
                while left:
                    b = f.read(min(chunk, left))
                    emit(b)
                    left -= len(b)
                size = e['size']
            trail = f.read(12)
            emit(trail)
            q = e['cd_off'] - 8
            struct.pack_into('<ii', cd, q + 0x14, size, size)
            struct.pack_into('<i', cd, q + 0x2A, pos)
            pos += hdr + size + 12
    eocd = bytearray(a.eocd)
    struct.pack_into('<I', eocd, 16, pos)
    emit(bytes(cd))
    emit(bytes(eocd))
    if fo:
        fo.close()
        os.replace(out + '.part', out)
    return h.hexdigest()


def file_sha256(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                return h.hexdigest()
            h.update(b)


def write_stored_zip(path, entries, mtime_from=None):
    """Plain STORED zip, no comment, no extras; entries: [(archive name, bytes)]. Same rules as the animation lab's
    anim_override.zip (proven in game)."""
    dt = (2018, 2, 27, 0, 0, 0)
    if mtime_from and os.path.exists(mtime_from):
        import time
        t = time.localtime(os.path.getmtime(mtime_from))
        dt = (max(1980, t.tm_year), t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec - t.tm_sec % 2)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as z:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, date_time=dt)
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 0
            z.writestr(zi, data)


def zip_readback(path, entries):
    """Read the zip with the engine's OpenZip/FindFile port and compare every entry."""
    a = tb.Archive(path)
    for name, data in entries:
        hit = a.find('/' + name)
        if hit is None:
            raise ValueError('FindFile does not find %s in the zip' % name)
        off, size, _ = hit
        with open(path, 'rb') as f:
            f.seek(off)
            got = f.read(size)
        if got != data:
            raise ValueError('zip entry %s reads back different bytes' % name)
    return len(entries)


# ------------------------------------------------------------------ WAV
def read_wav(path):
    import wave
    with wave.open(path, 'rb') as w:
        if w.getsampwidth() != 2:
            raise ValueError('%s: only 16-bit PCM WAV is supported' % path)
        return w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())


def write_wav(path, rate, channels, pcm):
    import wave
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
