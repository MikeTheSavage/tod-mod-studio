// The Debug area: a test run (settings, live engine log, what the last run said), the bad-mod search and the support bundle.
import React, { useEffect, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import { Advanced, Seg, Switch, useUI } from './ui.jsx'
import { SlotList } from './TestSave.jsx'
import TestControl, { Dots, fmtBytes, confirmFullCopy } from './TestGame.jsx'
import { useTest, setTestOpts, refreshTest, STEPS } from './testStore.js'
import { t as tr } from './i18n.js'

const base = p => String(p || '').split(/[\\/]/).pop()
const PROBLEM = /could not read|unable to load|failed|error|exception|assert|overflow|out of memory|cannot|not found|missing|invalid|corrupt/i
const NOISE = /chunksize .* of the StreamedWAV loader|available=0|dangling assets\s*:\s*0\b/i
const LOAD = /BLOCK IN MEMORY|read asset block file|Opening zip|Load Time:|ASSET MEMORY USAGE|MainAssetBlock|MissionAssetBlock|PlayerdataBlock/i

// ---------------------------------------------------------------- the live log
function LogView({ runId, running }) {
  const [lines, setLines] = useState([])
  const [mode, setMode] = useState('all')
  const off = useRef(0)
  const box = useRef(null)
  const stick = useRef(true)
  useEffect(() => { off.current = 0; setLines([]) }, [runId])
  useEffect(() => {
    let dead = false
    const tick = async () => {
      try {
        const r = await get('/api/testgame/log', { offset: off.current })
        if (dead) return
        if (r.offset < off.current) setLines([])
        off.current = r.offset
        if (r.text) setLines(l => { const add = r.text.split(/\r?\n/).filter(x => x !== ''); return l.concat(add).slice(-4000) })
      } catch { /* the app is busy */ }
    }
    tick()
    const t = setInterval(tick, running ? 700 : 3000)
    return () => { dead = true; clearInterval(t) }
  }, [runId, running])
  useEffect(() => { const e = box.current; if (e && stick.current) e.scrollTop = e.scrollHeight }, [lines, mode])
  const shown = mode === 'all' ? lines : lines.filter(l => mode === 'loads' ? LOAD.test(l) : PROBLEM.test(l) && !NOISE.test(l))
  return (
    <div className="logwrap">
      <div className="tb" style={{ borderTop: 0 }}>
        <Seg value={mode} onChange={setMode} options={[{ value: 'all', label: tr('everything') }, { value: 'loads', label: tr('loads') }, { value: 'problems', label: tr('problems') }]} />
        <div style={{ flex: 1 }} />
        <span className="small muted">{lines.length ? `${lines.length.toLocaleString('en-US')} lines` : ''}</span>
      </div>
      <div className="logview" ref={box} onScroll={e => { const t = e.currentTarget; stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < 40 }} role="log" aria-label={tr('engine_log')}>
        {!lines.length && <div className="muted" style={{ padding: 12 }}>{runId ? 'The log is empty.' : 'No test yet.'}</div>}
        {shown.map((l, i) => <div key={i} className={PROBLEM.test(l) && !NOISE.test(l) ? 'bad' : /BLOCK IN MEMORY/.test(l) ? 'ld' : ''}>{l}</div>)}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- what the last run said
const Bar = ({ pct, tone }) => <div className="mbar"><i style={{ width: Math.min(100, pct || 0) + '%', background: tone === 'bad' ? 'var(--bad)' : tone === 'warn' ? 'var(--warn)' : 'var(--ok)' }} /></div>

function Summary({ run, summary }) {
  if (!run) return <div className="panel-b muted">{tr('no_test_yet')}</div>
  const running = run.status === 'running'
  const crash = run.crash
  const tone = running ? 'warn' : crash ? 'bad' : 'ok'
  const head = running ? 'Running' : crash ? 'Crashed' : run.stopped ? 'Closed from here' : 'Closed normally'
  return (
    <div className="panel-b" style={{ gap: 10, overflow: 'auto' }}>
      <div className="row" style={{ gap: 8 }}><span className={'badge ' + (tone === 'ok' ? 'ok' : '')} style={tone === 'bad' ? { background: 'var(--bad-soft)', color: 'var(--bad)' } : tone === 'warn' ? { background: 'var(--warn-soft)', color: 'var(--warn)' } : undefined}>{head}</span>
        <span className="small muted">{(run.started || '').replace('T', ' ')}</span></div>
      {crash && <div className="callout bad" style={{ padding: '8px 12px' }}>
        <div style={{ fontWeight: 600 }}>{crash.why}</div>
        {(crash.loading || crash.last_read) && <div className="small" title={crash.loading || crash.last_read}>{tr('last_block_it_read')}{' '}<b>{base(crash.loading || crash.last_read)}</b></div>}
        {crash.last_block && <div className="small">{tr('last_block_in_memory')}{' '}<b>{crash.last_block}</b></div>}
        <Advanced title={tr('last_lines')}><pre className="mono small" style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 200, overflow: 'auto' }}>{(crash.tail || []).join('\n')}</pre></Advanced></div>}
      {summary && <>
        <div><div className="upper">{tr('blocks_loaded')}</div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{summary.blocks_loaded}</div>
          <div className="small muted" style={{ overflowWrap: 'anywhere' }}>{summary.blocks.map(b => b.name + (b.times > 1 ? ' ×' + b.times : '')).join(', ')}</div></div>
        <div><div className="upper" style={{ marginBottom: 4 }}>{tr('memory')}</div>
          {summary.pools.length ? summary.pools.map(p => <div key={p.name} style={{ marginBottom: 6 }} title={`Most used: ${p.peak} MB of ${p.cap} MB`}>
            <div className="row" style={{ justifyContent: 'space-between' }}><span>{p.name}</span><span className="small" style={{ fontVariantNumeric: 'tabular-nums' }}>{p.peak}{' '}{tr('of')}{' '}{p.cap}{' '}{tr('mb')}</span></div>
            <Bar pct={p.pct} tone={p.pct > 100 ? 'bad' : p.pct >= 70 ? 'warn' : 'ok'} /></div>) : <div className="small muted">{tr('not_reached_yet')}</div>}</div>
        <div><div className="upper" style={{ marginBottom: 4 }}>{tr('problems')}{' '}{summary.problem_count ? <span className="badge" style={{ marginLeft: 4 }}>{summary.problem_count}</span> : null}</div>
          {summary.problems.length ? summary.problems.map((p, i) => <div key={i} className="small" style={{ overflowWrap: 'anywhere', marginBottom: 4 }}><span className="bad">{p.count > 1 ? p.count + '× ' : ''}</span>{p.line}</div>) : <div className="small muted">{tr('none')}</div>}</div>
        {summary.slowest?.length > 0 && <div><div className="upper" style={{ marginBottom: 4 }}>{tr('slowest_loads')}</div>
          {summary.slowest.map(([n, ms]) => <div key={n} className="row small" style={{ justifyContent: 'space-between' }}><span>{n}</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{ms}{' '}{tr('ms')}</span></div>)}</div>}
      </>}
      {(run.notes || []).map((n, i) => <p key={i} className="small warn">{n}</p>)}
    </div>
  )
}

// ---------------------------------------------------------------- the test run screen
function TestRun({ project, go, spot }) {
  const t = useTest()
  const o = t.opts
  const st = t.status
  const [missions, setMissions] = useState([])
  const slots = st?.slots
  useEffect(() => { refreshTest(true) }, [])
  useEffect(() => { const i = setInterval(() => refreshTest(!st?.slots), st?.running ? 2000 : 6000); return () => clearInterval(i) }, [st?.running, !st?.slots])
  const newest = slots && slots.slice().sort((a, b) => (b.modified || '').localeCompare(a.modified || ''))[0]
  const src = o.source || newest?.path || ''
  useEffect(() => {
    if (!src) { setMissions([]); return }
    post('/api/saves/missions', { source: src }).then(r => setMissions(r.missions || [])).catch(() => setMissions([]))
  }, [src])
  const run = st?.run
  const picked = slots?.find(s => s.path === src)
  return (
    <div className="screen">
      <div className="tb">
        <div style={{ fontWeight: 600 }}>{tr('test_run')}</div>
        <TestControl project={project} go={go} primary />
        <div className="vsep" />
        <label className="check" title={tr('keep_the_private_copy_of_the')}><Switch label={tr('keep_the_copy')} on={o.keep} onChange={v => setTestOpts({ keep: v })} />{' '}{tr('keep_the_copy')}</label>
        <div style={{ flex: 1 }} />
        <span className="small muted">{st?.plan ? (st.plan.mode === 'linked' ? 'Shares the game files' : 'Full copy') + ' · ' + fmtBytes(st.plan.extra_bytes) : ''}</span>
      </div>
      <div className="split">
        <div className="panel-l" style={{ width: 'calc(var(--side-l) + 56px)', overflow: 'auto' }}>
          <div className="panel-b" style={{ gap: 10 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}><div className="upper">{tr('start_at')}</div>
              <label className="check" style={{ margin: 0 }}><Switch label={tr('make_a_test_save')} on={o.save} onChange={v => setTestOpts({ save: v })} /></label></div>
            {o.save && <>
              {slots ? (slots.length ? <SlotList slots={slots} value={src} onChange={p => setTestOpts({ source: p })} /> : <p className="warn small">{tr('no_saves_found')}</p>) : <div className="muted small">{tr('reading_saves')}{'…'}</div>}
              <label>{tr('spot')}{' '}<span className="muted">{tr('x_height_z')}</span>{o.spotName && <span className="muted"> {'·'} {o.spotName}</span>}
                <input value={o.pos} onChange={e => setTestOpts({ pos: e.target.value, spotName: '' })} placeholder={tr('where_the_save_is')} className="mono" /></label>
              <label>{tr('facing')}{' '}<input value={o.yaw} onChange={e => setTestOpts({ yaw: e.target.value })} placeholder={tr('keep')} style={{ width: 90 }} /></label>
              <label className="check"><Switch label={tr('full_health')} on={o.heal} onChange={v => setTestOpts({ heal: v })} />{' '}{tr('full_health')}</label>
              <label className="check"><Switch label={tr('all_weapons')} on={o.weapons} onChange={v => setTestOpts({ weapons: v })} />{' '}{tr('all_weapons')}</label>
              <label className="check"><Switch label={tr('god_mode')} on={o.god} onChange={v => setTestOpts({ god: v })} />{' '}{tr('god_mode')}</label>
              <label className="check"><Switch label={tr('unlimited_ammo')} on={o.ammo} onChange={v => setTestOpts({ ammo: v })} />{' '}{tr('unlimited_ammo')}</label>
              <label className="check"><Switch label={tr('open_every_mission')} on={o.unlock} onChange={v => setTestOpts({ unlock: v })} />{' '}{tr('open_every_mission')}</label>
              <Advanced title={tr('start_a_mission')} note={tr('not_playable_yet')}>
                <select value="" disabled aria-label={tr('mission_to_start')} title={tr('a_save_that_starts_a_mission')}>
                  <option value="">{tr('none_6eef66')}</option>
                  {missions.map(m => <option key={m.i} value={m.i}>{m.name.replace(/_award.*$/i, '')}</option>)}</select></Advanced>
            </>}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}><LogView runId={run?.id} running={st?.running} /></div>
        <div className="panel-r"><Summary run={run} summary={st?.summary} /></div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- find a bad mod
function Bisect({ go }) {
  const ui = useUI()
  const t = useTest()
  const [b, setB] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = () => get('/api/bisect').then(setB).catch(e => ui.say(e.message, 'bad'))
  useEffect(() => { load(); refreshTest(true) }, [])
  const act = async (action, extra) => { try { setB(await post('/api/bisect', { action, ...extra })) } catch (e) { ui.say(e.message, 'bad') } }
  const test = async () => {
    setBusy(true)
    try {
      let r = await runJob('/api/bisect', { action: 'test', opts: { save: false } })
      if (r?.confirm) { if (await confirmFullCopy(ui)(r.confirm)) r = await runJob('/api/bisect', { action: 'test', allow_full_copy: true, opts: { save: false } }) }
      await refreshTest(true)
    } catch (e) { ui.say(e.message, 'bad') }
    setBusy(false)
  }
  const s = b?.state
  const run = t.status?.run
  const waiting = run?.status === 'running' && !!run?.bisect
  const exited = run?.status === 'exited' && run?.bisect && s && s.phase !== 'done' && JSON.stringify(run.bisect.ids) === JSON.stringify(s.next_ids)
  return (
    <div className="screen"><div className="tb"><div style={{ fontWeight: 600 }}>{tr('find_a_bad_mod')}</div><div style={{ flex: 1 }} />
      {s && <button onClick={() => act('cancel')}>{tr('start_over')}</button>}</div>
    <div style={{ flex: 1, overflow: 'auto', padding: 20 }}><div style={{ maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {!s && <section className="card" style={{ gap: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{b?.mods?.length ? `${b.mods.length} mods are on` : 'No mods are on'}</div>
        <div className="small muted" style={{ overflowWrap: 'anywhere' }}>{(b?.mods || []).map(m => m.name).join(', ')}</div>
        <div><button className="primary" disabled={!b?.mods?.length} onClick={() => act('start')}>{tr('start_the_search')}</button></div></section>}
      {s && s.phase !== 'done' && <section className="card" style={{ gap: 10 }}>
        <div className="upper">{s.phase === 'confirm' ? 'Last one' : 'Next test'}</div>
        <div style={{ fontWeight: 600, fontSize: 15 }}>{s.next.join(', ')}</div>
        <div className="small muted">{s.candidate_names.length}{' '}{tr('left_to_check')}</div>
        {!waiting && !exited && <div><button className="primary" disabled={busy || t.busy} onClick={test}>{busy ? 'Starting…' : 'Test these'}</button></div>}
        {waiting && <div className="row" style={{ gap: 8 }}><span className="small">{tr('game_is_running')}</span></div>}
        {exited && <div className="row" style={{ gap: 8 }}><span>{tr('did_the_problem_happen')}</span>
          <button className="dangerfill" onClick={() => act('answer', { bad: true })}>{tr('yes')}</button><button onClick={() => act('answer', { bad: false })}>{tr('no')}</button></div>}
      </section>}
      {s?.phase === 'done' && <section className={'callout' + (s.verdict === 'one' ? '' : ' warn')} style={{ padding: '12px 16px' }}>
        {s.verdict === 'one' && <div style={{ fontWeight: 600, fontSize: 15 }}>{s.culprit_name}{' '}{tr('causes_it')}</div>}
        {s.verdict === 'several' && <div style={{ fontWeight: 600 }}>{tr('no_single_mod_does_it_it')}</div>}
        {s.verdict === 'none' && <div style={{ fontWeight: 600 }}>{tr('no_mods_are_on')}</div>}
        <div style={{ marginTop: 8 }}><button onClick={() => go('mods')}>{tr('open_the_mod_library')}</button></div></section>}
      {s?.steps.length > 0 && <section className="card sm" style={{ gap: 4 }}><div className="upper">{tr('tested')}</div>
        {s.steps.map((x, i) => <div key={i} className="row small" style={{ justifyContent: 'space-between' }}><span style={{ overflowWrap: 'anywhere' }}>{x.names.join(', ')}</span>
          <span className={x.bad ? 'bad' : 'good'}>{x.bad ? 'Problem' : 'Fine'}</span></div>)}</section>}
    </div></div></div>
  )
}

// ---------------------------------------------------------------- support bundle
function Support() {
  const ui = useUI()
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const make = async () => {
    setBusy(true)
    try { setRes(await post('/api/support/bundle', {})) } catch (e) { ui.say(e.message, 'bad') }
    setBusy(false)
  }
  return (
    <div className="screen"><div className="tb"><div style={{ fontWeight: 600 }}>{tr('support')}</div></div>
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}><section className="card" style={{ maxWidth: 560, gap: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{tr('support_bundle')}</div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>{['Game version', 'Mod list', 'Last test run', 'Engine log', 'System'].map(x => <span key={x} className="badge">{x}</span>)}</div>
        <div className="row" style={{ gap: 8 }}><button className="primary" disabled={busy} onClick={make}>{busy ? 'Working…' : 'Make the bundle'}</button>
          {res && <button onClick={() => post('/api/reveal', { path: res.path })}>{tr('show_in_folder')}</button>}</div>
        {res && <div className="small muted">{fmtBytes(res.bytes)}</div>}
      </section></div></div>
  )
}

export default function Debug({ view, project, go, spot }) {
  if (view === 'bisect') return <Bisect go={go} />
  if (view === 'support') return <Support />
  return <TestRun project={project} go={go} spot={spot} />
}
