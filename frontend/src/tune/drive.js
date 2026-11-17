// The playground's car: a raycast vehicle (cannon-es, loaded only when the drive playground opens) whose numbers come from
// the game's vehicle values (mapping.js physicsFor). `C` is the cannon-es module. Forward is +z in the physics world.
import { steerAngle, steerRamp, STEP } from './mapping.js'

export function createDrive(C, ph, spawn = {}) {
  const world = new C.World({ gravity: new C.Vec3(0, -12, 0) })
  world.broadphase = new C.SAPBroadphase(world)
  world.allowSleep = false
  world.defaultContactMaterial.friction = 0.35
  world.defaultContactMaterial.restitution = 0.05

  const [hx, hy, hz] = ph.halfExtents
  const chassis = new C.Body({ mass: ph.mass, position: new C.Vec3(spawn.x || 0, spawn.y ?? 3, spawn.z || 0) })
  // spheres collide with triangle meshes (boxes do not): a row down the middle and the four corners
  const rs = Math.max(0.3, Math.min(0.6, hx * 0.5))
  for (const z of [-hz * 0.72, -hz * 0.25, hz * 0.25, hz * 0.72]) for (const x of [-(hx - rs), hx - rs]) chassis.addShape(new C.Sphere(rs), new C.Vec3(x, 0.95, z))
  // the car's body meets walls only; the ground is for the wheel rays (see heightMesh)
  chassis.collisionFilterGroup = 4; chassis.collisionFilterMask = 2
  chassis.angularDamping = ph.angularDamping
  chassis.quaternion.setFromAxisAngle(new C.Vec3(0, 1, 0), spawn.yaw || 0)

  const vehicle = new C.RaycastVehicle({ chassisBody: chassis, indexRightAxis: 0, indexUpAxis: 1, indexForwardAxis: 2 })
  const half = ph.track / 2, wb = ph.wheelbase / 2
  const base = {
    radius: ph.wheelRadius, directionLocal: new C.Vec3(0, -1, 0), axleLocal: new C.Vec3(-1, 0, 0),
    suspensionStiffness: ph.suspensionStiffness, suspensionRestLength: ph.suspensionRest, frictionSlip: ph.frictionSlip,
    dampingRelaxation: ph.dampingRelaxation, dampingCompression: ph.dampingCompression, maxSuspensionForce: 120000,
    rollInfluence: 0.04, maxSuspensionTravel: 0.5, customSlidingRotationalSpeed: -30, useCustomSlidingRotationalSpeed: true,
  }
  const drop = -0.1
  // 0, 1 front (steered); 2, 3 rear (driven)
  for (const [x, z] of [[half, wb], [-half, wb], [half, -wb], [-half, -wb]]) {
    vehicle.addWheel({ ...base, chassisConnectionPointLocal: new C.Vec3(x, drop, z) })
  }
  vehicle.addToWorld(world)

  const st = { wheel: 0, grounds: [], t: 0 }
  const fwd = new C.Vec3(), tmp = new C.Vec3()

  function addGround(bodies) { for (const b of bodies) { world.addBody(b); st.grounds.push(b) } }
  function clearGround() { for (const b of st.grounds) world.removeBody(b); st.grounds = [] }
  function plane(y = 0) {
    const b = new C.Body({ mass: 0 })
    b.addShape(new C.Plane())
    b.quaternion.setFromAxisAngle(new C.Vec3(1, 0, 0), -Math.PI / 2)
    b.position.set(0, y, 0)
    return b
  }

  // one physics step with the keys: input = { throttle: -1..1, steer: -1..1 (left negative), brake: 0..1, hand: bool }
  function step(dt, input) {
    chassis.vectorToWorldFrame(new C.Vec3(0, 0, 1), fwd)
    const vF = chassis.velocity.dot(fwd)
    const t = input.throttle || 0
    let engine = 0, brake = 0
    if (t > 0) { if (vF < -1) brake = ph.brakeForce * (2 / 3); else engine = ph.engineForce * t }
    else if (t < 0) { if (vF > 1) brake = ph.brakeForce * (2 / 3); else engine = -ph.reverseForce * -t }
    if (input.brake) brake = ph.brakeForce * input.brake
    // Wheel force pushes along the axle-forward; sign checked in the unit test
    vehicle.applyEngineForce(-engine / 2, 2); vehicle.applyEngineForce(-engine / 2, 3)
    for (let i = 0; i < 4; i++) vehicle.setBrake(brake / 4, i)
    // the steering angle shrinks with speed and ramps like the game's
    const target = steerAngle(ph, -(input.steer || 0), Math.abs(vF), vF >= 0)
    st.wheel = steerRamp(st.wheel, target, dt, ph)
    vehicle.setSteeringValue(st.wheel, 0); vehicle.setSteeringValue(st.wheel, 1)
    // grip: perfect until the slide speed; the handbrake and hard turns above it free the rear
    const sliding = input.hand || (Math.abs(vF) > ph.slideSpeed && Math.abs(input.steer || 0) > 0.6)
    const grip = ph.frictionSlip * (sliding ? ph.slideGrip : 1)
    vehicle.wheelInfos[2].frictionSlip = grip; vehicle.wheelInfos[3].frictionSlip = grip
    if (input.hand) { vehicle.setBrake(ph.brakeForce / 3, 2); vehicle.setBrake(ph.brakeForce / 3, 3) }
    // below 1 m/s a brake stops the car dead, as in the game
    if (brake > 0 && engine === 0 && Math.abs(vF) < 1) { chassis.velocity.x = 0; chassis.velocity.z = 0 }
    // drag along the ground plane only, so falling is not slowed
    const k = Math.pow(1 - ph.linearDamping, dt)
    chassis.velocity.x *= k; chassis.velocity.z *= k
    world.step(1 / 60, dt, 4)
    st.t += dt
    return vF
  }

  function pose() {
    const wheels = vehicle.wheelInfos.map((w, i) => { vehicle.updateWheelTransform(i); return { p: w.worldTransform.position, q: w.worldTransform.quaternion, steer: w.steering, rot: w.rotation } })
    return { p: chassis.position, q: chassis.quaternion, wheels, speed: chassis.velocity.length(), vF: chassis.velocity.dot(chassis.vectorToWorldFrame(new C.Vec3(0, 0, 1), tmp)), steer: st.wheel, onGround: vehicle.numWheelsOnGround }
  }
  function reset(x, y, z, yaw = 0) {
    chassis.position.set(x, y, z); chassis.velocity.setZero(); chassis.angularVelocity.setZero()
    chassis.quaternion.setFromAxisAngle(new C.Vec3(0, 1, 0), yaw)
    st.wheel = 0
    chassis.force.setZero(); chassis.torque.setZero()
    chassis.previousPosition.copy(chassis.position); chassis.interpolatedPosition.copy(chassis.position)
    chassis.initPosition.copy(chassis.position); chassis.initQuaternion.copy(chassis.quaternion)
    // the wheels start fresh, as if the car had just been built
    for (const w of vehicle.wheelInfos) {
      w.suspensionLength = w.suspensionRestLength; w.suspensionRelativeVelocity = 0; w.suspensionForce = 0; w.rotation = 0
      w.deltaRotation = 0; w.isInContact = false; w.sliding = false; w.skidInfo = 1; w.clippedInvContactDotSuspension = 1
      w.forwardImpulse = 0; w.sideImpulse = 0
    }
  }
  return { world, vehicle, chassis, step, pose, reset, addGround, clearGround, plane, STEP }
}

// a triangle mesh body from world-space vertices (flat x,y,z) and indices
// The meshes keep the game's winding: the collision pieces are closed shapes, and the engine's wheel rays only see the outside.
export function trimeshBody(C, verts, indices, group = 1) {
  const b = new C.Body({ mass: 0 })
  b.collisionFilterGroup = group; b.collisionFilterMask = -1
  const both = indices
  b.addShape(new C.Trimesh(verts, both))
  return b
}

// Collision made of many separate convex pieces has cracks between them, and a wheel ray that falls into one passes through.
// This lays a continuous surface over the up-facing triangles: a grid of heights (the highest surface in each cell, small gaps
// filled from their neighbours), as a triangle mesh. `list` is [{ verts, idx }] in world space; the grid covers
// [cx - half, cx + half] x [cz - half, cz + half].
export function heightMesh(list, cx, cz, half, cell = 1) {
  const n = Math.max(2, Math.round((half * 2) / cell)) + 1
  const x0 = cx - half, z0 = cz - half
  const H = new Float32Array(n * n).fill(NaN)
  for (const g of list) {
    const V = g.verts, I = g.idx
    for (let t = 0; t < I.length; t += 3) {
      const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3
      const ux = V[b] - V[a], uy = V[b + 1] - V[a + 1], uz = V[b + 2] - V[a + 2]
      const vx = V[c] - V[a], vy = V[c + 1] - V[a + 1], vz = V[c + 2] - V[a + 2]
      const ny = uz * vx - ux * vz, len = Math.hypot(uy * vz - uz * vy, ny, ux * vy - uy * vx) || 1
      if (Math.abs(ny) / len < 0.45) continue                         // only surfaces that lie flat-ish (the winding of open meshes is not reliable)
      const minx = Math.min(V[a], V[b], V[c]), maxx = Math.max(V[a], V[b], V[c]), minz = Math.min(V[a + 2], V[b + 2], V[c + 2]), maxz = Math.max(V[a + 2], V[b + 2], V[c + 2])
      const i0 = Math.max(0, Math.ceil((minx - x0) / cell)), i1 = Math.min(n - 1, Math.floor((maxx - x0) / cell))
      const j0 = Math.max(0, Math.ceil((minz - z0) / cell)), j1 = Math.min(n - 1, Math.floor((maxz - z0) / cell))
      if (i0 > i1 || j0 > j1) continue
      const d = (V[b + 2] - V[c + 2]) * (V[a] - V[c]) + (V[c] - V[b]) * (V[a + 2] - V[c + 2])
      if (Math.abs(d) < 1e-9) continue
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        const px = x0 + i * cell, pz = z0 + j * cell
        const l1 = ((V[b + 2] - V[c + 2]) * (px - V[c]) + (V[c] - V[b]) * (pz - V[c + 2])) / d
        const l2 = ((V[c + 2] - V[a + 2]) * (px - V[c]) + (V[a] - V[c]) * (pz - V[c + 2])) / d
        const l3 = 1 - l1 - l2
        if (l1 < -0.08 || l2 < -0.08 || l3 < -0.08) continue
        const y = l1 * V[a + 1] + l2 * V[b + 1] + l3 * V[c + 1]
        const k = j * n + i
        if (!(H[k] >= y)) H[k] = y
      }
    }
  }
  // close small gaps: a cell with data on two opposite sides, or on at least three of its eight neighbours, takes their mean
  for (let pass = 0; pass < 4; pass++) {
    const fill = []
    for (let j = 1; j < n - 1; j++) for (let i = 1; i < n - 1; i++) {
      if (!Number.isNaN(H[j * n + i])) continue
      let s = 0, c = 0
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) { const h = H[(j + dj) * n + i + di]; if (!Number.isNaN(h)) { s += h; c++ } }
      if (c >= 3) fill.push([j * n + i, s / c])
    }
    for (const [k, h] of fill) H[k] = h
  }
  const verts = new Array(n * n * 3), idx = []
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) { const k = (j * n + i) * 3; verts[k] = x0 + i * cell; verts[k + 1] = Number.isNaN(H[j * n + i]) ? 0 : H[j * n + i]; verts[k + 2] = z0 + j * cell }
  for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
    const a = j * n + i, b = a + 1, c = a + n, e = c + 1
    if (Number.isNaN(H[a]) || Number.isNaN(H[b]) || Number.isNaN(H[c]) || Number.isNaN(H[e])) continue
    idx.push(a, c, b, b, c, e)                                         // both triangles face up (checked against the engine's own normals in the tests)
  }
  return idx.length ? { verts, idx } : null
}

// the steep triangles of the pieces (walls, cliffs, building sides), both windings, as one mesh
export function steepMesh(list) {
  const verts = [], idx = []
  for (const g of list) {
    const V = g.verts, I = g.idx, base = verts.length / 3
    let used = false
    for (let t = 0; t < I.length; t += 3) {
      const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3
      const ux = V[b] - V[a], uy = V[b + 1] - V[a + 1], uz = V[b + 2] - V[a + 2]
      const vx = V[c] - V[a], vy = V[c + 1] - V[a + 1], vz = V[c + 2] - V[a + 2]
      const ny = uz * vx - ux * vz, len = Math.hypot(uy * vz - uz * vy, ny, ux * vy - uy * vx) || 1
      if (Math.abs(ny) / len >= 0.45) continue
      if (!used) { used = true; for (let i = 0; i < V.length; i++) verts.push(V[i]) }
      idx.push(base + I[t], base + I[t + 1], base + I[t + 2], base + I[t], base + I[t + 2], base + I[t + 1])
    }
    if (!used) continue
  }
  return idx.length ? { verts, idx } : null
}
