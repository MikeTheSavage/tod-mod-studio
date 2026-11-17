// The texture editor: any texture of the game, replaced by a picture or edited, with a live look at the result (as the game will hold it)
// on a model that uses it. A texture is shared by several models and may already be changed by TOD HD: both are said before it is applied.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { post, runJob } from './api.js'
import { Seg, RangeField, NumField, useUI } from './ui.jsx'
import { TextureCanvas } from './AssetView.jsx'
import { Meter, MeterStrip } from './Meters.jsx'
import { useStore, useJump } from './problemsStore.js'
import { t as tr } from './i18n.js'

const SIDES = [16, 32, 64, 128, 256, 512, 1024, 2048]
const kb = n => n >= 1048576 ? (n / 1048576).toFixed(2) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'
const pow2floor = n => 2 ** Math.floor(Math.log2(Math.max(1, n)))
const short = n => (n || '').split('/').pop().replace(/\.bmp$/i, '')
const E0 = { hue: 0, brightness: 0, contrast: 0, saturation: 0, tint: '#ffffff', tint_amount: 0, alpha: 'keep', alpha_cut: 0.5 }
const hex = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16))

export default function Textures({ project, commit, go }) {
  const ui = useUI()
  const store = useStore()
  const [q, setQ] = useState('')
  const [only, setOnly] = useState('all')
  const [data, setData] = useState(null)
  const [thumbs, setThumbs] = useState({})
  const [sel, setSel] = useState(null)               // index key
  const [info, setInfo] = useState(null)
  const [draft, setDraft] = useState(null)           // { source, crop, side, fmt, edits }
  const [res, setRes] = useState(null)
  const [orig, setOrig] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [view, setView] = useState(() => new URLSearchParams(location.search).get('view') === 'model' ? 'model' : 'flat')
  const [rec, setRec] = useState(null)
  const [path, setPath] = useState('')
  const seq = useRef(0)
  const textures = project.textures || []
  const mine = useMemo(() => new Map(textures.map(t => [t.target.toLowerCase(), t])), [textures])

  const load = async () => { try { setData(await post('/api/textures/rows', { q, only: only === 'changed' ? undefined : only === 'hd' ? 'hd' : undefined, limit: 400 })) } catch (e) { setErr(e.message) } }
  useEffect(() => { const t = setTimeout(load, 180); return () => clearTimeout(t) }, [q, only])
  const rows = useMemo(() => {
    let r = data?.rows || []
    if (only === 'changed') r = r.filter(x => mine.has(x.name.toLowerCase()))
    return r
  }, [data, only, mine])
  // thumbnails of the rows on screen, in small batches
  useEffect(() => {
    const need = rows.slice(0, 60).map(r => r.name).filter(n => !(n in thumbs))
    if (!need.length) return
    let live = true
    post('/api/textures/thumbs', { names: need.slice(0, 24) }).then(r => { if (live) setThumbs(t => ({ ...t, ...r.thumbs })) }).catch(() => {})
    return () => { live = false }
  }, [rows, thumbs])
  const scan = async () => { setBusy(true); try { await runJob('/api/textures/build', {}); await load() } catch (e) { setErr(e.message) } setBusy(false) }

  const pick = async (name, entry) => {
    setSel(name); setErr(null); setRes(null); setOrig(null); setRec(null)
    try {
      const i = await post('/api/textures/info', { name })
      setInfo(i)
      const t = entry || mine.get(name.toLowerCase())
      const side = t ? Math.max(t.w, t.h) : Math.max(i.w, i.h)
      setDraft(t ? { source: t.source, srcInfo: t.source.sha ? { name: t.source.file, w: 0, h: 0 } : null, crop: t.crop || null, side, fmt: t.fmt, edits: { ...E0, ...(t.edits || {}), tint: toHex(t.edits?.tint) } }
        : { source: { game: true }, srcInfo: null, crop: null, side, fmt: i.fmt, edits: E0 })
      const mdl = i.users[0]
      if (mdl) post('/api/models/find', { names: [mdl.path] }).then(r => setRec({ name: mdl.path, rec: r.models[mdl.path] })).catch(() => {})
    } catch (e) { setErr(e.message) }
  }
  useJump('textures', ref => { if (ref.texture) { pick(ref.texture); return true } })
  useEffect(() => { const t = new URLSearchParams(location.search).get('texture'); if (t) pick(t) }, [])

  const dims = draft && info ? (() => { const a = info.w / info.h; return a >= 1 ? { w: draft.side, h: Math.max(1, Math.round(draft.side / a)) } : { w: Math.max(1, Math.round(draft.side * a)), h: draft.side } })() : null

  const request = useMemo(() => draft && info && dims ? ({ target: info.name, source: draft.source, crop: draft.crop, w: dims.w, h: dims.h, fmt: draft.fmt,
    edits: { ...draft.edits, tint: draft.edits.tint_amount ? hex(draft.edits.tint) : undefined } }) : null, [draft, info])
  useEffect(() => {
    if (!request) return
    const my = ++seq.current
    const t = setTimeout(async () => {
      setBusy(true)
      try {
        const r = await runJob('/api/textures/render', request)
        if (my === seq.current) { setRes(r); setErr(null) }
        if (!orig && info) {
          const o = await runJob('/api/textures/render', { target: info.name, source: { game: true }, w: info.w, h: info.h, fmt: info.fmt, edits: {} })
          if (my === seq.current) setOrig(o)
        }
      } catch (e) { if (my === seq.current) setErr(e.message) }
      if (my === seq.current) setBusy(false)
    }, 260)
    return () => clearTimeout(t)
  }, [JSON.stringify(request)])

  const set = (k, v) => setDraft(d => ({ ...d, [k]: v }))
  const setE = (k, v) => setDraft(d => ({ ...d, edits: { ...d.edits, [k]: v } }))
  const choose = async (p) => {
    try {
      const r = await post('/api/textures/upload', p ? { path: p } : {})
      if (r.cancelled) return
      setDraft(d => ({ ...d, source: { sha: r.sha, file: r.name }, srcInfo: r, crop: null }))
    } catch (e) { setErr(e.message) }
  }
  const cropPow2 = () => {
    const s = draft.srcInfo
    if (!s || !s.w) return
    const w = pow2floor(s.w), h = pow2floor(s.h)
    set('crop', [Math.floor((s.w - w) / 2), Math.floor((s.h - h) / 2), w, h])
  }
  const apply = () => {
    const e = { id: 't' + Math.abs(hashOf(info.key)).toString(36), target: info.name, source: draft.source.game ? { game: true } : { sha: draft.source.sha, file: draft.source.file },
      crop: draft.crop || null, w: dims.w, h: dims.h, fmt: draft.fmt, edits: cleanEdits(draft.edits) }
    commit({ ...project, textures: [...textures.filter(t => t.target.toLowerCase() !== info.name.toLowerCase()), e] })
    ui.say(tr('changed_in_this_mod'))
  }
  const revert = () => commit({ ...project, textures: textures.filter(t => t.target.toLowerCase() !== info.name.toLowerCase()) })
  const changed = info && mine.has(info.name.toLowerCase())
  const shared = info && info.users.length > 1
  const dxtLocked = info?.keep_dxt1

  return (
    <div className="screen">
      <div className="tb">
        <input style={{ width: 240 }} placeholder={tr('find_a_texture')} aria-label={tr('find_a_texture')} value={q} onChange={e => setQ(e.target.value)} />
        <Seg value={only} onChange={setOnly} options={[{ value: 'all', label: tr('all') }, { value: 'changed', label: `In this mod${textures.length ? ' (' + textures.length + ')' : ''}` }, { value: 'hd', label: tr('hd') }]} />
        <div style={{ flex: 1 }} />
        {busy && <span className="muted small">{tr('working')}{'…'}</span>}
        <button onClick={scan} disabled={busy} title={tr('read_every_block_of_the_game')}>{tr('scan')}</button>
        <button className="primary" disabled={!draft || !res || busy || !!err || res.refused} onClick={apply}>{changed ? 'Update in mod' : 'Apply to mod'}</button>
      </div>
      <MeterStrip kind="level" data={store.data.level} go={go} />
      <div className="split">
        <div className="panel-l" style={{ width: 'calc(var(--side-l) + 40px)' }}>
          {data && !data.ready ? <div className="empty"><div><p>{tr('the_textures_of_the_game_are')}</p><button className="primary" onClick={scan} disabled={busy}>{tr('read_the_game')}</button></div></div>
            : <div className="panel-b" style={{ gap: 2, padding: 6 }}>
              {!data && <div className="muted" style={{ padding: 8 }}>{tr('loading')}{'…'}</div>}
              {rows.map(r => <div key={r.key} className={'sideitem' + (sel === r.name ? ' on' : '')} onClick={() => pick(r.name)} title={r.name}
                style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {thumbs[r.name] ? <img src={thumbs[r.name]} width={36} height={36} alt="" style={{ objectFit: 'cover', borderRadius: 3 }} /> : <span style={{ width: 36, height: 36, flex: 'none', background: 'var(--surface-3)', borderRadius: 3 }} />}
                <span style={{ minWidth: 0, flex: 1 }}><div className="a" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{short(r.name)}</div>
                  <div className="b">{r.w}×{r.h} {r.fmt} · {r.users}{' '}{tr('model')}{r.users === 1 ? '' : 's'}{r.hd ? ' · HD' : ''}</div></span>
                {mine.has(r.name.toLowerCase()) && <span className="dot" style={{ background: 'var(--accent)' }} title={tr('changed_in_this_mod_fbab64')} />}
              </div>)}
              {data?.ready && data.count > rows.length && <div className="muted small" style={{ padding: 8 }}>{tr('narrow_the_search_to_see_the')}{' '}{(data.count - rows.length).toLocaleString()}.</div>}
            </div>}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--vp)' }}>
          {!info && <div className="empty">{err || 'Choose a texture.'}</div>}
          {info && <>
            <div className="tb" style={{ background: 'transparent', borderBottom: '1px solid var(--line)', height: 34 }}>
              <Seg value={view} onChange={setView} options={[{ value: 'flat', label: tr('picture') }, { value: 'model', label: tr('on_a_model') }]} />
              <b style={{ marginLeft: 6 }}>{short(info.name)}</b>
              <span className="muted small">{info.w}×{info.h} {info.fmt} · {kb(info.size)}</span>
            </div>
            <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
              {view === 'flat' ? <div style={{ position: 'absolute', inset: 0, display: 'flex', gap: 14, alignItems: 'center', justifyContent: 'center', padding: 16 }}>
                <Pane label={tr('now')} src={orig?.png || info.thumb} />
                <Pane label={tr('result')} src={res?.png} note={res ? `${res.w}×${res.h} ${res.fmt}${res.psnr ? ' · ' + res.psnr + ' dB' : ''}` : ''} />
              </div> : rec?.rec?.url ? <TextureCanvas rec={rec.rec} target={info.name} dataUrl={res?.png} /> : <div className="empty">{tr('no_model_in_the_game_uses')}</div>}
              {err && <div className="flash" style={{ position: 'absolute', left: 10, top: 8 }}>{err}</div>}
            </div>
          </>}
        </div>
        <div className="panel-r wide">
          {info && draft && <div className="panel-b">
            <h4 style={{ marginTop: 0 }}>{tr('picture')}</h4>
            <Seg value={draft.source.game ? 'game' : 'file'} onChange={v => v === 'game' ? setDraft(d => ({ ...d, source: { game: true }, srcInfo: null, crop: null })) : choose(path || null)}
              options={[{ value: 'game', label: tr('the_game_s') }, { value: 'file', label: tr('my_picture') }]} />
            {!draft.source.game && <div className="row"><input placeholder={tr('path_of_a_picture')} aria-label={tr('picture_file')} value={path} onChange={e => setPath(e.target.value)} onKeyDown={e => e.key === 'Enter' && choose(path)} />
              <button className="sm" onClick={() => choose(path || null)}>{tr('open')}</button></div>}
            {!draft.source.game && draft.srcInfo?.w > 0 && <div className="row small" style={{ justifyContent: 'space-between' }}>
              <span className="muted">{draft.srcInfo.name} · {draft.srcInfo.w}×{draft.srcInfo.h}</span>
              <button className="sm" onClick={cropPow2} title={tr('crop_the_middle_to_the_nearest')}>{tr('crop_to_power_of_two')}</button></div>}
            {draft.crop && <div className="muted small">{tr('crop')}{' '}{draft.crop.join(', ')} <button className="link" onClick={() => set('crop', null)}>{tr('clear_168cbb')}</button></div>}
            <h4>{tr('size')}</h4>
            <div className="row"><Seg value={String(draft.side)} onChange={v => set('side', Number(v))}
              options={SIDES.filter(s => s >= 16 && s <= Math.max(2048, Math.max(info.w, info.h))).filter(s => s >= Math.max(info.w, info.h) / 8 && s <= Math.max(info.w, info.h) * 2).map(s => ({ value: String(s), label: String(s) }))} /></div>
            <div className="muted small">{dims ? `${dims.w}×${dims.h}` : ''}{info.keep_dxt1 ? '' : ''}</div>
            <h4>{tr('format')}</h4>
            <div className="row" title={dxtLocked ? 'A DXT1 texture stays DXT1 in the game.' : undefined}><Seg value={draft.fmt} onChange={v => set('fmt', v)}
              options={[{ value: 'DXT1', label: tr('dxt1') }, { value: 'RGBA32', label: tr('rgba32'), disabled: dxtLocked }].filter(o => !o.disabled)} />
              {res && <span className="muted small" title={tr('how_close_the_stored_texture_is')}>{res.psnr}{' '}{tr('db')}</span>}</div>
            <h4>{tr('colour')}</h4>
            <RangeField label={tr('hue')} min={-180} max={180} step={1} def={0} value={draft.edits.hue} digits={0} unit="°" onChange={v => setE('hue', v)} onReset={() => setE('hue', 0)} />
            <RangeField label={tr('brightness')} min={-0.5} max={0.5} step={0.01} def={0} value={draft.edits.brightness} digits={2} onChange={v => setE('brightness', v)} onReset={() => setE('brightness', 0)} />
            <RangeField label={tr('contrast')} min={-0.5} max={0.5} step={0.01} def={0} value={draft.edits.contrast} digits={2} onChange={v => setE('contrast', v)} onReset={() => setE('contrast', 0)} />
            <RangeField label={tr('saturation')} min={-1} max={1} step={0.01} def={0} value={draft.edits.saturation} digits={2} onChange={v => setE('saturation', v)} onReset={() => setE('saturation', 0)} />
            <div className="row"><span className="muted" style={{ flex: 'none' }}>{tr('tint')}</span>
              <input type="color" aria-label={tr('tint')} value={draft.edits.tint} onChange={e => { setE('tint', e.target.value); if (!draft.edits.tint_amount) setE('tint_amount', 0.5) }} style={{ width: 40, padding: 0, flex: 'none' }} />
              <input type="range" aria-label={tr('tint_amount')} min={0} max={1} step={0.01} value={draft.edits.tint_amount} onChange={e => setE('tint_amount', Number(e.target.value))} /></div>
            <h4>{tr('transparency')}</h4>
            <div className="row"><Seg value={draft.edits.alpha} onChange={v => setE('alpha', v)} options={[{ value: 'keep', label: tr('keep') }, { value: 'opaque', label: tr('solid') }, { value: 'threshold', label: tr('cut_out') }]} /></div>
            {draft.edits.alpha === 'threshold' && <RangeField label={tr('cut_out_level')} min={0} max={1} step={0.01} def={0.5} value={draft.edits.alpha_cut} digits={2} onChange={v => setE('alpha_cut', v)} onReset={() => setE('alpha_cut', 0.5)} />}
            <h4>{tr('checks')}</h4>
            {res && res.limits.map(r => <Meter key={r.id} r={{ ...r, label: tr('size') }} />)}
            {shared && <p className="warn small" title={info.users.map(u => u.name).join('\n')}>{tr('shared_by')}{' '}{info.users.length}{' '}{tr('models_5f6957')}{' '}{info.users.slice(0, 4).map(u => u.name).join(', ')}{info.users.length > 4 ? ', …' : ''}{tr('all_of_them_change')}</p>}
            {info.hd && <p className="warn small" title={tr('tod_hd_keys_its_ground_height')}>{tr('already_changed_by_tod_hd_changing')}</p>}
            {info.blocks > 1 && <p className="muted small">{tr('changed_in')}{' '}{info.blocks}{' '}{tr('places_of_the_game')}</p>}
            <div className="btns">{changed && <button className="danger" onClick={revert}>{tr('revert')}</button>}</div>
          </div>}
        </div>
      </div>
    </div>
  )
}

function Pane({ label, src, note }) {
  return <div style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center', justifyContent: 'center' }}>
    <div style={{ flex: 1, minHeight: 0, width: '100%', display: 'grid', placeItems: 'center', position: 'relative' }}>
      {src ? <img src={src} alt={label} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', imageRendering: 'pixelated' }} /> : <span className="muted">{'…'}</span>}
    </div>
    <div className="small"><span className="upper">{label}</span> <span className="muted">{note}</span></div>
  </div>
}

const hashOf = s => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h }
function toHex(t) { return Array.isArray(t) ? '#' + t.map(v => v.toString(16).padStart(2, '0')).join('') : '#ffffff' }
function cleanEdits(e) {
  const o = {}
  if (e.hue) o.hue = e.hue
  for (const k of ['brightness', 'contrast', 'saturation']) if (e[k]) o[k] = e[k]
  if (e.tint_amount) { o.tint = hex(e.tint); o.tint_amount = e.tint_amount }
  if (e.alpha && e.alpha !== 'keep') { o.alpha = e.alpha; if (e.alpha === 'threshold') o.alpha_cut = e.alpha_cut }
  return o
}
