// Blockout: grey boxes first (drag a footprint on the ground), then swap a box for a real piece from a kit (adobe, downtown, industrial,
// hacienda, harbour) built from the shipped models in the asset catalogue. Every piece shows what it costs against the limits.
import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { get } from '../api.js'
import { usePointer } from './hooks.js'
import { heightAt, r2, rectOf, newId } from './geo.js'
import { toV, textSprite, marker, C, LIT } from './layer.js'
import { Sld, Num, Chips, Head, List } from './common.jsx'
import { t as tr } from '../i18n.js'

const mem = { mode: 'draw', height: 4, kit: 'adobe', piece: null }
const LS = 'todms.mapbuild.mine'
const mine = () => { try { return JSON.parse(localStorage.getItem(LS) || '[]') } catch { return [] } }
const saveMine = v => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private window */ } }
const yawOf = b => (b.yaw || 0)
// is a ground point inside the (turned) footprint of a box?
function insideBox(b, x, z) {
  const a = -yawOf(b) * Math.PI / 180, dx = x - b.pos[0], dz = z - b.pos[2]
  const lx = dx * Math.cos(a) - dz * Math.sin(a), lz = dx * Math.sin(a) + dz * Math.cos(a)
  return Math.abs(lx) <= b.size[0] / 2 && Math.abs(lz) <= b.size[2] / 2
}

export default function BlockoutTool({ c, which }) {
  const { map, put, api, layer, grid } = c
  const boxes = map.blockout || []
  const [s, setS] = useState(mem)
  Object.assign(mem, s)
  const set = p => setS(o => ({ ...o, ...p }))
  const [sel, setSel] = useState(boxes.length ? 0 : -1)
  const [kits, setKits] = useState(null), [kitErr, setKitErr] = useState('')
  const [draft, setDraft] = useState(null)
  const [saved, setSaved] = useState(mine)
  const B = useRef(boxes); B.current = boxes
  const S = useRef(s); S.current = s
  const Sel = useRef(sel); Sel.current = sel
  const dr = useRef(draft); dr.current = draft
  const g = useRef(null)
  const gh = (x, z) => (grid.current ? heightAt(grid.current, x, z) : 0)
  useEffect(() => { get('/api/mapbuild/kits').then(setKits).catch(e => setKitErr(e.message || 'No game found')) }, [])

  const shown = draft || boxes
  useEffect(() => {
    if (!layer) return
    const grp = new THREE.Group(); grp.userData = { overlay: true }
    shown.forEach((b, i) => {
      const [w, h, l] = b.size
      const geo = new THREE.BoxGeometry(w, h, l)
      const swapped = !!b.piece
      const m = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: C(swapped ? '#6aa7ff' : '#9aa3ad', LIT), transparent: true, opacity: swapped ? 0.35 : 0.85 }))
      m.position.copy(toV(b.pos[0], b.pos[1] + h / 2, b.pos[2])); m.rotation.y = (yawOf(b) * Math.PI / 180); m.userData = { overlay: true }
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: C(i === sel ? '#f2a541' : swapped ? '#6aa7ff' : '#2b323c'), depthTest: false, transparent: true }))
      e.renderOrder = 14; m.add(e)
      grp.add(m)
      if (swapped) grp.add(marker([b.pos[0], b.pos[1] + h + 1.5, b.pos[2]], 'diamond', '#6aa7ff', 0.026))
      if (i === sel) { const t = textSprite(b.label || b.id, '#ffffff', 0.03); t.position.copy(toV(b.pos[0], b.pos[1] + h + 3, b.pos[2])); grp.add(t) }
    })
    layer.set('blockout', grp)
    return () => layer.drop('blockout')
  }, [layer, shown, sel])

  const put1 = list => put({ blockout: list })
  const mk = (x0, z0, x1, z1, piece) => {
    const r = rectOf([x0, z0], [x1, z1])
    const w = Math.max(1, r[2] - r[0]), l = Math.max(1, r[3] - r[1])
    const cx = (r[0] + r[2]) / 2, cz = (r[1] + r[3]) / 2
    return { id: newId(B.current, 'box'), pos: [r2(cx), r2(gh(cx, cz)), r2(cz)], size: [r2(w), piece ? (piece.size?.[1] || 3) : S.current.height, r2(l)], yaw: 0, ...(piece ? { piece: { model: piece.path, name: piece.name } } : {}) }
  }
  const place = (x, z) => {
    const p = S.current.mode === 'piece' ? S.current.piece : null
    const w = p ? Math.max(1, Math.min(40, p.size?.[0] || 4)) : 6, l = p ? Math.max(1, Math.min(40, p.size?.[2] || 4)) : 6
    const b = mk(x - w / 2, z - l / 2, x + w / 2, z + l / 2, p)
    put1([...B.current, b]); setSel(B.current.length)
  }
  usePointer(api, {
    active: true,
    onDown: h => {
      const p = [h.pos[0], h.pos[2]], m = S.current.mode
      if (m === 'select') {
        const k = B.current.findIndex(b => insideBox(b, p[0], p[1]))
        if (k < 0) return false
        setSel(k); g.current = { move: k, from: p, orig: B.current[k].pos }; return true
      }
      if (m === 'piece') { g.current = { placeAt: p }; return true }
      g.current = { from: p }; setDraft([...B.current, mk(p[0], p[1], p[0] + 1, p[1] + 1)]); return true
    },
    onMove: h => {
      const gg = g.current; if (!gg || gg.placeAt) return
      const p = [h.pos[0], h.pos[2]]
      if (gg.move != null) { const dx = p[0] - gg.from[0], dz = p[1] - gg.from[1]; setDraft(B.current.map((b, i) => (i === gg.move ? { ...b, pos: [r2(gg.orig[0] + dx), r2(gh(gg.orig[0] + dx, gg.orig[2] + dz)), r2(gg.orig[2] + dz)] } : b))); return }
      setDraft([...B.current, mk(gg.from[0], gg.from[1], p[0], p[1])])
    },
    onUp: () => {
      const gg = g.current; g.current = null
      const d = dr.current; setDraft(null)
      if (gg?.placeAt) { place(gg.placeAt[0], gg.placeAt[1]); return }
      if (!gg || !d) return
      if (gg.move != null) { put1(d); return }
      const last = d[d.length - 1]
      if (last.size[0] > 1.2 || last.size[2] > 1.2) { put1(d); setSel(d.length - 1) } else place(gg.from[0], gg.from[1])
    },
    onKey: e => {
      if (e.key === 'Enter' && !['BUTTON', 'A'].includes(e.target?.tagName) && api?.centerPoint) { const p = api.centerPoint(); place(p[0], p[2]) }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && Sel.current >= 0) { put1(B.current.filter((_, i) => i !== Sel.current)); setSel(-1) }
    },
    onPad: (name, h) => { if (name === 'A') place(h.pos[0], h.pos[2]) },
  })

  const b = boxes[sel]
  const edit = patch => put1(boxes.map((x, i) => (i === sel ? { ...x, ...patch } : x)))
  const kit = kits?.kits?.find(k => k.id === s.kit)
  const piece = s.piece
  return <div className="mb-body">
    <Chips label={tr('mode_a7b93d')} value={s.mode} onChange={v => set({ mode: v })} options={[{ value: 'draw', label: tr('draw_box'), tip: tr('drag_a_footprint_on_the_ground') }, { value: 'select', label: tr('move'), tip: tr('click_a_box_drag_to_move') }, { value: 'piece', label: tr('place_piece'), tip: tr('click_the_ground_to_put_the') }]} />
    {s.mode !== 'piece' && <Sld label={tr('height')} value={s.height} min={1} max={30} step={0.5} unit="m" onChange={v => set({ height: v })} />}
    <Head>{tr('boxes')}</Head>
    <List items={boxes} sel={sel} onSel={setSel} onDelete={i => { put1(boxes.filter((_, k) => k !== i)); setSel(-1) }} name={x => x.label || x.id} extra={x => (x.piece ? '◆ ' + x.piece.name : '')} />
    {b && <>
      <Num label={tr('width')} value={b.size[0]} unit="m" digits={1} onChange={v => edit({ size: [v, b.size[1], b.size[2]] })} />
      <Num label={tr('height')} value={b.size[1]} unit="m" digits={1} onChange={v => edit({ size: [b.size[0], v, b.size[2]] })} />
      <Num label={tr('length')} value={b.size[2]} unit="m" digits={1} onChange={v => edit({ size: [b.size[0], b.size[1], v] })} />
      <Num label={tr('turn_368e80')} value={b.yaw || 0} unit="°" digits={0} onChange={v => edit({ yaw: v })} />
      {b.piece ? <div className="mb-btns"><span className="small" title={b.piece.model}>{'◆ ' + b.piece.name}</span><button onClick={() => edit({ piece: undefined })}>{tr('back_to_a_box')}</button></div>
        : piece ? <div className="mb-btns"><button className="soft" onClick={() => edit({ piece: { model: piece.path, name: piece.name } })} title={tr('the_box_becomes_this_piece_when')}>{tr('swap_for', { name: piece.name })}</button></div> : <p className="small muted mb-hint">{tr('pick_a_piece_below_to_swap')}</p>}
    </>}
    <Head>{tr('kits')}</Head>
    {kitErr && <p className="small warn">{kitErr}</p>}
    {kits && !kits.ready && <p className="small muted">{tr('the_game_s_pieces_are_not')}</p>}
    {kits?.kits && <Chips label={tr('kit')} value={s.kit} onChange={v => set({ kit: v })} options={[...kits.kits.map(k => ({ value: k.id, label: k.label })), { value: 'mine', label: tr('mine') }]} />}
    <div className="mb-pieces" role="listbox" aria-label={tr('pieces')}>
      {(s.kit === 'mine' ? saved : kit?.pieces || []).map(p => <button key={p.key || p.name} role="option" aria-selected={piece?.key === p.key} className={'mb-piece' + (piece?.key === p.key ? ' on' : '')}
        title={tr('piece_cost', { name: p.name, tris: p.tris })} onClick={() => set({ piece: p, mode: 'piece' })}>
        <span className="nm">{p.name}</span><span className="ct">{'△ ' + p.tris + ' · 1 node'}</span></button>)}
    </div>
    {piece && <div className="mb-stat" title={tr('what_one_placed_piece_adds_to')}>{`${piece.name}: 1 node · ${piece.tris} triangles`}</div>}
    {piece && s.kit !== 'mine' && <button className="sm" onClick={() => { const v = [...saved.filter(x => x.key !== piece.key), piece]; setSaved(v); saveMine(v) }}>{tr('keep_in_mine')}</button>}
  </div>
}
