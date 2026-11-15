"""cpu_guard.py - keep this process (and every child it starts) off CPU cores that compute SIMD division wrongly.

Found 2026-11-13: on this machine (AMD EPYC 7543P cloud host) logical CPUs 4 and 5 return wrong results for PACKED
float division (numpy float32/float64 `/`, SSE and AVX paths alike); scalar division and sqrt are fine. A process the
scheduler puts on those cores gets ~130 wrong elements out of 1024 in `np.arange(1024) / 1024`, every time. That was the
"numpy random texture error" (tex_gen.gen_wood IndexError, 1 build in 5) - and it can also corrupt textures SILENTLY.

Importing this module tests every CPU in the process affinity mask (a pinned thread runs a packed-division check),
then drops the bad ones from the process mask. Windows children inherit the mask. Cost: a few ms per core.

  import cpu_guard            # at the top of any builder that uses numpy
  python -I cpu_guard.py      # report only
"""
import ctypes
import os
import sys

BAD = []
MASK_BEFORE = MASK_AFTER = None


def _check():
    import numpy as np
    n = 1024
    a = np.arange(n, dtype=np.float64)
    ref = np.array([i / n for i in range(n)])
    for _ in range(20):
        if not np.array_equal(a / float(n), ref):
            return False
        if not np.array_equal(a.astype(np.float32) / np.float32(n), ref.astype(np.float32)):
            return False
    return True


def guard(verbose=False):
    global BAD, MASK_BEFORE, MASK_AFTER
    if os.name != "nt" or os.environ.get("CPU_GUARD_OFF") == "1":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.GetCurrentThread.restype = ctypes.c_void_p
    k.SetThreadAffinityMask.restype = ctypes.c_size_t
    k.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    proc = ctypes.c_size_t()
    sysm = ctypes.c_size_t()
    hp = ctypes.c_void_p(k.GetCurrentProcess())
    if not k.GetProcessAffinityMask(hp, ctypes.byref(proc), ctypes.byref(sysm)):
        return
    MASK_BEFORE = proc.value
    ht = ctypes.c_void_p(k.GetCurrentThread())
    good = 0
    bad = []
    for cpu in range(64):
        bit = 1 << cpu
        if not (MASK_BEFORE & bit):
            continue
        old = k.SetThreadAffinityMask(ht, bit)
        if not old:
            continue
        ok = _check()
        k.SetThreadAffinityMask(ht, old)
        if ok:
            good |= bit
        else:
            bad.append(cpu)
    BAD = bad
    if bad and good:
        k.SetProcessAffinityMask(hp, ctypes.c_size_t(good))
        k.SetThreadAffinityMask(ht, good)
    MASK_AFTER = good if (bad and good) else MASK_BEFORE
    if bad or verbose:
        print("cpu_guard: bad cores %s, affinity 0x%X -> 0x%X" % (bad, MASK_BEFORE, MASK_AFTER), file=sys.stderr, flush=True)
    if bad and not good:
        raise SystemExit("cpu_guard: every allowed core fails the SIMD division check - stop, hardware fault")


guard(verbose=__name__ == "__main__")
