// Section and transition tools (companion tools part B, same core as the Unreal TOD Level Editor plugin's Sections tab):
// every loader volume of a group of sections as boxes with arrows (top view), the teleport loaders flagged (the bridge,
// the tunnel, the farm pass), the T1 fix (empty both Teleport_to values, move one box past the other), a split planner
// (read only) and new sections (recorded, checked by submaptool). The edits are the mod's "sections" ops.
import React, { useEffect, useState } from 'react'
import { runJob } from './api.js'
import LoaderTopView from './LoaderTopView.jsx'
import { short, describeSection, newId } from './partb.js'

const CLS = { WALK: '#5ad06a', TELEPORT: '#ff4d4d', ONEWAY: '#9aa5b1', MISSION: '#c08aff' }

export default function Sections({ status, project, commit }) {
  const [group, setGroup] = useState('Downtown 01 + Harbour 01 (the bridge)')
  const [cat, setCat] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [sel, setSel] = useState(null)
  const [gap, setGap] = useState(23)
  const [check, setCheck] = useState(null)
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
      <div className="viewport" style={{ background: '#141920', overflow: 'auto', paddingTop: 34 }}>
        <div className="toolbar">
          <select value={group} onChange={e => setGroup(e.target.value)}>
            {(cat?.groups || [{ name: group }]).map(g => <option key={g.name}>{g.name}</option>)}</select>
          <span className="lbl">Top view, north up. Boxes coloured by class (green walk, red teleport, grey one-way); arrows to the other
            section's return box; dashed red: the teleport jump; bright green outline: the box after the fix.</span>
        </div>
        <LoaderTopView volumes={vols} after={after} selected={sel} onSelect={setSel} />
        <table className="sets" style={{ margin: 12 }}><thead><tr><th>Block</th><th>Loader</th><th>Class</th><th>Target</th><th>Teleport</th><th>Return (m)</th><th>Order</th><th>After</th><th /></tr></thead>
          <tbody>{vols.map(v => <tr key={v.id} className={sel === v.id ? 'sel' : ''} onClick={() => setSel(v.id)}>
            <td>{short(v.block)}</td><td>{v.name}</td><td style={{ color: CLS[v.cls] }}>{v.cls}</td><td>{v.target}</td>
            <td>{v.teleports?.length ? `${v.teleports[0]} (${v.teleport_dist} m)` : ''}</td><td>{v.return_loader?.dist ?? ''}</td>
            <td>{v.order ? `${v.order.state} (gap ${v.order.gap} m)` : ''}</td>
            <td style={{ color: CLS[after[v.id]?.cls] }}>{after[v.id]?.cls || ''}</td>
            <td>{v.cls === 'TELEPORT' && <button onClick={() => fix(v)}>Fix teleport</button>}</td></tr>)}</tbody></table>
      </div>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>Teleports <span className="badge">{cat?.teleports ?? '?'}</span></h3>
          <p className="muted">Seven shipped loaders teleport: the Downtown-Harbour bridge (2), the Downtown-Industrial tunnel (3) and
            the farm pass (2). Their boxes stand in the wrong order for walking, so the game moves the player past the other
            box. The fix (package T1) empties both Teleport_to values and moves this box past the other one by the gap.</p>
          <label className="kv">gap (m)<input value={gap} onChange={e => setGap(e.target.value)} /></label>
        </section>
        <section className="box">
          <h3>Edits <span className="badge">{ops.length}</span></h3>
          <ol className="changes">{ops.map((o, i) => <li key={i}>{describeSection(o)} <button onClick={() => setOps(ops.filter((_, j) => j !== i))}>x</button></li>)}</ol>
          <button className="primary" onClick={runCheck} disabled={!ops.length}>Check (build + seamless transitions)</button>
          {cat?.after && <ul className="checklist">{(cat.after.checks || []).map((c, i) => <li key={i} className={c[0] === 'PASS' ? 'ok' : 'error'}>{c[1]}</li>)}
            <li className="ok">teleports after the edit: {cat.after.teleports_after}</li></ul>}
        </section>
        {check && <section className="box"><h3>Check: {check.result}</h3>
          <ul className="checklist">{check.lines.map((l, i) => <li key={i} className={l.level}><b>{l.area}</b> {l.text}</li>)}</ul></section>}
        <section className="box">
          <h3>Split planner (read only)</h3>
          <div className="row3"><label>block<input value={split.entry} onChange={e => setSplit({ ...split, entry: e.target.value })} /></label>
            <label>axis<select value={split.axis} onChange={e => setSplit({ ...split, axis: e.target.value })}><option>x</option><option>z</option></select></label>
            <label>at (m)<input value={split.at} onChange={e => setSplit({ ...split, at: e.target.value })} /></label></div>
          <button onClick={runSplit}>Plan the cut</button>
          {split.res && <div className="muted">
            <p>Objects A / B: {split.res.placed_entities.A} / {split.res.placed_entities.B}; routes crossing {split.res.routes_crossing} of {split.res.route_groups};
              trigger volumes straddling {split.res.trigger_volumes_straddling.length}; loaders now {split.res.loaders_now}.</p>
            <ul>{split.res.not_solved.map((t, i) => <li key={i}>{t}</li>)}</ul></div>}
        </section>
        <section className="box">
          <h3>New section</h3>
          <p className="muted">A renamed copy of a section block with its language blocks, registered beside the map's MAINMAP_ folder
            (Specific_ID 21+ raises common.SUBMAPS_MAX), a load-screen entry, and a loader on each side. Everything new is
            appended after the existing objects of its block; a section that ends with a shared prefab (the jungle) gets its
            loaders in the map block.</p>
          {[['source', 'source section'], ['index', 'new number'], ['inPos', 'loader in (x, y, z)'], ['backPos', 'loader back (x, y, z)'], ['yaw', 'yaw']].map(([k, l]) =>
            <label key={k} className="kv">{l}<input value={sec[k]} onChange={e => setSec({ ...sec, [k]: e.target.value })} /></label>)}
          <button onClick={addSection}>Add section (then Check)</button>
        </section>
      </aside>
      {busy && <div className="busy">{busy}</div>}
      {msg && <div className="error" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}
