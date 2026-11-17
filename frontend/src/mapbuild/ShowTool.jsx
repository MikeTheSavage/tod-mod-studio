// Debug overlays: collision, routes, triggers, section bounds, spawns and the limit meter. The drawing lives in useDebugLayers so the overlays
// stay on while another tool is open; this panel is only the switches.
import React, { useEffect } from 'react'
import * as THREE from 'three'
import { polyOf } from './geo.js'
import { polyLine, lineOf, marker, textSprite, toV } from './layer.js'
import { Check, Head } from './common.jsx'
import { t as tr } from '../i18n.js'

const TRIGGER = { fall: ['cross', '#ff7070'], water: ['tri', '#4aa8ff'], end: ['square', '#f2c14e'] }
const rectPoly = (x, z, w, l) => [[x - w / 2, z - l / 2], [x + w / 2, z - l / 2], [x + w / 2, z + l / 2], [x - w / 2, z + l / 2]]

export function useDebugLayers(c, tab) {
  const { layer, map, pv, show, grid } = c
  useEffect(() => {
    if (!layer) return undefined
    const grp = new THREE.Group(); grp.userData = { overlay: true }
    if (show.spawns) {
      if (map.arrival?.pos) { const p = map.arrival.pos; grp.add(marker([p[0], p[1] + 2, p[2]], 'diamond', '#5fd38d', 0.034)); const t = textSprite('Arrival', '#5fd38d', 0.03); t.position.copy(toV(p[0], p[1] + 5, p[2])); grp.add(t) }
      if (map.return?.pos) { const p = map.return.pos; grp.add(marker([p[0], p[1] + 2, p[2]], 'square', '#f2a541', 0.03)); const t = textSprite('Return', '#f2a541', 0.03); t.position.copy(toV(p[0], p[1] + 5, p[2])); grp.add(t) }
      for (const tp of [...(map.teleports || []), ...(pv?.teleports || [])]) grp.add(marker([tp.pos[0], tp.pos[1] + 2, tp.pos[2]], 'dot', '#c7a6ff', 0.026))
    }
    if (show.triggers) {
      for (const t of pv?.triggers || []) {
        const [shape, col] = TRIGGER[t.reason] || ['square', '#ffffff']
        const poly = rectPoly(t.pos[0], t.pos[2], t.size[0], t.size[2])
        grp.add(lineOf(poly.map(p => [p[0], t.pos[1], p[1]]), col, { closed: true, dashed: true }))
        grp.add(marker(t.pos, shape, col, 0.028))
      }
      for (const w of pv?.walls || []) grp.add(lineOf(rectPoly(w.pos[0], w.pos[2], w.size[0], w.size[2]).map(p => [p[0], w.pos[1], p[1]]), '#8491a1', { closed: true, opacity: 0.8 }))
    }
    if (show.routes) {
      for (const r of pv?.traffic || []) {
        const pts = (r.points || []).map(p => p.pos)
        const col = r.direction === 'B' ? '#7be0d0' : '#4aa8ff'
        if (pts.length > 1) grp.add(lineOf(pts.map(p => [p[0], p[1] + 0.8, p[2]]), col))
        pts.forEach((p, i) => { if (i % 3 === 1) grp.add(marker([p[0], p[1] + 1, p[2]], 'tri', col, 0.016)) })
      }
    }
    const plan = map.sections_plan
    if (show.sections && plan?.sections?.length && tab !== 'sections') {
      for (const s of plan.sections) { const r = s.rect; grp.add(polyLine([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]], grid.current, '#ffffff', 1.5, { dashed: true, opacity: 0.6 })) }
    }
    layer.set('debug', grp)
    return () => layer.drop('debug')
  }, [layer, map, pv, show.spawns, show.triggers, show.routes, show.sections, tab, c.rev])
}
void polyOf

export default function ShowTool({ c }) {
  const { show, setShow, pv } = c
  const on = k => v => setShow({ ...show, [k]: v })
  return <div className="mb-body">
    <Head>{tr('show')}</Head>
    <Check label={tr('collision')} on={show.collision} onChange={on('collision')} tip={tr('solid_shapes_of_what_this_map')} />
    <Check label={tr('routes')} on={show.routes} onChange={on('routes')} tip={tr('the_seed_traffic_routes_of_the')} />
    <Check label={tr('triggers')} on={show.triggers} onChange={on('triggers')} tip={tr('fall_planes_water_triggers_and_invisible')} />
    <Check label={tr('sections')} on={show.sections} onChange={on('sections')} tip={tr('where_the_sections_you_planned_begin')} />
    <Check label={tr('spawns')} on={show.spawns} onChange={on('spawns')} tip={tr('arrival_return_and_named_arrival_spots')} />
    <Check label={tr('limits')} on={show.limits} onChange={on('limits')} tip={tr('the_limit_meters_over_the_view')} />
    <p className="small muted mb-hint">{`${(pv?.triggers || []).length} triggers · ${(pv?.walls || []).length} walls · ${(pv?.traffic || []).length} routes`}</p>
  </div>
}
