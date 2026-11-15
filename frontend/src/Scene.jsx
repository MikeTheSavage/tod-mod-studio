import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { toView, quatToView, fromView, quatFromView } from './coords.js'
import { CAT_COLOR } from './view.js'
import { loadModel } from './models.js'

const ONE = new THREE.Vector3(1, 1, 1)

// shared shapes for gameplay objects (metres)
const GEO = {
  box: new THREE.BoxGeometry(1, 1, 1),
  pickup: new THREE.OctahedronGeometry(0.45),
  weapon: new THREE.BoxGeometry(0.9, 0.25, 0.25),
  character: new THREE.CapsuleGeometry(0.35, 1.1, 4, 10),
  vehicle: new THREE.BoxGeometry(2.0, 1.5, 4.6),
  point: new THREE.SphereGeometry(0.35, 12, 8),
  marker: new THREE.ConeGeometry(0.6, 1.6, 4),
  havoc: new THREE.DodecahedronGeometry(0.6),
  small: new THREE.SphereGeometry(0.25, 8, 6),
}
const VOL_OPACITY = { wall: 0.2, navblock: 0.16, trigger: 0.04, sound: 0.03, box: 0.05 }
const matCache = new Map()
function catMaterial(cat, kind) {
  const key = cat + '|' + kind
  if (!matCache.has(key)) {
    const color = new THREE.Color(CAT_COLOR[cat] || '#cccccc')
    let m
    if (kind === 'volume') m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: VOL_OPACITY[cat] ?? 0.05, depthWrite: false, side: THREE.DoubleSide })
    else if (kind === 'volsel') m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.3, depthWrite: false, side: THREE.DoubleSide })
    else if (kind === 'edges') m = new THREE.LineBasicMaterial({ color })
    else if (kind === 'off') m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.25, wireframe: true })
    else if (kind === 'sel') m = new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true })
    else m = new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.35 })
    matCache.set(key, m)
  }
  return matCache.get(key)
}
const EDGES = new THREE.EdgesGeometry(GEO.box)

function shapeFor(e) {
  switch (e.cat) {
    case 'pickup': return GEO.pickup
    case 'weapon': return GEO.weapon
    case 'character': return GEO.character
    case 'vehicle': return GEO.vehicle
    case 'route': return GEO.point
    case 'marker': return GEO.marker
    case 'havoc': return GEO.havoc
    default: return GEO.small
  }
}

function isVolume(e) { return !!e.size }

// ------------------------------------------------------------------ one gameplay object
function Thing({ e, selected, register, onPick }) {
  const ref = useRef()
  useEffect(() => { register(e.id, ref.current); return () => register(e.id, null) }, [e.id])
  const off = e.deleted || e.off
  const yOffset = e.cat === 'character' ? 0.9 : e.cat === 'vehicle' ? 0.75 : e.cat === 'marker' ? 0.8 : 0
  const click = ev => { ev.stopPropagation(); onPick(e.id, ev) }
  return (
    <group ref={ref} position={toView(e.pos)} quaternion={quatToView(e.rot)} userData={{ eid: e.id }}>
      {isVolume(e) ? (
        <group scale={e.size}>
          <mesh geometry={GEO.box} material={catMaterial(e.cat, off ? 'off' : selected ? 'volsel' : 'volume')} onClick={click} />
          <lineSegments geometry={EDGES} material={selected ? catMaterial('x', 'sel') : catMaterial(e.cat, 'edges')} />
        </group>
      ) : (
        <mesh position={[0, yOffset, 0]} geometry={shapeFor(e)} material={catMaterial(e.cat, off ? 'off' : 'solid')}
              onClick={click} />
      )}
      {selected && !isVolume(e) && (
        <mesh position={[0, yOffset, 0]} geometry={shapeFor(e)} scale={1.25} material={catMaterial('x', 'sel')} />
      )}
    </group>
  )
}

// ------------------------------------------------------------------ one placed model
export function ModelThing({ e, rec, showGeom, showColl, selected, register, onPick }) {
  const ref = useRef()
  const [proto, setProto] = useState(null)
  useEffect(() => { let live = true; loadModel(e.model, rec).then(p => live && setProto(p)); return () => { live = false } }, [rec?.url])
  useEffect(() => { register(e.id, ref.current); return () => register(e.id, null) }, [e.id])
  const render = useMemo(() => proto?.render ? proto.render.clone() : null, [proto])
  const coll = useMemo(() => proto?.collision ? proto.collision.clone() : null, [proto])
  const box = useMemo(() => {
    if (!render) return null
    const b = new THREE.Box3().setFromObject(render)
    return b.isEmpty() ? null : b
  }, [render])
  const click = ev => { ev.stopPropagation(); onPick(e.id, ev) }
  return (
    <group ref={ref} position={toView(e.pos)} quaternion={quatToView(e.rot)} userData={{ eid: e.id }}>
      {render && <primitive object={render} visible={showGeom && !e.deleted} onClick={click} />}
      {coll && <primitive object={coll} visible={showColl} />}
      {!render && !coll && <mesh geometry={GEO.small} material={catMaterial('model', 'solid')} onClick={click} />}
      {selected && box && (
        <mesh position={box.getCenter(new THREE.Vector3())} scale={box.getSize(new THREE.Vector3())}
              geometry={GEO.box} material={catMaterial('x', 'sel')} />
      )}
    </group>
  )
}

// ------------------------------------------------------------------ the mod's new collision (companion tool)
const NEW_MAT = new THREE.MeshBasicMaterial({ color: '#1ef06e', transparent: true, opacity: 0.38, depthWrite: false, side: THREE.DoubleSide })
const NEW_EDGE = new THREE.LineBasicMaterial({ color: '#7dffb0' })
const OLD_COL = { solid: '#ff8c19', thin: '#ffd732', blocker: '#4b8cff', other: '#b4b4b4' }
export function pieceGeometry(verts, faces, tris) {
  const pos = []
  const T = tris || faces.flatMap(f => f.slice(1, -1).map((_, k) => [f[0], f[k + 1], f[k + 2]]))
  for (const t of T) for (const i of t) { const v = toView(verts[i]); pos.push(v.x, v.y, v.z) }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  return g
}
export function NewCollision({ sets, existing, visible }) {
  const geos = useMemo(() => {
    const out = []
    for (const s of sets || []) for (const p of s.pieces || []) {
      const g = pieceGeometry(p.verts, p.faces)
      out.push({ key: s.id + ':' + out.length, g, e: new THREE.EdgesGeometry(g, 1) })
    }
    return out
  }, [sets])
  const old = useMemo(() => (existing || []).map((it, i) => ({ key: 'x' + i, g: pieceGeometry(it.verts, null, it.tris), cls: it.cls })), [existing])
  if (!visible) return null
  return <group>
    {geos.map(x => <group key={x.key}><mesh geometry={x.g} material={NEW_MAT} /><lineSegments geometry={x.e} material={NEW_EDGE} /></group>)}
    {old.map(x => <mesh key={x.key} geometry={x.g}><meshBasicMaterial color={OLD_COL[x.cls] || '#b4b4b4'} transparent opacity={0.3} depthWrite={false} side={THREE.DoubleSide} wireframe /></mesh>)}
  </group>
}

// ------------------------------------------------------------------ route lines
function Routes({ links, ents, visible }) {
  const segs = useMemo(() => {
    const by = { goto: [], patrol: [], vehicle: [], traffic: [], ped: [], object: [] }
    for (const [a, b, kind] of links) {
      const A = ents.get(a), B = ents.get(b)
      if (!A || !B) continue
      ;(by[kind] || (by[kind] = [])).push(toView(A.pos), toView(B.pos))
    }
    return by
  }, [links, ents])
  if (!visible) return null
  const col = { goto: '#ef476f', patrol: '#80ed99', vehicle: '#06d6a0', traffic: '#4cc9f0', ped: '#ffd23f', object: '#6c7a89' }
  return Object.entries(segs).filter(([, p]) => p.length).map(([k, pts]) => (
    <Line key={k} points={pts} segments color={col[k] || '#ffffff'} lineWidth={k === 'object' ? 1 : 2} transparent opacity={k === 'object' ? 0.35 : 0.9} />
  ))
}

// ------------------------------------------------------------------ camera helpers
function CameraRig({ focus }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    if (!focus || !controls) return
    const t = toView(focus.pos)
    const d = focus.dist || 25
    const dir = new THREE.Vector3().subVectors(camera.position, controls.target)
    if (dir.lengthSq() < 1e-6 || focus.reset) dir.set(1, focus.dist < 15 ? 0.45 : 0.8, 1)
    dir.normalize().multiplyScalar(d)
    controls.target.copy(t)
    camera.position.copy(t).add(dir)
    camera.near = 0.2
    camera.far = 8000
    camera.updateProjectionMatrix()
    controls.update()
  }, [focus, controls])
  return null
}

// WASD / QE flying, while the 3D view has the mouse
function FlyKeys({ enabled }) {
  const { camera, controls } = useThree()
  const keys = useRef(new Set())
  useEffect(() => {
    const dn = e => { if (!enabled.current || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.ctrlKey) return; keys.current.add(e.key.toLowerCase()) }
    const up = e => keys.current.delete(e.key.toLowerCase())
    window.addEventListener('keydown', dn); window.addEventListener('keyup', up)
    const blur = () => keys.current.clear()
    window.addEventListener('blur', blur)
    return () => { window.removeEventListener('keydown', dn); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur) }
  }, [])
  useFrame((_, dt) => {
    const k = keys.current
    if (!controls || !k.size) return
    const speed = (k.has('shift') ? 60 : 18) * dt
    const fwd = new THREE.Vector3().subVectors(controls.target, camera.position).setY(0).normalize()
    const right = new THREE.Vector3().crossVectors(fwd, camera.up).normalize()
    const m = new THREE.Vector3()
    if (k.has('w')) m.add(fwd)
    if (k.has('s')) m.sub(fwd)
    if (k.has('d')) m.add(right)
    if (k.has('a')) m.sub(right)
    if (k.has('e')) m.y += 1
    if (k.has('q')) m.y -= 1
    if (m.lengthSq() === 0) return
    m.normalize().multiplyScalar(speed)
    camera.position.add(m)
    controls.target.add(m)
    controls.update()
  })
  return null
}

// exposes "what is under the screen centre" for the palette
function CenterProbe({ probe }) {
  const { camera, scene, controls } = useThree()
  useEffect(() => {
    probe.current = () => {
      const rc = new THREE.Raycaster()
      rc.setFromCamera(new THREE.Vector2(0, 0), camera)
      const hits = rc.intersectObjects(scene.children, true).filter(h => h.object.visible && h.object.isMesh &&
        !h.object.material?.transparent)
      if (hits.length && hits[0].distance < 400) return fromView(hits[0].point)
      return controls ? fromView(controls.target) : fromView(new THREE.Vector3())
    }
  }, [camera, scene, controls])
  return null
}

// ------------------------------------------------------------------ the scene
export default function Scene({ view, bundle, layers, showColl, showGeom, selectedId, onPick, onCommitTransform,
                                 gizmoMode, focus, probe, flyEnabled, newColl, showNewColl }) {
  const registry = useRef(new Map())
  const [, force] = useState(0)
  const register = (id, obj) => {
    if (obj) registry.current.set(id, obj); else registry.current.delete(id)
    if (id === selectedId) force(x => x + 1)
  }
  const visible = view.list.filter(e => layers[e.cat])
  const models = visible.filter(e => e.model && bundle.models[e.model] && !bundle.models[e.model].missing)
  const things = visible.filter(e => !(e.model && bundle.models[e.model] && !bundle.models[e.model].missing))
  const sel = selectedId ? view.ents.get(selectedId) : null
  const selObj = sel ? registry.current.get(selectedId) : null
  const dragging = useRef(false)
  return (
    <>
      <color attach="background" args={['#1a2029']} />
      <fog attach="fog" args={['#1a2029', 600, 3000]} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[300, 500, 200]} intensity={0.75} />
      <hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
      {models.map(e => (
        <ModelThing key={e.id} e={e} rec={bundle.models[e.model]} showGeom={showGeom} showColl={showColl}
                    selected={e.id === selectedId} register={register} onPick={onPick} />
      ))}
      {things.filter(e => e.cat !== 'model' && e.cat !== 'logic').map(e => (
        <Thing key={e.id} e={e} selected={e.id === selectedId} register={register} onPick={onPick} />
      ))}
      <Routes links={view.links} ents={view.ents} visible={layers.route} />
      <NewCollision sets={newColl} visible={showNewColl} />
      {sel && selObj && sel.ed && !sel.deleted && (
        <TransformControls object={selObj} mode={gizmoMode} size={0.8}
          showX showY showZ
          onMouseDown={() => { dragging.current = true }}
          onMouseUp={() => {
            dragging.current = false
            const o = selObj
            if (gizmoMode === 'scale' && sel.size) {
              const inner = o.children[0]
              const s = o.scale
              const size = [sel.size[0] * s.x, sel.size[1] * s.y, sel.size[2] * s.z].map(v => Math.max(0.05, Math.round(v * 100) / 100))
              o.scale.set(1, 1, 1)
              onCommitTransform(sel, null, null, size)
            } else {
              o.scale.set(1, 1, 1)
              onCommitTransform(sel, fromView(o.position), quatFromView(o.quaternion), null)
            }
          }} />
      )}
      {sel && (
        <Html position={toView(sel.pos).add(new THREE.Vector3(0, (sel.size ? sel.size[1] / 2 : 1.6) + 0.6, 0))}
              center style={{ pointerEvents: 'none' }}>
          <div className="tag">{sel.name || sel.type}</div>
        </Html>
      )}
      <OrbitControls makeDefault enableDamping={false} maxDistance={3000} />
      <CameraRig focus={focus} />
      <FlyKeys enabled={flyEnabled} />
      <CenterProbe probe={probe} />
    </>
  )
}
