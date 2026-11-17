import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as I from '../src/i18n.js'

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src')
const en = JSON.parse(fs.readFileSync(path.join(SRC, 'locales', 'en.json'), 'utf8'))

function* sources(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) { if (!['locales', 'fonts', 'vendor'].includes(e.name)) yield* sources(p) }
    else if (/\.(jsx?|mjs)$/.test(e.name)) yield p
  }
}

test('t() looks a key up, fills {name} and falls back to the key', () => {
  I.register('xx', { hello: 'Hola {who}', only_xx: 'solo' })
  I.register('en', en)
  I.setLanguage('en')
  const first = Object.keys(en)[0]
  assert.equal(I.t(first), en[first])
  assert.equal(I.t('no_such_key_anywhere'), 'no_such_key_anywhere')
  I.register('en', { ...en, greet: 'Hello {who}, {n} left' })
  assert.equal(I.t('greet', { who: 'Ram', n: 3 }), 'Hello Ram, 3 left')
  assert.equal(I.t('greet', { who: 'Ram' }), 'Hello Ram, {n} left')
  I.setLanguage('xx')
  assert.equal(I.t('hello', { who: 'Ram' }), 'Hola Ram')
  assert.equal(I.t(first), en[first], 'a key the translation lacks falls back to English')
  I.setLanguage('zz')
  assert.equal(I.getLanguage(), 'en', 'an unknown language means English')
  I.register('en', en)
})

test('only English is offered for now', () => {
  assert.deepEqual(I.LANGUAGES.map(l => l.code), ['en'])
})

test('every key used in the code exists in en.json', () => {
  const re = /\b(?:t|tr)\(\s*'([^']+)'/g
  const missing = []
  for (const f of sources(SRC)) {
    if (f.endsWith('i18n.js')) continue
    const code = fs.readFileSync(f, 'utf8')
    let m
    while ((m = re.exec(code))) if (!(m[1] in en)) missing.push(path.relative(SRC, f) + ': ' + m[1])
  }
  assert.deepEqual(missing, [])
})

test('every word in en.json is used by the code (no leftovers)', () => {
  const all = [...sources(SRC)].filter(f => !f.endsWith('i18n.js')).map(f => fs.readFileSync(f, 'utf8')).join('\n')
  const unused = Object.keys(en).filter(k => !new RegExp(`\\b(?:t|tr)\\(\\s*'${k}'`).test(all))
  assert.deepEqual(unused, [])
})

test('en.json is flat, non-empty text, and placeholders are plain {name}', () => {
  for (const [k, v] of Object.entries(en)) {
    assert.equal(typeof v, 'string', k)
    assert.ok(v.trim().length > 0, k)
    assert.equal(v, v.trim(), 'no loose spaces in ' + k)
    assert.match(k, /^[a-z0-9_]+$/)
    for (const p of v.match(/\{[^}]*\}/g) || []) assert.match(p, /^\{\w+\}$/, k)
  }
})

// ---- one key, one text
import { makeKeyer } from '../tools/i18n_keys.mjs'

test('texts that differ in any character, case included, never share a key', () => {
  const e = {}
  const keyFor = makeKeyer(e)
  const texts = ['Library', 'library', 'Add', 'add', 'Add ', 'Routes', 'routes', 'Place', 'place', 'More', 'more', 'Mission', 'mission', 'Search', 'search']
  const keys = texts.map(keyFor)
  assert.equal(new Set(keys).size, texts.length)
  texts.forEach((t, i) => { assert.equal(e[keys[i]], t); assert.equal(keyFor(t), keys[i], 'the same text keeps its key') })
})

test('the pairs that were once mixed up stay apart in en.json', () => {
  const val = k => en[k]
  // the screens' own capitalised words
  for (const [k, t] of [['library', 'Library'], ['community', 'Community'], ['author', 'Author'], ['routes', 'Routes'], ['tuning', 'Tuning'], ['profiles', 'Profiles'],
    ['conflicts', 'Conflicts'], ['needs', 'Needs'], ['online', 'Online'], ['locked', 'Locked']]) assert.equal(val(k), t, k)
  // a lowercase twin may exist, but never under the same key
  const byText = new Map()
  for (const [k, v] of Object.entries(en)) { assert.ok(!byText.has(v), `two keys hold the same text: ${k} and ${byText.get(v)}`); byText.set(v, k) }
  const lower = new Map()
  for (const [k, v] of Object.entries(en)) { const l = v.toLowerCase(); if (lower.has(l)) assert.notEqual(lower.get(l)[0], k); lower.set(l, [k, v]) }
})
