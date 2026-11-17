// Opening a map (or one section of it) with real models for the screens that show it as context.
// `pick` = { map, section, missions, blockOnly }. Quiet: the level editor's own last view is left alone.
import { useEffect, useMemo, useRef, useState } from 'react'
import { get, runJob } from './api.js'
import { buildView } from './view.js'

let catalogCache = null
export const getCatalog = () => (catalogCache ||= get('/api/catalog').catch(e => { catalogCache = null; throw e }))

export function openBundle(pick, progress) {
  const body = pick.section || pick.blockOnly || (pick.missions || []).length ? { ...pick, quiet: true } : { ...pick, sections: '*', quiet: true }
  return runJob('/api/open', body, progress)
}

// which map and section a block belongs to: { map, section, missions, blockOnly }
export function pickOfBlock(catalog, block) {
  const tail = s => (s || '').replace(/\\/g, '/').split('/').pop()
  const b = tail(block)
  for (const m of catalog?.maps || []) {
    if (tail(m.map_block) === b) return { map: m.id, section: null, missions: [], blockOnly: true }
    const s = m.sections.find(x => tail(x.entry) === b)
    if (s) return { map: m.id, section: s.entry, missions: [] }
    const q = m.missions.find(x => tail(x.entry) === b)
    if (q) return { map: m.id, section: q.section || null, missions: [q.entry], blockOnly: !q.section }
  }
  return null
}
// 'MAINMAP_Map04_..' or 'SUBMAP02_Map04_..' -> 'map04' (the 02 of the submap is its own number)
export const mapIdIn = name => { const m = String(name || '').toLowerCase().match(/(?:^|_)map(\d+)(?:_|$)/); return m ? 'map' + m[1] : null }
export const pickOfMapName = (catalog, name) => {
  const id = mapIdIn(name)
  return id && (catalog?.maps || []).some(m => m.id === id) ? { map: id, section: null, missions: [], blockOnly: true } : null
}

// the bundle of a pick, opened on demand (`enabled`) and reopened when the pick changes
export function useBundle(pick, enabled = true) {
  const [s, setS] = useState({ bundle: null, busy: null, err: null })
  const key = pick ? JSON.stringify([pick.map, pick.section, pick.missions, pick.blockOnly]) : ''
  const live = useRef(0)
  useEffect(() => {
    if (!pick || !enabled) { setS(c => (c.bundle || c.busy || c.err ? { bundle: null, busy: null, err: null } : c)); return }
    const id = ++live.current
    setS({ bundle: null, busy: 'Opening the map', err: null })
    openBundle(pick, j => live.current === id && setS(c => ({ ...c, busy: j.message || 'Opening the map' })))
      .then(b => live.current === id && setS({ bundle: b, busy: null, err: null }))
      .catch(e => live.current === id && setS({ bundle: null, busy: null, err: e.message }))
    return () => { live.current += 1 }
  }, [key, enabled])
  const view = useMemo(() => (s.bundle ? buildView(s.bundle, []) : null), [s.bundle])
  return { ...s, view, entries: s.bundle?.entries }
}

// the box around a set of game positions [[x, y, z]...] as [x0, z0, x1, z1]
export function boundsOf(points, pad = 20) {
  if (!points.length) return null
  const xs = points.map(p => p[0]), zs = points.map(p => p[2])
  return [Math.min(...xs) - pad, Math.min(...zs) - pad, Math.max(...xs) + pad, Math.max(...zs) + pad]
}

// only the level's own models are drawn when a screen shows a map as context (its things belong to the level editor)
export const CONTEXT_LAYERS = { model: true }

// the map and section a save slot is in: summary.folders = [['map', 'MAINMAP_Map06_...'], ['submap', 'SUBMAP02_Map06_...'], ...]
export function pickOfSave(catalog, summary) {
  const low = x => String(x || '').toLowerCase()
  const f = Object.fromEntries((summary?.folders || []).map(([k, v]) => [k, v]))
  const id = mapIdIn(f.submap || f.map)
  const m = (catalog?.maps || []).find(x => x.id === id)
  if (!m) return null
  const sec = m.sections.find(s => low(s.entry).split('/').pop().replace('.submap', '') === low(f.submap))
  return sec ? { map: m.id, section: sec.entry, missions: [] } : { map: m.id, section: null, missions: [], blockOnly: true }
}
