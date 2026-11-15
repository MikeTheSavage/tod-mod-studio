"""campos.py LOG T0 T1 - camera position (start of the lens-flare ray, LINE ra=8E4EBA whose 'from' is the camera)
next to the player probe position (POS r=2.000 mask=03), and their distance."""
import re, sys
L = open(sys.argv[1]).read().splitlines(); t0, t1 = int(sys.argv[2]), int(sys.argv[3])
player = None; last = None; rows = []
cam_prev_to = None
for l in L:
    m = re.match(r'(\d+) POS probe=\w+ ra=\w+ r=2\.000 mask=03 pos ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
    if m:
        player = tuple(map(float, m.groups()[1:])); continue
    m = re.match(r'(\d+) LINE ra=8E4EBA probe=\w+ mask=04 from ([-\d.]+) ([-\d.]+) ([-\d.]+) to ([-\d.]+) ([-\d.]+) ([-\d.]+)', l)
    if m:
        t = int(m.group(1)); fr = tuple(map(float, m.groups()[1:4])); to = tuple(map(float, m.groups()[4:7]))
        # the 4 rays are chained (ray k+1 starts where ray k ends); the camera ray is the one not starting at a previous end
        if cam_prev_to is not None and all(abs(a - b) < 1e-3 for a, b in zip(fr, cam_prev_to)):
            cam_prev_to = to; continue
        cam_prev_to = to
        if t0 <= t <= t1 and player and t != last:
            last = t
            d = ((fr[0]-player[0])**2 + (fr[2]-player[2])**2) ** 0.5
            rows.append((t, fr, player, d, fr[1] - player[1]))
for r in rows[::max(1, len(rows)//40)]:
    print('%d cam %8.3f %6.3f %8.3f  ram %8.3f %6.3f %8.3f  horiz dist %.2f  height %.2f' % (r[0], *r[1], *r[2], r[3], r[4]))
