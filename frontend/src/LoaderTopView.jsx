// Loader volumes and spots for the shared 3D view. This file used to hold the SVG top view; the drawing now lives in
// View3D (Top mode), and this keeps the helpers every screen shares: colours, facing maths and `loaderOverlays`,
// which turns loader volumes and spots into overlays. The default export is a ready-made view for those two kinds
// of data (used by Sections), with an optional map underneath.
import React, { useMemo } from 'react'
import View3D from './View3D.jsx'
import { boundsOf, CONTEXT_LAYERS } from './levelLoad.js'

export const loaderColors = { WALK: '#3fbf5a', TELEPORT: '#e5484d', ONEWAY: '#8491a1', MISSION: '#b27df0' }
export const spotYaw = s => {
  const [x, y, z, w] = s.orient || s.rot || [0, 0, 0, 1]
  return Math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / Math.PI
}
export const yawOrient = yaw => [0, Math.sin(yaw * Math.PI / 360), 0, Math.cos(yaw * Math.PI / 360)]

const resolve = c => (c && c.startsWith('var(') ? ({ 'var(--ok)': '#3fbf5a', 'var(--accent)': '#f2a541', 'var(--sel)': '#5b9bff' })[c] || '#5b9bff' : c)

// a volume (box with corners or size) or a spot (box with size, or a point with a facing) as an overlay
export function spotOverlay(v, color, extra = {}) {
  const base = { id: v.id, color: resolve(color), label: v.label || v.name || v.id, ...extra }
  if (v.corners) return { ...base, kind: 'poly', corners: v.corners, y: v.pos?.[1], h: v.size?.[1] ?? 4 }
  if (v.radius) return { ...base, kind: 'ring', pos: v.pos, radius: v.radius }
  if (v.size) return { ...base, kind: 'box', pos: v.pos, size: v.size, yaw: spotYaw(v), arrow: true }
  return { ...base, kind: 'point', pos: v.pos, yaw: spotYaw(v), arrow: true }
}

export function loaderOverlays({ volumes = [], spots = [], after = {}, selected }) {
  const out = []
  const byId = Object.fromEntries(volumes.map(v => [v.id, v]))
  for (const v of volumes) {
    if (byId[v.pair]) out.push({ id: v.id + '~pair', kind: 'path', points: [v.pos, byId[v.pair].pos], color: '#7d8896', pickable: false, layer: 'links' })
    if (v.teleport_dest) out.push({ id: v.id + '~tp', kind: 'path', points: [v.pos, v.teleport_dest.pos], color: '#e5484d', dashed: true, pickable: false, layer: 'links' })
    out.push(spotOverlay(v, loaderColors[v.cls] || '#888888', { selected: selected === v.id, layer: 'loaders', opacity: 0.22 }))
    if (after[v.id]) out.push(spotOverlay({ ...after[v.id], id: v.id + '-after' }, '#3cff8a', { pickable: false, layer: 'loaders' }))
  }
  for (const s of spots) out.push(spotOverlay(s, s.color || '#5b9bff', { selected: selected === s.id, always: true, layer: 'spots' }))
  return out
}

// the box of a level's blocks: where a section's own objects lie (a zone overlay per block)
export function boundsOverlays(bundle, color = '#5b9bff') {
  if (!bundle) return []
  return bundle.levels.map(L => {
    const pts = L.entities.filter(e => e.pos && e.cat !== 'logic').map(e => e.pos)
    const b = boundsOf(pts, 0)
    if (!b) return null
    return { id: 'bounds:' + L.entry, kind: 'zone', rect: b, h: 2, y: Math.min(...pts.map(p => p[1])), color, opacity: 0.05, pickable: false, always: true,
      label: (L.title || L.entry.split('/').pop()).replace(/\.(submap|map|mission)$/, ''), layer: 'bounds' }
  }).filter(Boolean)
}

export default function LoaderTopView({ volumes = [], spots = [], selected, onSelect, onPlace, after = {}, bundle, view, bounds = false, children }) {
  const overlays = useMemo(() => [...loaderOverlays({ volumes, spots, after, selected }), ...(bounds ? boundsOverlays(bundle) : [])], [volumes, spots, after, selected, bundle, bounds])
  const focus = useMemo(() => {
    const pts = [...volumes, ...spots, ...Object.values(after)].flatMap(v => [v.pos, v.teleport_dest?.pos].filter(Boolean))
    const b = boundsOf(pts, 40)
    return b ? { bounds: b, y: pts[0]?.[1] ?? 0 } : null
  }, [volumes.length, spots.length])
  return <View3D defaultMode="top" bundle={bundle} view={view} layers={CONTEXT_LAYERS} overlays={overlays} onPickOverlay={onSelect} focus={focus}
    onGround={onPlace ? (pos, ev, geometry) => onPlace([pos[0], pos[2]], pos, geometry) : undefined}>{children}</View3D>
}
