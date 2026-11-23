import test from 'node:test'
import assert from 'node:assert/strict'
import { zoomAt, clampView, boxOf, moved, wheelFactor } from '../src/graphview.js'

test('zoom keeps the point under the cursor still', () => {
  const v = { x: 20, y: 20, s: 0.8 }
  const z = zoomAt(v, 1.5, 300, 200)
  const before = [(300 - v.x) / v.s, (200 - v.y) / v.s], after = [(300 - z.x) / z.s, (200 - z.y) / z.s]
  assert.ok(Math.abs(before[0] - after[0]) < 1e-9 && Math.abs(before[1] - after[1]) < 1e-9)
})
test('zoom is limited and ignores junk factors', () => {
  assert.equal(zoomAt({ x: 0, y: 0, s: 2.4 }, 5, 0, 0).s, 2.5)
  assert.equal(zoomAt({ x: 0, y: 0, s: 0.2 }, 0.1, 0, 0).s, 0.15)
  assert.deepEqual(zoomAt({ x: 5, y: 6, s: 1 }, NaN, 10, 10), { x: 5, y: 6, s: 1 })
})
test('panning down can never push the graph off screen', () => {
  const box = boxOf({ a: { x: 0, y: 0, h: 100 }, b: { x: 390, y: 200, h: 100 } }, 300)
  assert.deepEqual(box, { x0: 0, y0: 0, x1: 690, y1: 300 })
  const c = clampView({ x: 20, y: 5000, s: 1 }, box, 800, 600)
  assert.equal(c.y, 600 - 80)
  const d = clampView({ x: 20, y: -5000, s: 1 }, box, 800, 600)
  assert.equal(d.y, 80 - 300)
  assert.equal(clampView({ x: -9e9, y: 0, s: 1 }, box, 800, 600).x, 80 - 690)
})
test('bad numbers are repaired, an empty graph is left alone', () => {
  assert.deepEqual(clampView({ x: NaN, y: Infinity, s: 0 }, null, 800, 600), { x: 0, y: 0, s: 1 })
  assert.equal(boxOf({}, 300), null)
})
test('a few pixels is a click, more is a pan', () => {
  assert.equal(moved({ x: 0, y: 0 }, { x: 2, y: 2 }), false)
  assert.equal(moved({ x: 0, y: 0 }, { x: 0, y: 9 }), true)
})
test('wheel steps zoom in on up and out on down', () => {
  assert.ok(wheelFactor({ deltaY: -100, deltaMode: 0 }) > 1)
  assert.ok(wheelFactor({ deltaY: 100, deltaMode: 0 }) < 1)
  assert.ok(wheelFactor({ deltaY: 5000, deltaMode: 0 }) > 0.5)
})
