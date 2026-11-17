// The per-user editor library (prefabs, shortcuts, scatter presets, the copy buffer): the backend keeps it in the
// user folder; localStorage is only the fallback when the backend is not there (a plain browser preview).
import { useEffect, useState } from 'react'
import { get, post } from './api.js'

const LS = 'todms.userlib.v1'
let cache = null, loading = null
const subs = new Set()
const SHAPES = { prefabs: [], shortcuts: {}, scatter: {}, clipboard: {} }

const fromLocal = () => { try { return { ...SHAPES, ...JSON.parse(localStorage.getItem(LS) || '{}') } } catch { return { ...SHAPES } } }
const toLocal = v => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private mode */ } }
const emit = () => subs.forEach(f => f())

export function loadLib() {
  if (cache) return Promise.resolve(cache)
  if (!loading) loading = get('/api/userlib').then(v => { cache = { ...SHAPES, ...v }; return cache }).catch(() => { cache = fromLocal(); return cache }).then(v => { emit(); return v })
  return loading
}

export async function saveLib(key, value) {
  cache = { ...(cache || fromLocal()), [key]: value }
  emit()
  toLocal(cache)
  try { await post('/api/userlib', { key, value }) } catch { /* kept in localStorage */ }
}

export function useLib(key) {
  const [, force] = useState(0)
  useEffect(() => {
    const f = () => force(n => n + 1)
    subs.add(f); loadLib()
    return () => subs.delete(f)
  }, [])
  const value = cache ? cache[key] : SHAPES[key]
  return [value ?? SHAPES[key], v => saveLib(key, typeof v === 'function' ? v(value ?? SHAPES[key]) : v), !!cache]
}

export const libSnapshot = key => (cache ? cache[key] : SHAPES[key])
