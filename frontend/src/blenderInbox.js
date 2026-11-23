// Models sent from Blender (the add-on of Mod Studio): the app polls the backend while "Send from Blender" is on and
// leaves what arrived here for the model import screen to open.
import { post } from './api.js'

const subs = new Set()
let queue = []
export const inbox = {
  push(items) { queue = queue.concat(items); subs.forEach(f => f()) },
  take() { return queue.shift() || null },
  subscribe(f) { subs.add(f); return () => subs.delete(f) },
}

export async function pollBlender(onArrive) {
  try {
    const r = await post('/api/blender/pending', {})
    if (r.items && r.items.length) { inbox.push(r.items); onArrive(r.items) }
  } catch { /* the backend is busy: try again on the next beat */ }
}

// Save the add-on (one .py) where the person chooses.
export async function saveAddon(say) {
  try {
    const r = await post('/api/blender/addon', {})
    if (!r.cancelled) say('Saved.')
  } catch (e) { say(e.message, 'bad') }
}
