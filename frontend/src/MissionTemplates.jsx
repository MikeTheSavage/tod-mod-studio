// Mission templates: pick a mission type, place its giver and points on a map, set its numbers, check, build and install.
// Backend: todms/missions_tpl.py (/api/missiontpl). All text here is for modders: no internal names.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import { spotOverlay } from './LoaderTopView.jsx'
import View3D from './View3D.jsx'
import { useBundle, pickOfBlock, pickOfMapName, boundsOf, CONTEXT_LAYERS } from './levelLoad.js'
import { useUI, Menu, Pipeline, CheckRow, RangeField, Advanced, Switch, UndoRedo } from './ui.jsx'
import { useHistory, useUndoKeys } from './history.js'
import { MeterStrip } from './Meters.jsx'
import { ProblemsBadge } from './ProblemsPanel.jsx'
import Snapshots from './Snapshots.jsx'
import { useStore, registerProject, setOpen as openProblems, useJump } from './problemsStore.js'
import { useAutosave, loadAutosave } from './autosave.js'
import { t as tr } from './i18n.js'

const short = e => (e || '').split('/').pop()
const round = v => Math.round(v * 100) / 100
const DOWNTOWN = 'submap01_map02_lostoros_downtown.submap'
const UNIT = { deg: '°', pts: 'pts' }
const COLORS = ['#3ec5e8', '#4dc27d', '#d9a21b', '#b27df0', '#f08a50', '#5bb3f5', '#e56fa0']

const uniqueId = (taken, base) => { let i = 1; while (taken.includes(base + i)) i++; return base + i }
const blank = () => ({ name: 'My missions', hosts: [], missions: [], options: {} })

// ---------------------------------------------------------------- small inputs
function Num({ value, onChange, min, max, step = 'any', nullable = false, placeholder }) {
  return <input type="number" step={step} min={min} max={max} value={value ?? ''} placeholder={placeholder}
    onChange={e => { const t = e.target.value; onChange(t === '' ? (nullable ? null : 0) : Number(t)) }} />
}

function PointInput({ value, onChange, onPlace, placing, label }) {
  const v = value || [0, null, 0]
  const set = (i, x) => onChange(v.map((n, j) => j === i ? x : n))
  return <div className="row" style={{ alignItems: 'center' }}>
    <div className="row3" style={{ flex: 1 }}>
      <label className="kv" style={{ margin: 0 }}>{tr('x_11f6ad')}<Num value={v[0]} onChange={x => set(0, x)} /></label>
      <label className="kv" style={{ margin: 0 }}>{tr('height_73e7e5')}<Num value={v[1]} nullable placeholder={tr('ground')} onChange={x => set(1, x)} /></label>
      <label className="kv" style={{ margin: 0 }}>{tr('z')}<Num value={v[2]} onChange={x => set(2, x)} /></label>
    </div>
    <button className={placing ? 'primary' : ''} title={tr('then_click_the_map')} onClick={onPlace}>{placing ? 'Click the map' : 'Place'}</button>
  </div>
}

function RectInput({ value, onChange, onPlace, placing }) {
  const v = value || [0, 0, 0, 0]
  return <div className="row" style={{ alignItems: 'center' }}>
    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
      {['west x', 'south z', 'east x', 'north z'].map((l, i) => <label className="kv" key={i} style={{ margin: 0 }}>{l}
        <Num value={v[i]} onChange={x => onChange(v.map((n, j) => j === i ? x : n))} /></label>)}
    </div>
    <button className={placing ? 'primary' : ''} title={tr('then_click_two_opposite_corners_on')} onClick={onPlace}>{placing ? 'Click 2 corners' : 'Place'}</button>
  </div>
}

function Field({ p, value, isSet, onChange, reset, placing, setPlacing }) {
  const k = p.kind
  const unit = p.unit ? (UNIT[p.unit] || p.unit) : ''
  const numeric = k === 'float' || k === 'int' || k === 'angle'
  if (numeric && p.min != null && p.max != null) {
    return <RangeField label={p.label} help={p.help} value={value} min={p.min} max={p.max} step={k === 'int' ? 1 : undefined} def={p.default} unit={unit}
      changed={isSet && value !== p.default} onChange={onChange} onReset={reset} digits={4} />
  }
  let input = null
  if (numeric) input = <Num value={value} nullable={p.default == null} min={p.min} max={p.max} step={k === 'int' ? 1 : 'any'} onChange={onChange} />
  else if (k === 'bool') input = <label className="check"><Switch label={p.label} on={!!value} onChange={onChange} /> <span>{value ? 'On' : 'Off'}</span></label>
  else if (k === 'text') input = (p.max_len || 0) > 60 ? <textarea rows={3} value={value ?? ''} onChange={e => onChange(e.target.value)} /> : <input value={value ?? ''} onChange={e => onChange(e.target.value)} />
  else if (k === 'choice') input = <select value={value ?? ''} onChange={e => onChange(e.target.value)}>{(p.choices || []).map(c => <option key={c} value={c}>{c}</option>)}</select>
  else if (k === 'point') input = <PointInput value={value} onChange={onChange} placing={placing?.key === p.key} onPlace={() => setPlacing({ key: p.key, kind: 'point' })} />
  else if (k === 'rect') input = <RectInput value={value} onChange={onChange} placing={placing?.key === p.key} onPlace={() => setPlacing({ key: p.key, kind: 'rect', corner: 0 })} />
  else if (k === 'points') {
    const list = value || []
    const fixed = p.min_len != null && p.min_len === p.max_len
    input = <div>{list.map((pt, i) => <div key={i} className="row" style={{ alignItems: 'center', marginBottom: 4 }}>
      <b style={{ width: 22 }}>{i + 1}</b>
      <div style={{ flex: 1 }}><PointInput value={pt} placing={placing?.key === p.key && placing.index === i}
        onChange={x => onChange(list.map((q, j) => j === i ? x : q))} onPlace={() => setPlacing({ key: p.key, kind: 'points', index: i })} /></div>
      {!fixed && list.length > (p.min_len || 0) && <button className="sm" title={tr('remove_this_point')} onClick={() => onChange(list.filter((_, j) => j !== i))}>{tr('x_11f6ad')}</button>}
    </div>)}
      {!fixed && list.length < (p.max_len || 99) && <button className="sm" onClick={() => { const last = list[list.length - 1] || [0, null, 0]; setPlacing({ key: p.key, kind: 'points', index: list.length }); onChange([...list, [last[0] + 3, last[1], last[2] + 3]]) }}>{tr('add_a_point')}</button>}
    </div>
  } else if (k === 'rects') {
    const list = value || []
    input = <div>{list.map((r, i) => <div key={i} className="row" style={{ alignItems: 'center', marginBottom: 4 }}>
      <b style={{ width: 22 }}>{i + 1}</b>
      <div style={{ flex: 1 }}><RectInput value={r} placing={placing?.key === p.key && placing.index === i}
        onChange={x => onChange(list.map((q, j) => j === i ? x : q))} onPlace={() => setPlacing({ key: p.key, kind: 'rects', index: i, corner: 0 })} /></div>
      <button className="sm" title={tr('remove')} onClick={() => onChange(list.filter((_, j) => j !== i))}>{tr('x_11f6ad')}</button></div>)}
      <button className="sm" onClick={() => { onChange([...list, [0, 0, 6, 6]]); setPlacing({ key: p.key, kind: 'rects', index: list.length, corner: 0 }) }}>{tr('add_a_rectangle')}</button></div>
  } else if (k === 'floats' || k === 'texts') {
    const list = value || []
    input = <div className="row" style={{ flexWrap: 'wrap' }}>{list.map((x, i) => <div key={i} style={{ width: k === 'texts' ? '100%' : 70 }}>
      {k === 'floats' ? <Num value={x} onChange={n => onChange(list.map((q, j) => j === i ? n : q))} />
        : <input value={x} onChange={e => onChange(list.map((q, j) => j === i ? e.target.value : q))} />}</div>)}</div>
  } else input = <i className="muted">{JSON.stringify(value)}</i>
  return <div className="field">
    <div className="fieldhead" title={p.help || undefined}><span className="l">{p.label}</span>
      {isSet ? <span className="d chg" role="button" tabIndex={0} onClick={reset} onKeyDown={e => e.key === 'Enter' && reset()}>{tr('use_the_default')}</span> : <span className="d">{tr('default')}</span>}</div>
    {input}
  </div>
}

// ---------------------------------------------------------------- the top view
function itemsOf(sc, vals) {
  const out = []
  const has = k => vals[k] != null
  for (const p of sc.params) {
    const v = vals[p.key]
    if (v == null) continue
    if (p.kind === 'point') {
      if (p.key === 'giver_pos') out.push({ id: p.key, key: p.key, shape: 'box', pos: v, size: vals.giver_size || 6, yaw: vals.giver_yaw || 0, label: 'giver', main: true })
      else {
        const base = p.key.replace(/_(pos|zone|centre|center)$/, '')
        const w = vals[p.key + '_width'] ?? vals[base + '_width'] ?? vals[p.key + '_w'] ?? vals[base + '_w']
        const l = vals[p.key + '_length'] ?? vals[base + '_length'] ?? vals[p.key + '_l'] ?? vals[base + '_l']
        if (typeof w === 'number' && typeof l === 'number') out.push({ id: p.key, key: p.key, shape: 'box', pos: v, size: [w, l], yaw: 0, label: p.label })
        else out.push({ id: p.key, key: p.key, shape: 'dot', pos: v, label: p.label })
      }
    } else if (p.kind === 'points') {
      v.forEach((pt, i) => out.push({ id: p.key + ':' + i, key: p.key, index: i, shape: p.key === 'gates' && vals.gate_radii?.[i] ? 'circle' : 'dot', radius: vals.gate_radii?.[i], pos: pt, label: (p.label.split(' ')[0] || '') + ' ' + (i + 1), short: String(i + 1) }))
    } else if (p.kind === 'rect') out.push({ id: p.key, key: p.key, shape: 'rect', rect: v, label: p.label })
    else if (p.kind === 'rects') v.forEach((r, i) => out.push({ id: p.key + ':' + i, key: p.key, index: i, shape: 'rect', rect: r, label: p.label + ' ' + (i + 1) }))
  }
  return out
}

// The host map as overlays for the shared 3D view: play area, props, reserved spots, loader boxes, the other missions'
// givers and the things this mission places. `g` is the ground height used where a point has none of its own.
function hostOverlays({ geom, loaders, others, items, active, g }) {
  const out = []
  const flat = { y: g, ground: g, pickable: false, layer: 'host' }
  if (geom?.plan) out.push({ id: 'h:plan', kind: 'plan', png: geom.plan.png, rect: geom.plan.rect, y: g - 0.1, pickable: false, layer: 'host' })
  if (geom?.bounds) out.push({ id: 'h:bounds', kind: 'zone', rect: geom.bounds, h: 0.4, color: '#8491a1', opacity: 0.04, ...flat })
  if (geom?.area) out.push({ id: 'h:area', kind: 'zone', rect: geom.area, h: 3, color: '#3fbf5a', opacity: 0.1, ...flat })
  ;(geom?.obstacles || []).forEach((o, i) => out.push({ id: 'h:o' + i, kind: 'zone', rect: o, h: 5, color: '#7d8896', opacity: 0.3, ...flat }))
  ;(geom?.reserved || []).forEach((o, i) => out.push({ id: 'h:r' + i, kind: 'zone', rect: o, h: 4, color: '#f2a541', opacity: 0.15, always: true,
    label: o[4] === 'arrival' ? 'arrival' : o[4] === 'exit_loader' ? 'exit' : undefined, ...flat }))
  ;(loaders || []).forEach((v, i) => out.push(spotOverlay({ ...v, id: 'l' + i }, '#c08aff', { opacity: 0.18, ground: g, pickable: false, layer: 'host' })))
  ;(others || []).forEach((it, i) => { const sz = Array.isArray(it.size) ? it.size : [it.size, it.size]
    out.push({ id: 'g' + i, kind: 'box', pos: it.pos, size: [sz[0], 4, sz[1]], yaw: it.yaw || 0, color: '#7d8896', opacity: 0.18, label: it.label, always: true, ground: g, pickable: false, layer: 'host' }) })
  items.forEach((it, i) => {
    const color = it.main ? '#f2a541' : COLORS[i % COLORS.length]
    const base = { id: it.id, color, label: it.short || it.label, always: true, selected: it.id === active, ground: g, layer: 'items' }
    if (it.shape === 'box') { const sz = Array.isArray(it.size) ? it.size : [it.size, it.size]; out.push({ ...base, kind: 'box', pos: it.pos, size: [sz[0], 4, sz[1]], yaw: it.yaw || 0, label: it.label }) }
    else if (it.shape === 'rect') out.push({ ...base, kind: 'zone', rect: it.rect, h: 5, y: g, opacity: 0.16, label: it.label })
    else out.push({ ...base, kind: 'point', pos: it.pos, radius: it.shape === 'circle' ? it.radius : undefined })
  })
  return out
}

// ---------------------------------------------------------------- the page
export default function MissionTemplates({ status, go }) {
  const ui = useUI()
  const pstore = useStore()
  const [meta, setMeta] = useState({ projects: [], samples: [], types: [], status: null })
  const [cur, setCur] = useState(null)               // { id, project }
  const [dirty, setDirty] = useState(false)
  const [sel, setSel] = useState(null)               // selected mission id
  const [choices, setChoices] = useState(null)
  const [slots, setSlots] = useState(null)
  const [schemas, setSchemas] = useState({})
  const [placing, setPlacing] = useState(null)
  const [placeOpen, setPlaceOpen] = useState(() => window.innerWidth >= 1300)
  const [active, setActive] = useState(null)
  const [msgs, setMsgs] = useState(null)             // validate result
  const [built, setBuilt] = useState(null)
  const [busy, setBusy] = useState(null)
  const [note, setNote] = useState('')
  const [loaders, setLoaders] = useState([])
  const [catalog, setCatalog] = useState(null)
  const [addType, setAddType] = useState(null)
  const [areaPick, setAreaPick] = useState(null)     // host id whose play area rectangle is being clicked in
  const [areaCorner, setAreaCorner] = useState(null)
  const [vw, setVw] = useState('pick')              // 'pick' (kinds) or 'place' (map and settings)
  const [busyPct, setBusyPct] = useState(null)
  const [showAll, setShowAll] = useState(false)

  const project = cur?.project
  useEffect(() => { if (project) registerProject('mission', cur.id || null, project) }, [project, cur?.id])
  useAutosave('mission', cur?.id || null, project, dirty && !!project)
  useJump('mtpl', ref => { if (ref.sample) { if (!meta.samples.some(x => x.key === ref.sample)) return false; openSample(ref.sample); return true } if (ref.mission && project?.missions.some(m => m.id === ref.mission)) setSel(ref.mission); return true })
  const refreshMeta = async () => { const m = await get('/api/missiontpl'); setMeta(m); return m }
  const refreshSlots = async () => { try { setSlots(await runJob('/api/missiontpl', { action: 'slots' })) } catch (e) { setNote(e.message) } }
  useEffect(() => { refreshMeta().then(async m => { if (m.projects.length && !cur) pick(m.projects[0]); const d = await loadAutosave('mission', null); if (d) { setCur({ id: null, project: d.project }); setDirty(true); setSel(d.project.missions?.[0]?.id || null); ui.say(tr('your_last_unsaved_changes_are_back')) } }).catch(e => setNote(e.message)); refreshSlots()
    runJob('/api/missiontpl', { action: 'hosts' }).then(setChoices).catch(e => setNote(e.message))
    get('/api/catalog').then(setCatalog).catch(() => {}) }, [])
  const pick = p => { loadAutosave('mission', p.id).then(a => { if (a) { setCur(c => c && c.id === p.id ? ({ ...c, project: a.project }) : c); setDirty(true); ui.say(tr('your_last_unsaved_changes_are_back')) } }); hist.clear(); setCur({ id: p.id, project: structuredClone(p.project), build: p.build }); setDirty(false); setMsgs(null); setBuilt(p.build?.ok ? p.build : null); setSel(p.project.missions?.[0]?.id || null); setPlacing(null); setActive(null); setVw(p.project.missions?.length ? 'place' : 'pick') }
  const curRef = useRef(cur); curRef.current = cur
  const hist = useHistory(() => curRef.current?.project, v => { setCur(c => c && ({ ...c, project: v })); setDirty(true); setMsgs(null); setBuilt(null) })
  useUndoKeys(hist)
  const edit = next => { hist.record(); setCur({ ...cur, project: next }); setDirty(true); setMsgs(null); setBuilt(null) }
  const mission = project?.missions.find(m => m.id === sel)
  const host = project?.hosts.find(h => h.id === mission?.host)
  const typeInfo = t => meta.types.find(x => x.name === t)

  // schemas of every mission (cached per type + host + host definitions)
  const hostKey = JSON.stringify(project?.hosts || [])
  useEffect(() => {
    if (!project) return
    let live = true
    const need = project.missions.filter(m => m.host && !schemas[m.type + '|' + m.host + '|' + hostKey])
    const seen = new Set()
    ;(async () => {
      for (const m of need) {
        const key = m.type + '|' + m.host + '|' + hostKey
        if (seen.has(key)) continue
        seen.add(key)
        try { const sc = await runJob('/api/missiontpl', { action: 'schema', project, type: m.type, host: m.host }); if (live) setSchemas(s => ({ ...s, [key]: sc })) }
        catch (e) { if (live) setSchemas(s => ({ ...s, [key]: { error: e.message, params: [] } })) }
      }
    })()
    return () => { live = false }
  }, [project?.missions.map(m => m.type + m.host).join(','), hostKey])
  const schemaOf = m => m && schemas[m.type + '|' + m.host + '|' + hostKey]
  const sc = schemaOf(mission)

  // loader boxes of an existing host (reference only)
  useEffect(() => {
    setLoaders([])
    if (host?.kind === 'existing' && host.block) runJob('/api/sections/catalog', { entries: [host.block] }).then(c => setLoaders(c.volumes || [])).catch(() => {})
  }, [host?.block])

  const valuesOf = (m, s) => { const v = {}; for (const p of s?.params || []) v[p.key] = m.params?.[p.key] !== undefined ? m.params[p.key] : p.default; return v }
  const vals = mission && sc ? valuesOf(mission, sc) : {}
  const items = mission && sc ? itemsOf(sc, vals) : []
  const others = (project?.missions || []).filter(m => m.id !== sel).map(m => { const s = schemaOf(m); if (!s?.params) return null; const v = valuesOf(m, s); return v.giver_pos ? { pos: v.giver_pos, size: v.giver_size || 6, yaw: v.giver_yaw || 0, label: m.params?.name || v.name || m.id, host: m.host } : null }).filter(x => x && x.host === mission?.host)
  const geom = sc?.host || (() => {
    if (!host) return null
    if (host.kind === 'new_map') return choices?.newmaps.find(n => n.id === host.newmap_id)?.maps[host.map_index || 0]?.geometry
    return { area: host.area || [-50, -50, 50, 50], bounds: host.area && host.area.map((v, i) => v + (i < 2 ? -30 : 30)), obstacles: [], reserved: [] }
  })()

  // the host map in 3D: real models under the overlays (the map of an existing section, or the source map of a new map)
  const [showMap, setShowMap] = useState(true)
  const hostPick = useMemo(() => {
    if (!host || !catalog) return null
    if (host.kind === 'existing') return host.block ? pickOfBlock(catalog, host.block) : null
    const m = choices?.newmaps.find(n => n.id === host.newmap_id)?.maps[host.map_index || 0]
    if (m?.geometry?.plan) return null                       // a scene map: its own picture below, not the map it was cloned from
    return m?.source ? pickOfMapName(catalog, m.source) : null
  }, [host?.id, host?.block, host?.newmap_id, host?.map_index, catalog, choices])
  const lvl = useBundle(hostPick, showMap && !!hostPick)
  const ground = geom?.ground_y ?? host?.ground_y ?? 0
  const overlays = useMemo(() => geom ? hostOverlays({ geom, loaders, others, items, active, g: ground }) : [], [geom, loaders, others, items, active, ground])
  const ghost = (() => {
    if (areaPick) return { kind: 'rect', rect: { first: areaCorner }, color: '#3fbf5a', label: tr('play_area'), planeY: ground }
    if (!placing || !sc) return null
    const p = sc.params.find(q => q.key === placing.key)
    if (placing.kind.startsWith('rect')) return { kind: 'rect', rect: { first: placing.corner === 1 ? placing.first : null }, color: '#3ec5e8', label: p?.label, planeY: ground }
    const w = vals[placing.key === 'giver_pos' ? 'giver_size' : null], base = placing.key.replace(/_(pos|zone|centre|center)$/, '')
    const bw = vals[placing.key + '_width'] ?? vals[base + '_width'], bl = vals[placing.key + '_length'] ?? vals[base + '_length']
    const size = typeof w === 'number' ? [w, 4, w] : (typeof bw === 'number' && typeof bl === 'number') ? [bw, 4, bl] : null
    return { kind: 'point', size, color: '#3ec5e8', label: p?.label, planeY: ground }
  })()
  const frameKey = [host?.id, sel, vw].join('|')
  const focus = useMemo(() => {
    const a = geom?.area || geom?.bounds
    const pts = items.flatMap(it => it.rect ? [[it.rect[0], 0, it.rect[1]], [it.rect[2], 0, it.rect[3]]] : it.pos ? [it.pos] : [])
    const b = boundsOf([...(a ? [[a[0], 0, a[1]], [a[2], 0, a[3]]] : []), ...pts], 12)
    return b ? { bounds: b, y: ground } : null
  }, [frameKey, !!geom])
  const setParam = (key, value) => edit({ ...project, missions: project.missions.map(m => m.id === sel ? { ...m, params: { ...m.params, [key]: value } } : m) })
  const resetParam = key => edit({ ...project, missions: project.missions.map(m => { if (m.id !== sel) return m; const p = { ...m.params }; delete p[key]; return { ...m, params: p } }) })
  const place = ([x, z]) => {
    if (areaPick) {
      if (!areaCorner) { setAreaCorner([x, z]); return }
      const a = [Math.min(areaCorner[0], x), Math.min(areaCorner[1], z), Math.max(areaCorner[0], x), Math.max(areaCorner[1], z)].map(round)
      edit({ ...project, hosts: project.hosts.map(h => h.id === areaPick ? { ...h, area: a } : h) }); setAreaPick(null); setAreaCorner(null); return
    }
    if (!placing || !sc) return
    const p = sc.params.find(q => q.key === placing.key), cv = vals[placing.key]
    x = round(x); z = round(z)
    if (placing.kind === 'point') { setParam(placing.key, [x, cv?.[1] ?? null, z]); setPlacing(null) }
    else if (placing.kind === 'points') { const list = [...(cv || [])]; const old = list[placing.index] || [0, null, 0]; list[placing.index] = [x, old[1], z]; setParam(placing.key, list)
      const next = placing.index + 1; setPlacing(p.max_len === p.min_len && next < list.length ? { ...placing, index: next } : null) }
    else if (placing.kind === 'rect' || placing.kind === 'rects') {
      if (placing.corner === 0) { setPlacing({ ...placing, corner: 1, first: [x, z] }); return }
      const f = placing.first, r = [Math.min(f[0], x), Math.min(f[1], z), Math.max(f[0], x), Math.max(f[1], z)]
      if (placing.kind === 'rect') setParam(placing.key, r)
      else { const list = [...(cv || [])]; list[placing.index] = r; setParam(placing.key, list) }
      setPlacing(null)
    }
  }
  const pickItem = it => { setActive(it.id); const p = sc.params.find(q => q.key === it.key); setPlacing({ key: it.key, kind: p.kind, index: it.index, corner: 0 }) }

  // ------------------------------------------------------------ actions
  const save = async () => {
    const p = await post('/api/missiontpl', { action: 'save', id: cur.id, project })
    setCur({ id: p.id, project: p.project, build: p.build }); setDirty(false); await refreshMeta(); return p
  }
  const run = async (name, label) => {
    setBusy(label); setNote('')
    try {
      const p = name === 'uninstall' || name === 'slots' ? cur : await save()
      if (name === 'save') { setNote('Saved'); return }
      const r = await runJob('/api/missiontpl', { action: name, id: p.id, project: p.project || project }, j => { setBusy(j.message || label); setBusyPct(j.total ? 100 * j.done / j.total : null) })
      if (name === 'validate') setMsgs(r)
      if (name === 'build') { setBuilt(r); setMsgs({ ok: r.ok, messages: r.result.messages || [] }); if (r.ok) setNote('Built. Install puts it into your game.') }
      if (name === 'install') setNote(r.message + '. Start the game and walk into the mission box. Saves made before this need the update on the Test saves screen, or pressing the use key at the box closes the game.')
      if (name === 'uninstall') setNote(r.message)
      await refreshMeta(); await refreshSlots()
      if (name !== 'validate') { const m = await get('/api/missiontpl'); const me = m.projects.find(q => q.id === p.id); if (me) setCur(c => ({ ...c, build: me.build })) }
    } catch (e) { setNote(e.message) } finally { setBusy(null) }
  }
  const discardOk = async () => !dirty || await ui.confirm({ title: tr('discard_unsaved_changes'), body: tr('the_changes_to_this_mission_project'), kept: tr('kept_other_mission_projects_your_mod'), ok: tr('discard_changes') })
  const newProject = async () => { if (!(await discardOk())) return; hist.clear(); setCur({ id: null, project: blank() }); setDirty(true); setSel(null); setMsgs(null); setBuilt(null); setVw('pick') }
  const openSample = async key => {
    const s = meta.samples.find(x => x.key === key)
    if (s.uses_all_slots && !(await ui.confirm({ title: `Open "${s.title}"?`, body: `It has ${s.missions} missions and uses ALL 17 new mission slots of a game. Installing it leaves no room for other new missions.`, ok: tr('open_it_anyway'), danger: false }))) return
    if (!(await discardOk())) return
    const p = await post('/api/missiontpl', { action: 'sample', key }); await refreshMeta(); pick(p)
    runJob('/api/missiontpl', { action: 'hosts' }).then(setChoices).catch(() => {})
  }
  const del = async () => {
    if (!cur.id || !(await ui.confirm({ title: tr('delete_this_mission_project'), body: tr('the_project_file_is_deleted_your'), kept: tr('kept_the_game_your_mod_library'), ok: tr('delete_project') }))) return
    try { await post('/api/missiontpl', { action: 'delete', id: cur.id }); const m = await refreshMeta(); setCur(null); setSel(null); if (m.projects[0]) pick(m.projects[0]) } catch (e) { setNote(e.message) }
  }
  const addHostNew = (nid, i) => {
    const nm = choices.newmaps.find(n => n.id === nid), g = nm.maps[i].geometry
    const id = uniqueId(project.hosts.map(h => h.id), (nm.maps[i].name || 'map').replace(/[^A-Za-z0-9]+/g, '_').toLowerCase() + '_')
    edit({ ...project, hosts: [...project.hosts, { id, kind: 'new_map', newmap_id: nid, map_index: i }] })
  }
  const addHostExisting = block => {
    const preset = block === DOWNTOWN ? choices.presets.downtown : null
    const id = uniqueId(project.hosts.map(h => h.id), 'section_')
    edit({ ...project, hosts: [...project.hosts, { id, kind: 'existing', block, ...(preset ? { map_ids_from_slot: preset.map_ids_from_slot, area: preset.area, ground_y: preset.ground_y } : { area: [-20, -20, 20, 20], ground_y: 0 }) }] })
  }
  const addMission = t => {
    if (!project.hosts.length) { setNote('Add a host first: the map or section the mission takes place in.'); return }
    const id = uniqueId(project.missions.map(m => m.id), t + '_')
    edit({ ...project, missions: [...project.missions, { id, type: t, host: sel && mission ? mission.host : project.hosts[0].id, index: 'auto', params: {} }] }); setSel(id); setAddType(null); setVw('place'); setPlacing(null); setActive(null)
  }
  const removeMission = id => { edit({ ...project, missions: project.missions.filter(m => m.id !== id) }); if (sel === id) setSel(null) }
  const installedHere = meta.status?.projects?.[cur?.id]
  const left = slots ? slots.left + (installedHere ? installedHere.count : 0) : null
  const needs = project?.missions.length || 0
  const hostLabel = h => h.kind === 'new_map' ? (choices?.newmaps.find(n => n.id === h.newmap_id)?.maps[h.map_index || 0]?.name || 'new map') : 'Section ' + short(h.block).replace('.submap', '').replace('.map', '').replace(/_/g, ' ')
  const mapIdOf = block => (block.match(/_(map\d\d)_/) || [])[1]
  const shipped = host?.kind === 'existing' && catalog ? (catalog.maps.find(m => m.id === mapIdOf(host.block))?.missions || []).filter(m => m.index != null) : []
  const errors = (msgs?.messages || []).filter(m => m.level === 'error').length

  const removeHost = async h => {
    if (project.missions.some(m => m.host === h.id) && !(await ui.confirm({ title: tr('remove_this_map'), body: tr('missions_in_this_project_use_it'), kept: tr('kept_the_map_itself_your_other'), ok: tr('remove_map_and_missions') }))) return
    edit({ ...project, hosts: project.hosts.filter(x => x.id !== h.id), missions: project.missions.filter(m => m.host !== h.id) })
  }
  const removeInstalled = async () => {
    if (!(await ui.confirm({ title: tr('remove_these_missions_from_the_game'), body: tr('the_missions_of_this_project_stop'), kept: tr('kept_this_project_your_mod_library'), ok: tr('remove_missions') }))) return
    run('uninstall', 'Removing')
  }
  const issuesOf = id => (msgs?.messages || []).filter(m => m.where === id && m.level === 'error').length

  if (!meta.types.length) return <div className="screen"><div className="empty">{note || 'Loading the mission kinds…'}</div></div>

  const placeKinds = sc?.params.filter(p => ['point', 'points', 'rect', 'rects'].includes(p.kind)) || []
  const placeRow = p => {
    const v = vals[p.key]
    const list = Array.isArray(v) && p.kind.endsWith('s') ? v : null
    const want = p.max_len ?? p.min_len
    const ok = p.kind.endsWith('s') ? (list && list.length >= (p.min_len || 1)) : v != null
    const count = list ? (want ? `${list.length} of ${want}` : String(list.length)) : (v != null ? 'placed' : 'click to place')
    const start = () => {
      setActive(p.key)
      if (p.kind === 'point') setPlacing({ key: p.key, kind: 'point' })
      else if (p.kind === 'rect') setPlacing({ key: p.key, kind: 'rect', corner: 0 })
      else if (p.kind === 'points') setPlacing({ key: p.key, kind: 'points', index: list && p.max_len !== p.min_len ? list.length : 0 })
      else setPlacing({ key: p.key, kind: 'rects', index: list ? list.length : 0, corner: 0 })
    }
    return { key: p.key, label: p.label, ok, count, start, on: placing?.key === p.key }
  }
  const nErr = (msgs?.messages || []).filter(m => m.level === 'error').length
  const nWarn = (msgs?.messages || []).filter(m => m.level === 'warn').length
  const nInfo = (msgs?.messages || []).filter(m => m.level !== 'error' && m.level !== 'warn').length
  const hasMissions = project?.missions.length > 0
  const pending = !!busy
  const checkStep = pending && /check/i.test(busy) ? { tone: 'busy', note: busy, pct: busyPct ?? 30 }
    : !msgs ? { tone: 'idle', note: hasMissions ? 'Not checked yet' : 'Add a mission first', action: hasMissions ? 'Check' : undefined, onClick: () => run('validate', 'Checking the missions'), disabled: pending }
    : nErr ? { tone: 'bad', note: `${nErr} problem${nErr === 1 ? '' : 's'} to fix${nWarn ? `, ${nWarn} warning${nWarn === 1 ? '' : 's'}` : ''}`, action: 'Check again', onClick: () => run('validate', 'Checking the missions'), disabled: pending }
    : { tone: nWarn ? 'warn' : 'ok', note: nWarn ? `Passed · ${nWarn} warning${nWarn === 1 ? '' : 's'}` : 'Passed', action: 'Check again', onClick: () => run('validate', 'Checking the missions'), disabled: pending }
  const buildStep = pending && /build/i.test(busy) ? { tone: 'busy', note: busy, pct: busyPct ?? 30 }
    : !hasMissions || nErr ? { tone: 'idle', note: nErr ? 'Fix the problem first' : 'Add a mission first' }
    : built?.ok && !dirty ? { tone: 'ok', note: `Built · ${built.result?.missions?.length || 0} mission${built.result?.missions?.length === 1 ? '' : 's'}`, action: 'Build again', onClick: () => run('build', 'Building the missions'), disabled: pending }
    : { tone: 'ready', note: 'Ready to build (about a minute)', action: 'Build', onClick: () => run('build', 'Building the missions'), disabled: pending }
  const canInstall = !pending && !dirty && cur?.build?.ok && built?.ok
  const installStep = pending && /install/i.test(busy) ? { tone: 'busy', note: busy, pct: busyPct ?? 30 }
    : installedHere && !dirty && built?.ok ? { tone: 'ok', note: 'In the game', action: 'Install again', onClick: () => run('install', 'Installing'), disabled: !canInstall }
    : canInstall ? { tone: 'ready', note: installedHere ? 'Game has an older version' : 'Not in the game yet', action: 'Install into the game', onClick: () => run('install', 'Installing') }
    : { tone: 'idle', note: built?.ok ? 'Save the project first' : 'Waits for the build' }
  const steps = [{ label: tr('check'), ...checkStep }, { label: tr('build'), ...buildStep }, { label: tr('install_into_the_game'), ...installStep }]

  const groups = sc && !sc.error ? ['Placement', 'Settings', 'Scores', 'Texts'].concat([...new Set(sc.params.map(p => p.group))].filter(g => !['Placement', 'Settings', 'Scores', 'Texts'].includes(g))).filter(g => sc.params.some(p => p.group === g)) : []
  const isMain = p => !p.advanced && p.group !== 'Placement' && p.group !== 'Texts'
  const mainParams = sc ? sc.params.filter(isMain) : []
  const advParams = sc ? sc.params.filter(p => !isMain(p) && p.key !== 'name') : []
  const renderField = p => <Field key={p.key} p={p} value={vals[p.key]} isSet={mission.params && mission.params[p.key] !== undefined}
    onChange={v => setParam(p.key, v)} reset={() => resetParam(p.key)} placing={placing} setPlacing={x => { setPlacing(x); setActive(x?.key + (x?.index != null ? ':' + x.index : '')) }} />
  const advSet = advParams.filter(p => mission?.params && mission.params[p.key] !== undefined).length

  return <div className="screen">
    {vw === 'pick' ? (
      <div className="tb">
        <Menu buttonClass="crumbbtn" label={<><em>{tr('project')}</em> {cur?.project?.name || 'Choose a project'}{dirty ? ' *' : ''} {'▾'}</>}>{close => <>
          {meta.projects.length === 0 && <div className="foot">{tr('no_saved_projects_yet')}</div>}
          {meta.projects.map(p => <div key={p.id} className={'item' + (p.id === cur?.id ? ' on' : '')} onClick={async () => { close(); if (p.id !== cur?.id && await discardOk()) pick(p) }}>{p.project.name}</div>)}</>}</Menu>
        {project?.hosts.length > 0 && <span className="muted small">{tr('on_db3d40')}{' '}{project.hosts.map(hostLabel).join(', ')}</span>}
        {dirty && <span className="badge" style={{ background: 'var(--accent-soft)', color: 'var(--accent-text)' }}>{tr('unsaved')}</span>}
        <div style={{ flex: 1 }} />
        <Menu right label={<>{tr('open_a_sample')}{'…'}</>}>{close => <>{meta.samples.map(s => <div key={s.key} className="item" onClick={() => { close(); openSample(s.key) }}>{s.title}</div>)}</>}</Menu>
        <UndoRedo h={hist} compact />
        <button onClick={newProject}>{tr('new_project')}</button>
        {cur?.id && <button className="danger" disabled={!!busy || !!installedHere} onClick={del} title={installedHere ? 'Remove it from the game first' : ''}>{tr('delete_project')}</button>}
      </div>
    ) : (
      <div className="tb">
        <button onClick={() => setVw('pick')}>{'‹'}{' '}{tr('all_kinds')}</button>
        <div style={{ fontWeight: 600 }}>{mission?.params?.name || mission?.id || 'Mission'}</div>
        {mission && <span className="badge">{typeInfo(mission.type)?.title || mission.type}</span>}
        {project?.hosts.length > 1 && mission && <select aria-label={tr('map_of_this_mission')} style={{ width: 'auto', maxWidth: 220 }} value={mission.host}
          onChange={e => edit({ ...project, missions: project.missions.map(m => m.id === sel ? { ...m, host: e.target.value, params: {} } : m) })}>
          {project.hosts.map(h => <option key={h.id} value={h.id}>{hostLabel(h)}</option>)}</select>}
        <div style={{ flex: 1 }} />
        <span className="small muted wide-only" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{placing ? (placing.kind.startsWith('rect') ? (placing.corner ? 'Click the opposite corner.' : 'Click one corner of the area.') : 'Click where it goes.') : areaPick ? 'Click two opposite corners for the play area.' : 'Click an item, then click the map.'}</span>
        <UndoRedo h={hist} compact />
        <button disabled={!!busy || !dirty} onClick={() => run('save', 'Saving')}>{tr('save_project')}</button>
      </div>
    )}
    {note && <div className="callout neutral" role="status" style={{ margin: 0, padding: '6px 12px', borderRadius: 0, display: 'flex', gap: 8, alignItems: 'center', overflowWrap: 'anywhere' }}>
      <span className="grow">{note}</span><button className="sm" onClick={() => setNote('')}>{tr('dismiss')}</button></div>}
    <MeterStrip kind="mission" data={pstore.data.mission} go={go} extra={project ? <>
      <Snapshots kind="mission" id={cur?.id} getProject={() => project} ensureId={async () => (await save()).id}
                 onLoad={p => { hist.record(); setCur(c => ({ ...c, project: p })); setDirty(true); setMsgs(null); setBuilt(null) }} disabled={!!busy} />
      <ProblemsBadge data={pstore.data.mission} onClick={() => openProblems(!pstore.open)} /></> : null} />
    <div className="split">
      <div className="panel-l" style={{ overflow: 'auto' }}>
        <div style={{ padding: '12px 8px 4px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {project && <label style={{ padding: '0 8px 8px', margin: 0 }}>{tr('project_name')}<input value={project.name} aria-label={tr('project_name')} onChange={e => edit({ ...project, name: e.target.value })} /></label>}
          <div className="upper" style={{ padding: '0 8px 6px' }}>{tr('missions_in_this_project')}</div>
          {project?.missions.map(m => (
            <div key={m.id} className={'sideitem' + (vw === 'place' && sel === m.id ? ' on' : '')} role="button" tabIndex={0}
                 onClick={() => { setSel(m.id); setPlacing(null); setActive(null); setVw('place') }} onKeyDown={e => e.key === 'Enter' && (setSel(m.id), setVw('place'))}>
              <div className="a">{m.params?.name || m.id}</div>
              <div className="b" style={{ color: issuesOf(m.id) ? 'var(--bad)' : msgs ? 'var(--ok)' : undefined }}>{typeInfo(m.type)?.title || m.type}
                {msgs ? (issuesOf(m.id) ? ` · ${issuesOf(m.id)} problem${issuesOf(m.id) === 1 ? '' : 's'}` : ' · ready') : ''}
                {msgs?.index?.[m.id] != null && ` · mission ${msgs.index[m.id]}`}</div>
            </div>))}
          <div className={'sideitem' + (vw === 'pick' ? ' on' : '')} role="button" tabIndex={0} onClick={() => setVw('pick')} onKeyDown={e => e.key === 'Enter' && setVw('pick')}>
            <div className="a" style={{ color: 'var(--accent-text)', fontWeight: 600 }}>{tr('new_mission')}</div></div>
        </div>
        {project && <div style={{ padding: '4px 8px 12px', borderTop: '1px solid var(--line)', marginTop: 4 }}>
          <div className="upper" style={{ padding: '8px 8px 6px' }}>{tr('maps_for_the_missions')}</div>
          {project.hosts.map(h => <div key={h.id} style={{ padding: '2px 8px 6px' }}>
            <div className="row"><b className="grow" style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={hostLabel(h)}>{hostLabel(h)}</b>
              <button className="sm danger" title={tr('remove_this_map_from_the_project')} onClick={() => removeHost(h)}>{tr('remove')}</button></div>
            {h.kind === 'existing' && <Advanced title={tr('play_area_and_start')} note={areaPick === h.id ? 'click the map' : ''}>
              <label className="kv" style={{ margin: 0 }}>{tr('play_area_west_x_south_z')}{' '}<button className="link" onClick={() => { setAreaPick(areaPick === h.id ? null : h.id); setAreaCorner(null); setVw('place') }}>{areaPick === h.id ? 'cancel' : 'set on the map'}</button>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 4 }}>{(h.area || [0, 0, 0, 0]).map((v, i) => <Num key={i} value={v} onChange={x => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, area: q.area.map((n, j) => j === i ? x : n) } : q) })} />)}</div></label>
              <label className="kv">{tr('ground_height_metres')}<Num value={h.ground_y} nullable onChange={x => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, ground_y: x } : q) })} /></label>
              <label className="kv">{tr('start_the_mission_like_this_shipped')}<select value={h.map_ids_from_slot ?? ''} onChange={e => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, map_ids_from_slot: Number(e.target.value) } : q) })}>
                  {h.map_ids_from_slot == null && <option value="">{tr('choose_one')}</option>}
                  {(catalog?.maps.find(m => m.id === mapIdOf(h.block))?.missions || []).filter(m => m.index != null).map(m => <option key={m.index} value={m.index}>{m.title} ({m.index})</option>)}
                  {h.map_ids_from_slot != null && !(catalog?.maps.find(m => m.id === mapIdOf(h.block))?.missions || []).some(m => m.index === h.map_ids_from_slot) && <option value={h.map_ids_from_slot}>{tr('mission')}{' '}{h.map_ids_from_slot}</option>}</select></label>
</Advanced>}
          </div>)}
          <Menu buttonClass="soft" label={<>{tr('add_a_map')}{' '}{'▾'}</>}>{close => <>
            <div className="grp" style={{ paddingTop: 0 }}>{tr('your_new_maps')}</div>
            {choices?.newmaps.length === 0 && <div className="foot" style={{ border: 0, marginTop: 0 }}>{tr('none_yet_make_one_in_new')}</div>}
            {choices?.newmaps.flatMap(n => n.maps.map((m, i) => {
              const used = m.error || project.hosts.some(h => h.kind === 'new_map' && h.newmap_id === n.id && (h.map_index || 0) === i)
              return <div key={n.id + i} className={'item' + (used ? ' off' : '')} onClick={() => { if (used) return; close(); addHostNew(n.id, i) }}>{m.name}</div>
            }))}
            <div className="grp">{tr('a_part_of_an_existing_map')}</div>
            {(choices?.existing || []).map(h => <div key={h.block} className={'item' + (!h.offer ? ' off' : '')} title={h.offer ? h.proven : h.reason} onClick={() => { if (!h.offer) return; close(); addHostExisting(h.block) }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.block.replace('.submap', '').replace('.map', '').replace(/_/g, ' ')}</span>
              <span className="hint">{!h.offer ? 'cannot host' : /^proven/.test(h.proven || '') ? 'tested' : 'not tested'}</span></div>)}
</>}</Menu>
        </div>}
      </div>

      {vw === 'pick' && <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{tr('pick_a_kind_of_mission')}</div>
</div>
        {!project && <div className="callout neutral" style={{ marginBottom: 12 }}>{tr('open_a_sample_or_start_a')}</div>}
        {project && !project.hosts.length && <div className="callout warn" style={{ marginBottom: 12 }}><b>{tr('add_a_map_first')}</b>{' '}{tr('use')}{' '}{'“'}{tr('add_a_map')}{'”'}{' '}{tr('on_the_left')}</div>}
        <div className="cards">
          {meta.types.map(t => <div key={t.name} title={'The map needs ' + (t.host_needs || []).map(n => n.replace(/\.$/, '')).join('; ')} className={'card sm' + (addType === t.name ? ' sel' : '')} role="button" tabIndex={0} onClick={() => setAddType(t.name)} onKeyDown={e => e.key === 'Enter' && setAddType(t.name)} style={{ cursor: 'pointer' }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{t.title}</div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', textWrap: 'pretty' }}>{t.summary}</div>
            {addType === t.name && <>
              <button className="primary" style={{ marginTop: 4 }} disabled={!project} onClick={e => { e.stopPropagation(); addMission(t.name) }}>{tr('use_this_kind')}</button></>}
          </div>)}
        </div>
      </div>}

      {vw === 'place' && <>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="vp" style={{ flex: 1, minHeight: 0 }}>
            {geom ? <View3D defaultMode="top" bundle={lvl.bundle} view={lvl.view} layers={CONTEXT_LAYERS} overlays={overlays} focus={focus} planeY={ground}
                onPickOverlay={id => { const it = items.find(q => q.id === id); if (it) pickItem(it) }}
                placing={ghost} onPlace={pos => place([pos[0], pos[2]])} style={{ position: 'absolute', inset: 0 }} />
              : <div className="vp" style={{ position: 'absolute', inset: 0 }}><div className="empty">{project?.hosts.length ? (hasMissions ? 'Choose a mission on the left to see its map.' : 'Pick a kind of mission first.') : 'Add a map on the left: the place the missions happen in.'}</div></div>}
            {geom && placeKinds.length > 0 && !placeOpen && <button className="sm" style={{ position: 'absolute', left: 12, top: 12 }} onClick={() => setPlaceOpen(true)} title={tr('show_the_list_of_things_to')}>{tr('place_on_the_map')}{' '}{'▸'}</button>}
            {geom && placeKinds.length > 0 && placeOpen && <div style={{ position: 'absolute', left: 12, top: 12, width: 228, padding: 8, border: '1px solid var(--line)', borderRadius: 'var(--r-lg)', background: 'var(--surface)', boxShadow: 'var(--shadow-1)' }}>
              <div className="row" style={{ padding: '0 4px 6px' }}><div className="upper grow">{tr('place_on_the_map')}</div>
                <button className="sm ghost" onClick={() => setPlaceOpen(false)} title={tr('hide_this_list')} aria-label={tr('hide_the_list')}>{'◂'}</button></div>
              {placeKinds.map(placeRow).map(r => <div key={r.key} role="button" tabIndex={0} onClick={r.start} onKeyDown={e => e.key === 'Enter' && r.start()}
                style={{ display: 'flex', alignItems: 'center', gap: 8, height: 28, padding: '0 6px', borderRadius: 'var(--r-sm)', cursor: 'pointer', background: r.on ? 'var(--accent-soft)' : r.ok ? 'transparent' : 'var(--bad-soft)' }}>
                <span style={{ width: 16, textAlign: 'center', fontWeight: 700, color: r.ok ? 'var(--ok)' : 'var(--bad)' }}>{r.ok ? '✓' : '×'}</span>
                <span style={{ flex: 1, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.label}</span>
                <span style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{r.count}</span></div>)}
            </div>}
            {geom && hostPick && <span style={{ position: 'absolute', right: 98, top: 12, zIndex: 5, display: 'flex', gap: 8, alignItems: 'center' }}>
              {lvl.busy && <span className="small muted">{lvl.busy}{'…'}</span>}{lvl.err && <span className="small warn" title={lvl.err}>{tr('no_map')}</span>}
              <button className={'sm' + (showMap ? ' on' : '')} aria-pressed={showMap} title={tr('draw_the_map_under_the_placements')} onClick={() => setShowMap(!showMap)}>{tr('map')}</button></span>}
            {geom && <span className="floatpanel" style={{ left: 12, bottom: 12, cursor: 'help', pointerEvents: 'auto' }} title={tr('green_play_area_grey_buildings_and')}>?</span>}
          </div>
          <div className="checks" style={{ flex: 'none', borderTop: '1px solid var(--line)' }}>
            <div className="ch"><span style={{ fontWeight: 600 }}>{tr('check_results')}</span>
              {msgs ? <>{nErr > 0 && <span style={{ color: 'var(--bad)', fontSize: 12 }}>{nErr}{' '}{tr('to_fix')}</span>}{nWarn > 0 && <span style={{ color: 'var(--warn)', fontSize: 12 }}>{nWarn}{' '}{tr('warning')}{nWarn === 1 ? '' : 's'}</span>}
                <span style={{ color: 'var(--ok)', fontSize: 12 }}>{nErr + nWarn === 0 ? 'Nothing to fix' : ''}</span></> : <span className="muted" style={{ fontSize: 12 }}>{tr('not_checked_yet')}</span>}
              <span style={{ flex: 1 }} />
              {msgs && nInfo > 0 && <button className="link" onClick={() => setShowAll(!showAll)}>{showAll ? 'Hide' : 'Show'} {nInfo}{' '}{tr('note')}{nInfo === 1 ? '' : 's'}</button>}
              <button className="sm" disabled={!!busy || !hasMissions} onClick={() => run('validate', 'Checking the missions')}>{msgs ? 'Check again' : 'Check'}</button></div>
            <div style={{ maxHeight: 132, overflow: 'auto' }}>
              {(msgs?.messages || []).filter(m => showAll || m.level === 'error' || m.level === 'warn').map((m, i) => {
                const can = m.where && project?.missions.some(x => x.id === m.where)
                return <CheckRow key={i} tone={m.level === 'error' ? 'bad' : m.level === 'warn' ? 'warn' : 'info'} title={m.text} fix={m.where && m.where !== 'project' ? `(${m.where})` : ''}
                  action={can && sel !== m.where ? 'Show me' : null} onAction={() => { setSel(m.where); setVw('place') }} />
              })}
              {msgs && !msgs.messages.length && <CheckRow tone="ok" title={tr('nothing_to_fix')} />}
              {built?.ok && built.result && <details style={{ padding: '6px 12px' }}><summary className="small">{tr('built')}{' '}{built.result.missions.length}{' '}{tr('mission')}{built.result.missions.length === 1 ? '' : 's'}{' '}{tr('in_one_package')}{Math.round(built.result.bytes / 1048576)}{' '}{tr('mb_e89828')}</summary>
                <table className="tbl small"><thead><tr><th>{tr('mission_e4698d')}</th><th>{tr('kind')}</th><th>{tr('number')}</th><th>{tr('giver_at')}</th></tr></thead><tbody>
                  {built.result.missions.map(m => <tr key={m.project + m.id}><td>{m.name}</td><td>{typeInfo(m.type)?.title || m.type}</td><td>{m.index}</td><td>{m.giver.pos.map(round).join(', ')}</td></tr>)}</tbody></table>
                </details>}
            </div>
          </div>
        </div>
        <div className="panel-r wide">
          <div className="panel-h"><div className="grow"><div className="t" style={{ fontWeight: 600 }}>{tr('settings')}</div></div></div>
          <div className="panel-b" style={{ gap: 14 }}>
            {!mission && <div className="muted">{tr('pick_a_kind_first')}</div>}
            {mission && <>
              {mission.type === 'chase' && <p className="warn small">{tr('always_plays_in_downtown_only_the')}</p>}
              {!sc && <p className="muted">{tr('loading_the_settings')}{'…'}</p>}
              {sc?.error && <p className="bad">{sc.error}</p>}
              {sc && !sc.error && <>
                <div><div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }}>{tr('mission_name')}</div>
                  <input aria-label={tr('mission_name')} value={mission.params?.name ?? vals.name ?? ''} onChange={e => setParam('name', e.target.value)} /></div>
                {mainParams.filter(p => p.key !== 'name').map(renderField)}
                {advParams.length > 0 && <Advanced title={tr('advanced')} note={advSet ? `${advParams.length} more, ${advSet} changed` : `${advParams.length} more, all on default`}>
                  {groups.filter(g => advParams.some(p => p.group === g)).map(g => <div key={g}><h4>{g === 'Placement' ? 'Exact positions' : g}</h4>{advParams.filter(p => p.group === g).map(renderField)}</div>)}
                </Advanced>}
              </>}
            </>}
          </div>
          {mission && <div className="panel-f"><button className="danger" onClick={() => removeMission(mission.id)}>{tr('remove_this_mission')}</button></div>}
        </div>
      </>}
    </div>
    <Pipeline steps={steps} removeLabel={tr('remove_missions_from_the_game')} onRemove={removeInstalled} removeDisabled={!!busy || !installedHere} />
    {busy && !/check|build|install/i.test(busy) && <div className="busy">{busy}</div>}
  </div>
}
