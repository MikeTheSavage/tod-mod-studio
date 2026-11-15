// Mesh and texture loading for the cached glbs: geometry from the glb, textures from .dds files (the GPU reads DXT
// directly), Lambert materials (TOD is diffuse lit; metalness would render black without an environment map).
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { DDSLoader } from 'three/examples/jsm/loaders/DDSLoader.js'

const gltfLoader = new GLTFLoader()
const ddsLoader = new DDSLoader()
const glbCache = new Map()
const texCache = new Map()
const matCache = new Map()

export const collisionMaterial = new THREE.MeshBasicMaterial({
  vertexColors: true, transparent: true, opacity: 0.45, depthWrite: false, side: THREE.DoubleSide,
  polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
})
const plainMaterial = new THREE.MeshLambertMaterial({ color: 0x9aa3ad, side: THREE.DoubleSide })

function texture(info) {
  if (!info?.url) return null
  if (!texCache.has(info.url)) {
    const t = ddsLoader.load(info.url, tex => {
      if (info.alpha && tex.format === THREE.RGB_S3TC_DXT1_Format) {
        tex.format = THREE.RGBA_S3TC_DXT1_Format
        tex.needsUpdate = true
      }
    })
    t.wrapS = t.wrapT = THREE.RepeatWrapping
    t.anisotropy = 4
    texCache.set(info.url, t)
  }
  return texCache.get(info.url)
}

function material(texName, info) {
  const key = texName || '-'
  if (!matCache.has(key)) {
    const map = texture(info)
    const m = map ? new THREE.MeshLambertMaterial({ map, side: THREE.DoubleSide }) : plainMaterial
    if (map && info.alpha) { m.alphaTest = 0.5; m.transparent = false }
    matCache.set(key, m)
  }
  return matCache.get(key)
}

// -> Promise<{render: Object3D|null, collision: Object3D|null}> shared prototypes (clone per instance)
export function loadModel(name, rec) {
  if (!rec?.url) return Promise.resolve(null)
  if (!glbCache.has(rec.url)) {
    glbCache.set(rec.url, new Promise(resolve => {
      gltfLoader.load(rec.url, g => {
        let render = null, collision = null
        g.scene.traverse(o => {
          if (!o.isMesh) return
          if (o.parent && /collision/.test(o.name + (o.parent.name || ''))) {
            o.material = collisionMaterial
            collision = collision || new THREE.Group()
          }
        })
        const r = g.scene.getObjectByName('render')
        const c = g.scene.getObjectByName('collision')
        if (r) {
          r.traverse(o => {
            if (o.isMesh) {
              const ref = o.material?.userData?.tod_texture
              o.material = material(ref, rec.textures?.[ref])
            }
          })
          render = r
        }
        if (c) {
          c.traverse(o => { if (o.isMesh) o.material = collisionMaterial })
          collision = c
        }
        resolve({ render, collision })
      }, undefined, () => resolve(null))
    }))
  }
  return glbCache.get(rec.url)
}
