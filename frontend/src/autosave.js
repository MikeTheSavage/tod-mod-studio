// Autosave: a few seconds after each change the project goes to the backend (the same JSON the project's own save writes).
// After a crash or a forced close the next start offers the last state back. Undo history may reset.
import { useEffect, useRef } from 'react'
import { get, post } from './api.js'

export const AUTOSAVE_MS = 3000

// kind: 'level' | 'mission' | 'newmap'; id: the project id (null = a project that was never saved); active: there are unsaved changes
export function useAutosave(kind, id, project, active, ms = AUTOSAVE_MS) {
  const wrote = useRef(null)                     // the key of the file this screen wrote (cleared again once its changes are saved)
  useEffect(() => {
    if (!project) return
    if (!active) {
      if (wrote.current) { const w = wrote.current; wrote.current = null; post('/api/autosave', { kind: w.kind, id: w.id, clear: true }).catch(() => {}) }
      return
    }
    const t = setTimeout(() => {
      post('/api/autosave', { kind, id, project }).then(() => {
        const w = wrote.current
        if (w && (w.kind !== kind || w.id !== id)) post('/api/autosave', { kind: w.kind, id: w.id, clear: true }).catch(() => {})
        wrote.current = { kind, id }
      }).catch(() => {})
    }, ms)
    return () => clearTimeout(t)
  }, [kind, id, project, active])
}

export async function loadAutosave(kind, id) {
  try {
    const r = await get('/api/autosave', id ? { kind, id } : { kind })
    return r.autosave && r.autosave.newer ? r.autosave : null
  } catch { return null }
}

export const clearAutosave = (kind, id) => post('/api/autosave', { kind, id, clear: true }).catch(() => {})
