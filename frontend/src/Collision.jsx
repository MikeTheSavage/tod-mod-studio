// Collision generator (companion tool): a mesh file placed in a map ->
// convex pieces with a TOD surface -> a collision set of the current mod. Built into a host model's HullList when
// the mod is built; shown in the Level editor's "New collision" layer and in the preview here.
import { vpColor } from './theme.js'
import React, { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { get, post, runJob } from './api.js'
import { NewCollision, pieceGeometry } from './Scene.jsx'
import { toView } from './coords.js'
import { t as tr } from './i18n.js'

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
            <h3>{tr('collision_generator')}</h3>
            
            <div className="row"><button onClick={() => pick()}>{tr('pick_a_mesh_file_glb_gltf')}</button>
              <input placeholder={tr('or_paste_a_file_path_and')} value={typed} onChange={e => setTyped(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && typed) pick(typed.replace(/^"|"$/g, '')) }} /></div>
            <div className="row">
              {mesh && <span className="muted">{mesh.name}: {mesh.triangles}{' '}{tr('triangles_size')}{' '}{mesh.max.map((v, i) => (v - mesh.min[i]).toFixed(2)).join(' x ')}{' '}{tr('m')}</span>}</div>
            <div className="row3">
              <label>{tr('name')}{' '}<input value={form.label} onChange={e => f('label', e.target.value)} /></label>
              <label>{tr('map')}{' '}<select value={form.map} onChange={e => f('map', e.target.value)}>
                <option value="">{tr('choose')}</option>{maps.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
              <label className="check"><input type="checkbox" checked={form.visual_only} onChange={e => f('visual_only', e.target.checked)} />
                <span>{tr('visual_only_no_collision_e_g')}</span></label>
            </div>
            <div className="row3">
              {['x', 'y', 'z'].map((a, i) => <label key={a}>{tr('position')}{' '}{a}{' '}{tr('game_m')}<input type="number" step="0.1" value={form.pos[i]} onChange={e => { const p = [...form.pos]; p[i] = e.target.value; f('pos', p) }} /></label>)}
            </div>
            <div className="row3">
              <label>{tr('turn_degrees_about_up')}{' '}<input type="number" value={form.yaw} onChange={e => f('yaw', e.target.value)} /></label>
              <label>{tr('scale')}{' '}<input type="number" step="0.1" value={form.scale} onChange={e => f('scale', e.target.value)} /></label>
              <label>{tr('method')}{' '}<select value={form.method} onChange={e => f('method', e.target.value)}>
                {(cat?.methods || []).map(m => <option key={m.id} value={m.id}>{m.text}</option>)}</select></label>
            </div>
            <div className="row3">
              <label>{tr('surface_material')}{' '}<select value={form.material} onChange={e => f('material', e.target.value)}>
                <option value="auto">{tr('auto_from_the_name')}{mesh ? ': ' + mesh.material : ''})</option>
                {(cat?.face_materials || []).map(m => <option key={m} value={m}>{m}{cat.footsteps[m] ? ' (' + cat.footsteps[m] + ' steps)' : ''}</option>)}</select></label>
              <label>{tr('collision')}{' '}<select value={form.surface} onChange={e => f('surface', e.target.value)}>
                {(cat?.presets || []).map(p => <option key={p.name} value={p.name} title={p.text}>{p.name} {p.word}{p.tested ? '' : ' (untested)'}</option>)}</select></label>
              <label>{tr('max_pieces')}{' '}<input type="number" value={form.max_pieces} onChange={e => f('max_pieces', e.target.value)} /></label>
            </div>
            
            <button className="primary" onClick={generate} disabled={!!job || !mesh}>{tr('generate_collision')}</button>
          </section>
          <section className="box">
            <h3>{tr('collision_sets_in_this_mod')}{' '}<span className="badge">{sets.length}</span></h3>
            <table className="sets"><thead><tr><th>{tr('set')}</th><th>{tr('map')}</th><th>{tr('pieces')}</th><th>{tr('max_verts')}</th><th>{tr('method')}</th><th>{tr('from')}</th><th></th></tr></thead>
              <tbody>{sets.map(s => <tr key={s.id} className={s.id === focusSet ? 'sel' : ''} onClick={() => setFocusSet(s.id)}>
                <td>{s.label}{s.visual_only && <span className="badge">{tr('visual_only')}</span>}</td><td>{s.map}</td>
                <td>{(s.pieces || []).length}</td><td>{Math.max(0, ...(s.pieces || []).map(p => p.verts.length))}</td>
                <td>{s.method}</td><td>{s.source?.file || ''}</td>
                <td className="btns"><button onClick={ev => { ev.stopPropagation(); toggleVis(s) }}>{s.visual_only ? 'Collision' : 'Visual only'}</button>
                  <button onClick={ev => { ev.stopPropagation(); remove(s.id) }}>{tr('remove')}</button></td></tr>)}
                {!sets.length && <tr><td colSpan={7} className="muted">{tr('no_collision_sets_yet')}</td></tr>}</tbody></table>
            <div className="row"><button onClick={check} disabled={!sets.length || !!job}>{tr('check_build_verify')}</button>
              <button onClick={showExisting} disabled={!sets.length}>{tr('show_the_game_s_collision_near')}</button>
              <button onClick={() => setFocusSet(null)}>{tr('show_all_sets')}</button></div>
            {report && <Report r={report} />}
          </section>
        </div>
        <div className="col view3d">
          <Canvas linear flat camera={{ fov: 50, near: 0.1, far: 5000, position: [20, 14, 20] }}>
            <Suspense fallback={null}>
              <Preview mesh={mesh} form={form} sets={shown} existing={existing} />
            </Suspense>
          </Canvas>
          <div className="hint" title={tr('green_new_pieces_grey_source_mesh')}>{tr('green_new_orange_yellow_blue_existing')}</div>
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
      {m.notes.map((n, j) => <li key={'n' + j} className="ok"><b>{tr('host')}</b> {n}</li>)}
      {m.skipped.map((n, j) => <li key={'s' + j} className="ok"><b>{tr('skip')}</b> {n}</li>)}
      {m.blocks.map(b => b.hosts.map((h, j) => <li key={b.entry + j} className={h.readback.ok ? 'ok' : 'error'}>
        <b>{tr('verified')}</b> {b.entry.split('/').pop()}: {h.model.split('/').pop()} {h.record_bytes_old} &rarr; {h.record_bytes_new} B,
        +{h.readback.shapes}{' '}{tr('pieces_read_back_within')}{' '}{h.readback.max_world_error_m.toExponential(1)}{' '}{tr('m_model_sphere')}{' '}{h.sphere.radius_old.toFixed(2)} &rarr; {h.sphere.radius_new.toFixed(2)}{' '}{tr('m_the_model_writer_s_checks')}</li>))}
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
    <color attach="background" args={[vpColor()]} />
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
