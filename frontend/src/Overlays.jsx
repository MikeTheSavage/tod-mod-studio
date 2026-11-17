// Overlays for the shared 3D view: boxes, points, paths, zones and polygons drawn over the level. Screens describe
// them as plain data (game coordinates, metres, yaw in degrees); the view draws them in both the 3D and the Top mode.
//
//   { id, kind: 'box' | 'point' | 'zone' | 'poly' | 'path' | 'ring' | 'plan',
//     pos: [x, y|null, z]          box, point, ring (a null height sits on the ground below)
//     size: [w, h, l], yaw         box (w = across, l = along the facing), arrow: show the facing
//     rect: [x0, z0, x1, z1], h, y zone
//     corners: [[x, z], ...], h, y poly
//     points: [[x, y|null, z], ...] path
//     radius                       point / ring
//     png (base64), rect, y        plan: a picture of the ground seen from above (a scene's streets and buildings) laid flat over the rect
//     color, label, always, selected, dashed, opacity, layer, pickable }
import React, { useEffect, useMemo, useState } from 'react'
import { Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { toView, quatToView, quatFromYaw, facingQuat } from './coords.js'

const BOX = new THREE.BoxGeometry(1, 1, 1)
const EDGES = new THREE.EdgesGeometry(BOX)
const SPHERE = new THREE.SphereGeometry(0.35, 12, 8)
const CONE = (() => { const g = new THREE.ConeGeometry(0.4, 1.4, 10); g.rotateX(-Math.PI / 2); return g })()   // points along game +z
const cache = new Map()
const fillMat = (color, opacity) => {
  const k = color + opacity
  if (!cache.has(k)) cache.set(k, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide }))
  return cache.get(k)
}
const lineMat = color => {
  const k = 'l' + color
  if (!cache.has(k)) cache.set(k, new THREE.LineBasicMaterial({ color }))
  return cache.get(k)
}
const solidMat = color => {
  const k = 's' + color
  if (!cache.has(k)) cache.set(k, new THREE.MeshBasicMaterial({ color }))
  return cache.get(k)
}

export const overlayYaw = o => {
  if (o.yaw != null) return o.yaw
  const q = o.orient || o.rot
  if (!q) return 0
  const [x, y, z, w] = q
  return Math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / Math.PI
}

// the ground height below (x, z), once the level's meshes are in; null until then
function useGround(api, x, z, need, tick) {
  const [y, setY] = useState(null)
  useEffect(() => {
    if (!need || !api.current) { setY(null); return }
    const h = api.current.castDown(x, z, 4000)
    setY(h.length ? h[h.length - 1] : null)
  }, [x, z, need, tick])
  return y
}

const Label = ({ at, text, color }) => <Html position={at} center style={{ pointerEvents: 'none' }} zIndexRange={[20, 0]}>
  <div className="v3tag" style={{ color }}>{text}</div></Html>

// the arrow points where the engine faces for this yaw (the parent group is turned by the plain quaternion)
function Facing({ color, len = 1.6, yaw = 0 }) {
  return <group quaternion={facingQuat(yaw)}><mesh geometry={CONE} material={solidMat(color)} position={[0, 0, -len]} userData={{ overlay: true }} /></group>
}

// a flat picture over a rectangle of the ground (north up: the top row of the picture is the largest game z)
function PlanSheet({ o, ud }) {
  const tex = useMemo(() => {
    const t = new THREE.TextureLoader().load('data:image/png;base64,' + o.png)
    t.colorSpace = THREE.SRGBColorSpace
    t.anisotropy = 4
    return t
  }, [o.png])
  useEffect(() => () => tex.dispose(), [tex])
  const [x0, z0, x1, z1] = o.rect
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: o.opacity ?? 1, depthWrite: false, side: THREE.DoubleSide }), [tex, o.opacity])
  return <mesh position={toView([(x0 + x1) / 2, o.y ?? 0, (z0 + z1) / 2])} rotation={[-Math.PI / 2, 0, 0]} scale={[x1 - x0, z1 - z0, 1]} material={mat} userData={ud} renderOrder={-1}>
    <planeGeometry args={[1, 1]} />
  </mesh>
}

function One({ o, api, tick, onPick }) {
  const color = o.color || '#4cc9f0'
  const sel = !!o.selected
  const need = o.pos ? o.pos[1] == null : o.kind === 'zone' || o.kind === 'poly' ? o.y == null : false
  const cx = o.pos ? o.pos[0] : o.rect ? (o.rect[0] + o.rect[2]) / 2 : o.corners ? o.corners[0][0] : 0
  const cz = o.pos ? o.pos[2] : o.rect ? (o.rect[1] + o.rect[3]) / 2 : o.corners ? o.corners[0][1] : 0
  const gy = useGround(api, cx, cz, need, tick)
  const base = o.pos?.[1] ?? o.y ?? gy ?? o.ground ?? 0
  const pick = o.pickable === false || !onPick ? undefined : ev => { ev.stopPropagation(); onPick(o.id, ev) }
  const ud = { overlay: true, oid: o.id }
  const op = o.opacity ?? 0.25
  const label = (o.always || sel) && o.label
  if (o.kind === 'plan') return <PlanSheet o={o} ud={ud} />
  if (o.kind === 'box') {
    const [w, h, l] = o.size || [3, 3, 3]
    const y = o.pos[1] == null ? (gy ?? o.ground ?? 0) + h / 2 : o.pos[1]
    return <group position={toView([o.pos[0], y, o.pos[2]])} quaternion={quatToView(quatFromYaw(overlayYaw(o)))} userData={ud}>
      <mesh geometry={BOX} scale={[w, h, l]} material={fillMat(color, sel ? Math.max(op, 0.5) : op)} onClick={pick} userData={ud} />
      <lineSegments geometry={EDGES} scale={[w, h, l]} material={lineMat(sel ? '#ffffff' : color)} userData={ud} />
      {o.arrow && <group position={[0, -h / 2 + 0.6, 0]}><Facing color={color} len={l / 2 + 0.9} yaw={overlayYaw(o)} /></group>}
      {label && <Label at={[0, h / 2 + 0.6, 0]} text={o.label} color={color} />}
    </group>
  }
  if (o.kind === 'zone') {
    const [x0, z0, x1, z1] = o.rect
    const h = o.h ?? 6
    return <group position={toView([(x0 + x1) / 2, base + h / 2, (z0 + z1) / 2])} userData={ud}>
      <mesh geometry={BOX} scale={[Math.abs(x1 - x0), h, Math.abs(z1 - z0)]} material={fillMat(color, sel ? 0.35 : o.opacity ?? 0.12)} onClick={pick} userData={ud} />
      <lineSegments geometry={EDGES} scale={[Math.abs(x1 - x0), h, Math.abs(z1 - z0)]} material={lineMat(sel ? '#ffffff' : color)} userData={ud} />
      {label && <Label at={[0, h / 2 + 0.6, 0]} text={o.label} color={color} />}
    </group>
  }
  if (o.kind === 'poly') {
    const h = o.h ?? 4
    const shape = new THREE.Shape(o.corners.map(c => new THREE.Vector2(c[0], c[1])))
    const g = new THREE.ShapeGeometry(shape); g.rotateX(-Math.PI / 2)
    const ring = [...o.corners, o.corners[0]]
    const c0 = o.corners.reduce((a, c) => [a[0] + c[0] / o.corners.length, a[1] + c[1] / o.corners.length], [0, 0])
    return <group userData={ud}>
      <mesh geometry={g} position={[0, base + 0.05, 0]} material={fillMat(color, sel ? 0.55 : op)} onClick={pick} userData={ud} />
      <Line points={ring.map(c => toView([c[0], base + 0.1, c[1]]))} color={sel ? '#ffffff' : color} lineWidth={sel ? 3 : 1.5} userData={ud} />
      <Line points={ring.map(c => toView([c[0], base + h, c[1]]))} color={sel ? '#ffffff' : color} lineWidth={1} transparent opacity={0.5} userData={ud} />
      {label && <Label at={toView([c0[0], base + h + 0.6, c0[1]])} text={o.label} color={color} />}
    </group>
  }
  if (o.kind === 'path') {
    const pts = o.points.map(p => toView([p[0], p[1] ?? base, p[2]]))
    return <group userData={ud}>
      {pts.length > 1 && <Line points={pts} color={sel ? '#ffffff' : color} lineWidth={sel ? 3 : 2} dashed={!!o.dashed} dashSize={1.5} gapSize={1} userData={ud} />}
      {pts.map((p, i) => <mesh key={i} geometry={SPHERE} position={p} scale={0.8} material={solidMat(color)} onClick={pick} userData={ud} />)}
      {label && pts[0] && <Label at={pts[0].clone().add(new THREE.Vector3(0, 1.6, 0))} text={o.label} color={color} />}
    </group>
  }
  if (o.kind === 'ring') {
    const r = o.radius || 3
    const pts = Array.from({ length: 49 }, (_, i) => new THREE.Vector3(Math.cos(i / 48 * Math.PI * 2) * r, 0, Math.sin(i / 48 * Math.PI * 2) * r))
    return <group position={toView([o.pos[0], base + 0.15, o.pos[2]])} userData={ud}>
      <Line points={pts} color={sel ? '#ffffff' : color} lineWidth={sel ? 3 : 1.5} dashed={!!o.dashed} dashSize={1} gapSize={0.7} userData={ud} />
      {label && <Label at={[0, 1.2, 0]} text={o.label} color={color} />}
    </group>
  }
  // point
  const r = o.radius
  const ring = r ? Array.from({ length: 49 }, (_, i) => new THREE.Vector3(Math.cos(i / 48 * Math.PI * 2) * r, 0, Math.sin(i / 48 * Math.PI * 2) * r)) : null
  return <group position={toView([o.pos[0], base, o.pos[2]])} quaternion={quatToView(quatFromYaw(overlayYaw(o)))} userData={ud}>
    <mesh geometry={SPHERE} position={[0, 0.8, 0]} scale={sel ? 1.5 : 1.1} material={solidMat(sel ? '#ffffff' : color)} onClick={pick} userData={ud} />
    <Line points={[new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0.8, 0)]} color={color} lineWidth={1.5} userData={ud} />
    {ring && <Line points={ring} color={color} lineWidth={1.2} transparent opacity={0.7} userData={ud} />}
    {o.arrow && <group position={[0, 0.8, 0]}><Facing color={color} len={1.6} yaw={overlayYaw(o)} /></group>}
    {label && <Label at={[0, 2, 0]} text={o.label} color={color} />}
  </group>
}

export default function Overlays({ items, api, tick, onPick, hidden }) {
  const list = useMemo(() => (items || []).filter(o => o && !(hidden && o.layer && hidden[o.layer] === false)), [items, hidden])
  return <>{list.map(o => <One key={o.id} o={o} api={api} tick={tick} onPick={onPick} />)}</>
}
