// Mission templates: pick a mission type, place its giver and points on a map, set its numbers, check, build and install.
// Backend: todms/missions_tpl.py (/api/missiontpl). All text here is for modders: no internal names.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import { spotYaw } from './LoaderTopView.jsx'

const short = e => (e || '').split('/').pop()
const round = v => Math.round(v * 100) / 100
const DOWNTOWN = 'submap01_map02_lostoros_downtown.submap'
const LEVEL_COLOR = { error: '#ff6b6b', warn: '#f2c14e', info: '#8b97a6' }
const COLORS = ['#55dbff', '#79ee96', '#ffd166', '#c08aff', '#ff9f6b', '#6bd0ff', '#f78fb3']

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
      <label className="kv" style={{ margin: 0 }}>x<Num value={v[0]} onChange={x => set(0, x)} /></label>
      <label className="kv" style={{ margin: 0 }}>height<Num value={v[1]} nullable placeholder="ground" onChange={x => set(1, x)} /></label>
      <label className="kv" style={{ margin: 0 }}>z<Num value={v[2]} onChange={x => set(2, x)} /></label>
    </div>
    <button className={placing ? 'primary' : ''} title="Then click the map" onClick={onPlace}>{placing ? 'Click the map' : 'Place'}</button>
  </div>
}

function RectInput({ value, onChange, onPlace, placing }) {
  const v = value || [0, 0, 0, 0]
  return <div className="row" style={{ alignItems: 'center' }}>
    <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
      {['west x', 'south z', 'east x', 'north z'].map((l, i) => <label className="kv" key={i} style={{ margin: 0 }}>{l}
        <Num value={v[i]} onChange={x => onChange(v.map((n, j) => j === i ? x : n))} /></label>)}
    </div>
    <button className={placing ? 'primary' : ''} title="Then click two opposite corners on the map" onClick={onPlace}>{placing ? 'Click 2 corners' : 'Place'}</button>
  </div>
}

function Field({ p, value, isSet, onChange, reset, placing, setPlacing }) {
  const range = [p.min != null && 'at least ' + p.min, p.max != null && 'at most ' + p.max].filter(Boolean).join(', ')
  const unit = p.unit ? ' ' + ({ deg: 'degrees', pts: 'points' }[p.unit] || p.unit) : ''
  let input = null
  const k = p.kind
  if (k === 'float' || k === 'int' || k === 'angle') input = <Num value={value} nullable={p.default == null} min={p.min} max={p.max} step={k === 'int' ? 1 : 'any'} onChange={onChange} />
  else if (k === 'bool') input = <label className="check"><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} /> <span>{value ? 'On' : 'Off'}</span></label>
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
      {!fixed && list.length > (p.min_len || 0) && <button title="Remove this point" onClick={() => onChange(list.filter((_, j) => j !== i))}>x</button>}
    </div>)}
      {!fixed && list.length < (p.max_len || 99) && <button onClick={() => { const last = list[list.length - 1] || [0, null, 0]; setPlacing({ key: p.key, kind: 'points', index: list.length }); onChange([...list, [last[0] + 3, last[1], last[2] + 3]]) }}>Add a point</button>}
    </div>
  } else if (k === 'rects') {
    const list = value || []
    input = <div>{list.map((r, i) => <div key={i} className="row" style={{ alignItems: 'center', marginBottom: 4 }}>
      <b style={{ width: 22 }}>{i + 1}</b>
      <div style={{ flex: 1 }}><RectInput value={r} placing={placing?.key === p.key && placing.index === i}
        onChange={x => onChange(list.map((q, j) => j === i ? x : q))} onPlace={() => setPlacing({ key: p.key, kind: 'rects', index: i, corner: 0 })} /></div>
      <button title="Remove" onClick={() => onChange(list.filter((_, j) => j !== i))}>x</button></div>)}
      <button onClick={() => { onChange([...list, [0, 0, 6, 6]]); setPlacing({ key: p.key, kind: 'rects', index: list.length, corner: 0 }) }}>Add a rectangle</button></div>
  } else if (k === 'floats' || k === 'texts') {
    const list = value || []
    input = <div className="row" style={{ flexWrap: 'wrap' }}>{list.map((x, i) => <div key={i} style={{ width: k === 'texts' ? '100%' : 70 }}>
      {k === 'floats' ? <Num value={x} onChange={n => onChange(list.map((q, j) => j === i ? n : q))} />
        : <input value={x} onChange={e => onChange(list.map((q, j) => j === i ? e.target.value : q))} />}</div>)}</div>
  } else input = <i className="muted">{JSON.stringify(value)}</i>
  return <div className="field" style={{ margin: '8px 0' }}>
    <div className="row" style={{ alignItems: 'baseline' }}><b style={{ fontWeight: 600 }}>{p.label}</b>
      <span className="muted small">{unit.trim()}{range && ' (' + range + ')'}</span>
      {isSet && <button className="link" style={{ marginLeft: 'auto' }} onClick={reset}>use the default</button>}</div>
    {input}
    <div className="muted small">{p.help}</div>
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

function HostView({ geom, loaders, others, items, placing, active, onPick, onPlace, areaMode }) {
  const W = 900, H = 600
  const [cursor, setCursor] = useState(null)
  const ref = useRef(null)
  const view = useMemo(() => {
    const a = geom?.area || geom?.bounds || [-50, -50, 50, 50]
    const pts = items.flatMap(it => it.rect ? [[it.rect[0], it.rect[1]], [it.rect[2], it.rect[3]]] : it.pos ? [[it.pos[0], it.pos[2]]] : [])
    let ax0 = a[0], az0 = a[1], ax1 = a[2], az1 = a[3]
    for (const [px, pz] of pts) { ax0 = Math.min(ax0, px); az0 = Math.min(az0, pz); ax1 = Math.max(ax1, px); az1 = Math.max(az1, pz) }
    const pad = Math.max(6, 0.06 * Math.max(ax1 - ax0, az1 - az0))
    let x0 = ax0 - pad, z0 = az0 - pad, x1 = ax1 + pad, z1 = az1 + pad
    const scale = Math.min(W / (x1 - x0), H / (z1 - z0))
    x1 = x0 + W / scale; z1 = z0 + H / scale              // use the whole drawing area
    return { x0, z0, x1, z1, scale }
  }, [geom, items])
  const { x0, z0, x1, z1, scale } = view
  const X = x => (x - x0) * scale, Z = z => H - (z - z0) * scale
  const grid = []
  const gstep = (x1 - x0) > 400 ? 50 : (x1 - x0) > 120 ? 20 : 10
  for (let gx = Math.ceil(x0 / gstep) * gstep; gx < x1; gx += gstep) grid.push(<g key={'x' + gx}><line x1={X(gx)} x2={X(gx)} y1={0} y2={H} stroke="#222b36" /><text x={X(gx) + 2} y={H - 3} fill="#566274" fontSize={9}>{gx}</text></g>)
  for (let gz = Math.ceil(z0 / gstep) * gstep; gz < z1; gz += gstep) grid.push(<g key={'z' + gz}><line y1={Z(gz)} y2={Z(gz)} x1={0} x2={W} stroke="#222b36" /><text x={2} y={Z(gz) - 2} fill="#566274" fontSize={9}>{gz}</text></g>)
  const rectEl = (r, props) => <rect x={X(Math.min(r[0], r[2]))} y={Z(Math.max(r[1], r[3]))} width={Math.abs(r[2] - r[0]) * scale} height={Math.abs(r[3] - r[1]) * scale} {...props} />
  const polygon = v => {
    if (v.corners) return v.corners.map(c => `${X(c[0])},${Z(c[1])}`).join(' ')
    const yaw = spotYaw(v) * Math.PI / 180, [w, , l] = v.size || [3, 3, 3]
    return [[-1, -1], [-1, 1], [1, 1], [1, -1]].map(([a, c]) => { const x = a * w / 2, z = c * l / 2
      return `${X(v.pos[0] + x * Math.cos(yaw) + z * Math.sin(yaw))},${Z(v.pos[2] - x * Math.sin(yaw) + z * Math.cos(yaw))}` }).join(' ')
  }
  const boxPoly = it => {
    const s = Array.isArray(it.size) ? it.size : [it.size, it.size], yaw = (it.yaw || 0) * Math.PI / 180
    return [[-1, -1], [-1, 1], [1, 1], [1, -1]].map(([a, c]) => { const x = a * s[0] / 2, z = c * s[1] / 2
      return `${X(it.pos[0] + x * Math.cos(yaw) + z * Math.sin(yaw))},${Z(it.pos[2] - x * Math.sin(yaw) + z * Math.cos(yaw))}` }).join(' ')
  }
  const click = e => {
    const svg = ref.current
    const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY
    const q = p.matrixTransform(svg.getScreenCTM().inverse())
    onPlace([x0 + q.x / scale, z0 + (H - q.y) / scale])
  }
  const color = (it, i) => it.id === active ? '#ffffff' : it.main ? '#ffd166' : COLORS[i % COLORS.length]
  return <svg ref={ref} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', background: '#10141a', cursor: placing || areaMode ? 'crosshair' : 'default', border: '1px solid var(--line)' }}
    aria-label="Map top view, north up" onClick={click}
    onMouseMove={e => { const svg = ref.current, p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(svg.getScreenCTM().inverse()); setCursor([x0 + q.x / scale, z0 + (H - q.y) / scale]) }}
    onMouseLeave={() => setCursor(null)}>
    {grid}
    {geom?.bounds && rectEl(geom.bounds, { fill: 'none', stroke: '#566274', strokeDasharray: '6 4' })}
    {geom?.area && rectEl(geom.area, { fill: '#1f3a2c', fillOpacity: 0.35, stroke: '#5fd38d', strokeWidth: 1 })}
    {(geom?.obstacles || []).map((o, i) => rectEl(o, { key: 'o' + i, fill: '#6b7686', fillOpacity: 0.7, stroke: '#9aa5b1' }))}
    {(geom?.reserved || []).map((o, i) => <g key={'r' + i}>{rectEl(o, { fill: '#f2a541', fillOpacity: 0.12, stroke: '#f2a541', strokeDasharray: '3 3' })}
      <text x={X(o[0]) + 3} y={Z(o[3]) + 11} fill="#f2a541" fontSize={10}>{o[4] === 'arrival' ? 'arrival' : o[4] === 'exit_loader' ? 'exit' : ''}</text></g>)}
    {(loaders || []).map((v, i) => <g key={'l' + i}><polygon points={polygon(v)} fill="#c08aff" fillOpacity={0.15} stroke="#c08aff" /></g>)}
    {(others || []).map((it, i) => <g key={'g' + i} opacity={0.55}><polygon points={boxPoly(it)} fill="#8b97a6" fillOpacity={0.2} stroke="#8b97a6" />
      <text x={X(it.pos[0]) + 5} y={Z(it.pos[2]) - 6} fill="#8b97a6" fontSize={10}>{it.label}</text></g>)}
    {items.map((it, i) => {
      const c = color(it, i), sel = it.id === active
      const onC = e => { e.stopPropagation(); onPick(it) }
      if (it.shape === 'box') return <g key={it.id} onClick={onC} style={{ cursor: 'pointer' }}><polygon points={boxPoly(it)} fill={c} fillOpacity={sel ? 0.55 : 0.3} stroke={c} strokeWidth={sel ? 3 : 1.5} />
        <text x={X(it.pos[0]) + 6} y={Z(it.pos[2]) - 8} fill={c} fontSize={11}>{it.label}</text></g>
      if (it.shape === 'rect') return <g key={it.id} onClick={onC} style={{ cursor: 'pointer' }}>{rectEl(it.rect, { fill: c, fillOpacity: sel ? 0.3 : 0.12, stroke: c, strokeWidth: sel ? 3 : 1.2, strokeDasharray: '5 3' })}
        <text x={X(Math.min(it.rect[0], it.rect[2])) + 3} y={Z(Math.max(it.rect[1], it.rect[3])) + 11} fill={c} fontSize={10}>{it.label}</text></g>
      return <g key={it.id} onClick={onC} style={{ cursor: 'pointer' }}>
        {it.shape === 'circle' && <circle cx={X(it.pos[0])} cy={Z(it.pos[2])} r={Math.max(3, it.radius * scale)} fill={c} fillOpacity={0.12} stroke={c} />}
        <circle cx={X(it.pos[0])} cy={Z(it.pos[2])} r={sel ? 6 : 4.5} fill={c} stroke="#0b0e12" />
        <text x={X(it.pos[0]) + 7} y={Z(it.pos[2]) - 6} fill={c} fontSize={10}>{it.short || it.label}</text></g>
    })}
    {cursor && <text x={W - 6} y={14} textAnchor="end" fill="#8b97a6" fontSize={11}>x {round(cursor[0])}, z {round(cursor[1])}</text>}
  </svg>
}

// ---------------------------------------------------------------- the page
export default function MissionTemplates({ status }) {
  const [meta, setMeta] = useState({ projects: [], samples: [], types: [], status: null })
  const [cur, setCur] = useState(null)               // { id, project }
  const [dirty, setDirty] = useState(false)
  const [sel, setSel] = useState(null)               // selected mission id
  const [choices, setChoices] = useState(null)
  const [slots, setSlots] = useState(null)
  const [schemas, setSchemas] = useState({})
  const [placing, setPlacing] = useState(null)
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

  const project = cur?.project
  const refreshMeta = async () => { const m = await get('/api/missiontpl'); setMeta(m); return m }
  const refreshSlots = async () => { try { setSlots(await runJob('/api/missiontpl', { action: 'slots' })) } catch (e) { setNote(e.message) } }
  useEffect(() => { refreshMeta().then(m => { if (m.projects.length && !cur) pick(m.projects[0]) }).catch(e => setNote(e.message)); refreshSlots()
    runJob('/api/missiontpl', { action: 'hosts' }).then(setChoices).catch(e => setNote(e.message))
    get('/api/catalog').then(setCatalog).catch(() => {}) }, [])
  const pick = p => { setCur({ id: p.id, project: structuredClone(p.project), build: p.build }); setDirty(false); setMsgs(null); setBuilt(p.build?.ok ? p.build : null); setSel(p.project.missions?.[0]?.id || null); setPlacing(null); setActive(null) }
  const edit = next => { setCur({ ...cur, project: next }); setDirty(true); setMsgs(null); setBuilt(null) }
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
      const r = await runJob('/api/missiontpl', { action: name, id: p.id, project: p.project || project }, j => setBusy(j.message || label))
      if (name === 'validate') setMsgs(r)
      if (name === 'build') { setBuilt(r); setMsgs({ ok: r.ok, messages: r.result.messages || [] }); if (r.ok) setNote('Built. Install puts it into your game.') }
      if (name === 'install') setNote(r.message + '. Start the game and walk into the mission box. Saves made before this need the update on the Test save page, or pressing the use key at the box closes the game.')
      if (name === 'uninstall') setNote(r.message)
      await refreshMeta(); await refreshSlots()
      if (name !== 'validate') { const m = await get('/api/missiontpl'); const me = m.projects.find(q => q.id === p.id); if (me) setCur(c => ({ ...c, build: me.build })) }
    } catch (e) { setNote(e.message) } finally { setBusy(null) }
  }
  const newProject = () => { if (dirty && !confirm('Discard unsaved changes?')) return; setCur({ id: null, project: blank() }); setDirty(true); setSel(null); setMsgs(null); setBuilt(null) }
  const openSample = async key => {
    const s = meta.samples.find(x => x.key === key)
    if (s.uses_all_slots && !confirm(`${s.title} has ${s.missions} missions: it uses ALL 17 new mission slots of a game. Installing it leaves no room for other new missions. Open it anyway?`)) return
    if (dirty && !confirm('Discard unsaved changes?')) return
    const p = await post('/api/missiontpl', { action: 'sample', key }); await refreshMeta(); pick(p)
    runJob('/api/missiontpl', { action: 'hosts' }).then(setChoices).catch(() => {})
  }
  const del = async () => {
    if (!cur.id || !confirm('Delete this mission project? Your game is not changed.')) return
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
    edit({ ...project, missions: [...project.missions, { id, type: t, host: sel && mission ? mission.host : project.hosts[0].id, index: 'auto', params: {} }] }); setSel(id); setAddType(null)
  }
  const removeMission = id => { edit({ ...project, missions: project.missions.filter(m => m.id !== id) }); if (sel === id) setSel(null) }
  const installedHere = meta.status?.projects?.[cur?.id]
  const left = slots ? slots.left + (installedHere ? installedHere.count : 0) : null
  const needs = project?.missions.length || 0
  const hostLabel = h => h.kind === 'new_map' ? (choices?.newmaps.find(n => n.id === h.newmap_id)?.maps[h.map_index || 0]?.name || 'new map') : 'Section ' + short(h.block).replace('.submap', '').replace('.map', '').replace(/_/g, ' ')
  const mapIdOf = block => (block.match(/_(map\d\d)_/) || [])[1]
  const shipped = host?.kind === 'existing' && catalog ? (catalog.maps.find(m => m.id === mapIdOf(host.block))?.missions || []).filter(m => m.index != null) : []
  const errors = (msgs?.messages || []).filter(m => m.level === 'error').length

  if (!meta.types.length) return <div className="page"><section className="box"><h3>Mission templates</h3><p className="muted">{note || 'Loading...'}</p></section></div>
  return <div className="editor sections" style={{ gridTemplateColumns: 'minmax(0, 1fr) 440px' }}>
    <div className="viewport" style={{ background: '#141920', overflow: 'auto', padding: 16 }}>
      <section className="box"><h3>Mission templates</h3>
        <p className="muted">Pick a kind of mission, choose the map it happens in, drop the mission giver and its points on the map, set the numbers,
          then check, build and install. Everything goes into a mission package that your game loads next to your other mods.</p>
        <div className="row">
          <select aria-label="Mission project" value={cur?.id || ''} onChange={e => { if (dirty && !confirm('Discard unsaved changes?')) return; const p = meta.projects.find(q => q.id === e.target.value); if (p) pick(p) }}>
            <option value="" disabled>{cur && !cur.id ? 'New mission project (not saved)' : 'Choose a mission project'}</option>
            {meta.projects.map(p => <option key={p.id} value={p.id}>{p.project.name}</option>)}</select>
          <button onClick={newProject}>New project</button>
          <select aria-label="Open a sample" value="" onChange={e => e.target.value && openSample(e.target.value)}>
            <option value="">Open a sample...</option>
            {meta.samples.map(s => <option key={s.key} value={s.key}>Open sample: {s.title}{s.uses_all_slots ? ' (uses all 17 slots)' : ''}</option>)}</select>
        </div>
        <p style={{ margin: '8px 0 0' }}><b>{slots ? `${slots.left} of ${slots.total} new mission slots left` : 'Counting free mission slots...'}</b>
          {slots && Object.keys(slots.projects).length > 0 && <span className="muted"> in this game: {Object.values(slots.projects).map(p => `${p.name} uses ${p.count}`).join(', ')}.</span>}
          {project && <span className="muted"> This project has {needs}{left != null && needs > left ? ' and needs more slots than are left.' : '.'}</span>}</p>
        <p className="muted small" style={{ margin: '4px 0 0' }}>A game can have at most 17 new missions in total, shared by everything you install.</p>
        {meta.samples.find(s => s.id === cur?.id)?.uses_all_slots && <p className="warn">This sample uses all 17 slots. Installing it leaves no room for other new missions.</p>}
      </section>
      {project && <>
        <section className="box">
          <div className="row" style={{ alignItems: 'center' }}><h3 style={{ margin: 0 }}>Map {mission && host && <span className="muted"> - {hostLabel(host)}</span>}</h3>
            <span className="muted small" style={{ marginLeft: 'auto' }}>North is up. {placing ? (placing.kind.startsWith('rect') ? (placing.corner ? 'Click the opposite corner.' : 'Click one corner of the area.') : 'Click where it goes.') : areaPick ? 'Click two opposite corners for the play area.' : 'Click an item to move it, then click the map.'}</span></div>
          {geom ? <HostView geom={geom} loaders={loaders} others={others} items={items} placing={placing} active={active} areaMode={!!areaPick} onPick={pickItem} onPlace={place} />
            : <p className="muted">{project.hosts.length ? 'Select a mission to see its map.' : 'Add a host on the right: the map the missions take place in.'}</p>}
          <p className="muted small">Green: the play area. Grey boxes: buildings and props. Orange: the arrival spot and exits. Purple: loading boxes of the section. Yellow box: the mission giver; step into it and press the use key to be offered the mission.</p>
        </section>
        <section className="box"><h3>Missions in this project</h3>
          {project.missions.map(m => <div className="row" key={m.id} style={{ marginBottom: 4 }}>
            <button className={sel === m.id ? 'primary' : ''} style={{ flex: 1, textAlign: 'left' }} onClick={() => { setSel(m.id); setPlacing(null); setActive(null) }}>
              {m.params?.name || m.id} <span className="muted">- {typeInfo(m.type)?.title || m.type}, {hostLabel(project.hosts.find(h => h.id === m.host) || { kind: 'x', block: '' })}{msgs?.index?.[m.id] != null && ', mission ' + msgs.index[m.id]}</span></button>
            <button onClick={() => removeMission(m.id)} title="Remove this mission">Remove</button></div>)}
          {!project.missions.length && <p className="muted">No missions yet. Pick a kind below.</p>}
          <h4 style={{ marginTop: 12 }}>Add a mission</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 6 }}>
            {meta.types.map(t => <button key={t.name} className={addType === t.name ? 'on' : ''} style={{ textAlign: 'left', whiteSpace: 'normal' }} onClick={() => setAddType(addType === t.name ? null : t.name)}>
              <b>{t.title}</b><div className="muted small">{t.summary}</div></button>)}
          </div>
          {addType && <div className="result"><b>{typeInfo(addType).title}</b><p>{typeInfo(addType).summary}</p>
            <div className="muted small">What the map needs:<ul style={{ margin: '2px 0', paddingLeft: 18 }}>{typeInfo(addType).host_needs.map((n, i) => <li key={i}>{n}</li>)}</ul></div>
            <button className="primary" onClick={() => addMission(addType)}>Add this mission</button></div>}
        </section>
      </>}
      {note && <section className="box" role="status" style={{ overflowWrap: 'anywhere' }}>{note}</section>}
      {msgs && <section className="box"><h3>{msgs.ok ? 'Looks good' : 'Needs attention'}</h3>
        {!msgs.messages.length && <p className="good">Nothing to fix.</p>}
        <ul className="checklist">{msgs.messages.map((m, i) => <li key={i} className={m.level === 'error' ? 'error' : m.level === 'warn' ? 'warn' : 'ok'} style={{ cursor: m.where && project?.missions.some(x => x.id === m.where) ? 'pointer' : 'default' }}
          onClick={() => project?.missions.some(x => x.id === m.where) && setSel(m.where)}>
          <b>{m.level === 'error' ? 'Fix' : m.level === 'warn' ? 'Check' : 'Note'}{m.where && m.where !== 'project' ? ' - ' + m.where : ''}</b> {m.text}</li>)}</ul></section>}
      {built?.ok && built.result && <section className="box"><h3>Built</h3>
        <p>{built.result.missions.length} mission{built.result.missions.length === 1 ? '' : 's'} in one package ({Math.round(built.result.bytes / 1048576)} MB). Installing replaces the mission package in your game folder; your game files are not touched.</p>
        <table className="modlist" style={{ width: '100%' }}><thead><tr><th>Mission</th><th>Kind</th><th>Number</th><th>Giver at</th></tr></thead><tbody>
          {built.result.missions.map(m => <tr key={m.project + m.id}><td>{m.name}</td><td>{typeInfo(m.type)?.title || m.type}</td><td>{m.index}</td><td>{m.giver.pos.map(round).join(', ')}</td></tr>)}</tbody></table></section>}
    </div>
    <aside className="panel" style={{ overflow: 'auto' }}>{project && <>
      <section className="box"><h3>Project {dirty && '- unsaved'}</h3>
        <label className="kv">Name<input value={project.name} onChange={e => edit({ ...project, name: e.target.value })} /></label>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <button disabled={!!busy} onClick={() => run('save', 'Saving')}>Save</button>
          <button disabled={!!busy || !project.missions.length} onClick={() => run('validate', 'Checking the missions')}>Check</button>
          <button className="primary" disabled={!!busy || !project.missions.length || errors > 0} onClick={() => run('build', 'Building the missions')}>Build</button>
          <button disabled={!!busy || dirty || !cur?.build?.ok || !built?.ok} title={!built?.ok ? 'Build first' : ''} onClick={() => run('install', 'Installing')}>Install</button>
          <button disabled={!!busy || !installedHere} onClick={() => run('uninstall', 'Removing')}>Uninstall</button>
          {cur?.id && <button disabled={!!busy || !!installedHere} onClick={del}>Delete project</button>}</div>
        <p className="muted small">Build makes the mission package for everything installed in this game plus this project (about a minute). Install copies it into the game folder and adds it to the game's archive list; your original game files are not changed. {installedHere && <b>Installed in this game.</b>}</p>
      </section>
      <section className="box"><h3>Maps for the missions</h3>
        {project.hosts.map(h => <div key={h.id} style={{ marginBottom: 8 }}>
          <div className="row" style={{ alignItems: 'center' }}><b style={{ flex: 1 }}>{hostLabel(h)}</b>
            <button title="Remove this host" onClick={() => { if (project.missions.some(m => m.host === h.id) && !confirm('Missions use this map. Remove them too?')) return; edit({ ...project, hosts: project.hosts.filter(x => x.id !== h.id), missions: project.missions.filter(m => m.host !== h.id) }) }}>Remove</button></div>
          {h.kind === 'existing' && <div className="muted small">
            <label className="kv">Play area (west x, south z, east x, north z) <button className="link" onClick={() => { setAreaPick(areaPick === h.id ? null : h.id); setAreaCorner(null) }}>{areaPick === h.id ? 'cancel' : 'set on the map'}</button>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>{(h.area || [0, 0, 0, 0]).map((v, i) => <Num key={i} value={v} onChange={x => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, area: q.area.map((n, j) => j === i ? x : n) } : q) })} />)}</div></label>
            <label className="kv">Ground height (metres)<Num value={h.ground_y} nullable onChange={x => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, ground_y: x } : q) })} /></label>
            <label className="kv">Start the mission like this shipped mission
              <select value={h.map_ids_from_slot ?? ''} onChange={e => edit({ ...project, hosts: project.hosts.map(q => q.id === h.id ? { ...q, map_ids_from_slot: Number(e.target.value) } : q) })}>
                {h.map_ids_from_slot == null && <option value="">choose one</option>}
                {(catalog?.maps.find(m => m.id === mapIdOf(h.block))?.missions || []).filter(m => m.index != null).map(m => <option key={m.index} value={m.index}>{m.title} ({m.index})</option>)}
                {h.map_ids_from_slot != null && !(catalog?.maps.find(m => m.id === mapIdOf(h.block))?.missions || []).some(m => m.index === h.map_ids_from_slot) && <option value={h.map_ids_from_slot}>mission {h.map_ids_from_slot}</option>}</select></label>
            <p>This section is an existing part of the game. Only the mission giver box is added to it; everything else the mission needs is added in new blocks. Give it the walkable play area and its ground height: the game does not tell us.</p></div>}
        </div>)}
        <h4>Add a map</h4>
        {choices?.newmaps.length === 0 && <p className="muted small">You have no New maps projects yet. Make one on the New maps tab, or open a sample above.</p>}
        {choices?.newmaps.flatMap(n => n.maps.map((m, i) => <div className="row" key={n.id + i} style={{ marginBottom: 3 }}>
          <button style={{ flex: 1, textAlign: 'left' }} disabled={m.error || project.hosts.some(h => h.kind === 'new_map' && h.newmap_id === n.id && (h.map_index || 0) === i)}
            onClick={() => addHostNew(n.id, i)}>New map: {m.name}</button></div>))}
        <label className="kv">A part of an existing map
          <select value="" onChange={e => e.target.value && addHostExisting(e.target.value)}>
            <option value="">Choose a section...</option>
            {(choices?.existing || []).map(h => <option key={h.block} value={h.block} disabled={!h.offer} title={h.offer ? h.proven : h.reason}>{h.block.replace('.submap', '').replace('.map', '').replace(/_/g, ' ')}{!h.offer ? ' (cannot host a giver)' : /^proven/.test(h.proven || '') ? ' (tested in the game)' : ' (not tested in the game yet)'}</option>)}</select></label>
        {choices && choices.existing.some(h => !h.offer) && <p className="muted small">Greyed sections cannot take a giver box: hover one for the reason. Only the Downtown sections are tested in the game; the others pass the safety checks but you should try them in a test save first.</p>}
        {project.hosts.some(h => h.kind === 'new_map') && <p className="muted small">A new map is built into the mission package. If you installed the same map from the New maps tab, installing the missions takes that map package out (it would be the same map twice).</p>}
      </section>
      {mission && <section className="box">
        <h3>{typeInfo(mission.type)?.title}: {mission.params?.name || mission.id}</h3>
        <p className="muted small">{typeInfo(mission.type)?.summary}</p>
        <label className="kv">Map<select value={mission.host} onChange={e => edit({ ...project, missions: project.missions.map(m => m.id === sel ? { ...m, host: e.target.value, params: {} } : m) })}>
          {project.hosts.map(h => <option key={h.id} value={h.id}>{hostLabel(h)}</option>)}</select></label>
        {mission.type === 'chase' && <p className="warn small">This one is not map independent: the chase always plays in Downtown, on its roads. Only the giver can go elsewhere.</p>}
        {!sc && <p className="muted">Loading the settings...</p>}
        {sc?.error && <p className="bad">{sc.error}</p>}
        {sc && !sc.error && ['Placement', 'Settings', 'Scores', 'Texts'].concat([...new Set(sc.params.map(p => p.group))].filter(g => !['Placement', 'Settings', 'Scores', 'Texts'].includes(g))).filter(g => sc.params.some(p => p.group === g)).map(g => {
          const ps = sc.params.filter(p => p.group === g)
          const main = ps.filter(p => !p.advanced), adv = ps.filter(p => p.advanced)
          const render = p => <Field key={p.key} p={p} value={vals[p.key]} isSet={mission.params && mission.params[p.key] !== undefined}
            onChange={v => setParam(p.key, v)} reset={() => resetParam(p.key)} placing={placing} setPlacing={x => { setPlacing(x); setActive(x?.key + (x?.index != null ? ':' + x.index : '')) }} />
          return <details key={g} open={g === 'Placement' || g === 'Settings'}><summary><b>{g}</b></summary>
            {main.map(render)}
            {adv.length > 0 && <details><summary className="muted">More {g.toLowerCase()} settings</summary>{adv.map(render)}</details>}</details>
        })}
      </section>}
    </>}
    {!project && <section className="box"><p className="muted">Open a sample from the top of the page or start a new project.</p></section>}
    </aside>
    {busy && <div className="busy">{busy}</div>}
  </div>
}
