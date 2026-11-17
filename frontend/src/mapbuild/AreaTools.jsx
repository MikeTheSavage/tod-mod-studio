// Areas drawn on the ground: edges (cliff or invisible wall, with a kill plane), water (level and rule) and scatter (trees, rocks, bushes).
// Polygon: click the corners, Enter or the first corner closes it. Rectangle and circle: drag. Corners of a polygon can be dragged after.
import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { usePointer } from './hooks.js'
import { heightAt, r2, polyOf, polyArea, rectOf, newId } from './geo.js'
import { polyLine, marker, lineOf, toV, textSprite } from './layer.js'
import { Sld, Num, Pick, Chips, Head, List, Check } from './common.jsx'
import { t as tr } from '../i18n.js'

const SECTION = { edges: 'edges', water: 'water', scatter: 'scatter' }
const COLOR = { edges: '#ff9f5a', water: '#4aa8ff', scatter: '#7be08a' }
const SHAPES = [{ value: 'polygon', label: tr('polygon'), tip: tr('click_the_corners_enter_closes_it') }, { value: 'rect', label: tr('box'), tip: tr('drag_from_corner_to_corner') }, { value: 'circle', label: tr('circle'), tip: tr('drag_from_the_centre') }]
const SETS = { forest: { label: tr('forest'), items: [{ kind: 'tree', weight: 8 }, { kind: 'bush', weight: 2 }, { kind: 'rock', weight: 1 }] }, rocky: { label: tr('rocky'), items: [{ kind: 'rock', weight: 8 }, { kind: 'bush', weight: 1 }] },
  scrub: { label: tr('scrub'), items: [{ kind: 'bush', weight: 8 }, { kind: 'rock', weight: 2 }, { kind: 'tree', weight: 1 }] }, mixed: { label: tr('mixed'), items: [{ kind: 'tree', weight: 4 }, { kind: 'rock', weight: 3 }, { kind: 'bush', weight: 3 }] } }
const mem = { shape: 'polygon', section: 'edges' }

const freshEdge = list => ({ id: newId(list, 'edge'), kind: 'cliff', height: 8, thickness: 1.2 })
const freshWater = list => ({ id: newId(list, 'pond'), level: null, depth: 2, bank: 5, rule: 'reset' })
const freshScatter = list => ({ id: newId(list, 'trees'), items: SETS.forest.items, density: 0.01, seed: 1, slope_max: 0.5, min_dist: 2.5, avoid_roads: 2, avoid_water: 1, variants: 3, max: 2000 })

export default function AreaTools({ c, which }) {
  const { map, put, api, layer, grid, pv } = c
  const [section, setSection] = useState(which === 'scatter' ? 'scatter' : mem.section === 'water' ? 'water' : 'edges')
  const [shape, setShape] = useState(mem.shape)
  mem.shape = shape; if (which !== 'scatter') mem.section = section
  const key = which === 'scatter' ? 'scatter' : SECTION[section]
  const list = map[key] || []
  const [sel, setSel] = useState(list.length ? 0 : -1)
  const [drawing, setDrawing] = useState(null)         // { shape, pts } while a shape is being made
  const [draft, setDraft] = useState(null)             // an edited polygon while a corner is dragged
  const L = useRef(list); L.current = list
  const S = useRef({ sel, shape, key }); S.current = { sel, shape, key }
  const dr = useRef(drawing); dr.current = drawing
  const dd = useRef(draft); dd.current = draft
  const g = useRef(null)
  const fresh = key === 'edges' ? freshEdge : key === 'water' ? freshWater : freshScatter
  useEffect(() => { setSel(list.length ? 0 : -1); setDrawing(null) }, [key])
  const setList = next => put({ [key]: next })
  const spec = (shapeName, pts) => (shapeName === 'polygon' ? { polygon: pts.map(p => [r2(p[0]), r2(p[1])]) } : shapeName === 'rect' ? { rect: rectOf(pts[0], pts[1]) } : { circle: [r2(pts[0][0]), r2(pts[0][1]), r2(Math.max(1, Math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])))] })
  const finish = (shapeName, pts) => {
    const area = spec(shapeName, pts)
    const item = { ...fresh(L.current), ...area }
    setList([...L.current, item]); setSel(L.current.length); setDrawing(null)
  }
  const gh = (x, z) => (grid.current ? heightAt(grid.current, x, z) : 0)

  // ---- drawing of every area, the selected one with corner handles
  useEffect(() => {
    if (!layer) return
    const grp = new THREE.Group(); grp.userData = { overlay: true }
    const all = [...(map.edges || []).map(a => ['edges', a]), ...(map.water || []).map(a => ['water', a]), ...(map.scatter || []).map(a => ['scatter', a])]
    all.forEach(([k, a]) => {
      const mine = k === key
      const idx = (map[k] || []).indexOf(a)
      const isSel = mine && idx === sel
      const poly = (isSel && draft) ? draft : polyOf(a)
      if (poly.length < 3) return
      grp.add(polyLine(poly, grid.current, COLOR[k], 0.5, { dashed: k === 'scatter', opacity: isSel ? 1 : mine ? 0.75 : 0.35 }))
      if (isSel) {
        if (a.polygon || draft) poly.forEach((p, i) => grp.add(marker([p[0], gh(p[0], p[1]) + 1, p[1]], 'square', '#ffffff', 0.026)))
        const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length, cz = poly.reduce((s, p) => s + p[1], 0) / poly.length
        const t = textSprite(a.id, '#ffffff', 0.03); t.position.copy(toV(cx, gh(cx, cz) + 3, cz)); grp.add(t)
      }
    })
    if (drawing) {
      const pts = drawing.pts.map(p => [p[0], gh(p[0], p[1]) + 0.6, p[1]])
      if (drawing.hover && drawing.shape === 'polygon') pts.push([drawing.hover[0], gh(drawing.hover[0], drawing.hover[1]) + 0.6, drawing.hover[1]])
      if (drawing.shape === 'polygon' && pts.length > 1) grp.add(lineOf(pts, '#f2a541'))
      if (drawing.shape !== 'polygon' && drawing.pts.length === 2) grp.add(polyLine(polyOf(spec(drawing.shape, drawing.pts)), grid.current, '#f2a541', 0.6))
      drawing.pts.forEach(p => grp.add(marker([p[0], gh(p[0], p[1]) + 1, p[1]], 'dot', '#f2a541', 0.028)))
    }
    layer.set('areas', grp)
    return () => layer.drop('areas')
  }, [layer, map.edges, map.water, map.scatter, key, sel, drawing, draft, c.rev])

  usePointer(api, {
    active: true,
    onDown: (h, ev) => {
      const a = L.current[S.current.sel]
      const rect = api.gl.domElement.getBoundingClientRect(), m = { x: ev.clientX - rect.left, y: ev.clientY - rect.top }
      const p = [h.pos[0], h.pos[2]]
      if (!dr.current && a && a.polygon) {                              // a corner of the selected polygon?
        for (let i = 0; i < a.polygon.length; i++) {
          const s = api.project([a.polygon[i][0], gh(a.polygon[i][0], a.polygon[i][1]) + 1, a.polygon[i][1]])
          if (s && Math.hypot(s.x - m.x, s.y - m.y) < 14) { g.current = { corner: i }; setDraft(a.polygon.map(q => q.slice())); return true }
        }
      }
      const sh = S.current.shape
      if (sh === 'polygon') {
        const cur = dr.current
        if (cur && cur.pts.length >= 3) {
          const s = api.project([cur.pts[0][0], gh(cur.pts[0][0], cur.pts[0][1]) + 1, cur.pts[0][1]])
          if (s && Math.hypot(s.x - m.x, s.y - m.y) < 14) { finish('polygon', cur.pts); return true }
        }
        setDrawing({ shape: 'polygon', pts: [...(cur?.pts || []), p] }); g.current = { click: true }
        return true
      }
      setDrawing({ shape: sh, pts: [p, p] }); g.current = { drag: true }
      return true
    },
    onMove: h => {
      const p = [h.pos[0], h.pos[2]], gg = g.current
      if (gg?.corner != null) { setDraft(dd.current.map((q, i) => (i === gg.corner ? [r2(p[0]), r2(p[1])] : q))); return }
      if (gg?.drag) setDrawing({ ...dr.current, pts: [dr.current.pts[0], p] })
    },
    onUp: () => {
      const gg = g.current; g.current = null
      if (gg?.corner != null && dd.current) { const a = L.current[S.current.sel]; setList(L.current.map((q, i) => (i === S.current.sel ? { ...a, polygon: dd.current } : q))); setDraft(null) } else if (gg?.drag) {
        const cur = dr.current
        if (cur && Math.hypot(cur.pts[1][0] - cur.pts[0][0], cur.pts[1][1] - cur.pts[0][1]) > 1) finish(cur.shape, cur.pts); else setDrawing(null)
      }
    },
    onHover: h => { if (dr.current?.shape === 'polygon') setDrawing({ ...dr.current, hover: [h.pos[0], h.pos[2]] }) },
    onKey: e => {
      if (e.key === 'Enter' && dr.current?.shape === 'polygon' && dr.current.pts.length >= 3) finish('polygon', dr.current.pts)
      else if (e.key === 'Enter' && !dr.current && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) { const p = api.centerPoint(); setDrawing({ shape: 'polygon', pts: [[p[0], p[2]]] }) }
      else if (e.key === 'Enter' && dr.current && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) { const p = api.centerPoint(); setDrawing({ ...dr.current, pts: [...dr.current.pts, [p[0], p[2]]] }) }
      else if (e.key === 'Escape') setDrawing(null)
      else if (e.key === 'Backspace' && dr.current) setDrawing({ ...dr.current, pts: dr.current.pts.slice(0, -1) })
    },
    onPad: (name, h) => { if (name === 'A') setDrawing(d => ({ shape: 'polygon', pts: [...(d?.pts || []), [h.pos[0], h.pos[2]]] })) },
  })

  const a = list[sel]
  const edit = patch => setList(list.map((q, i) => (i === sel ? { ...q, ...patch } : q)))
  const spots = [...(map.teleports || []).map(t => ({ value: t.name, label: t.name })), { value: '', label: tr('the_arrival_point') }]
  const respawnOf = v => (typeof v === 'string' ? v : '')
  const setRespawn = (obj, name) => (name ? name : (map.arrival?.pos ? [r2(map.arrival.pos[0]), r2(map.arrival.pos[2])] : [0, 0]))
  const stats = (pv?.stats?.scatter || []).find(s => s.id === a?.id)
  return <div className="mb-body">
    {which !== 'scatter' && <Chips label={tr('kind')} value={section} onChange={setSection} options={[{ value: 'edges', label: tr('edges'), tip: tr('cliffs_and_invisible_walls') }, { value: 'water', label: tr('water'), tip: tr('ponds_and_lakes') }]} />}
    <Head>{key === 'edges' ? 'Edges' : key === 'water' ? 'Water' : 'Scatter'}</Head>
    <List items={list} sel={sel} onSel={setSel} onDelete={i => { setList(list.filter((_, k) => k !== i)); setSel(Math.min(sel, list.length - 2)) }} name={x => x.id}
      extra={x => `${Math.round(polyArea(polyOf(x)))} m²`} />
    <Chips label={tr('shape')} value={shape} onChange={v => { setShape(v); setDrawing(null) }} options={SHAPES} />
    {drawing?.shape === 'polygon' && <div className="mb-btns"><button className="primary" disabled={drawing.pts.length < 3} onClick={() => finish('polygon', drawing.pts)}>{tr('close_the_shape')}</button><button onClick={() => setDrawing(null)}>{tr('cancel')}</button></div>}
    {a && key === 'edges' && <>
      <Chips label={tr('edge_kind')} value={a.kind} onChange={v => edit({ kind: v })} options={[{ value: 'cliff', label: tr('cliff'), tip: tr('a_rock_wall_you_can_see') }, { value: 'invisible', label: tr('invisible_wall'), tip: tr('stops_the_player_nothing_to_see') }]} />
      <Sld label={tr('height')} value={a.height ?? 8} min={1} max={60} step={0.5} unit="m" onChange={v => edit({ height: v })} />
      {a.kind === 'cliff' && <Sld label={tr('thickness')} value={a.thickness ?? 1.2} min={0.4} max={6} step={0.1} unit="m" onChange={v => edit({ thickness: v })} />}
      <Check label={tr('kill_plane')} on={!!a.kill} onChange={v => edit({ kill: v ? { below: -20, respawn: setRespawn(null, '') } : undefined })} tip={tr('below_this_height_a_fallen_player')} />
      {a.kill && <>
        <Num label={tr('below')} value={a.kill.below ?? -20} unit="m" digits={1} onChange={v => edit({ kill: { ...a.kill, below: v } })} tip={tr('world_height_of_the_plane')} />
        <Pick label={tr('back_to')} value={respawnOf(a.kill.respawn)} options={spots} onChange={v => edit({ kill: { ...a.kill, respawn: setRespawn(a.kill, v) } })} />
      </>}
    </>}
    {a && key === 'water' && <>
      <Num label={tr('level')} value={a.level} nullable placeholder={tr('auto_0d612c')} unit="m" digits={1} onChange={v => edit({ level: v })} tip={tr('empty_the_lowest_ground_under_it')} />
      <Sld label={tr('depth')} value={a.depth ?? 2} min={0.5} max={10} step={0.5} unit="m" onChange={v => edit({ depth: v })} />
      <Sld label={tr('bank')} value={a.bank ?? 5} min={0} max={20} step={0.5} unit="m" onChange={v => edit({ bank: v })} tip={tr('how_wide_the_shore_slopes_down')} />
      <div className="mb-row two" title={tr('you_can_t_swim_in_this')}><span className="k">{tr('if_you_fall_in')}</span>
        <Chips label={tr('rule')} value={a.rule || 'reset'} onChange={v => edit({ rule: v })} options={[{ value: 'reset', label: tr('reset'), tip: tr('back_to_a_spot') }, { value: 'kill', label: tr('fail'), tip: tr('ends_the_running_mission') }, { value: 'none', label: tr('nothing') }]} /></div>
      {(a.rule || 'reset') === 'reset' && <Pick label={tr('back_to')} value={respawnOf(a.reset)} options={spots} onChange={v => edit({ reset: setRespawn(a, v) })} />}
    </>}
    {a && key === 'scatter' && <>
      <Chips label={tr('set')} value={Object.keys(SETS).find(k => JSON.stringify(SETS[k].items) === JSON.stringify(a.items)) || ''} onChange={v => edit({ items: SETS[v].items })}
        options={Object.entries(SETS).map(([v, s]) => ({ value: v, label: s.label }))} />
      <Sld label={tr('density')} value={r2((a.density ?? 0.01) * 100)} min={0.1} max={10} step={0.1} unit="/100 m²" onChange={v => edit({ density: r2(v / 100) })} />
      <Sld label={tr('slope_limit')} value={a.slope_max ?? 0.5} min={0.1} max={1} step={0.05} onChange={v => edit({ slope_max: v })} tip={tr('nothing_grows_on_ground_steeper_than')} />
      <Sld label={tr('apart')} value={a.min_dist ?? 2.5} min={0.5} max={12} step={0.5} unit="m" onChange={v => edit({ min_dist: v })} />
      <Sld label={tr('off_roads')} value={a.avoid_roads ?? 2} min={0} max={12} step={0.5} unit="m" onChange={v => edit({ avoid_roads: v })} />
      <Sld label={tr('off_water')} value={a.avoid_water ?? 1} min={0} max={12} step={0.5} unit="m" onChange={v => edit({ avoid_water: v })} />
      <Sld label={tr('shapes')} value={a.variants ?? 3} min={1} max={5} step={1} digits={0} onChange={v => edit({ variants: v })} tip={tr('placed_models_cannot_be_turned_or')} />
      <Sld label={tr('most')} value={a.max ?? 2000} min={50} max={4000} step={50} digits={0} onChange={v => edit({ max: v })} tip={tr('a_cap_per_area_a_seeded')} />
      <Num label={tr('seed')} value={a.seed ?? 1} digits={0} onChange={v => edit({ seed: Math.round(v) })} />
      <div className={'mb-stat' + (stats?.capped ? ' hard' : '')} title={tr('every_placed_thing_is_one_node')}>{stats ? `● ${stats.instances}${stats.capped ? ' ▲ capped' : ''}` : '● …'}</div>
    </>}
    {!a && <p className="small muted">{tr('draw_a_shape_on_the_ground')}</p>}
  </div>
}
