// The asset catalogue: every model of the game, browsable. A grid of picture cards (drawn with the real textures), filters,
// and a live 3D preview with measures, textures and where the model is used. Place it in a level or replace it from here.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post, runJob } from './api.js'
import { jumpTo } from './problemsStore.js'
import { saveAddon } from './blenderInbox.js'
import { useUI } from './ui.jsx'
import AssetPreview from './AssetPreview.jsx'
import { want, warm, onCard, cardUrl, isDone } from './cards.js'
import { vpColor } from './theme.js'
import { t as tr } from './i18n.js'

const CARD_MIN = 148, CARD_MAX = 210, GAP = 8
const BANDS = [['', 'Any size', ''], ['tiny', 'Tiny', 'under 0.5 m'], ['small', 'Small', '0.5 to 2 m'], ['medium', 'Medium', '2 to 8 m'], ['large', 'Large', '8 to 40 m'], ['huge', 'Huge', 'over 40 m']]
const TRIS = [['', 'Any triangles'], ['0-500', 'Under 500'], ['500-2000', '500 to 2,000'], ['2000-10000', '2,000 to 10,000'], ['10000-', 'Over 10,000']]
const USED = [['', 'Used anywhere'], ['unused', 'Not placed'], ['1', 'Placed 1+'], ['5', 'Placed 5+'], ['20', 'Placed 20+']]
const SORTS = [['uses', 'Most placed'], ['name', 'Name'], ['tris', 'Triangles'], ['size', 'Size'], ['textures', 'Textures']]
const n0 = n => (n == null ? '-' : Math.round(n).toLocaleString())
const k = n => (n >= 10000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n))
const m2 = v => (v == null ? '-' : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2))
const KB = n => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round((n || 0) / 1024)) + ' KB')
const param = k2 => new URLSearchParams(location.search).get(k2)

export default function Assets({ status, theme }) {
  const [f, setF] = useState(() => ({ q: param('q') || '', cat: param('cat') || '', map: param('map') || '', band: param('band') || '', tris: param('tris') || '',
    used: param('used') || (param('min') ? param('min') : ''), sort: param('sort') || 'uses' }))
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(param('sel') || null)
  const [job, setJob] = useState(null)
  const [msg, setMsg] = useState(null)
  const [ver, setVer] = useState(0)
  const ui = useUI()
  const body = useMemo(() => {
    const [tmin, tmax] = (f.tris || '').split('-')
    return { q: f.q, cat: f.cat, map: f.map, band: f.band, tris_min: tmin || undefined, tris_max: tmax || undefined, sort: f.sort,
      unused: f.used === 'unused' || undefined, min_uses: f.used && f.used !== 'unused' ? Number(f.used) : undefined }
  }, [f])
  const load = useCallback(async () => {
    try { setData(await post('/api/catalogue/rows', body)) } catch (e) { setMsg(e.message) }
  }, [body])
  useEffect(() => { const t = setTimeout(load, f.q ? 160 : 0); return () => clearTimeout(t) }, [load])
  useEffect(() => onCard(() => setVer(v => v + 1)), [])
  useEffect(() => { if (param('warm') && data?.rows?.length) warm(data.rows) }, [data?.rows?.length])      // ?warm=1: draw every picture now (for proof runs)
  useEffect(() => { if (!sel && data?.rows?.length) setSel(data.rows[0].key) }, [data])
  const scan = async () => {
    setMsg(null)
    try { const r = await runJob('/api/catalogue/scan', {}, setJob); setMsg(`${r.models} models in ${r.maps} maps.`); load() } catch (e) { setMsg(e.message) }
    setJob(null)
  }
  const set = (key, v) => setF(o => ({ ...o, [key]: v }))
  if (!data) return <div className="page"><p className="muted" style={{ padding: 12 }}>{tr('loading')}</p></div>
  if (!data.ready) {
    return <div className="cat"><div className="empty"><div>
      <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-2)', marginBottom: 10 }}>{tr('asset_catalogue')}</div>
      <button className="primary lg" onClick={scan} disabled={!!job}>{tr('scan_the_game')}</button>
      {job && <div className="muted" style={{ marginTop: 10 }}>{job.message || 'Working'}{job.total ? ` ${job.done}/${job.total}` : ''}</div>}
      {msg && <p className="flash">{msg}</p>}</div></div></div>
  }
  return (
    <div className="cat">
      <Rail f={f} set={set} data={data} />
      <section className="cat-main">
        <div className="cat-tools">
          <input placeholder={tr('search')} value={f.q} onChange={e => set('q', e.target.value)} aria-label={tr('search')} />
          <select value={f.sort} onChange={e => set('sort', e.target.value)} aria-label={tr('sort')} title={tr('sort')}>{SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          <span className="muted small nowrap">{data.count.toLocaleString()}{' '}{tr('of')}{' '}{data.total.toLocaleString()}</span>
          <button className="ghost sm" onClick={scan} disabled={!!job} title={tr('count_the_models_again')}>{tr('rescan')}</button>
          <button className="ghost sm" onClick={() => saveAddon(ui.say)} title={tr('blender_add_on_tip')}>{tr('blender_add_on')}</button>
        </div>
        <div className="cat-small">
          <select value={f.cat} onChange={e => set('cat', e.target.value)} aria-label={tr('category')}><option value="">{tr('all_categories')}</option>
            {data.cats.map(c => <option key={c.id} value={c.id}>{c.label} ({c.count})</option>)}</select>
          <select value={f.map} onChange={e => set('map', e.target.value)} aria-label={tr('map')}><option value="">{tr('all_maps')}</option>{data.maps.map(m => <option key={m} value={m}>{m}</option>)}</select>
        </div>
        <Grid rows={data.rows} sel={sel} onSel={setSel} ver={ver} />
      </section>
      <Detail sel={sel} />
      {job && <div className="busy">{job.message || 'Working'} {job.total ? `${job.done}/${job.total}` : ''}</div>}
      {msg && !job && <div className="flashbar" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}

function Rail({ f, set, data }) {
  return (
    <aside className="cat-rail">
      <div className="upper">{tr('category')}</div>
      <button className={'catrow' + (!f.cat ? ' on' : '')} onClick={() => set('cat', '')}><span>{tr('all')}</span><i>{data.cats.reduce((a, c) => a + c.count, 0).toLocaleString()}</i></button>
      {data.cats.map(c => <button key={c.id} className={'catrow' + (f.cat === c.id ? ' on' : '')} disabled={!c.count && f.cat !== c.id} onClick={() => set('cat', f.cat === c.id ? '' : c.id)}>
        <span>{c.label}</span><i>{c.count.toLocaleString()}</i></button>)}
      <div className="upper" style={{ marginTop: 12 }}>{tr('map')}</div>
      <select value={f.map} onChange={e => set('map', e.target.value)} aria-label={tr('map')}><option value="">{tr('all_maps')}</option>{data.maps.map(m => <option key={m} value={m}>{m}</option>)}</select>
      <div className="upper" style={{ marginTop: 12 }}>{tr('size')}</div>
      <div className="chips">{BANDS.map(([v, l, t]) => <button key={v} className={'chip' + (f.band === v ? ' on' : '')} title={t} onClick={() => set('band', v)}>{l}</button>)}</div>
      <div className="upper" style={{ marginTop: 12 }}>{tr('triangles')}</div>
      <select value={f.tris} onChange={e => set('tris', e.target.value)} aria-label={tr('triangles')}>{TRIS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      <div className="upper" style={{ marginTop: 12 }}>{tr('used')}</div>
      <select value={f.used} onChange={e => set('used', e.target.value)} aria-label={tr('used_in')}>{USED.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    </aside>
  )
}

// ---------------------------------------------------------------------------------------------- the virtual grid
function Grid({ rows, sel, onSel, ver }) {
  const box = useRef(null)
  const [dim, setDim] = useState({ w: 700, h: 600 })
  const [top, setTop] = useState(0)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setDim({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setDim({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  const cols = Math.max(1, Math.floor((dim.w - GAP) / (CARD_MIN + GAP)))
  const cw = Math.min(CARD_MAX, Math.floor((dim.w - GAP * (cols + 1)) / cols))        // cards share the width, up to a limit
  const ch = Math.round(cw * 0.88) + 58
  const rh = ch + GAP
  const nrows = Math.ceil(rows.length / cols)
  const first = Math.max(0, Math.floor(top / rh) - 1)
  const last = Math.min(nrows, Math.ceil((top + dim.h) / rh) + 1)
  const pad = Math.max(GAP, (dim.w - cols * (cw + GAP) + GAP) / 2)
  useEffect(() => { if (box.current) box.current.scrollTop = 0; setTop(0) }, [rows.length && rows[0]?.key, rows.length])
  const shown = useMemo(() => rows.slice(first * cols, last * cols), [rows, first, last, cols])
  // pictures for the cards on screen: the ones in view first
  const midRow = Math.floor((top + dim.h / 2) / rh)
  useEffect(() => {
    const t = setTimeout(() => want([...shown].sort((a, b) => Math.abs(rows.indexOf(a) / cols - midRow) - Math.abs(rows.indexOf(b) / cols - midRow))), 140)
    return () => clearTimeout(t)
  }, [shown, midRow, cols])
  // keep the selected card in view when it was picked from a link
  useEffect(() => {
    const i = rows.findIndex(r => r.key === sel)
    if (i < 0 || !box.current) return
    const y = Math.floor(i / cols) * rh
    if (y < box.current.scrollTop || y > box.current.scrollTop + dim.h - rh) box.current.scrollTop = Math.max(0, y - rh)
  }, [sel, rows.length, cols])
  return (
    <div className="cat-grid" ref={box} onScroll={e => setTop(e.currentTarget.scrollTop)} role="listbox" aria-label={tr('models')}>
      {!rows.length && <div className="empty">{tr('nothing_matches')}</div>}
      <div style={{ height: nrows * rh + GAP, position: 'relative' }}>
        {shown.map((r, i) => {
          const idx = first * cols + i
          const x = pad + (idx % cols) * (cw + GAP), y = GAP + Math.floor(idx / cols) * rh
          return <Card key={r.key} r={r} on={r.key === sel} style={{ left: x, top: y, width: cw, height: ch }} pic={Math.round(cw * 0.88)} onClick={() => onSel(r.key)} ver={ver} />
        })}
      </div>
    </div>
  )
}

function Card({ r, on, style, pic, onClick, ver }) {
  const img = r.card || isDone(r.key)
  return (
    <button className={'card' + (on ? ' on' : '')} style={style} onClick={onClick} role="option" aria-selected={on} title={r.name}>
      <span className="pic" style={{ height: pic }}>{img ? <img src={cardUrl(r.key)} alt="" /> : <span className={'ph' + (r.none ? ' none' : '')} />}
        {r.hd && <i className="hdtag" title={tr('replaced_by_tod_hd')}>{tr('hd')}</i>}</span>
      <b>{r.name}</b>
      <span className="meta">{k(r.tris)}{' '}{tr('tris')}{r.uses ? ` · ${r.uses} placed` : ''}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------------------------- one model
const OPT0 = { wire: false, coll: false, bones: false, box: true, figure: null }       // null: Ram for scale on things, off on people
function Detail({ sel }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [opts, setOpts] = useState(() => {
    const o = { ...OPT0 }
    ;(param('opts') || '').split(',').filter(Boolean).forEach(x => { o[x.replace('-', '')] = !x.startsWith('-') })
    return o
  })
  const [stats, setStats] = useState(null)
  const [texPics, setTexPics] = useState({})
  const ctl = useRef({ t: 0, playing: true, speed: 1 })
  const [clips, setClips] = useState(null)               // { clips: [...], rigged }
  const [pick, setPick] = useState(null)
  const [clipData, setClipData] = useState(null)
  const [skin, setSkin] = useState(null)
  const [play, setPlay] = useState({ t: 0, playing: true })
  useEffect(() => {
    setClips(null); setPick(null); setClipData(null); setSkin(null)
    if (!d || d.rec?.missing || (d.kind !== 'skeletal' && !/\/animals\//i.test(d.path))) return
    let live = true
    post('/api/catalogue/clips', { key: d.key }).then(r => {
      if (!live) return
      setClips(r)
      const first = r.clips.find(c => /idle/i.test(c.name) && c.own) || r.clips.find(c => c.own) || r.clips[0]
      if (first) { const want = param('clip'); setPick((want && r.clips.find(c => c.name === want)?.name) || first.name) }
    }).catch(() => {})
    return () => { live = false }
  }, [d])
  useEffect(() => {
    if (!pick || !d) return
    let live = true
    ctl.current.t = Number(param('t') || 0); ctl.current.playing = param('still') ? false : true
    if (!skin) post('/api/catalogue/skin', { key: d.key }).then(r => { if (live) setSkin(r) }).catch(() => {})
    post('/api/catalogue/clip', { key: d.key, clip: pick }).then(r => { if (live) setClipData(r) }).catch(() => {})
    return () => { live = false }
  }, [pick, d])
  useEffect(() => { document.querySelector('.cliplist button.on')?.scrollIntoView({ block: 'nearest' }) }, [pick, clips])
  const rig = useMemo(() => (skin && clipData && d ? { skin: { ...skin, texInfo: d.rec?.textures }, clip: clipData } : null), [skin, clipData, d])
  const onTime = useCallback((t, playing) => setPlay({ t, playing }), [])
  useEffect(() => {
    setD(null); setErr(null); setStats(null)
    if (!sel) return
    let live = true
    post('/api/catalogue/model', { key: sel }).then(r => { if (live) setD(r) }).catch(e => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [sel])
  useEffect(() => {
    if (!d?.textures?.length) return
    const need = d.textures.map(t => t.name).filter(n => !(n in texPics)).slice(0, 24)
    if (!need.length) return
    let live = true
    post('/api/textures/thumbs', { names: need }).then(r => { if (live) setTexPics(p => ({ ...p, ...Object.fromEntries(need.map(n => [n, r.thumbs[n] || '']))})) }).catch(() => {})
    return () => { live = false }
  }, [d, texPics])
  const eff = { ...opts, figure: opts.figure ?? (d ? d.kind !== 'skeletal' : true) }
  const tog = key => setOpts(o => ({ ...o, [key]: !eff[key] }))
  if (!sel) return <aside className="cat-side"><div className="empty">{tr('pick_a_model')}</div></aside>
  const best = d?.where?.find(w => w.map)
  const place = () => jumpTo({ screen: 'level', map: best?.map, section: best?.kind === 'section' ? best.section : null, place: { path: d.path, name: d.name } })
  return (
    <aside className="cat-side">
      <div className="cat-head">
        <div className="grow"><b className="nm">{d?.name || '…'}</b>
          {d && <div className="muted small">{d.cat_label}{d.kind === 'skeletal' ? ' · rigged' : ''}{d.hd ? ' · replaced by TOD HD' : ''}</div>}</div>
        <button className="primary sm" disabled={!d || d.rec?.missing} onClick={place} title={tr('click_in_a_level_to_put')}>{tr('place_in_level')}</button>
        <button className="sm" disabled={!d} onClick={() => jumpTo({ screen: 'import', replace: d.path, name: d.name })} title={tr('swap_this_model_for_your_own')}>{tr('replace')}</button>
      </div>
      <div className="vp cat-vp">
        {d && !d.rec?.missing && <AssetPreview detail={d} opts={eff} onStats={setStats} vp={vpColor()} rig={rig} ctl={ctl} onTime={onTime} />}
        {err && <div className="empty">{err}</div>}
        {d?.rec?.missing && <div className="empty">{tr('no_mesh_to_show')}</div>}
        {!d && !err && <div className="empty">{tr('loading')}</div>}
        <div className="cat-toggles">
          {[['wire', 'Wire', 'Wireframe'], ['coll', 'Hulls', 'Collision hulls'], ['bones', 'Pivots', 'Pivots and bones'], ['box', 'Size', 'Size in metres'], ['figure', 'Ram', 'Ram for scale']].map(([key, l, t]) =>
            <button key={key} className={'sm' + (eff[key] ? ' on' : '')} title={t} onClick={() => tog(key)} aria-pressed={!!eff[key]}>{l}</button>)}
        </div>
      </div>
      {d && <div className="cat-body">
        <div className="stats">
          <div><i>{tr('size')}</i><b>{d.size ? d.size.map(m2).join(' × ') : '-'}{' '}{tr('m')}</b></div>
          <div><i>{tr('triangles')}</i><b>{n0(stats?.tris ?? d.tris)}</b></div>
          <div><i>{tr('sub_meshes')}</i><b>{stats ? stats.sub : '-'}</b></div>
          <div><i>{tr('textures')}</i><b title={`${d.textures.filter(t => t.url).length} on the mesh shown`}>{d.textures.length}</b></div>
          <div><i>{tr('hulls')}</i><b>{d.rec?.hulls ?? d.collision_shapes ?? 0}</b></div>
          <div><i>{tr('pivots')}</i><b>{d.pivots_n ?? d.pivots.length}</b></div>
        </div>
        {clips?.clips?.length > 0 && <>
          <h4>{tr('clips')}</h4>
          <div className="clipbar">
            <button className="sm" onClick={() => { ctl.current.playing = !ctl.current.playing; if (ctl.current.playing && clipData && !clipData.loop && ctl.current.t >= clipData.frames / clipData.fps) ctl.current.t = 0; setPlay(p => ({ ...p, playing: ctl.current.playing })) }}
              aria-label={play.playing ? 'Pause' : 'Play'} title={play.playing ? 'Pause' : 'Play'}>{play.playing ? '❚❚' : '▶'}</button>
            <input type="range" min={0} max={clipData ? clipData.frames / clipData.fps : 1} step={0.01} value={Math.min(play.t, clipData ? clipData.frames / clipData.fps : 1)}
              aria-label={tr('scrub')} onChange={e => { ctl.current.playing = false; ctl.current.t = Number(e.target.value); setPlay({ t: ctl.current.t, playing: false }) }} />
            <span className="muted small mono nowrap">{play.t.toFixed(2)} / {clipData ? (clipData.frames / clipData.fps).toFixed(2) : '-'}{' '}{tr('s')}</span>
          </div>
          <div className="cliplist" role="listbox" aria-label={tr('clips')}>{clips.clips.map(c => <button key={c.name} role="option" aria-selected={c.name === pick} className={c.name === pick ? 'on' : ''} onClick={() => setPick(c.name)}>
            <span>{c.name}</span><i>{c.seconds.toFixed(1)}{' '}{tr('s')}</i></button>)}</div>
        </>}
        <h4>{tr('where_it_is_used')}</h4>
        {d.where.length === 0 ? <div className="muted small">{tr('not_placed_in_a_map')}</div>
          : <div className="where">{d.where.slice(0, 40).map(w => <button key={w.entry} className="wrow" disabled={!w.map} title={tr('open_the_level_editor_here')}
            onClick={() => jumpTo({ screen: 'level', map: w.map, section: w.kind === 'section' ? w.section : null })}>
            <span>{w.map_title ? w.map_title.replace(/^Map\d\d /, '') : ''}</span><span className="muted">{w.title}</span><b>{w.count}</b></button>)}</div>}
        {d.textures.length > 0 && <>
          <h4>{tr('textures')}</h4>
          <div className="texstrip">{d.textures.map(t => <button key={t.name} className={'tex' + (t.url ? '' : ' alt')} onClick={() => jumpTo({ screen: 'textures', texture: t.name })}
            title={`${t.short}  ${t.w || '?'}×${t.h || '?'} ${t.fmt || ''}  ${t.size ? KB(t.size) : ''}${t.users > 1 ? '  used by ' + t.users + ' models' : ''}${t.hd ? '  (TOD HD)' : ''}${t.url ? '' : '  (not on the mesh shown)'}`}>
            {texPics[t.name] ? <img src={texPics[t.name]} alt="" /> : <span className="ph" />}<span>{t.short}</span></button>)}</div>
        </>}
      </div>}
    </aside>
  )
}
