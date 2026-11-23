// Driving presets: a preset is a small set of changes to the driving fields. Applying one writes plain numbers into the
// project (so every value stays editable and undoable). Pure functions only; the screen is DrivePresets.jsx.
//
// A preset: { name, tip, type: { <field>: { mul | add | set: n } }, car: { <field>: { set: n } } }
//   type  = fields of the vehicle rows (per vehicle); mul / add are applied to the SHIPPED value of that vehicle
//   car   = fields every four-wheel car shares (one value for all cars; only written when the target is every car)
// A shared file is the same object plus { format: 'todms-driving-preset', version: 1 }.

// The field ranges, the tips and the four built-in presets live in one plain data file that other tools read too
// (backend/data/driving_presets.json, the shared-file format). Nothing about them is written down here.
import DATA from '../../../backend/data/driving_presets.json' with { type: 'json' }

export const FIELDS = DATA.fields
// tips for fields that matter for driving but are not part of any preset
export const TIPS_ONLY = DATA.tipsOnly
export const tipOf = label => {
  const f = FIELDS.type[label] || FIELDS.car[label]
  return f ? f.tip + (f.unit ? ' (' + f.unit + ')' : '') : TIPS_ONLY[label] || null
}

export const TYPE_KEYS = Object.keys(FIELDS.type)
export const CAR_KEYS = Object.keys(FIELDS.car)

// what each target means (vehicle rows of the Vehicles table)
export const CLASSES = DATA.classes
export const ALL_ROWS = [...CLASSES.cars, ...CLASSES.vans, ...CLASSES.heavy]

export const BUILTIN = DATA.presets.filter(p => !p.restore).map(p => ({ id: p.id, name: p.name, tip: p.tip, type: p.type || {}, car: p.car || {} }))


const r6 = n => Math.round(n * 1e6) / 1e6
const isNum = v => typeof v === 'number' && Number.isFinite(v)
export const clampField = (group, key, v) => { const f = FIELDS[group][key]; return Math.min(f.hi, Math.max(f.lo, v)) }

export const rowName = group => String(group || '').replace(/^Vehicle type: /, '').replace(/\s*\([^)]*\)\s*$/, '')

// rows a target covers: { kind: 'one', row } | { kind: 'class', cls } | { kind: 'all' }
export function rowsOf(target) {
  if (!target) return []
  if (target.kind === 'one') return target.row ? [target.row] : []
  if (target.kind === 'class') return CLASSES[target.cls] || []
  return ALL_ROWS
}

// shipped value of a field of one row: `groups` is the Vehicles data ({ groups: [{ group, fields: [{ key, value }] }] })
export function shippedIndex(data) {
  const m = {}
  for (const g of (data && data.groups) || []) for (const f of g.fields) if (isNum(f.value)) m[f.key] = f.value
  return m
}

// What applying a preset to a target does: { set: { key: value }, clear: [keys] }.
//  - the preset's own fields are written as concrete numbers (computed from the shipped value, clamped to the field's range)
//  - a field the preset does not name is left alone (what you already changed stays)
//  - the shared car fields are only written when the target is every car
export function planApply(preset, target, shipped) {
  const set = {}, clear = []
  const rows = rowsOf(target)
  for (const row of rows) {
    for (const [prop, spec] of Object.entries(preset.type || {})) {
      if (!FIELDS.type[prop]) continue
      const key = `type.${row}.${prop}`, base = shipped[key]
      if (!isNum(base)) continue
      let v = null
      if (isNum(spec.set)) v = spec.set
      else if (isNum(spec.mul)) v = base * spec.mul
      else if (isNum(spec.add)) v = base + spec.add
      if (v == null) continue
      if (base === 0 && !isNum(spec.set)) continue            // a value that is zero in the game (never slides, ...) stays zero
      v = r6(clampField('type', prop, v))
      if (Math.abs(v - base) < 1e-9) clear.push(key); else set[key] = v
    }
  }
  if (target && target.kind === 'all') {
    for (const [prop, spec] of Object.entries(preset.car || {})) {
      if (!FIELDS.car[prop] || !isNum(spec.set)) continue
      const key = `car.${prop}`, base = shipped[key], v = r6(clampField('car', prop, spec.set))
      if (isNum(base) && Math.abs(v - base) < 1e-9) clear.push(key); else set[key] = v
    }
  }
  return { set, clear }
}

// Back to the game's own values for a target: every driving field the presets can touch is cleared.
export function planRestore(target) {
  const clear = []
  for (const row of rowsOf(target)) for (const prop of TYPE_KEYS) clear.push(`type.${row}.${prop}`)
  if (target && target.kind === 'all') for (const prop of CAR_KEYS) clear.push(`car.${prop}`)
  return { set: {}, clear }
}

// merge a plan into the project's vehicle values
export function applyPlan(vals, plan) {
  const out = { ...(vals || {}) }
  for (const k of plan.clear) delete out[k]
  Object.assign(out, plan.set)
  return out
}

// A preset made from what is changed on one vehicle: type values become factors of the shipped value, so the preset
// fits any vehicle; the shared car values are kept as they are.
export function captureFrom(vals, shipped, row, name) {
  const type = {}, car = {}
  for (const prop of TYPE_KEYS) {
    const key = `type.${row}.${prop}`
    if (!(key in vals) || !isNum(vals[key])) continue
    const base = shipped[key]
    if (!isNum(base)) continue
    if (base !== 0 && vals[key] / base > 0) type[prop] = { mul: r6(vals[key] / base) }
    else type[prop] = { set: r6(vals[key]) }
  }
  for (const prop of CAR_KEYS) {
    const key = `car.${prop}`
    if (key in vals && isNum(vals[key])) car[prop] = { set: r6(vals[key]) }
  }
  return { name: String(name || 'My preset').slice(0, 40), type, car }
}

export const isEmpty = p => !Object.keys(p.type || {}).length && !Object.keys(p.car || {}).length

// shared file <-> preset. A file from anywhere is cleaned: unknown fields are dropped (and counted), numbers are checked
// and clamped, and nothing but the driving fields can get through.
export const FORMAT = 'todms-driving-preset'
export function toFile(p) {
  return JSON.stringify({ format: FORMAT, version: 1, name: p.name, type: p.type || {}, car: p.car || {} }, null, 1) + '\n'
}
export function fromFile(text) {
  let o
  try { o = JSON.parse(text) } catch { return { error: 'Not a preset file' } }
  if (!o || typeof o !== 'object' || o.format !== FORMAT) return { error: 'Not a preset file' }
  const out = { name: String(o.name || 'Shared preset').replace(/[\u0000-\u001f]/g, '').trim().slice(0, 40) || 'Shared preset', type: {}, car: {} }
  let dropped = 0
  for (const [prop, spec] of Object.entries(o.type && typeof o.type === 'object' ? o.type : {})) {
    const f = FIELDS.type[prop]
    const kind = spec && ['mul', 'add', 'set'].find(k => isNum(spec[k]))
    if (!f || !kind) { dropped++; continue }
    let v = spec[kind]
    if (kind === 'mul') v = Math.min(20, Math.max(0, v))
    else if (kind === 'set') v = clampField('type', prop, v)
    else v = Math.min(f.hi, Math.max(-f.hi, v))
    out.type[prop] = { [kind]: r6(v) }
  }
  for (const [prop, spec] of Object.entries(o.car && typeof o.car === 'object' ? o.car : {})) {
    if (!FIELDS.car[prop] || !spec || !isNum(spec.set)) { dropped++; continue }
    out.car[prop] = { set: r6(clampField('car', prop, spec.set)) }
  }
  if (isEmpty(out)) return { error: 'Nothing in this file can be used' }
  return { preset: out, dropped }
}
