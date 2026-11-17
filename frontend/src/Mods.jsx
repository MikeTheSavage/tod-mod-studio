import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'
import { useUI, Menu, Switch, Pipeline, CheckRow, Seg, Advanced } from './ui.jsx'
import GameFiles from './GameFiles.jsx'
import TestControl from './TestGame.jsx'
import ModPage from './ModPage.jsx'
import Community from './Community.jsx'
import { t } from './i18n.js'

const plural = (n, a, b) => `${n} ${n === 1 ? a : b || a + 's'}`

// One small file: a prefab, a route set, a tuning preset or one mission.
function PieceDialog({ onClose }) {
  const ui = useUI()
  const [src, setSrc] = useState(null)
  const [kind, setKind] = useState('prefab')
  const [pick, setPick] = useState('')
  useEffect(() => { post('/api/pieces/sources', {}).then(setSrc).catch(e => ui.say(e.message, 'bad')) }, [])
  const list = !src ? [] : kind === 'prefab' ? src.prefabs.map(x => ({ id: x.id, name: x.name }))
    : kind === 'routes' ? src.routes.map(x => ({ id: x.id, name: x.name }))
    : kind === 'tuning' ? src.tuning.map(x => ({ id: x.id, name: x.name }))
    : src.missions.map(x => ({ id: x.project + '|' + x.mission, name: x.name }))
  const source = () => kind === 'mission' ? { project: pick.split('|')[0], mission: pick.split('|')[1] } : kind === 'tuning' ? { mod: pick } : pick
  const go = async () => {
    try {
      const r = await post('/api/pieces/export', { kind, source: source(), name: list.find(x => x.id === pick)?.name })
      if (r.path) { ui.say('Shared as ' + r.path); onClose() }
    } catch (e) { ui.say(e.message, 'bad') }
  }
  return (
    <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog" role="dialog" aria-label={t('share_a_piece')} style={{ width: 420 }}>
        <div className="dt">{t('share_a_piece')}</div>
        <div className="dd" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Seg value={kind} onChange={k => { setKind(k); setPick('') }} options={[{ value: 'prefab', label: t('prefab') }, { value: 'routes', label: t('routes') }, { value: 'tuning', label: t('tuning') }, { value: 'mission', label: t('mission_e4698d') }]} />
          <select value={pick} onChange={e => setPick(e.target.value)} aria-label={t('what_to_share')}>
            <option value="">{list.length ? 'Choose' : 'Nothing to share yet'}</option>
            {list.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        </div>
        <div className="da"><button onClick={onClose}>{t('cancel')}</button><button className="primary" disabled={!pick} onClick={go}>{t('share')}{'…'}</button></div>
      </div>
    </div>
  )
}

export default function Mods({ status, project, loadProject, replace, refresh, ov, dirty, go }) {
  const ui = useUI()
  const [st, setSt] = useState(null)
  const [job, setJob] = useState(null)
  const [exp, setExp] = useState(null)
  const [sel, setSel] = useState(null)
  const [drag, setDrag] = useState(null)
  const [busy, setBusy] = useState(null)
  const [view, setView] = useState(() => new URLSearchParams(location.search).get('view') === 'community' ? 'community' : 'library')
  const [cfOpen, setCfOpen] = useState(() => new URLSearchParams(location.search).get('conflicts') === '1')
  const [pageOpen, setPageOpen] = useState(() => new URLSearchParams(location.search).get('page') === '1')
  const [piece, setPiece] = useState(false)
  const [pname, setPname] = useState('')
  const [pmenu, setPmenu] = useState(() => new URLSearchParams(location.search).get('menu') === 'profiles')
  const load = () => get('/api/mods').then(setSt).catch(e => ui.say(e.message, 'bad'))
  useEffect(() => { load() }, [])
  if (!st) return <div className="screen"><div className="empty">{t('reading_the_mod_library')}{'…'}</div></div>
  const mods = st.mods
  const enabled = mods.filter(m => m.enabled).map(m => m.id)
  const inst = st.installed || {}
  const instIds = inst.zip_present ? (inst.mods || []) : []
  const cf = st.conflicts || { clashes: [], merged: [], by_mod: {}, counts: { clashes: 0, merged: 0 } }
  const unmet = st.unmet || []
  const profiles = st.profiles || { active: '', profiles: [] }
  const setState = async (order, en) => setSt(await post('/api/mods/state', { order, enabled: en }))
  const move = (i, d) => {
    const o = mods.map(m => m.id)
    const j = i + d
    if (j < 0 || j >= o.length) return
    ;[o[i], o[j]] = [o[j], o[i]]
    setState(o, enabled)
  }
  const dropOn = i => {
    if (drag == null || drag === i) return
    const o = mods.map(m => m.id)
    const [x] = o.splice(drag, 1)
    o.splice(i, 0, x)
    setState(o, enabled)
  }
  const toggle = (id, on) => setState(mods.map(m => m.id), on ? [...enabled, id] : enabled.filter(x => x !== id))
  const install = async () => {
    if (cf.counts.clashes > 0) {
      const top = cf.clashes.slice(0, 4).map(c => `${c.label}: ${c.mods.find(m => m.wins)?.name} wins`).join('\n')
      if (!(await ui.confirm({ title: `${plural(cf.counts.clashes, 'clash', 'clashes')} between your mods`,
        body: <span style={{ whiteSpace: 'pre-line' }}>{top}{cf.counts.clashes > 4 ? `\nand ${cf.counts.clashes - 4} more` : ''}</span>,
        ok: t('install_anyway'), danger: false }))) return
    }
    setBusy('install')
    try { const r = await runJob('/api/mods/install', {}, setJob); ui.say(r.configpc_line ? 'Mods installed.' : 'Original files restored.'); refresh() }
    catch (e) { ui.say(e.message, 'bad') }
    setJob(null); setBusy(null); load()
  }
  const uninstall = async () => {
    const n = instIds.length
    if (!(await ui.confirm({ title: t('remove_all_mods_from_the_game'),
      body: `This puts the game's original files back.${n ? ` The ${n} installed mod${n === 1 ? '' : 's'} stop${n === 1 ? 's' : ''} working in the game until you install ${n === 1 ? 'it' : 'them'} again.` : ''}`,
      kept: t('kept_your_mod_library_new_maps'), ok: t('remove_all_mods') }))) return
    setBusy('install')
    try { await runJob('/api/mods/uninstall', {}, setJob); ui.say(t('all_mods_removed_the_game_has')); refresh() } catch (e) { ui.say(e.message, 'bad') }
    setJob(null); setBusy(null); load()
  }
  const checkCurrent = async () => {
    setBusy('check')
    try { const r = await runJob('/api/export', { mod: { ...project, author: project.author || status.settings?.author || '' } }, setJob); setExp(r); replace({ ...project, id: r.mod.id }); load() }
    catch (e) { ui.say(e.message, 'bad') }
    setJob(null); setBusy(null)
  }
  const share = async m => {
    if (!m) return
    try {
      const r = await post('/api/mods/export', { id: m.id, suggest: m.id + '.todmod' })
      if (r.path) ui.say('Shared as ' + r.path)
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const shareCollection = async () => {
    const ids = enabled.length ? enabled : mods.map(m => m.id)
    try {
      const r = await post('/api/collections/export', { ids, name: profiles.active || 'My collection' })
      if (r.path) ui.say(`Shared ${plural(ids.length, 'mod')} as ${r.path}`)
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const imp = async () => {
    try {
      const r = await post('/api/mods/import', {})
      if (r.cancelled) return
      const need = (r.unmet || []).map(u => u.text).join(' ')
      ui.say((r.kind === 'collection' ? `Added ${plural(r.mods.filter(x => x.status !== 'skipped' && x.status !== 'same').length, 'mod')}.`
        : r.kind === 'mod' ? (r.status === 'updated' ? `Updated "${r.name}" (was ${r.from_version}).` : r.status === 'same' ? `"${r.name}" is already here.` : `Added "${r.name}".`)
        : `Added ${r.kind} "${r.name}".`) + (need ? ' ' + need : ''), need ? 'bad' : 'ok')
      load()
    } catch (e) { ui.say(e.message, 'bad') }
  }
  const edit = async m => {
    try { const full = await get('/api/mods/get', { id: m.id, edit: 1 }); loadProject(full); ui.say('Loaded "' + m.name + '".'); go?.('level') }
    catch (e) { ui.say(e.message, 'bad') }
  }
  const del = async m => {
    if (!(await ui.confirm({ title: `Delete "${m.name}" from the library?`, body: t('the_mod_file_is_removed_from'),
      kept: t('kept_your_other_mods_new_maps'), ok: t('delete_mod') }))) return
    setSt(await post('/api/mods/delete', { id: m.id }))
  }
  const removeNewMap = async n => {
    if (!(await ui.confirm({ title: `Remove the new map "${n.name}" from the game?`, body: t('this_puts_the_game_s_original'), kept: t('kept_your_mod_library_missions_and'), ok: t('remove_map') }))) return
    try { await runJob('/api/newmaps', { action: 'uninstall', id: n.id }); ui.say(t('the_map_was_removed_from_the')); refresh() } catch (e) { ui.say(e.message, 'bad') }
  }
  const removeMissions = async p => {
    if (!(await ui.confirm({ title: `Remove "${p.name}" from the game?`, body: t('the_missions_in_this_project_stop'), kept: t('kept_your_mod_library_new_maps_8330b9'), ok: t('remove_missions') }))) return
    try { await runJob('/api/missiontpl', { action: 'uninstall', id: p.id }); ui.say(t('the_missions_were_removed_from_the')); refresh() } catch (e) { ui.say(e.message, 'bad') }
  }

  // ---- profiles
  const profileAct = async (action, body, close) => {
    close?.()
    try { const r = await post('/api/profiles', { action, ...body }); if (r.profiles) load(); return r } catch (e) { ui.say(e.message, 'bad') }
  }
  const switchProfile = async (name, close) => {
    close?.()
    if (name === profiles.active) return
    if (!(await ui.confirm({ title: `Switch to "${name}"?`, body: t('the_game_is_rebuilt_from_that'),
      kept: t('kept_every_mod_in_the_library'), ok: t('switch'), danger: false }))) return
    setBusy('install')
    try { await runJob('/api/profiles', { action: 'switch', name }, setJob); ui.say(`Now using "${name}".`); refresh() } catch (e) { ui.say(e.message, 'bad') }
    setJob(null); setBusy(null); load()
  }

  // ---- status of every row
  const changedSince = m => m.enabled && inst.installed && (m.updated || '') > inst.installed
  const statusOf = m => !m.enabled ? ['Off', 'var(--text-3)']
    : !instIds.includes(m.id) ? ['Switched on, not in the game', 'var(--text-2)']
    : changedSince(m) ? ['Changed since last install', 'var(--accent-text)'] : ['Installed', 'var(--ok)']
  const same = enabled.length === instIds.length && enabled.every(id => instIds.includes(id))
  const anyChanged = mods.some(changedSince)
  const checkSteps = (() => {
    if (busy === 'check') return { tone: 'busy', note: job?.message || 'Checking…', pct: job?.total ? 100 * job.done / job.total : 5 }
    if (!exp) return { tone: 'idle', note: 'Not checked yet', action: 'Check and build this mod', onClick: checkCurrent }
    const bad = exp.checks.filter(c => c.level === 'error').length, warn = exp.checks.filter(c => c.level === 'warn').length
    if (bad) return { tone: 'bad', note: `${bad} problem${bad === 1 ? '' : 's'} to fix`, action: 'Check again', onClick: checkCurrent }
    return { tone: warn ? 'warn' : 'ok', note: warn ? `Passed · ${warn} warning${warn === 1 ? '' : 's'}` : 'Passed', action: 'Check again', onClick: checkCurrent }
  })()
  const installStep = busy === 'install' ? { tone: 'busy', note: job?.message || 'Installing…', pct: job?.total ? 100 * job.done / job.total : 5 }
    : !enabled.length && !instIds.length ? { tone: 'idle', note: 'Switch a mod on first' }
    : unmet.length ? { tone: 'bad', note: unmet[0].text, action: 'Install enabled mods into the game', onClick: install }
    : same && !anyChanged && instIds.length ? { tone: 'ok', note: `${instIds.length} mod${instIds.length === 1 ? '' : 's'} in the game, up to date`, action: 'Install again', onClick: install }
    : { tone: 'ready', note: !enabled.length ? 'Nothing switched on: removes the mods' : !instIds.length ? `${enabled.length} switched on, none in the game` : anyChanged ? `${mods.filter(changedSince).length} changed since last install` : 'The list changed since last install',
      action: 'Install enabled mods into the game', onClick: install }
  const steps = [{ label: t('check'), ...checkSteps }, { label: t('install'), ...installStep }]
  const nm = ov?.new_maps || [], mp = ov?.mission_projects || []
  const names = (ov?.mods_installed || []).join(', ')
  const chip = (txt, tone, tip) => <span className="badge" title={tip} style={{ background: tone === 'bad' ? 'var(--bad-soft)' : 'var(--warn-soft)', color: tone === 'bad' ? 'var(--bad)' : 'var(--warn)' }}>{txt}</span>

  return (
    <div className="screen">
      <div className="tb">
        <Seg value={view} onChange={setView} options={[{ value: 'library', label: t('library') }, { value: 'community', label: t('community'), title: t('mods_from_the_list_set_in') }]} />
        <span className="muted small">{mods.length}{' '}{t('mod_7dd30f')}{mods.length === 1 ? '' : 's'} {'·'} {enabled.length}{' '}{t('on_db3d40')}</span>
        <div style={{ flex: 1 }} />
        <Menu right buttonClass="soft" open={pmenu} setOpen={setPmenu} title={t('named_lists_of_switched_on_mods')} label={<>{profiles.active || 'Profile'} {'▾'}</>}>{close => <div style={{ minWidth: 240 }}>
          <div className="grp" style={{ paddingTop: 0 }}>{t('profiles')}</div>
          {profiles.profiles.map(p => <div key={p.name} role="menuitem" className={'item' + (p.active ? ' on' : '')} onClick={() => switchProfile(p.name, close)} title={p.enabled + ' on: ' + p.mods.join(', ')}>
            <span style={{ flex: 1 }}>{p.name}</span>
            {!p.active && <button className="sm ghost" aria-label={'Delete ' + p.name} onClick={e => { e.stopPropagation(); profileAct('delete', { name: p.name }, close) }}>{'×'}</button>}</div>)}
          <div className="row" style={{ padding: '6px 4px 2px', gap: 6 }}>
            <input value={pname} placeholder={t('new_profile')} aria-label={t('new_profile_name')} onChange={e => setPname(e.target.value)} onKeyDown={e => e.stopPropagation()} />
            <button className="sm" disabled={!pname.trim()} onClick={async () => { const r = await profileAct('create', { name: pname, copy: true }); if (r) setPname('') }}>{t('add')}</button></div>
        </div>}</Menu>
        <button onClick={imp}>{t('import')}{'…'}</button>
        <Menu buttonClass="" title={t('share_mods_as_files')} label={<>{t('share')}{' '}{'▾'}</>} right>{close => <>
          <div className={'item' + (sel ? '' : ' off')} onClick={() => { close(); share(mods.find(m => m.id === sel)) }} title={sel ? '' : 'Click a mod in the list first'}>{t('the_selected_mod')}{'…'}</div>
          <div className="item" onClick={() => { close(); shareCollection() }}>{t('the_switched_on_mods_as_a')}{'…'}</div>
          <div className="item" onClick={() => { close(); setPiece(true) }}>{t('one_piece')}{'…'}</div></>}</Menu>
      </div>
      <div className="split">
        {view === 'community' ? <Community go={go} onAdded={load} /> : <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: 16 }}>
          <div className="card sm" style={{ marginBottom: 14, gap: 8 }}>
            <div className="row"><div className="grow"><div className="upper">{t('the_mod_you_are_editing')}</div>
              <div style={{ fontWeight: 600, fontSize: 15 }}>{project.name} <span className="muted small" style={{ fontWeight: 400 }}>{dirty ? 'has unsaved changes' : project.id ? 'saved in the library' : 'not in the library yet'}</span></div></div>
              <button disabled={!!busy} onClick={checkCurrent}>{t('save_check_and_build')}</button></div>
            <textarea rows={2} aria-label={t('mod_description')} placeholder={t('what_does_this_mod_do')} defaultValue={project.description} key={project.id || 'new'} onBlur={e => replace({ ...project, description: e.target.value })} />
            <Advanced title={t('mod_page')} open={pageOpen}><ModPage project={project} replace={replace} library={mods} /></Advanced>
            {exp && <div>
              <div className="small muted" style={{ marginBottom: 4 }}>{t('built_e1b007')}{' '}{Math.round((exp.build.zip?.zip_bytes || 0) / 1024)}{' '}{t('kb')}</div>
              <div style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
                {exp.checks.slice().sort((a, b) => ({ error: 0, warn: 1 }[a.level] ?? 2) - ({ error: 0, warn: 1 }[b.level] ?? 2)).map((c, i) =>
                  <CheckRow key={i} tone={c.level === 'error' ? 'bad' : c.level === 'warn' ? 'warn' : 'ok'} title={c.title} fix={c.area} />)}</div>
              <div style={{ marginTop: 6 }}><button className="sm" onClick={() => post('/api/reveal', { path: exp.folder })}>{t('open_the_folder')}</button></div></div>}
          </div>

          {(cf.counts.clashes > 0 || cf.counts.merged > 0 || unmet.length > 0) && <div className="card sm" style={{ marginBottom: 14, gap: 8 }} id="conflicts">
            <div className="row" style={{ gap: 8 }}>
              <div className="upper grow">{t('conflicts')}</div>
              {cf.counts.clashes > 0 && chip(plural(cf.counts.clashes, 'clash', 'clashes'), 'warn', 'The same thing is set by more than one mod. The mod lower in the list wins.')}
              {cf.counts.merged > 0 && <span className="badge" title={t('these_mods_change_the_same_file')}>{cf.counts.merged}{' '}{t('merged')}</span>}
              {unmet.length > 0 && chip(plural(unmet.length, 'need') + ' not met', 'bad')}
              <button className="sm" onClick={() => setCfOpen(!cfOpen)} aria-expanded={cfOpen}>{cfOpen ? 'Hide' : 'Show'}</button></div>
            {unmet.map((u, i) => <div key={i} className="small" style={{ color: 'var(--bad)' }}>{u.text}</div>)}
            {cfOpen && <div style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
              {cf.clashes.map((c, i) => <div key={i} style={{ padding: '6px 10px', borderTop: i ? '1px solid var(--line)' : 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}><span className="badge">{({ value: 'Value', removed: 'Removed', model: 'Model', texture: 'Texture', collision: 'Collision' })[c.kind] || c.kind}</span>
                  <span className="mono small" style={{ overflowWrap: 'anywhere' }} title={[c.where, c.block].filter(Boolean).join(' · ')}>{c.label}</span></div>
                <div className="small" style={{ marginTop: 3, display: 'flex', flexWrap: 'wrap', gap: '2px 14px' }}>
                  {c.mods.map(m => <span key={m.id} style={{ color: m.wins ? 'var(--ok)' : 'var(--text-3)', textDecoration: m.wins ? 'none' : 'line-through' }}>{m.name}: {m.value}{m.wins ? ' wins' : ''}</span>)}</div></div>)}
              {cf.merged.map((m, i) => <div key={'m' + i} className="small muted" style={{ padding: '6px 10px', borderTop: '1px solid var(--line)' }}
                title={m.block + ': different values, all of them apply.'}>{m.mods.map(id => mods.find(x => x.id === id)?.name).join(', ')}: {plural(m.items, 'different thing')}{' '}{t('changed_all_applied')}</div>)}
              {cf.counts.clashes > cf.clashes.length && <div className="small muted" style={{ padding: '6px 10px' }}>{t('and')}{' '}{cf.counts.clashes - cf.clashes.length}{' '}{t('more_e7c95b')}</div>}
            </div>}
          </div>}

          <div role="list" aria-label={t('mod_library')} style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-lg)', background: 'var(--surface)', overflow: 'hidden' }}>
            {mods.map((m, i) => {
              const [stt, col] = statusOf(m)
              const mc = cf.by_mod[m.id]
              const um = unmet.filter(u => u.mod === m.id)
              return (
                <div key={m.id} role="listitem" tabIndex={0} aria-label={`${m.name}, ${stt}`} aria-current={sel === m.id ? 'true' : undefined}
                     onKeyDown={e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setSel(m.id) } }} draggable onDragStart={() => setDrag(i)} onDragOver={e => e.preventDefault()} onDrop={() => { dropOn(i); setDrag(null) }} onDragEnd={() => setDrag(null)}
                     onClick={() => setSel(m.id)} style={{ display: 'flex', alignItems: 'center', gap: 12, minHeight: 52, padding: '6px 12px', borderBottom: '1px solid var(--line)',
                       background: sel === m.id ? 'var(--surface-2)' : 'transparent', opacity: drag === i ? .5 : 1, cursor: 'pointer' }}>
                  <span style={{ color: 'var(--text-3)', cursor: 'grab', letterSpacing: -2 }} title={t('drag_to_reorder_a_mod_lower')}>{'⋮⋮'}</span>
                  <span className="mono muted" style={{ width: 16 }}>{i + 1}</span>
                  <span onClick={e => e.stopPropagation()}><Switch label={'Switch ' + m.name + ' on'} on={m.enabled} onChange={on => toggle(m.id, on)} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, color: m.enabled ? 'var(--text)' : 'var(--text-2)' }}>{m.name}<span className="muted small" style={{ fontWeight: 400 }}> {m.version}{m.author ? ' · ' + m.author : ''}</span>
                      {m.enabled && mc?.clashes > 0 && <> {chip(plural(mc.clashes, 'clash', 'clashes'), 'warn', 'Another mod sets the same thing. See Conflicts.')}</>}
                      {m.enabled && um.length > 0 && <> {chip('Needs', 'bad', um.map(u => u.text).join(' '))}</>}
                      {m.imported && !m.reuse && <> <span className="badge" title={t('the_author_does_not_allow_editing')}>{t('locked')}</span></>}</div>
                    <div className="small muted" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {[m.description, `${m.level_ops} level change${m.level_ops === 1 ? '' : 's'}, ${m.data_values} game data value${m.data_values === 1 ? '' : 's'}${m.collision_sets ? ', ' + m.collision_sets + ' collision' : ''}`].filter(Boolean).join(' · ')}</div></div>
                  <span style={{ flex: 'none', fontSize: 12, color: col, whiteSpace: 'nowrap' }}>{stt}</span>
                  <span onClick={e => e.stopPropagation()}><Menu right buttonClass="sm ghost" label={'⋯'} title={t('more')}>{close => <>
                    <div className={'item' + (m.imported && !m.reuse ? ' off' : '')} onClick={() => { close(); edit(m) }}>{t('edit_in_the_editor')}</div>
                    <div className={'item' + (m.imported && !m.reuse ? ' off' : '')} onClick={() => { close(); share(m) }}>{t('share_as_todmod')}{'…'}</div>
                    <div className={'item' + (i === 0 ? ' off' : '')} onClick={() => { close(); move(i, -1) }}>{t('move_up')}</div>
                    <div className={'item' + (i === mods.length - 1 ? ' off' : '')} onClick={() => { close(); move(i, 1) }}>{t('move_down')}</div>
                    <div className="item" style={{ color: 'var(--bad)' }} onClick={() => { close(); del(m) }}>{t('delete_from_the_library')}</div></>}</Menu></span>
                </div>)
            })}
            {!mods.length && <div style={{ padding: 16 }} className="muted">{t('no_mods_yet')}</div>}
          </div>
        </div>}
        <div className="panel-r" role="region" aria-label={t('in_the_game_now')} style={{ padding: '16px 12px', overflow: 'auto' }}>
          <div className="upper" style={{ marginBottom: 8 }}>{t('in_the_game_now')}</div>
          <div className="gnrow"><div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{instIds.length ? `${instIds.length} mod${instIds.length === 1 ? '' : 's'}` : 'No mods'}</div>
            <div className="small" style={{ color: 'var(--text-2)' }}>{instIds.length ? (names || 'Installed') : 'Original files'}</div></div></div>
          {nm.map(n => <div className="gnrow" key={n.id}><div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{t('new_map')}</div><div className="small" style={{ color: 'var(--text-2)' }}>{n.name}</div></div>
            <button className="sm danger" onClick={() => removeNewMap(n)}>{t('remove')}</button></div>)}
          {mp.map(p => <div className="gnrow" key={p.id}><div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{p.count}{' '}{t('new_mission_c6d5ef')}{p.count === 1 ? '' : 's'}</div><div className="small" style={{ color: 'var(--text-2)' }}>{p.name}</div></div>
            <button className="sm danger" onClick={() => removeMissions(p)}>{t('remove')}</button></div>)}
          {!nm.length && !mp.length && <div className="gnrow"><div className="small" style={{ color: 'var(--text-2)' }}>{t('no_new_maps_or_missions')}</div></div>}
          {ov?.gameplay_plus && <div className="gnrow"><div style={{ flex: 1 }}><div style={{ fontWeight: 600 }}>{t('gameplay')}</div><div className="small" style={{ color: 'var(--text-2)' }}>{t('detected')}</div></div></div>}
          {status.game.tod_hd && <div className="gnrow"><div style={{ flex: 1 }}><div style={{ fontWeight: 600 }}>{t('tod_hd')}</div><div className="small" style={{ color: 'var(--text-2)' }}>{t('detected')}</div></div></div>}
          <GameFiles refresh={() => { refresh(); load() }} />
        </div>
      </div>
      <Pipeline steps={steps} removeLabel={t('remove_all_mods')} onRemove={uninstall} removeDisabled={!!busy || !inst.zip_present} trailing={<TestControl project={project} go={go} />} />
      {piece && <PieceDialog onClose={() => setPiece(false)} />}
    </div>
  )
}
