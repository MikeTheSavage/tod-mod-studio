// Ground paint (the palette materials, capped by G1) and the separate surface-type layer (footsteps, grip, impacts), shown as an overlay
// with a pattern per type as well as a colour. Each stroke is one commit.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { usePointer } from './hooks.js'
import { updateTerrain, ringOf, lineOf, toV, surfaceTexture, swatchUrl, SURFACES, colorOfMaterial } from './layer.js'
import { heightAt, r2, clamp, stampsAlong, u8, rectOf } from './geo.js'
import { Sld, Chips, Head, Check } from './common.jsx'
import { t } from '../i18n.js'

const ALL = ['dirt', 'sand', 'asphalt', 'grass', 'rock']
const mem = { mode: 'ground', material: 'grass', surface: 'Dirt', radius: 6, shape: 'brush', overlay: true }

export default function PaintTool({ c }) {
  const { map, put, api, layer, grid, terrainRef, field, rev } = c
  const gp = map.ground_paint || {}
  const palette = (gp.palette || ['dirt']).map(p => (typeof p === 'string' ? p : p.id))
  const cap = c.pv?.rows?.find(r => r.id === 'G1')?.max ?? 6
  const [s, setS] = useState(mem)
  Object.assign(mem, s)
  const S = useRef(s); S.current = s
  const set = p => setS(o => ({ ...o, ...p }))
  const st = useRef(null)
  const GP = useRef(gp); GP.current = gp
  const names = field?.surfaces || []
  const surf = useRef(null)                                  // the local surface grid (palette-independent face material indices)
  const overlay = useRef(null)
  const dirtyTex = useRef(0)
  useEffect(() => { surf.current = field?.terrain ? Uint8Array.from(u8(field.terrain.surface)) : null }, [field])
  const showOverlay = s.mode === 'surface' && s.overlay

  // the overlay: the terrain's own geometry again, with the pattern picture on it
  const drawOverlay = () => {
    const T = terrainRef.current
    if (!T || !layer || !surf.current || !showOverlay) { layer?.drop('surface'); overlay.current = null; return }
    const tex = surfaceTexture(T.g.nx, T.g.nz, surf.current, names)
    const prev = overlay.current
    if (prev) { prev.material.map?.dispose(); prev.material.map = tex; prev.material.needsUpdate = true; return }
    const m = new THREE.Mesh(T.geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, side: THREE.DoubleSide }))
    m.userData = { overlay: true }; m.renderOrder = 5
    overlay.current = m; layer.set('surface', m)
  }
  useEffect(() => { overlay.current = null; drawOverlay() }, [layer, rev, field, showOverlay, names.length])
  useEffect(() => () => { layer?.drop('surface'); layer?.drop('brush') }, [layer])

  const tIndex = id => (field?.palette || []).findIndex(p => p.id === id)
  const maskCells = (shape, p, r, fn) => {
    const g = grid.current
    if (!g) return
    const rect = shape.rect
    const i0 = clamp(Math.floor(((rect ? rect[0] : p[0] - r) - g.ox) / g.cell - 0.5), 0, g.nx - 1), i1 = clamp(Math.ceil(((rect ? rect[2] : p[0] + r) - g.ox) / g.cell), 0, g.nx - 1)
    const j0 = clamp(Math.floor(((rect ? rect[1] : p[1] - r) - g.oz) / g.cell - 0.5), 0, g.nz - 1), j1 = clamp(Math.ceil(((rect ? rect[3] : p[1] + r) - g.oz) / g.cell), 0, g.nz - 1)
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const x = g.ox + (i + 0.5) * g.cell, z = g.oz + (j + 0.5) * g.cell
      const inside = rect ? x >= rect[0] && x <= rect[2] && z >= rect[1] && z <= rect[3] : Math.hypot(x - p[0], z - p[1]) <= r
      if (inside) fn(j * g.nx + i)
    }
    return [i0, i1, j0, j1]
  }
  const stampLocal = sm => {
    const T = terrainRef.current
    if (!T) return
    const o = S.current
    if (o.mode === 'ground') {
      const k = tIndex(sm.material)
      if (k < 0) return
      const box = maskCells(sm, sm.pos, sm.radius, idx => { T.paint[idx] = k })
      if (box) updateTerrain(T, box[0], box[1], box[2], box[3])
    } else if (surf.current) {
      const k = names.indexOf(sm.surface)
      if (k < 0) return
      maskCells(sm, sm.pos, sm.radius, idx => { surf.current[idx] = k })
      const now = performance.now()
      if (now - dirtyTex.current > 140) { dirtyTex.current = now; drawOverlay() }
    }
  }
  const mkStamp = (pos, rect) => {
    const o = S.current
    const base = o.mode === 'ground' ? { material: o.material } : { surface: o.surface }
    return rect ? { ...base, rect } : { ...base, pos: [r2(pos[0]), r2(pos[1])], radius: o.radius }
  }
  const commit = stamps => {
    if (!stamps.length) return
    const key = S.current.mode === 'ground' ? 'strokes' : 'surface_strokes'
    put({ ground_paint: { ...GP.current, palette: GP.current.palette || ['dirt'], [key]: [...(GP.current[key] || []), ...stamps] } })
  }
  const ring = pos => {
    if (!layer || !grid.current) return
    const g = new THREE.Group(); g.userData = { overlay: true }
    g.add(ringOf(S.current.shape === 'box' ? 0.01 : S.current.radius, S.current.mode === 'ground' ? '#7cc4ff' : '#ffd166'))
    g.position.copy(toV(pos[0], heightAt(grid.current, pos[0], pos[2]) + 0.3, pos[2])); layer.set('brush', g)
  }
  const ready = !!field?.terrain && !!grid.current && (s.mode === 'surface' || palette.includes(s.material))
  const paintHere = pos => { const sm = mkStamp([pos[0], pos[2]]); stampLocal(sm); drawOverlay(); commit([sm]) }
  usePointer(api, {
    active: ready,
    onDown: h => {
      const p = [h.pos[0], h.pos[2]]
      if (S.current.shape === 'box') { st.current = { box: true, from: p, to: p }; return true }
      st.current = { stamps: [], last: p }
      const sm = mkStamp(p); st.current.stamps.push(sm); stampLocal(sm)
      return true
    },
    onMove: h => {
      const g = st.current; if (!g) return
      const p = [h.pos[0], h.pos[2]]
      if (g.box) { g.to = p; const r = rectOf(g.from, p); const q = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]], [r[0], r[1]]].map(v => [v[0], heightAt(grid.current, v[0], v[1]) + 0.4, v[1]])
        layer?.set('brush', lineOf(q, '#7cc4ff')); return }
      ring(h.pos)
      const sp = Math.max(1, S.current.radius * 0.5)
      if (Math.hypot(p[0] - g.last[0], p[1] - g.last[1]) < sp) return
      for (const q of stampsAlong(g.last, p, sp)) { const sm = mkStamp(q); g.stamps.push(sm); stampLocal(sm) }
      g.last = p
    },
    onUp: () => {
      const g = st.current; st.current = null
      if (!g) return
      if (g.box) { const r = rectOf(g.from, g.to); if (r[2] - r[0] > 0.5 && r[3] - r[1] > 0.5) { const sm = mkStamp(null, r); stampLocal(sm); drawOverlay(); commit([sm]) } return }
      drawOverlay(); commit(g.stamps)
    },
    onHover: h => ring(h.pos),
    onKey: e => {
      if (e.key === '[') set({ radius: clamp(S.current.radius / 1.25, 1, 60) })
      else if (e.key === ']') set({ radius: clamp(S.current.radius * 1.25, 1, 60) })
      else if (e.key === 'Enter' && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) paintHere(api.centerPoint())
    },
    onPad: (name, h) => { if (name === 'A') paintHere(h.pos); else if (name === 'X') set({ radius: S.current.radius >= 30 ? 2 : S.current.radius * 1.5 }) },
  })

  const toggleMaterial = id => {
    const inPal = palette.includes(id)
    if (inPal && palette.length === 1) return
    if (!inPal && palette.length >= cap) return
    const next = inPal ? palette.filter(x => x !== id) : [...palette, id]
    const strokes = (gp.strokes || []).filter(x => x.material !== id)
    const g2 = { ...gp, palette: next, strokes }
    if (gp.default === id) g2.default = next[0]
    put({ ground_paint: g2 })
    if (!inPal) set({ material: id }); else if (s.material === id) set({ material: next[0] })
  }
  const swatches = useMemo(() => Object.fromEntries(SURFACES.map(x => [x.name, swatchUrl(x.name)])), [])
  if (!map.terrain) return <div className="mb-body"><p className="small muted">{t('make_the_ground_in_terrain_first')}</p></div>
  return <div className="mb-body">
    <Chips label={t('layer')} value={s.mode} onChange={v => set({ mode: v })} options={[{ value: 'ground', label: t('ground_143e94'), tip: t('what_the_ground_looks_like') }, { value: 'surface', label: t('surface'), tip: t('what_it_is_made_of_footsteps') }]} />
    {s.mode === 'ground' && <>
      <Head>{t('materials_n_of_cap', { n: palette.length, cap })}</Head>
      <div className="mb-mats" role="group" aria-label={t('materials_of_this_map')}>
        {ALL.map(id => <button key={id} className={'mb-mat' + (palette.includes(id) ? ' in' : '')} aria-pressed={palette.includes(id)} title={palette.includes(id) ? 'In this map. Click to take it out.' : palette.length >= cap ? 'The map is at its limit' : 'Add to this map'}
          onClick={() => toggleMaterial(id)}><i style={{ background: colorOfMaterial({ id }) }} />{palette.includes(id) ? '✓ ' : '+ '}{id}</button>)}
      </div>
      <Chips label={t('paint_with')} value={s.material} onChange={v => set({ material: v })} options={palette.map(id => ({ value: id, label: id }))} />
      {palette.includes('rock') && <Sld label={t('rock_above')} value={gp.rock_slope ?? 1} min={0.2} max={1} step={0.05} tip={t('cells_steeper_than_this_turn_to')} onChange={v => put({ ground_paint: { ...gp, rock_slope: v >= 1 ? null : v } })} />}
    </>}
    {s.mode === 'surface' && <>
      <Head>{t('surface')}</Head>
      <div className="mb-surfs" role="radiogroup" aria-label={t('surface_types')}>
        {SURFACES.map(x => <button key={x.name} role="radio" aria-checked={s.surface === x.name} className={'mb-surf' + (s.surface === x.name ? ' on' : '')} onClick={() => set({ surface: x.name })}
          title={x.name}><img src={swatches[x.name]} alt="" />{x.name}</button>)}
      </div>
      <Check label={t('show_on_the_ground')} on={s.overlay} onChange={v => set({ overlay: v })} />
    </>}
    <Chips label={t('shape')} value={s.shape} onChange={v => set({ shape: v })} options={[{ value: 'brush', label: t('brush') }, { value: 'box', label: t('box'), tip: t('drag_a_rectangle') }]} />
    {s.shape === 'brush' && <Sld label={t('size')} value={s.radius} min={1} max={40} step={0.5} unit="m" onChange={v => set({ radius: v })} tip={t('and_change_it')} />}
    <p className="small muted mb-hint">{(gp.strokes || []).length + (gp.surface_strokes || []).length}{' '}{t('strokes')}</p>
  </div>
}
