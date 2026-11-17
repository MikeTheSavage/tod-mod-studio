// Small calls of the world screens. getJob: a GET that starts a job (poll it); world: the POST of the world actions.
import { get, post } from '../api.js'

export async function getJob(path) {
  let job = await get(path)
  while (job.status === 'queued' || job.status === 'running') {
    await new Promise(r => setTimeout(r, 350))
    job = await get('/api/job/' + job.id)
  }
  if (job.status === 'failed') throw new Error(job.error || 'failed')
  return job.result
}
export const world = (action, body) => post('/api/world', { action, ...body })
