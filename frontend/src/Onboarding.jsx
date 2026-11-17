import React, { useEffect, useMemo, useRef, useState } from 'react'
import changelogText from './changelog.md?raw'
import { useHelpStore, gotoStep, endLesson, answerOffer, savedHelp, saveHelp, openHelp } from './helpstore.js'
import { lessonById, stepDone, snapshotOf } from './lessons.js'
import { parseChangelog, unseen, newest } from './whatsnew.js'
import { useTest } from './testStore.js'
import { useUI } from './ui.jsx'
import { useUi } from './uistore.js'
import { t as tr } from './i18n.js'

// a target is a css selector, or `btn:Text` for the visible button whose label contains Text
function findTarget(sel) {
  if (!sel) return null
  try {
    if (sel.startsWith('btn:')) { const w = sel.slice(4).toLowerCase(); return [...document.querySelectorAll('button')].find(b => visible(b) && b.textContent.toLowerCase().includes(w)) || null }
    return [...document.querySelectorAll(sel)].find(visible) || null
  } catch { return null }
}
const textIn = (sel, text) => { try { return [...document.querySelectorAll(sel)].some(e => e.textContent.toLowerCase().includes(String(text).toLowerCase())) } catch { return false } }
const visible = el => { if (!el || !el.isConnected) return false; const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2 }

function Coach({ lesson, screen, project }) {
  const ui = useUI()
  const look = useUi()
  const def = lessonById(lesson.id)
  const step = def && def.steps[lesson.step]
  const t = useTest()
  const [, tick] = useState(0)
  const base = useRef(snapshotOf(project))
  const [box, setBox] = useState(null)
  useEffect(() => { base.current = snapshotOf(project) }, [lesson.n, lesson.step])
  useEffect(() => { const i = setInterval(() => tick(n => n + 1), 350); return () => clearInterval(i) }, [])
  const running = !!(t.busy || (t.status && t.status.run && t.status.run.status === 'running'))
  const done = stepDone(step, { screen, project, base: base.current, test: running, exists: s => { try { return !!document.querySelector(s) } catch { return false } }, textIn })
  const last = def && lesson.step >= def.steps.length - 1
  const next = () => { if (last) { endLesson(); ui.say(tr('lesson_finished')) } else gotoStep(lesson.step + 1) }
  useEffect(() => { if (done && !last) { const id = setTimeout(next, 800); return () => clearTimeout(id) } }, [done, lesson.step])
  useEffect(() => {
    const el = step ? findTarget(step.target) : null
    if (!el) { if (box) setBox(null); return }
    const r = el.getBoundingClientRect()
    const nb = { x: r.left, y: r.top, w: r.width, h: r.height }
    if (!box || Math.abs(box.x - nb.x) > 1 || Math.abs(box.y - nb.y) > 1 || Math.abs(box.w - nb.w) > 1 || Math.abs(box.h - nb.h) > 1) setBox(nb)
  })
  useEffect(() => {
    const k = e => { if (e.key === 'Escape' && !document.querySelector('[role=dialog],[role=alertdialog],.menu')) endLesson() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])
  if (!def || !step) return null
  const z = look.prefs.scale / 100
  // the card sits under the target, or above it when there is no room, or at the bottom when nothing is pointed at
  const vw = window.innerWidth / z, vh = window.innerHeight / z
  const b = box && { x: box.x / z, y: box.y / z, w: box.w / z, h: box.h / z }
  let pos = { left: '50%', bottom: 44, transform: 'translateX(-50%)' }
  if (b) {
    const left = Math.max(12, Math.min(vw - 560, b.x))
    pos = b.y + b.h + 70 < vh ? { left, top: b.y + b.h + 10 } : { left, top: Math.max(8, b.y - 58) }
  }
  return <>
    {b && <div className="coach-ring" style={{ left: b.x - 3, top: b.y - 3, width: b.w + 6, height: b.h + 6 }} aria-hidden="true" />}
    <div className={'coach' + (done ? ' done' : '')} style={pos} role="status" aria-live="polite" aria-label={def.title}>
      <span className="coach-n">{lesson.step + 1}/{def.steps.length}</span>
      <span className="coach-t">{done ? <span className="coach-ok" aria-hidden="true">{'✓'} </span> : null}{step.text}</span>
      <button className="sm primary" onClick={next} disabled={!!step.done && !done} aria-label={last ? 'Finish the lesson' : 'Next step'}>{last ? 'Done' : 'Next'}</button>
      <button className="sm" onClick={endLesson}>{tr('skip_3da474')}</button>
    </div>
  </>
}

function Offer() {
  return <div className="scrim" style={{ zIndex: 60 }}>
    <div className="dialog" role="alertdialog" aria-label={tr('take_a_short_tour')}>
      <div className="dt">{tr('place_your_first_crate')}</div>
      <div className="dd">{tr('a_five_minute_tour_of_the')}</div>
      <div className="da"><button autoFocus onClick={() => answerOffer(false)}>{tr('not_now')}</button><button className="primary" onClick={() => answerOffer(true)}>{tr('show_me')}</button></div>
    </div>
  </div>
}

function News({ ready, busy }) {
  const entries = useMemo(() => parseChangelog(changelogText), [])
  const [list, setList] = useState(null)
  useEffect(() => {
    if (!ready || busy || list || new URLSearchParams(location.search).get('news') === 'off') return
    const seen = savedHelp().seen || null
    const u = unseen(entries, seen)
    if (u.length && (!seen || u[0].version !== seen)) setList(u)
    else if (!seen) saveHelp({ seen: newest(entries) })
  }, [ready, busy])
  if (!list) return null
  const close = more => { saveHelp({ seen: newest(entries) }); setList(null); if (more) openHelp({ tab: 'new' }) }
  return <div className="scrim" style={{ zIndex: 60 }}>
    <div className="dialog news" role="alertdialog" aria-label={tr('what_s_new')}>
      <div className="dt">{tr('what_s_new')}</div>
      {list.map(e => <section key={e.version}><h4>{e.version}</h4><ul>{e.items.slice(0, 6).map(x => <li key={x}>{x}</li>)}</ul></section>)}
      <div className="da"><button onClick={() => close(true)}>{tr('open_help')}</button><button className="primary" autoFocus onClick={() => close(false)}>{tr('close')}</button></div>
    </div>
  </div>
}

export default function Onboarding({ screen, project, ready }) {
  const { lesson, offer, help } = useHelpStore()
  return <>
    {lesson && <Coach lesson={lesson} screen={screen} project={project} />}
    {offer && !lesson && <Offer />}
    <News ready={ready} busy={!!lesson || offer || help.open} />
  </>
}
