import React, { useEffect, useState } from 'react'
import { get } from './api.js'
import { CAT_LABEL, catColor } from './view.js'
import { yawDeg, quatFromYaw } from './coords.js'
import { Advanced, Switch } from './ui.jsx'
import { t } from './i18n.js'

const FLAG_BITS = [[1, 'Solid'], [2, 'BulletProof'], [4, 'Opaque'], [8, 'CameraBlock'], [16, 'Trigger'], [32, 'NavBlock'],
  [64, 'Physics'], [128, 'ActivateTriggers']]
const SKIP = new Set(['pos', 'orient', 'parent', 'order', 'unique_id0', 'unique_id1'])
const AX = ['var(--ax-x)', 'var(--ax-y)', 'var(--ax-z)']
const KIND_NAME = { character: 'Enemy', pickup: 'Pickup', weapon: 'Weapon', vehicle: 'Vehicle', trigger: 'Trigger box', wall: 'Invisible wall',
  navblock: 'Nav blocker', route: 'Route point', marker: 'Marker', havoc: 'Destructible' }

// A number that is committed when the field loses focus or Enter is pressed.
function Num({ value, onCommit, digits = 3, label }) {
  const [v, setV] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => { setV(value == null ? '' : String(Math.round(value * 10 ** digits) / 10 ** digits)); setDirty(false) }, [value])
  return <input className="num" aria-label={label} value={v} onChange={e => { setV(e.target.value); setDirty(true) }} onFocus={e => e.target.select()}
    onBlur={() => { const n = parseFloat(v); if (dirty && !isNaN(n)) onCommit(n); setDirty(false) }}
    onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} />
}

function Text({ value, onCommit, label }) {
  const [v, setV] = useState('')
  useEffect(() => { setV(value ?? '') }, [value])
  return <input aria-label={label} value={v} onChange={e => setV(e.target.value)} onBlur={() => { if (v !== (value ?? '')) onCommit(v) }}
    onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }} />
}

const Axis = ({ i, name, children }) => <label className="axis" style={{ margin: 0 }}><span style={{ color: AX[i] }}>{name}</span>{children}</label>

export default function Properties({ e, enums, setProp, setPos, onDelete, onRestore, onDuplicate, onFocus, setSaveSpot, testHere }) {
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
  const subKeys = ['GoodieSubType', 'WeaponSubType', 'VehicleSubType'].filter(k => sub[k] != null)
  const advCount = (flags != null ? 1 : 0) + 1
  const title = e.name || (e.type || '').replace(/\(.*\)/, '')
  return (
    <>
      <div className="panel-h">
        <span className="swatch" style={{ background: catColor(e.cat) }} />
        <div className="grow"><div className="t" title={[(e.entry || '').split('/').pop(), e.target?.frag ? e.target.frag.split('/').pop() : '', e.node || '', e.ri != null ? 'save index ' + e.ri : ''].filter(Boolean).join(' / ')} style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</div>
          <div className="s" style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{KIND_NAME[e.cat] || CAT_LABEL[e.cat] || e.cat}</div></div>
        <button className="sm ghost" onClick={onFocus} title={t('frame_the_object_f')}>{t('focus')}{' '}<span className="kbd">{t('f')}</span></button>
      </div>
      <div className="panel-b">
        {(e.isNew || e.off || e.deleted || ro) && <div className="small" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {e.isNew && <div className="good">{t('new_object')}</div>}
          {e.off && <div className="warn">{t('off_until_a_trigger_switches_it')}</div>}
          {e.deleted && <div className="bad">{e.deleted === 'remove' ? 'Removed' : 'Retired'}{' '}{t('by_this_mod')}</div>}
          {ro && <div className="warn">{t('read_only_shared_prefab')}</div>}
        </div>}
        <fieldset disabled={ro || !!e.deleted} style={{ border: 0, padding: 0, margin: 0, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="prow">
            <div className="k">{t('name')}</div><Text label={t('name')} value={e.name} onCommit={v => setProp(e, 'name', v)} />
            {subKeys.map(k => <React.Fragment key={k}><div className="k">{k.replace('SubType', '').replace('Goodie', 'Kind')}</div>
              <select aria-label={k} value={String(sub[k])} onChange={ev => setProp(e, k, parseInt(ev.target.value))}>
                {Object.entries(enums[k] || { [sub[k]]: String(sub[k]) }).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select></React.Fragment>)}
          </div>
          <div className="upper" style={{ marginTop: 8 }}>{t('position')}</div>
          <div className="axes">
            <Axis i={0} name="X"><Num label={t('x')} value={e.pos[0]} onCommit={v => setPos(e, [v, e.pos[1], e.pos[2]])} /></Axis>
            <Axis i={1} name="Y"><Num label={t('y_up')} value={e.pos[1]} onCommit={v => setPos(e, [e.pos[0], v, e.pos[2]])} /></Axis>
            <Axis i={2} name="Z"><Num label={t('z_909f99')} value={e.pos[2]} onCommit={v => setPos(e, [e.pos[0], e.pos[1], v])} /></Axis>
          </div>
          <div className="prow"><div className="k">{t('turn_368e80')}</div>
            <div className="numfield"><Num label={t('turn_degrees_about_up')} value={yaw} digits={1} onCommit={v => setPos(e, e.pos, quatFromYaw(v))} /><span className="u">{'°'}</span></div></div>
          {e.size && <><div className="upper" style={{ marginTop: 8 }}>{t('size')}</div>
            <div className="axes">
              <Axis i={0} name="W"><Num label={t('width')} value={e.size[0]} onCommit={v => setProp(e, 'width', v)} /></Axis>
              <Axis i={1} name="H"><Num label={t('height')} value={e.size[1]} onCommit={v => setProp(e, 'height', v)} /></Axis>
              <Axis i={2} name="L"><Num label={t('length')} value={e.size[2]} onCommit={v => setProp(e, 'length', v)} /></Axis>
            </div></>}
          {sub.Respawnable != null && <div className="row" style={{ minHeight: 28 }}><Switch label={t('respawns')} on={!!sub.Respawnable} onChange={v => setProp(e, 'Respawnable', v)} /><span>{t('comes_back_after_it_is_picked')}</span></div>}
        </fieldset>
        <Advanced title={t('advanced')} note={flags != null ? 'collision flags, all properties' : 'all properties'}>
          <fieldset disabled={ro || !!e.deleted} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            {flags != null && <><div className="upper" style={{ margin: '6px 0 2px' }}>{t('collision_flags')}{flags})</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
                {FLAG_BITS.map(([b, n]) => <label key={b} className="check"><input type="checkbox" checked={!!(flags & b)}
                  onChange={ev => setProp(e, 'CollisionFlags', ev.target.checked ? (flags | b) : (flags & ~b))} /> <span>{n}</span></label>)}</div></>}
          </fieldset>
          {!e.isNew && <div className="allprops">
            <label className="check"><input type="checkbox" checked={showAll} onChange={ev => setShowAll(ev.target.checked)} /> <span>{t('show_every_property')}</span></label>
            {showAll && !props && <p className="muted">{t('loading')}{'…'}</p>}
            {showAll && props?.props && <table style={{ width: '100%', fontSize: 12 }}><tbody>
              {props.props.filter(p => !SKIP.has(p.name)).map(p => (
                <tr key={p.name}><td title={p.type} style={{ color: 'var(--text-3)', width: '45%', wordBreak: 'break-all', padding: '2px 4px', borderBottom: '1px solid var(--line)' }}>{p.name}</td><td style={{ padding: '2px 4px', borderBottom: '1px solid var(--line)' }}>
                  {ro || e.deleted ? <span>{JSON.stringify(p.value)}</span> :
                    p.type === 'truth' ? <input type="checkbox" checked={!!(e.props?.[p.name] ?? p.value)} onChange={ev => setProp(e, p.name, ev.target.checked)} /> :
                    p.type === 'number' ? <Num label={p.name} value={e.props?.[p.name] ?? p.value} onCommit={v => setProp(e, p.name, v)} /> :
                    p.type === 'integer' ? <Num label={p.name} value={e.props?.[p.name] ?? p.value} digits={0} onCommit={v => setProp(e, p.name, Math.round(v))} /> :
                    p.type === 'string' ? <Text label={p.name} value={e.props?.[p.name] ?? p.value} onCommit={v => setProp(e, p.name, v)} /> :
                    <span className="muted">{JSON.stringify(p.value)?.slice(0, 60)}</span>}
                </td></tr>))}
            </tbody></table>}
          </div>}
        </Advanced>
        {testHere && <button className="soft" onClick={() => testHere({ pos: [e.pos[0], e.pos[1] + 1, e.pos[2]], yaw, name: e.name || e.type })} title={t('starts_the_game_at_this_object')}>{t('test_in_game_from_here')}</button>}
        <button className="ghost" onClick={() => setSaveSpot({ pos: e.pos, yaw, name: e.name || e.type })}>{t('start_a_test_save_here')}</button>
      </div>
      <div className="panel-f">
        <button onClick={onDuplicate} disabled={ro} title={t('ctrl_d')}>{t('duplicate')}</button>
        {e.deleted ? <button onClick={onRestore}>{t('restore')}</button> : <button className="danger" onClick={onDelete} disabled={ro} title={t('delete')}>{t('delete')}</button>}
      </div>
    </>
  )
}
