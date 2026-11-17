// Value mapping for the Tune previews and the playground. Pure functions (no three.js, no DOM) so they can be
// tested with `node --test`. The rules come from the research notes on weapons, vehicles, camera and slow motion;
// the playground is an approximation of the game, not the game.

// ------------------------------------------------------------------ reading the editor data
// d = { groups: [{ group, fields: [{ key, label, value }] }] }, vals = { key: number } (the project's changes)
export function groupOf(d, name) { return (d && d.groups.find(g => g.group === name)) || null }
export function fieldsOf(group, vals = {}, useMine = true) {
  const out = {}
  for (const f of (group && group.fields) || []) out[f.label] = useMine && f.key in vals ? vals[f.key] : f.value
  return out
}
// every field of the whole data set by key: { key: value }
export function keyed(d, vals = {}, useMine = true) {
  const out = {}
  for (const g of (d && d.groups) || []) for (const f of g.fields) out[f.key] = useMine && f.key in vals ? vals[f.key] : f.value
  if (useMine) for (const k in vals) if (!(k in out)) out[k] = vals[k]
  return out
}

export function clamp(x, lo, hi) { return Math.min(hi, Math.max(lo, x)) }

// ------------------------------------------------------------------ weapons
export const PLAYER_CLOCK = 0.95          // the player's weapon clock runs on real time x 0.95

export function weaponOf(d, vals, groupName, useMine = true) {
  const f = fieldsOf(groupOf(d, groupName), vals, useMine)
  const n = (k, dflt = 0) => (typeof f[k] === 'number' ? f[k] : dflt)
  const max = n('MaxRange')
  return {
    clip: n('ClipSize', 1), reload: n('ReloadTime'), fireRate: n('FireRate'), manualRate: n('ManualFireRate') || n('FireRate'),
    pellets: Math.max(1, n('BulletsPerShot', 1)),
    dmg: [n('ShortRangeDamage'), n('MediumRangeDamage'), n('LongRangeDamage')],
    // the data holds Short, Medium and Max range; the long band ends at the longest shot
    short: n('ShortRange'), medium: Math.max(n('MediumRange'), n('ShortRange')), max: Math.max(max, n('MediumRange'), n('ShortRange')),
    spreadMin: n('SpreadMin'), spreadMax: Math.max(n('SpreadMax'), n('SpreadMin')), spreadInc: n('SpreadInc'),
    bulletSpeed: n('bullet speed', 70),
  }
}

export const BAND_NAMES = ['close', 'medium', 'long']

export function bands(w) {
  return [
    { name: 'close', from: 0, to: w.short, damage: w.dmg[0] },
    { name: 'medium', from: w.short, to: w.medium, damage: w.dmg[1] },
    { name: 'long', from: w.medium, to: w.max, damage: w.dmg[2] },
  ]
}
// The band is chosen from the distance to the aim point: no falloff inside a band, nothing beyond the longest shot.
export function bandIndex(w, dist) {
  if (dist <= w.short) return 0
  if (dist <= w.medium) return 1
  if (dist <= w.max) return 2
  return -1
}
export function damageAt(w, dist) { const i = bandIndex(w, dist); return i < 0 ? 0 : w.dmg[i] }
// Every pellet carries the full band damage: `hits` pellets of one shot that struck.
export function damagePerShot(w, dist, hits = w.pellets) { return damageAt(w, dist) * Math.max(0, Math.min(hits, w.pellets)) }
// A hit on an enemy: x the placement's headshot factor when the head was hit, x the shooter's damage mod (1 for Ram).
export function hitDamage(w, dist, { head = 1, mod = 1 } = {}) { return damageAt(w, dist) * head * mod }

// seconds between shots on the real clock: held trigger (FireRate) or taps (ManualFireRate)
export function shotInterval(w, held = true) {
  const rate = held ? w.fireRate : w.manualRate
  return rate > 0 ? 60 / (rate * PLAYER_CLOCK) : Infinity
}
export function rateOfFire(w) { return w.fireRate * PLAYER_CLOCK }               // rounds per real minute
export function magazineSeconds(w) { return w.clip * shotInterval(w, true) }
export function dps(w, dist) { const i = shotInterval(w, true); return isFinite(i) ? damageAt(w, dist) * w.pellets / i : 0 }
// Spread (degrees) after the trigger has been held for `held` seconds: it starts at SpreadMin and grows by SpreadInc.
export function spreadAt(w, held) { return Math.min(w.spreadMax, Math.max(0, w.spreadMin + w.spreadInc * Math.max(0, held))) }
// one pellet's angles: independent uniform values in [-spread, +spread] about two axes (a square pyramid)
export function pelletAngles(spread, r1, r2) { return [(r1 * 2 - 1) * spread, (r2 * 2 - 1) * spread] }

// ------------------------------------------------------------------ vehicles
export const ENGINE_FORCE = 12000, ROLLING_RES = 189, MAX_TURN = 0.785, TURN_RATE = 0.174, STEP = 0.04
const DEFAULTS = { max_engine_force: ENGINE_FORCE, max_reverse_force: 6000, rolling_res: ROLLING_RES, max_turn: MAX_TURN,
  turn_rate: TURN_RATE, slide_angle: 0.174 }

// forward force balance c v^2 + r v = F  ->  v
export function topSpeed(force, drag, rolling = ROLLING_RES) {
  if (!(force > 0) || !(drag > 0)) return 0
  return (-rolling + Math.sqrt(rolling * rolling + 4 * drag * force)) / (2 * drag)
}
export const kmh = ms => ms * 3.6

export function vehicleOf(d, vals, typeGroup, useMine = true) {
  const f = fieldsOf(groupOf(d, typeGroup), vals, useMine)
  const all = keyed(d, vals, useMine)
  const bike = /Dirtbike$/i.test(typeGroup)
  const shell = k => all[(bike ? 'bike.' : 'car.') + k] ?? DEFAULTS[k]
  const n = (k, dflt = 0) => (typeof f[k] === 'number' ? f[k] : dflt)
  return {
    bike, health: n('Health'), mass: n('Mass', 1000), drag: n('drag_coeff', 7), brake: n('BrakeForce', 12000),
    cornering: n('cornering_stiffness', 1.2), slideSpeed: n('lateral_slide_speed', 17), slideFactor: n('slide_factor', 1.3),
    brakeSlide: n('brake_slide_factor', 1.7), springK: n('spring_k', 40), springDamp: n('spring_damping', 2.5),
    wheelRadius: n('WheelRadius', 0.45), length: n('Vehicle_Length', 5), width: n('Vehicle_Width', 2.3), height: n('Inertial_Height', 1.8),
    engine: shell('max_engine_force'), reverse: shell('max_reverse_force'), rolling: shell('rolling_res'),
    maxTurn: shell('max_turn'), turnRate: shell('turn_rate'), slideAngle: shell('slide_angle'),
  }
}
export const wheelbaseOf = v => v.length * 0.74

// seconds from a standstill to speed `target` (m/s) by stepping the force balance; null when it never gets there
export function timeTo(v, target, dt = 0.01) {
  const vmax = topSpeed(v.engine, v.drag, v.rolling)
  if (target >= vmax * 0.995) return null
  let s = 0, t = 0
  while (s < target && t < 60) { s += (v.engine - v.drag * s * s - v.rolling * s) / v.mass * dt; t += dt }
  return t
}

// The drive model of the game, as numbers for the gauge.
export function vehicleStats(v) {
  const vmax = topSpeed(v.engine, v.drag, v.rolling)
  const vrev = topSpeed(v.reverse, v.drag, v.rolling)
  const wb = wheelbaseOf(v)
  return {
    topSpeed: vmax, topKmh: kmh(vmax), reverseKmh: kmh(vrev),
    steeringGoneKmh: kmh(vmax / Math.max(v.cornering, 1e-6)),            // the speed where the steering factor reaches its floor
    slideFromKmh: kmh(v.slideSpeed),
    minRadius: wb / Math.sin(v.maxTurn),
    accel0: v.engine / v.mass,                                           // m/s^2 at a standstill
    time0to: speedKmh => timeTo(v, speedKmh / 3.6),
    brakeDistance: speedKmh => { const u = speedKmh / 3.6; return u * u * v.mass / (2 * v.brake) },
  }
}
// steering angle (rad) for a key amount in [-1, 1] at `speed` (m/s): shrinks with speed down to a floor
export function steerAngle(v, input, speed, forward = true) {
  const vmax = topSpeed(v.engine, v.drag, v.rolling)
  const k = clamp(1 - Math.abs(speed) / vmax * v.cornering, 0.001, 1)
  return v.maxTurn * input * (forward ? k : 1)
}
// the angle grows by turn_rate per 0.04 s step; releasing the key snaps it to zero
export function steerRamp(cur, target, dt, v) {
  if (target === 0) return 0
  const d = v.turnRate / STEP * dt
  return cur + clamp(target - cur, -d, d)
}
// Damping that makes the physics engine's chassis settle at the game's top speed under the same engine force.
// The engine multiplies the velocity by (1 - damping)^dt every step; the balance F/m = v ln(1/(1-d)) gives d.
export function dampingFor(force, mass, vmax) {
  if (!(vmax > 0)) return 0.1
  return clamp(1 - Math.exp(-force / (mass * vmax)), 0, 0.95)
}
// Parameters for a raycast vehicle (cannon-es style).
export function physicsFor(v) {
  const vmax = topSpeed(v.engine, v.drag, v.rolling)
  const wb = wheelbaseOf(v)
  return {
    mass: v.mass, engine: v.engine, drag: v.drag, rolling: v.rolling, engineForce: v.engine, reverseForce: v.reverse, brakeForce: v.brake,
    topSpeed: vmax, linearDamping: dampingFor(v.engine, v.mass, vmax), angularDamping: 0.6,
    wheelRadius: v.wheelRadius, wheelbase: wb, track: v.width * 0.78, halfExtents: [v.width / 2, Math.max(0.3, v.height * 0.28), v.length / 2],
    suspensionStiffness: v.springK, suspensionRest: 0.4, dampingRelaxation: v.springDamp, dampingCompression: v.springDamp * 1.2,
    // grip: perfect grip until the slide speed; the handbrake and hard turns above it let the rear go
    frictionSlip: 4.5, slideSpeed: v.slideSpeed, slideGrip: clamp(1 / (1 + v.slideFactor * 0.6), 0.15, 0.8),
    maxTurn: v.maxTurn, turnRate: v.turnRate, cornering: v.cornering,
  }
}

// ------------------------------------------------------------------ slow motion and moves
// The code constants the game uses for automatic slow motion; the stamina values are editable data.
export const SLOWMO = { maxStamina: 1000, startStamina: 50, keepStamina: 1, dive: 0.11, wall: 0.07, other: 0.1375, rampIn: 0.2, rampOut: 0.1 }

export function slowmoOf(d, vals, useMine = true) {
  const all = keyed(d, vals, useMine)
  return { ...SLOWMO, cost: all['stamina.slowmo_cost_per_s'] ?? 125, gainStanding: all['stamina.gain_standing'] ?? 150, gainRunning: all['stamina.gain_running'] ?? 80 }
}
// How long a full bar lasts (real seconds) and what that is in game seconds.
export function slowmoSummary(p, scale = p.dive) {
  const real = Math.max(0, (p.maxStamina - p.keepStamina) / Math.max(p.cost, 1e-9))
  const ramp = Math.min(real, p.rampIn)
  const game = ramp * (1 + scale) / 2 + (real - ramp) * scale
  return { real, game, scale, recharge: p.maxStamina / Math.max(p.gainStanding, 1e-9), canStart: p.maxStamina >= p.startStamina }
}
// time scale at real time t for a slow-motion run of `real` seconds: ramps in, holds, ramps out
export function timeScaleAt(t, p, scale, real) {
  if (t < 0 || t > real + p.rampOut) return 1
  if (t < p.rampIn) return 1 + (scale - 1) * (t / p.rampIn)
  if (t <= real) return scale
  return scale + (1 - scale) * ((t - real) / p.rampOut)
}
// one frame of the playground's slow motion: returns the new state
export function stepSlowmo(s, p, dt, want, moving = false, scale = p.dive) {
  let { stamina, scale: cur, on } = s
  if (want && !on && stamina >= p.startStamina) on = true
  if (on && (!want || stamina <= p.keepStamina)) on = false
  if (on) stamina = Math.max(0, stamina - p.cost * dt)
  else stamina = Math.min(p.maxStamina, stamina + (moving ? p.gainRunning : p.gainStanding) * dt)
  const goal = on ? scale : 1
  const rate = Math.abs(1 - scale) / (on ? p.rampIn : p.rampOut)
  cur = cur < goal ? Math.min(goal, cur + rate * dt) : Math.max(goal, cur - rate * dt)
  return { stamina, scale: cur, on }
}

// ------------------------------------------------------------------ camera
export const CAM = { pos: [0.15, 1.05, -3.26], pitch: 10, rigHeight: 1.32, fov: 64 }

export function cameraOf(d, vals, useMine = true) {
  const all = keyed(d, vals, useMine)
  const cc = k => all['cameradict.CharacterCombatCam.' + k]
  return {
    back: all['player.back'] ?? 0, up: all['player.up'] ?? 0, pitch: all['player.pitch_deg'] ?? null,
    maxAngle: cc('MaxAngle') ?? 2, ease: cc('AngleEaseInSpeed') ?? 7.5, maxDist: cc('MaxDistance') ?? 0.5,
    moveOut: 0.3, moveIn: cc('DistanceMoveInSpeed') ?? 2, zFactor: cc('DistanceZFactor') ?? 0.5,
  }
}
// Camera position relative to Ram's feet (height above the ground, distance behind him, sideways) and its pitch.
export function cameraPose(c) {
  const pitch = c.pitch == null ? CAM.pitch : c.pitch
  const p = pitch * Math.PI / 180
  const f = [0, -Math.sin(p), Math.cos(p)]                // line of sight of a node pitched down
  const pos = [CAM.pos[0] - c.back * f[0], CAM.pos[1] - c.back * f[1] + c.up, CAM.pos[2] - c.back * f[2]]
  return { x: pos[0], height: pos[1] + CAM.rigHeight, behind: -pos[2], pitch }
}
// 64 is the horizontal field of view of a 4:3 picture; wider screens see more sideways, not more up and down
export function fovDeg(aspect = 16 / 9, base = CAM.fov) {
  const v = 2 * Math.atan(0.75 * Math.tan(base * Math.PI / 360))
  return { vertical: v * 180 / Math.PI, horizontal: 2 * Math.atan(Math.tan(v / 2) * aspect) * 180 / Math.PI }
}
// the rig's yaw follows Ram's: it eases by ease x dt of the gap, never more than maxAngle x pi
export function followYaw(cur, target, c, dt) {
  let d = target - cur
  d = Math.atan2(Math.sin(d), Math.cos(d))
  const step = clamp(d * Math.min(1, c.ease * dt), -c.maxAngle * Math.PI, c.maxAngle * Math.PI)
  return cur + step
}
// how far the rig sags behind a running Ram
export function runLag(c) { return Math.min(c.zFactor * c.maxDist, c.moveIn > 0 ? c.moveOut / c.moveIn : c.zFactor * c.maxDist) }
