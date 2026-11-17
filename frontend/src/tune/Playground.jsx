// Tune > Playground: try the tuned weapons, cars, camera and slow motion without starting the game.
// An approximation: the damage rules, rates, speeds and camera numbers are the game's; the physics and flight are not.
import React, { useEffect, useMemo, useState } from 'react'
import { get, runJob } from '../api.js'
import { Seg } from '../ui.jsx'
import * as M from './mapping.js'
import { vehicleModelPath } from './gameModels.js'
import RangeMode from './RangeMode.jsx'
import WalkMode from './WalkMode.jsx'
import DriveMode from './DriveMode.jsx'
import './tune.css'
import { t } from '../i18n.js'
import { t as tr } from '../i18n.js'

const MODES = [{ value: 'range', label: tr('range') }, { value: 'drive', label: tr('drive') }, { value: 'walk', label: tr('walk') }]
const HINT = {
  range: 'Mouse: aim. Left button or Space: fire. R: reload. W A S D: walk, Shift: run. Pad: left stick walk, right stick aim, RT or A fire, X reload, B leave.',
  drive: 'W S: gas and brake or reverse. A D: steer. V: brake. Space: handbrake. R: set upright. Pad: left stick steer, RT gas, LT brake or reverse, X brake, A handbrake, Y upright, B leave.',
  walk: 'W A S D: walk, Shift: run. Space: dive. Q: slow motion. Pad: left stick walk, RT run, A dive, LB or Y slow motion, B leave.',
}
const NONE = {}
const plain = g => String(g).replace(/^Vehicle type: /, '').replace(/\s*\([^)]*\)\s*$/, '')

export default function Playground({ data, vals, pick = {}, onBack }) {
  const q = useMemo(() => new URLSearchParams(location.search), [])
  const [mode, setMode] = useState(q.get('play') || 'range')
  const [mine, setMine] = useState(q.get('ab') !== 'default')
  const weapons = useMemo(() => data.weapons.groups.filter(g => { const w = M.weaponOf(data.weapons, {}, g.group, false); return w.clip > 0 && w.max > 0 && w.fireRate > 0 }).map(g => g.group), [data])
  const vehicles = useMemo(() => data.vehicles.groups.map(g => g.group).filter(g => /^Vehicle type: /.test(g) && vehicleModelPath(g)), [data])
  const [wg, setWg] = useState(() => (weapons.includes(pick.weapons) ? pick.weapons : null) || weapons.find(g => g.startsWith(q.get('gun') || 'Beretta')) || weapons[0])
  const [vg, setVg] = useState(() => (vehicles.includes(pick.vehicles) ? pick.vehicles : null) || vehicles.find(g => g === 'Vehicle type: ' + (q.get('car') || 'Sedan')) || vehicles[0])
  const [resetKey, setResetKey] = useState(0)

  // the current mod's values, or the game's own
  const w = useMemo(() => M.weaponOf(data.weapons, vals.weapons || NONE, wg, mine), [data, vals, wg, mine])
  const v = useMemo(() => M.vehicleOf(data.vehicles, vals.vehicles || NONE, vg, mine), [data, vals, vg, mine])
  const ph = useMemo(() => M.physicsFor(v), [v])
  const camPlayer = useMemo(() => M.cameraOf(data.camera, vals.camera || NONE, mine), [data, vals, mine])
  const camCar = useMemo(() => {
    const k = M.keyed(data.vehicles, vals.vehicles || NONE, mine), g = n => k['camdict.VehicleDefaultCam.' + n]
    return { maxAngle: g('MaxAngle') ?? 0.18, ease: g('AngleEaseInSpeed') ?? 8.5, maxDist: g('MaxDistance') ?? 0.8, moveIn: g('DistanceMoveInSpeed') ?? 2, moveOut: g('DistanceMoveOutSpeed') ?? 3.25, zFactor: g('DistanceZFactor') ?? 0.5 }
  }, [data, vals, mine])
  const sm = useMemo(() => M.slowmoOf(data.loco, vals.loco || NONE, mine), [data, vals, mine])

  // map sections for the drive mode
  const [catalog, setCatalog] = useState(null)
  const [place, setPlace] = useState({ map: q.get('map') || '', sec: 0 })
  const [mapData, setMapData] = useState(null)
  const [busy, setBusy] = useState(q.get('map') ? 'Opening the map' : null)
  const [err, setErr] = useState(null)
  useEffect(() => { if (mode === 'drive' && !catalog) get('/api/catalog').then(setCatalog).catch(() => setCatalog({ maps: [] })) }, [mode])
  useEffect(() => {
    if (!place.map || !catalog) { setMapData(null); return }
    const m = catalog.maps.find(x => x.id === place.map)
    const sec = m?.sections[place.sec]
    if (!m) return
    let live = true
    setBusy('Opening the map'); setErr(null)
    runJob('/api/open', { map: m.id, section: sec ? sec.entry : null, missions: [] }, j => live && setBusy(j.message || 'Opening the map'))
      .then(r => { if (live) { setMapData(r); setBusy(null) } })
      .catch(e => { if (live) { setErr(e.message); setBusy(null) } })
    return () => { live = false }
  }, [place.map, place.sec, catalog])
  const mapObj = catalog?.maps.find(x => x.id === place.map)

  return (
    <div className="pg screen" style={{ minHeight: 0 }}>
      <div className="tb">
        <div className="pgtb">
          <Seg value={mode} onChange={setMode} options={MODES} />
          <Seg value={mine ? 'mine' : 'default'} onChange={x => setMine(x === 'mine')} options={[{ value: 'mine', label: tr('mine') }, { value: 'default', label: tr('game') }]} />
          {mode === 'range' && <select aria-label={t('weapon')} value={wg} onChange={e => setWg(e.target.value)}>{weapons.map(g => <option key={g} value={g}>{plain(g)}</option>)}</select>}
          {mode === 'drive' && <>
            <select aria-label={t('car')} value={vg} onChange={e => setVg(e.target.value)}>{vehicles.map(g => <option key={g} value={g}>{plain(g)}</option>)}</select>
            <select aria-label={t('map')} value={place.map} onChange={e => setPlace({ map: e.target.value, sec: 0 })}>
              <option value="">{t('flat_ground')}</option>{(catalog?.maps || []).map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select>
            {mapObj && mapObj.sections.length > 0 && <select aria-label={t('section')} value={place.sec} onChange={e => setPlace(p => ({ ...p, sec: +e.target.value }))}>
              {mapObj.sections.map((s, i) => <option key={s.id} value={i}>{s.title}</option>)}</select>}
            <button className="sm" onClick={() => setResetKey(k => k + 1)} title={t('back_to_the_start')}>{t('reset')}</button>
          </>}
          <span className="chip" title={t('an_approximation_of_the_game_not')}>{t('approximate')}</span>
          <span className="chip" title={HINT[mode]}>{t('keys')}</span>
        </div>
        <div style={{ flex: 1 }} />
        <button className="sm" onClick={onBack}>{t('back_to_values')}</button>
      </div>
      <div className="pvbox" style={{ flex: 1 }}>
        {err && <div className="bad" style={{ padding: 10 }}>{err}</div>}
        {mode === 'range' && w && <RangeMode key={wg + (mine ? 'm' : 'g')} w={w} name={plain(wg)} cam={camPlayer} />}
        {mode === 'walk' && <WalkMode key={'w' + (mine ? 'm' : 'g')} cam={camPlayer} sm={sm} />}
        {mode === 'drive' && <DriveMode key={vg + (mine ? 'm' : 'g') + place.map + place.sec} vType={vg} ph={ph} mapData={place.map ? mapData : null} wantMap={!!place.map} cam={camCar} busyText={busy} resetKey={resetKey} />}
      </div>
    </div>
  )
}
