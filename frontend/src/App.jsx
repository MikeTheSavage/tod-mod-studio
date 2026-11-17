import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { get, post, runJob, jobsStore } from './api.js'
import { useProject, emptyProject } from './project.js'
import { UIProvider, useUI, Icon, ChangeBar, UndoRedo } from './ui.jsx'
import LevelEditor from './LevelEditor.jsx'
import DataEditors from './DataEditors.jsx'
import Mods from './Mods.jsx'
import TestSave from './TestSave.jsx'
import Collision from './Collision.jsx'
import Assets from './Assets.jsx'
import ImportModel from './ImportModel.jsx'
import Textures from './Textures.jsx'
import Routes from './Routes.jsx'
import Missions from './Missions.jsx'
import Sections from './Sections.jsx'
import NewMaps from './NewMaps.jsx'
// the building tools' stand-alone page loads only with ?build=1 (its own chunk; nothing is read otherwise)
try { if (new URLSearchParams(location.search).get('build')) import('./mapbuild/devhook.jsx') } catch { /* no window */ }
import MissionTemplates from './MissionTemplates.jsx'
import Home from './Home.jsx'
import FirstRun from './FirstRun.jsx'
import Settings from './Settings.jsx'
import { UpdateBar, useOpenFiles } from './Notices.jsx'
import Debug from './Debug.jsx'
import { refreshTest, useTest } from './testStore.js'
import { partBCount } from './partb.js'
import { useUndoKeys } from './history.js'
import Limits, { WorstChip } from './Meters.jsx'
import ProblemsPanel, { ProblemsStatus } from './ProblemsPanel.jsx'
import Snapshots from './Snapshots.jsx'
import { registerProject, kindOfScreen, setGo, setOpen as setProblemsOpen, useFeed } from './problemsStore.js'
import { useAutosave, loadAutosave, clearAutosave } from './autosave.js'
import { installKeys, openPalette } from './commands.js'
import { CommandHost } from './Palette.jsx'
import PadHost, { PadHints } from './pad/PadHost.jsx'
import HelpHost, { HelpButton } from './Help.jsx'
import Onboarding from './Onboarding.jsx'
import { openHelp, offerWalkthrough, saveHelp, startLesson, gotoStep } from './helpstore.js'
import { anchorFor } from './helpdata.js'
import { useUi } from './uistore.js'
import { visibleScreens, visibleAreas } from './uiprefs.js'
import { parseChangelog, newest } from './whatsnew.js'
import changelogText from './changelog.md?raw'
import { installA11y } from './a11y.js'
import { t as tr } from './i18n.js'

// The twelve screens, grouped into the design's areas. Screen ids are the old tab names so ?tab= links keep working.
export const AREAS = [
  { id: 'home', label: tr('home'), icon: 'home', hint: tr('start_here'), title: tr('home'), screens: [['home', 'What do you want to do?']] },
  { id: 'world', label: tr('world'), icon: 'world', hint: tr('edit_the_world'), title: tr('edit_the_world'),
    screens: [['level', 'Level editor'], ['routes', 'Routes'], ['sections', 'Sections'], ['collision', 'Collision'], ['missions', 'Mission logic']] },
  { id: 'create', label: tr('create'), icon: 'create', hint: tr('add_content'), title: tr('add_content'), screens: [['mtpl', 'Mission templates'], ['newmaps', 'New maps'], ['import', 'Import model'], ['textures', 'Textures']] },
  { id: 'tune', label: tr('tune'), icon: 'tune', hint: tr('tune_the_numbers'), title: tr('tune'), screens: [['data', 'Game data']] },
  { id: 'play', label: tr('play'), icon: 'play', hint: tr('play_and_share'), title: tr('play_and_share'), screens: [['mods', 'Mods and install'], ['save', 'Test saves'], ['limits', 'Limits']] },
  { id: 'debug', label: tr('debug'), icon: 'debug', hint: tr('test_in_the_game'), title: tr('test_and_debug'), screens: [['debug', 'Test run'], ['bisect', 'Find a bad mod'], ['support', 'Support']] },
  { id: 'assets', label: tr('assets'), icon: 'assets', hint: tr('browse_the_models'), title: tr('asset_catalogue'), bottom: true, screens: [['assets', 'Catalogue']] },
  { id: 'settings', label: tr('settings'), icon: 'settings', hint: tr('settings'), title: tr('settings'), bottom: true, screens: [['settings', 'Settings']] },
]
const SCREEN_NAME = Object.fromEntries(AREAS.flatMap(a => a.screens))
const LEGACY = { level: 'level', collision: 'collision', assets: 'assets', routes: 'routes', missions: 'missions', sections: 'sections', newmaps: 'newmaps',
  mtpl: 'mtpl', import: 'import', textures: 'textures', data: 'data', mods: 'mods', save: 'save', settings: 'settings', home: 'home', limits: 'limits', debug: 'debug', bisect: 'bisect', support: 'support' }

const lsGet = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const lsSet = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private window */ } }

export default function App() {
  return <UIProvider><Main /><PadHost /></UIProvider>
}

const PROJECT_SCREENS = ['level', 'data', 'collision', 'routes', 'missions', 'sections', 'import', 'textures']
const sigOf = p => JSON.stringify({ ...p, id: undefined, view: undefined })
const changeCount = p => p.level.length + Object.values(p.data || {}).reduce((a, v) => a + Object.keys(v).length, 0) + (p.collision || []).length + (p.models || []).length + (p.textures || []).length + partBCount(p)

function Main() {
  const ui = useUI()
  const look = useUi()
  const theme = look.resolved
  const [status, setStatus] = useState(null)
  const [screen, setScreen] = useState('home')
  const [saveSpot, setSaveSpot] = useState(null)
  const [frActive, setFrActive] = useState(false)
  const [ov, setOv] = useState(null)
  const [update, setUpdate] = useState(null)
  const P0 = useProject()
  const [savedSig, setSavedSig] = useState(() => lsGet('todms.saved.v1', null))
  const jobs = useSyncExternalStore(jobsStore.subscribe, jobsStore.get)
  const refresh = useCallback(() => get('/api/status').then(setStatus).catch(e => setStatus({ error: e.message })), [])
  const refreshOv = useCallback(() => get('/api/overview').then(setOv).catch(() => {}), [])
  useEffect(() => { refresh() }, [])
  const [linkWait, setLinkWait] = useState(() => !!new URLSearchParams(location.search).get('mod'))

  useEffect(() => installA11y(), [])
  useEffect(() => {          // screenshot / link hooks: ?open=help&q=&htab=&anchor= and ?lesson=<id>&step=<n>
    const q = new URLSearchParams(location.search)
    if (q.get('open') === 'help') setTimeout(() => openHelp({ tab: q.get('htab') || 'guide', anchor: q.get('anchor'), query: q.get('q') || '' }), 1200)
    if (q.get('lesson')) setTimeout(() => { startLesson(q.get('lesson')); if (q.get('step')) gotoStep(Number(q.get('step'))) }, 1500)
  }, [])
  useEffect(() => {
    const f1 = e => { if (e.key === 'F1') { e.preventDefault(); openHelp({ anchor: anchorFor(screenRef.current) }) } }
    window.addEventListener('keydown', f1)
    return () => window.removeEventListener('keydown', f1)
  }, [])
  useEffect(() => { const off = installKeys(); if (new URLSearchParams(location.search).get('open') === 'palette') setTimeout(() => openPalette(true), 1500); return off }, [])
  const screenRef = React.useRef('home')
  const mode = look.prefs.mode
  const navCommands = useMemo(() => [...AREAS.flatMap(a => visibleScreens(a.screens, mode, '').map(([k, l]) => ({ id: 'go.' + k, label: 'Go to ' + l, group: 'Go', run: () => setScreen(k) }))),
    { id: 'help.open', label: tr('open_help'), group: 'Help', run: () => openHelp({ anchor: anchorFor(screenRef.current) }) }], [mode])
  const project = P0.project
  screenRef.current = screen
  useUndoKeys(P0, PROJECT_SCREENS.includes(screen))
  const sig = sigOf(project)
  const changes = changeCount(project)
  const dirty = changes > 0 && sig !== savedSig
  const markSaved = p => { const s = sigOf(p); setSavedSig(s); lsSet('todms.saved.v1', s) }
  // the project API, with "saved" tracked beside it
  const P = useMemo(() => ({ ...P0, loadProject: p => { P0.loadProject(p); markSaved(p) } }), [P0])

  useEffect(() => {
    const q = new URLSearchParams(location.search)
    if (q.get('mod')) get('/api/mods/get', { id: q.get('mod') }).then(m => P.loadProject({ ...emptyProject(), ...m }))
      .catch(() => {}).finally(() => setLinkWait(false))
    const t = q.get('tab')
    if (t && LEGACY[t]) setScreen(LEGACY[t])
    else if (lsGet('todms.last', null) && !q.get('mod')) setScreen('home')
  }, [])
  useEffect(() => { if (screen !== 'home') lsSet('todms.last', screen) }, [screen])
  // facts for the status bar: refresh now, when a job ends, and every few seconds
  useEffect(() => { if (status?.ready) { refreshOv(); const t = setInterval(refreshOv, 5000); return () => clearInterval(t) } }, [status?.ready])
  // opt-in only: the check runs at start when online features AND the start-up check are on in Settings
  useEffect(() => {
    const st = status?.settings || {}
    if (status?.ready && st.online && st.update_auto && st.update_url) post('/api/update', { action: 'check' }).then(setUpdate).catch(() => {})
  }, [status?.ready])
  useOpenFiles(!!status?.ready && !frActive, () => refreshOv())
  useEffect(() => { if (status?.ready) { refreshTest(true); const t = setInterval(() => refreshTest(), 4000); return () => clearInterval(t) } }, [status?.ready])
  const jobCount = jobs.length
  useEffect(() => { if (status?.ready) refreshOv() }, [jobCount])

  // live meters and the Problems list: the screens register their project, the feed asks the backend
  const kind = kindOfScreen(screen)
  useEffect(() => { registerProject('level', project.id || null, project) }, [project])
  useEffect(() => { setGo(setScreen); if (new URLSearchParams(location.search).get('open') === 'problems') setProblemsOpen(true) }, [])
  const pdata = useFeed(kind, !!status?.ready && !frActive)
  // autosave: the unsaved mod goes to the backend a few seconds after each change; the next start restores it
  useAutosave('level', null, project, dirty)
  const restored = React.useRef(false)
  useEffect(() => {
    if (!status?.ready || restored.current) return
    restored.current = true
    if (changes > 0 || linkWait) return
    loadAutosave('level', null).then(a => {
      if (a && a.project && changeCount({ collision: [], data: {}, ...a.project }) > 0) {
        P0.loadProject({ ...emptyProject(), ...a.project })
        ui.say(tr('your_last_unsaved_changes_are_back'))
      }
    })
  }, [status?.ready])

  if (!status || linkWait) return <div className="splash">{tr('tod_mod_studio')}</div>
  if (status.error) return <div className="splash">{tr('backend_not_reachable')}{' '}{status.error}</div>
  if (!status.ready || frActive) return <FirstRun status={status} onDone={() => { saveHelp({ seen: newest(parseChangelog(changelogText)) }); setFrActive(false); refresh(); setScreen('home'); offerWalkthrough() }} onGame={refresh} keepOpen={() => setFrActive(true)} />

  const go = s => { setScreen(s) }
  const spot = s => { setSaveSpot(s); go('save') }
  const area = AREAS.find(a => a.screens.some(s => s[0] === screen)) || AREAS[0]
  const tabs = visibleScreens(area.screens, mode, screen)

  const save = async () => {
    try {
      const m = await post('/api/mods/save', { mod: project })
      P.replace({ ...project, id: m.id }); markSaved(project); clearAutosave('level', null)
      ui.say(tr('mod_saved'))
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const newMod = async () => {
    if (dirty && !(await ui.confirm({ title: tr('start_a_new_empty_mod'), body: `The ${changes} unsaved change${changes === 1 ? '' : 's'} in "${project.name}" will be lost.`,
      kept: tr('kept_mods_already_saved_in_your'), ok: tr('start_a_new_mod') }))) return
    P.loadProject(emptyProject()); clearAutosave('level', null); go('level')
  }
  const ensureId = async () => {
    if (project.id) return project.id
    const m = await post('/api/mods/save', { mod: project })
    P.replace({ ...project, id: m.id }); markSaved(project)
    return m.id
  }
  const common = { status, project, commit: P.commit, go, refresh, theme }

  return (
    <div className="shell">
      <a className="skip" href="#main" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus() }}>{tr('skip_to_the_main_content')}</a>
      <header className="topbar" role="banner">
        <button className="logo" onClick={() => go('home')} title={tr('home')} aria-label={tr('home')}><i><b /></i></button>
        <div className="title">{area.title}</div>
        {tabs.length > 1 && <div className="seg lg" role="tablist" aria-label={area.title}>
          {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={screen === k} className={screen === k ? 'on' : ''} onClick={() => go(k)}>{l}</button>)}
        </div>}
        <HelpButton onClick={() => openHelp({ anchor: anchorFor(screen) })} />
        <div style={{ flex: 1 }} />
        {PROJECT_SCREENS.includes(screen) && <UndoRedo h={P} compact />}
        <div className="upper" style={{ flex: 'none' }}>{tr('mod')}</div>
        <div className={'modbox' + (dirty ? ' dirty' : '')}>
          <input value={project.name} aria-label={tr('mod_name')} title={tr('mod_name')} onChange={e => P.replace({ ...project, name: e.target.value })} />
          {dirty ? <span className="unsaved"><span className="dot" style={{ background: 'var(--accent)' }} />{changes}{' '}{tr('unsaved_change')}{changes === 1 ? '' : 's'}</span>
            : <span className="saved">{changes ? `${changes} change${changes === 1 ? '' : 's'}, saved` : 'No changes yet'}</span>}
        </div>
        <Snapshots kind="level" id={project.id} getProject={() => project} ensureId={ensureId} onLoad={p => P0.loadProject({ ...emptyProject(), ...p, id: project.id })} />
        <button className="primary" onClick={save}>{tr('save_mod')}</button>
        <button onClick={newMod}>{tr('new')}</button>
      </header>
      <div className="body">
        <nav className="rail" aria-label={tr('areas')}>
          {visibleAreas(AREAS, mode, screen).filter(a => !a.bottom).map(a => <RailButton key={a.id} a={a} on={a === area} go={go} mode={mode} />)}
          <div style={{ flex: 1 }} />
          {visibleAreas(AREAS, mode, screen).filter(a => a.bottom).map(a => <RailButton key={a.id} a={a} on={a === area} go={go} bottom mode={mode} />)}
        </nav>
        <main className="main" id="main" tabIndex={-1} aria-label={area.title}>
          <UpdateBar info={update} onClose={() => setUpdate(null)} />
          {screen === 'home' && <Home {...common} dirty={dirty} changes={changes} openFirstRun={() => setFrActive(true)} />}
          {screen === 'level' && <LevelEditor status={status} {...P} theme={theme} go={go} dirty={dirty} setSaveSpot={spot} />}
          {screen === 'collision' && <Page><Collision status={status} project={project} commit={P.commit} /><Bar {...common} /></Page>}
          {screen === 'assets' && <Page><Assets status={status} /></Page>}
          {screen === 'routes' && <Page><Routes status={status} project={project} commit={P.commit} /><Bar {...common} /></Page>}
          {screen === 'missions' && <Page><Missions status={status} project={project} commit={P.commit} /><Bar {...common} /></Page>}
          {screen === 'sections' && <Page><Sections status={status} project={project} commit={P.commit} /><Bar {...common} /></Page>}
          {screen === 'newmaps' && <NewMaps go={go} ov={ov} />}
          {screen === 'mtpl' && <MissionTemplates status={status} go={go} />}
          {screen === 'import' && <ImportModel project={project} commit={P.commit} go={go} />}
          {screen === 'textures' && <Textures project={project} commit={P.commit} go={go} />}
          {screen === 'data' && <DataEditors {...common} />}
          {screen === 'mods' && <Mods status={status} project={project} loadProject={P.loadProject} replace={P.replace} refresh={() => { refresh(); refreshOv() }} ov={ov} dirty={dirty} go={go} />}
          {screen === 'save' && <TestSave status={status} spot={saveSpot} />}
          {(screen === 'debug' || screen === 'bisect' || screen === 'support') && <Debug view={screen} project={project} go={go} />}
          {screen === 'limits' && <Limits />}
          {screen === 'settings' && <Settings status={status} refresh={refresh} openFirstRun={() => setFrActive(true)} onUpdate={setUpdate} />}
        </main>
      </div>
      <ProblemsPanel data={pdata} kind={kind} />
      <CommandHost extra={navCommands} />
      <HelpHost project={project} dirty={dirty} loadProject={P.loadProject} go={go} />
      <Onboarding screen={screen} project={project} ready={!!status.ready && !frActive} />
      <StatusBar status={status} ov={ov} jobs={jobs} go={go} pdata={pdata} />
    </div>
  )
}

const Page = ({ children }) => <div className="screen" style={{ overflow: 'hidden' }}>{children}</div>
const Bar = ({ project, go }) => {
  const n = changeCount(project)
  return <ChangeBar count={n} name={project.name} go={() => go('mods')} />
}

function RailButton({ a, on, go, bottom, mode }) {
  const first = visibleScreens(a.screens, mode, on ? a.screens[0][0] : '')[0] || a.screens[0]
  return (
    <button className={(on ? 'on ' : '') + (bottom ? 'bottom' : '')} title={a.hint} aria-label={a.label} aria-current={on ? 'page' : undefined} onClick={() => go(first[0])}>
      <Icon name={a.icon} /><span>{a.label}</span>
    </button>
  )
}

function StatusBar({ status, ov, jobs, go, pdata }) {
  const ui = useUI()
  const wide = true
  const rebuild = async () => { try { await runJob('/api/pack/rebuild', {}); ui.say(tr('rebuilt')) } catch (e) { ui.say(e.message, 'bad') } }
  const j = jobs[0]
  const pct = j && j.total > 0 ? Math.round(100 * j.done / j.total) : null
  const mods = ov?.mods_installed?.length || 0, nm = ov?.new_maps?.length || 0, ms = ov?.missions_installed || 0
  const parts = [mods ? `${mods} mod${mods === 1 ? '' : 's'}` : null, nm ? `${nm} new map${nm === 1 ? '' : 's'}` : null, ms ? `${ms} mission${ms === 1 ? '' : 's'}` : null].filter(Boolean)
  const folder = status.game.folder
  const left = ov?.mission_slots_left
  return (
    <footer className="statusbar">
      <span className="it click" title={folder} onClick={() => go('settings')}><span className="dot" style={{ background: 'var(--ok)' }} /><span className="t3">{tr('game_folder')}</span><span className="path wide-only">{folder}</span></span>
      {status.game.tod_hd && <><span className="sep" /><span className="it">{tr('tod_hd')}</span></>}
      <span className="sep" />
      <span className="it"><span className="dot" style={ov?.game_running ? { background: 'var(--warn)' } : { border: '1px solid var(--text-3)' }} />{ov?.game_running ? 'Game is running' : 'Game is not running'}</span>
      {ov?.test?.status === 'running' && <><span className="sep" /><span className="it click" onClick={() => go('debug')}><span className="dot" style={{ background: 'var(--accent)' }} />{tr('test_game_is_running')}</span></>}
      {ov?.test?.status === 'exited' && ov.test.crashed && <><span className="sep" /><span className="it click" onClick={() => go('debug')}><span className="dot" style={{ background: 'var(--bad)' }} />{tr('test_game_crashed')}</span></>}
      <span className="sep" />
      <span className="it click" onClick={() => go('mods')}><span className="t3">{tr('in_the_game')}</span> {ov ? (parts.length ? parts.join(' · ') : 'nothing yet') : '...'}</span>
      {ov?.gameplay_plus && <span className="wide-only" style={{ display: 'contents' }}><span className="sep" /><span className="it">{tr('gameplay_detected')}</span></span>}
      {ov?.stale?.stale && <><span className="sep" /><span className="it stale" title={(ov.stale.changed || []).join(', ')}><span className="dot" style={{ background: 'var(--warn)' }} />{tr('game_changed_since_install')}<button className="sm" style={{ height: 20, padding: '0 8px' }} disabled={jobs.length > 0} onClick={rebuild}>{tr('rebuild')}</button></span></>}
      <span style={{ flex: 1 }} />
      <span className="it" style={{ flex: 'none', minWidth: 0 }}>
        {j ? <><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 360 }}>{j.label}{jobs.length > 1 ? ` (+${jobs.length - 1})` : ''}</span>
          <span className={'bar' + (pct == null ? ' indet' : '')}><i style={pct != null ? { width: pct + '%' } : undefined} /></span>
          <span style={{ fontVariantNumeric: 'tabular-nums', minWidth: 28 }}>{pct != null ? pct + '%' : ''}</span></> : <span className="t3">{tr('no_jobs_running')}</span>}
      </span>
      <span className="sep" /><PadHints />
      <span className="sep" /><ProblemsStatus data={pdata} />
      <span className="sep" /><WorstChip go={go} />
      {left != null && <><span className="sep" /><span className="it" style={{ flex: 'none' }}><b>{left}{' '}{tr('of')}{' '}{ov.mission_slots_total}</b> <span className="mt-wide">{tr('new_mission_slots_left')}</span><span className="mt-min">{tr('mission_slots_left')}</span></span></>}
    </footer>
  )
}
