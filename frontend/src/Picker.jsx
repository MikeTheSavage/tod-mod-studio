// A searchable choice: the current name on a button, a list below it. Typing narrows by readable name OR by the number / file name kept in `id` and `tip`.
import React, { useEffect, useMemo, useRef, useState } from 'react'

export default function Picker({ value, options, onChange, label, disabled, width, placeholder = 'Search', noneLabel, thumb }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const down = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const key = e => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', down); window.addEventListener('keydown', key)
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key) }
  }, [open])
  const cur = options.find(o => String(o.id) === String(value))
  const list = useMemo(() => {
    const s = q.trim().toLowerCase()
    return options.filter(o => !s || (o.name + ' ' + o.id + ' ' + (o.tip || '') + ' ' + (o.group || '')).toLowerCase().includes(s))
  }, [options, q])
  const groups = []
  for (const o of list) {
    const g = o.group || ''
    if (!groups.length || groups[groups.length - 1][0] !== g) groups.push([g, []])
    groups[groups.length - 1][1].push(o)
  }
  return (
    <div className="menuwrap pick" ref={ref} style={{ display: 'block', width: width || '100%' }}>
      <button type="button" className="pickbtn" aria-label={label} aria-haspopup="listbox" aria-expanded={open} disabled={disabled} title={cur ? (cur.tip || String(cur.id)) : ''}
        onClick={() => { setOpen(!open); setQ('') }}>
        {thumb && cur && thumb(cur)}<span className="nm">{cur ? cur.name : (noneLabel ?? String(value ?? ''))}</span><span className="car">▾</span>
      </button>
      {open && <div className="menu" role="listbox" style={{ top: 32, minWidth: 240 }}>
        <input className="find" autoFocus value={q} placeholder={placeholder} aria-label={label ? label + ' search' : 'Search'} onChange={e => setQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && list.length) { onChange(list[0].id); setOpen(false) } }} />
        {!list.length && <div className="foot">—</div>}
        {groups.map(([g, os]) => <React.Fragment key={g}>
          {g && <div className="grp">{g}</div>}
          {os.map(o => <div key={o.id} role="option" aria-selected={String(o.id) === String(value)} title={o.tip || String(o.id)}
            className={'item' + (String(o.id) === String(value) ? ' on' : '')} onClick={() => { onChange(o.id); setOpen(false) }}>
            {thumb && thumb(o)}<span>{o.name}</span>{o.hint && <span className="hint">{o.hint}</span>}</div>)}
        </React.Fragment>)}
      </div>}
    </div>
  )
}
