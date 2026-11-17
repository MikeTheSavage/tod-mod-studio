import test from 'node:test'
import assert from 'node:assert/strict'
import { followScale } from '../src/scene/followScale.js'

test('a new scale carries the region polygon with it', () => {
  const poly = [[-60, 330], [240, 330], [240, 630], [-60, 630]]
  const a = { scale: 1, region: { polygon: poly, mode: 'clip' } }
  const b = followScale(a, { ...a, scale: 2 })
  assert.deepEqual(b.region.polygon, [[-120, 660], [480, 660], [480, 1260], [-120, 1260]])
  assert.equal(b.region.mode, 'clip')
  assert.equal(a.region.polygon[0][0], -60)
})

test('a region edit at the same scale is left alone', () => {
  const a = { scale: 1.5, region: { polygon: [[0, 0], [10, 0], [10, 10]] } }
  const poly = [[1, 1], [20, 1], [20, 20]]
  const b = followScale(a, { ...a, region: { polygon: poly } })
  assert.deepEqual(b.region.polygon, poly)
})

test('a scale change with no region, or a bad scale, is harmless', () => {
  assert.deepEqual(followScale({ scale: 1, region: { polygon: null } }, { scale: 2, region: { polygon: null } }).region.polygon, null)
  assert.equal(followScale({ scale: 1 }, { scale: 0 }).scale, 0)
})
