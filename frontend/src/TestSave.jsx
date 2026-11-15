import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'

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
  useEffect(() => { if (spot) { setPos(spot.pos.map(v => Math.round(v * 100) / 100).join(', ')); setYaw(String(Math.round(spot.yaw))) } }, [spot])
  const make = async () => {
    setErr(null); setRes(null)
    try {
      const p = pos.trim() ? pos.split(',').map(Number) : null
      if (p && (p.length !== 3 || p.some(isNaN))) throw new Error('position: three numbers x, y, z')
      const r = await post('/api/saves/make', { source: src, pos: p, yaw: yaw === '' ? null : Number(yaw), heal, weapons,
        install_as: installAs || null })
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
    <div className="page">
      <section className="box">
        <h3>Start a test save at a chosen spot</h3>
        <p className="muted">Takes a copy of one of your saves and puts Ram at the spot (pick one in the level editor
          with "Test save here"). The new save is written to the app folder; installing it into the game's save
          folder backs up the slot it replaces. The save should come from the same map as the spot.</p>
        {slots && <label>Your save to start from ({slots.folder})
          <select value={src} onChange={e => setSrc(e.target.value)}>
            <option value="">choose a save</option>
            {slots.slots.map(s => <option key={s.path} value={s.path}>{s.name} {s.summary ? `- ${s.summary.submap || s.summary.map || ''} at ${(s.pos || []).map(v => Math.round(v)).join(', ')}` : s.error || ''}</option>)}
          </select></label>}
        {slots && !slots.slots.length && <p className="warn">No save slots found in {slots.folder}.</p>}
        <label>Position x, y, z (game coordinates, metres){spot && <i> from {spot.name}</i>}
          <input value={pos} onChange={e => setPos(e.target.value)} placeholder="keep the save's position" /></label>
        <label>Facing (degrees) <input value={yaw} onChange={e => setYaw(e.target.value)} placeholder="keep" /></label>
        <label className="check"><input type="checkbox" checked={heal} onChange={e => setHeal(e.target.checked)} /> <span>Full health</span></label>
        <label className="check"><input type="checkbox" checked={weapons} onChange={e => setWeapons(e.target.checked)} /> <span>All weapons, full ammo</span></label>
        <label>Install into the game's save folder as (optional, e.g. Slot09)
          <input value={installAs} onChange={e => setInstallAs(e.target.value)} placeholder="leave empty: only write the file" /></label>
        <button className="primary" disabled={!src} onClick={make}>Make the test save</button>
        {err && <p className="bad">{err}</p>}
        {res && <div className="result"><p>Written {res.path} ({res.bytes} bytes), Ram at {res.player?.map(v => Math.round(v * 100) / 100).join(', ')}.</p>
          {res.install && <p>Installed as {res.install.installed}{res.install.backup ? `, previous slot backed up to ${res.install.backup}` : ''}.</p>}</div>}
      </section>
      <section className="box">
        <h3>Update a save for new missions</h3>
        <p className="warn"><b>Why:</b> a save made before you installed new missions does not know about them. Without this update, pressing the use key at a new mission giver closes the game.
          Saves made after the install are fine. A new game needs nothing. For a giver box in an existing map section the update also adds the box's script thread when the save holds that section.</p>
        <p className="muted">This makes an updated COPY of a save in the app folder; your save is never changed. It is never done automatically. Installing the copy into the
          game's save folder (optional) backs up the slot it replaces first. Update the save again after you install or remove other new missions.</p>
        {slots && <label>Save to update
          <select value={mig.src} onChange={e => setMig({ ...mig, src: e.target.value })}>
            <option value="">choose a save</option>
            {slots.slots.map(s => <option key={s.path} value={s.path}>{s.name}</option>)}</select></label>}
        <label>Install the updated copy into the game's save folder as (optional, e.g. Slot09)
          <input value={mig.installAs} onChange={e => setMig({ ...mig, installAs: e.target.value })} placeholder="leave empty: only write the copy" /></label>
        <button className="primary" disabled={!mig.src || mig.busy} onClick={migrate}>{mig.busy ? 'Working...' : 'Make an updated copy'}</button>
        {mig.err && <p className="bad">{mig.err}</p>}
        {mig.res && <div className="result"><p>Updated copy written to {mig.res.path} ({mig.res.missions} mission{mig.res.missions === 1 ? '' : 's'}).</p>
          {mig.res.givers_patched > 0 && <p>{mig.res.givers_patched} giver box{mig.res.givers_patched === 1 ? '' : 'es'} in existing map sections got the script thread they need to offer from this save.</p>}
          {(mig.res.notes || []).map((n, i) => <p key={i} className="warn">{n}</p>)}
          {mig.res.install && <p>Installed as {mig.res.install.installed}{mig.res.install.backup ? `, the slot it replaced was backed up to ${mig.res.install.backup}` : ''}.</p>}</div>}
      </section>
    </div>
  )
}
