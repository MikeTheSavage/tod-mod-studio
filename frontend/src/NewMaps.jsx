import React, { useEffect, useState } from 'react'
import { get, post, runJob } from './api.js'
import LoaderTopView, { spotYaw, yawOrient } from './LoaderTopView.jsx'

const downtown = 'submap01_map02_lostoros_downtown.submap'
const parent = { fragment: 'SUBMAP01_Map02_LosToros_Downtown.fragment', entity: 'SUBMAP01_Map02_Geometry' }
const short = e => e?.split('/').pop()
const freshSpot = () => ({ pos: [0, 0, 0], orient: [0, 0, 0, 1], size: [12, 6, 2] })
const entryList = m => [...(m.entry ? [{ ...m.entry, id: m.entry.id || 'entry' }] : []), ...(m.entries || [])]

function SpotFields({ spot, change, box = false }) {
  return <>
    <label>Position (x, y height, z)</label><div className="row3">{spot.pos.map((v, i) => <input key={i} aria-label={['x', 'height', 'z'][i]} type="number" step="any" value={v}
      onChange={e => change({ ...spot, pos: spot.pos.map((n, j) => j === i ? Number(e.target.value) : n) })} />)}</div>
    <label className="kv">Facing (degrees)<input type="number" step="any" value={Math.round(spotYaw(spot) * 1000) / 1000}
      onChange={e => change({ ...spot, orient: yawOrient(Number(e.target.value)) })} /></label>
    {box && <><label>Box size (width, height, length)</label><div className="row3">{(spot.size || [12, 6, 2]).map((v, i) =>
      <input key={i} aria-label={['width', 'box height', 'length'][i]} type="number" min="0.01" step="any" value={v}
        onChange={e => change({ ...spot, size: (spot.size || [12, 6, 2]).map((n, j) => j === i ? Number(e.target.value) : n) })} />)}</div></>}
  </>
}

export default function NewMaps() {
  const [library, setLibrary] = useState({ projects: [], sources: {} })
  const [project, setProject] = useState(null), [mapIndex, setMapIndex] = useState(0)
  const [catalog, setCatalog] = useState([]), [volumes, setVolumes] = useState([])
  const [selected, setSelected] = useState('entry:0'), [view, setView] = useState('entries')
  const [busy, setBusy] = useState(null), [message, setMessage] = useState(''), [report, setReport] = useState(null)
  const [importPath, setImportPath] = useState(''), [dirty, setDirty] = useState(false)
  const [hosts, setHosts] = useState(null)
  useEffect(() => { runJob('/api/newmaps', { action: 'hosts' }).then(r => setHosts(r.supported ? Object.fromEntries(r.hosts.map(h => [h.block, h])) : null)).catch(() => setHosts(null)) }, [])
  const refresh = async () => setLibrary(await get('/api/newmaps'))
  useEffect(() => { refresh().catch(e => setMessage(e.message)); get('/api/catalog').then(c => setCatalog(c.maps)).catch(e => setMessage(e.message)) }, [])
  const params = project?.params, m = params?.maps[mapIndex], es = m ? entryList(m) : []
  const [kind, number] = selected.split(':'), index = Number(number)
  const active = m && (kind === 'entry' ? es[index] : kind === 'teleport' ? (m.teleports || [])[index] : m[kind])
  const block = kind === 'entry' ? active?.block : es[0]?.block
  useEffect(() => {
    let current = true
    setVolumes([])
    if (block) runJob('/api/sections/catalog', { entries: [block] }).then(c => { if (current) setVolumes(c.volumes || []) }).catch(e => { if (current) setMessage(e.message) })
    return () => { current = false }
  }, [block])
  const choose = p => {
    if (dirty && !confirm('Discard unsaved new-map changes?')) return
    setProject(structuredClone(p)); setMapIndex(0); setDirty(false); setReport(null); setSelected('entry:0')
  }
  const edit = next => { setProject({ ...project, params: next }); setDirty(true); setReport(null) }
  const editMap = next => edit({ ...params, maps: params.maps.map((v, i) => i === mapIndex ? next : v) })
  const setEntries = rows => { const next = { ...m, entries: rows }; delete next.entry; editMap(next) }
  const editSpot = next => {
    if (kind === 'entry') setEntries(es.map((v, i) => i === index ? next : v))
    else if (kind === 'teleport') editMap({ ...m, teleports: (m.teleports || []).map((v, i) => i === index ? next : v) })
    else editMap({ ...m, [kind]: next })
  }
  const save = async () => {
    const p = await post('/api/newmaps', { action: 'save', id: project.id, params })
    setProject(p); setDirty(false); await refresh(); return p
  }
  const action = async name => {
    setBusy(name); setMessage('')
    try {
      const p = name === 'uninstall' ? project : await save()
      if (name === 'save') { setMessage('Project saved'); return }
      const r = await runJob('/api/newmaps', { action: name, id: p.id }, j => setBusy(j.message || name))
      if (r.report) setReport(r.report)
      setMessage(r.folder ? `Output: ${r.folder}` : r.message || r.configpc_line || 'Done')
      const lib = await get('/api/newmaps'); setLibrary(lib)
      setProject(lib.projects.find(v => v.id === p.id) || p)
    } catch (e) { setMessage(e.message) } finally { setBusy(null) }
  }
  const create = () => {
    if (dirty && !confirm('Discard unsaved new-map changes?')) return
    const key = Object.keys(library.sources)[0], source = library.sources[key]
    if (!source) return
    setProject({ params: { package: 'My new map', maps: [{ name: source.map_name.replace('Map10', 'Map11'), source: key,
      arrival: { pos: [980.5, 4.7, 337], orient: [0, 0, 0, 1], floor: 'vanilla' },
      entries: [{ ...freshSpot(), id: 'entry_1', block: downtown, parent, pos: [-237, 2.5, -43.66] }],
      return: { ...freshSpot(), pos: [980.5, 6, 330], target_map: 'MAINMAP_Map02_LosToros_Downtown',
        target_submap: 'SUBMAP01_Map02_LosToros_Downtown', teleport_to: 'TELEPORTPOINT_SubM_10_Down_Mex_Sho_GunKill', teleport_block: 'overdose.main' }, teleports: [] }] } })
    setMapIndex(0); setDirty(true); setSelected('entry:0'); setReport(null)
  }
  const importFile = async () => {
    if (dirty && !confirm('Discard unsaved new-map changes?')) return
    try { const p = await post('/api/newmaps', { action: 'import', path: importPath }); setDirty(false); setProject(p); setMapIndex(0); setSelected('entry:0'); setReport(null); await refresh() }
    catch (e) { setMessage(e.message) }
  }
  const blocks = catalog.flatMap(c => [{ entry: c.map_block, title: c.title + ' — map' }, ...c.sections.map(s => ({ ...s, title: c.title + ' — ' + s.title }))])
  const spots = !m ? [] : view === 'entries' ? es.filter(e => short(e.block) === short(block)).map(e => ({ ...e, id: 'entry:' + es.indexOf(e), label: e.id }))
    : [{ ...m.arrival, id: 'arrival', label: 'Main arrival', color: '#79ee96' }, { ...m.return, id: 'return', label: 'Return', color: '#ffd166' },
      ...(m.teleports || []).map((t, i) => ({ ...t, id: 'teleport:' + i, label: t.name }))]
  return <div className="editor sections" style={{ gridTemplateColumns: 'minmax(0, 1fr) 390px' }}>
    <div className="viewport" style={{ background: '#141920', overflow: 'auto', padding: 16 }}>
      <section className="box"><h3>New maps</h3><div className="row"><select aria-label="New-map project" value={project?.id || ''} onChange={e => choose(library.projects.find(p => p.id === e.target.value))}>
        <option value="" disabled>Choose a project</option>{library.projects.map(p => <option key={p.id} value={p.id}>{p.params.package}</option>)}</select><button onClick={create}>Create project</button></div>
        <div className="row"><input aria-label="Recipe or build path" placeholder="PARAMS JSON path or build folder" value={importPath} onChange={e => setImportPath(e.target.value)} /><button onClick={importFile}>Import</button></div>
        <p className="muted">Projects are saved separately from the current mod. Choose a project, add entry boxes in an existing section, then Check and Build.</p>
        {!library.entries_supported && <p className="warning">This bundled builder supports one entry to the main arrival. Multiple entries and named destinations can be saved here, but need a newer recipe before building.</p>}
      </section>
      {m && <><div className="row"><select value={mapIndex} onChange={e => { setMapIndex(Number(e.target.value)); setSelected('entry:0') }}>{params.maps.map((v, i) => <option key={i} value={i}>{v.name}</option>)}</select>
        <button className={view === 'entries' ? 'primary' : ''} onClick={() => { setView('entries'); setSelected('entry:0') }}>Existing map entries</button>
        <button className={view === 'newmap' ? 'primary' : ''} onClick={() => { setView('newmap'); setSelected('arrival') }}>Inside new map</button></div>
        <p className="muted">North is up. Click a spot to select it. Click empty space to place the selected spot; height stays as typed. Arrows show facing. {view === 'entries' ? 'Existing loader boxes are shown for reference.' : 'This view shows your spots; the cloned terrain is not drawn.'}</p>
        <LoaderTopView volumes={view === 'entries' ? volumes : []} spots={spots} selected={selected}
          onSelect={id => { if (id.startsWith('entry:') || id.startsWith('teleport:') || ['arrival', 'return'].includes(id)) setSelected(id) }}
          onPlace={xz => { if (active) editSpot({ ...active, pos: [Number(xz[0].toFixed(2)), active.pos[1], Number(xz[1].toFixed(2))] }) }} />
        <section className="box"><h3>Entry spots</h3>{es.map((e, i) => <div className="row" key={i}><button className={selected === 'entry:' + i ? 'primary' : ''} onClick={() => { setSelected('entry:' + i); setView('entries') }}>{e.id || 'Entry'} — {short(e.block)} → {e.arrive_at || 'Main arrival'}</button>
          <button onClick={() => { setEntries(es.filter((_, j) => i !== j)); setSelected('arrival') }}>Delete</button></div>)}
          <button onClick={() => { setEntries([...es, { ...freshSpot(), id: 'entry_' + Date.now().toString(36), block: block || downtown, ...(short(block || downtown) === downtown ? { parent } : {}) }]); setSelected('entry:' + es.length); setView('entries') }}>Add entry spot</button>
        </section>
        <section className="box"><h3>Named arrivals inside the new map</h3>{(m.teleports || []).map((t, i) => <div className="row" key={i}><button onClick={() => { setSelected('teleport:' + i); setView('newmap') }}>{t.name}</button><button onClick={() => {
          if (es.some(e => e.arrive_at === t.name)) { setMessage('Choose another arrival for entries using this spot before deleting it.'); return }
          editMap({ ...m, teleports: m.teleports.filter((_, j) => j !== i) }); setSelected('arrival')
        }}>Delete</button></div>)}<button onClick={() => { editMap({ ...m, teleports: [...(m.teleports || []), { name: 'SPOT_' + Date.now().toString(36), pos: [...m.arrival.pos], orient: [0, 0, 0, 1] }] }); setSelected('teleport:' + (m.teleports || []).length); setView('newmap') }}>Add named arrival</button>
        </section></>}
      {message && <section className="box" role="status" style={{ overflowWrap: 'anywhere' }}>{message}</section>}
      {report && <section className="box"><h3>{report.result}</h3><p className="muted">Check reads the recipe and destinations. Build performs the full block, collision and archive checks.</p><ul className="checklist">{(report.checks || []).map((c, i) => <li key={i} className={c.result === 'PASS' ? 'ok' : c.result === 'WARN' ? 'warning' : 'error'}><b>{c.result}: {c.check}</b> — {c.evidence}</li>)}</ul></section>}
    </div>
    <aside className="panel" style={{ overflow: 'auto' }}>{m && <>
      <section className="box"><h3>Project {dirty && '• unsaved'}</h3><label className="kv">Package name<input value={params.package || ''} onChange={e => edit({ ...params, package: e.target.value })} /></label>
        <label className="kv">Map name<input value={m.name} onChange={e => editMap({ ...m, name: e.target.value })} /></label>
        <label className="kv">Clone source<select value={m.source} onChange={e => editMap({ ...m, source: e.target.value, nodes_in: library.sources[e.target.value].subparent ? 'submap' : 'map' })}>{Object.entries(library.sources).map(([k, v]) => <option key={k} value={k}>{v.map_name}</option>)}</select></label>
        <p className="muted">Map name needs exactly {library.sources[m.source]?.map_name.length} characters, the same length as the clone source. Choose an unused map number. {library.sources[m.source]?.status}</p>
        {params.import_warning && <p className="warning">{params.import_warning}</p>}
        <div className="row"><button disabled={!!busy} onClick={() => action('save')}>Save project</button><button disabled={!!busy} onClick={() => action('check')}>Check</button><button disabled={!!busy} onClick={() => action('build')}>Build</button></div>
        <div className="row"><button disabled={!!busy || dirty || !project.build?.sha256} onClick={() => action('install')}>Install package</button><button disabled={!!busy || !project.id} onClick={() => action('uninstall')}>Uninstall package</button></div>
        {project.path && <p className="muted" style={{ overflowWrap: 'anywhere' }}>Saved in {project.path}</p>}
      </section>
      <section className="box"><div className="row"><button onClick={() => { setSelected('arrival'); setView('newmap') }}>Main arrival</button><button onClick={() => { setSelected('return'); setView('newmap') }}>Return spot</button></div>
        {active && <><h3>{kind === 'entry' ? 'Entry box' : kind === 'teleport' ? 'Named arrival' : kind === 'return' ? 'Return box' : 'Main arrival'}</h3>
          {kind === 'entry' && <><label className="kv">Spot name<input value={active.id || ''} onChange={e => editSpot({ ...active, id: e.target.value })} /></label>
            <label>Existing map and section<select value={blocks.find(b => short(b.entry) === short(active.block))?.entry || active.block} onChange={e => { const next = { ...active, block: short(e.target.value) }; delete next.parent; if (short(next.block) === downtown) next.parent = parent; editSpot(next) }}>
              {!blocks.some(b => short(b.entry) === short(active.block)) && <option value={active.block}>{active.block}</option>}{blocks.map(b => { const h = hosts?.[short(b.entry)]; return <option key={b.entry} value={b.entry} disabled={!!h && !h.offer} title={h ? (h.offer ? h.proven : h.reason) : ''}>
                {b.title}{h ? (!h.offer ? ' (cannot take an entry)' : /^proven/.test(h.proven) ? ' (tested in game)' : '') : ''}</option> })}</select></label>
            {hosts && (h => h && <p className="muted small">{h.offer ? (/^proven/.test(h.proven) ? 'Tested in the game: an entry here works.' : 'Allowed, but not tested in the game yet: try it in a test save first.') : 'This section cannot take an entry: ' + h.reason}</p>)(hosts[short(active.block)])}
            <label className="kv">Arrive at<select value={active.arrive_at || ''} onChange={e => editSpot({ ...active, arrive_at: e.target.value })}><option value="">Main arrival</option>{(m.teleports || []).map(t => <option key={t.name}>{t.name}</option>)}</select></label>
            <details><summary>Parent folder (optional with newer builder)</summary>{['fragment', 'entity'].map(k => <label key={k}>{k}<input value={active.parent?.[k] || ''} onChange={e => editSpot({ ...active, parent: { ...active.parent, [k]: e.target.value } })} /></label>)}</details></>}
          {kind === 'teleport' && <label className="kv">Name<input value={active.name} onChange={e => {
            const name = e.target.value
            const next = { ...m, teleports: m.teleports.map((v, i) => i === index ? { ...v, name } : v), entries: es.map(v => v.arrive_at === active.name ? { ...v, arrive_at: name } : v) }
            delete next.entry
            editMap(next)
          }} /></label>}
          <SpotFields spot={active} change={editSpot} box={kind === 'entry' || kind === 'return'} />
          {kind === 'arrival' && <label>Ground check<select value={active.floor || 'vanilla'} onChange={e => editSpot({ ...active, floor: e.target.value })}><option value="vanilla">Use the source map's ground</option><option value="none">Require new solid ground</option></select></label>}
          {kind === 'return' && ['target_map', 'target_submap', 'teleport_to', 'teleport_block'].map(k => <label key={k}>{({ target_map: 'Return map name', target_submap: 'Return section name', teleport_to: 'Return arrival node', teleport_block: 'Block containing that node' })[k]}<input value={active[k] || ''} onChange={e => editSpot({ ...active, [k]: e.target.value })} /></label>)}
        </>}
      </section>
    </>}</aside>
    {busy && <div className="busy">{busy}</div>}
  </div>
}
