// Look: a preset of the shipped maps' own lighting, or your own sun, ambient light, fog and sky. The view shows a rough version of it
// while you work (fog and two lights); the real values go into the map's light nodes when it is built.
import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { get, post } from '../api.js'
import { buildGenerated, paintBaked, paintTerrainBaked, restoreTerrain } from './layer.js'
import { Sld, Chips, Head, Pick, Check, ColorField } from './common.jsx'
import { t } from '../i18n.js'
import { t as tr } from '../i18n.js'

const hex = c => '#' + (c || [1, 1, 1]).map(v => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('')
const unhex = h => [1, 3, 5].map(i => Math.round(parseInt(h.slice(i, i + 2), 16) / 255 * 10000) / 10000)
const mem = { preview: true }

// the direction the sunlight travels (game coordinates), from the resolved orient or from azimuth and elevation (the builder's own convention)
export function sunAim(sun) {
  if (sun?.azimuth != null || sun?.elevation != null) {
    const az = (sun.azimuth ?? 0) * Math.PI / 180, el = (sun.elevation ?? 45) * Math.PI / 180
    return new THREE.Vector3(Math.sin(az) * Math.cos(el), -Math.sin(el), Math.cos(az) * Math.cos(el))
  }
  const o = sun?.orient || [0, 0, 0, 1]
  return new THREE.Vector3(0, 0, 1).applyQuaternion(new THREE.Quaternion(-o[0], -o[1], -o[2], o[3]))      // the block stores the inverse
}

export default function LookTool({ c }) {
  const { map, put, api, pv, layer, terrainRef, rev } = c
  const [presets, setPresets] = useState(null)
  const [pre, setPre] = useState(mem.preview)
  const [live, setLive] = useState(null)                   // a value being dragged: { path: [..], v }
  mem.preview = pre
  useEffect(() => { get('/api/mapbuild/looks').then(setPresets).catch(() => setPresets({ presets: [], skies: [] })) }, [])
  const look = map.look || {}
  const R = pv?.lighting || null                             // the resolved values (every field filled in)
  const sunAz = look.sun?.azimuth ?? 135, sunEl = look.sun?.elevation ?? 40
  const S = look.sun || {}, A = look.ambient || {}, F = look.fog || {}
  const setLook = patch => put({ look: { ...look, ...patch } })
  const edit = (group, patch) => setLook({ [group]: { ...(look[group] || {}), ...patch } })
  const eff = (g, k, d) => live?.g === g && live?.k === k ? live.v : (look[g]?.[k] ?? R?.[g]?.[k] ?? d)

  // ---- the rough live preview: fog, a sun, an ambient light; the view's own lights are turned down while it is on
  const saved = useRef(null)
  useEffect(() => {
    const sc = api?.scene
    if (!sc || !pre || !R) return undefined
    if (!saved.current) saved.current = { fog: sc.fog, bg: sc.background, lights: [] }
    const st = saved.current
    for (const o of sc.children) if (o.isLight && !o.userData.mbLook) { if (!st.lights.some(l => l.o === o)) st.lights.push({ o, i: o.intensity }); o.intensity = 0 }
    const sunV = { ...(R.sun || {}), ...(live?.g === 'sun' || look.sun?.azimuth != null ? { azimuth: eff('sun', 'azimuth', sunAz), elevation: eff('sun', 'elevation', sunEl) } : {}) }
    const aim = sunAim(sunV)
    aim.y = -Math.max(0.25, Math.abs(aim.y))                   // the preview sun stays above the horizon (the real convention is unproven)
    const sun = new THREE.DirectionalLight(new THREE.Color(...(R.sun?.color || [1, 1, 1])), Math.min(6, (eff('sun', 'brightness', R.sun?.brightness ?? 1)) * 2.2))
    const tgt = api.camera ? new THREE.Vector3() : new THREE.Vector3()
    sun.position.set(-aim.x * 600, -aim.y * 600, aim.z * 600).add(tgt); sun.userData.mbLook = true
    const amb = new THREE.AmbientLight(new THREE.Color(...(R.ambient?.color || [0.5, 0.5, 0.6])), Math.min(5, eff('ambient', 'brightness', R.ambient?.brightness ?? 0.6) * 2.4)); amb.userData.mbLook = true
    sc.add(sun, amb)
    const fc = new THREE.Color(...(R.fog?.color || [0.7, 0.8, 0.9]))
    sc.fog = new THREE.Fog(fc, eff('fog', 'near', R.fog?.near ?? 100), eff('fog', 'far', R.fog?.far ?? 700))
    sc.background = fc.clone().multiplyScalar(0.9)
    return () => { sc.remove(sun, amb); sun.dispose?.(); amb.dispose?.() }
  }, [api, pre, R, live])
  useEffect(() => () => {
    const sc = api?.scene, st = saved.current
    if (sc && st) { for (const l of st.lights) l.o.intensity = l.i; sc.fog = st.fog; sc.background = st.bg }
    saved.current = null
  }, [api])
  useEffect(() => {
    if (pre) return
    const sc = api?.scene, st = saved.current
    if (sc && st) { for (const l of st.lights) l.o.intensity = l.i; sc.fog = st.fog; sc.background = st.bg; saved.current = null }
  }, [pre, api])

  // ---- baked lighting: the switch, the quality, and a before / after look at the generated ground and models
  const bake = map.bake || {}
  const bakeOn = bake.enabled !== false
  const quality = bake.quality || 'normal'
  const [after, setAfter] = useState(() => new URLSearchParams(location.search).get('mbbake') === 'after')
  const [baked, setBaked] = useState(null)
  const [busy, setBusy] = useState(false)
  const genKey = JSON.stringify(['terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'look', 'blockout'].map(k => map[k] ?? null))
  useEffect(() => {
    if (!after || !bakeOn) { setBaked(null); return undefined }
    let dead = false
    setBusy(true)
    const body = { map: Object.fromEntries(['name', 'terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'look', 'blockout'].filter(k => map[k] != null).map(k => [k, map[k]])), quality }
    const id = setTimeout(() => post('/api/mapbuild/bake', body).then(d => { if (!dead) setBaked(d) }).catch(() => { if (!dead) setBaked(null) }).finally(() => { if (!dead) setBusy(false) }), 500)
    return () => { dead = true; clearTimeout(id) }
  }, [after, bakeOn, quality, genKey])
  useEffect(() => {
    const T = terrainRef?.current
    const flat = () => { restoreTerrain(T); if (layer && pv) layer.set('generated', buildGenerated(pv)) }
    if (!after || !baked || !layer) return undefined
    const id = setTimeout(() => {                               // after the screen's own redraw of the models
      if (layer.parts.generated) { layer.set('generated', buildGenerated(pv)); paintBaked(layer.parts.generated, baked) }
      paintTerrainBaked(T, baked.ground)
    }, 30)
    return () => { clearTimeout(id); flat() }
  }, [after, baked, layer, pv, rev])
  useEffect(() => () => setAfter(false), [])

  const L = (g, k, v) => setLive({ g, k, v })
  const done = () => setLive(null)
  if (!presets) return <div className="mb-body"><p className="small muted">…</p></div>
  const tint = (g, k) => <ColorField label={`${g} colour`} value={hex(look[g]?.[k] ?? R?.[g]?.[k])} onChange={v => edit(g, { [k]: unhex(v) })} />
  return <div className="mb-body">
    <Head>{t('look_b8db51')}</Head>
    <div className="mb-presets" role="radiogroup" aria-label={t('presets')}>
      {presets.presets.map(p => <button key={p.id} role="radio" aria-checked={look.preset === p.id} className={'mb-preset' + (look.preset === p.id ? ' on' : '')} title={p.derived ? 'Made from the shipped maps' : 'Straight from a shipped map'}
        onClick={() => put({ look: { preset: p.id } })}>
        <span className="sw"><i style={{ background: hex(p.look.fog?.color) }} /><i style={{ background: hex(p.look.sun?.color) }} /><i style={{ background: hex(p.look.ambient?.color) }} /></span>{look.preset === p.id ? '✓ ' : ''}{p.label}</button>)}
    </div>
    <Check label={t('preview_in_the_view')} on={pre} onChange={setPre} tip={t('approximate_fog_and_two_lights_the')} />
    <Head>{tr('baked_light')}</Head>
    <Check label={tr('bake_lighting')} on={bakeOn} onChange={v => put({ bake: { ...bake, enabled: v } })} tip={tr('shadows_and_soft_light_are_worked')} />
    {bakeOn && <>
      <Chips label={tr('quality')} value={quality} options={[{ value: 'draft', label: tr('fast') }, { value: 'normal', label: tr('normal') }, { value: 'high', label: tr('fine') }]}
        onChange={v => put({ bake: { ...bake, quality: v } })} />
      <Chips label={tr('view')} value={after ? 'after' : 'before'} options={[{ value: 'before', label: tr('before') }, { value: 'after', label: busy ? tr('after') + ' …' : tr('after') }]} onChange={v => setAfter(v === 'after')} />
    </>}
    <Head>{t('sun')}</Head>
    <div className="mb-row two"><span className="k">{t('colour')}</span>{tint('sun', 'color')}</div>
    <Sld label={t('strength')} value={look.sun?.brightness ?? R?.sun?.brightness ?? 1} min={0} max={4} step={0.05} onLive={v => L('sun', 'brightness', v)} onChange={v => { done(); edit('sun', { brightness: v }) }} />
    <Sld label={t('direction')} value={sunAz} min={0} max={360} step={1} unit="°" digits={0} tip={t('compass_direction_the_light_comes_from')}
      onLive={v => L('sun', 'azimuth', v)} onChange={v => { done(); edit('sun', { azimuth: v, elevation: sunEl, orient: undefined }) }} />
    <Sld label={t('height')} value={sunEl} min={5} max={90} step={1} unit="°" digits={0} tip={t('angle_above_the_horizon')} onLive={v => L('sun', 'elevation', v)} onChange={v => { done(); edit('sun', { azimuth: sunAz, elevation: v, orient: undefined }) }} />
    <Head>{t('ambient')}</Head>
    <div className="mb-row two"><span className="k">{t('colour')}</span>{tint('ambient', 'color')}</div>
    <Sld label={t('strength')} value={look.ambient?.brightness ?? R?.ambient?.brightness ?? 0.6} min={0} max={2} step={0.05} onLive={v => L('ambient', 'brightness', v)} onChange={v => { done(); edit('ambient', { brightness: v }) }} />
    <Head>{t('fog')}</Head>
    <div className="mb-row two"><span className="k">{t('colour')}</span>{tint('fog', 'color')}</div>
    <Sld label={t('starts')} value={F.near ?? R?.fog?.near ?? 100} min={0} max={1500} step={10} unit="m" digits={0} onLive={v => L('fog', 'near', v)} onChange={v => { done(); edit('fog', { near: v, far: Math.max(v + 10, F.far ?? R?.fog?.far ?? 700) }) }} />
    <Sld label={t('ends')} value={F.far ?? R?.fog?.far ?? 700} min={50} max={4000} step={10} unit="m" digits={0} onLive={v => L('fog', 'far', v)} onChange={v => { done(); edit('fog', { far: Math.max(v, (F.near ?? R?.fog?.near ?? 100) + 10) }) }} />
    <Head>{t('sky_and_screen')}</Head>
    <Pick label={t('sky')} value={look.sky ?? R?.sky ?? ''} options={presets.skies.map(s => ({ value: s, label: s.replace(/([a-z])([A-Z])/g, '$1 $2').replace('_', ' ') }))} onChange={v => setLook({ sky: v })} />
    <Sld label={t('brightness')} value={look.screen?.brightness ?? R?.screen?.brightness ?? 1} min={0.5} max={1.5} step={0.05} onChange={v => edit('screen', { brightness: v })} />
    <Sld label={t('colour')} value={look.screen?.saturation ?? R?.screen?.saturation ?? 1} min={0} max={2} step={0.05} onChange={v => edit('screen', { saturation: v })} />
    <Sld label={t('glow')} value={look.screen?.light_bleeding ?? R?.screen?.light_bleeding ?? 0.2} min={0} max={1} step={0.05} onChange={v => edit('screen', { light_bleeding: v })} tip={t('how_much_bright_light_bleeds_into')} />
    {(map.scene || map.edges?.length > 0) && <>
      <Head>{tr('skyline')}</Head>
      <Check label={tr('far_towers')} on={map.backdrop?.kind === 'skyline'} tip={tr('a_ring_of_far_towers_beyond')}
        onChange={v => put({ backdrop: v ? { kind: 'skyline', height: map.scene ? 'scene' : [30, 150] } : { kind: 'none' } })} />
    </>}
    {pv?.notes?.filter(n => /sun/i.test(n)).map((n, i) => <p key={i} className="small muted mb-hint">{n}</p>)}
  </div>
}
