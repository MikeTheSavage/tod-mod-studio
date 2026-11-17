// Interface preferences: theme, scale, text size, reduced motion, colour-blind safe palette, Beginner / Advanced.
// The pure functions at the top are unit tested (tests/uiprefs.test.mjs); the store below keeps the choice in the browser
// (per viewer, like the old theme switch) and writes it onto <html> so the style sheet can react.

export const SCALE_MIN = 90, SCALE_MAX = 150
export const TEXT_SIZES = [90, 100, 115, 130]
export const THEMES = ['system', 'dark', 'light', 'contrast']
export const MOTIONS = ['system', 'reduce', 'full']
export const MODES = ['beginner', 'advanced']

export const DEFAULT_PREFS = { theme: 'system', scale: 100, text: 100, motion: 'system', cb: false, mode: 'advanced', lang: 'en' }

// screens that Beginner mode hides (the rarely used ones); Advanced shows everything
export const ADVANCED_SCREENS = ['missions', 'sections', 'collision', 'routes', 'bisect']

export function clampScale(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return DEFAULT_PREFS.scale
  return Math.min(SCALE_MAX, Math.max(SCALE_MIN, Math.round(n / 5) * 5))
}
export function clampText(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return DEFAULT_PREFS.text
  return TEXT_SIZES.reduce((a, b) => (Math.abs(b - n) < Math.abs(a - n) ? b : a))
}

// the saved object (or anything) -> a complete, valid set of preferences
export function normalize(raw) {
  const r = raw && typeof raw === 'object' ? raw : {}
  return {
    theme: THEMES.includes(r.theme) ? r.theme : DEFAULT_PREFS.theme,
    scale: clampScale(r.scale ?? DEFAULT_PREFS.scale),
    text: clampText(r.text ?? DEFAULT_PREFS.text),
    motion: MOTIONS.includes(r.motion) ? r.motion : DEFAULT_PREFS.motion,
    cb: r.cb === true,
    mode: MODES.includes(r.mode) ? r.mode : DEFAULT_PREFS.mode,
    lang: typeof r.lang === 'string' && r.lang ? r.lang : DEFAULT_PREFS.lang,
  }
}

// 'system' follows Windows: dark or light. High contrast is its own dark-based look.
export function resolveTheme(pref, systemDark) {
  if (pref === 'dark' || pref === 'light' || pref === 'contrast') return pref
  return systemDark === false ? 'light' : 'dark'
}
// what the 3D views and previews use: they only know dark and light
export const baseTheme = resolved => (resolved === 'light' ? 'light' : 'dark')

export function motionReduced(pref, systemReduce) {
  if (pref === 'reduce') return true
  if (pref === 'full') return false
  return !!systemReduce
}

export const screenVisible = (id, mode) => mode !== 'beginner' || !ADVANCED_SCREENS.includes(id)
// the screens of one area for the tab strip: Beginner hides the rare ones, but never the one you are on
export const visibleScreens = (screens, mode, current) => screens.filter(s => screenVisible(s[0], mode) || s[0] === current)

// the area rail: an area with no visible screens would be empty, so it is hidden too (never the current one)
export const visibleAreas = (areas, mode, current) =>
  areas.filter(a => a.screens.some(s => s[0] === current) || visibleScreens(a.screens, mode, current).length > 0)

// url overrides (headless screenshots, links): ?theme= ?scale= ?text= ?motion= ?cb= ?mode=
export function fromQuery(search) {
  const q = new URLSearchParams(search || '')
  const o = {}
  if (q.get('theme') && THEMES.includes(q.get('theme'))) o.theme = q.get('theme')
  if (q.get('scale')) o.scale = clampScale(q.get('scale'))
  if (q.get('text')) o.text = clampText(q.get('text'))
  if (q.get('motion') && MOTIONS.includes(q.get('motion'))) o.motion = q.get('motion')
  if (q.get('cb')) o.cb = q.get('cb') === '1' || q.get('cb') === 'true'
  if (q.get('mode') && MODES.includes(q.get('mode'))) o.mode = q.get('mode')
  return o
}

// the attributes and variables the style sheet reads
export function documentState(prefs, env = {}) {
  const resolved = resolveTheme(prefs.theme, env.systemDark)
  const reduced = motionReduced(prefs.motion, env.systemReduce)
  return {
    theme: resolved,
    attrs: { 'data-theme': resolved, 'data-motion': reduced ? 'reduce' : 'full', 'data-cb': prefs.cb ? 'on' : 'off', 'data-mode': prefs.mode },
    scale: prefs.scale / 100,
    text: prefs.text / 100,
  }
}

// ---------------------------------------------------------------- the store (browser only)
const KEY = 'todms.ui.v1'
const lsGet = k => { try { return localStorage.getItem(k) } catch { return null } }
const lsSet = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private window */ } }

function loadSaved() {
  let saved = {}
  try { saved = JSON.parse(lsGet(KEY) || '{}') } catch { saved = {} }
  const old = lsGet('todms.theme')                       // the old two-way theme switch: an explicit choice, so it stays
  if (!saved.theme && (old === 'dark' || old === 'light')) saved = { ...saved, theme: old }
  return normalize(saved)
}

// the width the layout really has once the scale is applied: xs below 1000, sm below 1280, else md
export const widthClass = w => (w < 1000 ? 'xs' : w < 1280 ? 'sm' : 'md')

const mq = q => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(q) : null)
const env = () => ({ systemDark: mq('(prefers-color-scheme: dark)')?.matches !== false, systemReduce: !!mq('(prefers-reduced-motion: reduce)')?.matches })

const S = { prefs: null, snap: null, subs: new Set() }
function init() {
  if (S.prefs) return
  S.prefs = loadSaved()
  S.query = typeof location !== 'undefined' ? fromQuery(location.search) : {}      // one-off overrides: not saved
  for (const m of ['(prefers-color-scheme: dark)', '(prefers-reduced-motion: reduce)']) {
    const l = mq(m)
    if (l && l.addEventListener) l.addEventListener('change', () => { apply(); emit() })
  }
  apply(); S.snap = snapshot()
  if (typeof window !== 'undefined') window.addEventListener('resize', apply)
}
const effective = () => ({ ...S.prefs, ...S.query })
function snapshot() {
  const p = effective()
  const st = documentState(p, env())
  return { prefs: p, resolved: st.theme, base: baseTheme(st.theme), reduced: st.attrs['data-motion'] === 'reduce' }
}
function apply() {
  if (typeof document === 'undefined') return
  const st = documentState(effective(), env())
  const root = document.documentElement
  for (const [k, v] of Object.entries(st.attrs)) root.setAttribute(k, v)
  root.setAttribute('data-w', widthClass(window.innerWidth / st.scale))
  root.style.setProperty('--ts', String(st.text))
  root.style.setProperty('--ui-zoom', String(st.scale))
}
function emit() { S.snap = snapshot(); S.subs.forEach(f => f()) }

export function getUi() { init(); return S.snap }
export function subscribeUi(f) { init(); S.subs.add(f); return () => S.subs.delete(f) }
export function setPrefs(patch) {
  init()
  S.prefs = normalize({ ...S.prefs, ...patch })
  for (const k of Object.keys(patch)) delete S.query[k]       // a choice made in the app wins over the address
  lsSet(KEY, JSON.stringify(S.prefs))
  apply(); emit()
}
export const resetPrefs = () => setPrefs({ ...DEFAULT_PREFS })
// for code outside React (camera fly-tos and similar): true when motion should be skipped
export const reducedMotion = () => { init(); return S.snap.reduced }
