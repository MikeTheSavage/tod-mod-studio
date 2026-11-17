// The shared 3D view. Every screen that shows a map (Level, New maps, Mission templates, Sections, Test saves, Mission
// logic) draws it through this one component: the level with real models, overlays (boxes, points, paths, zones), a
// ghost for click-to-place on the ground, tools as plugins, and a 3D / Top switch (Top is an orthographic view from
// above, north up, with the same picking).
import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, OrthographicCamera, PerspectiveCamera } from '@react-three/drei'
import * as THREE from 'three'
import { toView, fromView } from './coords.js'
import { LevelContent } from './Scene.jsx'
import PlacementGhost from './Ghost.jsx'
import Overlays from './Overlays.jsx'
import { RulerLayer, FigureLayer, ScatterLayer, NotePins } from './ViewTools.jsx'
import { Seg } from './ui.jsx'
import { padState, getCfg, getMode, rumble, setUi, usePad } from './pad/padstore.js'
import { registerView } from './pad/PadHost.jsx'
import { curve, flyStep, lookStep } from './pad/padlogic.js'
import { t as tr } from './i18n.js'

const TAN = Math.tan(55 * Math.PI / 360)
const EMPTY = new Set()
const NO_LAYERS = {}
const cssVar = (name, dflt) => { try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || dflt } catch { return dflt } }

// ------------------------------------------------------------------ the scene queries every tool uses
const solid = h => h.object.visible && h.object.isMesh && !h.object.material?.transparent && !h.object.userData.ghost && !h.object.userData.overlay
// the meshes a pick can land on (never overlays, ghosts, fat lines or see-through volumes), found once per query
function solids(root) {
  const out = []
  const walk = o => {
    if (!o.visible || o.userData?.overlay || o.userData?.ghost) return
    if (o.isMesh && !o.isLineSegments2 && !o.material?.transparent) out.push(o)
    for (const c of o.children) walk(c)
  }
  walk(root)
  return out
}
function inIds(o, ids) {
  for (let p = o; p; p = p.parent) if (p.userData?.eid && ids.has(p.userData.eid)) return true
  return false
}

function ApiBridge({ api, registryRef, planeY }) {
  const { camera, scene, gl, controls, size } = useThree()
  const rc = useMemo(() => new THREE.Raycaster(), [])
  const lastY = useRef(0)
  Object.assign(api.current, {
    camera, scene, gl, controls, size,
    registry: registryRef.current,
    // the view as a small JPEG (base64, no prefix) for the mod page: render, then copy at once while the buffer is valid
    capture(width = 960) {
      gl.render(scene, camera)
      const src = gl.domElement
      const c = document.createElement('canvas')
      c.width = width; c.height = Math.round(width * src.height / src.width)
      c.getContext('2d').drawImage(src, 0, 0, c.width, c.height)
      return c.toDataURL('image/jpeg', 0.82).split(',')[1]
    },
    // heights of what is under (x, z) (game coordinates), highest first; `ignore` = ids of objects to skip
    castDown(x, z, fromY = 4000, ignore) {
      rc.set(new THREE.Vector3(x, fromY, -z), new THREE.Vector3(0, -1, 0)); rc.near = 0; rc.far = 9000
      return rc.intersectObjects(solids(scene), false).filter(h => !(ignore && inIds(h.object, ignore))).map(h => h.point.y)
    },
    // a mouse position -> a point on the level: { pos (game), geometry: true when a mesh was hit }
    pointerHit(cx, cy) {
      const r = gl.domElement.getBoundingClientRect()
      rc.setFromCamera(new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), camera)
      rc.near = 0; rc.far = 9000
      const hits = rc.intersectObjects(solids(scene), false)
      if (hits.length && (camera.isOrthographicCamera || hits[0].distance < 2500)) { lastY.current = hits[0].point.y; return { pos: fromView(hits[0].point), geometry: true } }
      const t = new THREE.Vector3()
      if (rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -(planeY ?? lastY.current)), t)) return { pos: fromView(t), geometry: false }
      return null
    },
    // game position -> pixels inside the view (null when behind the camera)
    project(p) {
      const v = toView(p).project(camera)
      if (v.z < -1 || v.z > 1) return null
      return { x: (v.x * 0.5 + 0.5) * size.width, y: (-v.y * 0.5 + 0.5) * size.height }
    },
    centerPoint() {
      rc.setFromCamera(new THREE.Vector2(0, 0), camera)
      const hits = rc.intersectObjects(solids(scene), false)
      if (hits.length && hits[0].distance < 400) return fromView(hits[0].point)
      return controls ? fromView(controls.target) : [0, 0, 0]
    },
    // what the screen-centre reticle points at: the id of the object under it (the controller's A button)
    pickCenter() {
      rc.setFromCamera(new THREE.Vector2(0, 0), camera); rc.near = 0; rc.far = 9000
      const all = []
      scene.traverse(o => { if (o.isMesh && o.visible && !o.isLineSegments2 && !o.userData?.overlay && !o.userData?.ghost) all.push(o) })
      for (const h of rc.intersectObjects(all, false)) {
        for (let p = h.object; p; p = p.parent) if (p.userData?.eid) return p.userData.eid
      }
      return null
    },
    cameraState() {
      return controls ? { eye: fromView(camera.position), target: fromView(controls.target) } : null
    },
  })
  return null
}

// ------------------------------------------------------------------ camera: 3D perspective or Top (orthographic, north up)
function ModeCamera({ mode, tracker }) {
  const { camera, controls, size } = useThree()
  const applied = useRef(null)
  useFrame(() => {
    if (!controls || !camera || controls.object !== camera || applied.current !== controls) return
    const t = tracker.current
    t.dist = camera.isPerspectiveCamera ? camera.position.distanceTo(controls.target) : size.height / (2 * camera.zoom * TAN)
    t.target.copy(controls.target)
  })
  useEffect(() => {
    if (!controls || controls.object !== camera || applied.current === controls) return
    applied.current = controls
    const t = tracker.current
    if (camera.isOrthographicCamera) {
      camera.zoom = size.height / (2 * Math.max(t.dist, 2) * TAN)
      camera.position.set(t.target.x, t.target.y + 3000, t.target.z)
      controls.target.copy(t.target)
      camera.near = 1; camera.far = 8000
    } else {
      camera.position.copy(t.target).add(new THREE.Vector3(1, 0.8, 1).normalize().multiplyScalar(Math.max(t.dist, 2)))
      controls.target.copy(t.target)
      camera.near = 0.2; camera.far = 8000
    }
    camera.updateProjectionMatrix(); controls.update()
  }, [camera, controls, mode])
  return null
}

function CameraRig({ focus, tracker }) {
  const { camera, controls, size } = useThree()
  const done = useRef(null)
  useEffect(() => {
    if (!focus || !controls || done.current === focus) return
    done.current = focus
    const ortho = camera.isOrthographicCamera
    if (focus.eye && focus.target) {
      const t = toView(focus.target)
      controls.target.copy(t)
      if (ortho) { camera.position.set(t.x, t.y + 3000, t.z); camera.zoom = size.height / (2 * Math.max(1, toView(focus.eye).distanceTo(t)) * TAN) } else camera.position.copy(toView(focus.eye))
    } else if (focus.bounds) {
      const [x0, z0, x1, z1] = focus.bounds
      const t = toView([(x0 + x1) / 2, focus.y ?? 0, (z0 + z1) / 2])
      const w = Math.max(10, Math.abs(x1 - x0)), l = Math.max(10, Math.abs(z1 - z0))
      controls.target.copy(t)
      if (ortho) { camera.position.set(t.x, t.y + 3000, t.z); camera.zoom = Math.min(size.width / w, size.height / l) * 0.82 }
      else camera.position.copy(t).add(new THREE.Vector3(0.7, 0.9, 0.9).normalize().multiplyScalar(Math.max(w, l) * 0.95))
    } else if (focus.pos) {
      const t = toView(focus.pos)
      const d = focus.dist || 25
      if (ortho) {
        controls.target.copy(t); camera.position.set(t.x, t.y + 3000, t.z); camera.zoom = size.height / (2 * d * TAN)
      } else {
        const dir = new THREE.Vector3().subVectors(camera.position, controls.target)
        if (dir.lengthSq() < 1e-6 || focus.reset) dir.set(1, d < 15 ? 0.45 : 0.8, 1)
        dir.normalize().multiplyScalar(d)
        controls.target.copy(t)
        camera.position.copy(t).add(dir)
      }
    }
    camera.updateProjectionMatrix()
    controls.update()
    // the camera type may be swapped right after this (the first mount): hand the new spot over
    tracker.current.target.copy(controls.target)
    tracker.current.dist = ortho ? size.height / (2 * camera.zoom * TAN) : camera.position.distanceTo(controls.target)
  }, [focus, controls, camera])
  return null
}

// WASD / QE flying (also pans the Top view), while the view has the mouse
function FlyKeys({ enabled }) {
  const { camera, controls } = useThree()
  const keys = useRef(new Set())
  useEffect(() => {
    const dn = e => { if (!enabled.current || ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.ctrlKey || e.metaKey) return; keys.current.add(e.key.toLowerCase()) }
    const up = e => keys.current.delete(e.key.toLowerCase())
    const blur = () => keys.current.clear()
    window.addEventListener('keydown', dn); window.addEventListener('keyup', up); window.addEventListener('blur', blur)
    return () => { window.removeEventListener('keydown', dn); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur) }
  }, [])
  useFrame((_, dt) => {
    const k = keys.current
    if (!controls || !k.size) return
    const ortho = camera.isOrthographicCamera
    const speed = (k.has('shift') ? 60 : 18) * dt * (ortho ? 1 / camera.zoom * 4 : 1)
    const fwd = ortho ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3().subVectors(controls.target, camera.position).setY(0).normalize()
    const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize()
    const m = new THREE.Vector3()
    if (k.has('w')) m.add(fwd)
    if (k.has('s')) m.sub(fwd)
    if (k.has('d')) m.add(right)
    if (k.has('a')) m.sub(right)
    if (!ortho) { if (k.has('e')) m.y += 1; if (k.has('q')) m.y -= 1 }
    if (m.lengthSq() === 0) return
    m.normalize().multiplyScalar(speed)
    camera.position.add(m); controls.target.add(m); controls.update()
  })
  return null
}

// the controller flies the camera: left stick moves, right stick looks, the triggers go down and up (Top view: the left
// stick pans, the right stick zooms). Only while the view itself has focus.
const UP = new THREE.Vector3(0, 1, 0)
function PadRig({ active }) {
  const { camera, controls } = useThree()
  useFrame((_, dtRaw) => {
    if (!controls || !active()) return
    const { axes, held } = padState(), cfg = getCfg()
    if (!axes.lx && !axes.ly && !axes.rx && !axes.ry && !axes.lt && !axes.rt) return
    const dt = Math.min(dtRaw, 0.05), fast = held.L3 ? 3.3 : 1
    const ortho = camera.isOrthographicCamera
    if (ortho) {
      const sp = flyStep(1, cfg, dt, 90 * fast) / camera.zoom
      const m = new THREE.Vector3(curve(axes.lx, 1) * sp, 0, curve(axes.ly, 1) * sp)
      camera.position.add(m); controls.target.add(m)
      if (axes.ry) { camera.zoom = Math.min(controls.maxZoom, Math.max(controls.minZoom, camera.zoom * Math.exp(-curve(axes.ry, cfg.flySens) * dt * 1.6))); camera.updateProjectionMatrix() }
      controls.update()
      return
    }
    // look: turn the view direction about the camera, keep the distance to the orbit target
    if (axes.rx || axes.ry) {
      const dir = new THREE.Vector3().subVectors(controls.target, camera.position)
      const dist = Math.max(dir.length(), 0.5)
      const sph = new THREE.Spherical().setFromVector3(dir)
      sph.theta -= lookStep(axes.rx, cfg, dt)
      sph.phi = Math.min(Math.PI - 0.08, Math.max(0.08, sph.phi + lookStep(axes.ry, cfg, dt, true)))
      sph.radius = dist
      controls.target.copy(camera.position).add(new THREE.Vector3().setFromSpherical(sph))
    }
    const fwd = new THREE.Vector3().subVectors(controls.target, camera.position).setY(0)
    if (fwd.lengthSq() < 1e-8) fwd.set(0, 0, -1)
    fwd.normalize()
    const right = new THREE.Vector3().crossVectors(fwd, UP).normalize()
    const sp = 18 * fast * dt
    const m = new THREE.Vector3().addScaledVector(fwd, -curve(axes.ly, cfg.flySens) * sp).addScaledVector(right, curve(axes.lx, cfg.flySens) * sp)
    m.y += (curve(axes.rt, cfg.flySens) - curve(axes.lt, cfg.flySens)) * sp
    camera.position.add(m); controls.target.add(m)
    controls.update()
  })
  return null
}

// a flat invisible floor that catches clicks nothing else took (a click on empty ground)
function GroundClick({ onGround, planeY }) {
  const { camera } = useThree()
  const ref = useRef()
  const f = ev => {
    const first = ev.intersections.find(i => i.object.visible && i.object.isMesh && !i.object.material?.transparent && !i.object.userData.overlay && !i.object.userData.ghost)
    onGround(fromView((first || ev).point), ev, !!first)
  }
  useFrame(() => { if (ref.current) { ref.current.position.x = camera.position.x; ref.current.position.z = camera.position.z } })
  return <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, planeY ?? 0, 0]} onClick={f} userData={{ overlay: true }} renderOrder={-1}>
    <planeGeometry args={[20000, 20000]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} side={THREE.DoubleSide} /></mesh>
}

// a d-pad press on the screen -> the map direction it means (north up: up = +z, right = +x), from where the camera looks
export function cardinal(camera, dir, top) {
  if (!camera || top) return dir
  const f = new THREE.Vector3(); camera.getWorldDirection(f)
  const g = [f.x, -f.z]                                // game x, z of "forward"
  const len = Math.hypot(g[0], g[1]) || 1
  const F = [g[0] / len, g[1] / len], R = [F[1], -F[0]]
  const v = { up: F, down: [-F[0], -F[1]], right: R, left: [-R[0], -R[1]] }[dir]
  const C = { up: [0, 1], down: [0, -1], left: [-1, 0], right: [1, 0] }
  return Object.keys(C).sort((a, b) => (C[b][0] * v[0] + C[b][1] * v[1]) - (C[a][0] * v[0] + C[a][1] * v[1]))[0]
}

// ------------------------------------------------------------------ the component
export default function View3D({
  mode: modeProp, onMode, defaultMode = '3d', showModeToggle = true,
  bundle, view, layers = NO_LAYERS, showGeom = true, showColl = false, newColl, showNewColl = false, isVisible, isLocked,
  selectedIds = EMPTY, primaryId = null, onPick, onCommitTransform, onCommitGroup, gizmoMode = 'select', snap,
  overlays, hiddenLayers, onPickOverlay,
  placing, onPlace, tool = null, scatter, onScatter, tools,
  onGround, onMissed, boxSelect = false, selectables, onBoxSelect,
  focus, bg = '#1a2029', notes, onNote, planeY, grid, apiRef, flyRef, className = '', style, children, scene,
  onPadStep, onPadAdd, onPadMode, padInfo,
}) {
  const [modeState, setModeState] = useState(defaultMode)
  const mode = modeProp || modeState
  const setMode = m => { onMode ? onMode(m) : setModeState(m) }
  const api = useRef({})
  const registryRef = useRef(new Map())
  const tracker = useRef({ dist: 80, target: new THREE.Vector3() })
  const ownFly = useRef(false)
  const fly = flyRef || ownFly
  const wrap = useRef(null)
  const [tick, setTick] = useState(0)
  const [ruler, setRuler] = useState([])
  const [figures, setFigures] = useState([])
  const [band, setBand] = useState(null)
  const sceneKey = bundle ? bundle.entries?.join('|') : ''
  useEffect(() => {
    const ts = [1500, 4000, 9000].map(d => setTimeout(() => setTick(t => t + 1), d))
    return () => ts.forEach(clearTimeout)
  }, [sceneKey, bundle?.models && Object.keys(bundle.models).length])
  Object.assign(api.current, { clearMeasures: () => { setRuler([]); setFigures([]) }, setMode, mode, hasMeasures: ruler.length > 0 || figures.length > 0 })
  useEffect(() => { if (apiRef) apiRef.current = api.current })
  useEffect(() => { try { window.__v3 = api.current } catch { /* no window */ } }, [])

  // rubber band: plain drag in the Select tool, or Shift + drag
  const down = useRef(null)
  const sel = useRef({}); sel.current = { selectables, onBoxSelect, boxSelect, placing, tool }
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const rect = e => { const r = el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] }
    const pd = e => {
      const s = sel.current
      if (e.button !== 0 || s.placing || s.tool || !s.onBoxSelect || e.target.closest?.('.v3mode,button,input,select')) return
      if (!((s.boxSelect && !e.altKey) || e.shiftKey)) return
      const c = api.current.controls
      down.current = { p: rect(e), additive: e.shiftKey || e.ctrlKey, was: c ? c.enabled : true }
      if (c) c.enabled = false
    }
    const pm = e => {
      const d = down.current
      if (!d) return
      const q = rect(e)
      if (Math.hypot(q[0] - d.p[0], q[1] - d.p[1]) > 4) setBand([d.p[0], d.p[1], q[0], q[1]])
    }
    const pu = e => {
      const d = down.current
      if (!d) return
      down.current = null
      const c = api.current.controls; if (c) c.enabled = d.was
      const q = rect(e)
      setBand(null)
      if (Math.hypot(q[0] - d.p[0], q[1] - d.p[1]) <= 4) return
      const x0 = Math.min(d.p[0], q[0]), x1 = Math.max(d.p[0], q[0]), y0 = Math.min(d.p[1], q[1]), y1 = Math.max(d.p[1], q[1])
      const ids = []
      for (const it of sel.current.selectables || []) {
        const p = api.current.project(it.pos)
        if (p && p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1) ids.push(it.id)
      }
      sel.current.onBoxSelect(ids, d.additive)
    }
    el.addEventListener('pointerdown', pd, true); window.addEventListener('pointermove', pm); window.addEventListener('pointerup', pu)
    return () => { el.removeEventListener('pointerdown', pd, true); window.removeEventListener('pointermove', pm); window.removeEventListener('pointerup', pu) }
  }, [])

  // ---- controller: this view takes presses while it has focus (PadHost routes them here)
  const padOn = useCallback(() => getMode() === 'pad' && !!wrap.current && document.activeElement === wrap.current, [])
  Object.assign(api.current, { padOn })
  const P = useRef({}); P.current = { placing, tool, onPick, onMissed, selectedIds, view, isLocked, onPadStep, onPadAdd, onPadMode, mode }
  useEffect(() => registerView(wrap.current, a => {
    const p = P.current, A = api.current
    if (a.name === 'DPAD') {
      if (!p.onPadStep) return true
      p.onPadStep(cardinal(A.camera, a.dir, p.mode === 'top'))
      return true
    }
    switch (a.name) {
      case 'A': {
        if (p.placing) { if (A.padGhost?.place()) rumble('ok'); return true }
        if (p.tool) return true
        const id = A.pickCenter?.()
        const e = id != null && p.view ? p.view.ents.get(id) : null
        if (id != null && p.onPick && !(e && p.isLocked && p.isLocked(e))) { p.onPick(id, {}); rumble('ok') } else if (p.onMissed) p.onMissed({ type: 'pad' })
        return true
      }
      case 'LB': case 'RB': if (p.placing && A.padGhost) { A.padGhost.turn(a.name === 'RB' ? 1 : -1); return true } return false
      case 'X': if (p.onPadAdd) { p.onPadAdd(); return true } return false
      case 'Y': if (p.onPadMode) { p.onPadMode(); return true } return false
      case 'B':
        if (p.placing || p.tool || (p.selectedIds && p.selectedIds.size)) { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); return true }
        return false
      default: return false
    }
  }), [])
  useEffect(() => { setUi({ placing: !!placing, modeName: padInfo?.modeName || '' }) }, [!!placing, padInfo?.modeName])
  const pad = usePad()
  const ortho = mode === 'top'
  const gridColor = useMemo(() => cssVar('--line', '#28313d'), [bg])
  const plugins = tools || []
  const pick = useCallback((id, ev) => { if (!placing && !tool && onPick) onPick(id, ev) }, [placing, tool, onPick])
  const topNorth = ortho ? [0, 0, -1] : [0, 1, 0]
  void topNorth
  return (
    <div ref={wrap} className={'vp v3d ' + className} style={style} tabIndex={0} data-pad-ctx="view" aria-label={tr('3d_view')} onMouseEnter={() => { fly.current = true }} onMouseLeave={() => { fly.current = false }}>
      <Canvas linear flat camera={{ fov: 55, near: 0.2, far: 8000, position: [50, 50, 50] }} gl={{ antialias: true }}
              onPointerMissed={ev => { if (ev.type === 'click' && !placing && !tool) onMissed?.(ev) }}>
        <Suspense fallback={null}>
          <color attach="background" args={[bg]} />
          {!ortho && <fog attach="fog" args={[bg, 600, 3000]} />}
          <ambientLight intensity={0.85} />
          <directionalLight position={[300, 500, 200]} intensity={0.75} />
          <hemisphereLight args={['#d8e4f0', '#3a3022', 0.35]} />
          {ortho
            ? <OrthographicCamera makeDefault up={[0, 0, -1]} position={[0, 3000, 0]} near={1} far={8000} zoom={4} />
            : <PerspectiveCamera makeDefault fov={55} near={0.2} far={8000} position={[50, 50, 50]} />}
          <OrbitControls makeDefault enableDamping={false} maxDistance={3000} enableRotate={!ortho} screenSpacePanning={ortho}
            minZoom={0.02} maxZoom={120} zoomToCursor={ortho}
            mouseButtons={ortho ? { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN } : undefined} />
          <ModeCamera mode={mode} tracker={tracker} />
          <CameraRig focus={focus} tracker={tracker} />
          <FlyKeys enabled={fly} />
          <PadRig active={padOn} />
          <ApiBridge api={api} registryRef={registryRef} planeY={planeY} />
          {(grid ?? !bundle) && <gridHelper args={[2400, 240, gridColor, gridColor]} position={[0, (planeY ?? 0) - 0.02, 0]} userData={{ overlay: true }} />}
          {bundle && view && <LevelContent view={view} bundle={bundle} layers={layers} showColl={showColl} showGeom={showGeom} selectedIds={selectedIds}
            primaryId={primaryId} onPick={onPick ? pick : undefined} onCommitTransform={onCommitTransform || (() => {})} onCommitGroup={onCommitGroup || (() => {})}
            gizmoMode={gizmoMode} snap={snap} newColl={newColl} showNewColl={showNewColl} isVisible={isVisible} isLocked={isLocked} registryRef={registryRef} padOn={padOn} />}
          {overlays && <Overlays items={overlays} api={api} tick={tick} onPick={onPickOverlay ? (id, ev) => { if (!placing && !tool) onPickOverlay(id, ev) } : undefined} hidden={hiddenLayers} />}
          {placing && <PlacementGhost placing={placing} models={bundle?.models} onPlace={onPlace} snap={snap} api={api.current} />}
          <RulerLayer api={api} snap={snap} active={tool === 'ruler'} points={ruler} setPoints={setRuler} />
          <FigureLayer api={api} snap={snap} active={tool === 'figure'} figures={figures} setFigures={setFigures} />
          <ScatterLayer api={api} snap={snap} active={tool === 'scatter'} config={scatter || { radius: 6, density: 0.05, yawRandom: true, scale: [1, 1], gap: 0 }} onScatter={onScatter || (() => {})}
            taken={view ? view.list.filter(e => e.isNew).map(e => e.pos) : undefined} />
          {plugins.map(t => t.Layer && <t.Layer key={t.id} api={api} snap={snap} mode={mode} active={tool === t.id} />)}
          <NotePins notes={notes} onPick={onNote} />
          {onGround && !placing && !tool && <GroundClick onGround={onGround} planeY={planeY} />}
          {scene}
        </Suspense>
      </Canvas>
      {showModeToggle && <div className="v3mode"><Seg value={mode} onChange={setMode} options={[{ value: '3d', label: '3D', title: tr('look_around_the_map') }, { value: 'top', label: tr('top'), title: tr('from_above_north_is_up') }]} /></div>}
      {ortho && <div className="v3north" title={tr('north_is_up')} aria-hidden="true">{tr('n')}</div>}
      {band && <div className="v3band" style={{ left: Math.min(band[0], band[2]), top: Math.min(band[1], band[3]), width: Math.abs(band[2] - band[0]), height: Math.abs(band[3] - band[1]) }} />}
      {pad.mode === 'pad' && pad.ui.ctx === 'view' && <div className="v3ret" aria-hidden="true" />}
      {children}
    </div>
  )
}
