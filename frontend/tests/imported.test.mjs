import test from 'node:test'
import assert from 'node:assert/strict'
import { importedPalette, opForPlacing } from '../src/importedModels.js'

const project = { models: [
  { id: 'a', mode: 'new', name: 'Big Barrel', path: '/data/models/new/big_barrel.model', stats: { triangles: 120 } },
  { id: 'b', mode: 'replace', name: 'Crate', path: '/data/models/crate.model' }] }

test('palette lists only new models', () => {
  const l = importedPalette(project)
  assert.equal(l.length, 1)
  assert.equal(l[0].tris, 120)
})
test('placing op', () => {
  const m = importedPalette(project)[0]
  const op = opForPlacing(m, { entry: 'e', frag: 'f', node: 1 }, 'e', [1, 2, 3], null, 'u1')
  assert.equal(op.op, 'add')
  assert.equal(op.name, 'Big_Barrel')
  assert.equal(op.view.model, '/data/models/new/big_barrel.model')
  assert.deepEqual(op.rot, [0, 0, 0, 1])
})
