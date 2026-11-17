import React, { useEffect, useState } from 'react'
import { get } from './api.js'
import { openHelp } from './helpstore.js'
import { t } from './i18n.js'

const CARDS = [
  ['Edit the world', 'Change an existing level', 'level'],
  ['Add content', 'Make a mission', 'mtpl'],
  ['Add content', 'Make a new map', 'newmaps'],
  ['Add content', 'Bring in a model', 'import'],
  ['Add content', 'Change a texture', 'textures'],
  ['Tune', 'Change how the game feels', 'data'],
  ['Play and share', 'Install or share mods', 'mods'],
  ['Play and share', 'Make a test save', 'save'],
]
const NAMES = { level: 'Level editor', routes: 'Routes', sections: 'Sections', collision: 'Collision', missions: 'Mission logic', mtpl: 'Mission templates',
  newmaps: 'New maps', import: 'Import model', textures: 'Textures', data: 'Game data', mods: 'Mods and install', save: 'Test saves', assets: 'Asset catalogue', settings: 'Settings' }

export default function Home({ project, go, dirty, changes, openFirstRun, status }) {
  const [catalog, setCatalog] = useState(null)
  useEffect(() => { get('/api/catalog').then(setCatalog).catch(() => {}) }, [])
  let last = null
  try { last = localStorage.getItem('todms.last') } catch { /* no storage */ }
  const v = project.view || status.settings?.last_view
  const map = v?.map && catalog?.maps.find(m => m.id === v.map)
  const sect = map && v.section && map.sections.find(s => s.entry === v.section)
  const where = [map?.title, sect?.title].filter(Boolean).join(' › ')
  const target = last && NAMES[last] ? last : 'level'
  const show = changes > 0 || !!v?.map || !!last
  return (
    <div className="center-page">
      <div style={{ width: '100%', maxWidth: 880 }}>
        <h1 style={{ marginBottom: 20 }}>{t('what_do_you_want_to_do')}</h1>
        {show && <div className="card" style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: '12px 16px', borderColor: 'var(--line-strong)', marginBottom: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="upper">{t('pick_up_where_you_left_off')}</div>
            <div style={{ fontWeight: 600, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}
              <span style={{ fontWeight: 400, color: 'var(--text-2)' }}> {'·'} {NAMES[target]}{where ? ' · ' + where : ''}
                {changes > 0 ? ` · ${changes} ${dirty ? 'unsaved ' : ''}change${changes === 1 ? '' : 's'}` : ''}</span></div>
          </div>
          <button className="primary" onClick={() => go(target)}>{t('continue')}</button>
        </div>}
        <div className="cards" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
          {CARDS.map(c => <button key={c[1]} className="card" style={{ minHeight: 84 }} onClick={() => go(c[2])}>
            <span className="area">{c[0]}</span><span className="ct">{c[1]}</span></button>)}
          <button className="card" style={{ minHeight: 84 }} onClick={() => openHelp({ tab: 'lessons' })}>
            <span className="area">{t('learn')}</span><span className="ct">{t('take_a_lesson_or_open_an')}</span></button>
        </div>
        <div style={{ marginTop: 16, fontSize: 12.5, color: 'var(--text-3)' }}><a href="#" onClick={e => { e.preventDefault(); openFirstRun() }}>{t('first_run_setup')}</a></div>
      </div>
    </div>
  )
}
