// three.js drawing of the map building tools, added straight into the shared view's scene (game coordinates in, view coordinates out).
// Nothing here is a React component: MapBuildTools owns one BuildLayer and fills its named parts.
import * as THREE from 'three'
import { f32, u32, heightAt } from './geo.js'

export const toV = (x, y, z) => new THREE.Vector3(x, y, -z)
// The shared view draws in plain (linear) output, so a colour written as a hex string has to be used as-is, not converted twice.
// `lit` > 1 brightens a surface that is lit by the view's lights (they are dim: a lit grey of 0.4 shows as 0.13)
export const C = (hex, lit = 1) => {
  const c = new THREE.Color(hex)
  return c.setRGB(Math.pow(c.r, 1 / 2.2) * lit, Math.pow(c.g, 1 / 2.2) * lit, Math.pow(c.b, 1 / 2.2) * lit, THREE.LinearSRGBColorSpace)
}
export const LIT = 2.6

export const GROUND_COLORS = { dirt: '#9a7a54', sand: '#d6c080', asphalt: '#4a4d55', grass: '#5c8c46', rock: '#7a7a80' }
export const colorOfMaterial = p => GROUND_COLORS[p.id] || GROUND_COLORS[p.kind] || '#8a8a8a'

// the face materials a player can tell apart, each with a colour AND a pattern (colour is never the only signal)
export const SURFACES = [
  { name: 'Dirt', color: '#c9884a', pattern: 'dots' }, { name: 'Stone', color: '#9aa3b2', pattern: 'cross' }, { name: 'Grass', color: '#6fcf6f', pattern: 'ticks' },
  { name: 'Asphalt', color: '#6b7280', pattern: 'lines' }, { name: 'Water', color: '#4aa8ff', pattern: 'waves' }, { name: 'Concrete', color: '#d8d2c4', pattern: 'grid' },
  { name: 'Wood', color: '#b5733c', pattern: 'diag' }, { name: 'Metal', color: '#c7a6ff', pattern: 'diamond' },
]
export const surfaceStyle = name => SURFACES.find(s => s.name === name) || { name, color: '#cccccc', pattern: 'none' }

function drawPattern(ctx, kind, x, y, w, h) {
  ctx.beginPath()
  const cx = x + w / 2, cy = y + h / 2
  switch (kind) {
    case 'dots': ctx.arc(cx, cy, w * 0.14, 0, 7); ctx.fill(); return
    case 'cross': ctx.moveTo(x + 2, y + 2); ctx.lineTo(x + w - 2, y + h - 2); ctx.moveTo(x + w - 2, y + 2); ctx.lineTo(x + 2, y + h - 2); break
    case 'ticks': ctx.moveTo(x + w * 0.3, y + h - 2); ctx.lineTo(x + w * 0.3, y + h * 0.4); ctx.moveTo(x + w * 0.7, y + h - 2); ctx.lineTo(x + w * 0.7, y + h * 0.4); break
    case 'lines': ctx.moveTo(x + 1, cy); ctx.lineTo(x + w - 1, cy); break
    case 'waves': ctx.moveTo(x + 1, cy); ctx.lineTo(x + w * 0.3, cy - h * 0.25); ctx.lineTo(x + w * 0.6, cy + h * 0.25); ctx.lineTo(x + w - 1, cy); break
    case 'grid': ctx.moveTo(cx, y + 1); ctx.lineTo(cx, y + h - 1); ctx.moveTo(x + 1, cy); ctx.lineTo(x + w - 1, cy); break
    case 'diag': ctx.moveTo(x + 1, y + h - 1); ctx.lineTo(x + w - 1, y + 1); break
    case 'diamond': ctx.moveTo(cx, y + 1); ctx.lineTo(x + w - 1, cy); ctx.lineTo(cx, y + h - 1); ctx.lineTo(x + 1, cy); ctx.closePath(); break
    default: return
  }
  ctx.stroke()
}
// a small picture of one surface (the legend)
export function swatchUrl(name, size = 18) {
  const st = surfaceStyle(name), c = document.createElement('canvas')
  c.width = c.height = size
  const ctx = c.getContext('2d')
  ctx.fillStyle = st.color; ctx.globalAlpha = 0.45; ctx.fillRect(0, 0, size, size); ctx.globalAlpha = 1
  ctx.strokeStyle = '#10151b'; ctx.fillStyle = '#10151b'; ctx.lineWidth = 1.4
  drawPattern(ctx, st.pattern, 0, 0, size, size)
  return c.toDataURL()
}
// the overlay picture of the surface layer: one tile per grid cell
export function surfaceTexture(nx, nz, surf, surfNames, tile = 8) {
  const c = document.createElement('canvas')
  c.width = nx * tile; c.height = nz * tile
  const ctx = c.getContext('2d')
  ctx.lineWidth = 1
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const st = surfaceStyle(surfNames[surf[j * nx + i]])
    const x = i * tile, y = (nz - 1 - j) * tile
    ctx.fillStyle = st.color; ctx.globalAlpha = 0.5; ctx.fillRect(x, y, tile, tile); ctx.globalAlpha = 0.95
    ctx.strokeStyle = '#10151b'; ctx.fillStyle = '#10151b'
    drawPattern(ctx, st.pattern, x, y, tile, tile)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.magFilter = THREE.NearestFilter; tex.minFilter = THREE.LinearFilter; tex.needsUpdate = true
  return tex
}

// ---------------------------------------------------------------- sprites that keep their size on screen (handles and markers)
const glyphCache = new Map()
export function glyph(shape, color = '#ffffff', ring = '#10151b') {
  const key = shape + color + ring
  if (glyphCache.has(key)) return glyphCache.get(key)
  const c = document.createElement('canvas')
  c.width = c.height = 64
  const x = c.getContext('2d')
  x.lineWidth = 6; x.strokeStyle = ring; x.fillStyle = color; x.lineJoin = 'round'
  x.beginPath()
  if (shape === 'tri') { x.moveTo(32, 8); x.lineTo(58, 54); x.lineTo(6, 54); x.closePath() }
  else if (shape === 'cross') { x.lineWidth = 12; x.strokeStyle = ring; x.moveTo(12, 12); x.lineTo(52, 52); x.moveTo(52, 12); x.lineTo(12, 52); x.stroke(); x.lineWidth = 6; x.strokeStyle = color; x.beginPath(); x.moveTo(12, 12); x.lineTo(52, 52); x.moveTo(52, 12); x.lineTo(12, 52); x.stroke(); const t = new THREE.CanvasTexture(c); glyphCache.set(key, t); return t }
  else if (shape === 'square') x.rect(12, 12, 40, 40)
  else if (shape === 'diamond') { x.moveTo(32, 6); x.lineTo(58, 32); x.lineTo(32, 58); x.lineTo(6, 32); x.closePath() }
  else x.arc(32, 32, 20, 0, 7)
  x.fill(); x.stroke()
  const t = new THREE.CanvasTexture(c)
  glyphCache.set(key, t)
  return t
}
export function marker(pos, shape, color, size = 0.028, name) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glyph(shape, color), sizeAttenuation: false, depthTest: false, transparent: true }))
  s.position.copy(toV(pos[0], pos[1], pos[2])); s.scale.set(size, size, 1); s.renderOrder = 20; s.userData = { overlay: true, name }
  return s
}

export function lineOf(points, color, opts = {}) {
  const g = new THREE.BufferGeometry().setFromPoints(points.map(p => toV(p[0], p[1], p[2])))
  const m = opts.dashed ? new THREE.LineDashedMaterial({ color: C(color), dashSize: 1.5, gapSize: 1, depthTest: false, transparent: true, opacity: opts.opacity ?? 1 })
    : new THREE.LineBasicMaterial({ color: C(color), depthTest: opts.depthTest ?? false, transparent: true, opacity: opts.opacity ?? 1 })
  const l = opts.closed ? new THREE.LineLoop(g, m) : new THREE.Line(g, m)
  if (opts.dashed) l.computeLineDistances()
  l.renderOrder = opts.order ?? 15; l.userData = { overlay: true }
  return l
}
// a ring on the ground (brush)
export function ringOf(radius, color) {
  const pts = Array.from({ length: 49 }, (_, i) => new THREE.Vector3(Math.cos(i / 48 * Math.PI * 2), 0, Math.sin(i / 48 * Math.PI * 2)))
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: C(color), depthTest: false, transparent: true }))
  l.scale.setScalar(radius); l.renderOrder = 16; l.userData = { overlay: true }
  return l
}
// a polygon on the ground, with heights from the grid (or a fixed y)
export function polyLine(poly, g, color, y0 = 0.3, opts = {}) {
  const pts = poly.map(p => [p[0], (g ? heightAt(g, p[0], p[1]) : 0) + y0, p[1]])
  return lineOf(pts, color, { closed: opts.closed ?? true, dashed: opts.dashed, opacity: opts.opacity })
}
export function textSprite(text, color = '#ffffff', size = 0.045) {
  const c = document.createElement('canvas')
  c.width = 256; c.height = 64
  const x = c.getContext('2d')
  x.font = '600 34px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'
  x.lineWidth = 7; x.strokeStyle = '#10151b'; x.strokeText(text, 128, 32); x.fillStyle = color; x.fillText(text, 128, 32)
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), sizeAttenuation: false, depthTest: false, transparent: true }))
  s.scale.set(size * 4, size, 1); s.renderOrder = 21; s.userData = { overlay: true }
  return s
}

// ---------------------------------------------------------------- the terrain: one quad per cell (own vertices: hard colour edges)
export function buildTerrain(g, paintIdx, palette) {
  const { nx, nz, cell } = g
  const n = nx * nz
  const pos = new Float32Array(n * 12), nor = new Float32Array(n * 12), col = new Float32Array(n * 12), uv = new Float32Array(n * 8)
  const idx = new Uint32Array(n * 6)
  for (let c = 0; c < n; c++) {
    const b = c * 4
    idx.set([b, b + 2, b + 1, b, b + 3, b + 2], c * 6)
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3))
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3)); geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); geo.setIndex(new THREE.BufferAttribute(idx, 1))
  const cols = (palette || []).map(p => C(colorOfMaterial(p), LIT))
  const T = { geo, g, paint: paintIdx, cols }
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const c = j * nx + i
    for (let k = 0; k < 4; k++) { const ci = i + (k === 1 || k === 2 ? 1 : 0), cj = j + (k >= 2 ? 1 : 0); uv[(c * 4 + k) * 2] = ci / nx; uv[(c * 4 + k) * 2 + 1] = cj / nz }
  }
  updateTerrain(T, 0, nx - 1, 0, nz - 1)
  geo.computeBoundingSphere(); geo.computeBoundingBox()
  void cell
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }))
  mesh.userData = { terrain: true }
  T.mesh = mesh
  return T
}
const SUN = (() => { const v = [-0.45, 0.75, 0.5], l = Math.hypot(...v); return v.map(x => x / l) })()
// recompute the cells i0..i1, j0..j1 (positions, normals, colours) after a stroke or a paint change
export function updateTerrain(T, i0, i1, j0, j1) {
  const { g, geo, paint, cols } = T
  const { nx, nz, cell, ox, oz } = g
  const w = nx + 1
  const P = geo.attributes.position.array, N = geo.attributes.normal.array, C = geo.attributes.color.array
  const hh = (i, j) => g.h[Math.max(0, Math.min(nz, j)) * w + Math.max(0, Math.min(nx, i))]
  const normal = (i, j, out, o) => {
    const dx = (hh(i + 1, j) - hh(i - 1, j)) / (2 * cell), dz = (hh(i, j + 1) - hh(i, j - 1)) / (2 * cell)
    const l = Math.hypot(dx, 1, dz)
    out[o] = -dx / l; out[o + 1] = 1 / l; out[o + 2] = dz / l           // view z is flipped
  }
  for (let j = Math.max(0, j0 - 1); j <= Math.min(nz - 1, j1 + 1); j++) for (let i = Math.max(0, i0 - 1); i <= Math.min(nx - 1, i1 + 1); i++) {
    const c = j * nx + i
    const col = cols[paint ? paint[c] : 0] || cols[0]
    for (let k = 0; k < 4; k++) {
      const ci = i + (k === 1 || k === 2 ? 1 : 0), cj = j + (k >= 2 ? 1 : 0), o = (c * 4 + k) * 3
      P[o] = ox + ci * cell; P[o + 1] = g.h[cj * w + ci]; P[o + 2] = -(oz + cj * cell)
      normal(ci, cj, N, o)
      // a baked hill shade (the view's lights are flat), so the shape of the ground can be read while sculpting
      const sh = Math.max(0.35, Math.min(1.5, 0.5 + 0.95 * Math.max(0, N[o] * SUN[0] + N[o + 1] * SUN[1] + N[o + 2] * SUN[2])))
      if (col) { C[o] = col.r * sh; C[o + 1] = col.g * sh; C[o + 2] = col.b * sh } else { C[o] = C[o + 1] = C[o + 2] = 0.55 * sh }
    }
  }
  geo.attributes.position.needsUpdate = true; geo.attributes.normal.needsUpdate = true; geo.attributes.color.needsUpdate = true
  geo.computeBoundingSphere(); geo.computeBoundingBox()
}

// ---------------------------------------------------------------- generated models from /api/mapbuild/preview
const KIND_COLOR = { asphalt: '#3d4047', road_l1: '#3d4047', road_l2: '#3d4047', road_l3: '#3d4047', road_l4: '#3d4047', concrete: '#a9a79f', cliff: '#7d6f60', water: '#3d8fd8', foliage: '#3f7a3c', wood: '#7a5530', dirt: '#8f7350', grass: '#5c8c46', sand: '#d6c080' }
export function buildGenerated(pv) {
  const root = new THREE.Group()
  root.userData = { overlay: true }
  const kind = Object.fromEntries((pv.textures || []).map(t => [t.name, t.kind]))
  const made = {}
  for (const [name, md] of Object.entries(pv.models || {})) {
    if (name === 'BLOCKOUT') continue                  // the boxes are drawn by the blockout tool itself
    const grp = new THREE.Group()
    for (const me of md.meshes) {
      const P = f32(me.P), I = u32(me.I), pos = new Float32Array(P.length)
      for (let i = 0; i < P.length; i += 3) { pos[i] = P[i]; pos[i + 1] = P[i + 1]; pos[i + 2] = -P[i + 2] }
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setIndex(new THREE.BufferAttribute(I, 1)); geo.computeVertexNormals()
      const k = kind[me.tex] || 'concrete'
      const wat = k === 'water'
      const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: C(KIND_COLOR[k] || '#9a9a9a', k === 'water' ? 1.6 : LIT), side: THREE.DoubleSide, transparent: wat, opacity: wat ? 0.6 : 1, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 }))
      mesh.userData = { overlay: true, hex: KIND_COLOR[k] || '#9a9a9a', water: wat }
      grp.add(mesh)
    }
    made[name] = grp
  }
  for (const pl of pv.placements || []) {
    const src = made[pl.model]
    if (!src) continue
    const c = src.clone()
    c.userData.key = bakeKey(pl.model, pl.pos)
    c.position.copy(toV(pl.pos[0], pl.pos[1], pl.pos[2]))
    root.add(c)
  }
  return root
}

// ---------------------------------------------------------------- baked colours (Look tool: before / after)
// the key the server answers a placement under (todms.bakeprev.key_of)
export const bakeKey = (model, pos) => `${model}@${pos.map(v => (Math.round(v * 1e4) / 1e4 + 0).toFixed(4).replace('-0.0000', '0.0000')).join(',')}`
const b64u8 = s => { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a }

// the generated models drawn with their baked colours as vertex colours (unlit: the colours already hold the light)
export function paintBaked(root, baked) {
  if (!root || !baked) return 0
  let n = 0
  for (const grp of root.children) {
    const rows = baked.meshes?.[grp.userData.key]
    if (!rows) continue
    grp.children.forEach((mesh, k) => {
      const rgb = rows[k] && b64u8(rows[k])
      const count = mesh.geometry.attributes.position.count
      if (!rgb || rgb.length !== count * 3) return
      const base = C(mesh.userData.hex || '#9a9a9a', 1)
      const col = new Float32Array(count * 3)
      for (let i = 0; i < count; i++) { col[i * 3] = base.r * rgb[i * 3] / 255; col[i * 3 + 1] = base.g * rgb[i * 3 + 1] / 255; col[i * 3 + 2] = base.b * rgb[i * 3 + 2] / 255 }
      const geo = mesh.geometry.clone()
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3))
      mesh.geometry = geo
      mesh.material = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, transparent: !!mesh.userData.water, opacity: mesh.userData.water ? 0.6 : 1, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 })
      n++
    })
  }
  return n
}

// the terrain: the paint colour times the baked colour of each corner (unlit); `restoreTerrain` puts the flat view back
export function paintTerrainBaked(T, ground) {
  if (!T || !ground) return false
  const { nx, nz, cell } = T.g
  void cell
  const rgb = b64u8(ground.rgb), C3 = T.geo.attributes.color.array
  if (!T.lambert) T.lambert = T.mesh.material
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const c = j * nx + i
    const col = T.cols[T.paint ? T.paint[c] : 0] || T.cols[0]
    for (let k = 0; k < 4; k++) {
      const ci = i + (k === 1 || k === 2 ? 1 : 0), cj = j + (k >= 2 ? 1 : 0), o = (c * 4 + k) * 3
      const gi = (Math.min(cj, ground.nz - 1) * ground.nx + Math.min(ci, ground.nx - 1)) * 3
      for (let q = 0; q < 3; q++) C3[o + q] = (col ? [col.r, col.g, col.b][q] / LIT : 0.2) * rgb[gi + q] / 255
    }
  }
  T.geo.attributes.color.needsUpdate = true
  T.mesh.material = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 })
  return true
}
export function restoreTerrain(T) {
  if (!T || !T.lambert) return
  T.mesh.material.dispose?.()
  T.mesh.material = T.lambert
  T.lambert = null
  updateTerrain(T, 0, T.g.nx - 1, 0, T.g.nz - 1)
}

export function hullLines(pv) {
  const pts = []
  const place = {}
  for (const pl of pv.placements || []) (place[pl.model] ||= []).push(pl.pos)
  for (const [name, md] of Object.entries(pv.models || {})) {
    for (const o of place[name] || [[0, 0, 0]]) for (const s of md.hulls || []) pts.push(toV(s[0] + o[0], s[1] + o[1], s[2] + o[2]), toV(s[3] + o[0], s[4] + o[1], s[5] + o[2]))
  }
  if (!pts.length) return null
  const l = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: C('#ff5fb0'), depthTest: false, transparent: true, opacity: 0.8 }))
  l.renderOrder = 14; l.userData = { overlay: true }
  return l
}

// ---------------------------------------------------------------- the owner of the named parts
export class BuildLayer {
  constructor(scene) {
    this.scene = scene
    this.group = new THREE.Group()
    this.group.name = 'mapbuild'
    scene.add(this.group)
    this.parts = {}
  }
  set(name, obj) {
    this.drop(name)
    if (obj) { this.parts[name] = obj; this.group.add(obj) }
  }
  drop(name) {
    const o = this.parts[name]
    if (!o) return
    this.group.remove(o)
    o.traverse?.(c => { c.geometry?.dispose?.(); const m = c.material; if (m) (Array.isArray(m) ? m : [m]).forEach(x => x.dispose?.()) })
    delete this.parts[name]
  }
  dispose() {
    Object.keys(this.parts).forEach(n => this.drop(n))
    this.scene.remove(this.group)
  }
}
