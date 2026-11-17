// node --test tests   (pure editing helpers: no browser, no backend)
import test from 'node:test'
import assert from 'node:assert/strict'
import * as E from '../src/editing.js'
import { buildView } from '../src/view.js'
import { yawDeg } from '../src/coords.js'
import { nearestInDirection } from '../src/selection.js'

const ent = (id, pos, extra = {}) => ({ id, pos, rot: [0, 0, 0, 1], ed: true, target: { entry: 'e', frag: 'f', node: '0x0000000' + id }, cat: 'pickup', type: 'goodie_placeholder', ...extra })
const near = (a, b, d = 1e-6) => assert.ok(Math.abs(a - b) < d, `${a} vs ${b}`)

test('group translate and rotate keep the shape', () => {
  const g = [ent(1, [0, 0, 0]), ent(2, [4, 0, 0])]
  const r = E.rotateMoves(g, [2, 0, 0], 90)
  near(Math.hypot(r[0].pos[0] - r[1].pos[0], r[0].pos[2] - r[1].pos[2]), 4, 1e-9)
  near(yawDeg(r[0].rot), 90, 1e-4)
  const t = E.translateMoves(g, [1, 2, 3])
  assert.deepEqual(t[1].pos, [5, 2, 3])
})

test('moveMany is one op per object and replaces an earlier move', () => {
  const g = [ent(1, [0, 0, 0]), ent(2, [4, 0, 0])]
  let ops = E.moveMany([], E.translateMoves(g, [1, 0, 0]))
  assert.equal(ops.length, 2)
  ops = E.moveMany(ops, E.translateMoves([{ ...g[0], pos: [1, 0, 0] }], [1, 0, 0]))
  assert.equal(ops.length, 2)
  assert.deepEqual(ops.find(o => o.node === g[0].target.node).pos, [2, 0, 0])
})

test('align and distribute', () => {
  const g = [ent(1, [0, 0, 0]), ent(2, [10, 5, 3]), ent(3, [4, 9, -2])]
  const a = E.alignMoves(g, 'x', 'min')
  assert.ok(a.every(m => m.pos[0] === 0))
  const c = E.alignMoves(g, 'y', 'center')
  assert.ok(c.every(m => m.pos[1] === 4.5))
  const d = E.distributeMoves(g, 'x')
  assert.equal(d.length, 1)
  assert.equal(d[0].e.id, 3)
  assert.equal(d[0].pos[0], 5)
  assert.deepEqual(E.distributeMoves(g.slice(0, 2), 'x'), [])
})

test('snapping', () => {
  assert.equal(E.snapNum(3.7, 0.5), 3.5)
  assert.equal(E.snapNum(3.7, 0), 3.7)
  assert.deepEqual(E.snapXZ([1.2, 9, 2.6], 1), [1, 9, 3])
  assert.equal(E.snapYaw(52, 15), 45)
})

test('drop to ground only moves what has ground below', () => {
  const g = [ent(1, [0, 5, 0]), ent(2, [9, 5, 9]), ent(3, [1, 2, 1])]
  const m = E.dropMoves(g, (x, z) => (x === 9 ? null : 2))
  assert.equal(m.length, 1)
  assert.deepEqual(m[0].pos, [0, 2, 0])
})

test('scatter is deterministic with a seed, inside the disc and keeps its gap', () => {
  const run = () => E.scatterStamp({ center: [10, 0, 10], radius: 6, density: 0.2, gap: 1, rand: E.rng(7) })
  const a = run(), b = run()
  assert.deepEqual(a, b)
  assert.ok(a.length > 5 && a.length <= 23)
  for (const s of a) assert.ok(Math.hypot(s.pos[0] - 10, s.pos[2] - 10) <= 6 + 1e-9)
  for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) assert.ok(Math.hypot(a[i].pos[0] - a[j].pos[0], a[i].pos[2] - a[j].pos[2]) >= 1)
  const none = E.scatterStamp({ center: [0, 0, 0], radius: 5, density: 0, rand: E.rng(1) })
  assert.equal(none.length, 0)
  const capped = E.scatterStamp({ center: [0, 0, 0], radius: 100, density: 5, rand: E.rng(1), max: 50 })
  assert.ok(capped.length <= 50)
  for (const s of E.scatterStamp({ center: [0, 0, 0], radius: 5, density: 1, scale: [0.5, 2], rand: E.rng(3) })) assert.ok(s.scale >= 0.5 && s.scale <= 2)
})

test('prefab capture and stamp keep the layout, turn with the stamp and each object is a new add op', () => {
  const tpl = { entry: 'e', frag: 'f', node: '0x00000001' }
  const g = [ent(1, [100, 3, 200], { size: [2, 2, 2], cat: 'trigger' }), ent(2, [104, 3, 200], { cat: 'weapon' })]
  const pf = E.prefabFromEntities(g, 'Pair')
  assert.equal(pf.items.length, 2)
  assert.deepEqual(pf.items[0].dpos, [-2, 0, 0])
  const ops = E.stampOps(pf, [0, 10, 0], 0, () => 'blk')
  assert.equal(ops.length, 2)
  assert.deepEqual(ops[1].pos, [2, 10, 0])
  assert.ok(ops.every(o => o.op === 'add' && o.entry === 'blk' && o.uid))
  assert.equal(new Set(ops.map(o => o.uid)).size, 2)
  const turned = E.stampOps(pf, [0, 0, 0], 90, () => 'blk')
  near(turned[1].pos[0], 0, 1e-3); near(Math.abs(turned[1].pos[2]), 2, 1e-3)
  assert.deepEqual(E.stampOps(pf, [0, 0, 0], 0, () => null), [])
  assert.deepEqual(ops[0].set, { width: 2, height: 2, length: 2 })
  void tpl
})

test('scaling a stamped box scales its size', () => {
  const pf = E.prefabFromEntities([ent(1, [0, 0, 0], { size: [2, 3, 4], cat: 'wall' })], 'W')
  const [o] = E.stampOps(pf, [0, 0, 0], 0, () => 'b', { scale: 2 })
  assert.deepEqual(o.set, { width: 4, height: 6, length: 8 })
  assert.deepEqual(o.view.size, [4, 6, 8])
})

test('find and replace changes added objects and base objects once', () => {
  const bundle = { levels: [{ key: 'k', entry: 'blk', fragments: [{ k: 1, name: 'f' }], entities: [
    { id: 'a', k: 1, node: '0x0000000a', pos: [0, 0, 0], rot: [0, 0, 0, 1], cat: 'weapon', type: 'weapon_placeholder', ed: true, sub: { WeaponSubType: 3 } },
    { id: 'b', k: 1, node: '0x0000000b', pos: [1, 0, 0], rot: [0, 0, 0, 1], cat: 'weapon', type: 'weapon_placeholder', ed: true, sub: { WeaponSubType: 4 } }], links: [] }] }
  const add = { op: 'add', uid: 'u1', entry: 'blk', template: { entry: 'blk', frag: 'f', node: '0x0000000a' }, name: 'W_u1', pos: [2, 0, 0], rot: [0, 0, 0, 1], set: { WeaponSubType: 3 }, view: { cat: 'weapon', type: 'weapon_placeholder', sub: { WeaponSubType: 3 } } }
  const view = buildView(bundle, [add])
  const counts = E.kindCounts(view, 'WeaponSubType')
  assert.equal(counts.get(3), 2)
  const r = E.replaceKind([add], view, 'WeaponSubType', 3, 9)
  assert.equal(r.count, 2)
  assert.equal(r.ops.filter(o => o.op === 'add')[0].set.WeaponSubType, 9)
  assert.ok(r.ops.some(o => o.op === 'set' && o.prop === 'WeaponSubType' && o.value === 9))
  const v2 = buildView(bundle, r.ops)
  assert.equal(E.kindCounts(v2, 'WeaponSubType').get(9), 2)
  assert.equal(E.replaceKind(r.ops, v2, 'WeaponSubType', 3, 9).count, 0)
})

test('layers, bookmarks and notes live in project.editor only', () => {
  let p = { level: [], data: {} }
  p = E.addLayer(p, 'Props')
  const id = E.layersOf(p)[0].id
  p = E.patchLayer(p, id, { hidden: true })
  assert.equal(E.layersOf(p)[0].hidden, true)
  const e = ent(1, [0, 0, 0])
  p = E.assignLayer(p, [e], id)
  assert.equal(E.layerOfEntity(p, e).name, 'Props')
  p = E.removeLayer(p, id)
  assert.equal(E.layerOfEntity(p, e), undefined)
  p = E.addBookmark(p, 'Gate', [1, 2, 3], [0, 0, 0])
  p = E.addNote(p, [5, 1, 5], 'fix')
  assert.equal(E.bookmarksOf(p)[0].name, 'Gate')
  assert.equal(E.notesOf(p)[0].text, 'fix')
  p = E.removeNote(p, E.notesOf(p)[0].id)
  assert.equal(E.notesOf(p).length, 0)
  assert.deepEqual(p.level, [])
})

test('a d-pad step picks the nearest object in that direction (north is up)', () => {
  const items = [{ id: 'a', pos: [0, 0, 0] }, { id: 'b', pos: [10, 0, 1] }, { id: 'c', pos: [1, 0, 8] }, { id: 'd', pos: [-8, 0, 0] }, { id: 'e', pos: [0, 0, -5] }]
  assert.equal(nearestInDirection(items, 'a', 'right'), 'b')
  assert.equal(nearestInDirection(items, 'a', 'up'), 'c')
  assert.equal(nearestInDirection(items, 'a', 'left'), 'd')
  assert.equal(nearestInDirection(items, 'a', 'down'), 'e')
  assert.equal(nearestInDirection(items, 'b', 'right'), 'b')
})

test('key combos are written the same way they are matched', async () => {
  globalThis.document ??= { querySelector: () => null }
  globalThis.localStorage ??= { getItem: () => null, setItem: () => {} }
  const { comboOf, prettyCombo } = await import('../src/commands.js')
  assert.equal(comboOf({ key: 'K', ctrlKey: true }), 'ctrl+k')
  assert.equal(comboOf({ key: 'Delete' }), 'delete')
  assert.equal(comboOf({ key: 'ArrowUp', shiftKey: true }), 'shift+up')
  assert.equal(comboOf({ key: 'Control', ctrlKey: true }), '')
  assert.equal(prettyCombo('ctrl+shift+p'), 'Ctrl+Shift+P')
})
