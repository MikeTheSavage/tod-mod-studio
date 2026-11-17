import React, { useEffect, useRef, useState } from 'react'
import { get, post } from './api.js'
import { useUI } from './ui.jsx'
import { t } from './i18n.js'

// A thin bar under the top bar when a newer version is offered. Nothing is downloaded until the person asks, and the setup only
// runs after they confirm.
export function UpdateBar({ info, onClose }) {
  const ui = useUI()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!info || !info.available) return null
  const run = async () => {
    setBusy(true)
    try {
      const d = await post('/api/update', { action: 'download' })
      if (await ui.confirm({ title: `Install version ${d.version}?`, body: t('mod_studio_closes_and_the_new'), kept: t('kept_your_mods_projects_and_saves'), ok: t('install'), danger: false }))
        await post('/api/update', { action: 'run', path: d.path, confirmed: true })
    } catch (e) { ui.say(e.message, 'bad') }
    setBusy(false)
  }
  return (
    <div className="updatebar" role="status">
      <span><b>{t('version')}{' '}{info.version}</b>{' '}{t('is_available')}</span>
      <button className="sm" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide' : 'What is new'}</button>
      <button className="sm primary" disabled={busy} onClick={run}>{busy ? 'Downloading…' : 'Download and install'}</button>
      <div style={{ flex: 1 }} />
      <button className="sm ghost" aria-label={t('dismiss')} onClick={onClose}>{'×'}</button>
      {open && <ul>{info.changes.length ? info.changes.map((c, i) => <li key={i}>{c}</li>) : <li>{t('no_notes')}</li>}</ul>}
    </div>
  )
}

// A mod file the program was started with (a double click in Windows): check it, then offer to add it.
export function useOpenFiles(ready, onAdded) {
  const ui = useUI()
  const done = useRef(false)
  useEffect(() => {
    if (!ready || done.current) return
    done.current = true
    get('/api/startup/files').then(async r => {
      for (const path of r.files || []) {
        const c = await post('/api/mods/inspect', { path })
        const name = path.split(/[\\/]/).pop()
        if (!c.ok) { ui.say(`${name} was not added: ${c.problems.join(' ')}`, 'bad'); continue }
        const ok = await ui.confirm({ title: `Add "${c.name || name}"?`, body: c.notes?.length ? c.notes.join(' ') : undefined, kept: t('it_goes_into_your_mod_library'), ok: t('add'), danger: false })
        if (!ok) continue
        try {
          const res = await post('/api/mods/import', { path })
          const need = (res.unmet || []).map(u => u.text).join(' ')
          ui.say((res.kind === 'collection' ? `Added ${res.mods.length} mods.` : `Added "${res.name}".`) + (need ? ' ' + need : ''), need ? 'bad' : 'ok')
          onAdded?.()
        } catch (e) { ui.say(e.message, 'bad') }
      }
    }).catch(() => {})
  }, [ready])
}
