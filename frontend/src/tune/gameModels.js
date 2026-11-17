// Which game model stands for a weapon or a vehicle type, and a hook that fetches the extracted meshes.
import { useEffect, useState } from 'react'
import { post, runJob } from '../api.js'
import { loadModel } from '../models.js'

const W = '/data/models/collectables/weapons/', V = '/data/models/vehicles/'

// "Beretta (Gun_Light)" -> the weapon model folder
const WEAPON_MODEL = {
  Beretta: 'weapon_gun_light', Magnum: 'weapon_gun_heavy', Marlin: 'weapon_rifle_heavy', Winchester: 'weapon_rifle_light',
  Benelli: 'weapon_shotgun_combat', Hudson: 'weapon_shotgun_sawedoff', Mac10: 'weapon_sub_automatic_light', MP5: 'weapon_sub_automatic_heavy',
  AK47: 'weapon_automatic_heavy', M16: 'weapon_automatic_light', Gatling: 'weapon_automatic_heavy', HandGrenade: 'weapon_thrown_grenade',
  GrenadeLauncher: 'weapon_eksplosiv_grenade_launcher', RocketLauncher: 'weapon_eksplosiv_rocket_launcher', Machete: 'weapon_melee_machete',
  GoldenGun: 'weapon_gun_golden', MariachiGuitar: 'weapon_mariachi', Molotov: 'weapon_thrown_molotov', Dynamite: 'weapon_thrown_dynamite_bundle',
}
export function weaponModelPath(group) {
  const gun = String(group || '').split(' ')[0]
  const f = WEAPON_MODEL[gun]
  return f ? `${W}${f}/${f}.model` : null
}

// "Vehicle type: Sedan" -> the car model
const VEHICLE_MODEL = {
  Sedan: 'sedan_74_standard/vehicle', SedanRusty: 'sedan_74_standard/vehicle', Taxi: 'sedan_modernstandard/vehicle', PoliceCar: 'sedan_modernstandard/vehicle',
  ModernSedan: 'sedan_modernstandard/vehicle', '4x4Pickup': 'pickup4x4/vehicle', BigTruck: 'bigtruck/vehicle', BigTruckFlatnose: 'bigtruck/vehicle',
  BigTruckMoralez: 'bigtruck/vehicle', Truck: 'bigtruck/vehicle', VanUrban: 'van_urban/vehicle', VanHeavy: 'van_urban/vehicle', VanAngel: 'van_urban/vehicle',
  StationWagon: 'stationwagon/vehicle', Conquistador: 'conquistador/vehicle', ElCamino: 'elcamino_lostorosrose/vehicle', Pickup_Truck: 'pickuptruck/vehicle',
  Pickup: 'pickuptruck/vehicle', '57Pickup': 'pickuptruck/vehicle', Forklift: 'forklift/vehicle', Dirtbike: 'dirtbike/bike',
}
export function vehicleModelPath(group) {
  const t = String(group || '').replace(/^Vehicle type: /, '')
  const f = VEHICLE_MODEL[t]
  return f ? V + f + '.model' : null
}
export const RAM_MODEL = '/data/characters/ram/ram.model'

const recs = new Map()           // path -> rec | 'loading'
const protos = new Map()         // path -> Promise<{render, collision}>

// Fetch the meshes of some game models once; the answer is shared by every preview.
export function useGameModels(paths) {
  const key = paths.filter(Boolean).join('|')
  const [, bump] = useState(0)
  useEffect(() => {
    const need = key.split('|').filter(p => p && !recs.has(p))
    if (!need.length) return
    need.forEach(p => recs.set(p, 'loading'))
    let live = true
    post('/api/models/find', { names: need }).then(r => {
      need.forEach(p => recs.set(p, r.models?.[p] || { missing: true }))
      if (live) bump(x => x + 1)
    }).catch(() => { need.forEach(p => recs.set(p, { missing: true })); if (live) bump(x => x + 1) })
    return () => { live = false }
  }, [key])
  const out = {}
  key.split('|').forEach(p => { const r = recs.get(p); if (p && r && r !== 'loading') out[p] = r })
  return out
}

// the shared render/collision prototypes of a model (clone per use)
export function prototypeOf(path, rec) {
  if (!rec || rec.missing || !rec.url) return Promise.resolve(null)
  if (!protos.has(path)) protos.set(path, loadModel(path, rec))
  return protos.get(path)
}

// Ram with his move clips (built from the game once, then cached on disk by the app)
let ramJob = null
export function ramMoves() {
  if (!ramJob) ramJob = runJob('/api/ram/moves', {}).catch(e => { ramJob = null; throw e })
  return ramJob
}
