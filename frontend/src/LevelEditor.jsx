import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { get, post, runJob } from './api.js'
import Scene from './Scene.jsx'
import { CATS, CAT_COLOR, CAT_LABEL, GAMEPLAY, buildView, addableBlocks, keyOf } from './view.js'
import { opsMove, opsSet, opsDelete, opsRestore, newUid, describeOp } from './project.js'
import { r3, yawDeg, quatFromYaw } from './coords.js'
import Properties from './Properties.jsx'

const PALETTE = [
  ['pickup', 'Pickup', 'pickup', 'mission'],
  ['weapon', 'Weapon', 'weapon', 'mission'],
  ['enemy', 'Enemy', 'character', 'mission'],
  ['vehicle', 'Vehicle', 'vehicle', 'mission'],
  ['trigger', 'Trigger box', 'trigger', 'section'],
  ['wall', 'Invisible wall', 'wall', 'section'],
  ['navblock', 'Nav blocker', 'navblock', 'section'],
  ['trackpoint', 'Route point', 'route', 'mission'],
]
const KIND_SETS = {
  wall: { width: 6, height: 3, length: 0.5, CollisionFlags: 3 },
  navblock: { width: 4, height: 3, length: 4, CollisionFlags: 32 },
  trigger: { width: 4, height: 3, length: 4 },
}

export default function LevelEditor({ status, project, commit, replace, undo, redo, canUndo, canRedo, setSaveSpot }) {
  const [catalog, setCatalog] = useState(null)
  const [pick, setPick] = useState(() => project.view || status.settings?.last_view || { map: null, section: null, missions: [] })
  const [bundle, setBundle] = useState(null)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [layers, setLayers] = useState(() => Object.fromEntries(CATS.map(c => [c[0], c[3]])))
  const [showColl, setShowColl] = useState(false)
  const [showGeom, setShowGeom] = useState(true)
  const [showNewColl, setShowNewColl] = useState(true)
  const [selectedId, setSelectedId] = useState(null)
  const [gizmo, setGizmo] = useState('translate')
  const [focus, setFocus] = useState(null)
  const [filter, setFilter] = useState('')
  const [templates, setTemplates] = useState({})
  const [enums, setEnums] = useState({})
  const [addTarget, setAddTarget] = useState({})
  const [checks, setChecks] = useState(null)
  const [panel, setPanel] = useState('outliner')
  const probe = useRef(null)
  const flyEnabled = useRef(false)

  useEffect(() => { get('/api/catalog').then(setCatalog).catch(e => setErr(e.message)) }, [])
  useEffect(() => { get('/api/enums').then(setEnums).catch(() => {}) }, [])

  const map = catalog?.maps.find(m => m.id === pick.map)

  const open = useCallback(async (p = pick) => {
    if (!p.map) return
    setErr(null); setBusy('Opening level'); setSelectedId(null)
    try {
      const res = await runJob('/api/open', p, j => setBusy(j.message || 'Opening level'))
      setBundle(res)
      replace({ ...project, view: p })
      const ents = res.levels.flatMap(L => L.entities)
      const pts = ents.filter(e => GAMEPLAY.has(e.cat) && e.cat !== 'route').map(e => e.pos)
      const src = pts.length ? pts : ents.filter(e => e.cat === 'model').map(e => e.pos)
      if (src.length) {
        const med = i => src.map(p => p[i]).sort((a, b) => a - b)[src.length >> 1]
        setFocus({ pos: [med(0), med(1), med(2)], dist: 120, reset: true })
      }
      const tpl = await post('/api/templates', { entries: res.entries })
      setTemplates(tpl)
      if (new URLSearchParams(location.search).get('frame') === 'collision') {
        const P = (project.collision || []).flatMap(s => (s.pieces || []).flatMap(p => p.verts))
        if (P.length) setFocus({ pos: [0, 1, 2].map(i => P.reduce((a, v) => a + v[i], 0) / P.length), dist: 11, reset: true })
      }
    } catch (e) { setErr(e.message) }
    setBusy(null)
  }, [pick, project])

  useEffect(() => { if (pick.map && catalog && !bundle) open(pick) }, [catalog])

  const view = useMemo(() => buildView(bundle, project.level), [bundle, project.level])
  const sel = selectedId ? view.ents.get(selectedId) : null
  const addable = useMemo(() => addableBlocks(bundle), [bundle])

  // ---------------------------------------------------------------- edits
  const label = e => e.name || (e.type || '').replace(/\(.*\)/, '') + ' ' + (e.node || '')
  const withLabel = (ops, e) => ops.map(o => (!o.uid && o.node === e.target.node && o.frag === e.target.frag && !o.label)
    ? { ...o, label: label(e) } : o)
  const commitLevel = ops => commit({ ...project, level: ops })

  const onCommitTransform = (e, pos, rot, size) => {
    if (size) {
      let ops = project.level
      ;['width', 'height', 'length'].forEach((p, i) => { ops = opsSet(ops, e.target, p, size[i]) })
      commitLevel(withLabel(ops, e))
    } else {
      commitLevel(withLabel(opsMove(project.level, e.target, r3(pos), rot.map(x => Math.round(x * 1e6) / 1e6)), e))
    }
  }
  const setProp = (e, prop, value) => commitLevel(withLabel(opsSet(project.level, e.target, prop, value), e))
  const setPos = (e, pos, rot) => commitLevel(withLabel(opsMove(project.level, e.target, pos, rot || e.rot), e))
  const del = e => {
    if (!e || !e.ed) return
    const mode = status.settings?.save_safe_delete === false ? 'remove' : 'retire'
    commitLevel(withLabel(opsDelete(project.level, e.target, mode), e))
    if (e.isNew) setSelectedId(null)
  }
  const restore = e => commitLevel(opsRestore(project.level, e.target))

  const targetFor = kindWhere => {
    const ok = addable.filter(a => a.ok)
    const want = kindWhere === 'mission' ? ['mission', 'submap', 'map'] : ['submap', 'map', 'mission']
    for (const k of want) { const a = ok.find(x => x.kind === k); if (a) return a.entry }
    return null
  }

  const addFrom = (tpl, kind, catKey, where, pos, extraSet, srcEnt) => {
    const entry = addTarget[kind] || targetFor(where)
    if (!entry) { setErr('None of the open blocks can take new objects save-safely.'); return }
    const uid = newUid()
    const set = { ...(KIND_SETS[kind] || {}), ...(extraSet || {}) }
    const view = { type: tpl.type, cat: catKey, size: set.width != null ? [set.width, set.height, set.length] : tpl.size,
      sub: tpl.sub, model: srcEnt?.model, radius: srcEnt?.radius, kindLabel: PALETTE.find(p => p[0] === kind)?.[1] || kind,
      name: tpl.name }
    const op = { op: 'add', uid, entry, template: { entry: tpl.entry, frag: tpl.frag, node: tpl.node },
      name: `TODMS_${kind}_${uid}`, pos: r3(pos), rot: [0, 0, 0, 1], set, view }
    commitLevel([...project.level, op])
    setSelectedId('new:' + uid)
  }

  const addKind = kind => {
    const p = PALETTE.find(x => x[0] === kind)
    const tpl = templates[kind]
    if (!tpl) { setErr('No template for ' + p[1] + ' in the open blocks.'); return }
    const pos = probe.current ? probe.current() : [0, 0, 0]
    const ks = KIND_SETS[kind]
    if (ks && ks.height) pos[1] += ks.height / 2          // boxes are centred on their node: stand them on the ground
    addFrom(tpl, kind, p[2], p[3], pos)
  }

  const duplicate = e => {
    if (!e || !e.ed) return
    const off = [r3([e.pos[0] + 2, e.pos[1], e.pos[2] + 2])][0]
    if (e.isNew) {
      const o = e.op
      const uid = newUid()
      commitLevel([...project.level, { ...o, uid, name: `TODMS_copy_${uid}`, pos: off }])
      setSelectedId('new:' + uid)
      return
    }
    const tpl = { entry: e.target.entry, frag: e.target.frag, node: e.target.node, type: e.type, size: e.size, sub: e.sub, name: e.name }
    const where = ['pickup', 'weapon', 'character', 'vehicle', 'route'].includes(e.cat) ? 'mission' : 'section'
    const blockOk = addable.find(a => a.entry === e.entry && a.ok)
    const entry = blockOk ? e.entry : targetFor(where)
    if (!entry) { setErr('None of the open blocks can take new objects save-safely.'); return }
    const uid = newUid()
    const set = e.size ? { width: e.size[0], height: e.size[1], length: e.size[2] } : {}
    commitLevel([...project.level, { op: 'add', uid, entry, template: { entry: tpl.entry, frag: tpl.frag, node: tpl.node },
      name: `${(e.name || 'copy').slice(0, 40)}_${uid}`, pos: off, rot: e.rot, set,
      view: { type: e.type, cat: e.cat, size: e.size, sub: e.sub, model: e.model, radius: e.radius, kindLabel: 'copy', name: e.name } }])
    setSelectedId('new:' + uid)
  }

  // ---------------------------------------------------------------- keys
  useEffect(() => {
    const h = ev => {
      if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'SELECT') return
      if (ev.ctrlKey && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo() }
      else if (ev.ctrlKey && (ev.key.toLowerCase() === 'y' || (ev.shiftKey && ev.key.toLowerCase() === 'z'))) { ev.preventDefault(); redo() }
      else if (ev.ctrlKey && ev.key.toLowerCase() === 'd') { ev.preventDefault(); duplicate(sel) }
      else if (ev.key === 'Delete') del(sel)
      else if (ev.key === 'Escape') setSelectedId(null)
      else if (ev.key.toLowerCase() === 'f' && sel) setFocus({ pos: sel.pos, dist: 15 })
      else if (ev.key.toLowerCase() === 'g') setGizmo('translate')
      else if (ev.key.toLowerCase() === 'r') setGizmo('rotate')
      else if (ev.key.toLowerCase() === 't') setGizmo('scale')
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  // ---------------------------------------------------------------- outliner
  const counts = useMemo(() => {
    const c = {}
    for (const e of view.list) c[e.cat] = (c[e.cat] || 0) + 1
    return c
  }, [view])
  const outl = useMemo(() => {
    const f = filter.toLowerCase()
    return view.list.filter(e => GAMEPLAY.has(e.cat) && layers[e.cat] && e.cat !== 'route' || (e.isNew))
      .filter(e => !f || (e.name || '').toLowerCase().includes(f) || (e.type || '').toLowerCase().includes(f))
      .slice(0, 600)
  }, [view, layers, filter])

  const onPick = (id) => setSelectedId(id)

  const runCheck = async () => {
    setChecks({ running: true })
    try {
      const r = await runJob('/api/check', { mod: project }, j => setChecks({ running: true, msg: j.message }))
      setChecks(r)
    } catch (e) { setChecks({ error: e.message, trace: e.trace }) }
    setPanel('checks')
  }

  return (
    <div className="editor">
      <aside className="left">
        <section className="box">
          <h3>Level</h3>
          <label>Map
            <select value={pick.map || ''} onChange={ev => setPick({ map: ev.target.value, section: null, missions: [] })}>
              <option value="">choose a map</option>
              {catalog?.maps.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}
            </select>
          </label>
          {map && <label>Section
            <select value={pick.section || ''} onChange={ev => setPick({ ...pick, section: ev.target.value || null })}>
              <option value="">map block only</option>
              {map.sections.map(s => <option key={s.entry} value={s.entry}>{s.title}</option>)}
            </select>
          </label>}
          {map && map.missions.length > 0 && <div className="missions">
            <div className="sub">Missions on this map</div>
            {map.missions.map(m => (
              <label key={m.entry} className="check">
                <input type="checkbox" checked={pick.missions.includes(m.entry)} onChange={ev => setPick({
                  ...pick, missions: ev.target.checked ? [...pick.missions, m.entry] : pick.missions.filter(x => x !== m.entry),
                  section: pick.section || m.section || null })} />
                <span>{m.title} <i>{m.type}</i></span>
              </label>))}
          </div>}
          <button className="primary" disabled={!pick.map || !!busy} onClick={() => open(pick)}>Open</button>
        </section>
        <section className="box tabs">
          <div className="tabbar">
            <button className={panel === 'outliner' ? 'on' : ''} onClick={() => setPanel('outliner')}>Objects</button>
            <button className={panel === 'layers' ? 'on' : ''} onClick={() => setPanel('layers')}>Layers</button>
            <button className={panel === 'changes' ? 'on' : ''} onClick={() => setPanel('changes')}>Changes {project.level.length || ''}</button>
            <button className={panel === 'checks' ? 'on' : ''} onClick={() => setPanel('checks')}>Check</button>
          </div>
          {panel === 'layers' && <div className="layers">
            <label className="check"><input type="checkbox" checked={showGeom} onChange={e => setShowGeom(e.target.checked)} /> <span>Level meshes and textures</span></label>
            <label className="check"><input type="checkbox" checked={showColl} onChange={e => setShowColl(e.target.checked)} /> <span>Collision (model hulls)</span></label>
            <label className="check"><input type="checkbox" checked={showNewColl} onChange={e => setShowNewColl(e.target.checked)} />
              <span className="swatch" style={{ background: '#1ef06e' }} /> <span>New collision (this mod's collision sets)</span> <i>{(project.collision || []).reduce((a, s) => a + (s.pieces || []).length, 0)}</i></label>
            {(project.collision || []).some(s => (s.pieces || []).length) && <button onClick={() => {
              const P = (project.collision || []).flatMap(s => (s.pieces || []).flatMap(p => p.verts))
              setFocus({ pos: [0, 1, 2].map(i => P.reduce((a, v) => a + v[i], 0) / P.length), dist: 11, reset: true })
            }}>Frame the new collision</button>}
            <hr />
            {CATS.map(([k, lab, col]) => (
              <label key={k} className="check"><input type="checkbox" checked={!!layers[k]} onChange={ev => setLayers({ ...layers, [k]: ev.target.checked })} />
                <span className="swatch" style={{ background: col }} /> <span>{lab}</span> <i>{counts[k] || 0}</i></label>))}
          </div>}
          {panel === 'outliner' && <div className="outliner">
            <input placeholder="Filter by name or type" value={filter} onChange={e => setFilter(e.target.value)} />
            <ul>
              {outl.map(e => (
                <li key={e.id} className={(e.id === selectedId ? 'sel ' : '') + (e.deleted ? 'deleted ' : '') + (e.changed ? 'changed' : '')}
                    onClick={() => { setSelectedId(e.id); setFocus({ pos: e.pos, dist: 18 }) }}>
                  <span className="swatch" style={{ background: CAT_COLOR[e.cat] }} />
                  <span className="nm">{e.name || (e.type || '').replace(/\(.*\)/, '')}</span>
                  {e.off && <i title="disabled at load: a trigger switches it on">off</i>}
                </li>))}
            </ul>
          </div>}
          {panel === 'changes' && <div className="changes">
            {project.level.length === 0 && <p className="muted">No level changes yet. Select an object and move it, or add one from the palette.</p>}
            <ol>{project.level.map((o, i) => <li key={i} onClick={() => {
              const e = o.uid ? view.ents.get('new:' + o.uid) : view.byTarget.get(keyOf(o))
              if (e) { setSelectedId(e.id); setFocus({ pos: e.pos, dist: 18 }) }
            }}>{describeOp(o)}</li>)}</ol>
          </div>}
          {panel === 'checks' && <Checks checks={checks} onRun={runCheck} />}
        </section>
      </aside>

      <main className="viewport" onMouseEnter={() => { flyEnabled.current = true }} onMouseLeave={() => { flyEnabled.current = false }}>
        <div className="toolbar">
          <button onClick={undo} disabled={!canUndo} title="Ctrl+Z">Undo</button>
          <button onClick={redo} disabled={!canRedo} title="Ctrl+Y">Redo</button>
          <span className="sep" />
          <button className={gizmo === 'translate' ? 'on' : ''} onClick={() => setGizmo('translate')} title="G">Move</button>
          <button className={gizmo === 'rotate' ? 'on' : ''} onClick={() => setGizmo('rotate')} title="R">Rotate</button>
          <button className={gizmo === 'scale' ? 'on' : ''} onClick={() => setGizmo('scale')} title="T (boxes)">Size</button>
          <span className="sep" />
          <button onClick={() => duplicate(sel)} disabled={!sel?.ed} title="Ctrl+D">Duplicate</button>
          <button onClick={() => del(sel)} disabled={!sel?.ed || sel?.deleted} title="Delete">Delete</button>
          <span className="sep" />
          <span className="lbl">Add</span>
          {PALETTE.map(([k, lab, cat]) => (
            <button key={k} className="pal" disabled={!bundle || !templates[k]} onClick={() => addKind(k)}
                    title={templates[k] ? 'Adds at the point in the middle of the view' : 'no template in the open blocks'}>
              <span className="swatch" style={{ background: CAT_COLOR[cat] }} />{lab}</button>))}
          <span className="grow" />
          <button onClick={runCheck} disabled={!project.level.length && !Object.keys(project.data || {}).length && !(project.collision || []).length}>Check</button>
        </div>
        {bundle ? (
          <Canvas linear flat camera={{ fov: 55, near: 0.2, far: 8000, position: [50, 50, 50] }}
                  onPointerMissed={ev => { if (ev.type === 'click') setSelectedId(null) }} gl={{ antialias: true }}>
            <Suspense fallback={null}>
              <Scene view={view} bundle={bundle} layers={layers} showColl={showColl} showGeom={showGeom}
                     selectedId={selectedId} onPick={onPick} onCommitTransform={onCommitTransform}
                     gizmoMode={gizmo} focus={focus} probe={probe} flyEnabled={flyEnabled}
                     newColl={project.collision} showNewColl={showNewColl} />
            </Suspense>
          </Canvas>
        ) : (
          <div className="empty">{busy ? '' : 'Pick a map, a section and missions on the left, then Open.'}</div>
        )}
        {busy && <div className="busy">{busy}</div>}
        {err && <div className="error" onClick={() => setErr(null)}>{err}</div>}
        <div className="hint">Left drag: orbit, right drag: pan, wheel: zoom, W A S D Q E: fly (Shift faster), F: frame selection</div>
      </main>

      <aside className="right">
        {sel ? (
          <Properties e={sel} enums={enums} setProp={setProp} setPos={setPos} onDelete={() => del(sel)}
                      onRestore={() => restore(sel)} onDuplicate={() => duplicate(sel)} addable={addable}
                      setSaveSpot={setSaveSpot} />
        ) : (
          <div className="box">
            <h3>Nothing selected</h3>
            <p className="muted">Click an object in the view or in the list. New objects go into a block that can take
              them without breaking old saves:</p>
            <ul className="blocks">
              {addable.map(a => <li key={a.entry}><b>{a.title}</b> <i>{a.kind}</i> {a.ok ? 'can take new objects' : 'cannot (its last fragment is a shared prefab)'}</li>)}
            </ul>
            {bundle && <p className="muted">{view.list.length} objects in {bundle.levels.length} block(s), {Object.keys(bundle.models).length} meshes.</p>}
          </div>
        )}
      </aside>
    </div>
  )
}

function Checks({ checks, onRun }) {
  if (!checks) return <div className="checks"><p className="muted">Runs the full build in a temporary folder (nothing is
    written to the game) and the checks: objects per section, memory, box sizes, save safety, references, cars.</p>
    <button onClick={onRun}>Run the checker</button></div>
  if (checks.running) return <div className="checks"><p>Checking... {checks.msg || ''}</p></div>
  if (checks.error) return <div className="checks"><p className="bad">The build failed: {checks.error}</p><button onClick={onRun}>Run again</button></div>
  return (
    <div className="checks">
      <ul>{checks.checks.map((c, i) => <li key={i} className={c.level}><b>{c.area}</b> {c.title}{c.detail && <div className="det">{c.detail}</div>}</li>)}</ul>
      <button onClick={onRun}>Run again</button>
    </div>
  )
}
