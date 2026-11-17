// Playground: walk Ram with the tuned camera and toggle slow motion with the tuned stamina values.
import React, { useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { RamActor, GroundGrid, useSky } from './PreviewKit.jsx'
import { useInput, readPad, padPressed } from './input.js'
import * as M from './mapping.js'
import { t } from '../i18n.js'

const PILLARS = [[-8, -10], [9, -14], [-14, -26], [14, -30], [0, -40], [-20, 6], [20, 8], [-6, 22], [8, 28]]

function Scene({ cam, sm, input, hud }) {
  const { camera, size } = useThree()
  const ram = useRef(), orbs = useRef([]), pos = useRef(new THREE.Vector3()), yaw = useRef(Math.PI), camYaw = useRef(Math.PI)
  const slow = useRef({ stamina: sm.maxStamina, scale: 1, on: false, want: false })
  const state = useRef({ clip: 'ram_weapon_idle_gun', dive: 0, t: 0, acc: 0, moving: false })
  const [clip, setClip] = useState('ram_weapon_idle_gun')
  const rig = useMemo(() => M.cameraPose(cam), [cam])
  const fov = useMemo(() => M.fovDeg(size.width / Math.max(1, size.height)).vertical, [size.width, size.height])
  const world = useRef(0)

  const demo = useMemo(() => new URLSearchParams(location.search).get('demo'), [])
  const tick = dt => {
    const inp = input.current, pad = readPad(), S = state.current
    // ---- slow motion
    if (inp.take('q') || padPressed(input, pad, 'lb') || padPressed(input, pad, 'y')) slow.current.want = !slow.current.want
    const sl = slow.current
    const prev = sl.on
    const n = M.stepSlowmo(sl, sm, dt, sl.want, S.moving)
    sl.stamina = n.stamina; sl.scale = n.scale; sl.on = n.on
    if (prev && !n.on) sl.want = false
    const wdt = dt * sl.scale
    world.current += wdt
    // ---- Ram: real-time clock x 0.95
    const mx = (inp.key('d') || inp.key('arrowright') ? 1 : 0) - (inp.key('a') || inp.key('arrowleft') ? 1 : 0) + (pad ? pad.lx : 0)
    const mz = (inp.key('s') || inp.key('arrowdown') ? 1 : 0) - (inp.key('w') || inp.key('arrowup') ? 1 : 0) + (pad ? pad.ly : 0)
    const mag = Math.min(1, Math.hypot(mx, mz))
    const run = inp.key('shift') || (pad && pad.rt > 0.4)
    S.moving = mag > 0.1
    if ((inp.take(' ') || padPressed(input, pad, 'a')) && S.dive <= 0) S.dive = 0.9
    const c = Math.cos(camYaw.current), s = Math.sin(camYaw.current)
    let vx = (mx * c + mz * s), vz = (-mx * s + mz * c)
    if (S.moving) yaw.current = Math.atan2(-vx, -vz)
    let speed = S.moving ? (run ? 7.5 : 3.2) * M.PLAYER_CLOCK * mag : 0
    if (S.dive > 0) { S.dive -= dt; speed = 7; vx = -Math.sin(yaw.current); vz = -Math.cos(yaw.current) }
    if (speed) { const l = Math.hypot(vx, vz) || 1; pos.current.x += vx / l * speed * dt; pos.current.z += vz / l * speed * dt }
    pos.current.x = THREE.MathUtils.clamp(pos.current.x, -40, 40); pos.current.z = THREE.MathUtils.clamp(pos.current.z, -50, 50)
    const want = S.dive > 0 ? 'ram_shootdodge_front_midair_gun' : S.moving ? (run ? 'ram_run' : 'ram_walk') : 'ram_weapon_idle_gun'
    if (want !== S.clip) { S.clip = want; setClip(want) }
    if (ram.current) { ram.current.position.copy(pos.current); ram.current.rotation.y = yaw.current }
    // ---- camera: the rig's yaw eases toward Ram's
    camYaw.current = M.followYaw(camYaw.current, yaw.current, cam, dt)
    const cy = camYaw.current
    const behind = rig.behind + (S.moving ? M.runLag(cam) : 0)
    camera.position.set(pos.current.x + Math.sin(cy) * behind + Math.cos(cy) * rig.x, rig.height, pos.current.z + Math.cos(cy) * behind - Math.sin(cy) * rig.x)
    camera.rotation.order = 'YXZ'; camera.rotation.set(-rig.pitch * Math.PI / 180, cy, 0)
    if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix() }
    // ---- the world turns on world time
    orbs.current.forEach((o, i) => {
      if (!o) return
      const a = world.current * (0.9 + i * 0.12) + i * 1.3, r = 9 + i * 3
      o.position.set(Math.cos(a) * r, 1.2 + Math.sin(a * 2) * 0.6, Math.sin(a) * r - 6)
    })
    S.acc += dt
    if (S.acc > 0.1) { S.acc = 0; hud({ stamina: sl.stamina / sm.maxStamina, scale: sl.scale, on: sl.on, moving: S.moving }) }
  }
  const warmed = useRef(false)
  useFrame((_, rdt) => {
    // ?demo=1 runs two seconds of play before the first frame, with slow motion on (screenshots)
    if (demo && !warmed.current) { warmed.current = true; slow.current.want = true; for (let i = 0; i < 40; i++) tick(0.05) }
    tick(Math.min(rdt, 0.05))
  })
  return (
    <>
      <ambientLight intensity={0.95} /><directionalLight position={[40, 90, 30]} intensity={0.8} /><hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}><planeGeometry args={[220, 220]} /><meshLambertMaterial color="#5b6a54" /></mesh>
      <GroundGrid size={120} step={4} color="#5d6b5f" />
      {PILLARS.map(([x, z], i) => <mesh key={i} position={[x, 2, z]}><boxGeometry args={[2.2, 4, 2.2]} /><meshLambertMaterial color={i % 2 ? '#7c6f62' : '#6b7787'} /></mesh>)}
      {Array.from({ length: 5 }, (_, i) => <mesh key={i} ref={el => { orbs.current[i] = el }}><sphereGeometry args={[0.45, 14, 10]} /><meshLambertMaterial color="#ff9d3c" emissive="#a14a00" /></mesh>)}
      <group ref={ram}><RamActor clip={clip} rate={() => M.PLAYER_CLOCK} loop rotY={Math.PI} /></group>
    </>
  )
}

export default function WalkMode({ cam, sm }) {
  const wrap = useRef()
  const input = useInput(wrap)
  const bg = useSky()
  const [h, setH] = useState({ stamina: 1, scale: 1, on: false })
  return (
    <div className="pv-in" ref={wrap} tabIndex={0} data-pad-ctx="play" aria-label={t('playground')} style={{ outline: 'none' }}>
      <Canvas linear flat camera={{ fov: 50, near: 0.1, far: 600, position: [0, 3, 6] }} gl={{ antialias: true }} dpr={[1, 1.5]}>
        <color attach="background" args={[bg]} />
        <fog attach="fog" args={[bg, 120, 300]} />
        <Scene cam={cam} sm={sm} input={input} hud={setH} />
      </Canvas>
      <div className="slowmask" style={{ opacity: Math.min(1, (1 - h.scale) * 1.1) }} />
      <div className="hud" style={{ left: 12, top: 12 }}>
        <div className="box">
          <div className="row"><span className="big">×{h.scale < 0.1 ? h.scale.toFixed(2) : h.scale.toFixed(1)}</span><span className="dim">{h.on ? 'slow' : 'normal'}</span></div>
          <div className="bar" style={{ width: 150 }}><i style={{ width: `${h.stamina * 100}%`, background: h.on ? '#5b9bff' : 'var(--accent)' }} /></div>
        </div>
      </div>
    </div>
  )
}
