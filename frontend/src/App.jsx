import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'
import { useProject, emptyProject } from './project.js'
import LevelEditor from './LevelEditor.jsx'
import DataEditors from './DataEditors.jsx'
import Mods from './Mods.jsx'
import TestSave from './TestSave.jsx'
import Collision from './Collision.jsx'
import Assets from './Assets.jsx'
import Routes from './Routes.jsx'
import Missions from './Missions.jsx'
import Sections from './Sections.jsx'
import NewMaps from './NewMaps.jsx'
import MissionTemplates from './MissionTemplates.jsx'
import { partBCount } from './partb.js'

export default function App() {
  const [status, setStatus] = useState(null)
  const [tab, setTab] = useState('level')
  const [saveSpot, setSaveSpot] = useState(null)
  const P = useProject()
  const refresh = () => get('/api/status').then(setStatus).catch(e => setStatus({ error: e.message }))
  useEffect(() => { refresh() }, [])
  const [linkWait, setLinkWait] = useState(() => !!new URLSearchParams(location.search).get('mod'))
  useEffect(() => {
    const q = new URLSearchParams(location.search)
    if (q.get('mod')) get('/api/mods/get', { id: q.get('mod') }).then(m => P.loadProject({ collision: [], ...m }))
      .catch(() => {}).finally(() => setLinkWait(false))
    if (q.get('tab')) setTab(q.get('tab'))
  }, [])
  if (!status || linkWait) return <div className="splash">TOD Mod Studio</div>
  if (status.error) return <div className="splash">Backend not reachable: {status.error}</div>
  if (!status.ready) return <Setup status={status} onDone={refresh} />
  const spot = s => { setSaveSpot(s); setTab('save') }
  return (
    <div className="app">
      <header>
        <div className="brand">TOD Mod Studio</div>
        <nav>
          {[['level', 'Level editor'], ['collision', 'Collision'], ['assets', 'Assets'], ['routes', 'Routes'], ['missions', 'Missions'], ['sections', 'Sections'], ['newmaps', 'New maps'], ['mtpl', 'Mission templates'], ['data', 'Game data'], ['mods', 'Mods'], ['save', 'Test save'], ['settings', 'Settings']].map(([k, l]) =>
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}
        </nav>
        <ProjectBar P={P} onSaved={() => {}} />
        <div className="gameinfo" title={status.game.folder}>
          {status.game.folder.split(/[\\/]/).slice(-2).join('/')}
          {status.game.tod_hd && <span className="badge">TOD HD</span>}
          {status.installed?.zip_present && <span className="badge ok">mods installed</span>}
        </div>
      </header>
      <div className="body">
        {tab === 'level' && <LevelEditor status={status} {...P} setSaveSpot={spot} />}
        {tab === 'collision' && <Collision status={status} project={P.project} commit={P.commit} />}
        {tab === 'assets' && <Assets status={status} project={P.project} />}
        {tab === 'routes' && <Routes status={status} project={P.project} commit={P.commit} />}
        {tab === 'missions' && <Missions status={status} project={P.project} commit={P.commit} />}
        {tab === 'sections' && <Sections status={status} project={P.project} commit={P.commit} />}
        {tab === 'newmaps' && <NewMaps />}
        {tab === 'mtpl' && <MissionTemplates status={status} />}
        {tab === 'data' && <DataEditors project={P.project} commit={P.commit} />}
        {tab === 'mods' && <Mods status={status} project={P.project} loadProject={P.loadProject} replace={P.replace} refresh={refresh} />}
        {tab === 'save' && <TestSave status={status} spot={saveSpot} />}
        {tab === 'settings' && <Settings status={status} refresh={refresh} />}
      </div>
    </div>
  )
}

function ProjectBar({ P }) {
  const [msg, setMsg] = useState(null)
  const p = P.project
  const n = p.level.length + Object.values(p.data || {}).reduce((a, v) => a + Object.keys(v).length, 0) + (p.collision || []).length + partBCount(p)
  const save = async () => {
    try { const m = await post('/api/mods/save', { mod: p }); P.replace({ ...p, id: m.id }); setMsg('saved to the mod library') }
    catch (e) { setMsg(e.message) }
    setTimeout(() => setMsg(null), 2500)
  }
  return (
    <div className="projectbar">
      <input className="pname" value={p.name} onChange={e => P.replace({ ...p, name: e.target.value })} title="mod name" />
      <span className="muted">{n} change{n === 1 ? '' : 's'}</span>
      <button onClick={save}>Save mod</button>
      <button onClick={() => { if (confirm('Start a new, empty mod? Unsaved changes are lost.')) P.loadProject(emptyProject()) }}>New</button>
      {msg && <span className="flash">{msg}</span>}
    </div>
  )
}

function Setup({ status, onDone }) {
  const [folder, setFolder] = useState(status.settings?.game_folder || 'C:\\GOG Games\\Total Overdose')
  const [job, setJob] = useState(null)
  const [err, setErr] = useState(status.settings?.last_error || null)
  const browse = async () => { const r = await post('/api/dialog', { kind: 'folder' }); if (r.path) setFolder(r.path) }
  const go = async () => {
    setErr(null)
    try {
      await runJob('/api/setup', { folder }, setJob)
      await runJob('/api/prepare', {}, setJob)
      onDone()
    } catch (e) { setErr(e.message); setJob(null) }
  }
  return (
    <div className="setup">
      <h1>TOD Mod Studio</h1>
      <p>A level and data editor for Total Overdose. It reads your own installed game and never ships or copies its
        files: meshes, textures and level layouts are extracted from your game into a local cache, and mods are
        written as one override archive that the unmodified game loads.</p>
      <label>Your Total Overdose folder (the one with TOD.exe and blocks.naz)
        <div className="row"><input value={folder} onChange={e => setFolder(e.target.value)} />
          <button onClick={browse}>Browse</button></div>
      </label>
      <button className="primary" onClick={go} disabled={!!job && job.status !== 'failed'}>Use this folder</button>
      {job && <div className="progress">
        <div>{job.kind === 'prepare' ? 'Building the cache: ' : ''}{job.message || job.status}</div>
        {job.total > 0 && <progress value={job.done} max={job.total} />}
      </div>}
      {err && <p className="bad">{err}</p>}
      <p className="muted">Cache: {status.cache}</p>
    </div>
  )
}

function Settings({ status, refresh }) {
  const s = status.settings || {}
  const set = async (k, v) => { await post('/api/settings', { [k]: v }); refresh() }
  const [folder, setFolder] = useState(status.game.folder)
  const [job, setJob] = useState(null)
  const change = async () => { try { await runJob('/api/setup', { folder }, setJob); refresh() } catch (e) { alert(e.message) } }
  const rebuild = async () => { try { await runJob('/api/prepare', {}, setJob) } catch (e) { alert(e.message) } }
  return (
    <div className="page">
      <section className="box">
        <h3>Game</h3>
        <div className="row"><input value={folder} onChange={e => setFolder(e.target.value)} />
          <button onClick={async () => { const r = await post('/api/dialog', { kind: 'folder' }); if (r.path) setFolder(r.path) }}>Browse</button>
          <button onClick={change}>Use</button></div>
        <p>TOD.exe {status.game.gog_exe ? 'is the GOG build (the version every tool was checked against)' :
          'is not the GOG build: level and data editing work on the data, features that need the GOG exe are off'}.</p>
        <p>Archives the game reads (configpc.txt): {status.game.chain.join(', ')}</p>
        {status.game.tod_hd && <p>TOD HD is installed ({status.game.hd_zips.join(', ')}).</p>}
      </section>
      <section className="box">
        <h3>Building mods</h3>
        <label className="check"><input type="checkbox" checked={s.build_on_installed !== false}
          onChange={e => set('build_on_installed', e.target.checked)} />
          <span>Build on top of what the game loads now (TOD HD's blocks and other installed archives). Off: build on the plain blocks.naz.</span></label>
        <label className="check"><input type="checkbox" checked={s.save_safe_delete !== false}
          onChange={e => set('save_safe_delete', e.target.checked)} />
          <span>Delete retires objects: moved 5 km below the world with collision off (keeps old saves working). Off: delete removes them, which breaks saves made in that section.</span></label>
        <label>Author name for your mods <input defaultValue={s.author || ''} onBlur={e => set('author', e.target.value)} /></label>
      </section>
      <section className="box">
        <h3>Unreal project (optional)</h3>
        <p className="muted">The Assets tab can show the replacement table of an Unreal project made with the TOD Level
          Editor plugin: pick its <code>Config/TODBridge</code> folder. Mod Studio only reads it.</p>
        <div className="row"><input defaultValue={s.ue_config || ''} placeholder="the Unreal project's Config/TODBridge folder"
          onBlur={e => set('ue_config', e.target.value)} />
          <button onClick={async () => { const r = await post('/api/dialog', { kind: 'folder' }); if (r.path) set('ue_config', r.path) }}>Browse</button></div>
      </section>
      <section className="box">
        <h3>Cache</h3>
        <p>{status.cache}</p>
        <button onClick={rebuild}>Prepare every map now</button>
        {job && <span> {job.message} {job.total ? `${job.done}/${job.total}` : ''}</span>}
      </section>
    </div>
  )
}
