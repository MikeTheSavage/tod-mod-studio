import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, Html, Line } from '@react-three/drei'
import * as THREE from 'three'
import { toView, quatToView, fromView, quatFromView, quatFromYaw } from './coords.js'
import { catColor, cbOn } from './view.js'
import { loadModel } from './models.js'
import { padState, getCfg } from './pad/padstore.js'
import { isClick, changed } from './camdrag.js'
import { curve, lookStep, flyStep } from './pad/padlogic.js'

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
  const key = cat + '|' + kind + '|' + (cbOn() ? 'cb' : '')
  if (!matCache.has(key)) {
    const color = new THREE.Color(catColor(cat) || '#cccccc')
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
  const click = ev => { if (!onPick || !isClick(ev)) return; ev.stopPropagation(); onPick(e.id, ev) }
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
  const click = ev => { if (!onPick || !isClick(ev)) return; ev.stopPropagation(); onPick(e.id, ev) }
  return (
    <group ref={ref} position={toView(e.pos)} quaternion={quatToView(e.rot)} userData={{ eid: e.id }}>
      {render && <group position={[0, e.isNew && e.cat !== 'model' && box ? -box.min.y : 0, 0]}><primitive object={render} visible={showGeom && !e.deleted} onClick={click} /></group>}
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
export function RouteLines({ links, ents, visible }) {
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


// ------------------------------------------------------------------ moving a group: one pivot at the centre, every member follows it
function GroupGizmo({ ents, mode, registry, snap, onCommit }) {
  const [pv, setPv] = useState(null)
  const pivot = useRef(null)
  pivot.current = pv
  const start = useRef(null)
  const c = useMemo(() => {
    const v = new THREE.Vector3()
    ents.forEach(e => v.add(toView(e.pos)))
    return v.multiplyScalar(1 / Math.max(1, ents.length))
  }, [ents])
  const objs = () => ents.map(e => [e, registry.current.get(e.id)]).filter(([, o]) => o)
  const follow = () => {
    const st = start.current
    if (!st || !pivot.current) return
    pivot.current.updateMatrix()
    const D = pivot.current.matrix.clone().multiply(st.inv)
    for (const [o, m0] of st.members) {
      const M = D.clone().multiply(m0)
      M.decompose(o.position, o.quaternion, new THREE.Vector3())
    }
  }
  return <>
    <group ref={setPv} position={c} />
    {pv && <TransformControls object={pv} mode={mode} size={0.8}
      translationSnap={snap?.grid > 0 ? snap.grid : null} rotationSnap={snap?.angle > 0 ? snap.angle * Math.PI / 180 : null}
      onMouseDown={() => {
        pivot.current.updateMatrix()
        start.current = { inv: pivot.current.matrix.clone().invert(),
          members: objs().map(([, o]) => [o, new THREE.Matrix4().compose(o.position, o.quaternion, ONE)]) }
      }}
      onObjectChange={() => { if (start.current) start.current.moved = true; follow() }}
      onMouseUp={() => {
        const moved = start.current?.moved
        const moves = objs().map(([e, o]) => ({ e, pos: fromView(o.position), rot: quatFromView(o.quaternion) }))
        start.current = null
        if (pivot.current) { pivot.current.quaternion.identity(); pivot.current.scale.set(1, 1, 1) }
        if (moved) onCommit(moves)
      }} />}
  </>
}

// ------------------------------------------------------------------ the controller moves, turns or resizes the selection
// While the sticks are held the objects follow live (like the gizmo does); when both sticks come back to rest the whole gesture
// is ONE commit = one undo step. Move: left stick on the ground (camera relative), right stick up and down. Rotate: either
// stick sideways. Resize (boxes only): left stick width and length, right stick height. Grid and angle snap step the gesture.
const UPV = new THREE.Vector3(0, 1, 0)
function PadEdit({ members, mode, registry, snap, padOn, onCommitGroup, onCommitTransform }) {
  const { camera } = useThree()
  const st = useRef({ dirty: false, acc: [0, 0, 0], list: [], mode: null, single: null })
  const commit = () => {
    const S = st.current
    if (!S.dirty) return
    S.dirty = false
    const list = S.list.filter(([e, o]) => o)
    if (S.mode === 'scale' && S.single) {
      const [e, o] = list[0]
      const sc = o.scale
      const size = [e.size[0] * sc.x, e.size[1] * sc.y, e.size[2] * sc.z].map(v => Math.max(0.05, Math.round(v * 100) / 100))
      o.scale.set(1, 1, 1)
      onCommitTransform(e, null, null, size)
    } else {
      const moves = list.map(([e, o]) => ({ e, pos: fromView(o.position), rot: quatFromView(o.quaternion) }))
      list.forEach(([, o]) => o.scale.set(1, 1, 1))
      onCommitGroup(moves)
    }
    S.acc = [0, 0, 0]
  }
  useFrame((_, dtRaw) => {
    const S = st.current
    const { axes } = padState(), cfg = getCfg()
    const live = padOn() && members.length > 0 && mode !== 'select' && (axes.lx || axes.ly || axes.rx || axes.ry)
    if (!live) { if (S.dirty) commit(); return }
    if (!S.dirty) { S.dirty = true; S.mode = mode; S.single = members.length === 1 ? members[0] : null; S.list = members.map(e => [e, registry.current.get(e.id)]); S.acc = [0, 0, 0] }
    const dt = Math.min(dtRaw, 0.05)
    const objs = S.list.map(l => l[1]).filter(Boolean)
    if (!objs.length) return
    if (S.mode === 'translate') {
      const fwd = new THREE.Vector3(); camera.getWorldDirection(fwd)
      if (camera.isOrthographicCamera) fwd.set(0, 0, -1)
      fwd.y = 0
      if (fwd.lengthSq() < 1e-8) fwd.set(0, 0, -1)
      fwd.normalize()
      const right = new THREE.Vector3().crossVectors(fwd, UPV).normalize()
      const sp = flyStep(1, cfg, dt, 6)
      const d = new THREE.Vector3().addScaledVector(fwd, -curve(axes.ly, 1) * sp * cfg.flySens).addScaledVector(right, curve(axes.lx, 1) * sp * cfg.flySens)
      d.y = -curve(axes.ry, 1) * sp * cfg.flySens
      const g = snap?.grid > 0 ? snap.grid : 0
      if (g) {
        for (const k of [0, 1, 2]) {
          const comp = k === 0 ? d.x : k === 1 ? d.y : d.z
          S.acc[k] += comp
          const n = Math.trunc(S.acc[k] / g)
          if (n) { S.acc[k] -= n * g; const step = n * g; if (k === 0) d.x = step; else if (k === 1) d.y = step; else d.z = step } else { if (k === 0) d.x = 0; else if (k === 1) d.y = 0; else d.z = 0 }
        }
      }
      for (const o of objs) o.position.add(d)
    } else if (S.mode === 'rotate') {
      const v = Math.abs(axes.rx) > Math.abs(axes.lx) ? axes.rx : axes.lx
      let ang = -lookStep(v, cfg, dt) * 0.8
      const a = snap?.angle > 0 ? snap.angle * Math.PI / 180 : 0
      if (a) { S.acc[0] += ang; const n = Math.trunc(S.acc[0] / a); S.acc[0] -= n * a; ang = n * a }
      if (ang) {
        const q = new THREE.Quaternion().setFromAxisAngle(UPV, ang)
        const c = new THREE.Vector3()
        objs.forEach(o => c.add(o.position)); c.multiplyScalar(1 / objs.length)
        for (const o of objs) {
          if (objs.length > 1) o.position.sub(c).applyQuaternion(q).add(c)
          o.quaternion.premultiply(q)
        }
      }
    } else if (S.mode === 'scale' && S.single && S.single.size) {
      const o = objs[0], r = 0.9 * cfg.flySens
      o.scale.x = Math.min(40, Math.max(0.02, o.scale.x * Math.exp(curve(axes.lx, 1) * r * dt)))
      o.scale.z = Math.min(40, Math.max(0.02, o.scale.z * Math.exp(-curve(axes.ly, 1) * r * dt)))
      o.scale.y = Math.min(40, Math.max(0.02, o.scale.y * Math.exp(-curve(axes.ry, 1) * r * dt)))
    }
  })
  return null
}

// ------------------------------------------------------------------ the level: gameplay things, models, routes, collision, gizmo
export function LevelContent({ view, bundle, layers, showColl, showGeom, selectedIds, primaryId, onPick, onCommitTransform, onCommitGroup,
                                gizmoMode, snap, newColl, showNewColl, isVisible, isLocked, registryRef, padOn }) {
  const own = useRef(new Map())
  const registry = registryRef || own
  const [, force] = useState(0)
  const register = (id, obj) => {
    if (obj) registry.current.set(id, obj); else registry.current.delete(id)
    if (selectedIds.has(id)) force(x => x + 1)
  }
  const visible = view.list.filter(e => layers[e.cat] && (!isVisible || isVisible(e)))
  const hasModel = e => e.model && bundle.models[e.model] && !bundle.models[e.model].missing
  const models = visible.filter(hasModel)
  const things = visible.filter(e => !hasModel(e))
  const sel = primaryId ? view.ents.get(primaryId) : null
  const members = [...selectedIds].map(id => view.ents.get(id)).filter(e => e && e.ed && !e.deleted && registry.current.get(e.id))
  const dragging = useRef(false), from0 = useRef(null)
  const single = members.length === 1 ? members[0] : null
  const selObj = single ? registry.current.get(single.id) : null
  const snapProps = { translationSnap: snap?.grid > 0 ? snap.grid : null, rotationSnap: snap?.angle > 0 ? snap.angle * Math.PI / 180 : null }
  return (
    <>
      {models.map(e => (
        <ModelThing key={e.id} e={e} rec={bundle.models[e.model]} showGeom={showGeom} showColl={showColl}
                    selected={selectedIds.has(e.id)} register={register} onPick={isLocked && isLocked(e) ? undefined : onPick} />
      ))}
      {things.filter(e => e.cat !== 'model' && e.cat !== 'logic').map(e => (
        <Thing key={e.id} e={e} selected={selectedIds.has(e.id)} register={register} onPick={isLocked && isLocked(e) ? undefined : onPick} />
      ))}
      <RouteLines links={view.links} ents={view.ents} visible={layers.route} />
      <NewCollision sets={newColl} visible={showNewColl} />
      {single && selObj && gizmoMode !== 'select' && (
        <TransformControls object={selObj} mode={gizmoMode} size={0.8} showX showY showZ {...snapProps}
          onMouseDown={() => { dragging.current = true; from0.current = [...selObj.position.toArray(), ...selObj.quaternion.toArray(), ...selObj.scale.toArray()] }}
          onMouseUp={() => {
            dragging.current = false
            const o = selObj
            if (!changed(from0.current, [...o.position.toArray(), ...o.quaternion.toArray(), ...o.scale.toArray()], 1e-5)) return   // a press on the gizmo that moved nothing changes nothing
            if (gizmoMode === 'scale' && single.size) {
              const s = o.scale
              const size = [single.size[0] * s.x, single.size[1] * s.y, single.size[2] * s.z].map(v => Math.max(0.05, Math.round(v * 100) / 100))
              o.scale.set(1, 1, 1)
              onCommitTransform(single, null, null, size)
            } else {
              o.scale.set(1, 1, 1)
              onCommitTransform(single, fromView(o.position), quatFromView(o.quaternion), null)
            }
          }} />
      )}
      {members.length > 1 && (gizmoMode === 'translate' || gizmoMode === 'rotate') &&
        <GroupGizmo ents={members} mode={gizmoMode} registry={registry} snap={snap} onCommit={onCommitGroup} />}
      {padOn && <PadEdit members={members} mode={gizmoMode} registry={registry} snap={snap} padOn={padOn} onCommitGroup={onCommitGroup} onCommitTransform={onCommitTransform} />}
      {sel && (
        <Html position={toView(sel.pos).add(new THREE.Vector3(0, (sel.size ? sel.size[1] / 2 : 1.6) + 0.6, 0))}
              center style={{ pointerEvents: 'none' }}>
          <div className="tag">{members.length > 1 ? `${members.length} selected` : sel.name || sel.type}</div>
        </Html>
      )}
    </>
  )
}
