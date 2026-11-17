// One undo history for every editing screen. The mod project (level, game data, routes, sections, collision) keeps
// its own stack in project.js; screens with local state (Mission templates, New maps) use useHistory.
import { useCallback, useEffect, useRef, useState } from 'react'

// get() returns the current value, set(v) replaces it. Call record() just BEFORE a change is applied.
export function useHistory(get, set, limit = 100) {
  const past = useRef([]), future = useRef([])
  const [, force] = useState(0)
  const rec = useCallback(() => { past.current = [...past.current, get()].slice(-limit); future.current = []; force(n => n + 1) }, [get, limit])
  const undo = useCallback(() => {
    if (!past.current.length) return
    const prev = past.current[past.current.length - 1]
    future.current = [get(), ...future.current]; past.current = past.current.slice(0, -1); set(prev); force(n => n + 1)
  }, [get, set])
  const redo = useCallback(() => {
    if (!future.current.length) return
    const next = future.current[0]
    past.current = [...past.current, get()]; future.current = future.current.slice(1); set(next); force(n => n + 1)
  }, [get, set])
  const clear = useCallback(() => { past.current = []; future.current = []; force(n => n + 1) }, [])
  return { record: rec, undo, redo, clear, canUndo: past.current.length > 0, canRedo: future.current.length > 0 }
}

// Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z), unless a text box has the focus (it keeps its own undo)
export function useUndoKeys(h, enabled = true) {
  const ref = useRef(h)
  ref.current = h
  useEffect(() => {
    if (!enabled) return
    const f = ev => {
      const t = ev.target?.tagName
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || ev.target?.isContentEditable) return
      if (!ev.ctrlKey && !ev.metaKey) return
      const k = ev.key.toLowerCase()
      if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); ref.current.undo() }
      else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); ref.current.redo() }
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [enabled])
}
