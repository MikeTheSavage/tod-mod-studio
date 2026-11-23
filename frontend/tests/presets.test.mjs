import test from 'node:test'
import assert from 'node:assert/strict'
import * as P from '../src/tune/presets.js'

// a tiny Vehicles data set: the shipped values of two cars, a truck that never slides, and the shared car values
const F = (group, kv, prefix) => ({ group, fields: Object.entries(kv).map(([label, value]) => ({ key: prefix + '.' + label, label, value })) })
const data = { groups: [
  F('Vehicle type: Sedan', { Mass: 750, cornering_stiffness: 1.2, lateral_slide_speed: 17, slide_factor: 1, control_speed: 8, time_to_slide_factor: 0.7, spring_k: 40 }, 'type.Sedan'),
  F('Vehicle type: Taxi', { Mass: 700, cornering_stiffness: 0.95, lateral_slide_speed: 17, slide_factor: 0.8, control_speed: 2.5, time_to_slide_factor: 1 }, 'type.Taxi'),
  F('Vehicle type: BurritoCart', { Mass: 1000, cornering_stiffness: 0.66, lateral_slide_speed: 10, slide_factor: 0, control_speed: 1, time_to_slide_factor: 1 }, 'type.BurritoCart'),
  F('Car handling (all cars)', { turn_rate: 0.174, slide_angle: 0.174, standard_sideways_slide_resistance: 0.6 }, 'car')] }
const shipped = P.shippedIndex(data)
const demo = { name: 'Demo', type: { cornering_stiffness: { mul: 1.5 }, lateral_slide_speed: { mul: 0.5 }, slide_factor: { mul: 3 }, control_speed: { set: 4 }, Mass: { add: -50 } },
  car: { turn_rate: { set: 0.25 }, slide_angle: { set: 0.1 } } }

test('a preset on one vehicle writes concrete numbers computed from the shipped values', () => {
  const plan = P.planApply(demo, { kind: 'one', row: 'Sedan' }, shipped)
  assert.equal(plan.set['type.Sedan.cornering_stiffness'], 1.8)
  assert.equal(plan.set['type.Sedan.lateral_slide_speed'], 8.5)
  assert.equal(plan.set['type.Sedan.slide_factor'], 3)
  assert.equal(plan.set['type.Sedan.control_speed'], 4)
  assert.equal(plan.set['type.Sedan.Mass'], 700)
  assert.equal(Object.keys(plan.set).some(k => k.startsWith('type.Taxi') || k.startsWith('car.')), false, 'one vehicle, no shared values')
})

test('shared car values are written only when the target is every car', () => {
  assert.deepEqual(Object.keys(P.planApply(demo, { kind: 'class', cls: 'cars' }, shipped).set).filter(k => k.startsWith('car.')), [])
  const all = P.planApply(demo, { kind: 'all' }, shipped)
  assert.equal(all.set['car.turn_rate'], 0.25)
  assert.equal(all.set['car.slide_angle'], 0.1)
})

test('a group covers exactly its vehicles; a value that is zero in the game stays zero', () => {
  const cls = P.planApply(demo, { kind: 'class', cls: 'heavy' }, shipped)
  assert.equal(cls.set['type.BurritoCart.slide_factor'], undefined, 'never slides stays never slides')
  assert.equal(cls.set['type.BurritoCart.cornering_stiffness'], 0.99)
  assert.equal(Object.keys(cls.set).some(k => k.startsWith('type.Sedan')), false)
})

test('every value is kept inside the range of its field', () => {
  const p = { name: 'x', type: { Mass: { set: -5 }, cornering_stiffness: { mul: 100 }, control_speed: { set: 1e9 } }, car: { max_turn: { set: 9 } } }
  const plan = P.planApply(p, { kind: 'all' }, shipped)
  assert.equal(plan.set['type.Sedan.Mass'], P.FIELDS.type.Mass.lo)
  assert.equal(plan.set['type.Sedan.cornering_stiffness'], P.FIELDS.type.cornering_stiffness.hi)
  assert.equal(plan.set['type.Sedan.control_speed'], P.FIELDS.type.control_speed.hi)
  assert.equal(plan.set['car.max_turn'], P.FIELDS.car.max_turn.hi)
})

test('applying keeps what you changed by hand; Vanilla clears the driving fields of the target', () => {
  const mine = { 'type.Sedan.Mass': 900, 'type.Sedan.Health': 9999, 'type.Taxi.Mass': 650 }
  const after = P.applyPlan(mine, P.planApply({ name: 'x', type: { slide_factor: { set: 2 } }, car: {} }, { kind: 'one', row: 'Sedan' }, shipped))
  assert.equal(after['type.Sedan.Mass'], 900)
  assert.equal(after['type.Sedan.slide_factor'], 2)
  const back = P.applyPlan(after, P.planRestore({ kind: 'one', row: 'Sedan' }))
  assert.deepEqual(back, { 'type.Sedan.Health': 9999, 'type.Taxi.Mass': 650 }, 'driving fields gone, the rest untouched')
})

test('a value equal to the shipped one is cleared, not stored', () => {
  const plan = P.planApply({ name: 'x', type: { lateral_slide_speed: { set: 17 } }, car: {} }, { kind: 'one', row: 'Sedan' }, shipped)
  assert.deepEqual(plan, { set: {}, clear: ['type.Sedan.lateral_slide_speed'] })
})

test('a preset made from one vehicle fits any vehicle (factors of the shipped value)', () => {
  const vals = { 'type.Sedan.cornering_stiffness': 1.8, 'type.Sedan.slide_factor': 2, 'type.Sedan.Health': 9, 'car.turn_rate': 0.25 }
  const p = P.captureFrom(vals, shipped, 'Sedan', 'Mine')
  assert.deepEqual(p.type, { cornering_stiffness: { mul: 1.5 }, slide_factor: { mul: 2 } })
  assert.deepEqual(p.car, { turn_rate: { set: 0.25 } })
  const taxi = P.planApply(p, { kind: 'one', row: 'Taxi' }, shipped)
  assert.equal(taxi.set['type.Taxi.cornering_stiffness'], 1.425)
})

test('a shared file round-trips and a foreign or hostile file is cleaned', () => {
  const p = { name: 'Round trip', type: { slide_factor: { mul: 2 }, control_speed: { set: 4 } }, car: { turn_rate: { set: 0.25 } } }
  const r = P.fromFile(P.toFile(p))
  assert.deepEqual(r.preset, p)
  assert.equal(r.dropped, 0)
  assert.ok(P.fromFile('{"a":1}').error)
  assert.ok(P.fromFile('not json').error)
  const bad = P.fromFile(JSON.stringify({ format: P.FORMAT, version: 1, name: 'Evil\u0007', type: { spring_k: { set: 999 }, Health: { set: 1 }, slide_factor: { mul: 9999 }, Mass: { set: 'x' } }, car: { max_turn: { set: 99 }, foo: { set: 1 } } }))
  assert.deepEqual(Object.keys(bad.preset.type), ['slide_factor'], 'only driving fields get through (no suspension)')
  assert.equal(bad.preset.type.slide_factor.mul, 20)
  assert.equal(bad.preset.car.max_turn.set, P.FIELDS.car.max_turn.hi)
  assert.equal(bad.dropped, 4)
  assert.equal(bad.preset.name, 'Evil')
  assert.ok(P.fromFile(JSON.stringify({ format: P.FORMAT, version: 1, name: 'n', type: { Health: { set: 1 } }, car: {} })).error, 'nothing usable is refused')
})

test('no preset and no preset field touches the suspension (body roll)', () => {
  const all = [...P.TYPE_KEYS, ...P.CAR_KEYS]
  for (const k of ['spring_k', 'spring_damping', 'stiffness']) assert.equal(all.includes(k), false, k)
  for (const b of P.BUILTIN) for (const k of [...Object.keys(b.type), ...Object.keys(b.car)]) assert.equal(all.includes(k), true, b.id + ' ' + k)
})

test('the built-in presets use known fields and keep every shipped vehicle inside the ranges', () => {
  assert.deepEqual(P.BUILTIN.map(b => b.id), ['drift', 'arcade', 'heavy'])
  for (const b of P.BUILTIN) {
    assert.ok(b.name && b.tip, b.id)
    assert.ok(!P.isEmpty(b), b.id + ' is not empty')
    const plan = P.planApply(b, { kind: 'all' }, shipped)
    for (const [k, v] of Object.entries(plan.set)) {
      const [g, , prop] = k.startsWith('car.') ? ['car', null, k.slice(4)] : k.split('.')
      const f = P.FIELDS[g === 'type' ? 'type' : 'car'][prop]
      assert.ok(v >= f.lo && v <= f.hi, `${b.id} ${k}=${v}`)
    }
  }
})

test('every field has a one-line tip', () => {
  for (const g of ['type', 'car']) for (const [k, f] of Object.entries(P.FIELDS[g])) { assert.ok(f.tip && f.tip.length < 100, k); assert.equal(P.tipOf(k).startsWith(f.tip), true) }
})
