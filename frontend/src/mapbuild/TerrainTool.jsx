// Terrain: brushes (raise, lower, smooth, flatten, ramp) that are stored as the recipe's stroke list, a live triangle readout and
// heightmap files (16-bit PNG, raw). The brush is applied to a local copy of the grid while you drag (same maths as the builder); the
// finished stroke is ONE commit, then the server's own result replaces the local grid.
import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { post } from '../api.js'
import { usePointer } from './hooks.js'
import { applyStroke, heightAt, triangles, r2, clamp, stampsAlong, b64ToBytes, bytesToB64 } from './geo.js'
import { updateTerrain, ringOf, lineOf, toV } from './layer.js'
import { Sld, Num, Pick, Chips, Head, saveBlob } from './common.jsx'
import { t as tr } from '../i18n.js'

const mem = { tool: 'raise', radius: 8, strength: 0.5, falloff: 'smooth' }
const TOOLS = [
  { value: 'raise', label: tr('raise'), tip: tr('push_the_ground_up_metres_per') }, { value: 'lower', label: tr('lower'), tip: tr('dig_the_ground_down_metres_per') },
  { value: 'smooth', label: tr('smooth'), tip: tr('even_out_bumps') }, { value: 'flatten', label: tr('flatten'), tip: tr('level_to_the_height_where_you') },
  { value: 'ramp', label: tr('ramp'), tip: tr('drag_from_the_low_end_to') }]
const SIZES = [{ value: 'small', label: tr('small'), cells: 60, cell: 2 }, { value: 'medium', label: tr('medium'), cells: 120, cell: 2 }, { value: 'large', label: tr('large'), cells: 200, cell: 2 }]

export default function TerrainTool({ c }) {
  const { map, put, api, layer, grid, terrainRef, setRev } = c
  const t = map.terrain
  const [s, setS] = useState(mem)
  const [size, setSize] = useState('small')
  const [hm, setHm] = useState({ lo: 0, hi: 20, cell: 2, nx: 60, nz: 60 })
  const [tris, setTris] = useState(null)
  const [note, setNote] = useState('')
  const st = useRef(null)
  const S = useRef(s); S.current = s; Object.assign(mem, s)
  const T = useRef(t); T.current = t
  const set = p => setS(o => ({ ...o, ...p }))

  const refresh = box => { const T0 = terrainRef.current; if (T0) { updateTerrain(T0, box[0], box[1], box[2], box[3]); setTris(triangles(grid.current)) } }
  const stampAt = pos => {
    const o = S.current
    const base = { tool: o.tool, pos: [r2(pos[0]), r2(pos[1])], radius: o.radius, strength: o.tool === 'smooth' || o.tool === 'flatten' ? Math.min(1, o.strength) : o.strength, falloff: o.falloff }
    if (o.tool === 'flatten') base.height = st.current?.height ?? r2(heightAt(grid.current, pos[0], pos[1]))
    return base
  }
  const ring = pos => {
    if (!layer) return
    const g = new THREE.Group(); g.userData = { overlay: true }
    const r = ringOf(S.current.radius, '#7cc4ff')
    g.add(r); g.position.copy(toV(pos[0], (grid.current ? heightAt(grid.current, pos[0], pos[2]) : pos[1]) + 0.3, pos[2]))
    layer.set('brush', g)
  }
  useEffect(() => () => { layer?.drop('brush'); layer?.drop('ramp') }, [layer])

  const commit = stamps => { if (stamps.length) put({ terrain: { ...T.current, strokes: [...(T.current.strokes || []), ...stamps] } }) }
  usePointer(api, {
    active: !!t && !!grid.current,
    onDown: h => {
      if (!grid.current) return false
      const p = [h.pos[0], h.pos[2]], o = S.current
      if (o.tool === 'ramp') { st.current = { ramp: true, from: p, fromH: r2(heightAt(grid.current, p[0], p[1])) }; return true }
      st.current = { stamps: [], last: p, height: o.tool === 'flatten' ? r2(heightAt(grid.current, p[0], p[1])) : undefined }
      const sm = stampAt(p)
      st.current.stamps.push(sm); refresh(applyStroke(grid.current, sm))
      return true
    },
    onMove: h => {
      const g = st.current
      if (!g) return
      const p = [h.pos[0], h.pos[2]]
      ring(h.pos)
      if (g.ramp) {
        layer?.set('ramp', lineOf([[g.from[0], g.fromH + 0.5, g.from[1]], [p[0], heightAt(grid.current, p[0], p[1]) + 0.5, p[1]]], '#f2a541'))
        g.to = p; return
      }
      const spacing = Math.max(grid.current.cell, S.current.radius * 0.5)
      if (Math.hypot(p[0] - g.last[0], p[1] - g.last[1]) < spacing) return
      for (const q of stampsAlong(g.last, p, spacing)) { const sm = stampAt(q); g.stamps.push(sm); refresh(applyStroke(grid.current, sm)) }
      g.last = p
    },
    onUp: () => {
      const g = st.current; st.current = null
      layer?.drop('ramp')
      if (!g) return
      if (g.ramp) {
        if (!g.to || Math.hypot(g.to[0] - g.from[0], g.to[1] - g.from[1]) < 1) return
        const sm = { tool: 'ramp', pos: g.from.map(r2), to: g.to.map(r2), radius: S.current.radius, strength: 1, falloff: S.current.falloff, height: g.fromH, to_height: r2(heightAt(grid.current, g.to[0], g.to[1])) }
        applyStroke(grid.current, sm); refresh([0, grid.current.nx, 0, grid.current.nz]); commit([sm]); return
      }
      commit(g.stamps)
    },
    onHover: h => ring(h.pos),
    onKey: e => {
      if (e.key === '[') set({ radius: clamp(S.current.radius / 1.25, 1, 80) })
      else if (e.key === ']') set({ radius: clamp(S.current.radius * 1.25, 1, 80) })
      else if (e.key === '-') set({ strength: clamp(S.current.strength / 1.25, 0.05, 5) })
      else if (e.key === '=') set({ strength: clamp(S.current.strength * 1.25, 0.05, 5) })
      else if (e.key === 'Enter' && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) stampHere(api.centerPoint())
    },
    onPad: (name, h) => {
      if (name === 'A') stampHere(h.pos)
      else if (name === 'X') set({ radius: S.current.radius >= 40 ? 3 : S.current.radius * 1.5 })
      else if (name === 'Y') set({ strength: S.current.strength >= 3 ? 0.2 : S.current.strength * 1.6 })
    },
  })
  // a keyboard or pad stroke: one stamp at the centre reticle, one commit
  const stampHere = pos => {
    if (!grid.current || S.current.tool === 'ramp') return
    st.current = { height: S.current.tool === 'flatten' ? r2(heightAt(grid.current, pos[0], pos[2])) : undefined }
    const sm = stampAt([pos[0], pos[2]]); st.current = null
    refresh(applyStroke(grid.current, sm)); commit([sm])
  }

  const create = () => {
    const z = SIZES.find(x => x.value === size)
    put({ terrain: { cell: z.cell, size: [z.cells, z.cells], base: 0, strokes: [] } })
  }
  const exportMap = async kind => {
    try {
      const r = await post('/api/mapbuild/heightmap', { map: { name: map.name, terrain: map.terrain }, kind })
      saveBlob((map.name || 'terrain') + (kind === 'raw' ? '.raw' : '.png'), b64ToBytes(r.data), kind === 'raw' ? 'application/octet-stream' : 'image/png')
      setNote(kind === 'png' ? tr('height_picture_note', { hi: r2(r.hi), lo: r2(r.lo) }) : tr('n_by_n_values', { x: r.nx + 1, z: r.nz + 1 }))
      if (kind === 'png') setHm(h => ({ ...h, lo: r2(r.lo), hi: r2(r.hi) }))
    } catch (e) { setNote(e.message) }
  }
  const importFile = async file => {
    if (!file) return
    const raw = /\.raw$|\.r32$/i.test(file.name)
    try {
      const data = bytesToB64(new Uint8Array(await file.arrayBuffer()))
      const r = await post('/api/mapbuild/heightmap', { action: 'import', data, kind: raw ? 'raw' : 'png', lo: hm.lo, hi: hm.hi, cell: hm.cell, nx: hm.nx, nz: hm.nz, origin: map.terrain?.origin || null })
      put({ terrain: { ...r.terrain, strokes: [] } }); setNote('')
    } catch (e) { setNote(e.message) }
  }

  if (!t) return <div className="mb-body">
    <Head>{tr('new_terrain')}</Head>
    <Chips label={tr('size')} value={size} onChange={setSize} options={SIZES.map(x => ({ value: x.value, label: x.label, tip: `${x.cells * x.cell} m across` }))} />
    <button className="primary" onClick={create}>{tr('make_the_ground')}</button>
    <Head>{tr('heightmap')}</Head>
    <HeightmapIn hm={hm} setHm={setHm} onFile={importFile} />
    {note && <p className="small warn">{note}</p>}
  </div>
  const g = grid.current
  return <div className="mb-body">
    <Chips label={tr('brush')} value={s.tool} onChange={v => set({ tool: v })} options={TOOLS} />
    <Sld label={tr('size')} value={s.radius} min={1} max={60} step={0.5} unit="m" onChange={v => set({ radius: v })} tip={tr('and_change_it')} />
    <Sld label={tr('strength')} value={s.strength} min={0.05} max={s.tool === 'smooth' || s.tool === 'flatten' ? 1 : 5} step={0.05} onChange={v => set({ strength: v })} tip={tr('and_change_it_5f5096')} />
    <Pick label={tr('edge')} value={s.falloff} onChange={v => set({ falloff: v })} options={[{ value: 'smooth', label: tr('soft') }, { value: 'linear', label: tr('linear') }, { value: 'flat', label: tr('hard') }]} />
    <div className="mb-stat" title={tr('the_ground_is_drawn_as_two')}>{'△ '}{(tris ?? (g ? triangles(g) : 0)).toLocaleString('en-US')}{g ? ` · ${g.nx} × ${g.nz} · ${r2(g.nx * g.cell)} × ${r2(g.nz * g.cell)} m` : ''}</div>
    <p className="small muted mb-hint" title={tr('click_or_drag_on_the_ground')}>{(t.strokes || []).length}{' '}{tr('strokes')}</p>
    <Head>{tr('heightmap')}</Head>
    <div className="mb-btns"><button onClick={() => exportMap('png')} title={tr('a_16_bit_grey_picture')}>{tr('save_png')}</button><button onClick={() => exportMap('raw')} title={tr('raw_32_bit_numbers')}>{tr('save_raw')}</button></div>
    <HeightmapIn hm={hm} setHm={setHm} onFile={importFile} />
    {note && <p className="small warn">{note}</p>}
    <Num label={tr('base_height')} value={t.base ?? 0} unit="m" onChange={v => put({ terrain: { ...t, base: v } })} tip={tr('height_of_a_fresh_grid_only')} />
  </div>
}

function HeightmapIn({ hm, setHm, onFile }) {
  return <div className="mb-hm">
    <div className="mb-row two"><span className="k">{tr('low')}</span><input aria-label={tr('low_in_metres')} type="number" value={hm.lo} onChange={e => setHm({ ...hm, lo: Number(e.target.value) })} /></div>
    <div className="mb-row two"><span className="k">{tr('high')}</span><input aria-label={tr('high_in_metres')} type="number" value={hm.hi} onChange={e => setHm({ ...hm, hi: Number(e.target.value) })} /></div>
    <div className="mb-row two"><span className="k">{tr('cell')}</span><input aria-label={tr('cell_in_metres')} type="number" min="0.5" max="16" step="0.5" value={hm.cell} onChange={e => setHm({ ...hm, cell: Number(e.target.value) })} /></div>
    <label className="mb-file"><span className="btn">{tr('load_picture_or_raw')}</span><input type="file" accept=".png,.raw,.r32" onChange={e => { onFile(e.target.files?.[0]); e.target.value = '' }} /></label>
  </div>
}
