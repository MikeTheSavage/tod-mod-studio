import React, { useMemo } from 'react'

export const loaderColors = { WALK: '#5ad06a', TELEPORT: '#ff4d4d', ONEWAY: '#9aa5b1', MISSION: '#c08aff' }
export const spotYaw = s => {
  const [x, y, z, w] = s.orient || s.rot || [0, 0, 0, 1]
  return Math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / Math.PI
}
export const yawOrient = yaw => [0, Math.sin(yaw * Math.PI / 360), 0, Math.cos(yaw * Math.PI / 360)]

// Shared Sections / New maps top view. SVG coordinates are game x/z with north (+z) up.
export default function LoaderTopView({ volumes = [], spots = [], selected, onSelect, onPlace, after = {} }) {
  const W = 900, H = 640
  const frame = useMemo(() => {
    const points = [...volumes, ...spots, ...Object.values(after)].flatMap(v => [v.pos, v.teleport_dest?.pos].filter(Boolean))
    if (!points.length) points.push([0, 0, 0])
    const xs = points.map(p => p[0]), zs = points.map(p => p[2])
    const x0 = Math.min(...xs) - 40, z0 = Math.min(...zs) - 40
    const scale = Math.min(W / (Math.max(...xs) + 40 - x0), H / (Math.max(...zs) + 40 - z0))
    return { x0, z0, scale }
  }, [volumes, spots, after])
  const { x0, z0, scale } = frame
  const X = x => (x - x0) * scale, Z = z => H - (z - z0) * scale
  const polygon = v => {
    if (v.corners) return v.corners.map(c => `${X(c[0])},${Z(c[1])}`).join(' ')
    const yaw = spotYaw(v) * Math.PI / 180, [w, , l] = v.size || [3, 3, 3]
    return [[-1, -1], [-1, 1], [1, 1], [1, -1]].map(([a, b]) => {
      const x = a * w / 2, z = b * l / 2
      return `${X(v.pos[0] + x * Math.cos(yaw) + z * Math.sin(yaw))},${Z(v.pos[2] - x * Math.sin(yaw) + z * Math.cos(yaw))}`
    }).join(' ')
  }
  const byId = Object.fromEntries(volumes.map(v => [v.id, v]))
  const box = (v, color, click) => <g key={v.id} onClick={e => { e.stopPropagation(); click?.(v.id) }} style={{ cursor: click ? 'pointer' : 'default' }}>
    {v.radius ? <circle cx={X(v.pos[0])} cy={Z(v.pos[2])} r={Math.max(3, v.radius * scale)} fill={color} fillOpacity={0.25} stroke={color} />
      : <polygon points={polygon(v)} fill={color} fillOpacity={selected === v.id ? 0.6 : 0.25} stroke={color} strokeWidth={selected === v.id ? 3 : 1.5} />}
    <line x1={X(v.pos[0])} y1={Z(v.pos[2])} x2={X(v.pos[0]) + Math.sin(spotYaw(v) * Math.PI / 180) * 20}
      y2={Z(v.pos[2]) - Math.cos(spotYaw(v) * Math.PI / 180) * 20} stroke={color} strokeWidth={2} markerEnd="url(#loader-arrow)" />
    <text x={X(v.pos[0]) + 6} y={Z(v.pos[2]) - 7} fill={color} fontSize={11}>{v.label || v.name || v.id}</text>
  </g>
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minHeight: 360, maxHeight: 680, background: '#10141a' }}
    aria-label="Loader spots top view, north up" onClick={e => {
      if (!onPlace) return
      const p = e.currentTarget.createSVGPoint(); p.x = e.clientX; p.y = e.clientY
      const q = p.matrixTransform(e.currentTarget.getScreenCTM().inverse())
      onPlace([x0 + q.x / scale, z0 + (H - q.y) / scale])
    }}>
    <defs><marker id="loader-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#d8e2ef" /></marker></defs>
    {volumes.map(v => <g key={v.id}>
      {byId[v.pair] && <line x1={X(v.pos[0])} y1={Z(v.pos[2])} x2={X(byId[v.pair].pos[0])} y2={Z(byId[v.pair].pos[2])} stroke="#d8e2ef" opacity={0.4} />}
      {v.teleport_dest && <line x1={X(v.pos[0])} y1={Z(v.pos[2])} x2={X(v.teleport_dest.pos[0])} y2={Z(v.teleport_dest.pos[2])} stroke="#ff4d4d" strokeDasharray="6 4" />}
      {box(v, loaderColors[v.cls] || '#888', onSelect)}
      {after[v.id] && box({ ...after[v.id], id: v.id + '-after' }, '#3cff8a')}
    </g>)}
    {spots.map(v => box(v, v.color || '#55dbff', onSelect))}
  </svg>
}
