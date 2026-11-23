// Routes and nav editor (companion tools part B):
// enemy GotoPaths and patrols, vehicle tracks, pedestrian SignPosts, traffic points, NavBlock boxes and Neighborhood
// circles drawn in 3D with arrows; move, insert, remove, reorder, link and unlink points, set speeds and widths,
// validate, and check the build with navtool. The edits are the mod's "nav" ops.
import { vpColor } from './theme.js'
import React, { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, Line, Html } from '@react-three/drei'
import * as THREE from 'three'
import { get, runJob } from './api.js'
import { useUi } from './uistore.js'
import { toView, fromView, quatToView } from './coords.js'
import { buildView } from './view.js'
import { ModelThing } from './Scene.jsx'
import { isClick, changed } from './camdrag.js'
import { KIND_COLOR, KIND_MARK, kindColor, KIND_LABEL, short, navMove, navInsert, navRemove, navReorder, navLink, navSet, describeNav,
  newId, isNew } from './partb.js'
import { t } from './i18n.js'

const JUNGLE = ['mainmap_map09_jungle.map', 'submap01_map09_jungle.submap', 'submap02_map09_jungle.submap',
  'mm010_ernestocruz.mission'].map(b => 'data_pc/overdose_the_game/overdose/shared/' + b)
const SPHERE = new THREE.SphereGeometry(0.45, 12, 8)
const CONE = new THREE.ConeGeometry(0.45, 1.3, 10)
const BOX = new THREE.BoxGeometry(1, 1, 1)
const DIAMOND = new THREE.OctahedronGeometry(0.55)
const PYRAMID = new THREE.ConeGeometry(0.55, 1.0, 4)
const POINT_GEO = { sphere: SPHERE, box: new THREE.BoxGeometry(0.8, 0.8, 0.8), diamond: DIAMOND, cone: PYRAMID }
const UP = new THREE.Vector3(0, 1, 0)
const mats = new Map()
const mat = (c, o = 1) => {
  const k = c + o
  if (!mats.has(k)) mats.set(k, new THREE.MeshBasicMaterial({ color: c, transparent: o < 1, opacity: o, depthWrite: o >= 1 }))
  return mats.get(k)
}

function propsFor(route, point, editable) {
  if (!route) return []
  if (route.kind === 'navblocks') return editable.navblock || []
  if (route.kind === 'neighborhoods') return editable.Neighborhood || []
  if (route.kind === 'traffic') return editable.traffic_point || []
  if (!point) return editable.track || []
  return (point.type || '').startsWith('AI_track_point') ? editable.AI_track_point || [] : editable.TrackPoint || []
}

export default function Routes({ status, project, commit }) {
  const cbOn = useUi().prefs.cb
  const [catalog, setCatalog] = useState(null)
  const [mapId, setMapId] = useState('map09')
  const [entries, setEntries] = useState(JUNGLE)
  const [model, setModel] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [ri, setRi] = useState(null)
  const [pi, setPi] = useState(null)
  const [pi2, setPi2] = useState(null)
  const [filter, setFilter] = useState('all')
  const [showMap, setShowMap] = useState(true)
  const [bundle, setBundle] = useState(null)
  const [focus, setFocus] = useState({ p: [-520, -139, -2180], t: 0 })
  const [check, setCheck] = useState(null)
  const [prop, setProp] = useState('')
  const [val, setVal] = useState('')
  const [posEdit, setPosEdit] = useState(['', '', ''])
  const [nb, setNb] = useState({ entry: '', size: [3, 3, 3], yaw: 0 })
  const target = useRef(null)
  const ops = project.nav || []
  const setOps = o => commit({ ...project, nav: o })

  useEffect(() => { get('/api/catalog').then(setCatalog).catch(e => setMsg(e.message)) }, [])
  const map = catalog?.maps.find(m => m.id === mapId)
  const blocks = map ? [map.map_block, ...map.sections.map(s => s.entry), ...map.missions.map(m => m.entry)] : JUNGLE

  const load = async () => {
    try {
      const r = await runJob('/api/routes/model', { entries, ops, collision: project.collision || [] }, j => setBusy(j.message || 'Reading routes'))
      setModel(r)
      if (r.ops_error) setMsg('An edit no longer applies: ' + r.ops_error)
    } catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  useEffect(() => { load() }, [entries.join(), JSON.stringify(ops), (project.collision || []).length])
  useEffect(() => {
    if (!showMap || !map || bundle?.map === mapId) return
    const section = entries.find(e => e.endsWith('.submap')) || map.sections[0]?.entry
    runJob('/api/open', { map: mapId, section, missions: [] }, j => setBusy(j.message || 'Opening the map'))
      .then(b => { setBundle(b); setBusy(null) }).catch(e => { setMsg(e.message); setBusy(null) })
  }, [showMap, mapId, catalog])

  const routes = model?.routes || []
  const shown = routes.map((r, i) => [r, i]).filter(([r]) => filter === 'all' || r.kind === filter)
  const route = ri != null ? routes[ri] : null
  const point = route && pi != null ? route.points[pi] : null
  const point2 = route && pi2 != null ? route.points[pi2] : null
  const canAppend = e => model?.edit?.[e]?.can_append
  useEffect(() => { if (point) setPosEdit(point.pos.map(v => v.toFixed(3))) }, [point?.node, point?.pos?.join()])
  useEffect(() => { if (model && !nb.entry) setNb(n => ({ ...n, entry: entries.find(canAppend) || '' })) }, [model])

  const fly = p => setFocus({ p, t: Date.now() })
  useEffect(() => {                                    // deep link: ?tab=routes&route=0x0040005B&point=2
    const q = new URLSearchParams(location.search)
    const want = q.get('route')
    if (!want || !routes.length || ri != null) return
    const i = routes.findIndex(r => r.node === want)
    if (i >= 0) { setRi(i); const j = Number(q.get('point') || 0); setPi(j); fly(routes[i].points[j]?.pos || routes[i].points[0].pos) }
  }, [routes.length])
  const selectRoute = i => { setRi(i); setPi(null); setPi2(null); const r = routes[i]; if (r?.points.length) fly(r.points[0].pos) }
  const pick = (i, j, ev) => {
    if (ev?.shiftKey && i === ri) { setPi2(j); return }
    setRi(i); setPi(j); setPi2(null)
  }
  const insertAfter = (append) => {
    if (!route || !['goto', 'patrol', 'vehicle', 'ai_track', 'track'].includes(route.kind)) return setMsg('Pick a point of a track route first.')
    if (!canAppend(route.entry)) return setMsg(model.edit[route.entry].reason)
    const pts = route.points
    const i = append ? pts.length - 1 : (pi ?? pts.length - 1)
    const a = pts[i].pos
    let pos
    if (i + 1 < pts.length && !append) pos = a.map((v, k) => (v + pts[i + 1].pos[k]) / 2)
    else {
      const b = pts[i - 1]?.pos || [a[0] - 1, a[1], a[2]]
      const d = a.map((v, k) => v - b[k]); const L = Math.hypot(d[0], d[2]) || 1
      pos = [a[0] + 3 * d[0] / L, a[1], a[2] + 3 * d[2] / L]
    }
    const r = navInsert(ops, route, append ? null : i, pos.map(v => Math.round(v * 1e6) / 1e6))
    setOps(r.ops); setPi(append ? pts.length : i + 1)
  }
  const removePt = () => { if (point) { setOps(navRemove(ops, route, point)); setPi(null) } }
  const reorder = d => { if (point) { setOps(navReorder(ops, route, pi, d)); setPi(pi + d) } }
  const link = on => {
    if (!point || !point2 || route.kind !== 'signposts') return setMsg('Select a SignPost, then shift-click a second one.')
    setOps(navLink(ops, route, point, point2, on))
  }
  const setValue = () => {
    if (!prop) return
    let v = val
    try { v = JSON.parse(val) } catch { /* a bare string */ }
    if (!point && ['signposts', 'traffic', 'navblocks', 'neighborhoods'].includes(route.kind)) return setMsg('Select a point first.')
    setOps(navSet(ops, route, point, prop, v))
  }
  const applyPos = () => { if (point) setOps(navMove(ops, route, point, posEdit.map(Number))) }
  const addNavBlock = () => {
    if (!nb.entry) return setMsg('No block of this view can take new objects.')
    const p = target.current ? fromView(target.current) : focus.p
    setOps([...ops, { op: 'add_navblock', id: newId('nb'), entry: nb.entry, like: model.navblock_template,
      pos: p.map(v => Math.round(v * 1000) / 1000), size: nb.size.map(Number), yaw: Number(nb.yaw), flags: 32 }])
  }
  const runCheck = async () => {
    setCheck(null)
    try { setCheck(await runJob('/api/partb/check', { mod: project, kinds: ['nav'] }, j => setBusy(j.message || 'Checking'))) }
    catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  const onDrag = (pos) => { if (point) setOps(navMove(ops, route, point, pos.map(v => Math.round(v * 1e6) / 1e6))) }
  const props = propsFor(route, point, model?.editable || {})
  const issues = model?.issues || []

  return (
    <div className="editor routes" style={{ gridTemplateColumns: '360px 1fr 340px' }}>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>{t('routes_and_nav')}</h3>
          <div className="row"><select value={mapId} onChange={e => { setMapId(e.target.value); setBundle(null)
            const m = catalog.maps.find(x => x.id === e.target.value); setEntries([m.map_block, ...m.sections.map(s => s.entry)]) }}>
            {(catalog?.maps || []).map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select>
            <label className="check"><input type="checkbox" checked={showMap} onChange={e => setShowMap(e.target.checked)} /><span>{t('show_the_map')}</span></label></div>
          <div className="blocks">{blocks.map(b => <label key={b} className="check"><input type="checkbox" checked={entries.includes(b)}
            onChange={e => setEntries(e.target.checked ? [...entries, b] : entries.filter(x => x !== b))} />
            <span>{short(b)}{model?.edit?.[b] && !model.edit[b].can_append && <i className="muted" title={model.edit[b].reason}>{' '}{t('no_new_points')}</i>}</span></label>)}</div>
        </section>
        <section className="box">
          <div className="row"><select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">{t('all_routes')}{routes.length})</option>
            {Object.keys(KIND_LABEL).map(k => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select></div>
          <ul className="checklist" style={{ maxHeight: 220, overflow: 'auto' }}>{shown.map(([r, i]) => {
            const n = issues.filter(x => x.ref?.track === r.node || (x.ref?.entry === r.entry && r.points.some(p => p.node === x.ref?.node))).length
            return <li key={i} className={i === ri ? 'warn' : 'ok'} style={{ cursor: 'pointer', borderColor: kindColor(r.kind, cbOn) }} onClick={() => selectRoute(i)}>
              <span className="kmark" style={{ color: kindColor(r.kind, cbOn) }} title={KIND_LABEL[r.kind]} aria-hidden="true">{(KIND_MARK[r.kind] || KIND_MARK.goto).glyph}{(KIND_MARK[r.kind] || KIND_MARK.goto).letter}</span> <b>{r.kind}</b> {r.name || r.node} <span className="muted">{short(r.entry)} {r.points.length}{' '}{t('pts')}</span>
              {r.points.some(p => p.new) && <span className="badge ok">{t('edited_a22fca')}</span>}{n > 0 && <span className="badge">{n}{' '}{t('issues')}</span>}</li>
          })}</ul>
        </section>
        {route && <section className="box">
          <h3>{route.name || route.node} <span className="muted">{KIND_LABEL[route.kind]}</span></h3>
          <table className="sets"><tbody>{route.points.map((p, j) => <tr key={p.node} className={j === pi ? 'sel' : j === pi2 ? 'sel2' : ''}
            onClick={ev => { pick(ri, j, ev); fly(p.pos) }} style={{ cursor: 'pointer' }}>
            <td>{j + 1}</td><td>{p.new ? <b className="good">{p.node}{' '}{t('new_c2a6b0')}</b> : p.node}</td><td>{p.order ?? ''}</td>
            <td className="muted">{p.pos.map(v => v.toFixed(1)).join(', ')}</td></tr>)}</tbody></table>
          <div className="btns">
            <button onClick={() => insertAfter(false)} title={t('a_new_point_halfway_to_the')}>{t('insert_after')}</button>
            <button onClick={() => insertAfter(true)}>{t('append')}</button>
            <button onClick={removePt} disabled={!point}>{t('remove')}</button>
            <button onClick={() => reorder(-1)} disabled={!point || !pi}>{t('move_up')}</button>
            <button onClick={() => reorder(1)} disabled={!point || pi >= route.points.length - 1}>{t('move_down')}</button>
            {route.kind === 'signposts' && <><button onClick={() => link(true)}>{t('link')}</button><button onClick={() => link(false)}>{t('unlink')}</button></>}
          </div>
          {point && <div className="row3">{['x', 'y', 'z'].map((a, k) => <label key={a}>{a}<input value={posEdit[k]}
            onChange={e => { const c = [...posEdit]; c[k] = e.target.value; setPosEdit(c) }} /></label>)}</div>}
          {point && <button onClick={applyPos}>{t('apply_position')}</button>}
          <div className="row" style={{ marginTop: 8 }}><select value={prop} onChange={e => setProp(e.target.value)}>
            <option value="">{t('set_a_value')}</option>{props.map(p => <option key={p} value={p}>{p}</option>)}</select>
            <input value={val} onChange={e => setVal(e.target.value)} placeholder={t('value_f32b67')} style={{ width: 80 }} />
            <button onClick={setValue} disabled={!prop}>{t('set')}</button></div>
          {prop && model.units[prop] && <p className="muted">{prop}: {model.units[prop]}</p>}
        </section>}
        <section className="box">
          <h3>{t('new_navblock')}</h3>
          
          <div className="row"><select value={nb.entry} onChange={e => setNb({ ...nb, entry: e.target.value })}>
            {entries.filter(canAppend).map(e => <option key={e} value={e}>{short(e)}</option>)}</select></div>
          <div className="row3">{['w', 'h', 'l'].map((a, k) => <label key={a}>{a} (m)<input value={nb.size[k]}
            onChange={e => { const s = [...nb.size]; s[k] = e.target.value; setNb({ ...nb, size: s }) }} /></label>)}</div>
          <div className="row"><label>{t('yaw')}{' '}<input value={nb.yaw} onChange={e => setNb({ ...nb, yaw: e.target.value })} style={{ width: 60 }} /></label>
            <button onClick={addNavBlock}>{t('add_navblock')}</button></div>
        </section>
      </aside>
      <div className="viewport">
        <div className="toolbar"><span className="lbl" title={t('shift_click_a_second_signpost_to')}>{t('click_a_point_drag_the_arrows')}</span></div>
        <Canvas linear flat camera={{ fov: 55, near: 0.2, far: 6000, position: [-500, -120, 2200] }}>
          <Suspense fallback={null}>
            <View routes={routes} ri={ri} pi={pi} pi2={pi2} pick={pick} bundle={showMap ? bundle : null} issues={issues}
              focus={focus} onDrag={onDrag} target={target} />
          </Suspense>
        </Canvas>
      </div>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>{t('edits')}{' '}<span className="badge">{ops.length}</span></h3>
          <ol className="changes">{ops.map((o, i) => <li key={i}>{describeNav(o)} <button onClick={() => setOps(ops.filter((_, j) => j !== i))}>{t('x_11f6ad')}</button></li>)}</ol>
          <div className="btns"><button onClick={load}>{t('validate')}</button><button className="primary" onClick={runCheck} disabled={!ops.length}>{t('check_build_navtool')}</button></div>
        </section>
        <section className="box">
          <h3>{t('issues_30ce4c')}{' '}<span className="badge">{issues.length}</span></h3>
          <ul className="checklist">{issues.map((x, i) => <li key={i} className={x.severity === 'error' ? 'error' : x.severity === 'warning' ? 'warn' : 'ok'}
            style={{ cursor: x.pos ? 'pointer' : 'default' }} onClick={() => x.pos && fly(x.pos)}><b>{x.kind}</b> {x.message}</li>)}
            {!issues.length && <li className="ok">{t('no_dangling_or_one_way_links')}</li>}</ul>
        </section>
        {check && <section className="box">
          <h3>{t('check_695ef8')}{' '}{check.result}</h3>
          <ul className="checklist">{check.lines.map((l, i) => <li key={i} className={l.level}><b>{l.area}</b> {l.text}</li>)}</ul>
        </section>}
        
      </aside>
      {busy && <div className="busy">{busy}</div>}
      {msg && <div className="error" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}

function View({ routes, ri, pi, pi2, pick, bundle, issues, focus, onDrag, target }) {
  const view = useMemo(() => bundle ? buildView(bundle, []) : null, [bundle])
  const models = view ? view.list.filter(e => e.model && bundle.models[e.model] && !bundle.models[e.model].missing) : []
  const selRef = useRef(), from0 = useRef(null)
  const [selObj, setSelObj] = useState(null)
  const sel = ri != null && pi != null ? routes[ri]?.points[pi] : null
  useEffect(() => { setSelObj(selRef.current || null) }, [sel?.node, ri])
  return <>
    <color attach="background" args={[vpColor()]} />
    <fog attach="fog" args={[vpColor(), 500, 2500]} />
    <ambientLight intensity={0.85} />
    <directionalLight position={[300, 500, 200]} intensity={0.7} />
    {models.map(e => <ModelThing key={e.id} e={e} rec={bundle.models[e.model]} showGeom showColl={false}
      selected={false} register={() => {}} onPick={() => {}} />)}
    {routes.map((r, i) => <RouteDraw key={i} r={r} i={i} sel={i === ri} pi={i === ri ? pi : null} pi2={i === ri ? pi2 : null} pick={pick} />)}
    {issues.filter(x => x.pos).map((x, i) => <mesh key={'iss' + i} position={toView(x.pos).add(new THREE.Vector3(0, 1.5, 0))}
      geometry={SPHERE} scale={0.8} material={mat('#ff3b3b', 0.8)} />)}
    {sel && <group ref={selRef} position={toView(sel.pos)} />}
    {sel && selObj && <TransformControls object={selObj} mode="translate" size={0.8}
      onMouseDown={() => { from0.current = selObj.position.toArray() }}
      onMouseUp={() => { if (changed(from0.current, selObj.position.toArray(), 1e-5)) onDrag(fromView(selObj.position)) }} />}
    {sel && <Html position={toView(sel.pos).add(new THREE.Vector3(0, 2, 0))} center style={{ pointerEvents: 'none' }}>
      <div className="tag">{sel.node}{sel.new ? ' (new)' : ''}</div></Html>}
    <OrbitControls makeDefault enableDamping={false} maxDistance={3000} />
    <Rig focus={focus} target={target} />
  </>
}

function Rig({ focus, target }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    if (!controls) return
    const c = toView(focus.p)
    controls.target.copy(c)
    camera.position.set(c.x + 22, c.y + 26, c.z + 22)
    controls.update()
  }, [focus.t, controls])
  useEffect(() => { if (controls) target.current = controls.target })
  return null
}

function Arrow({ a, b, color }) {
  const A = toView(a), B = toView(b)
  const d = new THREE.Vector3().subVectors(B, A)
  const L = d.length()
  if (L < 0.5) return null
  const q = new THREE.Quaternion().setFromUnitVectors(UP, d.clone().normalize())
  const p = A.clone().add(d.multiplyScalar(0.62))
  return <mesh position={p} quaternion={q} geometry={CONE} material={mat(color)} />
}

function RouteDraw({ r, i, sel, pi, pi2, pick }) {
  const cb = useUi().prefs.cb
  const c = kindColor(r.kind, cb)
  const mark = KIND_MARK[r.kind] || KIND_MARK.goto
  const width = sel ? 4 : 2
  if (r.kind === 'navblocks') {
    return <>{r.points.map((b, j) => {
      const o = b.orient || [0, 0, 0, 1]
      const q = b.new ? quatToView(o) : quatToView([-o[0], -o[1], -o[2], o[3]])
      return <group key={j} position={toView(b.pos)} quaternion={q} onClick={ev => { if (!isClick(ev)) return; ev.stopPropagation(); pick(i, j, ev) }}>
        <mesh geometry={BOX} scale={b.size.map(Number)} material={mat(b.new ? '#3cff8a' : c, j === pi && sel ? 0.5 : 0.22)} />
      </group>
    })}</>
  }
  if (r.kind === 'neighborhoods') {
    return <>{r.points.map((h, j) => {
      const R = h.radius || 50
      const pts = Array.from({ length: 49 }, (_, k) => { const a = k / 48 * Math.PI * 2; return toView([h.pos[0] + R * Math.cos(a), h.pos[1] + 0.3, h.pos[2] + R * Math.sin(a)]) })
      return <Line key={j} points={pts} color={c} lineWidth={sel ? 3 : 1.5} />
    })}</>
  }
  const segs = []
  if (r.kind === 'signposts') {
    const by = Object.fromEntries(r.points.map(p => [p.node, p]))
    const seen = new Set()
    for (const p of r.points) for (const q of p.connections || []) {
      const k = [p.node, q].sort().join()
      if (by[q] && !seen.has(k)) { seen.add(k); segs.push([p.pos, by[q].pos, p.new || by[q].new, false]) }
    }
  } else if (r.kind === 'traffic') {
    const by = Object.fromEntries(r.points.map(p => [p.node, p]))
    for (const p of r.points) for (const q of p.next || []) if (by[q]) segs.push([p.pos, by[q].pos, p.new || by[q].new, true])
  } else {
    for (let k = 0; k + 1 < r.points.length; k++) segs.push([r.points[k].pos, r.points[k + 1].pos, r.points[k].new || r.points[k + 1].new, true])
  }
  return <>
    {segs.map(([a, b, nw, dir], k) => <React.Fragment key={k}>
      <Line points={[toView(a).add(new THREE.Vector3(0, 0.3, 0)), toView(b).add(new THREE.Vector3(0, 0.3, 0))]}
        color={nw ? '#3cff8a' : c} lineWidth={width} dashed={!!mark.dash} dashSize={mark.dash ? mark.dash[0] : 1} gapSize={mark.dash ? mark.dash[1] : 1} />
      {dir && <Arrow a={[a[0], a[1] + 0.3, a[2]]} b={[b[0], b[1] + 0.3, b[2]]} color={nw ? '#3cff8a' : c} />}
    </React.Fragment>)}
    {r.points.map((p, j) => <mesh key={p.node} position={toView(p.pos).add(new THREE.Vector3(0, 0.3, 0))} geometry={POINT_GEO[mark.shape] || SPHERE}
      scale={sel && (j === pi || j === pi2) ? 1.8 : 1} material={mat(p.new ? '#3cff8a' : sel && j === pi ? '#ffffff' : sel && j === pi2 ? '#ffe66d' : c)}
      onClick={ev => { if (!isClick(ev)) return; ev.stopPropagation(); pick(i, j, ev) }} />)}
  </>
}
