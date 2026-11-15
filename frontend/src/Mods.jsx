import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'

export default function Mods({ status, project, loadProject, replace, refresh }) {
  const [st, setSt] = useState(null)
  const [job, setJob] = useState(null)
  const [msg, setMsg] = useState(null)
  const [exp, setExp] = useState(null)
  const load = () => get('/api/mods').then(setSt).catch(e => setMsg(e.message))
  useEffect(() => { load() }, [])
  if (!st) return <div className="page"><p className="muted">loading</p></div>
  const mods = st.mods
  const enabled = mods.filter(m => m.enabled).map(m => m.id)
  const setState = async (order, en) => setSt(await post('/api/mods/state', { order, enabled: en }))
  const move = (i, d) => {
    const o = mods.map(m => m.id)
    const j = i + d
    if (j < 0 || j >= o.length) return
    ;[o[i], o[j]] = [o[j], o[i]]
    setState(o, enabled)
  }
  const toggle = (id, on) => setState(mods.map(m => m.id), on ? [...enabled, id] : enabled.filter(x => x !== id))
  const install = async () => {
    setMsg(null)
    try { const r = await runJob('/api/mods/install', {}, setJob); setMsg('Installed: ' + (r.configpc_line || 'nothing enabled')); refresh() }
    catch (e) { setMsg(e.message) }
    setJob(null); load()
  }
  const uninstall = async () => { try { await post('/api/mods/uninstall', {}); setMsg('Removed from the game.'); refresh() } catch (e) { setMsg(e.message) } load() }
  const exportBuild = async () => {
    setMsg(null)
    try { const r = await runJob('/api/export', { mod: { ...project, author: project.author || status.settings?.author || '' } }, setJob); setExp(r); replace({ ...project, id: r.mod.id }); load() }
    catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const share = async (m) => {
    const r = await post('/api/mods/export', { id: m.id, suggest: m.id + '.todmod' })
    if (r.path) setMsg('Shared as ' + r.path)
  }
  const imp = async () => { const r = await post('/api/mods/import', {}); if (!r.cancelled) { setMsg('Imported ' + r.name); load() } }
  const edit = async (m) => { const full = await get('/api/mods/get', { id: m.id }); loadProject(full); setMsg('Loaded "' + m.name + '" into the editor.') }
  const del = async (m) => { if (confirm('Delete "' + m.name + '" from the library?')) setSt(await post('/api/mods/delete', { id: m.id })) }
  const inst = st.installed || {}
  return (
    <div className="page mods">
      <section className="box">
        <h3>Current mod: {project.name}</h3>
        <label>Description <textarea defaultValue={project.description} rows={2}
          onBlur={e => replace({ ...project, description: e.target.value })} /></label>
        <button className="primary" onClick={exportBuild} disabled={!!job}>Save, check and build the override zip</button>
        {exp && <div className="result">
          <p>Built <b>{exp.build.zip?.zip}</b> ({Math.round((exp.build.zip?.zip_bytes || 0) / 1024)} KB, blocks: {exp.build.entries.map(e => e.split('/').pop()).join(', ')})</p>
          <ul className="checklist">{exp.checks.map((c, i) => <li key={i} className={c.level}><b>{c.area}</b> {c.title}</li>)}</ul>
          <button onClick={() => post('/api/reveal', { path: exp.folder })}>Open folder</button>
        </div>}
      </section>
      <section className="box">
        <h3>Mod library</h3>
        <p className="muted">Enabled mods are built together, top to bottom (a later mod wins where two change the same
          value), into one archive in the game folder. Shared files (.todmod) hold only the recipe, never game data:
          each player builds them from their own game.</p>
        <table className="modlist"><thead><tr><th>On</th><th>Mod</th><th>Changes</th><th>Updated</th><th></th></tr></thead><tbody>
          {mods.map((m, i) => <tr key={m.id}>
            <td><input type="checkbox" checked={m.enabled} onChange={e => toggle(m.id, e.target.checked)} /></td>
            <td><b>{m.name}</b>{m.author && <i> by {m.author}</i>}<div className="muted">{m.description}</div></td>
            <td>{m.level_ops} level, {m.data_values} data{m.collision_sets ? ', ' + m.collision_sets + ' collision' : ''}{m.asset_rows ? ', ' + m.asset_rows + ' Unreal assets' : ''}
              {m.source === 'unreal' && <span className="badge">from Unreal</span>}</td>
            <td>{(m.updated || '').replace('T', ' ')}</td>
            <td className="btns">
              <button onClick={() => move(i, -1)} disabled={i === 0}>Up</button>
              <button onClick={() => move(i, 1)} disabled={i === mods.length - 1}>Down</button>
              <button onClick={() => edit(m)}>Edit</button>
              <button onClick={() => share(m)}>Share</button>
              <button onClick={() => del(m)}>Delete</button>
            </td>
          </tr>)}
          {!mods.length && <tr><td colSpan={5} className="muted">No mods yet. Save the current mod or import a .todmod file.</td></tr>}
        </tbody></table>
        <button onClick={imp}>Import a .todmod file</button>
      </section>
      <section className="box">
        <h3>Game folder</h3>
        <p>{status.game.folder}{status.game.tod_hd && <> with TOD HD: mods are built on TOD HD's blocks and listed before its archives</>}</p>
        <p>configpc.txt filesystem line: <code>{(inst.filesystem_line || ['(default)']).join(', ')}</code></p>
        <p>{inst.zip_present ? `Installed ${inst.installed || ''}: ${(inst.mods || []).length} mod(s).` : 'No mods installed.'}</p>
        <button className="primary" onClick={install} disabled={!!job}>Install enabled mods into the game</button>
        <button onClick={uninstall} disabled={!!job}>Remove all mods from the game</button>
        <p className="muted">Installing writes todms_mods.zip and edits configpc.txt (a backup is kept as
          configpc.txt.todms_backup). blocks.naz is never changed. Close the game first.</p>
      </section>
      {job && <div className="busy">{job.message || job.status}</div>}
      {msg && <p className="flash">{msg}</p>}
    </div>
  )
}
