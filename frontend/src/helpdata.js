// Help content that is not the guide itself: which guide section belongs to which screen, the glossary, and a search over the guide.
import { t as tr } from './i18n.js'
// Pure (no DOM, no React) so it can be tested with node.

// screen id -> guide anchor
export const SCREEN_ANCHOR = {
  home: 'first', level: 'level', routes: 'more', sections: 'more', collision: 'more', missions: 'more',
  mtpl: 'missiontemplates', newmaps: 'newmaps', import: 'import', textures: 'textures', data: 'data',
  mods: 'play', save: 'saves', limits: 'limits', debug: 'testgame', bisect: 'debug', support: 'debug',
  assets: 'catalogue', settings: 'access',
}
export const anchorFor = screen => SCREEN_ANCHOR[screen] || 'what'

export const GLOSSARY = [
  { term: tr('archive'), def: tr('a_big_file_the_game_reads') },
  { term: tr('block'), def: tr('one_chunk_of_a_level_inside') },
  { term: tr('collision'), def: tr('the_invisible_shapes_you_bump_into') },
  { term: tr('giver'), def: tr('the_box_a_player_steps_into') },
  { term: tr('gameplay'), def: tr('another_mod_for_the_game_that') },
  { term: tr('loader'), def: tr('an_invisible_box_that_loads_the') },
  { term: tr('map'), def: tr('one_whole_area_of_the_game') },
  { term: tr('mission_slot'), def: tr('one_of_the_17_places_the') },
  { term: tr('mod'), def: tr('a_list_of_your_changes_it') },
  { term: tr('nav_blocker'), def: tr('an_invisible_box_that_enemies_and') },
  { term: tr('pack'), def: tr('the_one_extra_file_mod_studio') },
  { term: tr('prefab'), def: tr('a_group_of_objects_you_saved') },
  { term: tr('recipe'), def: tr('the_small_file_that_describes_a') },
  { term: tr('route'), def: tr('a_path_that_enemies_walkers_or') },
  { term: tr('section'), def: tr('a_part_of_a_map_that') },
  { term: tr('test_copy'), def: tr('a_private_copy_of_the_game') },
  { term: tr('teleport_spot'), def: tr('a_place_where_the_player_arrives') },
  { term: tr('tod_hd'), def: tr('a_graphics_mod_for_the_game') },
  { term: tr('trigger'), def: tr('an_invisible_box_that_starts_something') },
  { term: tr('invisible_wall'), def: tr('a_box_that_blocks_the_player') },
]

// ---------------------------------------------------------------- the guide as searchable sections
const entities = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&rarr;': '→', '&ldquo;': '“', '&rdquo;': '”', '&hellip;': '…', '&nbsp;': ' ', '&mdash;': '—' }
const plain = h => h.replace(/<style[\s\S]*?<\/style>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/&[a-z]+;/g, e => entities[e] || ' ').replace(/\s+/g, ' ').trim()

// html -> [{id, title, level, text}] one entry per h2 / h3, text = everything up to the next heading
export function indexGuide(html) {
  const body = html.split(/<body[^>]*>/i)[1] || html
  const re = /<h([23])\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/h\1>/g
  const hits = []
  let m
  while ((m = re.exec(body))) hits.push({ level: +m[1], id: m[2], title: plain(m[3]).replace(/^\d+\s*/, ''), at: m.index, end: re.lastIndex })
  return hits.map((h, i) => ({ id: h.id, title: h.title, level: h.level, text: plain(body.slice(h.end, i + 1 < hits.length ? hits[i + 1].at : body.length)) }))
}

const norm = s => s.toLowerCase()
const words = q => norm(q).split(/[^a-z0-9À-ɏ]+/).filter(w => w.length > 1 || /\d/.test(w))

// -> [{id, title, level, snippet, score}] best first. Every word must appear (in the title or the text).
export function searchIndex(index, query) {
  const ws = words(query)
  if (!ws.length) return []
  const out = []
  for (const s of index) {
    const t = norm(s.title), x = norm(s.text)
    if (!ws.every(w => t.includes(w) || x.includes(w))) continue
    let score = 0
    for (const w of ws) { if (t.includes(w)) score += 10; const c = x.split(w).length - 1; score += Math.min(c, 5) }
    if (s.level === 2) score += 1
    out.push({ id: s.id, title: s.title, level: s.level, score, snippet: snippetOf(s.text, ws) })
  }
  return out.sort((a, b) => b.score - a.score)
}

export function snippetOf(text, ws) {
  const low = norm(text)
  let at = -1
  for (const w of ws) { const i = low.indexOf(w); if (i >= 0 && (at < 0 || i < at)) at = i }
  if (at < 0) return text.slice(0, 110)
  const from = Math.max(0, at - 40)
  return (from > 0 ? '…' : '') + text.slice(from, from + 120) + (from + 120 < text.length ? '…' : '')
}

export function searchGlossary(query) {
  const ws = words(query)
  if (!ws.length) return GLOSSARY
  return GLOSSARY.filter(g => ws.every(w => norm(g.term).includes(w) || norm(g.def).includes(w)))
}
