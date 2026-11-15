"""Template 'lava': cross the area without ever touching the ground ("the floor is lava"). (Mesa index 51.)

Template: registry slot 33 block = the D1 variant of SubM_04_Down_SomSal_Kill (same as 'showdown': go to a zone, enemies wake, return zone, MISSION COMPLETE).
  * the 'go to the camp' zone is the START ZONE on the first platform: entering it enables the lava boxes, the goal zone and objectives 2/3.
  * LAVA = thin boxes (clones of the template's zone root, enter by the player, disabled until the start zone) that cover the floor except the safe footprints
    (platforms, stepping stones, ramps, walkways); each has a condition clone and 2 actions copied from the stunt block: feedback text + MISSION FAILED.
  * the goal zone (the template's return zone) is enabled by the start zone.   * 3 shooters stand on the ground and shoot at the player on the stones.
THE HOST MUST PROVIDE THE STEPPING STONES: platforms, crates, stones, ramps that the player can climb (>= 1.3 m high so a standing player is above the lava) - they are
map geometry (new_geometry placements of the host new map), not part of this mission. Give the lava rectangles directly, or the safe rectangles and let the template cut
the lava out of the lava area.
"""
import re, sys
from ..tpl_core import P
from .. import tpl_lib as L
from ._base import make_spec

MOD = sys.modules[__name__]
NAME = 'lava'
TITLE = 'Floor Is Lava'
SUMMARY = 'Climb onto a platform and cross a chain of stones, ramps and walkways to a goal zone. Touching the ground fails the mission.'
HOST_NEEDS = ['Stepping stones: a start platform, a chain of stones / crates / ramps (1.3 m or more high, jumpable gaps) and a goal platform that the HOST MAP provides as geometry.',
              'The lava boxes cover the floor of the lava area except the "safe" rectangles you give (the stones\' footprints), so the safe rectangles must match the real geometry.',
              'Free ground for three shooters. Works in a new map you build the stones into; an existing map section only if it has such a chain of props.']
LEGACY_INDEX = 51
LEGACY_ROOT = 'SubM_51_Down_LavaRn_Kill.fragment'
GIVER_NAME = 'MESA_GIVER_LAVA'
COMMON = dict(giver=(-34.0, -4.0, 6.0), name='FLOOR IS LAVA',
              description='The sand of the compound is scorching. Climb the platform, hop the crates and stones, cross the ramp and the walkway - and never touch the ground.',
              load_mid='DO NOT TOUCH THE SAND', load_low='HOP + CLIMB', pass_score=0)
ENEMY_NAMES = ['SubM_04_Down_SomSal_Kill_Peter', 'SubM_04_Down_SomSal_Kill_Peter01', 'SubM_04_Down_SomSal_Kill_Brian']
STUNT = 'subm_37_down_move_kill.mission'
STUNT_FRAG = 'SubM_37_Down_Move_Kill.fragment'


def lava_boxes_from_safe(area, safe):
    """Cover `area` [x0, z0, x1, z1] with rectangles except the `safe` rectangles: vertical strips between the safe rectangles' x edges, each strip cut at the safe z intervals.
    Returns [[x0, z0, x1, z1], ...] (slivers under 0.2 m are dropped)."""
    xs = sorted({area[0], area[2]} | {min(max(v, area[0]), area[2]) for r in safe for v in (r[0], r[2])})
    out = []
    for a, b in zip(xs, xs[1:]):
        if b - a < 0.2:
            continue
        mid = (a + b) / 2
        cuts = sorted((max(r[1], area[1]), min(r[3], area[3])) for r in safe if r[0] < mid < r[2] and r[3] > area[1] and r[1] < area[3])
        z = area[1]
        for c0, c1 in cuts:
            if c0 - z >= 0.2:
                out.append([a, z, b, c0])
            z = max(z, c1)
        if area[3] - z >= 0.2:
            out.append([a, z, b, area[3]])
    return out


PARAMS = [
    P('start_zone', 'point', lambda h, p: h.pt(11.5, -36), 'Start zone', 'Centre of the start zone on the first platform (x, y, z). y = the height of the surface the player stands on.', group='Placement'),
    P('start_size', 'floats', [2.4, 2.0, 2.6], 'Start zone size', 'Width, height, length of the start zone (m).', min_len=3, max_len=3, group='Placement', advanced=True),
    P('goal_zone', 'point', lambda h, p: h.pt(35, 25), 'Goal zone', 'Centre of the goal zone (x, y, z). y = the height of the walkway / platform surface it stands on.', group='Placement'),
    P('goal_size', 'floats', [3.6, 3.0, 6.0], 'Goal zone size', 'Width, height, length of the goal zone (m).', min_len=3, max_len=3, group='Placement', advanced=True),
    P('goal_prop', 'point', lambda h, p: h.pt(35, 27), 'Goal marker', 'Where the template\'s goal marker prop stands (decoration, on the goal surface).', group='Placement', advanced=True),
    P('shooters', 'points', lambda h, p: [h.pt(12, -16), h.pt(26, -12), h.pt(22, 6)], 'Shooter positions', 'Where the three ground shooters stand (x, y, z).', min_len=3, max_len=3, group='Placement'),
    P('lava_area', 'rect', lambda h, p: list(h.rr(-39.5, -39.5, 39.5, 39.5)), 'Lava area', 'Rectangle [x0, z0, x1, z1] of floor that is lava (everything outside it is safe).', group='Placement'),
    P('safe_rects', 'rects', [], 'Safe footprints', 'Rectangles of the stones, platforms, ramps and walkways the player may stand on. Used to cut the lava out of the lava area when "Lava boxes" is empty.', group='Placement'),
    P('lava_boxes', 'rects', [], 'Lava boxes', 'Rectangles that burn, each [x0, z0, x1, z1]. Empty = computed from the lava area minus the safe footprints.', group='Placement', advanced=True),
    P('park', 'point', lambda h, p: h.pt(-60, 55, None), 'Parking spot', 'Where leftover template content is parked (disabled).', group='Placement', advanced=True),
    P('snap_to_free_ground', 'bool', True, 'Keep clear of obstacles', 'Move shooters that fall inside a wall or prop to the nearest free ground.', group='Placement', advanced=True),
    P('lava_height', 'float', 1.0, 'Lava depth', 'Height of the lava boxes above the ground. A player standing on a prop at least 0.3 m higher is safe.', min=0.3, max=3.0, unit='m', group='Settings'),
    P('fail_delay', 'float', 1.5, 'Burn delay', 'Seconds between touching the lava and MISSION FAILED.', min=0.0, max=10.0, unit='s', group='Settings', advanced=True),
    P('enemy_health', 'float', 0.3, 'Shooter health', 'Health multiplier (1.0 = normal).', min=0.05, max=3.0, group='Settings'),
    P('enemy_damage', 'float', 0.12, 'Shooter damage', 'Damage multiplier (1.0 = normal).', min=0.0, max=3.0, group='Settings'),
    P('text_start', 'text', 'Climb onto the first platform', 'Objective 1 text', 'First objective line.', group='Texts', max_len=60),
    P('text_cross', 'text', 'Cross the compound without touching the sand', 'Objective 2 text', 'Second objective line.', group='Texts', max_len=60),
    P('text_goal', 'text', 'Reach the end of the walkway', 'Objective 3 text', 'Third objective line.', group='Texts', max_len=60),
    P('text_burnt', 'text', 'The floor is lava! You touched the sand.', 'Burn text', 'Shown when the player touches the lava.', group='Texts', max_len=60),
]


def boxes_of(p):
    return p['lava_boxes'] or lava_boxes_from_safe(p['lava_area'], p['safe_rects'])


def constraints(p, host):
    m = []
    if not p['lava_boxes'] and not p['safe_rects']:
        m.append(('warn', 'No safe footprints and no lava boxes: the whole area is lava and nothing can be stood on. Give the rectangles of the stones and platforms (the host map must contain them).'))
    boxes = boxes_of(p)
    if not boxes:
        m.append(('error', 'There is no lava: the safe footprints cover the whole lava area.'))
    for nm, pt in (('start zone', p['start_zone']), ('goal zone', p['goal_zone'])):
        if p['safe_rects'] and not any(r[0] <= pt[0] <= r[2] and r[1] <= pt[2] <= r[3] for r in p['safe_rects']):
            m.append(('warn', 'The %s is not on one of the safe footprints.' % nm))
        for b in boxes:
            if b[0] <= pt[0] <= b[2] and b[1] <= pt[2] <= b[3] and pt[1] is None:
                m.append(('warn', 'The %s lies over lava: give it the y of the stone it stands on.' % nm))
                break
    if len(boxes) > 24:
        m.append(('warn', 'The lava is cut into %d boxes; fewer, simpler safe footprints make a lighter mission.' % len(boxes)))
    return m


def make(p, host, inst):
    O = lambda n: n + inst.sfx
    enemies = {nm.lower(): pt for nm, pt in zip(ENEMY_NAMES, p['shooters'])}
    LAVA_H = p['lava_height']
    boxes = boxes_of(p)

    def design(ctx):
        W = ctx.world
        sz_, gz_ = p['start_zone'], p['goal_zone']
        ss, gs = p['start_size'], p['goal_size']
        sy = host.gy(sz_[0], sz_[2], sz_[1]) + ss[1] / 2.0
        gy_ = host.gy(gz_[0], gz_[2], gz_[1]) + gs[1] / 2.0
        hat = p['goal_prop']
        cur = None
        moved = 0
        for n in ctx.nodes():
            idx, ty, f, key, name, path = n
            t = ty.split('(')[0]
            if t == 'Folder' and str(name).startswith('Enemy'):
                cur = None
            if t == 'character_placeholder' and str(name).lower() in enemies:
                pt = enemies[str(name).lower()]
                x, z = W.snap(pt[0], pt[2], margin=1.5) if p['snap_to_free_ground'] else (pt[0], pt[2])
                gy = host.gy(x, z, pt[1]) + 0.8
                ctx.move(n, [x, gy, z]); moved += 1
                ctx.set(n, 'Damage_mod', p['enemy_damage']); ctx.set(n, 'Health_mod', p['enemy_health'])
                ctx.set_weapons(n, 0)
                cur = (x, z, gy)
            elif cur and t == 'Pathtype' and name == 'GotoPath':
                ctx.move(n, [cur[0], cur[2], cur[1]])
            elif cur and t == 'Trigger_Root' and name == 'Trigger':
                ctx.move(n, [cur[0], cur[2] + 1, cur[1]])
                ctx.resize_box(n, 14.0, 6.0, 14.0)
            elif t == 'Trigger_Root' and name == 'First_Enemy_team_KILL_Completed':
                ctx.set(n, 'ConditionsNeeded', 99.0)
            elif t == 'Trigger_Activate_Camera' and name == 'ACT_OpenLotJump_Cam01':
                ctx.retarget_camera_cuts(names=['ACT_OpenLotJump_Cam01'])
            elif t == 'Model' and name == 'SubM_04_Down_SomSal_Kill_Bur':
                ctx.place(n, (hat[0], host.gy(hat[0], hat[2], hat[1]) + 0.4, hat[2]))
        assert moved == len(enemies), moved
        zs = [n for n in ctx.nodes() if n[3] == 0x4018D3][0]
        gz = [n for n in ctx.nodes() if n[3] == 0x40190F][0]
        ctx.place(zs, (sz_[0], sy, sz_[2])); ctx.resize_box(zs, *ss)
        ctx.place(gz, (gz_[0], gy_, gz_[2])); ctx.resize_box(gz, *gs)
        ctx.set(gz, 'flags', 257)

        def which(v):
            m = re.fullmatch(r'SubM_04_Sombrero_OBJ(\d?)', v, re.I)
            return O('LAVA_OBJ' + (m.group(1) or '1')) if m else None
        ctx.retarget_names(which, props=('TargetName',), classes=('Trigger_Activate_Objective',), skip=('ACT_D1_Kill_OBJ_COMPLETE',))
        ctx.set(ctx.one(name='ACT_SubM_04_text'), 'FeedbackText', ctx.texts['@cross'])

        def byk(key):
            return [n for n in ctx.nodes() if n[3] == key][0]
        zcond = [n for n in ctx.nodes() if n[1].startswith('Trigger_Condition') and ctx.parent_key(n) == 0x4018D3][0]
        en_tmpl = byk(0x4018D9)
        SH = ctx.NEW.rsplit('/', 1)[0] + '/'
        for i, (x0, z0, x1, z1) in enumerate(boxes):
            nm = 'LAVA_' + (chr(65 + i) if i < 26 else str(i))
            uid = 'lava_' + nm
            ground = host.gy((x0 + x1) / 2, (z0 + z1) / 2)
            ctx.B.append(ctx.NEW, uid, (ctx.NEW, ctx.frag(zs[2]), zs[3]), parent=('ref', ctx.frag(zs[2]), ctx.parent_key(zs)), name=nm,
                         pos=[(x0 + x1) / 2, ground + LAVA_H / 2.0, (z0 + z1) / 2], rot=[0.0, 0.0, 0.0, 1.0],
                         sets={'width': float(x1 - x0), 'height': float(LAVA_H), 'length': float(z1 - z0), 'flags': 17})
            ctx.B.append(ctx.NEW, uid + '_c', (ctx.NEW, ctx.frag(zcond[2]), zcond[3]), parent=('new', uid), name='COND_Lava_Touch')
            ctx.B.append(ctx.NEW, uid + '_f', (SH + STUNT, STUNT_FRAG, 0x400089), parent=('new', uid), name='ACT_Lava_FAILED', sets={'Delay': p['fail_delay']})
            ctx.B.append(ctx.NEW, uid + '_t', (SH + STUNT, STUNT_FRAG, 0x40008A), parent=('new', uid), name='ACT_Lava_text', sets={'FeedbackText': ctx.texts['@burnt']})
            ctx.add_action(en_tmpl, zs, 'lava_en_' + nm, name='ACT_Enable_' + nm, sets={'Delay': 0.3, 'TargetName': nm})
        gp = zs
        ctx.add_action(en_tmpl, gp, 'lava_en_goal', name='ACT_Enable_Goal', sets={'Delay': 1.0, 'TargetName': 'SubM_04_Down_SomSal_Kill_SOMPickup_TRIGGER'})
        ctx.add_action(byk(0x40256B), gp, 'lava_obj2_done', name='ACT_Lava_OBJ2_COMPLETE', sets={'Delay': 12.0})
        ctx.add_action(byk(0x40256A), gp, 'lava_obj3_on', name='ACT_Lava_OBJ3_ON', sets={'Delay': 12.5})
        radar = [n for n in ctx.nodes() if n[1].startswith('Trigger_Activate_Radar') and ctx.parent_key(n) == 0x4018ED and
                 ctx.get(n, 'TargetName', '') == 'SubM_04_Down_SomSal_Kill_SOMPickup_TRIGGER'][0]
        ctx.add_action(radar, gp, 'lava_goal_blip', name='ACT_Lava_GoalBlip', sets={'Delay': 1.5})
        pk = p['park']
        L.park_strays(ctx, (pk[0] - 2.0, pk[2]))

    template = dict(slot=33, block='subm_04_down_somsal_kill.mission', root='SubM_04_Down_SomSal_Kill.fragment', block_path=MOD_VARIANT)
    return make_spec(MOD, p, host, inst, template,
                     [('start', p['text_start']), ('cross', p['text_cross']), ('goal', p['text_goal']), ('burnt', p['text_burnt'])],
                     [{'DisplayText': '@start', 'name': O('LAVA_OBJ1')}, {'DisplayText': '@cross', 'HasObjectivesCounter': False, 'name': O('LAVA_OBJ2')},
                      {'DisplayText': '@goal', 'name': O('LAVA_OBJ3')}], design,
                     ALLOW_UNRESOLVED=['SM04_DoorA', 'SM04_DoorB', 'Sm04_Havoc'],
                     OUTSIDE_OK='inactive template content of the Downtown camp, never enabled (same as showdown)')


from . import showdown as _sd
MOD_VARIANT = _sd.TEMPLATE_BLOCK_VARIANT
