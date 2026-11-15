"""TOD player locomotion model (GOG TOD.exe, static RE) and a checker against in-game position logs.

The model is the engine's own fixed-step update, read from the decompile (see docs/subsystem_player_movement.md):

  physics clock   character_root FUN_005C1C90: time_to_use += world_dt * MoveCtrl.SpeedMultiplier,
                  one PhysicCtrl integrate (FUN_0059C740) per TimeStep (0.04 s) of accumulated time.
  run / strafe    calc_velocity FUN_0055FC80, once per integrate:
                      v = A * v + B * k * stick          A 0.75 (0x9B397C), B 0.25 (0x9B6AE0)
                      k = 6 when move.x == 0, else 5    (0x9B6B84 / 0x9BBEC8)
  sprint          v = 0.75 * v + 2.25 (forward)          -> 9 m/s   (0x9BF630)
  stop (idle)     calc_velocity FUN_0055E600: v *= 0.5, v = 0 when |v|^2 < 0.05   (0x9B37C8 / 0x9B3BE8)
  player time     SpeedMultiplier 0.95 at full stick (0.8 / 0.65 for |stick| < 0.75 / < 0.5)

usage:
  velmodel.py table [--accel 0.75] [--stop 0.5] [--k 6] [--mult 0.95]     step tables (speed, distance, time)
  velmodel.py check <log> [...] [--accel 0.62] [--stop 0.5]               compare a collwatch or movefeel log_motion log
  velmodel.py compare                                                     vanilla vs the proposal in the doc

`check` reads the collision lab's collwatch proxy log (player body probe, mask 03, ground line test ra=8BDBCC runs
once per integrate), splits it into runs of consecutive integrates (log bursts) and prints, for every run that starts
from rest or stops, the measured per-step distance next to the model's.
"""
import re
import sys
import math

STEP = 0.04


def run_profile(n, target=6.0, accel=0.75, v0=0.0):
    """speeds after each of n integrates for v = accel*v + (1-accel)*target (the engine's 0.75/0.25 form)."""
    v, out = v0, []
    for _ in range(n):
        v = accel * v + (1.0 - accel) * target
        out.append(v)
    return out


def stop_profile(v0=6.0, decay=0.5, cut2=0.05, nmax=40):
    v, out = v0, []
    for _ in range(nmax):
        v = v * decay
        if v * v < cut2:
            v = 0.0
        out.append(v)
        if v == 0.0:
            break
    return out


def steps_to(frac, accel):
    return math.log(1.0 - frac) / math.log(accel)


def table(accel=0.75, stop=0.5, k=6.0, mult=0.95):
    rt = STEP / mult
    print('run start (target %.2f m/s sim, %.2f m/s real), A=%.3f, one step = %.1f ms real' % (k, k * mult, accel, rt * 1000))
    d = 0.0
    for i, v in enumerate(run_profile(12, k, accel), 1):
        d += v * STEP
        print('  step %2d  t=%5.3f s  v=%5.2f m/s (%5.1f%%)  step dist %.3f m  total %.3f m' % (i, i * rt, v, 100 * v / k, v * STEP, d))
    for f in (0.63, 0.9, 0.95):
        n = steps_to(f, accel)
        print('  %2d%% of target after %.1f steps = %.3f s real' % (f * 100, n, n * rt))
    print('stop from %.2f m/s, decay %.2f:' % (k, stop))
    d = 0.0
    for i, v in enumerate(stop_profile(k, stop), 1):
        d += v * STEP
        print('  step %2d  t=%5.3f s  v=%5.2f m/s  total slide %.3f m' % (i, i * rt, v, d))


def parse_collwatch(path):
    """collision lab collwatch log (player probe ground line test, once per integrate) or the movefeel proxy's
    log_motion lines (INT <ms> pos x y z ...); returns [(ms, x, y, z)]."""
    pts = []
    for line in open(path, errors='replace'):
        m = re.match(r'(\d+) LINE ra=8BDBCC probe=(\w+) mask=03 from (\S+) (\S+) (\S+) to', line)
        if m:
            pts.append((int(m.group(1)), float(m.group(3)), float(m.group(4)), float(m.group(5))))
            continue
        m = re.search(r'INT (\d+) pos (\S+) (\S+) (\S+)', line)
        if m:
            pts.append((int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))))
    return pts


def check(path, accel=0.75, stop=0.5):
    """Starts from rest and stops to rest in a collwatch log, compared step by step with the model.
    The proxy logs every integrate while the player moves (bursts) and about every 200 ms while he stands."""
    pts = parse_collwatch(path)
    print('%s: %d player integrate samples' % (path, len(pts)))
    # drop exact duplicates (same time and position logged twice)
    q = [pts[0]] if pts else []
    for p in pts[1:]:
        if p != q[-1]:
            q.append(p)
    d = [0.0] + [math.hypot(q[i][1] - q[i - 1][1], q[i][3] - q[i - 1][3]) for i in range(1, len(q))]
    dt = [0] + [q[i][0] - q[i - 1][0] for i in range(1, len(q))]
    worst = 0.0
    nstart = nstop = 0
    i = 1
    while i < len(q):
        # start from rest: previous step zero, this step ~0.06 (run, k 6) or ~0.05 (strafe, k 5)
        first = {k: (1.0 - accel) * k * STEP for k in (6.0, 5.0)}
        kk = [k for k, f in first.items() if abs(d[i] - f) < 0.12 * f]
        if d[i - 1] == 0.0 and kk:
            j = i + 1
            while j < len(q) and dt[j] <= 70 and d[j] >= d[j - 1] - 1e-4 and d[j] > 0.0:
                j += 1
            meas = d[i:j]
            if len(meas) >= 3:
                k = kk[0]
                model = [v * STEP for v in run_profile(len(meas), k, accel)]
                err = max(abs(a - b) for a, b in zip(meas, model))
                worst = max(worst, err)
                nstart += 1
                print('  start k=%g  measured %s' % (k, ' '.join('%.3f' % x for x in meas)))
                print('              model    %s   max err %.4f m' % (' '.join('%.3f' % x for x in model), err))
            i = j
            continue
        # stop: steady run/strafe step, then halving with consecutive integrates
        if 0.18 < d[i - 1] < 0.25 and dt[i] <= 70 and 0.4 < d[i] / d[i - 1] < 0.6:
            j = i + 1
            while j < len(q) and dt[j] <= 70 and d[j] < d[j - 1] and d[j] > 0.0:
                j += 1
            meas = d[i:j]
            model = [v * STEP for v in stop_profile(d[i - 1] / STEP, stop)][:len(meas)]
            # a step far below the model means Ram ran into a collision shape while stopping: report, do not score
            cut = [k for k, (a, b) in enumerate(zip(meas, model)) if a < 0.5 * b - 0.005]
            if cut:
                meas, model = meas[:cut[0]], model[:cut[0]]
            err = max(abs(a - b) for a, b in zip(meas, model)) if meas else 0.0
            worst = max(worst, err)
            nstop += 1
            print('  stop  from %.3f  measured %s%s' % (d[i - 1], ' '.join('%.3f' % x for x in meas),
                                                     '  (then blocked by a collision shape)' if cut else ''))
            print('                     model    %s   max err %.4f m' % (' '.join('%.3f' % x for x in model), err))
            i = j
            continue
        i += 1
    # steady speed and real time per integrate inside bursts of consecutive integrates
    st = [(d[i], dt[i]) for i in range(1, len(q)) if dt[i] <= 70 and d[i] > 0.18 and abs(d[i] - d[i - 1]) < 0.002]
    if st:
        run = [x for x in st if x[0] > 0.22]
        strafe = [x for x in st if x[0] <= 0.22]
        for nm, s in (('run', run), ('strafe', strafe)):
            if s:
                m = sum(x[0] for x in s) / len(s)
                print('  steady %-6s %3d steps: %.4f m/step = %.3f m/s sim' % (nm, len(s), m, m / STEP))
    bursts, cur = [], []
    for i in range(1, len(q)):
        if dt[i] <= 70 and d[i] > 0.0:
            cur.append(q[i])
        else:
            if len(cur) >= 6:
                bursts.append(cur)
            cur = []
    if bursts:
        ms = [(b[-1][0] - b[0][0]) / (len(b) - 1) for b in bursts]
        print('  real time per integrate over %d bursts: %.1f ms (model 40 / 0.95 = 42.1 ms)' % (len(bursts), sum(ms) / len(ms)))
    print('  starts %d, stops %d, worst deviation from the model %.4f m per step' % (nstart, nstop, worst))
    return worst


def compare():
    print('vanilla: accel 0.75/step, stop 0.5/step')
    table(0.75, 0.5)
    print()
    print('proposal (doc section 9, change 2): accel 0.62/step, stop 0.5/step')
    table(0.62, 0.5)


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd = argv[1]
    if cmd == 'table':
        kw = dict(accel=0.75, stop=0.5, k=6.0, mult=0.95)
        a = argv[2:]
        for i in range(0, len(a) - 1, 2):
            kw[a[i].lstrip('-')] = float(a[i + 1])
        table(**kw)
    elif cmd == 'check':
        a = argv[2:]
        kw = {}
        for key in ('--accel', '--stop'):
            if key in a:
                i = a.index(key); kw[key[2:]] = float(a[i + 1]); del a[i:i + 2]
        worst = max(check(p, **kw) for p in a)
        return 0 if worst < 0.003 else 1
    elif cmd == 'compare':
        compare()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
