// Keyboard and screen-reader repairs that apply to the whole app: items that only react to a mouse click get a focus stop, a role and
// Enter / Space; progress bars announce themselves. Installed once from App; it only adds attributes, never removes them.

export const CLICKABLE = [
  '.statusbar .it.click', '.checkrow.click', '.li', '.sideitem', '.step', '.prow', '.meter.click', '.menu .item', '.cmdk .row2',
  '.changes ol li', '.gd .c.nm', '.fieldhead .d.chg', '.v3note', '.error', 'table.sets tr',
].join(',')
const PROGRESS = '.progbar, .statusbar .bar, .pb'

export function repair(root = document) {
  for (const el of root.querySelectorAll(CLICKABLE)) {
    if (el.dataset.a11y) continue
    if (el.matches('button,a[href],input,select,textarea,summary')) continue
    el.dataset.a11y = '1'
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0')
    if (el.tagName !== 'TR' && !el.hasAttribute('role')) el.setAttribute('role', el.matches('.menu .item') ? 'menuitem' : 'button')
  }
  for (const el of root.querySelectorAll(PROGRESS)) {
    if (!el.hasAttribute('role')) { el.setAttribute('role', 'progressbar'); el.setAttribute('aria-label', 'Progress'); el.setAttribute('aria-valuemin', '0'); el.setAttribute('aria-valuemax', '100') }
    const w = parseFloat(el.firstElementChild && el.firstElementChild.style && el.firstElementChild.style.width)
    if (Number.isFinite(w)) el.setAttribute('aria-valuenow', String(Math.round(w))); else el.removeAttribute('aria-valuenow')
  }
}

export function installA11y() {
  let queued = false
  const run = () => { queued = false; repair() }
  const queue = () => { if (!queued) { queued = true; (window.requestAnimationFrame ? window.requestAnimationFrame(run) : setTimeout(run, 16)) } }
  const mo = new MutationObserver(queue)
  mo.observe(document.body, { childList: true, subtree: true })
  const key = e => {
    if ((e.key !== 'Enter' && e.key !== ' ') || e.ctrlKey || e.altKey || e.metaKey) return
    const el = e.target
    if (!(el instanceof Element) || !el.dataset || !el.dataset.a11y) return
    e.preventDefault(); el.click()
  }
  window.addEventListener('keydown', key)
  repair()
  return () => { mo.disconnect(); window.removeEventListener('keydown', key) }
}
