import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { get, post, runJob } from './api.js'
import View3D from './View3D.jsx'
import { useSelection } from './selection.js'
import { usePad } from './pad/padstore.js'
import { useCommands, openPalette, openShortcuts } from './commands.js'
import { useLib, saveLib, libSnapshot } from './userlib.js'
import * as ED from './editing.js'
import { SnapPanel, snapLabel, LayersPanel, PrefabsPanel, SpotsPanel, SelectionPanel, FindReplace, ScatterHud } from './EditorPanels.jsx'
import { CATS, catColor, CAT_LABEL, GAMEPLAY, buildView, addableBlocks, keyOf } from './view.js'
import { opsMove, opsSet, opsDelete, opsRestore, newUid, describeOp } from './project.js'
import { r3, yawDeg, quatFromYaw } from './coords.js'
import Properties from './Properties.jsx'
import { modelPathFor } from './placeModels.js'
import { importedPalette, opForPlacing } from './importedModels.js'
import { Menu, Seg, CheckRow, UndoRedo, useUI } from './ui.jsx'
import { MeterStrip } from './Meters.jsx'
import { ProblemsBadge } from './ProblemsPanel.jsx'
import TestControl, { useTestActions } from './TestGame.jsx'
import { useStore, setOpen as openProblems, useJump } from './problemsStore.js'
import { t as tr } from './i18n.js'

const PALETTE = [
  ['pickup', 'Pickup', 'pickup', 'mission'],
  ['weapon', 'Weapon', 'weapon', 'mission'],
  ['enemy', 'Enemy', 'character', 'mission'],
  ['vehicle', 'Vehicle', 'vehicle', 'mission'],
  ['trigger', 'Trigger box', 'trigger', 'section'],
  ['wall', 'Invisible wall', 'wall', 'section'],
  ['navblock', 'Nav blocker', 'navblock', 'section'],
  ['trackpoint', 'Route point', 'route', 'mission'],
]
const KIND_SETS = {
  wall: { width: 6, height: 3, length: 0.5, CollisionFlags: 3 },
  navblock: { width: 4, height: 3, length: 4, CollisionFlags: 32 },
  trigger: { width: 4, height: 3, length: 4 },
}

const PALETTE_BY = Object.fromEntries(PALETTE.map(p => [p[0], p]))
const ADD_GROUPS = [
  { title: tr('things_to_pick_up'), items: ['pickup', 'weapon'] },
  { title: tr('characters_and_vehicles'), items: ['enemy', 'vehicle'] },
  { title: tr('invisible_helpers'), items: ['trigger', 'wall', 'navblock', 'trackpoint'] },
]
const ADD_HINT = { pickup: 'health, score', trigger: 'starts something', wall: 'blocks the player', navblock: 'blocks enemies', trackpoint: 'enemy path' }
const KIND_NAME = { character: 'Enemy', pickup: 'Pickup', weapon: 'Weapon', vehicle: 'Vehicle', trigger: 'Trigger box', wall: 'Invisible wall',
  navblock: 'Nav blocker', route: 'Route point', marker: 'Marker', havoc: 'Destructible' }

export default function LevelEditor({ status, project, commit, replace, undo, redo, canUndo, canRedo, setSaveSpot, theme, go }) {
  const pstore = useStore()
  const [catalog, setCatalog] = useState(null)
  const [pick, setPick] = useState(() => (new URLSearchParams(location.search).get('map') && { map: new URLSearchParams(location.search).get('map'), section: null, missions: [] }) || project.view || status.settings?.last_view || { map: null, section: null, missions: [] })
  const [bundle, setBundle] = useState(null)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [layers, setLayers] = useState(() => Object.fromEntries(CATS.map(c => [c[0], c[3]])))
  const [showColl, setShowColl] = useState(false)
  const [showGeom, setShowGeom] = useState(true)
  const [showNewColl, setShowNewColl] = useState(true)
  const ui = useUI()
  const selection = useSelection()
  const pad = usePad().mode === 'pad'
  const selectedId = selection.primary
  const setSelectedId = id => selection.set(id == null ? [] : [id])
  const [gizmo, setGizmo] = useState('translate')
  const [chip, setChip] = useState('all')
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth >= 1280)
  const [addQ, setAddQ] = useState('')
  const [checkOpen, setCheckOpen] = useState(false)
  const [vp, setVp] = useState('#0a0d11')
  useEffect(() => { setVp(getComputedStyle(document.documentElement).getPropertyValue('--vp').trim() || '#0a0d11') }, [theme])
  const [focus, setFocus] = useState(null)
  const [filter, setFilter] = useState('')
  const [templates, setTemplates] = useState({})
  const [enums, setEnums] = useState({})
  const [addTarget, setAddTarget] = useState({})
  const [checks, setChecks] = useState(null)
  const [panel, setPanel] = useState('objects')
  const viewApi = useRef(null)
  const [mode, setMode] = useState(() => new URLSearchParams(location.search).get('mode') === 'top' ? 'top' : '3d')
  const [snap, setSnap] = useState(ED.defaultSnap)
  const [tool, setTool] = useState(null)                 // ruler | figure | scatter
  const [hidden, setHidden] = useState(() => new Set())
  const [locked, setLocked] = useState(() => new Set())
  const [isolate, setIsolate] = useState(null)
  const [tab, setTab] = useState(() => ['layers', 'prefabs', 'spots'].includes(new URLSearchParams(location.search).get('lt')) ? new URLSearchParams(location.search).get('lt') : 'objects')   // objects | layers | prefabs | spots
  const [prefabs, setPrefabs] = useLib('prefabs')
  const [findOpen, setFindOpen] = useState(false)
  const [scat, setScat] = useState({ radius: 6, density: 0.04, yawRandom: true, scale: [1, 1], gap: 1.5 })
  const [scatChosen, setScatChosen] = useState(['pickup'])
  const [scatSubs, setScatSubs] = useState({})

  useEffect(() => { get('/api/catalog').then(setCatalog).catch(e => setErr(e.message)) }, [])
  useEffect(() => { get('/api/enums').then(setEnums).catch(() => {}) }, [])

  const map = catalog?.maps.find(m => m.id === pick.map)

  const open = useCallback(async (p = pick) => {
    if (!p.map) return
    setErr(null); setBusy('Opening level'); setSelectedId(null)
    try {
      const res = await runJob('/api/open', p.section || p.blockOnly ? p : { ...p, sections: '*' }, j => setBusy(j.message || 'Opening level'))
      setBundle(res)
      replace({ ...project, view: p })
      const ents = res.levels.flatMap(L => L.entities)
      const pts = ents.filter(e => GAMEPLAY.has(e.cat) && e.cat !== 'route').map(e => e.pos)
      const src = pts.length ? pts : ents.filter(e => e.cat === 'model').map(e => e.pos)
      if (src.length) {
        const med = i => src.map(p => p[i]).sort((a, b) => a - b)[src.length >> 1]
        setFocus({ pos: [med(0), med(1), med(2)], dist: 120, reset: true })
      }
      const tpl = await post('/api/templates', { entries: res.entries })
      setTemplates(tpl)
      if (new URLSearchParams(location.search).get('frame') === 'collision') {
        const P = (project.collision || []).flatMap(s => (s.pieces || []).flatMap(p => p.verts))
        if (P.length) setFocus({ pos: [0, 1, 2].map(i => P.reduce((a, v) => a + v[i], 0) / P.length), dist: 11, reset: true })
      }
    } catch (e) { setErr(e.message) }
    setBusy(null)
  }, [pick, project])

  useEffect(() => { if (pick.map && catalog && !bundle) open(pick) }, [catalog])

  const modelFor = useCallback((cat, sub) => modelPathFor(cat, sub, enums), [enums])
  const view = useMemo(() => buildView(bundle, project.level, modelFor), [bundle, project.level, modelFor])
  // live preview: fetch the mesh of every added object (and of the item being placed) that the open blocks do not hold
  const asked = useRef(new Set())
  useEffect(() => { asked.current = new Set() }, [bundle?.entries?.join('|')])
  const [placing, setPlacing] = useState(null)
  const imported = useMemo(() => importedPalette(project), [project.models])
  const wanted = useMemo(() => {
    const s = new Set(view.list.filter(e => e.isNew && e.model).map(e => e.model))
    if (placing?.model) s.add(placing.model)
    return [...s]
  }, [view, placing])
  useEffect(() => {
    if (!bundle) return
    const need = wanted.filter(n => !bundle.models[n] && !asked.current.has(n))
    if (!need.length) return
    need.forEach(n => asked.current.add(n))
    const mine = new Set(imported.map(m => m.path.toLowerCase()))
    post('/api/models/find', need.some(n => mine.has(n)) ? { names: need, imported: project.models } : { names: need }).then(r => setBundle(b => b && ({ ...b, models: { ...b.models, ...r.models } }))).catch(() => {})
  }, [wanted, bundle, imported])
  const sel = selectedId ? view.ents.get(selectedId) : null
  // a click in the Problems list or on a meter: select the object and frame the camera
  useJump('level', ref => {
    if (!bundle && (ref.uid || ref.node)) return false
    const e = ref.uid ? view.ents.get('new:' + ref.uid) : ref.node ? view.byTarget.get(keyOf(ref)) : null
    if (e) { setSelectedId(e.id); setFocus({ pos: e.pos, dist: 18 }) }
    return true
  })
  const addable = useMemo(() => addableBlocks(bundle), [bundle])

  // ---------------------------------------------------------------- what the view shows and what can be picked
  const layerState = useMemo(() => Object.fromEntries(ED.layersOf(project).map(l => [l.id, l])), [project.editor])
  const layerOf = e => layerState[ED.assignOf(project)[keyOf(e.target)]]
  const isLocked = e => locked.has(e.id) || !!layerOf(e)?.locked
  const isVisible = e => !hidden.has(e.id) && !(isolate && !isolate.has(e.id)) && !layerOf(e)?.hidden
  const selEnts = useMemo(() => selection.ids.map(id => view.ents.get(id)).filter(Boolean), [selection.ids, view])
  const editEnts = useMemo(() => ED.editable(selEnts), [selEnts])
  const onPick = (id, ev) => { const e = view.ents.get(id); if (e && !isLocked(e)) selection.pick(id, ev) }
  const selectables = useMemo(() => view.list.filter(e => layers[e.cat] && e.cat !== 'model' && e.cat !== 'logic' && isVisible(e) && !isLocked(e)).map(e => ({ id: e.id, pos: e.pos })),
    [view, layers, hidden, locked, isolate, project.editor])
  const onBoxSelect = (ids, additive) => selection.set(additive ? [...new Set([...selection.ids, ...ids])] : ids)

  // ---------------------------------------------------------------- edits (each tool is ONE commit = one undo step)
  const label = ED.labelOf
  const withLabel = ED.withLabel
  const commitLevel = ops => commit({ ...project, level: ops })
  const dropOffset = e => (e.size ? e.size[1] / 2 : (e.isNew || ['pickup', 'weapon', 'route', 'marker', 'havoc'].includes(e.cat)) ? 0 : null)
  const groundFor = (e, ids) => {
    const off = dropOffset(e)
    if (off == null || !viewApi.current) return null
    const ys = viewApi.current.castDown(e.pos[0], e.pos[2], e.pos[1] + 0.75 + off, ids)
    return ys.length ? ys[0] + off : null
  }
  // snap mode "ground": a finished move also puts the objects on the floor under them
  const settle = moves => {
    if (snap.mode !== 'ground') return moves
    const ids = new Set(moves.map(m => m.e.id))
    return moves.map(m => { const y = groundFor({ ...m.e, pos: m.pos }, ids); return y == null ? m : { ...m, pos: [m.pos[0], y, m.pos[2]] } })
  }
  const commitMoves = moves => { if (moves.length) commitLevel(ED.moveMany(project.level, moves)) }

  const onCommitTransform = (e, pos, rot, size) => {
    if (size) {
      let ops = project.level
      ;['width', 'height', 'length'].forEach((p, i) => { ops = opsSet(ops, e.target, p, size[i]) })
      commitLevel(withLabel(ops, e))
    } else {
      commitMoves(settle([{ e, pos, rot: rot.map(x => Math.round(x * 1e6) / 1e6) }]))
    }
  }
  const onCommitGroup = moves => commitMoves(settle(moves))
  const setProp = (e, prop, value) => commitLevel(withLabel(opsSet(project.level, e.target, prop, value), e))
  const setPos = (e, pos, rot) => commitLevel(withLabel(opsMove(project.level, e.target, pos, rot || e.rot), e))
  const delMode = status.settings?.save_safe_delete === false ? 'remove' : 'retire'
  const delMany = ents => {
    const list = ED.editable(ents)
    if (!list.length) return
    commitLevel(ED.deleteMany(project.level, list, delMode))
    selection.set(selection.ids.filter(id => !list.some(e => e.id === id && e.isNew)))
  }
  const del = e => { if (e) delMany([e]) }
  const restore = e => commitLevel(opsRestore(project.level, e.target))

  const targetFor = kindWhere => {
    const ok = addable.filter(a => a.ok)
    const want = kindWhere === 'mission' ? ['mission', 'submap', 'map'] : ['submap', 'map', 'mission']
    for (const k of want) { const a = ok.find(x => x.kind === k); if (a) return a.entry }
    return null
  }
  const entryFor = it => (addable.find(a => a.entry === it.template?.entry && a.ok) ? it.template.entry : targetFor(it.where || ED.whereOf(it.cat)))
  const noRoom = () => ui.say(tr('none_of_the_open_blocks_can'), 'bad')

  const addFrom = (tpl, kind, catKey, where, pos, extraSet, srcEnt, yaw) => {
    const entry = addTarget[kind] || targetFor(where)
    if (!entry) { noRoom(); return }
    const uid = newUid()
    const set = { ...(KIND_SETS[kind] || {}), ...(extraSet || {}) }
    const view = { type: tpl.type, cat: catKey, size: set.width != null ? [set.width, set.height, set.length] : tpl.size,
      sub: tpl.sub, model: srcEnt?.model, radius: srcEnt?.radius, kindLabel: PALETTE.find(p => p[0] === kind)?.[1] || kind,
      name: tpl.name }
    const op = { op: 'add', uid, entry, template: { entry: tpl.entry, frag: tpl.frag, node: tpl.node },
      name: `TODMS_${kind}_${uid}`, pos: r3(pos), rot: yaw ? quatFromYaw(yaw) : [0, 0, 0, 1], set, view }
    commitLevel([...project.level, op])
    setSelectedId('new:' + uid)
  }

  const lastAdd = useRef(null)                        // what the controller's X adds again: the last Add choice
  const addKind = kind => {
    lastAdd.current = { kind }
    const p = PALETTE.find(x => x[0] === kind)
    const tpl = templates[kind]
    if (!tpl) { ui.say('No template for ' + p[1] + ' in the open blocks.', 'bad'); return }
    const ks = KIND_SETS[kind]
    const size = ks ? [ks.width, ks.height, ks.length] : null
    setSelectedId(null); setTool(null)
    setPlacing({ kind, label: p[1], model: size ? null : modelPathFor(p[2], tpl.sub, enums), size })
  }
  const addImported = m => {
    lastAdd.current = { imported: m }
    const tpl = templates.model
    if (!tpl) { noRoom(); return }
    setSelectedId(null); setTool(null)
    setPlacing({ kind: 'imported', label: m.name, model: m.path.toLowerCase(), imported: m })
  }
  const selDone = useRef(false)
  useEffect(() => {      // ?select=all: select everything the box select could reach (screenshots)
    if (new URLSearchParams(location.search).get('select') === 'all' && !selDone.current && bundle && selectables.length) { selDone.current = true; selection.set(selectables.map(x => x.id)) }
  }, [bundle, selectables])
  const demoDone = useRef(false)
  useEffect(() => {      // ?demo=enemy|pickup|...: start placing at once (used for screenshots)
    const d = new URLSearchParams(location.search).get('demo')
    if (d && !demoDone.current && bundle && templates[d]) { demoDone.current = true; addKind(d) }
  }, [bundle, templates, enums])

  // a prefab, or the copy buffer, as a ghost the user stamps with a click
  const ghostOf = pf => pf.items.map(it => ({ dpos: it.dpos, rot: it.rot, model: it.view?.model || modelPathFor(it.cat, it.view?.sub, enums),
    size: it.set?.width != null ? [it.set.width, it.set.height, it.set.length] : it.view?.size }))
  const startStamp = (pf, labelText) => {
    if (!addable.some(a => a.ok)) { noRoom(); return }
    setTool(null); selection.clear()
    setPlacing({ kind: 'prefab', prefab: pf, label: labelText || pf.name, items: ghostOf(pf) })
  }
  const placeAt = useCallback((pos, yaw) => {
    if (!placing) return
    if (placing.kind === 'note') { setPlacing(null); commit(ED.addNote(project, r3(pos), 'Note')); setTab('spots'); return }
    if (placing.kind === 'prefab') {
      const ops = ED.stampOps(placing.prefab, pos, yaw, entryFor)
      if (!ops.length) { noRoom(); return }
      commitLevel([...project.level, ...ops])
      selection.set(ops.map(o => 'new:' + o.uid))
      setPlacing(null)
      return
    }
    if (placing.kind === 'imported') {
      const tpl = templates.model, entry = tpl && (addable.find(a => a.entry === tpl.entry && a.ok) ? tpl.entry : targetFor('section'))
      setPlacing(null)
      if (!tpl || !entry) { noRoom(); return }
      const uid = newUid()
      commitLevel([...project.level, opForPlacing(placing.imported, { entry: tpl.entry, frag: tpl.frag, node: tpl.node }, entry, r3(pos), yaw ? quatFromYaw(yaw) : [0, 0, 0, 1], uid)])
      setSelectedId('new:' + uid)
      return
    }
    if (placing.kind === 'model') {
      setPlacing(null)
      if (templates.model) addFrom(templates.model, 'model', 'model', 'section', pos, { modelres: placing.modelres }, { model: placing.model }, yaw)
      return
    }
    const p = PALETTE_BY[placing.kind], tpl = templates[placing.kind]
    setPlacing(null)
    if (tpl) addFrom(tpl, placing.kind, p[2], p[3], pos, null, null, yaw)
  }, [placing, templates, project, addTarget, addable])

  // one object per selected object, a little to the side
  const duplicate = ents => {
    const list = ED.editable(Array.isArray(ents) ? ents : ents ? [ents] : editEnts)
    if (!list.length) return
    const ops = []
    for (const e of list) {
      const tpl = ED.entityTemplate(e)
      const entry = e.isNew ? e.entry : (addable.find(a => a.entry === e.entry && a.ok) ? e.entry : targetFor(ED.whereOf(e.cat)))
      if (!entry) { noRoom(); return }
      ops.push(ED.addOpFrom(tpl, entry, { pos: [e.pos[0] + 2, e.pos[1], e.pos[2] + 2], rot: e.rot }, { prefix: e.isNew ? 'TODMS_copy' : undefined }))
    }
    commitLevel([...project.level, ...ops])
    selection.set(ops.map(o => 'new:' + o.uid))
  }

  // ---- group tools
  const moveBy = d => commitMoves(ED.translateMoves(editEnts, d))
  const turnBy = deg => commitMoves(ED.rotateMoves(editEnts, ED.centroid(editEnts), deg))
  const alignTo = (axis, how) => commitMoves(ED.alignMoves(editEnts, axis, how))
  const spread = axis => commitMoves(ED.distributeMoves(editEnts, axis))
  const dropDown = () => {
    const ids = new Set(editEnts.map(e => e.id))
    const moves = ED.dropMoves(editEnts, (x, z, e) => groundFor(e, ids))
    if (!moves.length) { ui.say(tr('nothing_to_drop')); return }
    commitMoves(moves)
  }
  const setOnAll = (prop, value) => commitLevel(ED.setMany(project.level, editEnts, prop, value))
  const sameModel = () => {
    const ref = selEnts[0]
    if (!ref) return
    const same = view.list.filter(e => (ref.model ? e.model === ref.model : e.type === ref.type) && isVisible(e) && !isLocked(e) && layers[e.cat])
    selection.set(same.map(e => e.id), ref.id)
    ui.say(`${same.length} selected.`)
  }
  const selectAll = () => selection.set(selectables.map(s => s.id))
  const focusSel = () => {
    if (!selEnts.length) return
    const c = ED.centroid(selEnts)
    const ext = Math.max(8, ...selEnts.map(e => Math.hypot(e.pos[0] - c[0], e.pos[2] - c[2])))
    setFocus({ pos: c, dist: selEnts.length > 1 ? Math.min(400, ext * 3 + 10) : 15 })
  }
  const assignLayer = (ents, id) => commit(ED.assignLayer(project, ents, id))
  const isolateSel = () => { if (isolate) setIsolate(null); else if (selection.count) setIsolate(new Set(selection.ids)) }
  const clearView = () => { setHidden(new Set()); setIsolate(null) }

  // ---- prefabs and the copy buffer (kept in the user's library, so they follow to other maps and projects)
  const savePrefab = nm => {
    if (!editEnts.length) return
    setPrefabs([...prefabs, ED.prefabFromEntities(editEnts, nm || 'Prefab ' + (prefabs.length + 1))])
    ui.say(tr('prefab_saved'))
  }
  const copySel = () => {
    const list = ED.editable(selEnts)
    if (!list.length) return
    saveLib('clipboard', ED.clipFromEntities(list))
    ui.say(`${list.length} copied.`)
  }
  const paste = () => {
    const c = libSnapshot('clipboard')
    if (!c?.items?.length) { ui.say(tr('nothing_copied_yet')); return }
    startStamp(c, 'Paste')
  }

  // ---- scatter brush: one stroke = one commit
  const SCAT_KINDS = [['pickup', 'Pickups', 'GoodieSubType'], ['weapon', 'Weapons', 'WeaponSubType'], ['enemy', 'Enemies', null], ['vehicle', 'Vehicles', 'VehicleSubType']]
  const scatterSources = [...SCAT_KINDS.map(([id, lb, subKey]) => ({ id, label: lb, subKey, ok: !!templates[id] })), { id: 'selection', label: tr('selection'), ok: editEnts.length > 0 }]
  const onScatter = stamps => {
    const srcs = scatChosen.filter(id => scatterSources.find(s => s.id === id)?.ok)
    if (!srcs.length) { ui.say(tr('pick_what_to_scatter'), 'bad'); return }
    const keep = editEnts.slice()
    const ops = []
    for (const s of stamps) {
      const id = srcs[Math.floor(Math.random() * srcs.length)]
      if (id === 'selection') {
        const e = keep[Math.floor(Math.random() * keep.length)]
        const entry = e.isNew ? e.entry : (addable.find(a => a.entry === e.entry && a.ok) ? e.entry : targetFor(ED.whereOf(e.cat)))
        if (entry) ops.push(ED.addOpFrom(ED.entityTemplate(e), entry, { pos: s.pos, yaw: s.yaw }, { scale: s.scale, prefix: 'TODMS_scatter' }))
        continue
      }
      const pk = PALETTE_BY[id], tpl = templates[id]
      const entry = targetFor(pk[3])
      if (!tpl || !entry) continue
      const subKey = SCAT_KINDS.find(k => k[0] === id)[2]
      const set = { ...(KIND_SETS[id] || {}), ...(subKey && scatSubs[id] != null ? { [subKey]: scatSubs[id] } : {}) }
      const sub = subKey && scatSubs[id] != null ? { ...(tpl.sub || {}), [subKey]: scatSubs[id] } : tpl.sub
      ops.push(ED.addOpFrom({ template: { entry: tpl.entry, frag: tpl.frag, node: tpl.node }, set,
        view: { type: tpl.type, cat: pk[2], size: set.width != null ? [set.width, set.height, set.length] : tpl.size, sub, kindLabel: pk[1], name: tpl.name } },
        entry, { pos: s.pos, yaw: s.yaw }, { scale: s.scale, prefix: `TODMS_${id}` }))
    }
    if (!ops.length) { noRoom(); return }
    commitLevel([...project.level, ...ops])
    ui.say(`${ops.length} placed.`)
  }

  // ---- find and replace
  const applyReplace = (key, from, to) => {
    const r = ED.replaceKind(project.level, view, key, from, to)
    if (r.count) { commitLevel(r.ops); ui.say(`${r.count} changed.`) }
  }

  // ---- saved camera spots and notes live in the project (never in the game)
  const addSpot = () => { const c = viewApi.current?.cameraState(); if (c) commit(ED.addBookmark(project, null, c.eye, c.target)) }
  const goSpot = b => setFocus({ eye: b.pos, target: b.target })
  // a picture of the 3D view for the mod page (up to six, small JPEGs)
  const capture = () => {
    const data = viewApi.current?.capture?.(960)
    const shots = project.page?.screenshots || []
    if (!data) return
    if (shots.length >= 6) { ui.say(tr('the_mod_page_holds_six_pictures'), 'bad'); return }
    commit({ ...project, page: { ...(project.page || {}), screenshots: [...shots, { name: 'view-' + (shots.length + 1), data, caption: '' }] } })
    ui.say(tr('added_to_the_mod_page'))
  }
  const startNote = () => { setTool(null); setPlacing({ kind: 'note', label: tr('note_2c924e') }) }

  // ---------------------------------------------------------------- commands and keys (editable in Keyboard shortcuts)
  // ---- controller: X starts placing from the last Add choice (X again cancels), Y cycles select / move / rotate / resize, the d-pad steps the selection
  const PAD_MODES = ['select', 'translate', 'rotate', 'scale']
  const PAD_NAMES = { select: 'Select', translate: 'Move', rotate: 'Rotate', scale: 'Resize' }
  const padAdd = () => {
    if (placing) { setPlacing(null); return }
    const l = lastAdd.current
    if (l?.imported) { addImported(l.imported); return }
    const kind = l?.kind || PALETTE.map(p => p[0]).find(k => templates[k])
    if (kind) addKind(kind)
  }
  const padMode = () => setGizmo(PAD_MODES[(PAD_MODES.indexOf(gizmo) + 1) % PAD_MODES.length])
  const padStep = dir => {
    if (!selection.primary && selectables.length) {      // nothing selected yet: start with the object nearest the middle of the view
      const c = viewApi.current?.centerPoint?.() || [0, 0, 0]
      let best = selectables[0], bd = Infinity
      for (const it of selectables) { const d = Math.hypot(it.pos[0] - c[0], it.pos[1] - c[1], it.pos[2] - c[2]); if (d < bd) { bd = d; best = it } }
      selection.set([best.id]); return
    }
    selection.step(dir, selectables)
  }
  const esc = () => { if (placing) setPlacing(null); else if (tool) setTool(null); else selection.clear() }
  const useTool = t => { setPlacing(null); setTool(tool === t ? null : t) }
  const cycle = (list, v) => list[(list.indexOf(v) + 1) % list.length]
  useCommands('level', [
    { id: 'level.escape', label: tr('cancel_or_clear_the_selection'), group: 'Selection', keys: 'escape', run: esc },
    { id: 'level.selectAll', label: tr('select_all'), group: 'Selection', keys: 'ctrl+a', run: selectAll },
    { id: 'level.sameModel', label: tr('select_all_of_this_model'), group: 'Selection', keys: 'shift+a', enabled: selEnts.length > 0, run: sameModel },
    { id: 'level.focus', label: tr('frame_the_selection'), group: 'View', keys: 'f', enabled: selEnts.length > 0, run: focusSel },
    { id: 'level.mode', label: tr('switch_between_3d_and_top'), group: 'View', keys: 'm', run: () => setMode(mode === 'top' ? '3d' : 'top') },
    { id: 'level.isolate', label: isolate ? 'Show everything again' : 'Isolate the selection', group: 'View', keys: 'ctrl+i', run: isolateSel },
    { id: 'level.showAll', label: tr('show_all_hidden_objects'), group: 'View', keys: 'alt+h', run: clearView },
    { id: 'level.hide', label: tr('hide_the_selection'), group: 'View', keys: 'h', enabled: selEnts.length > 0, run: () => setHidden(new Set([...hidden, ...selection.ids])) },
    { id: 'level.lock', label: tr('lock_the_selection'), group: 'View', keys: 'ctrl+l', enabled: selEnts.length > 0, run: () => { setLocked(new Set([...locked, ...selection.ids])); selection.clear() } },
    { id: 'level.delete', label: tr('delete'), group: 'Edit', keys: 'delete', enabled: editEnts.length > 0, run: () => delMany(selEnts) },
    { id: 'level.duplicate', label: tr('duplicate'), group: 'Edit', keys: 'ctrl+d', enabled: editEnts.length > 0, run: () => duplicate() },
    { id: 'level.copy', label: tr('copy'), group: 'Edit', keys: 'ctrl+c', enabled: editEnts.length > 0, run: copySel },
    { id: 'level.paste', label: tr('paste'), group: 'Edit', keys: 'ctrl+v', run: paste },
    { id: 'level.drop', label: tr('drop_to_the_ground'), group: 'Edit', keys: 'end', enabled: editEnts.length > 0, run: dropDown },
    { id: 'level.prefab', label: tr('save_the_selection_as_a_prefab'), group: 'Edit', keys: 'ctrl+shift+p', enabled: editEnts.length > 0, run: () => { savePrefab(''); setTab('prefabs') } },
    { id: 'level.find', label: tr('find_and_replace'), group: 'Edit', keys: 'ctrl+h', run: () => setFindOpen(true) },
    { id: 'level.toolSelect', label: tr('select_tool'), group: 'Tools', keys: 'v', run: () => setGizmo('select') },
    { id: 'level.toolMove', label: tr('move_tool'), group: 'Tools', keys: 'g', run: () => setGizmo('translate') },
    { id: 'level.toolRotate', label: tr('rotate_tool'), group: 'Tools', keys: 'r', run: () => setGizmo('rotate') },
    { id: 'level.toolResize', label: tr('resize_tool'), group: 'Tools', keys: 't', run: () => setGizmo('scale') },
    { id: 'level.ruler', label: tr('ruler'), group: 'Tools', keys: 'u', run: () => useTool('ruler') },
    { id: 'level.figure', label: tr('scale_figure'), group: 'Tools', keys: 'i', run: () => useTool('figure') },
    { id: 'level.scatter', label: tr('scatter_brush'), group: 'Tools', keys: 'b', run: () => useTool('scatter') },
    { id: 'level.clearMeasures', label: tr('clear_measurements'), group: 'Tools', keys: '', run: () => viewApi.current?.clearMeasures() },
    { id: 'level.snapGrid', label: tr('next_grid_size'), group: 'Snap', keys: '', run: () => setSnap({ ...snap, grid: cycle(ED.SNAP_GRIDS, snap.grid) }) },
    { id: 'level.snapAngle', label: tr('next_angle_step'), group: 'Snap', keys: '', run: () => setSnap({ ...snap, angle: cycle(ED.SNAP_ANGLES, snap.angle) }) },
    { id: 'level.spot', label: tr('save_this_view_as_a_camera'), group: 'Spots', keys: 'ctrl+b', run: addSpot },
    { id: 'level.note', label: tr('pin_a_note'), group: 'Spots', keys: '', run: startNote },
    { id: 'level.check', label: tr('run_the_check'), group: 'Mod', keys: '', run: () => runCheck() },
    ...(bundle ? imported.map(m => ({ id: 'level.addimp.' + m.id, label: 'Add ' + m.name, group: 'Add', keys: '', enabled: !!templates.model && addable.some(a => a.ok), run: () => addImported(m) })) : []),
    ...(bundle ? PALETTE.map(p => ({ id: 'level.add.' + p[0], label: 'Add ' + p[1].toLowerCase(), group: 'Add', keys: '', enabled: !!templates[p[0]], run: () => addKind(p[0]) })) : []),
  ])

  // ---------------------------------------------------------------- outliner
  const counts = useMemo(() => {
    const c = {}
    for (const e of view.list) c[e.cat] = (c[e.cat] || 0) + 1
    return c
  }, [view])
  const counts2 = useMemo(() => bundle
    ? { gameplay: view.list.filter(e => GAMEPLAY.has(e.cat) && e.cat !== 'route' || e.isNew).length, total: view.list.length }
    : { gameplay: 0, total: 0 }, [view, bundle])
  const n = v => v.toLocaleString('en-US')
  const outl = useMemo(() => {
    const f = filter.toLowerCase()
    const base = f ? view.list.filter(e => e.cat !== 'logic' && layers[e.cat])                 // searching looks at everything shown
      : chip === 'level' ? view.list.filter(e => e.cat === 'model' && layers.model)
      : view.list.filter(e => GAMEPLAY.has(e.cat) && layers[e.cat] && e.cat !== 'route' || (e.isNew))
    return base.filter(e => !f || (e.name || '').toLowerCase().includes(f) || (e.type || '').toLowerCase().includes(f) || (e.model || '').toLowerCase().includes(f))
      .slice(0, 600)
  }, [view, layers, filter, chip])

  const runCheck = async () => {
    setChecks({ running: true })
    try {
      const r = await runJob('/api/check', { mod: project }, j => setChecks({ running: true, msg: j.message }))
      setChecks(r)
    } catch (e) { setChecks({ error: e.message, trace: e.trace }) }
    setCheckOpen(true)
  }

  const pickAndOpen = next => { setPick(next); open(next) }
  // from the asset catalogue: open a map (and section) and start placing a game model there
  const [wantPlace, setWantPlace] = useState(null)
  useJump('level', ref => {
    if (!ref.map && !ref.place) return false
    if (ref.map) pickAndOpen({ map: ref.map, section: ref.section || null, missions: [] })
    if (ref.place) setWantPlace(ref.place)
    return true
  })
  useEffect(() => {
    if (!wantPlace || busy || !bundle || !templates.model) return
    setSelectedId(null)
    setPlacing({ kind: 'model', label: wantPlace.name, model: wantPlace.path.toLowerCase(), modelres: wantPlace.path.replace(/^\/data/i, '') })
    setWantPlace(null)
  }, [wantPlace, busy, bundle, templates])
  const testActions = useTestActions(project)
  const checkCount = checks && !checks.running && !checks.error ? checks.checks.filter(c => c.level === 'error' || c.level === 'warn').length : null
  const checkTone = checks?.error ? 'bad' : checks?.checks?.some(c => c.level === 'error') ? 'bad' : checkCount ? 'warn' : 'ok'
  const canCheck = !!project.level.length || !!Object.keys(project.data || {}).length || !!(project.collision || []).length
  const chipCats = { enemies: ['character'], pickups: ['pickup', 'weapon'], vehicles: ['vehicle'], helpers: ['trigger', 'wall', 'navblock', 'marker', 'havoc'], level: ['model'] }
  const shown = panel === 'changes' ? [] : outl.filter(e => chip === 'all' || chip === 'level' || (chip === 'changed' ? (e.changed || e.isNew || e.deleted) : chipCats[chip]?.includes(e.cat)))
  const sections = map?.sections || []
  const sectionTitle = sections.find(x => x.entry === pick.section)?.title
  const nMissions = pick.missions.length
  const missionLabel = nMissions === 0 ? 'None' : nMissions === 1 ? (map?.missions.find(m => m.entry === pick.missions[0])?.title || '1 mission') : nMissions + ' missions'

  return (
    <div className="screen">
      <div className="tb">
        <button className={leftOpen ? 'on' : ''} aria-pressed={leftOpen} onClick={() => setLeftOpen(!leftOpen)} title={bundle ? `${n(counts2.gameplay)} of ${n(counts2.total)} objects in this view` : undefined}>{tr('objects')}{' '}<span className="muted">{n(counts2.gameplay)}</span></button>
        <div className="crumb">
          <Menu buttonClass="crumbbtn" label={<><em>{tr('map')}</em> {map?.title || 'Choose a map'} {'▾'}</>} title={tr('the_map_to_edit')}>{close => <>
            {catalog?.maps.map(m => <div key={m.id} className={'item' + (m.id === pick.map ? ' on' : '')} role="menuitem" onClick={() => { close(); pickAndOpen({ map: m.id, section: null, missions: [] }) }}>{m.title}</div>)}
            {!catalog && <div className="foot">{tr('reading_the_map_list')}{'…'}</div>}</>}</Menu>
          <span>{'›'}</span>
          <Menu buttonClass="crumbbtn" disabled={!map} label={<><em>{tr('section')}</em> {pick.section ? (sectionTitle || 'Section') : pick.blockOnly ? 'Map block only' : 'Whole map'} {'▾'}</>} title={tr('a_part_of_the_map')}>{close => <>
            <div className={'item' + (!pick.section && !pick.blockOnly ? ' on' : '')} onClick={() => { close(); pickAndOpen({ ...pick, section: null, blockOnly: false }) }}>{tr('whole_map')}</div>
            <div className={'item' + (!pick.section && pick.blockOnly ? ' on' : '')} onClick={() => { close(); pickAndOpen({ ...pick, section: null, blockOnly: true }) }}>{tr('map_block_only')}</div>
            {sections.map(x => <div key={x.entry} className={'item' + (x.entry === pick.section ? ' on' : '')} onClick={() => { close(); pickAndOpen({ ...pick, section: x.entry, blockOnly: false }) }}>{x.title}</div>)}</>}</Menu>
          <span>{'›'}</span>
          <Menu buttonClass="crumbbtn" disabled={!map || !map.missions.length} label={<><em>{tr('missions')}</em> {missionLabel} {'▾'}</>} title={tr('missions_whose_objects_are_shown')}>{close => <>
            <div className="grp" style={{ paddingTop: 0 }}>{tr('missions_on_this_map')}</div>
            {map?.missions.map(m => (
              <label key={m.entry} className="check" style={{ padding: '2px 8px', margin: 0 }}>
                <input type="checkbox" checked={pick.missions.includes(m.entry)} onChange={ev => setPick({
                  ...pick, missions: ev.target.checked ? [...pick.missions, m.entry] : pick.missions.filter(x => x !== m.entry),
                  section: pick.section || m.section || null })} />
                <span>{m.title} <span className="muted small">{m.type}</span></span>
              </label>))}
            <div className="foot"><button className="primary sm" disabled={!!busy} onClick={() => { close(); open(pick) }}>{tr('open_with_these')}</button></div></>}</Menu>
        </div>
        <div className="vsep" />
        <Menu buttonClass="soft" disabled={!bundle} label={<>{tr('add_109b93')}{' '}{'▾'}</>} title={tr('add_something_to_the_level')}>{close => <>
          <input className="find" placeholder={tr('search_things_to_add')} value={addQ} onChange={e => setAddQ(e.target.value)} autoFocus aria-label={tr('search_things_to_add_a0f018')} />
          {ADD_GROUPS.map(g => {
            const items = g.items.filter(k => PALETTE_BY[k][1].toLowerCase().includes(addQ.toLowerCase()))
            if (!items.length) return null
            return <div key={g.title}><div className="grp">{g.title}</div>
              {items.map(k => <div key={k} role="menuitem" className={'item' + (templates[k] ? '' : ' off')} title={templates[k] ? ADD_HINT[k] : 'Not available in this section'}
                onClick={() => { if (!templates[k]) return; close(); setAddQ(''); addKind(k) }}>
                <span className="swatch" style={{ background: catColor(PALETTE_BY[k][2]) }} /><span>{PALETTE_BY[k][1]}</span></div>)}</div>
          })}
          {(() => {
            const items = imported.filter(m => m.name.toLowerCase().includes(addQ.toLowerCase()))
            if (!items.length) return null
            const ok = !!templates.model && addable.some(a => a.ok)
            return <div><div className="grp">{tr('imported')}</div>
              {items.map(m => <div key={m.id} role="menuitem" className={'item' + (ok ? '' : ' off')} title={ok ? `${m.tris.toLocaleString()} triangles` : 'Not available in this section'}
                onClick={() => { if (!ok) return; close(); setAddQ(''); addImported(m) }}>
                <span className="swatch" style={{ background: catColor('model') }} /><span>{m.name}</span></div>)}</div>
          })()}
          </>}</Menu>
        <Seg value={gizmo} onChange={setGizmo} options={[
          { value: 'select', label: tr('select'), key: 'V', title: tr('click_to_select_drag_for_a') },
          { value: 'translate', label: tr('move'), key: 'G' }, { value: 'rotate', label: tr('rotate'), key: 'R' },
          { value: 'scale', label: tr('resize'), key: 'T', title: tr('resizes_boxes_triggers_and_walls') }]} />
        <UndoRedo h={{ undo, redo, canUndo, canRedo }} />
        <Menu buttonClass="soft" title={tr('snapping')} label={<>{tr('snap')}{' '}{snapLabel(snap) !== 'Off' && <span className="muted">{snapLabel(snap)}</span>} {'▾'}</>}>{() => <SnapPanel snap={snap} setSnap={setSnap} />}</Menu>
        <Menu buttonClass={tool ? 'on' : 'soft'} disabled={!bundle} title={tr('measure_scatter_find_and_replace')} label={<>{tr('tools')}{' '}{'▾'}</>}>{close => <>
          <div className="grp" style={{ paddingTop: 0 }}>{tr('measure')}</div>
          <div role="menuitem" className={'item' + (tool === 'ruler' ? ' on' : '')} onClick={() => { close(); useTool('ruler') }}>{tr('ruler')}<span className="hint">{tr('u')}</span></div>
          <div role="menuitem" className={'item' + (tool === 'figure' ? ' on' : '')} onClick={() => { close(); useTool('figure') }} title={tr('a_1_8_m_figure_to')}>{tr('scale_figure')}<span className="hint">{tr('i')}</span></div>
          <div role="menuitem" className="item" onClick={() => { close(); viewApi.current?.clearMeasures() }}>{tr('clear_measurements')}</div>
          <div className="grp">{tr('place_c32a01')}</div>
          <div role="menuitem" className={'item' + (tool === 'scatter' ? ' on' : '')} onClick={() => { close(); useTool('scatter') }}>{tr('scatter_brush')}<span className="hint">{tr('b')}</span></div>
          <div role="menuitem" className="item" onClick={() => { close(); paste() }}>{tr('paste')}<span className="hint">{tr('ctrl_v')}</span></div>
          <div className="grp">{tr('project')}</div>
          <div role="menuitem" className="item" onClick={() => { close(); setFindOpen(true) }}>{tr('find_and_replace')}<span className="hint">{tr('ctrl_h')}</span></div>
          <div role="menuitem" className="item" onClick={() => { close(); openPalette(true) }}>{tr('search_commands')}<span className="hint">{tr('ctrl_k')}</span></div>
          <div role="menuitem" className="item" onClick={() => { close(); openShortcuts(true) }}>{tr('keyboard_shortcuts')}</div></>}</Menu>
        <div style={{ flex: 1 }} />
        <ProblemsBadge data={pstore.data.level} onClick={() => openProblems(!pstore.open)} />
        <TestControl project={project} go={go} />
        <button className="soft" disabled={!bundle} title={tr('add_a_picture_of_this_view')} onClick={capture}>{tr('capture')}</button>
        <Menu right label={<>{tr('show')}{' '}{'▾'}</>} title={tr('what_the_view_shows')}>{() => <div style={{ minWidth: 280 }}>
          <label className="check"><input type="checkbox" checked={showGeom} onChange={e => setShowGeom(e.target.checked)} /> <span>{tr('level_meshes_and_textures')}</span></label>
          <label className="check"><input type="checkbox" checked={showColl} onChange={e => setShowColl(e.target.checked)} /> <span>{tr('collision_model_hulls')}</span></label>
          <label className="check"><input type="checkbox" checked={showNewColl} onChange={e => setShowNewColl(e.target.checked)} />
            <span className="swatch" style={{ background: '#1ef06e' }} /> <span>{tr('new_collision_this_mod_s')}</span> <i>{(project.collision || []).reduce((a, x) => a + (x.pieces || []).length, 0)}</i></label>
          {(project.collision || []).some(x => (x.pieces || []).length) && <button className="sm" onClick={() => {
            const Pt = (project.collision || []).flatMap(x => (x.pieces || []).flatMap(q => q.verts))
            setFocus({ pos: [0, 1, 2].map(i => Pt.reduce((a, v) => a + v[i], 0) / Pt.length), dist: 11, reset: true })
          }}>{tr('frame_the_new_collision')}</button>}
          <hr />
          {CATS.map(([k, lab, col]) => (
            <label key={k} className="check"><input type="checkbox" checked={!!layers[k]} onChange={ev => setLayers({ ...layers, [k]: ev.target.checked })} />
              <span className="swatch" style={{ background: col }} /> <span>{lab}</span> <i>{counts[k] || 0}</i></label>))}</div>}</Menu>
        <Menu right open={checkOpen} setOpen={setCheckOpen} buttonClass="" label={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>{tr('check')}{checks?.running ? <span className="badge">{'…'}</span> : checkCount != null && <span style={{ padding: '0 6px', borderRadius: 8, fontSize: 11.5, fontWeight: 600,
            background: `var(--${checkTone}-soft)`, color: `var(--${checkTone})` }}>{checkCount}</span>}</span>} title={tr('checks_the_whole_mod_builds_it')} menuStyle={{ maxWidth: 'none', padding: 0, width: 440 }}>{() =>
          <div><Checks checks={checks} onRun={runCheck} canRun={canCheck} /></div>}</Menu>
      </div>
      <MeterStrip kind="level" data={pstore.data.level} go={go} />
      <div className="split">
        {leftOpen && <div className="panel-l">
          <div className="tabs2" role="tablist">
            {[['objects', 'Objects'], ['layers', 'Layers'], ['prefabs', 'Prefabs'], ['spots', 'Spots']].map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
          {tab === 'layers' && <LayersPanel project={project} ents={view.list} selected={editEnts} onAdd={nm => commit(ED.addLayer(project, nm))} onPatch={(id, p) => commit(ED.patchLayer(project, id, p))}
            onRemove={id => commit(ED.removeLayer(project, id))} onAssign={assignLayer}
            onSelect={id => selection.set(view.list.filter(e => ED.assignOf(project)[keyOf(e.target)] === id).map(e => e.id))} />}
          {tab === 'prefabs' && <PrefabsPanel prefabs={prefabs} canSave={editEnts.length > 0} onSave={savePrefab} onStamp={p => startStamp(p)} stamping={placing?.prefab?.id}
            onDelete={id => setPrefabs(prefabs.filter(p => p.id !== id))} onRename={(id, nm) => setPrefabs(prefabs.map(p => p.id === id ? { ...p, name: nm } : p))} />}
          {tab === 'spots' && <SpotsPanel project={project} noting={placing?.kind === 'note'} onAddSpot={addSpot} onGo={goSpot}
            onRenameSpot={(id, nm) => commit(ED.renameBookmark(project, id, nm))} onRemoveSpot={id => commit(ED.removeBookmark(project, id))}
            onAddNote={startNote} onGoNote={nt => setFocus({ pos: nt.pos, dist: 14 })} onEditNote={(id, tx) => commit(ED.patchNote(project, id, { text: tx }))} onRemoveNote={id => commit(ED.removeNote(project, id))} />}
          {tab === 'objects' && <><div style={{ padding: 8 }}>
            <input placeholder={tr('find_an_object')} aria-label={tr('find_an_object_d6edd0')} value={filter} onChange={e => setFilter(e.target.value)} />
            <div className="chips">
              {[['all', 'All'], ['enemies', 'Enemies'], ['pickups', 'Pickups'], ['vehicles', 'Vehicles'], ['helpers', 'Helpers'], ['level', 'Level'], ['changed', 'Changed']].map(([k, l]) =>
                <button key={k} className={'chip' + (chip === k && panel === 'objects' ? ' on' : '')} onClick={() => { setChip(k); setPanel('objects') }}>{l}</button>)}
              <button className={'chip' + (panel === 'changes' ? ' on' : '')} onClick={() => setPanel(panel === 'changes' ? 'objects' : 'changes')}>{tr('edit_list')}{project.level.length ? ' ' + project.level.length : ''}</button>
            </div>
          </div>
          {panel === 'objects' && <div className="list">
            {!bundle && <div className="muted small" style={{ padding: 8 }}>{tr('open_a_map_to_list_its')}</div>}
            {(hidden.size > 0 || isolate) && <div className="row" style={{ padding: '2px 8px', gap: 6 }}><span className="small muted grow">{isolate ? 'Isolated' : hidden.size + ' hidden'}</span>
              <button className="link" onClick={clearView}>{tr('show_all')}</button></div>}
            {shown.map((e, i) => (
              <div key={e.id} className={'li' + (selection.has(e.id) ? ' sel' : '') + (e.deleted ? ' deleted' : '') + (e.changed ? ' changed' : '') + (!isVisible(e) ? ' hid' : '') + (isLocked(e) ? ' locked' : '')} role="button" tabIndex={0}
                   onClick={ev => {
                     if (ev.shiftKey && selection.primary) {
                       const a = shown.findIndex(x => x.id === selection.primary)
                       if (a >= 0) { selection.set(shown.slice(Math.min(a, i), Math.max(a, i) + 1).filter(x => !isLocked(x)).map(x => x.id), e.id); return }
                     }
                     if (isLocked(e)) return
                     if (ev.ctrlKey || ev.metaKey) selection.toggle(e.id)
                     else { setSelectedId(e.id); setFocus({ pos: e.pos, dist: 18 }) }
                   }} onKeyDown={ev => ev.key === 'Enter' && setSelectedId(e.id)}>
                <button className={'ico' + (isVisible(e) ? ' on' : '')} aria-label={isVisible(e) ? 'Hide' : 'Show'} title={isVisible(e) ? 'Hide' : 'Show'}
                  onClick={ev => { ev.stopPropagation(); const h = new Set(hidden); h.has(e.id) ? h.delete(e.id) : h.add(e.id); setHidden(h) }}>{isVisible(e) ? '◉' : '○'}</button>
                <button className={'ico' + (isLocked(e) ? ' on' : '')} aria-label={isLocked(e) ? 'Unlock' : 'Lock'} title={isLocked(e) ? 'Unlock' : 'Lock'}
                  onClick={ev => { ev.stopPropagation(); const l = new Set(locked); l.has(e.id) ? l.delete(e.id) : l.add(e.id); setLocked(l) }}>{isLocked(e) ? '▣' : '□'}</button>
                <span className="swatch" style={{ background: catColor(e.cat) }} />
                <span className="nm">{e.name || (e.type || '').replace(/\(.*\)/, '') || (e.model || '').split('/').pop()}</span>
                {e.off && <span className="ty" title={tr('disabled_at_load_a_trigger_switches')}>{tr('off_da7a68')}</span>}
                <span className="ty">{KIND_NAME[e.cat] || CAT_LABEL[e.cat]}</span>
              </div>))}
            {bundle && !shown.length && <div className="muted small" style={{ padding: 8 }}>{tr('nothing_here')}</div>}
          </div>}
          {panel === 'changes' && <div className="list changes" style={{ padding: '0 8px' }}>
            {project.level.length === 0 && <p className="muted small">{tr('no_level_changes_yet_select_an')}</p>}
            <ol>{project.level.map((o, i) => <li key={i} onClick={() => {
              const e = o.uid ? view.ents.get('new:' + o.uid) : view.byTarget.get(keyOf(o))
              if (e) { setSelectedId(e.id); setFocus({ pos: e.pos, dist: 18 }) }
            }}>{describeOp(o)}</li>)}</ol>
          </div>}</>}
        </div>}

        {bundle ? (
          <View3D mode={mode} onMode={setMode} bundle={bundle} view={view} layers={layers} showColl={showColl} showGeom={showGeom} bg={vp}
            selectedIds={selection.idSet} primaryId={selectedId} onPick={onPick} onCommitTransform={onCommitTransform} onCommitGroup={onCommitGroup}
            gizmoMode={gizmo} snap={snap} focus={focus} newColl={project.collision} showNewColl={showNewColl} isVisible={isVisible} isLocked={isLocked}
            placing={placing} onPlace={placeAt} tool={tool} scatter={scat} onScatter={onScatter} onMissed={() => selection.clear()}
            boxSelect={gizmo === 'select'} selectables={selectables} onBoxSelect={onBoxSelect} apiRef={viewApi}
            notes={ED.notesOf(project)} onNote={() => setTab('spots')}
            onPadStep={padStep} onPadAdd={padAdd} onPadMode={padMode} padInfo={{ modeName: PAD_NAMES[gizmo] }}>
            {placing && <div className="floatpanel" style={{ left: 12, right: 12, top: 12, margin: '0 auto', width: 'fit-content' }}><b>{placing.label}</b>{pad ? <><span><b>{tr('a')}</b>{' '}{tr('place')}</span><span><b>{tr('lb_rb')}</b>{' '}{tr('turn')}</span><span><b>{tr('b')}</b>{' '}{tr('cancel_4fd065')}</span></> : <><span>{tr('click_to_place')}</span><span><b>{tr('r')}</b>{' '}{tr('or')}{' '}<b>{tr('shift_wheel')}</b>{' '}{tr('turn')}</span><span><b>{tr('esc')}</b>{' '}{tr('cancel_4fd065')}</span></>}</div>}
            {tool === 'scatter' && <ScatterHud cfg={scat} setCfg={setScat} sources={scatterSources} chosen={scatChosen} setChosen={setScatChosen} subs={scatSubs} setSubs={setScatSubs} enums={enums} onClose={() => setTool(null)} />}
            {(tool === 'ruler' || tool === 'figure') && <div className="floatpanel" style={{ left: 12, right: 12, top: 12, margin: '0 auto', width: 'fit-content' }}><b>{tool === 'ruler' ? 'Ruler' : 'Scale figure'}</b><span>{tr('click_to')}{' '}{tool === 'ruler' ? 'add a point' : 'place the figure'}</span><span><b>{tr('esc')}</b>{' '}{tr('done')}</span></div>}
            {busy && <div className="busy">{busy}{'…'}</div>}
            {err && <div className="error" onClick={() => setErr(null)}>{err}</div>}
            <div className="floatpanel" style={{ left: 12, bottom: 12, flexWrap: 'wrap', maxWidth: 'calc(100% - 24px)', whiteSpace: 'normal' }} title={tr('left_drag_orbit_right_drag_pan')}>
              {pad ? <><span><b>{tr('l')}</b>{' '}{tr('fly')}</span><span><b>{tr('r')}</b>{' '}{tr('look')}</span><span><b>{tr('lt_rt')}</b>{' '}{tr('down_up')}</span><span><b>{tr('a')}</b>{' '}{tr('pick')}</span><span><b>{tr('x')}</b>{' '}{tr('add_58d1bb')}</span><span><b>{tr('y')}</b> {PAD_NAMES[gizmo]}</span><span><b>{tr('view_lb_rb')}</b>{' '}{tr('undo_redo')}</span></>
                : <><span><b>{tr('wasd')}</b>{' '}{tr('fly')}</span><span><b>Q E</b>{' '}{tr('down_up')}</span><span><b>{tr('f')}</b>{' '}{tr('focus_78918d')}</span><span><b>G R T</b>{' '}{tr('tools_0284c6')}</span><span><b>{tr('ctrl_d')}</b>{' '}{tr('duplicate_5e4cd5')}</span><span><b>{tr('ctrl_k')}</b>{' '}{tr('search_3559d7')}</span><span><b>{tr('del')}</b>{' '}{tr('delete_948598')}</span></>}
            </div>
            <div className="floatpanel wide-only" style={{ right: 12, bottom: 12 }}><span className="muted">{tr('showing')}</span>
              {showGeom && <span>{'■'}{' '}{tr('models')}</span>}{showColl && <span style={{ color: 'var(--warn)' }}>{'■'}{' '}{tr('collision')}</span>}
              {layers.trigger && <span style={{ color: 'var(--sel)' }}>{'■'}{' '}{tr('trigger_boxes')}</span>}</div>
          </View3D>
        ) : (
          <div className="vp">
            <div className="empty">{busy ? '' : <div><div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-2)', marginBottom: 6 }}>{tr('pick_a_map_to_start')}</div>
              <div style={{ marginBottom: 12 }}>{tr('use_the_map_menu_above_or')}</div>
              <div className="row" style={{ justifyContent: 'center', flexWrap: 'wrap', maxWidth: 560 }}>{(catalog?.maps || []).slice(0, 12).map(m =>
                <button key={m.id} onClick={() => pickAndOpen({ map: m.id, section: null, missions: [] })}>{m.title}</button>)}</div></div>}</div>
            {busy && <div className="busy">{busy}{'…'}</div>}
            {err && <div className="error" onClick={() => setErr(null)}>{err}</div>}
          </div>
        )}

        <div className="panel-r">
          {selection.count > 1 ? (
            <SelectionPanel ents={selEnts} enums={enums} project={project} actions={{ focus: focusSel, move: moveBy, turn: turnBy, align: alignTo, distribute: spread,
              setProp: setOnAll, layer: id => assignLayer(editEnts, id), drop: dropDown, sameModel, prefab: () => { savePrefab(''); setTab('prefabs') }, copy: copySel, duplicate: () => duplicate(), del: () => delMany(selEnts) }} />
          ) : sel ? (
            <Properties e={sel} enums={enums} setProp={setProp} setPos={setPos} onDelete={() => del(sel)}
                        onRestore={() => restore(sel)} onDuplicate={() => duplicate(sel)} addable={addable}
                        onFocus={() => setFocus({ pos: sel.pos, dist: 15 })} setSaveSpot={setSaveSpot} testHere={spot => testActions.run({ spot })} />
          ) : (
            <div className="panel-b">
              <div className="panel-h" style={{ margin: '-12px -12px 0' }}><div><div className="t">{tr('nothing_selected')}</div></div></div>
              {bundle && addable.length > 0 && !addable.some(a => a.ok) && <p className="small" style={{ color: 'var(--warn)' }}>{tr('this_section_cannot_take_new_objects')}</p>}
              {bundle && <p className="muted small">{n(counts2.gameplay)}{' '}{tr('of')}{' '}{n(counts2.total)}{' '}{tr('objects_f0f7f3')}</p>}
            </div>
          )}
        </div>
      </div>
      {findOpen && <FindReplace view={view} enums={enums} onApply={applyReplace} onClose={() => setFindOpen(false)} />}
    </div>
  )
}

function Checks({ checks, onRun, canRun }) {
  if (!checks) return <div style={{ padding: 12 }}><button className="primary" disabled={!canRun} onClick={onRun}>{tr('run_the_check')}</button>{!canRun && <div className="muted small" style={{ marginTop: 6 }}>{tr('change_the_level_first')}</div>}</div>
  if (checks.running) return <div style={{ padding: 12 }}>{tr('checking')}{'…'} {checks.msg || ''}</div>
  if (checks.error) return <div style={{ padding: 12 }}><CheckRow tone="bad" title={tr('the_check_could_not_finish')} fix={checks.error} /><div style={{ padding: 8 }}><button onClick={onRun}>{tr('run_again')}</button></div></div>
  const list = checks.checks
  const order = { error: 0, warn: 1, ok: 2 }
  const sorted = list.slice().sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3))
  const bad = list.filter(c => c.level === 'error').length, warn = list.filter(c => c.level === 'warn').length
  return (
    <div className="checks" style={{ borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
      <div className="ch"><span style={{ fontWeight: 600 }}>{tr('check_results')}</span>
        {bad > 0 && <span style={{ color: 'var(--bad)', fontSize: 12 }}>{bad}{' '}{tr('to_fix')}</span>}{warn > 0 && <span style={{ color: 'var(--warn)', fontSize: 12 }}>{warn}{' '}{tr('warning')}{warn === 1 ? '' : 's'}</span>}
        <span style={{ color: 'var(--ok)', fontSize: 12 }}>{list.length - bad - warn}{' '}{tr('passed')}</span></div>
      <div style={{ maxHeight: 340, overflow: 'auto' }}>
        {sorted.map((c, i) => <CheckRow key={i} tone={c.level === 'error' ? 'bad' : c.level === 'warn' ? 'warn' : 'ok'} title={c.title} fix={[c.area, c.detail].filter(Boolean).join(': ')} />)}</div>
      <div style={{ padding: 8 }}><button className="sm" onClick={onRun}>{tr('run_again')}</button></div>
    </div>
  )
}
