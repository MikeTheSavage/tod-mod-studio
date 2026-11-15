import React, { useEffect, useState } from 'react'
import { get } from './api.js'
import { CAT_LABEL, CAT_COLOR } from './view.js'
import { yawDeg, quatFromYaw } from './coords.js'

const FLAG_BITS = [[1, 'Solid'], [2, 'BulletProof'], [4, 'Opaque'], [8, 'CameraBlock'], [16, 'Trigger'], [32, 'NavBlock'],
  [64, 'Physics'], [128, 'ActivateTriggers']]
const SKIP = new Set(['pos', 'orient', 'parent', 'order', 'unique_id0', 'unique_id1'])

function Num({ value, onCommit, digits = 3 }) {
  const [v, setV] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => { setV(value == null ? '' : String(Math.round(value * 10 ** digits) / 10 ** digits)); setDirty(false) }, [value])
  return <input className="num" value={v} onChange={e => { setV(e.target.value); setDirty(true) }} onFocus={e => e.target.select()}
    onBlur={() => { const n = parseFloat(v); if (dirty && !isNaN(n)) onCommit(n); setDirty(false) }}
    onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} />
}

function Text({ value, onCommit }) {
  const [v, setV] = useState('')
  useEffect(() => { setV(value ?? '') }, [value])
  return <input value={v} onChange={e => setV(e.target.value)} onBlur={() => { if (v !== (value ?? '')) onCommit(v) }}
    onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} />
}

export default function Properties({ e, enums, setProp, setPos, onDelete, onRestore, onDuplicate, setSaveSpot }) {
  const [props, setProps] = useState(null)
  const [showAll, setShowAll] = useState(false)
  useEffect(() => {
    setProps(null)
    if (!showAll || e.isNew) return
    get('/api/entity', { entry: e.entry, k: e.k, node: e.node }).then(setProps).catch(() => setProps({ error: true }))
  }, [e.id, showAll])
  const ro = !e.ed
  const sub = e.sub || {}
  const flags = sub.CollisionFlags
  const yaw = yawDeg(e.rot)
  return (
    <div className="box props">
      <h3><span className="swatch" style={{ background: CAT_COLOR[e.cat] }} /> {e.name || (e.type || '').replace(/\(.*\)/, '')}</h3>
      <div className="meta">
        <div>{CAT_LABEL[e.cat] || e.cat} <i>{e.type}</i></div>
        <div>{(e.entry || '').split('/').pop()}{e.target?.frag ? ' / ' + e.target.frag.split('/').pop() : ''} {e.node || ''}</div>
        {e.ri != null && <div>save index {e.ri}</div>}
        {e.isNew && <div className="good">new object (added after every existing one: old saves keep working)</div>}
        {e.off && <div className="warn">disabled at load: appears when a trigger enables its group</div>}
        {e.deleted && <div className="bad">{e.deleted === 'remove' ? 'removed' : 'retired (moved 5 km below the world, collision off)'} by this mod</div>}
        {ro && <div className="warn">read only: part of a prefab placed several times (a change would hit every copy)</div>}
      </div>
      <fieldset disabled={ro || !!e.deleted}>
        <label>Name <Text value={e.name} onCommit={v => setProp(e, 'name', v)} /></label>
        <div className="row3">
          <label>X <Num value={e.pos[0]} onCommit={v => setPos(e, [v, e.pos[1], e.pos[2]])} /></label>
          <label>Y (up) <Num value={e.pos[1]} onCommit={v => setPos(e, [e.pos[0], v, e.pos[2]])} /></label>
          <label>Z <Num value={e.pos[2]} onCommit={v => setPos(e, [e.pos[0], e.pos[1], v])} /></label>
        </div>
        <label>Turn (degrees about up) <Num value={yaw} digits={1} onCommit={v => setPos(e, e.pos, quatFromYaw(v))} /></label>
        {e.size && <div className="row3">
          <label>Width <Num value={e.size[0]} onCommit={v => setProp(e, 'width', v)} /></label>
          <label>Height <Num value={e.size[1]} onCommit={v => setProp(e, 'height', v)} /></label>
          <label>Length <Num value={e.size[2]} onCommit={v => setProp(e, 'length', v)} /></label>
        </div>}
        {flags != null && <div className="flags">
          <div className="sub">Collision flags ({flags})</div>
          {FLAG_BITS.map(([b, n]) => <label key={b} className="check"><input type="checkbox" checked={!!(flags & b)}
            onChange={ev => setProp(e, 'CollisionFlags', ev.target.checked ? (flags | b) : (flags & ~b))} /> <span>{n}</span></label>)}
        </div>}
        {['GoodieSubType', 'WeaponSubType', 'VehicleSubType'].filter(k => sub[k] != null).map(k => (
          <label key={k}>{k.replace('SubType', ' type')}
            <select value={String(sub[k])} onChange={ev => setProp(e, k, parseInt(ev.target.value))}>
              {Object.entries(enums[k] || { [sub[k]]: String(sub[k]) }).map(([v, n]) => <option key={v} value={v}>{v}: {n}</option>)}
            </select>
          </label>))}
        {sub.Respawnable != null && <label className="check"><input type="checkbox" checked={!!sub.Respawnable}
          onChange={ev => setProp(e, 'Respawnable', ev.target.checked)} /> <span>Respawns</span></label>}
      </fieldset>
      <div className="btns">
        <button onClick={onDuplicate} disabled={ro}>Duplicate</button>
        {e.deleted ? <button onClick={onRestore}>Restore</button> : <button onClick={onDelete} disabled={ro}>Delete</button>}
        <button onClick={() => setSaveSpot({ pos: e.pos, yaw, name: e.name || e.type })}>Test save here</button>
      </div>
      {!e.isNew && <div className="allprops">
        <label className="check"><input type="checkbox" checked={showAll} onChange={ev => setShowAll(ev.target.checked)} /> <span>All properties</span></label>
        {showAll && !props && <p className="muted">loading</p>}
        {showAll && props?.props && <table><tbody>
          {props.props.filter(p => !SKIP.has(p.name)).map(p => (
            <tr key={p.name}><td title={p.type}>{p.name}</td><td>
              {ro || e.deleted ? <span>{JSON.stringify(p.value)}</span> :
                p.type === 'truth' ? <input type="checkbox" checked={!!(e.props?.[p.name] ?? p.value)} onChange={ev => setProp(e, p.name, ev.target.checked)} /> :
                p.type === 'number' ? <Num value={e.props?.[p.name] ?? p.value} onCommit={v => setProp(e, p.name, v)} /> :
                p.type === 'integer' ? <Num value={e.props?.[p.name] ?? p.value} digits={0} onCommit={v => setProp(e, p.name, Math.round(v))} /> :
                p.type === 'string' ? <Text value={e.props?.[p.name] ?? p.value} onCommit={v => setProp(e, p.name, v)} /> :
                <span className="muted">{JSON.stringify(p.value)?.slice(0, 60)}</span>}
            </td></tr>))}
        </tbody></table>}
      </div>}
    </div>
  )
}
