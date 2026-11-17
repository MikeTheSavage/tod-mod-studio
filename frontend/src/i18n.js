// Translations: every word of the interface lives in locales/<code>.json (flat: key -> text). `t('key')` returns the text,
// `t('key', { n: 3 })` fills {n}. A missing key in another language falls back to English, and a key missing everywhere
// shows the key itself. See locales/README.md for how a community translation is added.
import en from './locales/en.json' with { type: 'json' }

export const LANGUAGES = [{ code: 'en', name: 'English' }]
const CATALOGUES = { en }
let current = 'en'

export function setLanguage(code) { current = CATALOGUES[code] ? code : 'en' }
export const getLanguage = () => current
// for tests and for translations loaded later
export function register(code, catalogue) { CATALOGUES[code] = catalogue }
export const catalogue = (code = 'en') => CATALOGUES[code] || en

export function t(key, vars) {
  const s = (CATALOGUES[current] && CATALOGUES[current][key]) ?? en[key] ?? key
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? String(vars[k]) : m))
}
export const tr = t
