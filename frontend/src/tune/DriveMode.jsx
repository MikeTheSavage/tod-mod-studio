// Playground: drive the selected car. Flat ground, or a section of a real map using its extracted collision.
// The physics engine is loaded here, the first time this mode opens.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { GameModel, GroundGrid, useSky } from './PreviewKit.jsx'
import { ModelThing } from '../Scene.jsx'
import { buildView } from '../view.js'
import { toView, quatToView } from '../coords.js'
import { useInput, readPad } from './input.js'
import { prototypeOf, useGameModels, vehicleModelPath } from './gameModels.js'
import { createDrive, trimeshBody, heightMesh, steepMesh } from './drive.js'
import * as M from './mapping.js'
import { t as tr } from '../i18n.js'

const PHYS_R = 110, SHOW_R = 220
const noop = () => {}
const DEBUG = typeof location !== 'undefined' && new URLSearchParams(location.search).has('debug')

// world-space triangles of a model's collision at an entity's place
function collisionOf(proto, e) {
  if (!proto?.collision) return null
  const root = proto.collision
  root.updateMatrixWorld(true)
  const E = new THREE.Matrix4().compose(toView(e.pos), quatToView(e.rot), new THREE.Vector3(1, 1, 1))
  const verts = [], idx = []
  const v = new THREE.Vector3()
  root.traverse(o => {
    if (!o.isMesh || !o.geometry?.attributes?.position) return
    const m = new THREE.Matrix4().multiplyMatrices(E, o.matrixWorld)
    const P = o.geometry.attributes.position, I = o.geometry.index
    const base = verts.length / 3
    for (let i = 0; i < P.count; i++) { v.fromBufferAttribute(P, i).applyMatrix4(m); verts.push(v.x, v.y, v.z) }
    if (I) for (let i = 0; i < I.count; i++) idx.push(base + I.getX(i))
    else for (let i = 0; i < P.count; i++) idx.push(base + i)
  })
  return verts.length ? { verts, idx } : null
}

function Scene({ C, ph, vType, path, rec, mapData, wantMap, input, hud, cam, resetKey }) {
  const { camera, size } = useThree()
  // the car is rebuilt only when its numbers change, not when a parent re-renders
  const phKey = JSON.stringify(ph)
  const drive = useMemo(() => createDrive(C, ph, { y: 2 }), [C, phKey])
  const carRef = useRef(), wheelRefs = useRef([])
  const camYaw = useRef(0), spawn = useRef({ x: 0, y: 2, z: 0 })
  const geoms = useRef(new Map())
  const bodies = useRef(new Map()), center = useRef(null), busy = useRef(false), ready = useRef(false)
  const [near, setNear] = useState([])
  const st = useRef({ acc: 0, fell: 0, t: 0, handUp: true })
  const fov = useMemo(() => M.fovDeg(size.width / Math.max(1, size.height)).vertical, [size.width, size.height])
  const back = ph.wheelbase / 0.74 * 1.95, up = ph.wheelbase / 0.74 * 0.38

  // ground: flat, or the map's collision streamed around the car
  useEffect(() => { bodies.current.clear(); geoms.current.clear(); center.current = null; ready.current = false }, [drive])
  useEffect(() => {
    if (mapData) return
    drive.clearGround(); drive.addGround([drive.plane(0)])
    drive.reset(0, 1.2, 0, 0)
    return () => drive.clearGround()
  }, [drive, mapData])
  const ents = useMemo(() => {
    if (!mapData) return []
    const view = buildView(mapData, [], null)
    return view.list.filter(e => e.model && mapData.models[e.model] && !mapData.models[e.model].missing && !e.deleted)
  }, [mapData])
  async function rebuild(cx, cz) {
    if (busy.current) return
    busy.current = true
    try {
      const want = ents.filter(e => {
        const r = mapData.models[e.model]
        if (!r.coll) return false
        const b = r.bound || [0, 0, 0, 0]
        return Math.hypot(e.pos[0] + b[0] - cx, -e.pos[2] + b[2] - cz) < PHYS_R + b[3]
      })
      const ids = new Set(want.map(e => e.id))
      for (const id of [...geoms.current.keys()]) if (!ids.has(id)) geoms.current.delete(id)
      for (const e of want) {
        if (geoms.current.has(e.id)) continue
        const proto = await prototypeOf(e.model, mapData.models[e.model])
        geoms.current.set(e.id, collisionOf(proto, e))
      }
      const list = [...geoms.current.values()].filter(Boolean)
      // the ground the wheels see (a continuous surface over the pieces) and the walls the body meets
      for (const k of ['hf', 'walls']) { if (bodies.current.get(k)) drive.world.removeBody(bodies.current.get(k)); bodies.current.delete(k) }
      const hm = heightMesh(list, cx, cz, PHYS_R)
      if (hm) { const b = trimeshBody(C, hm.verts, hm.idx, 1); drive.world.addBody(b); bodies.current.set('hf', b) }
      const wm = steepMesh(list)
      if (wm) { const b = trimeshBody(C, wm.verts, wm.idx, 2); drive.world.addBody(b); bodies.current.set('walls', b) }
      setNear(ents.filter(e => Math.hypot(e.pos[0] - cx, -e.pos[2] - cz) < SHOW_R))
      center.current = [cx, cz]
    } finally { busy.current = false }
  }
  // where to start: on the biggest piece of collision (the terrain), dropped from above
  useEffect(() => {
    if (!mapData) return
    let live = true
    ;(async () => {
      const cand = ents.filter(e => mapData.models[e.model].coll > 300).sort((a, b) => mapData.models[b.model].coll - mapData.models[a.model].coll).slice(0, 3)
      let first = null
      const probe = (x, z) => {
        const r = new C.RaycastResult()
        drive.world.raycastClosest(new C.Vec3(x, 600, z), new C.Vec3(x, -600, z), { skipBackfaces: false }, r)
        if (!r.hasHit) return null
        const y = r.hitPointWorld.y + 0.55
        if (!first) first = { x, y: y + 0.2, z }
        drive.reset(x, y, z, 0)
        for (let i = 0; i < 60; i++) drive.step(1 / 60, {})
        const p = drive.pose()
        // a good start: the car holds its height on the wheels and can pull away (not wedged in a yard)
        if (!(p.onGround >= 3 && p.p.y > y - 0.2 && p.speed < 1)) return null
        const sy = p.p.y, sx = p.p.x, sz = p.p.z
        for (let i = 0; i < 80; i++) drive.step(1 / 60, { throttle: 1 })
        const q = drive.pose()
        if (Math.hypot(q.p.x - sx, q.p.z - sz) < 10 || q.p.y < sy - 3) return null
        return { x: sx, y: sy + 0.1, z: sz }
      }
      for (const e of cand) {
        const b = mapData.models[e.model].bound || [0, 0, 0, 0]
        const cx = e.pos[0] + b[0], cz = -e.pos[2] + b[2]
        await rebuild(cx, cz)
        if (!live) return
        for (const [dx, dz] of [[0, 0], [14, 0], [-14, 0], [0, 14], [0, -14], [30, 10], [-30, 10], [10, 30], [10, -30]]) {
          const s = probe(cx + dx, cz + dz)
          if (s) { spawn.current = s; drive.reset(s.x, s.y, s.z, 0); for (let i = 0; i < 40; i++) drive.step(1 / 60, {}); ready.current = true; return }
        }
      }
      const f = first || { x: 0, y: 30, z: 0 }
      spawn.current = f; drive.reset(f.x, f.y, f.z, 0); ready.current = true
    })()
    return () => { live = false; for (const b of bodies.current.values()) b && drive.world.removeBody(b); bodies.current.clear(); geoms.current.clear() }
  }, [ents, drive])
  useEffect(() => { const s = spawn.current; drive.reset(s.x, s.y, s.z, 0) }, [resetKey])

  const demo = useMemo(() => new URLSearchParams(location.search).get('demo'), [])
  const tick = dt => {
    const inp = input.current, pad = readPad()
    const k = n => (inp.key(n) ? 1 : 0)
    let throttle = k('w') + k('arrowup') - 0 - 0, rev = k('s') + k('arrowdown')
    let steer = k('d') + k('arrowright') - k('a') - k('arrowleft')
    let brake = k('v') || k('b') ? 1 : 0
    let hand = !!inp.key(' ')
    if (pad) {
      steer += pad.lx; throttle += pad.rt; rev += pad.lt; if (pad.x) brake = 1; if (pad.a) hand = true
      if (pad.y) drive.reset(spawn.current.x, spawn.current.y + 1, spawn.current.z, 0)
    }
    if (inp.take('r')) { const p = drive.pose(); drive.reset(p.p.x, p.p.y + 1.5, p.p.z, Math.atan2(2 * (p.q.w * p.q.y), 1 - 2 * p.q.y * p.q.y)) }
    const t = Math.max(-1, Math.min(1, Math.min(1, throttle) - Math.min(1, rev)))
    drive.step(dt, { throttle: t, steer: Math.max(-1, Math.min(1, steer)), brake, hand })
    const pose = drive.pose()
    // ---- the car
    if (carRef.current) {
      carRef.current.position.set(pose.p.x, pose.p.y, pose.p.z)
      carRef.current.quaternion.set(pose.q.x, pose.q.y, pose.q.z, pose.q.w)
    }
    const wi = drive.vehicle.wheelInfos
    wheelRefs.current.forEach((m, i) => {
      if (!m) return
      const w = pose.wheels[i]
      m.position.set(w.p.x, w.p.y, w.p.z); m.quaternion.set(w.q.x, w.q.y, w.q.z, w.q.w)
    })
    const sl = wi.reduce((a, w) => a + w.suspensionLength, 0) / wi.length
    if (carRef.current) carRef.current.userData.drop = -0.1 - sl - ph.wheelRadius
    // ---- chase camera (the vehicle camera values)
    const f = new THREE.Vector3(0, 0, 1).applyQuaternion(new THREE.Quaternion(pose.q.x, pose.q.y, pose.q.z, pose.q.w))
    const heading = Math.atan2(f.x, f.z)
    camYaw.current = M.followYaw(camYaw.current, heading, cam, dt)
    const cy = camYaw.current
    camera.position.set(pose.p.x - Math.sin(cy) * back, pose.p.y + up + 1.2, pose.p.z - Math.cos(cy) * back)
    camera.lookAt(pose.p.x, pose.p.y + 0.8, pose.p.z)
    if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix() }
    // ---- stream the map when the car has moved on; respawn when it falls out
    const S = st.current
    if (DEBUG) document.title = 'D' + JSON.stringify({ x: pose.p.x, y: pose.p.y, z: pose.p.z, vF: pose.vF, wheels: pose.onGround })      // screenshot checks
    if (mapData && center.current && Math.hypot(pose.p.x - center.current[0], pose.p.z - center.current[1]) > PHYS_R * 0.45) rebuild(pose.p.x, pose.p.z)
    if (pose.p.y < spawn.current.y - 80) drive.reset(spawn.current.x, spawn.current.y + 2, spawn.current.z, 0)
    S.acc += dt
    if (S.acc > 0.08) { S.acc = 0; hud({ kmh: Math.abs(pose.vF) * 3.6, rev: pose.vF < -0.5, slide: Math.abs(pose.steer) > 0.05 && Math.abs(pose.vF) > ph.slideSpeed, ground: pose.onGround }) }
  }
  const warmed = useRef(0)
  useFrame((_, rdt) => {
    // ?demo=1 drives for a few seconds once the ground is there, before the picture (screenshots)
    if (demo && warmed.current < 3 && (!wantMap || (mapData && ready.current))) { warmed.current++; if (warmed.current === 2) for (let i = 0; i < (+demo > 1 ? +demo : 360); i++) tick(1 / 60) }
    tick(Math.min(rdt, 1 / 30))
  })
  const missing = !path || !rec || rec.missing
  return (
    <>
      <ambientLight intensity={0.95} /><directionalLight position={[300, 500, 200]} intensity={0.8} /><hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
      {!mapData && <><mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}><planeGeometry args={[1200, 1200]} /><meshLambertMaterial color="#5b6a54" /></mesh><GroundGrid size={1200} step={10} color="#68745f" /></>}
      {near.map(e => <ModelThing key={e.id} e={e} rec={mapData.models[e.model]} showGeom showColl={false} selected={false} register={noop} onPick={noop} />)}
      <group ref={carRef}>
        <group position={[0, -(0.1 + 0.2 + ph.wheelRadius), 0]}>
          <GameModel path={path} rec={rec} fit={ph.wheelbase / 0.74} rotY={Math.PI} />
          {missing && <mesh position={[0, 0.9, 0]}><boxGeometry args={[ph.halfExtents[0] * 2, ph.halfExtents[1] * 2, ph.halfExtents[2] * 2]} /><meshLambertMaterial color="#9aa3ad" /></mesh>}
        </group>
      </group>
      {missing && [0, 1, 2, 3].map(i => <group key={i} ref={el => { wheelRefs.current[i] = el }}><mesh rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[ph.wheelRadius, ph.wheelRadius, 0.28, 16]} /><meshLambertMaterial color="#1c1f24" /></mesh></group>)}
    </>
  )
}

export default function DriveMode({ vType, ph, mapData, wantMap, cam, busyText, resetKey }) {
  const wrap = useRef()
  const input = useInput(wrap)
  const bg = useSky()
  const [C, setC] = useState(null)
  const [h, setH] = useState({ kmh: 0 })
  useEffect(() => { let live = true; import('../vendor/cannon-es.js').then(m => live && setC(m)); return () => { live = false } }, [])
  const path = vehicleModelPath(vType)
  const recs = useGameModels([path])
  return (
    <div className="pv-in" ref={wrap} tabIndex={0} data-pad-ctx="play" aria-label={tr('playground')} style={{ outline: 'none' }}>
      {C && <Canvas linear flat camera={{ fov: 55, near: 0.2, far: 1500, position: [0, 4, -10] }} gl={{ antialias: true }} dpr={[1, 1.5]}>
        <color attach="background" args={[bg]} />
        <fog attach="fog" args={[bg, 200, 900]} />
        <Scene C={C} ph={ph} vType={vType} path={path} rec={recs[path]} mapData={mapData} wantMap={wantMap} input={input} hud={setH} cam={cam} resetKey={resetKey} />
      </Canvas>}
      <div className="hud" style={{ left: 12, bottom: 12 }}>
        <div className="box">
          <div className="row"><span className="big">{Math.round(h.kmh)}</span><span className="dim">{tr('km_h')}</span>{h.rev && <span className="dim">{tr('r')}</span>}{h.slide && <span className="dim" style={{ color: '#ff8f8f' }}>{tr('slide')}</span>}</div>
          <div className="bar"><i style={{ width: `${Math.min(100, (h.kmh / 3.6) / Math.max(ph.topSpeed, 1) * 100)}%` }} /></div>
        </div>
      </div>
      {busyText && <div className="pgstart"><div className="box">{busyText}</div></div>}
    </div>
  )
}
