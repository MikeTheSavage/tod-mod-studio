// The "Test in game" control: one button, the five steps as small bars, Stop while the game runs. Used in the editor bar, the mod library
// bar and the Debug area.
import React from 'react'
import { Menu, useUI } from './ui.jsx'
import { useTest, startTest, stopTest, STEPS, STEP_LABEL } from './testStore.js'
import { t as tr } from './i18n.js'

export const fmtBytes = n => n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n >= 1048576 ? Math.round(n / 1048576) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'

export function Dots({ steps }) {
  return <span className="tdots" role="img" aria-label={tr('test_steps')}>
    {steps.map((s, i) => <i key={STEPS[i]} className={s.tone} title={STEP_LABEL[STEPS[i]] + (s.note ? ': ' + s.note : '')} />)}</span>
}

export const confirmFullCopy = ui => plan => ui.confirm({ title: tr('make_a_full_copy_of_the'), body: `${fmtBytes(plan.extra_bytes)} on ${plan.dest}`, ok: tr('make_the_copy'), danger: false })

export function useTestActions(project) {
  const ui = useUI()
  const run = async (opts = {}) => {
    try { return await startTest({ project, confirmFull: confirmFullCopy(ui), ...opts }) } catch (e) { ui.say(e.message, 'bad'); return null }
  }
  const real = async () => {
    if (!(await ui.confirm({ title: tr('test_in_your_own_game'), body: tr('the_mod_goes_into_your_game'), kept: tr('your_saves_are_copied_first_and'), ok: tr('install_and_play'), danger: false }))) return null
    return run({ real: true })
  }
  return { run, real }
}

export default function TestControl({ project, go, className = '', primary }) {
  const t = useTest()
  const act = useTestActions(project)
  const run = t.status?.run
  const running = run?.status === 'running'
  const crashed = run?.status === 'exited' && run.crash
  const cur = t.steps.find(s => s.tone === 'busy')
  if (t.busy) return <span className={'tctl ' + className}><Dots steps={t.steps} /><span className="small muted" title={cur?.note}>{STEP_LABEL[STEPS[t.steps.indexOf(cur)]] || 'Starting'}{'…'}</span></span>
  if (running) return <span className={'tctl ' + className}><Dots steps={t.steps} /><span className="small">{tr('game_is_running')}</span><button className="sm" onClick={() => stopTest().catch(() => {})}>{tr('stop')}</button></span>
  return (
    <span className={'tctl ' + className}>
      {crashed && <button className="sm danger" title={run.crash.why} onClick={() => go?.('debug')}>{tr('crashed')}</button>}
      <span className="splitbtn">
        <button className={primary ? 'primary' : 'soft'} onClick={() => act.run()} title={tr('check_build_put_it_in_a')}>{tr('test_in_game')}</button>
        <Menu right buttonClass={primary ? 'primary' : 'soft'} label={'▾'} title={tr('more')}>{close => <>
          <div className="item" onClick={() => { close(); go?.('debug') }}>{tr('test_settings')}{'…'}</div>
          <div className="item" onClick={() => { close(); act.real() }}>{tr('test_in_my_own_game')}{'…'}</div></>}</Menu>
      </span>
    </span>
  )
}
