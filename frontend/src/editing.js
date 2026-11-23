// Pure editing helpers for the level editor tools: group transforms, snapping, align and distribute, drop to ground,
// scatter, prefabs (also the copy buffer), find and replace, and the project-only editor data (layers, bookmarks,
// notes). Everything here returns new level ops (or new data); nothing reads the screen. A screen applies the result
// with ONE commit, so every tool is one undo step.
import { opsMove, opsSet, opsDelete, newUid } from './project.js'
import { quatFromYaw, yawDeg, r3 } from './coords.js'
import { keyOf } from './view.js'

// ------------------------------------------------------------------ labels (the edit list names what moved)
export const labelOf = e => e.name || (e.type || '').replace(/\(.*\)/, '') + ' ' + (e.node || '')
export const withLabel = (ops, e) => ops.map(o => (!o.uid && e.target && o.node === e.target.node && o.frag === e.target.frag && !o.label)
  ? { ...o, label: labelOf(e) } : o)

// ------------------------------------------------------------------ quaternions in game space ([x, y, z, w])
export const qmul = (a, b) => [
  a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
  a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
  a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
  a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]]
export const qnorm = q => { const n = Math.hypot(...q) || 1; return q.map(v => Math.round(v / n * 1e6) / 1e6) }

// ------------------------------------------------------------------ applying many edits to ops
export function moveMany(ops, moves) {
  let out = ops
  for (const m of moves) out = withLabel(opsMove(out, m.e.target, r3(m.pos), (m.rot || m.e.rot).map(v => Math.round(v * 1e6) / 1e6)), m.e)
  return out
}
export function setMany(ops, ents, prop, value) {
  let out = ops
  for (const e of ents) out = withLabel(opsSet(out, e.target, prop, value), e)
  return out
}
export function deleteMany(ops, ents, mode) {
  let out = ops
  for (const e of ents) out = withLabel(opsDelete(out, e.target, mode), e)
  return out
}
export const editable = ents => ents.filter(e => e.ed && !e.deleted)

// ------------------------------------------------------------------ group transforms
export function centroid(ents) {
  if (!ents.length) return [0, 0, 0]
  return [0, 1, 2].map(i => ents.reduce((a, e) => a + e.pos[i], 0) / ents.length)
}
export function translateMoves(ents, d) {
  return ents.map(e => ({ e, pos: [e.pos[0] + d[0], e.pos[1] + d[1], e.pos[2] + d[2]] }))
}
// turn a group about the up axis around a pivot; deg in the game's sense (the same as the Turn field)
export function rotateMoves(ents, pivot, deg) {
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), q = quatFromYaw(deg)
  return ents.map(e => {
    const dx = e.pos[0] - pivot[0], dz = e.pos[2] - pivot[2]
    return { e, pos: [pivot[0] + dx * c + dz * s, e.pos[1], pivot[2] - dx * s + dz * c], rot: qnorm(qmul(q, e.rot)) }
  })
}

// ------------------------------------------------------------------ snapping
export const snapNum = (v, step) => (step > 0 ? Math.round(v / step) * step : v)
export const snapXZ = (p, grid) => (grid > 0 ? [snapNum(p[0], grid), p[1], snapNum(p[2], grid)] : p)
export const snapYaw = (deg, step) => (step > 0 ? Math.round(deg / step) * step : deg)
export const SNAP_GRIDS = [0, 0.25, 0.5, 1, 2, 5, 10]
export const SNAP_ANGLES = [0, 5, 15, 45, 90]
export const defaultSnap = () => ({ grid: 0, angle: 0, mode: 'surface' })     // surface | ground | free

// ------------------------------------------------------------------ align and distribute (by position, one axis)
const AX = { x: 0, y: 1, z: 2 }
export function alignMoves(ents, axis, mode) {
  const i = AX[axis]
  if (ents.length < 2) return []
  const vs = ents.map(e => e.pos[i])
  const t = mode === 'min' ? Math.min(...vs) : mode === 'max' ? Math.max(...vs) : (Math.min(...vs) + Math.max(...vs)) / 2
  return ents.filter(e => Math.abs(e.pos[i] - t) > 1e-6).map(e => { const p = e.pos.slice(); p[i] = t; return { e, pos: p } })
}
export function distributeMoves(ents, axis) {
  const i = AX[axis]
  if (ents.length < 3) return []
  const s = ents.slice().sort((a, b) => a.pos[i] - b.pos[i])
  const lo = s[0].pos[i], hi = s[s.length - 1].pos[i], step = (hi - lo) / (s.length - 1)
  return s.slice(1, -1).map((e, k) => { const p = e.pos.slice(); p[i] = lo + step * (k + 1); return { e, pos: p } })
    .filter(m => Math.abs(m.pos[i] - m.e.pos[i]) > 1e-6)
}
// drop onto what is below: groundY(x, z, e) gives the height or null
export function dropMoves(ents, groundY) {
  const out = []
  for (const e of ents) {
    const y = groundY(e.pos[0], e.pos[2], e)
    if (y != null && Math.abs(y - e.pos[1]) > 1e-3) out.push({ e, pos: [e.pos[0], y, e.pos[2]] })
  }
  return out
}

// ------------------------------------------------------------------ scatter
export function rng(seed) {
  let a = seed >>> 0
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}
export const SCATTER_MAX = 400          // objects in one stroke (a guard, the ledger shows the rest)
// one brush stamp: objects per square metre in a disc; positions keep `gap` metres from `taken`
export function scatterStamp({ center, radius, density, yawRandom = true, scale = [1, 1], gap = 0, taken = [], rand = Math.random, max = SCATTER_MAX }) {
  const n = Math.min(max, Math.max(density * Math.PI * radius * radius, 0))
  const count = Math.floor(n) + (rand() < n - Math.floor(n) ? 1 : 0)
  const out = []
  for (let tries = 0; out.length < count && tries < count * 12; tries += 1) {
    const r = radius * Math.sqrt(rand()), a = rand() * Math.PI * 2
    const p = [center[0] + r * Math.cos(a), center[1], center[2] + r * Math.sin(a)]
    if (gap > 0 && [...taken, ...out.map(o => o.pos)].some(q => Math.hypot(q[0] - p[0], q[2] - p[2]) < gap)) continue
    out.push({ pos: p, yaw: yawRandom ? rand() * 360 : 0, scale: scale[0] + (scale[1] - scale[0]) * rand() })
  }
  return out
}

// ------------------------------------------------------------------ add ops from entities, prefabs and the copy buffer
export const whereOf = cat => (['pickup', 'weapon', 'character', 'vehicle', 'route'].includes(cat) ? 'mission' : 'section')

// what an entity needs to be added again: the template to clone, its box size and how it looks
export function entityTemplate(e) {
  if (e.isNew && e.op) {
    return { template: e.op.template, set: { ...(e.op.set || {}) }, view: { ...(e.op.view || {}) }, name: e.op.view?.name || e.name, cat: e.cat }
  }
  const set = e.size ? { width: e.size[0], height: e.size[1], length: e.size[2] } : {}
  return { template: { entry: e.target.entry, frag: e.target.frag, node: e.target.node }, set,
    view: { type: e.type, cat: e.cat, size: e.size, sub: e.sub, model: e.model, radius: e.radius, kindLabel: 'copy', name: e.name }, name: e.name, cat: e.cat }
}

const safeName = s => String(s || 'copy').replace(/[^A-Za-z0-9_ ]/g, '').trim().slice(0, 32) || 'copy'

// one add op. `at` = {pos, yaw?, rot?}; `scale` scales a box size (the engine has no scale on models)
export function addOpFrom(tpl, entry, at, { uid = newUid(), scale = 1, prefix } = {}) {
  const set = { ...(tpl.set || {}) }
  let view = { ...(tpl.view || {}) }
  if (scale !== 1 && set.width != null) {
    ;['width', 'height', 'length'].forEach(k => { set[k] = Math.max(0.05, Math.round(set[k] * scale * 100) / 100) })
    view = { ...view, size: [set.width, set.height, set.length] }
  }
  const rot = at.rot ? qnorm(at.rot) : at.yaw ? quatFromYaw(at.yaw) : [0, 0, 0, 1]
  return { op: 'add', uid, entry, template: tpl.template, name: `${prefix || safeName(tpl.name || view.kindLabel)}_${uid}`,
    pos: r3(at.pos), rot, set, view }
}

// An enemy is added as a whole fighter (body, weapon, a short path); `group: 'enemy'` tells the build to place it that way.
// The engine lowers a placeholder by ENEMY_DROP at its first frame, so the stored height is the floor plus that.
export const ENEMY_DROP = 1.07
export const enemySet = (row, extra = {}) => ({ Model: row.id, AISubType: row.ai, FactionID: row.side, Real_Active_Texture_Set: row.looks?.[0]?.id ?? 0, ...extra })
export function enemyOp(tpl, entry, at, row, { uid = newUid(), prefix = 'TODMS_enemy', weapon = 0, set = {} } = {}) {
  const st = enemySet(row, { FactionID: 9, WeaponSubType: weapon, ...set })
  const rot = at.rot ? qnorm(at.rot) : at.yaw ? quatFromYaw(at.yaw) : [0, 0, 0, 1]
  const pos = r3([at.pos[0], at.pos[1] + ENEMY_DROP, at.pos[2]])
  return { op: 'add', uid, entry, template: { entry: tpl.entry, frag: tpl.frag, node: tpl.node }, deep: true, group: 'enemy',
    name: `${prefix}_${uid}`, pos, rot, set: st,
    view: { type: 'character_placeholder(CharacterPlaceHolder)', cat: 'character', sub: { Model: st.Model, AISubType: st.AISubType, FactionID: st.FactionID, Real_Active_Texture_Set: st.Real_Active_Texture_Set, WeaponSubType: weapon },
      kindLabel: 'Enemy', name: row.name } }
}

// ---- prefabs: the selection relative to its own origin (centre on the ground plane, lowest point as height 0)
export function prefabFromEntities(ents, name) {
  const list = ents.filter(e => !e.deleted)
  const c = centroid(list), y0 = Math.min(...list.map(e => e.pos[1]))
  const items = list.map(e => ({ ...entityTemplate(e), dpos: r3([e.pos[0] - c[0], e.pos[1] - y0, e.pos[2] - c[2]]), rot: e.rot, where: whereOf(e.cat) }))
  const ext = Math.max(1, ...items.map(i => Math.hypot(i.dpos[0], i.dpos[2])))
  return { id: 'pf' + newUid(), name: name || 'Prefab', created: new Date().toISOString().slice(0, 10), items, extent: Math.round(ext * 10) / 10 }
}
// add ops for stamping a prefab at `origin` turned by `yaw`; entryFor(item) picks the block that takes it
export function stampOps(prefab, origin, yaw, entryFor, { scale = 1 } = {}) {
  const a = (yaw || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), q = quatFromYaw(yaw || 0)
  const out = []
  for (const it of prefab.items) {
    const entry = entryFor(it)
    if (!entry) continue
    const [dx, dy, dz] = it.dpos
    const pos = [origin[0] + dx * c + dz * s, origin[1] + dy, origin[2] - dx * s + dz * c]
    out.push(addOpFrom(it, entry, { pos, rot: yaw ? qmul(q, it.rot || [0, 0, 0, 1]) : it.rot }, { scale }))
  }
  return out
}

// ------------------------------------------------------------------ find and replace (the kind a pickup, weapon or vehicle is)
export const KIND_KEYS = ['GoodieSubType', 'WeaponSubType', 'VehicleSubType']
export function kindCounts(view, key) {
  const m = new Map()
  for (const e of view.list) if (e.sub && e.sub[key] != null && !e.deleted && e.ed) m.set(e.sub[key], (m.get(e.sub[key]) || 0) + 1)
  return m
}
export function replaceKind(ops, view, key, from, to) {
  let out = ops, n = 0
  for (const e of view.list) {
    if (!e.ed || e.deleted || !e.sub || e.sub[key] !== from) continue
    if (e.isNew) out = out.map(o => (o.op === 'add' && o.uid === e.target.uid) ? { ...o, set: { ...(o.set || {}), [key]: to } } : o)
    else out = withLabel(opsSet(out, e.target, key, to), e)
    n += 1
  }
  return { ops: out, count: n }
}

// ------------------------------------------------------------------ project-only editor data (never built into the game)
export const editorOf = p => p?.editor || {}
export const withEditor = (p, patch) => ({ ...p, editor: { ...editorOf(p), ...patch } })
export const newId = pre => pre + newUid()

export const layersOf = p => editorOf(p).layers || []
export const assignOf = p => editorOf(p).assign || {}
export function addLayer(p, name) {
  const l = { id: newId('ly'), name: name || 'Layer ' + (layersOf(p).length + 1), hidden: false, locked: false }
  return withEditor(p, { layers: [...layersOf(p), l] })
}
export const patchLayer = (p, id, patch) => withEditor(p, { layers: layersOf(p).map(l => l.id === id ? { ...l, ...patch } : l) })
export function removeLayer(p, id) {
  const assign = Object.fromEntries(Object.entries(assignOf(p)).filter(([, v]) => v !== id))
  return withEditor(p, { layers: layersOf(p).filter(l => l.id !== id), assign })
}
export function assignLayer(p, ents, id) {
  const assign = { ...assignOf(p) }
  for (const e of ents) { if (id) assign[keyOf(e.target)] = id; else delete assign[keyOf(e.target)] }
  return withEditor(p, { assign })
}
export const layerOfEntity = (p, e) => layersOf(p).find(l => l.id === assignOf(p)[keyOf(e.target)])

export const bookmarksOf = p => editorOf(p).bookmarks || []
export const notesOf = p => editorOf(p).notes || []
export const addBookmark = (p, name, pos, target) => withEditor(p, { bookmarks: [...bookmarksOf(p), { id: newId('bm'), name: name || 'Spot ' + (bookmarksOf(p).length + 1), pos, target }] })
export const removeBookmark = (p, id) => withEditor(p, { bookmarks: bookmarksOf(p).filter(b => b.id !== id) })
export const renameBookmark = (p, id, name) => withEditor(p, { bookmarks: bookmarksOf(p).map(b => b.id === id ? { ...b, name } : b) })
export const addNote = (p, pos, text) => withEditor(p, { notes: [...notesOf(p), { id: newId('nt'), pos, text: text || 'Note' }] })
export const patchNote = (p, id, patch) => withEditor(p, { notes: notesOf(p).map(n => n.id === id ? { ...n, ...patch } : n) })
export const removeNote = (p, id) => withEditor(p, { notes: notesOf(p).filter(n => n.id !== id) })

// ------------------------------------------------------------------ the copy buffer (between maps and projects)
export function clipFromEntities(ents) {
  const p = prefabFromEntities(ents, 'Copy')
  return { ...p, id: 'clip', origin: centroid(ents.filter(e => !e.deleted)) }
}
export const yawOf = e => yawDeg(e.rot)
