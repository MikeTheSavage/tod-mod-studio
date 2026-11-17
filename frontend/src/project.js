// The mod being edited: level ops (the backend's build.py grammar) + data-editor values, with undo/redo.
import { useCallback, useEffect, useReducer } from 'react'

const KEY = 'todms.project.v1'

export function emptyProject() {
  return { id: null, name: 'My mod', author: '', description: '', level: [], data: {}, collision: [], models: [], textures: [], view: null }
}

function load() {
  try { const p = JSON.parse(localStorage.getItem(KEY)); if (p && p.level) return { collision: [], models: [], textures: [], ...p } } catch { /* first run */ }
  return emptyProject()
}

function reducer(s, a) {
  switch (a.type) {
    case 'commit': {                                  // new project state, undoable
      const past = [...s.past, s.project].slice(-200)
      return { project: a.project, past, future: [] }
    }
    case 'replace':                                   // not undoable (meta edits, loads)
      return { ...s, project: a.project }
    case 'load':
      return { project: a.project, past: [], future: [] }
    case 'undo':
      if (!s.past.length) return s
      return { project: s.past[s.past.length - 1], past: s.past.slice(0, -1), future: [s.project, ...s.future] }
    case 'redo':
      if (!s.future.length) return s
      return { project: s.future[0], past: [...s.past, s.project], future: s.future.slice(1) }
    default:
      return s
  }
}

export function useProject() {
  const [s, dispatch] = useReducer(reducer, null, () => ({ project: load(), past: [], future: [] }))
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(s.project)) } catch { /* private mode */ }
  }, [s.project])
  const commit = useCallback(p => dispatch({ type: 'commit', project: p }), [])
  const replace = useCallback(p => dispatch({ type: 'replace', project: p }), [])
  const loadProject = useCallback(p => dispatch({ type: 'load', project: p }), [])
  const undo = useCallback(() => dispatch({ type: 'undo' }), [])
  const redo = useCallback(() => dispatch({ type: 'redo' }), [])
  return { project: s.project, canUndo: s.past.length > 0, canRedo: s.future.length > 0,
           commit, replace, loadProject, undo, redo }
}

// ------------------------------------------------------------------ op helpers (pure)
const same = (o, t) => o.entry === t.entry && o.frag === t.frag && o.node === t.node

// target: {entry, frag, node} for a base entity, or {uid} for an added one
export function opsMove(ops, t, pos, rot) {
  if (t.uid) return ops.map(o => o.op === 'add' && o.uid === t.uid ? { ...o, pos, rot } : o)
  const i = ops.findIndex(o => o.op === 'move' && same(o, t))
  const m = { op: 'move', entry: t.entry, frag: t.frag, node: t.node, pos, rot }
  if (i >= 0) { const c = ops.slice(); c[i] = m; return c }
  return [...ops, m]
}

export function opsSet(ops, t, prop, value) {
  if (t.uid) {
    return ops.map(o => {
      if (o.op !== 'add' || o.uid !== t.uid) return o
      if (prop === 'name') return { ...o, name: value }
      return { ...o, set: { ...(o.set || {}), [prop]: value } }
    })
  }
  const i = ops.findIndex(o => o.op === 'set' && same(o, t) && o.prop === prop)
  const m = { op: 'set', entry: t.entry, frag: t.frag, node: t.node, prop, value }
  if (i >= 0) { const c = ops.slice(); c[i] = m; return c }
  return [...ops, m]
}

export function opsDelete(ops, t, mode) {
  if (t.uid) return ops.filter(o => !(o.op === 'add' && o.uid === t.uid))
  if (ops.some(o => o.op === 'delete' && same(o, t))) return ops
  return [...ops, { op: 'delete', entry: t.entry, frag: t.frag, node: t.node, mode }]
}

export function opsRestore(ops, t) {
  return ops.filter(o => !(o.op === 'delete' && same(o, t)))
}

let uidCounter = Date.now() % 100000
export function newUid() { uidCounter += 1; return 'n' + uidCounter.toString(36) }

export function describeOp(o) {
  const nm = o.view?.name || o.name || o.node || o.uid
  switch (o.op) {
    case 'move': return `Move ${o.label || o.node}`
    case 'set': return `Set ${o.prop} = ${JSON.stringify(o.value)} on ${o.label || o.node}`
    case 'delete': return `${o.mode === "remove" ? "Remove" : "Retire"} ${o.label || o.node}`
    case 'add': return `Add ${o.view?.kindLabel || o.view?.type || 'object'} ${o.name || ''} (${(o.entry || '').split('/').pop()})`
    default: return o.op
  }
}
