import React, { useEffect, useState } from 'react'
import { post } from './api.js'
import { useUI } from './ui.jsx'
import { t } from './i18n.js'

// The community pack: a list read from the address set in Settings. Empty until the person turns online features on.
export default function Community({ go, onAdded }) {
  const ui = useUI()
  const [cat, setCat] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(null)
  const [q, setQ] = useState('')
  const load = () => { setErr(null); post('/api/community', {}).then(setCat).catch(e => { setCat(null); setErr(e.message) }) }
  useEffect(() => { load() }, [])
  const get = async r => {
    setBusy(r.id)
    try {
      const res = await post('/api/community', { action: 'get', id: r.id })
      ui.say(res.kind === 'collection' ? `Added ${res.mods.length} mods.` : res.status === 'updated' ? `Updated "${res.name}" to ${r.version}.` : `Added "${res.name}".`)
      onAdded?.(); load()
    } catch (e) { ui.say(e.message, 'bad') }
    setBusy(null)
  }
  const rows = (cat?.rows || []).filter(r => !q || (r.name + ' ' + r.author + ' ' + r.description).toLowerCase().includes(q.toLowerCase()))
  return (
    <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: 16 }}>
      <div className="row" style={{ marginBottom: 12, gap: 8 }}>
        <input style={{ maxWidth: 280 }} placeholder={t('search')} aria-label={t('search_the_community_pack')} value={q} onChange={e => setQ(e.target.value)} />
        <div className="grow" />
        {cat?.name && <span className="muted small">{cat.name}</span>}
        <button onClick={load}>{t('refresh')}</button>
      </div>
      {err && <div className="card sm" style={{ gap: 8 }}>
        <div>{err}</div>
        <div><button onClick={() => go?.('settings')}>{t('open_settings')}</button></div></div>}
      {!err && !cat && <div className="empty">{t('reading_the_list')}{'…'}</div>}
      {cat && !rows.length && <div className="muted">{t('nothing_here')}</div>}
      {!!rows.length && <div style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-lg)', background: 'var(--surface)', overflow: 'hidden' }}>
        {rows.map(r => <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 12, minHeight: 56, padding: '6px 12px', borderBottom: '1px solid var(--line)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{r.name}<span className="muted small" style={{ fontWeight: 400 }}>{r.author ? ' by ' + r.author : ''}{r.version ? ' · ' + r.version : ''}{r.kind === 'collection' ? ' · collection' : ''}</span></div>
            <div className="small muted" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.description}>{r.description}</div></div>
          <span style={{ fontSize: 12, color: r.state === 'installed' ? 'var(--ok)' : r.state === 'update' ? 'var(--accent-text)' : 'var(--text-3)' }}>
            {r.state === 'installed' ? 'Added' : r.state === 'update' ? `Update from ${r.have}` : ''}</span>
          <button className={r.state === 'installed' ? '' : 'primary'} disabled={!!busy || r.state === 'installed' || !r.sha256} title={r.sha256 ? '' : 'No fingerprint: not downloaded'}
            onClick={() => get(r)}>{busy === r.id ? 'Adding…' : r.state === 'update' ? 'Update' : 'Get'}</button>
        </div>)}
      </div>}
    </div>
  )
}
