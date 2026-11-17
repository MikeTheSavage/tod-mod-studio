// The map identity card, and the start panel (a blank map, templates, a shipped map copy, recipe import) with the expected share of the meters per size.
import React, { useEffect, useRef, useState } from 'react'
import { Seg } from '../ui.jsx'
import { t as tr } from '../i18n.js'
import { world } from './worldapi.js'
import * as W from './worldlib.js'

const THEMES = ['Desert', 'Canyon', 'Town', 'Industrial', 'Jungle', 'Farm', 'Other']

// a picture file -> a small data URL (the card keeps it with the project)
function shrink(file, max = 320) {
  return new Promise((ok, no) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height))
      const c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k)
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height)
      URL.revokeObjectURL(url); ok(c.toDataURL('image/jpeg', 0.8))
    }
    img.onerror = () => { URL.revokeObjectURL(url); no(new Error('not a picture')) }
    img.src = url
  })
}

export function Card({ m, params, edit, editMap, say, length = 18, projectId }) {
  const card = m.card || {}
  const set = patch => editMap({ ...m, card: { ...card, ...patch } })
  const file = useRef()
  const side = Math.round(W.rectSize(W.ownRect(m))[0])
  return <div className="cardbox">
    <label>{tr('name')}<input aria-label={tr('map_name')} value={card.title ?? ''} placeholder={m.name} onChange={e => set({ title: e.target.value })} /></label>
    <div className="prow"><div className="k">{tr('map_name')}</div><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input className="mono" aria-label={tr('map_name')} value={m.name || ''} style={{ flex: 1, minWidth: 0 }} onChange={e => editMap({ ...m, name: e.target.value })} />
      <span className={'small mono' + ((m.name || '').length === length ? ' muted' : ' warn')} title={tr('map_name_length')}>{(m.name || '').length}{'/'}{length}</span>
      <button className="sm" onClick={async () => { try { editMap({ ...m, name: (await world('mapname', { title: card.title || m.name, length, id: projectId, taken: (params.maps || []).filter(x => x !== m).map(x => x.name) })).name }) } catch (x) { say(x.message) } }}>{tr('suggest')}</button></div></div>
    <label>{tr('description')}<textarea aria-label={tr('description')} rows={2} value={card.description || ''} onChange={e => set({ description: e.target.value })}
      style={{ height: 'auto', padding: '6px 8px', resize: 'vertical' }} /></label>
    <label>{tr('author')}<input aria-label={tr('author')} value={card.author || ''} onChange={e => set({ author: e.target.value })} /></label>
    <label>{tr('theme')}<select aria-label={tr('theme')} value={card.theme || ''} onChange={e => set({ theme: e.target.value })}>
      <option value="">{'—'}</option>{[...new Set([...THEMES, card.theme].filter(Boolean))].map(x => <option key={x}>{x}</option>)}</select></label>
    <div className="prow"><div className="k">{tr('size')}</div><div>{card.size ? (card.size === 'small' ? tr('small') : card.size === 'medium' ? tr('medium') : card.size === 'large' ? tr('large') : card.size) + ' · ' : ''}{side}{' m'}</div></div>
    <div className="prow"><div className="k">{tr('picture')}</div><div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {card.picture ? <img src={card.picture} alt={tr('map_picture')} style={{ height: 44, borderRadius: 4, border: '1px solid var(--line)' }} /> : <span className="muted small">{'—'}</span>}
      <input ref={file} type="file" accept="image/*" hidden onChange={async e => { const f = e.target.files?.[0]; if (!f) return; try { set({ picture: await shrink(f) }) } catch (x) { say(x.message) } e.target.value = '' }} />
      <button className="sm" onClick={() => file.current?.click()}>{tr('choose_78b7c9')}</button>
      {card.picture && <button className="sm" onClick={() => set({ picture: '' })}>{tr('remove')}</button>}</div></div>
    <label>{tr('package_name')}<input aria-label={tr('package_name')} value={params.package || ''} onChange={e => edit({ ...params, package: e.target.value })} /></label>
  </div>
}

const Bar = ({ m }) => <div className="sizebar" title={`${m.label}: ${m.used.toLocaleString()} / ${m.max.toLocaleString()}`}>
  <span className="small" style={{ width: 62 }}>{m.id === 'G2' ? tr('triangles') : m.id === 'G3' ? tr('collision') : tr('materials')}</span>
  <span className="track"><span style={{ width: Math.max(2, Math.min(100, m.pct)) + '%' }} /></span><span className="small mono" style={{ width: 42, textAlign: 'right' }}>{m.pct}{'%'}</span></div>

export function Start({ c, onClose }) {
  const { library, hosts, data, say } = c
  const [tid, setTid] = useState('desert'), [size, setSize] = useState('medium'), [src, setSrc] = useState(Object.keys(library.sources || {})[0] || '')
  const [sizes, setSizes] = useState([]), [pack, setPack] = useState('My new map'), [hostBlock, setHostBlock] = useState('submap01_map02_lostoros_downtown.submap')
  const [path, setPath] = useState('')
  const info = data?.templates || []
  useEffect(() => { let live = true; world('sizes', { template: tid === 'shell' ? 'blank' : tid }).then(r => live && setSizes(r.sizes)).catch(() => {}); return () => { live = false } }, [tid])
  const entryHosts = hosts.filter(h => h.offer && !h.section_copy || h.block === 'submap01_map02_lostoros_downtown.submap')
  const entryList = entryHosts.length ? entryHosts : [{ block: hostBlock, label: tr('los_toros_downtown') }]       // the section list is still being read
  const go = async () => {
    try {
      const h = hosts.find(x => x.block === hostBlock)
      const pos = W.boxAround(hostBlock, data?.bounds).enter
      const p = await world('start', { template: tid, size, source: src, package: pack, host: { block: hostBlock, parent: h?.default_parent, pos } })
      await c.createProject(p)
      onClose()
    } catch (e) { say(e.message) }
  }
  return <div className="startpanel" role="dialog" aria-label={tr('new_map_project')}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div className="upper grow">{tr('start')}</div><button className="sm" onClick={onClose} aria-label={tr('close')}>{tr('close')}</button></div>
    <div className="tiles" role="radiogroup" aria-label={tr('template')}>
      {info.map(t => <button key={t.id} role="radio" aria-checked={tid === t.id} className={'tile' + (tid === t.id ? ' on' : '')} onClick={() => setTid(t.id)}>{t.label}</button>)}</div>
    {tid === 'shell' && <label>{tr('copy_of')}<select aria-label={tr('copy_of')} value={src} onChange={e => setSrc(e.target.value)}>{Object.entries(library.sources || {}).filter(([k, v]) => /^PROVEN/.test(v.status || '') || k === src).map(([k, v]) => <option key={k} value={k}>{v.map_name}</option>)}</select></label>}
    {tid !== 'shell' && <div className="tiles" role="radiogroup" aria-label={tr('size')}>
      {(sizes.length ? sizes : (data?.sizes || []).map(s => ({ id: s.id, label: s.label, side: W.SIZES[s.id], meters: [] }))).map(s => <button key={s.id} role="radio" aria-checked={size === s.id} className={'tile size' + (size === s.id ? ' on' : '')} onClick={() => setSize(s.id)}>
        <b>{s.id === 'small' ? tr('small') : s.id === 'medium' ? tr('medium') : tr('large')}</b><span className="small muted">{s.side}{' × '}{s.side}{' m'}</span>{s.meters.map(mm => <Bar key={mm.id} m={mm} />)}</button>)}</div>}
    <label>{tr('entrance_in')}<select aria-label={tr('entrance_in')} value={hostBlock} onChange={e => setHostBlock(e.target.value)}>{entryList.map(h => <option key={h.block} value={h.block}>{h.label}</option>)}</select></label>
    <label>{tr('package_name')}<input aria-label={tr('package_name')} value={pack} onChange={e => setPack(e.target.value)} /></label>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><button className="primary" onClick={go}>{tr('create')}</button></div>
    <hr />
    <div className="upper">{tr('import_a_recipe')}</div>
    <div style={{ display: 'flex', gap: 6 }}><input aria-label={tr('recipe_path')} placeholder={tr('path_to_a_recipe_file')} value={path} onChange={e => setPath(e.target.value)} />
      <button disabled={!path.trim()} onClick={async () => { await c.importFile(path); onClose() }}>{tr('import')}</button></div>
  </div>
}
