// What's new: a short changelog file (changelog.md) -> entries, and the rule for when to show them.
//
// changelog.md looks like:
//   ## 1.0.11
//   - one short line per change
//   - another
//   ## 1.0.10
//   - ...
// The newest version comes first.

export function parseChangelog(text) {
  const out = []
  let cur = null
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    const h = /^##\s+([0-9]+(?:\.[0-9]+)*)\s*$/.exec(line)
    if (h) { cur = { version: h[1], items: [] }; out.push(cur); continue }
    const li = /^[-*]\s+(.+)$/.exec(line)
    if (li && cur) cur.items.push(li[1].trim())
  }
  return out.filter(e => e.items.length)
}

export function cmpVersion(a, b) {
  const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number)
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0)
    if (d) return d < 0 ? -1 : 1
  }
  return 0
}

export const newest = entries => entries.reduce((a, e) => (!a || cmpVersion(e.version, a) > 0 ? e.version : a), null)

// entries to show: everything newer than the version the user last saw. Nothing seen yet (an update from before this existed) = the newest entry only.
// A fresh install is marked as seen by the caller, so it never gets a list of old changes.
export function unseen(entries, lastSeen) {
  const sorted = [...entries].sort((a, b) => cmpVersion(b.version, a.version))
  if (!lastSeen) return sorted.slice(0, 1)
  return sorted.filter(e => cmpVersion(e.version, lastSeen) > 0)
}
