import test from 'node:test'
import assert from 'node:assert/strict'
import { isClick, clickOnly, isTap, changed, createTracker, CLICK_PX } from '../src/camdrag.js'

test('a press that stays put is a click', () => {
  assert.equal(isClick({ delta: 0, nativeEvent: { button: 0 } }), true)
  assert.equal(isClick({ delta: CLICK_PX, nativeEvent: { button: 0 } }), true)
  assert.equal(isClick({}), true)
})
test('a press that moved is a camera move', () => {
  assert.equal(isClick({ delta: CLICK_PX + 1, nativeEvent: { button: 0 } }), false)
  assert.equal(isClick({ delta: 120 }), false)
})
test('right and middle button never select', () => {
  assert.equal(isClick({ delta: 0, nativeEvent: { button: 2 } }), false)
  assert.equal(isClick({ delta: 0, nativeEvent: { button: 1 } }), false)
  assert.equal(isClick({ delta: 0, button: 2 }), false)
})
test('clickOnly runs the handler for clicks only', () => {
  let n = 0
  const f = clickOnly(() => { n++ })
  f({ delta: 0 }); f({ delta: 30 }); f({ delta: 1, nativeEvent: { button: 2 } })
  assert.equal(n, 1)
  assert.equal(clickOnly(undefined), undefined)
})
test('DOM press/release pairs', () => {
  assert.equal(isTap({ clientX: 10, clientY: 10 }, { clientX: 12, clientY: 11 }), true)
  assert.equal(isTap({ clientX: 10, clientY: 10 }, { clientX: 30, clientY: 10 }), false)
  assert.equal(isTap(null, { clientX: 0, clientY: 0 }), false)
})
test('a gizmo press with no movement is not a change', () => {
  assert.equal(changed([1, 2, 3], [1, 2, 3]), false)
  assert.equal(changed([1, 2, 3], [1, 2, 3.5]), true)
  assert.equal(changed([1, 2], [1, 2, 3]), true)
})

test('a loop that returns to where it started is still a camera move', () => {
  const t = createTracker()
  t.down(100, 100)
  for (const [x, y] of [[140, 100], [140, 140], [100, 140], [100, 100]]) t.move(x, y)
  assert.equal(isClick({ delta: 0, nativeEvent: { button: 0 } }, t), false)
  const u = createTracker()
  u.down(100, 100); u.move(102, 101)
  assert.equal(isClick({ delta: 1, nativeEvent: { button: 0 } }, u), true)
})
test('moves with no button down do not count, a new press starts over', () => {
  const t = createTracker()
  t.down(0, 0); t.move(500, 500, 0)
  assert.equal(t.travel(), 0)
  t.move(50, 0, 1); assert.equal(t.travel(), 50)
  t.down(10, 10); assert.equal(t.travel(), 0)
})
