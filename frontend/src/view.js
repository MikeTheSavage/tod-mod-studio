// Derive what the editor shows from the opened level (backend level JSON) plus the project's ops.
import * as THREE from 'three'
import { toView, quatToView, fromView, quatFromView } from './coords.js'

export const CATS = [
  ['pickup', 'Pickups and goodies', '#ffd23f', true],
  ['weapon', 'Weapon pickups', '#ff9f1c', true],
  ['character', 'Enemies and civilians', '#ef476f', true],
  ['vehicle', 'Vehicles', '#06d6a0', true],
  ['trigger', 'Trigger boxes', '#4cc9f0', true],
  ['wall', 'Invisible walls', '#f72585', true],
  ['navblock', 'Nav blockers', '#b5179e', true],
  ['route', 'Route points', '#80ed99', true],
  ['marker', 'Mission markers', '#ffbe0b', true],
  ['model', 'Level geometry', '#adb5bd', true],
  ['havoc', 'Destructible objects', '#e07a5f', true],
  ['light', 'Lights', '#fff3b0', false],
  ['sound', 'Sound', '#9d4edd', false],
  ['effect', 'Effects and particles', '#ff70a6', false],
  ['box', 'Other boxes', '#7f8c8d', false],
  ['logic', 'Logic and folders', '#6c757d', false],
]
export const CAT_COLOR = Object.fromEntries(CATS.map(c => [c[0], c[2]]))
// colour-blind safe colours (Okabe-Ito) for the kinds that matter most; the others keep their colour. Every kind also has its own 3D shape and a name in the lists.
export const CAT_COLOR_CB = { pickup: '#009e73', weapon: '#e69f00', character: '#cc79a7', vehicle: '#0072b2', trigger: '#56b4e9', wall: '#d55e00', navblock: '#f0e442', route: '#009e73', marker: '#f0e442', havoc: '#d55e00' }
export const cbOn = () => typeof document !== 'undefined' && document.documentElement.getAttribute('data-cb') === 'on'
export const catColor = cat => (cbOn() && CAT_COLOR_CB[cat]) || CAT_COLOR[cat]
export const CAT_LABEL = Object.fromEntries(CATS.map(c => [c[0], c[1]]))
export const GAMEPLAY = new Set(['pickup', 'weapon', 'character', 'vehicle', 'trigger', 'wall', 'navblock', 'route',
  'marker', 'havoc'])

export const keyOf = t => t.uid ? 'uid:' + t.uid : `${t.entry}|${t.frag}|${t.node}`

export function buildView(bundle, ops, modelFor) {
  const ents = new Map()
  const byTarget = new Map()
  const kids = new Map()
  if (!bundle) return { ents, list: [], links: [], byTarget }
  for (const L of bundle.levels) {
    const fn = Object.fromEntries(L.fragments.map(f => [f.k, f.name]))
    for (const e of L.entities) {
      const target = { entry: L.entry, frag: fn[e.k], node: e.node }
      const v = { ...e, entry: L.entry, level: L.key, target, base: e }
      ents.set(e.id, v)
      byTarget.set(keyOf(target), v)
      if (e.parent) {
        if (!kids.has(e.parent)) kids.set(e.parent, [])
        kids.get(e.parent).push(e.id)
      }
    }
  }
  const moved = new Map()
  for (const o of ops) {
    if (o.op === 'add') {
      const vw = o.view || {}
      const set = o.set || {}
      const id = 'new:' + o.uid
      const size = set.width != null ? [set.width, set.height, set.length] : vw.size
      const sub = { ...(vw.sub || {}) }
      for (const k of Object.keys(set)) if (k in sub || /SubType|CollisionFlags/.test(k)) sub[k] = set[k]
      ents.set(id, { id, isNew: true, entry: o.entry, target: { uid: o.uid }, type: vw.type, cat: vw.cat,
        name: o.name || vw.name, pos: o.pos, rot: o.rot || [0, 0, 0, 1], size, sub, model: vw.model || (modelFor && modelFor(vw.cat, sub)) || undefined,
        radius: vw.radius, ed: true, op: o, changed: true })
      byTarget.set(keyOf({ uid: o.uid }), ents.get(id))
      continue
    }
    const v = byTarget.get(keyOf(o))
    if (!v) continue
    const c = { ...v, changed: true }
    if (o.op === 'move') {
      if (o.pos) c.pos = o.pos
      if (o.rot) c.rot = o.rot
      moved.set(c.id, [v.pos, v.rot, c.pos, c.rot])
    } else if (o.op === 'set') {
      if (o.prop === 'name') c.name = o.value
      else if (['width', 'height', 'length'].includes(o.prop)) {
        const s = [...(c.size || [1, 1, 1])]
        s[['width', 'height', 'length'].indexOf(o.prop)] = o.value
        c.size = s
      } else c.sub = { ...(c.sub || {}), [o.prop]: o.value }
      c.props = { ...(c.props || {}), [o.prop]: o.value }
    } else if (o.op === 'delete') {
      c.deleted = o.mode || 'retire'
    }
    ents.set(c.id, c)
    byTarget.set(keyOf(o), c)
  }
  // children follow a moved parent in the view (the game composes parent * local)
  for (const [id, [p0, q0, p1, q1]] of moved) {
    const A0 = new THREE.Matrix4().compose(toView(p0), quatToView(q0), new THREE.Vector3(1, 1, 1))
    const A1 = new THREE.Matrix4().compose(toView(p1), quatToView(q1), new THREE.Vector3(1, 1, 1))
    const D = A1.multiply(A0.invert())
    const stack = [...(kids.get(id) || [])]
    while (stack.length) {
      const k = stack.pop()
      const e = ents.get(k)
      if (!e) continue
      if (!moved.has(k)) {
        const M = new THREE.Matrix4().compose(toView(e.pos), quatToView(e.rot), new THREE.Vector3(1, 1, 1))
        M.premultiply(D)
        const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3()
        M.decompose(p, q, s)
        ents.set(k, { ...e, pos: fromView(p), rot: quatFromView(q) })
      }
      stack.push(...(kids.get(k) || []))
    }
  }
  const links = []
  for (const L of bundle.levels) for (const l of L.links) links.push(l)
  return { ents, list: [...ents.values()], links, byTarget }
}

// Which loaded block may take new objects without shifting save indices: its last-instantiated fragment must be
// instanced once (the backend checks again when it builds).
export function addableBlocks(bundle) {
  if (!bundle) return []
  return bundle.levels.map(L => {
    const f = L.fragments.find(x => x.name === L.last_fragment)
    return { entry: L.entry, kind: L.kind, title: L.title, ok: !!f && f.inst === 1 }
  })
}
