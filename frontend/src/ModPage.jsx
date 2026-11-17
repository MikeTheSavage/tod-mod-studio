import React, { useState } from 'react'
import { Seg, Switch } from './ui.jsx'
import { t } from './i18n.js'

// The mod page: what a person sees before they add the mod. Edits go into project.page / project.requires (saved with the mod).
const MAX_SHOTS = 6

export default function ModPage({ project, replace, library = [] }) {
  const page = project.page || {}
  const req = project.requires || {}
  const setPage = patch => replace({ ...project, page: { ...page, ...patch } })
  const setReq = patch => {
    const r = { ...req, ...patch }
    for (const k of Object.keys(r)) if (r[k] === undefined || r[k] === '' || (Array.isArray(r[k]) && !r[k].length)) delete r[k]
    replace({ ...project, requires: r })
  }
  const [dep, setDep] = useState('')
  const log = page.changelog || []
  const shots = page.screenshots || []
  const gp = req.gameplay_plus === true ? 'needs' : req.gameplay_plus === false ? 'original' : 'any'
  const others = library.filter(m => m.id !== project.id && !(req.mods || []).some(d => d.id === m.id))

  return (
    <div className="modpage">
      <div className="mp-grid">
        <label>{t('version')}<input value={page.version || ''} placeholder="1.0" onChange={e => setPage({ version: e.target.value })} aria-label={t('mod_version')} /></label>
        <label>{t('author')}<input value={project.author || ''} onChange={e => replace({ ...project, author: e.target.value })} aria-label={t('author')} /></label>
        <label className="mp-wide">{t('credits')}<textarea rows={2} value={page.credits || ''} onChange={e => setPage({ credits: e.target.value })} aria-label={t('credits')} /></label>
        <label className="mp-wide">{t('licence')}<input value={page.license || ''} onChange={e => setPage({ license: e.target.value })} aria-label={t('licence')} /></label>
        <div className="row mp-wide" title={t('off_the_mod_can_be_switched')}>
          <Switch label={t('others_may_reuse_or_edit_this')} on={page.reuse !== false} onChange={v => setPage({ reuse: v })} />
          <span>{t('others_may_reuse_or_edit')}</span></div>
      </div>

      <h4>{t('needs')}</h4>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Seg value={gp} onChange={v => setReq({ gameplay_plus: v === 'needs' ? true : v === 'original' ? false : undefined })}
          options={[{ value: 'any', label: t('any_game') }, { value: 'needs', label: t('gameplay') }, { value: 'original', label: t('original_only') }]} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="muted">{t('mod_studio')}</span>
          <input style={{ width: 80 }} value={req.min_app || ''} placeholder={t('any')} onChange={e => setReq({ min_app: e.target.value })} aria-label={t('lowest_mod_studio_version')} /></label>
      </div>
      <div className="chips" style={{ marginTop: 8 }}>
        {(req.mods || []).map(d => {
          const m = library.find(x => x.id === d.id)
          return <span key={d.id} className="chip on" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {m?.name || d.id}
            <input aria-label={'Lowest version of ' + (m?.name || d.id)} style={{ width: 54, height: 20 }} value={d.version || ''} placeholder={t('any')}
              onChange={e => setReq({ mods: req.mods.map(x => x.id === d.id ? { ...x, version: e.target.value } : x) })} />
            <button className="sm ghost" aria-label={t('remove')} onClick={() => setReq({ mods: req.mods.filter(x => x.id !== d.id) })}>{'×'}</button></span>
        })}
        {!!others.length && <select value={dep} aria-label={t('needs_another_mod')} style={{ width: 170 }} onChange={e => { setDep(''); if (e.target.value) setReq({ mods: [...(req.mods || []), { id: e.target.value, version: '' }] }) }}>
          <option value="">{t('needs_a_mod')}{'…'}</option>{others.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>}
      </div>

      <h4>{t('changelog')}</h4>
      {log.map((c, i) => <div key={i} className="row" style={{ gap: 6, marginBottom: 4, alignItems: 'flex-start' }}>
        <input style={{ width: 64 }} value={c.version || ''} placeholder="1.0" aria-label={t('changelog_version')} onChange={e => setPage({ changelog: log.map((x, j) => j === i ? { ...x, version: e.target.value } : x) })} />
        <input className="grow" value={c.text || ''} aria-label={t('what_changed')} onChange={e => setPage({ changelog: log.map((x, j) => j === i ? { ...x, text: e.target.value } : x) })} />
        <button className="sm ghost" aria-label={t('remove')} onClick={() => setPage({ changelog: log.filter((_, j) => j !== i) })}>{'×'}</button></div>)}
      <button className="sm" onClick={() => setPage({ changelog: [{ version: page.version || '1.0', date: new Date().toISOString().slice(0, 10), text: '' }, ...log] })}>{t('add_an_entry')}</button>

      <h4 title={t('take_pictures_with_capture_in_the')}>{t('pictures')}{' '}<span className="muted" style={{ fontWeight: 400 }}>{shots.length}/{MAX_SHOTS}</span></h4>
      <div className="shots">
        {shots.map((s, i) => <figure key={i}>
          <img alt={s.caption || 'Screenshot ' + (i + 1)} src={'data:image/jpeg;base64,' + s.data} />
          <button className="sm" onClick={() => setPage({ screenshots: shots.filter((_, j) => j !== i) })}>{t('remove')}</button></figure>)}
        {!shots.length && <div className="muted small">{t('no_pictures_yet')}</div>}
      </div>
    </div>
  )
}
