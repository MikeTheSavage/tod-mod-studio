// The 3D views of the model import and the texture editor: a baked model (a .glb with its own textures), the game's model as a ghost, the
// reference figure, and a game model with one texture swapped for the edited picture.
import React, { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { DDSLoader } from 'three/examples/jsm/loaders/DDSLoader.js'
import { loadModel } from './models.js'
import { vpColor } from './theme.js'

const gltf = new GLTFLoader()
const dds = new DDSLoader()

// ---- the reference figure: the player, 1.8 m, as a plain silhouette
export function Figure({ x, label = 'Ram 1.8 m' }) {
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: '#9cc3ff', transparent: true, opacity: 0.45, depthWrite: false }), [])
  return <group position={[x, 0, 0]}>
    <mesh position={[0, 0.9 - 0.12, 0]} material={mat}><capsuleGeometry args={[0.2, 1.1, 4, 12]} /></mesh>
    <mesh position={[0, 1.66, 0]} material={mat}><sphereGeometry args={[0.14, 14, 10]} /></mesh>
    <Html position={[0, 1.95, 0]} center style={{ pointerEvents: 'none' }}><div className="tag">{label}</div></Html>
  </group>
}

export function useGlb(url) {
  const [obj, setObj] = useState(null)
  useEffect(() => {
    let live = true
    setObj(null)
    if (!url) return
    gltf.load(url, g => { if (live) setObj(g.scene) }, undefined, () => {})
    return () => { live = false }
  }, [url])
  return obj
}

function litCopy(scene) {
  const o = scene.clone(true)
  o.traverse(m => {
    if (!m.isMesh) return
    const src = m.material
    if (src.map) src.map.colorSpace = THREE.NoColorSpace         // the canvas is linear: pictures pass through as stored
    const mat = new THREE.MeshLambertMaterial({ map: src.map || null, side: THREE.DoubleSide, transparent: false })
    if (src.alphaTest || src.alphaMode === 'MASK' || src.transparent) { mat.alphaTest = 0.5 }
    if (src.map) { src.map.wrapS = src.map.wrapT = THREE.RepeatWrapping; src.map.needsUpdate = true }
    m.material = mat
  })
  return o
}

export function Fit({ box, dist = 2.2 }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    if (!controls || !box || box.isEmpty()) return
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3())
    const r = Math.max(s.x, s.y, s.z, 0.5)
    controls.target.copy(c)
    camera.position.set(c.x + r * dist * 0.7, c.y + r * dist * 0.55, c.z + r * dist * 0.9)
    camera.near = Math.max(0.01, r / 200); camera.far = r * 200
    camera.updateProjectionMatrix(); controls.update()
  }, [box && box.min.x + box.max.x + box.min.y + box.max.y + box.min.z + box.max.z, controls])
  return null
}

function Ghost({ name, rec }) {
  const [obj, setObj] = useState(null)
  useEffect(() => {
    let live = true
    loadModel(name, rec).then(p => {
      if (!live || !p?.render) return
      const o = p.render.clone(true)
      const wire = new THREE.MeshBasicMaterial({ color: '#f2a541', wireframe: true, transparent: true, opacity: 0.45, depthWrite: false })
      o.traverse(m => { if (m.isMesh) m.material = wire })
      setObj(o)
    })
    return () => { live = false }
  }, [rec?.url])
  return obj ? <primitive object={obj} /> : null
}

// a baked model, optionally with the game's model drawn as a wire ghost and the reference figure beside it
export function ModelCanvas({ url, ghost, figure = true, height = '100%' }) {
  const glb = useGlb(url)
  const obj = useMemo(() => glb && litCopy(glb), [glb])
  const box = useMemo(() => (obj ? new THREE.Box3().setFromObject(obj) : null), [obj])
  const half = box && !box.isEmpty() ? (box.max.x - box.min.x) / 2 : 0.5
  const fx = (box ? box.max.x : 0.5) + Math.max(half * 0.4, 0.7)
  const fit = useMemo(() => {
    if (!box) return null
    const b = box.clone()
    if (figure) b.union(new THREE.Box3(new THREE.Vector3(fx - 0.3, 0, -0.3), new THREE.Vector3(fx + 0.3, 1.9, 0.3)))
    return b
  }, [box, figure, fx])
  return (
    <Canvas linear flat style={{ height }} camera={{ fov: 45, near: 0.05, far: 500, position: [4, 3, 5] }}>
      <color attach="background" args={[vpColor()]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[4, 8, 5]} intensity={0.8} />
      <gridHelper args={[20, 40, '#3a4655', '#232b36']} />
      <Suspense fallback={null}>
        {obj && <primitive object={obj} />}
        {ghost?.rec && <Ghost name={ghost.name} rec={ghost.rec} />}
      </Suspense>
      {figure && <Figure x={fx} />}
      <OrbitControls makeDefault />
      {fit && <Fit box={fit} />}
    </Canvas>
  )
}

// a game model, one of its textures swapped for `dataUrl` (the edited picture, decoded back from what the game will hold)
export function TextureCanvas({ rec, target, dataUrl, height = '100%' }) {
  const glb = useGlb(rec?.url)
  const [tick, setTick] = useState(0)
  const swap = useMemo(() => {
    if (!dataUrl) return null
    const t = new THREE.TextureLoader().load(dataUrl, () => setTick(n => n + 1))
    t.flipY = false; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 4; t.colorSpace = THREE.NoColorSpace
    return t
  }, [dataUrl])
  const obj = useMemo(() => {
    if (!glb) return null
    const render = glb.getObjectByName('render') || glb
    const o = render.clone(true)
    o.traverse(m => {
      if (!m.isMesh) return
      const ref = (m.material?.userData?.tod_texture || '').toLowerCase()
      const info = rec.textures?.[m.material?.userData?.tod_texture]
      let map = null
      if (ref === (target || '').toLowerCase() && swap) map = swap
      else if (info?.url) { map = dds.load(info.url); map.wrapS = map.wrapT = THREE.RepeatWrapping }
      m.material = new THREE.MeshLambertMaterial({ map, color: map ? 0xffffff : 0x9aa3ad, side: THREE.DoubleSide, alphaTest: info?.alpha || (ref === (target || '').toLowerCase() && swap) ? 0.5 : 0 })
    })
    return o
  }, [glb, swap, target, tick])
  const box = useMemo(() => (obj ? new THREE.Box3().setFromObject(obj) : null), [glb])
  return (
    <Canvas linear flat style={{ height }} camera={{ fov: 45, near: 0.05, far: 500, position: [4, 3, 5] }}>
      <color attach="background" args={[vpColor()]} />
      <ambientLight intensity={0.95} />
      <directionalLight position={[4, 8, 5]} intensity={0.7} />
      <gridHelper args={[20, 40, '#3a4655', '#232b36']} />
      {obj && <primitive object={obj} />}
      <OrbitControls makeDefault />
      {box && <Fit box={box} />}
    </Canvas>
  )
}
