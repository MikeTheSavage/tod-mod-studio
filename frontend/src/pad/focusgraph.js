// Spatial navigation: from the focused control, which control does a d-pad (or arrow) press reach? Pure geometry, no DOM:
// items are { id, x, y, w, h } rectangles. Node tests: frontend/tests/pad.test.mjs.

const AX = { right: [1, 0], left: [-1, 0], down: [0, 1], up: [0, -1] }   // screen y grows downward

const spans = (r, horiz) => (horiz ? [r.x, r.x + r.w] : [r.y, r.y + r.h])
const mid = (r, horiz) => (horiz ? r.x + r.w / 2 : r.y + r.h / 2)
const gap = (a, b) => Math.max(0, Math.max(a[0], b[0]) - Math.min(a[1], b[1]))     // 0 when the spans overlap

// score of `r` as a target from `c` in `dir` (lower is better); null when it is not in that direction
export function score(c, r, dir) {
  const horiz = dir === 'left' || dir === 'right'
  const sign = AX[dir][horiz ? 0 : 1]
  const along = (mid(r, horiz) - mid(c, horiz)) * sign
  if (along <= 0.5) return null
  const [c0, c1] = spans(c, horiz), [r0, r1] = spans(r, horiz)
  const edge = sign > 0 ? r0 - c1 : c0 - r1          // edge to edge along the direction (negative = they overlap)
  const main = Math.max(0, edge)
  const cross = gap(spans(c, !horiz), spans(r, !horiz))
  const off = Math.abs(mid(c, !horiz) - mid(r, !horiz))
  return main + 3 * cross + 0.25 * off + (edge < 0 ? 4 : 0)
}

export function pickNext(items, curId, dir) {
  const c = items.find(i => i.id === curId)
  if (!c) return null
  let best = null, bs = Infinity
  for (const r of items) {
    if (r.id === c.id) continue
    const s = score(c, r, dir)
    if (s != null && s < bs) { bs = s; best = r }
  }
  return best ? best.id : null
}

// nothing in that direction: wrap to the far side, on the same row or column, so no control is a dead end
export function pickWrap(items, curId, dir) {
  const c = items.find(i => i.id === curId)
  if (!c) return null
  const horiz = dir === 'left' || dir === 'right'
  const sign = AX[dir][horiz ? 0 : 1]
  let best = null, bs = Infinity
  for (const r of items) {
    if (r.id === c.id) continue
    const cross = gap(spans(c, !horiz), spans(r, !horiz)) + 0.25 * Math.abs(mid(c, !horiz) - mid(r, !horiz))
    const s = cross * 1000 + sign * mid(r, horiz)       // same row or column first, then the far side
    if (s < bs) { bs = s; best = r }
  }
  return best ? best.id : null
}

export const move = (items, curId, dir) => pickNext(items, curId, dir) ?? pickWrap(items, curId, dir)

// where focus starts when nothing has it: the item nearest the middle of the preferred area, else the first
export function pickEntry(items, area) {
  if (!items.length) return null
  if (!area) return items[0].id
  const cx = area.x + area.w / 2, cy = area.y + area.h / 2
  let best = null, bs = Infinity
  for (const r of items) {
    const inside = r.x < area.x + area.w && r.x + r.w > area.x && r.y < area.y + area.h && r.y + r.h > area.y
    const s = Math.hypot(r.x + r.w / 2 - cx, r.y + r.h / 2 - cy) + (inside ? 0 : 1e6)
    if (s < bs) { bs = s; best = r }
  }
  return best.id
}

// the ids that cannot be reached from `startId` by direction moves (the no-trap property: this must be empty)
export function unreachable(items, startId) {
  const seen = new Set([startId]), stack = [startId]
  while (stack.length) {
    const id = stack.pop()
    for (const d of Object.keys(AX)) { const n = move(items, id, d); if (n != null && !seen.has(n)) { seen.add(n); stack.push(n) } }
  }
  return items.map(i => i.id).filter(i => !seen.has(i))
}
