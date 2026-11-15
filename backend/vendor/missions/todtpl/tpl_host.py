"""tpl_host.py - the HOST of a mission: the map (or map section) the mission's giver stands in and its play area lies in.

A Host answers the questions the old Mesa-only code answered with constants:
    where is free ground (obstacle footprints), what is the ground height at (x, z), how big is the play area, where may leftovers of the
    template be parked, what is the arrival / start spot, which map ids does the award need, which block takes the giver box.

Two kinds:
  new_map   a map built by maps/tools/make_new_map.py from the project's new-map params (TOD Mod Studio "New maps" project). Obstacles, arrival,
            return loader and pickups are read from those params; ground height from the "heightfield" parts of new_geometry (or a flat ground_y).
  existing  an existing map / section (entry-host rules, make_new_map.py --list-entry-hosts). Its giver box is grafted into the block's last,
            once-instanced fragment; Mission_Map / SubMap come from the host dict; free ground uses the "obstacles" the caller lists.
Host dict (JSON, all coordinates WORLD metres, TOD axes y up):
    id, kind, area [x0, z0, x1, z1]   the play area (flat, walkable) missions may use; default for a new map: 78 x 78 m around the arrival
    ground_y  number = the ground is flat at that height (no probing)  |  null = probe the heightfield of the new geometry
    bounds    [x0, z0, x1, z1] nothing of a mission may lie outside (default: the map walls, else the area grown 2x)
    unit      half extent (m) of the area the DEFAULT layouts were drawn for (39 = the Mesa courtyard); defaults scale with area_half / unit
    start_spot  name of the teleport node the award starts at (default: the map arrival node)
    existing: block, parent {fragment, entity}, map_ids {map, submap, start_map} OR map_ids_from_slot (the shipped award of that registry slot supplies the proven
              map ids and start spot, e.g. 33 = a Downtown mission), obstacles [[x0,z0,x1,z1],...], spots [names]
"""
import json, math, os, sys
sys.dont_write_bytecode = True

NEW_MAP, EXISTING = 'new_map', 'existing'


class HostError(ValueError):
    pass


def _footprints(models, placements):
    """obstacle rectangles (x0, z0, x1, z1, label) of every placed model of a new_geometry (the ground model is not an obstacle)"""
    out = []
    for pl in placements:
        m = models.get(pl['model'])
        if m is None:
            continue
        if any(pt['type'] == 'heightfield' for pt in m['parts']) and len(m['parts']) == 1:
            continue
        px, py, pz = pl['pos']
        for part in m['parts']:
            t = part['type']
            if t in ('box', 'wedge'):
                mn, mx = part['min'], part['max']
                out.append((px + mn[0], pz + mn[2], px + mx[0], pz + mx[2], pl['name']))
            elif t == 'rock':
                c, r = part['center'], part['radius']
                out.append((px + c[0] - r, pz + c[2] - r, px + c[0] + r, pz + c[2] + r, pl['name']))
    return out


class Host:
    def __init__(self, hd, map_params=None):
        self.d = dict(hd)
        self.id = hd.get('id', 'host')
        self.kind = hd.get('kind', NEW_MAP)
        if self.kind not in (NEW_MAP, EXISTING):
            raise HostError('host %s: kind must be new_map or existing' % self.id)
        self.map_params = map_params                          # the make_new_map map dict (maps[i]) for a new map
        self.obst, self.reserved, self._hf = [], [], []
        self.walls = None
        area = hd.get('area')
        if map_params is not None:
            g = map_params.get('new_geometry') or {}
            models = {m['name']: m for m in g.get('models', [])}
            self.obst = _footprints(models, g.get('placements', []))
            for pl in g.get('placements', []):                # heightfield pieces (ground model) for ground probing
                m = models.get(pl['model'])
                for part in (m or {}).get('parts', []):
                    if part['type'] == 'heightfield':
                        self._hf.append((pl['pos'], part))
            a = map_params['arrival']['pos']
            self.arrival = dict(pos=list(a), node=None)
            self.reserved.append((a[0] - 8, a[2] - 8, a[0] + 8, a[2] + 8, 'arrival'))
            r = map_params.get('return')
            if r:
                rp, rs = r['pos'], r.get('size', [8, 8, 2])
                self.reserved.append((rp[0] - rs[0] / 2 - 2, rp[2] - 10, rp[0] + rs[0] / 2 + 2, rp[2] + rs[2] / 2 + 2, 'exit_loader'))
            for pk in map_params.get('pickups', []):
                self.reserved.append((pk['pos'][0] - 1.5, pk['pos'][2] - 1.5, pk['pos'][0] + 1.5, pk['pos'][2] + 1.5, 'pickup'))
            ws = map_params.get('walls') or []
            if ws:
                self.walls = (min(w['pos'][0] - w['size'][0] / 2 for w in ws), min(w['pos'][2] - w['size'][2] / 2 for w in ws),
                              max(w['pos'][0] + w['size'][0] / 2 for w in ws), max(w['pos'][2] + w['size'][2] / 2 for w in ws))
            if area is None:
                area = [a[0] - 39.0, a[2] - 39.0, a[0] + 39.0, a[2] + 39.0]
            self.map_name = map_params.get('name')
        else:
            self.arrival = dict(pos=None, node=hd.get('start_spot'))
            self.map_name = None
        for o in hd.get('obstacles', []):
            self.obst.append((o[0], o[1], o[2], o[3], o[4] if len(o) > 4 else 'obstacle'))
        if area is None:
            raise HostError('host %s: "area" [x0, z0, x1, z1] is required' % self.id)
        self.area = tuple(float(v) for v in area)
        if not (self.area[2] > self.area[0] and self.area[3] > self.area[1]):
            raise HostError('host %s: area must have x1 > x0 and z1 > z0' % self.id)
        self.cx, self.cz = (self.area[0] + self.area[2]) / 2.0, (self.area[1] + self.area[3]) / 2.0
        self.half = min(self.area[2] - self.area[0], self.area[3] - self.area[1]) / 2.0
        self.unit = float(hd.get('unit', 39.0))
        self.scale = self.half / self.unit
        self.ground_y = hd.get('ground_y', 20.0 if (map_params is None or not self._hf) else None)
        if hd.get('bounds'):
            self.bounds = tuple(float(v) for v in hd['bounds'])
        elif self.walls:
            self.bounds = (self.walls[0] + 1.0, self.walls[1] + 1.0, self.walls[2] - 1.0, self.walls[3] - 1.0)       # 1 m inside the walls (Mesa: 79 of 80)
        else:
            self.bounds = (self.cx - 2 * self.half, self.cz - 2 * self.half, self.cx + 2 * self.half, self.cz + 2 * self.half)
        self.start_spot = hd.get('start_spot')
        self.spots = list(hd.get('spots', []))
        if map_params is not None:                            # the recipe names the arrival node ARRIVAL_<NAME>; teleports keep their names
            import re
            self.arrival['node'] = 'ARRIVAL_%s' % re.sub(r'[^A-Za-z0-9]+', '_', map_params['name']).upper()
            self.spots = [self.arrival['node']] + [t['name'] for t in map_params.get('teleports', [])] + [s for s in self.spots if s]
            if not self.start_spot:
                self.start_spot = self.arrival['node']
        elif self.start_spot and self.start_spot not in self.spots:
            self.spots.append(self.start_spot)
        self.map_ids = dict(hd.get('map_ids', {}))
        self.block = hd.get('block')
        self.parent = hd.get('parent')

    # ---------------------------------------------------------------- default layouts: the Mesa layout scaled onto this host
    def w(self, rx, rz):
        """world (x, z) of a point given in Mesa-courtyard units (metres from the area centre of a 39 m half-extent courtyard)"""
        return self.cx + rx * self.scale, self.cz + rz * self.scale

    def rr(self, x0, z0, x1, z1):
        """world rect of a Mesa-unit rect"""
        return (self.cx + x0 * self.scale, self.cz + z0 * self.scale, self.cx + x1 * self.scale, self.cz + z1 * self.scale)

    def pt(self, rx, rz, y=None):
        """default point [x, y|None, z] (y None = ground)"""
        x, z = self.w(rx, rz)
        return [x, y, z]

    # ---------------------------------------------------------------- ground
    def ground_at(self, x, z):
        """ground height at (x, z): the flat ground_y, else the heightfield of the new geometry, else None (unknown: use the y you were given)"""
        if self.ground_y is not None:
            return float(self.ground_y)
        best = None
        for (pos, part) in self._hf:
            xs, zs, H = part['xs'], part['zs'], part['heights']
            lx, lz = x - pos[0], z - pos[2]
            if not (xs[0] <= lx <= xs[-1] and zs[0] <= lz <= zs[-1]):
                continue
            i = max(0, min(len(xs) - 2, next((k for k in range(len(xs) - 1) if xs[k] <= lx <= xs[k + 1]), 0)))
            j = max(0, min(len(zs) - 2, next((k for k in range(len(zs) - 1) if zs[k] <= lz <= zs[k + 1]), 0)))
            tx = (lx - xs[i]) / max(xs[i + 1] - xs[i], 1e-9)
            tz = (lz - zs[j]) / max(zs[j + 1] - zs[j], 1e-9)
            h = (H[j][i] * (1 - tx) * (1 - tz) + H[j][i + 1] * tx * (1 - tz) + H[j + 1][i] * (1 - tx) * tz + H[j + 1][i + 1] * tx * tz)
            y = pos[1] + h
            if best is None or y > best:
                best = y
        return best

    def gy(self, x, z, y=None):
        """the y a template should use as ground at (x, z): the given y when the user placed one, else the host's ground, else 20.0"""
        if y is not None:
            return float(y)
        g = self.ground_at(x, z)
        return 20.0 if g is None else g

    # ---------------------------------------------------------------- free ground (the old World)
    def reserve(self, x, z, hx, hz, label):
        self.reserved.append((x - hx, z - hz, x + hx, z + hz, label))

    def inside(self, x, z, margin=0.0):
        a = self.area
        return a[0] + margin <= x <= a[2] - margin and a[1] + margin <= z <= a[3] - margin

    def free(self, x, z, margin=1.2, taken=(), min_sep=0.0):
        if not self.inside(x, z, margin):
            return False
        for (x0, z0, x1, z1, _l) in self.obst:
            if x0 - margin <= x <= x1 + margin and z0 - margin <= z <= z1 + margin:
                return False
        for (x0, z0, x1, z1, _l) in self.reserved:
            if x0 <= x <= x1 and z0 <= z <= z1:
                return False
        for (tx, tz) in taken:
            if (tx - x) ** 2 + (tz - z) ** 2 < min_sep ** 2:
                return False
        return True

    def snap(self, x, z, margin=1.2, taken=(), min_sep=0.0, step=0.5, maxr=40.0):
        """nearest free grid spot to (x, z) (ring search, deterministic)"""
        if self.free(x, z, margin, taken, min_sep):
            return x, z
        r = step
        maxr = max(maxr, 1.2 * self.half)
        while r <= maxr:
            n = max(8, int(2 * math.pi * r / step))
            best = None
            for k in range(n):
                a = 2 * math.pi * k / n
                px, pz = x + r * math.cos(a), z + r * math.sin(a)
                if self.free(px, pz, margin, taken, min_sep):
                    d = (px - x) ** 2 + (pz - z) ** 2
                    if best is None or d < best[0]:
                        best = (d, round(px, 2), round(pz, 2))
            if best:
                return best[1], best[2]
            r += step
        raise RuntimeError('no free ground near (%.1f, %.1f) in host %s' % (x, z, self.id))

    def fit(self, pts, region, margin=1.2, min_sep=3.0, keep_order=True):
        """Fit a template point cloud [(x, z)...] (old map coordinates) into `region` (WORLD rect x0, z0, x1, z1): uniform scale + translation so
        its bounding box fills the region, then every point snaps to free ground with at least min_sep m to the others."""
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        bx0, bx1, bz0, bz1 = min(xs), max(xs), min(zs), max(zs)
        rw, rh = region[2] - region[0], region[3] - region[1]
        s = min(rw / max(bx1 - bx0, 1e-6), rh / max(bz1 - bz0, 1e-6))
        ox = (region[0] + region[2]) / 2 - s * (bx0 + bx1) / 2
        oz = (region[1] + region[3]) / 2 - s * (bz0 + bz1) / 2
        out, taken = [], []
        for (x, z) in pts:
            tx, tz = self.snap(ox + s * x, oz + s * z, margin, taken, min_sep)
            out.append((tx, tz)); taken.append((tx, tz))
        return out

    # ---------------------------------------------------------------- reachability (BFS over the obstacle footprints)
    def reach(self, start, targets, radius=0.6, cell=0.25):
        """BFS from `start` (x, z) over free cells of the area; returns {name: path metres or None} for each target (name, x, z, size).
        Obstacles are the footprints known to the host (new-geometry models / listed obstacles). A host without obstacle data reports everything reachable."""
        import collections
        a = self.area
        pad = 1.0
        x0, z0 = a[0] - pad, a[1] - pad
        n_x = int((a[2] - a[0] + 2 * pad) / cell) + 1
        n_z = int((a[3] - a[1] + 2 * pad) / cell) + 1
        blocked = [bytearray(n_z) for _ in range(n_x)]
        for (ox0, oz0, ox1, oz1, _l) in self.obst:
            ia, ib = int((ox0 - radius - x0) / cell), int((oz0 - radius - z0) / cell)
            ic, id_ = int((ox1 + radius - x0) / cell), int((oz1 + radius - z0) / cell)
            for i in range(max(ia, 0), min(ic, n_x - 1) + 1):
                row = blocked[i]
                for j in range(max(ib, 0), min(id_, n_z - 1) + 1):
                    row[j] = 1
        cellof = lambda x, z: (int((x - x0) / cell), int((z - z0) / cell))
        s = cellof(*start)
        dist = {s: 0}
        q = collections.deque([s])
        while q:
            i, j = q.popleft()
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                k = (i + di, j + dj)
                if 0 <= k[0] < n_x and 0 <= k[1] < n_z and k not in dist and not blocked[k[0]][k[1]]:
                    dist[k] = dist[(i, j)] + 1
                    q.append(k)
        res = {}
        for (name, gx, gz, size) in targets:
            h, best = size / 2.0, None
            xx = gx - h
            while xx <= gx + h:
                zz = gz - h
                while zz <= gz + h:
                    c = cellof(xx, zz)
                    if c in dist and (best is None or dist[c] < best):
                        best = dist[c]
                    zz += cell
                xx += cell
            res[name] = None if best is None else best * cell
        return res

    def clearance(self, x, z):
        """distance from (x, z) to the nearest obstacle footprint (99 when there is none)"""
        dm = 99.0
        for (a1, b1, c1, d1, _l) in self.obst:
            dx = max(a1 - x, 0, x - c1); dz = max(b1 - z, 0, z - d1)
            dm = min(dm, (dx * dx + dz * dz) ** 0.5)
        return dm


def load_project_hosts(project, base_dir='.'):
    """-> (new_map_params | None, {host id: Host}) for a project dict. The new-map params are inline ("new_map") or a file ("new_map_path",
    relative to base_dir)."""
    nm = project.get('new_map')
    if nm is None and project.get('new_map_path'):
        p = project['new_map_path']
        p = p if os.path.isabs(p) else os.path.join(base_dir, p)
        nm = json.load(open(p, encoding='utf-8'))
    hosts = {}
    for hd in project.get('hosts', []):
        mp = None
        if hd.get('kind', NEW_MAP) == NEW_MAP:
            if nm is None:
                raise HostError('host %s is a new_map host but the project has no "new_map" params' % hd.get('id'))
            mp = nm['maps'][hd.get('map_index', 0)]
        h = Host(hd, mp)
        if h.id in hosts:
            raise HostError('duplicate host id %s' % h.id)
        hosts[h.id] = h
    return nm, hosts
