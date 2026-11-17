import test from 'node:test'
import assert from 'node:assert/strict'
import * as W from '../src/world/worldlib.js'

test('own rect from terrain and from the size preset', () => {
  assert.deepEqual(W.ownRect({ terrain: { cell: 2, size: [40, 20] } }), [-40, -20, 40, 20])
  assert.deepEqual(W.ownRect({ terrain: { cell: 2, size: [10, 10], origin: [5, 6] } }), [5, 6, 25, 26])
  assert.deepEqual(W.rectSize(W.ownRect({ card: { size: 'small' }, arrival: { pos: [0, 0, 0] } })), [80, 80])
})
test('corners turn about the anchor', () => {
  const c = W.atlasCorners([-10, -5, 10, 5], [100, 100], 0)
  assert.deepEqual(c[0], [90, 95])
  const d = W.atlasCorners([-10, -5, 10, 5], [0, 0], 90).map(p => p.map(v => Math.round(v)))
  assert.equal(Math.max(...d.map(p => Math.abs(p[0]))), 5)
})
test('snap to a neighbour edge, nothing beyond the distance', () => {
  const s = W.snapFootprint([95, 0], [100, 100], [[0, -50, 40, 50]], 40)
  assert.equal(s.pos[0], 90)                     // left edge 45 -> 40 is not within; right edge? left edge at 45, neighbour right edge 40: moves -5
  assert.equal(s.guides.some(g => g.axis === 'x'), true)
  const far = W.snapFootprint([500, 500], [100, 100], [[0, 0, 40, 40]], 40)
  assert.deepEqual(far.pos, [500, 500])
})
test('yaw snaps to 15 and wraps', () => {
  assert.equal(W.snapYaw(97), 90)
  assert.equal(W.snapYaw(181), -180)
  assert.equal(W.compassOf(90), 'E')
})
test('guard flags a far map and an overlap', () => {
  assert.equal(W.guard([0, 0, 10, 10], []).out, false)
  assert.equal(W.guard([20000, 0, 20010, 10], []).out, true)
  assert.deepEqual(W.guard([0, 0, 10, 10], [[5, 5, 20, 20], [30, 30, 40, 40]]).over, [0])
})
test('a map needs one unlocked way out', () => {
  assert.equal(W.wayOut({ entries: [{ id: 'a', block: 'x' }] }), false)
  assert.equal(W.wayOut({ return: { pos: [0, 0, 0] }, entries: [] }), true)
  assert.equal(W.wayOut({ entries: [{ id: 'a', back: { pos: [0, 0, 0] }, one_way: true }] }), false)
  assert.equal(W.wayOut({ entries: [{ id: 'a', back: { pos: [0, 0, 0] } }] }), true)
})
test('vehicle box size rule', () => {
  assert.equal(W.vehicleOk({ vehicle: true, size: [12, 6, 2] }), false)
  assert.equal(W.vehicleOk({ vehicle: true, size: [16, 6, 8] }), true)
  assert.equal(W.vehicleOk({ size: [1, 1, 1] }), true)
})
test('entrance table rows', () => {
  const rows = W.entranceRows({ maps: [{ name: 'M', entries: [{ id: 'a', block: 'x.submap', lock: { mission: 5 }, prompt: 'use', back: { pos: [0, 0, 0] } }, { id: 'b', block: 'y.submap', one_way: true }] }] })
  assert.equal(rows.length, 2)
  assert.equal(rows[0].lock, 5)
  assert.equal(rows[0].mode, 'foot / use')
  assert.equal(rows[1].back, 'no')
})
test('readiness counts errors and warnings per map and blocks install', () => {
  const p = { maps: [{ name: 'A', entries: [{ id: 'a', block: 'x' }] }, { name: 'B', return: { pos: [0, 0, 0] } }] }
  const r = W.readiness(p, [{ map: 1, level: 'warn', title: 'w' }], [])
  assert.equal(r[0].errors, 1)
  assert.equal(r[1].warns, 1)
  assert.equal(W.blocked(r, []), true)
  assert.equal(W.blocked([{ errors: 0 }], [{ level: 'warn' }]), false)
})
test('stand-in cells are moved by the layout', () => {
  const b = { 'a.map': { map: 'map01', kind: 'map', box: [0, 0, 100, 100], cell: 40, cells: [[0, 0, 3]] } }
  const s = W.standIn(b, 'map01', { map01: [1000, 2000] })
  assert.deepEqual(s.box, [1000, 2000, 1100, 2100])
  assert.deepEqual(s.cells[0], [1020, 2020, 40, 3])
})
test('arrival of an entrance falls back to the map arrival', () => {
  const m = { arrival: { pos: [1, 2, 3], orient: [0, 0, 0, 1] } }
  assert.deepEqual(W.arriveOf(m, {}).pos, [1, 2, 3])
  assert.deepEqual(W.arriveOf(m, { arrive: { pos: [9, 9, 9], yaw: 90 } }).yaw, 90)
})
test('map id comes from the _mapNN_ part, not from submapNN', () => {
  assert.equal(W.mapIdOf('submap01_map02_lostoros_downtown.submap'), 'map02')
  assert.equal(W.mapIdOf('data/x/mainmap_map10_runawaytrain.map'), 'map10')
  assert.equal(W.mapIdOf('map04'), 'map04')
})
test('labels that overlap are spread and keep a leader; lone labels stay', () => {
  const r = W.declutter([{ id: 'a', x: 0, z: 0 }, { id: 'b', x: 10, z: 2 }, { id: 'c', x: 5000, z: 0 }], 100, 40)
  const by = Object.fromEntries(r.map(x => [x.id, x]))
  assert.equal(by.c.moved, false)
  assert.equal(by.a.moved === by.b.moved, false)                        // exactly one of the two clashing labels moves
  const moved = r.find(x => x.moved)
  assert.ok(Math.abs(moved.lz - moved.z) >= 40)
  assert.equal(W.declutter([{ id: 'a', x: 0, z: 0 }, { id: 'b', x: 10, z: 2 }], 100, 40)[0].id, W.declutter([{ id: 'b', x: 10, z: 2 }, { id: 'a', x: 0, z: 0 }], 100, 40)[0].id)
})
test('a problem is sent to the area and tool that fix it', () => {
  assert.deepEqual(W.jumpOf('Ground triangles: 100,000 of 90,000'), { screen: 'newmaps', area: 'map', tool: 'terrain' })
  assert.deepEqual(W.jumpOf('section X: edge of view: 12 sight lines'), { screen: 'newmaps', area: 'atlas' })
  assert.deepEqual(W.jumpOf('The arrival lies outside the map ground', 'arrival', 1), { screen: 'newmaps', area: 'entrances', map: 1 })
  assert.deepEqual(W.jumpOf('Ground at the seam differs by 2 m', 'seam').area, 'atlas')
  assert.equal(W.jumpOf('minimap area of X').tool, 'minimap')
  assert.equal(W.jumpOf('The look is dark').tool, 'look')
})
test('arrows point where the engine faces: yaw 0 is +z, 90 is -x, 270 is +x', async () => {
  const C = await import('../src/coords.js')
  const near = (a, b) => Math.abs(a - b) < 1e-9
  for (const [yaw, x, z] of [[0, 0, 1], [90, -1, 0], [180, 0, -1], [270, 1, 0]]) {
    const f = C.facingDir(yaw)
    assert.ok(near(f[0], x) && near(f[1], z), `facingDir ${yaw}`)
    // the drawn arrow: a box group turned by the plain quaternion, the arrow turned back by facingQuat, tip at game +z
    const { Vector3, Quaternion } = await import('three')
    const parent = C.quatToView(C.quatFromYaw(yaw)), child = C.facingQuat(yaw)
    const tip = C.fromView(new Vector3(0, 0, -1).applyQuaternion(child).applyQuaternion(new Quaternion(parent.x, parent.y, parent.z, parent.w)))
    assert.ok(near(tip[0], x) && near(tip[2], z), `drawn arrow ${yaw}: ${tip}`)
  }
})
