// The shared name table (todms/names.py): readable names for characters, behaviours, sides, weapons, pickups and vehicles.
// Loaded once; `useNames()` re-renders a component when it arrives. Lookups before that return the plain number or raw text.
import { useEffect, useState } from 'react'
import { get } from './api.js'

let table = null, pending = null
const subs = new Set()

export function loadNames() {
  if (table) return Promise.resolve(table)
  if (!pending) pending = get('/api/names').then(t => { table = t; subs.forEach(f => f(t)); return t }).catch(() => { pending = null; return null })
  return pending
}
export function useNames() {
  const [t, setT] = useState(table)
  useEffect(() => { if (table) { setT(table); return } subs.add(setT); loadNames(); return () => subs.delete(setT) }, [])
  return t
}
export const namesNow = () => table

const prettyRaw = s => {
  const v = String(s ?? '').replace(/\s*->.*$/, '').replace(/_/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/\s+/g, ' ').trim()
  return v ? v[0].toUpperCase() + v.slice(1).toLowerCase() : v
}
export { prettyRaw }

export const charRow = n => table?.characters?.find(c => c.id === Number(n)) || null
export const charName = n => charRow(n)?.name ?? (n == null ? '' : 'Character ' + n)
export const aiName = n => table?.ai?.[n] ?? (n == null ? '' : 'Behaviour ' + n)
export const sideName = n => table?.factions?.[n] ?? (n == null ? '' : 'Side ' + n)
export const weaponName = n => table?.weapons?.[n] ?? (n == null ? '' : 'Weapon ' + n)
export const goodieName = n => table?.goodies?.[n] ?? (n == null ? '' : 'Pickup ' + n)
export const vehicleName = n => table?.vehicles?.[n] ?? (n == null ? '' : 'Vehicle ' + n)
export const lookName = (model, set) => charRow(model)?.looks?.find(l => l.id === Number(set))?.name ?? 'Look ' + (Number(set || 0) + 1)

// readable name of a placed thing from its kind and sub-type numbers; null when the thing has none (a box, a wall ...)
export function kindName(cat, sub) {
  if (!sub || !table) return null
  if (cat === 'character' && sub.Model != null) return charName(sub.Model)
  if (cat === 'vehicle' && sub.VehicleSubType != null) return vehicleName(sub.VehicleSubType)
  if (cat === 'weapon' && sub.WeaponSubType != null) return weaponName(sub.WeaponSubType)
  if (cat === 'pickup' && sub.GoodieSubType != null) return goodieName(sub.GoodieSubType)
  return null
}
// the text of a list row: the readable name first; the designer's own name (when it is not just the kind) goes after it
export function entityTitle(e, fallback) {
  const k = kindName(e.cat, e.sub)
  const own = e.name || ''
  if (!k) return own || fallback
  if (!own || own.toLowerCase().startsWith('todms_') || own.toLowerCase().startsWith('character_placeholder')) return k
  return k + ' · ' + own.replace(/^[A-Za-z]+\d*_/, '')
}
export const entityTip = e => [e.name, e.sub?.Model != null ? 'model ' + e.sub.Model : '', e.sub?.VehicleSubType != null ? 'vehicle ' + e.sub.VehicleSubType : '',
  e.sub?.WeaponSubType != null ? 'weapon ' + e.sub.WeaponSubType : '', e.sub?.GoodieSubType != null ? 'pickup ' + e.sub.GoodieSubType : '', e.node].filter(Boolean).join(' · ')
