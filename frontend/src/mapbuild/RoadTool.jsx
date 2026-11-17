// Roads: a spline tool (click to add points, drag the handles, click the line to add one in between), width, lanes, kerbs, bridges and
// ramps through the `elevated` flag, and slope warnings drawn on the road itself (a shape as well as a colour).
import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { usePointer } from './hooks.js'
import { roadProfile, spline, nearestOnLine, heightAt, r2, newId, slopeClass, SLOPE_CAR, SLOPE_WALK } from './geo.js'
import { marker, lineOf, toV, textSprite, C } from './layer.js'
import { Sld, Check, Head, List } from './common.jsx'
import { NumField } from '../ui.jsx'
import { t as tr } from '../i18n.js'

const COLORS = { ok: '#5fd38d', hard: '#f2c14e', steep: '#ff7070' }
const fresh = roads => ({ id: newId(roads, 'road'), points: [], width: 8, lanes: 2, kerb: true, grade: true, shoulder: 6, elevated: false, traffic: true })
const pct = v => Math.round(v * 100)

export default function RoadTool({ c }) {
  const { map, put, api, layer, grid, pv } = c
  const roads = map.roads || []
  const [sel, setSel] = useState(0), [pt, setPt] = useState(-1)
  const [adding, setAdding] = useState(true)
  const [draft, setDraft] = useState(null)
  const shown = draft || roads
  const R = useRef(roads); R.current = roads
  const D = useRef(draft); D.current = draft
  const Sx = useRef({ sel, pt, adding }); Sx.current = { sel, pt, adding }
  const gesture = useRef(null)
  const road = shown[sel]

  // ---- drawing: the line coloured by slope, markers where it is too steep, handles
  const profiles = useMemo(() => shown.map(r => roadProfile(r, grid.current)), [shown, c.rev])
  useEffect(() => {
    if (!layer) return
    const g = new THREE.Group(); g.userData = { overlay: true }
    shown.forEach((r, ri) => {
      const prof = profiles[ri] || []
      if (prof.length < 2) return
      const dim = ri !== sel ? 0.55 : 1
      for (const cls of ['ok', 'hard', 'steep']) {
        const pts = []
        for (let i = 0; i < prof.length - 1; i++) if (slopeClass(Math.max(prof[i].slope, prof[i + 1].slope)) === cls) pts.push(toV(prof[i].pos[0], prof[i].pos[1] + 0.5, prof[i].pos[2]), toV(prof[i + 1].pos[0], prof[i + 1].pos[1] + 0.5, prof[i + 1].pos[2]))
        if (!pts.length) continue
        const l = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: C(COLORS[cls]), depthTest: false, transparent: true, opacity: dim }))
        l.renderOrder = 15; l.userData = { overlay: true }; g.add(l)
      }
      let lastMark = -99
      prof.forEach((p, i) => {
        const cls = slopeClass(p.slope)
        if (cls === 'ok' || i - lastMark < 6) return
        lastMark = i
        g.add(marker([p.pos[0], p.pos[1] + 2, p.pos[2]], cls === 'steep' ? 'cross' : 'tri', COLORS[cls], 0.024))
      })
      if (ri === sel) (r.points || []).forEach((p, i) => {
        const y = r.elevated && p[2] != null ? p[2] : heightAt(grid.current || { nx: 1, nz: 1, ox: 0, oz: 0, cell: 1, h: new Float32Array(4) }, p[0], p[1])
        g.add(marker([p[0], y + 1, p[1]], i === pt ? 'diamond' : 'dot', i === pt ? '#f2a541' : '#ffffff', i === pt ? 0.034 : 0.026))
        if (p[2] != null) { g.add(lineOf([[p[0], y, p[1]], [p[0], (grid.current ? heightAt(grid.current, p[0], p[1]) : 0), p[1]]], '#f2a541', { dashed: true, opacity: 0.8 })) }
      })
      if (ri === sel && prof.length) { const m = prof[Math.floor(prof.length / 2)].pos; const t = textSprite(r.id, '#ffffff', 0.032); t.position.copy(toV(m[0], m[1] + 4, m[2])); g.add(t) }
    })
    layer.set('roads', g)
    return () => layer.drop('roads')
  }, [layer, shown, profiles, sel, pt])
  useEffect(() => () => layer?.drop('hint'), [layer])

  const stats = useMemo(() => {
    const prof = profiles[sel] || []
    let worst = 0, len = 0
    prof.forEach((p, i) => { worst = Math.max(worst, p.slope); if (i) len += Math.hypot(p.pos[0] - prof[i - 1].pos[0], p.pos[2] - prof[i - 1].pos[2]) })
    return { worst, len }
  }, [profiles, sel])

  const setRoads = (next, keepSel) => { put({ roads: next }); if (!keepSel) { /* selection stays */ } }
  const edit = patch => setRoads(roads.map((r, i) => (i === sel ? { ...r, ...patch } : r)))
  const setPoints = pts => edit({ points: pts })
  const px = p => api.project(p)

  // ---- the mouse: handle drag, insert on the line, append at the end
  const append = (list, x, z) => {
    let rs = list.slice(), si = Sx.current.sel
    if (!rs[si]) { rs = [...rs, fresh(rs)]; si = rs.length - 1 }
    rs[si] = { ...rs[si], points: [...(rs[si].points || []), [r2(x), r2(z)]] }
    return { rs, si, pi: rs[si].points.length - 1 }
  }
  usePointer(api, {
    active: true,
    onDown: (h, ev) => {
      const L = D.current || R.current, r = L[Sx.current.sel]
      const rect = api.gl.domElement.getBoundingClientRect()
      const m = { x: ev.clientX - rect.left, y: ev.clientY - rect.top }
      if (r) {
        for (let i = 0; i < (r.points || []).length; i++) {
          const q = r.points[i]
          const s = px([q[0], (r.elevated && q[2] != null ? q[2] : grid.current ? heightAt(grid.current, q[0], q[1]) : 0) + 1, q[1]])
          if (s && Math.hypot(s.x - m.x, s.y - m.y) < 14) { gesture.current = { drag: i, moved: false }; setPt(i); return true }
        }
        const prof = profiles[Sx.current.sel] || []
        if (prof.length > 1 && r.points.length > 1) {
          const sp = spline(r.points, 2)
          const near = nearestOnLine(prof.map(q => q.pos), m, v => px(v))
          if (near.d < 9) {
            const s = sp.s[Math.min(sp.s.length - 1, near.i)]
            let k = 0
            while (k < sp.at.length - 2 && sp.at[k + 1] <= s) k++
            const pts = r.points.slice()
            pts.splice(k + 1, 0, [r2(h.pos[0]), r2(h.pos[2])])
            const next = L.map((q, i) => (i === Sx.current.sel ? { ...q, points: pts } : q))
            setDraft(next); setPt(k + 1); gesture.current = { drag: k + 1, moved: true, inserted: true }
            return true
          }
        }
      }
      if (!Sx.current.adding && r) return false
      const a = append(L, h.pos[0], h.pos[2])
      setDraft(a.rs); setSel(a.si); setPt(a.pi); gesture.current = { drag: a.pi, moved: true }
      return true
    },
    onMove: h => {
      const g = gesture.current
      if (!g) return
      g.moved = true
      const L = D.current || R.current
      setDraft(L.map((r, i) => (i === Sx.current.sel ? { ...r, points: r.points.map((q, k) => (k === g.drag ? (q[2] != null ? [r2(h.pos[0]), r2(h.pos[2]), q[2]] : [r2(h.pos[0]), r2(h.pos[2])]) : q)) } : r)))
    },
    onUp: () => {
      const g = gesture.current; gesture.current = null
      const d = D.current
      if (g && g.moved && d) setRoads(d)
      setDraft(null)
    },
    onKey: e => {
      const r = R.current[Sx.current.sel]
      if (e.key === 'Enter' && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) { const p = api.centerPoint(); const a = append(R.current, p[0], p[2]); setRoads(a.rs); setSel(a.si); setPt(a.pi) }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && r) {
        const k = Sx.current.pt >= 0 ? Sx.current.pt : r.points.length - 1
        if (k >= 0) { setPoints(r.points.filter((_, i) => i !== k)); setPt(-1) }
      } else if (e.key === 'Escape') setPt(-1)
    },
    onPad: (name, h) => { if (name === 'A') { const a = append(R.current, h.pos[0], h.pos[2]); setRoads(a.rs); setSel(a.si); setPt(a.pi) } },
  })

  const addRoad = () => { setRoads([...roads, fresh(roads)]); setSel(roads.length); setPt(-1); setAdding(true) }
  const delRoad = i => { setRoads(roads.filter((_, k) => k !== i)); setSel(Math.max(0, Math.min(sel, roads.length - 2))); setPt(-1) }
  const bridge = () => {
    if (!road || road.points.length < 2) return
    const n = road.points.length
    const ground = p => (grid.current ? heightAt(grid.current, p[0], p[1]) : 0)
    const top = Math.max(...road.points.map(ground)) + 6
    edit({ elevated: true, points: road.points.map((p, i) => (i === 0 || i === n - 1 ? [p[0], p[1]] : [p[0], p[1], r2(top)])) })
  }
  const traffic = (pv?.traffic || []).find(t => (t.road || t.id || '').toString().toLowerCase().includes(String(road?.id || '').toLowerCase()))
  const p0 = road && pt >= 0 ? road.points[pt] : null
  return <div className="mb-body">
    <Head>{tr('roads')}</Head>
    <List items={roads} sel={sel} onSel={i => { setSel(i); setPt(-1) }} onDelete={delRoad} name={r => r.id} extra={r => (r.elevated ? 'bridge' : `${r.points.length} pts`)} />
    <div className="mb-btns"><button onClick={addRoad}>{tr('new_road')}</button><button className={adding ? 'on' : ''} aria-pressed={adding} onClick={() => setAdding(!adding)} title={tr('click_the_ground_to_add_a')}>{tr('add_points')}</button></div>
    {road && <>
      <Sld label={tr('width')} value={road.width ?? 8} min={1.5} max={40} step={0.5} unit="m" onChange={v => edit({ width: v })} />
      <Sld label={tr('lanes')} value={road.lanes ?? 2} min={1} max={4} step={1} digits={0} onChange={v => edit({ lanes: v })} />
      <div className="mb-checks">
        <Check label={tr('kerbs')} on={road.kerb !== false} onChange={v => edit({ kerb: v })} />
        <Check label={tr('level_the_ground')} on={road.grade !== false} disabled={road.elevated} onChange={v => edit({ grade: v })} tip={tr('flatten_the_terrain_under_the_road')} />
        <Check label={tr('traffic')} on={road.traffic !== false} onChange={v => edit({ traffic: v })} tip={tr('a_seed_traffic_route_follows_the')} />
        <Check label={tr('bridge_or_ramp')} on={!!road.elevated} onChange={v => edit({ elevated: v })} tip={tr('the_deck_follows_the_heights_you')} />
      </div>
      {road.elevated && <div className="mb-btns"><button onClick={bridge} title={tr('pin_the_middle_points_high_keep')}>{tr('lift_the_middle')}</button></div>}
      <div className={'mb-stat ' + slopeClass(stats.worst)} title={tr('car_slope_note', { a: pct(SLOPE_CAR), b: pct(SLOPE_WALK) })}>
        {slopeClass(stats.worst) === 'steep' ? '✖' : slopeClass(stats.worst) === 'hard' ? '▲' : '✓'} {tr('steepest_n', { n: pct(stats.worst) })}{` · ${Math.round(stats.len)} m`}
        {traffic ? ' · ' + tr('n_traffic_points', { n: traffic.points?.length || 0 }) : ''}
      </div>
      <Head>{tr('points_4b2a6a')}</Head>
      <div className="mb-pts">{(road.points || []).map((p, i) => <div key={i} className={'mb-pt' + (i === pt ? ' on' : '')} onClick={() => setPt(i)} role="button" tabIndex={0} onKeyDown={e => e.key === 'Enter' && setPt(i)}>
        <span className="n">{i + 1}</span>
        <NumField value={p[0]} digits={1} label={tr('point_n_x', { n: i + 1 })} onCommit={v => setPoints(road.points.map((q, k) => (k === i ? [v, ...q.slice(1)] : q)))} />
        <NumField value={p[1]} digits={1} label={tr('point_n_z', { n: i + 1 })} onCommit={v => setPoints(road.points.map((q, k) => (k === i ? [q[0], v, ...q.slice(2)] : q)))} />
        <NumField value={p[2]} digits={1} nullable placeholder={tr('free_4ff88a')} label={tr('point_n_height', { n: i + 1 })} title={tr('pin_the_road_to_this_height')}
          onCommit={v => setPoints(road.points.map((q, k) => (k === i ? (v == null ? [q[0], q[1]] : [q[0], q[1], v]) : q)))} />
        <button className="link" aria-label={tr('remove_point_n', { n: i + 1 })} onClick={e => { e.stopPropagation(); setPoints(road.points.filter((_, k) => k !== i)); setPt(-1) }}>×</button>
      </div>)}</div>
      {p0 && <p className="small muted mb-hint">{`Point ${pt + 1}`}</p>}
    </>}
    {!road && <p className="small muted">{tr('add_a_road_then_click_the')}</p>}
  </div>
}
