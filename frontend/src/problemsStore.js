// One app-level store for the live ceiling meters and the Problems list.
// Screens register the project they edit; App feeds the backend (/api/problems) and keeps the answer here. Check results that the
// screens already fetch (api.js runJob) are recorded with the signature of the project they were run against, so a stale one is ignored.
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { post } from './api.js'

const S = { live: {}, results: {}, data: {}, open: false, pending: null, go: null, snap: null }
const subs = new Set()
const snap = () => { S.snap = { live: S.live, results: S.results, data: S.data, open: S.open, pending: S.pending }; subs.forEach(f => f()) }
snap()
export const subscribe = f => { subs.add(f); return () => subs.delete(f) }
export const getStore = () => S.snap
export const useStore = () => useSyncExternalStore(subscribe, getStore)

// ---- signatures: a result belongs to the project state it was computed from
export const modSig = p => JSON.stringify([p.level, p.data, p.collision, p.nav, p.missions, p.sections, p.models, p.textures])
const partSig = (p, k) => JSON.stringify([p[k] || [], p.collision || []])

export function registerProject(kind, id, project) {
  const cur = S.live[kind]
  if (cur && cur.project === project && cur.id === id) return
  S.live = { ...S.live, [kind]: { id, project } }
  snap()
}

// the kind of project a screen edits
export const kindOfScreen = s => (s === 'mtpl' ? 'mission' : s === 'newmaps' ? 'newmap' : 'level')

export function recordResult(path, body, result) {
  const R = { ...S.results }
  if (path === '/api/check' || path === '/api/export') {
    R.check = { sig: modSig(body.mod || {}), data: result }
  } else if (path === '/api/partb/check') {
    for (const k of body.kinds || []) R[k] = { sig: partSig(body.mod || {}, k), data: result }
  } else if (path === '/api/missiontpl' && body.action === 'validate') {
    R.tpl = { sig: JSON.stringify(body.project || null), data: result }
  } else if (path === '/api/newmaps' && body.action === 'check') {
    const list = (result?.report?.checks || []).map(c => ({ level: c.result === 'PASS' ? 'ok' : c.result === 'WARN' ? 'warn' : 'error', title: c.name || c.title || c.text || String(c.detail || ''), detail: c.detail }))
    R.newmap = { sig: null, data: { checks: list } }
  } else return
  S.results = R
  snap()
}

// the part of the results that still belongs to the project (sent along with it)
export function freshResults(kind, project) {
  const out = {}
  const r = S.results
  if (kind === 'level' && project) {
    if (r.check && r.check.sig === modSig(project)) out.check = r.check.data
    for (const k of ['nav', 'missions', 'sections']) if (r[k] && r[k].sig === partSig(project, k)) out[k] = r[k].data
  } else if (kind === 'mission' && r.tpl && r.tpl.sig === JSON.stringify(project || null)) out.tpl = r.tpl.data
  else if (kind === 'newmap' && r.newmap) out.newmap = r.newmap.data
  return out
}

export const setOpen = v => { S.open = v; snap() }
export const setGo = fn => { S.go = fn }

// a click on a problem or a meter: open the screen, then let the screen select / focus
export function jumpTo(ref) {
  if (!ref) return
  S.pending = { ref, n: Date.now() }
  snap()
  if (ref.screen && S.go) S.go(ref.screen)
}
export function useJump(screen, fn) {
  const st = useStore()
  useEffect(() => {
    const p = st.pending
    if (p && p.ref.screen === screen && fn(p.ref) !== false) { S.pending = null; snap() }
  })
}

// ---- the feed: App calls this for the kind the screen shows
export function useFeed(kind, enabled) {
  const st = useStore()
  const live = st.live[kind]
  const results = st.results
  const timer = useRef(null)
  const seq = useRef(0)
  useEffect(() => {
    if (!enabled || !live) return
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      const my = ++seq.current
      const res = freshResults(kind, live.project)
      try {
        const out = await post('/api/problems', { kind, project: live.project, id: live.id, results: res,
          heavy: kind === 'level' ? res.check?.ledger : undefined })
        if (my === seq.current) { S.data = { ...S.data, [kind]: out }; snap() }
      } catch { /* the backend is busy or the game is not set up: keep the last answer */ }
    }, 350)
    return () => clearTimeout(timer.current)
  }, [kind, live, results, enabled])
  return st.data[kind] || null
}
