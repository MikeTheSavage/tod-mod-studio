// The ceiling meters: a strip for an editor, the full Limits table, and the status-bar item.
// Green below 70 %, amber 70-100 %, red above; a limit that nothing measures is grey and never green.
import React, { useEffect, useMemo, useState } from 'react'
import { post } from './api.js'
import { Menu, Seg } from './ui.jsx'
import { jumpTo, useStore } from './problemsStore.js'
import { t as tr } from './i18n.js'

export const SHORT = { L1: 'Block nodes', L4: 'Cars', P1: 'Archives', P2: 'Pack size', P8: 'Level memory', P5: 'Largest asset', L7: 'Mission slots', L8: 'Maps',
  L11: 'Text', G2: 'Section triangles', G3: 'Collision pieces', M1: 'Model detail', P6: 'Biggest texture', L15: 'Collision points', L15_index: 'Collision faces', L16_pos: 'Distance', L16_box: 'Box size' }
const short = r => SHORT[r.id] || r.label

export function fmt(v, unit) {
  if (v == null) return ''
  if (unit === 'bytes') {
    if (v >= 1073741824) return (v / 1073741824).toFixed(2) + ' GB'
    if (v >= 1048576) return (v / 1048576).toFixed(1) + ' MB'
    if (v >= 1024) return (v / 1024).toFixed(0) + ' KB'
    return v + ' B'
  }
  return typeof v === 'number' ? v.toLocaleString('en-US') : String(v)
}

const ORDER = { red: 0, amber: 1, ok: 2, grey: 3 }
const TONE = { red: 't-bad', amber: 't-warn', ok: 't-ok', grey: 't-grey' }
// colour is never the only signal: every state also has a shape and (for screen readers and tooltips) a word
export const GLYPH = { ok: '✓', amber: '▲', red: '✖', grey: '–' }
export const STATE_WORD = { ok: 'Fine', amber: 'Getting close', red: 'Over the limit', grey: 'Not measured' }

export function meterTip(r) {
  const p = r.parts || {}
  const lines = [`${r.label}${r.id ? ' (' + r.id + ')' : ''}`]
  if (r.used != null && r.max != null) lines.push(`${fmt(r.used, r.unit)} of ${fmt(r.max, r.unit)}${r.pct != null ? ' (' + Math.round(r.pct) + ' %)' : ''}`)
  if (r.used != null && (p.vanilla || p.packages || p.project)) lines.push(`game ${fmt(p.vanilla || 0, r.unit)} + installed ${fmt(p.packages || 0, r.unit)} + this project ${fmt(p.project || 0, r.unit)}`)
  if (r.status === 'grey') lines.push(r.reason === 'run Check' ? 'Measured by Check.' : 'Not measured.')
  if (r.note) lines.push(r.note)
  lines.push(r.scope, r.effect, 'Confidence: ' + r.confidence, 'Source: ' + r.source)
  return lines.join('\n')
}

export function Meter({ r, onClick }) {
  const tone = TONE[r.status]
  const pct = r.pct == null ? 0 : Math.min(100, r.pct)
  return (
    <div className={'meter ' + tone + (onClick ? ' click' : '')} title={STATE_WORD[r.status] + ' - ' + meterTip(r)} onClick={onClick}
      role={r.pct == null || r.status === 'grey' ? 'img' : 'meter'} aria-label={short(r) || undefined}
      aria-valuemin={r.pct == null || r.status === 'grey' ? undefined : 0} aria-valuemax={r.pct == null || r.status === 'grey' ? undefined : 100}
      aria-valuenow={r.pct == null || r.status === 'grey' ? undefined : Math.round(pct)}
      aria-valuetext={`${STATE_WORD[r.status]}: ${r.status === 'grey' ? (r.reason || 'not measured') : `${fmt(r.used, r.unit)} of ${fmt(r.max, r.unit)}`}`}>
      <span className="mg" aria-hidden="true">{GLYPH[r.status]}</span>
      <span className="ml">{short(r)}</span>
      <span className="mb"><i style={{ width: r.status === 'grey' ? 0 : Math.max(2, pct) + '%' }} /></span>
      <span className="mv">{r.status === 'grey' ? (r.reason || 'not measured') : `${fmt(r.used, r.unit)} / ${fmt(r.max, r.unit)}`}</span>
    </div>
  )
}

const relevant = (rows, kind) => (rows || []).filter(r => r.kinds.includes(kind))
const sortRows = rows => rows.slice().sort((a, b) => ORDER[a.status] - ORDER[b.status] || (b.pct || 0) - (a.pct || 0))

// the strip under an editor toolbar: the worst few meters, everything else in a popover
export function MeterStrip({ kind, data, go, n = 3, extra }) {
  const [allOpen, setAllOpen] = useState(() => new URLSearchParams(location.search).get('open') === 'meters')      // ?open=meters: screenshots
  const rows = relevant(data?.ledger?.rows, kind)
  if (!rows.length && !extra) return null
  const sorted = sortRows(rows)
  const top = sorted.slice(0, n)
  return (
    <div className="mstrip" role="group" aria-label={tr('limits')}>
      {top.map(r => <Meter key={r.id} r={r} onClick={() => jumpTo(r.items?.[0]?.jump || (r.jump ? { screen: r.jump } : null))} />)}
      <div style={{ flex: 1 }} />
      {extra}
      {rows.length > 0 && <Menu right open={allOpen} setOpen={setAllOpen} label={<>{tr('all')}{' '}{'▾'}</>} title={tr('all_limits_for_this_screen')} menuStyle={{ width: 360 }}>{close => <div>
        {sorted.map(r => <Meter key={r.id} r={r} />)}
        <div className="foot"><button className="sm" onClick={() => { close(); go('limits') }}>{tr('all_limits')}</button></div></div>}</Menu>}
    </div>
  )
}

// the one item in the status bar: the worst measured limit
export function WorstChip({ go }) {
  const st = useStore()
  // what the mods and this project add to the game (vanilla alone is not worth a status-bar item)
  const rows = Object.values(st.data).flatMap(d => d?.ledger?.rows || []).filter(r => r.status !== 'grey' && ((r.parts?.packages || 0) + (r.parts?.project || 0) > 0 || r.status === 'red'))
  if (!rows.length) return <span className="it click" title={tr('engine_and_format_limits')} onClick={() => go('limits')}><span className="dot" style={{ background: 'var(--ok)' }} /><span className="t3">{tr('limits')}</span>{' '}{tr('ok')}</span>
  const w = sortRows(rows)[0]
  return (
    <span className="it click" title={meterTip(w)} onClick={() => go('limits')}>
      <span className="dot" style={{ background: `var(--${w.status === 'red' ? 'bad' : w.status === 'amber' ? 'warn' : 'ok'})` }} /><span aria-hidden="true">{GLYPH[w.status]}</span>
      <span className="sr-only">{STATE_WORD[w.status]}</span><span className="t3">{short(w)}</span> <b>{w.pct != null ? Math.round(w.pct) + ' %' : ''}</b>
    </span>
  )
}

// ---------------------------------------------------------------- the full table (Play > Limits)
const conf = c => (String(c || '').toUpperCase().match(/MEASURED|INFERRED|UNKNOWN|POLICY/) || ['mixed'])[0]

export default function Limits() {
  const st = useStore()
  const [rows, setRows] = useState(null)
  const [mode, setMode] = useState('all')
  const [q, setQ] = useState('')
  const lv = st.live.level, ms = st.live.mission, nm = st.live.newmap
  useEffect(() => {
    let live = true
    const t = setTimeout(async () => {
      try {
        const [a, b, c] = await Promise.all([
          post('/api/ledger', { kind: 'level', project: lv?.project, id: lv?.id }),
          post('/api/ledger', { kind: 'mission', project: ms?.project, id: ms?.id }),
          post('/api/ledger', { kind: 'newmap', project: nm?.project, id: nm?.id })])
        if (!live) return
        const heavy = st.data.level?.ledger?.rows || []
        const by = Object.fromEntries(a.rows.map(r => [r.id, r]))
        const merged = a.rows.map(r => {
          if (r.kinds[0] === 'mission') return b.rows.find(x => x.id === r.id) || r
          if (r.kinds[0] === 'newmap') return c.rows.find(x => x.id === r.id) || r
          const h = heavy.find(x => x.id === r.id)
          return h && r.status === 'grey' && h.status !== 'grey' ? h : r
        })
        setRows(merged)
      } catch { if (live) setRows([]) }
    }, 100)
    return () => { live = false; clearTimeout(t) }
  }, [lv?.project, ms?.project, nm?.project, st.data.level])
  const shown = useMemo(() => (rows || []).filter(r => (mode === 'all' || (mode === 'measured' ? r.status !== 'grey' : r.status === 'grey'))
    && (!q || (r.label + ' ' + r.id + ' ' + r.scope).toLowerCase().includes(q.toLowerCase()))), [rows, mode, q])
  return (
    <div className="screen">
      <div className="tb">
        <Seg value={mode} onChange={setMode} options={[{ value: 'all', label: tr('all') }, { value: 'measured', label: tr('measured') }, { value: 'grey', label: tr('not_measured') }]} />
        <input style={{ width: 220 }} placeholder={tr('find_a_limit')} aria-label={tr('find_a_limit')} value={q} onChange={e => setQ(e.target.value)} />
        <div style={{ flex: 1 }} />
        <span className="muted small">{rows ? `${shown.length} of ${rows.length}` : ''}</span>
      </div>
      <div className="page" style={{ padding: 0 }}>
        <table className="ltable" aria-label={tr('limits')}>
          <thead><tr><th scope="col">{tr('limit')}</th><th scope="col">{tr('value')}</th><th scope="col" style={{ width: 230 }}>{tr('used')}</th><th scope="col">{tr('scope')}</th><th scope="col">{tr('confidence')}</th><th scope="col">{tr('source')}</th></tr></thead>
          <tbody>
            {!rows && <tr><td colSpan={6} className="muted">{tr('reading_the_limits')}{'…'}</td></tr>}
            {shown.map(r => (
              <tr key={r.id} className={'lrow ' + TONE[r.status]} title={meterTip(r)}>
                <td><span className="mg" aria-hidden="true">{GLYPH[r.status]}</span><b>{r.label}</b> <span className="muted mono">{r.id}</span><span className="sr-only"> {STATE_WORD[r.status]}</span></td>
                <td className="mono">{typeof r.value === 'number' ? fmt(r.value, r.unit) + (r.unit !== 'bytes' ? ' ' + r.unit : '') : <span className="clip" title={String(r.value)}>{String(r.value)}</span>}</td>
                <td>{r.max != null ? <Meter r={{ ...r, label: '', id: '' }} /> : <span className="muted">{r.reason || 'not measured'}</span>}</td>
                <td><span className="clip" title={r.scope}>{r.scope}</span></td>
                <td><span className={'cf ' + conf(r.confidence).toLowerCase()} title={r.confidence}>{conf(r.confidence).toLowerCase()}</span></td>
                <td><span className="clip" title={r.source}>{r.source}</span></td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
