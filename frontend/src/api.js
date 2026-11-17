// Small client for the local backend (todms/server.py).
import { recordResult } from './problemsStore.js'
let token = document.querySelector('meta[name="todms-token"]')?.content || null

async function getToken() {
  if (token) return token
  const r = await fetch('/api/token')            // only answered by the development server
  if (r.ok) token = (await r.json()).token
  return token
}

async function handle(r) {
  let j = null
  try { j = await r.json() } catch { j = { error: 'bad reply (' + r.status + ')' } }
  if (!r.ok) {
    const e = new Error(j?.error || ('HTTP ' + r.status))
    e.trace = j?.trace
    throw e
  }
  return j
}

export async function get(path, params) {
  const q = params ? '?' + new URLSearchParams(params).toString() : ''
  return handle(await fetch(path + q))
}

export async function post(path, body) {
  const t = await getToken()
  return handle(await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-TODMS-Token': t || '' },
    body: JSON.stringify(body || {}),
  }))
}

// One app-level store of running jobs: the status bar and the screens read the same list, so a job that was
// started on one screen keeps showing its progress after the user moves to another.
const store = { jobs: [], subs: new Set(), snap: [] }
const emit = () => { store.snap = store.jobs.slice(); store.subs.forEach(f => f()) }
export const jobsStore = {
  subscribe: f => { store.subs.add(f); return () => store.subs.delete(f) },
  get: () => store.snap,
}
const LABELS = { prepare: 'Reading the game', setup: 'Opening the game folder', open: 'Opening the level', check: 'Checking', export: 'Building the mod',
  install: 'Installing', build: 'Building', 'catalogue-scan': 'Scanning the game', testrun: 'Testing in game', bisect: 'Preparing the test' }
function track(job, path, body) {
  const a = body?.action
  const label = (job.message && job.message.includes('|') ? '' : job.message) || (a && ({ build: 'Building', check: 'Checking', validate: 'Checking the missions', install: 'Installing', uninstall: 'Removing', schema: 'Reading the mission settings', slots: 'Counting mission slots', hosts: 'Listing the maps', savefix: 'Updating the save' }[a])) || LABELS[job.kind] || 'Working'
  const rec = { id: job.id, kind: job.kind, label, done: job.done || 0, total: job.total || 0, status: job.status, path }
  const i = store.jobs.findIndex(j => j.id === job.id)
  if (i >= 0) store.jobs[i] = rec; else store.jobs.push(rec)
  emit()
}
function untrack(id) { store.jobs = store.jobs.filter(j => j.id !== id); emit() }

// Start a job (POST returning {id,...}) and poll it; onProgress gets the job record.
export async function runJob(path, body, onProgress) {
  let job = await post(path, body)
  track(job, path, body)
  try {
    while (job.status === 'queued' || job.status === 'running') {
      onProgress?.(job)
      await new Promise(r => setTimeout(r, 350))
      job = await get('/api/job/' + job.id)
      track(job, path, body)
    }
  } finally { untrack(job.id) }
  onProgress?.(job)
  if (job.status === 'failed') {
    const e = new Error(job.error || 'failed')
    e.trace = job.trace
    throw e
  }
  try { recordResult(path, body || {}, job.result) } catch { /* the Problems list is optional */ }
  return job.result
}
