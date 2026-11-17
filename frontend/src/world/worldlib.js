// Pure helpers of the New maps world screens (no React, no DOM): atlas anchors, footprints, snapping, links, the entrance
// table and the readiness summary. Node tests: frontend/tests/world.test.mjs.
// Coordinates: game metres, (x, z) on the ground. The atlas is an EDITOR layout: every map keeps its own space in the game.

export const SAFE = 16000                        // M0 Q7: beyond this a coordinate loses precision
export const SIZES = { small: 80, medium: 160, large: 300 }
export const short = e => String(e || '').replace(/\\/g, '/').split('/').pop().toLowerCase()
export const mapIdOf = block => { const m = short(block).match(/(?:^|_)map(\d+)(?:_|$)/); return m ? 'map' + m[1] : null }
const r1 = v => Math.round(v * 10) / 10

// ---- footprints
// the box of a new map in ITS OWN space, [x0, z0, x1, z1]
export function ownRect(m) {
  const t = m?.terrain
  if (t) {
    const cell = t.cell ?? 2
    const [nx, nz] = t.size || [60, 60]
    const o = t.origin || [-nx * cell / 2, -nz * cell / 2]
    return [o[0], o[1], o[0] + nx * cell, o[1] + nz * cell]
  }
  const s = SIZES[m?.card?.size] || 300
  const a = m?.arrival?.pos || [0, 0, 0]
  return [a[0] - s / 2, a[2] - s / 2, a[0] + s / 2, a[2] + s / 2]
}
export const rectSize = r => [r[2] - r[0], r[3] - r[1]]
export const rectCentre = r => [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]
export const rotate = ([x, z], yaw) => { const a = yaw * Math.PI / 180, c = Math.cos(a), s = Math.sin(a); return [x * c + z * s, -x * s + z * c] }
// the footprint corners in the atlas, for a map anchored at pos and turned by yaw degrees
export function atlasCorners(rect, pos, yaw = 0) {
  const [w, l] = rectSize(rect)
  return [[-w / 2, -l / 2], [w / 2, -l / 2], [w / 2, l / 2], [-w / 2, l / 2]].map(p => { const q = rotate(p, yaw); return [pos[0] + q[0], pos[1] + q[1]] })
}
export const aabb = corners => [Math.min(...corners.map(c => c[0])), Math.min(...corners.map(c => c[1])), Math.max(...corners.map(c => c[0])), Math.max(...corners.map(c => c[1]))]
export const overlaps = (a, b) => !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1])

// where a new map sits in the layout: its stored anchor, else a slot east of the map of its first entrance (used = slots taken per map id)
export function anchorOf(m, i, ships = {}, used = {}) {
  const a = m?.atlas
  if (a?.pos) return { pos: a.pos, yaw: a.yaw || 0, stored: true }
  const id = mapIdOf(entriesOf(m)[0]?.block || m?.host?.block)
  const box = ships[id]
  const [w, l] = rectSize(ownRect(m))
  if (box) {
    const k = used[id] || 0
    used[id] = k + 1
    return { pos: [Math.round(box[2] + 300 + w / 2), Math.round((box[1] + box[3]) / 2 + k * Math.max(520, l + 220))], yaw: 0, stored: false }
  }
  return { pos: [17000 + 600 * i, 0], yaw: 0, stored: false }
}
// a point in a new map's own space -> the atlas (anchor = the map's anchor)
export function toAtlas(m, anchor, p) {
  const c = rectCentre(ownRect(m))
  const q = rotate([p[0] - c[0], p[2] - c[1]], anchor.yaw)
  return [anchor.pos[0] + q[0], anchor.pos[1] + q[1]]
}

// ---- the placement ghost: snap a footprint centre to neighbour edges (within `dist` m) and the angle to 15 degrees
export function snapFootprint(pos, size, others, dist = 40) {
  let [x, z] = pos
  const hw = size[0] / 2, hl = size[1] / 2
  const guides = []
  let bx = null, bz = null
  for (const o of others) {
    for (const ex of [o[0], o[2]]) for (const mine of [x - hw, x + hw]) {
      const d = ex - mine
      if (Math.abs(d) <= dist && (bx === null || Math.abs(d) < Math.abs(bx.d))) bx = { d, at: ex }
    }
    for (const ez of [o[1], o[3]]) for (const mine of [z - hl, z + hl]) {
      const d = ez - mine
      if (Math.abs(d) <= dist && (bz === null || Math.abs(d) < Math.abs(bz.d))) bz = { d, at: ez }
    }
  }
  if (bx) { x += bx.d; guides.push({ axis: 'x', at: bx.at }) }
  if (bz) { z += bz.d; guides.push({ axis: 'z', at: bz.at }) }
  return { pos: [r1(x), r1(z)], guides }
}
export const snapYaw = (yaw, step = 15) => { let y = Math.round(yaw / step) * step; y = ((y + 180) % 360 + 360) % 360 - 180; return y }
export const compassOf = yaw => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][((Math.round(yaw / 45) % 8) + 8) % 8]

// the coordinate guard: -> { out: bool, over: [indices of maps whose footprint overlaps this one] }
export function guard(rect, others) {
  const out = Math.max(...rect.map(Math.abs)) > SAFE
  return { out, over: others.map((o, i) => overlaps(rect, o) ? i : -1).filter(i => i >= 0) }
}

// ---- entrances
export const entriesOf = m => [...(m?.entry ? [{ ...m.entry, id: m.entry.id || 'entry' }] : []), ...(m?.entries || [])]
export const yawOfQuat = q => { if (!q) return 0; const [x, y, z, w] = q; return Math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / Math.PI }
export const quatOfYaw = yaw => [0, Math.sin(yaw * Math.PI / 360), 0, Math.cos(yaw * Math.PI / 360)]
// the arrival of an entrance: its own, else the map's
export const arriveOf = (m, e) => e.arrive || { pos: m.arrival?.pos, yaw: yawOfQuat(m.arrival?.orient) }
export const isLocked = e => !!e.lock
// the live rule: a map needs one unlocked way out (a return spot, or an entrance with its own way back that is not one-way)
export function wayOut(m) {
  if (m.placement === 'extension') return true
  return !!m.return || entriesOf(m).some(e => e.back && !e.one_way)
}
// vehicle entrances need a box of at least 16 x 8 x 6 m
export const VEHICLE_MIN = [16, 6, 8]
export const vehicleOk = e => !e.vehicle || ((e.size || [12, 6, 2])[0] >= 16 && (e.size || [12, 6, 2])[2] >= 8)
export function modeOf(e) {
  const bits = [e.vehicle ? 'vehicle' : 'foot', e.prompt === 'use' ? 'use' : 'touch']
  if (e.one_way) bits.push('one-way')
  return bits.join(' / ')
}
// one row per link of a project: source, destination, mode, lock, way back
export function entranceRows(params, label = x => x) {
  const rows = []
  ;(params?.maps || []).forEach((m, mi) => {
    if (m.placement === 'extension') {
      const h = m.host || {}
      rows.push({ id: 'host:' + mi, map: mi, entry: null, source: label(h.block), dest: m.name, mode: h.prompt === 'use' ? 'foot / use' : 'foot / touch', lock: null, back: 'yes' })
      return
    }
    entriesOf(m).forEach((e, ei) => rows.push({ id: mi + ':' + ei, map: mi, entry: ei, source: label(e.block), dest: m.name + (e.arrive_at ? ' / ' + e.arrive_at : ''),
      mode: modeOf(e), lock: e.lock ? e.lock.mission : null, back: e.one_way ? 'no' : (e.back || m.return) ? 'yes' : 'no', e }))
  })
  return rows
}
// the host-side box of an entrance and the way back, as boxes for the overlay
export function pairBoxes(m, e) {
  const a = arriveOf(m, e)
  return { trigger: { pos: e.pos, size: e.size || [12, 6, 2], yaw: yawOfQuat(e.orient) }, arrival: a, back: e.back || m.return || null }
}

// ---- readiness: problems per map. items = world analysis items [{map, level, title}], global = the Problems list of the project
export function readiness(params, items = [], global = [], checks = []) {
  const maps = params?.maps || []
  return maps.map((m, i) => {
    const mine = items.filter(x => x.map === i)
    const own = []
    if (!wayOut(m)) own.push({ level: 'error', title: 'No unlocked way out' })
    entriesOf(m).forEach(e => { if (!vehicleOk(e)) own.push({ level: 'error', title: (e.id || 'Entrance') + ': a vehicle box needs 16 x 8 m' }) })
    const rows = [...own, ...mine]
    const errors = rows.filter(x => x.level === 'error').length + (i === 0 ? checks.filter(c => c.result && c.result !== 'PASS' && c.result !== 'WARN').length : 0)
    const warns = rows.filter(x => x.level === 'warn').length + (i === 0 ? checks.filter(c => c.result === 'WARN').length : 0)
    return { index: i, name: m.name, errors, warns, rows }
  })
}
export const blocked = (ready, global) => ready.some(r => r.errors > 0) || (global || []).some(p => p.level === 'error')

// the atlas stand-in of a shipped map: the cells of its blocks in the layout. bounds = /api/world/atlas `bounds`
export function standIn(bounds, mapId, layout) {
  const o = layout[mapId] || [0, 0]
  const cells = []
  let box = null
  for (const v of Object.values(bounds)) {
    if (v.map !== mapId) continue
    const b = [v.box[0] + o[0], v.box[1] + o[1], v.box[2] + o[0], v.box[3] + o[1]]
    if (v.kind === 'map') box = b
    for (const [i, j, n] of v.cells) cells.push([b[0] + i * v.cell + v.cell / 2, b[1] + j * v.cell + v.cell / 2, v.cell, n])
  }
  return { cells, box }
}
export const layoutEnd = (bounds, layout) => {
  let e = 0
  for (const v of Object.values(bounds)) { const o = layout[v.map] || [0, 0]; e = Math.max(e, v.box[2] + o[0]) }
  return Math.ceil(e / 100) * 100 + 400
}

// first guesses for a new extension section on a host: the footprint beside the host's objects, the loader boxes either side
export function boxAround(block, bounds) {
  const b = bounds?.[short(block)]?.box
  const plaza = short(block) === 'submap01_map02_lostoros_downtown.submap'
  const enter = plaza ? [-237, 2.5, -43.66] : b ? [Math.round((b[0] + b[2]) / 2), 0, Math.round((b[1] + b[3]) / 2)] : [0, 0, 0]
  const origin = b ? [Math.round(b[2] + 60), Math.round((b[1] + b[3]) / 2 - 60)] : [100, -60]
  return { enter, leave: [origin[0] + 12, 0.5, origin[1] + 60], origin }
}

// ---- where a problem is fixed: the area of the New maps screen and the build tool. Equal to NEWMAP_JUMP in backend/todms/problems.py.
const JUMP_RULES = [
  [/edge of view|seam|footprint|in the layout|safe box|neighbour|aligned|fog distance|differs from the next|road width differs/, ['atlas', null]],
  [/entrance|arrival|way back|portal|vehicle box|way out|trigger box|host section|loader box|return/, ['entrances', null]],
  [/minimap/, ['map', 'minimap']],
  [/quadtree|\bnodes?\b/, ['map', 'scatter']],
  [/road|traffic|bridge|ramp/, ['map', 'roads']],
  [/water|pond|kill|invisible wall|cliff|\bedges?\b/, ['map', 'edges']],
  [/tree|rock|bush|scatter|shipped/, ['map', 'scatter']],
  [/\blook\b|sun|ambient|fog|sky|light|screen/, ['map', 'look']],
  [/blockout|piece/, ['map', 'blockout']],
  [/section|loader/, ['map', 'sections']],
  [/picture|texture|material|paint/, ['map', 'paint']],
  [/triangle|ground|terrain|steep|collision|hull|vertices|sub-mesh/, ['map', 'terrain']],
]
export function jumpOf(text, where, map) {
  const j = { screen: 'newmaps' }
  const hay = String(text || '').toLowerCase()
  const w = String(where || '')
  if (/entrance/.test(w) || w === 'arrival') j.area = 'entrances'
  else if (/atlas|seam/.test(w)) j.area = 'atlas'
  else {
    const r = JUMP_RULES.find(([re]) => re.test(hay))
    if (r) { j.area = r[1][0]; if (r[1][1]) j.tool = r[1][1] }
  }
  if (map != null) j.map = map
  return j
}

// ---- labels that would sit on each other: the later one moves up (or down) to a free slot and gets a leader line.
// items [{id, x, z, label}] (the spot a label belongs to), minDx / minDz = the room one label needs, in metres of the view.
// -> [{id, x, z, lx, lz, moved}]; the first of two clashing labels keeps its place (sorted by id so the result does not depend on the order given)
export function declutter(items, minDx, minDz) {
  const placed = []
  const out = []
  const clash = (x, z) => placed.some(p => Math.abs(p.x - x) < minDx && Math.abs(p.z - z) < minDz)
  for (const it of [...items].sort((a, b) => (b.z - a.z) || (a.x - b.x) || String(a.id).localeCompare(String(b.id)))) {
    let lx = it.x, lz = it.z, k = 0
    while (clash(lx, lz) && k < 12) {
      k += 1
      const side = k % 2 === 1 ? 1 : -1
      lz = it.z + side * Math.ceil(k / 2) * minDz * 1.15
    }
    placed.push({ x: lx, z: lz })
    out.push({ id: it.id, x: it.x, z: it.z, lx, lz, moved: lx !== it.x || lz !== it.z })
  }
  return out
}
