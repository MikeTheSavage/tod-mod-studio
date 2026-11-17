// Scale: pick a spot on the top view, then two points on something of a known size (a door, a car, a lane). The Ram figure stands in the view.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api.js'
import { NumField } from '../ui.jsx'
import { t as tr } from '../i18n.js'
import SceneCanvas from './SceneCanvas.jsx'
import { TopView } from './RegionPage.jsx'

const known = () => [[tr('door'), 2.1], [tr('lane'), 3.5], [tr('car'), 4.5]]

export default function ScalePage({ S }) {
  const { params, edit, sc, ov } = S
  const [spot, setSpot] = useState(null)               // game x, z at scale 1
  const [radius, setRadius] = useState(40)
  const [glb, setGlb] = useState(null)
  const [pts, setPts] = useState([])
  const [measure, setMeasure] = useState(false)
  const [real, setReal] = useState(2.1)
  const seq = useRef(0)

  useEffect(() => {
    if (!sc || !spot) return
    const my = ++seq.current
    const t = setTimeout(async () => {
      try {
        const r = await post('/api/scene/sample', { sid: sc.sid, params: { up: params.up, mirror: params.mirror, yaw: params.yaw }, center: spot, radius })
        if (my === seq.current) { setGlb(r); setPts([]) }
      } catch (e) { S.setErr(e.message) }
    }, 200)
    return () => clearTimeout(t)
  }, [sc?.sid, spot?.[0], spot?.[1], radius, params.up, params.mirror, params.yaw])
  // the first sample: the middle of the scene (links for screenshots: scene_spot=x,z  scene_radius=r  scene_pts=x,y,z,x,y,z)
  useEffect(() => {
    if (!ov || spot) return
    const u = new URLSearchParams(location.search)
    if (u.get('scene_radius')) setRadius(Number(u.get('scene_radius')))
    if (u.get('scene_spot')) setSpot(u.get('scene_spot').split(',').map(Number))
    else setSpot([(ov.min[0] + ov.max[0]) / 2, (ov.min[1] + ov.max[1]) / 2])
  }, [ov])
  useEffect(() => {
    const q = new URLSearchParams(location.search).get('scene_pts')
    if (glb && q) { const v = q.split(',').map(Number); setMeasure(true); setPts([v.slice(0, 3), v.slice(3, 6)]) }
  }, [glb?.url])

  const dist = pts.length === 2 ? Math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2]) : null
  const apply = () => { if (dist > 1e-6) edit({ scale: Math.round(real / dist * 1e6) / 1e6 }) }
  const label = dist != null ? (dist * params.scale).toFixed(2) + ' m' : ''
  const pick = measure ? { points: pts, label, onPoint: p => setPts(a => a.length >= 2 ? [p] : [...a, p]) } : undefined
  return (
    <div className="split">
      <div className="panel-l" style={{ width: 'calc(var(--side-l) + 20px)' }}>
        <div className="panel-b">
          <h4 style={{ marginTop: 0 }}>{tr('size')}</h4>
          <div className="row">
            <span className="muted" style={{ flex: 'none' }}>{tr('metres_per_unit')}</span>
            <NumField value={params.scale} digits={5} onCommit={v => v > 0 && edit({ scale: v })} label={tr('scale')} />
          </div>
          <div className="row">
            <button className={'sm' + (measure ? ' primary' : '')} onClick={() => { setMeasure(m => !m); setPts([]) }} disabled={!glb}>{tr('measure')}</button>
            {known().map(([n, v]) => <button key={n} className={'sm' + (real === v ? ' on' : '')} onClick={() => setReal(v)} title={v + ' m'}>{n}</button>)}
          </div>
          <div className="row">
            <NumField value={real} digits={2} unit="m" onCommit={v => v > 0 && setReal(v)} label={tr('real_length')} />
            <button className="primary sm" onClick={apply} disabled={dist == null}>{tr('apply')}</button>
          </div>
          <div className="muted small">{dist != null ? `${dist.toFixed(3)} ${tr('units')} → ${label}` : (measure ? tr('click_two_points') : '')}</div>
          <h4>{tr('area')}</h4>
          <div className="row">{[20, 40, 80].map(r => <button key={r} className={'sm' + (radius === r ? ' on' : '')} onClick={() => setRadius(r)}>{r}</button>)}</div>
          <div className="row" style={{ marginTop: 8 }}><button onClick={() => S.setPage('region')} disabled={!ov}>{tr('next')}</button></div>
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, position: 'relative', background: 'var(--vp)' }}>
        {glb ? <SceneCanvas url={glb.url} scale={params.scale} pick={pick} /> : <div className="empty">{ov ? tr('pick_a_spot_on_the_map') : tr('open_a_scene_first')}</div>}
        {glb && <div className="hint" style={{ position: 'absolute', left: 10, bottom: 8 }}>{glb.triangles.toLocaleString()} {tr('triangles')}</div>}
      </div>
      <div className="panel-r">
        <div className="panel-b">
          <TopView S={S} spot={spot} onSpot={setSpot} readOnly />
        </div>
      </div>
    </div>
  )
}
