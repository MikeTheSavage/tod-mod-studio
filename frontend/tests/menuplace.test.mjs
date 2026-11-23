import test from 'node:test'
import assert from 'node:assert/strict'
import { menuPlace } from '../src/menuplace.js'

test('opens just under the button', () => {
  const p = menuPlace({ left: 100, right: 180, bottom: 40 }, 220, false, 1600, 960)
  assert.equal(p.position, 'fixed'); assert.equal(p.left, 100); assert.equal(p.top, 44)
})
test('right-aligned menus end at the button right edge', () => {
  const p = menuPlace({ left: 1500, right: 1580, bottom: 40 }, 300, true, 1600, 960)
  assert.equal(p.left, 1280)
})
test('stays inside the window on both sides', () => {
  assert.equal(menuPlace({ left: 1500, right: 1580, bottom: 40 }, 300, false, 1600, 960).left, 1292)
  assert.equal(menuPlace({ left: 0, right: 40, bottom: 40 }, 300, true, 1600, 960).left, 8)
})
test('max height fits the space below, never tiny', () => {
  assert.equal(menuPlace({ left: 0, right: 40, bottom: 40 }, 200, false, 1600, 960).maxHeight, 420)
  assert.equal(menuPlace({ left: 0, right: 40, bottom: 500 }, 200, false, 1100, 700).maxHeight, 188)
  assert.equal(menuPlace({ left: 0, right: 40, bottom: 680 }, 200, false, 1100, 700).maxHeight, 120)
})
