"""Game-side data layer for the TOD HD Texture Tool: read the GOG game's blocks.naz, find every copy of a texture,
patch texture records and payloads inside asset blocks, and package rewritten blocks the way TOD.exe will load them.

Everything here is a consolidation of research that was checked against the GOG TOD.exe bytes and all 696 shipped
blocks (work/research/digest/*.md, reference code under work/research/). Rules that decide whether the game crashes
are asserted, never assumed:

  Block layout      [299-byte prefix for .map] + <IIIiII ts, propCk, cmdCk, N, S, M> + info[S] + sizes[N] + payloads,
                    no padding, file ends after the last payload, M == max(sizes).
  Records           16-aligned in info; type <= 10, u32@+0x0C == 0xBAADF00D, self-relative name pointer to '/...'.
                    Record k owns payload k. The count must equal N or the block is refused.
  Texture record    G = GfxTexture: +0x0C/+0x10 resolution, +0x14/+0x18 surface size, +0x1C format (1 A8R8G8B8, 7 DXT1),
                    +0x20 format descriptor (byte +0x22 = bits per pixel), +0x24 u32 bitfield (bit0 = DXT sizing,
                    bits 1-8 = level count, bit 9 engine flag, rest fill), +0x28 u32 mip mode (1 full chain, 0 one level).
  Engine size       GetSizeForLevel @0x4633D0: DXT -> 8*max(1,w/4)*max(1,h/4); else (bpp&0x3F)*w*h>>3; summed, align 4.
  Load buffer       each payload is read into an M-byte buffer from a shared 10 MiB pool with no size check. The largest
                    M the shipped game already uses is 1,351,384 bytes, so that is the cap until tested in game.
  Base bytes        ALWAYS from the GOG blocks.naz (source/blocks .map files carry retail fingerprint bytes 37..294).
  Override archive  plain zip, STORED, no extras, no comment, < 2 GiB, lowercase entry names, listed first in the
                    'filesystem' line of an ASCII configpc.txt that ends with a newline.
"""
import hashlib
import json
import os
import struct
import subprocess
import time
import zipfile
from pathlib import Path

# ------------------------------------------------------------------------------------------------ constants

SENTINEL = 0xBAADF00D
NULLPTR = 0x80000000
NAZ_SIG = 0x16ED5B50
MAP_PREFIX = 299
MAP_IDENTIFIER = b"DB851B2E-F452-47f7-9C7D-0BD4918F6F07"
BLOCK_EXTS = {".main": 0, ".mission": 0, ".submap": 0, ".playerdata": 0, ".map": MAP_PREFIX}
FMT_A8R8G8B8, FMT_DXT1 = 1, 7
FMT_NAME = {FMT_A8R8G8B8: "RGBA32", FMT_DXT1: "DXT1"}
FMT_CODE = {"RGBA32": FMT_A8R8G8B8, "DXT1": FMT_DXT1}
DESCRIPTOR = {FMT_A8R8G8B8: 0x208888, FMT_DXT1: 0x40000}     # the values the shipped records use per format
# The engine reads every payload into a scratch buffer from the 10 MiB RENDERLIST pool (fully free before each block load).
# PROVEN IN GAME 2026-09-18 (work\game_tests\t7_loadcap): 34 blocks incl. startmap.map and the MM010 jungle submap loaded
# assets of 2,796,216 B with no crash and correct rendering. That is the block-level limit (lighting records, geometry-heavy
# blocks). Texture PLANNING keeps the original, conservative per-texture size: TEXTURE_CAP.
LOAD_BUFFER_CAP = 2_796_216
TEXTURE_CAP = 1_351_384              # largest maximumAssetSize in any shipped block (overdose.main); texture sizing policy
ZIP_LIMIT = 0x7FFFFFFF               # SetFilePointer with a signed 32-bit distance
MAX_SLOTS = 8                        # archive slots; no bounds check in the engine past this
MAX_DIM = 4096
BASE_ARCHIVES = ["blocks.naz", "sounds.naz", "videos00.naz", "videos01.naz"]
LANGS = ("uk", "de", "es", "fr", "it")
GAME_LANG = "uk"                     # the GOG build ships only uk_sounds.naz, so the engine runs in English


class GameDataError(Exception):
    pass


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def a4(x):
    return (x + 3) & ~3


def a16(x):
    return (x + 15) & ~15


def selfptr(buf, off):
    v = u32(buf, off)
    if v == NULLPTR:
        return None
    return (off + v) & 0xFFFFFFFC


def cstring(buf, o, limit=1024):
    e = buf.find(b"\0", o, min(len(buf), o + limit))
    if e < 0:
        raise GameDataError("unterminated string at 0x%x" % o)
    return buf[o:e]


def is_pow2(n):
    return n > 0 and n & (n - 1) == 0


def full_chain(w, h):
    return max(w, h).bit_length()


def size_for_level(w, h, level, compressed, bpp):
    """Exact port of Texture::GetSizeForLevel @0x4633D0."""
    ww, hh = max(w >> level, 1), max(h >> level, 1)
    if compressed:
        return 8 * max(ww // 4, 1) * max(hh // 4, 1)
    return ((bpp & 0x3F) * hh * ww) >> 3


def engine_data_size(w, h, levels, compressed, bpp):
    return a4(sum(size_for_level(w, h, L, compressed, bpp) for L in range(levels)))


def payload_size(fmt, w, h, levels):
    """Size the engine will copy for a texture of this format (fmt 'DXT1'/'RGBA32' or code 7/1)."""
    code = FMT_CODE.get(fmt, fmt)
    return engine_data_size(w, h, levels, code == FMT_DXT1, 4 if code == FMT_DXT1 else 32)


def texture_key(name):
    """Engine name ('/data/Textures/x.bmp') or tool key ('data/textures/x') -> lookup key.
    Case-insensitive, extension dropped, and '/ ' folded to '/' (3 engine names have a space after a slash)."""
    s = name.replace("\\", "/")
    i = s.lower().find("data/")
    if i >= 0:
        s = s[i:]
    s = s.lstrip("/")
    base, ext = os.path.splitext(s)
    if ext.lower() in (".bmp", ".dds", ".png", ".tga"):
        s = base
    return s.replace("/ ", "/").lower()


# ------------------------------------------------------------------------------------------------ archives

def tod_crc(b):
    """FUN_004657c0: the engine's file-name hash (CRC-32 poly, LSB-first feed, 4 zero bytes appended)."""
    r = 0
    for c in b + b"\0\0\0\0":
        for bit in range(8):
            top = r & 0x80000000
            r = ((r << 1) & 0xFFFFFFFF) | ((c >> bit) & 1)
            if top:
                r ^= 0x04C11DB7
    return r


def engine_name(name):
    """How OpenZip stores a name: backslash -> '/', A-Z lowercased, nothing else."""
    b = name.encode("latin-1") if isinstance(name, str) else name
    b = b.replace(b"\\", b"/")
    return bytes(c + 32 if 0x41 <= c <= 0x5A else c for c in b)


class Archive:
    """Faithful port of OpenZip (FUN_00419100): {crc: (data offset, size, name)}; the last duplicate wins."""

    def __init__(self, path):
        self.path = str(path)
        with open(self.path, "rb") as f:
            f.seek(0, 2)
            fsize = f.tell()
            f.seek(fsize - 22)
            e = f.read(20)
            self.naz = u32(e, 0) == NAZ_SIG
            count = e[10] | e[11] << 8
            cdsize, cdoff = u32(e, 12), u32(e, 16)
            f.seek(cdoff)
            cd = f.read(cdsize)
        self.table, self.dups = {}, 0
        p = 0
        for _ in range(count):
            q = p - 8 if self.naz else p
            size = i32(cd, q + 0x18)
            nlen, xlen, clen = struct.unpack_from("<HHH", cd, q + 0x1C)
            lhoff = i32(cd, q + 0x2A)
            raw = cd[p + 0x2E:p + 0x2E + nlen]
            if self.naz:
                raw = bytes(((c << 2) | (c >> 6)) & 0xFF for c in raw)
            name = engine_name(raw)
            crc = tod_crc(name)
            if crc in self.table:
                self.dups += 1
            self.table[crc] = (lhoff + xlen + 0x1E + nlen, size, name.decode("latin-1"))
            p += 0x2E + clen + xlen + nlen
        self.names = {v[2]: (v[0], v[1]) for v in self.table.values()}

    def read(self, name):
        off, size = self.names[name]
        with open(self.path, "rb") as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            raise GameDataError("short read of %s from %s" % (name, self.path))
        return data

    def find(self, request):
        """FindFile: the first character of the request is dropped, A-Z lowercased."""
        key = engine_name(request[1:])
        return self.table.get(tod_crc(key))


# ------------------------------------------------------------------------------------------------ blocks

class Block:
    """Exact reader/writer of an asset block, with the locator's strict record accounting."""

    def __init__(self, data, ext):
        d = bytes(data)
        ext = ext.lower()
        if ext not in BLOCK_EXTS:
            raise GameDataError("not an asset block: %s" % ext)
        base = BLOCK_EXTS[ext]
        if base and d[:36] != MAP_IDENTIFIER:
            raise GameDataError(".map identifier missing")
        if len(d) < base + 24:
            raise GameDataError("shorter than the header")
        self.ext, self.prefix = ext, d[:base]
        (self.timestamp, self.prop_ck, self.cmd_ck, n, s, self.max_asset) = struct.unpack_from("<IIIiII", d, base)
        if not 0 <= n < 1_000_000:
            raise GameDataError("bad resource count %d" % n)
        tbl = base + 24 + s
        if tbl + 4 * n > len(d):
            raise GameDataError("size table beyond end of file")
        sizes = list(struct.unpack_from("<%dI" % n, d, tbl))
        if any(x >= 0x80000000 for x in sizes):
            raise GameDataError("payload size >= 2^31")
        p = tbl + 4 * n
        self.payloads = []
        for x in sizes:
            self.payloads.append(d[p:p + x])
            p += x
        if p != len(d):
            raise GameDataError("file length not accounted for (%d != %d)" % (p, len(d)))
        if self.max_asset != (max(sizes) if n else 0):
            raise GameDataError("maximumAssetSize %d != max(sizes) %d" % (self.max_asset, max(sizes) if n else 0))
        self.info = bytearray(d[base + 24:base + 24 + s])
        self.records = self._records() if n else []

    @property
    def sizes(self):
        return [len(x) for x in self.payloads]

    def _records(self):
        info, n = self.info, len(self.payloads)
        starts = []
        for o in range(0, len(info) - 15, 16):
            if u32(info, o + 12) != SENTINEL or u32(info, o) > 10:
                continue
            np_ = (o + 4 + u32(info, o + 4)) & 0xFFFFFFFC
            if np_ >= len(info) or info[np_] != 0x2F:
                continue
            try:
                nm = cstring(info, np_)
            except GameDataError:
                continue
            if all(32 <= c < 127 for c in nm):
                starts.append(o)
        if len(starts) != n or (starts and starts[0] != 0):
            raise GameDataError("record scan found %d records, header says %d" % (len(starts), n))
        out = []
        for k, R in enumerate(starts):
            nxt = starts[k + 1] if k + 1 < n else len(info)
            typ = u32(info, R)
            name_ptr = (R + 4 + u32(info, R + 4)) & 0xFFFFFFFC
            name = cstring(info, name_ptr)
            if not (R < name_ptr and name_ptr + len(name) + 1 <= nxt):
                raise GameDataError("record %d name outside its span" % k)
            rec = {"index": k, "offset": R, "end": nxt, "type": typ, "name": name.decode("ascii")}
            if typ == 0:
                rec.update(self._texture(R, nxt, name_ptr, len(name)))
                if self.sizes[k] != rec["engine_size"]:
                    raise GameDataError("texture %s: payload %d != engine size %d" % (rec["name"], self.sizes[k], rec["engine_size"]))
            out.append(rec)
        return out

    def _texture(self, R, nxt, name_ptr, name_len):
        info = self.info
        T, G = selfptr(info, R + 0x20), selfptr(info, R + 0x28)
        if T is None or G is None:
            raise GameDataError("texture record 0x%x has a null TextureInfo/GfxTexture" % R)
        if not (R + 0x30 <= G and G + 0x2C <= nxt and R + 0x30 <= T and T + 0x54 <= nxt):
            raise GameDataError("texture record 0x%x: TextureInfo/GfxTexture outside its span" % R)
        far = max(a4(name_ptr + name_len + 1), G + 0x2C, T + 0x54)
        for so in (T, T + 0x10):
            slen, sp = u32(info, so), selfptr(info, so + 4)
            if sp is not None and sp >= T + 0x54:
                if info[sp + slen] != 0:
                    raise GameDataError("texture record 0x%x: string not NUL-terminated" % R)
                far = max(far, a4(sp + slen + 1))
        if a16(far) != nxt:
            raise GameDataError("texture record 0x%x: exact end 0x%x != next record 0x%x" % (R, a16(far), nxt))
        bits_ptr = selfptr(info, G + 0x08)
        lw = u32(info, G + 0x24)
        t = {
            "gfx": G, "texinfo": T,
            "res_w": u32(info, G + 0x0C), "res_h": u32(info, G + 0x10),
            "w": u32(info, G + 0x14), "h": u32(info, G + 0x18),
            "fmt": i32(info, G + 0x1C), "descriptor": u32(info, G + 0x20), "bpp": info[G + 0x22],
            "levels_word": lw, "compressed": lw & 1, "levels": (lw >> 1) & 0xFF, "mip_mode": u32(info, G + 0x28),
            "flags_24": u32(info, R + 0x24), "ti_pair4": struct.unpack_from("<II", info, T + 0x4C),
        }
        if bits_ptr != R:
            raise GameDataError("texture record 0x%x: surface-bits pointer does not resolve to the record" % R)
        if t["fmt"] not in (FMT_A8R8G8B8, FMT_DXT1):
            raise GameDataError("texture record 0x%x: format %d is not supported" % (R, t["fmt"]))
        if bool(t["compressed"]) != (t["fmt"] == FMT_DXT1):
            raise GameDataError("texture record 0x%x: DXT sizing bit disagrees with the format" % R)
        if t["mip_mode"] not in (0, 1):
            raise GameDataError("texture record 0x%x: mip mode %d" % (R, t["mip_mode"]))
        if not (is_pow2(t["w"]) and is_pow2(t["h"])):
            raise GameDataError("texture record 0x%x: surface %dx%d not a power of two" % (R, t["w"], t["h"]))
        want_levels = full_chain(t["w"], t["h"]) if t["mip_mode"] == 1 else 1
        if t["levels"] != want_levels:
            raise GameDataError("texture record 0x%x: %d levels with mip mode %d" % (R, t["levels"], t["mip_mode"]))
        t["engine_size"] = engine_data_size(t["w"], t["h"], t["levels"], t["compressed"], t["bpp"])
        return t

    def textures(self):
        return [r for r in self.records if r["type"] == 0]

    def serialize(self):
        n = len(self.payloads)
        out = bytearray(self.prefix)
        out += struct.pack("<IIIiII", self.timestamp, self.prop_ck, self.cmd_ck, n, len(self.info), max(self.sizes) if n else 0)
        out += self.info
        out += struct.pack("<%dI" % n, *self.sizes)
        for p in self.payloads:
            out += p
        return bytes(out)


def texture_patches(block, rec, new_fmt, new_w, new_h, new_levels):
    """Same-length info patches for one texture record. Returns [(offset, bytes)] and the byte ranges touched."""
    info = block.info
    G, R = rec["gfx"], rec["offset"]
    w, h = rec["w"], rec["h"]
    if not (is_pow2(new_w) and is_pow2(new_h)) or new_w > MAX_DIM or new_h > MAX_DIM:
        raise GameDataError("%s: new size %dx%d must be powers of two up to %d" % (rec["name"], new_w, new_h, MAX_DIM))
    if new_w * h != new_h * w:
        raise GameDataError("%s: shape changed (%dx%d -> %dx%d)" % (rec["name"], w, h, new_w, new_h))
    new_code = FMT_CODE[new_fmt]
    if new_code == FMT_DXT1 and (new_w < 4 or new_h < 4):
        raise GameDataError("%s: DXT1 needs at least 4x4" % rec["name"])
    if rec["fmt"] == FMT_DXT1 and new_code != FMT_DXT1:
        raise GameDataError("%s: DXT1 textures stay DXT1" % rec["name"])
    want = full_chain(new_w, new_h) if rec["mip_mode"] == 1 else 1
    if new_levels != want:
        raise GameDataError("%s: %d levels, the record's mip mode needs %d" % (rec["name"], new_levels, want))
    res_w, res_h = rec["res_w"] * new_w // w, rec["res_h"] * new_h // h
    if res_w * w != rec["res_w"] * new_w or res_h * h != rec["res_h"] * new_h:
        raise GameDataError("%s: resolution does not scale to whole pixels" % rec["name"])
    lw = rec["levels_word"]
    lw = (lw & ~0x1FF) | (new_levels << 1) | (1 if new_code == FMT_DXT1 else 0)     # keep bit 9 and fill bits
    patches = [
        (G + 0x0C, struct.pack("<II", res_w, res_h)),
        (G + 0x14, struct.pack("<II", new_w, new_h)),
        (G + 0x24, struct.pack("<I", lw)),
        (G + 0x28, struct.pack("<I", 1 if new_levels > 1 else 0)),
    ]
    if new_code != rec["fmt"]:
        patches.append((G + 0x1C, struct.pack("<i", new_code)))
        patches.append((G + 0x20, struct.pack("<I", DESCRIPTOR[new_code])))
    if rec["ti_pair4"] == (rec["res_w"], rec["res_h"]):
        patches.append((rec["texinfo"] + 0x4C, struct.pack("<II", res_w, res_h)))   # kept equal to the resolution
    for off, data in patches:
        if not (R <= off and off + len(data) <= rec["end"]):
            raise GameDataError("%s: patch at 0x%x outside its record" % (rec["name"], off))
    return patches


def rewrite_block(data, ext, replacements):
    """replacements: {resource index: (fmt 'DXT1'|'RGBA32', w, h, levels, payload bytes)}.
    Returns (new bytes, report). Refuses on any rule violation; re-parses and diffs the result."""
    old = Block(data, ext)
    new = Block(data, ext)
    touched = []
    by_index = {r["index"]: r for r in old.textures()}
    for idx, (fmt, w, h, levels, payload) in replacements.items():
        rec = by_index.get(idx)
        if rec is None:
            raise GameDataError("resource %d is not a texture" % idx)
        want = payload_size(fmt, w, h, levels)
        if len(payload) != want:
            raise GameDataError("%s: payload %d bytes, engine will copy %d" % (rec["name"], len(payload), want))
        if len(payload) > LOAD_BUFFER_CAP:
            raise GameDataError("%s: %d bytes is over the game's %d-byte load buffer" % (rec["name"], len(payload), LOAD_BUFFER_CAP))
        for off, patch in texture_patches(old, rec, fmt, w, h, levels):
            new.info[off:off + len(patch)] = patch
            touched.append((off, off + len(patch)))
        new.payloads[idx] = bytes(payload)
    out = new.serialize()

    # verify: strict re-parse, identity of everything we did not mean to change
    chk = Block(out, ext)
    problems = []
    if chk.prefix != old.prefix or (chk.timestamp, chk.prop_ck, chk.cmd_ck) != (old.timestamp, old.prop_ck, old.cmd_ck):
        problems.append("prefix, timestamp or checksums changed")
    if len(chk.info) != len(old.info) or len(chk.payloads) != len(old.payloads):
        problems.append("info size or resource count changed")
    if chk.max_asset > LOAD_BUFFER_CAP and chk.max_asset > old.max_asset:
        problems.append("maximumAssetSize %d over the load buffer cap" % chk.max_asset)
    for k, (a, b) in enumerate(zip(old.payloads, chk.payloads)):
        if k not in replacements and a != b:
            problems.append("payload %d changed" % k)
    for k in range(len(old.info)):
        if old.info[k] != chk.info[k] and not any(lo <= k < hi for lo, hi in touched):
            problems.append("info byte 0x%x changed outside the patched fields" % k)
            break
    new_recs = {r["index"]: r for r in chk.textures()}
    for idx, (fmt, w, h, levels, payload) in replacements.items():
        r = new_recs[idx]
        if (FMT_NAME[r["fmt"]], r["w"], r["h"], r["levels"]) != (fmt, w, h, levels) or chk.payloads[idx] != payload:
            problems.append("%s did not read back as written" % r["name"])
    if [r["name"] for r in chk.records] != [r["name"] for r in old.records]:
        problems.append("record names changed")
    if problems:
        raise GameDataError("verification failed: " + "; ".join(problems[:5]))
    return out, {"textures": len(replacements), "max_asset_before": old.max_asset, "max_asset_after": chk.max_asset,
                 "bytes_before": len(data), "bytes_after": len(out)}


# ------------------------------------------------------------------------------------------------ texture index

def block_language(name):
    parts = name.split("/")
    for p in parts[:-1]:
        if p in LANGS:
            return p
    return None


def loaded_by_this_game(name):
    """Shared blocks and the game's own language; other languages' copies are never loaded by the GOG build."""
    lang = block_language(name)
    return lang is None or lang == GAME_LANG


def build_index(game_dir, cache_file=None, progress=None):
    """Scan every asset block in the GOG blocks.naz. -> {"textures": {key: [location...]}, "blocks": {...}, ...}
    Cached against the archive's size and modification time."""
    naz = Path(game_dir) / "blocks.naz"
    st = naz.stat()
    stamp = "%d:%d" % (st.st_size, int(st.st_mtime))
    if cache_file and Path(cache_file).exists():
        try:
            cached = json.loads(Path(cache_file).read_text(encoding="utf-8"))
            if cached.get("stamp") == stamp and cached.get("version") == 3:
                return cached
        except Exception:
            pass
    arch = Archive(naz)
    names = sorted(n for n in arch.names if os.path.splitext(n)[1].lower() in BLOCK_EXTS)
    textures, blocks, errors = {}, {}, {}
    t0 = time.time()
    with open(naz, "rb") as f:
        for i, name in enumerate(names):
            off, size = arch.names[name]
            f.seek(off)
            data = f.read(size)
            try:
                b = Block(data, os.path.splitext(name)[1])
            except GameDataError as e:
                errors[name] = str(e)
                continue
            texs = b.textures()
            blocks[name] = {"bytes": size, "resources": len(b.payloads), "textures": len(texs), "max_asset": b.max_asset,
                            "texture_bytes": sum(b.sizes[r["index"]] for r in texs), "loaded": loaded_by_this_game(name)}
            for r in texs:
                textures.setdefault(texture_key(r["name"]), []).append({
                    "block": name, "index": r["index"], "name": r["name"], "fmt": FMT_NAME[r["fmt"]],
                    "w": r["w"], "h": r["h"], "res_w": r["res_w"], "res_h": r["res_h"], "levels": r["levels"],
                    "mip_mode": r["mip_mode"], "bytes": b.sizes[r["index"]], "flags_24": r["flags_24"],
                    "levels_word": r["levels_word"], "loaded": blocks[name]["loaded"],
                })
            if progress and i % 25 == 0:
                progress(i + 1, len(names))
    index = {"version": 3, "stamp": stamp, "built": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - t0, 1),
             "textures": textures, "blocks": blocks, "errors": errors}
    if cache_file:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(cache_file) + ".tmp")
        tmp.write_text(json.dumps(index), encoding="utf-8")
        os.replace(tmp, cache_file)
    return index


def level_sets(index):
    """Groups of blocks the game can hold at the same time, for a memory estimate. Upper bound: the shared
    .main blocks, one map with all of its submaps, every vehicle playerdata block and the largest mission."""
    import re
    loaded = {n: b for n, b in index["blocks"].items() if b["loaded"]}
    mains = [n for n in loaded if n.endswith(".main") and "/overdose/" in n]
    players = [n for n in loaded if n.endswith(".playerdata")]
    missions = [n for n in loaded if n.endswith(".mission")]
    world = [n for n in loaded if n.endswith(".map") or n.endswith(".submap")]
    groups = {}
    for n in world:
        m = re.search(r"(map\d\d(?:_[a-z_]+?)?)(?:_uk)?\.(?:sub)?map$", os.path.basename(n))
        mid = re.search(r"map\d\d", os.path.basename(n))
        key = mid.group(0) if mid else os.path.splitext(os.path.basename(n))[0]
        label = m.group(1) if (m and n.endswith(".map")) else None
        g = groups.setdefault(key, {"blocks": [], "label": key})
        g["blocks"].append(n)
        if label:
            g["label"] = label
    sets = {}
    for key, gr in groups.items():
        others = [n for n in world if n not in gr["blocks"] and not re.search(r"map\d\d", os.path.basename(n))]
        sets[gr["label"]] = {"blocks": mains + gr["blocks"] + others + players, "missions": missions}
    return sets


# ------------------------------------------------------------------------------------------------ override archive

def build_override_zip(path, entries):
    """entries: [(entry name, bytes)]. Plain zip exactly as the engine can read it."""
    tmp = Path(str(path) + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        for name, data in entries:
            if name != name.lower() or name.startswith("/") or "\\" in name:
                raise GameDataError("bad entry name %r" % name)
            name.encode("ascii")
            zi = zipfile.ZipInfo(name, date_time=(2005, 8, 21, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 0
            zi.external_attr = 0
            zf.writestr(zi, data)
    return tmp


def verify_override_zip(path, entries, base_archives):
    """Re-read the archive with the engine's own parse and check every byte and every rule. -> [problems]"""
    errs = []
    size = os.path.getsize(path)
    if size > ZIP_LIMIT:
        errs.append("archive is 2 GiB or larger")
    with open(path, "rb") as f:
        f.seek(size - 22)
        eocd = f.read(22)
        if eocd[:4] != b"PK\x05\x06" or struct.unpack_from("<H", eocd, 20)[0] != 0:
            errs.append("end record not at the end of the file (comment?)")
        arch = Archive(path)
        if arch.naz:
            errs.append("archive parsed as .naz")
        if arch.dups:
            errs.append("duplicate name hashes inside the archive")
        if len(arch.table) != len(entries):
            errs.append("engine sees %d entries, expected %d" % (len(arch.table), len(entries)))
        with zipfile.ZipFile(path) as zf:
            for zi in zf.infolist():
                f.seek(zi.header_offset)
                lh = f.read(30)
                meth, flags, xlen = struct.unpack_from("<H", lh, 8)[0], struct.unpack_from("<H", lh, 6)[0], struct.unpack_from("<H", lh, 28)[0]
                if meth != 0 or flags & 1 or xlen != len(zi.extra) or xlen:
                    errs.append("%s: compressed, encrypted or has extra fields" % zi.filename)
        for name, data in entries:
            hit = arch.table.get(tod_crc(name.encode("ascii")))
            if hit is None:
                errs.append("%s: not found by the engine's lookup" % name)
                continue
            off, sz, nm = hit
            f.seek(off)
            if nm != name or sz != len(data) or f.read(sz) != data:
                errs.append("%s: bytes at the engine's offset differ" % name)
            if off + sz > ZIP_LIMIT:
                errs.append("%s: data past 2 GiB" % name)
    for base in base_archives:
        for crc, (_, _, basename) in base.table.items():
            if crc in arch.table and arch.table[crc][2] != basename:
                errs.append("name hash collision: %s vs %s" % (arch.table[crc][2], basename))
    for name, _ in entries:
        if not any(b.find("/" + name) for b in base_archives):
            errs.append("%s is not in the game's archives (would be an addition, not a replacement)" % name)
    return errs


# ------------------------------------------------------------------------------------------------ configpc.txt

def _fold(raw):
    out, i = bytearray(), 0
    while i < len(raw):
        if raw[i] == 0x0D:
            out.append(0x0A)
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return bytes(out)


def parse_config(raw):
    """Port of ConfigVariables::ParseVariablesFile (FUN_00411a30) after the text-mode CR fold. -> {key: value}"""
    buf = _fold(raw)
    ws = (0x20, 0x09, 0x0A, 0x0D, 0x00)
    n, b = len(buf), buf + b"\0"
    out, scopes, i = {}, [], 0
    if n < 1:
        return out
    while True:
        c = b[i]
        while c in ws:
            if i >= n:
                return out
            c = b[i + 1]
            i += 1
        if i >= n:
            return out
        if not ((0x61 <= c <= 0x7A) or (0x41 <= c <= 0x5A) or c == 0x2F):
            if c == 0x7D and scopes:
                scopes.pop()
            while c not in (0, 0x0A):
                i += 1
                c = b[i]
            if i >= n:
                return out
            continue
        key = bytearray()
        while True:
            key.append(c)
            i += 1
            c = b[i]
            if c in ws or c == 0x3D:
                break
            if i >= n:
                return out
        if i >= n:
            return out
        while c in ws:
            if i >= n:
                return out
            c = b[i + 1]
            i += 1
        if i >= n:
            return out
        if c == 0x7B:
            scopes.append(key.decode("latin-1"))
            i += 1
            if i >= n:
                return out
            continue
        if c != 0x3D:
            continue
        c = b[i + 1]
        i += 1
        if i >= n:
            return out
        while c in (0x20, 0x09, 0x0D, 0x00):
            if i >= n:
                return out
            c = b[i + 1]
            i += 1
        if i >= n:
            return out
        quoted = c == 0x22
        if quoted:
            c = b[i + 1]
            i += 1
        if i >= n:
            return out
        val = bytearray()
        while True:
            if c not in (0x0A, 0x0D):
                while True:
                    val.append(c)
                    c = b[i + 1]
                    i += 1
                    stop = (c == 0x22) if quoted else (c in (0x0A, 0x0D, 0x23))
                    if stop or c == 0:
                        if i >= n:
                            return out
                        break
                    if i >= n:
                        return out
            if c == 0x30:
                break
            if quoted:
                c = b[i + 1]
                i += 1
                if i >= n:
                    return out
                if c == 0x22:
                    continue
                break
            while c not in (0x00, 0x0A, 0x0D):
                if i >= n:
                    return out
                c = b[i + 1]
                i += 1
            if i >= n:
                return out
            break
        out[".".join(scopes + [key.decode("latin-1")])] = val.decode("latin-1")


CONFIG_HEADER = "# TOD HD texture pack (remove this file and hd_override*.zip to restore the original game)"


def write_config(game_dir, override_names, extra=None, drop=(), header=None):
    """Write game/configpc.txt: ASCII, no BOM, CRLF, '#' comment first, override archives first in 'filesystem'.
    Returns (path, raw bytes, parsed dict). Existing lines are kept; our keys are appended last (the last one wins).
    drop: keys whose existing lines are removed (e.g. the windowed test-run keys when installing normally).
    header: the first comment line (default CONFIG_HEADER); it must start with '# TOD HD' (that marks the file as ours
    and every such line is replaced on the next write), e.g. naming the fx DLL files when they are installed."""
    header = CONFIG_HEADER if header is None else header
    if not header.startswith("# TOD HD") or any(not (32 <= ord(c) < 127) for c in header):
        raise GameDataError("configpc.txt header must be one printable ASCII line starting with '# TOD HD'")
    path = Path(game_dir) / "configpc.txt"
    old = path.read_bytes() if path.exists() else b""
    fs = ", ".join(list(override_names) + BASE_ARCHIVES)
    dropped = tuple(k.lower().encode("ascii") for k in drop)
    keep = []
    for line in old.replace(b"\r\n", b"\n").split(b"\n"):
        if line.strip().lower().startswith(b"filesystem") or line.startswith(b"# TOD HD"):
            continue
        if dropped and line.strip().lower().split(b"=")[0].strip() in dropped:
            continue
        keep.append(line)
    while keep and not keep[-1].strip():
        keep.pop()
    lines = [header.encode("ascii")]
    lines += [l for l in keep if l.strip()]
    lines.append(b"filesystem = " + fs.encode("ascii"))
    for k, v in (extra or {}).items():
        lines = [l for l in lines if not l.strip().lower().startswith(k.encode("ascii"))]
        lines.append(("%s = %s" % (k, v)).encode("ascii"))
    raw = b"\r\n".join(lines) + b"\r\n"
    parsed = parse_config(raw)
    if parsed.get("filesystem") != fs:
        raise GameDataError("configpc.txt would not parse to the intended archive list: %r" % parsed.get("filesystem"))
    for k, v in (extra or {}).items():
        if parsed.get(k) != str(v):
            raise GameDataError("configpc.txt would not parse %s correctly" % k)
    return path, raw, parsed


def archive_slots(game_dir, names):
    """Slots the engine will use: every listed name and its '<lang>_' variant that exists in the game folder."""
    n = 0
    for nm in names:
        for cand in (nm, GAME_LANG + "_" + nm):
            if os.path.exists(os.path.join(game_dir, cand)):
                n += 1
    return n


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15).stdout.lower()
    except Exception:
        return False
    return '"tod.exe"' in out or '"totaloverdose.exe"' in out


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
