import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { get } from './api.js'
import { Seg, Switch, RangeField, ChangeBar } from './ui.jsx'
import { nice } from './labels.js'
import { WeaponPreview, VehiclePreview, MovesPreview, CameraPreview } from './tune/Previews.jsx'
import './tune/tune.css'
import { t } from './i18n.js'

// the playground (and its physics engine) is only fetched when it is opened
const Playground = lazy(() => import('./tune/Playground.jsx'))

const NONE = {}
function useWide() {
  const q = '(min-width: 1280px)'
  const [w, setW] = useState(() => typeof matchMedia === 'undefined' || matchMedia(q).matches)
  useEffect(() => { const m = matchMedia(q), f = () => setW(m.matches); m.addEventListener('change', f); return () => m.removeEventListener('change', f) }, [])
  return w
}

const EDITORS = [['weapons', 'Weapons', 'weapon'], ['vehicles', 'Vehicles', 'vehicle'], ['loco', 'Moves and slow motion', 'move or setting'], ['camera', 'Camera', 'camera setting']]
const show = v => (typeof v === 'number' && !Number.isInteger(v)) ? String(Number(v.toPrecision(6))) : (v == null ? '' : String(v))
const tidy = g => g.replace(/^Vehicle type: /, '').replace(/^Camera type /, '')
const plain = g => tidy(g).replace(/\s*\([^)]*\)\s*$/, '')

// A table cell that is committed when it loses focus.
function Cell({ value, was, changed, onCommit, label }) {
  const [v, setV] = useState(show(value))
  const [dirty, setDirty] = useState(false)
  useEffect(() => { setV(show(value)); setDirty(false) }, [value])
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', width: '100%' }}>
      {changed && <span className="was">{show(was)}</span>}
      <input className={'cell' + (changed ? ' chg' : '')} aria-label={label} value={v} onChange={e => { setV(e.target.value); setDirty(true) }} onFocus={e => e.target.select()}
        onBlur={() => { if (!dirty) return; setDirty(false); if (v === '') { onCommit(null); return } const n = Number(v); if (!isNaN(n)) onCommit(n); else setV(show(value)) }}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} style={{ maxWidth: 96 }} />
    </div>
  )
}

export default function DataEditors({ project, commit, go }) {
  const [ed, setEd] = useState(() => { const v = new URLSearchParams(location.search).get('ed'); return v === 'playground' || EDITORS.some(x => x[0] === v) ? v : 'weapons' })
  const [data, setData] = useState({})
  const wide = useWide()
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('')
  const [onlyChanged, setOnlyChanged] = useState(false)
  const [selRow, setSelRow] = useState(null)
  useEffect(() => {
    const want = ed === 'playground' ? EDITORS.map(x => x[0]) : [ed]
    want.filter(k => !data[k]).forEach(k => {
      setErr(null)
      get('/api/data/' + k).then(d => setData(x => ({ ...x, [k]: d }))).catch(e => setErr(e.message))
    })
  }, [ed])
  useEffect(() => setSelRow(null), [ed])
  const vals = (project.data || {})[ed] || NONE
  const setVal = (key, v, orig) => {
    const cur = { ...vals }
    if (v === '' || v == null || (typeof orig === 'number' && Math.abs(v - orig) < 1e-9) || v === orig) delete cur[key]
    else cur[key] = v
    const data2 = { ...(project.data || {}), [ed]: cur }
    if (!Object.keys(cur).length) delete data2[ed]
    commit({ ...project, data: data2 })
  }
  const total = Object.values(project.data || {}).reduce((a, v) => a + Object.keys(v).length, 0)
  const d = data[ed]
  const f = filter.toLowerCase()
  const noun = (EDITORS.find(x => x[0] === ed) || [0, 0, 'weapon'])[2]
  // tables need every row to carry the same columns (weapons, vehicles)
  const labelsOf = g => g.fields.map(x => x.label)
  const table = useMemo(() => {
    if (!d || (ed !== 'weapons' && ed !== 'vehicles')) return null
    const seen = []
    d.groups.forEach(g => labelsOf(g).forEach(l => { if (!seen.includes(l)) seen.push(l) }))
    return seen
  }, [d, ed])
  const rangeOf = (label, def) => {
    if (!d || !table) return {}
    const all = d.groups.map(g => g.fields.find(x => x.label === label)?.value).filter(v => typeof v === 'number')
    if (!all.length) return {}
    const lo = Math.min(0, ...all), hi = Math.max(...all) * 1.5 || 1
    return { min: lo, max: Math.max(hi, def ?? 0) }
  }
  const changedIn = g => g.fields.filter(x => x.key in vals).length

  const rows = d ? d.groups.filter(g => (!f || tidy(g.group).toLowerCase().includes(f) || (!table && g.fields.some(x => (x.label + x.key).toLowerCase().includes(f)))) && (!onlyChanged || changedIn(g) > 0)) : []
  const sel = table && d ? d.groups.find(g => g.group === (selRow || (rows[0] && rows[0].group))) : null
  const cols = table ? `minmax(170px, 1.4fr) repeat(${table.length}, minmax(96px, 1fr))` : ''
  const [picked, setPicked] = useState({})
  useEffect(() => { if (sel && table) setPicked(p => (p[ed] === sel.group ? p : { ...p, [ed]: sel.group })) }, [sel && sel.group, ed])
  const pv = !d || ed === 'playground' ? null : (
    <div className="pvbox">
      {ed === 'weapons' && sel && <WeaponPreview d={d} vals={vals} group={sel.group} />}
      {ed === 'vehicles' && sel && <VehiclePreview d={d} vals={vals} group={sel.group} />}
      {ed === 'loco' && <MovesPreview d={d} vals={vals} />}
      {ed === 'camera' && <CameraPreview d={d} vals={vals} />}
    </div>)

  return (
    <div className="screen">
      <div className="tb">
        <Seg large value={ed} onChange={setEd} options={EDITORS.map(([k, l]) => ({ value: k, label: l + ((project.data || {})[k] ? ` (${Object.keys(project.data[k]).length})` : '') }))} />
        <button className={'sm' + (ed === 'playground' ? ' primary' : '')} onClick={() => setEd('playground')} title={t('try_weapons_cars_and_the_camera')}>{t('playground')}</button>
        <div style={{ flex: 1 }} />
        {ed !== 'playground' && <>
          <input style={{ width: 180 }} placeholder={`Find a ${noun}…`} aria-label={t('find')} value={filter} onChange={e => setFilter(e.target.value)} />
          <label className="check" style={{ margin: 0, fontSize: 12.5 }}><Switch label={t('only_changed')} on={onlyChanged} onChange={setOnlyChanged} />{' '}{t('only_changed')}</label></>}
      </div>
      {ed === 'playground' ? (
        <Suspense fallback={<div className="empty">{t('loading')}{'…'}</div>}>
          {EDITORS.every(x => data[x[0]]) ? <Playground data={data} vals={project.data || NONE} pick={picked} onBack={() => setEd('weapons')} /> : <div className="empty">{t('reading_the_values_from_your_game')}{'…'}</div>}
        </Suspense>
      ) : (
      <div className="split">
        <div className="col"><div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
          {err && <p className="bad" style={{ padding: 16 }}>{err}</p>}
          {!d && !err && <div className="empty">{t('reading_the_values_from_your_game')}{'…'}</div>}
          {d && table && <div className="gd" role="table" aria-label={ed === 'weapons' ? 'Weapons' : 'Vehicles'} aria-rowcount={rows.length + 1} style={{ gridTemplateColumns: cols, minWidth: 'max-content' }}>
            <div role="row" style={{ display: 'contents' }}>
            <div className="c h" role="columnheader" style={{ borderRight: '1px solid var(--line)', left: 0, zIndex: 3 }}>{ed === 'weapons' ? 'Weapon' : 'Vehicle'}</div>
            {table.map(l => <div key={l} className="c h r" role="columnheader" title={l}>{nice(l)}</div>)}
            </div>
            {rows.map(g => {
              const on = sel && sel.group === g.group
              return <div role="row" aria-selected={on ? 'true' : undefined} style={{ display: 'contents' }} key={g.group}>
                <div className={'c nm' + (on ? ' row-sel' : '')} role="rowheader" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelRow(g.group) } }} onClick={() => setSelRow(g.group)} style={{ position: 'sticky', left: 0, background: on ? 'var(--sel-soft)' : 'var(--bg)', boxShadow: on ? 'inset 3px 0 0 var(--sel)' : 'none' }}>
                  <span title={tidy(g.group)}>{plain(g.group)}</span>{changedIn(g) > 0 && <span style={{ fontSize: 11, color: 'var(--accent-text)' }}>{changedIn(g)}{' '}{t('changed')}</span>}</div>
                {table.map(label => {
                  const x = g.fields.find(f => f.label === label)
                  if (!x) return <div key={label} role="cell" className={'c r' + (on ? ' row-sel' : '')} />
                  const changed = x.key in vals
                  return <div key={x.key} role="cell" className={'c r' + (on ? ' row-sel' : '')} title={x.label} onClick={() => setSelRow(g.group)}>
                    {typeof x.value === 'boolean'
                      ? <input type="checkbox" aria-label={nice(x.label)} checked={!!(changed ? vals[x.key] : x.value)} onChange={e => setVal(x.key, e.target.checked, x.value)} />
                      : <Cell label={`${tidy(g.group)} ${nice(x.label)}`} value={changed ? vals[x.key] : x.value} was={x.value} changed={changed} onCommit={n => setVal(x.key, n, x.value)} />}
                  </div>
                })}
              </div>
            })}
          </div>}
          {d && !table && <div style={{ padding: '0 12px 16px', display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
            {rows.map(g => {
              const fields = g.fields.filter(x => (!f || (g.group + ' ' + x.label + ' ' + x.key).toLowerCase().includes(f)) && (!onlyChanged || x.key in vals))
              if (!fields.length) return null
              return (
                <section key={g.group} className="card sm" style={{ gap: 4 }}>
                  <h3 style={{ marginBottom: 4 }}>{g.group}</h3>
                  {fields.map(x => {
                    const changed = x.key in vals
                    const v = changed ? vals[x.key] : x.value
                    return typeof x.value === 'boolean'
                      ? <label key={x.key} className="check" title={x.label}><Switch label={nice(x.label)} on={!!v} onChange={b => setVal(x.key, b, x.value)} /> <span>{nice(x.label)}</span>
                        {changed && <button className="link" onClick={() => setVal(x.key, null, x.value)}>{t('use_the_default')}</button>}</label>
                      : <div key={x.key} style={{ margin: '4px 0' }} title={x.label}>
                        <RangeField label={nice(x.label)} value={v} def={x.value} changed={changed} digits={6}
                          onChange={n => setVal(x.key, n, x.value)} onReset={() => setVal(x.key, null, x.value)} />
                      </div>
                  })}
                </section>)
            })}
            {!rows.length && <div className="muted" style={{ padding: 8 }}>{t('nothing_matches')}</div>}
          </div>}
          {d && table && !rows.length && <div className="muted" style={{ padding: 16 }}>{onlyChanged ? 'No values changed here yet' : 'Nothing matches'}</div>}
        </div>
          {!wide && pv && <div className="pvdock">{pv}</div>}
        </div>
        {wide && d && !table && <div className="panel-r pvp only">{pv}</div>}
        {wide && d && table && sel && <div className="panel-r pvp">
          {pv}
          <div className="panel-h"><div className="grow"><div className="t" title={tidy(sel.group)} style={{ fontWeight: 600 }}>{plain(sel.group)}</div>
            <div className="s" style={{ fontSize: 11.5, color: changedIn(sel) ? 'var(--accent-text)' : 'var(--text-3)' }}>{changedIn(sel) ? `${changedIn(sel)} value${changedIn(sel) === 1 ? '' : 's'} changed` : ''}</div></div>
            <button className="sm" disabled={!changedIn(sel)} onClick={() => {
              const cur = { ...vals }; sel.fields.forEach(x => delete cur[x.key])
              const data2 = { ...(project.data || {}), [ed]: cur }; if (!Object.keys(cur).length) delete data2[ed]
              commit({ ...project, data: data2 })
            }}>{t('reset_all')}</button></div>
          <div className="panel-b" style={{ gap: 14 }}>
            {sel.fields.filter(x => typeof x.value !== 'boolean').map(x => {
              const changed = x.key in vals, v = changed ? vals[x.key] : x.value
              const r = typeof x.value === 'number' ? rangeOf(x.label, x.value) : {}
              return <RangeField key={x.key} label={nice(x.label)} tip={x.label} value={v} def={x.value} changed={changed} min={r.min} max={r.max} digits={6}
                step={Number.isInteger(x.value) ? 1 : undefined} onChange={n => setVal(x.key, n, x.value)} onReset={() => setVal(x.key, null, x.value)} />
            })}
            {sel.fields.filter(x => typeof x.value === 'boolean').map(x => <label key={x.key} className="check" title={x.label}><Switch label={nice(x.label)} on={!!(x.key in vals ? vals[x.key] : x.value)} onChange={b => setVal(x.key, b, x.value)} /> {nice(x.label)}</label>)}
          </div>
        </div>}
      </div>)}
      <ChangeBar count={total} one="value changed" many="values changed" name={project.name} go={() => go('mods')} />
    </div>
  )
}
