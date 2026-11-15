"""Template 'destroy': blow up three burrito stands, collect the dope packs they drop, bring them to a delivery zone. (Mesa index 75.)

Template: registry slot 31 = SubM_02_Down_BuyBur_Steal. The three stands are DEEP CLONES of the Downtown submap's Buritto_Cart0N_sm08 folders (Destroyable_Object +
wreck + conditions) grafted into the mission block and moved to your stand positions; the dope pack model + ground marker are copies placed behind each stand;
pickup zones at the packs; delivery zone = a strip you choose. Five of the 25 enemies guard the stands (pistols), the rest are parked in disabled folders.
"""
import sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'destroy'
TITLE = 'Destroy & Collect'
SUMMARY = 'Blow up three stands, pick up the packs they drop and deliver them to a zone. Five guards defend the stands.'
HOST_NEEDS = ['Three free spots for the stands (3 m clearance, the packs lie 3.5 m behind) with guards standing 6-10 m from each.',
              'A delivery zone and a free spot for a pickup; a parking strip for leftovers.',
              'Needs the Downtown submap data blocks (burrito stand model, pack model) installed: they are copied into the mission block.',
              'Works in any new map or existing section with flat ground.']
LEGACY_INDEX = 75
LEGACY_ROOT = 'SubM_75_Mesa_DestroyDope1.fragment'
GIVER_NAME = 'MESA_GIVER_DESTROY'
COMMON = dict(giver=(24.0, 0.0, 8.0), name='DESTROY & COLLECT',
              description='Dealers have set up burrito stands inside the compound. Blow them up, pick up the dope packs they drop and bring them to the gate.',
              pass_score=400, silver_score=800, gold_score=1200)

SUBMAP = 'data_pc/overdose_the_game/overdose/shared/submap02_map02_lostoros_downtown.submap'
SUBFRAG = 'SUBMAP02_Map02_Roaming_GamePlay_Objects.fragment'
CART_FOLDERS = {1: 0x300AA4, 2: 0x300AF4, 3: 0x300ACC}
COKE_NODES = {1: (0x300B1E, 0x300B1F), 2: (0x300B27, 0x300B28), 3: (0x300B32, 0x300B33)}
FIGHTERS = {0x400029: (0, (-9.0, -6.0)), 0x400059: (0, (-6.0, -3.0)), 0x400082: (1, (-9.0, -4.0)), 0x40009F: (2, (-10.0, 4.0)), 0x4000AF: (2, (-7.0, -3.0))}

PARAMS = [
    P('stands', 'points', lambda h, p: [h.pt(27, 10), h.pt(27, 27), h.pt(27, -9)], 'Stand positions', 'The three burrito stands (x, y, z). Guards stand 6-10 m to the west of each; the dope pack lies behind it.', min_len=3, max_len=3, group='Placement'),
    P('pack_offset', 'float', 3.5, 'Pack distance', 'How far behind its stand (towards +z) each dope pack lies.', min=1.5, max=10.0, unit='m', group='Placement', advanced=True),
    P('pack_zone_length', 'float', 8.0, 'Pickup zone length', 'North-south length of each pickup zone (width is 10 m).', min=3.0, max=30.0, unit='m', group='Placement', advanced=True),
    P('delivery_zone', 'point', lambda h, p: h.pt(0, -23), 'Delivery zone', 'Centre of the strip where the packs are delivered.', group='Placement'),
    P('delivery_width', 'float', 20.0, 'Delivery zone width', 'East-west size of the delivery zone.', min=4.0, max=80.0, unit='m', group='Placement'),
    P('delivery_length', 'float', 12.0, 'Delivery zone length', 'North-south size of the delivery zone.', min=3.0, max=60.0, unit='m', group='Placement'),
    P('weapon_pickup', 'point', lambda h, p: h.pt(9, -22), 'Weapon pickup', 'Where the template weapon pickup lies (next to the start).', group='Placement'),
    P('goodies', 'points', lambda h, p: [h.pt(14, 4), h.pt(-12, 20), h.pt(-26, -22), h.pt(0, 12), h.pt(30, -6), h.pt(-10, -14)], 'Health pickups', 'Up to six health pickups spread over the area.', max_len=6, group='Placement'),
    P('vehicle_park', 'point', lambda h, p: h.pt(30, 36), 'Vehicle parking', 'Where the template pick-up truck and its passengers are parked (disabled, never seen).', group='Placement', advanced=True),
    P('track_park', 'point', lambda h, p: h.pt(0, 30, None), 'Camera track parking', 'Where the leftover camera track points of the Downtown shots are parked (inert).', group='Placement', advanced=True),
    P('giver_npc_park', 'point', lambda h, p: h.pt(24, 8), 'Parked task giver', 'Where the template task-giver character is parked.', group='Placement', advanced=True),
    P('spare_region', 'rect', lambda h, p: list(h.rr(-38, 34, 38, 38.5)), 'Spare strip', 'Where the enemies that do not guard are parked (disabled).', group='Placement', advanced=True),
    P('enemy_health', 'float', 0.3, 'Guard health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.05, 'Guard damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('stand_health', 'float', 0.3, 'Stand health', 'How much damage a stand takes before it blows up (template 0.0 in the database; scripted runs have about 200 rounds).', min=0.0, max=10.0, group='Settings'),
    P('text_packs', 'text', 'Destroy the burrito stands and collect the dope packs', 'Objective 1 text', 'First objective line.', group='Texts', max_len=70),
    P('text_deliver', 'text', 'Bring the dope packs to the gate', 'Objective 2 text', 'Second objective line.', group='Texts', max_len=70),
]


def constraints(p, host):
    m = []
    s = p['stands']
    for i in range(3):
        for j in range(i + 1, 3):
            d = ((s[i][0] - s[j][0]) ** 2 + (s[i][2] - s[j][2]) ** 2) ** 0.5
            if d < 6.0:
                m.append(('warn', 'Stands %d and %d are only %.1f m apart: one explosion may take out both.' % (i + 1, j + 1, d)))
    if p['pass_score'] > 120:
        m.append(('info', 'Five guards pay about 10-19 points each; stands and packs add more. A pass score of %d should be checked.' % p['pass_score']))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx

    def design(ctx):
        E = _env()
        BE, lib_read = E.BE, E.read
        W = ctx.world
        L.install_assets(ctx, SUBMAP, ['/data/Models/Addons/BurritoStand/ADD_BurritoStand.model', '/data/Models/Addons/BurritoStand/ADD_BurritoStand_Static.model',
                                      '/data/Models/Addons/BurritoStand/ADD_BurritoStand_Static_Replace.model', '/data/Models/Addons/PackCoke/PackCokeLarge.model'])
        G = lambda x, z, y=None: host.gy(x, z, y)
        stands, packs, taken = [], [], []
        for st in p['stands']:
            sx, sz = W.snap(st[0], st[2], margin=3.0, taken=taken, min_sep=3.0)
            taken.append((sx, sz)); stands.append((sx, sz))
        for (sx, sz) in stands:
            px, pz = W.snap(sx, sz + p['pack_offset'], margin=1.5, taken=taken, min_sep=1.5)
            taken.append((px, pz)); packs.append((px, pz))
        ctx.log.append('stands %s packs %s' % (stands, packs))
        sbi = BE.BlockInfo(SUBMAP, lib_read(SUBMAP))
        sdoc = sbi.doc([nm for k, nm in sbi.frs if nm.split('/')[-1] == SUBFRAG][0])
        gameplay = ctx.one(name='SubM_02_Down_BuyBur_Steal_GAMEPLAY')
        parent = ('ref', ctx.new_root, gameplay[3])
        for i in (1, 2, 3):
            root = CART_FOLDERS[i]
            nodes = sdoc.subtree(root)
            cart = [n for n in nodes if sdoc.type_of(n) == 'Destroyable_Object(CollisionBox)'][0]
            old = [float(v) for v in sdoc.get(cart, 'pos')]
            sx, sz = stands[i - 1]
            new = [sx, G(sx, sz, p['stands'][i - 1][1]) + 1.4, sz]
            d = [new[k] - old[k] for k in range(3)]
            child_sets, seen = [], {}
            for n in nodes[1:]:
                ty = sdoc.type_of(n)
                idx = seen.get(ty, 0); seen[ty] = idx + 1
                pp = sdoc.get(n, 'pos')
                if pp is None:
                    continue
                pp = [float(v) for v in pp]
                if max(abs(v) for v in pp) > 40.0:
                    sets = {'pos': [pp[k] + d[k] for k in range(3)]}
                    if ty.startswith('Destroyable_Object(CollisionBox)'):
                        sets['Health_m'] = p['stand_health']
                    if ty.startswith('Destroyable_Object_Move_Ctrl'):
                        sets['Position_t'] = list(sets['pos'])
                    child_sets.append({'type': ty, 'index': idx, 'set': sets})
            ctx.B.append(ctx.NEW, 'destroy_stand_%d' % i, (SUBMAP, SUBFRAG, root), parent=parent, deep=True, child_sets=child_sets)
            ctx.log.append('stand %d: %d nodes, %d absolute-position children shifted by %s' % (i, len(nodes), len(child_sets), [round(v, 1) for v in d]))
        for i in (1, 2, 3):
            mk, md = COKE_NODES[i]
            px, pz = packs[i - 1]
            gp = G(px, pz)
            ctx.B.append(ctx.NEW, 'destroy_packmk_%d' % i, (SUBMAP, SUBFRAG, mk), parent=parent, pos=[px, gp + 0.05, pz])
            ctx.B.append(ctx.NEW, 'destroy_pack_%d' % i, (SUBMAP, SUBFRAG, md), parent=parent, pos=[px, gp + 0.07, pz])
        for i in (1, 2, 3):
            z = ctx.one(name='Downtown_DrugCollect_BackAlley_DrugPickup_0%d_TRIGGER' % i)
            px, pz = packs[i - 1]; sx, sz = stands[i - 1]
            ctx.place(z, (px, G(px, pz) + 0.6, pz)); ctx.resize_box(z, 10.0, 4.0, p['pack_zone_length'])
            ctx.move(ctx.one(name='Burrito_0%d_RADAR_Node' % i), (sx, G(sx, sz) + 1.5, sz))
            ctx.move(ctx.one(name='Coke_0%d_RADAR_Node' % i), (px, G(px, pz) + 0.1, pz))
        dzp = p['delivery_zone']
        DX, DZ = dzp[0], dzp[2]
        GG = G(DX, DZ, dzp[1])
        dz = ctx.one(name='Downtown_DrugCollect_BackAlley_Delivery_TRIGGER')
        ctx.place(dz, (DX, GG + 0.8, DZ)); ctx.resize_box(dz, p['delivery_width'], 4.0, p['delivery_length'])
        ctx.move(ctx.one(name='Marker_Arrow', type='generic_object_effect(Sprite)'), (DX, GG + 0.15, DZ))
        ctx.move(ctx.one(name='Marker_Cone', type='generic_object_effect(Model)'), (DX, GG + 2.4, DZ))
        ctx.set(ctx.one(name='Activate_Delevery_radar_Blib'), 'TargetName', 'Downtown_DrugCollect_BackAlley_Delivery_TRIGGER')
        tg = ctx.one(name='SubM_02_Down_BuyBur_Steal_loader_Guy')
        gq = p['giver_npc_park']
        tx, tz = W.snap(gq[0], gq[2], margin=1.5)
        ctx.move(tg, (tx, G(tx, tz) + 0.8, tz))
        pw = [x for x in ctx.nodes() if x[3] == 0x40000E][0]
        wq = p['weapon_pickup']
        wx, wz = W.snap(wq[0], wq[2], margin=1.0)
        ctx.move(pw, (wx, G(wx, wz, wq[1]) + 0.6, wz))
        chars = [c for c in ctx.find(type='character_placeholder') if c[3] != 0x40009C]
        keep = [c for c in chars if c[3] in FIGHTERS]
        spare = [c for c in chars if c[3] not in FIGHTERS]
        assert len(keep) == len(FIGHTERS), (len(keep), len(FIGHTERS))
        kept_folders = {ctx.parent_key(c) for c in keep}
        for c in keep:
            si, (ox, oz) = FIGHTERS[c[3]]
            ex, ez = W.snap(stands[si][0] + ox, stands[si][1] + oz, margin=1.5, taken=taken, min_sep=2.5)
            taken.append((ex, ez))
            ctx.place_enemy(c, (ex, ez), health_mod=p['enemy_health'], damage_mod=p['enemy_damage'])
            for s_ in ctx.siblings(c):
                if s_[1].startswith('Trigger_Root'):
                    ctx.resize_box(s_, 16.0, 6.0, 16.0)
        vp = p['vehicle_park']
        vyk = G(vp[0], vp[2], vp[1])
        veh_kids = set()
        for v in ctx.find(type='vehicle_placeholder'):
            vpos = ctx._pos_of(v)
            vx, vz = W.snap(vp[0] + 3.0 * (v[0] % 5), vp[2], margin=0.5)
            d = (vx - vpos[0], vyk + 0.6 - vpos[1], vz - vpos[2])
            for c in [c for c in spare if any(a_[3] == v[3] and a_[2] == v[2] for a_ in ctx.chain(c))]:
                ctx.place_enemy(c, (vp[0] - 10.0 - d[0], vp[2] - d[2]), y=(vyk + 0.8) - d[1])
                veh_kids.add(c[3])
            ctx.move(v, (vx, vyk + 0.6, vz))
        rest = [c for c in spare if c[3] not in veh_kids]
        sp = W.fit([(ctx._pos_of(c)[0], ctx._pos_of(c)[2]) for c in rest], region=p['spare_region'], min_sep=1.2, margin=0.4)
        for c, xz in zip(rest, sp):
            ctx.place_enemy(c, xz)
        for c in spare:
            pk = ctx.parent_key(c)
            if pk in kept_folders:
                raise RuntimeError('spare enemy shares a folder with a fighter')
            folder = [x for x in ctx.nodes() if x[2] == c[2] and x[3] == pk][0]
            ctx.disable_folder(folder)
        ctx.retarget_names({'AI_Vehicle1_sm02': 'MESA_UNUSED_TARGET', 'AI_Vehicle2': 'MESA_UNUSED_TARGET', 'Pick_Up': 'MESA_UNUSED_TARGET',
                            'Pick_Up1': 'MESA_UNUSED_TARGET'}, props=('TargetName',),
                           classes=('Trigger_Activate_Enable_Disable', 'Trigger_Activate_Trig_Noaction_Reactivate'))
        ctx.retarget_names({'Downtown_DrugCollect_BackAlley_Delivery_Point1': 'Downtown_DrugCollect_BackAlley_Delivery_TRIGGER'}, props=('TargetName',),
                           classes=('Trigger_Activate_Radar',))
        ctx.retarget_names({'Explosive_StreetCart0%d' % i: 'SM08_Explosive_StreetCart0%d' % i for i in (1, 2, 3)}, props=('TargetName',),
                           classes=('Trigger_Activate_Particle',))
        for g, gq in zip(ctx.find(type='goodie_placeholder'), p['goodies']):
            gx, gz = W.snap(gq[0], gq[2], margin=1.0)
            ctx.move(g, (gx, G(gx, gz, gq[1]) + 0.5, gz))
        ctx.retarget_names({'SubM_02_Intro_OBJ': O('DESTROY_OBJ_PACKS'), 'SubM_02_Return_the_Dope_Packs_OBJ': O('DESTROY_OBJ_DELIVER')},
                           props=('TargetName', 'SpecificActivator'))
        k = 0
        tp = p['track_park']
        tpy = G(tp[0], tp[2], tp[1]) + 6.0 if tp[1] is None else tp[1]
        bd = host.bounds
        for n in ctx.find(type='TrackPoint'):
            pp = ctx._pos_of(n)
            if not (bd[0] <= pp[0] <= bd[2] and bd[1] <= pp[2] <= bd[3]):
                ctx.move(n, (tp[0] + 2.0 * (k % 5), tpy + (k // 5), tp[2])); k += 1
        ctx.log.append('camera track points moved: %d' % k)
        ctx.retarget_camera_cuts()

    template = dict(slot=31, block='subm_02_down_buybur_steal.mission', root='SubM_02_Down_BuyBur_Steal.fragment', block_path=None)
    return make_spec(MOD, p, host, inst, template, [('packs', p['text_packs']), ('deliver', p['text_deliver'])],
                     [{'DisplayText': '@packs', 'MaxCounter': 3, 'name': O('DESTROY_OBJ_PACKS')}, {'DisplayText': '@deliver', 'name': O('DESTROY_OBJ_DELIVER')}], design,
                     ALLOW_UNRESOLVED=['Marker_Arrow01', 'Marker_Arrow02', 'Marker_Arrow03', 'Activate_Text01', 'Activate_Text02', 'Activate_Text04',
                                       'Buritto_Cart01_sm08_', 'coke_sm08', 'TrafficPoints_M02S02', 'RubbishBag_Group_sm02', 'PublicPhone_sm02', 'sm02_barrel01',
                                       'SM02_Coke02_Track_CTRL', 'SM02_Coke03_Track_CTRL', 'SM02_Coke04_Track_CTRL', 'MESA_UNUSED_TARGET',
                                       'SubM_02_Down_BuyBur_Steal_loader_Guy'],
                     OUTSIDE_OK=('the three cloned stands carry the Downtown convention: physics body / mesh folder at ABSOLUTE positions (flags 16) under the stand, '
                                 'which the generic lint composes with the parent (false positive: 3 Model nodes); everything else is checked by out/B*/outside list'))


def _env():
    from .. import tpl_env
    return tpl_env.get()
