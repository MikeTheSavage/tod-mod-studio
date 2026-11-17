// Named versions of a project: save, list, restore (the state you have now is kept as a version first), delete.
import React, { useCallback, useEffect, useState } from 'react'
import { get, post } from './api.js'
import { Menu, useUI } from './ui.jsx'
import { t as tr } from './i18n.js'

const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t)
  if (s < 60) return 'now'
  if (s < 3600) return Math.floor(s / 60) + ' min ago'
  if (s < 86400) return Math.floor(s / 3600) + ' h ago'
  return new Date(t * 1000).toLocaleDateString()
}

// kind: 'level' | 'mission' | 'newmap'; getProject() -> the project as it is now; ensureId() -> a saved id (saves first if needed);
// onLoad(project) puts a restored version into the editor as an unsaved change
export default function Snapshots({ kind, id, getProject, ensureId, onLoad, disabled }) {
  const ui = useUI()
  const [list, setList] = useState([])
  const [name, setName] = useState('')
  const [open, setOpen] = useState(() => new URLSearchParams(location.search).get('open') === 'versions')      // ?open=versions: screenshots
  const load = useCallback(async pid => {
    if (!pid) { setList([]); return }
    try { setList((await get('/api/projsnaps', { kind, id: pid })).snapshots) } catch { setList([]) }
  }, [kind])
  useEffect(() => { if (open) load(id) }, [open, id])
  const save = async () => {
    try {
      const pid = id || await ensureId()
      const r = await post('/api/projsnaps', { action: 'save', kind, id: pid, name, project: getProject() })
      setList(r.snapshots); setName('')
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const restore = async s => {
    try {
      const r = await post('/api/projsnaps', { action: 'restore', kind, id, snapshot: s.id, project: getProject() })
      setList(r.snapshots); setOpen(false)
      onLoad(r.project)
      ui.say(`Restored "${s.name}". What you had is kept as a version.`)
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const del = async s => {
    if (!(await ui.confirm({ title: `Delete the version "${s.name}"?`, body: tr('it_cannot_be_brought_back'), ok: tr('delete_version') }))) return
    try { setList((await post('/api/projsnaps', { action: 'delete', kind, id, snapshot: s.id })).snapshots) } catch (e) { ui.say(e.message, 'bad') }
  }
  return (
    <Menu right open={open} setOpen={setOpen} disabled={disabled} label={<>{tr('versions')}{' '}{'▾'}</>} title={tr('named_versions_of_this_project')} menuStyle={{ width: 340 }}>{() => <div>
      <div className="row" style={{ gap: 6, marginBottom: 6 }}>
        <input aria-label={tr('version_name')} placeholder={tr('name_this_version')} value={name} onChange={e => setName(e.target.value)}
               onKeyDown={e => { if (e.key === 'Enter') save() }} />
        <button className="primary sm" onClick={save}>{tr('save')}</button>
      </div>
      {!list.length && <div className="muted small" style={{ padding: '6px 2px' }}>{tr('no_versions_yet')}</div>}
      {list.map(s => (
        <div key={s.id} className="snaprow">
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="sn" title={s.name}>{s.name}</div>
            <div className="muted small">{ago(s.created)}{s.auto ? ' · automatic' : ''}</div>
          </div>
          <button className="sm" onClick={() => restore(s)}>{tr('restore')}</button>
          <button className="sm danger" onClick={() => del(s)} aria-label={'Delete ' + s.name}>{tr('delete')}</button>
        </div>))}
    </div>}</Menu>
  )
}
