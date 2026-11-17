// One selection model for every screen that uses the shared 3D view (and for controller input later:
// `step(dir, items)` moves the selection to the nearest item in a direction, like a d-pad).
import { useCallback, useMemo, useState } from 'react'

const uniq = a => [...new Set(a)]

export function useSelection(initial = []) {
  const [s, setS] = useState({ ids: initial, primary: initial[initial.length - 1] ?? null })
  const set = useCallback((ids, primary) => {
    const list = uniq(Array.isArray(ids) ? ids : ids == null ? [] : [ids])
    setS({ ids: list, primary: primary !== undefined ? primary : list[list.length - 1] ?? null })
  }, [])
  const clear = useCallback(() => setS(c => (c.ids.length ? { ids: [], primary: null } : c)), [])
  const add = useCallback(ids => setS(c => {
    const list = uniq([...c.ids, ...(Array.isArray(ids) ? ids : [ids])])
    return { ids: list, primary: list[list.length - 1] ?? null }
  }), [])
  const remove = useCallback(ids => setS(c => {
    const gone = new Set(Array.isArray(ids) ? ids : [ids])
    const list = c.ids.filter(i => !gone.has(i))
    return { ids: list, primary: gone.has(c.primary) ? list[list.length - 1] ?? null : c.primary }
  }), [])
  const toggle = useCallback(id => setS(c => {
    if (c.ids.includes(id)) {
      const list = c.ids.filter(i => i !== id)
      return { ids: list, primary: c.primary === id ? list[list.length - 1] ?? null : c.primary }
    }
    return { ids: [...c.ids, id], primary: id }
  }), [])
  // a pick with the usual modifier rules: Ctrl or Shift adds or removes, a plain click replaces
  const pick = useCallback((id, ev) => {
    if (ev && (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.nativeEvent?.ctrlKey || ev.nativeEvent?.shiftKey || ev.nativeEvent?.metaKey)) toggle(id)
    else set([id])
  }, [set, toggle])
  const idSet = useMemo(() => new Set(s.ids), [s.ids])
  const has = useCallback(id => idSet.has(id), [idSet])
  // nearest item in a screen direction (north up: up = +z, right = +x); items: [{id, pos: [x, y, z]}]
  const step = useCallback((dir, items) => {
    if (!items.some(i => i.id === s.primary)) { if (items[0]) set([items[0].id]); return items[0]?.id ?? null }
    const id = nearestInDirection(items, s.primary, dir)
    if (id !== s.primary) set([id])
    return id
  }, [s.primary, set])
  return useMemo(() => ({ ids: s.ids, primary: s.primary, count: s.ids.length, idSet, has, set, clear, add, remove, toggle, pick, step }),
    [s, idSet, has, set, clear, add, remove, toggle, pick, step])
}

// the item nearest to `from` in a direction on the map (north up): what a d-pad press selects
export function nearestInDirection(items, from, dir) {
  const cur = items.find(i => i.id === from)
  const D = { right: [1, 0], left: [-1, 0], up: [0, 1], down: [0, -1] }[dir]
  if (!cur || !D) return from
  let best = null, bestScore = Infinity
  for (const i of items) {
    if (i.id === cur.id) continue
    const dx = i.pos[0] - cur.pos[0], dz = i.pos[2] - cur.pos[2]
    const along = dx * D[0] + dz * D[1]
    if (along <= 0) continue
    const score = along + 2 * Math.abs(dx * D[1] - dz * D[0])
    if (score < bestScore) { bestScore = score; best = i }
  }
  return best ? best.id : from
}
