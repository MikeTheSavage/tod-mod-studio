import React, { useRef, useState } from 'react'
import { Menu, Seg, useUI } from '../ui.jsx'
import { useLib } from '../userlib.js'
import { t } from '../i18n.js'
import { BUILTIN, planApply, planRestore, applyPlan, captureFrom, isEmpty, toFile, fromFile } from './presets.js'

// "Presets" in the Vehicles toolbar: one click applies a driving preset to this vehicle, a group or every car.
// The result is plain numbers in the project (editable, undoable, built and installed like any other change).
export default function DrivePresets({ shipped, vals, row, setVals }) {
  const ui = useUI()
  const [lib, setLib] = useLib('driving')
  const [kind, setKind] = useState('one')
  const [name, setName] = useState('')
  const file = useRef(null)
  const [open, setOpen] = useState(() => new URLSearchParams(location.search).get('open') === 'presets')   // screenshot hook
  const mine = Object.entries(lib || {}).filter(([, p]) => p && typeof p === 'object')
  const target = kind === 'one' ? { kind: 'one', row } : kind === 'all' ? { kind: 'all' } : { kind: 'class', cls: kind }
  const noTarget = kind === 'one' && !row
  const where = kind === 'one' ? row : kind === 'all' ? t('all_cars') : { cars: t('cars'), vans: t('vans'), heavy: t('trucks') }[kind]

  const apply = (p, close) => {
    if (noTarget) return
    const plan = planApply(p, target, shipped)
    setVals(applyPlan(vals, plan))
    ui.say(`${p.name}: ${where}`)
    close && close()
  }
  const restore = close => {
    if (noTarget) return
    setVals(applyPlan(vals, planRestore(target)))
    ui.say(`Vanilla: ${where}`)
    close && close()
  }
  const saveMine = () => {
    const p = captureFrom(vals, shipped, row, name.trim() || 'My preset')
    if (isEmpty(p)) { ui.say(t('change_something_first'), 'bad'); return }
    setLib({ ...(lib || {}), [p.name]: p })
    setName('')
    ui.say(p.name)
  }
  const drop = n => { const o = { ...(lib || {}) }; delete o[n]; setLib(o) }
  const share = p => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([toFile(p)], { type: 'application/json' }))
    a.download = (p.name.replace(/[^A-Za-z0-9 _-]/g, '').trim() || 'driving preset') + '.todms-drive.json'
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(a.href), 4000)
  }
  const load = async e => {
    const f = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!f) return
    const r = fromFile(await f.text())
    if (r.error) { ui.say(r.error, 'bad'); return }
    setLib({ ...(lib || {}), [r.preset.name]: r.preset })
    ui.say(r.dropped ? `${r.preset.name} (${r.dropped} ${t('skipped')})` : r.preset.name)
  }

  return (
    <Menu open={open} setOpen={setOpen} buttonClass="soft" label={<>{t('presets')} {'▾'}</>} title={t('driving_presets')} menuStyle={{ width: 340 }}>
      {close => <div className="dpm">
        <div className="grp">{t('apply_to')}</div>
        <div style={{ padding: '0 4px 6px' }}>
          <Seg value={kind} onChange={setKind} label={t('apply_to')} options={[
            { value: 'one', label: t('this_vehicle'), title: row || undefined }, { value: 'cars', label: t('cars') }, { value: 'vans', label: t('vans') },
            { value: 'heavy', label: t('trucks') }, { value: 'all', label: t('all_cars') }]} />
        </div>
        {BUILTIN.map(p => <div key={p.id} role="menuitem" className={'item' + (noTarget ? ' off' : '')} title={p.tip} onClick={() => apply(p, close)}>{p.name}</div>)}
        <div role="menuitem" className={'item' + (noTarget ? ' off' : '')} title={t('the_values_the_game_shipped_with')} onClick={() => restore(close)}>{t('vanilla')}</div>
        <div className="grp">{t('my_presets')}</div>
        {mine.map(([n, p]) => <div key={n} className="item dprow" role="menuitem" onClick={() => apply({ ...p, name: n }, close)}>
          <span className="dpn">{n}</span>
          <button className="ico" title={t('share')} aria-label={t('share')} onClick={e => { e.stopPropagation(); share({ ...p, name: n }) }}>{'↧'}</button>
          <button className="ico" title={t('delete')} aria-label={t('delete')} onClick={e => { e.stopPropagation(); drop(n) }}>{'×'}</button>
        </div>)}
        <div className="dpsave">
          <input value={name} placeholder={t('name')} aria-label={t('name')} maxLength={40} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') saveMine() }} />
          <button className="sm" disabled={!row} title={t('keep_this_vehicles_changes_as_a_preset')} onClick={saveMine}>{t('save')}</button>
          <button className="sm" title={t('open_a_shared_preset')} onClick={() => file.current && file.current.click()}>{t('import')}</button>
          <input ref={file} type="file" accept=".json,application/json" style={{ display: 'none' }} onChange={load} />
        </div>
      </div>}
    </Menu>
  )
}

