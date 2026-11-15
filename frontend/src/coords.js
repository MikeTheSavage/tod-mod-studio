// TOD (Kapow) is left-handed, y up, metres. The cached glbs negate Z (right-handed, like every exporter of the
// project). So a game position (x, y, z) is shown at (x, y, -z) and a game rotation quaternion (x, y, z, w) (the
// TRUE rotation, i.e. the stored one conjugated) becomes (-x, -y, z, w). Both maps are their own inverse.
import * as THREE from 'three'

export const toView = p => new THREE.Vector3(p[0], p[1], -p[2])
export const fromView = v => [v.x, v.y, -v.z]
export const quatToView = q => new THREE.Quaternion(-q[0], -q[1], q[2], q[3])
export const quatFromView = q => [-q.x, -q.y, q.z, q.w]

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
