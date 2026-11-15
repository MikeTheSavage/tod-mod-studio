"""Build a test override that makes one asset block need MORE MAIN_ASSETS memory, without changing what it contains.

    python pad_block.py --out <output folder>\\padtest                            (build pool_test.zip only)
    python pad_block.py --out DIR --deploy <test game folder>                      (also install it there)
    python pad_block.py --undeploy <test game folder>                              (remove it again)

How: a block is [299-byte prefix for .map] + <IIIiII timestamp, propCk, cmdCk, N, S, M> + info[S] + sizes[N] + payloads.
AssetManager::LoadResourceBlock (0x8759E0) allocates S (+alignment) bytes from the block's pool
(Asset::AllocateResourceForBlockLoad 0x852070 -> MemoryManager::AllocateByType; .map/.submap -> MAIN_ASSETS),
reads S bytes into it in one read, then walks the N records by their own sizes. Bytes after the last record are
never looked at. So S += P with P zero bytes appended to the info region raises the pool demand by exactly P and
changes nothing else. Default: the Map07 (Meat Factory) map block, which "The Ambush" loads, padded by 80 MiB.

Vanilla MAIN_ASSETS fill at The Ambush is 24.5 MB (engine log). +80 MiB = about 108 MB:
  - stock 90 MiB pool  -> overflow -> AllocateByType returns NULL, unchecked -> access violation while loading
  - pool patched to 256 MiB (tod_mempool.ini main_mb = 256) -> loads; the engine log shows "asset block took" ~ 81940 Kb

Sources are only read (the GOG blocks.naz). --deploy refuses the GOG folder and other protected folders,
refuses while TOD runs, keeps configpc.txt as configpc.txt.pool_bak, and writes the filesystem line last.
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "anim_replace", "codec"),):
    if os.path.exists(os.path.join(cand, "todblock.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break
import todblock as tb  # noqa: E402  (read-only archive reader, tools/anim_replace/codec)

GOG = r"C:\GOG Games\Total Overdose"
DEFAULT_BLOCK = "data_pc/overdose_the_game/overdose/shared/mainmap_map07_meat_factory.map"
ZIP_NAME = "pool_test.zip"
LOG_NAME = "tod_pool_log.txt"
BASE_ARCHIVES = ["blocks.naz", "sounds.naz", "videos00.naz", "videos01.naz"]
FORBIDDEN = [r"C:\GOG Games"]


class Fail(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def tod_running():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=30).stdout.lower()
    except Exception:
        return True
    return '"tod.exe"' in out or '"totaloverdose.exe"' in out


def forbidden(path):
    p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    for f in FORBIDDEN:
        f = os.path.normcase(os.path.realpath(f))
        if p == f or p.startswith(f + os.sep):
            return True
    return False


def pad(data, ext, pad_bytes):
    pre = tb.BLOCK_EXTS[ext]
    ts, pc, cc, n, s, m = struct.unpack_from("<IIIiII", data, pre)
    h = pre + 24
    if h + s + 4 * n > len(data):
        raise Fail("block header does not fit the file (S=%d N=%d size=%d)" % (s, n, len(data)))
    if pad_bytes % 16:
        raise Fail("pad must be a multiple of 16")
    out = bytearray(data[:pre])
    out += struct.pack("<IIIiII", ts, pc, cc, n, s + pad_bytes, m)
    out += data[h:h + s]
    out += b"\0" * pad_bytes
    out += data[h + s:]
    # checks: header round trip, info identical, tail identical
    ts2, pc2, cc2, n2, s2, m2 = struct.unpack_from("<IIIiII", out, pre)
    if (ts2, pc2, cc2, n2, m2) != (ts, pc, cc, n, m) or s2 != s + pad_bytes:
        raise Fail("header check failed")
    if bytes(out[h:h + s]) != data[h:h + s] or bytes(out[h + s + pad_bytes:]) != data[h + s:]:
        raise Fail("body check failed")
    return bytes(out), {"timestamp": "%08x" % ts, "records": n, "info_S_before": s, "info_S_after": s + pad_bytes,
                        "max_asset_M": m}


def write_zip(path, entry, data):
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        zi = zipfile.ZipInfo(entry, date_time=(2005, 8, 21, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_STORED
        zi.create_system = 0
        zi.external_attr = 0
        zf.writestr(zi, data)
    os.replace(tmp, path)
    st = os.stat(os.path.join(GOG, "blocks.naz"))
    os.utime(path, (st.st_atime, st.st_mtime))
    a = tb.Archive(path)                                       # the engine's own lookup (OpenZip port)
    hit = a.find("/" + entry)
    if a.naz or hit is None or hit[1] != len(data):
        raise Fail("zip: engine lookup failed")
    with open(path, "rb") as f:
        f.seek(hit[0])
        if f.read(hit[1]) != data:
            raise Fail("zip: bytes at the engine's offset differ")


def deploy(game, zip_path):
    if forbidden(game):
        raise Fail("refusing to deploy into %s (only a private test copy is allowed)" % game)
    if not os.path.exists(os.path.join(game, "TOD.exe")):
        raise Fail("no TOD.exe in " + game)
    if tod_running():
        raise Fail("TOD.exe / TotalOverdose.exe is running; not touching any game folder now")
    shutil.copy2(zip_path, os.path.join(game, ZIP_NAME))
    cfg = os.path.join(game, "configpc.txt")
    old = open(cfg, "rb").read() if os.path.exists(cfg) else b""
    if old.startswith(b"\xef\xbb\xbf") or b"\0" in old:
        raise Fail("configpc.txt is not plain ASCII")
    bak = cfg + ".pool_bak"
    if not os.path.exists(bak):
        open(bak, "wb").write(old)
    lines = [l for l in old.replace(b"\r\n", b"\n").split(b"\n") if l.strip()
             and not l.strip().lower().startswith(b"filesystem") and not l.strip().lower().startswith(b"logdumpfile")
             and not l.startswith(b"# pool test")]
    lines = [b"# pool test override (undo: pad_block.py --undeploy <folder>)"] + lines
    lines.append(("logdumpfile = " + LOG_NAME).encode("ascii"))
    lines.append(("filesystem = " + ", ".join([ZIP_NAME] + BASE_ARCHIVES)).encode("ascii"))
    open(cfg, "wb").write(b"\r\n".join(lines) + b"\r\n")
    return open(cfg, "rb").read().decode("ascii")


def undeploy(game):
    if forbidden(game):
        raise Fail("refusing %s" % game)
    if tod_running():
        raise Fail("TOD is running")
    cfg = os.path.join(game, "configpc.txt")
    bak = cfg + ".pool_bak"
    if os.path.exists(bak):
        shutil.copyfile(bak, cfg)
        os.remove(bak)
    z = os.path.join(game, ZIP_NAME)
    if os.path.exists(z):
        os.remove(z)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--block", default=DEFAULT_BLOCK, help="archive name of the block to pad (a .map/.submap goes to MAIN_ASSETS)")
    ap.add_argument("--pad-mib", type=float, default=80.0, help="extra pool demand in MiB (default 80)")
    ap.add_argument("--out", help="output folder for pool_test.zip + report")
    ap.add_argument("--deploy", help="TEST game folder to receive pool_test.zip + configpc.txt lines")
    ap.add_argument("--undeploy", help="remove pool_test.zip and restore configpc.txt in this TEST folder")
    a = ap.parse_args()
    try:
        if a.undeploy:
            undeploy(a.undeploy)
            print("undeployed", a.undeploy)
            return 0
        if not a.out:
            raise Fail("--out is required")
        if forbidden(a.out):
            raise Fail("refusing --out %s" % a.out)
        if a.deploy and forbidden(a.deploy):
            raise Fail("refusing to deploy into %s (only a private test copy is allowed)" % a.deploy)
        arch = tb.open_naz(GOG)
        name = a.block.lower().replace("\\", "/")
        if name not in arch.names:
            raise Fail("no such block in blocks.naz: " + name)
        ext = os.path.splitext(name)[1]
        if ext not in tb.BLOCK_EXTS:
            raise Fail("not a block: " + ext)
        base = arch.read(name)
        pb = int(round(a.pad_mib * 1048576)) & ~15
        out, rep = pad(base, ext, pb)
        os.makedirs(a.out, exist_ok=True)
        zp = os.path.join(a.out, ZIP_NAME)
        write_zip(zp, name, out)
        rep.update({"block": name, "pad_bytes": pb, "base_sha256": sha(base), "padded_sha256": sha(out),
                    "zip": zp, "zip_bytes": os.path.getsize(zp)})
        with open(os.path.join(a.out, "pad_report.txt"), "w") as f:
            for k, v in rep.items():
                f.write("%s = %s\n" % (k, v))
        for k, v in rep.items():
            print("%s = %s" % (k, v))
        if a.deploy:
            print(deploy(a.deploy, zp))
        return 0
    except Fail as e:
        print("FAIL:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
