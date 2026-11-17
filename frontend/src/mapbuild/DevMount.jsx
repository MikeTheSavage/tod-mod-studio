// A stand-alone page for trying the building tools without the New maps screen: open the app with ?build=1 (add &sample=1 for the
// sample map). It holds one map in memory with the shared undo history and mounts MapBuildTools exactly as the screen does.
import React, { useMemo, useRef, useState } from 'react'
import View3D from '../View3D.jsx'
import { UndoRedo } from '../ui.jsx'
import { useHistory, useUndoKeys } from '../history.js'
import MapBuildTools from './MapBuildTools.jsx'
import { SAMPLE } from './sample.js'
import { t } from '../i18n.js'

export default function DevMount() {
  const p = new URLSearchParams(location.search)
  const [map, setMap] = useState(() => (p.get('sample') ? structuredClone(SAMPLE) : { name: 'Dev', source: 'map10_runawaytrain', arrival: { pos: [0, 3, 0], orient: [0, 0, 0, 1] } }))
  const ref = useRef(map); ref.current = map
  const hist = useHistory(() => ref.current, v => setMap(v))
  useUndoKeys(hist)
  const commit = next => { hist.record(); setMap(next) }
  const apiRef = useRef({})
  window.__mb = { get map() { return ref.current }, commit, hist }
  const focus = useMemo(() => ({ eye: [-110, 70, -110], target: [0, 0, 0] }), [])
  return <div className="screen" style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'var(--bg)' }}>
    <div className="tb"><b>{map.name}</b><div style={{ flex: 1 }} /><UndoRedo h={hist} compact />
      <button onClick={() => commit(structuredClone(SAMPLE))}>{t('sample_map')}</button></div>
    <div style={{ position: 'absolute', inset: '40px 0 0 0', display: 'flex' }}>
      <View3D defaultMode="3d" apiRef={apiRef} focus={focus} bg="#1a2029">
        <MapBuildTools map={map} project={{ maps: [map] }} commit={commit} viewApi={apiRef} />
      </View3D>
    </div>
  </div>
}
