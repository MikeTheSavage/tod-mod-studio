// Controller logic that needs no browser: button names, the dead zone and sensitivity curves, edge detection, the View
// chord (View + LB / RB = undo / redo), stick-as-d-pad repeat, and the rule that switches the hints between the pad and
// the keyboard. Node tests: frontend/tests/pad.test.mjs.

// the standard (Xbox-style) layout of the browser Gamepad API
export const INDEX = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, LT: 6, RT: 7, VIEW: 8, START: 9, L3: 10, R3: 11, UP: 12, DOWN: 13, LEFT: 14, RIGHT: 15 }
export const NAMES = Object.keys(INDEX)
export const DIRS = ['up', 'down', 'left', 'right']

export const DEFAULTS = { invertY: false, lookSens: 1, flySens: 1, deadzone: 0.18, swapAB: false, rumble: true }
export const LIMITS = { lookSens: [0.25, 3], flySens: [0.25, 3], deadzone: [0.05, 0.5] }
const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

// a settings object from anything stored: unknown keys dropped, numbers clamped, flags forced to booleans
export function cleanCfg(c) {
  const o = { ...DEFAULTS }
  if (!c || typeof c !== 'object') return o
  for (const k of ['invertY', 'swapAB', 'rumble']) if (k in c) o[k] = !!c[k]
  for (const k of Object.keys(LIMITS)) if (c[k] !== null && c[k] !== '' && Number.isFinite(+c[k])) o[k] = clamp(+c[k], LIMITS[k][0], LIMITS[k][1])
  return o
}

// ------------------------------------------------------------------ sticks
// radial dead zone: inside the circle nothing, outside it the push is rescaled so it starts at 0 and still reaches 1
export function deadzone(x, y, dz) {
  const m = Math.hypot(x, y)
  if (!(m > dz)) return [0, 0]
  const s = Math.min(1, (m - dz) / (1 - dz)) / m
  return [x * s, y * s]
}
// a trigger: nothing below a small floor, then 0..1
export const trigger = (v, floor = 0.06) => (v > floor ? Math.min(1, (v - floor) / (1 - floor)) : 0)
// the response curve: gentle near the centre, full at the edge; `sens` scales the top speed
export const curve = (v, sens = 1) => Math.sign(v) * Math.pow(Math.abs(v), 1.6) * sens
// what the look stick turns the camera by this frame (radians): rate in rad/s at full push = LOOK_RATE * sens
export const LOOK_RATE = 2.4
export const lookStep = (v, cfg, dt, isY = false) => curve(v, cfg.lookSens) * LOOK_RATE * dt * (isY && cfg.invertY ? -1 : 1)
// metres this frame for a fly / move stick; base m/s at full push
export const flyStep = (v, cfg, dt, base = 18) => curve(v, cfg.flySens) * base * dt

// ------------------------------------------------------------------ state from raw pad numbers
// the name a physical index has, with A and B swapped for Nintendo-style pads
export function nameAt(i, swapAB) {
  const n = NAMES[i]
  if (!swapAB) return n
  return n === 'A' ? 'B' : n === 'B' ? 'A' : n
}
// raw: { buttons: [{pressed, value} | number], axes: [lx, ly, rx, ry] } -> { held: {NAME: bool}, axes: {lx, ly, rx, ry, lt, rt} }
export function readState(raw, cfg) {
  const held = Object.fromEntries(NAMES.map(n => [n, false]))
  const B = raw?.buttons || []
  const val = i => { const b = B[i]; return !b ? 0 : typeof b === 'number' ? b : b.value ?? (b.pressed ? 1 : 0) }
  B.forEach((b, i) => { const n = i < 16 ? nameAt(i, cfg.swapAB) : null; if (n) held[n] = !!(b && (typeof b === 'number' ? b > 0.5 : b.pressed || b.value > 0.5)) })
  const ax = raw?.axes || []
  const [lx, ly] = deadzone(ax[0] || 0, ax[1] || 0, cfg.deadzone)
  const [rx, ry] = deadzone(ax[2] || 0, ax[3] || 0, cfg.deadzone)
  const lt = trigger(val(INDEX.LT)), rt = trigger(val(INDEX.RT))
  held.LT = lt > 0.5; held.RT = rt > 0.5
  return { held, axes: { lx, ly, rx, ry, lt, rt } }
}
export const emptyState = () => readState(null, DEFAULTS)

// the d-pad, or else the left stick pushed past a threshold, as one of four directions (or null)
export function dirOf(state, useStick = true, thresh = 0.55) {
  const h = state.held
  if (h.UP) return 'up'
  if (h.DOWN) return 'down'
  if (h.LEFT) return 'left'
  if (h.RIGHT) return 'right'
  if (!useStick) return null
  const { lx, ly } = state.axes
  if (Math.hypot(lx, ly) < thresh) return null
  return Math.abs(lx) > Math.abs(ly) ? (lx > 0 ? 'right' : 'left') : (ly > 0 ? 'down' : 'up')
}

// names that went down / up between two held maps
export function edges(prev, cur) {
  const down = [], up = []
  for (const n of NAMES) { if (cur[n] && !prev[n]) down.push(n); else if (!cur[n] && prev[n]) up.push(n) }
  return { down, up }
}

// ------------------------------------------------------------------ chords
// View held + LB / RB is undo / redo. View alone (pressed and released with no chord) is a plain View press, fired on release.
export function createRouter() { return { view: false, used: false } }
export function route(r, e) {
  const out = []
  for (const n of e.down) {
    if (n === 'VIEW') { r.view = true; r.used = false; continue }
    if (r.view && (n === 'LB' || n === 'RB')) { r.used = true; out.push({ name: 'VIEW+' + n, chord: true, action: n === 'LB' ? 'undo' : 'redo' }); continue }
    out.push({ name: n })
  }
  for (const n of e.up) {
    if (n === 'VIEW') { if (r.view && !r.used) out.push({ name: 'VIEW' }); r.view = false; r.used = false }
  }
  return out
}

// ------------------------------------------------------------------ d-pad / stick repeat: fires at once, then after a delay, then steadily
export function createRepeat(delay = 380, interval = 110) { return { dir: null, next: 0, delay, interval } }
export function repeat(r, dir, now) {
  if (!dir) { r.dir = null; return null }
  if (dir !== r.dir) { r.dir = dir; r.next = now + r.delay; return dir }
  if (now >= r.next) { r.next = now + r.interval; return dir }
  return null
}

// ------------------------------------------------------------------ hints: pad glyphs while a pad is in use, keyboard otherwise
// kind: 'pad' (a button or a stick past the dead zone), 'key' (a key), 'mouse' (a click, or a move of a few pixels)
export function nextMode(cur, kind, moved = 99) {
  if (kind === 'pad') return 'pad'
  if (kind === 'key' || (kind === 'mouse' && moved >= 4)) return 'keys'
  return cur
}
// a stick counts as used only when pushed clearly (drift does not switch the hints)
export const stickUsed = axes => Math.hypot(axes.lx, axes.ly) > 0.35 || Math.hypot(axes.rx, axes.ry) > 0.35 || axes.lt > 0.35 || axes.rt > 0.35

// the status bar strip for a context; every entry is a glyph and one short word
export function hintsFor(ctx, mode, extra = {}) {
  if (mode !== 'pad') return [{ k: 'Ctrl+K', l: 'Search' }]
  if (ctx === 'osk') return [{ k: 'A', l: 'Key' }, { k: 'X', l: 'Delete' }, { k: 'Y', l: 'Space' }, { k: 'Start', l: 'Done' }]
  if (ctx === 'view') return extra.placing
    ? [{ k: 'A', l: 'Place' }, { k: 'LB RB', l: 'Turn' }, { k: 'B', l: 'Cancel' }]
    : [{ k: 'A', l: 'Pick' }, { k: 'X', l: 'Add' }, { k: 'Y', l: extra.modeName || 'Mode' }, { k: 'B', l: 'Back' }]
  if (ctx === 'play') return [{ k: 'B', l: 'Leave' }, { k: 'Start', l: 'Search' }]
  return [{ k: 'A', l: 'Select' }, { k: 'B', l: 'Back' }, { k: 'LB RB', l: 'Tabs' }, { k: 'LT RT', l: 'Areas' }, { k: 'Start', l: 'Search' }, { k: 'View', l: 'Problems' }]
}
