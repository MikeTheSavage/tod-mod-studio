// Shared interface parts: icons, menus, switch, number fields with ranges, the pipeline bar, check rows, toast and dialog.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { rumble } from './pad/padstore.js'
import { t } from './i18n.js'

// ---------------------------------------------------------------- icons (small stroke set, 20px grid)
const PATHS = {
  home: 'M3 10.5 10 4l7 6.5M5 9v7h4v-4h2v4h4V9',
  world: 'M10 3 17 7v6l-7 4-7-4V7zM3 7l7 4 7-4M10 11v6',
  create: 'M10 4v12M4 10h12',
  tune: 'M4 6h12M4 10h12M4 14h12M7 4v4M13 8v4M9 12v4',
  play: 'M6 4l10 6-10 6z',
  assets: 'M4 4h5v5H4zM11 4h5v5h-5zM4 11h5v5H4zM11 11h5v5h-5z',
  settings: 'M10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM10 2v2.5M10 15.5V18M2 10h2.5M15.5 10H18M4.3 4.3l1.8 1.8M13.9 13.9l1.8 1.8M4.3 15.7l1.8-1.8M13.9 6.1l1.8-1.8',
  debug: 'M7 6.5a3 3 0 0 1 6 0M6 8.5h8v4a4 4 0 0 1-8 0zM3 9.5h3M14 9.5h3M3.5 14l2.5-1.5M16.5 14 14 12.5M10 8.5v8',
}
export function Icon({ name }) {
  return <svg viewBox="0 0 20 20" aria-hidden="true"><path d={PATHS[name] || PATHS.create} /></svg>
}

// ---------------------------------------------------------------- toast and dialog (one provider for the app)
const UIContext = createContext(null)
export const useUI = () => useContext(UIContext)

export function UIProvider({ children }) {
  const [toast, setToast] = useState(null)
  const [dialog, setDialog] = useState(null)
  const timer = useRef(null)
  const say = useCallback((text, tone = 'ok') => {
    clearTimeout(timer.current)
    if (tone === 'bad') rumble('bad')
    setToast({ text, tone })
    timer.current = setTimeout(() => setToast(null), tone === 'bad' ? 12000 : 7000)
  }, [])
  const confirm = useCallback(opts => new Promise(res => setDialog({ ...opts, res })), [])
  const close = v => { dialog?.res(v); setDialog(null) }
  useEffect(() => {
    if (!dialog) return
    const h = e => { if (e.key === 'Escape') { e.stopPropagation(); close(false) } }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [dialog])
  return (
    <UIContext.Provider value={{ say, confirm }}>
      {children}
      {toast && <div className={'toast ' + toast.tone} role="status"><span className="ic">{toast.tone === 'bad' ? '!' : '✓'}</span><span style={{ overflowWrap: 'anywhere' }}>{toast.text}</span>
        <button className="sm" onClick={() => setToast(null)}>{t('dismiss')}</button></div>}
      {dialog && <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) close(false) }}>
        <div className="dialog" role="alertdialog" aria-label={dialog.title}>
          <div className="dt">{dialog.title}</div>
          {dialog.body && <div className="dd">{dialog.body}</div>}
          {dialog.kept && <div className="kept">{dialog.kept}</div>}
          <div className="da">
            <button autoFocus onClick={() => close(false)}>{dialog.cancel || 'Cancel'}</button>
            <button className={dialog.danger === false ? 'primary' : 'dangerfill'} onClick={() => close(true)}>{dialog.ok || 'Remove'}</button>
          </div>
        </div>
      </div>}
    </UIContext.Provider>
  )
}

// ---------------------------------------------------------------- menu (button with a popover)
export function Menu({ label, className = '', buttonClass = '', title, right, children, open: openProp, setOpen: setOpenProp, disabled, menuStyle }) {
  const [openLocal, setOpenLocal] = useState(false)
  const open = openProp ?? openLocal, setOpen = setOpenProp ?? setOpenLocal
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const down = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const key = e => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', down)
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key) }
  }, [open])
  return (
    <div className={'menuwrap ' + className} ref={ref}>
      <button className={buttonClass} title={title} aria-label={typeof label !== 'string' && title ? title : undefined} disabled={disabled} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>{label}</button>
      {open && <div className={'menu' + (right ? ' right' : '')} role="menu" style={menuStyle}>{typeof children === 'function' ? children(() => setOpen(false)) : children}</div>}
    </div>
  )
}

export const Seg = ({ value, options, onChange, large, label, padFirst }) => (
  <div className={'seg' + (large ? ' lg' : '')} role="tablist" aria-label={label} data-pad-first={padFirst ? "1" : undefined}>
    {options.map(o => <button key={o.value} role="tab" aria-selected={value === o.value} className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}
      title={o.title}>{o.label}{o.key && <span className="key">{o.key}</span>}</button>)}
  </div>
)

export const Switch = ({ on, onChange, label, disabled }) => (
  <button type="button" role="switch" aria-checked={!!on} aria-label={label} disabled={disabled} className={'switch' + (on ? ' on' : '')} onClick={() => onChange(!on)} />
)

export function Advanced({ title = 'Advanced', note, children, open }) {
  return <details className="adv" open={open}><summary><b>{title}</b>{note && <span className="n">{note}</span>}</summary><div className="inner">{children}</div></details>
}

// ---------------------------------------------------------------- number field, with an optional slider and "use the default"
const fmt = (v, digits = 3) => v == null || v === '' || Number.isNaN(v) ? '' : String(Math.round(Number(v) * 10 ** digits) / 10 ** digits)

export function NumField({ value, onCommit, digits = 3, unit, changed, nullable, placeholder, label, ...rest }) {
  const [v, setV] = useState(fmt(value, digits))
  const [dirty, setDirty] = useState(false)
  useEffect(() => { setV(fmt(value, digits)); setDirty(false) }, [value])
  return (
    <div className={'numfield' + (changed ? ' changed' : '')}>
      <input aria-label={label} value={v} placeholder={placeholder} onChange={e => { setV(e.target.value); setDirty(true) }} onFocus={e => e.target.select()}
        onBlur={() => {
          if (!dirty) return
          if (v.trim() === '') { if (nullable) onCommit(null); else setV(fmt(value, digits)); setDirty(false); return }
          const n = parseFloat(v); if (!isNaN(n)) onCommit(n); else setV(fmt(value, digits)); setDirty(false)
        }}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} {...rest} />
      {unit && <span className="u">{unit}</span>}
    </div>
  )
}

// A value with a known range: slider plus number, and the "Use the default (x)" link when it differs.
export function RangeField({ label, help, tip, value, min, max, step, def, unit, onChange, onReset, digits = 3, changed }) {
  const has = min != null && max != null && max > min
  const v = value == null ? (def ?? min ?? 0) : value
  const pct = has ? Math.max(0, Math.min(100, (v - min) / (max - min) * 100)) : 0
  const diff = changed ?? (def != null && value != null && Math.abs(value - def) > 1e-9)
  return (
    <div>
      <div className="fieldhead" title={[tip, help].filter(Boolean).join(': ') || undefined}><span className="l">{label}</span>
        {diff && onReset ? <span className="d chg" role="button" tabIndex={0} onClick={onReset} onKeyDown={e => e.key === 'Enter' && onReset()}>{t('use_the_default_e42e03')}{fmt(def, digits)}{unit ? ' ' + unit : ''})</span> : <span className="d">{t('default')}</span>}</div>
      <div className="slidefield">
        <div className="rng">
          {has && <input type="range" aria-label={label + ' slider'} min={min} max={max} step={step ?? 'any'} value={v} onChange={e => onChange(Number(e.target.value))}
            style={{ background: `linear-gradient(to right, var(--accent) ${pct}%, var(--surface-3) ${pct}%)`, height: 4, borderRadius: 2, appearance: 'none', width: '100%', margin: '6px 0' }} />}
          {has && <div className="ends"><span>{fmt(min, digits)}{unit ? ' ' + unit : ''}</span><span>{fmt(max, digits)}{unit ? ' ' + unit : ''}</span></div>}
        </div>
        <div style={{ gridColumn: has ? undefined : '1 / -1' }}><NumField value={value ?? (def ?? '')} onCommit={n => onChange(n)} unit={unit} digits={digits} changed={diff} label={label} /></div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- pipeline: Check, Build, Install (or Remove) in one bar
const TONE = { ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)', busy: 'var(--accent-text)', ready: 'var(--accent-text)', idle: 'var(--text-3)' }
const MARK = { ok: '✓', warn: '!', bad: '×' }
export function Pipeline({ steps, removeLabel = 'Remove from the game', onRemove, removeDisabled, trailing }) {
  return (
    <div className="pipe" role="group" aria-label={t('into_the_game')}>
      <div className="lab">{t('into_the_game')}</div>
      {steps.map((s, i) => {
        const filled = s.tone === 'ok' || s.tone === 'bad' || s.tone === 'warn'
        const primary = s.tone === 'ready'
        return (
          <React.Fragment key={s.label}>
            <div className={'st t-' + s.tone}>
              <div className="mk" style={{ color: filled ? 'var(--bg)' : TONE[s.tone], background: filled ? TONE[s.tone] : 'transparent', borderColor: TONE[s.tone] }}>{MARK[s.tone] ?? String(i + 1)}</div>
              <div className="tx"><div className="l1" title={s.label}>{s.label}</div><div className="l2" style={{ color: TONE[s.tone] }} title={s.note}>{s.note}</div></div>
              {s.tone === 'busy' && <div className="pb"><i style={{ width: (s.pct ?? 0) + '%' }} /></div>}
              {s.action && <button className={primary ? 'primary' : ''} disabled={s.disabled} onClick={s.onClick}>{s.action}</button>}
            </div>
            {i < steps.length - 1 && <div className="arrow">{'›'}</div>}
          </React.Fragment>)
      })}
      {trailing && <><div className="vsep" />{trailing}</>}
      {onRemove && <><div className="vsep" /><button className="rm" disabled={removeDisabled} onClick={onRemove}>{removeLabel}</button></>}
    </div>
  )
}

// One check result: a tag, a plain sentence and (maybe) one button.
export function CheckRow({ tone, title, fix, action, onAction, onClick }) {
  const tag = { bad: 'FIX', warn: 'WARN', ok: 'PASS', info: 'NOTE' }[tone] || 'NOTE'
  return (
    <div className={'checkrow' + (onClick ? ' click' : '')} onClick={onClick}>
      <span className={'tg ' + tone}>{tag}</span>
      <span className="tx"><b>{title}</b> {fix && <span>{fix}</span>}</span>
      {action && <button className="sm" onClick={e => { e.stopPropagation(); onAction?.() }}>{action}</button>}
    </div>
  )
}

// "N values changed in <mod>. They reach the game when you install the mod."
export function UndoRedo({ h, compact }) {
  return <span className="undoredo">
    <button className="sm" onClick={h.undo} disabled={!h.canUndo} title={t('undo_ctrl_z')} aria-label={t('undo')}><span className="ic">{'↶'}</span>{!compact && <span className="mt-wide">{' '}{t('undo')}</span>}</button>
    <button className="sm" onClick={h.redo} disabled={!h.canRedo} title={t('redo_ctrl_y')} aria-label={t('redo')}><span className="ic">{'↷'}</span>{!compact && <span className="mt-wide">{' '}{t('redo')}</span>}</button>
  </span>
}

export function ChangeBar({ count, name, one = 'change', many = 'changes', go }) {
  if (!count) return null
  return (
    <div className="changebar"><span className="dot" style={{ background: 'var(--accent)' }} />
      <span><b style={{ fontWeight: 600 }}>{count} {count === 1 ? one : many}</b> <span style={{ color: 'var(--text-2)' }}>{t('in')}{' '}{name}</span></span>
      <span style={{ flex: 1 }} /><button onClick={go}>{t('go_to_mods_and_install')}{' '}{'›'}</button></div>
  )
}
