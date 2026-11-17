import React, { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { post, runJob, jobsStore } from './api.js'
import { t } from './i18n.js'

const STEPS = ['Game folder', 'One-time setup', 'Get started']
const DEFAULT_FOLDER = 'C:\\GOG Games\\Total Overdose'

function Steps({ n }) {
  return (
    <div className="frsteps">
      {STEPS.map((l, i) => {
        const k = i + 1, done = n > k, cur = n === k
        return (
          <div className="s" key={l}>
            <div className="n" style={{ background: done ? 'var(--ok)' : cur ? 'var(--accent)' : 'transparent', color: done ? 'var(--bg)' : cur ? 'var(--accent-ink)' : 'var(--text-3)',
              borderColor: done ? 'var(--ok)' : cur ? 'var(--accent)' : 'var(--line-strong)' }}>{done ? '\u2713' : k}</div>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: cur ? 'var(--text)' : 'var(--text-3)' }}>{l}</div>
            <div className="ln" />
          </div>)
      })}
    </div>
  )
}

// Welcome flow: choose the game folder, then the one-time cache. Uses /api/setup and /api/prepare like the old setup page.
export default function FirstRun({ status, onDone, onGame, keepOpen }) {
  const [step, setStep] = useState(1)
  const [folder, setFolder] = useState(status.settings?.game_folder || DEFAULT_FOLDER)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(status.settings?.last_error || null)
  const [prep, setPrep] = useState(null)
  const t0 = useRef(0)
  const browse = async () => { const r = await post('/api/dialog', { kind: 'folder' }); if (r.path) { setFolder(r.path); setErr(null) } }
  useEffect(() => { keepOpen?.() }, [])
  const use = async () => {
    setErr(null); setBusy(true)
    try {
      await runJob('/api/setup', { folder })
      await onGame()
      setStep(2); setBusy(false)
      t0.current = Date.now()
      runJob('/api/prepare', {}, setPrep).catch(e => setErr(e.message))
    } catch (e) { setErr(e.message); setBusy(false) }
  }
  const total = prep?.total || 0, done = prep?.done || 0
  const pct = total ? Math.round(100 * done / total) : 0
  const mins = total && done > 2 ? Math.max(1, Math.round(((Date.now() - t0.current) / done) * (total - done) / 60000)) : null
  const finished = prep?.status === 'done'
  const jobs = useSyncExternalStore(jobsStore.subscribe, jobsStore.get)
  const j = jobs[0], jp = j && j.total > 0 ? Math.round(100 * j.done / j.total) : null
  return (
    <div className="shell">
      <header className="topbar"><div className="logo" style={{ cursor: 'default' }}><i><b /></i></div><div className="title">{t('mod_studio')}{' '}{'·'}{' '}{t('welcome')}</div></header>
      <div className="body"><main className="main"><div className="center-page" style={{ height: '100%' }}>
      <div className="fr">
        <Steps n={step} />
        {step === 1 && <>
          <h1 style={{ marginBottom: 20 }}>{t('where_is_your_game_installed')}</h1>
          <div className="card" style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: '14px 16px', borderColor: 'var(--line-strong)', marginBottom: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="upper" style={{ marginBottom: 4 }}>{status.settings?.game_folder ? 'Your game folder' : 'Usual place'}</div>
              <input value={folder} onChange={e => setFolder(e.target.value)} aria-label={t('game_folder')} style={{ fontFamily: 'var(--mono)', fontWeight: 500 }} />
            </div>
            <button onClick={browse}>{t('choose_another_folder')}{'\u2026'}</button>
          </div>
          {err && <div className="callout bad" style={{ marginBottom: 16 }}>{err}</div>}
          <button className="primary lg" disabled={busy || !folder.trim()} onClick={use}>{busy ? 'Checking the folder\u2026' : 'Use this folder'}</button>
        </>}
        {step === 2 && <>
          <h1>{t('one_time_setup')}</h1>
          <div style={{ height: 20 }} />
          <div className="card" style={{ padding: 16, borderColor: 'var(--line-strong)', marginBottom: 12, gap: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
              <span style={{ fontWeight: 600 }}>{finished ? 'Done' : total ? `Reading maps \u00b7 ${Math.min(done + 1, total)} of ${total}` : 'Starting\u2026'}</span>
              <span style={{ color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>{finished ? '100%' : total ? `${pct}%${mins ? ` \u00b7 about ${mins} min left` : ''}` : ''}</span></div>
            <div className="progbar"><i style={{ width: (finished ? 100 : pct) + '%' }} /></div>
            {prep?.message && !finished && <div className="muted small" style={{ marginTop: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{prep.message}</div>}
          </div>
          {err && <div className="callout bad" style={{ marginBottom: 12 }}>{err}</div>}
          <div style={{ height: 24 }} />
          <div className="row"><button className="primary lg" onClick={() => setStep(3)}>{t('continue')}</button><button className="lg" onClick={() => setStep(1)}>{t('back')}</button></div>
        </>}
        {step === 3 && <>
          <h1>{t('you_are_ready')}</h1>
          <div style={{ height: 20 }} />
          <button className="primary lg" onClick={onDone}>{t('go_to_home')}</button>
        </>}
      </div>
    </div></main></div>
      <footer className="statusbar"><span style={{ flex: 1 }} />
        <span className="it" style={{ flex: 'none' }}>{j ? <><span>{step === 1 ? j.label : 'First-time setup'}</span><span className={'bar' + (jp == null ? ' indet' : '')}><i style={jp != null ? { width: jp + '%' } : undefined} /></span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{jp != null ? jp + '%' : ''}</span></> : <span className="t3">{t('no_jobs_running')}</span>}</span></footer>
    </div>
  )
}
