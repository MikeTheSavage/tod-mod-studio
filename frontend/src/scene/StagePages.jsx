// The pages that run a stage of the backend and show what came out: Clean, Textures, Sections, Collision.
import React, { useEffect, useMemo, useState } from 'react'
import { post } from '../api.js'
import { Seg, Switch, NumField } from '../ui.jsx'
import { Meter } from '../Meters.jsx'
import { t as tr } from '../i18n.js'
import SceneCanvas from './SceneCanvas.jsx'

const n0 = v => v == null ? '–' : Math.round(v).toLocaleString()
const kb = v => v >= 1048576 ? (v / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(v / 1024)) + ' KB'
const SURFACES = ['AllRound', 'Metal', 'Concrete', 'Wood', 'Dirt', 'Stone', 'Glass', 'Bush', 'Wirefence', 'Grass', 'Asphalt', 'Water', 'Cloth', 'SolidGlass']

function Rows({ rows }) {
  return <table className="scene-table"><tbody>{rows.filter(r => r).map(([k, v, tip]) => <tr key={k} title={tip}><td>{k}</td><td className="num">{v}</td></tr>)}</tbody></table>
}

function useGlbUrl(S, stage, deps) {
  const [g, setG] = useState(null)
  useEffect(() => {
    if (!S.sc || !S.params.region.polygon) { setG(null); return }
    let live = true
    post('/api/scene/glb', { sid: S.sc.sid, params: S.params, stage }).then(r => { if (live) setG(r) }).catch(e => { if (live) S.setErr(e.message) })
    return () => { live = false }
  }, [S.sc?.sid, stage, JSON.stringify(S.params.region), S.params.scale, S.params.up, S.params.mirror, S.params.yaw, JSON.stringify(S.params.clean), ...deps])
  return g
}

function Shell({ S, left, children, next, nextPage, runLabel, stage, glb }) {
  const ok = S.sc && S.params.region.polygon
  return (
    <div className="split">
      <div className="panel-l" style={{ width: 'calc(var(--side-l) + 40px)' }}>
        <div className="panel-b">
          {left}
          <div className="row" style={{ marginTop: 6 }}>
            <button className="primary" disabled={!ok || !!S.busy} onClick={() => S.run(stage)}>{runLabel}</button>
            {next && <button onClick={() => S.setPage(nextPage)} disabled={!S.rep[stage]}>{tr('next')}</button>}
          </div>
          {!ok && <div className="muted small">{tr('draw_the_region_first')}</div>}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, position: 'relative', background: 'var(--vp)' }}>
        {glb ? <SceneCanvas url={glb.url} /> : children || <div className="empty">{S.busy || ''}</div>}
        {glb && <div className="hint" style={{ position: 'absolute', left: 10, bottom: 8 }}>{glb.triangles.toLocaleString()} {tr('triangles')}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- Clean
export function CleanPage({ S }) {
  const { params, edit, rep } = S
  const c = params.clean
  const set = (k, v) => edit(p => ({ ...p, clean: { ...p.clean, [k]: v } }))
  const r = rep.clean
  const glb = useGlbUrl(S, r ? 'clean' : 'select', [!!r])
  const left = <>
    <h4 style={{ marginTop: 0 }}>{tr('remove')}</h4>
    <label className="check"><Switch on={c.drop_exact} onChange={v => set('drop_exact', v)} />{' '}{tr('repeated_triangles')}</label>
    <label className="check"><Switch on={c.drop_near} onChange={v => set('drop_near', v)} />{' '}{tr('overlapping_draws')}</label>
    <label className="check"><Switch on={c.strays} onChange={v => set('strays', v)} />{' '}{tr('stray_islands')}</label>
    {c.strays && <div className="row"><span className="muted" style={{ flex: 'none' }}>{tr('far')}</span><NumField value={c.far_m} digits={0} unit="m" onCommit={v => v > 1 && set('far_m', v)} label={tr('far')} /></div>}
    <label className="check"><Switch on={c.weld_vertices} onChange={v => set('weld_vertices', v)} />{' '}{tr('weld_vertices')}</label>
    {r && <>
      <h4>{tr('removed')}</h4>
      <Rows rows={[[tr('triangles'), n0(r.triangles_in) + ' → ' + n0(r.triangles_out)], [tr('repeated'), n0(r.exact)], [tr('overlapping'), n0(r.near)], [tr('degenerate'), n0(r.degenerate)],
        [tr('far_islands'), n0(r.far) + ' (' + n0(r.far_islands) + ')'], [tr('specks'), n0(r.tiny) + ' (' + n0(r.tiny_islands) + ')'], [tr('vertices'), n0(r.vertices_in) + ' → ' + n0(r.vertices_out)]]} />
    </>}
  </>
  return <Shell S={S} left={left} runLabel={tr('clean')} stage="clean" next nextPage="textures" glb={glb} />
}

// ---------------------------------------------------------------------------------------------- Textures
export function TexturesPage({ S }) {
  const { params, edit, rep } = S
  const t = params.textures
  const set = (k, v) => edit(p => ({ ...p, textures: { ...p.textures, [k]: v } }))
  const r = rep.textures?.report
  const left = <>
    <h4 style={{ marginTop: 0 }}>{tr('size')}</h4>
    <div className="row"><Seg value={String(t.max_tex)} onChange={v => set('max_tex', Number(v))} options={['64', '128', '256', '512'].map(v => ({ value: v, label: v }))} /></div>
    <label className="check"><Switch on={t.atlas} onChange={v => set('atlas', v)} />{' '}{tr('merge_small_pictures')}</label>
    <div className="row" title={tr('the_whole_set_of_pictures_stays')}><span className="muted" style={{ flex: 'none' }}>{tr('budget')}</span><NumField value={t.budget_mb} digits={0} unit="MB" onCommit={v => v > 1 && set('budget_mb', v)} label={tr('budget')} /></div>
  </>
  return (
    <Shell S={S} left={left} runLabel={tr('convert')} stage="textures" next nextPage="sections">
      {r ? <div className="scene-sheet">
        <div className="scene-facts">
          <Fact k={tr('pictures')} v={n0(r.pictures_in)} /><Fact k={tr('unique')} v={n0(r.slots)} /><Fact k={tr('scene_merged')} v={n0(r.duplicates_merged)} />
          <Fact k={tr('textures')} v={n0(r.textures)} /><Fact k={tr('atlas_pages')} v={n0(r.atlas.reduce((a, x) => a + x.pages, 0))} /><Fact k={tr('tiling')} v={n0(r.wrapping)} />
          <Fact k={tr('scene_cut_out')} v={n0(r.cutout)} /><Fact k={tr('see_through')} v={n0(r.blend)} /><Fact k={tr('total')} v={kb(r.bytes)} />
        </div>
        {(rep.textures.meters || []).map(m => <Meter key={m.id} r={m} />)}
        {rep.textures.notes.map((x, i) => <div key={i} className="warn small">{x}</div>)}
        <h4>{tr('pictures')}</h4>
        <table className="scene-table"><tbody>{rep.textures.list.slice(0, 40).map(x => <tr key={x.name}><td>{x.size}×{x.size}</td><td>{x.format}</td><td>{x.atlas ? tr('atlas') : ''}</td><td className="num">{kb(x.bytes)}</td></tr>)}</tbody></table>
      </div> : <div className="empty">{S.busy || ''}</div>}
    </Shell>
  )
}

const Fact = ({ k, v }) => <div className="fact"><div className="v">{v}</div><div className="k">{k}</div></div>

// ---------------------------------------------------------------------------------------------- Sections
const tone = (used, cap) => used > cap ? 'bad' : used >= 0.7 * cap ? 'warn' : 'ok'

export function SectionsPage({ S }) {
  const { params, edit, rep } = S
  const sp = params.sections
  const set = (k, v) => edit(p => ({ ...p, sections: { ...p.sections, [k]: v } }))
  const r = rep.chunks
  const cap = 120000
  const left = <>
    <h4 style={{ marginTop: 0 }}>{tr('sections')}</h4>
    <div className="row"><Seg value={String(sp.section_m)} onChange={v => set('section_m', Number(v))} options={['64', '128', '256'].map(v => ({ value: v, label: v + ' m' }))} /></div>
    <label className="check" title={tr('only_where_a_section_is_over_its_budget')}><Switch on={sp.reduce} onChange={v => set('reduce', v)} />{' '}{tr('reduce_triangles')}</label>
    <label className="check"><Switch on={sp.double_sided} onChange={v => set('double_sided', v)} />{' '}{tr('both_sides_of_see_through_parts')}</label>
    {r && <>
      <h4>{tr('result')}</h4>
      <Rows rows={[[tr('sections'), n0(r.stats.sections)], [tr('parts'), n0(r.stats.objects)], [tr('triangles'), n0(r.stats.tris_in) + ' → ' + n0(r.stats.tris_out)], [tr('reduced'), n0(r.stats.reduced_objects)],
        [tr('most_pictures'), n0(r.stats.max_textures)]]} />
      {r.notes.map((x, i) => <div key={i} className="warn small">{x}</div>)}
    </>}
  </>
  return (
    <Shell S={S} left={left} runLabel={tr('plan')} stage="chunks" next nextPage="collision">
      {r ? <div className="scene-sheet">
        <SectionMap sections={r.sections} objects={r.objects} cap={cap} />
        <table className="scene-table"><thead><tr><th>{tr('section')}</th><th className="num">{tr('parts')}</th><th className="num">{tr('triangles')}</th><th className="num">{tr('kept')}</th></tr></thead>
          <tbody>{r.sections.map(s => <tr key={s.id} className={'t-' + tone(s.tris_out, cap)}><td>{s.id}</td><td className="num">{s.objects}</td>
            <td className="num">{n0(s.tris_in)} → {n0(s.tris_out)}</td><td className="num">{Math.round(100 * s.tris_out / Math.max(1, s.tris_in))}%</td></tr>)}</tbody></table>
      </div> : <div className="empty">{S.busy || ''}</div>}
    </Shell>
  )
}

function SectionMap({ sections, objects, cap }) {
  const xs = sections.flatMap(s => [s.box[0], s.box[2]]), zs = sections.flatMap(s => [s.box[1], s.box[3]])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs)
  const w = x1 - x0, h = z1 - z0
  return (
    <svg className="scene-map" viewBox={`${x0 - 4} ${-z1 - 4} ${w + 8} ${h + 8}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={tr('sections')}>
      {sections.map(s => <rect key={s.id} x={s.box[0]} y={-s.box[3]} width={s.box[2] - s.box[0]} height={s.box[3] - s.box[1]} className={'sec ' + tone(s.tris_out, cap)} />)}
      {objects.map(o => <rect key={o.id} x={o.box[0] + 0} y={-o.box[3]} width={Math.max(0.5, o.box[2] - o.box[0])} height={Math.max(0.5, o.box[3] - o.box[1])} className="obj" />)}
      {sections.map(s => <text key={s.id + 't'} x={s.box[0] + 3} y={-s.box[3] + 8} className="lbl" style={{ fontSize: Math.max(3, w / 60) }}>{n0(s.tris_out / 1000)}{tr('k')}</text>)}
    </svg>
  )
}

// ---------------------------------------------------------------------------------------------- Collision
export function CollisionPage({ S }) {
  const { params, edit, rep } = S
  const cp = params.collision
  const r = rep.collision
  const set = (k, v) => edit(p => ({ ...p, collision: { ...p.collision, [k]: v } }))
  const setSurface = (id, v) => edit(p => ({ ...p, collision: { ...p.collision, surface: { ...p.collision.surface, [id]: v } } }))
  const left = <>
    <h4 style={{ marginTop: 0 }}>{tr('collision')}</h4>
    <label className="check"><Switch on={cp.enabled} onChange={v => set('enabled', v)} />{' '}{tr('solid_ground_and_walls')}</label>
    {r && <>
      <h4>{tr('result')}</h4>
      <Rows rows={[[tr('pieces'), n0(r.stats.pieces)], [tr('cut_outs'), n0(r.stats.skipped_cutout) + ' ' + tr('triangles')], [tr('small_parts'), n0(r.stats.skipped_small) + ' ' + tr('triangles')]]} />
      {(r.notes || []).map((x, i) => <div key={i} className="muted small">{x}</div>)}
    </>}
  </>
  return (
    <Shell S={S} left={left} runLabel={tr('generate')} stage="collision" next nextPage="send">
      {r ? <div className="scene-sheet">
        <h4 style={{ marginTop: 0 }}>{tr('surface')}</h4>
        <table className="scene-table"><thead><tr><th>{tr('material')}</th><th className="num">{tr('triangles')}</th><th>{tr('surface')}</th></tr></thead>
          <tbody>{r.classes.map(c => <tr key={c.id}><td title={c.name}>{c.name.length > 26 ? c.name.slice(0, 26) + '…' : c.name}</td><td className="num">{n0(c.tris)}</td>
            <td>{c.kind && c.kind !== 'opaque' ? <span className="muted">{tr('none_6eef66')}</span> :
              <select value={cp.surface[c.id] || c.surface || 'Concrete'} onChange={e => setSurface(c.id, e.target.value)} aria-label={tr('surface')}>{SURFACES.map(x => <option key={x} value={x}>{x}</option>)}</select>}</td></tr>)}</tbody></table>
      </div> : <div className="empty">{S.busy || ''}</div>}
    </Shell>
  )
}
