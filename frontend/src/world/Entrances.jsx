// Entrances as PAIRS: the box in the host section (left view) and the arrival with its facing in the new map (right view), edited together.
// Also the entrance table (every link: source, destination, mode, lock) and the live rules (one unlocked way out, vehicle box, arrival checks).
import React, { useEffect, useMemo, useRef, useState } from 'react'
import View3D from '../View3D.jsx'
import MapPreview from '../mapbuild/MapPreview.jsx'
import { Seg, Switch } from '../ui.jsx'
import { useUi } from '../uistore.js'
import { useBundle, pickOfBlock, pickOfMapName, boundsOf, CONTEXT_LAYERS } from '../levelLoad.js'
import { runJob } from '../api.js'
import { loaderOverlays, spotYaw } from '../LoaderTopView.jsx'
import { t as tr } from '../i18n.js'
import * as W from './worldlib.js'

const GREEN = '#3fbf5a', AMBER = '#f2a541', RED = '#e5484d', BLUE = '#5b9bff'
const r2 = v => Math.round(v * 100) / 100
const Num = ({ label, value, onChange, step = 'any', min }) => <label className="axis" style={{ margin: 0 }}><span>{label}</span>
  <input aria-label={label} type="number" step={step} min={min} value={value} onChange={e => onChange(Number(e.target.value))} /></label>
const Row = ({ k, children }) => <div className="prow"><div className="k">{k}</div><div>{children}</div></div>

// the entrance a project map can reach: a legacy single `entry` counts as an entrance
function setEntries(m, rows) { const next = { ...m, entries: rows }; delete next.entry; return next }

export default function Entrances({ c }) {
  const { m, mapIndex, editMap, hosts, catalog, analysis } = c
  const ui = useUi()
  const advanced = ui.prefs.mode !== 'beginner'
  const es = W.entriesOf(m)
  const [sel, setSel] = useState(0)
  const [table, setTable] = useState(false)
  const [placeKind, setPlaceKind] = useState(null)         // 'trigger' | 'arrive' | 'back'
  const [showMap, setShowMap] = useState(false), [previewBusy, setPreviewBusy] = useState(false)
  const arrivalApi = useRef({})
  const ext = m?.placement === 'extension'
  const e = ext ? null : es[Math.min(sel, es.length - 1)]
  const ei = e ? es.indexOf(e) : -1
  const catalogObj = useMemo(() => ({ maps: catalog }), [catalog])
  const hostBlock = ext ? m.host?.block : e?.block
  const hostPick = hostBlock ? pickOfBlock(catalogObj, hostBlock) : null
  const hostLvl = useBundle(hostPick, !!hostPick)
  const newPick = showMap && m && !m.terrain ? pickOfMapName(catalogObj, m.source) : null
  const newLvl = useBundle(newPick, !!newPick)
  const [volumes, setVolumes] = useState([])
  useEffect(() => {
    let live = true
    setVolumes([])
    if (hostBlock) runJob('/api/sections/catalog', { entries: [hostBlock] }).then(r => live && setVolumes(r.volumes || [])).catch(() => {})
    return () => { live = false }
  }, [hostBlock])
  useEffect(() => { if (sel >= es.length) setSel(Math.max(0, es.length - 1)) }, [es.length])
  if (!m) return <div className="vp"><div className="empty">{tr('choose_a_map_project_or_make_8432a7')}</div></div>

  const mine = (analysis?.maps?.[mapIndex]?.items || []).filter(x => !e || x.where === 'entrance ' + e.id || x.where === 'arrival')
  const replace = next => editMap(setEntries(m, es.map((x, i) => i === ei ? next : x)))
  const hostRow = e && hosts.find(h => h.block === W.short(e.block))
  const arrive = e ? W.arriveOf(m, e) : null
  const back = e ? (e.back || m.return) : null
  // ---- live checks (no round trip): the arrival clear of the way back box, inside the ground, a vehicle box, the way out
  const live = []
  if (e && arrive?.pos && back?.pos) {
    const bs = back.size || [8, 5, 1.5]
    if (Math.abs(arrive.pos[0] - back.pos[0]) < bs[0] / 2 + 1 && Math.abs(arrive.pos[2] - back.pos[2]) < bs[2] / 2 + 1) live.push({ level: 'error', title: tr('the_arrival_is_inside_the_way') })
  }
  if (e && arrive?.pos && m.terrain) { const r = W.ownRect(m); if (arrive.pos[0] < r[0] || arrive.pos[0] > r[2] || arrive.pos[2] < r[1] || arrive.pos[2] > r[3]) live.push({ level: 'error', title: tr('the_arrival_is_outside_the_map') }) }
  if (e && !W.vehicleOk(e)) live.push({ level: 'error', title: tr('a_vehicle_box_needs_at_least') })
  if (!W.wayOut(m)) live.push({ level: 'error', title: tr('the_map_needs_one_unlocked_way') })
  const wayOutOk = W.wayOut(m)
  // ---- overlays: host side
  const hostSpots = e ? [{ ...e, id: 'trigger', label: e.id, color: AMBER, size: e.size || [12, 6, 2], orient: e.orient }] : []
  const hostOv = useMemo(() => {
    const out = ext ? [] : loaderOverlays({ volumes, spots: hostSpots, selected: 'trigger' })
    if (ext) for (const [k, col, lab] of [['enter', GREEN, tr('enter')], ['leave', RED, tr('leave')]]) { const b = m.host?.[k]; if (b?.pos) out.push({ id: 'ext:' + k, kind: 'box', pos: b.pos, size: b.size || [12, 6, 2], yaw: W.yawOfQuat(b.orient), color: col, label: lab, always: true, arrow: true }) }
    if (e?.back?.spot?.pos) out.push({ id: 'backspot', kind: 'point', pos: e.back.spot.pos, yaw: e.back.spot.yaw || 0, arrow: true, color: BLUE, label: tr('way_back_lands_here'), always: true })
    for (const o of es) if (o !== e && W.short(o.block) === W.short(e?.block)) out.push({ id: 'o:' + o.id, kind: 'box', pos: o.pos, size: o.size || [12, 6, 2], yaw: W.yawOfQuat(o.orient), color: '#7d8896', label: o.id, always: true, pickable: false })
    return out
  }, [volumes, e, es, ext, m.host])
  const hostFocus = useMemo(() => {
    const p = e?.pos || m.host?.enter?.pos
    return p ? { bounds: [p[0] - 50, p[2] - 40, p[0] + 50, p[2] + 40], y: p[1] } : null
  }, [e?.id, hostBlock, m.host?.enter?.pos?.join()])
  // ---- overlays: the new map
  const newOv = useMemo(() => {
    const out = []
    if (m.terrain) { const r = W.ownRect(m); out.push({ id: 'ground', kind: 'zone', rect: r, h: 1, y: 0, color: '#8aa0b8', opacity: 0.1, pickable: false, always: true, label: m.card?.title || m.name }) }
    for (const rd of m.roads || []) out.push({ id: 'road:' + rd.id, kind: 'path', points: rd.points.map(p => [p[0], 0.3, p[1]]), color: '#7d8896', pickable: false })
    if (e && arrive?.pos) {
      const bad = live.some(x => /arrival/i.test(x.title)) || mine.some(x => x.level === 'error' && x.where === 'entrance ' + e.id + '' && /arrival|ground/i.test(x.title))
      out.push({ id: 'arrive', kind: 'point', pos: arrive.pos, yaw: arrive.yaw || 0, arrow: true, color: bad ? RED : GREEN, label: bad ? tr('arrival_check') : tr('arrival'), always: true, selected: true })
    }
    if (back?.pos) out.push({ id: 'back', kind: 'box', pos: back.pos, size: back.size || [8, 5, 1.5], yaw: W.yawOfQuat(back.orient), color: BLUE, label: tr('way_back'), always: true, arrow: true })
    for (const t of m.teleports || []) out.push({ id: 'tp:' + t.name, kind: 'point', pos: t.pos, color: '#b27df0', label: t.name, always: true, pickable: false })
    return out
  }, [m, e, arrive?.pos?.join(), arrive?.yaw, back?.pos?.join(), live.length, mine.length])
  const newFocus = useMemo(() => {
    const pts = [arrive?.pos, back?.pos].filter(Boolean)
    const b = boundsOf(pts.length ? pts : [[0, 0, 0]], 60)
    return { bounds: b, y: arrive?.pos?.[1] ?? 0 }
  }, [e?.id, arrive?.pos?.join(), back?.pos?.join()])
  // ---- edits
  const setTrigger = patch => replace({ ...e, ...patch })
  const setArrive = patch => replace({ ...e, arrive: { ...arrive, ...patch } })
  const setBack = patch => replace({ ...e, back: { ...(e.back || m.return || { pos: arrive.pos, size: [8, 5, 1.5] }), ...patch } })
  const add = () => {
    const base = e || {}
    const host = hosts.find(h => h.offer && !h.section_copy) || hosts.find(h => h.offer)
    const blockName = base.block || host?.block || 'submap01_map02_lostoros_downtown.submap'
    const hrow = hosts.find(h => h.block === W.short(blockName))
    const p = base.pos ? [base.pos[0] + 18, base.pos[1], base.pos[2]] : [-237, 2.5, -43.66]
    const ne = { id: 'entrance_' + (es.length + 1), block: blockName, pos: p, size: [12, 6, 2], orient: base.orient || [0, 0.70710678, 0, 0.70710678], arrive: { pos: [...(m.arrival?.pos || [0, 0, 0])], yaw: W.yawOfQuat(m.arrival?.orient) },
      back: { pos: [(m.arrival?.pos?.[0] || 0) + 16, (m.arrival?.pos?.[1] || 0) + 0.5, m.arrival?.pos?.[2] || 0], size: [8, 5, 1.5], spot: { pos: [p[0] + 6, p[1], p[2] + 3], yaw: 180 } } }
    if (hrow?.default_parent) ne.parent = hrow.default_parent
    else if (base.parent && W.short(base.block) === W.short(blockName)) ne.parent = base.parent
    editMap(setEntries(m, [...es, ne])); setSel(es.length); setTable(false)
  }
  const del = () => { editMap(setEntries(m, es.filter((_, i) => i !== ei))); setSel(0) }
  const missions = useMemo(() => catalog.flatMap(x => x.missions || []).filter(q => q.type === 'story' || q.type === 'intermission').sort((a, b) => a.index - b.index), [catalog])
  const place = (pos, yaw) => {
    const q = W.quatOfYaw(Math.round(yaw))
    if (placeKind === 'trigger') setTrigger({ pos: [r2(pos[0]), r2(pos[1]), r2(pos[2])], orient: q })
    else if (placeKind === 'arrive') setArrive({ pos: [r2(pos[0]), r2(pos[1]), r2(pos[2])], yaw: Math.round(yaw) })
    else if (placeKind === 'back') setBack({ pos: [r2(pos[0]), r2(pos[1]), r2(pos[2])], orient: q })
    setPlaceKind(null)
  }
  const ghostFor = side => {
    if (!e || !placeKind) return null
    if (side === 'host' && placeKind === 'trigger') return { kind: 'spot', label: e.id, size: e.size || [12, 6, 2], arrow: true, facingDrag: true, color: AMBER, yaw: W.yawOfQuat(e.orient) }
    if (side === 'new' && placeKind === 'arrive') return { kind: 'spot', label: tr('arrival'), arrow: true, facingDrag: true, color: GREEN, yaw: arrive.yaw || 0 }
    if (side === 'new' && placeKind === 'back') return { kind: 'spot', label: tr('way_back'), size: back?.size || [8, 5, 1.5], arrow: true, facingDrag: true, color: BLUE, yaw: W.yawOfQuat(back?.orient) }
    return null
  }
  const rows = W.entranceRows(c.params, b => c.hostLabel(b))
  const wayCount = W.entriesOf(m).filter(x => x.back && !x.one_way).length + (m.return ? 1 : 0)
  const lockedAll = es.length > 0 && es.every(x => x.lock) && !m.return

  if (table) return <div className="split">
    <div className="vp" style={{ overflow: 'auto', padding: 16 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <div className="upper grow">{tr('all_entrances')}</div>
        <button className="sm" onClick={() => setTable(false)}>{tr('back_to_the_pair')}</button>
      </div>
      <table className="grid" style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>{[tr('source'), tr('destination'), tr('mode_a7b93d'), tr('lock'), tr('way_back')].map(h => <th key={h} className="upper" style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>)}</tr></thead>
        <tbody>{c.allRows.map(r => <tr key={r.key} className={'trow' + (r.cur && r.entry === ei ? ' sel' : '')} tabIndex={0} role="button" aria-label={`${r.source} ${r.dest}`}
          onClick={() => { if (r.cur) { c.setMapIndex(r.map); setSel(r.entry ?? 0); setTable(false) } }} onKeyDown={ev => ev.key === 'Enter' && r.cur && (c.setMapIndex(r.map), setSel(r.entry ?? 0), setTable(false))}
          style={{ opacity: r.cur ? 1 : 0.6 }}>
          <td>{r.source}</td><td>{r.dest}{!r.cur && <span className="muted small">{' · '}{r.project}</span>}</td><td>{r.mode}</td>
          <td>{r.lock != null ? '🔒 ' + tr('after_mission') + ' ' + r.lock : tr('open')}</td><td>{r.back === 'yes' ? '✓ ' + tr('yes') : '✕ ' + tr('no')}</td></tr>)}</tbody>
      </table>
      <div className={'callout small ' + (wayOutOk ? 'neutral' : 'warn')} style={{ marginTop: 12 }} role="status">{wayOutOk ? '✓ ' + tr('this_map_has_an_unlocked_way') : '⚠ ' + tr('the_map_needs_one_unlocked_way')}</div>
    </div>
  </div>

  return <div className="split">
    <div className="panel-l" style={{ overflow: 'auto', padding: '12px 8px' }}>
      <div className="upper" style={{ padding: '0 8px 6px' }}>{tr('entrances')}</div>
      {ext && <div className="li sel"><span className="nm">{tr('section_loader')}</span></div>}
      {es.map((x, i) => <div key={i} className={'li' + (i === ei ? ' sel' : '')} role="button" tabIndex={0} aria-label={x.id} onClick={() => setSel(i)} onKeyDown={ev => ev.key === 'Enter' && setSel(i)}
        title={c.hostLabel(x.block)}><span className="nm">{x.id}</span><span className="ty">{x.lock ? '🔒' : ''}{x.one_way ? '→' : '⇄'}</span></div>)}
      {!ext && <div style={{ padding: '6px 4px', display: 'flex', gap: 6 }}><button className="sm" onClick={add}>{tr('add_an_entrance')}</button><button className="sm" onClick={() => setTable(true)}>{tr('table')}</button></div>}
      <div className={'small ' + (wayOutOk ? 'good' : 'warn')} style={{ padding: '8px 8px 0' }} role="status">{wayOutOk ? '✓ ' : '⚠ '}{wayOutOk ? tr('unlocked_way_out') : tr('no_unlocked_way_out')}{wayCount > 0 && ` (${wayCount})`}</div>
      {lockedAll && <div className="small warn" style={{ padding: '4px 8px' }}>{tr('every_entrance_is_locked')}</div>}
    </div>
    <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
      <View3D defaultMode="top" bundle={hostLvl.bundle} view={hostLvl.view} layers={CONTEXT_LAYERS} overlays={hostOv} focus={hostFocus} placing={ghostFor('host')} onPlace={place}
        onPickOverlay={() => {}} onGround={(pos, ev, g) => { if (e && !placeKind) setTrigger({ pos: [r2(pos[0]), g ? r2(pos[1]) : e.pos[1], r2(pos[2])] }) }} style={{ borderRight: '1px solid var(--line-strong)' }}>
        <div style={{ position: 'absolute', left: 12, top: 12, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', maxWidth: 'calc(100% - 135px)' }}>
          <span className="badge" title={tr('the_box_in_the_existing_map') + ': ' + c.hostLabel(hostBlock)} style={{ maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis' }}>{tr('host_3960ec')}{' · '}{c.hostLabel(hostBlock)}</span>
          {e && <button className={'sm' + (placeKind === 'trigger' ? ' on' : '')} aria-pressed={placeKind === 'trigger'} onClick={() => setPlaceKind(placeKind === 'trigger' ? null : 'trigger')}
            title={tr('click_where_the_box_goes_drag')}>{tr('place_box')}</button>}
          {hostLvl.busy && <span className="small muted">{hostLvl.busy}{'…'}</span>}
        </div>
      </View3D>
      <View3D defaultMode="top" apiRef={arrivalApi} bundle={newLvl.bundle} view={newLvl.view} layers={CONTEXT_LAYERS} overlays={newOv} focus={newFocus} placing={ghostFor('new')} onPlace={place} planeY={arrive?.pos?.[1] ?? 0}
        onPickOverlay={() => {}} onGround={(pos, ev, g) => { if (e && !placeKind) setArrive({ pos: [r2(pos[0]), g ? r2(pos[1]) : arrive.pos[1], r2(pos[2])] }) }}>
        <div style={{ position: 'absolute', left: 12, top: 12, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', maxWidth: 'calc(100% - 135px)' }}>
          <span className="badge" title={tr('the_arrival_in_the_new_map')}>{tr('new_map')}{' · '}{m.card?.title || m.name}</span>
          {e && <button className={'sm' + (placeKind === 'arrive' ? ' on' : '')} aria-pressed={placeKind === 'arrive'} onClick={() => setPlaceKind(placeKind === 'arrive' ? null : 'arrive')}>{tr('place_arrival')}</button>}
          {e && <button className={'sm' + (placeKind === 'back' ? ' on' : '')} aria-pressed={placeKind === 'back'} onClick={() => setPlaceKind(placeKind === 'back' ? null : 'back')}>{tr('place_way_back')}</button>}
          {!m.terrain && <button className={'sm' + (showMap ? ' on' : '')} aria-pressed={showMap} onClick={() => setShowMap(!showMap)}>{tr('map')}</button>}
          {(newLvl.busy || previewBusy) && <span className="small muted">{newLvl.busy || ''}{'…'}</span>}
        </div>
        <MapPreview map={m} viewApi={arrivalApi} onBusy={setPreviewBusy} />
      </View3D>
    </div>
    <div className="panel-r">
      <div className="panel-h"><div className="grow"><div className="t">{e ? e.id : tr('section_loader')}</div></div>{e && <button className="sm danger" onClick={del} aria-label={tr('delete_this_entrance')}>{tr('delete')}</button>}</div>
      <div className="panel-b">
        {ext && <>
          <Row k={tr('enter')}><Seg value={m.host?.prompt || 'touch'} onChange={v => editMap({ ...m, host: { ...m.host, prompt: v } })} options={[{ value: 'touch', label: tr('touch') }, { value: 'use', label: tr('use') }]} label={tr('prompt')} /></Row>
          {['enter', 'leave'].map(k => <div key={k}><div className="upper" style={{ marginTop: 6 }}>{k === 'enter' ? tr('enter_box') : tr('leave_box')}</div>
            <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={'XYZ'[i]} value={m.host?.[k]?.pos?.[i] ?? 0} onChange={v => editMap({ ...m, host: { ...m.host, [k]: { ...m.host[k], pos: m.host[k].pos.map((n, j) => j === i ? v : n) } } })} />)}</div></div>)}
        </>}
        {e && <>
          <Row k={tr('name')}><input aria-label={tr('entrance_name')} value={e.id || ''} onChange={ev => replace({ ...e, id: ev.target.value })} /></Row>
          <label>{tr('in_section')}<select aria-label={tr('host_section')} value={W.short(e.block)} onChange={ev => { const h = hosts.find(x => x.block === ev.target.value); const next = { ...e, block: ev.target.value }; delete next.parent; if (h?.default_parent) next.parent = h.default_parent; replace(next) }}>
            {hosts.filter(h => h.offer || h.block === W.short(e.block)).map(h => <option key={h.block} value={h.block}>{h.label}{/^proven/.test(h.proven || '') ? ' ✓' : ''}</option>)}
            {!hosts.some(h => h.block === W.short(e.block)) && <option value={W.short(e.block)}>{W.short(e.block)}</option>}</select></label>
          {hostRow && !hostRow.offer && <div className="small warn" title={hostRow.reason}>{tr('this_section_cannot_take_an_entrance')}</div>}
          <div className="upper" style={{ marginTop: 6 }}>{tr('trigger_box')}</div>
          <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={'XYZ'[i]} value={e.pos?.[i] ?? 0} onChange={v => setTrigger({ pos: e.pos.map((n, j) => j === i ? v : n) })} />)}</div>
          <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={['W', 'H', 'L'][i]} min={0.1} value={(e.size || [12, 6, 2])[i]} onChange={v => setTrigger({ size: (e.size || [12, 6, 2]).map((n, j) => j === i ? Math.max(0.1, v) : n) })} />)}</div>
          <Row k={tr('facing')}><Num label={'°'} value={r2(W.yawOfQuat(e.orient))} onChange={v => setTrigger({ orient: W.quatOfYaw(v) })} /></Row>
          <Row k={tr('fires_on')}><Seg value={e.prompt || 'touch'} onChange={v => setTrigger({ prompt: v })} options={[{ value: 'touch', label: tr('touch') }, { value: 'use', label: tr('use') }]} label={tr('fires_on')} /></Row>
          <Row k={tr('icon')}><select aria-label={tr('icon')} value={e.marker?.icon || 'church'} onChange={ev => setTrigger({ marker: { ...(e.marker || {}), icon: ev.target.value } })}>{[['church', tr('church')], ['bullring', tr('bullring')], ['downtown', tr('downtown')], ['harbour', tr('harbour')], ['industrial', tr('industrial')], ['border', tr('border')], ['angel', tr('angel')], ['none', tr('none_6eef66')]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Row>
          <Row k={tr('beam')}><Seg value={e.marker?.beam || 'slim'} onChange={v => setTrigger({ marker: { ...(e.marker || {}), beam: v } })} options={[{ value: 'none', label: tr('none_6eef66') }, { value: 'slim', label: tr('slim') }, { value: 'full', label: tr('full') }]} label={tr('beam')} /></Row>
          <div className="upper" style={{ marginTop: 6 }}>{tr('arrival')}</div>
          <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={'XYZ'[i]} value={arrive.pos?.[i] ?? 0} onChange={v => setArrive({ pos: arrive.pos.map((n, j) => j === i ? v : n) })} />)}</div>
          <Row k={tr('facing')}><Num label={'°'} value={r2(arrive.yaw || 0)} onChange={v => setArrive({ yaw: v })} /></Row>
          {(m.teleports || []).length > 0 && <label>{tr('arrives_at')}<select aria-label={tr('arrives_at')} value={e.arrive_at || ''} onChange={ev => replace({ ...e, arrive_at: ev.target.value })}><option value="">{tr('main_arrival')}</option>{m.teleports.map(t => <option key={t.name}>{t.name}</option>)}</select></label>}
          <div className="upper" style={{ marginTop: 6 }}>{tr('way_back')}</div>
          <Row k={tr('one_way')}><Switch on={!!e.one_way} onChange={v => replace({ ...e, one_way: v })} label={tr('one_way')} /></Row>
          {!e.one_way && e.back && <>
            <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={'XYZ'[i]} value={e.back.pos?.[i] ?? 0} onChange={v => setBack({ pos: e.back.pos.map((n, j) => j === i ? v : n) })} />)}</div>
            {e.back.spot && <>
              <div className="small muted">{tr('lands_in_the_host_at')}</div>
              <div className="axes">{[0, 1, 2].map(i => <Num key={i} label={'XYZ'[i]} value={e.back.spot.pos?.[i] ?? 0} onChange={v => setBack({ spot: { ...e.back.spot, pos: e.back.spot.pos.map((n, j) => j === i ? v : n) } })} />)}</div></>}
          </>}
          {!e.one_way && !e.back && <div className="small muted">{m.return ? tr('uses_the_map_return_spot') : tr('no_way_back_yet')}
            {' '}<button className="link" onClick={() => replace({ ...e, back: { pos: [arrive.pos[0] + 16, arrive.pos[1] + 0.5, arrive.pos[2]], size: [8, 5, 1.5], spot: { pos: [e.pos[0] + 6, e.pos[1], e.pos[2] + 3], yaw: 180 } } })}>{tr('add_one')}</button></div>}
          {advanced && <>
            <div className="upper" style={{ marginTop: 6 }}>{tr('options')}</div>
            <Row k={tr('by_vehicle')}><Switch on={!!e.vehicle} onChange={v => replace({ ...e, vehicle: v, ...(v ? { size: (e.size || [12, 6, 2]).map((n, j) => Math.max(n, [16, 6, 8][j])) } : {}) })} label={tr('by_vehicle')} /></Row>
            <label>{tr('locked_until_mission')}<select aria-label={tr('locked_until_mission')} value={e.lock?.mission ?? ''} onChange={ev => { const n = { ...e }; if (ev.target.value === '') delete n.lock; else n.lock = { mission: Number(ev.target.value) }; replace(n) }}>
              <option value="">{tr('open_from_the_start')}</option>
              {missions.map(q => <option key={q.index} value={q.index}>{q.title} (#{q.index})</option>)}</select></label>
            {e.lock && <div className="small muted" title={tr('unlocks_when_that_mission_was_the')}>{'🔒 '}{tr('opens_after_mission')} #{e.lock.mission}</div>}
          </>}
          <div className="small muted" title={tr('a_portal_marker_is_hidden_when')}>{'ⓘ '}{tr('marker_can_be_hidden')}</div>
          {(live.length > 0 || mine.length > 0) && <><div className="upper" style={{ marginTop: 6 }}>{tr('checks')}</div>
            {[...live, ...mine].map((x, i) => <div key={i} className="small" title={x.detail}><span className={x.level === 'error' ? 'bad' : 'warn'}>{x.level === 'error' ? '✕ ' : '⚠ '}</span>{x.title}</div>)}</>}
          {live.length === 0 && mine.length === 0 && <div className="small good">{'✓ '}{tr('no_problem_found')}</div>}
        </>}
        {!e && !ext && <div className="muted small">{tr('no_entrances_yet')}{' '}<button className="link" onClick={add}>{tr('add_an_entrance')}</button></div>}
      </div>
    </div>
  </div>
}
