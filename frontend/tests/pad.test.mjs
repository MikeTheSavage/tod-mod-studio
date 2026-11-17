import test from 'node:test'
import assert from 'node:assert/strict'
import * as P from '../src/pad/padlogic.js'
import * as G from '../src/pad/focusgraph.js'

const R = (id, x, y, w = 80, h = 28) => ({ id, x, y, w, h })

// ------------------------------------------------------------------ the focus graph
test('focus: a row of buttons moves left and right, a column up and down', () => {
  const row = [R('a', 0, 0), R('b', 100, 0), R('c', 200, 0)]
  assert.equal(G.pickNext(row, 'a', 'right'), 'b')
  assert.equal(G.pickNext(row, 'b', 'right'), 'c')
  assert.equal(G.pickNext(row, 'c', 'left'), 'b')
  assert.equal(G.pickNext(row, 'a', 'left'), null)
  const col = [R('a', 0, 0), R('b', 0, 40), R('c', 0, 80)]
  assert.equal(G.pickNext(col, 'a', 'down'), 'b')
  assert.equal(G.pickNext(col, 'c', 'up'), 'b')
})

test('focus: prefers the control in line over a nearer one off to the side', () => {
  const items = [R('cur', 100, 0), R('inline', 100, 100), R('side', 300, 40)]
  assert.equal(G.pickNext(items, 'cur', 'down'), 'inline')
  assert.equal(G.pickNext(items, 'cur', 'right'), 'side')
})

test('focus: a rail on the left, a toolbar on top and a panel reach each other', () => {
  const items = [R('rail1', 0, 50, 60, 50), R('rail2', 0, 110, 60, 50), R('top1', 70, 0), R('top2', 160, 0), R('p1', 70, 60), R('p2', 70, 100), R('side', 400, 100)]
  assert.equal(G.pickNext(items, 'rail1', 'right'), 'p1')
  assert.equal(G.pickNext(items, 'p1', 'left'), 'rail1')
  assert.equal(G.pickNext(items, 'p1', 'up'), 'top1')
  assert.equal(G.pickNext(items, 'p2', 'right'), 'side')
})

test('focus: no direction is a dead end (wraps to the far side)', () => {
  const row = [R('a', 0, 0), R('b', 100, 0), R('c', 200, 0)]
  assert.equal(G.move(row, 'a', 'left'), 'c')
  assert.equal(G.move(row, 'c', 'right'), 'a')
  assert.notEqual(G.move(row, 'a', 'up'), null)
})

test('focus: every item is reachable from every other in a ragged layout (no trap)', () => {
  const items = [R('logo', 0, 0, 30, 30), R('t1', 50, 0), R('t2', 150, 0, 120), R('save', 600, 0), R('r1', 0, 60, 60, 50), R('r2', 0, 120, 60, 50), R('r3', 0, 180, 60, 50),
    R('a', 80, 70, 200), R('b', 80, 110, 200), R('c', 80, 150, 90), R('d', 180, 150, 100), R('v', 300, 60, 260, 300), R('p1', 580, 70, 200), R('p2', 580, 110, 90), R('s1', 0, 500, 200), R('s2', 220, 500, 200)]
  for (const i of items) assert.deepEqual(G.unreachable(items, i.id), [], 'from ' + i.id)
  const single = [R('only', 10, 10)]
  assert.deepEqual(G.unreachable(single, 'only'), [])
  assert.equal(G.move(single, 'only', 'down'), null)
})

test('focus: the entry point is the item nearest the middle of the preferred area', () => {
  const items = [R('logo', 0, 0), R('rail', 0, 100), R('main1', 300, 300), R('main2', 500, 100)]
  assert.equal(G.pickEntry(items, { x: 250, y: 50, w: 600, h: 600 }), 'main1')
  assert.equal(G.pickEntry(items, null), 'logo')
  assert.equal(G.pickEntry([], null), null)
})

// ------------------------------------------------------------------ dead zone and sensitivity
test('dead zone: nothing inside, rescaled outside, full push stays 1', () => {
  assert.deepEqual(P.deadzone(0.1, 0.1, 0.2), [0, 0])
  const [x, y] = P.deadzone(0.6, 0, 0.2)
  assert.ok(Math.abs(x - 0.5) < 1e-9 && y === 0)
  const [fx, fy] = P.deadzone(1, 0, 0.3)
  assert.ok(Math.abs(fx - 1) < 1e-9 && fy === 0)
  const [dx, dy] = P.deadzone(0.8, 0.8, 0.2)             // the diagonal is not clipped to a square
  assert.ok(Math.hypot(dx, dy) <= 1 + 1e-9 && dx === dy)
  // a bigger dead zone needs a bigger push for the same output
  assert.ok(P.deadzone(0.4, 0, 0.1)[0] > P.deadzone(0.4, 0, 0.3)[0])
})

test('sensitivity: curve is 0 at rest, monotonic, signed and scaled by the setting', () => {
  assert.equal(P.curve(0, 2), 0)
  assert.ok(P.curve(0.5) < P.curve(0.9))
  assert.equal(P.curve(-0.5), -P.curve(0.5))
  assert.ok(Math.abs(P.curve(1, 1) - 1) < 1e-12)
  assert.ok(Math.abs(P.curve(0.7, 2) - 2 * P.curve(0.7, 1)) < 1e-12)
  const cfg = { ...P.DEFAULTS, lookSens: 2 }
  assert.ok(Math.abs(P.lookStep(1, cfg, 1) - 2 * P.LOOK_RATE) < 1e-9)
  assert.ok(Math.abs(P.flyStep(1, { ...P.DEFAULTS, flySens: 0.5 }, 1, 18) - 9) < 1e-9)
})

test('invert look Y flips only the vertical look', () => {
  const on = { ...P.DEFAULTS, invertY: true }
  assert.equal(P.lookStep(0.8, on, 0.1, true), -P.lookStep(0.8, P.DEFAULTS, 0.1, true))
  assert.equal(P.lookStep(0.8, on, 0.1, false), P.lookStep(0.8, P.DEFAULTS, 0.1, false))
})

test('settings are clamped and unknown keys dropped', () => {
  const c = P.cleanCfg({ lookSens: 99, flySens: -3, deadzone: 0.9, invertY: 1, swapAB: 'yes', bogus: 1 })
  assert.equal(c.lookSens, 3); assert.equal(c.flySens, 0.25); assert.equal(c.deadzone, 0.5)
  assert.equal(c.invertY, true); assert.equal(c.swapAB, true); assert.equal(c.rumble, true); assert.ok(!('bogus' in c))
  assert.deepEqual(P.cleanCfg(null), P.DEFAULTS)
  assert.deepEqual(P.cleanCfg({ lookSens: '' }), P.DEFAULTS)
})

test('raw pad numbers become names, with A and B swapped on request', () => {
  const B = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 }))
  B[0] = { pressed: true, value: 1 }; B[7] = { pressed: false, value: 0.8 }; B[12] = { pressed: true, value: 1 }
  const s = P.readState({ buttons: B, axes: [0.05, 0, 0, 0.9] }, P.DEFAULTS)
  assert.equal(s.held.A, true); assert.equal(s.held.B, false); assert.equal(s.held.RT, true); assert.equal(s.held.UP, true)
  assert.equal(s.axes.lx, 0); assert.ok(s.axes.ry > 0.8)
  const sw = P.readState({ buttons: B, axes: [] }, { ...P.DEFAULTS, swapAB: true })
  assert.equal(sw.held.A, false); assert.equal(sw.held.B, true)
  assert.deepEqual(P.readState(null, P.DEFAULTS).held.A, false)
})

test('the d-pad wins over the stick; the stick needs a clear push', () => {
  const B = Array.from({ length: 16 }, () => ({ pressed: false, value: 0 }))
  assert.equal(P.dirOf(P.readState({ buttons: B, axes: [0.3, 0] }, P.DEFAULTS)), null)
  assert.equal(P.dirOf(P.readState({ buttons: B, axes: [0, -1] }, P.DEFAULTS)), 'up')
  assert.equal(P.dirOf(P.readState({ buttons: B, axes: [0.9, 0.4] }, P.DEFAULTS)), 'right')
  assert.equal(P.dirOf(P.readState({ buttons: B, axes: [0, -1] }, P.DEFAULTS), false), null)
  B[15] = { pressed: true, value: 1 }
  assert.equal(P.dirOf(P.readState({ buttons: B, axes: [0, -1] }, P.DEFAULTS)), 'right')
})

test('repeat: one step at once, then after the delay, then steadily', () => {
  const r = P.createRepeat(400, 100)
  assert.equal(P.repeat(r, 'down', 0), 'down')
  assert.equal(P.repeat(r, 'down', 200), null)
  assert.equal(P.repeat(r, 'down', 410), 'down')
  assert.equal(P.repeat(r, 'down', 450), null)
  assert.equal(P.repeat(r, 'down', 520), 'down')
  assert.equal(P.repeat(r, null, 600), null)
  assert.equal(P.repeat(r, 'down', 610), 'down')
  assert.equal(P.repeat(r, 'left', 620), 'left')
})

// ------------------------------------------------------------------ chords
test('edges: what went down and what came up', () => {
  const a = { A: true, B: false }, b = { A: false, B: true }
  const e = P.edges(a, b)
  assert.deepEqual(e.down, ['B']); assert.deepEqual(e.up, ['A'])
})

test('chord: View + LB is undo, View + RB is redo, and View alone fires on release', () => {
  const r = P.createRouter()
  assert.deepEqual(P.route(r, { down: ['VIEW'], up: [] }), [])
  const u = P.route(r, { down: ['LB'], up: [] })
  assert.deepEqual(u, [{ name: 'VIEW+LB', chord: true, action: 'undo' }])
  assert.deepEqual(P.route(r, { down: [], up: ['LB'] }), [])
  assert.deepEqual(P.route(r, { down: ['RB'], up: [] }), [{ name: 'VIEW+RB', chord: true, action: 'redo' }])
  assert.deepEqual(P.route(r, { down: [], up: ['VIEW'] }), [])          // used as a chord: no Problems
  assert.deepEqual(P.route(r, { down: ['VIEW'], up: [] }), [])
  assert.deepEqual(P.route(r, { down: [], up: ['VIEW'] }), [{ name: 'VIEW' }])
})

test('chord: LB and RB alone are plain presses, other buttons pass through while View is held', () => {
  const r = P.createRouter()
  assert.deepEqual(P.route(r, { down: ['LB'], up: [] }), [{ name: 'LB' }])
  assert.deepEqual(P.route(r, { down: ['VIEW'], up: [] }), [])
  assert.deepEqual(P.route(r, { down: ['A'], up: [] }), [{ name: 'A' }])
  assert.deepEqual(P.route(r, { down: [], up: ['VIEW'] }), [{ name: 'VIEW' }])
  // LB pressed first, then View: not a chord (View was not held first)
  const r2 = P.createRouter()
  assert.deepEqual(P.route(r2, { down: ['LB', 'VIEW'], up: [] }), [{ name: 'LB' }])
})

// ------------------------------------------------------------------ hint switching
test('hints: a pad switches to glyphs, a key or a real mouse move switches back', () => {
  let m = 'keys'
  m = P.nextMode(m, 'pad'); assert.equal(m, 'pad')
  m = P.nextMode(m, 'mouse', 1); assert.equal(m, 'pad')             // a twitch of the hand does not
  m = P.nextMode(m, 'mouse', 12); assert.equal(m, 'keys')
  m = P.nextMode(m, 'pad'); m = P.nextMode(m, 'key'); assert.equal(m, 'keys')
  m = P.nextMode('pad', 'other'); assert.equal(m, 'pad')
})

test('hints: stick drift does not count as use, a clear push does', () => {
  assert.equal(P.stickUsed({ lx: 0.1, ly: 0, rx: 0, ry: 0, lt: 0, rt: 0 }), false)
  assert.equal(P.stickUsed({ lx: 0, ly: 0, rx: 0, ry: 0.6, lt: 0, rt: 0 }), true)
  assert.equal(P.stickUsed({ lx: 0, ly: 0, rx: 0, ry: 0, lt: 0, rt: 0.9 }), true)
})

test('hints: keyboard mode shows one keyboard hint, pad mode shows glyphs per context', () => {
  assert.deepEqual(P.hintsFor('ui', 'keys'), [{ k: 'Ctrl+K', l: 'Search' }])
  const ui = P.hintsFor('ui', 'pad').map(h => h.k)
  assert.ok(ui.includes('A') && ui.includes('B') && ui.includes('Start') && ui.includes('View'))
  assert.deepEqual(P.hintsFor('view', 'pad', { placing: true }).map(h => h.l), ['Place', 'Turn', 'Cancel'])
  assert.ok(P.hintsFor('view', 'pad', { modeName: 'Move' }).some(h => h.l === 'Move'))
  for (const c of ['ui', 'view', 'play', 'osk']) for (const h of P.hintsFor(c, 'pad')) assert.ok(h.l.split(' ').length === 1, 'one word: ' + h.l)
})
