// A read-only picture of a map's own geometry (ground, roads, water, scatter, blockout) inside a shared 3D view. The Entrances screen shows the
// arrival in it. Same server answers and the same drawing code as the build tools; nothing is edited here.
import { useEffect, useRef, useState } from 'react'
import { post } from '../api.js'
import { useViewApi, useBuildLayer, useDebounced } from './hooks.js'
import { buildTerrain, buildGenerated } from './layer.js'
import { gridFromField, u8 } from './geo.js'

const KEYS = ['terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'blockout']
const keyOf = m => JSON.stringify(KEYS.map(k => m?.[k] ?? null))

export default function MapPreview({ map, viewApi, onBusy }) {
  const api = useViewApi(viewApi)
  const layer = useBuildLayer(api)
  const [terrain, setTerrain] = useState(null), [pv, setPv] = useState(null)
  const key = useDebounced(keyOf(map), 400)
  const cb = useRef(onBusy); cb.current = onBusy
  useEffect(() => {
    let live = true
    const has = KEYS.some(k => map?.[k] != null)
    if (!has) { setTerrain(null); setPv(null); return undefined }
    const body = { name: map.name, ...Object.fromEntries(KEYS.map(k => [k, map[k]]).filter(([, v]) => v != null)) }
    cb.current?.(true)
    post('/api/mapbuild/field', { map: body }).then(f => { if (live) setTerrain(f.terrain ? buildTerrain(gridFromField(f.terrain), u8(f.terrain.paint), f.palette) : null) }).catch(() => {})
    post('/api/mapbuild/preview', { map: body }).then(p => { if (live) { setPv(p); cb.current?.(false) } }).catch(() => { if (live) cb.current?.(false) })
    return () => { live = false }
  }, [key])
  useEffect(() => { if (layer) layer.set('terrain', terrain?.mesh || null) }, [layer, terrain])
  useEffect(() => { if (layer) layer.set('generated', pv ? buildGenerated(pv) : null) }, [layer, pv])
  useEffect(() => {
    const grid3 = api?.scene?.children.find(o => o.type === 'GridHelper')
    if (!grid3) return undefined
    const was = grid3.visible
    grid3.visible = !terrain
    return () => { grid3.visible = was }
  }, [api, terrain])
  return null
}
