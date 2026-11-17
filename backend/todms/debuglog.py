"""The engine's own log (the `logdumpfile =` key of configpc.txt): where it is, how to tail it while the game runs, and what it says
afterwards (blocks loaded, memory pools, errors, what was loading last). Read only; Mod Studio ships no code of its own for this (K5)."""
import os
import re

from . import limits

POOL_RE = re.compile(r'^\s*(MainAssetBlock|MissionAssetBlock|PlayerdataBlock)\s*:\s*([\d.]+)\s*MB,\s*Max\s*([\d.]+)\s*MB', re.I)
BLOCK_RE = re.compile(r'^\s*BLOCK IN MEMORY:\s*(\S+)', re.I)
READ_RE = re.compile(r'^\s*read asset block file:\s*(\S+)', re.I)
ZIP_RE = re.compile(r'^\s*Opening zip <([^>]+)> into slot (\d+)', re.I)
LOADTIME_RE = re.compile(r"^\s*Load Time: '([^']+)'\.\s*(\d+)ms of (\d+)ms", re.I)
LOGKEY_RE = re.compile(r'^\s*logdumpfile\s*=\s*(.*?)\s*$', re.I)

# lines that look like problems and are not (the engine prints them on every start)
NOISE = (re.compile(r'chunksize .* of the StreamedWAV loader', re.I), re.compile(r'^\s*Could not find a matching language', re.I),
         re.compile(r'available=0'), re.compile(r'Number of dangling assets\s*:\s*0\b', re.I))
PROBLEM = re.compile(r'could not read|unable to load|failed|error|exception|assert|not found|missing|invalid|corrupt|overflow|out of memory|cannot', re.I)

POOL_LIMITS = (('MainAssetBlock', 'Main', 'P8'), ('MissionAssetBlock', 'Mission', None), ('PlayerdataBlock', 'Player', None))
POOL_FIXED = {'MissionAssetBlock': 7 << 20, 'PlayerdataBlock': 3 << 20}      # P9: MISSION 7 MiB, PLAYERDATA 3 MiB

EXIT_NAMES = {0xC0000005: 'the game read memory it should not (access violation)', 0xC000001D: 'illegal instruction',
              0xC0000094: 'division by zero', 0xC00000FD: 'stack overflow', 0xC0000409: 'the game stopped itself after a memory error',
              0xC0000374: 'heap corruption', 0xC0000142: 'a library failed to start', 0xC0000135: 'a library is missing',
              0x40010004: 'the game was closed from outside', 1: 'the game stopped with an error'}


def configured_log(lines):
    """The value of the last `logdumpfile =` line of a configpc.txt (list of lines), or None."""
    v = None
    for ln in lines:
        m = LOGKEY_RE.match(ln)
        if m and m.group(1):
            v = m.group(1)
    return v


def resolve(folder, value):
    return value if os.path.isabs(value) else os.path.join(folder, value)


def read_chunk(path, offset=0, limit=262144):
    """-> dict(text, offset (the next one), size). A file that got shorter than `offset` (the game truncates it at start) is read from 0."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return dict(text='', offset=0, size=0, exists=False)
    if offset > size:
        offset = 0
    if size - offset > limit:
        offset = size - limit
    with open(path, 'rb') as f:
        f.seek(offset)
        data = f.read(size - offset)
    return dict(text=data.decode('latin-1'), offset=offset + len(data), size=size, exists=True)


def read_tail_lines(path, n=50):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 262144))
            data = f.read().decode('latin-1')
    except OSError:
        return []
    return data.splitlines()[-n:]


def is_noise(line):
    return any(r.search(line) for r in NOISE)


def summarize(text, max_problems=12):
    """What a finished (or crashed) run's log says."""
    lines = text.splitlines()
    zips, blocks, reads, loads = [], [], [], []
    pools = {}
    problems = {}
    last_read, last_block_idx, last_read_idx = None, -1, -1
    for i, ln in enumerate(lines):
        m = ZIP_RE.match(ln)
        if m:
            zips.append(dict(name=m.group(1), slot=int(m.group(2))))
            continue
        m = BLOCK_RE.match(ln)
        if m:
            blocks.append(m.group(1))
            last_block_idx = i
            continue
        m = READ_RE.match(ln)
        if m:
            reads.append(m.group(1))
            last_read, last_read_idx = m.group(1), i
            continue
        m = POOL_RE.match(ln)
        if m:
            p = pools.setdefault(m.group(1), dict(used=0.0, peak=0.0))
            p['used'] = float(m.group(2))
            p['peak'] = max(p['peak'], float(m.group(3)), float(m.group(2)))
            continue
        m = LOADTIME_RE.match(ln)
        if m:
            loads.append((m.group(1), int(m.group(2))))
            continue
        if PROBLEM.search(ln) and not is_noise(ln):
            key = re.sub(r'\d+', '#', ln.strip())[:160]
            e = problems.setdefault(key, dict(line=ln.strip()[:240], count=0))
            e['count'] += 1
    pool_rows = []
    for key, label, lid in POOL_LIMITS:
        if key in pools:
            cap = limits.value(lid) if lid else POOL_FIXED.get(key)
            mb = 1048576.0
            pool_rows.append(dict(name=label, used=round(pools[key]['used'], 2), peak=round(pools[key]['peak'], 2),
                                  cap=round(cap / mb, 1) if cap else None,
                                  pct=round(100.0 * pools[key]['peak'] * mb / cap) if cap else None))
    counts = {}
    for b in blocks:
        counts[b] = counts.get(b, 0) + 1
    # a block file that was read and never reported as in memory afterwards was still loading when the log ended
    loading = last_read if last_read_idx > last_block_idx and last_read else None
    return dict(lines=len(lines), zips=zips, blocks=[dict(name=k, times=v) for k, v in counts.items()], blocks_loaded=len(blocks),
                reads=len(reads), pools=pool_rows, problems=sorted(problems.values(), key=lambda e: -e['count'])[:max_problems],
                problem_count=sum(e['count'] for e in problems.values()), last_read=last_read, loading=loading,
                slowest=sorted(loads, key=lambda t: -t[1])[:3])


def exit_text(code):
    if code is None:
        return 'the game closed and did not report why'
    if code == 0:
        return None
    return EXIT_NAMES.get(code & 0xFFFFFFFF) or EXIT_NAMES.get(code) or 'the game stopped with code %d' % code


def crash_report(code, text, tail=30):
    """Abnormal exit -> what was loading last. None for a normal exit."""
    why = exit_text(code)
    if why is None:
        return None
    s = summarize(text)
    lines = [ln for ln in text.splitlines() if ln.strip()][-tail:]
    return dict(code=code, why=why, loading=s['loading'], last_read=s['last_read'], last_block=(s['blocks'][-1]['name'] if s['blocks'] else None),
                tail=lines)
