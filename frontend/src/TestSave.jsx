import React, { useEffect, useMemo, useState } from 'react'
import { get, post, runJob } from './api.js'
import { Advanced, Switch, useUI } from './ui.jsx'
import View3D from './View3D.jsx'
import { useBundle, getCatalog, pickOfSave, CONTEXT_LAYERS } from './levelLoad.js'
import { yawOrient } from './LoaderTopView.jsx'
import { t as tr } from './i18n.js'

export const SlotList = ({ slots, value, onChange }) => (
  <div role="radiogroup" aria-label={tr('saves')} style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-md)', overflow: 'hidden', maxHeight: 240, overflowY: 'auto' }}>
    {slots.map(s => {
      const on = value === s.path
      return (
        <div key={s.path} role="radio" aria-checked={on} tabIndex={0} onClick={() => onChange(s.path)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onChange(s.path)}
             style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44, padding: '4px 12px', borderBottom: '1px solid var(--line)', cursor: 'pointer', background: on ? 'var(--surface-2)' : 'transparent' }}>
          <span style={{ flex: 'none', width: 14, height: 14, borderRadius: '50%', border: '1.5px solid ' + (on ? 'var(--accent)' : 'var(--line-strong)'), display: 'grid', placeItems: 'center' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: on ? 'var(--accent)' : 'transparent' }} /></span>
          <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 500 }}>{s.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{s.summary ? `${s.summary.submap || s.summary.map || ''} at ${(s.pos || []).map(v => Math.round(v)).join(', ')}` : s.error || ''}</div></div>
        </div>)
    })}
  </div>
)

const snapSize = n => n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB'

// The saves folder is copied before every install and uninstall (the last 20 are kept); restoring one copies the current state first.
function Snapshots() {
  const ui = useUI()
  const [list, setList] = useState(null)
  const load = () => get('/api/snapshots').then(r => setList(r.snapshots)).catch(e => ui.say(e.message, 'bad'))
  useEffect(() => { load() }, [])
  const restore = async s => {
    if (!(await ui.confirm({ title: tr('put_these_saves_back'), body: `${s.label}, ${(s.created || '').replace('T', ' ')}. The saves you have now are copied first.`, ok: tr('restore_saves') }))) return
    try { await post('/api/snapshots/restore', { id: s.id }); ui.say(tr('saves_restored')); load() } catch (e) { ui.say(e.message, 'bad') }
  }
  return (
    <section className="card" aria-label={tr('save_copies')} style={{ gap: 10 }}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{tr('save_copies')}</div>
      {list && !list.length && <p className="muted small">{tr('none_yet_a_copy_is_made')}</p>}
      {list && list.length > 0 && <div style={{ border: '1px solid var(--line)', borderRadius: 'var(--r-md)', overflow: 'hidden', maxHeight: 260, overflowY: 'auto' }}>
        {list.map(s => <div key={s.id} className="row" style={{ gap: 10, minHeight: 44, padding: '4px 12px', borderBottom: '1px solid var(--line)' }}>
          <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label}</div>
            <div className="small muted">{(s.created || '').replace('T', ' ')} {'·'} {s.files}{' '}{tr('files')}{' '}{'·'} {snapSize(s.bytes)}</div></div>
          <button className="sm" onClick={() => restore(s)}>{tr('restore')}</button></div>)}
      </div>}
    </section>
  )
}

export default function TestSave({ status, spot }) {
  const [slots, setSlots] = useState(null)
  const [src, setSrc] = useState('')
  const [pos, setPos] = useState(spot ? spot.pos.map(v => Math.round(v * 100) / 100).join(', ') : '')
  const [yaw, setYaw] = useState(spot ? String(Math.round(spot.yaw)) : '')
  const [heal, setHeal] = useState(true)
  const [weapons, setWeapons] = useState(false)
  const [installAs, setInstallAs] = useState('')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { get('/api/saves').then(setSlots).catch(e => setErr(e.message)) }, [])
  // the spot picker: the save's map in 3D; click to set the start position, press and drag to set the facing too
  const [maps, setMaps] = useState(null)
  const [mapId, setMapId] = useState('auto')
  const [placing, setPlacing] = useState(false)
  useEffect(() => { getCatalog().then(setMaps).catch(() => {}) }, [])
  useEffect(() => {      // ?slot=3 picks the fourth save (screenshots)
    const q = new URLSearchParams(location.search).get('slot')
    if (q != null && slots?.slots[Number(q)]) setSrc(slots.slots[Number(q)].path)
  }, [slots])
  const slot = slots?.slots.find(x => x.path === src)
  const mapPick = useMemo(() => {
    if (!maps || mapId === 'none') return null
    if (mapId !== 'auto') return { map: mapId, section: null, missions: [], blockOnly: true }
    if (slot?.summary) return pickOfSave(maps, slot.summary)
    return null
  }, [maps, mapId, slot])
  const lvl = useBundle(mapPick, !!mapPick)
  const parsed = (() => { const p = pos.split(',').map(t => Number(t.trim())); return p.length === 3 && !p.some(v => isNaN(v)) && pos.trim() ? p : null })()
  const yawNum = yaw === '' || isNaN(Number(yaw)) ? 0 : Number(yaw)
  const overlays = useMemo(() => [
    ...(slot?.pos ? [{ id: 'save', kind: 'point', pos: slot.pos, color: '#8491a1', label: tr('in_the_save'), always: true, pickable: false }] : []),
    ...(parsed ? [{ id: 'start', kind: 'point', pos: parsed, yaw: yawNum, arrow: true, color: '#f2a541', label: tr('start'), always: true, selected: true, pickable: false }] : [])],
    [slot, pos, yaw])
  const focus = useMemo(() => { const p = parsed || slot?.pos; return p ? { pos: p, dist: 90, reset: true } : null }, [src, !!parsed, mapPick?.map, mapPick?.section])
  const r2 = v => Math.round(v * 100) / 100
  const setSpot = (p, facing) => { setPos(p.map(r2).join(', ')); if (facing != null) setYaw(String(Math.round(facing))) }
  useEffect(() => { if (spot) { setPos(spot.pos.map(v => Math.round(v * 100) / 100).join(', ')); setYaw(String(Math.round(spot.yaw))) } }, [spot])
  const make = async () => {
    setErr(null); setRes(null)
    try {
      const p = pos.trim() ? pos.split(',').map(Number) : null
      if (p && (p.length !== 3 || p.some(isNaN))) throw new Error('The position needs three numbers: x, height and z, separated by commas.')
      const r = await post('/api/saves/make', { source: src, pos: p, yaw: yaw === '' ? null : Number(yaw), heal, weapons, install_as: installAs || null })
      setRes(r)
    } catch (e) { setErr(e.message) }
  }
  const [mig, setMig] = useState({ src: '', installAs: '', res: null, err: null, busy: false })
  const migrate = async () => {
    setMig(m => ({ ...m, res: null, err: null, busy: true }))
    try {
      const r = await runJob('/api/missiontpl/savefix', { source: mig.src, install_as: mig.installAs || null })
      setMig(m => ({ ...m, res: r, busy: false }))
    } catch (e) { setMig(m => ({ ...m, err: e.message, busy: false })) }
  }
  return (
    <div className="screen" style={{ overflow: 'auto', padding: 20 }}>
      <div className="testgrid">
        <section className="card" aria-label={tr('start_at_a_chosen_spot')} style={{ gap: 10 }}>
          <div><div style={{ fontSize: 16, fontWeight: 600 }}>{tr('start_at_a_chosen_spot')}</div>
</div>
          {slots && <div><div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }}><span title={slots.folder}>{tr('start_from_one_of_your_saves')}</span></div>
            {slots.slots.length ? <SlotList slots={slots.slots} value={src} onChange={setSrc} /> : <p className="warn">{tr('no_save_slots_found_in')}{' '}{slots.folder}.</p>}</div>}
          <label>{tr('position_x_height_z_game_coordinates')}{spot && <span className="muted"> {'·'}{' '}{tr('from_0b1e95')}{' '}{spot.name}</span>}
            <input value={pos} onChange={e => setPos(e.target.value)} placeholder={tr('keep_the_save_s_position')} style={{ fontVariantNumeric: 'tabular-nums' }} /></label>
          <label>{tr('facing_degrees')}{' '}<input value={yaw} onChange={e => setYaw(e.target.value)} placeholder={tr('keep_it')} /></label>
          <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
            <label className="check"><Switch label={tr('full_health')} on={heal} onChange={setHeal} />{' '}{tr('full_health')}</label>
            <label className="check"><Switch label={tr('all_weapons_full_ammo')} on={weapons} onChange={setWeapons} />{' '}{tr('all_weapons_full_ammo')}</label></div>
          <Advanced note={tr('put_it_into_the_game')}><label>{tr('put_it_into_the_game_s')}<input value={installAs} onChange={e => setInstallAs(e.target.value)} placeholder={tr('leave_empty_to_only_write_a')} /></label>
</Advanced>
          <div className="row" style={{ gap: 10 }}><button className="primary" style={{ height: 32, padding: '0 16px', fontSize: 13 }} disabled={!src} onClick={make}>{tr('make_test_save')}</button>
            <span className="muted small">{tr('use_a_save_from_the_spot')}</span></div>
          {err && <div className="callout bad">{err}</div>}
          {res && <div className="callout" style={{ display: 'flex', gap: 8, padding: '8px 12px' }}><span style={{ color: 'var(--ok)', fontWeight: 700 }}>{'✓'}</span>
            <span style={{ overflowWrap: 'anywhere' }}>{tr('test_save_written_to')}{' '}{res.path}.
              {res.install && ` Installed as ${res.install.installed}${res.install.backup ? `, previous slot backed up to ${res.install.backup}` : ''}.`}</span></div>}
        </section>
        <section className="card" aria-label={tr('pick_the_spot')} style={{ gap: 8, padding: 0, overflow: 'hidden' }}>
          <div className="row" style={{ padding: '8px 12px', gap: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }} className="grow">{tr('pick_the_spot')}</div>
            <select aria-label={tr('map')} style={{ width: 'auto', maxWidth: 220 }} value={mapId} onChange={e => setMapId(e.target.value)}>
              <option value="auto">{tr('map_of_the_save')}</option><option value="none">{tr('no_map')}</option>
              {(maps?.maps || []).map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select>
            <button className={placing ? 'primary' : ''} onClick={() => setPlacing(!placing)} title={tr('click_to_set_the_spot_press')}>{tr('place_c32a01')}</button>
            {lvl.busy && <span className="small muted">{lvl.busy}{'…'}</span>}{lvl.err && <span className="small warn">{tr('no_map')}</span>}
          </div>
          <div style={{ display: 'flex', height: 460 }}>
            <View3D defaultMode="3d" bundle={lvl.bundle} view={lvl.view} layers={CONTEXT_LAYERS} overlays={overlays} focus={focus}
              onGround={(p, ev, geometry) => { if (!placing) setSpot([p[0], geometry ? p[1] : (parsed ? parsed[1] : 0), p[2]]) }}
              placing={placing ? { kind: 'spot', label: tr('start'), arrow: true, facingDrag: true, color: '#f2a541', yaw: yawNum } : null}
              onPlace={(p, facing) => { setSpot(p, facing); setPlacing(false) }} />
          </div>
        </section>
        <section className="card" aria-label={tr('update_a_save_for_new_missions')} style={{ gap: 10 }}>
          <div><div style={{ fontSize: 16, fontWeight: 600 }}>{tr('update_a_save_for_new_missions')}</div>
            <div className="warn" style={{ fontSize: 12.5 }}>{tr('old_saves_close_the_game_at')}</div></div>
          {slots && (slots.slots.length ? <SlotList slots={slots.slots} value={mig.src} onChange={p => setMig({ ...mig, src: p })} /> : <p className="warn">{tr('no_save_slots_found')}</p>)}
          <Advanced note={tr('put_it_into_the_game')}><label>{tr('put_the_copy_into_the_game')}<input value={mig.installAs} onChange={e => setMig({ ...mig, installAs: e.target.value })} placeholder={tr('leave_empty_to_only_write_a')} /></label></Advanced>
          <div className="row" style={{ gap: 10 }}><button className="primary" style={{ height: 32, padding: '0 16px', fontSize: 13 }} disabled={!mig.src || mig.busy} onClick={migrate}>{mig.busy ? 'Working…' : 'Make an updated copy'}</button>
</div>
          {mig.err && <div className="callout bad">{mig.err}</div>}
          {mig.res && <div className="callout" style={{ padding: '8px 12px' }}><div style={{ display: 'flex', gap: 8 }}><span style={{ color: 'var(--ok)', fontWeight: 700 }}>{'✓'}</span>
            <span style={{ overflowWrap: 'anywhere' }}>{tr('updated_copy_written_to')}{' '}{mig.res.path}.</span></div>
            {mig.res.givers_patched > 0 && <p className="small">{mig.res.givers_patched}{' '}{tr('giver_box')}{mig.res.givers_patched === 1 ? '' : 'es'}{' '}{tr('updated')}</p>}
            {(mig.res.notes || []).map((n, i) => <p key={i} className="warn small">{n}</p>)}
            {mig.res.install && <p className="small">{tr('installed_as')}{' '}{mig.res.install.installed}{mig.res.install.backup ? `, the slot it replaced was backed up to ${mig.res.install.backup}` : ''}.</p>}</div>}
        </section>
        <Snapshots />
      </div>
    </div>
  )
}
