// The in-map building tools of the New maps screen: terrain, ground and surface paint, roads and bridges, edges, water and kill planes,
// scatter, look, blockout, kits, section planner, debug overlays and the minimap preview.
//
//   <MapBuildTools map={the map object of the recipe} project={the whole recipe} commit={fn} viewApi={ref of the shared 3D view} />
//
// commit(nextMap) receives the COMPLETE new map object. One call = one gesture (a brush stroke, a spline edit, a paint stroke, a field
// change), so the screen's own undo history records one step per call. Mount it as a child of the 3D view (it draws HTML on top and
// adds its geometry to the view's scene through viewApi.current). The recipe keys it writes are the ones of backend/todms/mapgen
// (terrain, ground_paint, roads, edges, water, scatter, look) plus two editor keys the builder ignores: `blockout` and `sections_plan`.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api.js'
import { Meter } from '../Meters.jsx'
import { useUi } from '../uistore.js'
import { useViewApi, useBuildLayer, useDebounced } from './hooks.js'
import { buildTerrain, buildGenerated, hullLines } from './layer.js'
import { gridFromField, u8, triangles } from './geo.js'
import { Toggle } from './common.jsx'
import TerrainTool from './TerrainTool.jsx'
import PaintTool from './PaintTool.jsx'
import RoadTool from './RoadTool.jsx'
import AreaTools from './AreaTools.jsx'
import LookTool from './LookTool.jsx'
import BlockoutTool from './BlockoutTool.jsx'
import SectionsTool from './SectionsTool.jsx'
import ShowTool, { useDebugLayers } from './ShowTool.jsx'
import MinimapTool from './MinimapTool.jsx'
import './mapbuild.css'
import { t } from '../i18n.js'

const KEYS = ['terrain', 'ground_paint', 'roads', 'edges', 'water', 'scatter', 'look', 'blockout']
const TABS = [
  { id: 'terrain', label: t('terrain'), tip: t('raise_lower_smooth_flatten_and_ramp') },
  { id: 'paint', label: t('paint'), tip: t('ground_materials_and_the_surface_type') },
  { id: 'roads', label: t('roads'), tip: t('roads_bridges_and_ramps') },
  { id: 'edges', label: t('edges'), tip: t('cliffs_invisible_walls_water_and_kill') },
  { id: 'scatter', label: t('scatter'), tip: t('trees_rocks_and_bushes_over_an') },
  { id: 'look', label: t('look_b8db51'), tip: t('sun_ambient_light_fog_and_sky') },
  { id: 'blockout', label: t('blockout'), tip: t('grey_boxes_first_then_real_pieces') },
  { id: 'sections', label: t('sections'), tip: t('split_the_map_into_sections_and'), advanced: true },
  { id: 'show', label: t('show'), tip: t('collision_routes_triggers_section_bounds_and'), advanced: true },
  { id: 'minimap', label: t('minimap'), tip: t('the_minimap_picture_and_its_test'), advanced: true },
]
const COMPONENTS = { terrain: TerrainTool, paint: PaintTool, roads: RoadTool, edges: AreaTools, scatter: AreaTools, look: LookTool, blockout: BlockoutTool, sections: SectionsTool, show: ShowTool, minimap: MinimapTool }

const ROW_LABEL = { G1: t('ground_pictures'), G2: t('ground_triangles'), G3: t('collision_pieces'), Q_main: t('main_quadtree'), Q_aux: t('aux_quadtree') }
const keyOf = m => JSON.stringify(KEYS.map(k => m?.[k] ?? null))
const lsGet = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const lsSet = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private window */ } }

export default function MapBuildTools({ map, project, pid, commit, viewApi, float = true, writeMinimap, toolRequest }) {
  const ui = useUi()
  const api = useViewApi(viewApi)
  const layer = useBuildLayer(api)
  const [open, setOpen] = useState(() => lsGet('todms.mapbuild.open', '1') === '1')
  const [tab, setTab] = useState(() => new URLSearchParams(location.search).get('mbtab') || lsGet('todms.mapbuild.tab', 'terrain'))
  const [show, setShow] = useState({ collision: false, routes: true, triggers: false, sections: true, spawns: true, limits: true })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [field, setField] = useState(null), [pv, setPv] = useState(null)
  const grid = useRef(null)                                 // the local height grid: { ox, oz, cell, nx, nz, h } (strokes are applied to it while you drag)
  const terrainRef = useRef(null)                           // { geo, g, paint, cols, mesh }
  const [rev, setRev] = useState(0)                         // bumps when the local grid / terrain mesh is rebuilt
  const M = useRef({ map, commit }); M.current = { map, commit }
  const put = useCallback(patch => { const m = M.current.map; M.current.commit({ ...m, ...patch }) }, [])
  const advanced = ui.prefs.mode === 'advanced'
  const tabs = TABS.filter(x => advanced || !x.advanced)
  useEffect(() => { if (!tabs.some(x => x.id === tab)) setTab('terrain') }, [advanced])
  useEffect(() => { if (toolRequest?.tab && Date.now() - toolRequest.n < 3000 && TABS.some(x => x.id === toolRequest.tab)) { setTab(toolRequest.tab); setOpen(true) } }, [toolRequest?.n])
  useEffect(() => lsSet('todms.mapbuild.tab', tab), [tab])
  useEffect(() => lsSet('todms.mapbuild.open', open ? '1' : '0'), [open])

  // ---- the server's evaluation of the recipe keys: cheap field first (grids), then the generated geometry; debounced and cached there by hash
  const key = useDebounced(keyOf(map), 350)
  const needCollision = show.collision
  useEffect(() => {
    let live = true
    const body = { name: map?.name, ...Object.fromEntries(KEYS.map(k => [k, map?.[k]]).filter(([, v]) => v != null)) }
    setBusy(true)
    post('/api/mapbuild/field', { map: body }).then(f => {
      if (!live) return
      setField(f); setErr('')
      if (f.terrain) { grid.current = gridFromField(f.terrain); terrainRef.current = buildTerrain(grid.current, u8(f.terrain.paint), f.palette) } else { grid.current = null; terrainRef.current = null }
      setRev(r => r + 1)
    }).catch(e => { if (live) setErr(e.message || String(e)) })
    post('/api/mapbuild/preview', { map: body, collision: needCollision }).then(p => { if (live) { setPv(p); setBusy(false) } }).catch(e => { if (live) { setErr(e.message || String(e)); setBusy(false) } })
    return () => { live = false }
  }, [key, needCollision])

  // ---- the terrain mesh and the generated geometry go into the view's scene
  useEffect(() => { if (layer) layer.set('terrain', terrainRef.current?.mesh || null) }, [layer, rev])
  // the view's floor grid would show through flat ground (same height): it is hidden while there is ground of our own
  useEffect(() => {
    const grid3 = api?.scene?.children.find(o => o.type === 'GridHelper')
    if (!grid3) return undefined
    const was = grid3.visible
    grid3.visible = !terrainRef.current
    return () => { grid3.visible = was }
  }, [api, rev])
  useEffect(() => {
    if (!layer) return
    layer.set('generated', pv ? buildGenerated(pv) : null)
  }, [layer, pv])
  useEffect(() => {
    if (!layer) return
    layer.set('collision', show.collision && pv ? hullLines(pv) : null)
  }, [layer, pv, show.collision])

  const ctx = useMemo(() => ({ map, project, pid, put, api, layer, grid, terrainRef, rev, field, pv, show, setShow, setRev, advanced, key, writeMinimap }), [map, project, pid, put, api, layer, rev, field, pv, show, advanced, key, writeMinimap])
  useDebugLayers(ctx, tab)
  const Tool = COMPONENTS[tab]
  const rows = (pv?.rows || []).filter(r => ['G1', 'G2', 'G3', 'Q_main', 'Q_aux'].includes(r.id))
  const st = pv?.stats
  const liveTris = grid.current ? triangles(grid.current) : st?.ground_triangles
  if (!map) return null
  return <div className={'mb-root' + (float ? ' float' : '')} data-input-scope="mapbuild"><div className="mb-flow">
    {!open && <button className="mb-open" onClick={() => setOpen(true)} title={t('build_tools_for_this_map')} aria-expanded="false">{'Build'}</button>}
    {open && <div className="mb-dock">
      <div className="mb-tabs" role="tablist" aria-orientation="vertical" aria-label={t('build_tools')}>
        {tabs.map(x => <button key={x.id} role="tab" aria-selected={tab === x.id} className={tab === x.id ? 'on' : ''} title={x.tip} onClick={() => setTab(x.id)}>{x.label}</button>)}
        <button className="mb-close" title={t('hide_the_build_tools')} onClick={() => setOpen(false)}>{'×'}</button>
      </div>
      <div className="mb-panel" role="tabpanel" aria-label={TABS.find(x => x.id === tab)?.label}>
        {err && <div className="callout warn mb-err" role="status">{err}</div>}
        {Tool && <Tool key={tab} c={ctx} which={tab} />}
      </div>
    </div>}
    {open && show.limits && <div className="mb-meters" role="group" aria-label={t('limits_of_this_map')}>
      {rows.map(r => <Meter key={r.id} r={{ ...r, label: ROW_LABEL[r.id] || r.label }} />)}
      <span className="mb-chip" title={t('ground_triangles_right_now')}>{'△ '}{liveTris != null ? liveTris.toLocaleString('en-US') : '–'}</span>
      <span className="mb-chip" title={t('pictures_this_map_makes')}>{'▣ '}{st ? st.textures : '–'}</span>
      <span className="mb-chip" title={t('things_placed')}>{'● '}{st ? st.instances : '–'}</span>
      {busy && <span className="mb-chip" role="status">{'…'}</span>}
    </div>}
    {open && pv?.notes?.length > 0 && tab !== 'look' && <Toggle className="mb-notes" label={t('notes_n', { n: pv.notes.length })}>
      {pv.notes.map((n, i) => <div key={i}>{n}</div>)}</Toggle>}
  </div></div>
}
