// The focus model that the keyboard and the controller share: which controls can take focus, where an arrow or a d-pad
// press leads (focusgraph.js does the geometry), what A does to the focused control, and what B does.
import { move as graphMove, pickEntry } from './focusgraph.js'

const FOCUSABLE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex],[role=menuitem],[role=option],[role=tab]'
const TEXTY = new Set(['text', 'search', 'number', 'email', 'url', 'tel', 'password', 'date', 'time'])

export const isText = el => !!el && ((el.tagName === 'INPUT' && TEXTY.has((el.type || 'text').toLowerCase())) || el.tagName === 'TEXTAREA' || el.isContentEditable === true)
export const isRange = el => el?.tagName === 'INPUT' && el.type === 'range'

export function isShown(el) {
  if (!el.isConnected || el.closest('[inert],[aria-hidden=true],[data-pad-skip]')) return false
  const r = el.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) return false
  if (r.right < 0 || r.left > window.innerWidth || r.bottom < -4000 || r.top > window.innerHeight + 4000) return false
  const cs = getComputedStyle(el)
  return cs.visibility !== 'hidden' && cs.display !== 'none'
}

// the topmost thing that keeps focus inside it: the pad's own keyboard or picker, the command search, a dialog, an open menu
const SCOPES = ['.osk', '.picker', '.cmdk .box', '[role=alertdialog]', '[role=dialog]', '.menu[role=menu]']
export function modalRoot() {
  for (const s of SCOPES) {
    const nodes = [...document.querySelectorAll(s)].filter(n => n.getBoundingClientRect().width > 0)
    if (nodes.length) return nodes[nodes.length - 1]
  }
  return null
}
export const problemsOpen = () => !!document.querySelector('aside.problems')
export const hasScope = () => !!modalRoot() || problemsOpen()

// 'view' = the 3D view itself has focus, 'play' = a playground has focus, else the ordinary interface
export function contextOf() {
  const a = document.activeElement
  if (a && a !== document.body && a.matches?.('[data-pad-ctx]')) return a.dataset.padCtx
  return 'ui'
}

export function candidates(root) {
  const out = []
  let n = 0
  for (const el of (root || document).querySelectorAll(FOCUSABLE)) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue
    const ti = el.getAttribute('tabindex')
    if (ti === '-1' && !/^(menuitem|option)$/.test(el.getAttribute('role') || '')) continue
    if (!isShown(el)) continue
    const r = el.getBoundingClientRect()
    out.push({ id: n++, el, x: r.left, y: r.top, w: r.width, h: r.height })
  }
  return out
}

export function focusEl(el) {
  if (!el) return false
  if (el.tabIndex < 0 && !el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
  try { el.scrollIntoView({ block: 'nearest', inline: 'nearest' }) } catch { /* old engine */ }
  return document.activeElement === el
}

// the last few controls that had focus, so focus can go back when one is removed (a menu closes, a dialog ends)
const trail = []
export function remember(el) { if (!el || el === document.body) return; const i = trail.indexOf(el); if (i >= 0) trail.splice(i, 1); trail.push(el); if (trail.length > 12) trail.shift() }
export function recover() {
  const a = document.activeElement
  if (a && a !== document.body && a.isConnected) return false
  const root = modalRoot()
  for (let i = trail.length - 1; i >= 0; i--) {
    const el = trail[i]
    if (el.isConnected && isShown(el) && (!root || root.contains(el))) return focusEl(el)
  }
  return false
}

const MAIN = () => { const m = document.querySelector('.main'); if (!m) return null; const r = m.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height } }

// move focus one step in a direction; true when focus moved
export function moveFocus(dir) {
  const root = modalRoot()
  const list = candidates(root)
  if (!list.length) return false
  const cur = document.activeElement
  let from = list.find(i => i.el === cur) || list.find(i => i.el.contains(cur) && cur !== document.body)
  if (!from) {
    const id = root ? list[0].id : pickEntry(list, MAIN())
    return focusEl(list.find(i => i.id === id).el)
  }
  const id = graphMove(list, from.id, dir)
  if (id == null || id === from.id) return false
  return focusEl(list.find(i => i.id === id).el)
}

// first control inside a freshly opened scope
export function enterScope(root) {
  if (!root) return false
  const list = candidates(root)
  if (!list.length) return false
  const pref = list.find(i => i.el.matches('[autofocus],input[type=text],input:not([type])')) || list[0]
  return focusEl(pref.el)
}

// keep focus inside the scope that is open: call after anything that may have opened one
export function afterOpen() {
  setTimeout(() => { const r = modalRoot(); if (r && !r.contains(document.activeElement)) enterScope(r) }, 80)
}

export function pressKey(el, key, extra = {}) {
  const t = el && el.isConnected ? el : document.body
  t.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...extra }))
}
export const pressEscape = () => pressKey(document.activeElement, 'Escape')

// React-controlled inputs only notice a value set through the native setter followed by an input event
export function setValue(el, v) {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v)
  el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
}

// a range slider moves by its step with the d-pad
export function nudgeRange(el, dir) {
  const step = parseFloat(el.step) || (parseFloat(el.max) - parseFloat(el.min)) / 20 || 1
  const v = Math.min(parseFloat(el.max), Math.max(parseFloat(el.min), parseFloat(el.value) + (dir === 'right' ? step : -step)))
  setValue(el, String(Math.round(v * 1e6) / 1e6))
}

// keyboard: arrows move focus between controls (the same graph the pad uses); Enter and Space press menu items
export function installKeyNav() {
  const h = e => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
    const t = e.target
    if (!(t instanceof Element) || t === document.body) return
    const role = t.getAttribute('role')
    if ((e.key === 'Enter' || e.key === ' ') && (role === 'menuitem' || role === 'option') && t.tagName !== 'BUTTON') { e.preventDefault(); t.click(); return }
    const dir = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' }[e.key]
    if (!dir || e.shiftKey) return
    if (isText(t) || t.tagName === 'SELECT' || isRange(t) || t.matches('[data-pad-ctx]')) return
    if (moveFocus(dir)) e.preventDefault()
  }
  const fin = e => remember(e.target)
  window.addEventListener('keydown', h)
  window.addEventListener('focusin', fin)
  return () => { window.removeEventListener('keydown', h); window.removeEventListener('focusin', fin) }
}
