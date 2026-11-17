// Large scene: a big captured or downloaded scene (one .glb) cut down to map pieces. Eight pages, one working state, one undo history.
// Source, Scale, Region, Clean, Textures, Sections, Collision, Send. The backend keeps the open file; this screen only holds the settings.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from '../api.js'
import { NumField, Seg, UndoRedo, useUI } from '../ui.jsx'
import { Meter } from '../Meters.jsx'
import { useHistory, useUndoKeys } from '../history.js'
import { t as tr } from '../i18n.js'
import ScalePage from './ScalePage.jsx'
import RegionPage from './RegionPage.jsx'
import { CleanPage, TexturesPage, SectionsPage, CollisionPage } from './StagePages.jsx'
import './scene.css'
import { followScale } from './followScale.js'

export const DEFP = {
  up: 'y', mirror: 'z', yaw: 0, scale: 1, place: [0, 0, 0], name: 'Scene',
  region: { polygon: null, mode: 'clip' },
  clean: { drop_exact: true, drop_near: true, strays: true, far_m: 60, weld_vertices: true },
  textures: { max_tex: 256, atlas: true, atlas_max_px: 64, budget_mb: 64, alpha: {} },
  sections: { section_m: 128, reduce: true, double_sided: true },
  collision: { enabled: true, surface: {} },
}
const PAGES = ['source', 'scale', 'region', 'clean', 'textures', 'sections', 'collision', 'send']
const labels = () => ({ source: tr('source'), scale: tr('scale'), region: tr('region'), clean: tr('clean'), textures: tr('textures'), sections: tr('sections'), collision: tr('collision'), send: tr('send') })
const STAGE_OF = { clean: 'clean', textures: 'textures', sections: 'chunks', collision: 'collision' }
const mb = n => n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GB' : (n / 1048576).toFixed(0) + ' MB'

export default function LargeScene({ go, onBack }) {
  const ui = useUI()
  const [page, setPage] = useState('source')
  const [params, setParams] = useState(DEFP)
  const [sc, setSc] = useState(null)                   // the open scene: { sid, file, triangles, ... }
  const [ov, setOv] = useState(null)                   // the top view
  const [rep, setRep] = useState({})                   // stage reports
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [path, setPath] = useState('')
  const pRef = useRef(params); pRef.current = params
  const hist = useHistory(() => pRef.current, v => { setParams(v); setRep({}) })
  useUndoKeys(hist)
  const edit = useCallback(fn => {
    hist.record()
    setParams(p => followScale(p, typeof fn === 'function' ? fn(p) : { ...p, ...fn }))
    setRep({})
  }, [hist])
  const S = { params, edit, sc, ov, rep, busy, err, setErr, setPage, hist }

  const open = async p => {
    setErr(null); setBusy('Reading the file')
    try {
      const r = await runJob('/api/scene/open', p ? { path: p } : {}, j => setBusy(j.message || 'Reading the file'))
      if (r.cancelled) { setBusy(null); return }
      setSc(r); setOv(null); setRep({})
      const g = r.up_guess || {}
      setParams(q => ({ ...q, up: g.suggest_up || 'y', mirror: 'z', name: r.file.replace(/\.[^.]+$/, '').slice(0, 24) || 'Scene' }))
      hist.clear()
      loadOverview(r.sid, { up: g.suggest_up || 'y', mirror: 'z' })
    } catch (e) { setErr(e.message) }
    setBusy(null)
  }
  const loadOverview = async (sid, p) => {
    try {
      const r = await runJob('/api/scene/overview', { sid, params: p }, j => setBusy(j.message || 'Top view'))
      setOv(r)
    } catch (e) { setErr(e.message) }
  }
  // the axes decide the top view: draw it again when they change
  const axesKey = sc ? [params.up, params.mirror, params.yaw].join() : null
  useEffect(() => {
    if (!sc || !ov) return
    const t = setTimeout(() => loadOverview(sc.sid, { up: params.up, mirror: params.mirror, yaw: params.yaw }), 250)
    return () => clearTimeout(t)
  }, [axesKey])

  const run = async stage => {
    if (!sc) return null
    setErr(null); setBusy(labels()[page])
    try {
      const r = await runJob('/api/scene/report', { sid: sc.sid, params, stage }, j => setBusy(j.message || labels()[page]))
      setRep(old => ({ ...old, ...r }))
      setBusy(null)
      return r
    } catch (e) { setErr(e.message) }
    setBusy(null)
    return null
  }
  S.run = run; S.open = open

  // deep links for screenshots and tests: ?scene_file=&scene_page=&scene_region=x0,z0,x1,z1&scene_scale=&scene_run=
  useEffect(() => {
    const u = new URLSearchParams(location.search)
    const f = u.get('scene_file')
    if (!f) { if (u.get('scene_page')) setPage(u.get('scene_page')); return }
    ;(async () => {
      await open(f)
      const r = u.get('scene_region')
      setParams(q => {
        const n = { ...q }
        if (u.get('scene_scale')) n.scale = Number(u.get('scene_scale'))
        if (u.get('scene_up')) n.up = u.get('scene_up')
        if (r) { const [a, b, c, d] = r.split(',').map(Number); n.region = { ...q.region, polygon: [[a, b], [c, b], [c, d], [a, d]] } }
        return n
      })
      if (u.get('scene_page')) setPage(u.get('scene_page'))
    })()
  }, [])
  useEffect(() => {
    const u = new URLSearchParams(location.search)
    const st = u.get('scene_run')
    if (st && sc && params.region.polygon && !rep[st] && !busy && !err) run(st)
  }, [sc, params.region.polygon, busy])

  const order = ['G3', 'L15', 'G2', 'M1', 'P5', 'P6', 'P8', 'L1']
  const meters = (rep.collision?.meters || rep.chunks?.meters || []).slice().sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
  const PageC = { scale: ScalePage, region: RegionPage, clean: CleanPage, textures: TexturesPage, sections: SectionsPage, collision: CollisionPage, send: SendPage, source: SourcePage }[page]
  const ready = !!sc
  return (
    <div className="screen scene">
      <div className="tb">
        <Seg value={page} onChange={setPage} options={PAGES.map(p => ({ value: p, label: labels()[p], title: p !== 'source' && !ready ? tr('open_a_scene_first') : undefined }))} />
        <span className="vsep" />
        <UndoRedo h={hist} compact />
        <div style={{ flex: 1 }} />
        {busy && <span className="muted small">{busy}{'…'}</span>}
        {onBack && <button onClick={onBack}>{tr('single_model')}</button>}
      </div>
      {meters.length > 0 && <div className="mstrip scene-meters">{meters.slice(0, 8).map(r => <Meter key={r.id} r={r} />)}</div>}
      {err && <div className="flash scene-err">{err}</div>}
      <PageC S={S} path={path} setPath={setPath} go={go} />
    </div>
  )
}

function SourcePage({ S, path, setPath }) {
  const { sc, params, edit } = S
  const g = sc?.up_guess
  return (
    <div className="page scene-page">
      <div className="row" style={{ maxWidth: 640 }}>
        <input placeholder={tr('path_of_a_glb_or_gltf')} aria-label={tr('scene_file')} value={path} onChange={e => setPath(e.target.value)} onKeyDown={e => e.key === 'Enter' && S.open(path)} />
        <button className="primary" onClick={() => S.open(path || null)} disabled={!!S.busy}>{tr('choose_78b7c9')}{'…'}</button>
      </div>
      {sc && <>
        <div className="scene-facts">
          <Fact k={tr('triangles')} v={sc.triangles.toLocaleString()} /><Fact k={tr('vertices')} v={sc.vertices.toLocaleString()} />
          <Fact k={tr('parts')} v={sc.prims.toLocaleString()} /><Fact k={tr('materials')} v={sc.materials.toLocaleString()} />
          <Fact k={tr('pictures')} v={sc.images.toLocaleString()} /><Fact k={tr('file')} v={mb(sc.size)} />
          <Fact k={tr('size')} v={sc.extent.map(v => Math.round(v)).join(' × ')} />
        </div>
        <h4>{tr('direction')}</h4>
        <div className="row" title={g?.turned ? tr('the_file_turns_a_z_up_scene') : undefined}>
          <Seg value={params.up} onChange={v => edit({ up: v })} options={[{ value: 'y', label: tr('y_up_f2d782') }, { value: 'z', label: tr('z_up') }, { value: '-y', label: tr('upside_down') }]} />
          <Seg value={params.mirror} onChange={v => edit({ mirror: v })} options={[{ value: 'z', label: tr('flip_z') }, { value: 'x', label: tr('flip_x') }, { value: 'none', label: tr('no_flip') }]} />
          <Seg value={String(params.yaw)} onChange={v => edit({ yaw: Number(v) })} options={['0', '90', '180', '270'].map(v => ({ value: v, label: v + '°' }))} />
        </div>
        {g?.turned && <div className="muted small">{tr('z_up_turned_by_the_file')}</div>}
        {g?.flipped && <div className="warn small">{tr('most_surfaces_face_down_try')}</div>}
        <div className="row" style={{ marginTop: 10 }}><button className="primary" onClick={() => S.setPage('scale')}>{tr('next')}</button></div>
      </>}
    </div>
  )
}

const Fact = ({ k, v }) => <div className="fact"><div className="v">{v}</div><div className="k">{k}</div></div>

function SendPage({ S, go }) {
  const { params, edit, sc, rep } = S
  const ui = useUI()
  const [kind, setKind] = useState('newmap')
  const [host, setHost] = useState('submap01_map02_lostoros_downtown.submap')
  const [done, setDone] = useState(null)
  const [projects, setProjects] = useState([])
  const [into, setInto] = useState('')
  useEffect(() => { get('/api/newmaps').then(r => setProjects(r.projects || [])).catch(() => {}) }, [done])
  const send = async () => {
    S.setErr(null)
    try {
      const target = { kind, name: params.name, id: into || undefined, host: kind === 'section' ? { block: host, enter: { pos: [-237, 2.5, -43.66], size: [12, 6, 2], orient: [0, 0.70710678, 0, 0.70710678] }, leave: { pos: [20, 2.5, 0], size: [12, 6, 2], orient: [0, 0, 0, 1] } } : undefined }
      const r = await runJob('/api/scene/send', { sid: sc.sid, params, target })
      setDone(r); ui.say(tr('sent'))
    } catch (e) { S.setErr(e.message) }
  }
  const st = rep.chunks?.stats
  useEffect(() => {                                    // link for screenshots: scene_send=1 sends as soon as the stages have run
    if (new URLSearchParams(location.search).get('scene_send') && rep.collision && !done && !S.busy) send()
  }, [rep.collision])
  return (
    <div className="page scene-page">
      <div className="row" style={{ maxWidth: 560 }}>
        <input value={params.name} aria-label={tr('name')} placeholder={tr('name')} onChange={e => edit({ name: e.target.value.replace(/[^A-Za-z0-9_ -]/g, '').slice(0, 30) })} />
        <Seg value={kind} onChange={setKind} options={[{ value: 'newmap', label: tr('new_map') }, { value: 'section', label: tr('section') }]} />
      </div>
      {kind === 'newmap' && projects.length > 0 && <div className="row" style={{ maxWidth: 560 }}>
        <select value={into} onChange={e => setInto(e.target.value)} aria-label={tr('into')}>
          <option value="">{tr('a_new_project')}</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.params.package || p.id}</option>)}
        </select>
      </div>}
      {kind === 'newmap' && <div className="row" style={{ maxWidth: 560 }} title={tr('where_the_district_stands_in_the_world')}>
        <span className="muted" style={{ flex: 'none' }}>{tr('place')}</span>
        <NumField value={params.place?.[0] ?? 0} digits={0} unit="x" onCommit={v => edit({ place: [v, params.place?.[1] ?? 0, params.place?.[2] ?? 0] })} label={tr('place_x')} />
        <NumField value={params.place?.[2] ?? 0} digits={0} unit="z" onCommit={v => edit({ place: [params.place?.[0] ?? 0, params.place?.[1] ?? 0, v] })} label={tr('place_z')} />
      </div>}
      {kind === 'section' && <div className="row" style={{ maxWidth: 560 }}><input value={host} aria-label={tr('host_section')} onChange={e => setHost(e.target.value)} /></div>}
      {st && <div className="scene-facts">
        <Fact k={tr('parts')} v={st.objects} /><Fact k={tr('triangles')} v={st.tris_out.toLocaleString()} /><Fact k={tr('pictures')} v={rep.textures?.report?.textures ?? ''} />
        <Fact k={tr('pieces')} v={(rep.collision?.stats?.pieces ?? 0).toLocaleString()} />
      </div>}
      <div className="row"><button className="primary" onClick={send} disabled={!sc || !params.region.polygon || !!S.busy}>{kind === 'section' ? tr('send_to_section') : tr('send_to_new_map')}</button></div>
      {done && <div className="scene-done">
        <div><b>{done.models}</b> {tr('parts')}, <b>{done.textures}</b> {tr('pictures')}</div>
        {(done.notes || []).slice(0, 5).map((n, i) => <div key={i} className="warn small">{n}</div>)}
        <div className="row"><button onClick={() => go && go('newmaps')}>{tr('open_in_new_maps')}</button></div>
      </div>}
    </div>
  )
}
