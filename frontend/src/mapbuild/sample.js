// The sample map of the proof: a hill, a bridge over a pond, scatter, a look preset, two sections and a loader.
export const SAMPLE = {
  name: 'Sample', source: 'map10_runawaytrain', arrival: { pos: [-40, 3, -30], orient: [0, 0, 0, 1] }, return: { pos: [40, 3, -30], size: [8, 4, 2], orient: [0, 0, 0, 1] },
  terrain: { cell: 2, size: [80, 80], base: 0, noise: { seed: 3, amp: 1.2, scale: 40, octaves: 3 },
    strokes: [{ tool: 'raise', pos: [-30, 20], radius: 34, strength: 9, falloff: 'smooth' }, { tool: 'flatten', pos: [0, -30], radius: 14, strength: 1, height: 1, falloff: 'smooth' }] },
  ground_paint: { palette: ['grass', 'dirt', 'rock'], default: 'grass', rock_slope: 0.45, strokes: [{ material: 'dirt', pos: [20, 18], radius: 14 }],
    surface_strokes: [{ surface: 'Stone', pos: [-30, 20], radius: 9 }] },
  roads: [{ id: 'main', points: [[-70, -30], [-30, -30], [10, -10, 8], [40, 20, 8], [70, 30]], width: 8, lanes: 2, kerb: true, elevated: true, traffic: true }],
  water: [{ id: 'pond', circle: [30, -40, 11], depth: 2, bank: 5, rule: 'reset' }],
  edges: [{ id: 'rim', kind: 'invisible', rect: [-76, -76, 76, 76], height: 6, kill: { below: -20, respawn: [-40, -30] } }],
  scatter: [{ id: 'trees', circle: [-45, 40, 24], items: [{ kind: 'tree', weight: 8 }, { kind: 'bush', weight: 2 }], density: 0.008, seed: 4, slope_max: 0.5, min_dist: 3, variants: 3, max: 400 }],
  look: { preset: 'clear_day' },
  blockout: [{ id: 'box1', pos: [-5, 0, 30], size: [10, 5, 8], yaw: 20 }],
  sections_plan: { sections: [{ id: 'sec1', name: 'West', rect: [-80, -80, 0, 80] }, { id: 'sec2', name: 'East', rect: [0, -80, 80, 80] }],
    loaders: [{ id: 'loader1', a: 'sec1', b: 'sec2', pos: [0, 2, -30], size: [4, 6, 14] }], path: [[-60, -30], [60, -30]] },
}
