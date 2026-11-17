import test from 'node:test'
import assert from 'node:assert/strict'
import * as U from '../src/uiprefs.js'

const AREAS = [
  { id: 'world', screens: [['level', 'Level editor'], ['routes', 'Routes'], ['sections', 'Sections'], ['collision', 'Collision'], ['missions', 'Mission logic']] },
  { id: 'create', screens: [['mtpl', 'Mission templates'], ['newmaps', 'New maps']] },
  { id: 'debug', screens: [['debug', 'Test run'], ['bisect', 'Find a bad mod'], ['support', 'Support']] },
]

test('theme: Follow Windows is the default and resolves from the system', () => {
  assert.equal(U.DEFAULT_PREFS.theme, 'system')
  assert.equal(U.resolveTheme('system', true), 'dark')
  assert.equal(U.resolveTheme('system', false), 'light')
  assert.equal(U.resolveTheme('light', true), 'light')
  assert.equal(U.resolveTheme('dark', false), 'dark')
  assert.equal(U.resolveTheme('contrast', false), 'contrast')
  assert.equal(U.baseTheme('contrast'), 'dark')
  assert.equal(U.baseTheme('light'), 'light')
})

test('scale: 90 to 150 percent in steps of 5, anything else is repaired', () => {
  assert.equal(U.clampScale(125), 125)
  assert.equal(U.clampScale(50), 90)
  assert.equal(U.clampScale(400), 150)
  assert.equal(U.clampScale(112), 110)
  assert.equal(U.clampScale('abc'), 100)
  assert.equal(U.clampScale(undefined), 100)
})

test('text size: snaps to the nearest of the four sizes', () => {
  assert.deepEqual(U.TEXT_SIZES, [90, 100, 115, 130])
  assert.equal(U.clampText(120), 115)
  assert.equal(U.clampText(1000), 130)
  assert.equal(U.clampText('x'), 100)
})

test('normalize: a complete valid set from anything', () => {
  const d = U.normalize(null)
  assert.deepEqual(d, U.DEFAULT_PREFS)
  const p = U.normalize({ theme: 'bogus', scale: 133, text: 99, motion: 'x', cb: 'yes', mode: 'beginner', lang: '' })
  assert.equal(p.theme, 'system'); assert.equal(p.scale, 135); assert.equal(p.text, 100); assert.equal(p.motion, 'system')
  assert.equal(p.cb, false); assert.equal(p.mode, 'beginner'); assert.equal(p.lang, 'en')
  assert.equal(U.normalize({ cb: true }).cb, true)
})

test('reduced motion follows Windows unless the toggle says otherwise', () => {
  assert.equal(U.motionReduced('system', true), true)
  assert.equal(U.motionReduced('system', false), false)
  assert.equal(U.motionReduced('reduce', false), true)
  assert.equal(U.motionReduced('full', true), false)
})

test('beginner mode hides the rarely used screens, advanced shows all', () => {
  const ids = a => a.map(s => s[0])
  const world = AREAS[0].screens
  assert.deepEqual(ids(U.visibleScreens(world, 'beginner', 'level')), ['level'])
  assert.deepEqual(ids(U.visibleScreens(world, 'advanced', 'level')), ids(world))
  // the screen you are on never disappears
  assert.deepEqual(ids(U.visibleScreens(world, 'beginner', 'collision')), ['level', 'collision'])
  assert.deepEqual(ids(U.visibleScreens(AREAS[2].screens, 'beginner', 'debug')), ['debug', 'support'])
  assert.equal(U.screenVisible('bisect', 'beginner'), false)
  assert.equal(U.screenVisible('mtpl', 'beginner'), true)
  for (const s of ['missions', 'sections', 'collision', 'routes', 'bisect']) assert.ok(U.ADVANCED_SCREENS.includes(s), s)
})

test('beginner mode keeps every area that still has a screen', () => {
  const only = [{ id: 'adv', screens: [['routes', 'Routes'], ['collision', 'Collision']] }, ...AREAS]
  assert.deepEqual(U.visibleAreas(only, 'beginner', 'home').map(a => a.id), ['world', 'create', 'debug'])
  assert.deepEqual(U.visibleAreas(only, 'beginner', 'routes').map(a => a.id), ['adv', 'world', 'create', 'debug'])
  assert.equal(U.visibleAreas(only, 'advanced', 'home').length, 4)
})

test('address overrides for screenshots and links', () => {
  assert.deepEqual(U.fromQuery('?theme=contrast&scale=125&text=130&motion=reduce&cb=1&mode=beginner'),
    { theme: 'contrast', scale: 125, text: 130, motion: 'reduce', cb: true, mode: 'beginner' })
  assert.deepEqual(U.fromQuery('?theme=nope&scale=abc'), { scale: 100 })
  assert.deepEqual(U.fromQuery(''), {})
})

test('document state: attributes the style sheet reads, scale as a factor', () => {
  const st = U.documentState(U.normalize({ theme: 'system', scale: 125, text: 115, cb: true, mode: 'beginner' }), { systemDark: false, systemReduce: true })
  assert.equal(st.theme, 'light')
  assert.deepEqual(st.attrs, { 'data-theme': 'light', 'data-motion': 'reduce', 'data-cb': 'on', 'data-mode': 'beginner' })
  assert.equal(st.scale, 1.25)
  assert.equal(st.text, 1.15)
})

test('width class uses the width the layout really has once scaled', () => {
  assert.equal(U.widthClass(1100 / 1.25), 'xs')
  assert.equal(U.widthClass(1100), 'sm')
  assert.equal(U.widthClass(1600), 'md')
})
