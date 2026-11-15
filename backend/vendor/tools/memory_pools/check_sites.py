r"""Print every memory-pool size site of a TOD.exe (GOG build or its LAA copy) and its LARGE_ADDRESS_AWARE flag.
Read only.   python check_sites.py ["C:\GOG Games\Total Overdose\TOD.exe"]

Sites are the imm32 operands of the `push imm32` (opcode 68) instructions in MemoryManager::CreateAllocators
(0x478440) and Scene::CreateQuadTrees (0x894880). File offset = VA - 0x400000 (.text raw offset == RVA here).
"""
import hashlib
import struct
import sys

SITES = [  # (name, push VA, original value, kind, what)
    ("CUTSCENE_OR_REWIND", 0x47864C, 0x00200000, "Frame", "cutscene / rewind blocks"),
    ("PLAYER_DATA", 0x478662, 0x00300000, "Frame", "playerdata blocks (vehicles, player variants)"),
    ("MISSION_ASSETS", 0x478678, 0x00700000, "Frame", "mission blocks; fragment fallback when flag 0xA3CE60"),
    ("MAIN_ASSETS", 0x47868E, 0x05A00000, "Frame", "main + map + submap INFO, scene graph"),
    ("COLLISION_CACHE_ENTRIES", 0x4786A7, 0x0003E800, "Pool(0x30)", "5,333 x 48-byte collision cache objects"),
    ("DEFRAGMENTING", 0x4786BD, 0x00096000, "BestFit", "fragment fallback (flag 0xA3CE60)"),
    ("RENDERLIST", 0x4786D3, 0x00A00000, "BestFit", "display lists, quadtree nodes, per-block payload staging (M)"),
    ("TEMP", 0x4786E9, 0x00040000, "FirstFit", "String and file-name helpers (74 direct refs in 0x402000-0x41E000)"),
    ("SCRATCHPAD", 0x478702, 0x00003FC0, "Stack", "16,320-byte scratch stack"),
    ("quadtree main nodes", 0x894884, 10000, "count", "32 B each in RENDERLIST, u16 index (max 65,534)"),
    ("quadtree aux nodes", 0x894892, 12200, "count", "32 B each in RENDERLIST, u16 index (max 65,534)"),
]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:\GOG Games\Total Overdose\TOD.exe"
    d = open(path, "rb").read()
    e = struct.unpack_from("<I", d, 0x3C)[0]
    ch = struct.unpack_from("<H", d, e + 0x16)[0]
    print("%s  md5 %s" % (path, hashlib.md5(d).hexdigest()))
    print("Characteristics 0x%04X at file 0x%X -> LARGE_ADDRESS_AWARE %s" % (ch, e + 0x16, "YES" if ch & 0x20 else "no"))
    bad = 0
    for name, va, orig, kind, what in SITES:
        off = va - 0x400000
        op, imm = d[off], struct.unpack_from("<I", d, off + 1)[0]
        state = "original" if (op == 0x68 and imm == orig) else ("CHANGED" if op == 0x68 else "NOT A PUSH")
        bad += state == "NOT A PUSH"
        size = ("%.3f MiB" % (imm / 1048576.0)) if kind != "count" else "%d nodes" % imm
        print("  %-24s imm @ VA 0x%06X (file 0x%06X)  0x%08X = %-13s %-10s %-9s %s" % (name, va + 1, off + 1, imm, size, kind, state, what))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
