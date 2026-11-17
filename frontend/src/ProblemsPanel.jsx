// The Problems list: errors and warnings of the current project in one place. A row jumps to its cause.
import React, { useEffect } from 'react'
import { jumpTo, setOpen, useStore } from './problemsStore.js'
import { t } from './i18n.js'

export function ProblemsBadge({ data, onClick, label = 'Problems' }) {
  const e = data?.errors || 0, w = data?.warnings || 0
  const tone = e ? 'bad' : w ? 'warn' : null
  return (
    <button className={'probbtn' + (e ? ' err' : '')} onClick={onClick} title={e || w ? `${e} error${e === 1 ? '' : 's'}, ${w} warning${w === 1 ? '' : 's'}` : 'No problems'}>
      {label}{(e || w) ? <span className={'pcount ' + tone}>{e + w}</span> : null}
    </button>
  )
}

export function ProblemsStatus({ data }) {
  const e = data?.errors || 0, w = data?.warnings || 0
  const tone = e ? 'var(--bad)' : w ? 'var(--warn)' : 'var(--ok)'
  return (
    <span className="it click" title={e || w ? `${e} error${e === 1 ? '' : 's'}, ${w} warning${w === 1 ? '' : 's'}` : 'No problems'} onClick={() => setOpen(true)}>
      <span className="dot" style={{ background: tone }} /><span aria-hidden="true">{e ? '✖' : w ? '▲' : '✓'}</span>{e || w ? <><b>{e + w}</b> <span className="t3">{e + w === 1 ? 'problem' : 'problems'}</span></> : <span className="t3">{t('no_problems')}</span>}
    </span>
  )
}

export default function ProblemsPanel({ data, kind }) {
  const st = useStore()
  useEffect(() => {
    if (!st.open) return
    const h = ev => { if (ev.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [st.open])
  if (!st.open) return null
  const list = data?.problems || []
  const e = data?.errors || 0, w = data?.warnings || 0
  return (
    <aside className="problems" role="complementary" aria-label={t('problems')}>
      <div className="ph">
        <b>{t('problems')}</b>
        {e > 0 && <span className="pcount bad" title={t('errors')}><span aria-hidden="true">✖ </span>{e}<span className="sr-only">{' '}{t('errors')}</span></span>}{w > 0 && <span className="pcount warn" title={t('warnings')}><span aria-hidden="true">▲ </span>{w}<span className="sr-only">{' '}{t('warnings')}</span></span>}
        <div style={{ flex: 1 }} />
        <button className="sm" onClick={() => setOpen(false)} aria-label={t('close')}>{t('close')}</button>
      </div>
      <div className="pl" role="list" aria-label={t('problems_list')}>
        {!data && <div className="muted small" style={{ padding: 12 }}>{t('looking')}{'…'}</div>}
        {data && !list.length && <div className="muted small" style={{ padding: 12 }}>{t('no_problems_97dd02')}</div>}
        {list.map(p => (
          <div key={p.id} className={'prow ' + (p.level === 'error' ? 'err' : 'wrn')} role="listitem" tabIndex={0} title={[p.detail, 'Click to go there'].filter(Boolean).join('\n')}
               onClick={() => { jumpTo(p.jump); if (window.innerWidth < 1100) setOpen(false) }} onKeyDown={ev => { if (ev.key === 'Enter') jumpTo(p.jump) }}>
            <span className="pdot" aria-hidden="true">{p.level === 'error' ? '✖' : '▲'}</span><span className="sr-only">{p.level === 'error' ? 'Error: ' : 'Warning: '}</span>
            <span className="pt">{p.title}</span>
            <span className="ps">{p.source}</span>
          </div>))}
      </div>
    </aside>
  )
}
