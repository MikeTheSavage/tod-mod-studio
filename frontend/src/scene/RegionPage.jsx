// Region: the whole scene from above; draw a rectangle or a polygon, or stamp a square. Live counts follow the shape.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api.js'
import { Seg, NumField } from '../ui.jsx'
import { t as tr } from '../i18n.js'

const toXY = ([x, z]) => [x, -z]

// The top view. World metres at the chosen scale; north (+z) is up. spot: a point in file units (drawn as a ring).
export function TopView({ S, spot, onSpot, readOnly, tool, stampM, onShape, children }) {
  const { ov, params } = S
  const svg = useRef(null)
  const s = params.scale
  const full = useMemo(() => ov ? { x0: ov.min[0] * s, x1: ov.max[0] * s, z0: ov.min[1] * s, z1: ov.max[1] * s } : null, [ov, s])
  const [view, setView] = useState(null)               // { x, z, w } the centre and width in metres
  const [drag, setDrag] = useState(null)
  const [hover, setHover] = useState(null)
  const [, force] = useState(0)
  useEffect(() => { if (full) setView({ x: (full.x0 + full.x1) / 2, z: (full.z0 + full.z1) / 2, w: Math.max(full.x1 - full.x0, full.z1 - full.z0) * 1.04 }) }, [ov?.png, s])
  useEffect(() => { force(n => n + 1) }, [])
  if (!ov || !view || !full) return <div className="empty">{S.busy || tr('open_a_scene_first')}</div>
  const world = e => {
    const el = svg.current
    const pt = el.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY
    const p = pt.matrixTransform(el.getScreenCTM().inverse())
    return [p.x, -p.y]
  }
  const rect = svg.current?.getBoundingClientRect()
  const ratio = rect && rect.width > 0 ? rect.height / rect.width : 1
  const vb = [view.x - view.w / 2, -(view.z + view.w * ratio / 2), view.w, view.w * ratio]
  const wheel = e => {
    e.preventDefault()
    const [wx, wz] = world(e)
    const k = e.deltaY > 0 ? 1.18 : 1 / 1.18
    const w = Math.min(Math.max(view.w * k, 20), Math.max(full.x1 - full.x0, full.z1 - full.z0) * 1.6)
    const f = w / view.w
    setView({ x: wx + (view.x - wx) * f, z: wz + (view.z - wz) * f, w })
  }
  const down = e => {
    const p = world(e)
    if (e.button === 1 || e.shiftKey) { setDrag({ pan: true, last: [e.clientX, e.clientY] }); e.currentTarget.setPointerCapture(e.pointerId); return }
    if (e.button !== 0) return
    if (readOnly) { onSpot?.([p[0] / s, p[1] / s]); return }
    if (tool === 'stamp') { const h = stampM / 2; onShape?.([[p[0] - h, p[1] - h], [p[0] + h, p[1] - h], [p[0] + h, p[1] + h], [p[0] - h, p[1] + h]]); return }
    if (tool === 'rect') { setDrag({ rect: true, a: p, b: p }); e.currentTarget.setPointerCapture(e.pointerId); return }
    if (tool === 'poly') { setDrag(d => ({ poly: [...(d?.poly || []), p] })) }
  }
  const move = e => {
    if (drag?.pan) {
      const k = view.w / rect.width
      setView(v => ({ ...v, x: v.x - (e.clientX - drag.last[0]) * k, z: v.z + (e.clientY - drag.last[1]) * k }))
      setDrag({ pan: true, last: [e.clientX, e.clientY] })
    } else if (drag?.rect) setDrag({ ...drag, b: world(e) })
    setHover(world(e))
  }
  const up = () => {
    if (drag?.rect) {
      const [a, b] = [drag.a, drag.b]
      if (Math.abs(a[0] - b[0]) > 2 && Math.abs(a[1] - b[1]) > 2) onShape?.([[Math.min(a[0], b[0]), Math.min(a[1], b[1])], [Math.max(a[0], b[0]), Math.min(a[1], b[1])], [Math.max(a[0], b[0]), Math.max(a[1], b[1])], [Math.min(a[0], b[0]), Math.max(a[1], b[1])]])
    }
    if (drag?.pan || drag?.rect) setDrag(null)
  }
  const closePoly = () => { if (drag?.poly?.length >= 3) onShape?.(drag.poly); setDrag(null) }
  const poly = params.region.polygon
  const path = pts => pts.map(p => toXY(p).join(',')).join(' ')
  const live = drag?.rect ? [drag.a, [drag.b[0], drag.a[1]], drag.b, [drag.a[0], drag.b[1]]] : null
  const px = vb[2] / (rect?.width || 600)
  return (
    <div className="topview" style={{ height: readOnly ? 300 : '100%' }}>
      <svg ref={svg} viewBox={vb.join(' ')} preserveAspectRatio="xMidYMid meet" tabIndex={0} aria-label={tr('top_view')}
        onWheel={wheel} onPointerDown={down} onPointerMove={move} onPointerUp={up} onDoubleClick={closePoly}
        onKeyDown={e => { if (e.key === 'Enter') closePoly(); if (e.key === 'Escape') setDrag(null) }}
        style={{ cursor: 'crosshair' }}>
        <rect x={vb[0]} y={vb[1]} width={vb[2]} height={vb[3]} className="tv-bg" />
        <image href={ov.png} x={full.x0} y={-full.z1} width={full.x1 - full.x0} height={full.z1 - full.z0} preserveAspectRatio="none" />
        <Grid vb={vb} />
        {poly && <polygon points={path(poly)} className="tv-region" strokeWidth={px * 2} />}
        {live && <polygon points={path(live)} className="tv-region live" strokeWidth={px * 2} />}
        {drag?.poly && <polyline points={path(drag.poly.concat(hover ? [hover] : []))} className="tv-region live" fill="none" strokeWidth={px * 2} />}
        {drag?.poly?.map((p, i) => <circle key={i} cx={p[0]} cy={-p[1]} r={px * 4} className="tv-dot" />)}
        {spot && <circle cx={spot[0] * s} cy={-spot[1] * s} r={px * 8} className="tv-spot" strokeWidth={px * 2} />}
        {children}
      </svg>
      {hover && <div className="tv-xy">{hover[0].toFixed(0)}, {hover[1].toFixed(0)}{' '}{tr('m')}</div>}
    </div>
  )
}

function Grid({ vb }) {
  const span = vb[2]
  const step = [10, 20, 50, 100, 200, 500, 1000].find(v => span / v < 12) || 1000
  const out = []
  for (let x = Math.ceil(vb[0] / step) * step; x < vb[0] + vb[2]; x += step) out.push(<line key={'x' + x} x1={x} x2={x} y1={vb[1]} y2={vb[1] + vb[3]} className="tv-grid" strokeWidth={span / 1200} />)
  for (let y = Math.ceil(vb[1] / step) * step; y < vb[1] + vb[3]; y += step) out.push(<line key={'y' + y} y1={y} y2={y} x1={vb[0]} x2={vb[0] + vb[2]} className="tv-grid" strokeWidth={span / 1200} />)
  return <g>{out}</g>
}

export const bounds = poly => poly ? [Math.min(...poly.map(p => p[0])), Math.min(...poly.map(p => p[1])), Math.max(...poly.map(p => p[0])), Math.max(...poly.map(p => p[1]))] : null

export default function RegionPage({ S }) {
  const { params, edit, sc } = S
  const [tool, setTool] = useState('rect')
  const [stampM, setStampM] = useState(300)
  const [n, setN] = useState(null)
  const poly = params.region.polygon
  const seq = useRef(0)
  useEffect(() => {
    if (!sc || !poly) { setN(null); return }
    const my = ++seq.current
    const t = setTimeout(async () => {
      try { const r = await post('/api/scene/count', { sid: sc.sid, params }); if (my === seq.current) setN(r) } catch (e) { if (my === seq.current) setN(null) }
    }, 220)
    return () => clearTimeout(t)
  }, [sc?.sid, JSON.stringify(poly), params.region.mode, params.scale, params.up, params.mirror, params.yaw])
  const b = bounds(poly)
  useEffect(() => {
    const nudge = (dx, dz) => edit(p => ({ ...p, region: { ...p.region, polygon: p.region.polygon.map(([x, z]) => [x + dx, z + dz]) } }))
    const f = e => {
      if (e.target?.tagName === 'INPUT' || !poly) return
      const k = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[e.key]
      if (k) { e.preventDefault(); nudge(k[0] * (e.shiftKey ? 1 : 10), k[1] * (e.shiftKey ? 1 : 10)) }
      if (e.key === 'Delete') edit(p => ({ ...p, region: { ...p.region, polygon: null } }))
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [poly, edit])
  return (
    <div className="split">
      <div className="panel-l" style={{ width: 'calc(var(--side-l) + 20px)' }}>
        <div className="panel-b">
          <h4 style={{ marginTop: 0 }}>{tr('shape')}</h4>
          <Seg value={tool} onChange={setTool} options={[{ value: 'rect', label: tr('rectangle') }, { value: 'poly', label: tr('polygon') }, { value: 'stamp', label: tr('square') }]} />
          {tool === 'stamp' && <div className="row"><NumField value={stampM} digits={0} unit="m" onCommit={v => v > 5 && setStampM(v)} label={tr('side')} /></div>}
          <div className="row" title={tr('clip_cuts_at_the_border')}>
            <Seg value={params.region.mode} onChange={m => edit(p => ({ ...p, region: { ...p.region, mode: m } }))} options={[{ value: 'clip', label: tr('clip') }, { value: 'whole', label: tr('whole_parts') }]} />
          </div>
          {b && <div className="muted small tab">{(b[2] - b[0]).toFixed(0)} × {(b[3] - b[1]).toFixed(0)}{' '}{tr('m')}</div>}
          <div className="row"><button className="sm" disabled={!poly} onClick={() => edit(p => ({ ...p, region: { ...p.region, polygon: null } }))}>{tr('clear')}</button></div>
          <h4>{tr('inside')}</h4>
          <div className="scene-facts one">
            <Count k={tr('triangles')} v={n?.triangles} /><Count k={tr('parts')} v={n?.primitives} /><Count k={tr('materials')} v={n?.materials} /><Count k={tr('pictures')} v={n?.textures} />
          </div>
          <div className="row" style={{ marginTop: 8 }}><button className="primary" disabled={!poly || !n?.triangles} onClick={() => S.setPage('clean')}>{tr('next')}</button></div>
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, position: 'relative', background: 'var(--vp)' }}>
        <TopView S={S} tool={tool} stampM={stampM} onShape={p => edit(q => ({ ...q, region: { ...q.region, polygon: p.map(v => v.map(c => Math.round(c * 10) / 10)) } }))} />
      </div>
    </div>
  )
}

const Count = ({ k, v }) => <div className="fact"><div className="v">{v == null ? '–' : v.toLocaleString()}</div><div className="k">{k}</div></div>
