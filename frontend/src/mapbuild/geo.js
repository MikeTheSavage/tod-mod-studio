// Pure helpers of the map building tools (node tests: tests/mapbuild.test.mjs). Game coordinates: x east, y up, z north.

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v))
export const r2 = v => Math.round(v * 100) / 100
export const smoothstep = t => { const c = clamp(t, 0, 1); return c * c * (3 - 2 * c) }

// ---- packed arrays (base64 of little-endian typed arrays, as the backend sends them)
export function b64ToBytes(s) {
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
export function bytesToB64(bytes) {
  let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
  return btoa(s)
}
export const f32 = s => { const b = b64ToBytes(s); return new Float32Array(b.buffer, b.byteOffset, b.byteLength >> 2) }
export const u32 = s => { const b = b64ToBytes(s); return new Uint32Array(b.buffer, b.byteOffset, b.byteLength >> 2) }
export const u8 = s => b64ToBytes(s)

// ---- the height grid: { ox, oz, cell, nx, nz, h: Float32Array((nz+1)*(nx+1)) }, h[j*(nx+1)+i] at (ox+i*cell, oz+j*cell)
export function gridFromField(t) {
  return { ox: t.origin[0], oz: t.origin[1], cell: t.cell, nx: t.nx, nz: t.nz, h: Float32Array.from(f32(t.heights)) }
}
export const cloneGrid = g => ({ ...g, h: Float32Array.from(g.h) })
export function heightAt(g, x, z) {
  const fx = clamp((x - g.ox) / g.cell, 0, g.nx), fz = clamp((z - g.oz) / g.cell, 0, g.nz)
  const i0 = Math.min(Math.floor(fx), g.nx - 1), j0 = Math.min(Math.floor(fz), g.nz - 1)
  const tx = fx - i0, tz = fz - j0, w = g.nx + 1
  return g.h[j0 * w + i0] * (1 - tx) * (1 - tz) + g.h[j0 * w + i0 + 1] * tx * (1 - tz) + g.h[(j0 + 1) * w + i0] * (1 - tx) * tz + g.h[(j0 + 1) * w + i0 + 1] * tx * tz
}
export function slopeAt(g, x, z) {
  const d = g.cell * 0.5
  const gx = (heightAt(g, x + d, z) - heightAt(g, x - d, z)) / (2 * d), gz = (heightAt(g, x, z + d) - heightAt(g, x, z - d)) / (2 * d)
  return Math.hypot(gx, gz)
}
export const triangles = g => g.nx * g.nz * 2

// ---- brush strokes: the same maths as backend/todms/mapgen/terrain.py (so the live view matches what the builder makes)
export function falloff(d, radius, kind) {
  const t = d / Math.max(radius, 1e-6)
  if (kind === 'flat') return t <= 1 ? 1 : 0
  if (kind === 'linear') return clamp(1 - t, 0, 1)
  return 1 - smoothstep(t)
}
function blur(g) {
  const w = g.nx + 1, H = g.nz + 1, out = new Float32Array(g.h.length)
  for (let j = 0; j < H; j++) for (let i = 0; i < w; i++) {
    let s = 0
    for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) s += g.h[clamp(j + dj, 0, H - 1) * w + clamp(i + di, 0, w - 1)]
    out[j * w + i] = s / 9
  }
  return out
}
// only the grid points inside the stroke are touched (a big map stays fast while dragging); returns the touched index box
export function applyStroke(g, s) {
  const w = g.nx + 1
  const [px, pz] = s.pos
  const radius = s.radius ?? 10, strength = s.strength ?? 1, kind = s.falloff || 'smooth'
  const ramp = s.tool === 'ramp'
  let qx = px, qz = pz, L = 0, ux = 0, uz = 0, h0 = 0, h1 = 0
  if (ramp) {
    [qx, qz] = s.to || [px + radius, pz]
    const dx = qx - px, dz = qz - pz
    L = Math.max(Math.hypot(dx, dz), 1e-6); ux = dx / L; uz = dz / L
    h0 = s.height != null ? s.height : heightAt(g, px, pz); h1 = s.to_height != null ? s.to_height : heightAt(g, qx, qz)
  }
  const i0 = clamp(Math.floor((Math.min(px, qx) - radius - g.ox) / g.cell), 0, g.nx), i1 = clamp(Math.ceil((Math.max(px, qx) + radius - g.ox) / g.cell), 0, g.nx)
  const j0 = clamp(Math.floor((Math.min(pz, qz) - radius - g.oz) / g.cell), 0, g.nz), j1 = clamp(Math.ceil((Math.max(pz, qz) + radius - g.oz) / g.cell), 0, g.nz)
  const target = s.tool === 'flatten' ? (s.height != null ? s.height : heightAt(g, px, pz)) : 0
  const src = s.tool === 'smooth' ? blur(g) : null
  const k = Math.min(1, Math.abs(strength))
  const passes = s.tool === 'smooth' ? Math.max(1, s.passes ?? 2) : 1
  for (let pass = 0; pass < passes; pass++) {
    const from = pass === 0 ? src : blur(g)
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const x = g.ox + i * g.cell, z = g.oz + j * g.cell, at = j * w + i
      if (ramp) {
        const along = (x - px) * ux + (z - pz) * uz, lat = Math.abs((x - px) * -uz + (z - pz) * ux)
        const beyond = Math.max(-along, along - L, 0)
        const wt = falloff(Math.hypot(lat, beyond), radius, kind)
        g.h[at] += (h0 + (h1 - h0) * clamp(along / L, 0, 1) - g.h[at]) * wt * k
        continue
      }
      const wt = falloff(Math.hypot(x - px, z - pz), radius, kind)
      if (!wt) continue
      if (s.tool === 'raise') g.h[at] += strength * wt
      else if (s.tool === 'lower') g.h[at] -= strength * wt
      else if (s.tool === 'flatten') g.h[at] += (target - g.h[at]) * wt * k
      else if (s.tool === 'smooth') g.h[at] = g.h[at] * (1 - wt * k) + from[at] * wt * k
    }
  }
  return [i0, i1, j0, j1]
}

// ---- splines (Catmull-Rom through the control points, resampled every `step` metres of arc: backend roads.spline)
const cr = (p0, p1, p2, p3, t) => {
  const t2 = t * t, t3 = t2 * t
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
}
export function spline(pts, step = 2) {
  const P = pts.map(p => [p[0], p[1]])
  if (P.length < 2) return { xz: P, s: [0], at: P.map(() => 0) }
  const dense = [], ctl = []
  if (P.length === 2) {
    for (let k = 0; k <= 63; k++) dense.push([P[0][0] + (P[1][0] - P[0][0]) * k / 63, P[0][1] + (P[1][1] - P[0][1]) * k / 63])
    ctl.push(0, 63)
  } else {
    const ext = [[2 * P[0][0] - P[1][0], 2 * P[0][1] - P[1][1]], ...P, [2 * P[P.length - 1][0] - P[P.length - 2][0], 2 * P[P.length - 1][1] - P[P.length - 2][1]]]
    for (let i = 1; i < ext.length - 2; i++) {
      ctl.push(dense.length)
      const last = i === ext.length - 3
      for (let k = 0; k < (last ? 25 : 24); k++) {
        const t = k / 24
        dense.push([cr(ext[i - 1][0], ext[i][0], ext[i + 1][0], ext[i + 2][0], t), cr(ext[i - 1][1], ext[i][1], ext[i + 1][1], ext[i + 2][1], t)])
      }
    }
    ctl.push(dense.length - 1)
  }
  const sd = [0]
  for (let i = 1; i < dense.length; i++) sd.push(sd[i - 1] + Math.hypot(dense[i][0] - dense[i - 1][0], dense[i][1] - dense[i - 1][1]))
  const total = sd[sd.length - 1]
  const n = Math.max(2, Math.ceil(total / step) + 1)
  const xz = [], s = []
  let j = 0
  for (let k = 0; k < n; k++) {
    const q = total * k / (n - 1)
    while (j < sd.length - 2 && sd[j + 1] < q) j++
    const f = sd[j + 1] > sd[j] ? (q - sd[j]) / (sd[j + 1] - sd[j]) : 0
    xz.push([dense[j][0] + (dense[j + 1][0] - dense[j][0]) * f, dense[j][1] + (dense[j + 1][1] - dense[j][1]) * f]); s.push(q)
  }
  return { xz, s, at: ctl.map(d => sd[d]) }
}

// slope along a road: [{pos [x, y, z], slope}] using the terrain, or the deck heights of a bridge (pinned points; free ends sit on the ground)
export function roadProfile(road, g, step = 2) {
  const pts = road.points || []
  if (pts.length < 2) return []
  const sp = spline(pts, step)
  const ground = sp.xz.map(p => (g ? heightAt(g, p[0], p[1]) : 0))
  let y = ground
  if (road.elevated) {
    const knots = pts.map((p, i) => ({ s: sp.at[i], y: p[2] != null ? p[2] : (i === 0 || i === pts.length - 1 ? ground[Math.min(ground.length - 1, Math.round(sp.at[i] / step))] : null) })).filter(k => k.y != null)
    y = sp.s.map(s => {
      if (!knots.length) return 0
      if (s <= knots[0].s) return knots[0].y
      for (let i = 1; i < knots.length; i++) if (s <= knots[i].s) { const f = (s - knots[i - 1].s) / Math.max(1e-6, knots[i].s - knots[i - 1].s); return knots[i - 1].y + (knots[i].y - knots[i - 1].y) * f }
      return knots[knots.length - 1].y
    })
  } else if (g) {
    y = ground.map((v, i) => (ground[Math.max(0, i - 2)] + v + ground[Math.min(ground.length - 1, i + 2)]) / 3)     // the road is a low-passed line
  }
  return sp.xz.map((p, i) => {
    const a = Math.max(0, i - 1), b = Math.min(sp.xz.length - 1, i + 1)
    return { pos: [p[0], y[i], p[1]], slope: Math.abs(y[b] - y[a]) / Math.max(1e-6, sp.s[b] - sp.s[a]) }
  })
}
export const SLOPE_CAR = 0.15, SLOPE_WALK = 0.35
export const slopeClass = s => (s > SLOPE_WALK ? 'steep' : s > SLOPE_CAR ? 'hard' : 'ok')

// nearest segment of a polyline to a screen point: { d (pixels), i (segment index), t }
export function nearestOnLine(pts2, p, project) {
  let best = { d: Infinity, i: -1, t: 0 }
  for (let i = 0; i < pts2.length - 1; i++) {
    const a = project(pts2[i]), b = project(pts2[i + 1])
    if (!a || !b) continue
    const dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy
    const t = L2 ? clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / L2, 0, 1) : 0
    const d = Math.hypot(p.x - (a.x + dx * t), p.y - (a.y + dy * t))
    if (d < best.d) best = { d, i, t }
  }
  return best
}

// ---- polygons
export function polyOf(a) {
  if (a.polygon) return a.polygon
  if (a.rect) { const [x0, z0, x1, z1] = a.rect; return [[Math.min(x0, x1), Math.min(z0, z1)], [Math.max(x0, x1), Math.min(z0, z1)], [Math.max(x0, x1), Math.max(z0, z1)], [Math.min(x0, x1), Math.max(z0, z1)]] }
  if (a.circle) return Array.from({ length: 24 }, (_, k) => [a.circle[0] + a.circle[2] * Math.cos(2 * Math.PI * k / 24), a.circle[1] + a.circle[2] * Math.sin(2 * Math.PI * k / 24)])
  return []
}
export function polyArea(p) {
  let a = 0
  for (let i = 0; i < p.length; i++) { const q = p[(i + 1) % p.length]; a += p[i][0] * q[1] - q[0] * p[i][1] }
  return Math.abs(a) / 2
}
export function inPoly(x, z, p) {
  let inside = false
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, zi] = p[i], [xj, zj] = p[j]
    if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) inside = !inside
  }
  return inside
}
export const inRect = (r, x, z) => x >= r[0] && x <= r[2] && z >= r[1] && z <= r[3]
export const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(r2)

// unique id for a new recipe entry
export function newId(list, base) {
  const used = new Set((list || []).map(x => x.id))
  for (let i = 1; i < 999; i++) if (!used.has(base + i)) return base + i
  return base + Date.now().toString(36)
}

export const sectionAt = (plan, x, z) => (plan || []).find(s => inRect(s.rect, x, z))?.id || null
// points every `spacing` metres from a (exclusive) to b (inclusive)
export function stampsAlong(a, b, spacing) {
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.floor(L / Math.max(0.25, spacing)))
  return Array.from({ length: n }, (_, k) => [a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n])
}
