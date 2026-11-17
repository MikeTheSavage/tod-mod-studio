import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'
import { useUI } from './ui.jsx'
import { t } from './i18n.js'

const fmt = n => n == null ? '' : n >= 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB'
const when = s => (s || '').replace('T', ' ')

// Verify the game files, the backup list and restore-to-original (Mods, right panel).
export default function GameFiles({ refresh }) {
  const ui = useUI()
  const [busy, setBusy] = useState(null)
  const [ver, setVer] = useState(null)
  const [bk, setBk] = useState(null)
  const run = async (kind, fn) => { setBusy(kind); try { await fn() } catch (e) { ui.say(e.message, 'bad') } setBusy(null) }
  const verify = () => run('verify', async () => setVer(await runJob('/api/verify', {})))
  const repair = f => run('repair', async () => { await runJob('/api/verify/repair', { names: [f.name] }); ui.say(f.name + ' restored from its backup.'); setVer(await runJob('/api/verify', {})) })
  const loadBackups = async () => setBk((await get('/api/backups')).backups)
  useEffect(() => { loadBackups().catch(() => setBk([])) }, [])
  const vanilla = () => run('vanilla', async () => {
    if (!(await ui.confirm({ title: t('restore_the_game_to_its_original'),
      body: t('every_mod_studio_archive_and_entry'),
      kept: t('kept_your_mod_library_projects_and'), ok: t('restore_to_original') }))) return
    await runJob('/api/restore/vanilla', {})
    ui.say(t('the_game_has_its_original_files')); refresh?.()
    if (bk) await loadBackups()
  })
  const restore = b => run('restore', async () => {
    if (!(await ui.confirm({ title: t('go_back_to_this_backup'), body: `${b.label || b.kind}, ${when(b.created)}`, ok: t('restore') }))) return
    await runJob('/api/backups/restore', { id: b.id }); ui.say(t('backup_restored')); refresh?.(); await loadBackups()
  })
  const del = b => run('delete', async () => {
    if (!(await ui.confirm({ title: t('delete_this_backup'), body: `${b.label || b.kind}, ${when(b.created)}`, ok: t('delete') }))) return
    await post('/api/backups/delete', { ids: [b.id] }); await loadBackups()
  })
  return (
    <div style={{ marginTop: 18 }}>
      <div className="upper" style={{ marginBottom: 8 }}>{t('game_files')}</div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        <button className="sm" disabled={!!busy} onClick={verify} title={t('check_the_game_archives_and_tod')}>{busy === 'verify' ? 'Checking…' : 'Verify files'}</button>
        <button className="sm danger" disabled={!!busy} onClick={vanilla} title={t('remove_everything_mod_studio_put_in')}>{t('restore_to_original')}</button>
      </div>
      {ver && <div style={{ marginTop: 8 }}>
        {ver.files.map(f => <div className="gnrow" key={f.name} style={{ padding: '6px 0' }}>
          <div style={{ flex: 1, minWidth: 0 }}><div className="small" style={{ fontWeight: 600 }}>{f.name}</div></div>
          <span className="small" style={{ color: f.status === 'changed' ? 'var(--bad)' : f.status === 'missing' ? 'var(--text-3)' : 'var(--ok)' }}>
            {f.status === 'ok' ? 'Original' : f.status === 'recorded' ? 'Noted' : f.status === 'changed' ? 'Changed' : 'Not there'}</span>
          {f.status === 'changed' && f.backup && <button className="sm" disabled={!!busy} onClick={() => repair(f)}>{t('restore')}</button>}
        </div>)}
      </div>}
      {bk && <div style={{ marginTop: 12 }}>
        <div className="upper" style={{ marginBottom: 4 }}>{t('backups')}</div>
        <div style={{ maxHeight: 220, overflowY: 'auto' }}>
        {!bk.length && <div className="small muted">{t('no_backups_yet')}</div>}
        {bk.map(b => <div className="gnrow" key={b.id} style={{ padding: '6px 0' }}>
          <div style={{ flex: 1, minWidth: 0 }}><div className="small" style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.label || b.kind}</div>
            <div className="small muted">{when(b.created)} {'·'} {fmt(b.bytes)}</div></div>
          <button className="sm" disabled={!!busy} onClick={() => restore(b)}>{t('restore')}</button>
          <button className="sm ghost" disabled={!!busy} onClick={() => del(b)} title={t('delete_this_backup_4c6b25')} aria-label={t('delete_this_backup_4c6b25')}>{'✕'}</button>
        </div>)}
        </div>
      </div>}
    </div>
  )
}
