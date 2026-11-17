// A rigged model playing a clip: the skin is deformed on the CPU from the game's own skeleton and keyframes.
// Game axes inside (left-handed, y up); the picture negates z like the other views. The engine's bone rotation is the transpose of the
// usual quaternion matrix, so the data arrives with every rotation already conjugated.
import React, { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { texture } from './models.js'

const ACCENT = '#f2a541'
const q = new THREE.Quaternion(), q2 = new THREE.Quaternion(), v3 = new THREE.Vector3(), v4 = new THREE.Vector3()

// frame f (float) of a track stored as flat arrays: [x, y, z, w] per frame (rotation) or [x, y, z] (position)
function sampleRot(track, isStatic, i0, i1, a, out) {
  if (isStatic) return out.set(track[0], track[1], track[2], track[3])
  out.set(track[i0 * 4], track[i0 * 4 + 1], track[i0 * 4 + 2], track[i0 * 4 + 3])
  q2.set(track[i1 * 4], track[i1 * 4 + 1], track[i1 * 4 + 2], track[i1 * 4 + 3])
  return out.slerp(q2, a)
}
function samplePos(track, isStatic, i0, i1, a, out) {
  if (isStatic) return out.set(track[0], track[1], track[2])
  out.set(track[i0 * 3], track[i0 * 3 + 1], track[i0 * 3 + 2])
  v4.set(track[i1 * 3], track[i1 * 3 + 1], track[i1 * 3 + 2])
  return out.lerp(v4, a)
}

export default function RigView({ skin, clip, ctl, showBones, wire, onTime }) {
  const n = skin.pivots.length
  const bind = useMemo(() => {
    const local = skin.pivots.map(p => new THREE.Matrix4().compose(new THREE.Vector3(...p.pos), new THREE.Quaternion(...p.quat), new THREE.Vector3(1, 1, 1)))
    const world = new Array(n)
    const get = i => {
      if (world[i]) return world[i]
      const par = skin.pivots[i].parent
      world[i] = par >= 0 && par !== i && par < n ? get(par).clone().multiply(local[i]) : local[i].clone()
      return world[i]
    }
    for (let i = 0; i < n; i++) get(i)
    return { world, inv: world.map(m => m.clone().invert()) }
  }, [skin])
  const order = useMemo(() => {                       // parents before children
    const seen = new Set(), out = []
    const visit = i => { if (seen.has(i)) return; seen.add(i); const p = skin.pivots[i].parent; if (p >= 0 && p !== i && p < n) visit(p); out.push(i) }
    for (let i = 0; i < n; i++) visit(i)
    return out
  }, [skin])
  const meshes = useMemo(() => skin.meshes.map(m => {
    const geo = new THREE.BufferGeometry()
    const pos = new Float32Array(m.pos.length), nrm = new Float32Array(m.nrm.length)
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage))
    geo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3).setUsage(THREE.DynamicDrawUsage))
    geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(m.uv), 2))
    geo.setIndex(new THREE.BufferAttribute(new Uint32Array(m.idx), 1))
    const info = m.tex && skin.texInfo?.[m.tex]
    const map = info?.url ? texture(info) : null
    const mat = new THREE.MeshLambertMaterial({ map, color: map ? 0xffffff : 0x9aa3ad, side: THREE.DoubleSide, alphaTest: info?.alpha ? 0.5 : 0 })
    mat.userData.map = map
    const mesh = new THREE.Mesh(geo, mat)
    mesh.frustumCulled = false
    return { m, geo, mesh, pos, nrm }
  }), [skin])
  useEffect(() => () => meshes.forEach(x => { x.geo.dispose(); x.mesh.material.dispose() }), [meshes])
  useEffect(() => {
    meshes.forEach(x => {
      const t = x.mesh.material
      t.wireframe = !!wire
      t.map = wire ? null : t.userData.map
      t.color.set(wire ? ACCENT : (t.userData.map ? 0xffffff : 0x9aa3ad))
      t.needsUpdate = true
    })
  }, [meshes, wire])

  const W = useMemo(() => Array.from({ length: n }, () => new THREE.Matrix4()), [n])
  const S = useMemo(() => Array.from({ length: n }, () => new THREE.Matrix4()), [n])
  const tmpT = useMemo(() => new THREE.Vector3(), []), tmpQ = useMemo(() => new THREE.Quaternion(), []), tmpL = useMemo(() => new THREE.Matrix4(), [])
  const one = useMemo(() => new THREE.Vector3(1, 1, 1), [])
  const boneGeo = useMemo(() => { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 6), 3)); return g }, [n])
  const sph = useMemo(() => new THREE.SphereGeometry(1, 8, 6), [])
  const dotMat = useMemo(() => new THREE.MeshBasicMaterial({ color: ACCENT, depthTest: false, transparent: true }), [])
  const dots = useRef([])
  const last = useRef(0)

  useFrame((_, dt) => {
    const c = ctl.current
    if (clip && c.playing) {
      c.t += dt * (c.speed || 1)
      const len = clip.frames / (clip.fps || 25)
      if (clip.loop) c.t %= len
      else if (c.t >= len) { c.t = len; c.playing = false }
    }
    // the pose
    let i0 = 0, i1 = 0, a = 0
    if (clip && clip.frames > 1) {
      const f = Math.min(clip.frames - 1, Math.max(0, c.t * (clip.fps || 25)))
      i0 = Math.floor(f); i1 = Math.min(clip.frames - 1, i0 + 1); a = f - i0
      if (clip.loop && c.t * (clip.fps || 25) >= clip.frames - 1) { i1 = 0; a = Math.min(1, f - (clip.frames - 1)); i0 = clip.frames - 1 }
    }
    for (const i of order) {
      const p = skin.pivots[i]
      const hasR = clip && clip.rot[i], hasP = clip && clip.pos[i]
      if (hasR) sampleRot(clip.rot[i], clip.rot_static[i], i0, i1, a, tmpQ); else tmpQ.set(...p.quat)
      if (hasP) samplePos(clip.pos[i], clip.pos_static[i], i0, i1, a, tmpT); else tmpT.set(...p.pos)
      tmpL.compose(tmpT, tmpQ, one)
      const par = p.parent
      if (par >= 0 && par !== i && par < n) W[i].copy(W[par]).multiply(tmpL); else W[i].copy(tmpL)
      S[i].copy(W[i]).multiply(bind.inv[i])
    }
    for (const { m, geo, pos, nrm } of meshes) {
      const P = m.pos, N = m.nrm, nv = P.length / 3
      for (let v = 0; v < nv; v++) {
        const x = P[v * 3], y = P[v * 3 + 1], z = P[v * 3 + 2], nx = N[v * 3], ny = N[v * 3 + 1], nz = N[v * 3 + 2]
        let ox = 0, oy = 0, oz = 0, px = 0, py = 0, pz = 0
        if (m.skinned) {
          for (let k = 0; k < 4; k++) {
            const w = m.weights[v * 4 + k]
            if (!w) continue
            const e = S[m.joints[v * 4 + k]].elements
            ox += w * (e[0] * x + e[4] * y + e[8] * z + e[12]); oy += w * (e[1] * x + e[5] * y + e[9] * z + e[13]); oz += w * (e[2] * x + e[6] * y + e[10] * z + e[14])
            px += w * (e[0] * nx + e[4] * ny + e[8] * nz); py += w * (e[1] * nx + e[5] * ny + e[9] * nz); pz += w * (e[2] * nx + e[6] * ny + e[10] * nz)
          }
        } else {                                      // a rigid mesh: its vertices live in the pivot's own space
          const e = W[m.pivot].elements
          ox = e[0] * x + e[4] * y + e[8] * z + e[12]; oy = e[1] * x + e[5] * y + e[9] * z + e[13]; oz = e[2] * x + e[6] * y + e[10] * z + e[14]
          px = e[0] * nx + e[4] * ny + e[8] * nz; py = e[1] * nx + e[5] * ny + e[9] * nz; pz = e[2] * nx + e[6] * ny + e[10] * nz
        }
        pos[v * 3] = ox; pos[v * 3 + 1] = oy; pos[v * 3 + 2] = -oz
        nrm[v * 3] = px; nrm[v * 3 + 1] = py; nrm[v * 3 + 2] = -pz
      }
      geo.attributes.position.needsUpdate = true
      geo.attributes.normal.needsUpdate = true
      geo.computeBoundingSphere()
    }
    if (showBones) {
      const b = boneGeo.attributes.position.array
      for (let i = 0; i < n; i++) {
        const par = skin.pivots[i].parent
        const e = W[i].elements, pe = par >= 0 && par !== i ? W[par].elements : e
        b.set([pe[12], pe[13], -pe[14], e[12], e[13], -e[14]], i * 6)
        const d = dots.current[i]
        if (d) d.position.set(e[12], e[13], -e[14])
      }
      boneGeo.attributes.position.needsUpdate = true
    }
    const now = performance.now()
    if (onTime && now - last.current > 90) { last.current = now; onTime(c.t, c.playing) }
  })
  return <>
    {meshes.map((x, i) => <primitive key={i} object={x.mesh} />)}
    {showBones && <group renderOrder={20}>
      <lineSegments geometry={boneGeo} renderOrder={20} frustumCulled={false}><lineBasicMaterial color="#4b9fff" depthTest={false} transparent /></lineSegments>
      {skin.pivots.map((_, i) => <mesh key={i} ref={el => { dots.current[i] = el }} geometry={sph} material={dotMat} scale={0.018} renderOrder={21} frustumCulled={false} />)}
    </group>}
  </>
}
