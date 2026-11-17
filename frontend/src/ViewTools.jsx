// Tool layers of the shared 3D view. A tool is a component rendered inside the canvas while it is the active tool; it
// gets `{ api, snap, mode, active }` and reads pointer events itself (api.pointerHit turns a mouse position into a
// point on the level). Built in: ruler, scale figure, scatter brush. A later screen adds its own through the
// `tools` prop of View3D: [{ id, Layer }].
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { toView, fromView } from './coords.js'
import { scatterStamp, rng, snapXZ } from './editing.js'
import { t } from './i18n.js'

export const RAM_HEIGHT = 1.8

// pointer position -> point on the level (game coordinates), re-evaluated on every call
export function useCursor(api) {
  const { gl } = useThree()
  const last = useRef(null)
  useEffect(() => {
    const el = gl.domElement
    const f = e => { last.current = api.current?.pointerHit(e.clientX, e.clientY) || null }
    el.addEventListener('pointermove', f)
    return () => el.removeEventListener('pointermove', f)
  }, [gl, api])
  return last
}

// a click (not a drag) on the canvas; capture=true runs before the camera controls see the press
function useClicks(onClick, deps) {
  const { gl } = useThree()
  useEffect(() => {
    const el = gl.domElement
    let down = null
    const pd = e => { if (e.button === 0) down = [e.clientX, e.clientY] }
    const pu = e => {
      if (e.button !== 0 || !down) return
      const d = Math.hypot(e.clientX - down[0], e.clientY - down[1]); down = null
      if (d < 5) onClick(e)
    }
    el.addEventListener('pointerdown', pd); el.addEventListener('pointerup', pu)
    return () => { el.removeEventListener('pointerdown', pd); el.removeEventListener('pointerup', pu) }
  }, [gl, ...deps])
}

const dist3 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
const fmt = d => (d >= 100 ? d.toFixed(0) : d.toFixed(1)) + ' m'

// ---------------------------------------------------------------- ruler: click points, read the distances
export function RulerLayer({ api, snap, active, points, setPoints }) {
  const cursor = useCursor(api)
  const [cur, setCur] = useState(null)
  const { gl } = useThree()
  useClicks(e => {
    if (!active) return
    const h = api.current?.pointerHit(e.clientX, e.clientY)
    if (!h) return
    const p = snap?.grid > 0 ? snapXZ(h.pos, snap.grid) : h.pos
    setPoints(pts => [...pts, p])
  }, [active, api, snap?.grid])
  useEffect(() => {
    if (!active) { setCur(null); return }
    const el = gl.domElement
    const mv = e => { const h = api.current?.pointerHit(e.clientX, e.clientY); setCur(h ? (snap?.grid > 0 ? snapXZ(h.pos, snap.grid) : h.pos) : null) }
    const key = e => { if (e.key === 'Escape') setPoints([]) }
    el.addEventListener('pointermove', mv); window.addEventListener('keydown', key)
    return () => { el.removeEventListener('pointermove', mv); window.removeEventListener('keydown', key) }
  }, [active, gl, api, snap?.grid])
  void cursor
  const live = active && cur && points.length ? [...points, cur] : points
  if (!live.length) return null
  const pts = live.map(p => toView(p))
  const segs = live.slice(1).map((p, i) => ({ a: live[i], b: p, d: dist3(live[i], p) }))
  const total = segs.reduce((a, s) => a + s.d, 0)
  return <group userData={{ overlay: true }}>
    {pts.length > 1 && <Line points={pts} color="#ffd23f" lineWidth={2.5} userData={{ overlay: true }} depthTest={false} renderOrder={20} />}
    {pts.map((p, i) => <mesh key={i} position={p} userData={{ overlay: true }} renderOrder={21}><sphereGeometry args={[0.28, 10, 8]} /><meshBasicMaterial color="#ffd23f" depthTest={false} /></mesh>)}
    {segs.map((s, i) => <Html key={i} position={toView([(s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2 + 0.4, (s.a[2] + s.b[2]) / 2])} center style={{ pointerEvents: 'none' }}>
      <div className="v3tag meas">{fmt(s.d)}</div></Html>)}
    {segs.length > 1 && <Html position={pts[pts.length - 1].clone().add(new THREE.Vector3(0, 1.6, 0))} center style={{ pointerEvents: 'none' }}><div className="v3tag meas tot">{fmt(total)}</div></Html>}
  </group>
}

// ---------------------------------------------------------------- a Ram-sized figure (about 1.8 m) to judge sizes by
export function FigureLayer({ api, snap, active, figures, setFigures }) {
  useClicks(e => {
    if (!active) return
    const h = api.current?.pointerHit(e.clientX, e.clientY)
    if (!h) return
    setFigures(fs => [...fs, snap?.grid > 0 ? snapXZ(h.pos, snap.grid) : h.pos])
  }, [active, api, snap?.grid])
  return <>{figures.map((p, i) => <group key={i} position={toView(p)} userData={{ overlay: true }}>
    <mesh position={[0, 0.45, 0]} userData={{ overlay: true }}><capsuleGeometry args={[0.2, 0.7, 4, 10]} /><meshLambertMaterial color="#e5a15a" /></mesh>
    <mesh position={[0, 1.5, 0]} userData={{ overlay: true }}><sphereGeometry args={[0.15, 12, 10]} /><meshLambertMaterial color="#f0c9a0" /></mesh>
    <mesh position={[0, 0.9, 0]} userData={{ overlay: true }}><capsuleGeometry args={[0.24, 0.5, 4, 10]} /><meshLambertMaterial color="#3a7bd5" /></mesh>
    <Line points={[new THREE.Vector3(0.5, 0, 0), new THREE.Vector3(0.5, RAM_HEIGHT, 0)]} color="#ffd23f" lineWidth={1.5} userData={{ overlay: true }} />
    <Html position={[0.6, RAM_HEIGHT, 0]} style={{ pointerEvents: 'none' }}><div className="v3tag meas">{RAM_HEIGHT}{' '}{t('m')}</div></Html>
  </group>)}</>
}

// ---------------------------------------------------------------- scatter brush
// config: { radius, density, yawRandom, scale: [lo, hi], gap }; onScatter(stamps: [{ pos, yaw, scale }]) once per stroke
export function ScatterLayer({ api, snap, active, config, onScatter, taken }) {
  const { gl } = useThree()
  const [ring, setRing] = useState(null)
  const [preview, setPreview] = useState([])
  const stroke = useRef(null)
  const seed = useRef((Date.now() % 1e6) | 0)
  const cfg = useRef(config); cfg.current = config
  useEffect(() => {
    if (!active) { setRing(null); setPreview([]); stroke.current = null; return }
    const el = gl.domElement
    const stampAt = pos => {
      const c = cfg.current
      const rand = rng(seed.current += 1)
      const done = stroke.current?.items || []
      const got = scatterStamp({ center: pos, radius: c.radius, density: c.density, yawRandom: c.yawRandom, scale: c.scale, gap: c.gap, rand,
        taken: [...(taken || []), ...done.map(s => s.pos)], max: Math.max(0, (c.max || 400) - done.length) })
      for (const s of got) {
        const ys = api.current.castDown(s.pos[0], s.pos[2], pos[1] + 30)
        s.pos[1] = ys.length ? ys[0] : pos[1]
      }
      return got
    }
    const pd = e => {
      if (e.button !== 0) return
      const h = api.current.pointerHit(e.clientX, e.clientY)
      if (!h) return
      e.stopImmediatePropagation()
      const c = api.current.controls; if (c) c.enabled = false
      stroke.current = { items: [], last: h.pos }
      const got = stampAt(h.pos); stroke.current.items.push(...got); setPreview(stroke.current.items.slice())
    }
    const mv = e => {
      const h = api.current.pointerHit(e.clientX, e.clientY)
      setRing(h ? h.pos : null)
      const s = stroke.current
      if (!s || !h) return
      if (Math.hypot(h.pos[0] - s.last[0], h.pos[2] - s.last[2]) >= Math.max(0.5, cfg.current.radius * 0.7)) {
        s.last = h.pos
        const got = stampAt(h.pos); s.items.push(...got); setPreview(s.items.slice())
      }
    }
    const pu = () => {
      const s = stroke.current; stroke.current = null
      const c = api.current?.controls; if (c) c.enabled = true
      if (s && s.items.length) onScatter(s.items)
      setPreview([])
    }
    el.addEventListener('pointerdown', pd, true); el.addEventListener('pointermove', mv); window.addEventListener('pointerup', pu)
    return () => { el.removeEventListener('pointerdown', pd, true); el.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', pu)
      const c = api.current?.controls; if (c) c.enabled = true }
  }, [active, gl, api, onScatter, taken])
  const circle = useMemo(() => Array.from({ length: 49 }, (_, i) => new THREE.Vector3(Math.cos(i / 48 * Math.PI * 2), 0, Math.sin(i / 48 * Math.PI * 2))), [])
  return <>
    {active && ring && <group position={toView(ring).add(new THREE.Vector3(0, 0.2, 0))} scale={config.radius} userData={{ overlay: true }}>
      <Line points={circle} color="#7cc4ff" lineWidth={2} userData={{ overlay: true }} /></group>}
    {preview.map((s, i) => <mesh key={i} position={toView(s.pos).add(new THREE.Vector3(0, 0.4 * s.scale, 0))} scale={s.scale} userData={{ overlay: true }}>
      <sphereGeometry args={[0.35, 8, 6]} /><meshBasicMaterial color="#7cc4ff" transparent opacity={0.6} /></mesh>)}
  </>
}

// ---------------------------------------------------------------- notes pinned in the level
export function NotePins({ notes, onPick, selected }) {
  return <>{(notes || []).map(n => <Html key={n.id} position={toView(n.pos)} center zIndexRange={[30, 0]}>
    <div className={'v3note' + (selected === n.id ? ' on' : '')} onClick={() => onPick?.(n.id)} title={n.text}><span>{n.text}</span></div></Html>)}</>
}
export { fromView }
