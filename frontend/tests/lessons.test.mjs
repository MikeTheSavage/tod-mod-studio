import test from 'node:test'
import assert from 'node:assert/strict'
import * as L from '../src/lessons.js'

const proj = (level = [], data = {}, view = null) => ({ level, data, view })
const add = n => Array.from({ length: n }, (_, i) => ({ op: 'add', uid: 'u' + i }))

test('a step with no condition is only finished by Next', () => {
  assert.equal(L.stepDone({ text: 'x' }, { screen: 'level' }), false)
  assert.equal(L.stepDone(null, {}), false)
})

test('screen steps', () => {
  assert.equal(L.stepDone({ done: { screen: 'level' } }, { screen: 'level' }), true)
  assert.equal(L.stepDone({ done: { screen: 'level' } }, { screen: 'home' }), false)
  assert.equal(L.stepDone({ done: { screen: ['data', 'mods'] } }, { screen: 'mods' }), true)
})

test('map step: a level is open', () => {
  assert.equal(L.stepDone({ done: { map: true } }, { project: proj([], {}, { map: 'map09' }) }), true)
  assert.equal(L.stepDone({ done: { map: true } }, { project: proj() }), false)
})

test('added objects count from where the step began', () => {
  const step = { done: { adds: 1 } }
  const base = L.snapshotOf(proj(add(2)))
  assert.deepEqual(base, { adds: 2, changes: 0 })
  assert.equal(L.stepDone(step, { project: proj(add(2)), base }), false)
  assert.equal(L.stepDone(step, { project: proj(add(3)), base }), true)
  assert.equal(L.stepDone(step, { project: proj([{ op: 'move' }, ...add(2)]), base }), false)       // a move is not an add
})

test('changed game values count from where the step began', () => {
  const step = { done: { changes: 1 } }
  const base = L.snapshotOf(proj([], { weapons: { a: 1 } }))
  assert.equal(base.changes, 1)
  assert.equal(L.stepDone(step, { project: proj([], { weapons: { a: 1 } }), base }), false)
  assert.equal(L.stepDone(step, { project: proj([], { weapons: { a: 1, b: 2 } }), base }), true)
  assert.equal(L.stepDone(step, { project: proj([], { weapons: { a: 1 }, camera: { c: 3 } }), base }), true)
})

test('test step and screen text steps', () => {
  assert.equal(L.stepDone({ done: { test: true } }, { test: true }), true)
  assert.equal(L.stepDone({ done: { test: true } }, { test: false }), false)
  const textIn = (sel, t) => sel === '.tb button' && 'A race in the yard (sample)'.toLowerCase().includes(t)
  assert.equal(L.stepDone({ done: { textIn: ['.tb button', 'race in the yard'] } }, { textIn }), true)
  assert.equal(L.stepDone({ done: { textIn: ['.tb button', 'nothing'] } }, { textIn }), false)
  assert.equal(L.stepDone({ done: { dom: '.x' } }, { exists: s => s === '.x' }), true)
  assert.equal(L.stepDone({ done: { dom: '.x' } }, {}), false)
})

test('all / any combine conditions', () => {
  const st = { screen: 'level', test: false }
  assert.equal(L.condDone({ all: [{ screen: 'level' }, { test: true }] }, st), false)
  assert.equal(L.condDone({ any: [{ screen: 'level' }, { test: true }] }, st), true)
})

test('the shipped lessons are well formed', () => {
  assert.ok(L.LESSONS.length >= 2 && L.LESSONS.length <= 4)
  const ids = new Set()
  for (const l of L.LESSONS) {
    assert.ok(!ids.has(l.id)); ids.add(l.id)
    assert.ok(l.title && l.steps.length >= 3)
    for (const s of l.steps) {
      assert.ok(s.text && s.text.length < 90, 'one short line: ' + s.text)
      assert.ok(!/\n/.test(s.text))
    }
    assert.ok(!l.steps[l.steps.length - 1].done, 'the last step is an information step')
  }
  assert.equal(L.lessonById('crate').id, 'crate')
  assert.equal(L.lessonById('nope'), undefined)
})
