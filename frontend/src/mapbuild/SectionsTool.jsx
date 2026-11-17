// Section planner: split the map into sections seen from above, place the loaders between them, and walk or drive a path to see which
// section is loaded where. Every reachable spot whose ground is not loaded is flagged. The load time is a rough guess.
import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { post } from '../api.js'
import { usePointer, useDebounced } from './hooks.js'
import { heightAt, r2, rectOf, newId } from './geo.js'
import { polyLine, lineOf, marker, textSprite, toV } from './layer.js'
import { Chips, Head, List } from './common.jsx'
import { t as tr } from '../i18n.js'

const mem = { mode: 'section' }
const COLORS = ['#7cc4ff', '#ffd166', '#9be28a', '#ff9fb2', '#c7a6ff', '#ffb870', '#7be0d0', '#e0e07b', '#b0b8c4']
const EMPTY = { sections: [], loaders: [], path: [] }

export default function SectionsTool({ c }) {
  const { map, put, api, layer, grid } = c
  const plan = map.sections_plan || EMPTY
  const [s, setS] = useState(mem)
  Object.assign(mem, s)
  const [sel, setSel] = useState(plan.sections.length ? 0 : -1)
  const [sim, setSim] = useState(null)
  const [draft, setDraft] = useState(null)
  const P = useRef(plan); P.current = plan
  const S = useRef(s); S.current = s
  const dr = useRef(draft); dr.current = draft
  const g = useRef(null)
  const gh = (x, z) => (grid.current ? heightAt(grid.current, x, z) : 0)
  const setPlan = patch => put({ sections_plan: { ...P.current, ...patch } })

  // the numbers per section and the walk: asked of the server, debounced
  const sig = useDebounced(JSON.stringify([plan, c.key]), 500)
  useEffect(() => {
    let live = true
    const body = { name: map.name, ...Object.fromEntries(['terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'blockout'].map(k => [k, map[k]]).filter(([, v]) => v != null)) }
    if (!plan.sections.length) { setSim(null); return undefined }
    post('/api/mapbuild/plan', { map: body, plan: plan.sections, loaders: plan.loaders, path: plan.path }).then(r => { if (live) setSim(r) }).catch(() => { if (live) setSim(null) })
    return () => { live = false }
  }, [sig])

  useEffect(() => {
    if (!layer) return
    const grp = new THREE.Group(); grp.userData = { overlay: true }
    const secs = draft?.sections || plan.sections
    secs.forEach((sc, i) => {
      const col = COLORS[i % COLORS.length], r = sc.rect
      grp.add(polyLine([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]], grid.current, col, 1.2, { opacity: i === sel ? 1 : 0.7 }))
      const t = textSprite(sc.name || sc.id, col, 0.034); t.position.copy(toV((r[0] + r[2]) / 2, gh((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) + 6, (r[1] + r[3]) / 2)); grp.add(t)
    })
    plan.loaders.forEach(l => {
      const [w, h, ln] = l.size || [12, 6, 2]
      const cx = l.pos[0], cz = l.pos[2]
      grp.add(polyLine([[cx - w / 2, cz - ln / 2], [cx + w / 2, cz - ln / 2], [cx + w / 2, cz + ln / 2], [cx - w / 2, cz + ln / 2]], grid.current, '#ffffff', 1.4, { dashed: true }))
      grp.add(marker([cx, l.pos[1] + 2, cz], 'diamond', '#ffffff', 0.026))
      void h
    })
    const pth = draft?.path || plan.path
    if (pth.length > 1) grp.add(lineOf(pth.map(p => [p[0], gh(p[0], p[1]) + 1.5, p[1]]), '#f2a541'))
    pth.forEach(p => grp.add(marker([p[0], gh(p[0], p[1]) + 1.5, p[1]], 'dot', '#f2a541', 0.022)))
    ;(sim?.flags || []).forEach(f => grp.add(marker([f.pos[0], gh(f.pos[0], f.pos[1]) + 3, f.pos[1]], 'cross', '#ff7070', 0.03)))
    ;(sim?.gaps || []).forEach(q => grp.add(marker([q[0], gh(q[0], q[1]) + 2, q[1]], 'tri', '#f2c14e', 0.02)))
    layer.set('sections', grp)
    return () => layer.drop('sections')
  }, [layer, plan, draft, sel, sim])

  const nearestTwo = (x, z) => {
    const d = sc => { const r = sc.rect; const dx = Math.max(r[0] - x, 0, x - r[2]), dz = Math.max(r[1] - z, 0, z - r[3]); return Math.hypot(dx, dz) }
    return [...P.current.sections].sort((a, b) => d(a) - d(b)).slice(0, 2).map(q => q.id)
  }
  usePointer(api, {
    active: true,
    onDown: h => {
      const p = [h.pos[0], h.pos[2]], m = S.current.mode
      if (m === 'section') { g.current = { from: p }; return true }
      if (m === 'loader' || m === 'path') { g.current = { click: p, y: h.pos[1] }; return true }
      return false
    },
    onMove: h => { const gg = g.current; if (gg) setDraft({ ...P.current, sections: [...P.current.sections, { id: '_', name: '', rect: rectOf(gg.from, [h.pos[0], h.pos[2]]) }] }) },
    onUp: () => {
      const gg = g.current; g.current = null
      const d = dr.current; setDraft(null)
      if (gg?.click) {
        const p = gg.click
        if (S.current.mode === 'loader') { const [a, b] = nearestTwo(p[0], p[1]); setPlan({ loaders: [...P.current.loaders, { id: newId(P.current.loaders, 'loader'), a, b, pos: [r2(p[0]), r2(gg.y), r2(p[1])], size: [12, 6, 2] }] }) } else setPlan({ path: [...P.current.path, [r2(p[0]), r2(p[1])]] })
        return
      }
      if (!gg || !d) return
      const r = d.sections[d.sections.length - 1].rect
      if (r[2] - r[0] < 4 || r[3] - r[1] < 4) return
      const id = newId(P.current.sections, 'sec')
      setPlan({ sections: [...P.current.sections, { id, name: 'Section ' + (P.current.sections.length + 1), rect: r }] }); setSel(P.current.sections.length)
    },
    onKey: e => {
      if (e.key === 'Backspace' && S.current.mode === 'path') setPlan({ path: P.current.path.slice(0, -1) })
      else if (e.key === 'Enter' && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint && S.current.mode === 'path') { const p = api.centerPoint(); setPlan({ path: [...P.current.path, [r2(p[0]), r2(p[2])]] }) }
    },
    onPad: (name, h) => { if (name === 'A') setPlan({ path: [...P.current.path, [r2(h.pos[0]), r2(h.pos[2])]] }) },
  })

  const split = (nx, nz) => {
    const gr = grid.current
    if (!gr) return
    const x0 = gr.ox, z0 = gr.oz, x1 = gr.ox + gr.nx * gr.cell, z1 = gr.oz + gr.nz * gr.cell
    const secs = [], loaders = []
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) secs.push({ id: 'sec' + (secs.length + 1), name: 'Section ' + (secs.length + 1), rect: [r2(x0 + (x1 - x0) * i / nx), r2(z0 + (z1 - z0) * j / nz), r2(x0 + (x1 - x0) * (i + 1) / nx), r2(z0 + (z1 - z0) * (j + 1) / nz)] })
    const at = (i, j) => secs[j * nx + i].id
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
      if (i + 1 < nx) { const x = x0 + (x1 - x0) * (i + 1) / nx, z = z0 + (z1 - z0) * (j + 0.5) / nz; loaders.push({ id: 'loader' + (loaders.length + 1), a: at(i, j), b: at(i + 1, j), pos: [r2(x), r2(gh(x, z)), r2(z)], size: [4, 6, 12] }) }
      if (j + 1 < nz) { const x = x0 + (x1 - x0) * (i + 0.5) / nx, z = z0 + (z1 - z0) * (j + 1) / nz; loaders.push({ id: 'loader' + (loaders.length + 1), a: at(i, j), b: at(i, j + 1), pos: [r2(x), r2(gh(x, z)), r2(z)], size: [12, 6, 4] }) }
    }
    setPlan({ sections: secs, loaders }); setSel(0)
  }
  const stat = id => sim?.stats?.[id]
  return <div className="mb-body">
    <Chips label={tr('place_c32a01')} value={s.mode} onChange={v => setS({ mode: v })} options={[{ value: 'section', label: tr('section'), tip: tr('drag_a_box_over_the_part') }, { value: 'loader', label: tr('loader'), tip: tr('click_where_one_section_hands_over') }, { value: 'path', label: tr('walk'), tip: tr('click_the_points_of_a_path') }]} />
    <div className="mb-btns"><span className="k small">{tr('split')}</span>{[[2, 1], [2, 2], [3, 3]].map(([a, b]) => <button key={a + 'x' + b} className="sm" disabled={!grid.current} onClick={() => split(a, b)}>{a + ' × ' + b}</button>)}</div>
    <Head>{tr('sections')}</Head>
    <List items={plan.sections} sel={sel} onSel={setSel} onDelete={i => { const id = plan.sections[i].id; setPlan({ sections: plan.sections.filter((_, k) => k !== i), loaders: plan.loaders.filter(l => l.a !== id && l.b !== id) }); setSel(-1) }} name={x => x.name || x.id}
      extra={x => (stat(x.id) ? `${stat(x.id).seconds} s` : '')} />
    {plan.sections[sel] && <>
      <label className="mb-row two"><span className="k">{tr('name')}</span><input aria-label={tr('section_name')} value={plan.sections[sel].name || ''} onChange={e => setPlan({ sections: plan.sections.map((q, i) => (i === sel ? { ...q, name: e.target.value } : q)) })} /></label>
      {stat(plan.sections[sel].id) && (st => <div className="mb-sec" title={tr('what_this_section_holds')}>
        <div>{'△ ' + st.triangles.toLocaleString('en-US')}<span className="u">{' '}{tr('triangles_304a1e')}</span></div><div>{'▣ ' + st.textures}<span className="u">{' '}{tr('pictures_0a3c15')}</span></div>
        <div>{'● ' + st.instances}<span className="u">{' '}{tr('things')}</span></div>
        <div className={'mb-bar' + (st.main > 8500 ? ' bad' : st.main > 7000 ? ' warn' : '')} title={tr('main_quadtree_about', { n: st.main })}><i style={{ width: Math.min(100, st.main / 100) + '%' }} /><span>{(st.main > 8500 ? '✖ ' : st.main > 7000 ? '▲ ' : '✓ ') + 'Main ' + st.main}</span></div>
        <div>{tr('about_n_seconds_to_load', { n: st.seconds })}<span className="u" title={tr('a_rough_guess')}>{' '}{tr('rough')}</span></div></div>)(stat(plan.sections[sel].id))}
    </>}
    <Head>{tr('loaders')}</Head>
    <List items={plan.loaders} sel={-1} onSel={() => {}} onDelete={i => setPlan({ loaders: plan.loaders.filter((_, k) => k !== i) })} name={x => x.id} extra={x => `${x.a} ↔ ${x.b}`} />
    <Head>{tr('walk')}</Head>
    <div className="mb-btns"><button className="sm" disabled={!plan.path.length} onClick={() => setPlan({ path: [] })}>{tr('clear_path')}</button><span className="small muted">{tr('n_points', { n: plan.path.length })}</span></div>
    {sim && plan.path.length > 1 && <div className={'mb-stat ' + (sim.flags.length ? 'steep' : 'ok')} role="status" title={tr('spots_on_the_path_where_the')}>
      {sim.flags.length ? '✖ ' + tr('n_spots_not_loaded', { n: sim.flags.length }) : '✓ ' + tr('every_spot_on_the_path_is_loaded')}{sim.total_seconds ? ` · ≈ ${sim.total_seconds} s` : ''}</div>}
    {sim?.gaps?.length > 0 && <div className="mb-stat hard" role="status" title={tr('reachable_ground_that_no_section_covers')}>{'▲ ' + tr('n_reachable_spots_in_no_section', { n: sim.gaps.length })}</div>}
  </div>
}
