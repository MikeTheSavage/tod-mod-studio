// Collision generator (companion tool, same core as the Unreal TODLevelEditor plugin): a mesh file placed in a map ->
// convex pieces with a TOD surface -> a collision set of the current mod. Built into a host model's HullList when
// the mod is built; shown in the Level editor's "New collision" layer and in the preview here.
import React, { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { get, post, runJob } from './api.js'
import { NewCollision, pieceGeometry } from './Scene.jsx'
import { toView } from './coords.js'

const EMPTY = { label: '', pos: [0, 0, 0], yaw: 0, scale: 1, method: 'solid', material: 'auto', surface: 'solid', visual_only: false,
  concavity: 0.04, max_pieces: 24 }

export default function Collision({ status, project, commit }) {
  const [cat, setCat] = useState(null)
  const [maps, setMaps] = useState([])
  const [mesh, setMesh] = useState(null)
  const [form, setForm] = useState({ ...EMPTY, map: project.view?.map || '' })
  const [job, setJob] = useState(null)
  const [msg, setMsg] = useState(null)
  const [report, setReport] = useState(null)
  const [existing, setExisting] = useState(null)
  const [focusSet, setFocusSet] = useState(null)
  useEffect(() => { get('/api/companion/catalog').then(setCat).catch(e => setMsg(e.message)) }, [])
  useEffect(() => { get('/api/catalog').then(c => setMaps(c.maps || [])).catch(() => {}) }, [])
  const sets = project.collision || []
  const f = (k, v) => setForm({ ...form, [k]: v })

  const [typed, setTyped] = useState('')
  const pick = async (path) => {
    setMsg(null)
    try {
      const r = await post('/api/collision/preview', path ? { path } : {})
      if (r.cancelled) return
      setMesh(r)
      setForm({ ...form, label: form.label || r.name.replace(/\.[^.]+$/, ''), material: r.material || form.material })
    } catch (e) { setMsg(e.message) }
  }
  const generate = async () => {
    if (!mesh || !form.map) { setMsg('Pick a mesh file and a map first.'); return }
    setMsg(null)
    try {
      const req = { path: mesh.path, label: form.label, map: form.map, pos: form.pos.map(Number), yaw: Number(form.yaw),
        scale: Number(form.scale), method: form.method, material: form.material === 'auto' ? mesh.material : form.material,
        surface: form.surface, visual_only: form.visual_only, concavity: Number(form.concavity), max_pieces: Number(form.max_pieces) }
      const r = await runJob('/api/collision/generate', req, setJob)
      const s = r.set
      const rest = sets.filter(x => x.id !== s.id)
      commit({ ...project, collision: [...rest, s] })
      setFocusSet(s.id)
      setMsg(`${s.label}: ${s.visual_only ? 'visual only, no collision' : `${r.stats.pieces} pieces, largest ${r.stats.max_verts} vertices`}. ${(r.log || []).join(' ')}`)
    } catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const check = async () => {
    setReport(null); setMsg(null)
    try { setReport(await runJob('/api/collision/check', { sets }, setJob)) } catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const showExisting = async () => {
    const s = sets.find(x => x.id === focusSet) || sets.find(x => (x.pieces || []).length)
    if (!s) return
    const P = s.pieces.flatMap(p => p.verts)
    const c = [0, 1, 2].map(i => P.reduce((a, v) => a + v[i], 0) / P.length)
    try { const r = await post('/api/collision/existing', { map: s.map, centre: c, radius: 35 }); setExisting(r.items) } catch (e) { setMsg(e.message) }
  }
  useEffect(() => {                                  // deep link: ?tab=collision&existing=1&check=1
    const q = new URLSearchParams(location.search)
    if (q.get('existing') && sets.length) showExisting()
    if (q.get('check') && sets.length) check()
  }, [])
  const remove = id => commit({ ...project, collision: sets.filter(x => x.id !== id) })
  const toggleVis = s => commit({ ...project, collision: sets.map(x => x.id === s.id ? { ...x, visual_only: !x.visual_only } : x) })
  const shown = focusSet ? sets.filter(s => s.id === focusSet) : sets

  return (
    <div className="page collision">
      <div className="split">
        <div className="col">
          <section className="box">
            <h3>Collision generator</h3>
            <p className="muted">Turns new geometry into Total Overdose collision: the mesh is split into convex pieces
              (at most 255 vertices each, the game's limit), each with a surface material (footsteps, bullet decals) and a
              collision type, and written into the static collision of a model of that map when the mod is built. The
              Unreal TOD Level Editor plugin uses the same code, so a mod made there builds the same bytes here.</p>
            <div className="row"><button onClick={() => pick()}>Pick a mesh file (.glb, .gltf, .obj)</button>
              <input placeholder="or paste a file path and press Enter" value={typed} onChange={e => setTyped(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && typed) pick(typed.replace(/^"|"$/g, '')) }} /></div>
            <div className="row">
              {mesh && <span className="muted">{mesh.name}: {mesh.triangles} triangles, size {mesh.max.map((v, i) => (v - mesh.min[i]).toFixed(2)).join(' x ')} m</span>}</div>
            <div className="row3">
              <label>Name <input value={form.label} onChange={e => f('label', e.target.value)} /></label>
              <label>Map <select value={form.map} onChange={e => f('map', e.target.value)}>
                <option value="">choose</option>{maps.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
              <label className="check"><input type="checkbox" checked={form.visual_only} onChange={e => f('visual_only', e.target.checked)} />
                <span>Visual only (no collision, e.g. far forest)</span></label>
            </div>
            <div className="row3">
              {['x', 'y', 'z'].map((a, i) => <label key={a}>Position {a} (game, m)
                <input type="number" step="0.1" value={form.pos[i]} onChange={e => { const p = [...form.pos]; p[i] = e.target.value; f('pos', p) }} /></label>)}
            </div>
            <div className="row3">
              <label>Turn (degrees about up) <input type="number" value={form.yaw} onChange={e => f('yaw', e.target.value)} /></label>
              <label>Scale <input type="number" step="0.1" value={form.scale} onChange={e => f('scale', e.target.value)} /></label>
              <label>Method <select value={form.method} onChange={e => f('method', e.target.value)}>
                {(cat?.methods || []).map(m => <option key={m.id} value={m.id}>{m.text}</option>)}</select></label>
            </div>
            <div className="row3">
              <label>Surface material <select value={form.material} onChange={e => f('material', e.target.value)}>
                <option value="auto">auto (from the name{mesh ? ': ' + mesh.material : ''})</option>
                {(cat?.face_materials || []).map(m => <option key={m} value={m}>{m}{cat.footsteps[m] ? ' (' + cat.footsteps[m] + ' steps)' : ''}</option>)}</select></label>
              <label>Collision <select value={form.surface} onChange={e => f('surface', e.target.value)}>
                {(cat?.presets || []).map(p => <option key={p.name} value={p.name} title={p.text}>{p.name} {p.word}{p.tested ? '' : ' (untested)'}</option>)}</select></label>
              <label>Max pieces <input type="number" value={form.max_pieces} onChange={e => f('max_pieces', e.target.value)} /></label>
            </div>
            <p className="muted">{(cat?.presets || []).find(p => p.name === form.surface)?.text}</p>
            <p className="muted">Tip: the Level editor's object panel shows game positions; the ground height is the y of a
              nearby object on the ground.</p>
            <button className="primary" onClick={generate} disabled={!!job || !mesh}>Generate collision</button>
          </section>
          <section className="box">
            <h3>Collision sets in this mod <span className="badge">{sets.length}</span></h3>
            <table className="sets"><thead><tr><th>Set</th><th>Map</th><th>Pieces</th><th>Max verts</th><th>Method</th><th>From</th><th></th></tr></thead>
              <tbody>{sets.map(s => <tr key={s.id} className={s.id === focusSet ? 'sel' : ''} onClick={() => setFocusSet(s.id)}>
                <td>{s.label}{s.visual_only && <span className="badge">visual only</span>}</td><td>{s.map}</td>
                <td>{(s.pieces || []).length}</td><td>{Math.max(0, ...(s.pieces || []).map(p => p.verts.length))}</td>
                <td>{s.method}</td><td>{s.source?.editor === 'unreal' ? 'Unreal: ' + (s.source.actor || '') : (s.source?.file || '')}</td>
                <td className="btns"><button onClick={ev => { ev.stopPropagation(); toggleVis(s) }}>{s.visual_only ? 'Collision' : 'Visual only'}</button>
                  <button onClick={ev => { ev.stopPropagation(); remove(s.id) }}>Remove</button></td></tr>)}
                {!sets.length && <tr><td colSpan={7} className="muted">No collision sets yet.</td></tr>}</tbody></table>
            <div className="row"><button onClick={check} disabled={!sets.length || !!job}>Check (build + verify)</button>
              <button onClick={showExisting} disabled={!sets.length}>Show the game's collision near</button>
              <button onClick={() => setFocusSet(null)}>Show all sets</button></div>
            {report && <Report r={report} />}
          </section>
        </div>
        <div className="col view3d">
          <Canvas linear flat camera={{ fov: 50, near: 0.1, far: 5000, position: [20, 14, 20] }}>
            <Suspense fallback={null}>
              <Preview mesh={mesh} form={form} sets={shown} existing={existing} />
            </Suspense>
          </Canvas>
          <div className="hint">Green: new collision pieces. Grey: the source mesh at its placement. Orange / yellow / blue
            wire: the game's own collision (solid / thin / blockers).</div>
        </div>
      </div>
      {job && <div className="busy">{job.message || job.status}</div>}
      {msg && <p className="flash" style={{ padding: '0 12px' }}>{msg}</p>}
    </div>
  )
}

function Report({ r }) {
  return <ul className="checklist">
    {(r.maps || []).map((m, i) => <React.Fragment key={i}>
      {m.notes.map((n, j) => <li key={'n' + j} className="ok"><b>host</b> {n}</li>)}
      {m.skipped.map((n, j) => <li key={'s' + j} className="ok"><b>skip</b> {n}</li>)}
      {m.blocks.map(b => b.hosts.map((h, j) => <li key={b.entry + j} className={h.readback.ok ? 'ok' : 'error'}>
        <b>verified</b> {b.entry.split('/').pop()}: {h.model.split('/').pop()} {h.record_bytes_old} &rarr; {h.record_bytes_new} B,
        +{h.readback.shapes} pieces, read-back within {h.readback.max_world_error_m.toExponential(1)} m, model sphere
        {' '}{h.sphere.radius_old.toFixed(2)} &rarr; {h.sphere.radius_new.toFixed(2)} m; the model writer's checks passed
        (other records identical, every model round-trips, sphere covers the collision)</li>))}
    </React.Fragment>)}
  </ul>
}

function Preview({ mesh, form, sets, existing }) {
  const src = useMemo(() => {
    if (!mesh) return null
    const a = Number(form.yaw) * Math.PI / 360
    const q = [0, Math.sin(a), 0, Math.cos(a)]
    const R = new THREE.Quaternion(-q[0], -q[1], q[2], q[3])
    const s = Number(form.scale) || 1
    const P = mesh.verts.map(v => {
      const w = toView([v[0] * s, v[1] * s, v[2] * s]).applyQuaternion(R)
      const o = toView(form.pos.map(Number))
      return [w.x + o.x, w.y + o.y, w.z + o.z]
    })
    const pos = []
    for (const t of mesh.tris) for (const i of t) pos.push(...P[i])
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    return g
  }, [mesh, form.pos, form.yaw, form.scale])
  const centre = useMemo(() => {
    const pts = sets.flatMap(s => (s.pieces || []).flatMap(p => p.verts))
    if (pts.length) return toView([0, 1, 2].map(i => pts.reduce((a, v) => a + v[i], 0) / pts.length))
    return toView(form.pos.map(Number))
  }, [sets, form.pos])
  return <>
    <color attach="background" args={['#1a2029']} />
    <ambientLight intensity={0.9} />
    <gridHelper args={[60, 60, '#33404f', '#232b36']} position={[centre.x, centre.y - 0.02, centre.z]} />
    {src && <mesh geometry={src}><meshBasicMaterial color="#8a8f99" wireframe transparent opacity={0.6} /></mesh>}
    <NewCollision sets={sets} existing={existing} visible />
    <OrbitControls makeDefault />
    <CamTo c={centre} />
  </>
}

function CamTo({ c }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    if (!controls) return
    controls.target.set(c.x, c.y + 1, c.z)
    camera.position.set(c.x + 14, c.y + 10, c.z + 14)
    camera.updateProjectionMatrix()
    controls.update()
  }, [c.x, c.y, c.z, controls])
  return null
}
