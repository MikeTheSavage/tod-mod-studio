"""limtool.py - raise two Total Overdose engine limits on the ORIGINAL GOG TOD.exe: the number of live placed cars (A)
and the number of loco-move / power-up slots (B), and migrate saves to edited blocks.
docs/subsystem_vehicle_and_loco_limits.md has the findings; this tool builds and checks the packages.

  python limtool.py sites                                   check every proxy site in TOD.exe (bytes, no branch into
                                                            a patched range) and the built proxy's hook stubs
  python limtool.py cars  --shells 10 [--max-live 9] [--lot] --out DIR
        A: clone vehicle_root shells in overdose.main DefaultVehicleResources (pool 5 -> N), limits.ini
           car_max_allocated (code constant 4 -> N-1); --lot adds the 8-car test lot in SUBMAP03 Map02 (block 3)
  python limtool.py loco  [--timestop-max 2] [--timestop-start 1] [--award6-timestop] [--slots 16] --out DIR
        B1: Time Stop unlocked (limits.ini timestop_max / _start; --award6-timestop: the 6-kill combo award gives
            Time Stop instead of the Golden Gun, a set record, no new entity)
        B2: --slots N: common.POWER_UP_TYPES_MAX_NUM 12 -> N (set record on Overdose.scene common(Node)), N-12 more
            HUD power-up sprite groups (HUDAuxCtrl), limits.ini slots16 = 1 with maxima / start counts / icons
  python limtool.py migrate SLOT OUT --pkg DIR [--move x,y,z,yaw] [--slot-counts 12=1,13=1] [--timestop 2,1]
        rewrites a save for the package's edited blocks: node indices (creation order) of every record, Entity values,
        thread / raw words that hold node ids and the header folder ids; with a B2 package also extends the power-up
        lists to N and drops the records the init rebuilds (POWERUP_SPRITE_LIST, HUD SpriteList / DescriptionList)
  python limtool.py selftest
Python 3.12, the project's fragment writer (tools/fragment_writer) and save editor (tools/save_editor); capstone for
'sites' (PYTHONPATH with capstone). Read only on the game install.
"""
import argparse, copy, hashlib, json, os, re, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.environ.get('TOD_PROJECT', os.path.dirname(os.path.dirname(HERE)))
FW = os.path.join(PROJ, 'tools', 'fragment_writer')
SAVE = os.path.join(PROJ, 'tools', 'save_editor')
EXE = os.environ.get('TOD_EXE', r'C:/GOG Games/Total Overdose/TOD.exe')
EXE_MD5 = 'd9beb351b3c78ee9f14a766a368f3ff9'
LAB = os.environ.get('LIMITS_LAB', os.path.join(HERE, 'lab'))
PROXY_DLL = os.environ.get('LIMITS_PROXY', os.path.join(HERE, 'proxy', 'dinput8.dll'))
if not os.path.exists(PROXY_DLL):
    PROXY_DLL = os.path.join(LAB, 'proxy', 'dinput8.dll')
sys.dont_write_bytecode = True

# fragment writer first (it binds its own todblock / pe), then the save editor with its own copies
sys.path.insert(0, FW)
import fragtool as ft      # noqa: E402
import fragedit as fe      # noqa: E402
import todfrag as tf       # noqa: E402
FW_TB = sys.modules['todblock']
for m in ('todblock', 'pe'):
    sys.modules.pop(m, None)
sys.path.insert(0, SAVE)
import savefile            # noqa: E402
import nodemap             # noqa: E402
sys.path.remove(SAVE)

MAIN = 'data_pc/overdose_the_game/overdose/shared/overdose.main'
SM03 = 'data_pc/overdose_the_game/overdose/shared/submap03_map02_lostoros_downtown.submap'
PY = sys.executable

# ------------------------------------------------------------------ exe sites (VA, shipped bytes, what)
SITES = [
    (0x7635C5, 'c7471804000000', 'A car_max_allocated: vehicle resource sub-ctrl (ResourcesToCollect 1) MaxAllocated = 4'),
    (0x7635B3, 'c7471805000000', 'A traffic_max_allocated: traffic sub-ctrl (ResourcesToCollect 9) MaxAllocated = 5'),
    (0x5BD4CB, 'c744241807000000895c241c', 'B1 timestop_max: inventory init MaxPowerUpList[7] = 0 (ebx)'),
    (0x5BD7E0, 'c744241807000000895c241c', 'B1 timestop_start: inventory init PowerUpList[7] = 0 (ebx)'),
    (0x5BD92C, '8b47148b08', 'B2 hook H1: inventory init tail (mov eax,[edi+14h]; mov ecx,[eax])'),
    (0x5BC7D0, '8b0d5cb7a300', 'B2 guard G1: command_has_this_powerup entry (mov ecx,[0A3B75Ch])'),
    (0x5BCBA0, 'a190b5a300', 'B2 guard G2: selection scan up entry (mov eax,[0A3B590h])'),
    (0x5BCCA0, '538b1d5cb7a300', 'B2 guard G3: selection scan down entry (push ebx; mov ebx,[0A3B75Ch])'),
]
# functions that contain the sites (start, size from the decompile's funcs.tsv) for the branch-target check
SITE_FUNCS = {0x7635C5: (0x763440, 691), 0x7635B3: (0x763440, 691), 0x5BD4CB: (0x5BD1E0, 1953),
              0x5BD7E0: (0x5BD1E0, 1953), 0x5BD92C: (0x5BD1E0, 1953), 0x5BC7D0: (0x5BC7D0, 68),
              0x5BCBA0: (0x5BCBA0, 242), 0x5BCCA0: (0x5BCCA0, 225)}
STUBS = {0x5BD931: ['mov eax, dword ptr [edi + 0x14]', 'mov ecx, dword ptr [eax]'],
         0x5BC7D6: ['mov ecx, dword ptr [0xa3b75c]'], 0x5BCBA5: ['mov eax, dword ptr [0xa3b590]'],
         0x5BCCA7: ['push ebx', 'mov ebx, dword ptr [0xa3b75c]']}


def pe_sections(d):
    e = struct.unpack_from('<I', d, 0x3c)[0]; ns = struct.unpack_from('<H', d, e + 6)[0]
    osz = struct.unpack_from('<H', d, e + 20)[0]; base = struct.unpack_from('<I', d, e + 52)[0]
    out = []; o = e + 24 + osz
    for _ in range(ns):
        vs, va, rs, raw = struct.unpack_from('<IIII', d, o + 8)
        out.append((d[o:o + 8].rstrip(b'\0').decode(), base + va, vs, raw, rs)); o += 40
    return out


def va_bytes(d, secs, va, n):
    for nm, sva, vs, raw, rs in secs:
        if sva <= va < sva + rs:
            return d[raw + va - sva: raw + va - sva + n]
    raise KeyError(hex(va))


def check_sites(verbose=True):
    d = open(EXE, 'rb').read()
    md5 = hashlib.md5(d).hexdigest()
    secs = pe_sections(d)
    rep = dict(exe=EXE, md5=md5, md5_ok=md5 == EXE_MD5, sites=[])
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
        md = Cs(CS_ARCH_X86, CS_MODE_32)
    except ImportError:
        md = None
    ok = rep['md5_ok']
    for va, hexb, what in SITES:
        b = va_bytes(d, secs, va, len(hexb) // 2)
        s = dict(va='0x%06X' % va, bytes=b.hex(), shipped=b.hex() == hexb, what=what)
        if md:
            f0, fn = SITE_FUNCS[va]
            ins = list(md.disasm(va_bytes(d, secs, f0, fn), f0))
            starts = {i.address for i in ins}
            end = va + len(hexb) // 2
            s['instruction_aligned'] = va in starts and (end in starts or end >= f0 + fn)
            into = []
            for i in ins:
                if i.mnemonic.startswith('j') or i.mnemonic == 'call':
                    m = re.fullmatch(r'0x([0-9a-f]+)', i.op_str)
                    if m and va < int(m.group(1), 16) < end:
                        into.append('0x%X' % i.address)
            s['branches_into_patched_range'] = into
            ok = ok and s['instruction_aligned'] and not into
        ok = ok and s['shipped']
        rep['sites'].append(s)
    rep['proxy'] = check_proxy(md)
    ok = ok and rep['proxy'].get('ok', False)
    rep['ok'] = ok
    if verbose:
        print(json.dumps(rep, indent=1))
    return rep


def check_proxy(md):
    if not os.path.exists(PROXY_DLL):
        return dict(ok=False, why='no proxy dll at %s' % PROXY_DLL)
    if md is None:
        return dict(ok=False, why='capstone not importable')
    d = open(PROXY_DLL, 'rb').read()
    secs = pe_sections(d)
    text = [s for s in secs if s[0] == '.text'][0]
    code = d[text[3]:text[3] + text[4]]
    found = {}
    for m in re.finditer(rb'\x60\x9c', code):                        # pushad ; pushfd
        ins = list(md.disasm(code[m.start():m.start() + 64], text[1] + m.start()))
        txt = ['%s %s' % (i.mnemonic, i.op_str.replace('ds:', '')) for i in ins]
        pf = [k for k, t in enumerate(txt) if t.startswith('popfd')]
        if not pf or not txt[pf[0] + 1].startswith('popal'):
            continue
        body = txt[pf[0] + 2:]
        j = [k for k, t in enumerate(body) if t.startswith('jmp')]
        if not j:
            continue
        mm = re.search(r'\[(0x[0-9a-f]+)\]', body[j[0]])
        back = struct.unpack('<I', va_bytes(d, secs, int(mm.group(1), 16), 4))[0] if mm else None
        found[back] = [t.strip() for t in body[:j[0]]]
    res = {}
    ok = True
    for back, want in STUBS.items():
        got = found.get(back)
        res['0x%X' % back] = dict(stolen=got, expected=want, ok=got == want)
        ok = ok and got == want
    return dict(ok=ok, dll=PROXY_DLL, sha256=hashlib.sha256(d).hexdigest(), stubs=res)


# ------------------------------------------------------------------ fragment edits
def build_blocks(ops_by_block, base=None):
    """ops_by_block: {entry: [ops]} -> {entry: (new bytes, verification report)} (fragment writer verify_block)."""
    T = ft.types()
    out = {}
    for e, ops in ops_by_block.items():
        raw = (base or {}).get(e) or ft.archive().read(ft.resolve_entry(e))
        ext = os.path.splitext(e)[1]
        r0 = ft.roundtrip_block(raw, ext, T)
        if r0['fail'] or not r0['block_identical']:
            raise RuntimeError('base block %s does not round-trip' % e)
        old, nb, docs, intended = ft.apply_ops(raw, ext, ops, T)
        newb = nb.serialize()
        vrep, _ = ft.verify_block(old, newb, ext, docs, intended, T)
        out[e] = (newb, vrep, raw)
    return out


def frags_of(raw, ext):
    b = FW_TB.Block(raw, ext)
    info = bytes(b.info)
    st = FW_TB.record_starts(info, b.n)
    fr = {}
    for i, R in enumerate(st):
        nm = FW_TB.record_name(info, R)
        if nm.lower().endswith('.fragment') or nm.lower().endswith('.scene'):
            fr[nm] = b.payloads[i]
    return fr


def node_list(frags, root, start, fallback=None):
    return nodemap.build(frags, root, start, fallback=fallback)


def extras(typestr):
    return nodemap.EXTRA_NODES.get(nodemap._cls(typestr), 0)


def index_map(old_nodes, new_nodes):
    """old runtime index -> new runtime index for one block (static nodes by identity, hidden children, runtime tail)."""
    key = lambda n: (n[2], n[3], n[5])
    newk = {}
    for n in new_nodes:
        newk.setdefault(key(n), n)
    m = {}
    for n in old_nodes:
        nn = newk.get(key(n))
        if nn is None:
            raise RuntimeError('node %s %s %s of the shipped block not found in the edited block' % (hex(n[0]), n[1], n[2]))
        for j in range(extras(n[1]) + 1):
            m[n[0] + j] = nn[0] + j
    old_end = old_nodes[-1][0] + extras(old_nodes[-1][1]) + 1
    new_end = new_nodes[-1][0] + extras(new_nodes[-1][1]) + 1
    added = len(new_nodes) - len(old_nodes)
    return m, old_end, new_end, added


def block_summary(entry, old_raw, new_raw):
    ext = os.path.splitext(entry)[1]
    of, nf = frags_of(old_raw, ext), frags_of(new_raw, ext)
    if entry == MAIN:
        on = node_list(of, savefile.MAIN_SCENE, 5); nn = node_list(nf, savefile.MAIN_SCENE, 5)
    else:
        mf = savefile.block_frags(MAIN)
        root = [x for x in of if x.split('/')[-1].lower() == os.path.basename(entry).rsplit('.', 1)[0].lower() + '.fragment']
        on = node_list(of, root[0], 1, [mf]); nn = node_list(nf, root[0], 1, [mf])
    m, oe, ne, added = index_map(on, nn)
    first = min([o for o, n in m.items() if o != n] or [None]) if any(o != n for o, n in m.items()) else None
    return dict(entry=entry, nodes_old=len(on), nodes_new=len(nn), static_end_old='0x%X' % oe, static_end_new='0x%X' % ne,
                first_shifted_index=('0x%X' % first) if first is not None else None, shift_after=ne - oe)


def write_package(outdir, blocks, ini, meta):
    os.makedirs(outdir, exist_ok=True)
    outs = []
    meta['blocks'] = []
    for e, (nb, vrep, raw) in blocks.items():
        open(os.path.join(outdir, os.path.basename(e)), 'wb').write(nb)
        outs.append((e, nb))
        s = block_summary(e, raw, nb)
        s.update(base_sha256=hashlib.sha256(raw).hexdigest(), out_sha256=hashlib.sha256(nb).hexdigest(), bytes=len(nb),
                 verify={k: v for k, v in vrep.items() if k != '4_edited_fragments'},
                 edited_fragments=[dict(fragment=f['fragment'], new_entities=f['new_entities'],
                                        changed_props=f['changed_props'], independent_reader=f['independent_reader'],
                                        dangling_refs=f['dangling_refs']) for f in vrep['4_edited_fragments']])
        meta['blocks'].append(s)
    if outs:
        meta['zip'] = ft.write_zip(os.path.join(outdir, ft.ZIP_NAME), outs)
        meta['configpc_line'] = 'filesystem = ' + ', '.join([ft.ZIP_NAME] + ft.BASE_ARCHIVES)
    if ini:
        open(os.path.join(outdir, 'limits.ini'), 'w', newline='\r\n').write(ini)
    if os.path.exists(PROXY_DLL):
        shutil.copyfile(PROXY_DLL, os.path.join(outdir, 'dinput8.dll'))
        meta['proxy_sha256'] = hashlib.sha256(open(PROXY_DLL, 'rb').read()).hexdigest()
    json.dump(meta, open(os.path.join(outdir, 'package.json'), 'w'), indent=1, default=str)
    return meta


def readback(entry, raw, frag, sel, props):
    """Fresh parse of a built block: props of one entity (decoded)."""
    T = ft.types()
    b = FW_TB.Block(raw, os.path.splitext(entry)[1])
    frs, _ = ft.fragments(b)
    k, nm = ft.pick_fragment(frs, frag)
    d = fe.FragDoc(b.payloads[k], T, nm)
    n = d.find(sel)
    return {p: d.get(n, p) for p in props}


def count_type(entry, raw, frag, typestr):
    T = ft.types()
    b = FW_TB.Block(raw, os.path.splitext(entry)[1])
    frs, _ = ft.fragments(b)
    k, nm = ft.pick_fragment(frs, frag)
    fr = tf.Fragment(b.payloads[k], T)
    return sum(1 for r in fr.records if r.op == tf.CREATE and tf.decode_value(r.raw, 0, ('string',)).startswith(typestr))


# ------------------------------------------------------------------ A: cars
LOT_Z = [157.0, 164.0, 171.0, 178.0]
def lane_y(z):   # SUBMAP03 Map02 traffic points (world): z 97.66 y 13.4, 160.21 y 18.51, 176.35 y 19.31, 212.91 y 19.48
    pts = [(97.66, 13.4), (160.21, 18.51), (176.35, 19.31), (212.91, 19.48)]
    for (z0, y0), (z1, y1) in zip(pts, pts[1:]):
        if z0 <= z <= z1:
            return y0 + (y1 - y0) * (z - z0) / (z1 - z0)
    return pts[-1][1]
# 8 parked-car sources of SUBMAP03_Map02_Traffic (model / type pairs as shipped): Sedan, StationWagon, Conquistador,
# VanHeavy, 4x4Pickup, ElCamino, VanUrban, Sedan
LOT_SOURCES = ['0x00300397', '0x00300399', '0x0030039B', '0x0030039D', '0x0030039F', '0x003003A1', '0x00300395', '0x00300397']


def lot_ops():
    ops = []
    k = 0
    for col, (x, dy) in enumerate([(403.1, 1.46), (397.8, 1.30)]):     # east curb row (like the shipped wagon) and lane
        for z in LOT_Z:
            ops.append(dict(op='clone', fragment='SUBMAP03_Map02_Traffic', entity=LOT_SOURCES[k], deep=True,
                            name='LimitsTest_Car_%d' % (k + 1), pos=[x, round(lane_y(z) + dy, 2), z],
                            orient=[0.0, 0.0, 0.0, 1.0], space='local'))
            k += 1
    return ops


def cmd_cars(a):
    if a.shells < 5 or a.shells > 40:
        raise SystemExit('--shells 5..40')
    live = a.max_live if a.max_live is not None else a.shells - 1
    ops = {MAIN: [dict(op='clone', fragment='DefaultVehicleResources.fragment', entity='Vehicle05', deep=True,
                       name='Vehicle%02d' % i) for i in range(6, a.shells + 1)]}
    if a.lot:
        ops[SM03] = lot_ops()
    if not ops[MAIN]:
        del ops[MAIN]
    blocks = build_blocks(ops)
    meta = dict(kind='A', shells=a.shells, car_max_allocated=live, lot=bool(a.lot), ops=ops)
    if MAIN in blocks:
        nb = blocks[MAIN][0]
        meta['readback_vehicle_root_resources'] = count_type(MAIN, nb, 'DefaultVehicleResources.fragment', 'vehicle_root')
        meta['readback_last_shell'] = readback(MAIN, nb, 'DefaultVehicleResources.fragment', 'Vehicle%02d' % a.shells,
                                               ['IsResource', 'fragment', 'Sub_Type', 'name'])
        if meta['readback_vehicle_root_resources'] != a.shells:
            raise RuntimeError('read-back shells %d != %d' % (meta['readback_vehicle_root_resources'], a.shells))
    if SM03 in blocks:
        nb = blocks[SM03][0]
        meta['readback_lot'] = [readback(SM03, nb, 'SUBMAP03_Map02_Traffic', 'Parked Vehicles/Civil cars/LimitsTest_Car_%d' % i,
                                         ['VehicleSubType', 'pos', 'name']) for i in range(1, 9)]
    ini = ('# limits proxy (tools/limits/proxy): placed cars that can be live at once (vanilla 4, code 0x7635C5)\n'
           'car_max_allocated = %d\nlog_state = 1\nlog_interval_ms = 500\n' % live)
    meta = write_package(a.out, blocks, ini, meta)
    print(json.dumps({k: v for k, v in meta.items() if k != 'ops'}, indent=1, default=str))


# ------------------------------------------------------------------ B: loco slots
HUD_LIST = 'On_Foot_HUD/PowerUp_Bar/PowerUp_Sprite_List/'


def cmd_loco(a):
    ops = []
    ini = ['# limits proxy (tools/limits/proxy): power-up slots']
    meta = dict(kind='B', timestop_max=a.timestop_max, timestop_start=a.timestop_start, slots=a.slots,
                award6_timestop=a.award6_timestop)
    if a.timestop_max is not None:
        ini.append('timestop_max = %d' % a.timestop_max)
    if a.timestop_start is not None:
        ini.append('timestop_start = %d' % a.timestop_start)
    if a.award6_timestop:
        ops.append(dict(op='set', fragment='ComboAwardDict.fragment', entity='0x00101F7F', prop='Specific_ID', value=13))
    if a.slots and a.slots != 12:
        if a.slots < 13 or a.slots > 24:
            raise SystemExit('--slots 13..24')
        ops.append(dict(op='set', fragment='Overdose.scene', entity='0x0010000C', prop='POWER_UP_TYPES_MAX_NUM',
                        value=a.slots))
        for g in range(11, a.slots - 1):          # HUD groups: 10 shipped = slots 2..11; one more per new slot
            for src, nm in (('PowerUp_Sprite_10', 'PowerUp_Sprite_%02d'), ('PowerUp_Sprite_BG_10', 'PowerUp_Sprite_BG_%02d'),
                            ('PowerUp_10_Num_TB', 'PowerUp_%02d_Num_TB'), ('PowerUp_10_Num_TB_BG', 'PowerUp_%02d_Num_TB_BG')):
                ops.append(dict(op='clone', fragment='HUDAuxCtrl.fragment', entity=HUD_LIST + src, deep=True, name=nm % g))
        icons = {12: 2, 13: 3, 14: 4, 15: 9}
        ini += ['slots16 = 1'] + ['slot_max_%d = 2\nslot_start_%d = %d\nslot_icon_%d = %d' %
                                  (k, k, a.slot_start, k, icons.get(k, 11)) for k in range(12, a.slots)]
    ini += ['log_state = 1', 'log_interval_ms = 500']
    blocks = build_blocks({MAIN: ops}) if ops else {}
    meta['ops'] = ops
    if MAIN in blocks:
        nb = blocks[MAIN][0]
        if a.slots and a.slots != 12:
            meta['readback_common'] = readback(MAIN, nb, 'Overdose.scene', '0x0010000C', ['POWER_UP_TYPES_MAX_NUM'])
            assert meta['readback_common']['POWER_UP_TYPES_MAX_NUM'] == a.slots
            meta['readback_hud_sprites'] = count_type(MAIN, nb, 'HUDAuxCtrl.fragment', 'Sprite') - \
                count_type(MAIN, blocks[MAIN][2], 'HUDAuxCtrl.fragment', 'Sprite')
        if a.award6_timestop:
            meta['readback_award'] = readback(MAIN, nb, 'ComboAwardDict.fragment', '0x00101F7F', ['Specific_ID', 'name'])
            assert meta['readback_award']['Specific_ID'] == 13
    meta = write_package(a.out, blocks, '\n'.join(ini) + '\n', meta)
    print(json.dumps({k: v for k, v in meta.items() if k != 'ops'}, indent=1, default=str))


# ------------------------------------------------------------------ save migration
ENT = re.compile(r'^E([0-9a-f]{6})$')


def remap_value(v, f):
    if isinstance(v, str):
        m = ENT.match(v)
        return ('E%06x' % f(int(m.group(1), 16))) if m else v
    if isinstance(v, list):
        return [remap_value(x, f) for x in v]
    if isinstance(v, dict):
        return {k: remap_value(x, f) for k, x in v.items()}
    return v


def migrate_json(j, pkg_blocks, n_slots=None, slot_counts=None, slot_max=2, timestop=None):
    """j = savefile.decode() of the shipped-block save; pkg_blocks = {entry: new bytes}. Returns (j2, report)."""
    folders = [f['id'] if isinstance(f, dict) else f for f in j['header']['folders']]
    w = savefile.World(folders)
    maps = {}
    rep = dict(blocks={}, records=len(j['records']))
    main_new = frags_of(pkg_blocks[MAIN], '.main') if MAIN in pkg_blocks else None
    for blk, entry in w.blocks.items():
        if entry not in pkg_blocks:
            continue
        ext = os.path.splitext(entry)[1]
        nf = frags_of(pkg_blocks[entry], ext)
        old = sorted(w.maps[blk].values())
        if blk == 1:
            new = node_list(nf, savefile.MAIN_SCENE, 5)
        else:
            root = old[0][2]
            new = node_list(nf, root, 1, [main_new or w.main_frags])
        m, oe, ne, added = index_map(old, new)
        maps[blk] = (m, oe, ne)
        rep['blocks'][blk] = dict(entry=entry, static_end_old=hex(oe), static_end_new=hex(ne), added_nodes=added,
                                  moved=sum(1 for o, n in m.items() if o != n))
    if not maps:
        rep['note'] = 'the save has none of the package blocks loaded: indices unchanged'

    def f(v):   # (block<<20)|index -> remapped
        blk, idx = v >> 20, v & 0xFFFFF
        if blk not in maps:
            return v
        m, oe, ne = maps[blk]
        if idx in m:
            return (blk << 20) | m[idx]
        if idx >= oe:
            return (blk << 20) | (idx + ne - oe)
        return v
    stats = dict(keys=0, entity_values=0, raw_words=0, folders=0, dropped=[], lists=[])
    recs = []
    for r in j['records']:
        r = copy.deepcopy(r)
        if 'junk' in r:
            recs.append(r); continue
        blk, idx = savefile.parse_key(r['n'])
        nk = f((blk << 20) | idx)
        if nk != ((blk << 20) | idx):
            stats['keys'] += 1
        r['n'] = savefile.node_key(blk, nk & 0xFFFFF)
        if 'raw' in r:
            raw2 = []
            for x in r['raw']:
                v = int(x, 16)
                if 1 <= (v >> 20) <= 6 and v < 0x700000 and (v & 0xFFFFF):
                    nv = f(v)
                    if nv != v:
                        stats['raw_words'] += 1
                    v = nv
                raw2.append('%08x' % v)
            r['raw'] = raw2
        elif 'v' in r and ('ntity' in r['t'] or 's_' in r['t']):
            nv = remap_value(r['v'], f)
            if nv != r['v']:
                stats['entity_values'] += 1
            r['v'] = nv
        recs.append(r)
    j2 = copy.deepcopy(j)
    j2['records'] = recs
    for fo in j2['header']['folders']:
        fid = fo['id'] if isinstance(fo, dict) else fo
        if fid is not None and fid > 0:
            nf_ = f(fid)
            if nf_ != fid:
                stats['folders'] += 1
                if isinstance(fo, dict):
                    fo['id'] = nf_
    # power-up inventory for more slots (B2) and Time Stop (B1)
    if n_slots or timestop:
        keep = []
        for r in j2['records']:
            nm = r.get('name')
            if n_slots and nm in ('POWERUP_SPRITE_LIST', 'SpriteList', 'DescriptionList') and \
                    (nm != 'SpriteList' or r.get('t') == 'list(s_PowerUpSprite)'):
                stats['dropped'].append('%s.%s' % (r['n'], nm)); continue
            if nm == 'PowerUpInventory':
                v = r['v']
                if n_slots:
                    for fld in ('PowerUpList', 'MaxPowerUpList'):
                        v[fld] = v[fld] + [0] * max(0, n_slots - len(v[fld]))
                    for k in range(12, n_slots):
                        if v['MaxPowerUpList'][k] == 0:
                            v['MaxPowerUpList'][k] = slot_max
                        if slot_counts and k in slot_counts:
                            v['PowerUpList'][k] = min(slot_counts[k], v['MaxPowerUpList'][k])
                if timestop:
                    v['MaxPowerUpList'][7] = timestop[0]
                    v['PowerUpList'][7] = min(timestop[1], timestop[0])
                stats['lists'].append(dict(PowerUpList=v['PowerUpList'], MaxPowerUpList=v['MaxPowerUpList']))
            if n_slots and nm == 'PowerUpSaveList' and len(r['v']) < n_slots:
                r['v'] = r['v'] + [0] * (n_slots - len(r['v']))
            keep.append(r)
        j2['records'] = keep
    rep['remapped'] = stats
    return j2, rep, maps


def verify_migrated(out_bytes, pkg_blocks, j_old, j_new):
    """Decode the migrated save against the EDITED blocks: no parse problem, and every record keeps its property
    name and type (so each record reaches the same entity it addressed before)."""
    saved = dict(savefile._BLOCKS); saved_main = savefile.World._main
    try:
        for e, b in pkg_blocks.items():
            savefile._BLOCKS[e] = frags_of(b, os.path.splitext(e)[1])
        savefile.World._main = None
        j3 = savefile.decode(out_bytes)
    finally:
        savefile._BLOCKS.clear(); savefile._BLOCKS.update(saved); savefile.World._main = saved_main
    probs = j3['parse_problems']
    a = [(r.get('n'), r.get('p'), r.get('t')) for r in j_new['records']]
    b = [(r.get('n'), r.get('p'), r.get('t')) for r in j3['records']]
    same_types = a == b
    old_types = [(r.get('p'), r.get('t'), r.get('name')) for r in j_new['records']]
    new_types = [(r.get('p'), r.get('t'), r.get('name')) for r in j3['records']]
    names_ok = old_types == new_types
    rt = savefile.encode(j3) == out_bytes
    return dict(parse_problems=len(probs), records=len(j3['records']), keys_types_equal=same_types,
                prop_names_types_equal=names_ok, reencode_identical=rt,
                ok=not probs and same_types and names_ok and rt)


def cmd_migrate(a):
    pkg = json.load(open(os.path.join(a.pkg, 'package.json')))
    pkg_blocks = {}
    for bl in pkg.get('blocks', []):
        pkg_blocks[bl['entry']] = open(os.path.join(a.pkg, os.path.basename(bl['entry'])), 'rb').read()
    src = a.slot
    tmp = None
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if a.move:      # position edit on the shipped-index save first (the save editor types records with shipped blocks)
        tmp = a.out + '.premove'
        r = subprocess.run([PY, '-B', os.path.join(SAVE, 'tod_save.py'), 'edit', src, tmp, '--move', a.move],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stdout + r.stderr)
        src = tmp
    j = savefile.decode(open(src, 'rb').read())
    n_slots = pkg.get('slots') if pkg.get('slots') and pkg.get('slots') != 12 else None
    counts = {int(k): int(v) for k, v in (x.split('=') for x in a.slot_counts.split(','))} if a.slot_counts else None
    ts = tuple(int(x) for x in a.timestop.split(',')) if a.timestop else None
    j2, rep, maps = migrate_json(j, pkg_blocks, n_slots, counts, 2, ts)
    out = savefile.encode(j2)
    rep['verify'] = verify_migrated(out, pkg_blocks, j, j2)
    if not rep['verify']['ok']:
        raise SystemExit('migration check failed: %s' % json.dumps(rep['verify']))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, 'wb').write(out)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
    rep['out'] = a.out; rep['sha256'] = hashlib.sha256(out).hexdigest()
    rep['remapped']['lists'] = rep['remapped']['lists'][:1]
    json.dump(rep, open(a.out + '.migrate.json', 'w'), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))


# ------------------------------------------------------------------ selftest
def cmd_selftest(a):
    res = {}
    s = check_sites(verbose=False)
    res['1_sites_and_proxy'] = dict(ok=s['ok'], md5_ok=s['md5_ok'], proxy=s['proxy'].get('ok'),
                                    sites=[(x['va'], x['shipped'], x.get('instruction_aligned'),
                                            x.get('branches_into_patched_range')) for x in s['sites']])
    tmp = os.path.join(LAB, 'selftest')
    # 2: an edit with zero ops writes nothing; 3: A and B packages build + verify + read back
    class NS: pass
    A = NS(); A.shells = 10; A.max_live = None; A.lot = True; A.out = os.path.join(tmp, 'A')
    B = NS(); B.timestop_max = 2; B.timestop_start = 1; B.award6_timestop = True; B.slots = 16; B.slot_start = 1
    B.out = os.path.join(tmp, 'B')
    import io, contextlib
    for nm, fn, arg in (('2_cars_package', cmd_cars, A), ('3_loco_package', cmd_loco, B)):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fn(arg)
            pk = json.load(open(os.path.join(arg.out, 'package.json')))
            res[nm] = dict(ok=True, blocks=[(b['entry'].split('/')[-1], b['nodes_old'], b['nodes_new'],
                                             b['first_shifted_index']) for b in pk['blocks']])
        except Exception as e:
            res[nm] = dict(ok=False, error=repr(e))
    # 4: save migration round trip on every user save copy that loads a package block
    saves = os.environ.get('LIMITS_SAVES', '')
    mig = []
    for pkgdir in (A.out, B.out):
        pk = json.load(open(os.path.join(pkgdir, 'package.json')))
        blocks = {b['entry']: open(os.path.join(pkgdir, os.path.basename(b['entry'])), 'rb').read() for b in pk['blocks']}
        for sl in sorted(os.listdir(saves)) if os.path.isdir(saves) else []:
            if not re.fullmatch(r'Slot\d\d', sl) or sl == 'Slot11' or os.path.getsize(os.path.join(saves, sl)) != 0x50000:
                continue
            p = os.path.join(saves, sl)
            try:
                j = savefile.decode(open(p, 'rb').read())
                j2, rep, maps = migrate_json(j, blocks, pk.get('slots') if pk.get('slots') not in (None, 12) else None,
                                             {12: 1, 13: 1} if pk.get('slots') else None, 2,
                                             (2, 1) if pk.get('kind') == 'B' else None)
                out = savefile.encode(j2)
                v = verify_migrated(out, blocks, j, j2)
                mig.append((os.path.basename(pkgdir), sl, v['ok'], rep['remapped']['keys'], rep['remapped']['entity_values'],
                            rep['remapped']['raw_words'], rep['remapped']['folders'], len(rep['remapped']['dropped'])))
            except Exception as e:
                mig.append((os.path.basename(pkgdir), sl, False, repr(e)))
    res['4_save_migration'] = mig
    ok = res['1_sites_and_proxy']['ok'] and res['2_cars_package']['ok'] and res['3_loco_package']['ok'] and \
        all(m[2] for m in mig) and len(mig) > 0
    res['result'] = 'PASS' if ok else 'FAIL'
    print(json.dumps(res, indent=1, default=str))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('sites')
    c = sp.add_parser('cars'); c.add_argument('--shells', type=int, default=10); c.add_argument('--max-live', type=int)
    c.add_argument('--lot', action='store_true'); c.add_argument('--out', required=True)
    l = sp.add_parser('loco'); l.add_argument('--timestop-max', type=int); l.add_argument('--timestop-start', type=int)
    l.add_argument('--award6-timestop', action='store_true'); l.add_argument('--slots', type=int, default=12)
    l.add_argument('--slot-start', type=int, default=1); l.add_argument('--out', required=True)
    m = sp.add_parser('migrate'); m.add_argument('slot'); m.add_argument('out'); m.add_argument('--pkg', required=True)
    m.add_argument('--move'); m.add_argument('--slot-counts'); m.add_argument('--timestop')
    sp.add_parser('selftest')
    a = ap.parse_args()
    try:
        import lowprio  # noqa: F401  (below-normal priority on Windows; from the fragment writer)
    except ImportError:
        pass
    if a.cmd == 'sites':
        sys.exit(0 if check_sites()['ok'] else 1)
    if a.cmd == 'cars':
        cmd_cars(a)
    elif a.cmd == 'loco':
        cmd_loco(a)
    elif a.cmd == 'migrate':
        cmd_migrate(a)
    elif a.cmd == 'selftest':
        sys.exit(0 if cmd_selftest(a) else 1)


if __name__ == '__main__':
    main()
