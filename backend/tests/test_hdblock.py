"""The block reader guard: a header-shaped spot inside a record must not count as a record (synthetic block, no game files)."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from todms import hdblock, paths

SENT = 0xBAADF00D


def block(decoy):
    info = bytearray(160)
    struct.pack_into('<IIII', info, 0, 3, 44, 0, SENT)                    # record A, name at 48
    info[48:48 + 26] = b'/data/a/textures/Sc99.bmp\0'
    if decoy:                                                             # looks like a header; its name pointer lands on the '/' of "/Sc99.bmp"
        struct.pack_into('<IIII', info, 96, 1, (64 - 100) & 0xFFFFFFFF, 0, SENT)
    struct.pack_into('<IIII', info, 128, 3, 12, 0, SENT)                  # record B, name at 144
    info[144:144 + 14] = b'/data/b.model\0'
    head = struct.pack('<IIIiII', 0, 0, 0, 2, len(info), 4)
    return head + bytes(info) + struct.pack('<2I', 4, 4) + b'abcdefgh'


class Guard(unittest.TestCase):
    def setUp(self):
        paths.setup_tools()

    def test_plain_block_reads(self):
        b = hdblock.Block(block(False), '.main')
        self.assertEqual([r['name'] for r in b.records], ['/data/a/textures/Sc99.bmp', '/data/b.model'])

    def test_a_pointer_into_the_middle_of_a_string_is_not_a_record(self):
        b = hdblock.Block(block(True), '.main')
        self.assertEqual(len(b.records), 2)
        import todblock
        raw = block(True)
        blk = todblock.Block(raw, '.main')
        self.assertEqual(len(todblock.record_starts(blk.info, 2)), 2)


def block_lone_slash():
    info = bytearray(160)
    struct.pack_into('<IIII', info, 0, 3, 44, 0, SENT)
    info[48:48 + 26] = b'/data/a/textures/Sc99.bmp\0'
    info[70:72] = b'\0/'                                                          # a lone "/" after a NUL: a name pointer can land on it
    info[72] = 0
    struct.pack_into('<IIII', info, 96, 1, (71 - 100) & 0xFFFFFFFF, 0, SENT)   # decoy header pointing at the lone "/"
    struct.pack_into('<IIII', info, 128, 3, 12, 0, SENT)
    info[144:144 + 14] = b'/data/b.model\0'
    head = struct.pack('<IIIiII', 0, 0, 0, 2, len(info), 4)
    return head + bytes(info) + struct.pack('<2I', 4, 4) + b'abcdefgh'


class LoneSlash(unittest.TestCase):
    def setUp(self):
        paths.setup_tools()

    def test_a_pointer_at_a_lone_slash_is_not_a_record(self):
        b = hdblock.Block(block_lone_slash(), '.main')
        self.assertEqual(len(b.records), 2)
        import todblock
        blk = todblock.Block(block_lone_slash(), '.main')
        self.assertEqual(len(todblock.record_starts(blk.info, 2)), 2)


if __name__ == '__main__':
    unittest.main()
