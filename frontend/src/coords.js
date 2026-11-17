// TOD (Kapow) is left-handed, y up, metres. The cached glbs negate Z (right-handed, like every exporter of the
// project). So a game position (x, y, z) is shown at (x, y, -z) and a game rotation quaternion (x, y, z, w) (the
// TRUE rotation, i.e. the stored one conjugated) becomes (-x, -y, z, w). Both maps are their own inverse.
import * as THREE from 'three'

export const toView = p => new THREE.Vector3(p[0], p[1], -p[2])
export const fromView = v => [v.x, v.y, -v.z]
export const quatToView = q => new THREE.Quaternion(-q[0], -q[1], q[2], q[3])
export const quatFromView = q => [-q.x, -q.y, q.z, q.w]

// The engine's facing, measured in game: an arrival yaw of 0 faces +z, 90 faces -x (west), 270 faces +x. -> ground direction [x, z].
// (The same as make_new_map.facing_vector.) The arrows of the editor point this way; a box still turns by the plain quaternion.
export const facingDir = yawDeg_ => { const a = yawDeg_ * Math.PI / 180; return [-Math.sin(a), Math.cos(a)] }
// the turn of an arrow that sits inside a group already turned by quatToView(quatFromYaw(yaw)): together they point along facingDir(yaw)
export const facingQuat = yawDeg_ => quatToView(quatFromYaw(-2 * yawDeg_))

export const r3 = v => v.map(x => Math.round(x * 1000) / 1000)

// yaw in degrees about +Y in game space, from a game quaternion
export function yawDeg(q) {
  const [x, y, z, w] = q
  const siny = 2 * (w * y + z * x)
  const cosy = 1 - 2 * (y * y + x * x)
  return Math.atan2(siny, cosy) * 180 / Math.PI
}

export function quatFromYaw(deg) {
  const a = deg * Math.PI / 360
  return [0, Math.sin(a), 0, Math.cos(a)]
}
