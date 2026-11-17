// Mounted once in the app: starts the controller, turns presses into the shared focus model (move, press, back, tabs, areas,
// search, problems, undo and redo), draws the focus chip, the on-screen keyboard and the choice list, and the hint strip.
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { startPad, onAction, onTick, usePad, setUi, rumble, getMode } from './padstore.js'
import * as L from './padlogic.js'
import * as D from './dom.js'
import { getStore, setOpen as setProblemsOpen } from '../problemsStore.js'
import { t as tr } from '../i18n.js'

// 3D views register themselves here: the element that takes focus -> a function that gets presses and d-pad steps
const views = new Map()
export function registerView(el, fn) { views.set(el, fn); return () => { if (views.get(el) === fn) views.delete(el) } }

const key = (k, extra) => window.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...extra }))

function distance(el, a) {
  const r = el.getBoundingClientRect(), b = a && a !== document.body ? a.getBoundingClientRect() : { left: innerWidth / 2, top: innerHeight / 2, width: 0, height: 0 }
  return Math.hypot(r.left + r.width / 2 - (b.left + b.width / 2), r.top + r.height / 2 - (b.top + b.height / 2))
}
function switchTab(delta) {
  const a = document.activeElement
  const lists = [...document.querySelectorAll('[role=tablist]')].filter(D.isShown)
  const own = a?.closest?.('[role=tablist]')
  // a screen can name the tab row that LB / RB change when focus is not inside another one (the New maps area row)
  const list = own || lists.find(l => l.dataset.padFirst) || lists.sort((p, q) => distance(p, a) - distance(q, a))[0]
  if (!list) return false
  const tabs = [...list.querySelectorAll('[role=tab]')].filter(t => !t.disabled)
  if (tabs.length < 2) return false
  const i = Math.max(0, tabs.findIndex(t => t.getAttribute('aria-selected') === 'true'))
  const next = tabs[(i + delta + tabs.length) % tabs.length]
  next.click()
  if (own) setTimeout(() => D.focusEl(next), 0)
  return true
}
function switchArea(delta) {
  const btns = [...document.querySelectorAll('nav.rail button')]
  if (btns.length < 2) return false
  const i = Math.max(0, btns.findIndex(b => b.getAttribute('aria-current') === 'page'))
  const next = btns[(i + delta + btns.length) % btns.length]
  next.click()
  setTimeout(() => D.focusEl(next), 0)
  return true
}
function toggleProblems() {
  const open = getStore().open
  setProblemsOpen(!open)
  if (!open) setTimeout(() => D.enterScope(document.querySelector('aside.problems')), 120)
}
function leaveView() {
  const el = document.activeElement
  el?.blur?.()
  const near = D.candidates(D.modalRoot()).filter(c => !el.contains(c.el) && !c.el.disabled).sort((p, q) => distance(p.el, el) - distance(q.el, el))[0]
  if (near) D.focusEl(near.el)
}
function goBack() {
  if (D.hasScope()) { D.pressEscape(); return }
  const a = document.activeElement
  if (D.isText(a)) { a.blur(); return }
  const cur = document.querySelector('nav.rail button[aria-current=page]')
  if (cur && cur.getAttribute('aria-label') !== 'Home') document.querySelector('.topbar .logo')?.click()
}

export default function PadHost() {
  const [osk, setOsk] = useState(null)         // the text control being typed into
  const [pick, setPick] = useState(null)       // the <select> being chosen from
  const oskApi = useRef(null)
  const pickApi = useRef(null)
  const modal = useRef({ osk: null, pick: null })
  modal.current = { osk, pick }

  useEffect(() => { startPad(); return D.installKeyNav() }, [])

  const openOsk = useCallback(el => { setOsk(el) }, [])

  useEffect(() => {
    const press = a => {
      const m = modal.current
      if (m.osk) return oskApi.current?.press(a) ?? true
      if (m.pick) return pickApi.current?.press(a) ?? true
      if (a.chord) { key(a.action === 'undo' ? 'z' : 'y', { ctrlKey: true }); return true }
      const ctx = D.contextOf()
      const act = document.activeElement
      if (ctx === 'view') {
        const v = views.get(act)
        if (v && v(a)) return true
        if (a.name === 'B') { leaveView(); return true }
      }
      if (ctx === 'play') {
        if (a.name === 'B') { leaveView(); return true }
        if (a.name !== 'START' && a.name !== 'VIEW') return true
      }
      switch (a.name) {
        case 'START': key('k', { ctrlKey: true }); return true
        case 'VIEW': toggleProblems(); return true
        case 'LB': return switchTab(-1)
        case 'RB': return switchTab(1)
        case 'LT': if (ctx === 'ui') return switchArea(-1); return false
        case 'RT': if (ctx === 'ui') return switchArea(1); return false
        case 'B': goBack(); return true
        case 'X': if (act && D.isText(act)) { openOsk(act); return true } return false
        case 'A': {
          if (!act || act === document.body) { D.moveFocus('down'); return true }
          if (act.closest('.cmdk') && act.matches('input')) { D.pressKey(act, 'Enter'); return true }
          if (D.isText(act)) { openOsk(act); return true }
          if (act.tagName === 'SELECT') { setPick(act); return true }
          if (D.isRange(act)) { const num = act.closest('.slidefield')?.querySelector('input:not([type=range])'); if (num) openOsk(num); return true }
          rumble('ok'); act.click(); D.afterOpen()
          return true
        }
        default: return false
      }
    }
    const rep = L.createRepeat()
    const step = (st, now) => {
      const m = modal.current
      const ctx = m.osk || m.pick ? 'ui' : D.contextOf()
      const dir = ctx === 'play' ? null : L.dirOf(st, ctx === 'ui')
      const d = L.repeat(rep, dir, now)
      if (d && getMode() === 'pad') {
        if (ctx === 'view') { views.get(document.activeElement)?.({ name: 'DPAD', dir: d }); return }
        const a = document.activeElement
        if (ctx === 'ui') {
          if (D.isRange(a) && (d === 'left' || d === 'right')) { D.nudgeRange(a, d); return }
          if (a?.closest?.('.cmdk') && a.matches('input') && (d === 'up' || d === 'down')) { D.pressKey(a, d === 'up' ? 'ArrowUp' : 'ArrowDown'); return }
          D.moveFocus(d)
        }
      }
      // keep the hints and the focus honest
      const c = m.osk ? 'osk' : D.contextOf()
      setUi({ ctx: c })
      if (getMode() === 'pad') D.recover()
    }
    const off1 = onAction(press), off2 = onTick(step)
    return () => { off1(); off2() }
  }, [openOsk])

  return <>
    {osk && <Osk el={osk} api={oskApi} onClose={() => { setOsk(null); setUi({ ctx: 'ui' }) }} />}
    {pick && <Picker el={pick} api={pickApi} onClose={() => setPick(null)} />}
    <FocusChip hidden={!!osk || !!pick} />
  </>
}

// ------------------------------------------------------------------ the little glyph on the focused control
function FocusChip({ hidden }) {
  const pad = usePad()
  const [r, setR] = useState(null)
  useEffect(() => {
    if (pad.mode !== 'pad' || hidden) { setR(null); return }
    const t = setInterval(() => {
      const a = document.activeElement
      if (!a || a === document.body || a.matches('[data-pad-ctx]') || D.isRange(a) || a.closest('.osk,.picker')) { setR(null); return }
      const b = a.getBoundingClientRect()
      setR(p => (p && Math.abs(p.x - b.right) < 1 && Math.abs(p.y - b.top) < 1 ? p : { x: b.right, y: b.top, w: b.width }))
    }, 120)
    return () => clearInterval(t)
  }, [pad.mode, hidden])
  if (!r || pad.mode !== 'pad') return null
  return <span className="padchip" aria-hidden="true" style={{ left: Math.min(innerWidth - 24, r.x - 11), top: Math.max(2, r.y - 9) }}>{tr('a')}</span>
}

// ------------------------------------------------------------------ hints in the status bar
export function PadHints() {
  const p = usePad()
  const list = L.hintsFor(p.ui.ctx, p.mode, { placing: p.ui.placing, modeName: p.ui.modeName })
  return <span className={'padhints' + (p.mode === 'pad' ? ' pad' : '')} aria-hidden={p.mode !== 'pad'}>
    {list.map((h, i) => <span key={i} className="ph1"><kbd className={'gl' + (p.mode === 'pad' ? ' g' : '')}>{h.k}</kbd>{h.l}</span>)}
  </span>
}

// ------------------------------------------------------------------ the on-screen keyboard
const ROWS = {
  low: ['1234567890-', 'qwertyuiop', 'asdfghjkl.', 'zxcvbnm,/_'],
  up: ['1234567890-', 'QWERTYUIOP', 'ASDFGHJKL.', 'ZXCVBNM,/_'],
  sym: ['!@#$%^&*()+', '=:;"\'?<>[]{', '}\\|~`/.,-_ ', '0123456789 '],
}
function Osk({ el, api, onClose }) {
  const [shift, setShift] = useState(false)
  const [sym, setSym] = useState(false)
  const [val, setVal] = useState(el.value || '')
  const box = useRef(null)
  useEffect(() => { setTimeout(() => { const f = box.current?.querySelector('button.k'); f && D.focusEl(f) }, 0) }, [])
  const put = v => { D.setValue(el, v); setVal(v) }
  const type = ch => { rumble('ok'); put((el.value || '') + ch); if (shift) setShift(false) }
  const back = () => put((el.value || '').slice(0, -1))
  const done = () => {
    onClose()
    setTimeout(() => { el.focus({ preventScroll: true }); D.pressKey(el, 'Enter') }, 0)
  }
  api.current = {
    press: a => {
      if (a.name === 'X') { back(); return true }
      if (a.name === 'Y') { type(' '); return true }
      if (a.name === 'START' || a.name === 'B') { done(); return true }
      if (a.name === 'A') { const f = document.activeElement; if (f && box.current?.contains(f)) f.click(); return true }
      if (a.name === 'LB' || a.name === 'RB') { setShift(s => !s); return true }
      return a.name === 'VIEW' || a.name === 'LT' || a.name === 'RT'
    },
  }
  useEffect(() => {
    const h = e => { if (e.key === 'Escape') { e.stopPropagation(); done() } }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [])
  const rows = sym ? ROWS.sym : shift ? ROWS.up : ROWS.low
  const label = el.getAttribute('aria-label') || el.placeholder || ''
  return <div className="osk" role="dialog" aria-label={tr('keyboard')} ref={box}>
    <div className="oskval"><span className="oskl">{label}</span><span className="oskt">{val}<i className="oskc" /></span></div>
    <div className="oskrows">
      {rows.map((r, ri) => <div key={ri} className="oskrow">{[...r].map((c, ci) => c === ' ' ? null : <button key={ci} className="k" onClick={() => type(c)}>{c}</button>)}</div>)}
      <div className="oskrow">
        <button className={'k w' + (shift ? ' on' : '')} onClick={() => setShift(s => !s)} aria-label={tr('shift')}>{'⇧'}</button>
        <button className={'k w' + (sym ? ' on' : '')} onClick={() => setSym(s => !s)}>{sym ? 'abc' : '#+='}</button>
        <button className="k sp" onClick={() => type(' ')} aria-label={tr('space')}>{'␣'}</button>
        <button className="k w" onClick={back} aria-label={tr('delete')}>{'⌫'}</button>
        <button className="k w" onClick={() => put('')}>{tr('clear')}</button>
        <button className="k w ok" onClick={done}>{tr('done_e9b450')}</button>
      </div>
    </div>
  </div>
}

// ------------------------------------------------------------------ a choice list for a <select>
function Picker({ el, api, onClose }) {
  const box = useRef(null)
  const opts = [...el.options]
  const close = () => { onClose(); setTimeout(() => D.focusEl(el), 0) }
  useEffect(() => { setTimeout(() => { const i = opts.findIndex(o => o.value === el.value); const bs = box.current?.querySelectorAll('button'); bs && D.focusEl(bs[Math.max(0, i)]) }, 0) }, [])
  api.current = { press: a => { if (a.name === 'B' || a.name === 'START') { close(); return true } if (a.name === 'A') { const f = document.activeElement; if (f && box.current?.contains(f)) f.click(); return true } return true } }
  useEffect(() => {
    const h = e => { if (e.key === 'Escape') { e.stopPropagation(); close() } }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [])
  return <div className="picker" role="dialog" aria-label={el.getAttribute('aria-label') || 'Choose'} ref={box}>
    {opts.map(o => <button key={o.value} className={o.value === el.value ? 'on' : ''} disabled={o.disabled}
      onClick={() => { rumble('ok'); D.setValue(el, o.value); close() }}>{o.textContent}</button>)}
  </div>
}
