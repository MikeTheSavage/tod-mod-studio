// Plain-English names for the game-data fields (the engine names stay as tooltips).
const MAP = {
  ClipSize: 'Clip size', ReloadTime: 'Reload time', FireRate: 'Fire rate (auto)', ManualFireRate: 'Fire rate (tap)', BulletsPerShot: 'Pellets per shot',
  ShortRangeDamage: 'Damage, close range', MediumRangeDamage: 'Damage, medium range', LongRangeDamage: 'Damage, long range',
  ShortRange: 'Close range (m)', MediumRange: 'Medium range (m)', MaxRange: 'Longest shot (m)', SpreadMin: 'Spread, steady', SpreadMax: 'Spread, widest',
  SpreadInc: 'Spread growth', SpreadEnemy: 'Spread, enemies', AimFocus: 'Aim focus', speed: 'Bullet speed', 'bullet speed': 'Bullet speed (m/s)',
  Engine_SoundID: 'Engine sound', Health: 'Health', CollisionDamage: 'Crash damage', ExplosionDamage: 'Explosion damage', ExplosionRange: 'Explosion radius',
  Player_Flee_time: 'Driver flee time', spring_k: 'Suspension spring', spring_damping: 'Suspension damping', stiffness: 'Suspension travel', drag_coeff: 'Drag (top speed)',
  Mass: 'Mass', cornering_stiffness: 'Cornering grip', lateral_slide_speed: 'Slide start speed', front_slide_factor: 'Front slide', brake_slide_factor: 'Brake slide',
  brake_front_slide_factor: 'Brake slide, front', slide_factor: 'Slide limit', control_speed: 'Slide recovery', crash_angular_friction: 'Crash spin friction',
  crash_linear_friction: 'Crash friction', spinning_linear_friction: 'Spin friction', spinning_angular_friction: 'Spin turn friction', handbrake_boost: 'Handbrake spin boost',
  time_to_slide_factor: 'Spin-out threshold', collision_mass: 'Crash mass', BrakeForce: 'Brake force', PointValue: 'Kill points', InflictorValue: 'Inflictor points',
  ComboStringValue: 'Combo text value', Inertial_Length: 'Inertia length', Inertial_Width: 'Inertia width', Inertial_Height: 'Inertia height', WheelRadius: 'Wheel radius',
  MaxAngle: 'Camera angle limit', AngleEaseInSpeed: 'Camera angle ease', MaxDistance: 'Camera distance limit', DistanceMoveOutSpeed: 'Camera pull-out speed',
  DistanceMoveInSpeed: 'Camera pull-in speed', DistanceZFactor: 'Camera depth factor', Vehicle_Length: 'AI length', Vehicle_Width: 'AI width', Shadow_opacity: 'Shadow strength',
  max_engine_force: 'Engine force', max_reverse_force: 'Reverse force', rolling_res: 'Rolling resistance', max_turn: 'Steering lock', turn_rate: 'Steering speed',
  slide_angle: 'Slide angle', powerslide_minimum_turnrate: 'Powerslide steering', static_brake_resistance: 'Braking stop speed', rolling_static_threshold: 'Coasting stop speed',
  burn_out_speed: 'Burnout speed', sideways_slide_resistance: 'Sideways slide, braking', standard_sideways_slide_resistance: 'Sideways slide', sideways_static_resistance: 'Slide end speed',
  standard_sideways_static_resistance: 'Sideways grip', standard_ground_clearance: 'Ground clearance', anchor_ground_clearance: 'Anchor clearance', self_righting_speed: 'Self-righting speed',
  wheelie_max_angle: 'Wheelie limit', wheelie_speed: 'Wheelie rate', jump_minimum_time: 'Jump reset time', cant_move_reaction_time: 'Stuck timer', engine_res: 'Engine resistance',
  fork_speed: 'Fork speed', cornering_ref_speed: 'Cornering reference speed',
  slowmo_cost_per_s: 'Slow motion cost per second', gain_standing: 'Stamina regained standing', gain_running: 'Stamina regained running', cost_sprinting: 'Sprint cost',
  health_after: 'Health after rewind', possession_time: 'Hat bonus time', vision_angle: 'Auto-aim vision cone', lock_angle: 'Auto-aim lock cone', shoot_angle: 'Shoot cone',
  turn_speed: 'Turn speed', normal_motion_blur: 'Motion blur, normal', slomo_motion_blur: 'Motion blur, slow motion', time_limit: 'Combo time', fast_kill_time_limit: 'Fast-kill window',
  MediumHealth: 'Medium health pickup', LargeHealth: 'Large health pickup', GodTime: 'God mode time', 'move back': 'Move back', 'move up': 'Move up',
  'pitch (deg, empty = keep)': 'Pitch (degrees)', 'far clip (m)': 'Draw distance (m)', 'move back (all vehicles)': 'Move back, all vehicles', 'move up (all vehicles)': 'Move up, all vehicles',
}
const SUFFIX = { FirstAward: '1st use', SecondAward: '2nd use', ThirdAward: '3rd use', FourthAward: '4th use', FifthAward: '5th use', KillsNeeded: 'Kills needed',
  ComboBonus: 'Combo bonus', MoveBonus: 'Move bonus', GoodieAward: 'Pickup awarded', goodie: 'Pickup given', PointValue: 'Kill points' }
const words = s => s.replace(/_/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/\s+/g, ' ').trim()
const cap = s => s.charAt(0).toUpperCase() + s.slice(1)

export function nice(label) {
  if (MAP[label]) return MAP[label]
  const m = /^(max|start)\.(.+)$/.exec(label)
  if (m) return cap(words(m[2])) + (m[1] === 'max' ? ', most charges' : ', at new game')
  const m2 = /^(Default_max_clips|Default_clips)_(.+)$/.exec(label)
  if (m2) return (m2[1] === 'Default_clips' ? 'Starting clips, ' : 'Most clips, ') + words(m2[2])
  const dm = /^(.*)Drop(From|To)$/.exec(label)
  if (dm) return cap(words(dm[1])) + ' drop, ' + (dm[2] === 'From' ? 'from' : 'to')
  if (label.includes('.')) {
    const i = label.lastIndexOf('.')
    const head = label.slice(0, i), tail = label.slice(i + 1)
    return cap(words(head.replace(/\//g, ' > '))) + ': ' + (SUFFIX[tail] || words(tail).toLowerCase())
  }
  return cap(words(label))
}
