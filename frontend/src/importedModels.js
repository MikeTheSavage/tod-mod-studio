// Imported models as placeable things, for the level editor's Add menu (the editor itself is not changed here).
//
//   const list = importedPalette(project)                 -> [{ id, name, path, modelres, tris, size }]   path = the game path of the model
//   fetch the mesh for the live preview:  post('/api/models/find', { names: list.map(m => m.path), imported: project.models })
//        -> { models: { [path]: { url (a textured .glb with a 'render' node), bound, tris, imported: true } } }   (models.js loadModel draws it)
//   place one:  opForPlacing(model, template, entry, pos, rot, uid)    template = any Model node of the block (the palette's usual template)
//
// The build puts the model and its textures into every block that has such an `add` op; a model nobody places is not written.
export function importedPalette(project) {
  return (project?.models || []).filter(m => m.mode === 'new').map(m => ({
    id: m.id, name: m.name, path: m.path, modelres: m.path.replace(/^\/data/i, ''), tris: m.stats?.triangles || 0, size: m.stats?.size || null,
  }))
}

export function opForPlacing(model, template, entry, pos, rot, uid) {
  return {
    op: 'add', uid, entry, template, name: model.name.replace(/\s+/g, '_'), pos, rot: rot || [0, 0, 0, 1],
    set: { modelres: model.modelres },
    view: { type: 'Model', cat: 'model', kindLabel: 'Model', name: model.name, model: model.path.toLowerCase() },
  }
}
