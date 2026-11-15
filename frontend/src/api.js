// Small client for the local backend (todms/server.py).
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

// Start a job (POST returning {id,...}) and poll it; onProgress gets the job record.
export async function runJob(path, body, onProgress) {
  let job = await post(path, body)
  while (job.status === 'queued' || job.status === 'running') {
    onProgress?.(job)
    await new Promise(r => setTimeout(r, 350))
    job = await get('/api/job/' + job.id)
  }
  onProgress?.(job)
  if (job.status === 'failed') {
    const e = new Error(job.error || 'failed')
    e.trace = job.trace
    throw e
  }
  return job.result
}
