// Shared parts of the Tune previews: a self-contained canvas, a fitted game model, and Ram with his move clips.
import React, { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { clone as skeletonClone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { vpColor } from '../theme.js'
import { prototypeOf, ramMoves, useGameModels, RAM_MODEL } from './gameModels.js'

// the viewport colour of the current theme, kept in step when the theme changes
export function useVp() {
  const [c, setC] = useState(vpColor())
  useEffect(() => {
    const o = new MutationObserver(() => setC(vpColor()))
    o.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => o.disconnect()
  }, [])
  return c
}

// puts the camera where the caller wants it whenever `k` changes
function Frame({ k, pos, target }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    camera.position.set(...pos)
    if (controls) { controls.target.set(...target); controls.update() } else camera.lookAt(...target)
  }, [k, controls])
  return null
}

export function PreviewCanvas({ children, pos = [5, 3.5, 7], target = [0, 0.8, 0], fov = 38, frameKey = 'a', controls = true, far = 3000, shadowless = true }) {
  const bg = useVp()
  return (
    <Canvas linear flat camera={{ fov, near: 0.05, far, position: pos }} gl={{ antialias: true }} dpr={[1, 1.5]}>
      <color attach="background" args={[bg]} />
      <ambientLight intensity={0.95} />
      <directionalLight position={[40, 90, 30]} intensity={0.8} />
      <hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
      <Suspense fallback={null}>{children}</Suspense>
      {controls && <OrbitControls makeDefault enableDamping={false} maxDistance={far / 2} />}
      <Frame k={frameKey} pos={pos} target={target} />
    </Canvas>
  )
}

// sky colour of the playground scenes
export function useSky() {
  const bg = useVp()
  return new THREE.Color(bg).getHSL({}).l > 0.5 ? '#b9cbdd' : '#243142'
}

export const Tag = ({ position, children, tone }) => (
  <Html position={position} center style={{ pointerEvents: 'none' }}><div className={'tag' + (tone ? ' ' + tone : '')}>{children}</div></Html>
)

// Disc with distance rings on the ground (a flat ring mesh per radius)
export function Ring({ r, color, width = 0.06, y = 0.02, opacity = 0.9, dashed }) {
  const geo = useMemo(() => new THREE.RingGeometry(Math.max(0.001, r - width), r + width, 96, 1), [r, width])
  return <mesh geometry={geo} rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]}>
    <meshBasicMaterial color={color} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} /></mesh>
}

export function GroundGrid({ size = 40, step = 1, color, floor = true }) {
  const bg = useVp()
  const light = new THREE.Color(bg).getHSL({}).l > 0.5
  const col = color || (light ? '#9aa3ad' : '#4b5b70')
  const fl = new THREE.Color(bg).offsetHSL(0, 0, light ? 0.07 : 0.13)
  return <>
    {floor && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.015, 0]}><circleGeometry args={[size * 0.6, 64]} /><meshBasicMaterial color={fl} /></mesh>}
    <gridHelper args={[size, Math.round(size / step), col, col]} position={[0, 0, 0]} />
  </>
}

// A game model scaled to `fit` metres on its longest side and standing on y = 0 (centred over the origin).
export function GameModel({ path, rec, fit, scale, rotY = 0, wire, onBox, children }) {
  const [proto, setProto] = useState(null)
  useEffect(() => { let live = true; setProto(null); prototypeOf(path, rec).then(p => live && setProto(p)); return () => { live = false } }, [path, rec?.url])
  const obj = useMemo(() => proto?.render ? proto.render.clone() : null, [proto])
  const { s, off, box } = useMemo(() => {
    if (!obj) return { s: 1, off: [0, 0, 0], box: null }
    const b = new THREE.Box3().setFromObject(obj)
    if (b.isEmpty()) return { s: 1, off: [0, 0, 0], box: null }
    const size = b.getSize(new THREE.Vector3())
    const k = scale || (fit ? fit / Math.max(size.x, size.y, size.z, 1e-6) : 1)
    const c = b.getCenter(new THREE.Vector3())
    return { s: k, off: [-c.x * k, -b.min.y * k, -c.z * k], box: { size: size.toArray(), k } }
  }, [obj, fit, scale])
  useEffect(() => { if (box) onBox?.(box) }, [box])
  if (!obj) return null
  return (
    <group rotation={[0, rotY, 0]}>
      <group position={off} scale={s}><primitive object={obj} />{children}</group>
    </group>
  )
}

// ------------------------------------------------------------------ Ram with his clips
const RAM_LIFT = 0.97          // the player's skeleton is rooted at the pelvis
const gltf = new GLTFLoader()
const ramCache = { p: null }
function loadRam() {
  if (!ramCache.p) {
    ramCache.p = ramMoves().then(r => new Promise((res, rej) => gltf.load(r.url, g => res({ scene: g.scene, clips: g.animations, names: r.clips }), undefined, rej)))
      .catch(e => { ramCache.p = null; throw e })
  }
  return ramCache.p
}

// Ram, skinned on the CPU (the same way the asset viewer plays these clips), one clip at a time.
// `rate` is a function returning the playback speed each frame; `clip` the clip name; `loop` false holds the last pose.
export function RamActor({ clip, rate, loop = true, rotY = 0, onTime, onInfo, restart }) {
  const [ram, setRam] = useState(null)
  const models = useGameModels([RAM_MODEL])
  const [look, setLook] = useState(null)
  useEffect(() => { let live = true; loadRam().then(r => live && setRam(r)).catch(() => {}); return () => { live = false } }, [])
  useEffect(() => {
    const rec = models[RAM_MODEL]
    if (!rec) return
    let live = true
    prototypeOf(RAM_MODEL, rec).then(p => {
      let mat = null
      p?.render?.traverse(o => { if (!mat && o.isMesh && o.material?.map) mat = o.material })
      if (live) setLook(mat)
    })
    return () => { live = false }
  }, [models[RAM_MODEL]])
  const group = useRef()
  const st = useMemo(() => {
    if (!ram) return null
    const cloned = skeletonClone(ram.scene)
    const baked = []
    cloned.traverse(o => {
      if (o.isSkinnedMesh) {
        o.visible = false
        const geo = o.geometry.clone()
        geo.deleteAttribute('skinIndex'); geo.deleteAttribute('skinWeight')
        const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: 0xc9b8a4, emissive: 0x2a2a2a, side: THREE.DoubleSide }))
        baked.push({ src: o, geo, base: o.geometry.attributes.position, mesh })
      }
    })
    return { cloned, baked, mixer: new THREE.AnimationMixer(cloned), action: null, name: null }
  }, [ram])
  useEffect(() => {
    if (!st) return
    st.baked.forEach(b => { if (look) { b.mesh.material.dispose(); b.mesh.material = look.clone(); b.mesh.material.side = THREE.DoubleSide; b.mesh.material.emissive = new THREE.Color(0x3c3c3c) } })
  }, [st, look])
  useEffect(() => {
    if (!st) return
    const c = ram.clips.find(x => x.name === clip)
    if (!c) return
    if (st.action) st.action.stop()
    const a = st.mixer.clipAction(c)
    a.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity)
    a.clampWhenFinished = true
    a.reset().play()
    st.action = a; st.name = clip
    onInfo?.({ duration: c.duration })
  }, [st, clip, loop, restart])
  const v = useMemo(() => new THREE.Vector3(), [])
  const inv = useMemo(() => new THREE.Matrix4(), [])
  useFrame((_, dt) => {
    if (!st) return
    st.mixer.update(Math.min(dt, 0.1) * (rate ? rate() : 1))
    st.cloned.updateMatrixWorld(true)
    if (group.current) { group.current.updateMatrixWorld(true); inv.copy(group.current.matrixWorld).invert() }
    for (const b of st.baked) {
      b.src.skeleton.update()
      const dst = b.geo.attributes.position
      for (let i = 0; i < dst.count; i++) { v.fromBufferAttribute(b.base, i); b.src.applyBoneTransform(i, v); dst.setXYZ(i, v.x, v.y, v.z) }
      dst.needsUpdate = true
      b.geo.computeVertexNormals(); b.geo.computeBoundingSphere()
      b.mesh.matrixAutoUpdate = false
      b.mesh.matrix.multiplyMatrices(inv, b.src.matrixWorld)
    }
    if (st.action && onTime) onTime(st.action.time, st.action.getClip().duration)
  })
  if (!st) return null
  return (
    <group ref={group} position={[0, RAM_LIFT, 0]} rotation={[0, rotY, 0]}>
      <primitive object={st.cloned} />
      {st.baked.map((b, i) => <primitive key={i} object={b.mesh} />)}
    </group>
  )
}

export const hasRam = () => !!ramCache.p
