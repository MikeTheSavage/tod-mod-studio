// Pan and zoom maths for the card graphs (pure, so it can be tested).
export const ZMIN = 0.15, ZMAX = 2.5, DRAG_PX = 4

// a press that moved more than a few pixels is a pan, not a click
export const moved = (a, b, px = DRAG_PX) => Math.hypot(b.x - a.x, b.y - a.y) > px

// zoom by `factor` keeping the graph point under (px, py) where it is
export function zoomAt(view, factor, px, py, lo = ZMIN, hi = ZMAX) {
  const s = Math.min(hi, Math.max(lo, view.s * (Number.isFinite(factor) && factor > 0 ? factor : 1)))
  const k = s / view.s
  return { s, x: px - (px - view.x) * k, y: py - (py - view.y) * k }
}

// the box of all cards: pos = { id: {x, y, h} }, card width cw
export function boxOf(pos, cw) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const p of Object.values(pos || {})) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + cw); y1 = Math.max(y1, p.y + (p.h || 0)) }
  return Number.isFinite(x0) ? { x0, y0, x1, y1 } : null
}

// keep at least `keep` px of the graph on screen, so panning can never lose it; never NaN
export function clampView(view, box, w, h, keep = 80) {
  const s = Number.isFinite(view.s) && view.s > 0 ? view.s : 1
  let x = Number.isFinite(view.x) ? view.x : 0, y = Number.isFinite(view.y) ? view.y : 0
  if (box && w > 0 && h > 0) {
    const kx = Math.min(keep, (box.x1 - box.x0) * s), ky = Math.min(keep, (box.y1 - box.y0) * s)
    x = Math.min(w - kx - box.x0 * s, Math.max(kx - box.x1 * s, x))
    y = Math.min(h - ky - box.y0 * s, Math.max(ky - box.y1 * s, y))
  }
  return { x, y, s }
}

// plain wheel steps, whatever the unit the device reports
export const wheelFactor = e => Math.exp(-Math.max(-300, Math.min(300, e.deltaY * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 100 : 1))) * 0.0015)
