// The live 3D preview of a catalogue model: the game's own mesh with its real textures, orbit, wireframe, collision hulls, pivots and
// bones, its size in metres and a Ram-sized figure for scale. Materials are diffuse lit (metalness 0), as the game draws them.
import { reducedMotion } from './uiprefs.js'
import React, { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { loadModel } from './models.js'
import { vpColor } from './theme.js'
import RigView from './RigView.jsx'
import { t as tr } from './i18n.js'

const ACCENT = '#f2a541'

function Figure({ x, height }) {
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: '#9cc3ff', transparent: true, opacity: 0.5, depthWrite: false }), [])
  const k = height / 1.8
  return <group position={[x, 0, 0]} scale={[k, k, k]}>
    <mesh position={[0, 0.78, 0]} material={mat}><capsuleGeometry args={[0.2, 1.1, 4, 12]} /></mesh>
    <mesh position={[0, 1.66, 0]} material={mat}><sphereGeometry args={[0.14, 14, 10]} /></mesh>
  </group>
}

function Fit({ box }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    if (!controls || !box || box.isEmpty()) return
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3())
    const r = Math.max(s.x, s.y, s.z, 0.4)
    controls.target.copy(c)
    camera.position.set(c.x + r * 1.05, c.y + r * 0.7, c.z + r * 1.35)
    camera.near = Math.max(0.01, r / 200); camera.far = r * 300
    camera.updateProjectionMatrix(); controls.update()
  }, [box && [box.min.x, box.max.x, box.min.y, box.max.y, box.min.z, box.max.z].join(), controls])
  return null
}

// the model, rebuilt from the cached prototype for each viewer so toggles never touch the editor's shared materials
function useProto(path, rec) {
  const [p, setP] = useState(null)
  useEffect(() => {
    let live = true
    setP(null)
    if (rec?.url) loadModel(path, rec).then(x => { if (live) setP(x) })
    return () => { live = false }
  }, [path, rec?.url])
  return p
}

function Bones({ pivots, scale }) {
  const geo = useMemo(() => {
    const pos = []
    pivots.forEach(p => { if (p.parent >= 0 && pivots[p.parent]) pos.push(...pivots[p.parent].pos, ...p.pos) })
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    return g
  }, [pivots])
  const sph = useMemo(() => new THREE.SphereGeometry(scale, 8, 6), [scale])
  const dot = useMemo(() => new THREE.MeshBasicMaterial({ color: ACCENT, depthTest: false, transparent: true }), [])
  return <group renderOrder={20}>
    <lineSegments geometry={geo} renderOrder={20}><lineBasicMaterial color="#4b9fff" depthTest={false} transparent /></lineSegments>
    {pivots.map((p, i) => <mesh key={i} geometry={sph} material={dot} position={p.pos} renderOrder={21} />)}
  </group>
}

function Scene({ detail, opts, onStats, rig, ctl, onTime }) {
  const proto = useProto(detail.path, detail.rec)
  const obj = useMemo(() => {
    if (!proto?.render) return null
    const o = proto.render.clone(true)
    o.traverse(m => {
      if (!m.isMesh) return
      const src = m.material
      m.material = new THREE.MeshLambertMaterial({ map: src.map || null, color: src.map ? 0xffffff : 0x9aa3ad, side: THREE.DoubleSide, alphaTest: src.alphaTest || 0 })
      m.material.userData.map = src.map || null
    })
    return o
  }, [proto])
  const coll = useMemo(() => {
    if (!proto?.collision) return null
    const c = proto.collision.clone(true)
    c.traverse(m => { if (m.isMesh) m.material = m.material.clone(), m.material.depthTest = false, m.material.opacity = 0.42, m.renderOrder = 5 })
    return c
  }, [proto])
  useEffect(() => {
    if (!obj) return
    let sub = 0, tris = 0
    const maps = new Set()
    obj.traverse(m => {
      if (!m.isMesh) return
      sub++
      tris += (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3
      if (m.material.map) maps.add(m.material.map.uuid)
    })
    onStats && onStats({ sub, tris: Math.round(tris), maps: maps.size, coll: !!coll })
  }, [obj, coll])
  // toggles
  useEffect(() => {
    if (!obj) return
    obj.traverse(m => {
      if (!m.isMesh) return
      const t = m.material
      t.wireframe = !!opts.wire
      t.map = opts.wire ? null : t.userData.map
      t.color.set(opts.wire ? ACCENT : (t.userData.map ? 0xffffff : 0x9aa3ad))
      t.transparent = !!opts.coll
      t.opacity = opts.coll ? 0.45 : 1
      t.depthWrite = !opts.coll
      t.needsUpdate = true
    })
  }, [obj, opts.wire, opts.coll])
  const box = useMemo(() => {
    if (!obj) return null
    const b = new THREE.Box3().setFromObject(obj)
    return b.isEmpty() ? null : b
  }, [obj])
  const size = box ? box.getSize(new THREE.Vector3()) : null
  const figX = box ? box.max.x + Math.max((box.max.x - box.min.x) * 0.25, 0.8) : 1
  const fit = useMemo(() => {
    if (!box) return null
    const b = box.clone()
    if (opts.figure) b.union(new THREE.Box3(new THREE.Vector3(figX - 0.3, 0, -0.3), new THREE.Vector3(figX + 0.3, 1.8, 0.3)))
    return b
  }, [box, opts.figure, figX])
  const boneR = size ? Math.max(0.012, Math.max(size.x, size.y, size.z) * 0.012) : 0.02
  return <>
    {obj && <primitive object={obj} visible={!rig} />}
    {rig && <RigView skin={rig.skin} clip={rig.clip} ctl={ctl} showBones={opts.bones} wire={opts.wire} onTime={onTime} />}
    {opts.coll && coll && <primitive object={coll} />}
    {opts.bones && !rig && detail.pivots?.length > 0 && <Bones pivots={detail.pivots} scale={boneR} />}
    {opts.box && box && <box3Helper args={[box, new THREE.Color('#5b9bff')]} />}
    {opts.figure && box && <Figure x={figX} height={detail.ram || 1.8} />}
    {opts.figure && box && <Html position={[figX, 2.05, 0]} center style={{ pointerEvents: 'none' }}><div className="tag">{tr('ram_1_8_m')}</div></Html>}
    {opts.box && box && size && <Html position={[(box.min.x + box.max.x) / 2, box.max.y, (box.min.z + box.max.z) / 2]} center style={{ pointerEvents: 'none' }}>
      <div className="tag">{size.x.toFixed(2)} × {size.y.toFixed(2)} × {size.z.toFixed(2)}{' '}{tr('m')}</div></Html>}
    {fit && <Fit box={fit} />}
  </>
}

export default function AssetPreview({ detail, opts, onStats, vp, rig, ctl, onTime }) {
  return (
    <Canvas linear flat style={{ position: 'absolute', inset: 0 }} gl={{ preserveDrawingBuffer: true }} camera={{ fov: 42, near: 0.05, far: 800, position: [4, 3, 5] }}>
      <color attach="background" args={[vp || vpColor()]} />
      <ambientLight intensity={0.95} />
      <directionalLight position={[4, 8, 5]} intensity={0.8} />
      <gridHelper args={[40, 80, '#3a4655', '#232b36']} />
      <Suspense fallback={null}><Scene detail={detail} opts={opts} onStats={onStats} rig={rig} ctl={ctl} onTime={onTime} /></Suspense>
      <OrbitControls makeDefault enableDamping={!reducedMotion()} />
    </Canvas>
  )
}
