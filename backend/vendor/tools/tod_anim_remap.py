#!/usr/bin/env python3
"""
STATIC derivation of the per-animation bone remap (no runtime / SecuROM).

The engine's AnimationController rebuilds a remap table (controller+0xc) every time a clip is set,
by matching MODEL pivot names to .ani channel names, case-insensitively. We reproduce that here so
skinned animation can be decoded fully statically. Traced from FUN_009032d0 (builder) / FUN_008fff50
(.ani channel-name getter) / FUN_009083f0 (model name lookup) in TOD.exe.c.

.ani channel-name block (the keyframe block at AnimationAsset+0x5C, base = &~3):
  +0x00 u32 entryCount
  +0x0c per-entry 12-byte (0xc) records: u32 hdr, u32 posOff(words), u32 oriOff(words)
        hdr & 0xfff  = byte offset of the channel name string from the block base
        hdr & 0x4000 = name is a builtin (index into the engine GamePivot table) instead of pool
The name strings live in a pool that immediately follows the offset/keyframe table in the same block.

remap[model_pivot] = ani_entry  (or -1 if that model pivot has no matching channel).
"""
import struct

def _u32(b, o): return struct.unpack_from('<I', b, o)[0]

def _cstr(info, off):
    end = info.find(b'\0', off)
    return info[off:end].decode('latin-1', 'replace') if end >= 0 else info[off:].decode('latin-1', 'replace')

# Engine builtin pivot-name table (PTR_s_GamePivot_00a12ff0 in TOD.exe). Character anims reference
# bones by INDEX into this table (channel hdr bit 0x4000 set, index = hdr & 0xfff) instead of an
# inline string — it's the standard 3ds-Max Biped skeleton naming shared by every humanoid. The 49
# names were extracted from the clean GOG TOD.exe .rdata (see tools/extract_gamepivot.py output).
import os, json as _json
_GP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gamepivot_names.json')
try:
    _gp = _json.load(open(_GP_PATH))
    GAMEPIVOT_BUILTINS = {i: n for i, n in enumerate(_gp)}
except Exception:
    GAMEPIVOT_BUILTINS = {0: 'GamePivot'}

def ani_channel_names(info, anim_base, deref):
    """Return the ordered list of .ani channel names for the animation record at anim_base."""
    kf = deref(info, anim_base + 0x5C)
    if kf is None:
        return []
    cnt = _u32(info, kf)
    if not (0 < cnt < 4096):
        return []
    names = []
    for e in range(cnt):
        hdr = _u32(info, kf + 0xc + e * 0xc)
        off = hdr & 0xfff
        if hdr & 0x4000:
            names.append(GAMEPIVOT_BUILTINS.get(off, '__builtin%d__' % off))
        else:
            names.append(_cstr(info, kf + off))
    return names

def derive_remap(info, anim_base, model_pivots, deref):
    """Build remap[model_pivot_index] -> ani_entry_index by case-insensitive bone-name match.

    model_pivots: list of dicts with a 'name' key (from tod_model_extract.extract_model).
    Returns (remap, names) where remap is a list len(model_pivots), -1 where no channel matches.
    """
    names = ani_channel_names(info, anim_base, deref)
    lut = {}
    for e, nm in enumerate(names):
        if nm:
            lut.setdefault(nm.lower(), e)   # first-seen wins (matches engine linear scan)
    remap = []
    for pv in model_pivots:
        nm = (pv.get('name') or '').lower()
        remap.append(lut.get(nm, -1) if nm else -1)
    return remap, names

if __name__ == '__main__':
    import sys, argparse
    sys.argv = sys.argv
    import tod_model_extract as me
    import tod_anim_extract as ae
    ap = argparse.ArgumentParser(description='Derive + print the static bone remap for a model/anim.')
    ap.add_argument('block')
    ap.add_argument('model', help='model name substring')
    ap.add_argument('-a', '--anim', default=None, help='anim name substring (default: first for model)')
    args = ap.parse_args()
    info = me.load_info(args.block)
    mrec = [(p, n) for p, n in me.find_model_records(info) if args.model.lower() in n.lower()]
    if not mrec:
        print('no model matching', args.model); sys.exit(1)
    mp, mn = mrec[0]
    model = me.extract_model(info, mp, mn)
    arec = [(p, n) for p, n in ae.find_anim_records(info)
            if (args.anim or args.model).lower() in n.lower()]
    if not arec:
        print('no anim matching', args.anim or args.model); sys.exit(1)
    ap_, an = arec[0]
    remap, names = derive_remap(info, ap_, model['pivots'], me.deref)
    print('MODEL %s (%d pivots)' % (mn, len(model['pivots'])))
    print('ANIM  %s (%d channels)' % (an, len(names)))
    ident = sum(1 for i, v in enumerate(remap) if v == i)
    print('remap (model_pivot -> ani_entry), %d/%d identity:' % (ident, len(remap)))
    for i, (pv, r) in enumerate(zip(model['pivots'], remap)):
        cn = names[r] if 0 <= r < len(names) else '--'
        print('  bone%2d %-22r -> e%-3s  %s' % (i, pv.get('name'), r if r >= 0 else 'x', cn))
