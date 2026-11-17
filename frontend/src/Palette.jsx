// The command search (Ctrl+K) and the shortcut editor. Both read the commands the open screen registered
// (commands.js) plus the app's own navigation commands passed in `extra`.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { allCommands, bindingOf, comboOf, conflictOf, openPalette, openShortcuts, prettyCombo, resetBindings, setBinding, useCommandUI } from './commands.js'
import { t as tr } from './i18n.js'

export function CommandHost({ extra = [] }) {
  const ui = useCommandUI()
  return <>
    {ui.paletteOpen && <Palette extra={extra} />}
    {ui.shortcutsOpen && <Shortcuts />}
  </>
}

function Palette({ extra }) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const inp = useRef(null)
  useEffect(() => { inp.current?.focus() }, [])
  const list = useMemo(() => {
    const own = allCommands().filter(c => c.enabled !== false)
    const all = [...own, ...extra, { id: 'app.shortcuts', label: tr('keyboard_shortcuts'), group: 'App', run: () => openShortcuts(true) }]
    const t = q.toLowerCase().split(/\s+/).filter(Boolean)
    return all.filter(c => t.every(w => (c.label + ' ' + (c.group || '')).toLowerCase().includes(w))).slice(0, 60)
  }, [q, extra])
  const run = c => { openPalette(false); setTimeout(() => c.run(), 0) }
  const key = e => {
    if (e.key === 'Escape') { e.preventDefault(); openPalette(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setI(Math.min(list.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setI(Math.max(0, i - 1)) }
    else if (e.key === 'Enter' && list[i]) { e.preventDefault(); run(list[i]) }
  }
  return <div className="cmdk" onMouseDown={e => { if (e.target === e.currentTarget) openPalette(false) }}>
    <div className="box" role="dialog" aria-label={tr('search_commands')}>
      <input ref={inp} aria-label={tr('search_commands')} placeholder={tr('type_a_command')} value={q} onChange={e => { setQ(e.target.value); setI(0) }} onKeyDown={key} />
      <div className="res" role="listbox">
        {list.map((c, n) => <div key={c.id} role="option" aria-selected={n === i} className={'row2' + (n === i ? ' on' : '')} onMouseEnter={() => setI(n)} onClick={() => run(c)}>
          <span>{c.label}</span>{c.group && <span className="g">{c.group}</span>}{bindingOf(c) && <span className="k">{prettyCombo(bindingOf(c))}</span>}</div>)}
        {!list.length && <div className="muted small" style={{ padding: 10 }}>{tr('nothing_matches')}</div>}
      </div>
    </div>
  </div>
}

function Shortcuts() {
  const [rec, setRec] = useState(null)
  const [msg, setMsg] = useState('')
  const ui = useCommandUI()
  const cmds = ui.commands.filter(c => c.keys !== undefined || c.id)
  useEffect(() => {
    const h = e => {
      if (!rec) { if (e.key === 'Escape') openShortcuts(false); return }
      e.preventDefault(); e.stopPropagation()
      if (e.key === 'Escape') { setRec(null); setMsg(''); return }
      const combo = comboOf(e)
      if (!combo) return
      const clash = conflictOf(rec, combo)
      if (clash) { setMsg(`${prettyCombo(combo)} is used by ${clash.label}.`); return }
      setBinding(rec, combo); setRec(null); setMsg('')
    }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [rec])
  const groups = [...new Set(cmds.map(c => c.group || 'Other'))]
  return <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) openShortcuts(false) }}>
    <div className="dialog" role="dialog" aria-label={tr('keyboard_shortcuts')} style={{ width: 520, maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
      <div className="dt">{tr('keyboard_shortcuts')}</div>
      <div style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
        {groups.map(g => <div key={g}><div className="upper" style={{ padding: '8px 8px 2px' }}>{g}</div>
          {cmds.filter(c => (c.group || 'Other') === g).map(c => <div key={c.id} className="keyrow">
            <span className="l">{c.label}</span>
            <button className={'cap' + (rec === c.id ? ' rec' : '')} onClick={() => { setRec(rec === c.id ? null : c.id); setMsg('') }}>{rec === c.id ? 'Press a key…' : bindingOf(c) ? prettyCombo(bindingOf(c)) : 'None'}</button>
            <button className="sm ghost" title={tr('back_to_the_default')} disabled={bindingOf(c) === (c.keys || '')} onClick={() => setBinding(c.id, null)}>{'↺'}</button>
            <button className="sm ghost" title={tr('remove_the_key')} disabled={!bindingOf(c)} onClick={() => setBinding(c.id, '')}>{'×'}</button></div>)}</div>)}
      </div>
      {msg && <div className="small warn" style={{ padding: '6px 8px' }}>{msg}</div>}
      <div className="da"><button onClick={() => resetBindings()}>{tr('reset_all')}</button><button className="primary" onClick={() => openShortcuts(false)}>{tr('done_e9b450')}</button></div>
    </div>
  </div>
}
