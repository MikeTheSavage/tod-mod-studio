// The world atlas: every shipped map (a light stand-in) and every new map in ONE 3D scene, plus where a new map lives:
// separate (its own space), extension (a section inside a shipped map, drawn on that map's real geometry) or aligned (next to a neighbour).
// The layout is an editor picture: each map keeps its own space in the game. All edits go through the screen's undo (c.editMap).
import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import View3D from '../View3D.jsx'
import { Seg } from '../ui.jsx'
import { useUi } from '../uistore.js'
import { useBundle, pickOfBlock, CONTEXT_LAYERS } from '../levelLoad.js'
import { toView } from '../coords.js'
import { t as tr } from '../i18n.js'
import * as W from './worldlib.js'
import { world } from './worldapi.js'

const COL = ['#6aa7e8', '#c78be8', '#e8a76a', '#6ae8c2', '#e86a8f', '#b4e86a', '#e8e06a', '#6a8ee8', '#e8886a']
const NEW = '#f2a541'

// the shipped maps as flat tiles, one instance per occupied cell (a stand-in: no meshes, so the whole world stays fast)
function StandIns({ items }) {
  const ref = useRef()
  useEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    const m4 = new THREE.Matrix4(), col = new THREE.Color()
    items.forEach((c, i) => {
      const s = c.size * 1.5
      m4.compose(new THREE.Vector3(c.x, 0.2, -c.z), new THREE.Quaternion(), new THREE.Vector3(s, 0.4, s))
      mesh.setMatrixAt(i, m4); mesh.setColorAt(i, col.set(c.color).multiplyScalar(0.55 + 0.45 * Math.min(1, c.n / 10)))
    })
    mesh.count = items.length
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [items])
  if (!items.length) return null
  return <instancedMesh ref={ref} args={[null, null, items.length]} userData={{ overlay: true }} frustumCulled={false}>
    <boxGeometry args={[1, 1, 1]} /><meshBasicMaterial /></instancedMesh>
}

const Num = ({ label, value, onChange, step = 1, suffix }) => <label className="axis" style={{ margin: 0 }}><span>{label}</span>
  <input aria-label={label} type="number" step={step} value={value} onChange={e => onChange(Number(e.target.value))} />{suffix}</label>

export default function Atlas({ c }) {
  const { params, m, mapIndex, editMap, data, hosts, catalog, library, links } = c
  const ui = useUi()
  const advanced = ui.prefs.mode !== 'beginner'
  const [placing, setPlacing] = useState(false)
  const [snapNote, setSnapNote] = useState(null)
  const [regionFirst, setRegionFirst] = useState(null), [drawRegion, setDrawRegion] = useState(false)
  const [frameTo, setFrameTo] = useState(null)
  const apiRef = useRef({})
  const ext = m?.placement === 'extension'
  const layout = data?.layout || {}, bounds = data?.bounds || {}
    const titleOf = id => catalog.find(x => x.id === id)?.title || id
  // ---- what is drawn
  const ships = useMemo(() => [...new Set(Object.values(bounds).map(v => v.map))].sort().map((id, n) => ({ id, color: COL[n % COL.length], ...W.standIn(bounds, id, layout) })), [bounds, layout])
  const tiles = useMemo(() => ships.flatMap(s => s.cells.map(([x, z, size, n]) => ({ x, z, size, n, color: s.color }))), [ships])
  const projects = useMemo(() => {
    const cur = library.projects.filter(p => p.id !== c.project?.id).map(p => ({ id: p.id, label: p.params.package, params: p.params, cur: false }))
    return [...cur, { id: c.project?.id || 'now', label: params?.package, params, cur: true }].filter(p => p.params)
  }, [library, params, c.project?.id])
  const installed = useMemo(() => new Set((links?.maps || []).filter(x => x.installed).map(x => x.key)), [links])
  const shipBoxes = useMemo(() => Object.fromEntries(ships.filter(s => s.box).map(s => [s.id, s.box])), [ships])
  const footprints = useMemo(() => { const used = {}; return projects.flatMap(p => (p.params.maps || []).map((mm, i) => ({ p, mm, i }))).filter(x => x.mm.placement !== 'extension').map(({ p, mm, i }) => {
    const a = W.anchorOf(mm, i, shipBoxes, used), rect = W.ownRect(mm)
    const corners = W.atlasCorners(rect, a.pos, a.yaw)
    return { id: (p.cur ? 'new:' : 'other:' + p.id + ':') + i, p, mm, i, a, rect, corners, box: W.aabb(corners), title: mm.card?.title || mm.name }
  }) }, [projects, shipBoxes])
  const mine = footprints.find(f => f.p.cur && f.i === mapIndex)
  const others = footprints.filter(f => f !== mine).map(f => f.box)
  const guard = useMemo(() => mine ? W.guard(mine.box, others) : null, [mine, others])
  // links: the entrances of every project, drawn between the shipped section and the new map in the layout
  const linkOv = useMemo(() => {
    const out = []
    for (const f of footprints) {
      W.entriesOf(f.mm).forEach((e, ei) => {
        const mid = W.mapIdOf(e.block)
        if (!mid || !e.pos) return
        const lo = layout[mid] || [0, 0]
        const from = [e.pos[0] + lo[0], 0.8, e.pos[2] + lo[1]]
        const ar = W.arriveOf(f.mm, e)
        const q = ar.pos ? W.toAtlas(f.mm, f.a, ar.pos) : f.a.pos
        const sel = f.p.cur && f.i === mapIndex
        const tag = [e.id || 'entrance', e.one_way ? '→' : '⇄', e.lock ? tr('locked') : ''].filter(Boolean).join(' ')
        out.push({ id: 'link:' + f.id + ':' + ei, kind: 'path', points: [from, [q[0], 0.8, q[1]]], color: sel ? NEW : '#9aa7b5', dashed: !!e.one_way, label: tag, always: sel,
          selected: false, pickable: false, layer: 'links' })
      })
    }
    for (const mm of projects.filter(p => p.cur).flatMap(p => (p.params.maps || []).map((x, i) => ({ x, i }))).filter(v => v.x.placement === 'extension')) {
      const h = mm.x.host || {}, mid = W.mapIdOf(h.block)
      if (mid && h.enter?.pos) { const lo = layout[mid] || [0, 0]
        out.push({ id: 'ext:' + mm.i, kind: 'point', pos: [h.enter.pos[0] + lo[0], 0.8, h.enter.pos[2] + lo[1]], radius: 60, color: NEW, label: mm.x.name, always: true, pickable: true, layer: 'links' }) }
    }
    return out
  }, [footprints, projects, layout, mapIndex])
  const overlays = useMemo(() => {
    const out = [{ id: 'guard', kind: 'zone', rect: [-W.SAFE, -W.SAFE, W.SAFE, W.SAFE], h: 0.5, y: 0, color: '#f2c14e', opacity: 0.025, pickable: false, layer: 'guard', label: tr('safe_box'), always: false }]
    for (const s of ships) if (s.box) out.push({ id: 'ship:' + s.id, kind: 'zone', rect: s.box, h: 1, y: 0, color: s.color, opacity: 0.05, always: true, label: titleOf(s.id).replace(/^Map\d+ /, s.id.replace('map', 'M') + ' '), pickable: true, layer: 'shipped', at: [(s.box[0] + s.box[2]) / 2, (s.box[1] + s.box[3]) / 2] })
    for (const f of footprints) out.push({ id: f.id, kind: 'poly', corners: f.corners, y: 0.6, h: 8, color: f.p.cur ? NEW : '#8aa0b8', opacity: f.p.cur && f.i === mapIndex ? 0.55 : 0.32,
      selected: f.p.cur && f.i === mapIndex, always: true, label: `${f.title} (${installed.has(f.p.id) ? tr('installed') : tr('project')})`, layer: 'new', at: [(f.box[0] + f.box[2]) / 2, (f.box[1] + f.box[3]) / 2] })
    for (const f of footprints) out.push({ id: 'ring:' + f.id, kind: 'ring', pos: [f.a.pos[0], 0.7, f.a.pos[1]], radius: Math.max(160, Math.hypot(...W.rectSize(f.rect)) / 2 + 60), color: f.p.cur ? NEW : '#8aa0b8', dashed: !f.p.cur, pickable: false, layer: 'new' })
    if (mine) {
      const [x0, z0, x1, z1] = mine.box
      const p = mine.a.pos
      out.push({ id: 'arrow', kind: 'point', pos: [p[0], 0.6, p[1]], yaw: -mine.a.yaw, arrow: true, color: NEW, pickable: false, layer: 'new' })
      for (const g of snapNote?.guides || []) out.push({ id: 'guide:' + g.axis, kind: 'path', color: '#5fd38d', pickable: false, layer: 'new',
        points: g.axis === 'x' ? [[g.at, 1, z0 - 200], [g.at, 1, z1 + 200]] : [[x0 - 200, 1, g.at], [x1 + 200, 1, g.at]] })
    }
    const nb = m?.placement === 'aligned' ? m.neighbour : null
    const nbBox = nb && nbRect(nb, ships, footprints, params)
    if (nbBox) {
      const strip = stripOf(nbBox, nb.edge || 'e', 60)
      out.push({ id: 'strip', kind: 'zone', rect: strip, h: 3, y: 0, color: '#5fd38d', opacity: 0.35, pickable: false, always: true, label: tr('neighbour_edge_locked'), layer: 'new' })
    }
    const xs = [...ships.flatMap(s => s.box ? [s.box[0], s.box[2]] : []), ...footprints.flatMap(f => [f.box[0], f.box[2]])]
    const zs = [...ships.flatMap(s => s.box ? [s.box[1], s.box[3]] : []), ...footprints.flatMap(f => [f.box[1], f.box[3]])]
    const ext = xs.length ? [Math.max(...xs) - Math.min(...xs) + 400, Math.max(...zs) - Math.min(...zs) + 400] : [1000, 1000]
    return [...spreadLabels(out, ext), ...linkOv]
  }, [ships, footprints, mine, snapNote, linkOv, m, params, mapIndex, installed, catalog])
  // ---- the host section (extension): its real geometry, the footprint of the new section and the loader boxes
  const catalogObj = useMemo(() => ({ maps: catalog }), [catalog])
  const hostPick = ext && m.host?.block ? pickOfBlock(catalogObj, m.host.block) : null
  const lvl = useBundle(hostPick, !!hostPick)
  const extRect = ext ? W.ownRect(m) : null
  const hostOv = useMemo(() => {
    if (!ext) return []
    const h = m.host || {}
    const out = []
    if (extRect) out.push({ id: 'extfoot', kind: 'zone', rect: extRect, h: 10, y: null, color: NEW, opacity: 0.18, always: true, label: m.card?.title || m.name, selected: true, pickable: false, layer: 'new' })
    for (const [k, col, lab] of [['enter', '#3fbf5a', tr('enter')], ['leave', '#e5484d', tr('leave')]]) {
      const b = h[k]
      if (b?.pos) out.push({ id: 'host:' + k, kind: 'box', pos: b.pos, size: b.size || [12, 6, 2], yaw: W.yawOfQuat(b.orient), color: col, label: lab, always: true, arrow: true, layer: 'loaders' })
    }
    const car = m.carry
    if (car?.mode === 'region' && car.region) out.push({ id: 'carry', kind: 'zone', rect: car.region, h: 4, y: null, color: '#5b9bff', opacity: 0.2, always: true, label: tr('carried_over'), pickable: false, layer: 'new' })
    return out
  }, [ext, m, extRect])
  // the seam: ground of the host along the footprint edges against the new section's own ground (heights are the new map's terrain)
  useEffect(() => {
    if (!ext || !lvl.bundle || !m.terrain) { c.setClientItems('seam', []); return }
    let live = true
    const t = setTimeout(async () => {
      try {
        const rows = []
        for (const edge of ['n', 's', 'e', 'w']) rows.push((await world('edge', { map: m, edge })).profile)
        const api = apiRef.current
        if (!api?.castDown) return
        let worst = 0, n = 0, at = null
        for (const pr of rows.filter(Boolean)) pr.points.forEach((p, i) => {
          const hs = api.castDown(p[0], p[1], 4000)
          if (!hs.length) return
          n += 1
          const d = Math.abs(hs[hs.length - 1] - pr.heights[i] - (m.terrain.base || 0) * 0)
          if (d > worst) { worst = d; at = p }
        })
        if (!live) return
        c.setClientItems('seam', n && worst > 1.5 ? [{ map: mapIndex, level: worst > 4 ? 'error' : 'warn', title: tr('ground_at_the_seam_differs', { d: worst.toFixed(1), n }), detail: at ? tr('worst_near', { x: Math.round(at[0]), z: Math.round(at[1]) }) : '', where: 'seam' }] : [])
      } catch { /* the host is still opening */ }
    }, 1200)
    return () => { live = false; clearTimeout(t) }
  }, [ext, lvl.bundle, m?.terrain, mapIndex])
  const seamItems = (c.analysis?.maps?.[mapIndex]?.items || []).filter(x => ['light', 'fog', 'road_width'].includes(x.code)).concat((c.clientItems.seam || []))

  // ---- placing
  const ghostSize = ext ? W.rectSize(extRect) : mine ? W.rectSize(mine.rect) : [80, 80]
  const planning = useMemo(() => {
    if (drawRegion && ext) return { kind: 'rect', rect: { first: regionFirst }, color: '#5b9bff', label: tr('carried_over'), planeY: 0 }
    if (!placing || !m) return null
    return { kind: 'spot', label: m.card?.title || m.name, size: [ghostSize[0], 3, ghostSize[1]], color: NEW, yaw: mine?.a.yaw || 0, planeY: 0, facingDrag: false }
  }, [placing, drawRegion, regionFirst, m, ghostSize.join(), mine?.a.yaw, ext])
  const onPlace = (pos, yaw) => {
    if (drawRegion && ext) {
      if (!regionFirst) { setRegionFirst([pos[0], pos[2]]); return }
      const r = [Math.min(regionFirst[0], pos[0]), Math.min(regionFirst[1], pos[2]), Math.max(regionFirst[0], pos[0]), Math.max(regionFirst[1], pos[2])].map(v => Math.round(v))
      editMap({ ...m, carry: { mode: 'region', region: r } }); setDrawRegion(false); setRegionFirst(null); return
    }
    if (ext) {
      const [w, l] = ghostSize
      const o = [Math.round(pos[0] - w / 2), Math.round(pos[2] - l / 2)]
      editMap({ ...m, terrain: { ...(m.terrain || { cell: 2, size: [60, 60] }), origin: o } }); setPlacing(false); return
    }
    const s = W.snapFootprint([pos[0], pos[2]], W.rectSize(W.aabb(W.atlasCorners(W.ownRect(m), [0, 0], W.snapYaw(yaw)))), others)
    setSnapNote({ guides: s.guides })
    editMap({ ...m, atlas: { pos: s.pos, yaw: W.snapYaw(yaw) } }); setPlacing(false)
  }
  const focus = useMemo(() => {
    if (frameTo) return { bounds: frameTo, y: 0 }
    if (ext && extRect) { const ps = [m.host?.enter?.pos, m.host?.leave?.pos].filter(Boolean); return { bounds: [Math.min(extRect[0], ...ps.map(p => p[0])) - 60, Math.min(extRect[1], ...ps.map(p => p[2])) - 60, Math.max(extRect[2], ...ps.map(p => p[0])) + 60, Math.max(extRect[3], ...ps.map(p => p[2])) + 60], y: 0 } }
    const xs = [...ships.flatMap(s => s.box ? [s.box[0], s.box[2]] : []), ...footprints.flatMap(f => [f.box[0], f.box[2]])]
    const zs = [...ships.flatMap(s => s.box ? [s.box[1], s.box[3]] : []), ...footprints.flatMap(f => [f.box[1], f.box[3]])]
    return xs.length ? { bounds: [Math.min(...xs) - 200, Math.min(...zs) - 200, Math.max(...xs) + 200, Math.max(...zs) + 200], y: 0 } : null
  }, [ships.length, ext, extRect?.join(), frameTo, mapIndex, footprints.length])
  const [pickedShip, setPickedShip] = useState(null)
  const pick = id => {
    if (id.startsWith('new:')) c.setMapIndex(Number(id.slice(4)))
    else if (id.startsWith('ship:')) { setPickedShip(id.slice(5)); const s = ships.find(x => x.id === id.slice(5)); if (s?.box) setFrameTo(s.box) }
    else if (id.startsWith('ext:')) c.setMapIndex(Number(id.slice(4)))
  }
  // ---- the mode of the selected map
  const setMode = mode => {
    if (!m || mode === (m.placement || 'separate')) return
    const next = { ...m, placement: mode }
    if (mode === 'extension') {
      const h = hosts.find(x => x.section_copy && x.offer) || hosts.find(x => x.section_copy)
      const block = m.host?.block || h?.block || 'submap01_map02_lostoros_downtown.submap'
      const b = W.boxAround(block, bounds)
      next.host = m.host || { block, enter: { pos: b.enter, size: [12, 6, 2], orient: [0, 0.70710678, 0, 0.70710678] }, leave: { pos: b.leave, size: [12, 6, 2], orient: [0, 0.70710678, 0, 0.70710678] }, prompt: 'touch' }
      next.carry = m.carry || { mode: 'all' }
      next.terrain = m.terrain || { cell: 2, size: [60, 60], origin: b.origin, noise: { seed: 1, amp: 0.2, scale: 30 } }
    }
    if (mode === 'aligned' && !m.neighbour) next.neighbour = { map: 'map02', edge: 'e', offset: [0, 0, 0], yaw: 0 }
    editMap(next)
  }
  const modes = [{ value: 'separate', label: tr('separate') }, ...(advanced || m?.placement !== 'separate' && m?.placement ? [{ value: 'extension', label: tr('extension') }, { value: 'aligned', label: tr('aligned') }] : [])]
  const hostRow = hosts.find(h => h.block === W.short(m?.host?.block))
  const sectionHosts = hosts.filter(h => h.section_copy)
  const nb = m?.neighbour
  const snapToNeighbour = () => {
    const nbBox = nbRect(nb, ships, footprints, params)
    if (!nbBox || !mine) return
    const [w, l] = W.rectSize(mine.rect)
    const e = nb.edge || 'e', off = nb.offset || [0, 0, 0]
    const cx = e === 'e' ? nbBox[2] + w / 2 + off[0] : e === 'w' ? nbBox[0] - w / 2 - off[0] : (nbBox[0] + nbBox[2]) / 2 + off[0]
    const cz = e === 'n' ? nbBox[3] + l / 2 + off[2] : e === 's' ? nbBox[1] - l / 2 - off[2] : (nbBox[1] + nbBox[3]) / 2 + off[2]
    editMap({ ...m, atlas: { pos: [Math.round(cx), Math.round(cz)], yaw: 0 } })
  }
  const listOf = footprints.filter(f => f.p.cur)

  return <div className="split">
    <div className="panel-l" style={{ overflow: 'auto', padding: '12px 8px' }}>
      <div className="upper" style={{ padding: '0 8px 6px' }}>{tr('new_maps')}</div>
      {(params?.maps || []).map((mm, i) => <div key={i} className={'li' + (i === mapIndex ? ' sel' : '')} role="button" tabIndex={0} aria-label={mm.card?.title || mm.name}
        onClick={() => { c.setMapIndex(i); setFrameTo(null) }} onKeyDown={e => e.key === 'Enter' && c.setMapIndex(i)} title={mm.name}>
        <span className="nm">{mm.card?.title || mm.name}</span><span className="ty">{{ separate: '◻', extension: '▭', aligned: '▯' }[mm.placement || 'separate']} {(mm.placement || 'separate') === 'separate' ? tr('separate') : mm.placement === 'extension' ? tr('extension') : tr('aligned')}</span></div>)}
      <div className="upper" style={{ padding: '14px 8px 6px' }}>{tr('shipped_maps')}</div>
      {ships.map(s => <div key={s.id} className={'li' + (pickedShip === s.id ? ' sel' : '')} role="button" tabIndex={0} aria-label={titleOf(s.id)}
        onClick={() => pick('ship:' + s.id)} onKeyDown={e => e.key === 'Enter' && pick('ship:' + s.id)}>
        <span aria-hidden style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flex: 'none' }} /><span className="nm">{titleOf(s.id)}</span></div>)}
    </div>
    <View3D defaultMode="top" bundle={ext ? lvl.bundle : null} view={ext ? lvl.view : null} layers={CONTEXT_LAYERS} apiRef={apiRef}
      overlays={ext ? hostOv : overlays} focus={focus} planeY={0} scene={!ext ? <StandIns items={tiles} /> : null} placing={planning}
      onPickOverlay={pick} onPlace={onPlace} snap={{ grid: 0, angle: 15, mode: 'ground' }} grid={!ext}>
      <div style={{ position: 'absolute', left: 12, top: 12, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', maxWidth: 'calc(100% - 135px)' }}>
        <button className={'sm' + (placing ? ' on' : '')} aria-pressed={placing} disabled={!m} onClick={() => { setPlacing(!placing); setDrawRegion(false) }}
          title={tr('click_where_the_map_goes_r')}>{ext ? tr('place_the_section') : tr('place_on_the_layout')}</button>
        {guard?.out && <span className="badge" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }} title={tr('beyond_16_km_precision_drops')}>{'⚠ '}{tr('outside_the_safe_box')}</span>}
        {guard?.over?.length > 0 && <span className="badge" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>{'⚠ '}{tr('overlaps_another_map')}</span>}
        {ext && lvl.busy && <span className="small muted">{lvl.busy}{'…'}</span>}{ext && lvl.err && <span className="small warn" title={lvl.err}>{tr('no_map')}</span>}
      </div>
      <div className="floatpanel" style={{ left: 12, bottom: 12 }}>{ext ? tr('real_geometry_of_the_host_section') : tr('editor_layout_each_map_has_its')}</div>
    </View3D>
    <div className="panel-r">
      <div className="panel-h"><div className="grow"><div className="t">{m ? (m.card?.title || m.name) : tr('world')}</div></div></div>
      <div className="panel-b">
        {m && <>
          <div className="upper">{tr('placement')}</div>
          <Seg value={m.placement || 'separate'} onChange={setMode} options={modes} label={tr('placement')} />
          {(m.placement || 'separate') === 'separate' && <>
            <div className="axes"><Num label={tr('x')} value={mine?.a.pos[0] ?? 0} onChange={v => editMap({ ...m, atlas: { pos: [v, mine?.a.pos[1] ?? 0], yaw: mine?.a.yaw || 0 } })} />
              <Num label={tr('z_909f99')} value={mine?.a.pos[1] ?? 0} onChange={v => editMap({ ...m, atlas: { pos: [mine?.a.pos[0] ?? 0, v], yaw: mine?.a.yaw || 0 } })} />
              <Num label={'°'} value={mine?.a.yaw ?? 0} step={15} onChange={v => editMap({ ...m, atlas: { pos: mine?.a.pos || [0, 0], yaw: W.snapYaw(v) } })} /></div>
            <div className="small muted">{W.compassOf(mine?.a.yaw || 0)}{' · '}{Math.round(W.rectSize(W.ownRect(m))[0])}{' × '}{Math.round(W.rectSize(W.ownRect(m))[1])}{' m'}</div>
          </>}
          {ext && <>
            <label>{tr('host_section')}<select aria-label={tr('host_section')} value={W.short(m.host?.block)} onChange={e => editMap({ ...m, host: { ...m.host, block: e.target.value } })}>
              {sectionHosts.map(h => <option key={h.block} value={h.block} disabled={!h.offer}>{h.label}{h.offer ? '' : ' ✕'}</option>)}
              {!sectionHosts.some(h => h.block === W.short(m.host?.block)) && <option value={W.short(m.host?.block)}>{W.short(m.host?.block)}</option>}</select></label>
            {hostRow && <div className="small" title={hostRow.reason || hostRow.proven || ''}>
              <span className={'badge ' + (hostRow.offer ? 'ok' : '')}>{hostRow.offer ? (/^proven/.test(hostRow.proven || '') ? tr('tested_in_game') : tr('can_host')) : tr('cannot_host')}</span>
              {hostRow.free_main != null && <span className="muted">{' '}{tr('main')} {hostRow.free_main}{' · '}{tr('aux')} {hostRow.free_aux}{' '}{tr('free')}</span>}</div>}
            <div className="upper" style={{ marginTop: 6 }}>{tr('carry_over')}</div>
            <Seg value={m.carry?.mode || 'all'} onChange={v => editMap({ ...m, carry: v === 'region' ? { mode: 'region', region: m.carry?.region || [extRect[0], extRect[1], extRect[2], extRect[3]] } : { mode: v } })}
              options={[{ value: 'all', label: tr('all') }, ...(m.carry?.mode === 'region' ? [{ value: 'region', label: tr('region') }] : []), { value: 'nothing', label: tr('nothing') }]} label={tr('carry_over')} />
            {m.carry?.mode === 'region' && <button className={'sm' + (drawRegion ? ' on' : '')} onClick={() => { setDrawRegion(!drawRegion); setRegionFirst(null); setPlacing(false) }}>{drawRegion ? tr('click_the_second_corner') : tr('draw_on_the_host')}</button>}
            <div className="axes"><Num label={tr('x')} value={extRect[0]} onChange={v => editMap({ ...m, terrain: { ...m.terrain, origin: [v, extRect[1]] } })} />
              <Num label={tr('z_909f99')} value={extRect[1]} onChange={v => editMap({ ...m, terrain: { ...m.terrain, origin: [extRect[0], v] } })} /></div>
          </>}
          {m.placement === 'aligned' && nb && <>
            <label>{tr('neighbour')}<select aria-label={tr('neighbour')} value={nb.map} onChange={e => editMap({ ...m, neighbour: { ...nb, map: e.target.value } })}>
              {[...ships.map(s => <option key={s.id} value={s.id}>{titleOf(s.id)}</option>), ...(params.maps || []).filter((_, i) => i !== mapIndex).map(x => <option key={x.name} value={x.name}>{x.name}</option>)]}</select></label>
            <Seg value={nb.edge || 'e'} onChange={v => editMap({ ...m, neighbour: { ...nb, edge: v } })} label={tr('edge')}
              options={[{ value: 'n', label: tr('north') }, { value: 'e', label: tr('east') }, { value: 's', label: tr('south') }, { value: 'w', label: tr('west') }]} />
            <div className="axes"><Num label={tr('along')} value={(nb.offset || [0, 0, 0])[0]} onChange={v => editMap({ ...m, neighbour: { ...nb, offset: [v, (nb.offset || [0, 0, 0])[1], (nb.offset || [0, 0, 0])[2]] } })} />
              <Num label={tr('gap')} value={(nb.offset || [0, 0, 0])[2]} onChange={v => editMap({ ...m, neighbour: { ...nb, offset: [(nb.offset || [0, 0, 0])[0], (nb.offset || [0, 0, 0])[1], v] } })} /></div>
            <button className="sm" onClick={snapToNeighbour}>{tr('snap_to_the_neighbour')}</button>
          </>}
          {(guard?.out || guard?.over?.length > 0) && <div className="callout warn small" role="status">{guard.out ? tr('outside_the_safe_box') : tr('overlaps_another_map')}</div>}
          {advanced && seamItems.length > 0 && <>
            <div className="upper" style={{ marginTop: 6 }}>{tr('seam')}</div>
            {seamItems.map((x, i) => <div key={i} className="small" title={x.detail}><span className={x.level === 'error' ? 'bad' : 'warn'}>{x.level === 'error' ? '✕' : '⚠'}</span>{' '}{x.title}</div>)}
          </>}
          {advanced && m.placement && m.placement !== 'separate' && seamItems.length === 0 && <div className="small muted">{tr('seam_no_mismatch_found')}</div>}
        </>}
        {!m && <div className="muted small">{tr('no_map_project_open')}</div>}
      </div>
    </div>
  </div>
}

// labels that would sit on each other (Map02 and the projects beside it) move to a free slot and get a leader line
function spreadLabels(list, [w, h]) {
  const items = list.filter(o => o.always && o.label && o.at).map(o => ({ id: o.id, x: o.at[0], z: o.at[1] }))
  if (items.length < 2) return list
  const by = Object.fromEntries(W.declutter(items, w * 0.16, h * 0.04).map(x => [x.id, x]))
  const out = []
  for (const o of list) {
    const d = by[o.id]
    if (!d?.moved) { out.push(o); continue }
    out.push({ ...o, label: undefined })
    out.push({ id: 'lead:' + o.id, kind: 'path', points: [[d.x, 1, d.z], [d.lx, 1, d.lz]], color: o.color, pickable: false, layer: o.layer })
    out.push({ id: 'tag:' + o.id, kind: 'point', pos: [d.lx, 1, d.lz], radius: 1, color: o.color, label: o.label, always: true, pickable: false, layer: o.layer })
  }
  return out
}

// the box of a neighbour (a shipped map id or another map of the project) in the layout
function nbRect(nb, ships, footprints, params) {
  const s = ships.find(x => x.id === nb.map)
  if (s?.box) return s.box
  const f = footprints.find(x => x.p.cur && x.mm.name === nb.map)
  return f ? f.box : null
}
// a strip along one edge of a box, inside it
function stripOf(b, edge, w) {
  return { e: [b[2] - w, b[1], b[2], b[3]], w: [b[0], b[1], b[0] + w, b[3]], n: [b[0], b[3] - w, b[2], b[3]], s: [b[0], b[1], b[2], b[1] + w] }[edge] || b
}
