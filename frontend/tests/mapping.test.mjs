import test from 'node:test'
import assert from 'node:assert/strict'
import * as M from '../src/tune/mapping.js'

const F = (group, kv, prefix) => ({ group, fields: Object.entries(kv).map(([label, value]) => ({ key: prefix + '.' + label, label, value })) })
const data = {
  groups: [
    F('Beretta (Gun_Light)', { ClipSize: 10, ReloadTime: 1, FireRate: 150, ManualFireRate: 350, BulletsPerShot: 1, ShortRangeDamage: 30,
      MediumRangeDamage: 20, LongRangeDamage: 10, ShortRange: 9, MediumRange: 17, MaxRange: 30, SpreadMin: 1.3, SpreadMax: 1.3, SpreadInc: 0 }, 'weapons.Beretta'),
    F('Benelli (Combat)', { ClipSize: 6, ReloadTime: 1.5, FireRate: 55, ManualFireRate: 200, BulletsPerShot: 10, ShortRangeDamage: 22,
      MediumRangeDamage: 16, LongRangeDamage: 10, ShortRange: 8, MediumRange: 15, MaxRange: 25, SpreadMin: 3.5, SpreadMax: 3.5, SpreadInc: 0 }, 'weapons.Benelli'),
    F('Mac10 (sub_automatic_light)', { ClipSize: 30, ReloadTime: 0.7, FireRate: 750, ManualFireRate: 750, BulletsPerShot: 1, ShortRangeDamage: 17,
      MediumRangeDamage: 13, LongRangeDamage: 11, ShortRange: 8, MediumRange: 16, MaxRange: 25, SpreadMin: 0.5, SpreadMax: 8.5, SpreadInc: 5 }, 'weapons.Mac10'),
    F('Vehicle type: Sedan', { Mass: 750, drag_coeff: 7, BrakeForce: 12000, cornering_stiffness: 1.2, lateral_slide_speed: 17, slide_factor: 1.3,
      spring_k: 40, spring_damping: 2.5, WheelRadius: 0.45, Vehicle_Length: 5.58, Vehicle_Width: 2.34, Inertial_Height: 1.8 }, 'type.Sedan'),
    F('Car handling (all cars)', { max_engine_force: 12000, max_reverse_force: 6000, rolling_res: 189, max_turn: 0.785, turn_rate: 0.174 }, 'car'),
    F('Slow motion and stamina', { slowmo_cost_per_s: 125, gain_standing: 150, gain_running: 80 }, 'stamina'),
    F('Camera type CharacterCombatCam', { MaxAngle: 2, AngleEaseInSpeed: 7.5, MaxDistance: 0.5, DistanceMoveInSpeed: 2, DistanceZFactor: 0.5 }, 'cameradict.CharacterCombatCam'),
    F('Player camera', { back: 0, up: 0 }, 'player'),
  ],
}

// ---- weapons: damage per distance band
test('damage steps by band and is zero beyond the longest shot', () => {
  const w = M.weaponOf(data, {}, 'Beretta (Gun_Light)')
  assert.equal(M.damageAt(w, 0), 30)
  assert.equal(M.damageAt(w, 9), 30)           // the band edge belongs to the closer band
  assert.equal(M.damageAt(w, 9.01), 20)
  assert.equal(M.damageAt(w, 17), 20)
  assert.equal(M.damageAt(w, 17.5), 10)
  assert.equal(M.damageAt(w, 30), 10)
  assert.equal(M.damageAt(w, 30.01), 0)
  assert.deepEqual(M.bands(w).map(b => [b.name, b.to, b.damage]), [['close', 9, 30], ['medium', 17, 20], ['long', 30, 10]])
})
test('every pellet carries the full band damage', () => {
  const w = M.weaponOf(data, {}, 'Benelli (Combat)')
  assert.equal(M.damagePerShot(w, 8), 220)     // 10 x 22, as in the research notes
  assert.equal(M.damagePerShot(w, 8, 3), 66)
  assert.equal(M.damagePerShot(w, 20), 100)
  assert.equal(M.damagePerShot(w, 40), 0)
})
test('headshot factor and shooter mod multiply', () => {
  const w = M.weaponOf(data, {}, 'Beretta (Gun_Light)')
  assert.equal(M.hitDamage(w, 5, { head: 0.5 }), 15)
  assert.equal(M.hitDamage(w, 5, { head: 2, mod: 0.25 }), 15)
})
test("the mod's values replace the defaults and 'game default' ignores them", () => {
  const vals = { 'weapons.Beretta.ShortRangeDamage': 300, 'weapons.Beretta.ShortRange': 12 }
  assert.equal(M.damageAt(M.weaponOf(data, vals, 'Beretta (Gun_Light)'), 11), 300)
  assert.equal(M.damageAt(M.weaponOf(data, vals, 'Beretta (Gun_Light)', false), 11), 20)
})
test('fire rate runs on the real clock x 0.95; magazine and dps follow', () => {
  const w = M.weaponOf(data, {}, 'Beretta (Gun_Light)')
  assert.ok(Math.abs(M.rateOfFire(w) - 142.5) < 1e-9)
  assert.ok(Math.abs(M.shotInterval(w, true) - 60 / 142.5) < 1e-9)
  assert.ok(Math.abs(M.shotInterval(w, false) - 60 / (350 * 0.95)) < 1e-9)
  assert.ok(Math.abs(M.magazineSeconds(w) - 10 * 60 / 142.5) < 1e-9)
  assert.ok(Math.abs(M.dps(w, 5) - 30 * 142.5 / 60) < 1e-9)
})
test('spread grows while held (automatics) and stays between min and max', () => {
  const mac = M.weaponOf(data, {}, 'Mac10 (sub_automatic_light)')
  assert.equal(M.spreadAt(mac, 0), 0.5)
  assert.ok(Math.abs(M.spreadAt(mac, 1) - 5.5) < 1e-9)
  assert.equal(M.spreadAt(mac, 10), 8.5)       // capped; 0.5 -> 8.5 takes 1.6 s
  const ber = M.weaponOf(data, {}, 'Beretta (Gun_Light)')
  assert.equal(M.spreadAt(ber, 5), 1.3)
  const [a, b] = M.pelletAngles(4, 0, 1)
  assert.deepEqual([a, b], [-4, 4])
  assert.deepEqual(M.pelletAngles(4, 0.5, 0.5), [0, 0])
})

// ---- vehicles
test('top speed reproduces the research table (Sedan 108 km/h, steering gone 90, slide from 61)', () => {
  const v = M.vehicleOf(data, {}, 'Vehicle type: Sedan')
  const s = M.vehicleStats(v)
  assert.ok(Math.abs(s.topKmh - 108) < 1, s.topKmh)
  assert.ok(Math.abs(s.reverseKmh - 67) < 1, s.reverseKmh)
  assert.ok(Math.abs(s.steeringGoneKmh - 90) < 1, s.steeringGoneKmh)
  assert.ok(Math.abs(s.slideFromKmh - 61) < 1, s.slideFromKmh)
  assert.ok(Math.abs(s.minRadius - 5.8) < 0.2, s.minRadius)
  assert.ok(Math.abs(s.time0to(100) - 3.6) < 0.4, s.time0to(100))
})
test('vehicle parameters map onto the physics engine', () => {
  const v = M.vehicleOf(data, { 'car.max_engine_force': 24000 }, 'Vehicle type: Sedan')
  const p = M.physicsFor(v)
  assert.equal(p.mass, 750)
  assert.equal(p.engineForce, 24000)
  assert.equal(p.brakeForce, 12000)
  assert.equal(p.suspensionStiffness, 40)
  assert.equal(p.wheelRadius, 0.45)
  assert.ok(p.topSpeed > M.physicsFor(M.vehicleOf(data, {}, 'Vehicle type: Sedan')).topSpeed)
  const slick = M.physicsFor(M.vehicleOf(data, { 'type.Sedan.slide_factor': 6 }, 'Vehicle type: Sedan'))
  assert.ok(slick.slideGrip < M.physicsFor(M.vehicleOf(data, {}, 'Vehicle type: Sedan')).slideGrip)
})
test('the damping settles a chassis at the game top speed', () => {
  const p = M.physicsFor(M.vehicleOf(data, {}, 'Vehicle type: Sedan'))
  let v = 0
  const dt = 1 / 60
  for (let i = 0; i < 60 * 60; i++) { v += p.engineForce / p.mass * dt; v *= Math.pow(1 - p.linearDamping, dt) }
  assert.ok(Math.abs(v - p.topSpeed) / p.topSpeed < 0.04, `${v} vs ${p.topSpeed}`)
})
test('steering shrinks with speed, ramps by turn_rate per step and snaps back on release', () => {
  const v = M.vehicleOf(data, {}, 'Vehicle type: Sedan')
  const slow = M.steerAngle(v, 1, 0), fast = M.steerAngle(v, 1, 20)
  assert.ok(Math.abs(slow - 0.785) < 1e-9)
  assert.ok(fast < slow && fast > 0)
  assert.ok(Math.abs(M.steerAngle(v, 1, 40) - 0.785 * 0.001) < 1e-9)    // below the floor at top speed
  assert.ok(Math.abs(M.steerRamp(0, 0.785, 0.04, v) - 0.174) < 1e-9)
  assert.equal(M.steerRamp(0.5, 0, 0.04, v), 0)
})

// ---- slow motion
test('automatic slow motion lasts stamina / cost real seconds', () => {
  const p = M.slowmoOf(data, {})
  const s = M.slowmoSummary(p)
  assert.ok(Math.abs(s.real - 999 / 125) < 1e-9)
  assert.ok(s.game < s.real * 0.2)
  assert.ok(Math.abs(s.recharge - 1000 / 150) < 1e-9)
  const cheap = M.slowmoSummary(M.slowmoOf(data, { 'stamina.slowmo_cost_per_s': 50 }))
  assert.ok(cheap.real > s.real * 2)
})
test('the time scale ramps in, holds, ramps out', () => {
  const p = M.slowmoOf(data, {})
  const real = 4
  assert.equal(M.timeScaleAt(-1, p, 0.11, real), 1)
  assert.ok(Math.abs(M.timeScaleAt(0.1, p, 0.11, real) - 0.555) < 1e-9)
  assert.equal(M.timeScaleAt(2, p, 0.11, real), 0.11)
  assert.ok(Math.abs(M.timeScaleAt(4.05, p, 0.11, real) - 0.555) < 1e-9)
  assert.equal(M.timeScaleAt(5, p, 0.11, real), 1)
})
test('slow motion needs stamina to start, drains in real time and recharges', () => {
  const p = M.slowmoOf(data, {})
  let s = { stamina: 40, scale: 1, on: false }
  s = M.stepSlowmo(s, p, 0.1, true)
  assert.equal(s.on, false)                                    // under the start stamina
  s = { stamina: 1000, scale: 1, on: false }
  for (let i = 0; i < 10; i++) s = M.stepSlowmo(s, p, 0.1, true)
  assert.equal(s.on, true)
  assert.ok(Math.abs(s.stamina - (1000 - 125)) < 1e-6)        // 1 real second
  assert.ok(Math.abs(s.scale - 0.11) < 1e-9)
  for (let i = 0; i < 100; i++) s = M.stepSlowmo(s, p, 0.1, true)
  assert.equal(s.on, false)                                    // ran dry
  for (let i = 0; i < 100; i++) s = M.stepSlowmo(s, p, 0.1, false)
  assert.equal(s.scale, 1)
  assert.ok(s.stamina > 900)
})

// ---- camera
test('the camera rig starts 3.26 m behind and moves with back / up / pitch', () => {
  const base = M.cameraPose(M.cameraOf(data, {}))
  assert.ok(Math.abs(base.behind - 3.26) < 1e-9)
  assert.equal(base.pitch, 10)
  const back = M.cameraPose(M.cameraOf(data, { 'player.back': 2 }))
  assert.ok(back.behind > base.behind + 1.9 && back.behind < base.behind + 2.001)
  assert.ok(back.height > base.height)                         // moving back along a downward line of sight raises it
  const up = M.cameraPose(M.cameraOf(data, { 'player.up': 0.5 }))
  assert.ok(Math.abs(up.height - base.height - 0.5) < 1e-9)
  assert.equal(M.cameraPose(M.cameraOf(data, { 'player.pitch_deg': 25 })).pitch, 25)
})
test('field of view 64 is the 4:3 horizontal angle; wide screens widen sideways only', () => {
  const a = M.fovDeg(4 / 3), b = M.fovDeg(16 / 9)
  assert.ok(Math.abs(a.horizontal - 64) < 1e-6)
  assert.ok(Math.abs(a.vertical - 50.2) < 0.1)
  assert.ok(Math.abs(b.horizontal - 79.6) < 0.2)
  assert.ok(Math.abs(b.vertical - a.vertical) < 1e-9)
})
test('the rig yaw eases toward Ram and never jumps more than maxAngle', () => {
  const c = M.cameraOf(data, {})
  const y = M.followYaw(0, 1, c, 0.016)
  assert.ok(y > 0 && y < 1)
  const tight = { ...c, maxAngle: 0.01 }
  assert.ok(Math.abs(M.followYaw(0, 3, tight, 1)) <= 0.01 * Math.PI + 1e-12)
  assert.ok(Math.abs(M.runLag(c) - 0.15) < 1e-9)
})
