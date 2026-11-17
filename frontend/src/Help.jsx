import React, { useEffect, useMemo, useRef, useState } from 'react'
import guideHtml from '../../guide/TOD Mod Studio Guide.html?raw'
import changelogText from './changelog.md?raw'
import { useHelpStore, closeHelp, setHelpTab } from './helpstore.js'
import { indexGuide, searchIndex, searchGlossary } from './helpdata.js'
import { LESSONS } from './lessons.js'
import { parseChangelog } from './whatsnew.js'
import { startLesson } from './helpstore.js'
import { useUi } from './uistore.js'
import { post } from './api.js'
import { emptyProject } from './project.js'
import { jumpTo } from './problemsStore.js'
import { useUI, Seg } from './ui.jsx'
import { t } from './i18n.js'
import { t as tr } from './i18n.js'

const TABS = [{ id: 'guide', label: tr('guide') }, { id: 'lessons', label: tr('lessons') }, { id: 'examples', label: tr('examples') }, { id: 'glossary', label: tr('glossary') }, { id: 'new', label: tr('what_s_new') }]
const EXAMPLES = [{ id: 'level', title: tr('a_level_tweak'), text: tr('two_invisible_walls_in_the_jungle') }, { id: 'tuning', title: tr('a_tuning_tweak'), text: tr('a_bigger_clip_and_a_faster') },
  { id: 'race', title: tr('a_race_in_the_yard'), text: tr('a_checkpoint_race_on_the_sample') }]

// wrap the words in <mark> inside one guide section (from its heading to the next heading)
function markWords(doc, id, words) {
  doc.querySelectorAll('mark.hit').forEach(m => m.replaceWith(...m.childNodes))
  doc.body.normalize()
  const head = doc.getElementById(id)
  if (!head || !words.length) return
  const re = new RegExp('(' + words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'ig')
  const roots = []
  for (let n = head.nextElementSibling; n && !/^H[23]$/.test(n.tagName); n = n.nextElementSibling) roots.push(n)
  roots.push(head)
  for (const r of roots) {
    const tw = doc.createTreeWalker(r, NodeFilter.SHOW_TEXT)
    const nodes = []
    while (tw.nextNode()) nodes.push(tw.currentNode)
    for (const tn of nodes) {
      if (!re.test(tn.nodeValue)) { re.lastIndex = 0; continue }
      re.lastIndex = 0
      const span = doc.createElement('span')
      span.innerHTML = tn.nodeValue.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(re, '<mark class="hit">$1</mark>')
      tn.replaceWith(...span.childNodes)
    }
  }
}

function GuideFrame({ target, words }) {
  const ref = useRef(null)
  const ui = useUi()
  const [loaded, setLoaded] = useState(false)
  const style = () => {
    const d = ref.current && ref.current.contentDocument
    if (!d || !d.documentElement || !d.body) return null
    d.documentElement.setAttribute('data-theme', ui.resolved)
    d.body.style.zoom = String(ui.prefs.text / 100)
    return d
  }
  useEffect(() => { if (loaded) style() }, [loaded, ui.resolved, ui.prefs.text])
  useEffect(() => {
    if (!loaded || !target) return
    const d = style()
    if (!d) return
    markWords(d, target.id, words)
    const el = d.getElementById(target.id)
    if (el) el.scrollIntoView({ block: 'start', behavior: ui.reduced ? 'auto' : 'smooth' })
  }, [loaded, target])
  return <iframe ref={ref} className="help-frame" title={t('guide')} sandbox="allow-same-origin" srcDoc={guideHtml} onLoad={() => setLoaded(true)} />
}

function GuideTab({ index, query, target, setTarget }) {
  const results = useMemo(() => searchIndex(index, query), [index, query])
  const words = useMemo(() => query.toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length > 1), [query])
  const searching = query.trim().length > 0
  const first = results.length ? results[0].id : null
  useEffect(() => { if (searching && first && !(target && results.some(r => r.id === target.id))) setTarget({ id: first, n: Date.now() }) }, [first, searching])
  return (
    <div className="help-guide">
      <nav className="help-toc" aria-label={searching ? 'Search results' : 'Contents'}>
        {searching && !results.length && <div className="help-none">{t('nothing_found')}</div>}
        {searching ? results.map(r => <button key={r.id} className={'help-hit' + (target?.id === r.id ? ' on' : '')} onClick={() => setTarget({ id: r.id, n: Date.now() })}>
          <b>{r.title}</b><span>{r.snippet}</span></button>)
          : index.map(s => <button key={s.id} className={'help-toc-i l' + s.level + (target?.id === s.id ? ' on' : '')} onClick={() => setTarget({ id: s.id, n: Date.now() })}>{s.title}</button>)}
      </nav>
      <GuideFrame target={target} words={words} />
    </div>
  )
}

function Lessons({ go }) {
  return <div className="help-list" role="list">
    {LESSONS.map((l, i) => <div key={l.id} className="help-row" role="listitem">
      <div className="grow"><div className="help-t">{l.title}</div><div className="help-s">{l.steps.length}{' '}{t('steps')}</div></div>
      <button className={i === 0 ? 'primary' : ''} onClick={() => { startLesson(l.id) }}>{t('start')}</button></div>)}
  </div>
}

function Examples({ project, dirty, loadProject, go }) {
  const ui = useUI()
  const [busy, setBusy] = useState(null)
  const open = async id => {
    setBusy(id)
    try {
      const r = await post('/api/starters/open', { id })
      if (r.kind === 'mod') {
        if (dirty && !(await ui.confirm({ title: t('open_this_example'), body: t('the_changes_you_have_not_saved'), ok: t('open_the_example'), danger: false }))) return
        loadProject({ ...emptyProject(), ...r.mod }); closeHelp(); go(r.screen)
      } else { closeHelp(); jumpTo({ screen: r.screen, sample: r.sample }) }
    } catch (e) { ui.say(e.message, 'bad') } finally { setBusy(null) }
  }
  return <div className="help-list" role="list">
    {EXAMPLES.map(({ id, title, text }) => <div key={id} className="help-row" role="listitem">
      <div className="grow"><div className="help-t">{title}</div><div className="help-s">{text}</div></div>
      <button disabled={!!busy} onClick={() => open(id)}>{t('open')}</button></div>)}
  </div>
}

function Glossary({ query }) {
  const rows = useMemo(() => searchGlossary(query), [query])
  return <dl className="help-gloss" aria-label={t('glossary')}>
    {rows.map(g => <div key={g.term}><dt>{g.term}</dt><dd>{g.def}</dd></div>)}
    {!rows.length && <div className="help-none">{t('nothing_found')}</div>}
  </dl>
}

function WhatsNew() {
  const entries = useMemo(() => parseChangelog(changelogText), [])
  return <div className="help-new">
    {entries.map(e => <section key={e.version}><h3>{e.version}</h3><ul>{e.items.map(x => <li key={x}>{x}</li>)}</ul></section>)}
  </div>
}

function trapTab(e, root) {
  if (e.key !== 'Tab' || !root) return
  const f = [...root.querySelectorAll('button:not(:disabled),input,a[href],[tabindex]:not([tabindex="-1"])')].filter(x => x.offsetParent !== null)
  if (!f.length) return
  const first = f[0], last = f[f.length - 1]
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
}

export default function HelpHost({ project, dirty, loadProject, go }) {
  const { help } = useHelpStore()
  if (!help.open) return null
  return <HelpWindow key={help.n} help={help} project={project} dirty={dirty} loadProject={loadProject} go={go} />
}

function HelpWindow({ help, project, dirty, loadProject, go }) {
  const ui = useUi()
  const [query, setQuery] = useState(help.query || '')
  const [target, setTarget] = useState(help.anchor ? { id: help.anchor, n: help.n } : null)
  const root = useRef(null)
  const index = useMemo(() => indexGuide(guideHtml), [])
  useEffect(() => {
    const back = document.activeElement
    const k = e => { if (e.key === 'Escape') { e.stopPropagation(); closeHelp() } }
    window.addEventListener('keydown', k, true)
    return () => { window.removeEventListener('keydown', k, true); try { back && back.focus && back.focus() } catch { /* gone */ } }
  }, [])
  useEffect(() => { root.current && root.current.querySelector('input[type=search]')?.focus() }, [])
  const tab = help.tab
  const onQuery = v => { setQuery(v); if (v.trim() && tab !== 'guide' && tab !== 'glossary') setHelpTab('guide') }
  return (
    <div className="scrim help-scrim" onMouseDown={e => { if (e.target === e.currentTarget) closeHelp() }}>
      <div className="help" role="dialog" aria-modal="true" aria-label={t('help')} ref={root} onKeyDown={e => trapTab(e, root.current)}>
        <div className="help-head">
          <div className="help-title">{t('help')}</div>
          <input type="search" className="help-search" aria-label={t('search_the_guide')} placeholder={t('search')} value={query} onChange={e => onQuery(e.target.value)} />
          <Seg value={ui.prefs.mode} onChange={m => ui.set({ mode: m })} options={[{ value: 'beginner', label: tr('beginner') }, { value: 'advanced', label: tr('advanced') }]} />
          <button className="sm" onClick={closeHelp} aria-label={t('close_help')} title={t('close_esc')}>{'✕'}</button>
        </div>
        <div className="help-tabs" role="tablist" aria-label={t('help_sections')}>
          {TABS.map(({ id: k, label: l }) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setHelpTab(k)}>{l}</button>)}
        </div>
        <div className="help-main" role="tabpanel" aria-label={(TABS.find(x => x.id === tab) || TABS[0]).label}>
          {tab === 'guide' && <GuideTab index={index} query={query} target={target} setTarget={setTarget} />}
          {tab === 'lessons' && <Lessons go={go} />}
          {tab === 'examples' && <Examples project={project} dirty={dirty} loadProject={loadProject} go={go} />}
          {tab === 'glossary' && <Glossary query={query} />}
          {tab === 'new' && <WhatsNew />}
        </div>
      </div>
    </div>
  )
}

export function HelpButton({ onClick }) {
  return <button className="helpbtn" onClick={onClick} aria-label={t('help')} title={t('help_f1')}>?</button>
}
