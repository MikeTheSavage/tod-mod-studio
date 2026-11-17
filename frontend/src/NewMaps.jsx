// New maps: where a map lives in the world (Atlas), how it is entered (Entrances), what it is (Map), whether it is ready (Ready) and what is
// installed (Manage). This file is the shell: the project, its undo, save / check / build / install and the pipeline. The areas live in ./world/.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import View3D from './View3D.jsx'
import { spotYaw, yawOrient, loaderOverlays } from './LoaderTopView.jsx'
import { useBundle, pickOfMapName, boundsOf, CONTEXT_LAYERS } from './levelLoad.js'
import { useUI, Menu, Seg, Pipeline, CheckRow, Advanced, UndoRedo } from './ui.jsx'
import { useHistory, useUndoKeys } from './history.js'
import { MeterStrip } from './Meters.jsx'
import { ProblemsBadge } from './ProblemsPanel.jsx'
import Snapshots from './Snapshots.jsx'
import { useStore, registerProject, setOpen as openProblems, useJump, recordResult } from './problemsStore.js'
import { useAutosave, loadAutosave } from './autosave.js'
import { t as tr } from './i18n.js'
import { useUi as useUiPrefs } from './uistore.js'
import * as W from './world/worldlib.js'
import { getJob, world } from './world/worldapi.js'
import Atlas from './world/Atlas.jsx'
import Entrances from './world/Entrances.jsx'
import { Card, Start } from './world/MapCard.jsx'
import { Ready, Manage } from './world/Manage.jsx'
import MapBuildTools from './mapbuild/MapBuildTools.jsx'

const short = e => e?.split('/').pop()
const AXC = ['var(--ax-x)', 'var(--ax-y)', 'var(--ax-z)']
const AREAS = ['atlas', 'entrances', 'map', 'ready', 'manage']
const urlArea = () => { const a = new URLSearchParams(location.search).get('area'); return AREAS.includes(a) ? a : 'atlas' }

function SpotFields({ spot, change, box = false }) {
  const size = spot.size || [12, 6, 2]
  return <>
    <div className="upper" style={{ marginTop: 8 }}>{tr('position')}</div>
    <div className="axes">{spot.pos.map((v, i) => <label key={i} className="axis" style={{ margin: 0 }}><span style={{ color: AXC[i] }}>{'XYZ'[i]}</span>
      <input aria-label={['x', 'height', 'z'][i]} type="number" step="any" value={v} onChange={e => change({ ...spot, pos: spot.pos.map((n, j) => j === i ? Number(e.target.value) : n) })} /></label>)}</div>
    <div className="prow"><div className="k">{tr('facing')}</div><div className="numfield"><input aria-label={tr('facing_degrees')} type="number" step="any" value={Math.round(spotYaw(spot) * 1000) / 1000}
      onChange={e => change({ ...spot, orient: yawOrient(Number(e.target.value)) })} /><span className="u">{'°'}</span></div></div>
    {box && <><div className="upper" style={{ marginTop: 8 }}>{tr('box_size')}</div>
      <div className="axes">{size.map((v, i) => <label key={i} className="axis" style={{ margin: 0 }}><span style={{ color: AXC[i] }}>{'WHL'[i]}</span>
        <input aria-label={['width', 'box height', 'length'][i]} type="number" min="0.01" step="any" value={v}
          onChange={e => change({ ...spot, size: size.map((n, j) => j === i ? Number(e.target.value) : n) })} /></label>)}</div></>}
  </>
}

export default function NewMaps({ go, ov }) {
  const ui = useUI()
  const prefs = useUiPrefs().prefs
  const pstore = useStore()
  const [area, setArea] = useState(urlArea)
  const [startOpen, setStartOpen] = useState(false)
  const [showChecks, setShowChecks] = useState(false)
  const [busyPct, setBusyPct] = useState(null)
  const [library, setLibrary] = useState({ projects: [], sources: {} })
  const [project, setProject] = useState(null), [mapIndex, setMapIndex] = useState(0)
  const [catalog, setCatalog] = useState([])
  const [selected, setSelected] = useState('arrival')
  const [busy, setBusy] = useState(null), [message, setMessage] = useState(''), [report, setReport] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [hosts, setHosts] = useState([]), [data, setData] = useState(null), [links, setLinks] = useState(null)
  const [analysis, setAnalysis] = useState(null), [clientItems, setClientItems0] = useState({})
  const setClientItems = (k, v) => setClientItems0(c => (JSON.stringify(c[k] || []) === JSON.stringify(v) ? c : { ...c, [k]: v }))
  const refresh = async () => setLibrary(await get('/api/newmaps'))
  useEffect(() => {
    refresh().catch(e => setMessage(e.message))
    get('/api/catalog').then(c => setCatalog(c.maps)).catch(e => setMessage(e.message))
    get('/api/world/atlas').then(setData).catch(e => setMessage(e.message))
    getJob('/api/newmap/hosts').then(r => setHosts(r.supported ? r.hosts : [])).catch(() => setHosts([]))
    get('/api/newmap/links').then(setLinks).catch(() => setLinks(null))
  }, [])
  useEffect(() => {
    if (!project && library.projects.length) {
      const want = new URLSearchParams(location.search).get('project')
      const p0 = structuredClone(library.projects.find(p => p.id === want) || library.projects[0])
      setProject(p0); setMapIndex(0); setSelected('arrival')
      loadAutosave('newmap', p0.id).then(a => { if (a) { setProject(c => c && c.id === p0.id ? { ...c, params: a.project } : c); setDirty(true); ui.say(tr('your_last_unsaved_changes_are_back')) } })
    }
  }, [library])
  useEffect(() => { loadAutosave('newmap', null).then(a => { if (a) { setProject({ params: a.project }); setMapIndex(0); setSelected('arrival'); setDirty(true); ui.say(tr('your_last_unsaved_changes_are_back')) } }) }, [])
  const params = project?.params, m = params?.maps[Math.min(mapIndex, (params?.maps.length || 1) - 1)]
  useEffect(() => { if (params) registerProject('newmap', project.id || null, params) }, [params, project?.id])
  useAutosave('newmap', project?.id || null, params, dirty && !!params)
  const [toolReq, setToolReq] = useState(null)
  // a click in Problems or Ready: the area, the map and the build tool that fix the problem
  const goTo = j => {
    if (j.map != null && j.map >= 0) setMapIndex(j.map)
    setArea(j.area || 'map')
    if (j.tool) setToolReq({ tab: j.tool, n: Date.now() })
    if (j.area === 'atlas') setSelected('arrival')
  }
  useJump('newmaps', ref => { goTo(ref); return true })
  const discardOk = async () => !dirty || await ui.confirm({ title: tr('discard_unsaved_changes'), body: tr('the_changes_to_this_map_project'), kept: tr('kept_other_map_projects_your_mod'), ok: tr('discard_changes') })
  const projRef = useRef(project); projRef.current = project
  const hist = useHistory(() => projRef.current?.params, v => { setProject(p => p && ({ ...p, params: v })); setDirty(true); setReport(null) })
  useUndoKeys(hist)
  const choose = async p => {
    if (!(await discardOk())) return
    hist.clear(); setProject(structuredClone(p)); setMapIndex(0); setDirty(false); setReport(null); setSelected('arrival')
  }
  const edit = next => { hist.record(); setProject({ ...project, params: next }); setDirty(true); setReport(null) }
  const editMap = next => edit({ ...params, maps: params.maps.map((v, i) => i === mapIndex ? next : v) })
  const save = async () => {
    const p = await post('/api/newmaps', { action: 'save', id: project.id, params })
    setProject(p); setDirty(false); await refresh(); return p
  }
  const action = async (name, pid) => {
    setBusy(name); setMessage('')
    try {
      if (pid && pid !== project?.id) {
        const r = await runJob('/api/newmaps', { action: name, id: pid }, j => setBusy(j.message || name))
        setMessage(r?.message || tr('done_e9b450')); setLibrary(await get('/api/newmaps')); get('/api/newmap/links').then(setLinks).catch(() => {}); return
      }
      const p = name === 'uninstall' || name === 'enable' || name === 'disable' ? project : await save()
      if (name === 'save') { setMessage(tr('project_saved')); return }
      const r = await runJob('/api/newmaps', { action: name, id: p.id }, j => { setBusy(j.message || name); setBusyPct(j.total ? 100 * j.done / j.total : null) })
      if (r.report) setReport(r.report)
      setMessage(r.message || tr('done_e9b450'))
      const lib = await get('/api/newmaps'); setLibrary(lib)
      setProject(lib.projects.find(v => v.id === p.id) || p)
      get('/api/newmap/links').then(setLinks).catch(() => {})
    } catch (e) { setMessage(e.message) } finally { setBusy(null) }
  }
  // the minimap pack of this project: save first (the server draws it from the saved recipe), then the job; its checks join Problems and Ready
  const writeMinimap = async () => {
    const p = await save()
    const r = await runJob('/api/newmaps', { action: 'minimap', id: p.id }, j => setBusy(j.message || 'minimap'))
    setBusy(null)
    const rows = (r.checks || []).filter(x => x.result !== 'PASS').map(x => ({ level: x.result === 'WARN' ? 'warn' : 'error', title: x.check, detail: x.evidence, map: undefined }))
    setClientItems('minimap', rows)
    return r
  }
  const createProject = async next => {
    if (!(await discardOk())) return
    hist.clear(); setProject({ params: next }); setMapIndex(0); setDirty(true); setSelected('arrival'); setReport(null); setArea('atlas')
  }
  const importFile = async path => {
    if (!(await discardOk())) return
    try { const p = await post('/api/newmaps', { action: 'import', path }); setDirty(false); hist.clear(); setProject(p); setMapIndex(0); setSelected('arrival'); setReport(null); await refresh() }
    catch (e) { setMessage(e.message) }
  }
  const removeProject = async id => {
    if (!(await ui.confirm({ title: tr('uninstall_this_map_package'), body: tr('the_map_package_is_taken_out'), kept: tr('kept_this_project_your_mod_library_b0da05'), ok: tr('uninstall_package') }))) return
    action('uninstall', id)
  }
  // ---- numbers the areas share: the live checks (server numbers, debounced) and what Problems and the install gate read
  useEffect(() => {
    if (!params) { setAnalysis(null); return }
    const h = setTimeout(() => { world('analyse', { params, id: project?.id }).then(setAnalysis).catch(() => {}) }, 700)
    return () => clearTimeout(h)
  }, [params])
  const report0 = report || (!dirty && project?.check?.report) || null
  const checks = report0?.checks || []
  const worldItems = useMemo(() => [...(analysis?.items || []), ...Object.values(clientItems).flat()], [analysis, clientItems])
  useEffect(() => {
    if (!params) return
    const list = [...checks.map(c => ({ result: c.result, title: c.check || c.name || c.title, detail: c.evidence || c.detail, jump: W.jumpOf(c.check || c.name || c.title) })),
      ...worldItems.map(x => ({ result: x.level === 'error' ? 'FAIL' : 'WARN', title: x.title, detail: x.detail, jump: W.jumpOf(x.title, x.where, x.map) }))]
    recordResult('/api/newmaps', { action: 'check' }, { report: { checks: list } })
  }, [report0, worldItems, params])
  const ready = useMemo(() => W.readiness(params, worldItems, [], checks), [params, worldItems, checks])
  const blocked = W.blocked(ready, pstore.data.newmap?.problems)
  const nProblems = ready.reduce((a, r) => a + r.errors, 0)
  const hostLabel = b => hosts.find(h => h.block === W.short(b))?.label || W.short(b)
  const allRows = useMemo(() => !params ? [] : [
    ...W.entranceRows(params, hostLabel).map(r => ({ ...r, key: 'c' + r.id, cur: true, project: params.package })),
    ...library.projects.filter(p => p.id !== project?.id).flatMap(p => W.entranceRows(p.params, hostLabel).map(r => ({ ...r, key: p.id + r.id, cur: false, project: p.params.package })))],
  [params, library, hosts, project?.id])
  const c = { params, m, mapIndex, setMapIndex, edit, editMap, hist, project, library, catalog, hosts, data, links, analysis, clientItems, setClientItems, ready, blocked, pstore, ov,
    hostLabel, allRows, setArea, goTo, say: setMessage, createProject, importFile, action, removeProject }

  // ---- the pipeline
  const nFail = checks.filter(x => x.result !== 'PASS' && x.result !== 'WARN').length, nWarn = checks.filter(x => x.result === 'WARN').length
  const installedHere = !!project?.id && (ov?.new_maps || []).some(n => n.id === project.id)
  const built = !!project?.build?.sha256
  const isBusy = !!busy
  const checkStep = (isBusy && busy !== 'save' && /check/i.test(busy)) ? { tone: 'busy', note: busy, pct: 30 }
    : !report0 ? { tone: 'idle', note: m ? tr('not_checked_yet') : tr('choose_a_project_first'), action: m ? tr('check') : undefined, onClick: () => action('check'), disabled: isBusy }
    : nFail ? { tone: 'bad', note: tr('n_problems_to_fix', { n: nFail }), action: tr('check_again'), onClick: () => action('check'), disabled: isBusy }
    : { tone: nWarn ? 'warn' : 'ok', note: nWarn ? tr('passed_with_n_warnings', { n: nWarn }) : tr('passed_271d60'), action: tr('details'), onClick: () => setShowChecks(!showChecks) }
  const buildStep = (isBusy && /build/i.test(busy)) ? { tone: 'busy', note: busy, pct: busyPct ?? 30 }
    : !m ? { tone: 'idle', note: tr('waits_for_the_check') }
    : nFail ? { tone: 'idle', note: tr('fix_the_problem_first') }
    : built && !dirty ? { tone: 'ok', note: tr('built_a6ad3f'), action: tr('build_again'), onClick: () => action('build'), disabled: isBusy }
    : { tone: 'ready', note: tr('ready_to_build'), action: tr('build'), onClick: () => action('build'), disabled: isBusy }
  const canInstall = !isBusy && !dirty && built && !blocked
  const installStep = (isBusy && /install/i.test(busy)) ? { tone: 'busy', note: busy, pct: 30 }
    : blocked && built ? { tone: 'bad', note: tr('fix_the_problems_first'), action: tr('see_them'), onClick: () => setArea('ready') }
    : installedHere && built && !dirty ? { tone: 'ok', note: tr('in_the_game'), action: tr('install_again'), onClick: () => action('install'), disabled: !canInstall }
    : canInstall ? { tone: 'ready', note: tr('not_in_the_game_yet'), action: tr('install_into_the_game'), onClick: () => action('install') }
    : { tone: 'idle', note: built ? tr('save_the_project_first') : tr('waits_for_the_build') }
  const steps = [{ label: tr('check'), ...checkStep }, { label: tr('build'), ...buildStep }, { label: tr('install_into_the_game'), ...installStep }]

  const areaOptions = [{ value: 'atlas', label: tr('atlas') }, { value: 'entrances', label: tr('entrances') }, { value: 'map', label: tr('map') },
    { value: 'ready', label: <>{tr('ready')}{nProblems > 0 && <span className="badge" style={{ marginLeft: 6, background: 'var(--bad-soft)', color: 'var(--bad)' }}>{'✕ '}{nProblems}</span>}</> },
    ...(prefs.mode === 'beginner' ? [] : [{ value: 'manage', label: tr('manage') }])]
  const emptyHere = !m

  return <div className="screen">
    <div className="tb">
      <Menu buttonClass="crumbbtn" label={<><em>{tr('map_project')}</em> {project?.params?.package || tr('choose_a_project')}{dirty ? ' *' : ''} {'▾'}</>}>{close => <>
        {library.projects.length === 0 && <div className="foot" style={{ border: 0 }}>{tr('no_map_projects_yet_press_new')}</div>}
        {library.projects.map(p => <div key={p.id} className={'item' + (p.id === project?.id ? ' on' : '')} onClick={() => { close(); const q = library.projects.find(x => x.id === p.id); if (q) choose(q) }}>{p.params.package}</div>)}</>}</Menu>
      <Seg value={area} onChange={setArea} options={areaOptions} label={tr('area')} padFirst />
      {m && params.maps.length > 1 && <select aria-label={tr('map_in_this_project')} style={{ width: 'auto' }} value={mapIndex} onChange={e => setMapIndex(Number(e.target.value))}>{params.maps.map((v, i) => <option key={i} value={i}>{v.card?.title || v.name}</option>)}</select>}
      {dirty && <span className="badge" style={{ background: 'var(--accent-soft)', color: 'var(--accent-text)' }}>{tr('unsaved')}</span>}
      <div style={{ flex: 1 }} />
      <UndoRedo h={hist} compact />
      <button onClick={() => setStartOpen(true)}>{tr('new_map_project')}</button>
      <button disabled={!m || !!busy} onClick={() => action('save')}>{tr('save_project')}</button>
    </div>
    <MeterStrip kind="newmap" data={pstore.data.newmap} go={go} extra={params ? <>
      <Snapshots kind="newmap" id={project?.id} getProject={() => params} ensureId={async () => (await save()).id}
                 onLoad={p => { hist.record(); setProject(cc => ({ ...cc, params: p })); setDirty(true); setReport(null) }} disabled={!!busy} />
      <ProblemsBadge data={pstore.data.newmap} onClick={() => openProblems(!pstore.open)} /></> : null} />
    {message && <div className="callout neutral" role="status" style={{ margin: 0, padding: '6px 12px', borderRadius: 0, display: 'flex', gap: 8, alignItems: 'center', overflowWrap: 'anywhere' }}>
      <span className="grow">{message}</span><button className="sm" onClick={() => setMessage('')}>{tr('dismiss')}</button></div>}
    <div style={{ flex: 1, display: 'flex', minHeight: 0, position: 'relative' }}>
      {emptyHere && area !== 'manage' && <div className="vp" style={{ display: 'grid', placeItems: 'center' }}>
        <div style={{ textAlign: 'center' }}><div className="muted" style={{ marginBottom: 10 }}>{tr('choose_a_map_project_or_make')}</div><button className="primary" onClick={() => setStartOpen(true)}>{tr('new_map_project')}</button></div></div>}
      {!emptyHere && area === 'atlas' && <Atlas c={c} />}
      {!emptyHere && area === 'entrances' && <Entrances c={c} />}
      {!emptyHere && area === 'map' && <MapArea c={c} toolReq={toolReq} writeMinimap={writeMinimap} selected={selected} setSelected={setSelected} busy={busy} report0={report0} showChecks={showChecks} setShowChecks={setShowChecks} />}
      {!emptyHere && area === 'ready' && <Ready c={c} />}
      {area === 'manage' && <Manage c={c} />}
      {startOpen && <Start c={c} onClose={() => setStartOpen(false)} />}
    </div>
    <Pipeline steps={steps} removeLabel={tr('uninstall_package')} onRemove={() => removeProject(project.id)} removeDisabled={!!busy || !project?.id || !installedHere} />
  </div>
}

// the inside of the new map: the arrival, the named arrivals and the way back, with the card and the building tools
function MapArea({ c, selected, setSelected, busy, report0, showChecks, setShowChecks, toolReq, writeMinimap }) {
  const { params, m, editMap, library, catalog, edit } = c
  const [kind, number] = selected.split(':'), index = Number(number)
  const [placingSpot, setPlacingSpot] = useState(false), [showMap, setShowMap] = useState(false)
  const apiRef = useRef({})
  const ext = m.placement === 'extension'
  const tps = m.teleports || []
  const active = kind === 'teleport' ? tps[index] : m[kind]
  const editSpot = next => { if (kind === 'teleport') editMap({ ...m, teleports: tps.map((v, i) => i === index ? next : v) }); else editMap({ ...m, [kind]: next }) }
  const cat = useMemo(() => ({ maps: catalog }), [catalog])
  const lvl = useBundle(showMap && !m.terrain ? pickOfMapName(cat, m.source) : null, true)
  const r2 = v => Math.round(v * 100) / 100
  const spots = [...(m.arrival ? [{ ...m.arrival, id: 'arrival', label: tr('main_arrival'), color: 'var(--ok)' }] : []), ...(m.return ? [{ ...m.return, id: 'return', label: tr('return'), color: 'var(--accent)' }] : []),
    ...tps.map((t, i) => ({ ...t, id: 'teleport:' + i, label: t.name }))]
  const overlays = useMemo(() => [...loaderOverlays({ volumes: [], spots, selected }),
    ...(m.terrain ? [{ id: 'ground', kind: 'zone', rect: W.ownRect(m), h: 1, y: 0, color: '#8aa0b8', opacity: 0.08, pickable: false }] : []),
    ...(m.walls || []).map((w, i) => ({ id: 'wall:' + i, kind: 'box', pos: w.pos, size: w.size, color: '#8491a1', label: w.name, pickable: false, opacity: 0.18, layer: 'walls' }))], [spots.length, selected, m])
  const focus = useMemo(() => {
    const pts = spots.map(v => v.pos).filter(Boolean)
    if (m.terrain) { const r = W.ownRect(m); pts.push([r[0], 0, r[1]], [r[2], 0, r[3]]) }               // the whole ground is in the frame
    const b = boundsOf(pts.length ? pts : [[0, 0, 0]], 40)
    return b ? { bounds: b, y: pts[0]?.[1] ?? 0 } : null
  }, [c.mapIndex, c.project?.id, m.name])
  const addTeleport = () => { editMap({ ...m, teleports: [...tps, { name: 'SPOT_' + Date.now().toString(36), pos: [...m.arrival.pos], orient: [0, 0, 0, 1] }] }); setSelected('teleport:' + tps.length) }
  const delTeleport = i => {
    const t = tps[i]
    if (W.entriesOf(m).some(e => e.arrive_at === t.name)) { c.say(tr('entrances_still_arrive_here_pick_another')); return }
    editMap({ ...m, teleports: tps.filter((_, j) => j !== i) }); setSelected('arrival')
  }
  const addReturn = () => { const a = m.arrival.pos; editMap({ ...m, return: { pos: [a[0] + 8, a[1] + 0.5, a[2]], orient: [0, 0, 0, 1], size: [8, 5, 1.5], target_map: 'MAINMAP_Map02_LosToros_Downtown', target_submap: 'SUBMAP01_Map02_LosToros_Downtown',
    teleport_to: 'TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill', teleport_block: 'overdose.main' } }); setSelected('return') }
  const checks = report0?.checks || []
  const title = kind === 'teleport' ? (active?.name || tr('named_arrival')) : kind === 'return' ? tr('return_spot') : tr('arrival_spot')
  if (ext) return <div className="split"><div className="vp" style={{ display: 'grid', placeItems: 'center' }}><div className="muted">{tr('a_section_lives_on_its_host')}</div></div>
    <div className="panel-r"><div className="panel-b"><Card m={m} params={params} edit={edit} editMap={editMap} say={c.say} length={library.sources[m.source]?.map_name.length} projectId={c.project?.id} /></div></div></div>
  return <div className="split">
    <div className="panel-l" style={{ overflow: 'auto', padding: '12px 8px' }}>
      <div className="upper" style={{ padding: '0 8px 6px' }}>{tr('inside_the_map')}</div>
      <div className={'step' + (kind === 'arrival' ? ' on' : '')} role="button" tabIndex={0} onClick={() => setSelected('arrival')} onKeyDown={e => e.key === 'Enter' && setSelected('arrival')}>
        <span className="mk" style={{ color: 'var(--ok)', borderColor: 'var(--ok)' }}>{'✓'}</span><div><div className="a">{tr('arrival_spot')}</div></div></div>
      <div className={'step' + (kind === 'return' ? ' on' : '')} role="button" tabIndex={0} onClick={() => m.return ? setSelected('return') : addReturn()} onKeyDown={e => e.key === 'Enter' && (m.return ? setSelected('return') : addReturn())}>
        <span className="mk" style={{ color: m.return ? 'var(--ok)' : 'var(--text-3)', borderColor: m.return ? 'var(--ok)' : 'var(--text-3)' }}>{m.return ? '✓' : '+'}</span><div><div className="a">{tr('return_spot')}</div></div></div>
      <div className="upper" style={{ padding: '10px 8px 4px' }}>{tr('named_arrivals')}</div>
      <div style={{ paddingLeft: 8 }}>
        {tps.map((t, j) => <div key={j} className={'li' + (selected === 'teleport:' + j ? ' sel' : '')} role="button" tabIndex={0} onClick={() => setSelected('teleport:' + j)} onKeyDown={e => e.key === 'Enter' && setSelected('teleport:' + j)}>
          <span className="nm">{t.name}</span><button className="link" aria-label={tr('delete') + ' ' + t.name} onClick={ev => { ev.stopPropagation(); delTeleport(j) }}>{tr('delete')}</button></div>)}
        <button className="link" style={{ margin: '2px 0 6px' }} onClick={addTeleport}>{tr('add_a_named_arrival')}</button></div>
    </div>
    <View3D defaultMode="top" apiRef={apiRef} bundle={lvl.bundle} view={lvl.view} layers={CONTEXT_LAYERS} overlays={overlays} focus={focus} planeY={m.arrival?.pos?.[1] ?? 0}
      onPickOverlay={id => { if (id.startsWith('teleport:') || ['arrival', 'return'].includes(id)) setSelected(id) }}
      onGround={(pos, ev, g) => { if (active && !placingSpot) editSpot({ ...active, pos: [r2(pos[0]), g ? r2(pos[1]) : active.pos[1], r2(pos[2])] }) }}
      placing={placingSpot && active ? { kind: 'spot', label: title, size: active.size, arrow: true, facingDrag: true, color: '#f2a541', yaw: spotYaw(active) } : null}
      onPlace={(pos, yaw) => { if (active) editSpot({ ...active, pos: [r2(pos[0]), r2(pos[1]), r2(pos[2])], orient: yawOrient(Math.round(yaw)) }); setPlacingSpot(false) }}>
      <div style={{ position: 'absolute', left: 12, top: 12, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', maxWidth: 'calc(100% - 135px)' }}>
        {!m.terrain && <button className={'sm' + (showMap ? ' on' : '')} aria-pressed={showMap} title={tr('draw_the_map_under_the_spots')} onClick={() => setShowMap(!showMap)}>{tr('map')}</button>}
        <button className={'sm' + (placingSpot ? ' on' : '')} disabled={!active} title={tr('click_where_it_goes_drag_after')} onClick={() => setPlacingSpot(!placingSpot)}>{tr('place_c32a01')}</button>
        {lvl.busy && <span className="small muted">{lvl.busy}{'…'}</span>}
      </div>
      <MapBuildTools map={m} project={params} pid={c.project?.id} commit={editMap} viewApi={apiRef} writeMinimap={writeMinimap} toolRequest={toolReq} />
      {report0 && showChecks && <div className="checks" style={{ position: 'absolute', left: 12, right: 12, bottom: 56, maxHeight: '50%', overflow: 'auto', border: '1px solid var(--line-strong)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-2)' }}>
        <div className="ch"><span style={{ fontWeight: 600 }}>{tr('check_results')}</span><span className="muted small">{report0.result}</span><span style={{ flex: 1 }} /><button className="sm" onClick={() => setShowChecks(false)}>{tr('close')}</button></div>
        {checks.map((x, i) => <CheckRow key={i} tone={x.result === 'PASS' ? 'ok' : x.result === 'WARN' ? 'warn' : 'bad'} title={x.check} fix={x.evidence} />)}</div>}
      {busy && !/check|build|install/i.test(busy) && <div className="busy">{busy}</div>}
    </View3D>
    <div className="panel-r">
      <div className="panel-h"><div className="grow"><div className="t" style={{ fontWeight: 600 }}>{active ? title : tr('map')}</div></div></div>
      <div className="panel-b">
        {active && <>
          {kind === 'teleport' && <div className="prow"><div className="k">{tr('name')}</div><input aria-label={tr('name')} value={active.name} onChange={e => {
            const name = e.target.value
            const es = W.entriesOf(m).map(v => v.arrive_at === active.name ? { ...v, arrive_at: name } : v)
            const next = { ...m, teleports: tps.map((v, i) => i === index ? { ...v, name } : v), entries: es }; delete next.entry
            editMap(next) }} /></div>}
          <SpotFields spot={active} change={editSpot} box={kind === 'return'} />
          {kind === 'arrival' && <label>{tr('ground_check')}<select value={active.floor || 'vanilla'} onChange={e => editSpot({ ...active, floor: e.target.value })}><option value="vanilla">{tr('use_the_source_map_s_ground')}</option><option value="none">{tr('require_new_solid_ground')}</option></select></label>}
          {kind === 'return' && <Advanced title={tr('where_it_leads')} note={tr('map_section_arrival_node')}>{['target_map', 'target_submap', 'teleport_to', 'teleport_block'].map(k => <label key={k}>{({ target_map: 'Return map name', target_submap: 'Return section name', teleport_to: 'Return arrival node', teleport_block: 'Block containing that node' })[k]}<input value={active[k] || ''} onChange={e => editSpot({ ...active, [k]: e.target.value })} /></label>)}</Advanced>}
          {kind === 'return' && <button className="sm danger" onClick={() => { const n = { ...m }; delete n.return; editMap(n); setSelected('arrival') }}>{tr('remove_the_return_spot')}</button>}
        </>}
        <div className="upper" style={{ marginTop: 8 }}>{tr('map_card')}</div>
        <Card m={m} params={params} edit={edit} editMap={editMap} say={c.say} length={library.sources[m.source]?.map_name.length} projectId={c.project?.id} />
        <Advanced title={tr('the_map_itself')} note={tr('names_and_clone_source')}>
          <label className="kv">{tr('map_name')}<input value={m.name} onChange={e => editMap({ ...m, name: e.target.value })} /></label>
          <label className="kv">{tr('clone_source')}<select value={m.source} onChange={e => editMap({ ...m, source: e.target.value, nodes_in: library.sources[e.target.value].subparent ? 'submap' : 'map' })}>{Object.entries(library.sources).map(([k, v]) => <option key={k} value={k}>{v.map_name}</option>)}</select></label>
          <p className="muted small">{tr('the_map_name_is')}{' '}{library.sources[m.source]?.map_name.length}{' '}{tr('characters')}</p>
          {params.import_warning && <p className="warn small">{params.import_warning}</p>}
        </Advanced>
      </div>
      <div className="panel-f"><button disabled={!!busy} onClick={() => c.action('save')}>{tr('save_project')}</button></div>
    </div>
  </div>
}
