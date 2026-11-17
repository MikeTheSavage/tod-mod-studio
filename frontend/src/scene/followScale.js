// A new scale moves the region with it: the polygon is in metres at the chosen scale, so the same ground needs the polygon's numbers
// multiplied by new scale / old scale (and the point it stands at, if one is placed).
export function followScale(oldP, newP) {
  const a = Number(oldP.scale), b = Number(newP.scale)
  if (!(a > 0) || !(b > 0) || a === b) return newP
  const r = b / a
  const sc = v => Math.round(v * r * 1e4) / 1e4
  const out = { ...newP }
  const poly = newP.region && newP.region.polygon
  if (poly && poly === (oldP.region && oldP.region.polygon)) out.region = { ...newP.region, polygon: poly.map(q => [sc(q[0]), sc(q[1])]) }
  return out
}
