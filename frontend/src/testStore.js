// Test in game: the options, the steps of the running test and the state of the last run, shared by the editor bar, the Debug area and Settings.
import { useSyncExternalStore } from 'react'
import { get, post, runJob } from './api.js'

export const STEPS = ['check', 'build', 'install', 'save', 'launch']
export const STEP_LABEL = { check: 'Check', build: 'Build', install: 'Test copy', save: 'Test save', launch: 'Launch' }

const KEY = 'todms.test.v1'
const DEFAULTS = { save: true, source: '', pos: '', yaw: '', spotName: '', heal: true, weapons: false, god: false, ammo: false, unlock: false, start_mission: '', keep: false }
const lsGet = () => { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') } } catch { return { ...DEFAULTS } } }
const lsSet = o => { try { localStorage.setItem(KEY, JSON.stringify(o)) } catch { /* private window */ } }

const idle = () => STEPS.map(() => ({ tone: 'idle', note: '' }))
const S = { opts: lsGet(), busy: false, error: null, steps: idle(), status: null, snap: null, subs: new Set() }
const emit = () => { S.snap = { opts: S.opts, busy: S.busy, error: S.error, steps: S.steps, status: S.status }; S.subs.forEach(f => f()) }
emit()

export const useTest = () => useSyncExternalStore(f => { S.subs.add(f); return () => S.subs.delete(f) }, () => S.snap)

export function setTestOpts(patch) { S.opts = { ...S.opts, ...patch }; lsSet(S.opts); emit() }

export async function refreshTest(full) {
  try { S.status = await get('/api/testgame', full ? undefined : { light: 1 }) } catch (e) { S.status = { ...(S.status || {}), error: e.message } }
  emit()
  return S.status
}

const parsePos = t => {
  if (!t || !String(t).trim()) return null
  const p = String(t).split(',').map(x => Number(x.trim()))
  if (p.length !== 3 || p.some(isNaN)) throw new Error('The position needs three numbers: x, height and z.')
  return p
}

const at = (i, msg, bad) => STEPS.map((_, j) => j < i ? { tone: 'ok', note: '' } : j === i ? { tone: bad ? 'bad' : 'busy', note: msg || '' } : { tone: 'idle', note: '' })

// Start a test. spot: { pos, yaw, name } replaces the saved spot. confirmFull(plan) -> Promise<bool> asks before a full copy across drives.
export async function startTest({ project, real = false, spot, confirmFull }) {
  if (S.busy) return null
  S.error = null
  if (spot) S.opts = { ...S.opts, pos: spot.pos.map(v => Math.round(v * 100) / 100).join(', '), yaw: String(Math.round(spot.yaw ?? 0)), spotName: spot.name || '' }
  lsSet(S.opts)
  S.busy = true; S.steps = at(0, ''); emit()
  let cur = 0
  try {
    const o = S.opts
    const body = { mod: project, real, keep: o.keep, opts: { save: o.save, source: o.source || null, pos: parsePos(o.pos), yaw: o.yaw === '' ? null : Number(o.yaw), heal: o.heal, weapons: o.weapons,
      god: o.god, ammo: o.ammo, unlock: o.unlock ? 'open' : null, start_mission: null } }
    const onProgress = j => {
      const [name, msg] = String(j.message || '').split('|')
      cur = Math.max(0, STEPS.indexOf(name))
      S.steps = at(cur, msg); emit()
    }
    let r = await runJob('/api/testgame/run', body, onProgress)
    if (r?.confirm) {
      const yes = confirmFull ? await confirmFull(r.confirm) : false
      if (!yes) { S.busy = false; S.steps = idle(); emit(); return null }
      r = await runJob('/api/testgame/run', { ...body, allow_full_copy: true }, onProgress)
    }
    S.steps = STEPS.map((_, j) => ({ tone: j === 3 && r.save?.skipped ? 'idle' : 'ok', note: '' }))
    S.busy = false
    await refreshTest(true)
    return r
  } catch (e) {
    S.error = e.message; S.busy = false; S.steps = at(cur, e.message, true); emit()
    refreshTest()
    throw e
  }
}

export const stopTest = async () => { await post('/api/testgame/stop'); await refreshTest(true) }
export const clearTestError = () => { S.error = null; S.steps = idle(); emit() }
