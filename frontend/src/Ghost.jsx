// The ghost that follows the mouse while something is placed: one model, a box, a marker, a whole prefab, or an arrow
// (a spot with a facing). Click places it, R or Shift+wheel turns it, dragging after the press sets the facing when the
// placement asks for it. `onPlace(pos, yaw)` gets game coordinates.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { toView, quatToView, fromView, quatFromYaw, facingQuat } from './coords.js'
import { loadModel } from './models.js'
import { snapXZ } from './editing.js'

const BOX = new THREE.BoxGeometry(1, 1, 1)
const DOT = new THREE.SphereGeometry(0.25, 8, 6)
const ARROW = (() => { const g = new THREE.ConeGeometry(0.45, 1.5, 12); g.rotateX(-Math.PI / 2); return g })()   // points to game +z (view -z)
const mat = (color, opacity = 0.35) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide })
const MATS = {}
const ghostMat = color => (MATS[color] ||= mat(color))

function GhostPiece({ item, rec, color }) {
  const [proto, setProto] = useState(null)
  useEffect(() => { let live = true; setProto(null); if (item.model && rec?.url) loadModel(item.model, rec).then(p => live && setProto(p)); return () => { live = false } }, [item.model, rec?.url])
  const m = ghostMat(color)
  const render = useMemo(() => {
    if (!proto?.render) return null
    const c = proto.render.clone()
    c.traverse(o => { if (o.isMesh) o.material = Array.isArray(o.material) ? o.material.map(() => m) : m })
    return c
  }, [proto, m])
  const lift = useMemo(() => {
    if (item.size) return item.size[1] / 2
    if (!render) return 0
    const b = new THREE.Box3().setFromObject(render)
    return b.isEmpty() ? 0 : -b.min.y
  }, [render, item])
  const q = item.rot ? quatToView(item.rot) : undefined
  return <group position={toView(item.dpos || [0, 0, 0])} quaternion={q}>
    <group position={[0, lift, 0]}>
      {render ? <primitive object={render} />
        : item.size ? <mesh scale={item.size} geometry={BOX} material={m} />
        : <mesh geometry={DOT} material={m} />}
    </group>
  </group>
}

export default function PlacementGhost({ placing, models, onPlace, snap = {}, api }) {
  const { camera, scene, gl } = useThree()
  const grp = useRef()
  const yaw = useRef(placing.yaw || 0)
  const arrowGrp = useRef(null)
  const hit = useRef(null)
  const [cursor, setCursor] = useState(null)
  const downRef = useRef(null)          // a press survives the effect being re-bound by a re-render
  const color = placing.color || '#7cc4ff'
  const items = useMemo(() => placing.items || [{ dpos: [0, 0, 0], model: placing.model, size: placing.size }], [placing])
  const step = snap.angle > 0 ? snap.angle : 15
  useEffect(() => {
    const el = gl.domElement
    const rc = new THREE.Raycaster()
    const ndc = e => { const r = el.getBoundingClientRect(); return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1) }
    let moved = false
    const get = () => downRef.current, put = v => { downRef.current = v }
    const setYaw = v => { yaw.current = (v % 360 + 360) % 360; if (grp.current) grp.current.quaternion.copy(quatToView(quatFromYaw(yaw.current))); if (arrowGrp.current) arrowGrp.current.quaternion.copy(facingQuat(yaw.current)) }
    const move = (e, centre, ret) => {
      if (!centre) moved = true
      rc.setFromCamera(centre ? new THREE.Vector2(0, ret ? 0 : -0.2) : ndc(e), camera)
      const own = grp.current
      const hits = rc.intersectObjects(scene.children, true).filter(h => h.object.visible && h.object.isMesh && !h.object.isLineSegments2 && !h.object.material?.transparent &&
        !h.object.userData.ghost && !h.object.userData.overlay && !(own && (own === h.object || own.getObjectById(h.object.id))))
      let p = snap.mode !== 'free' && hits.length && (camera.isOrthographicCamera || hits[0].distance < 1500) ? hits[0].point.clone() : null
      if (!p) { const t = new THREE.Vector3(); if (rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -(placing.planeY ?? hit.current?.y ?? 0)), t)) p = t }
      if (p && snap.mode === 'ground' && api) { const ys = api.castDown(p.x, -p.z, 4000); if (ys.length) p.y = ys[ys.length - 1] }
      if (p && snap.grid > 0) { const g = snapXZ(fromView(p), snap.grid); p.set(g[0], p.y, -g[2]) }
      hit.current = p
      if (p && own) { own.position.copy(p); own.visible = true }
      if (placing.rect) setCursor(p ? fromView(p) : null)
      if (get() && placing.facingDrag && p) {
        const d0 = get(), a = fromView(d0.p), b = fromView(p)
        if (Math.hypot(e.clientX - d0.x, e.clientY - d0.y) > 8) { setYaw(Math.atan2(-(b[0] - a[0]), b[2] - a[2]) * 180 / Math.PI); if (own) own.position.copy(d0.p) }
      }
    }
    const t1 = setTimeout(() => { if (!moved) move(null, true) }, 400), t2 = setTimeout(() => { if (!moved) move(null, true) }, 1500)
    const pd = e => { if (e.button === 0 && hit.current) { put({ x: e.clientX, y: e.clientY, p: hit.current.clone(), at: e }); if (placing.facingDrag && api?.controls) api.controls.enabled = false } }
    const pu = e => {
      if (e.button !== 0 || !get()) return
      const d = get(); put(null)
      if (api?.controls) api.controls.enabled = true
      const dragged = Math.hypot(e.clientX - d.x, e.clientY - d.y)
      if (dragged < 5 || placing.facingDrag) {
        const p = fromView(d.p)
        onPlace([p[0], p[1] + (placing.size ? placing.size[1] / 2 : 0), p[2]], yaw.current)
      }
    }
    const wheel = e => { if (e.shiftKey || e.altKey) { e.preventDefault(); e.stopImmediatePropagation(); setYaw(yaw.current + (e.deltaY > 0 ? step : -step)) } }
    const key = e => { if (e.key.toLowerCase() === 'r' && !e.ctrlKey && e.target.tagName !== 'INPUT') { setYaw(yaw.current + (e.shiftKey ? -step : step)); e.stopImmediatePropagation() } }
    setYaw(yaw.current)
    // controller: the ghost rides the screen-centre reticle; A places it, the bumpers turn it
    const padTimer = setInterval(() => { if (api?.padOn?.() && !get()) move(null, true, true) }, 33)
    if (api) api.padGhost = {
      place: () => { const p = hit.current; if (!p) return false; const q = fromView(p); onPlace([q[0], q[1] + (placing.size ? placing.size[1] / 2 : 0), q[2]], yaw.current); return true },
      turn: d => setYaw(yaw.current + d * step),
    }
    el.addEventListener('pointermove', move); el.addEventListener('pointerdown', pd); el.addEventListener('pointerup', pu)
    el.addEventListener('wheel', wheel, { capture: true, passive: false }); window.addEventListener('keydown', key, true)
    return () => { clearTimeout(t1); clearTimeout(t2); clearInterval(padTimer); if (api && api.padGhost) api.padGhost = null; el.removeEventListener('pointermove', move); el.removeEventListener('pointerdown', pd); el.removeEventListener('pointerup', pu)
      el.removeEventListener('wheel', wheel, { capture: true }); window.removeEventListener('keydown', key, true) }
  }, [camera, scene, gl, placing, onPlace, snap.grid, snap.angle, snap.mode, api])
  const first = placing.rect?.first
  const rectBox = first && cursor ? { x: (first[0] + cursor[0]) / 2, z: (first[1] + cursor[2]) / 2, w: Math.abs(cursor[0] - first[0]), l: Math.abs(cursor[2] - first[1]) } : null
  return <>
    <group ref={grp} visible={false} userData={{ ghost: true }}>
      {items.map((it, i) => <GhostPiece key={i} item={it} rec={it.model ? models?.[it.model] : null} color={color} />)}
      {placing.arrow && <group ref={arrowGrp}><mesh geometry={ARROW} material={ghostMat('#ffffff')} position={[0, 1.2, -1.4]} userData={{ ghost: true }} /></group>}
    </group>
    {rectBox && <mesh userData={{ ghost: true }} position={[rectBox.x, (placing.planeY ?? hit.current?.y ?? 0) + 3, -rectBox.z]} scale={[Math.max(rectBox.w, 0.1), 6, Math.max(rectBox.l, 0.1)]}
      geometry={BOX} material={ghostMat(color)} />}
  </>
}
