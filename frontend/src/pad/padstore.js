// The one controller store: reads the first connected pad (or the dev simulator), keeps the settings, tells listeners about
// button presses (with the View chord already resolved) and which input kind the user used last (pad or keys), and
// gives the 3D views the stick values. Everything pure lives in padlogic.js.
import { useSyncExternalStore } from 'react'
import * as L from './padlogic.js'

const LS = 'todms.pad.v1'
const lsGet = () => { try { return JSON.parse(localStorage.getItem(LS) || 'null') } catch { return null } }
const lsSet = v => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private window */ } }

const S = {
  cfg: L.cleanCfg(lsGet()), mode: 'keys', connected: false, name: '',
  raw: [0, 0, 0, 0], state: L.emptyState(), prev: L.emptyState().held, router: L.createRouter(),
  acts: new Set(), ticks: new Set(), subs: new Set(), snap: null, started: false, pad: null,
  ui: { ctx: 'ui', placing: false, modeName: '' }, sim: { on: false, buttons: Array.from({ length: 17 }, () => 0), axes: [0, 0, 0, 0] }, rumbles: [],
}
const snap = () => { S.snap = { cfg: S.cfg, mode: S.mode, connected: S.connected, name: S.name, ui: S.ui }; S.subs.forEach(f => f()) }
snap()
const subscribe = f => { S.subs.add(f); return () => S.subs.delete(f) }
const getSnap = () => S.snap

export const usePad = () => useSyncExternalStore(subscribe, getSnap)
export const getCfg = () => S.cfg
export const getMode = () => S.mode
export const rawAxes = () => S.raw
export const padState = () => S.state             // { held, axes } with the dead zone and A/B swap applied
export const onAction = f => { S.acts.add(f); return () => S.acts.delete(f) }
export const onTick = f => { S.ticks.add(f); return () => S.ticks.delete(f) }
export const rumbleLog = () => S.rumbles
// what the hints need to know about the screen: which context has focus, whether something is being placed, the edit mode's name
export function setUi(patch) {
  if (Object.keys(patch).every(k => S.ui[k] === patch[k])) return
  S.ui = { ...S.ui, ...patch }; snap()
}

export function setCfg(patch) {
  S.cfg = L.cleanCfg({ ...S.cfg, ...patch })
  lsSet(S.cfg); snap()
}
export const resetCfg = () => { S.cfg = { ...L.DEFAULTS }; lsSet(S.cfg); snap() }

export function setMode(kind, moved) {
  const m = L.nextMode(S.mode, kind, moved)
  if (m === S.mode) return
  S.mode = m
  try { document.documentElement.dataset.input = m } catch { /* no document */ }
  snap()
}

// a short buzz on the pad: 'ok' for a confirm, 'bad' for an error (only where the pad supports it)
export function rumble(kind = 'ok') {
  if (!S.cfg.rumble || S.mode !== 'pad') return
  S.rumbles.push(kind)
  if (S.rumbles.length > 50) S.rumbles.shift()
  try {
    const a = S.pad && S.pad.vibrationActuator
    if (a && a.playEffect) a.playEffect('dual-rumble', kind === 'bad' ? { duration: 240, strongMagnitude: 0.8, weakMagnitude: 0.5 } : { duration: 60, strongMagnitude: 0, weakMagnitude: 0.4 }).catch(() => {})
  } catch { /* not supported */ }
}

function readRaw() {
  if (S.sim.on) return { buttons: S.sim.buttons.map(v => ({ pressed: v > 0.5, value: v })), axes: S.sim.axes, sim: true }
  const list = typeof navigator !== 'undefined' && navigator.getGamepads ? navigator.getGamepads() : []
  const g = [...list].find(x => x && x.connected)
  S.pad = g || null
  if (!g) return null
  return { buttons: [...g.buttons].map(b => ({ pressed: b.pressed, value: b.value })), axes: [...g.axes], id: g.id }
}

function frame(now) {
  const raw = readRaw()
  const connected = !!raw
  const name = raw ? (raw.sim ? 'Simulated pad' : String(raw.id || 'Controller').replace(/\s*\(.*$/, '').slice(0, 40)) : ''
  if (connected !== S.connected || name !== S.name) { S.connected = connected; S.name = name; snap() }
  const st = L.readState(raw, S.cfg)
  S.raw = raw ? raw.axes.slice(0, 4) : [0, 0, 0, 0]
  const ed = L.edges(S.prev, st.held)
  S.state = st; S.prev = st.held
  const acts = L.route(S.router, ed)
  if (ed.down.length || L.stickUsed(st.axes)) setMode('pad')
  for (const a of acts) for (const f of [...S.acts]) { try { if (f(a) === true) break } catch (e) { console.error(e) } }
  for (const f of [...S.ticks]) { try { f(st, now) } catch (e) { console.error(e) } }
}

export function startPad() {
  if (S.started || typeof window === 'undefined') return
  S.started = true
  const loop = t => { frame(t); requestAnimationFrame(loop) }
  requestAnimationFrame(loop)
  let lx = null, ly = null
  window.addEventListener('keydown', () => setMode('key'), true)
  window.addEventListener('pointerdown', () => setMode('mouse', 99), true)
  window.addEventListener('mousemove', e => { const d = lx == null ? 0 : Math.hypot(e.clientX - lx, e.clientY - ly); lx = e.clientX; ly = e.clientY; if (d) setMode('mouse', d) }, true)
  document.documentElement.dataset.input = S.mode
  installSim()
}

// ------------------------------------------------------------------ the dev simulator: only when the address has ?pad
// window.__pad.press('A'), .hold('LT'), .release('LT'), .stick('l', x, y), .run('A,wait:200,ls:0:-1:500')
const wait = ms => new Promise(r => setTimeout(r, ms))
function installSim() {
  let wanted = false
  try { wanted = new URLSearchParams(location.search).has('pad') } catch { /* no location */ }
  if (!wanted) return
  const sim = S.sim
  const idx = n => { const i = L.INDEX[String(n).toUpperCase()]; if (i == null) throw new Error('No button ' + n); return i }
  const api = {
    press: async (n, ms = 90) => { sim.on = true; sim.buttons[idx(n)] = 1; await wait(ms); sim.buttons[idx(n)] = 0; await wait(40) },
    hold: n => { sim.on = true; sim.buttons[idx(n)] = 1 },
    release: n => { if (n == null) { sim.buttons.fill(0); sim.axes = [0, 0, 0, 0] } else sim.buttons[idx(n)] = 0 },
    value: (n, v) => { sim.on = true; sim.buttons[idx(n)] = v },                   // a trigger: value(RT, 1)
    stick: (which, x, y) => { sim.on = true; const o = which === 'r' ? 2 : 0; sim.axes[o] = x; sim.axes[o + 1] = y },
    wait,
    state: () => S.state, mode: () => S.mode, rumbles: () => S.rumbles, cfg: () => S.cfg, setCfg,
    run: async script => {
      for (const tok of String(script).split(',').map(s => s.trim()).filter(Boolean)) {
        const p = tok.split(':')
        const k = p[0].toLowerCase()
        if (k === 'wait') await wait(+p[1] || 200)
        else if (k === 'ls' || k === 'rs') { api.stick(k === 'rs' ? 'r' : 'l', +p[1], +p[2]); await wait(+p[3] || 300); api.stick(k === 'rs' ? 'r' : 'l', 0, 0) }
        else if (k === 'lt' || k === 'rt') { api.value(k.toUpperCase(), +p[1]); await wait(+p[2] || 300); api.value(k.toUpperCase(), 0) }
        else if (k === 'hold') await api.press(p[1], +p[2] || 600)
        else if (k === 'down' || k === 'up' || k === 'left' || k === 'right') await api.press(k.toUpperCase())
        else await api.press(p[0].toUpperCase())
      }
    },
  }
  window.__pad = api
  const q = new URLSearchParams(location.search).get('pad')
  if (q) setTimeout(() => api.run(q).catch(e => console.error(e)), +(new URLSearchParams(location.search).get('padwait') || 2500))
}
