// Pure helpers of the map building tools (src/mapbuild/geo.js). Run: node --test tests/mapbuild.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import * as G from '../src/mapbuild/geo.js'
import { EXPECT } from './mapbuild_expect.mjs'

const grid = () => ({ ox: -8, oz: -8, cell: 2, nx: 8, nz: 8, h: new Float32Array(81) })
const close = (a, b, tol = 2e-3) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < tol, `index ${i}: ${v} vs ${b[i]}`))

test('the live brush matches the builder: raise', () => {
  const g = grid(); G.applyStroke(g, { tool: 'raise', pos: [0, 0], radius: 6, strength: 1 }); close(Array.from(g.h), EXPECT[0])
})
test('the live brush matches the builder: raise then smooth', () => {
  const g = grid(); G.applyStroke(g, { tool: 'raise', pos: [1, 1], radius: 6, strength: 2 }); G.applyStroke(g, { tool: 'smooth', pos: [0, 0], radius: 8, strength: 1, passes: 2 }); close(Array.from(g.h), EXPECT[1])
})
test('the live brush matches the builder: raise, flatten, ramp', () => {
  const g = grid()
  G.applyStroke(g, { tool: 'raise', pos: [-2, 0], radius: 5, strength: 3 }); G.applyStroke(g, { tool: 'flatten', pos: [2, 2], radius: 6, strength: 0.7, height: 1.5 })
  G.applyStroke(g, { tool: 'ramp', pos: [-4, -4], to: [4, 4], radius: 3, strength: 1, height: 0, to_height: 5 }); close(Array.from(g.h), EXPECT[2])
})
test('height and slope on a plane', () => {
  const g = grid()
  for (let j = 0; j <= 8; j++) for (let i = 0; i <= 8; i++) g.h[j * 9 + i] = (g.ox + i * 2) * 0.1
  assert.ok(Math.abs(G.heightAt(g, 1, 1) - 0.1) < 1e-6)
  assert.ok(Math.abs(G.slopeAt(g, 0, 0) - 0.1) < 1e-6)
  assert.equal(G.triangles(g), 128)
})
test('spline passes the control points and is evenly resampled', () => {
  const sp = G.spline([[0, 0], [20, 0], [20, 20]], 2)
  assert.deepEqual(sp.xz[0].map(Math.round), [0, 0]); assert.deepEqual(sp.xz[sp.xz.length - 1].map(Math.round), [20, 20])
  assert.equal(sp.at.length, 3)
  const mid = sp.xz.reduce((b, p) => (Math.hypot(p[0] - 20, p[1]) < Math.hypot(b[0] - 20, b[1]) ? p : b))
  assert.ok(Math.hypot(mid[0] - 20, mid[1]) < 1.2)
})
test('road slope: a bridge follows its pinned heights, a draped road the ground', () => {
  const g = grid()
  const flat = G.roadProfile({ points: [[-6, 0], [6, 0]] }, g)
  assert.ok(flat.every(p => p.slope < 1e-6))
  const bridge = G.roadProfile({ elevated: true, points: [[-6, 0], [-2, 0, 8], [2, 0, 8], [6, 0]] }, g)
  assert.ok(Math.max(...bridge.map(p => p.slope)) > 0.5)
  assert.equal(G.slopeClass(0.1), 'ok'); assert.equal(G.slopeClass(0.2), 'hard'); assert.equal(G.slopeClass(0.5), 'steep')
})
test('polygons', () => {
  const sq = G.polyOf({ rect: [4, 4, 0, 0] })
  assert.equal(G.polyArea(sq), 16); assert.ok(G.inPoly(2, 2, sq)); assert.ok(!G.inPoly(5, 2, sq))
  assert.equal(G.polyOf({ circle: [0, 0, 10] }).length, 24)
  assert.deepEqual(G.rectOf([5, 1], [2, 7]), [2, 1, 5, 7])
})
test('ids, stamps and sections', () => {
  assert.equal(G.newId([{ id: 'road1' }, { id: 'road2' }], 'road'), 'road3')
  const s = G.stampsAlong([0, 0], [10, 0], 2.5); assert.equal(s.length, 4); assert.deepEqual(s[3], [10, 0])
  assert.equal(G.sectionAt([{ id: 'a', rect: [0, 0, 5, 5] }], 2, 2), 'a'); assert.equal(G.sectionAt([{ id: 'a', rect: [0, 0, 5, 5] }], 9, 9), null)
})
test('packed arrays round trip', () => {
  const f = new Float32Array([1.5, -2, 3]); const b64 = G.bytesToB64(new Uint8Array(f.buffer))
  assert.deepEqual(Array.from(G.f32(b64)), [1.5, -2, 3])
})
