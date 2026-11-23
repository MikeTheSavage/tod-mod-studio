import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'
import { useUI, Seg, Switch, RangeField } from './ui.jsx'
import { usePad, setCfg, resetCfg, rawAxes } from './pad/padstore.js'
import { DEFAULTS, LIMITS } from './pad/padlogic.js'
import { useTest, setTestOpts, refreshTest } from './testStore.js'
import { fmtBytes } from './TestGame.jsx'
import { useUi } from './uistore.js'
import { DEFAULT_PREFS, SCALE_MIN, SCALE_MAX, TEXT_SIZES } from './uiprefs.js'
import { LANGUAGES } from './i18n.js'
import { t as tr } from './i18n.js'
import { saveAddon } from './blenderInbox.js'

// The games Mod Studio knows: yours, and the private test copies it made (they share the big files with yours).
function Installs({ status }) {
  const ui = useUI()
  const t = useTest()
  useEffect(() => { refreshTest(true) }, [])
  const list = t.status?.installs || []
  const remove = async i => {
    if (!(await ui.confirm({ title: tr('remove_this_test_copy'), body: i.folder, kept: tr('kept_your_game_your_mods_and'), ok: tr('remove_the_copy') }))) return
    try { await post('/api/testgame/remove', { id: i.id }); refreshTest(true) } catch (e) { ui.say(e.message, 'bad') }
  }
  return (
    <section className="card" aria-label={tr('installs')}>
      <h3>{tr('installs')}</h3>
      <div style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
        <div className="row" style={{ gap: 10, minHeight: 44, padding: '4px 12px' }}>
          <span className="badge ok">{tr('your_game')}</span>
          <div className="mono small grow" style={{ overflowWrap: 'anywhere' }} title={status.game.folder}>{status.game.folder}</div></div>
        {list.map(i => <div key={i.id} className="row" style={{ gap: 10, minHeight: 44, padding: '4px 12px', borderTop: '1px solid var(--line)' }}>
          <span className="badge">{tr('test_copy')}</span>
          <div className="grow"><div className="mono small" style={{ overflowWrap: 'anywhere' }} title={i.folder}>{i.folder}</div>
            <div className="small muted">{i.mode === 'linked' ? `${fmtBytes(i.real_bytes)} of its own, shares the rest` : fmtBytes(i.total_bytes)}{i.exists ? '' : ' Â· missing'}</div></div>
          <button className="sm danger" onClick={() => remove(i)}>{tr('remove')}</button></div>)}
      </div>
      <div className="row" style={{ alignItems: 'flex-start', gap: 12, marginTop: 10 }} title={tr('off_the_private_copy_is_removed')}>
        <Switch label={tr('keep_the_test_copy_after_the')} on={t.opts.keep} onChange={v => setTestOpts({ keep: v })} />
        <div style={{ fontWeight: 500 }}>{tr('keep_the_test_copy_after_the')}</div></div>
    </section>
  )
}

// the live stick circles: the ring is the dead zone, the dot goes bright once the push gets through it
function Stick({ x, y, dz }) {
  const R = 26
  const out = Math.hypot(x, y) > dz
  return <svg width="64" height="64" viewBox="-32 -32 64 64" aria-hidden="true">
    <circle r={R} fill="none" stroke="var(--line-strong)" strokeWidth="1.5" />
    <circle r={Math.max(2, dz * R)} fill="var(--surface-3)" stroke="var(--line)" />
    <circle cx={x * R} cy={y * R} r="5" fill={out ? 'var(--accent)' : 'var(--text-3)'} />
  </svg>
}
function Controller() {
  const p = usePad()
  const c = p.cfg
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(n => n + 1), 60); return () => clearInterval(t) }, [])
  const a = rawAxes()
  const row = (label, on, k, tip) => <div className="row" style={{ justifyContent: 'space-between', minHeight: 34 }} title={tip}>
    <div style={{ fontWeight: 500 }}>{label}</div><Switch label={label} on={on} onChange={v => setCfg({ [k]: v })} /></div>
  const rng = (label, k, step) => <RangeField label={label} min={LIMITS[k][0]} max={LIMITS[k][1]} step={step} def={DEFAULTS[k]} value={c[k]} digits={2}
    onChange={v => setCfg({ [k]: v })} onReset={() => setCfg({ [k]: DEFAULTS[k] })} />
  return <section className="card" aria-label={tr('controller')}>
    <h3>{tr('controller')}{' '}<span className={'badge' + (p.connected ? ' ok' : '')} style={{ marginLeft: 'auto', fontWeight: 500 }}>{p.connected ? p.name : 'Not connected'}</span></h3>
    <div className="row" style={{ gap: 18, alignItems: 'center', marginBottom: 8 }}>
      <Stick x={a[0]} y={a[1]} dz={c.deadzone} /><Stick x={a[2]} y={a[3]} dz={c.deadzone} />
      <div className="grow" />
      <button className="sm" onClick={resetCfg}>{tr('reset')}</button>
    </div>
    {row('Invert look Y', c.invertY, 'invertY')}
    {row('Swap A and B', c.swapAB, 'swapAB', 'For Nintendo-style pads')}
    {row('Vibration', c.rumble, 'rumble', 'A short buzz on confirm and on errors, where the pad supports it')}
    <div style={{ display: 'grid', gap: 10, marginTop: 8 }}>
      {rng('Look speed', 'lookSens', 0.05)}
      {rng('Fly speed', 'flySens', 0.05)}
      {rng('Dead zone', 'deadzone', 0.01)}
    </div>
  </section>
}


// Online features: nothing is read from a network until the switch is on and an address is set. Both addresses start empty.
function Online({ s, set, onUpdate }) {
  const ui = useUI()
  const [busy, setBusy] = useState(false)
  const check = async () => {
    setBusy(true)
    try { const r = await post('/api/update', { action: 'check' }); onUpdate(r); if (!r.available) ui.say(tr('you_have_the_newest_version')) }
    catch (e) { ui.say(e.message, 'bad') }
    setBusy(false)
  }
  return (
    <section className="card">
      <h3>{tr('online')}</h3>
      <div className="row" style={{ alignItems: 'flex-start', gap: 12 }} title={tr('off_mod_studio_never_connects_to')}>
        <Switch label={tr('allow_online_features')} on={!!s.online} onChange={v => set('online', v)} />
        <div style={{ fontWeight: 500 }}>{tr('allow_online_features')}</div></div>
      <label style={{ marginTop: 10 }}>{tr('community_list_address')}{' '}<input defaultValue={s.community_url || ''} placeholder={tr('https')} spellCheck={false} onBlur={e => set('community_url', e.target.value)} /></label>
      <label style={{ marginTop: 10 }}>{tr('update_address')}{' '}<input defaultValue={s.update_url || ''} placeholder={tr('https')} spellCheck={false} onBlur={e => set('update_url', e.target.value)} /></label>
      <div className="row" style={{ marginTop: 10, gap: 12 }}>
        <Switch label={tr('check_for_updates_when_mod_studio')} on={!!s.update_auto} onChange={v => set('update_auto', v)} disabled={!s.online} />
        <div className="grow">{tr('check_for_updates_when_it_starts')}</div>
        <button disabled={busy || !s.online || !s.update_url} onClick={check}>{tr('check_now')}</button></div>
    </section>
  )
}

function Variant() {
  const [v, setV] = useState(null)
  useEffect(() => { get('/api/variant').then(setV).catch(() => {}) }, [])
  if (!v) return null
  return <p className={'small' + (v.supported ? '' : ' warn')} title={`${v.store}, ${v.language}${v.exe_md5 ? ', ' + v.exe_md5 : ''}`}>{v.text}</p>
}

function Report() {
  const ui = useUI()
  const [what, setWhat] = useState('')
  const [steps, setSteps] = useState('')
  const [r, setR] = useState(null)
  const go = async () => {
    try { const res = await post('/api/report', { what, steps }); setR(res); post('/api/reveal', { path: res.folder }) }
    catch (e) { ui.say(e.message, 'bad') }
  }
  return (
    <section className="card">
      <h3>{tr('report_a_problem')}</h3>
      <label>{tr('what_happened')}{' '}<textarea rows={3} value={what} onChange={e => setWhat(e.target.value)} /></label>
      <label style={{ marginTop: 8 }}>{tr('what_you_did_before')}{' '}<textarea rows={2} value={steps} onChange={e => setSteps(e.target.value)} /></label>
      <div className="row" style={{ marginTop: 8 }}><button disabled={!what.trim()} onClick={go}>{tr('make_the_report')}</button>
        {r && <span className="small muted mono" style={{ overflowWrap: 'anywhere' }} title={r.folder}>{r.folder}</span>}</div>
    </section>
  )
}

function Appearance() {
  const look = useUi()
  const p = look.prefs
  const sw = (label, on, k, tip) => <div className="row" style={{ justifyContent: 'space-between', minHeight: 34 }} title={tip}>
    <div style={{ fontWeight: 500 }}>{label}</div><Switch label={label} on={on} onChange={v => look.set({ [k]: v })} /></div>
  return <>
    <section className="card" aria-label={tr('appearance')}>
      <h3>{tr('appearance')}</h3>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div style={{ fontWeight: 500 }}>{tr('theme')}</div>
        <Seg label={tr('theme')} large value={p.theme} onChange={v => look.set({ theme: v })} options={[{ value: 'system', label: tr('follow_windows') }, { value: 'dark', label: tr('dark') }, { value: 'light', label: tr('light') }, { value: 'contrast', label: tr('high_contrast') }]} />
      </div>
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 10 }}>
        <div style={{ fontWeight: 500 }}>{tr('mode')}</div>
        <Seg label={tr('mode')} large value={p.mode} onChange={v => look.set({ mode: v })} options={[{ value: 'beginner', label: tr('beginner'), title: tr('hides_the_rarely_used_screens') }, { value: 'advanced', label: tr('advanced'), title: tr('shows_everything') }]} />
      </div>
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 10 }}>
        <label htmlFor="lang-pick" style={{ fontWeight: 500, color: 'var(--text)', margin: 0 }}>{tr('language')}</label>
        <select id="lang-pick" style={{ width: 200 }} value={p.lang} onChange={e => look.set({ lang: e.target.value })}>
          {LANGUAGES.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}</select>
      </div>
    </section>
    <section className="card" aria-label={tr('accessibility')}>
      <h3>{tr('accessibility')}</h3>
      <RangeField label={tr('ui_scale')} min={SCALE_MIN} max={SCALE_MAX} step={5} def={DEFAULT_PREFS.scale} value={p.scale} unit="%" digits={0}
        onChange={v => look.set({ scale: v })} onReset={() => look.set({ scale: DEFAULT_PREFS.scale })} />
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 12 }}>
        <div style={{ fontWeight: 500 }}>{tr('text_size')}</div>
        <Seg label={tr('text_size')} value={p.text} onChange={v => look.set({ text: v })} options={TEXT_SIZES.map((v, i) => ({ value: v, label: ['Small', 'Normal', 'Large', 'Larger'][i] }))} />
      </div>
      {sw('Colour-blind safe colours', p.cb, 'cb', 'Meters, routes and the 3D view use colours that stay apart; shapes and words are always shown too')}
      <div className="row" style={{ justifyContent: 'space-between', minHeight: 34 }}>
        <div style={{ fontWeight: 500 }}>{tr('reduced_motion')}</div>
        <Seg label={tr('reduced_motion')} value={p.motion} onChange={v => look.set({ motion: v })} options={[{ value: 'system', label: tr('follow_windows') }, { value: 'reduce', label: tr('on') }, { value: 'full', label: tr('off') }]} />
      </div>
    </section>
  </>
}

export default function Settings({ status, refresh, openFirstRun, onUpdate }) {
  const ui = useUI()
  const s = status.settings || {}
  const set = async (k, v) => { await post('/api/settings', { [k]: v }); refresh() }
  const [folder, setFolder] = useState(status.game.folder)
  const [job, setJob] = useState(null)
  const pick = async setter => { const r = await post('/api/dialog', { kind: 'folder' }); if (r.path) setter(r.path) }
  const change = async () => { try { await runJob('/api/setup', { folder }, setJob); refresh(); ui.say(tr('game_folder_changed')) } catch (e) { ui.say(e.message, 'bad') } setJob(null) }
  const rebuild = async () => { try { await runJob('/api/prepare', {}, setJob); ui.say(tr('every_map_is_ready')) } catch (e) { ui.say(e.message, 'bad') } setJob(null) }
  return (
    <div className="center-page" style={{ placeItems: 'start center' }}>
      <div className="settings" style={{ width: '100%' }}>
        <h1>{tr('settings')}</h1>
        <Appearance />
        <Controller />
        <section className="card" aria-label={tr('game')}>
          <h3>{tr('game')}</h3>
          <div className="row"><input value={folder} onChange={e => setFolder(e.target.value)} aria-label={tr('game_folder')} style={{ fontFamily: 'var(--mono)' }} />
            <button onClick={() => pick(setFolder)}>{tr('browse')}</button><button className="primary" disabled={folder === status.game.folder || !!job} onClick={change}>{tr('use_this_folder')}</button></div>
          {!status.game.gog_exe && <p className="warn small">{tr('not_the_gog_build_some_features')}</p>}
          {status.game.tod_hd && <p className="small">{tr('tod_hd_detected')}</p>}
          <Variant />
          {(status.missing || []).length > 0 && <p className="warn small" role="status" title={status.missing.join(', ')}>{tr('a_picture_library_is_missing_the')}</p>}
          <p className="small"><a href="#" onClick={e => { e.preventDefault(); openFirstRun() }}>{tr('show_the_first_run_setup_again')}</a></p>
        </section>
        <Installs status={status} />
        <section className="card" aria-label={tr('building_mods')}>
          <h3>{tr('building_mods')}</h3>
          <div className="row" style={{ alignItems: 'flex-start', gap: 12 }} title={tr('off_mods_are_built_on_the')}><Switch label={tr('build_on_top_of_what_the')} on={s.build_on_installed !== false} onChange={v => set('build_on_installed', v)} />
            <div style={{ fontWeight: 500 }}>{tr('build_on_top_of_what_the')}</div></div>
          <div className="row" style={{ alignItems: 'flex-start', gap: 12, marginTop: 10 }}><Switch label={tr('deleting_an_object_keeps_old_saves')} on={s.save_safe_delete !== false} onChange={v => set('save_safe_delete', v)} />
            <div><div style={{ fontWeight: 500 }}>{tr('deleting_an_object_keeps_old_saves')}</div>
              {s.save_safe_delete === false && <div className="warn small">{tr('off_old_saves_may_break')}</div>}</div></div>
          <label style={{ marginTop: 12 }}>{tr('author_name_for_your_mods')}{' '}<input defaultValue={s.author || ''} onBlur={e => set('author', e.target.value)} /></label>
          <label style={{ marginTop: 12 }}>{tr('chili_con_carnage_data')}{' '}<input defaultValue={s.ccc_folder || ''} placeholder={tr('folder')} onBlur={e => set('ccc_folder', e.target.value)} /></label>
        </section>
        <Online s={s} set={set} onUpdate={onUpdate || (() => {})} />
        <section className="card" aria-label={tr('blender')}>
          <h3>{tr('blender')}</h3>
          <div className="row" style={{ alignItems: 'flex-start', gap: 12 }} title={tr('send_from_blender_tip')}>
            <Switch label={tr('send_from_blender')} on={!!s.blender_bridge} onChange={v => set('blender_bridge', v)} />
            <div className="grow" style={{ fontWeight: 500 }}>{tr('send_from_blender')}</div>
            {s.blender_bridge && <span className="mono small" title={tr('blender_port_tip')}>{tr('blender_port')} {location.port}</span>}
            <button onClick={() => saveAddon(ui.say)} title={tr('blender_add_on_tip')}>{tr('blender_add_on')}</button></div>
        </section>
        <Report />
        <section className="card">
          <h3>{tr('cache')}</h3>
          <p className="mono small" style={{ overflowWrap: 'anywhere' }}>{status.cache}</p>
          <div className="row"><button onClick={rebuild} disabled={!!job}>{tr('prepare_every_map_now')}</button>
            {job && <span className="muted small">{job.message} {job.total ? `${job.done}/${job.total}` : ''}</span>}</div>
        </section>
      </div>
    </div>
  )
}
