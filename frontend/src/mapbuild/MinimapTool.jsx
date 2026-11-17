// Minimap: the picture the pack will hold (drawn by the server with the same code that writes the pack), a test dot that shows where the game
// looks for a world position, and the write of the pack into the project.
import React, { useEffect, useRef, useState } from 'react'
import { post } from '../api.js'
import { useDebounced } from './hooks.js'
import { b64ToBytes, r2 } from './geo.js'
import { Check, Head, saveBlob } from './common.jsx'
import { t as tr } from '../i18n.js'

const KEYS = ['terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter']
const INK = () => ({ road: tr('ink_road'), kerb: tr('ink_kerb'), grass: tr('ink_grass'), dirt: tr('ink_dirt'), water: tr('ink_water'), wline: tr('ink_water'), rock: tr('ink_rock'), wall: tr('ink_wall'),
  tree: tr('ink_tree'), treel: tr('ink_tree'), bush: tr('ink_bush'), cont: tr('ink_contour'), out: tr('ink_outline'), ground: tr('ground') })
export const minimapKey = m => JSON.stringify([...KEYS.map(k => m?.[k] ?? null), m?.scene?.plan ?? null])

export default function MinimapTool({ c }) {
  const { map, put } = c
  const mm = map.minimap || { icons: true }
  const [img, setImg] = useState(null), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const [written, setWritten] = useState(null)
  const cv = useRef(null)
  const key = useDebounced(JSON.stringify([minimapKey(map), mm.test || null]), 450)
  useEffect(() => {
    let live = true
    const body = { name: map.name, ...Object.fromEntries(KEYS.map(k => [k, map[k]]).filter(([, v]) => v != null)), ...(map.scene?.plan ? { scene: { plan: map.scene.plan } } : {}) }
    setBusy(true)
    post('/api/mapbuild/minimap', { map: body, pid: c.pid, size: 512, test: mm.test || null })
      .then(r => { if (live) { setImg(r); setErr(''); setBusy(false) } })
      .catch(e => { if (live) { setImg(null); setErr(e.message); setBusy(false) } })
    return () => { live = false }
  }, [key])
  const toPx = (p, n) => (img ? [(p[0] - img.bounds[0]) / (img.bounds[2] - img.bounds[0]) * n, (1 - (p[1] - img.bounds[1]) / (img.bounds[3] - img.bounds[1])) * n] : [0, 0])
  useEffect(() => {
    const cn = cv.current
    if (!cn || !img) return undefined
    const x = cn.getContext('2d'), im = new Image(), N = 256
    im.onload = () => {
      x.clearRect(0, 0, N, N); x.fillStyle = '#e2d0aa'; x.fillRect(0, 0, N, N)
      const k = Math.min(N / img.width, N / img.height), w = img.width * k, h = img.height * k, ox = (N - w) / 2, oy = (N - h) / 2
      x.drawImage(im, ox, oy, w, h)
      const at = p => { const [px, py] = toPx(p, 1); return [ox + px * w, oy + py * h] }
      const dot = (p, col, shape) => {
        const [px, py] = at(p)
        x.fillStyle = col; x.strokeStyle = '#10151b'; x.lineWidth = 2; x.beginPath()
        if (shape === 'sq') x.rect(px - 4, py - 4, 8, 8); else if (shape === 'tri') { x.moveTo(px, py - 5); x.lineTo(px + 5, py + 4); x.lineTo(px - 5, py + 4); x.closePath() } else x.arc(px, py, 4, 0, 7)
        x.fill(); x.stroke()
      }
      if (mm.icons !== false) {
        if (map.arrival?.pos) dot([map.arrival.pos[0], map.arrival.pos[2]], '#5fd38d', 'tri')
        if (map.return?.pos) dot([map.return.pos[0], map.return.pos[2]], '#f2a541', 'sq')
        for (const t of map.teleports || []) dot([t.pos[0], t.pos[2]], '#c7a6ff', 'dot')
      }
      if (mm.test) { const [px, py] = at(mm.test); x.strokeStyle = '#ff5fb0'; x.lineWidth = 2; x.beginPath(); x.arc(px, py, 7, 0, 7); x.moveTo(px - 11, py); x.lineTo(px + 11, py); x.moveTo(px, py - 11); x.lineTo(px, py + 11); x.stroke() }
    }
    im.src = 'data:image/png;base64,' + img.png
  }, [img, mm.icons, mm.test, map.arrival, map.return, map.teleports])
  const setMm = patch => put({ minimap: { ...mm, ...patch } })
  const click = e => {
    if (!img) return
    const r = e.currentTarget.getBoundingClientRect(), N = 256
    const k = Math.min(N / img.width, N / img.height), w = img.width * k, h = img.height * k
    const fx = ((e.clientX - r.left) / r.width * N - (N - w) / 2) / w, fy = ((e.clientY - r.top) / r.height * N - (N - h) / 2) / h
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return
    setMm({ test: [r2(img.bounds[0] + fx * (img.bounds[2] - img.bounds[0])), r2(img.bounds[1] + (1 - fy) * (img.bounds[3] - img.bounds[1]))] })
  }
  const write = async () => {
    setBusy(true)
    try { setWritten(await c.writeMinimap()) } catch (e) { setWritten({ error: e.message }) } finally { setBusy(false) }
  }
  const at = img?.at
  const fails = (written?.checks || []).filter(x => x.result === 'FAIL').length
  return <div className="mb-body">
    <Head>{tr('minimap')}</Head>
    {err ? <p className="small warn" role="status">{err}</p>
      : <canvas ref={cv} width={256} height={256} className="mb-mini" role="img" aria-label={tr('minimap_preview')} tabIndex={0} onClick={click}
        onKeyDown={e => { if (e.key === 'Enter' && map.arrival?.pos) setMm({ test: [map.arrival.pos[0], map.arrival.pos[2]] }) }} title={tr('click_to_put_the_test_dot')} />}
    <div className="mb-stat" title={at ? `${tr('pixel')} ${at.pixel[0]}, ${at.pixel[1]}` : tr('the_world_position_of_the_dot')}>
      {mm.test ? `◎ ${mm.test[0]}, ${mm.test[1]}${at ? (at.inside ? ' · ' + INK()[at.ink] : ' · ' + tr('outside')) : ''}` : '◎ ' + tr('click_the_picture')}</div>
    {img?.overlaps?.length > 0 && <div className="mb-stat steep" role="status" title={img.overlaps.join(', ')}>{'⚠ '}{tr('shares_ground_with_another_minimap')}</div>}
    <Check label={tr('icons')} on={mm.icons !== false} onChange={v => setMm({ icons: v })} tip={tr('arrival_return_and_named_spots')} />
    <div className="mb-btns">
      <button disabled={!img} onClick={() => saveBlob((map.name || 'minimap') + '.png', b64ToBytes(img.png), 'image/png')}>{tr('save_picture')}</button>
      {mm.test && <button onClick={() => setMm({ test: undefined })}>{tr('clear_dot')}</button>}
      <button className="primary" disabled={!img || busy || !c.writeMinimap} title={tr('draw_the_minimap_pack_into_the_project')} onClick={write}>{tr('write_minimap')}</button></div>
    {written && (written.error ? <p className="small warn" role="status">{written.error}</p>
      : <div className={'mb-stat ' + (fails ? 'steep' : 'ok')} role="status" title={(written.checks || []).map(x => `${x.result} ${x.check}`).join('\n')}>
        {fails ? '✖ ' + fails + ' ' + tr('checks_failed') : '✓ ' + tr('written')}{' · '}{written.maps.reduce((a, x) => a + x.tiles, 0)}{' '}{tr('tiles')}</div>)}
  </div>
}
