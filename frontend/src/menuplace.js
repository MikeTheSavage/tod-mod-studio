// where a popover goes: just under its button, kept inside the window (pure, so it can be tested)
export function menuPlace(r, w, right, vw, vh, gap = 4, edge = 8) {
  const left = right ? Math.max(edge, Math.min(r.right - w, vw - w - edge)) : Math.max(edge, Math.min(r.left, vw - w - edge))
  const top = r.bottom + gap
  return { position: 'fixed', top, left, right: 'auto', maxHeight: Math.max(120, Math.min(420, vh - top - edge)) }
}
