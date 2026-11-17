// Readiness (per map errors and warnings; install waits for zero errors) and management (numbers, switch off, remove with the saves report,
// shared host sections, map package export).
import React, { useEffect, useState } from 'react'
import { get, post } from '../api.js'
import { Switch } from '../ui.jsx'
import { useUi } from '../uistore.js'
import { t as tr } from '../i18n.js'
import { world } from './worldapi.js'
import * as W from './worldlib.js'

const Count = ({ n, kind }) => <span className={'badge ' + (n ? '' : 'ok')} style={n ? { background: kind === 'error' ? 'var(--bad-soft)' : 'var(--warn-soft)', color: kind === 'error' ? 'var(--bad)' : 'var(--warn)' } : null}
  aria-label={`${n} ${kind === 'error' ? tr('errors') : tr('warnings')}`}>{kind === 'error' ? '✕' : '⚠'}{' '}{n}</span>

export function Ready({ c }) {
  const rows = c.ready
  const glob = (c.pstore.data.newmap?.problems || [])
  const seen = new Set(rows.flatMap(r => r.rows.map(x => x.title)))
  const extra = glob.filter(p => !seen.has(p.title || p.text))
  const errs = rows.reduce((a, r) => a + r.errors, 0) + extra.filter(p => p.level === 'error').length, warns = rows.reduce((a, r) => a + r.warns, 0) + extra.filter(p => p.level !== 'error').length
  const go = (x, index) => c.goTo({ ...W.jumpOf(x.title, x.where, index), ...(x.jump || {}), ...(index != null ? { map: index } : {}) })
  return <div className="vp" style={{ overflow: 'auto', padding: 18 }}>
    <div style={{ maxWidth: 780 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <div className="upper grow">{tr('readiness')}</div>
        <Count n={errs} kind="error" /><Count n={warns} kind="warn" />
        <span className={'badge ' + (c.blocked ? '' : 'ok')} style={c.blocked ? { background: 'var(--bad-soft)', color: 'var(--bad)' } : null} role="status">{c.blocked ? '✕ ' + tr('install_blocked') : '✓ ' + tr('ready_to_install')}</span>
      </div>
      {rows.length === 0 && <div className="muted">{tr('no_map_project_open')}</div>}
      {rows.map(r => <div key={r.index} className="rcard">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><b className="grow">{c.params.maps[r.index].card?.title || r.name}</b><Count n={r.errors} kind="error" /><Count n={r.warns} kind="warn" /></div>
        {r.rows.length === 0 && r.errors === 0 && <div className="small good">{'✓ '}{tr('no_problem_found')}</div>}
        {r.rows.map((x, i) => <div key={i} className="small rrow" role="button" tabIndex={0} title={x.detail} onClick={() => go(x, r.index)}
          onKeyDown={e => e.key === 'Enter' && go(x, r.index)}><span className={x.level === 'error' ? 'bad' : 'warn'}>{x.level === 'error' ? '✕' : '⚠'}</span>{' '}{x.title}</div>)}
      </div>)}
      {extra.length > 0 && <div className="rcard"><div className="upper" style={{ marginBottom: 6 }}>{tr('project')}</div>
        {extra.slice(0, 40).map((p, i) => <div key={i} className="small rrow" role="button" tabIndex={0} title={p.detail} onClick={() => go(p)} onKeyDown={e => e.key === 'Enter' && go(p)}><span className={p.level === 'error' ? 'bad' : 'warn'}>{p.level === 'error' ? '✕' : '⚠'}</span>{' '}{p.title || p.text}</div>)}</div>}
    </div>
  </div>
}

export function Manage({ c }) {
  const ui = useUi()
  const advanced = ui.prefs.mode !== 'beginner'
  const [alloc, setAlloc] = useState(null), [shared, setShared] = useState([]), [report, setReport] = useState(null), [path, setPath] = useState(''), [note, setNote] = useState('')
  const load = () => { get('/api/newmap/allocation').then(setAlloc).catch(() => setAlloc({ owners: [], limits: {} })) }
  useEffect(() => {
    load()
    if (advanced) get('/api/mods').then(r => setShared(r.conflicts?.shared_hosts || [])).catch(() => {})
  }, [c.project?.id, c.library.projects.length, advanced])
  const owner = id => (alloc?.owners || []).find(o => o.project === id)
  const installed = id => !!owner(id) || (c.ov?.new_maps || []).some(n => n.id === id)
  const lim = alloc?.limits || {}
  const nameOf = o => o.name || o.label || o.project || o.key
  const showRemoval = async id => {
    try { setReport(await post('/api/newmaps', { action: 'removal', id })) } catch (e) { setNote(e.message) }
  }
  const exportIt = async () => {
    try { const r = await world('export', { params: c.params, path }); setNote(tr('written') + ': ' + r.path) } catch (e) { setNote(e.message) }
  }
  return <div className="vp" style={{ overflow: 'auto', padding: 18 }}>
    <div style={{ maxWidth: 820, display: 'flex', flexDirection: 'column', gap: 14 }}>
      {note && <div className="callout neutral small" role="status">{note}</div>}
      <section>
        <div className="upper" style={{ marginBottom: 6 }}>{tr('numbers_given_out')}</div>
        {(alloc?.owners || []).length === 0 && <div className="muted small">{tr('nothing_installed_yet')}</div>}
        {(alloc?.owners || []).map(o => <div key={o.key} className="rcard" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <b className="grow">{nameOf(o)}</b>
          {o.maps.map((r, i) => <span key={i} className="badge mono">{tr('map')} {r.map_id}{' · '}{tr('section')} {r.submap_id}</span>)}
          {(o.sections || []).map(s => <span key={s} className="badge mono">{tr('section')} {s}</span>)}
          {o.disabled && <span className="badge">{tr('switched_off')}</span>}
        </div>)}
        {lim.total_maps != null && <div className="small muted">{tr('maps_in_the_game')}{': '}{lim.total_maps}{' / '}{lim.measured_maps}{' '}{tr('tested')}{lim.holes?.length ? ' · ' + tr('gaps') + ' ' + lim.holes.join(', ') : ''}</div>}
      </section>
      <section>
        <div className="upper" style={{ marginBottom: 6 }}>{tr('map_projects')}</div>
        {c.library.projects.map(p => <div key={p.id} className="rcard" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <b className="grow">{p.params.package}</b>
          {installed(p.id) ? <>
            <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{tr('on')}
              <Switch on={!owner(p.id)?.disabled} label={tr('on')} onChange={v => c.action(v ? 'enable' : 'disable', p.id)} /></label>
            <button className="sm" onClick={() => showRemoval(p.id)}>{tr('what_it_touches')}</button>
            <button className="sm danger" onClick={() => c.removeProject(p.id)}>{tr('remove')}</button></> : <span className="muted small">{tr('not_in_the_game')}</span>}
        </div>)}
        {report && <div className="rcard" role="region" aria-label={tr('removal_report')}>
          <div className="upper" style={{ marginBottom: 6 }}>{tr('taking_it_out_touches')}</div>
          <div className="small">{tr('maps')}{': '}{report.maps.join(', ') || '—'}</div>
          <div className="small">{tr('entrances_in')}{': '}{[...new Set(report.entrances.map(x => x.label))].join(', ') || '—'}</div>
          {report.missions?.length > 0 && <div className="small warn">{tr('missions_inside')}{': '}{report.missions.map(x => x.name).join(', ')}</div>}
          <div className={'small ' + (report.saves?.length ? 'warn' : 'good')}>{report.saves?.length ? '⚠ ' + tr('saves_standing_on_it') + ': ' + report.saves.length : '✓ ' + tr('no_save_stands_on_it')}</div>
          {(report.saves || []).slice(0, 6).map((s, i) => <div key={i} className="small muted mono">{typeof s === 'string' ? s : (s.file || s.name || JSON.stringify(s))}</div>)}
          <div className="small muted">{report.backup}</div>
          <button className="sm" onClick={() => setReport(null)}>{tr('close')}</button>
        </div>}
      </section>
      {advanced && <section>
        <div className="upper" style={{ marginBottom: 6 }}>{tr('shared_sections')}</div>
        {shared.length === 0 && <div className="muted small">{tr('no_section_is_shared')}</div>}
        {shared.map(s => <div key={s.block} className="rcard"><b>{s.label}</b>
          {s.owners.map((o, i) => <div key={i} className="small">{o.name}<span className="muted">{' · '}{o.kind}{' · '}{o.entries}</span></div>)}</div>)}
      </section>}
      <section>
        <div className="upper" style={{ marginBottom: 6 }}>{tr('map_package')}</div>
        <div style={{ display: 'flex', gap: 6 }}><input aria-label={tr('folder_or_file')} placeholder={tr('folder_or_file_to_write')} value={path} onChange={e => setPath(e.target.value)} />
          <button disabled={!path.trim() || !c.params} onClick={exportIt}>{tr('export')}</button></div>
      </section>
    </div>
  </div>
}
