// Section and transition tools (companion tools part B):
// every loader volume of a group of sections as boxes with arrows (top view), the teleport loaders flagged (the bridge,
// the tunnel, the farm pass), the T1 fix (empty both Teleport_to values, move one box past the other), a split planner
// (read only) and new sections (recorded, checked by submaptool). The edits are the mod's "sections" ops.
import React, { useEffect, useMemo, useState } from 'react'
import { runJob } from './api.js'
import LoaderTopView from './LoaderTopView.jsx'
import { useBundle, pickOfBlock, getCatalog } from './levelLoad.js'
import { short, describeSection, newId } from './partb.js'
import { t as tr } from './i18n.js'

const CLS = { WALK: '#5ad06a', TELEPORT: '#ff4d4d', ONEWAY: '#9aa5b1', MISSION: '#c08aff' }

export default function Sections({ status, project, commit }) {
  const [group, setGroup] = useState('Downtown 01 + Harbour 01 (the bridge)')
  const [cat, setCat] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [sel, setSel] = useState(null)
  const [gap, setGap] = useState(23)
  const [check, setCheck] = useState(null)
  const [showMap, setShowMap] = useState(() => new URLSearchParams(location.search).get('showmap') === '1')
  const [catalogMaps, setCatalogMaps] = useState(null)
  useEffect(() => { if (showMap && !catalogMaps) getCatalog().then(setCatalogMaps).catch(e => setMsg(e.message)) }, [showMap])
  const [split, setSplit] = useState({ entry: 'submap01_map09_jungle.submap', axis: 'x', at: -600, res: null })
  const [sec, setSec] = useState({ source: 'submap01_map09_jungle.submap', index: 3, inPos: '-560, -105, -2300', backPos: '-575, -105, -2300', yaw: 0 })
  const ops = project.sections || []
  const setOps = o => commit({ ...project, sections: o })

  const load = async () => {
    try { setCat(await runJob('/api/sections/catalog', { group, ops }, j => setBusy(j.message || 'Reading the loaders'))) }
    catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  useEffect(() => { load() }, [group, JSON.stringify(ops)])
  const vols = cat?.volumes || []
  const after = Object.fromEntries((cat?.volumes_after || []).map(v => [v.id, v]))
  const shownBlock = (vols.find(v => v.id === sel) || vols[0])?.block
  const mapPick = useMemo(() => (showMap && catalogMaps && shownBlock) ? pickOfBlock(catalogMaps, shownBlock) : null, [showMap, catalogMaps, shownBlock])
  const lvl = useBundle(mapPick, !!mapPick)

  const fix = async v => {
    try {
      const r = await runJob('/api/sections/fix', { group, volume: v.id, gap }, j => setBusy(j.message || 'Planning the fix'))
      const keep = ops.filter(o => !r.ops.some(n => n.node === o.node && n.entry === o.entry && n.op === o.op))
      setOps([...keep, ...r.ops])
    } catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  const runCheck = async () => {
    setCheck(null)
    try { setCheck(await runJob('/api/partb/check', { mod: project, kinds: ['sections'] }, j => setBusy(j.message || 'Building and checking'))) }
    catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  const runSplit = async () => {
    try {
      const r = await runJob('/api/sections/split', { entry: 'data_pc/overdose_the_game/overdose/shared/' + split.entry, axis: split.axis, at: Number(split.at) },
        j => setBusy(j.message || 'Scanning'))
      setSplit({ ...split, res: r })
    } catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  const addSection = () => {
    const p = s => s.split(',').map(Number)
    setOps([...ops, { op: 'add_section', id: newId('sec'), entry: 'data_pc/overdose_the_game/overdose/shared/' + sec.source,
      source_submap: sec.source, new_index: Number(sec.index), specific_id: null,
      loader_in: { pos: p(sec.inPos), size: [12, 6, 2], yaw: Number(sec.yaw) }, loader_back: { pos: p(sec.backPos), size: [12, 6, 2], yaw: Number(sec.yaw) } }])
  }

  return (
    <div className="editor sections" style={{ gridTemplateColumns: '1fr 380px' }}>
      <div className="viewport" style={{ background: 'var(--vp)', overflow: 'auto', paddingTop: 34 }}>
        <div className="toolbar">
          <select value={group} onChange={e => setGroup(e.target.value)}>
            {(cat?.groups || [{ name: group }]).map(g => <option key={g.name}>{g.name}</option>)}</select>
          <button className={showMap ? 'on' : ''} aria-pressed={showMap} title={tr('draw_the_map_under_the_loaders')} onClick={() => setShowMap(!showMap)}>{tr('map')}</button>
          <span className="lbl" title={tr('green_walk_red_teleport_grey_one')}>{lvl.busy ? lvl.busy + '…' : lvl.err ? 'No map' : ''}</span>
        </div>
        <div style={{ display: 'flex', height: 460, margin: '0 0 6px' }}><LoaderTopView volumes={vols} after={after} selected={sel} onSelect={setSel} bundle={lvl.bundle} view={lvl.view} bounds={showMap} /></div>
        <table className="sets" style={{ margin: 12 }}><thead><tr><th>{tr('block')}</th><th>{tr('loader')}</th><th>{tr('class')}</th><th>{tr('target')}</th><th>{tr('teleport')}</th><th>{tr('return_m')}</th><th>{tr('order')}</th><th>{tr('after')}</th><th /></tr></thead>
          <tbody>{vols.map(v => <tr key={v.id} className={sel === v.id ? 'sel' : ''} onClick={() => setSel(v.id)}>
            <td>{short(v.block)}</td><td>{v.name}</td><td style={{ color: CLS[v.cls] }}>{v.cls}</td><td>{v.target}</td>
            <td>{v.teleports?.length ? `${v.teleports[0]} (${v.teleport_dist} m)` : ''}</td><td>{v.return_loader?.dist ?? ''}</td>
            <td>{v.order ? `${v.order.state} (gap ${v.order.gap} m)` : ''}</td>
            <td style={{ color: CLS[after[v.id]?.cls] }}>{after[v.id]?.cls || ''}</td>
            <td>{v.cls === 'TELEPORT' && <button onClick={() => fix(v)}>{tr('fix_teleport')}</button>}</td></tr>)}</tbody></table>
      </div>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>{tr('teleports')}{' '}<span className="badge">{cat?.teleports ?? '?'}</span></h3>
          
          <label className="kv">{tr('gap_m')}<input value={gap} onChange={e => setGap(e.target.value)} /></label>
        </section>
        <section className="box">
          <h3>{tr('edits')}{' '}<span className="badge">{ops.length}</span></h3>
          <ol className="changes">{ops.map((o, i) => <li key={i}>{describeSection(o)} <button onClick={() => setOps(ops.filter((_, j) => j !== i))}>{tr('x_11f6ad')}</button></li>)}</ol>
          <button className="primary" onClick={runCheck} disabled={!ops.length}>{tr('check')}</button>
          {cat?.after && <ul className="checklist">{(cat.after.checks || []).map((c, i) => <li key={i} className={c[0] === 'PASS' ? 'ok' : 'error'}>{c[1]}</li>)}
            <li className="ok">{tr('teleports_after_the_edit')}{' '}{cat.after.teleports_after}</li></ul>}
        </section>
        {check && <section className="box"><h3>{tr('check_695ef8')}{' '}{check.result}</h3>
          <ul className="checklist">{check.lines.map((l, i) => <li key={i} className={l.level}><b>{l.area}</b> {l.text}</li>)}</ul></section>}
        <section className="box">
          <h3>{tr('split_planner_read_only')}</h3>
          <div className="row3"><label>{tr('block_0214b4')}<input value={split.entry} onChange={e => setSplit({ ...split, entry: e.target.value })} /></label>
            <label>{tr('axis')}<select value={split.axis} onChange={e => setSplit({ ...split, axis: e.target.value })}><option>{tr('x_11f6ad')}</option><option>{tr('z')}</option></select></label>
            <label>{tr('at_m')}<input value={split.at} onChange={e => setSplit({ ...split, at: e.target.value })} /></label></div>
          <button onClick={runSplit}>{tr('plan_the_cut')}</button>
          {split.res && <div className="muted">
            <p>{tr('objects_a_b')}{' '}{split.res.placed_entities.A} / {split.res.placed_entities.B}{tr('routes_crossing')}{' '}{split.res.routes_crossing}{' '}{tr('of')}{' '}{split.res.route_groups}{tr('trigger_volumes_straddling')}{' '}{split.res.trigger_volumes_straddling.length}{tr('loaders_now')}{' '}{split.res.loaders_now}.</p>
            <ul>{split.res.not_solved.map((t, i) => <li key={i}>{t}</li>)}</ul></div>}
        </section>
        <section className="box">
          <h3>{tr('new_section')}</h3>
          
          {[['source', 'source section'], ['index', 'new number'], ['inPos', 'loader in (x, y, z)'], ['backPos', 'loader back (x, y, z)'], ['yaw', 'yaw']].map(([k, l]) =>
            <label key={k} className="kv">{l}<input value={sec[k]} onChange={e => setSec({ ...sec, [k]: e.target.value })} /></label>)}
          <button onClick={addSection}>{tr('add_section_then_check')}</button>
        </section>
      </aside>
      {busy && <div className="busy">{busy}</div>}
      {msg && <div className="error" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}
