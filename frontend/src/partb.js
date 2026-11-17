// Companion tools part B: pure helpers for the route (nav), mission and section ops of the mod.
// The op grammar is the core's (backend/todct nav.py, missions.py, sections.py).

export const SHARED = 'data_pc/overdose_the_game/overdose/shared/'
export const short = e => (e || '').replace(/\\/g, '/').split('/').pop()
export const fshort = f => (f || '').replace(/\\/g, '/').split('/').pop()

let n = Date.now() % 46656
export function newId(prefix) { n += 1; return `${prefix}${n.toString(36)}` }

export const isNew = x => typeof x === 'string' && !/^0x/i.test(x)

export const KIND_COLOR = {
  goto: '#ff9f1c', patrol: '#ff70a6', vehicle: '#a0703c', ai_track: '#c08a4a', track: '#9aa5b1',
  signposts: '#5ad06a', traffic: '#4c9be8', navblocks: '#d633c8', neighborhoods: '#9d6bff',
}
// colour-blind safe set (Okabe-Ito), used when that setting is on; each kind also has a letter, a point shape and a line pattern
export const KIND_COLOR_CB = {
  goto: '#e69f00', patrol: '#cc79a7', vehicle: '#d55e00', ai_track: '#f0e442', track: '#bbbbbb',
  signposts: '#009e73', traffic: '#56b4e9', navblocks: '#0072b2', neighborhoods: '#ffffff',
}
export const KIND_MARK = {
  goto: { letter: 'G', glyph: '●', shape: 'sphere', dash: null }, patrol: { letter: 'P', glyph: '■', shape: 'box', dash: [1.2, 0.8] },
  vehicle: { letter: 'V', glyph: '◆', shape: 'diamond', dash: null }, ai_track: { letter: 'A', glyph: '◆', shape: 'diamond', dash: [1.2, 0.8] },
  track: { letter: 'T', glyph: '▲', shape: 'cone', dash: [0.4, 0.8] }, signposts: { letter: 'S', glyph: '●', shape: 'sphere', dash: [0.4, 0.8] },
  traffic: { letter: 'R', glyph: '■', shape: 'box', dash: null }, navblocks: { letter: 'N', glyph: '▣', shape: 'box', dash: null },
  neighborhoods: { letter: 'H', glyph: '○', shape: 'sphere', dash: [2, 1] },
}
export const kindColor = (kind, cb) => (cb ? KIND_COLOR_CB : KIND_COLOR)[kind] || '#cccccc'
export const KIND_LABEL = {
  goto: 'GotoPath (enemy entry run)', patrol: 'Patrol path', vehicle: 'Vehicle track', ai_track: 'AI vehicle track',
  track: 'Track (camera, plane, door)', signposts: 'Pedestrian SignPosts', traffic: 'Traffic points',
  navblocks: 'NavBlock boxes', neighborhoods: 'Neighborhood circles',
}

// replace ops matching pred by op (or append it)
export function upsert(ops, pred, op) {
  const out = ops.filter(o => !pred(o))
  return op ? [...out, op] : out
}

// ------------------------------------------------------------------ routes
export function navMove(ops, route, point, pos) {
  if (point.new) return ops.map(o => (o.op === 'insert_point' || o.op === 'add_signpost' || o.op === 'add_traffic_point' ||
    o.op === 'add_navblock') && o.id === point.node ? { ...o, pos } : o)
  const frag = point.frag || route.frag
  return upsert(ops, o => o.op === 'move' && o.entry === route.entry && o.node === point.node,
    { op: 'move', entry: route.entry, frag, node: point.node, pos })
}

export function navInsert(ops, route, idx, pos) {
  // insert after point idx (null = append at the end)
  const pts = route.points
  const before = idx == null || idx + 1 >= pts.length ? null : pts[idx + 1].node
  const like = pts.length ? pts[idx == null ? pts.length - 1 : idx].node : undefined
  const id = newId('np')
  return { ops: [...ops, { op: 'insert_point', id, entry: route.entry, frag: route.frag, track: route.node, before,
    pos, ...(like && !isNew(like) ? { like } : {}) }], id }
}

export function navRemove(ops, route, point) {
  if (point.new) {
    // drop the insert and every op that names the new point
    return ops.filter(o => o.id !== point.node && o.node !== point.node)
      .map(o => o.op === 'reorder' && o.track === route.node ? { ...o, points: o.points.filter(x => x !== point.node) } : o)
  }
  // first in the list: a later reorder of this track names the remaining points only
  return [{ op: 'remove_point', entry: route.entry, frag: route.frag, node: point.node },
    ...ops.map(o => o.op === 'reorder' && o.track === route.node ? { ...o, points: o.points.filter(x => x !== point.node) } : o)]
}

export function navReorder(ops, route, idx, d) {
  const seq = route.points.map(p => p.node)
  const j = idx + d
  if (j < 0 || j >= seq.length) return ops
  ;[seq[idx], seq[j]] = [seq[j], seq[idx]]
  return upsert(ops, o => o.op === 'reorder' && o.entry === route.entry && o.track === route.node,
    { op: 'reorder', entry: route.entry, frag: route.frag, track: route.node, points: seq })
}

export function navLink(ops, route, a, b, on) {
  const frag = a.frag || route.frag
  const rest = ops.filter(o => !((o.op === 'link' || o.op === 'unlink') && o.entry === route.entry &&
    ((o.a === a.node && o.b === b.node) || (o.a === b.node && o.b === a.node))))
  return [...rest, { op: on ? 'link' : 'unlink', entry: route.entry, frag, a: a.node, b: b.node }]
}

export function navSet(ops, route, point, prop, value) {
  const key = point ? point.node : route.node
  const frag = (point && point.frag) || route.frag
  if (isNew(key)) {
    return upsert(ops, o => o.op === 'set' && o.id === key && o.prop === prop,
      { op: 'set', entry: route.entry, frag, id: key, prop, value })
  }
  return upsert(ops, o => o.op === 'set' && o.node === key && o.prop === prop && o.entry === route.entry,
    { op: 'set', entry: route.entry, frag, node: key, prop, value })
}

export function describeNav(o) {
  switch (o.op) {
    case 'move': return `Move ${o.node} (${short(o.entry)})`
    case 'insert_point': return `New point ${o.id} in ${o.track} ${o.before ? 'before ' + o.before : 'at the end'}`
    case 'remove_point': return `Detach point ${o.node} from its route`
    case 'reorder': return `Reorder ${o.track}: ${o.points.join(' > ')}`
    case 'link': case 'unlink': return `${o.op === 'link' ? 'Link' : 'Unlink'} SignPosts ${o.a} - ${o.b}`
    case 'set': return `Set ${o.prop} = ${JSON.stringify(o.value)} on ${o.node || o.id}`
    case 'add_navblock': return `New NavBlock ${o.id} ${o.size.join(' x ')} m`
    case 'retire_navblock': return `Retire NavBlock ${o.node}`
    default: return o.op
  }
}

// ------------------------------------------------------------------ missions
export function describeMission(o) {
  switch (o.op) {
    case 'set': return `Set ${o.prop} = ${JSON.stringify(o.value)} on ${o.node || o.id}`
    case 'rewire': return `Rewire action ${o.action} to trigger ${o.to.node}`
    case 'retarget': return `Retarget ${o.action} -> "${o.target}"`
    case 'add_trigger': return `New trigger ${o.name || o.id} (${o.template})`
    case 'add_action': return `New action ${o.action} on ${typeof o.root === 'string' ? o.root : o.root.node}`
    case 'disable_trigger': return `Disable trigger ${o.node}`
    default: return o.op
  }
}

// ------------------------------------------------------------------ sections
export function describeSection(o) {
  switch (o.op) {
    case 'set_teleport': return `Empty Teleport_to of ${o.node} (${short(o.entry)})`
    case 'move_loader': return `Move loader ${o.node} to ${o.pos.map(v => v.toFixed(1)).join(', ')}`
    case 'add_section': return `New section SUBMAP${String(o.new_index).padStart(2, '0')} from ${short(o.source_submap)}`
    default: return o.op
  }
}

export function partBCount(p) {
  return (p.nav || []).length + (p.missions || []).length + (p.sections || []).length
}
