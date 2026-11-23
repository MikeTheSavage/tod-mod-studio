// One rule for every 3D view: a press that moves more than a few pixels before release is a camera move, never a select,
// a pick or a place; right and middle button drags never select; a gizmo only commits a change when it really changed something.
export const CLICK_PX = 4

// how far the pointer wandered from where the last press began (path, not just the end point: a loop that comes back
// to its start is still a camera move)
export function createTracker() {
  const P = { x: 0, y: 0, max: 0 }
  return {
    down(x, y) { P.x = x; P.y = y; P.max = 0 },
    move(x, y, buttons = 1) { if (buttons) P.max = Math.max(P.max, Math.hypot(x - P.x, y - P.y)) },
    travel: () => P.max,
  }
}
export const tracker = createTracker()
if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', e => tracker.down(e.clientX, e.clientY), true)
  window.addEventListener('pointermove', e => tracker.move(e.clientX, e.clientY, e.buttons), true)
}

// react-three-fiber click events carry `delta` (pixels between press and release) and the DOM event
export const isClick = (ev, t = tracker) => {
  if (!ev) return true
  if (ev.delta != null && ev.delta > CLICK_PX) return false
  if ((ev.nativeEvent || ev.type === 'click') && t.travel() > CLICK_PX) return false
  const b = ev.nativeEvent ? ev.nativeEvent.button : ev.button
  return b == null || b === 0
}

// wrap a click handler so a camera drag that ends over an object does nothing
export const clickOnly = fn => fn && (ev => { if (isClick(ev)) fn(ev) })

// a plain DOM press/release pair (clientX/clientY): true when it was a click
export const isTap = (down, up) => !!down && Math.hypot(up.clientX - down.clientX, up.clientY - down.clientY) <= CLICK_PX

// did a gizmo drag change anything? a, b: arrays of numbers (position, rotation quaternion, size), compared with a tolerance
export const changed = (a, b, eps = 1e-6) => !a || !b || a.length !== b.length || a.some((v, i) => Math.abs(v - b[i]) > eps)
