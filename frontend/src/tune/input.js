// Keyboard, mouse and the pad for the playground. One shared state object read every frame. The pad is the app's one
// controller (pad/padstore.js: dead zone, sensitivity, A/B swap, the simulator) and it plays only while the playground has focus.
import { useEffect, useRef } from 'react'
import { padState, getCfg, getMode } from '../pad/padstore.js'
import { curve } from '../pad/padlogic.js'

const BLOCK = new Set([' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'tab'])

// sticks lx ly (walk, steer), rx ry (aim, look), triggers lt rt (0..1), buttons a b x y lb rb; null when the playground has no focus
export function readPad() {
  const f = typeof document !== 'undefined' ? document.activeElement : null
  if (!f || !f.matches || !f.matches('[data-pad-ctx=play]')) return null
  const { held, axes } = padState(), cfg = getCfg()
  return { lx: axes.lx, ly: axes.ly, rx: curve(axes.rx, cfg.lookSens), ry: curve(axes.ry, cfg.lookSens) * (cfg.invertY ? -1 : 1),
    a: held.A, b: held.B, x: held.X, y: held.Y, lb: held.LB, rb: held.RB, lt: axes.lt, rt: axes.rt }
}

// el: ref to the element that takes the mouse. Returns a ref { keys, edge, nx, ny, down, right, inside, pad() }.
export function useInput(el) {
  const s = useRef({ keys: new Set(), edge: new Set(), nx: 0, ny: 0, down: false, right: false, inside: false, padEdge: {}, prevPad: {},
    key: k => s.current.keys.has(k), take: k => { const had = s.current.edge.has(k); s.current.edge.delete(k); return had } })
  useEffect(() => {
    const st = s.current
    // screenshot hook: ?keys=w,d holds those keys down from the start
    const pre = new URLSearchParams(location.search).get('keys')
    if (pre) pre.split(',').forEach(k => st.keys.add(k))
    const typing = e => /INPUT|TEXTAREA|SELECT/.test(e.target?.tagName || '')
    const kd = e => {
      if (typing(e) || e.ctrlKey || e.metaKey) return
      const k = e.key.toLowerCase()
      if (!st.keys.has(k)) st.edge.add(k)
      st.keys.add(k)
      if (BLOCK.has(k)) e.preventDefault()
    }
    const ku = e => { st.keys.delete(e.key.toLowerCase()) }
    const blur = () => { if (!pre) st.keys.clear(); st.down = false; st.right = false }
    window.addEventListener('keydown', kd); window.addEventListener('keyup', ku); window.addEventListener('blur', blur)
    const node = el.current
    if (node && getMode() === 'pad') node.focus?.({ preventScroll: true })      // a pad in the hand: the playground takes it at once
    const move = e => { const r = node.getBoundingClientRect(); st.nx = ((e.clientX - r.left) / r.width) * 2 - 1; st.ny = -(((e.clientY - r.top) / r.height) * 2 - 1); st.inside = true }
    const down = e => { move(e); if (e.button === 0) st.down = true; if (e.button === 2) st.right = true; node.focus?.({ preventScroll: true }) }
    const up = e => { if (e.button === 0) st.down = false; if (e.button === 2) st.right = false }
    const leave = () => { st.inside = false }
    const ctx = e => e.preventDefault()
    if (node) {
      node.addEventListener('pointermove', move); node.addEventListener('pointerdown', down); window.addEventListener('pointerup', up)
      node.addEventListener('pointerleave', leave); node.addEventListener('contextmenu', ctx)
    }
    return () => {
      window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku); window.removeEventListener('blur', blur)
      window.removeEventListener('pointerup', up)
      if (node) { node.removeEventListener('pointermove', move); node.removeEventListener('pointerdown', down); node.removeEventListener('pointerleave', leave); node.removeEventListener('contextmenu', ctx) }
    }
  }, [el])
  return s
}

// a gamepad button that went down since the last call (by name)
export function padPressed(inp, pad, name) {
  const was = inp.current.prevPad[name]
  const now = !!(pad && pad[name])
  inp.current.prevPad[name] = now
  return now && !was
}
