// Panels of the level editor tools: layers, prefabs, saved camera spots and notes, the multi-selection panel,
// find and replace, snapping and the scatter brush options. They only show state and call back; the level editor
// turns every callback into ONE commit, so each is one undo step.
import React, { useMemo, useState } from 'react'
import { Seg } from './ui.jsx'
import { catColor, CAT_LABEL } from './view.js'
import { SNAP_GRIDS, SNAP_ANGLES, layersOf, assignOf, bookmarksOf, notesOf, KIND_KEYS, kindCounts, centroid, layerOfEntity } from './editing.js'
import { keyOf } from './view.js'
import { t } from './i18n.js'
import { t as tr } from './i18n.js'

const Eye = ({ on }) => <span aria-hidden="true">{on ? '◉' : '○'}</span>
const Lock = ({ on }) => <span aria-hidden="true">{on ? '▣' : '□'}</span>
const fmt = n => (Math.round(n * 100) / 100).toString()

// ---------------------------------------------------------------- snapping
export function SnapPanel({ snap, setSnap }) {
  return <div style={{ minWidth: 240 }}>
    <div className="kvrow"><span>{t('grid')}</span>
      <select aria-label={t('grid')} value={snap.grid} onChange={e => setSnap({ ...snap, grid: Number(e.target.value) })}>
        {SNAP_GRIDS.map(g => <option key={g} value={g}>{g ? g + ' m' : 'Off'}</option>)}</select></div>
    <div className="kvrow"><span>{t('angle')}</span>
      <select aria-label={t('angle')} value={snap.angle} onChange={e => setSnap({ ...snap, angle: Number(e.target.value) })}>
        {SNAP_ANGLES.map(g => <option key={g} value={g}>{g ? g + '°' : 'Off'}</option>)}</select></div>
    <div className="kvrow"><span title={t('where_placed_things_land')}>{t('height')}</span>
      <Seg value={snap.mode} onChange={m => setSnap({ ...snap, mode: m })} options={[
        { value: 'surface', label: tr('surface'), title: tr('on_whatever_is_under_the_mouse') },
        { value: 'ground', label: tr('ground_143e94'), title: tr('on_the_lowest_floor_under_the') },
        { value: 'free', label: tr('free'), title: tr('at_the_same_height_as_before') }]} /></div>
  </div>
}
export const snapLabel = s => (s.grid ? s.grid + ' m' : '') + (s.grid && s.angle ? ' · ' : '') + (s.angle ? s.angle + '°' : '') || 'Off'

// ---------------------------------------------------------------- layers
export function LayersPanel({ project, ents, selected, onAdd, onPatch, onRemove, onAssign, onSelect }) {
  const layers = layersOf(project), assign = assignOf(project)
  const counts = useMemo(() => {
    const c = {}
    for (const e of ents) { const id = assign[keyOf(e.target)]; if (id) c[id] = (c[id] || 0) + 1 }
    return c
  }, [ents, project.editor])
  const [name, setName] = useState('')
  return <div className="list" style={{ padding: '4px 8px' }}>
    {layers.map(l => <div key={l.id} className={'li' + (l.hidden ? ' hid' : '') + (l.locked ? ' locked' : '')}>
      <button className={'ico' + (l.hidden ? '' : ' on')} aria-label={l.hidden ? 'Show layer' : 'Hide layer'} title={l.hidden ? 'Show' : 'Hide'} onClick={() => onPatch(l.id, { hidden: !l.hidden })}><Eye on={!l.hidden} /></button>
      <button className={'ico' + (l.locked ? ' on' : '')} aria-label={l.locked ? 'Unlock layer' : 'Lock layer'} title={l.locked ? 'Unlock' : 'Lock'} onClick={() => onPatch(l.id, { locked: !l.locked })}><Lock on={l.locked} /></button>
      <input aria-label={t('layer_name')} className="nm" style={{ border: 0, background: 'transparent', padding: 0, height: 24 }} defaultValue={l.name}
        onBlur={e => e.target.value !== l.name && onPatch(l.id, { name: e.target.value })} onKeyDown={e => e.key === 'Enter' && e.target.blur()} />
      <button className="ty link" title={t('select_what_is_on_this_layer')} onClick={() => onSelect(l.id)}>{counts[l.id] || 0}</button>
      <button className="ico" title={t('put_the_selection_on_this_layer')} disabled={!selected.length} onClick={() => onAssign(selected, l.id)}>{'+'}</button>
      <button className="ico" aria-label={t('delete_layer')} title={t('delete_layer_objects_stay')} onClick={() => onRemove(l.id)}>{'×'}</button>
    </div>)}
    <div className="row" style={{ marginTop: 6, gap: 6 }}>
      <input aria-label={t('new_layer_name')} placeholder={t('new_layer')} value={name} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { onAdd(name); setName('') } }} />
      <button className="sm" onClick={() => { onAdd(name); setName('') }}>{t('add')}</button></div>
    {selected.length > 0 && layers.length > 0 && <button className="link" style={{ marginTop: 6 }} onClick={() => onAssign(selected, null)}>{t('take_the_selection_off_its_layer')}</button>}
  </div>
}

// ---------------------------------------------------------------- prefabs
export function PrefabsPanel({ prefabs, canSave, onSave, onStamp, onDelete, onRename, stamping }) {
  const [name, setName] = useState('')
  return <div className="list" style={{ padding: '4px 8px' }}>
    <div className="row" style={{ gap: 6, marginBottom: 6 }}>
      <input aria-label={t('prefab_name')} placeholder={t('name')} value={name} onChange={e => setName(e.target.value)} />
      <button className="sm primary" disabled={!canSave} title={canSave ? 'Save the selected objects as a reusable piece' : 'Select objects first'} onClick={() => { onSave(name); setName('') }}>{t('save')}</button></div>
    {prefabs.length === 0 && <div className="muted small" style={{ padding: '4px 0' }}>{t('none_yet')}</div>}
    {prefabs.map(p => <div key={p.id} className={'li' + (stamping === p.id ? ' sel' : '')} onClick={() => onStamp(p)} title={t('click_then_click_in_the_view')}>
      <span className="swatch" style={{ background: catColor(p.items[0]?.cat) || '#adb5bd' }} />
      <span className="nm">{p.name}</span><span className="ty">{p.items.length}</span>
      <button className="ico" title={t('rename')} aria-label={t('rename')} onClick={ev => { ev.stopPropagation(); const n = prompt('Name', p.name); if (n) onRename(p.id, n) }}>{'✎'}</button>
      <button className="ico" title={t('delete')} aria-label={t('delete_prefab')} onClick={ev => { ev.stopPropagation(); onDelete(p.id) }}>{'×'}</button></div>)}
  </div>
}

// ---------------------------------------------------------------- saved camera spots and pinned notes
export function SpotsPanel({ project, onAddSpot, onGo, onRenameSpot, onRemoveSpot, onAddNote, onGoNote, onEditNote, onRemoveNote, noting }) {
  const spots = bookmarksOf(project), notes = notesOf(project)
  return <div className="list" style={{ padding: '4px 8px' }}>
    <div className="upper" style={{ padding: '4px 0' }}>{t('camera_spots')}</div>
    {spots.map(b => <div key={b.id} className="li" onClick={() => onGo(b)}>
      <input aria-label={t('spot_name')} className="nm" style={{ border: 0, background: 'transparent', padding: 0, height: 24 }} defaultValue={b.name} onClick={e => e.stopPropagation()}
        onBlur={e => e.target.value !== b.name && onRenameSpot(b.id, e.target.value)} onKeyDown={e => e.key === 'Enter' && e.target.blur()} />
      <button className="ico" aria-label={t('delete_spot')} onClick={ev => { ev.stopPropagation(); onRemoveSpot(b.id) }}>{'×'}</button></div>)}
    <button className="link" onClick={onAddSpot}>{t('save_this_view')}</button>
    <div className="upper" style={{ padding: '10px 0 4px' }}>{t('notes_in_the_level')}</div>
    {notes.map(n => <div key={n.id} className="li" onClick={() => onGoNote(n)}>
      <input aria-label={t('note_text')} className="nm" style={{ border: 0, background: 'transparent', padding: 0, height: 24 }} defaultValue={n.text} onClick={e => e.stopPropagation()}
        onBlur={e => e.target.value !== n.text && onEditNote(n.id, e.target.value)} onKeyDown={e => e.key === 'Enter' && e.target.blur()} />
      <button className="ico" aria-label={t('delete_note')} onClick={ev => { ev.stopPropagation(); onRemoveNote(n.id) }}>{'×'}</button></div>)}
    <button className={'link'} onClick={onAddNote}>{noting ? 'Click in the view…' : '+ Pin a note'}</button>
  </div>
}

// ---------------------------------------------------------------- many objects at once
const PROP_SKIP = new Set(['CollisionFlags'])
export function SelectionPanel({ ents, enums, project, actions }) {
  const editable = ents.filter(e => e.ed && !e.deleted)
  const c = centroid(ents)
  const kinds = useMemo(() => { const m = {}; for (const e of ents) m[e.cat] = (m[e.cat] || 0) + 1; return Object.entries(m) }, [ents])
  // properties every editable object has: its name, box size, kinds and plain values
  const props = useMemo(() => {
    if (!editable.length) return []
    const out = [['name', 'Name', 'text']]
    if (editable.every(e => e.size)) out.push(['width', 'Width', 'num'], ['height', 'Height', 'num'], ['length', 'Length', 'num'])
    const keys = Object.keys(editable[0].sub || {}).filter(k => !PROP_SKIP.has(k) && editable.every(e => e.sub && e.sub[k] !== undefined))
    for (const k of keys) {
      const v = editable[0].sub[k]
      if (enums?.[k]) out.push([k, k.replace('SubType', '').replace('Goodie', 'Kind'), 'enum'])
      else if (typeof v === 'boolean') out.push([k, k, 'bool'])
      else if (typeof v === 'number') out.push([k, k, 'num'])
    }
    return out
  }, [ents, enums])
  const [prop, setProp] = useState('')
  const [val, setVal] = useState('')
  const [turn, setTurn] = useState(15)
  const p = props.find(x => x[0] === prop)
  const [dx, setDx] = useState({ x: '', y: '', z: '' })
  const move = () => {
    const d = ['x', 'y', 'z'].map(k => Number(dx[k]) || 0)
    if (d.some(Boolean)) actions.move(d)
    setDx({ x: '', y: '', z: '' })
  }
  const sameModel = ents.length && ents.every(e => (e.model || e.type) === (ents[0].model || ents[0].type)) ? ents[0] : null
  const lay = layersOf(project)
  const common = ents.every(e => layerOfEntity(project, e)?.id === layerOfEntity(project, ents[0])?.id) ? layerOfEntity(project, ents[0])?.id || '' : '__mixed'
  return <>
    <div className="panel-h"><div className="grow"><div className="t" style={{ fontWeight: 600 }}>{ents.length}{' '}{t('selected')}</div>
      <div className="s" style={{ fontSize: 11.5, color: 'var(--text-3)' }}>{kinds.map(([k, n]) => `${n} ${(CAT_LABEL[k] || k).toLowerCase()}`).join(', ')}</div></div>
      <button className="sm ghost" onClick={actions.focus} title={t('frame_them_f')}>{t('focus')}{' '}<span className="kbd">{t('f')}</span></button></div>
    <div className="panel-b">
      {editable.length < ents.length && <div className="small warn">{ents.length - editable.length}{' '}{t('cannot_be_edited_shared_or_removed')}</div>}
      <div className="upper">{t('move_by')}</div>
      <div className="axes">{['x', 'y', 'z'].map((k, i) => <label key={k} className="axis" style={{ margin: 0 }}><span style={{ color: ['var(--ax-x)', 'var(--ax-y)', 'var(--ax-z)'][i] }}>{k.toUpperCase()}</span>
        <input type="number" step="any" aria-label={'Move ' + k} value={dx[k]} placeholder="0" onChange={e => setDx({ ...dx, [k]: e.target.value })} onKeyDown={e => e.key === 'Enter' && move()} /></label>)}</div>
      <button className="sm" onClick={move} disabled={!editable.length}>{t('move')}</button>
      <div className="kvrow"><span>{t('turn_the_group')}</span>
        <button className="sm" title={`Turn ${turn}° left`} onClick={() => actions.turn(-turn)}>{'↺'}</button>
        <input type="number" aria-label={t('turn_step')} value={turn} style={{ width: 56 }} onChange={e => setTurn(Number(e.target.value) || 0)} />
        <button className="sm" title={`Turn ${turn}° right`} onClick={() => actions.turn(turn)}>{'↻'}</button></div>
      <div className="upper" style={{ marginTop: 6 }}>{t('align')}</div>
      <div className="toolgrid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        {['x', 'y', 'z'].flatMap(a => [['min', 'low'], ['center', 'mid'], ['max', 'high']].map(([m, l]) =>
          <button key={a + m} className="sm" disabled={editable.length < 2} title={`Align ${a.toUpperCase()}: ${l}`} onClick={() => actions.align(a, m)}>{a.toUpperCase()} {l}</button>))}
      </div>
      <div className="upper" style={{ marginTop: 6 }}>{t('spread_evenly')}</div>
      <div className="toolgrid">{['x', 'y', 'z'].map(a => <button key={a} className="sm" disabled={editable.length < 3} onClick={() => actions.distribute(a)}>{a.toUpperCase()}</button>)}</div>
      <div className="upper" style={{ marginTop: 6 }}>{t('set_on_all')}</div>
      <div className="row" style={{ gap: 6 }}>
        <select aria-label={t('property')} value={prop} onChange={e => { setProp(e.target.value); setVal('') }}><option value="">{t('property')}</option>{props.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        {p?.[2] === 'enum' ? <select aria-label={t('value')} value={val} onChange={e => setVal(e.target.value)}><option value="">{t('value')}</option>{Object.entries(enums[prop]).map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select>
          : p?.[2] === 'bool' ? <select aria-label={t('value')} value={val} onChange={e => setVal(e.target.value)}><option value="">{t('value')}</option><option value="1">{t('on')}</option><option value="0">{t('off')}</option></select>
          : <input aria-label={t('value')} value={val} onChange={e => setVal(e.target.value)} disabled={!p} />}
        <button className="sm" disabled={!p || val === ''} onClick={() => actions.setProp(prop, p[2] === 'num' ? Number(val) : p[2] === 'enum' ? Number(val) : p[2] === 'bool' ? val === '1' : val)}>{t('apply')}</button></div>
      {lay.length > 0 && <label className="kvrow"><span>{t('layer')}</span><select aria-label={t('layer')} value={common} onChange={e => actions.layer(e.target.value || null)}>
        {common === '__mixed' && <option value="__mixed" disabled>{t('mixed')}</option>}<option value="">{t('none_6eef66')}</option>{lay.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>}
    </div>
    <div className="panel-f" style={{ flexWrap: 'wrap' }}>
      <button onClick={actions.drop} disabled={!editable.length} title={t('put_them_on_the_ground_below')}>{t('drop')}</button>
      {sameModel && <button onClick={actions.sameModel} title={t('select_every_object_with_this_model')}>{t('all_of_this')}</button>}
      <button onClick={actions.prefab} disabled={!editable.length} title={t('save_as_a_reusable_piece')}>{t('prefab')}</button>
      <button onClick={actions.copy} title={t('ctrl_c')}>{t('copy')}</button>
      <button onClick={actions.duplicate} disabled={!editable.length} title={t('ctrl_d')}>{t('duplicate')}</button>
      <button className="danger" onClick={actions.del} disabled={!editable.length} title={t('delete')}>{t('delete')}</button>
    </div>
  </>
}

// ---------------------------------------------------------------- find and replace: one kind for another, everywhere
export function FindReplace({ view, enums, onApply, onClose }) {
  const [key, setKey] = useState(() => KIND_KEYS.find(k => kindCounts(view, k).size) || KIND_KEYS[0])
  const counts = useMemo(() => kindCounts(view, key), [view, key])
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const names = enums?.[key] || {}
  const n = from !== '' ? counts.get(Number(from)) || 0 : 0
  return <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
    <div className="dialog" role="dialog" aria-label={t('find_and_replace')} style={{ width: 400 }}>
      <div className="dt">{t('find_and_replace')}</div>
      <div className="dd" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Seg value={key} onChange={k => { setKey(k); setFrom(''); setTo('') }} options={KIND_KEYS.map(k => ({ value: k, label: k.replace('SubType', '').replace('Goodie', 'Pickups') + (k === 'GoodieSubType' ? '' : 's') }))} />
        <label>{t('find')}<select value={from} onChange={e => setFrom(e.target.value)}><option value="">{t('choose_78b7c9')}</option>
          {[...counts.entries()].map(([v, c]) => <option key={v} value={v}>{names[v] || v} ({c})</option>)}</select></label>
        <label>{t('replace_with')}<select value={to} onChange={e => setTo(e.target.value)}><option value="">{t('choose_78b7c9')}</option>
          {Object.entries(names).map(([v, nm]) => <option key={v} value={v}>{nm}</option>)}</select></label>
        {from !== '' && <div className="small muted">{n}{' '}{t('object')}{n === 1 ? '' : 's'}{' '}{t('change')}</div>}
      </div>
      <div className="da"><button onClick={onClose}>{t('cancel')}</button>
        <button className="primary" disabled={from === '' || to === '' || from === to || !n} onClick={() => { onApply(key, Number(from), Number(to)); onClose() }}>{t('replace')}{' '}{n || ''}</button></div>
    </div>
  </div>
}

// ---------------------------------------------------------------- scatter brush options (floats over the view)
export function ScatterHud({ cfg, setCfg, sources, chosen, setChosen, subs, setSubs, enums, onClose }) {
  const set = (k, v) => setCfg({ ...cfg, [k]: v })
  return <div className="v3hud" style={{ left: 12, top: 12, flexDirection: 'column', alignItems: 'stretch', width: 252, padding: 10, gap: 6 }}>
    <div className="row"><div className="upper grow">{t('scatter_brush')}</div><button className="sm ghost" onClick={onClose} aria-label={t('close')}>{'×'}</button></div>
    <div className="chips" style={{ marginTop: 0 }}>{sources.map(s => <button key={s.id} className={'chip' + (chosen.includes(s.id) ? ' on' : '')} disabled={!s.ok}
      title={s.ok ? '' : 'Not in this section'} onClick={() => setChosen(chosen.includes(s.id) ? chosen.filter(x => x !== s.id) : [...chosen, s.id])}>{s.label}</button>)}</div>
    {sources.filter(s => chosen.includes(s.id) && s.subKey && enums?.[s.subKey]).map(s => <label key={s.id} className="kvrow"><span>{s.label}</span>
      <select style={{ width: 130 }} value={subs[s.id] ?? ''} onChange={e => setSubs({ ...subs, [s.id]: e.target.value === '' ? null : Number(e.target.value) })}>
        <option value="">{t('as_the_template')}</option>{Object.entries(enums[s.subKey]).map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>)}
    <label className="kvrow"><span>{t('radius')}</span><input type="range" min="1" max="30" step="0.5" value={cfg.radius} onChange={e => set('radius', Number(e.target.value))} /><span className="mono small" style={{ width: 38, textAlign: 'right' }}>{cfg.radius}{' '}{t('m')}</span></label>
    <label className="kvrow"><span>{t('density')}</span><input type="range" min="0.005" max="0.3" step="0.005" value={cfg.density} onChange={e => set('density', Number(e.target.value))} /><span className="mono small" style={{ width: 38, textAlign: 'right' }}>{Math.round(cfg.density * Math.PI * cfg.radius * cfg.radius)}</span></label>
    <label className="kvrow"><span>{t('spacing')}</span><input type="range" min="0" max="6" step="0.25" value={cfg.gap} onChange={e => set('gap', Number(e.target.value))} /><span className="mono small" style={{ width: 38, textAlign: 'right' }}>{cfg.gap}{' '}{t('m')}</span></label>
    <label className="check"><input type="checkbox" checked={cfg.yawRandom} onChange={e => set('yawRandom', e.target.checked)} /> <span>{t('turn_at_random')}</span></label>
    <label className="kvrow" title={t('boxes_only_the_game_has_no')}><span>{t('size')}</span>
      <input type="number" step="0.1" min="0.1" style={{ width: 54 }} value={cfg.scale[0]} onChange={e => set('scale', [Number(e.target.value) || 1, Math.max(Number(e.target.value) || 1, cfg.scale[1])])} />
      <span>{t('to')}</span><input type="number" step="0.1" min="0.1" style={{ width: 54 }} value={cfg.scale[1]} onChange={e => set('scale', [Math.min(cfg.scale[0], Number(e.target.value) || 1), Number(e.target.value) || 1])} /></label>
  </div>
}
export { fmt }
