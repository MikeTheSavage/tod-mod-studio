// Keys for interface texts. One key stands for exactly one text: texts that differ in any character, case included, never share a key.
import crypto from 'node:crypto'

export const slug = s => (s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean).slice(0, 6).join('_') || 'text').slice(0, 44)

// en = the key -> text object (changed in place when a new text is added). Returns keyFor(text).
export function makeKeyer(en) {
  const byText = new Map(Object.entries(en).map(([k, v]) => [v, k]))
  const used = new Set(Object.keys(en))
  return function keyFor(text) {
    if (byText.has(text)) return byText.get(text)                         // exact same text (case included): same key
    let k = slug(text)
    if (used.has(k)) k = k + '_' + crypto.createHash('sha1').update(text).digest('hex').slice(0, 6)   // the slug is taken by another text
    for (let i = 2; used.has(k); i++) k = slug(text) + '_' + crypto.createHash('sha1').update(text + i).digest('hex').slice(0, 6)
    used.add(k); byText.set(text, k); en[k] = text
    return k
  }
}
