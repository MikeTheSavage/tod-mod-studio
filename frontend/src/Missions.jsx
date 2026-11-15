// Mission graph editor (companion tools part B, same core as the Unreal TOD Level Editor plugin's Mission Graph tab):
// a mission's trigger trees as cards (conditions with their event codes and activators, actions with their ActionType,
// target and delay) and lines from an action to the trigger it acts on. Edit values, rewire which trigger fires an
// action, retarget it, disable a trigger, add a trigger from a template, and check the build with missiontool's lint.
// The edits are the mod's "missions" ops.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, runJob } from './api.js'
import { short, describeMission, newId } from './partb.js'

const M10 = 'data_pc/overdose_the_game/overdose/shared/mm010_ernestocruz.mission'
const CW = 300, ROWH = 15, HEAD = 34, GAPX = 90, GAPY = 26

function cardHeight(t) { return HEAD + (t.conditions.length + t.actions.length) * ROWH + 10 }

function layout(triggers) {
  const cols = {}
  for (const t of triggers) (cols[t.column ?? 0] ||= []).push(t)
  const pos = {}
  for (const [c, list] of Object.entries(cols)) {
    let y = 0
    list.sort((a, b) => (a.row ?? 0) - (b.row ?? 0))
    for (const t of list) { pos[t.id] = { x: Number(c) * (CW + GAPX), y, h: cardHeight(t) }; y += pos[t.id].h + GAPY }
  }
  return pos
}

export default function Missions({ status, project, commit }) {
  const [catalog, setCatalog] = useState(null)
  const [entry, setEntry] = useState(M10)
  const [graph, setGraph] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [sel, setSel] = useState(null)              // {tid, kind: 'trigger'|'cond'|'act', node}
  const [rewiring, setRewiring] = useState(null)    // action being rewired
  const [onlyEdited, setOnlyEdited] = useState(() => !!new URLSearchParams(location.search).get('edited'))
  const [check, setCheck] = useState(null)
  const [prop, setProp] = useState('')
  const [val, setVal] = useState('')
  const [tpl, setTpl] = useState({ template: 'go_to_point', name: 'CB_GoTo', pos: '-495, -139, -2185', size: '6, 4, 6', yaw: 0,
    objective: 'MM010_GetToAirstrip_OBJ', action: '', text: '', count: 3, seconds: 5, target: '', camera: '', hold: 3 })
  const ops = project.missions || []
  const setOps = o => commit({ ...project, missions: o })
  const [view, setView] = useState(() => ({ x: 20, y: 20, s: new URLSearchParams(location.search).get('edited') ? 1.9 : 0.8 }))
  const drag = useRef(null)

  useEffect(() => { get('/api/catalog').then(setCatalog).catch(e => setMsg(e.message)) }, [])
  const missions = useMemo(() => (catalog?.maps || []).flatMap(m => m.missions.map(x => ({ ...x, map: m.title }))), [catalog])
  const load = async (lint) => {
    try {
      const g = await runJob('/api/missions/graph', { entry, ops, lint: !!lint }, j => setBusy(j.message || 'Reading the mission'))
      setGraph(g)
    } catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  useEffect(() => { load(true) }, [entry, JSON.stringify(ops)])

  const trig = graph?.triggers || []
  const editedIds = useMemo(() => {
    const s = new Set()
    for (const o of ops) {
      if (o.entry !== entry) continue
      for (const t of trig) {
        if (t.new || t.node === o.node || t.actions.some(a => a.node === o.action || a.node === o.node || a.rewired_from) ||
            t.conditions.some(c => c.node === o.node) || (o.to && t.node === o.to.node)) s.add(t.id)
      }
    }
    return s
  }, [graph, ops])
  const shown = onlyEdited ? trig.filter(t => editedIds.has(t.id)) : trig
  const pos = useMemo(() => layout(onlyEdited ? shown.map((t, i) => ({ ...t, column: i % 3, row: Math.floor(i / 3) })) : shown), [graph, onlyEdited])
  const byId = Object.fromEntries(trig.map(t => [t.id, t]))
  const selT = sel ? byId[sel.tid] : null
  const selRow = selT && sel.kind === 'cond' ? selT.conditions.find(c => c.node === sel.node)
    : selT && sel.kind === 'act' ? selT.actions.find(a => a.node === sel.node) : null

  const clickCard = (t, kind, node) => {
    if (rewiring && kind === 'trigger') {
      if (t.frag !== rewiring.frag) { setMsg('Rewire works inside one fragment (the action keeps its node; only its parent changes).'); return }
      setOps([...ops.filter(o => !(o.op === 'rewire' && o.action === rewiring.node)),
        { op: 'rewire', entry, frag: rewiring.fragFull, action: rewiring.node, to: { frag: t.frag, node: t.node } }])
      setRewiring(null); return
    }
    setSel({ tid: t.id, kind, node })
  }
  const fragFull = t => t.path ? t.frag : t.frag
  const setValue = () => {
    if (!sel || !prop) return
    let v = val
    try { v = JSON.parse(val) } catch { /* bare string */ }
    const node = sel.kind === 'trigger' ? selT.node : sel.node
    const isNew = !/^0x/i.test(node)
    setOps([...ops.filter(o => !(o.op === 'set' && (o.node === node || o.id === node) && o.prop === prop)),
      isNew ? { op: 'set', entry, frag: selT.frag, id: node, prop, value: v }
            : { op: 'set', entry, frag: selT.frag, node, prop, value: v }])
  }
  const retarget = () => {
    if (!selRow || sel.kind !== 'act') return
    const name = prompt('TargetName (an entity name; FindNode, first match):', selRow.target_name || '')
    if (name == null) return
    setOps([...ops.filter(o => !(o.op === 'retarget' && o.action === sel.node)), { op: 'retarget', entry, frag: selT.frag, action: sel.node, target: name, who: 3 }])
  }
  const disable = () => { if (selT && !selT.new) setOps([...ops, { op: 'disable_trigger', entry, frag: selT.frag, node: selT.node }]) }
  const addTrigger = () => {
    const T = graph?.enums?.TEMPLATES?.[tpl.template] || {}
    const params = {}
    for (const k of ['objective', 'count', 'seconds', 'target', 'camera', 'hold', 'text']) if (tpl[k] !== '' && tpl[k] != null) params[k] = isNaN(Number(tpl[k])) || k === 'objective' || k === 'target' || k === 'camera' ? tpl[k] : Number(tpl[k])
    if (tpl.action) params.action = tpl.action
    const o = { op: 'add_trigger', id: newId('trg'), entry, template: tpl.template, name: tpl.name || undefined, params }
    if (['go_to_point', 'spawn_group', 'camera_cut', 'objective_text'].includes(tpl.template)) {
      o.pos = tpl.pos.split(',').map(Number); o.size = tpl.size.split(',').map(Number); o.yaw = Number(tpl.yaw) || 0
    }
    if (T.needs) for (const k of T.needs) if (params[k] == null && !(k === 'objective' && params.action && !params.action.includes('objective'))) { setMsg(`${T.label} needs ${k}`); return }
    setOps([...ops, o])
  }
  const runCheck = async () => {
    setCheck(null)
    try { setCheck(await runJob('/api/partb/check', { mod: project, kinds: ['missions'] }, j => setBusy(j.message || 'Building and linting'))) }
    catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  const wheel = e => { const f = e.deltaY < 0 ? 1.12 : 1 / 1.12; setView(v => ({ ...v, s: Math.min(2.5, Math.max(0.15, v.s * f)) })) }
  const down = e => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y } }
  const move = e => { if (drag.current) setView(v => ({ ...v, x: drag.current.vx + e.clientX - drag.current.x, y: drag.current.vy + e.clientY - drag.current.y })) }
  const up = () => { drag.current = null }
  const props = sel?.kind === 'trigger' ? ['TriggerOn', 'ConditionsNeeded', 'Reactivate', 'ReactivateDelay', 'flags', 'name', 'width', 'height', 'length']
    : sel?.kind === 'cond' ? ['TrueOn', 'ActivatorType', 'SpecificActivator', 'IntervalTrue', 'TrigAmount', 'APBonus']
    : sel?.kind === 'act' ? ['ActionType', 'TargetName', 'ActivateWho', 'Delay', 'FeedbackText', 'ActivationTime', 'Do_What', 'APBonus'] : []
  const lint = graph?.lint

  return (
    <div className="editor mgraph" style={{ gridTemplateColumns: '1fr 360px' }}>
      <div className="viewport" style={{ background: '#151a21' }}>
        <div className="toolbar">
          <select value={entry} onChange={e => { setEntry(e.target.value); setSel(null) }}>
            {missions.map(m => <option key={m.entry} value={m.entry}>{m.title} ({short(m.entry)})</option>)}
            {!missions.length && <option value={M10}>MM010 Ernesto Cruz</option>}</select>
          <button onClick={() => setOnlyEdited(false)} className={!onlyEdited ? 'on' : ''}>All triggers ({trig.length})</button>
          <button onClick={() => setOnlyEdited(true)} className={onlyEdited ? 'on' : ''}>Edited ({editedIds.size})</button>
          <span className="lbl">Drag to pan, wheel to zoom. Green: new, yellow: rewired or edited.{rewiring && <b> Click the trigger that should fire {rewiring.node}.</b>}</span>
        </div>
        <svg style={{ position: "absolute", top: 34, left: 0, width: "100%", height: "calc(100% - 34px)" }} onWheel={wheel} onMouseDown={down} onMouseMove={move} onMouseUp={up} onMouseLeave={up}>
          <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#8fb3ff" /></marker></defs>
          <g transform={`translate(${view.x},${view.y}) scale(${view.s})`}>
            {(graph?.edges || []).map((e, i) => {
              const a = pos[e.src], b = pos[e.dst], t = byId[e.src]
              if (!a || !b || !t) return null
              const k = t.conditions.length + t.actions.findIndex(x => x.node === e.action)
              const y1 = a.y + HEAD + k * ROWH + 6, x1 = a.x + CW, x2 = b.x, y2 = b.y + 16
              const back = x2 <= x1
              const d = back ? `M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}` : `M${x1},${y1} C${x1 + 45},${y1} ${x2 - 45},${y2} ${x2},${y2}`
              return <path key={i} d={d} fill="none" stroke={back ? '#6b7d99' : '#8fb3ff'} strokeWidth={1.4} markerEnd="url(#arr)" opacity={0.8}><title>{e.kind}</title></path>
            })}
            {shown.map(t => {
              const p = pos[t.id]; if (!p) return null
              const edited = editedIds.has(t.id)
              const fill = t.new ? '#173b26' : t.disabled ? '#2a2a2a' : '#1f2733'
              const stroke = t.new ? '#3cff8a' : edited ? '#ffd166' : sel?.tid === t.id ? '#ffffff' : (graph.starts || []).includes(t.id) ? '#ff9f1c' : '#3b4a5e'
              return <g key={t.id} transform={`translate(${p.x},${p.y})`}>
                <rect width={CW} height={p.h} rx={6} fill={fill} stroke={stroke} strokeWidth={edited || t.new ? 2.5 : 1.2}
                  onClick={ev => { ev.stopPropagation(); clickCard(t, 'trigger', t.node) }} />
                <text x={8} y={15} fill="#e8eef7" fontSize={12} fontWeight="bold">{(t.name || t.node).slice(0, 38)}{t.disabled ? ' (disabled)' : ''}</text>
                <text x={8} y={28} fill="#9fb0c4" fontSize={10}>{t.cls}{t.base} {String(t.trigger_on || '').slice(0, 26)}{t.reactivate ? ' re-arms' : ''}</text>
                {t.conditions.map((c, i) => <text key={c.node} x={10} y={HEAD + i * ROWH + 10} fontSize={10}
                  fill={sel?.node === c.node ? '#ffffff' : '#7fd1ff'} onClick={ev => { ev.stopPropagation(); clickCard(t, 'cond', c.node) }}>
                  IF {String(c.event).slice(0, 30)}{c.activator ? ' by ' + String(c.activator).split(' ').slice(0, 3).join(' ') : ''}</text>)}
                {t.actions.map((a, i) => <text key={a.node} x={10 + (a.depth || 0) * 8} y={HEAD + (t.conditions.length + i) * ROWH + 10} fontSize={10}
                  fill={a.rewired_from ? '#ffd166' : a.new ? '#3cff8a' : sel?.node === a.node ? '#ffffff' : '#ffc9a3'}
                  onClick={ev => { ev.stopPropagation(); clickCard(t, 'act', a.node) }}>
                  DO {a.short} {a.code ?? ''}: {String(a.does || '').split(/[:(;]/)[0].slice(0, 22)} {'-> ' + String(a.target_name || a.target || '').slice(0, 22)}{a.delay ? ` +${a.delay}s` : ''}</text>)}
              </g>
            })}
          </g>
        </svg>
      </div>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>Selection</h3>
          {!sel && <p className="muted">Click a card (the trigger), an IF row (a condition) or a DO row (an action).</p>}
          {selT && <div>
            <p><b>{selT.name}</b> <span className="muted">{selT.frag} {selT.node}</span></p>
            {selRow && <pre className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{JSON.stringify(selRow, null, 1).slice(0, 900)}</pre>}
            <div className="row"><select value={prop} onChange={e => setProp(e.target.value)}><option value="">set a value</option>
              {props.map(p => <option key={p}>{p}</option>)}</select>
              <input value={val} onChange={e => setVal(e.target.value)} style={{ width: 90 }} /><button onClick={setValue} disabled={!prop}>Set</button></div>
            <div className="btns">
              {sel.kind === 'act' && !selRow?.new && <button onClick={() => setRewiring({ node: sel.node, frag: selT.frag, fragFull: fragFull(selT) })}>Rewire to another trigger</button>}
              {sel.kind === 'act' && <button onClick={retarget}>Retarget</button>}
              {sel.kind === 'trigger' && !selT.new && <button onClick={disable}>Disable trigger</button>}
            </div>
          </div>}
        </section>
        <section className="box">
          <h3>New trigger from a template</h3>
          <div className="row"><select value={tpl.template} onChange={e => setTpl({ ...tpl, template: e.target.value })}>
            {Object.entries(graph?.enums?.TEMPLATES || {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div>
          <p className="muted">{graph?.enums?.TEMPLATES?.[tpl.template]?.help}</p>
          {['name', 'pos', 'size', 'yaw', 'objective', 'text', 'count', 'seconds', 'target', 'camera', 'hold'].map(k =>
            <label key={k} className="kv">{k}<input value={tpl[k]} onChange={e => setTpl({ ...tpl, [k]: e.target.value })} /></label>)}
          <label className="kv">action<select value={tpl.action} onChange={e => setTpl({ ...tpl, action: e.target.value })}>
            <option value="">(template default: {graph?.enums?.TEMPLATES?.[tpl.template]?.action})</option>
            {(graph?.enums?.ACTION_KINDS || []).map(a => <option key={a}>{a}</option>)}</select></label>
          <button onClick={addTrigger}>Add trigger</button>
        </section>
        <section className="box">
          <h3>Edits <span className="badge">{ops.length}</span></h3>
          <ol className="changes">{ops.map((o, i) => <li key={i}>{describeMission(o)} <button onClick={() => setOps(ops.filter((_, j) => j !== i))}>x</button></li>)}</ol>
          <button className="primary" onClick={runCheck} disabled={!ops.length}>Check (build + missiontool lint)</button>
          {lint && <p className="muted">missiontool lint of the shipped block: {lint.length} issues (leftover targets of the original data).</p>}
        </section>
        {check && <section className="box"><h3>Check: {check.result}</h3>
          <ul className="checklist">{check.lines.map((l, i) => <li key={i} className={l.level}><b>{l.area}</b> {l.text}</li>)}</ul></section>}
        <section className="box"><p className="muted">Save safety: values, rewires (an action's parent), retargets and disabling change
          existing objects only. A new trigger (root, condition, action) is appended after the last object of the mission block,
          so every existing object keeps its creation index and old saves still load.</p></section>
      </aside>
      {busy && <div className="busy">{busy}</div>}
      {msg && <div className="error" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}
