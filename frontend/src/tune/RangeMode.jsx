// Playground: the weapon range. Targets at set distances; fire and see the damage of each band, the fire rate, clip and
// reload, and pellets. The damage rules are the game's (mapping.js); the flight and the hit boxes are simplified.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { RamActor, Ring, GroundGrid, useSky } from './PreviewKit.jsx'
import { useInput, readPad, padPressed } from './input.js'
import * as M from './mapping.js'
import { BAND_COLOR } from './Previews.jsx'
import { t as tr } from '../i18n.js'

export const RAM_YAW = 0                      // the player model faces -z at yaw 0
const DISTANCES = [4, 8, 12, 17, 22, 28, 36, 45, 56]
const CHEST = 1.2

function newSim(w) {
  return { w, clip: w.clip, reload: 0, lastShot: -9, wasDown: false, held: 0, spread: w.spreadMin, shots: 0, hits: 0, dmg: 0, kills: 0,
    log: [], last: null, flash: 0, rnd: Math.random }
}
const newTargets = () => DISTANCES.map((d, i) => ({ id: i, x: ((i % 3) - 1) * 3.4, z: -d, hp: 100, max: 100, down: 0 }))

function Dummy({ t, w, ram }) {
  const g = useRef(), bar = useRef(), body = useRef()
  useFrame(({ camera }) => {
    const d = Math.hypot(t.x - ram.pos.x, t.z - ram.pos.z)
    const bi = M.bandIndex(w, d)
    body.current.material.color.set(bi < 0 ? '#7d8794' : BAND_COLOR[bi])
    bar.current.scale.x = Math.max(0.001, t.hp / t.max)
    bar.current.position.x = -(1 - t.hp / t.max) * 0.45
    g.current.rotation.x = t.down > 0 ? -Math.min(1.4, (1.5 - t.down) * 3) : 0
    bar.current.parent.quaternion.copy(camera.quaternion)
  })
  return (
    <group position={[t.x, 0, t.z]}>
      <group ref={g}>
        <mesh ref={body} position={[0, 0.9, 0]}><capsuleGeometry args={[0.32, 1.1, 4, 10]} /><meshLambertMaterial color="#7d8794" /></mesh>
        <mesh position={[0, 1.72, 0]}><sphereGeometry args={[0.17, 12, 10]} /><meshLambertMaterial color="#d9c3a5" /></mesh>
      </group>
      <group position={[0, 2.25, 0]}>
        <mesh position={[0, 0, -0.001]}><planeGeometry args={[0.9, 0.09]} /><meshBasicMaterial color="#1b1f25" /></mesh>
        <mesh ref={bar}><planeGeometry args={[0.9, 0.09]} /><meshBasicMaterial color="#4cd47d" /></mesh>
      </group>
    </group>
  )
}

function Labels({ targets, w, ram }) {
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(x => x + 1), 250); return () => clearInterval(id) }, [])
  return targets.map(t => {
    const d = Math.hypot(t.x - ram.pos.x, t.z - ram.pos.z)
    const bi = M.bandIndex(w, d)
    return <Html key={t.id} position={[t.x, 2.7, t.z]} center style={{ pointerEvents: 'none' }}>
      <div className="tag dist">{Math.round(d)} m · <b style={{ color: bi < 0 ? '#8491a1' : BAND_COLOR[bi] }}>{Math.round(M.damageAt(w, d))}</b></div>
    </Html>
  })
}

function Scene({ w, sim, targets, ram, input, cam, onPop, aimOut, hud }) {
  const { camera, size } = useThree()
  const bullets = useRef([]), pool = useRef([])
  const camYaw = useRef(0), ramYaw = useRef(RAM_YAW)
  const ray = useMemo(() => new THREE.Raycaster(), [])
  const plane = useMemo(() => new THREE.Plane(new THREE.Vector3(0, 1, 0), -CHEST), [])
  const hit = useMemo(() => new THREE.Vector3(), [])
  const acc = useRef(0)
  const aim = useRef(new THREE.Vector3(0, CHEST, -20))
  const rig = useMemo(() => M.cameraPose(cam), [cam])
  const fov = useMemo(() => M.fovDeg(size.width / Math.max(1, size.height)).vertical, [size.width, size.height])
  const ramGroup = useRef()
  const N = 128
  const now = useRef(0)
  const demo = useMemo(() => new URLSearchParams(location.search).get('demo'), [])

  const tick = dt => {
    now.current += dt
    const t = now.current
    const inp = input.current
    const pad = readPad()
    // ---- walking (camera relative)
    let mx = (inp.key('d') ? 1 : 0) - (inp.key('a') ? 1 : 0) + (pad ? pad.lx : 0)
    let mz = (inp.key('s') ? 1 : 0) - (inp.key('w') ? 1 : 0) + (pad ? pad.ly : 0)
    const sp = (inp.key('shift') ? 8 : 5) * M.PLAYER_CLOCK
    const c = Math.cos(camYaw.current), s = Math.sin(camYaw.current)
    ram.pos.x += (mx * c + mz * s) * sp * dt
    ram.pos.z += (-mx * s + mz * c) * sp * dt
    ram.pos.x = THREE.MathUtils.clamp(ram.pos.x, -30, 30); ram.pos.z = THREE.MathUtils.clamp(ram.pos.z, -20, 40)
    // ---- aim
    let nx = inp.nx, ny = inp.ny
    if (pad && (pad.rx || pad.ry)) { inp.nx = nx = THREE.MathUtils.clamp(nx + pad.rx * dt * 1.6, -1, 1); inp.ny = ny = THREE.MathUtils.clamp(ny - pad.ry * dt * 1.6, -1, 1) }
    ray.setFromCamera({ x: nx, y: ny }, camera)
    if (demo != null && targets[+demo]) aim.current.set(targets[+demo].x, CHEST, targets[+demo].z)
    else if (ray.ray.intersectPlane(plane, hit) && hit.distanceTo(camera.position) < 400) aim.current.copy(hit)
    else aim.current.copy(ray.ray.origin).addScaledVector(ray.ray.direction, 60)
    const ay = Math.atan2(-(aim.current.x - ram.pos.x), -(aim.current.z - ram.pos.z))
    let dy = ay - ramYaw.current; dy = Math.atan2(Math.sin(dy), Math.cos(dy))
    ramYaw.current += dy * Math.min(1, 14 * dt)
    camYaw.current = M.followYaw(camYaw.current, ramYaw.current, cam, dt)
    if (ramGroup.current) { ramGroup.current.position.set(ram.pos.x, 0, ram.pos.z); ramGroup.current.rotation.y = ramYaw.current }
    // ---- camera rig (the tuned one)
    const cy = camYaw.current
    const behind = rig.behind + (Math.hypot(mx, mz) > 0.1 ? M.runLag(cam) : 0)
    camera.position.set(ram.pos.x + Math.sin(cy) * behind + Math.cos(cy) * rig.x, rig.height, ram.pos.z + Math.cos(cy) * behind - Math.sin(cy) * rig.x)
    camera.rotation.order = 'YXZ'; camera.rotation.set(-rig.pitch * Math.PI / 180, cy, 0)
    if (camera.fov !== fov) { camera.fov = fov; camera.updateProjectionMatrix() }
    // ---- trigger
    const down = inp.down || inp.key(' ') || (demo != null && t > 1.2) || (pad && (pad.rt > 0.4 || pad.a))
    if (inp.take('r') || padPressed(input, pad, 'x')) startReload(sim)
    if (sim.reload > 0) { sim.reload -= dt; if (sim.reload <= 0) { sim.reload = 0; sim.clip = w.clip } }
    const muzzle = new THREE.Vector3(ram.pos.x - Math.sin(ramYaw.current) * 0.6, 1.35, ram.pos.z - Math.cos(ramYaw.current) * 0.6)
    if (down) {
      if (!sim.wasDown) { sim.held = 0; sim.spread = w.spreadMin }
      else sim.held += dt
      sim.spread = M.spreadAt(w, sim.held)
      const gap = t - sim.lastShot
      const need = M.shotInterval(w, sim.wasDown)
      if (sim.reload <= 0 && gap >= need - 1e-6) {
        if (sim.clip > 0) { fire(); sim.lastShot = t } else startReload(sim)
      }
    } else sim.spread = M.spreadAt(w, 0)
    sim.wasDown = !!down
    function fire() {
      const toAim = aim.current.clone().sub(muzzle)
      const dist = toAim.length()
      const base = toAim.clone().normalize()
      const dmg = M.damageAt(w, dist), band = M.bandIndex(w, dist)
      const right = new THREE.Vector3().crossVectors(base, new THREE.Vector3(0, 1, 0)).normalize()
      const up = new THREE.Vector3().crossVectors(right, base).normalize()
      for (let k = 0; k < w.pellets; k++) {
        const [a, b] = M.pelletAngles(sim.spread, Math.random(), Math.random())
        const dir = base.clone().applyAxisAngle(up, a * Math.PI / 180).applyAxisAngle(right, b * Math.PI / 180)
        bullets.current.push({ p: muzzle.clone(), d: dir, left: w.max, dmg, band })
      }
      if (bullets.current.length > N) bullets.current.splice(0, bullets.current.length - N)
      sim.clip -= 1; sim.shots += 1; sim.flash = 1
      sim.last = { dist, dmg, band }
      sim.log.push({ t, shots: 1 })
    }
    // ---- bullets
    const list = bullets.current
    for (let i = list.length - 1; i >= 0; i--) {
      const b = list[i]
      const step = Math.min(b.left, w.bulletSpeed * dt)
      const a0 = b.p.clone(); b.p.addScaledVector(b.d, step); b.left -= step
      let stopped = b.left <= 0
      for (const tg of targets) {
        if (tg.down > 0) continue
        // closest approach of this move to the target's vertical axis, in the ground plane
        const abx = b.p.x - a0.x, abz = b.p.z - a0.z, L = abx * abx + abz * abz
        const u = L > 1e-9 ? THREE.MathUtils.clamp(((tg.x - a0.x) * abx + (tg.z - a0.z) * abz) / L, 0, 1) : 0
        const px = a0.x + abx * u, pz = a0.z + abz * u, py = a0.y + (b.p.y - a0.y) * u
        if (Math.hypot(px - tg.x, pz - tg.z) < 0.36 && py > 0 && py < 1.9) {
          const head = py > 1.55
          const dmg = b.dmg
          tg.hp = Math.max(0, tg.hp - dmg); sim.hits += 1; sim.dmg += dmg
          sim.log.push({ t, dmg })
          onPop({ pos: [px, py, pz], text: String(Math.round(dmg)) + (head ? '!' : ''), tone: b.band < 0 ? 3 : b.band })
          if (tg.hp <= 0) { tg.down = 1.5; sim.kills += 1 }
          stopped = true
          break
        }
      }
      if (stopped) list.splice(i, 1)
    }
    for (const tg of targets) if (tg.down > 0) { tg.down -= dt; if (tg.down <= 0) { tg.down = 0; tg.hp = tg.max } }
    // ---- bullet meshes
    for (let i = 0; i < N; i++) {
      const m = pool.current[i]; if (!m) continue
      const b = list[i]
      m.visible = !!b
      if (b) m.position.copy(b.p)
    }
    sim.flash = Math.max(0, sim.flash - dt * 10)
    // ---- hud numbers (a few times a second)
    acc.current += dt
    if (acc.current > 0.1) {
      acc.current = 0
      sim.log = sim.log.filter(e => t - e.t < 3)
      const win = Math.min(3, Math.max(0.5, t - (sim.log[0]?.t ?? t)))
      const shots = sim.log.filter(e => e.shots).length, dsum = sim.log.reduce((a, e) => a + (e.dmg || 0), 0)
      hud({ clip: sim.clip, size: w.clip, reload: sim.reload > 0 ? 1 - sim.reload / Math.max(w.reload, 0.01) : null, spread: sim.spread,
        last: sim.last, shots: sim.shots, hits: sim.hits, kills: sim.kills, rpm: shots ? (shots / win) * 60 : 0, dps: dsum / win })
    }
    aimOut.current = { aim: aim.current, spread: sim.spread, vfov: fov }
  }
  const warmed = useRef(false)
  useFrame((_, rdt) => {
    // ?demo=<target> aims at that target and fires for a few seconds before the first frame (screenshots)
    if (demo != null && !warmed.current) { warmed.current = true; for (let i = 0; i < 70; i++) tick(0.05) }
    tick(Math.min(rdt, 0.05))
  })
  function startReload(sm) { if (sm.reload <= 0 && sm.clip < w.clip) sm.reload = Math.max(0.05, w.reload) }

  return (
    <>
      <ambientLight intensity={0.95} /><directionalLight position={[40, 90, 30]} intensity={0.8} /><hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, -20]}><planeGeometry args={[140, 160]} /><meshLambertMaterial color="#5b6a54" /></mesh>
      <GroundGrid size={140} step={4} color="#566453" />
      <group position={[0, 0, 0]}>
        {M.bands(w).map((b, i) => b.to > 0 && <group key={i} position={[0, 0, 0]}><Ring r={b.to} color={BAND_COLOR[i]} width={0.12} opacity={0.7} /></group>)}
      </group>
      <group ref={ramGroup}><RamActor clip="ram_weapon_idle_gun" rate={() => 1} rotY={Math.PI} /></group>
      {targets.map(t => <Dummy key={t.id} t={t} w={w} ram={ram} />)}
      <Labels targets={targets} w={w} ram={ram} />
      {Array.from({ length: N }, (_, i) => <mesh key={i} ref={el => { pool.current[i] = el }} visible={false}><sphereGeometry args={[0.06, 6, 5]} /><meshBasicMaterial color="#fff2b0" /></mesh>)}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}><ringGeometry args={[0.04, 0.09, 12]} /><meshBasicMaterial color="#fff" /></mesh>
    </>
  )
}

function Pops({ pops }) {
  return pops.map(p => <Html key={p.id} position={p.pos} center style={{ pointerEvents: 'none' }}><div className={'tag dmg t' + p.tone} style={{ animation: 'pgrise 0.9s ease-out forwards' }}>{p.text}</div></Html>)
}

export default function RangeMode({ w, name, cam }) {
  const wrap = useRef()
  const input = useInput(wrap)
  const bg = useSky()
  const wkey = JSON.stringify(w)
  const sim = useMemo(() => newSim(w), [wkey])
  const targets = useMemo(() => newTargets(), [wkey])
  const ram = useMemo(() => ({ pos: new THREE.Vector3(0, 0, 0) }), [])
  const [hud, setHud] = useState(null)
  const [pops, setPops] = useState([])
  const aimOut = useRef(null)
  const cross = useRef()
  const seq = useRef(0)
  const onPop = p => {
    const id = ++seq.current
    setPops(a => [...a.slice(-18), { ...p, id }])
    if (!new URLSearchParams(location.search).get('demo')) setTimeout(() => setPops(a => a.filter(x => x.id !== id)), 900)
  }
  useEffect(() => {
    let raf
    const loop = () => {
      const c = cross.current, a = aimOut.current, el = wrap.current
      if (c && el) {
        const r = el.getBoundingClientRect()
        const px = r.height / 2 * Math.tan((a?.spread || 0) * Math.PI / 180) / Math.tan(((a?.vfov || 50) * Math.PI / 180) / 2)
        c.style.transform = `translate(${(input.current.nx * 0.5 + 0.5) * r.width}px, ${(0.5 - input.current.ny * 0.5) * r.height}px)`
        c.style.setProperty('--g', Math.max(5, px) + 'px')
        c.style.opacity = input.current.inside ? 1 : 0
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])
  const bands = M.bands(w)
  const last = hud?.last
  return (
    <div className="pv-in" ref={wrap} tabIndex={0} data-pad-ctx="play" aria-label={tr('playground')} style={{ cursor: 'none', outline: 'none' }}>
      <Canvas linear flat camera={{ fov: 50, near: 0.1, far: 600, position: [0, 3, 6] }} gl={{ antialias: true }} dpr={[1, 1.5]}>
        <color attach="background" args={[bg]} />
        <fog attach="fog" args={[bg, 150, 320]} />
        <Scene w={w} sim={sim} targets={targets} ram={ram} input={input} cam={cam} onPop={onPop} aimOut={aimOut} hud={setHud} />
        <Pops pops={pops} />
      </Canvas>
      <div className="cross" ref={cross} style={{ '--g': '8px' }}>
        {[[0, -1], [0, 1], [-1, 0], [1, 0]].map(([x, y], i) => <i key={i} style={{ width: x ? 8 : 2, height: y ? 8 : 2, left: x ? `calc(${x} * var(--g) + ${x > 0 ? 0 : -8}px)` : -1, top: y ? `calc(${y} * var(--g) + ${y > 0 ? 0 : -8}px)` : -1 }} />)}
      </div>
      <div className="hud" style={{ left: 12, top: 12 }}>
        <div className="box">
          <div className="row"><span className="big">{hud ? hud.clip : w.clip}</span><span className="dim">/ {w.clip}</span><span style={{ fontWeight: 600 }}>{name}</span></div>
          <div className="bar" style={{ opacity: hud?.reload != null ? 1 : 0.25 }}><i style={{ width: `${(hud?.reload ?? 0) * 100}%` }} /></div>
          <div className="bandrow">
            {bands.map((b, i) => <span key={i} className={'band' + (last && last.band === i ? ' on' : '')} title={`${M.BAND_NAMES[i]} to ${Math.round(b.to)} m`}>
              <span className="dot" style={{ background: BAND_COLOR[i] }} />{Math.round(b.to)} m · {Math.round(b.damage)}{w.pellets > 1 ? ` ×${w.pellets}` : ''}</span>)}
          </div>
        </div>
      </div>
      <div className="hud" style={{ right: 12, top: 12 }}>
        <div className="box" style={{ textAlign: 'right' }}>
          <div className="row" style={{ justifyContent: 'flex-end' }}><span className="dim">{tr('rate')}</span><b>{Math.round(hud?.rpm || 0)}</b><span className="dim">{tr('rpm')}</span></div>
          <div className="row" style={{ justifyContent: 'flex-end' }}><span className="dim">{tr('dps')}</span><b>{Math.round(hud?.dps || 0)}</b></div>
          <div className="row" style={{ justifyContent: 'flex-end' }}><span className="dim">{tr('hits')}</span><b>{hud?.hits || 0}</b><span className="dim">/ {hud?.shots || 0}</span></div>
          <div className="row" style={{ justifyContent: 'flex-end' }}><span className="dim">{tr('down')}</span><b>{hud?.kills || 0}</b></div>
        </div>
      </div>
      {last && <div className="hud" style={{ left: '50%', bottom: 16, transform: 'translateX(-50%)' }}>
        <div className="box row"><span className="dim">{tr('aim')}</span><b>{last.dist.toFixed(1)}{' '}{tr('m')}</b><span className="dim">→</span><b style={{ color: last.band < 0 ? '#8491a1' : BAND_COLOR[last.band] }}>{Math.round(last.dmg)}{w.pellets > 1 ? ` ×${w.pellets}` : ''}</b></div>
      </div>}
    </div>
  )
}

