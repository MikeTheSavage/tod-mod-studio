import test from 'node:test'
import assert from 'node:assert/strict'
import * as C from '../src/vendor/cannon-es.js'
import { createDrive } from '../src/tune/drive.js'
import * as M from '../src/tune/mapping.js'

const F = (group, kv, prefix) => ({ group, fields: Object.entries(kv).map(([label, value]) => ({ key: prefix + '.' + label, label, value })) })
const data = { groups: [
  F('Vehicle type: Sedan', { Mass: 750, drag_coeff: 7, BrakeForce: 12000, cornering_stiffness: 1.2, lateral_slide_speed: 17, slide_factor: 1.3,
    spring_k: 40, spring_damping: 2.5, WheelRadius: 0.45, Vehicle_Length: 5.58, Vehicle_Width: 2.34, Inertial_Height: 1.8 }, 'type.Sedan'),
  F('Car handling (all cars)', { max_engine_force: 12000, max_reverse_force: 6000, rolling_res: 189, max_turn: 0.785, turn_rate: 0.174 }, 'car')] }

function run(secs, input, vals = {}) {
  const v = M.vehicleOf(data, vals, 'Vehicle type: Sedan')
  const ph = M.physicsFor(v)
  const d = createDrive(C, { ...ph, ...v, steerAngle: undefined }, { y: 1.2 })
  d.addGround([d.plane(0)])
  for (let i = 0; i < 120; i++) d.step(1 / 60, {})            // settle
  const p0 = d.pose()
  let fwd0 = p0.p.z
  for (let i = 0; i < secs * 60; i++) d.step(1 / 60, input)
  return { d, ph, p: d.pose(), z0: fwd0 }
}

test('the car drives forward (+z) when the throttle is held and settles near the game top speed', () => {
  const { p, ph, z0 } = run(14, { throttle: 1 })
  assert.ok(p.p.z - z0 > 100, 'moved forward ' + (p.p.z - z0))
  assert.ok(Math.abs(p.vF - ph.topSpeed) / ph.topSpeed < 0.25, `${p.vF} vs ${ph.topSpeed}`)
  assert.ok(p.p.y > 0.2 && p.p.y < 2.5, 'stays on its wheels ' + p.p.y)
})
test('brakes stop it and reverse goes backwards', () => {
  const { d } = run(6, { throttle: 1 })
  for (let i = 0; i < 60 * 8; i++) d.step(1 / 60, { brake: 1 })
  assert.ok(Math.abs(d.pose().vF) < 1.0, 'stopped ' + d.pose().vF)
  const z = d.pose().p.z
  for (let i = 0; i < 60 * 3; i++) d.step(1 / 60, { throttle: -1 })
  assert.ok(d.pose().p.z < z - 1, 'reversed')
})
test('steering turns the car; a stronger engine is faster', () => {
  const a = run(6, { throttle: 1, steer: 1 })
  const dx = a.p.p.x
  assert.ok(Math.abs(dx) > 3, 'turned ' + dx)
  const b = run(8, { throttle: 1 }), c = run(8, { throttle: 1 }, { 'car.max_engine_force': 24000 })
  assert.ok(c.p.vF > b.p.vF)
})

import { heightMesh, steepMesh, trimeshBody } from '../src/tune/drive.js'
test('a ground made of separate pieces with a crack becomes one surface the wheel rays hit', () => {
  // two slabs at y = 5 with a 0.6 m crack between them (open meshes, wound either way)
  const slab = (x0, x1, flip) => ({ verts: [x0, 5, -10, x1, 5, -10, x1, 5, 10, x0, 5, 10], idx: flip ? [0, 2, 1, 0, 3, 2] : [0, 1, 2, 0, 2, 3] })
  const hm = heightMesh([slab(-10, -0.3, false), slab(0.3, 10, true)], 0, 0, 8, 1)
  assert.ok(hm && hm.idx.length > 0)
  const w = new C.World()
  w.addBody(trimeshBody(C, hm.verts, hm.idx, 1))
  for (const x of [-4, -0.2, 0, 0.2, 4]) {
    const r = new C.RaycastResult()
    w.raycastClosest(new C.Vec3(x, 20, 0), new C.Vec3(x, -20, 0), { skipBackfaces: true }, r)
    assert.ok(r.hasHit, 'ray at ' + x)
    assert.ok(Math.abs(r.hitPointWorld.y - 5) < 1e-6)
  }
})
test('walls are the steep triangles only', () => {
  const g = { verts: [0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 3, 0, 1, 0, 0], idx: [0, 1, 2, 3, 4, 5] }   // one flat, one vertical
  const wm = steepMesh([g])
  assert.equal(wm.idx.length / 6, 1)
  assert.equal(steepMesh([{ verts: g.verts, idx: [0, 1, 2] }]), null)
})
