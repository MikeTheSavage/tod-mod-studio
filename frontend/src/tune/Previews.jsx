// Live 3D previews for the Tune screens: weapons, vehicles, moves and slow motion, camera.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { PreviewCanvas, GameModel, RamActor, Ring, Tag, GroundGrid } from './PreviewKit.jsx'
import { useGameModels, weaponModelPath, vehicleModelPath } from './gameModels.js'
import * as M from './mapping.js'
import { t as tr } from '../i18n.js'

export const BAND_COLOR = ['#5fd38d', '#f2c14e', '#ff7070']
const f1 = v => (Math.round(v * 10) / 10).toString()
const f0 = v => Math.round(v).toString()

// a tiny seeded generator so scatter patterns stay put between renders
function rng(seed) { let s = seed >>> 0 || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296 } }

function Stat({ k, v, u, tip }) { return <span className="pvs" title={tip}><i>{k}</i><b>{v}</b>{u && <em>{u}</em>}</span> }

// ------------------------------------------------------------------ weapons
function SpreadPyramid({ half, length, y, color, opacity = 1 }) {
  const geo = useMemo(() => {
    const r = Math.tan(half * Math.PI / 180) * length
    const o = [0, y, 0], c = [[-r, y - r, -length], [r, y - r, -length], [r, y + r, -length], [-r, y + r, -length]]
    const p = []
    c.forEach((q, i) => { p.push(...o, ...q); const n = c[(i + 1) % 4]; p.push(...q, ...n) })
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return g
  }, [half, length, y])
  return <lineSegments geometry={geo}><lineBasicMaterial color={color} transparent opacity={opacity} /></lineSegments>
}

function Tracers({ w, y, color }) {
  const pool = useRef([])
  const state = useRef({ t: 0, next: 0, flash: 0, rnd: rng(7), i: 0 })
  const N = 36
  const flash = useRef()
  useFrame((_, dt) => {
    const s = state.current
    dt = Math.min(dt, 0.1)
    s.t += dt
    const gap = Math.max(M.shotInterval(w, true), 0.05)
    while (s.t >= s.next) {
      s.next += gap
      const spread = M.spreadAt(w, Math.min(1.6, (s.t % 4)))
      for (let k = 0; k < Math.min(w.pellets, 8); k++) {
        const [a, b] = M.pelletAngles(spread, s.rnd(), s.rnd())
        const m = pool.current[s.i++ % N]
        if (m) { m.userData.v = [Math.tan(a * Math.PI / 180), Math.tan(b * Math.PI / 180)]; m.userData.d = 0; m.visible = true }
      }
      s.flash = 1
    }
    for (const m of pool.current) {
      if (!m || !m.visible) continue
      m.userData.d += w.bulletSpeed * dt
      const d = m.userData.d
      if (d >= w.max) { m.visible = false; continue }
      m.position.set(m.userData.v[0] * d, y + m.userData.v[1] * d, -d)
    }
    s.flash = Math.max(0, s.flash - dt * 12)
    if (flash.current) { flash.current.scale.setScalar(0.2 + s.flash * 0.9); flash.current.visible = s.flash > 0.02 }
  })
  return <>
    {Array.from({ length: N }, (_, i) => <mesh key={i} ref={el => { pool.current[i] = el }} visible={false}><sphereGeometry args={[Math.max(0.12, w.max * 0.007), 8, 6]} /><meshBasicMaterial color={color} /></mesh>)}
    <mesh ref={flash} position={[0, y, -0.4]} visible={false}><sphereGeometry args={[Math.max(0.25, w.max * 0.012), 10, 8]} /><meshBasicMaterial color="#ffd36a" transparent opacity={0.9} /></mesh>
  </>
}

export function WeaponPreview({ d, vals, group }) {
  const w = useMemo(() => M.weaponOf(d, vals, group), [d, vals, group])
  const path = weaponModelPath(group)
  const recs = useGameModels([path])
  const R = Math.max(w.max, 8)
  const fit = Math.min(Math.max(R * 0.1, 1.4), 6)
  const y = fit * 0.55
  if (!w.max) return <div className="pv-empty" />
  return (
    <>
      <div className="pv-in"><PreviewCanvas frameKey={group} pos={[0, R * 1.45, R * 0.8]} target={[0, 0, -R * 0.46]} fov={40} far={R * 40}>
        <GroundGrid size={Math.ceil(R * 2.4)} step={Math.max(1, Math.round(R / 20))} />
        {M.bands(w).map((b, i) => b.to > 0 && <Ring key={i} r={b.to} color={BAND_COLOR[i]} width={Math.max(0.05, R * 0.004)} />)}
        {M.bands(w).map((b, i) => b.to > 0 && <Tag key={i} position={[0, 0.3, -b.to]} tone={'t' + i}>{f0(b.to)} m · {f0(b.damage)}</Tag>)}
        <group position={[0, 0, 0]}>
          <GameModel path={path} rec={recs[path]} fit={fit} rotY={Math.PI} />
          <mesh position={[0, y, 0]} visible={!recs[path] || recs[path].missing}><boxGeometry args={[fit * 0.3, fit * 0.3, fit]} /><meshLambertMaterial color="#9aa3ad" /></mesh>
        </group>
        <SpreadPyramid half={w.spreadMax} length={w.max} y={y} color="#9fb4ff" />
        {w.spreadMax > w.spreadMin + 0.01 && <SpreadPyramid half={w.spreadMin} length={w.max} y={y} color="#ffffff" opacity={0.5} />}
        <Tracers w={w} y={y} color="#fff2b0" />
      </PreviewCanvas></div>
      <div className="pvbar">
        <Stat k="Clip" v={f0(w.clip)} />
        <Stat k="Reload" v={f1(w.reload)} u="s" />
        <Stat k="Rate" v={f0(M.rateOfFire(w))} u="rpm" tip={tr('rounds_per_minute_on_the_real')} />
        <Stat k="Spread" v={f1(w.spreadMin) + (w.spreadMax > w.spreadMin ? '–' + f1(w.spreadMax) : '')} u="°" />
        {w.pellets > 1 && <Stat k="Pellets" v={f0(w.pellets)} />}
        <Stat k="DPS" v={f0(M.dps(w, 0))} tip={tr('close_range_trigger_held')} />
      </div>
    </>
  )
}

// ------------------------------------------------------------------ vehicles
function runProfile(v) {
  // speed over time from a standstill by the force balance; held at the top for a moment
  const out = [], dt = 0.05
  let s = 0
  const vmax = M.topSpeed(v.engine, v.drag, v.rolling)
  for (let t = 0; t < 16; t += dt) {
    out.push(s)
    s += (v.engine - v.drag * s * s - v.rolling * s) / v.mass * dt
    if (s > vmax * 0.995 && t > 1) { for (let k = 0; k < 24; k++) out.push(vmax); break }
  }
  return { speeds: out, dt, vmax }
}

function Road({ clock, speedAt, dir }) {
  const strips = useRef([])
  const off = useRef(0)
  useFrame((_, dt) => {
    off.current = (off.current + speedAt(clock.current) * Math.min(dt, 0.1)) % 6
    strips.current.forEach((m, i) => { if (m) m.position.z = ((i * 6 + off.current) % 60) - 30 })
  })
  return <>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}><planeGeometry args={[9, 90]} /><meshLambertMaterial color="#3a3f47" /></mesh>
    {Array.from({ length: 10 }, (_, i) => <mesh key={i} ref={el => { strips.current[i] = el }} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, 0]}><planeGeometry args={[0.18, 2.6]} /><meshBasicMaterial color="#d9d4c3" /></mesh>)}
  </>
}

function Gauge({ kmh, top, steerGone, slide, max }) {
  const R = 54, cx = 70, cy = 66
  const ang = k => Math.PI * (0.85 + 1.3 * Math.min(1, k / max))
  const pt = (k, r) => [cx + Math.cos(ang(k)) * r, cy + Math.sin(ang(k)) * r]
  const arc = (a, b, r) => { const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r); return `M${x1},${y1} A${r},${r} 0 ${ang(b) - ang(a) > Math.PI ? 1 : 0} 1 ${x2},${y2}` }
  const mark = (k, c, t) => { const [x1, y1] = pt(k, R - 7), [x2, y2] = pt(k, R + 5); return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={c} strokeWidth="2.2"><title>{t}</title></line> }
  const [nx, ny] = pt(kmh, R - 12)
  return (
    <svg className="gauge" viewBox="0 0 140 96" aria-label={tr('speed')}>
      <path d={arc(0, max, R)} fill="none" stroke="var(--line-strong)" strokeWidth="6" strokeLinecap="round" />
      <path d={arc(0, Math.max(0.01, Math.min(kmh, max)), R)} fill="none" stroke="var(--accent)" strokeWidth="6" strokeLinecap="round" />
      {mark(top, 'var(--text)', 'Top speed')}
      {steerGone < max && mark(steerGone, 'var(--warn)', 'Steering gone')}
      {slide < max && mark(slide, 'var(--bad)', 'Slides from')}
      <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--text)" strokeWidth="2" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="4" fill="var(--text)" />
      <text x={cx} y={cy + 24} textAnchor="middle" className="gv">{Math.round(kmh)}</text>
      <text x={cx} y={cy + 34} textAnchor="middle" className="gu">{tr('km_h')}</text>
    </svg>
  )
}

export function VehiclePreview({ d, vals, group }) {
  const typeGroup = /^Vehicle type: /.test(group || '') ? group : 'Vehicle type: Sedan'
  const v = useMemo(() => M.vehicleOf(d, vals, typeGroup), [d, vals, typeGroup])
  const s = useMemo(() => M.vehicleStats(v), [v])
  const prof = useMemo(() => runProfile(v), [v])
  const path = vehicleModelPath(typeGroup)
  const recs = useGameModels([path])
  const clock = useRef(0)
  const speedAt = t => { const i = Math.min(prof.speeds.length - 1, Math.floor(t / prof.dt)); return prof.speeds[Math.max(0, i)] || 0 }
  const [kmh, setKmh] = useState(0)
  useEffect(() => {
    clock.current = 0
    const total = prof.speeds.length * prof.dt + 1.2
    let last = performance.now(), live = true
    const tick = () => {
      if (!live) return
      const now = performance.now()
      clock.current = (clock.current + (now - last) / 1000) % total
      last = now
      setKmh(speedAt(clock.current) * 3.6)
    }
    const id = setInterval(tick, 60)
    return () => { live = false; clearInterval(id) }
  }, [prof])
  const turn = s.minRadius
  const missing = !path || !recs[path] || recs[path].missing
  const max = Math.max(60, Math.ceil(Math.max(s.topKmh, s.steeringGoneKmh * 0.2) / 20) * 20)
  return (
    <>
      <div className="pv-in">
        <PreviewCanvas frameKey={typeGroup} pos={[v.length * 1.5, v.length * 0.7, v.length * 1.6]} target={[0, v.height * 0.25, 0]} fov={36} far={400}>
          <Road clock={clock} speedAt={speedAt} />
          <GameModel path={path} rec={recs[path]} fit={v.length} rotY={0} />
          {missing && <mesh position={[0, v.height * 0.5, 0]}><boxGeometry args={[v.width, v.height, v.length]} /><meshLambertMaterial color="#9aa3ad" /></mesh>}
          <mesh position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]} visible={turn < 40}>
            <ringGeometry args={[turn - 0.05, turn + 0.05, 96]} /><meshBasicMaterial color="#9fb4ff" transparent opacity={0.45} side={THREE.DoubleSide} />
          </mesh>
        </PreviewCanvas>
        <div className="pv-gauge"><Gauge kmh={kmh} top={s.topKmh} steerGone={s.steeringGoneKmh} slide={s.slideFromKmh} max={max} /></div>
      </div>
      <div className="pvbar">
        <Stat k="Top" v={f0(s.topKmh)} u="km/h" />
        <Stat k="0–100" v={s.time0to(100) == null ? '–' : f1(s.time0to(100))} u="s" />
        <Stat k="Brake" v={f0(s.brakeDistance(100))} u="m" tip={tr('braking_distance_from_100_km_h')} />
        <Stat k="Turn" v={f1(s.minRadius)} u="m" tip={tr('tightest_turning_circle')} />
        <Stat k="Slides" v={f0(s.slideFromKmh)} u="km/h" />
      </div>
    </>
  )
}

// ------------------------------------------------------------------ moves and slow motion
const MOVES = [
  { id: 'dive', label: tr('dive'), seq: ['ram_shootdodge_front_jump_gun', 'ram_shootdodge_front_midair_gun', 'ram_shootdodge_front_land_gun'], slow: 'dive' },
  { id: 'wall', label: tr('wall_bounce'), seq: ['ram_wallvault_left_gun'], slow: 'wall' },
  { id: 'tornado', label: tr('tornado'), seq: ['ram_locomove'], fixed: { scale: 0.01, ramp: 0.3, hold: 2.5 } },
  { id: 'run', label: tr('run'), seq: ['ram_run'] },
]

function Timeline({ curve, total, now, scale }) {
  const W = 300, H = 56, pad = 4
  const X = t => pad + (t / total) * (W - 2 * pad), Y = k => H - 4 - k * (H - 12)
  const pts = []
  for (let i = 0; i <= 120; i++) { const t = total * i / 120; pts.push(`${X(t)},${Y(curve(t))}`) }
  return (
    <div className="tlwrap">
      <svg className="timeline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label={tr('time_scale')}>
        <line x1={pad} x2={W - pad} y1={Y(1)} y2={Y(1)} stroke="var(--line-strong)" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
        <polyline points={pts.join(' ')} fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
        <line x1={X(now)} x2={X(now)} y1={2} y2={H - 2} stroke="var(--sel)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="tlx"><span>0 s</span><span>×{scale < 0.1 ? scale.toFixed(2) : String(Math.round(scale * 100) / 100)}</span><span>{f1(total)}{' '}{tr('s')}</span></div>
    </div>
  )
}

export function MovesPreview({ d, vals }) {
  const p = useMemo(() => M.slowmoOf(d, vals), [d, vals])
  const [mv, setMv] = useState('dive')
  const move = MOVES.find(m => m.id === mv)
  const scale = move.slow ? p[move.slow] : move.fixed ? move.fixed.scale : 1
  const sum = M.slowmoSummary(p, scale)
  const real = move.slow ? sum.real : move.fixed ? move.fixed.hold : 3
  const total = real + p.rampOut
  const curve = t => move.slow ? M.timeScaleAt(t, p, scale, real)
    : move.fixed ? (t < move.fixed.ramp ? 1 + (scale - 1) * t / move.fixed.ramp : t <= real ? scale : 1) : 1
  const clock = useRef(0)
  const [now, setNow] = useState(0)
  const [idx, setIdx] = useState(0)
  useEffect(() => { clock.current = 0; setIdx(0) }, [mv, real])
  useEffect(() => {
    let last = performance.now()
    const id = setInterval(() => {
      const t = performance.now()
      clock.current = (clock.current + (t - last) / 1000) % (total + 0.8)
      last = t
      setNow(Math.min(clock.current, total))
    }, 60)
    return () => clearInterval(id)
  }, [total])
  const clip = move.seq[Math.min(idx, move.seq.length - 1)]
  // the tornado plays its clip against the slow world time, so it looks normal
  const rate = () => (move.fixed ? 1 : curve(Math.min(clock.current, total)))
  const advance = useRef(0)
  const onTime = (t, dur) => {
    if (move.seq.length > 1 && t >= dur - 0.03 && performance.now() - advance.current > 200) {
      advance.current = performance.now()
      setIdx(i => (i + 1) % move.seq.length)
    }
  }
  return (
    <>
      <div className="pvchips">{MOVES.map(m => <button key={m.id} className={'chip' + (m.id === mv ? ' on' : '')} onClick={() => setMv(m.id)}>{m.label}</button>)}</div>
      <div className="pv-in"><PreviewCanvas frameKey={mv} pos={[3, 1.6, -4.4]} target={[0, 0.9, 0]} fov={46} far={200}>
        <GroundGrid size={16} step={1} />
        <RamActor clip={clip} rate={rate} loop={move.seq.length === 1} onTime={onTime} restart={mv + idx} />
      </PreviewCanvas></div>
      <div className="pvtl"><Timeline curve={curve} total={total} now={now} scale={scale} /></div>
      <div className="pvbar">
        <Stat k="Real" v={f1(real)} u="s" tip={tr('how_long_it_lasts_on_the')} />
        {move.slow && <Stat k="Game" v={f1(sum.game)} u="s" tip={tr('game_time_that_passes')} />}
        {move.slow && <Stat k="Recharge" v={f1(sum.recharge)} u="s" tip={tr('stamina_back_to_full_standing')} />}
        <Stat k="Speed" v={'×' + (scale < 0.1 ? scale.toFixed(2) : String(Math.round(scale * 1000) / 1000))} />
      </div>
    </>
  )
}

// ------------------------------------------------------------------ camera
function Rig({ pose, fov, aspect, groupRef }) {
  const geo = useMemo(() => {
    const dist = pose.behind + 4
    const h = Math.tan(fov * Math.PI / 360) * dist, wd = h * aspect
    const c = [[-wd, -h], [wd, -h], [wd, h], [-wd, h]].map(([x, y]) => [x, y, -dist])
    const p = []
    c.forEach((q, i) => { p.push(0, 0, 0, ...q); const n = c[(i + 1) % 4]; p.push(...q, ...n) })
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return g
  }, [pose.behind, fov, aspect])
  return (
    <group ref={groupRef} position={[pose.x, pose.height, pose.behind]} rotation={[-pose.pitch * Math.PI / 180, 0, 0]}>
      <lineSegments geometry={geo}><lineBasicMaterial color="#ffd36a" transparent opacity={0.7} /></lineSegments>
      <mesh><boxGeometry args={[0.32, 0.2, 0.34]} /><meshBasicMaterial color="#f2a541" /></mesh>
      <mesh position={[0, 0, -0.26]}><cylinderGeometry args={[0.09, 0.12, 0.2, 12]} /><meshBasicMaterial color="#f2a541" /></mesh>
    </group>
  )
}

function PiP({ pose, fov, aspect, w, h, hide }) {
  const cam = useMemo(() => new THREE.PerspectiveCamera(50, 1.78, 0.05, 400), [])
  useFrame(({ gl, scene, camera, size }) => {
    cam.fov = fov; cam.aspect = aspect
    cam.position.set(pose.x, pose.height, pose.behind)
    cam.rotation.set(-pose.pitch * Math.PI / 180, 0, 0)
    cam.updateProjectionMatrix()
    gl.setScissorTest(false); gl.setViewport(0, 0, size.width, size.height)
    gl.render(scene, camera)
    const x = size.width - w - 10, y = 10
    gl.setScissorTest(true); gl.setViewport(x, y, w, h); gl.setScissor(x, y, w, h)
    gl.clear(true, true, true)
    if (hide.current) hide.current.visible = false
    gl.render(scene, cam)
    if (hide.current) hide.current.visible = true
    gl.setScissorTest(false); gl.setViewport(0, 0, size.width, size.height)
  }, 1)
  return null
}

export function CameraPreview({ d, vals }) {
  const c = useMemo(() => M.cameraOf(d, vals), [d, vals])
  const pose = M.cameraPose(c)
  const aspect = 16 / 9
  const fov = M.fovDeg(aspect)
  const hide = useRef()
  const W = 220, H = Math.round(W / aspect)
  // a set to look at: a few posts down the street
  const posts = useMemo(() => [[-3, 6], [3, 11], [-3, 16], [3, 21], [-3, 26]], [])
  return (
    <>
      <div className="pv-in">
        <PreviewCanvas frameKey="cam" pos={[11, 3.6, 1.7]} target={[0, 1.2, 1.5]} fov={52} far={400}>
          <GroundGrid size={60} step={1} />
          <RamActor clip="ram_weapon_idle_gun" rotY={Math.PI} />
          <Rig pose={pose} fov={fov.vertical} aspect={aspect} groupRef={hide} />
          {posts.map(([x, z], i) => <mesh key={i} position={[x, 1.5, -z]}><boxGeometry args={[0.5, 3, 0.5]} /><meshLambertMaterial color={i % 2 ? '#6d7f94' : '#8a7060'} /></mesh>)}
          <Tag position={[pose.x, pose.height + 0.5, pose.behind]}>{f1(pose.behind)} m · {f1(pose.height)}{' '}{tr('m')}</Tag>
          <PiP pose={pose} fov={fov.vertical} aspect={aspect} w={W} h={H} hide={hide} />
        </PreviewCanvas>
        <div className="pv-pip" style={{ width: W, height: H }} />
      </div>
      <div className="pvbar">
        <Stat k="Back" v={f1(pose.behind)} u="m" />
        <Stat k="Up" v={f1(pose.height)} u="m" tip={tr('height_above_his_feet')} />
        <Stat k="Tilt" v={f0(pose.pitch)} u="°" />
        <Stat k="View" v={f0(fov.horizontal)} u="°" tip={tr('field_of_view_across_a_16')} />
        <Stat k="Lag" v={f1(M.runLag(c))} u="m" tip={tr('how_far_the_camera_sags_behind')} />
      </div>
    </>
  )
}
