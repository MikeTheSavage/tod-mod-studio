// Import a model: a .glb / .gltf / .obj with its textures, as a NEW model the level editor can place or as a REPLACEMENT for a game model.
// The preview is the baked result (what the game will hold), drawn with the reference figure; every number is checked against the limits.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post, runJob } from './api.js'
import { Seg, Switch, RangeField, NumField, useUI } from './ui.jsx'
import { ModelCanvas } from './AssetView.jsx'
import { Meter, MeterStrip } from './Meters.jsx'
import { useStore, useJump } from './problemsStore.js'
import { t as tr } from './i18n.js'
import LargeScene from './scene/LargeScene.jsx'
import { inbox, saveAddon } from './blenderInbox.js'

const DEF = { up: 'y', mirror: 'z', yaw: 0, scale: 1, origin: 'bottom', reduce: 1, max_tex: 512, tex_format: 'auto', double_sided: true,
  collision: { mode: 'hull', material: 'Stone', max_pieces: 24 }, keep_collision: true }
const AXES = [['y', 'tall'], ['x', 'wide'], ['z', 'deep']]
const kb = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'

export default function ImportModel({ project, commit, go }) {
  const ui = useUI()
  const store = useStore()
  const [path, setPath] = useState('')
  const [file, setFile] = useState(null)               // { sha, file, name, images, extent, suggest }
  const [params, setParams] = useState(DEF)
  const [mode, setMode] = useState('new')
  const [target, setTarget] = useState(null)           // { path, name }
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(null)         // id of the entry being changed
  const [pv, setPv] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [axis, setAxis] = useState('y')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState(null)
  const [scan, setScan] = useState(false)
  const [tick, setTick] = useState(0)
  const seq = useRef(0)
  const [ccc, setCcc] = useState([])                  // vehicles of the game data folder set in Settings
  const [big, setBig] = useState(() => new URLSearchParams(location.search).get('mode') === 'scene')
  const models = project.models || []

  const open = async (p) => {
    setErr(null)
    try {
      const r = await post('/api/import/analyze', p ? { path: p } : {})
      if (r.cancelled) return
      setFile(r); setName(r.name); setEditing(null); setPv(null)
      setParams({ ...DEF, up: r.suggest?.up || 'y', mirror: r.suggest?.mirror || 'z', origin: mode === 'replace' ? 'match' : 'bottom' })
    } catch (e) { setErr(e.message) }
  }
  // a model sent from Blender opens here
  const openRef = useRef(null)
  openRef.current = open
  useEffect(() => {
    const take = () => { const it = inbox.take(); if (it) { setPath(it.path); openRef.current(it.path); take() } }
    take()
    return inbox.subscribe(take)
  }, [])
  useEffect(() => { post('/api/ccc/vehicles', {}).then(r => setCcc(r.vehicles || [])).catch(() => {}) }, [])
  const openCcc = async (id) => {
    setErr(null)
    try {
      const r = await post('/api/ccc/analyze', { id })
      setFile(r); setName(r.name); setEditing(null); setPv(null); setMode('replace')
      setParams({ ...DEF, ccc: true, mirror: '', origin: 'none' })
    } catch (e) { setErr(e.message) }
  }
  // screenshot / deep-link hooks: ?file=<path>&mode=replace&target=<model path>&scale=..
  useEffect(() => {
    const u = new URLSearchParams(location.search)
    if (u.get('mode') === 'replace') setMode('replace')
    if (u.get('target')) setTarget({ path: u.get('target'), name: u.get('target').split('/').pop().replace('.model', '') })
    if (u.get('ccc')) openCcc(u.get('ccc'))
    if (u.get('file')) open(u.get('file')).then(() => { if (u.get('scale')) setParams(p => ({ ...p, scale: Number(u.get('scale')) })) })
  }, [])

  // the preview follows the settings (a short pause so a slider does not start a job per step)
  useEffect(() => {
    if (!file) return
    if (mode === 'replace' && !target) { setPv(null); return }
    const my = ++seq.current
    const t = setTimeout(async () => {
      setBusy(true); setErr(null)
      try {
        const r = await runJob('/api/import/preview', { sha: file.sha, params, mode, target: target?.path })
        if (my === seq.current) setPv(r)
      } catch (e) { if (my === seq.current) { setErr(e.message); setPv(null) } }
      if (my === seq.current) setBusy(false)
    }, 280)
    return () => clearTimeout(t)
  }, [file?.sha, params, mode, target?.path])

  // the model picker of "replace"
  useEffect(() => {
    if (mode !== 'replace') return
    const t = setTimeout(() => post('/api/models/search', { q, limit: 40 }).then(r => { setRows(r.ready ? r.rows : []); setScan(!r.ready) }).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [mode, q, tick])
  const build = async () => {
    try { await runJob('/api/textures/build', {}); setScan(false); setTick(n => n + 1) } catch (e) { setErr(e.message) }
  }

  const set = (k, v) => setParams(p => ({ ...p, [k]: v }))
  const size = pv?.stats?.size
  const setSize = (v) => {
    if (!size || !(v > 0)) return
    const i = axis === 'y' ? 1 : axis === 'x' ? 0 : 2
    if (size[i] > 1e-6) set('scale', Math.round(params.scale * v / size[i] * 1e6) / 1e6)
  }
  const sizeNow = size ? size[axis === 'y' ? 1 : axis === 'x' ? 0 : 2] : 0
  const orig = pv?.original

  const add = async () => {
    if (!file || (mode === 'replace' && !target)) return
    setBusy(true)
    try {
      const r = await runJob('/api/import/entry', { sha: file.sha, file: file.file, params, mode, target: target?.path, name: name || file.name, id: editing || undefined })
      const e = r.entry
      const next = editing ? models.map(m => m.id === editing ? e : m) : [...models.filter(m => (m.target || m.path) !== (e.target || e.path)), e]
      commit({ ...project, models: next })
      setEditing(e.id)
      ui.say(mode === 'new' ? 'Added. Place it from the level editor.' : 'The game model is replaced in this mod.')
    } catch (e2) { setErr(e2.message) }
    setBusy(false)
  }
  const remove = id => { commit({ ...project, models: models.filter(m => m.id !== id) }); if (editing === id) setEditing(null) }
  const edit = m => {
    setFile({ sha: m.source.sha, file: m.source.file, name: m.name, images: [], extent: m.stats?.size || [1, 1, 1], suggest: {} })
    setParams({ ...DEF, ...m.params, collision: { ...DEF.collision, ...(m.params?.collision || {}) } }); setMode(m.mode); setName(m.name); setEditing(m.id)
    setTarget(m.mode === 'replace' ? { path: m.target, name: m.target.split('/').pop().replace('.model', '') } : null)
  }
  useJump('import', ref => {
    if (ref.replace) {                                   // from the asset catalogue: replace this game model
      setMode('replace'); setEditing(null); setTarget({ path: ref.replace, name: ref.name || ref.replace.split('/').pop().replace('.model', '') })
      return true
    }
    const m = models.find(x => x.id === ref.model); if (m) edit(m); return true
  })

  if (big) return <LargeScene go={go} onBack={() => setBig(false)} />
  const blocked = !file || (mode === 'replace' && !target) || !pv || busy || (pv.refused || []).length > 0
  const col = params.collision || DEF.collision

  return (
    <div className="screen">
      <div className="tb">
        <input style={{ width: 300 }} placeholder={tr('path_of_a_glb_gltf_or')} aria-label={tr('model_file')} value={path} onChange={e => setPath(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && open(path)} />
        <button onClick={() => open(path || null)} title={tr('choose_a_file')}>{tr('choose_78b7c9')}{'…'}</button>
        <button className="ghost" onClick={() => saveAddon(ui.say)} title={tr('blender_add_on_tip')}>{tr('blender_add_on')}</button>
        {ccc.length > 0 && <select style={{ width: 190 }} aria-label={tr('from_chili_con_carnage')} title={tr('from_chili_con_carnage')} value="" onChange={e => e.target.value && openCcc(e.target.value)}>
          <option value="">{tr('from_chili_con_carnage')}</option>{ccc.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select>}
        <span className="vsep" />
        <Seg value={mode} onChange={m => { setMode(m); set('origin', m === 'replace' ? 'match' : 'bottom'); setEditing(null) }}
          options={[{ value: 'new', label: tr('new_model') }, { value: 'replace', label: tr('replace_a_game_model') }]} />
        {mode === 'new' && <input style={{ width: 170 }} placeholder={tr('name')} aria-label={tr('model_name')} value={name} onChange={e => setName(e.target.value)} />}
        <div style={{ flex: 1 }} />
        <button onClick={() => setBig(true)} title={tr('a_big_captured_scene_cut_into')}>{tr('large_scene')}</button>
        {busy && <span className="muted small">{tr('working')}{'…'}</span>}
        <button className="primary" disabled={blocked} onClick={add}>{editing ? 'Update in mod' : 'Add to mod'}</button>
      </div>
      <MeterStrip kind="level" data={store.data.level} go={go} />
      <div className="split">
        <div className="panel-l" style={{ width: 'calc(var(--side-l) + 40px)' }}>
          <div className="panel-b">
            <h4 style={{ marginTop: 0 }}>{tr('direction')}</h4>
            <div className="row"><Seg value={params.up} onChange={v => set('up', v)} options={[{ value: 'y', label: tr('y_up_f2d782') }, { value: 'z', label: tr('z_up') }]} /></div>
            <div className="row" title={tr('turn_about_the_up_axis')}><Seg value={String(params.yaw)} onChange={v => set('yaw', Number(v))} options={['0', '90', '180', '270'].map(v => ({ value: v, label: v + '°' }))} /></div>
            <div className="row" title={tr('game_space_is_left_handed_a')}><Seg value={params.mirror} onChange={v => set('mirror', v)}
              options={[{ value: 'z', label: tr('flip_z') }, { value: 'x', label: tr('flip_x') }, { value: 'none', label: tr('no_flip') }]} /></div>
            <h4>{tr('size')}</h4>
            <div className="row" title={tr('type_a_size_for_one_side')}>
              <span className="muted" style={{ flex: 'none' }}>{tr('this_is')}</span>
              <NumField value={sizeNow} digits={3} unit="m" onCommit={setSize} label={tr('size')} />
              <select value={axis} onChange={e => setAxis(e.target.value)} style={{ width: 76, flex: 'none' }} aria-label={tr('side')}>{AXES.map(([a, l]) => <option key={a} value={a}>{l}</option>)}</select>
            </div>
            <div className="row">
              <button className="sm" onClick={() => { setAxis('y'); setParams(p => ({ ...p, scale: Math.round(p.scale * 1.8 / (size?.[1] || 1.8) * 1e6) / 1e6 })) }} disabled={!size}>{tr('as_tall_as_ram')}</button>
              {mode === 'replace' && orig && <button className="sm" onClick={() => setParams(p => ({ ...p, scale: Math.round(p.scale * (orig.size[1] || 1) / (size?.[1] || 1) * 1e6) / 1e6 }))} disabled={!size}>{tr('game_s_height')}</button>}
            </div>
            <div className="muted small" style={{ fontVariantNumeric: 'tabular-nums' }}>{size ? size.map(v => v.toFixed(2)).join(' × ') + ' m' : ''}{params.scale !== 1 ? `  (scale ${params.scale})` : ''}</div>
            <div className="row"><Seg value={params.origin} onChange={v => set('origin', v)}
              options={[{ value: 'bottom', label: tr('base') }, { value: 'center', label: tr('centre') }, { value: 'none', label: tr('keep') }, ...(mode === 'replace' ? [{ value: 'match', label: tr('match') }] : [])]} /></div>
            <h4>{tr('detail')}</h4>
            <RangeField label={tr('triangles_kept')} min={0.05} max={1} step={0.01} def={1} value={params.reduce} digits={2} onChange={v => set('reduce', Math.max(0.05, Math.min(1, v)))} onReset={() => set('reduce', 1)} />
            <div className="muted small">{pv ? `${pv.stats.triangles_in.toLocaleString()} → ${pv.stats.triangles.toLocaleString()} triangles, ${pv.stats.vertices.toLocaleString()} vertices` : ''}</div>
            <h4>{tr('textures')}</h4>
            <div className="row" title={tr('largest_side_of_a_texture')}><Seg value={String(params.max_tex)} onChange={v => set('max_tex', Number(v))} options={['128', '256', '512', '1024'].map(v => ({ value: v, label: v }))} /></div>
            <div className="row" title={tr('auto_dxt1_rgba32_only_for_see')}><Seg value={params.tex_format} onChange={v => set('tex_format', v)} options={[{ value: 'auto', label: tr('auto') }, { value: 'DXT1', label: tr('dxt1') }, { value: 'RGBA32', label: tr('rgba32') }]} /></div>
            {(pv?.textures || []).map((t, i) => <div key={i} className="row small" style={{ justifyContent: 'space-between' }} title={`Source ${t.source[0]}×${t.source[1]}`}>
              <span>{t.w}×{t.h} {t.fmt}</span><span className="muted">{kb(t.bytes)}{t.psnr ? ` · ${t.psnr} dB` : ''}</span></div>)}
            <h4>{tr('collision')}</h4>
            {mode === 'replace' && <label className="check"><Switch on={params.keep_collision} onChange={v => set('keep_collision', v)} />{' '}{tr('keep_the_game_s_collision')}</label>}
            {(mode === 'new' || !params.keep_collision) && <div className="row"><Seg value={col.mode} onChange={v => set('collision', { ...col, mode: v })}
              options={[{ value: 'none', label: tr('none_6eef66') }, { value: 'box', label: tr('box') }, { value: 'hull', label: tr('hull') }, { value: 'solid', label: tr('pieces') }]} /></div>}
            {pv && pv.collision.pieces > 0 && (mode === 'new' || !params.keep_collision) && <div className="muted small">{pv.collision.pieces}{' '}{tr('piece')}{pv.collision.pieces === 1 ? '' : 's'}, {pv.collision.vertices}{' '}{tr('points')}</div>}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0, position: 'relative', background: 'var(--vp)' }}>
          {pv ? <ModelCanvas url={pv.url} ghost={orig?.mesh ? { name: target?.path, rec: orig.mesh } : null} />
            : <div className="empty">{file ? (mode === 'replace' && !target ? 'Pick the game model on the right.' : busy ? 'Building the preview…' : (err || '')) : (err || 'Choose a model file.')}</div>}
          {pv && <div className="hint" style={{ position: 'absolute', left: 10, bottom: 8 }}>{orig ? 'Amber lines: the game model.' : ''}</div>}
          {err && pv && <div className="flash" style={{ position: 'absolute', left: 10, top: 8 }}>{err}</div>}
        </div>
        <div className="panel-r">
          <div className="panel-b">
            {mode === 'replace' && <>
              <h4 style={{ marginTop: 0 }}>{tr('game_model')}</h4>
              {scan ? <div><button onClick={build} disabled={busy}>{tr('read_the_game_s_models')}</button></div> : <>
                <input placeholder={tr('find_a_model')} aria-label={tr('find_a_model')} value={q} onChange={e => setQ(e.target.value)} />
                {target && <div className="sideitem on" title={target.path} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ flex: 1, minWidth: 0 }}><div className="a" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{target.name}</div>
                    <div className="b">{orig ? `${orig.size.map(v => v.toFixed(2)).join(' × ')} m · ${orig.blocks} place${orig.blocks === 1 ? '' : 's'}` : ' '}</div></span>
                  <button className="sm ghost" aria-label={tr('choose_another')} title={tr('choose_another')} onClick={() => setTarget(null)}>{'×'}</button></div>}
                <div style={{ maxHeight: target ? 150 : 190, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {(rows || []).filter(r => r.path !== target?.path).map(r => <div key={r.path} className={'sideitem' + (target?.path === r.path ? ' on' : '')} onClick={() => setTarget({ path: r.path, name: r.name })} title={r.path}
                    style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {r.thumb ? <img src={r.thumb} width={32} height={32} alt="" /> : <span style={{ width: 32, flex: 'none' }} />}
                    <span style={{ minWidth: 0 }}><div className="a" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</div>
                      <div className="b">{r.blocks}{' '}{tr('place')}{r.blocks === 1 ? '' : 's'}{r.hd ? ' · already replaced' : ''}</div></span></div>)}
                </div></>}
              {target && orig?.hd && <p className="warn small">{tr('already_replaced_by_tod_hd_or')}</p>}
              {orig?.skinned && <p className="bad small">{tr('a_character_cannot_be_replaced')}</p>}
            </>}
            <h4 style={mode === 'replace' ? undefined : { marginTop: 0 }}>{tr('limits')}</h4>
            {(pv?.limits || []).map(r => <Meter key={r.id} r={r} />)}
            {(pv?.notes || []).map((n, i) => <p key={i} className={n.level === 'error' ? 'bad small' : 'warn small'} style={{ margin: '4px 0' }}>{n.text}</p>)}
            {!pv && <p className="muted small">{busy ? 'Working…' : ''}</p>}
            <h4>{tr('in_this_mod')}</h4>
            {models.length === 0 && <p className="muted small">{tr('nothing_yet')}</p>}
            {models.map(m => <div key={m.id} className={'sideitem' + (editing === m.id ? ' on' : '')} onClick={() => edit(m)} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ flex: 1, minWidth: 0 }}><div className="a" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.name}</div>
                <div className="b">{m.mode === 'new' ? 'New' : 'Replaces ' + m.target.split('/').pop().replace('.model', '')} · {(m.stats?.triangles || 0).toLocaleString()}{' '}{tr('tris')}</div></span>
              <button className="sm ghost" title={tr('remove_from_the_mod')} aria-label={tr('remove')} onClick={e => { e.stopPropagation(); remove(m.id) }}>{'×'}</button></div>)}
          </div>
        </div>
      </div>
    </div>
  )
}
