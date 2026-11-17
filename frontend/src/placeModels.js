// Which game model shows an added pickup, weapon, vehicle or enemy (the live preview), picked from its Kind.
const G = '/data/models/collectables/goodies/', W = '/data/models/collectables/weapons/', V = '/data/models/vehicles/'
const GOODIE = [['medium_health', 'pickup_oneshot_health_small'], ['large_health', 'pickup_oneshot_health_big'], ['permhealth', 'pickup_permanent_health'],
  ['combotime', 'pickup_oneshot_timeextend'], ['godmode', 'pickup_oneshot_armour'], ['medium', 'pickup_mediumracebonus'], ['large', 'pickup_largeracebonus'],
  ['medkit', 'pickup_locomove_medkit'], ['rewind', 'pickup_locomove_rewind'], ['golden', 'pickup_locomove_goldengun'], ['sombrero', 'pickup_locomove_sombrero'],
  ['mariachi', 'pickup_locomove_mariachi'], ['pinata', 'pickup_locomove_pinata'], ['tornado', 'pickup_locomove_tornado'], ['wrestler', 'pickup_locomove_wrestler'],
  ['toro', 'pickup_locomove_toro'], ['gun', 'pickup_permanent_gunskill'], ['stamina', 'pickup_permanent_stamina'], ['armour', 'pickup_oneshot_armour'],
  ['timestop', 'pickup_oneshot_timestop'], ['dead', 'pickup_dayofthedead']]
const WEAPON = [['beretta', 'weapon_gun_light'], ['magnum', 'weapon_gun_heavy'], ['marlin', 'weapon_rifle_light'], ['winchester', 'weapon_rifle_heavy'],
  ['benelli', 'weapon_shotgun_combat'], ['hudson', 'weapon_shotgun_sawedoff'], ['mac10', 'weapon_sub_automatic_light'], ['mp5', 'weapon_sub_automatic_heavy'],
  ['ak47', 'weapon_automatic_light'], ['m16', 'weapon_automatic_light'], ['gatling', 'weapon_automatic_heavy'], ['handgrenade', 'weapon_thrown_grenade'],
  ['grenadelauncher', 'weapon_eksplosiv_grenade_launcher'], ['rocket', 'weapon_eksplosiv_rocket_launcher'], ['machete', 'weapon_melee_machete'],
  ['golden', 'weapon_gun_golden'], ['mariachi', 'weapon_mariachi'], ['molotov', 'weapon_thrown_molotov'], ['dyna', 'weapon_thrown_dynamite_bundle'],
  ['bat', 'weapon_melee_baseballbat'], ['shovel', 'weapon_melee_shovel'], ['rake', 'weapon_melee_rake'], ['iron', 'weapon_melee_ironbar']]
const VEHICLE = [['dirtbike', 'dirtbike/bike'], ['forklift', 'forklift/vehicle'], ['elcamino', 'elcamino_lostorosrose/vehicle'], ['4x4', 'pickup4x4/vehicle'],
  ['pickup_truck', 'pickuptruck/vehicle'], ['57pickup', 'pickuptruck/vehicle'], ['pickup', 'pickuptruck/vehicle'], ['bigtruck', 'bigtruck/vehicle'], ['truck', 'bigtruck/vehicle'],
  ['van', 'van_urban/vehicle'], ['station', 'stationwagon/vehicle'], ['modern', 'sedan_modernstandard/vehicle'], ['taxi', 'sedan_modernstandard/vehicle'],
  ['police', 'sedan_modernstandard/vehicle'], ['conquista', 'conquistador/vehicle'], ['sedan', 'sedan_74_standard/vehicle']]

const pick = (table, name, dflt) => (table.find(([k]) => name.includes(k)) || [0, dflt])[1]

// -> lower-case model path, or null when the kind has no model (boxes)
export function modelPathFor(cat, sub, enums) {
  const nm = k => String((enums?.[k] || {})[sub?.[k]] ?? '').toLowerCase().replace(/[\s-]/g, '')
  if (cat === 'pickup') return G + pick(GOODIE, nm('GoodieSubType'), 'pickup') + '.model'
  if (cat === 'weapon') { const f = pick(WEAPON, nm('WeaponSubType'), 'default_weapon'); return W + f + '/' + f + '.model' }
  if (cat === 'vehicle') return V + pick(VEHICLE, nm('VehicleSubType'), 'sedan_74_standard/vehicle') + '.model'
  if (cat === 'character') return '/data/characters/gangster/gangster.model'
  return null
}
