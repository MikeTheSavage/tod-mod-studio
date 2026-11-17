// The 3D view of the large-scene import: a vertex-coloured glb of the scene, the 1.8 m figure, and optional point picking (the scale tool).
import React, { Suspense, useEffect, useMemo, useRef } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { Figure, Fit, useGlb } from '../AssetView.jsx'
import { vpColor } from '../theme.js'

function paint(scene) {
  const o = scene.clone(true)
  o.traverse(m => {
    if (m.isMesh) m.material = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })
  })
  return o
}

// a camera for screenshots: ?scene_cam=x,y,z,tx,ty,tz (view axes)
function CamLink({ ready }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    const q = new URLSearchParams(location.search).get('scene_cam')
    if (!q || !ready || !controls) return
    const v = q.split(',').map(Number)
    camera.position.set(v[0], v[1], v[2]); controls.target.set(v[3], v[4], v[5]); camera.near = 0.05; camera.updateProjectionMatrix(); controls.update()
  }, [ready, controls])
  return null
}

function Marker({ p, color = '#ffd23f', size = 0.25 }) {
  return <mesh position={p}><sphereGeometry args={[size, 12, 8]} /><meshBasicMaterial color={color} depthTest={false} transparent opacity={0.95} /></mesh>
}

// url: the glb. scale: the group scale (the scene is drawn at the chosen scale while the figure stays 1.8 m). pick: { points, onPoint } for two-point measuring.
export default function SceneCanvas({ url, scale = 1, figure = true, pick, children, overlay }) {
  const glb = useGlb(url)
  const obj = useMemo(() => glb && paint(glb), [glb])
  const box = useMemo(() => {
    if (!obj) return null
    const b = new THREE.Box3().setFromObject(obj)
    return b.isEmpty() ? null : b
  }, [obj])
  const fig = useMemo(() => {
    if (!obj) return null
    const b = new THREE.Box3().setFromObject(obj)
    return b.isEmpty() ? null : { x: (b.min.x + b.max.x) / 2, z: (b.min.z + b.max.z) / 2, y: b.min.y }
  }, [obj])
  const fitBox = useMemo(() => box && new THREE.Box3(box.min.clone().multiplyScalar(scale), box.max.clone().multiplyScalar(scale)), [box, scale])
  const click = e => {
    if (!pick) return
    e.stopPropagation()
    pick.onPoint(e.point.clone().divideScalar(scale).toArray())
  }
  return (
    <Canvas linear flat style={{ height: '100%' }} camera={{ fov: 45, near: 0.05, far: 4000, position: [20, 15, 25] }}>
      <color attach="background" args={[vpColor()]} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[40, 80, 30]} intensity={0.8} />
      <Suspense fallback={null}>
        {obj && <group scale={[scale, scale, scale]}><primitive object={obj} onPointerDown={pick ? click : undefined} /></group>}
      </Suspense>
      {figure && fig && <group position={[fig.x * scale, fig.y * scale, fig.z * scale]}><Figure x={0} /></group>}
      {pick && (pick.points || []).map((p, i) => <Marker key={i} p={[p[0] * scale, p[1] * scale, p[2] * scale]} size={Math.max(0.12, 0.3 * Math.min(scale, 1))} />)}
      {pick && (pick.points || []).length === 2 && <Html position={pick.points[1].map(v => v * scale)} center style={{ pointerEvents: 'none' }}><div className="v3tag meas">{pick.label}</div></Html>}
      {children}
      <OrbitControls makeDefault />
      {fitBox && <Fit box={fitBox} dist={1.6} />}
      <CamLink ready={!!obj} />
      {overlay}
    </Canvas>
  )
}
