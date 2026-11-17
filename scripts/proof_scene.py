"""Proof run of the large-scene import on a real capture, in-process on a private data copy (never the game, never the user's saves).

    python -I scripts/proof_scene.py FILE.glb WORK_DIR [--region x0,z0,x1,z1] [--scale S] [--up y|z|-y] [--sample x,z,r] [--check GAME]
                                     [--stages select,clean,textures,chunks,collision,send] [--sections section_m=300,section_tris=60000]

Writes numbers per step (wall clock, peak working set) to WORK_DIR/proof_scene.json and prints them. The source file is read only; nothing
of it is copied into the repository. Set TODMS_HOME and TODMS_CACHE to a private copy first.
"""
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'backend'))


def peak_mb():
    class PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    ps = ctypes.WinDLL('psapi', use_last_error=True)
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PeakWorkingSetSize / 1048576.0), round(c.PeakPagefileUsage / 1048576.0)


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def main():
    glb, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    from todms import sceneimport as SI
    out, t_all = {}, time.time()

    def step(name, fn):
        t0 = time.time()
        r = fn()
        ws, pf = peak_mb()
        out[name] = dict(seconds=round(time.time() - t0, 1), peak_working_set_mb=ws, peak_commit_mb=pf)
        print('%-10s %6.1f s  working set peak %5d MB  commit peak %5d MB' % (name, time.time() - t0, ws, pf), flush=True)
        return r
    info = step('open', lambda: SI.open_scene(glb))
    out['open'].update(triangles=info['triangles'], vertices=info['vertices'], prims=info['prims'], materials=info['materials'], images=info['images'],
                       extent=info['extent'], up_guess=info['up_guess'])
    sid = info['sid']
    up = arg('--up', info['up_guess'].get('suggest_up') or 'y')
    ov = step('overview', lambda: SI.overview(sid, dict(up=up, mirror='z')))
    import base64
    with open(os.path.join(work, 'overview.png'), 'wb') as f:
        f.write(base64.b64decode(ov['png'].split(',', 1)[1]))
    out['overview'].update(min=ov['min'], max=ov['max'], cell=ov['cell'])
    if arg('--sample'):
        x, z, r = [float(v) for v in arg('--sample').split(',')]
        s = step('sample', lambda: SI.sample_glb(sid, dict(up=up, mirror='z'), [x, z], r))
        out['sample'].update(url=s['url'], triangles=s['triangles'])
    scale = float(arg('--scale', 1.0))
    p = dict(up=up, mirror='z', scale=scale, name=arg('--name', 'Showcase'))
    for key in ('sections', 'textures', 'clean', 'collision'):
        if arg('--' + key):
            p[key] = {k: json.loads(v) for k, v in (kv.split('=', 1) for kv in arg('--' + key).split(','))}
    if arg('--region'):
        x0, z0, x1, z1 = [float(v) for v in arg('--region').split(',')]
        p['region'] = dict(polygon=[[x0, z0], [x1, z0], [x1, z1], [x0, z1]], mode='clip')
        out['count'] = SI.count_region(sid, p)
        print('count', out['count'], flush=True)
    stages = (arg('--stages', 'select,clean,textures,chunks,collision') or '').split(',')
    reps = {}
    for st in stages:
        if st == 'send':
            r = step('send', lambda: SI.send(sid, p, dict(kind='newmap', name=p['name'])))
            out['send'].update(r)
            continue
        if st in ('select', 'clean', 'textures', 'chunks', 'collision'):
            reps = step(st, lambda st=st: SI.report(sid, p, st))
            out[st].update(report=json.loads(json.dumps(reps.get(st if st != 'select' else 'select'), default=str)))
    if 'collision' in reps or 'chunks' in reps:
        top = reps.get('collision') or reps.get('chunks')
        out['meters'] = [dict(id=m['id'], used=m['used'], max=m['max'], status=m['status']) for m in top['meters']]
    out['total_seconds'] = round(time.time() - t_all, 1)
    with open(os.path.join(work, 'proof_scene.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps(out.get('meters', []), indent=0))
    return out


if __name__ == '__main__':
    main()
