// Mission graph editor (companion tools part B):
// a mission's trigger trees as cards (conditions with their event codes and activators, actions with their ActionType,
// target and delay) and lines from an action to the trigger it acts on. Edit values, rewire which trigger fires an
// action, retarget it, disable a trigger, add a trigger from a template, and check the build with missiontool's lint.
// The edits are the mod's "missions" ops.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import { short, describeMission, newId } from './partb.js'
import View3D from './View3D.jsx'
import { useBundle, pickOfBlock, boundsOf, CONTEXT_LAYERS } from './levelLoad.js'
import { t as tr } from './i18n.js'
import { boxOf, clampView, moved, wheelFactor, zoomAt } from './graphview.js'

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
  const [tpl, setTpl] = useState({ template: 'go_to_point', name: 'CB_GoTo', pos: '', size: '6, 4, 6', yaw: 0,
    objective: 'MM010_GetToAirstrip_OBJ', action: '', text: '', count: 3, seconds: 5, target: '', camera: '', hold: 3,
    ap: '', weapon: '', ammo: '', pickups: [] })
  const [texts, setTexts] = useState([])
  const [guns, setGuns] = useState({})
  const [pinning, setPinning] = useState(false)
  const ops = project.missions || []
  const setOps = o => commit({ ...project, missions: o })
  const [view, setView] = useState(() => ({ x: 20, y: 20, s: new URLSearchParams(location.search).get('edited') ? 1.9 : 0.8 }))
  const drag = useRef(null), justPanned = useRef(false)
  const [panning, setPanning] = useState(false)
  const [showMap, setShowMap] = useState(() => new URLSearchParams(location.search).get('showmap') === '1')
  const [focus3, setFocus3] = useState(null)

  useEffect(() => { get('/api/catalog').then(c => {
    setCatalog(c)
    const want = new URLSearchParams(location.search).get('block')
    const hit = want && (c.maps || []).flatMap(m => [...m.sections, ...m.missions]).find(x => short(x.entry) === want)
    if (hit) setEntry(hit.entry)
  }).catch(e => setMsg(e.message)) }, [])
  useEffect(() => {
    post('/api/missions/texts', {}).then(r => setTexts(r.texts || [])).catch(() => {})
    get('/api/enums').then(r => setGuns(r.WeaponSubType || {})).catch(() => {})
  }, [])
  const missions = useMemo(() => (catalog?.maps || []).flatMap(m => m.missions.map(x => ({ ...x, map: m.title }))), [catalog])
  const loadId = useRef(0)
  const load = async (lint) => {
    const id = ++loadId.current                              // an older answer never replaces a newer pick
    try {
      const g = await runJob('/api/missions/graph', { entry, ops, lint: !!lint }, j => setBusy(j.message || 'Reading the mission'))
      if (id === loadId.current) setGraph(g)
    } catch (e) { if (id === loadId.current) setMsg(e.message) }
    if (id === loadId.current) setBusy(null)
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
  // where the triggers are: the mission's own map in 3D, a box or ring for every trigger
  const mapPick = useMemo(() => (showMap && catalog ? pickOfBlock(catalog, entry) : null), [showMap, catalog, entry])
  const lvl = useBundle(mapPick, !!mapPick)
  const overlays = useMemo(() => trig.filter(t => t.pos).map(t => {
    const color = t.new ? '#3cff8a' : editedIds.has(t.id) ? '#ffd166' : (graph?.starts || []).includes(t.id) ? '#ff9f1c' : t.disabled ? '#6b7280' : '#4cc9f0'
    const tagOf = t.new ? 'NEW' : editedIds.has(t.id) ? 'EDITED' : (graph?.starts || []).includes(t.id) ? 'START' : ''
    const base = { id: t.id, color, label: (tagOf ? tagOf + ' · ' : '') + (t.name || t.node), selected: sel?.tid === t.id, opacity: 0.18 }
    if (t.box && t.box.every(v => v > 0)) return { ...base, kind: 'box', pos: t.pos, size: t.box }
    if (t.radius) return { ...base, kind: 'ring', pos: t.pos, radius: t.radius }
    return { ...base, kind: 'point', pos: t.pos }
  }), [graph, editedIds, sel?.tid])
  const mapFocus = useMemo(() => { const b = boundsOf(trig.filter(t => t.pos).map(t => t.pos), 30); return b ? { bounds: b, y: trig.find(t => t.pos)?.pos[1] ?? 0 } : null }, [graph, entry])
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
    if (t.pos) setFocus3({ pos: t.pos, dist: 40 })
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
  const textValue = v => {                                  // a line of the game (its number) or the user's own words
    const s = String(v ?? '').trim()
    if (!s) return null
    const hit = texts.find(x => x.text === s)
    return hit ? hit.i : /^\d+$/.test(s) ? Number(s) : s
  }
  const addTrigger = () => {
    const T = graph?.enums?.TEMPLATES?.[tpl.template] || {}
    const params = {}
    for (const k of T.needs || []) if (tpl[k] !== '' && tpl[k] != null) params[k] = isNaN(Number(tpl[k])) || k === 'objective' || k === 'target' || k === 'camera' ? tpl[k] : Number(tpl[k])
    if (T.box && tpl.template === 'camera_cut' && tpl.hold !== '') params.hold = Number(tpl.hold)
    const textVal = textValue(tpl.text)
    if (textVal != null) params.text = textVal
    if (Number(tpl.ap) > 0) params.ap = Number(tpl.ap)
    if (tpl.weapon !== '') { params.weapon = Number(tpl.weapon); params.ammo = Number(tpl.ammo) || 30 }
    if (tpl.pickups.length) params.pickups = tpl.pickups
    if (tpl.action && tpl.template !== 'car_enters') params.action = tpl.action
    const o = { op: 'add_trigger', id: newId('trg'), entry, template: tpl.template, name: tpl.name || undefined, params }
    if (T.box) {
      const pos = String(tpl.pos).split(',').map(Number), size = String(tpl.size).split(',').map(Number)
      if (pos.length !== 3 || pos.some(v => !isFinite(v) || String(tpl.pos).trim() === '')) { setMsg(tr('pick_a_place_on_the_map')); return }
      o.pos = pos; o.size = size.length === 3 && size.every(v => isFinite(v) && v > 0) ? size : [6, 4, 6]; o.yaw = Number(tpl.yaw) || 0
    }
    if (T.needs) for (const k of T.needs) if (params[k] == null && !(k === 'objective' && params.action && !params.action.includes('objective'))) { setMsg(`${T.label} needs ${k}`); return }
    if (tpl.template === 'car_enters' && !(params.text != null || params.ap || params.weapon != null || params.pickups)) { setMsg(tr('choose_a_text_a_reward_or_both')); return }
    setOps([...ops, o])
  }
  const runCheck = async () => {
    setCheck(null)
    try { setCheck(await runJob('/api/partb/check', { mod: project, kinds: ['missions'] }, j => setBusy(j.message || 'Building and linting'))) }
    catch (e) { setMsg(e.message) }
    setBusy(null)
  }
  // pan with a press-and-drag anywhere on the graph (the pointer is captured, so leaving the box never drops it),
  // zoom with the wheel around the cursor; a press that did not move still clicks the card under it
  const svgRef = useRef(null)
  const box = useMemo(() => boxOf(pos, CW), [pos])
  const fit = v => { const r = svgRef.current?.getBoundingClientRect(); return clampView(v, box, r ? r.width : 0, r ? r.height : 0) }
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = e => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      setView(v => fit(zoomAt(v, wheelFactor(e), e.clientX - r.left, e.clientY - r.top)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [box])
  const down = e => { if (e.button === 0 || e.button === 1) drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, on: false } }
  const move = e => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    if (!d.on) { if (!moved(d, { x: e.clientX, y: e.clientY })) return; d.on = true; try { svgRef.current.setPointerCapture(e.pointerId) } catch { /* the pointer is gone */ } setPanning(true) }
    const nx = d.vx + e.clientX - d.x, ny = d.vy + e.clientY - d.y
    setView(v => fit({ ...v, x: nx, y: ny }))
  }
  const up = e => {
    const d = drag.current
    if (!d || (e && d.id !== e.pointerId)) return
    drag.current = null
    if (d.on) { justPanned.current = true; setTimeout(() => { justPanned.current = false }, 0); try { svgRef.current.releasePointerCapture(d.id) } catch { /* already released */ } }
    setPanning(false)
  }
  const noClickAfterPan = e => { if (justPanned.current) { e.stopPropagation(); e.preventDefault() } }
  const props = sel?.kind === 'trigger' ? ['TriggerOn', 'ConditionsNeeded', 'Reactivate', 'ReactivateDelay', 'flags', 'name', 'width', 'height', 'length']
    : sel?.kind === 'cond' ? ['TrueOn', 'ActivatorType', 'SpecificActivator', 'IntervalTrue', 'TrigAmount', 'APBonus']
    : sel?.kind === 'act' ? ['ActionType', 'TargetName', 'ActivateWho', 'Delay', 'FeedbackText', 'ActivationTime', 'Do_What', 'APBonus'] : []
  const lint = graph?.lint
  const TT = graph?.enums?.TEMPLATES?.[tpl.template] || {}

  return (
    <div className="editor mgraph" style={{ gridTemplateColumns: '1fr 360px' }}>
      <div className="viewport" style={{ background: 'var(--vp)' }}>
        <div className="toolbar">
          <select value={entry} onChange={e => { setEntry(e.target.value); setSel(null); setTpl(t => ({ ...t, pos: '' })) }} aria-label={tr('block')}>
            {(catalog?.maps || []).map(m => <optgroup key={m.id} label={m.title}>
              {m.sections.map(x => <option key={x.entry} value={x.entry}>{x.title}</option>)}
              {m.missions.map(x => <option key={x.entry} value={x.entry}>{x.title} ({short(x.entry)})</option>)}
            </optgroup>)}
            {!catalog && <option value={M10}>{tr('mm010_ernesto_cruz')}</option>}</select>
          <button onClick={() => setOnlyEdited(false)} className={!onlyEdited ? 'on' : ''}>{tr('all_triggers')}{trig.length})</button>
          <button onClick={() => setOnlyEdited(true)} className={onlyEdited ? 'on' : ''}>{tr('edited')}{editedIds.size})</button>
          <button onClick={() => setShowMap(!showMap)} className={showMap ? 'on' : ''} aria-pressed={showMap} title={tr('where_the_triggers_are_on_the')}>{tr('map')}</button>
          <span className="lbl" title={tr('green_new_yellow_rewired_or_edited')}>{tr('drag_to_pan_wheel_to_zoom')}{rewiring && <b>{' '}{tr('click_the_trigger_that_should_fire')}{' '}{rewiring.node}.</b>}</span>
        </div>
        <svg ref={svgRef} className={panning ? 'panning' : undefined} style={{ position: "absolute", top: 34, left: 0, width: "100%", height: showMap ? "calc(55% - 34px)" : "calc(100% - 34px)" }} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onClickCapture={noClickAfterPan}>
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
                <text x={8} y={15} fill="#e8eef7" fontSize={12} fontWeight="bold" pointerEvents="none">{(t.name || t.node).slice(0, t.new || edited || (graph.starts || []).includes(t.id) ? 30 : 38)}{t.disabled ? ' (disabled)' : ''}</text>
                {(t.new || edited || (graph.starts || []).includes(t.id)) && <text x={CW - 8} y={13} textAnchor="end" fill={stroke} fontSize={9} fontWeight="bold" pointerEvents="none">{t.new ? 'NEW' : edited ? 'EDITED' : 'START'}</text>}
                <text x={8} y={28} fill="#9fb0c4" fontSize={10} pointerEvents="none">{t.cls}{t.base} {String(t.trigger_on || '').slice(0, 26)}{t.reactivate ? ' re-arms' : ''}</text>
                {t.conditions.map((c, i) => <text key={c.node} x={10} y={HEAD + i * ROWH + 10} fontSize={10}
                  fill={sel?.node === c.node ? '#ffffff' : '#7fd1ff'} onClick={ev => { ev.stopPropagation(); clickCard(t, 'cond', c.node) }}>{tr('if')}{' '}{String(c.event).slice(0, 30)}{c.activator ? ' by ' + String(c.activator).split(' ').slice(0, 3).join(' ') : ''}</text>)}
                {t.actions.map((a, i) => <text key={a.node} x={10 + (a.depth || 0) * 8} y={HEAD + (t.conditions.length + i) * ROWH + 10} fontSize={10}
                  fill={a.rewired_from ? '#ffd166' : a.new ? '#3cff8a' : sel?.node === a.node ? '#ffffff' : '#ffc9a3'}
                  onClick={ev => { ev.stopPropagation(); clickCard(t, 'act', a.node) }}>
                  {a.new ? 'DO+' : a.rewired_from ? 'DO↻' : 'DO'} {a.short} {a.code ?? ''}: {String(a.does || '').split(/[:(;]/)[0].slice(0, 22)} {'-> ' + String(a.target_name || a.target || '').slice(0, 22)}{a.delay ? ` +${a.delay}s` : ''}</text>)}
              </g>
            })}
          </g>
        </svg>
        {showMap && <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: '45%', display: 'flex', borderTop: '1px solid var(--line)' }}>
          <View3D defaultMode="top" bundle={lvl.bundle} view={lvl.view} layers={CONTEXT_LAYERS} overlays={overlays} focus={focus3 || mapFocus}
            onGround={pinning ? (p, ev, geometry) => { setTpl(t => ({ ...t, pos: [p[0], geometry ? p[1] + (Number(String(t.size).split(',')[1]) || 4) / 2 : p[1], p[2]].map(v => Math.round(v * 100) / 100).join(', ') })); setPinning(false) } : undefined}
            onPickOverlay={id => { const t = byId[id]; if (t) { setSel({ tid: id, kind: 'trigger', node: t.node }); setFocus3({ pos: t.pos, dist: 40 }) } }}>
            {(lvl.busy || lvl.err) && <span className="floatpanel" style={{ left: 12, top: 12 }}>{lvl.busy ? lvl.busy + '…' : 'No map'}</span>}
          </View3D></div>}
      </div>
      <aside className="panel" style={{ overflow: 'auto' }}>
        <section className="box">
          <h3>{tr('selection')}</h3>
          {!sel && <p className="muted">{tr('click_a_card_the_trigger_an')}</p>}
          {selT && <div>
            <p><b>{selT.name}</b> <span className="muted">{selT.frag} {selT.node}</span></p>
            {selRow && <pre className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{JSON.stringify(selRow, null, 1).slice(0, 900)}</pre>}
            <div className="row"><select value={prop} onChange={e => setProp(e.target.value)}><option value="">{tr('set_a_value')}</option>
              {props.map(p => <option key={p}>{p}</option>)}</select>
              <input value={val} onChange={e => setVal(e.target.value)} style={{ width: 90 }} /><button onClick={setValue} disabled={!prop}>{tr('set')}</button></div>
            <div className="btns">
              {sel.kind === 'act' && !selRow?.new && <button onClick={() => setRewiring({ node: sel.node, frag: selT.frag, fragFull: fragFull(selT) })}>{tr('rewire_to_another_trigger')}</button>}
              {sel.kind === 'act' && <button onClick={retarget}>{tr('retarget')}</button>}
              {sel.kind === 'trigger' && !selT.new && <button onClick={disable}>{tr('disable_trigger')}</button>}
            </div>
          </div>}
        </section>
        <section className="box">
          <h3>{tr('new_trigger_from_a_template')}</h3>
          <div className="row"><select value={tpl.template} title={graph?.enums?.TEMPLATES?.[tpl.template]?.help} onChange={e => setTpl({ ...tpl, template: e.target.value })}>
            {Object.entries(graph?.enums?.TEMPLATES || {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></div>
          <label className="kv">{tr('name')}<input value={tpl.name} onChange={e => setTpl({ ...tpl, name: e.target.value })} /></label>
          {TT.box && <>
            <label className="kv">{tr('position')}<span className="row" style={{ gap: 4 }}>
              <input value={tpl.pos} placeholder="x, y, z" onChange={e => setTpl({ ...tpl, pos: e.target.value })} />
              <button className={pinning ? 'on' : ''} aria-pressed={pinning} title={tr('click_the_map_to_set_the_position')}
                onClick={() => { setShowMap(true); setPinning(!pinning) }}>{tr('pin')}</button></span></label>
            <label className="kv">{tr('size')}<input value={tpl.size} onChange={e => setTpl({ ...tpl, size: e.target.value })} title={tr('width_height_length')} /></label>
            <label className="kv">{tr('turn_368e80')}<input value={tpl.yaw} onChange={e => setTpl({ ...tpl, yaw: e.target.value })} /></label>
          </>}
          {(TT.needs || []).filter(k => k !== 'objective' || !tpl.action || tpl.action.includes('objective')).map(k =>
            <label key={k} className="kv">{k}<input value={tpl[k]} onChange={e => setTpl({ ...tpl, [k]: e.target.value })} /></label>)}
          {tpl.template === 'camera_cut' && <label className="kv">{tr('hold')}<input value={tpl.hold} onChange={e => setTpl({ ...tpl, hold: e.target.value })} /></label>}
          {TT.box && <>
            <label className="kv">{tr('text')}<input list="mtexts" value={tpl.text} onChange={e => setTpl({ ...tpl, text: e.target.value })} title={tr('your_own_words_or_a_line_of_the_game')} />
              <datalist id="mtexts">{texts.map(x => <option key={x.i} value={x.text} />)}</datalist></label>
            <label className="kv">{tr('points_4b2a6a')}<input value={tpl.ap} onChange={e => setTpl({ ...tpl, ap: e.target.value })} /></label>
            <label className="kv">{tr('gun')}<span className="row" style={{ gap: 4 }}>
              <select value={tpl.weapon} onChange={e => setTpl({ ...tpl, weapon: e.target.value })}><option value="">-</option>
                {Object.entries(guns).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <input value={tpl.ammo} placeholder={tr('ammo')} style={{ width: 56 }} onChange={e => setTpl({ ...tpl, ammo: e.target.value })} /></span></label>
            <div className="chips" role="group" aria-label={tr('pickups')}>
              {(graph?.enums?.REWARDS || []).map(r => <button key={r.id} className={tpl.pickups.includes(r.id) ? 'on' : ''} aria-pressed={tpl.pickups.includes(r.id)}
                onClick={() => setTpl({ ...tpl, pickups: tpl.pickups.includes(r.id) ? tpl.pickups.filter(x => x !== r.id) : [...tpl.pickups, r.id] })}>{r.label}</button>)}
            </div>
          </>}
          {tpl.template !== 'car_enters' && <label className="kv">{tr('action')}<select value={tpl.action} onChange={e => setTpl({ ...tpl, action: e.target.value })}>
            <option value="">{tr('template_default')}{' '}{TT.action})</option>
            {(graph?.enums?.ACTION_KINDS || []).map(a => <option key={a}>{a}</option>)}</select></label>}
          <button onClick={addTrigger}>{tr('add_trigger')}</button>
        </section>
        <section className="box">
          <h3>{tr('edits')}{' '}<span className="badge">{ops.length}</span></h3>
          <ol className="changes">{ops.map((o, i) => <li key={i}>{describeMission(o)} <button onClick={() => setOps(ops.filter((_, j) => j !== i))}>{tr('x_11f6ad')}</button></li>)}</ol>
          <button className="primary" onClick={runCheck} disabled={!ops.length}>{tr('check')}</button>
          {lint && <p className="muted">{lint.length}{' '}{tr('leftover_targets_in_the_shipped_data')}</p>}
        </section>
        {check && <section className="box"><h3>{tr('check_695ef8')}{' '}{check.result}</h3>
          <ul className="checklist">{check.lines.map((l, i) => <li key={i} className={l.level}><b>{l.area}</b> {l.text}</li>)}</ul></section>}
        
      </aside>
      {busy && <div className="busy">{busy}</div>}
      {msg && <div className="error" onClick={() => setMsg(null)}>{msg}</div>}
    </div>
  )
}
