"""Semantic editing helpers on a decoded save (savefile.decode() JSON).

Every edit works on the record list and keeps the engine's record order (node by node in (block, index) order;
inside a node: C++ class slots ascending, then the script-thread record (prop 0), then script members ascending).
New records may be inserted: on load the engine replays every record through the property setter
(FUN_008AA770 -> FUN_0086A860), whether or not the property was in the save before.
"""
import math, re, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import savefile, kmodel, ktypes, kfrag

POWERUPS = ['none', 'rewind', 'golden_gun', 'loco', 'ram', 'medkit', 'sombrero', 'time_stop', 'wrestler',
            'el_mariachi', 'pinata', 'tequila']            # POWERUP_SPRITE_LIST order (cache 0x14a)
WEAPONS = ['beretta', 'magnum', 'marlin', 'winchester', 'benelli', 'hudson', 'mac10', 'mp5', 'ak47', 'm16',
           '(unused10)', 'hand_grenade', 'grenade_launcher', 'rocket_launcher', '(melee14)', 'golden_gun',
           'mariachi', 'pinata', 'molotov', 'dynamite']     # DB_MODELDICT_WEAPON_LIST order (cache 0xf3)


class Save:
    def __init__(self, j, world=None):
        self.j = j
        folders = [f['id'] if isinstance(f, dict) else f for f in j['header']['folders']]
        self.world = world or savefile.World(folders)

    # ------------------------------------------------------------ lookup
    def records(self):
        return self.j['records']

    def node_records(self, key):
        return [r for r in self.j['records'] if r.get('n') == key]

    def find_nodes(self, typestr=None, name=None, block=1):
        out = []
        for idx, n in self.world.maps.get(block, {}).items():
            if typestr and not re.fullmatch(typestr, n[1]):
                continue
            if name and n[4] != name:
                continue
            out.append(savefile.node_key(block, idx))
        return sorted(out, key=savefile.parse_key)

    def node1(self, typestr, name=None):
        k = self.find_nodes(typestr, name)
        if len(k) != 1:
            raise KeyError('expected one node %s/%s, found %s' % (typestr, name, k))
        return k[0]

    def nodetype(self, key):
        blk, idx = savefile.parse_key(key)
        return self.world.nodetype(blk, idx)

    def prop_index(self, key, propname):
        nt = self.nodetype(key)
        for p, (n, t) in nt._saved.items():
            if n == propname:
                return p, t, 'class'
        for i, m in enumerate(nt.members):
            n, t = kmodel.GPROPS[m['id']].rsplit(':', 1)
            if n == propname:
                return nt.T + i, t, 'script'
        raise KeyError('%s has no property %s' % (nt.typestr, propname))

    def get(self, key, propname, default=None):
        for r in self.node_records(key):
            if r.get('name') == propname:
                return r['v']
        return default

    # ------------------------------------------------------------ write
    def _order_key(self, r):
        blk, idx = savefile.parse_key(r['n'])
        p = r['p']
        nt = self.nodetype(r['n'])
        phase = 1 if p == 0 else (0 if p < nt.T else 2)
        return (blk, idx, phase, p)

    def set(self, key, propname, value):
        p, t, kind = self.prop_index(key, propname)
        recs = self.j['records']
        for r in recs:
            if r.get('n') == key and r.get('p') == p:
                if 'v' not in r:
                    raise ValueError('record %s/%s is raw' % (key, propname))
                r['v'] = value
                return 'changed'
        new = {'n': key, 'p': p, 'name': propname, 't': ktypes.type_str(ktypes.parse_type(t)), 'v': value}
        kn = self._order_key(new)
        pos = len(recs)
        for i, r in enumerate(recs):
            if 'n' in r and self._order_key(r) > kn:
                pos = i
                break
        recs.insert(pos, new)
        if key not in self.j['nodes']:
            blk, idx = savefile.parse_key(key)
            self.j['nodes'][key] = self.world.info(blk, idx)
        return 'inserted'

    def drop_blocks(self, blocks):
        before = len(self.j['records'])
        self.j['records'] = [r for r in self.j['records'] if 'n' not in r or savefile.parse_key(r['n'])[0] not in blocks]
        return before - len(self.j['records'])

    # ------------------------------------------------------------ semantic: player
    def player(self):
        return {
            'root': self.node1(r'character_root\(NodeSpatial\)', 'PlayerCharacter'),
            'ai': self.node1(r'character_player_ai\(NodeLogical\)'),
            'weapons': self.find_player('character_weapon_ctrl'),
            'powerups': self.node1(r'character_powerup_ctrl\(NodeLogical\)'),
            'physic': self.find_player('character_physic_ctrl'),
            'anim': self.find_player('character_animation_ctrl'),
            'camera': self.node1(r'camera_root\(Camera\)', 'GameCamera'),
        }

    def find_player(self, script):
        ks = [k for k in self.find_nodes(r'%s\(.*\)' % script)
              if self.world.maps[1][savefile.parse_key(k)[1]][2].endswith('CharacterPlayerControlled.fragment')]
        if len(ks) != 1:
            raise KeyError('player %s: %s' % (script, ks))
        return ks[0]

    def player_pos(self):
        return self.get(self.player()['root'], 'current_world_pos') or self.get(self.player()['root'], 'pos')

    def move_player(self, pos, yaw_deg=None, radius=12.0):
        """Teleport Ram: shift every saved vector of the player rig (character fragment nodes, game camera rig)
        that lies within `radius` m of the old position by the same delta; set yaw if given (Kapow characters
        look down local -Z: facing direction d = (-sin yaw, 0, -cos yaw))."""
        old = self.player_pos()
        delta = [pos[i] - old[i] for i in range(3)]
        pl = self.player()
        # the player's CharacterPlayerControlled.fragment instance (+ its Weapon.fragment children) and the
        # GameCamera.fragment rig; AI characters, props and HUD nodes are never touched
        rig = set(k for k, v in self.j['nodes'].items() if k.startswith('1:') and
                  v.get('fragment') in ('CharacterPlayerControlled.fragment', 'Weapon.fragment', 'GameCamera.fragment')
                  and (v.get('path', '').startswith('/0x100041') or v.get('fragment') == 'GameCamera.fragment'))
        rig |= {pl['root'], pl['camera']}
        changed = []
        for r in self.j['records']:
            if r.get('n') in rig and r.get('t') == 'vector' and isinstance(r.get('v'), list) \
                    and all(isinstance(x, (int, float)) for x in r['v']) and math.dist(r['v'], old) <= radius:
                r['v'] = [r['v'][i] + delta[i] for i in range(3)]
                changed.append('%s.%s' % (r['n'], r['name']))
        for name in ('pos', 'current_world_pos', 'previous_world_pos'):
            self.set(pl['root'], name, list(pos))
        if yaw_deg is not None:
            q = [0.0, math.sin(math.radians(yaw_deg) / 2), 0.0, math.cos(math.radians(yaw_deg) / 2)]
            for name in ('orient', 'current_world_orient'):
                self.set(pl['root'], name, q)
            for name in ('worldstartorient', 'worldendorient'):
                if self.get(pl['anim'], name) is not None:
                    self.set(pl['anim'], name, q)
        return {'old': old, 'delta': delta, 'shifted': changed}

    def heal(self):
        return self.set(self.player()['ai'], 'DamageTaken', 0.0)

    def give_weapons(self, which='all', ammo='max'):
        k = self.player()['weapons']
        inv = self.get(k, 'Inventory')
        n = len(inv['RightHandGunList'])
        for i in range(n):
            if WEAPONS[i].startswith('('):
                continue
            if which == 'all' or WEAPONS[i] in which:
                inv['RightHandGunList'][i] = True
                if ammo == 'max':
                    inv['AmmoList'][i] = inv['MaxAmmoList'][i]
        self.set(k, 'Inventory', inv)
        return inv

    def set_powerups(self, counts):
        k = self.player()['powerups']
        pi = self.get(k, 'PowerUpInventory')
        for name, v in counts.items():
            i = POWERUPS.index(name)
            pi['PowerUpList'][i] = int(v) if v != 'max' else pi['MaxPowerUpList'][i]
        self.set(k, 'PowerUpInventory', pi)
        return pi

    # ------------------------------------------------------------ semantic: progress
    def mission_ctrl(self):
        return self.node1(r'master_mission_ctrl\(NodeLogical\)')

    def player_status(self):
        return self.node1(r'database_player_status\(NodeLogical\)')

    def mission_names(self):
        ml = self.get(self.mission_ctrl(), 'Mission_List')
        out = []
        for m in ml:
            out.append(self.entity_name(m['Mission_Entity']))
        return out

    def entity_name(self, e):
        if not e or not isinstance(e, str):
            return None
        v = int(e[1:], 16)
        n = self.world.maps.get((v >> 20) & 7, {}).get(v & 0xFFFFF)
        return n[4] if n else None

    def unlock(self, mode='open'):
        """mode 'open': every valid mission (story, intermission, sub-mission) Mission_open = true.
           mode 'complete': additionally every valid story/intermission entry Mission_complete = true."""
        k = self.mission_ctrl()
        ml = self.get(k, 'Mission_List')
        n = 0
        for m in ml:
            if not m['Mission_Valid']:
                continue
            m['Mission_open'] = True
            if mode == 'complete' and m['Mission_type'] in (0, 2):
                m['Mission_complete'] = True
            n += 1
        self.set(k, 'Mission_List', ml)
        return n


def summary(s):
    """Human readable dict of the interesting values."""
    j = s.j
    h = j['header']
    out = {'folders': [(f['slot'], f['folder']) for f in h['folders'] if f['folder']],
           'game_time_min': round(h['game_time_ms'] / 60000.0, 1), 'frame': h['frame'],
           'summary(SaveInMission,GlobalScore,TheSubMap)': [it[0] for it in j['summary']['items']]}
    pl = s.player()
    out['player_pos'] = s.player_pos()
    out['player_damage_taken'] = s.get(pl['ai'], 'DamageTaken')
    out['player_health_prop'] = s.get(pl['ai'], 'Health')
    inv = s.get(pl['weapons'], 'Inventory')
    if inv:
        out['weapons'] = {WEAPONS[i]: {'own': bool(inv['RightHandGunList'][i]), 'dual': bool(inv['LeftHandGunList'][i]),
                                       'ammo': inv['AmmoList'][i], 'max': inv['MaxAmmoList'][i],
                                       'clip1': inv['AmmoInPrimWeapon'][i], 'clip2': inv['AmmoInSecWeapon'][i]}
                          for i in range(len(inv['AmmoList'])) if not WEAPONS[i].startswith('(')}
    pu = s.get(pl['powerups'], 'PowerUpInventory')
    if pu:
        out['powerups'] = {POWERUPS[i]: [pu['PowerUpList'][i], pu['MaxPowerUpList'][i]] for i in range(1, len(POWERUPS))}
    ps = s.player_status()
    for nm in ('OverallScore', 'TotalEnemiesKilled', 'TotalCiviliansKilled', 'LargestOverallCombo',
               'CollectedHealthSkills', 'CollectedStaminaSkills', 'CollectedWeaponSkills',
               'HealthSkillPoints', 'StaminaSkillPoints', 'WeaponSkillPoints'):
        out[nm] = s.get(ps, nm)
    mc = s.mission_ctrl()
    for nm in ('Current_Mission', 'Last_Mission', 'Last_StoryMission', 'Start_Mission', 'TargetName',
               'Teleport_to', 'Mission_Score', 'Game_Completed'):
        v = s.get(mc, nm)
        out[nm] = v['s'] if isinstance(v, dict) and 's' in v else v
    ml = s.get(mc, 'Mission_List') or []
    names = s.mission_names()
    out['missions'] = [{'i': i, 'name': names[i], 'type': ['story', 'sub', 'intermission'][m['Mission_type']]
                        if m['Mission_type'] in (0, 1, 2) else m['Mission_type'],
                        'complete': m['Mission_complete'], 'open': m['Mission_open'],
                        'hiscore': m['Highest_Score'], 'award': m['Award_achived']}
                       for i, m in enumerate(ml) if m['Mission_Valid']]
    return out


# ------------------------------------------------------------ fragment transforms / mission start
def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def qrot(q, v):
    p = qmul(qmul(q, [v[0], v[1], v[2], 0.0]), [-q[0], -q[1], -q[2], q[3]])
    return p[:3]


def fragment_nodes(blob):
    """stored id -> {type, name, pos, orient, parent(stored id or None), fragment}"""
    out = {}
    for o in kfrag.decode(blob):
        if o[0] == 'create':
            out[o[1]] = {'type': o[2], 'pos': [0.0, 0.0, 0.0], 'orient': [0.0, 0.0, 0.0, 1.0], 'parent': None, 'name': None}
        elif o[0] == 'set' and o[1] in out:
            v = o[4]
            if o[3] == 'name':
                out[o[1]]['name'] = v['s'] if isinstance(v, dict) else v
            elif o[3] in ('pos', 'orient') and isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
                out[o[1]][o[3]] = v
            elif o[3] == 'parent':
                out[o[1]]['parent'] = None if (v is None or v == 'E000000') else int(v[1:], 16)
    return out


def world_transform(nodes, sid):
    """Compose pos/orient up the parent chain inside one fragment (the instancing root is taken as identity)."""
    pos, q = list(nodes[sid]['pos']), list(nodes[sid]['orient'])
    seen = set()
    p = nodes[sid]['parent']
    while p is not None and p in nodes and p not in seen:
        seen.add(p)
        par = nodes[p]
        pos = [a + b for a, b in zip(qrot(par['orient'], pos), par['pos'])]
        q = qmul(par['orient'], q)
        p = par['parent']
    return pos, q


def find_named_node(block_file, pattern):
    """First node whose name matches regex `pattern` in a block's fragments -> (fragment, stored id, name, world pos, world orient)."""
    for nm, blob in savefile.block_frags(block_file).items():
        nodes = fragment_nodes(blob)
        for sid, n in nodes.items():
            if n['name'] and re.search(pattern, n['name'], re.I):
                pos, q = world_transform(nodes, sid)
                return nm, sid, n['name'], pos, q
    return None


INTERMISSION_FOLDERS = {2: 'InterMission_AFTER_Tommy', 4: 'InterMission_AFTER_Marco', 7: 'InterMission_AFTER_GetTheCar',
                        9: 'InterMission_AFTER_GetTheTrucks', 13: 'InterMission_AFTER_Escape',
                        17: 'InterMission_AFTER_BreakIntoSafe', 19: 'InterMission_AFTER_Elvez',
                        22: 'InterMission_AFTER_Bridge', 25: 'InterMission_AFTER_Jungle', 80: 'GAMEOVER_INTERMISSION'}


def mission_folder(s, m):
    """Block-1 runtime index of the Missions.fragment folder for Mission_List index m."""
    w = s.world
    mf = [n for n in w.maps[1].values() if n[2].endswith('Missions.fragment')]
    if m in INTERMISSION_FOLDERS:
        hit = [n for n in mf if n[4] == INTERMISSION_FOLDERS[m]]
    else:
        dec = kfrag.decode(w.main_frags[mf[0][2]])
        sids = [o[1] for o in dec if o[0] == 'set' and o[3] == 'Mission' and o[4] == m]
        hit = [n for n in mf if n[3] in sids and n[1].startswith('database_Mission_ID')]
    if len(hit) != 1:
        raise KeyError('no unique folder for mission %d: %s' % (m, hit))
    return hit[0]


def map_of_submap(s, sub_idx):
    """The database_Map_ID folder that precedes a database_SubMap_ID folder in Overdose.scene (same map group)."""
    by = s.world.maps[1]
    i = sub_idx
    while i > 0:
        i -= 1
        n = by.get(i)
        if n and n[1].startswith('database_Map_ID'):
            return i
    raise KeyError('no map for submap %x' % sub_idx)


def start_mission(s, m, player_at_teleport=True, submap=None):
    """EXPERIMENTAL 'start of mission m': header -> the mission's map/submap/mission blocks, every record of
    blocks 2-6 dropped (they load in their authored initial state), master_mission_ctrl -> mission m with zeroed
    per-mission counters, the summary updated, Ram placed on the mission's TELEPORT node.
    submap: the mission's `Mission_SubMap` from its award (the engine loads THAT submap; the list entry's Mission_start_submap is the
    award's Mission_StartMap and differs for missions 5, 8, 10, 18, 20 and 23). Without it the list entry is used (older behaviour)."""
    mc = s.mission_ctrl()
    ml = s.get(mc, 'Mission_List')
    info = ml[m]
    if not info['Mission_Valid']:
        raise ValueError('mission %d is not valid' % m)
    cache = s.node1(r'cache\(Node\)')
    subs = s.get(cache, 'DB_SUBMAP_LIST')
    maps = s.get(cache, 'DB_MAP_LIST')
    sub_no = info['Mission_start_submap'] if submap is None else int(submap)
    sub_ent = subs[sub_no]
    sub_idx = int(sub_ent[1:], 16) & 0xFFFFF
    map_idx = map_of_submap(s, sub_idx)
    folder = mission_folder(s, m)
    hdr = s.j['header']
    old = [f['id'] for f in hdr['folders']]
    new = [-1, 0x100000 | map_idx, 0x100000 | sub_idx, 0x100000 | folder[0], -1, old[5]]
    for f, v in zip(hdr['folders'], new):
        f['id'] = v
        f['folder'] = s.world.folder_name(v) if v > 0 else None
        f['block'] = None
    dropped = s.drop_blocks({2, 3, 4, 5, 6})
    # world for the new blocks (node types for the remaining block-1 records are unchanged)
    s.world = savefile.World(new)
    for f, k in zip(hdr['folders'], range(6)):
        f['block'] = s.world.blocks.get(k + 1)
    mapent = 'E%06x' % (0x100000 | map_idx)
    mapno = maps.index(mapent) if mapent in maps else None
    fragpath = s.world.folder_fragment(folder[0])
    mission_block = savefile.block_file_for(fragpath)
    tp = find_named_node(mission_block, r'teleport')
    sets = {'Current_Mission': m, 'Start_Mission': m, 'TargetName': folder[4],
            'EnemiesKilledOnCurrentMission': 0, 'NeutralsKilledOnCurrentMission': 0, 'Mission_Score': 0,
            'Curr_L_Combo': 0.0, 'Curr_Best_Move': 0, 'MissionLoad': False, 'MissionCanceled': False,
            'Current_loaded_SubMap': sub_no, 'LastSubMap': sub_ent, 'LastMap': mapent}
    if mapno is not None:
        sets['Current_loaded_MainMap'] = mapno
    if info['Mission_type'] == 0:
        sets['Last_StoryMission'] = m
    if tp:
        sets['Teleport_to'] = tp[2]
    for k, v in sets.items():
        s.set(mc, k, v)
    info['Mission_open'] = True
    info['Mission_complete'] = False
    info['Current_Score'] = 0
    s.set(mc, 'Mission_List', ml)
    items = s.j['summary']['items']
    items[0] = [m]
    items[2] = [sub_no]
    moved = None
    if player_at_teleport and tp:
        q = tp[4]
        yaw = math.degrees(2 * math.atan2(q[1], q[3]))
        moved = s.move_player(tp[3], yaw)
    return {'mission': m, 'folder': folder[4], 'map': s.world.folder_name(map_idx), 'submap': s.world.folder_name(sub_idx),
            'blocks': s.world.blocks, 'dropped_records': dropped, 'teleport': tp[2:] if tp else None, 'moved': moved}
