import React, { useEffect, useState } from 'react'
import { get } from './api.js'

const EDITORS = [['weapons', 'Weapons'], ['vehicles', 'Vehicles'], ['loco', 'Loco moves and slow motion'], ['camera', 'Camera']]

export default function DataEditors({ project, commit }) {
  const [ed, setEd] = useState('weapons')
  const [data, setData] = useState({})
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('')
  useEffect(() => {
    if (data[ed]) return
    setErr(null)
    get('/api/data/' + ed).then(d => setData(x => ({ ...x, [ed]: d }))).catch(e => setErr(e.message))
  }, [ed])
  const vals = (project.data || {})[ed] || {}
  const setVal = (key, v, orig) => {
    const cur = { ...vals }
    if (v === '' || v == null || (typeof orig === 'number' && Math.abs(v - orig) < 1e-9) || v === orig) delete cur[key]
    else cur[key] = v
    const data2 = { ...(project.data || {}), [ed]: cur }
    if (!Object.keys(cur).length) delete data2[ed]
    commit({ ...project, data: data2 })
  }
  const d = data[ed]
  const f = filter.toLowerCase()
  return (
    <div className="page data">
      <div className="tabbar big">
        {EDITORS.map(([k, l]) => <button key={k} className={ed === k ? 'on' : ''} onClick={() => setEd(k)}>
          {l}{(project.data || {})[k] ? ` (${Object.keys(project.data[k]).length})` : ''}</button>)}
        <input placeholder="Filter" value={filter} onChange={e => setFilter(e.target.value)} />
      </div>
      {err && <p className="bad">{err}</p>}
      {!d && !err && <p className="muted">Reading the values from your game...</p>}
      {d && <>
        <p className="muted">{d.note} Changed values are part of the current mod and are built together with its level edits.</p>
        <div className="groups">
          {d.groups.map(g => {
            const fields = g.fields.filter(x => !f || (g.group + ' ' + x.label + ' ' + x.key).toLowerCase().includes(f))
            if (!fields.length) return null
            return (
              <section key={g.group} className="box">
                <h4>{g.group}</h4>
                <table><tbody>{fields.map(x => {
                  const changed = x.key in vals
                  const v = changed ? vals[x.key] : x.value
                  return (
                    <tr key={x.key} className={changed ? 'changed' : ''} title={x.help || ''}>
                      <td>{x.label}{x.source === 'code default' && <i> default</i>}</td>
                      <td>{typeof x.value === 'boolean'
                        ? <input type="checkbox" checked={!!v} onChange={e => setVal(x.key, e.target.checked, x.value)} />
                        : <NumField value={v} onCommit={n => setVal(x.key, n, x.value)} />}</td>
                      <td>{changed && <button className="link" onClick={() => setVal(x.key, null, x.value)}>reset</button>}</td>
                    </tr>)
                })}</tbody></table>
              </section>)
          })}
        </div>
        {d.code_only?.length > 0 && <p className="muted">Not editable here (code constants, need a proxy DLL):
          {' '}{d.code_only.slice(0, 20).map(c => c.key).join(', ')}{d.code_only.length > 20 ? ' ...' : ''}</p>}
      </>}
    </div>
  )
}

const show = v => (typeof v === 'number' && !Number.isInteger(v)) ? String(Number(v.toPrecision(6))) : (v == null ? '' : String(v))

function NumField({ value, onCommit }) {
  const [v, setV] = useState(show(value))
  const [dirty, setDirty] = useState(false)
  useEffect(() => { setV(show(value)); setDirty(false) }, [value])
  return <input className="num" value={v} onChange={e => { setV(e.target.value); setDirty(true) }} onFocus={e => e.target.select()}
    onBlur={() => { if (!dirty || v === '') return; const n = Number(v); if (!isNaN(n)) onCommit(n); setDirty(false) }}
    onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} />
}
