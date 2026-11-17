// Commands and shortcuts. A screen registers its commands while it is open (`useCommands`); one global key listener
// runs the command whose key matches; the command search (Ctrl+K) lists them all. Keys the user changed are kept in
// the per-user library (`shortcuts`: command id -> key), so they follow the user to every project.
import { useEffect, useRef, useState } from 'react'
import { loadLib, saveLib, libSnapshot } from './userlib.js'

const scopes = new Map()          // scope -> () => latest list [{id, label, keys, run, group, enabled}]
const subs = new Set()
const emit = () => subs.forEach(f => f())
let overrides = {}
let paletteOpen = false, shortcutsOpen = false

export function useCommands(scope, list) {
  const ref = useRef(list)
  ref.current = list
  useEffect(() => {
    scopes.set(scope, () => ref.current)
    emit()
    return () => { scopes.delete(scope); emit() }
  }, [scope])
  return null
}

export const allCommands = () => [...scopes.values()].flatMap(f => f()).filter(Boolean)
export const bindingOf = cmd => (overrides[cmd.id] !== undefined ? overrides[cmd.id] : cmd.keys) || ''

export function comboOf(ev) {
  const k = ev.key
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(k)) return ''
  const name = k === ' ' ? 'space' : k.length === 1 ? k.toLowerCase() : k.toLowerCase().replace('arrow', '')
  return [(ev.ctrlKey || ev.metaKey) && 'ctrl', ev.altKey && 'alt', ev.shiftKey && 'shift', name].filter(Boolean).join('+')
}
const NAMES = { ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', delete: 'Del', escape: 'Esc', space: 'Space' }
export const prettyCombo = c => (c || '').split('+').map(p => NAMES[p] || (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1))).join('+')

export function setBinding(id, combo) {
  overrides = { ...overrides }
  if (combo === null) delete overrides[id]; else overrides[id] = combo
  saveLib('shortcuts', overrides); emit()
}
export const resetBindings = () => { overrides = {}; saveLib('shortcuts', {}); emit() }
export const conflictOf = (id, combo) => (combo ? allCommands().find(c => c.id !== id && bindingOf(c) === combo) : null)

export function openPalette(v = true) { paletteOpen = v; emit() }
export function openShortcuts(v = true) { shortcutsOpen = v; emit() }
export function useCommandUI() {
  const [, force] = useState(0)
  useEffect(() => { const f = () => force(n => n + 1); subs.add(f); return () => subs.delete(f) }, [])
  return { paletteOpen, shortcutsOpen, commands: allCommands() }
}

const isTyping = t => ['INPUT', 'TEXTAREA', 'SELECT'].includes(t?.tagName) || t?.isContentEditable

// one listener for the whole app (installed once by the host component)
export function installKeys() {
  loadLib().then(() => { overrides = { ...(libSnapshot('shortcuts') || {}) }; emit() })
  const h = ev => {
    const combo = comboOf(ev)
    if (!combo) return
    if (combo === 'ctrl+k') { ev.preventDefault(); openPalette(!paletteOpen); return }
    if (paletteOpen || shortcutsOpen) return
    if (isTyping(ev.target)) return
    for (const c of allCommands()) {
      if (c.enabled === false) continue
      if (bindingOf(c) === combo) { ev.preventDefault(); c.run(ev); return }
    }
  }
  window.addEventListener('keydown', h)
  return () => window.removeEventListener('keydown', h)
}
