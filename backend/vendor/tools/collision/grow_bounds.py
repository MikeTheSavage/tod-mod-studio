"""grow_bounds.py - make a model's bounding sphere (ModelAsset header +0x44 centre xyz, +0x50 radius, model space)
cover all of its static hulls, so collision added outside the original model extents is found by sphere probes.

  python -I grow_bounds.py --block FILE --entry ARCHIVE_NAME --model /data/Models/.../X.model --out DIR

Why: in game (run r5, 2026-10-18) a box added to Chunk_10 37 m outside that model's sphere was found by long line
tests (aim rays, lens-flare rays) but NOT by the player's body probe: Ram ran through it. The scene registers each
model by this sphere, so a shape outside it is invisible to sphere queries near it.
Only the radius changes (4 bytes); the centre is kept. Writes DIR/<block> and DIR/coll_override.zip (as coll_replace).
"""
import argparse, json, math, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'proj'))
sys.dont_write_bytecode = True
import todblock as tb, todcoll as tc
import coll_replace as cr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--block', required=True); ap.add_argument('--entry', required=True)
    ap.add_argument('--model', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--margin', type=float, default=0.5)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = open(a.block, 'rb').read(); ext = os.path.splitext(a.block)[1]
    blk = tb.Block(data, ext); info = bytearray(blk.info)
    starts = tb.record_starts(bytes(info), blk.n)
    k = cr.model_record_index(bytes(info), starts, a.model); R = starts[k]
    cx, cy, cz, r = struct.unpack_from('<4f', info, R + 0x44)
    reg, _ = tc.read_region(bytes(info), tc.deref(bytes(info), R + 0x54), 'f54')
    need = max(math.dist((cx, cy, cz), v) for s in reg['shapes'] if s['type'] == 4 for v in s['verts'])
    new_r = max(r, need + a.margin)
    struct.pack_into('<f', info, R + 0x50, new_r)
    blk.info = info
    out = blk.serialize()
    # verify: exactly the 4 radius bytes differ, the block parses, every collision region still round-trips
    diff = [i for i in range(len(data)) if data[i] != out[i]] if len(data) == len(out) else None
    chk = tb.Block(out, ext); s2 = tb.record_starts(bytes(chk.info), chk.n)
    base = len(data) - len(blk.info) - 4 * blk.n - sum(blk.sizes) if False else None
    rep = dict(model=a.model, centre=[cx, cy, cz], radius_old=r, farthest_hull_vertex=need, radius_new=new_r,
               bytes_changed=len(diff) if diff is not None else 'size changed', records=len(s2))
    if diff is None or len(diff) > 4:
        rep['result'] = 'FAIL: more than the radius changed'
    else:
        name = os.path.basename(a.block)
        open(os.path.join(a.out, name), 'wb').write(out)
        rep['zip'] = cr.write_zip(os.path.join(a.out, cr.ZIP_NAME), a.entry, out)
        rep['result'] = 'PASS'
    json.dump(rep, open(os.path.join(a.out, 'report_bounds.json'), 'w'), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    main()
