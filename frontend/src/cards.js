// The pictures on the catalogue cards: each model drawn once, with its real textures, by the browser's own renderer,
// then kept by the backend (cache) so the next visit shows them at once. One model at a time; the visible cards first.
import * as THREE from 'three'
import { post } from './api.js'
import { loadModel } from './models.js'

const SIZE = 168
let R = null, scene = null, cam = null
const done = new Set(), failed = new Set()
let queue = []
let running = false
const listeners = new Set()
export const onCard = f => { listeners.add(f); return () => listeners.delete(f) }

function setup() {
  if (R) return
  R = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
  R.setPixelRatio(1)
  R.setSize(SIZE, SIZE, false)
  R.outputColorSpace = THREE.LinearSRGBColorSpace        // like the editor's canvases: the game's pictures pass through as stored
  scene = new THREE.Scene()
  scene.add(new THREE.AmbientLight(0xffffff, 1.0))
  const d = new THREE.DirectionalLight(0xffffff, 0.8); d.position.set(4, 8, 5); scene.add(d)
  cam = new THREE.PerspectiveCamera(36, 1, 0.01, 4000)
}

export function lit(proto) {
  const o = proto.clone(true)
  o.traverse(m => {
    if (!m.isMesh) return
    const src = m.material
    m.material = new THREE.MeshLambertMaterial({ map: src.map || null, color: src.map ? 0xffffff : 0x9aa3ad, side: THREE.DoubleSide, alphaTest: src.alphaTest || 0 })
  })
  return o
}

const wait = ms => new Promise(r => setTimeout(r, ms))
async function texturesReady(obj) {
  for (let i = 0; i < 25; i++) {
    let all = true
    obj.traverse(m => { const t = m.isMesh && m.material.map; if (t && !(t.mipmaps && t.mipmaps.length)) all = false })
    if (all) return
    await wait(100)
  }
}

async function make(item) {
  const found = await post('/api/models/find', { names: [item.path.toLowerCase()] })
  const rec = found.models[item.path.toLowerCase()]
  if (!rec || rec.missing) throw new Error('no mesh')
  const p = await loadModel(item.path, rec)
  if (!p?.render) throw new Error('no mesh')
  const obj = lit(p.render)
  await texturesReady(obj)
  setup()
  scene.add(obj)
  const box = new THREE.Box3().setFromObject(obj)
  const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3())
  const r = Math.max(s.length() / 2, 0.05)
  const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2)) * 1.05
  cam.position.set(c.x + dist * 0.62, c.y + dist * 0.42, c.z + dist * 0.66)
  cam.near = dist / 100; cam.far = dist * 20
  cam.lookAt(c); cam.updateProjectionMatrix()
  R.setClearColor(0x000000, 0)
  R.render(scene, cam)
  const png = R.domElement.toDataURL('image/png')
  scene.remove(obj)
  obj.traverse(m => { if (m.isMesh) m.material.dispose() })
  await post('/api/catalogue/card', { key: item.key, png })
}

async function pump() {
  if (running) return
  running = true
  while (queue.length) {
    const it = queue.shift()
    if (done.has(it.key) || failed.has(it.key)) continue
    try { await make(it); done.add(it.key) } catch (e) {
      failed.add(it.key)
      if (e && e.message === 'no mesh') post('/api/catalogue/card', { key: it.key, none: true }).catch(() => {})
    }
    listeners.forEach(f => f(it.key, done.has(it.key)))
  }
  running = false
}

// the cards on screen, nearest first; whatever was queued before is dropped
let warming = false
export function warm(items) {         // every picture, in this order (proof runs)
  warming = true
  queue = items.filter(i => !i.card && !i.none && !done.has(i.key) && !failed.has(i.key))
  pump()
}
export function want(items) {
  if (warming) return
  queue = items.filter(i => !i.card && !i.none && !done.has(i.key) && !failed.has(i.key))
  pump()
}
export const isDone = key => done.has(key)
export const cardUrl = key => `/cache/assets/thumbs_tex/${key}.png`
