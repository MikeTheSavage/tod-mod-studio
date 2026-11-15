"""Make a LARGE_ADDRESS_AWARE copy of the GOG TOD.exe. The source is only read.

    python make_laa_copy.py --out <output folder>\\TOD.exe
    python make_laa_copy.py --out <test game folder>\\TOD.exe      (replaces that folder's TOD.exe; keeps a backup)

What changes: one byte, IMAGE_FILE_HEADER.Characteristics at file offset 0x166, 0x0E -> 0x2E (bit 0x20,
IMAGE_FILE_LARGE_ADDRESS_AWARE). The PE checksum field is 0 in this exe and Windows does not check it for
user-mode programs, so it stays 0. Nothing else moves, so every hooked address in the proxies stays valid.
The result must have md5 988808a8bea09242a17827d723e9f468 (the same one-byte patch as TOD HD's game\\TOD.exe).

Refuses to write into the GOG folder and the other protected folders, refuses when TOD is running,
and never writes through an existing file (a hard link would carry the change into the original): it writes a new
file and renames it into place.
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys

GOG_EXE = r"C:\GOG Games\Total Overdose\TOD.exe"
GOG_MD5 = "d9beb351b3c78ee9f14a766a368f3ff9"
LAA_MD5 = "988808a8bea09242a17827d723e9f468"
FORBIDDEN = [r"C:\GOG Games", r"C:\Program Files", r"C:\Program Files (x86)"]


class Fail(Exception):
    pass


def md5(b):
    return hashlib.md5(b).hexdigest()


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


def laa_bytes(src):
    if md5(src) != GOG_MD5:
        raise Fail("source is not the GOG TOD.exe (md5 %s, expected %s)" % (md5(src), GOG_MD5))
    e = struct.unpack_from("<I", src, 0x3C)[0]
    if src[e:e + 4] != b"PE\0\0":
        raise Fail("no PE header")
    off = e + 0x16
    ch = struct.unpack_from("<H", src, off)[0]
    if off != 0x166 or ch != 0x010E:
        raise Fail("unexpected Characteristics 0x%04X at 0x%X" % (ch, off))
    out = bytearray(src)
    struct.pack_into("<H", out, off, ch | 0x0020)
    diff = [i for i in range(len(src)) if src[i] != out[i]]
    if diff != [0x166] or out[0x166] != 0x2E:
        raise Fail("patch check failed: %r" % diff[:4])
    if md5(out) != LAA_MD5:
        raise Fail("result md5 %s, expected %s" % (md5(out), LAA_MD5))
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=GOG_EXE, help="GOG TOD.exe to read (default: the GOG install, read only)")
    ap.add_argument("--out", required=True, help="where to write the LAA copy (a file path)")
    a = ap.parse_args()
    try:
        if forbidden(a.out):
            raise Fail("refusing to write %s (protected folder)" % a.out)
        if os.path.exists(a.out) and os.path.samefile(a.out, a.src):
            raise Fail("--out is the source file itself")
        src = open(a.src, "rb").read()
        data = laa_bytes(src)
        d = os.path.dirname(os.path.abspath(a.out))
        os.makedirs(d, exist_ok=True)
        if os.path.exists(os.path.join(d, "blocks.naz")) and tod_running():
            raise Fail("TOD.exe / TotalOverdose.exe is running; not touching a game folder now")
        if os.path.exists(a.out):
            old = open(a.out, "rb").read()
            if md5(old) == LAA_MD5:
                print("already LAA:", a.out)
                return 0
            bak = a.out + ".prelaa_bak"
            if not os.path.exists(bak):
                shutil.copyfile(a.out, bak)                      # copy, not rename: the original stays in place until replace
                print("backup:", bak, md5(old))
        tmp = a.out + ".laa_part"
        with open(tmp, "wb") as f:
            f.write(data)
        st = os.stat(a.src)
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, a.out)                                  # new inode: a hard-linked original is never written
        chk = open(a.out, "rb").read()
        if md5(chk) != LAA_MD5:
            raise Fail("written file md5 mismatch")
        if md5(open(a.src, "rb").read()) != GOG_MD5:
            raise Fail("SOURCE CHANGED - stop and check")
        print("wrote %s  md5 %s  (Characteristics 0x010E -> 0x012E at 0x166)" % (a.out, LAA_MD5))
        if os.path.exists(a.out + ".prelaa_bak"):
            print("undo: copy %s back over it" % (a.out + ".prelaa_bak"))
        return 0
    except Fail as e:
        print("FAIL:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
