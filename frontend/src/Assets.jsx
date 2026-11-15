// Asset replacements, read-only overview (companion tool; the table is edited in the Unreal TOD Level Editor plugin,
// which renders the Unreal assets). Every TOD model of the player's game with its maps, use counts and a thumbnail
// rendered from the game's own mesh; the Unreal columns come from the current mod's "assets" section (a .todmod made
// in Unreal) or from an Unreal project's Config/TODBridge folder (Settings).
import React, { useEffect, useState } from 'react'
import { post, runJob } from './api.js'

const SHOW = [['', 'all models'], ['assigned', 'with a replacement'], ['unassigned', 'without a replacement'],
  ['imported', 'imported into Unreal'], ['todhd', 'TOD HD replacement'], ['visual_only', 'marked visual only'],
  ['needs_collision', 'marked needs collision change'], ['with_candidates', 'with candidates']]

export default function Assets({ status, project }) {
  const [q, setQ] = useState(() => {               // deep link: ?tab=assets&map=..&only=..&min=..
    const u = new URLSearchParams(location.search)
    return { map: u.get('map') || '', min: Number(u.get('min') || 0), q: u.get('q') || '', only: u.get('only') || '', offset: 0, limit: 150 }
  })
  const [data, setData] = useState(null)
  const [job, setJob] = useState(null)
  const [msg, setMsg] = useState(null)
  const load = async (qq = q) => {
    try { setData(await post('/api/assets/rows', { ...qq, mod: project })) } catch (e) { setMsg(e.message) }
  }
  useEffect(() => { load() }, [q, project.assets])
  const census = async () => {
    setMsg(null)
    try { const r = await runJob('/api/assets/census', {}, setJob); setMsg(`Counted ${r.models} models in ${r.maps.length} maps (${r.seconds} s).`); load() }
    catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const thumbs = async () => {
    const keys = (data?.rows || []).filter(r => !r.thumb).map(r => r.key)
    if (!keys.length) return
    try { await runJob('/api/assets/thumbs', { keys }, setJob); load() } catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const set = (k, v) => setQ({ ...q, [k]: v, offset: k === 'offset' ? v : 0 })
  if (!data) return <div className="page"><p className="muted" style={{ padding: 12 }}>loading</p></div>
  return (
    <div className="page assets">
      <section className="box wide">
        <h3>Asset replacements <span className="badge">read only</span></h3>
        <p className="muted">Each Total Overdose model (the key the Unreal bridge uses) and the Unreal asset that replaces
          it. Assigning, bulk assignment, candidates and the "visual only / needs collision change" markers are done in
          Unreal (TOD Level Editor, Asset Replacements); a mod shared from Unreal carries its rows. Models marked
          "needs collision change" want new collision: use the Collision tab.</p>
        {!data.ready ? <div><p>The table counts every model's placements in every map of your game (about two minutes).</p>
          <button className="primary" onClick={census} disabled={!!job}>Build the table</button></div> : <>
          <div className="row filters">
            <input placeholder="search model or path" value={q.q} onChange={e => set('q', e.target.value)} />
            <select value={q.map} onChange={e => set('map', e.target.value)}>
              <option value="">all maps</option>{data.maps.map(m => <option key={m} value={m}>{m}</option>)}</select>
            <label className="inl">uses &ge; <input type="number" value={q.min} onChange={e => set('min', e.target.value)} /></label>
            <select value={q.only} onChange={e => set('only', e.target.value)}>{SHOW.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <button onClick={thumbs} disabled={!!job}>Thumbnails for this page</button>
            <button onClick={census} disabled={!!job}>Count again</button>
          </div>
          <p className="muted">{data.count} of {data.total} models.
            {' '}Unreal columns: {data.mod_rows ? `${data.mod_rows} rows from this mod` : 'none in this mod'}{data.ue_config ? `; Unreal project ${data.ue_config}` : ''}.</p>
          <table className="assettable"><thead><tr><th>TOD</th><th>Model</th><th>Maps (placements)</th><th>Uses</th><th>Game collision</th>
            <th>Unreal original</th><th>Replacement</th><th>Marker</th><th>Candidates</th></tr></thead>
            <tbody>{data.rows.map(r => <tr key={r.key}>
              <td>{r.thumb ? <img src={r.thumb} width={64} height={64} alt="" /> : <span className="muted">-</span>}</td>
              <td><b>{r.name}</b><div className="muted small">{r.key}</div><div className="muted small">{r.kind}, {r.size ? r.size.map(v => v.toFixed(1)).join(' x ') + ' m' : ''}</div></td>
              <td className="small">{Object.entries(r.maps).map(([m, n]) => <div key={m}>{m} {n}</div>)}</td>
              <td>{r.uses}</td>
              <td>{r.collision}{r.collision_shapes ? ` (${r.collision_shapes})` : ''}</td>
              <td className="small">{r.ue_original ? r.ue_original.split('/').pop() : <span className="muted">not imported</span>}</td>
              <td className="small">{r.ue_thumb && <img src={r.ue_thumb} width={64} height={64} alt="" />}{r.ue_hd && <div><span className="badge">TOD HD</span> {r.ue_hd.split('/').pop()}</div>}
                {r.ue_assigned ? <div className={r.from_mod ? 'flash' : ''}>{r.ue_assigned}</div> : (!r.ue_hd && <span className="muted">-</span>)}</td>
              <td>{r.marker === 'visual_only' ? <span className="good">visual only</span> : r.marker === 'needs_collision' ? <span className="warn">needs collision change</span> : ''}</td>
              <td className="small">{(r.candidates || []).slice(0, 2).map(c => <div key={c.ue}>{c.ue.split('/').pop()} <i>{c.score}</i></div>)}</td>
            </tr>)}</tbody></table>
          <div className="row"><button disabled={q.offset === 0} onClick={() => set('offset', Math.max(0, q.offset - q.limit))}>Previous</button>
            <span className="muted">{q.offset + 1} - {Math.min(data.count, q.offset + q.limit)}</span>
            <button disabled={q.offset + q.limit >= data.count} onClick={() => set('offset', q.offset + q.limit)}>Next</button></div>
        </>}
      </section>
      {job && <div className="busy">{job.message || job.status} {job.total ? `${job.done}/${job.total}` : ''}</div>}
      {msg && <p className="flash" style={{ padding: '0 12px' }}>{msg}</p>}
    </div>
  )
}
