import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as H from '../src/helpdata.js'
import * as W from '../src/whatsnew.js'

const guide = fs.readFileSync(new URL('../../guide/TOD Mod Studio Guide.html', import.meta.url), 'utf8')
const index = H.indexGuide(guide)

test('the guide has a section for every feature in the app', () => {
  const ids = new Set(index.map(s => s.id))
  for (const id of ['testgame', 'debug', 'import', 'textures', 'catalogue', 'limits', 'versions', 'tools', 'view3d', 'playground', 'controller', 'access', 'saves', 'help', 'mode'])
    assert.ok(ids.has(id), 'guide section ' + id)
  assert.ok(index.length > 30)
  assert.ok(index.every(s => s.title && s.id))
})

test('the guide never mentions another engine', () => {
  for (const w of ['Unreal']) assert.equal(guide.includes(w), false, w)
})

test('every screen opens help at a section that exists', () => {
  const ids = new Set(index.map(s => s.id))
  for (const [screen, anchor] of Object.entries(H.SCREEN_ANCHOR)) assert.ok(ids.has(anchor), `${screen} -> ${anchor}`)
  assert.equal(H.anchorFor('level'), 'level')
  assert.equal(H.anchorFor('unknown-screen'), 'what')
})

test('guide search: every word has to match, the title counts most', () => {
  const r = H.searchIndex(index, 'test in game')
  assert.ok(r.length > 0)
  assert.equal(r[0].id, 'testgame')
  assert.ok(r[0].snippet.length > 10)
  assert.deepEqual(H.searchIndex(index, ''), [])
  assert.deepEqual(H.searchIndex(index, 'zzzqqqxxx'), [])
  const two = H.searchIndex(index, 'restore original')
  assert.ok(two.some(x => x.id === 'versions'))
  assert.ok(H.searchIndex(index, 'webview2').length >= 1, 'search is not case sensitive')
})

test('glossary has the words the roadmap names and filters', () => {
  const terms = H.GLOSSARY.map(g => g.term.toLowerCase())
  for (const w of ['section', 'loader', 'trigger', 'route', 'archive', 'pack', 'block', 'giver']) assert.ok(terms.includes(w), w)
  assert.ok(H.GLOSSARY.every(g => g.def.length > 15 && !/Unreal/.test(g.def)))
  assert.deepEqual(H.searchGlossary('loader').map(g => g.term), ['Loader'])
  assert.equal(H.searchGlossary('').length, H.GLOSSARY.length)
})

test('changelog: parse, order and the show-once rule', () => {
  const text = '## 1.0.11\n- one\n- two\n\n## 1.0.10\n- old\n## 1.0.9\n'
  const e = W.parseChangelog(text)
  assert.deepEqual(e, [{ version: '1.0.11', items: ['one', 'two'] }, { version: '1.0.10', items: ['old'] }])
  assert.equal(W.cmpVersion('1.0.10', '1.0.9'), 1)
  assert.equal(W.cmpVersion('1.1', '1.1.0'), 0)
  assert.equal(W.newest(e), '1.0.11')
  assert.deepEqual(W.unseen(e, '1.0.11'), [])
  assert.deepEqual(W.unseen(e, '1.0.10').map(x => x.version), ['1.0.11'])
  assert.deepEqual(W.unseen(e, '1.0.0').map(x => x.version), ['1.0.11', '1.0.10'])
  assert.deepEqual(W.unseen(e, null).map(x => x.version), ['1.0.11'])
})

test('the shipped changelog parses and its newest entry is not empty', () => {
  const e = W.parseChangelog(fs.readFileSync(new URL('../src/changelog.md', import.meta.url), 'utf8'))
  assert.ok(e.length >= 1 && e[0].items.length >= 3)
  for (const x of e) for (const i of x.items) assert.ok(!/Unreal/.test(i))
})
