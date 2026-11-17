// Small controls shared by the building tools (same look as the rest of the app: tokens from styles.css, classes in mapbuild.css).
import React, { useEffect, useRef, useState } from 'react'
import { NumField } from '../ui.jsx'
import { t } from '../i18n.js'

// a labelled slider with its number. onChange = the final value (one commit: when the slider is let go or a number is typed);
// onLive = every step while dragging (for a preview that is not saved)
export function Sld({ label, value, min, max, step = 1, unit, onChange, onLive, tip, digits = 2 }) {
  const [local, setLocal] = useState(null)
  const v = local ?? value ?? min
  const pct = Math.max(0, Math.min(100, (v - min) / (max - min) * 100))
  const done = () => { if (local != null) { const f = local; setLocal(null); if (f !== value) onChange(f) } }
  return <div className="mb-row" title={tip}>
    <span className="k">{label}</span>
    <input type="range" aria-label={label} min={min} max={max} step={step} value={v}
      onChange={e => { const n = Number(e.target.value); setLocal(n); onLive?.(n) }} onPointerUp={done} onKeyUp={done} onBlur={done}
      style={{ background: `linear-gradient(to right, var(--accent) ${pct}%, var(--surface-3) ${pct}%)` }} />
    <NumField value={v} onCommit={n => { setLocal(null); onChange(Math.min(max * 10, Math.max(min, n))) }} unit={unit} digits={digits} label={label + ' number'} />
  </div>
}

export function Num({ label, value, onChange, unit, tip, digits = 2, nullable, placeholder }) {
  return <div className="mb-row two" title={tip}>
    <span className="k">{label}</span>
    <NumField value={value} onCommit={onChange} unit={unit} digits={digits} label={label} nullable={nullable} placeholder={placeholder} />
  </div>
}

export function Pick({ label, value, options, onChange, tip }) {
  return <div className="mb-row two" title={tip}>
    <span className="k">{label}</span>
    <select aria-label={label} value={value ?? ''} onChange={e => onChange(e.target.value)}>{options.map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}</select>
  </div>
}

export function Check({ label, on, onChange, tip, disabled }) {
  return <label className="mb-check" title={tip}><input type="checkbox" checked={!!on} disabled={disabled} onChange={e => onChange(e.target.checked)} /><span>{label}</span></label>
}

// a row of buttons, one of them on (a shape as well as colour: the checked one carries a tick)
export function Chips({ value, options, onChange, label }) {
  return <div className="mb-chips" role="radiogroup" aria-label={label}>
    {options.map(o => <button key={o.value} role="radio" aria-checked={value === o.value} className={value === o.value ? 'on' : ''} title={o.tip}
      onClick={() => onChange(o.value)}>{value === o.value ? '✓ ' : ''}{o.label}</button>)}
  </div>
}

export function Toggle({ label, children, className = '', open: o0 = false }) {
  const [open, setOpen] = useState(o0)
  return <div className={'mb-toggle ' + className}><button className="sm" aria-expanded={open} onClick={() => setOpen(!open)}>{label}{open ? ' ▴' : ' ▾'}</button>{open && <div className="mb-pop">{children}</div>}</div>
}

export function Head({ children }) { return <div className="mb-head">{children}</div> }

// a list of recipe entries: pick one, delete one
export function List({ items, sel, onSel, onDelete, name, extra }) {
  return <div className="mb-list" role="listbox" aria-label={t('list')}>
    {items.map((it, i) => <div key={it.id ?? i} role="option" aria-selected={sel === i} tabIndex={0} className={'mb-li' + (sel === i ? ' on' : '')}
      onClick={() => onSel(i)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSel(i) } else if (e.key === 'Delete') onDelete?.(i) }}>
      <span className="nm">{name(it, i)}</span><span className="ty">{extra?.(it, i)}</span>
      {onDelete && <button className="link" aria-label={t('delete_item', { name: name(it, i) })} onClick={e => { e.stopPropagation(); onDelete(i) }}>{t('delete')}</button>}
    </div>)}
  </div>
}

// download a file the tool made (heightmap, minimap picture)
export function saveBlob(name, bytes, type = 'application/octet-stream') {
  const url = URL.createObjectURL(new Blob([bytes], { type }))
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

// a colour picker that saves once, when the picker closes (the browser's own change event), not on every drag inside it
export function ColorField({ label, value, onChange }) {
  const ref = useRef(null)
  const cb = useRef(onChange); cb.current = onChange
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const f = () => cb.current(el.value)
    el.addEventListener('change', f)
    return () => el.removeEventListener('change', f)
  }, [])
  useEffect(() => { if (ref.current) ref.current.value = value }, [value])
  return <input ref={ref} type="color" aria-label={label} defaultValue={value} />
}
