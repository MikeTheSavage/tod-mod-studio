// How the building tools reach the shared 3D view: its api object (scene, camera, picking), a drawing layer inside its scene,
// the mouse, and the controller. The view itself is never changed.
import { useEffect, useRef, useState } from 'react'
import { BuildLayer } from './layer.js'
import { onTick, getMode } from '../pad/padstore.js'

// viewApi is the ref the screen gave to View3D (apiRef); the canvas fills it a moment after the first render
export function useViewApi(viewApi) {
  const [api, setApi] = useState(null)
  useEffect(() => {
    let cur = null
    const look = () => {
      const a = viewApi?.current
      const ok = a && a.scene && a.gl && a.camera ? a : null
      if (ok !== cur) { cur = ok; setApi(ok) }
    }
    look()
    const id = setInterval(look, 400)
    return () => clearInterval(id)
  }, [viewApi])
  return api
}

export function useBuildLayer(api) {
  const [layer, setLayer] = useState(null)
  useEffect(() => {
    if (!api?.scene) { setLayer(null); return undefined }
    const l = new BuildLayer(api.scene)
    setLayer(l)
    return () => { l.dispose(); setLayer(null) }
  }, [api?.scene])
  return layer
}

// Left button on the ground. cfg: { active, onDown(hit, ev) -> true to take the gesture, onMove(hit, ev, down), onUp(hit, ev), onHover(hit, ev), onKey(ev), onPad(name, hit) }.
// Alt or Shift + drag still orbits and pans; the camera only stops while a gesture of the tool is running.
export function usePointer(api, cfg) {
  const ref = useRef(cfg); ref.current = cfg
  useEffect(() => {
    if (!api?.gl || !cfg.active) return undefined
    const el = api.gl.domElement
    let down = false
    const hit = e => api.pointerHit(e.clientX, e.clientY)
    const pd = e => {
      if (e.button !== 0 || e.altKey || e.shiftKey || e.ctrlKey) return
      const h = hit(e)
      if (!h) return
      if (ref.current.onDown?.(h, e)) {
        e.stopImmediatePropagation(); e.preventDefault()
        down = true
        if (api.controls) api.controls.enabled = false
      }
    }
    const mv = e => {
      const h = hit(e)
      if (!h) return
      if (down) ref.current.onMove?.(h, e, true)
      else ref.current.onHover?.(h, e)
    }
    const pu = e => {
      if (!down) return
      down = false
      if (api.controls) api.controls.enabled = true
      ref.current.onUp?.(hit(e) || null, e)
    }
    const key = e => {
      const t = e.target?.tagName
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') return
      ref.current.onKey?.(e)
    }
    el.addEventListener('pointerdown', pd, true); el.addEventListener('pointermove', mv); window.addEventListener('pointerup', pu); window.addEventListener('keydown', key)
    return () => {
      el.removeEventListener('pointerdown', pd, true); el.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', pu); window.removeEventListener('keydown', key)
      if (api.controls) api.controls.enabled = true
    }
  }, [api, cfg.active])
  // the controller: while the 3D view has the focus in pad mode, A acts at the centre reticle (one press = one gesture), X and Y step the size and strength.
  // The pad host answers A itself and stops the other listeners, so the raw button state is watched instead (every frame, rising edges only).
  useEffect(() => {
    if (!api || !cfg.active) return undefined
    let prev = {}
    return onTick(st => {
      const held = st.held || {}
      const down = n => held[n] && !prev[n]
      const a = down('A'), x = down('X'), y = down('Y')
      prev = { A: held.A, X: held.X, Y: held.Y }
      if (!(a || x || y) || getMode() !== 'pad' || !api.padOn?.()) return
      if (a) {
        const p = api.centerPoint?.()
        if (p) ref.current.onPad?.('A', { pos: p, geometry: true })
      } else ref.current.onPad?.(x ? 'X' : 'Y', null)
    })
  }, [api, cfg.active])
}

// the tool's answer from the server, kept until the recipe it came from changes (debounced)
export function useDebounced(value, ms) {
  const [v, setV] = useState(value)
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id) }, [value, ms])
  return v
}
