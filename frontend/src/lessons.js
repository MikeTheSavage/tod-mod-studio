// Interactive lessons: data (step text, what to point at, how to tell the step is done) and the pure step checker.
import { t } from './i18n.js'
// A step is done when its `done` condition holds. No `done` = an information step: only Next moves on.
//
// done conditions:
//   { screen: 'level' } | { screen: ['data', 'mods'] }   the open screen
//   { map: true }                                         a level is open in the editor
//   { adds: 1 }                                           this many objects added since the step began
//   { changes: 1 }                                        this many game values changed since the step began
//   { test: true }                                        a test in the game is building or running
//   { dom: 'css selector' }                               something on the screen matches
//   { textIn: ['css selector', 'text'] }                  an element matching the selector contains the text (any case)
//   { all: [..] } | { any: [..] }

export const countAdds = p => ((p && p.level) || []).filter(o => o.op === 'add').length
export const countChanges = p => Object.values((p && p.data) || {}).reduce((a, v) => a + Object.keys(v || {}).length, 0)

export function snapshotOf(project) { return { adds: countAdds(project), changes: countChanges(project) } }

// st = { screen, project, base: {adds, changes}, test: bool, exists: selector => bool }
export function condDone(c, st) {
  if (!c) return false
  if (c.all) return c.all.every(x => condDone(x, st))
  if (c.any) return c.any.some(x => condDone(x, st))
  if (c.screen !== undefined) return [].concat(c.screen).includes(st.screen)
  if (c.map) return !!(st.project && st.project.view && st.project.view.map)
  if (c.adds !== undefined) return countAdds(st.project) - ((st.base && st.base.adds) || 0) >= c.adds
  if (c.changes !== undefined) return countChanges(st.project) - ((st.base && st.base.changes) || 0) >= c.changes
  if (c.test) return !!st.test
  if (c.dom) return !!(st.exists && st.exists(c.dom))
  if (c.textIn) return !!(st.textIn && st.textIn(c.textIn[0], c.textIn[1]))
  return false
}
export const stepDone = (step, st) => !!step && !!step.done && condDone(step.done, st)

// target = a css selector the coach mark points at (optional); the first line of text is the whole instruction
export const LESSONS = [
  { id: 'crate', title: t('place_a_crate_and_test_it'), steps: [
    { text: t('open_the_level_editor'), target: '.rail button[aria-label="World"]', done: { screen: 'level' } },
    { text: t('pick_a_map_and_a_section'), target: '.crumb', done: { map: true } },
    { text: t('press_add_choose_pickup_then_click'), target: 'btn:Add', done: { adds: 1 } },
    { text: t('press_test_in_game'), target: '.tctl', done: { test: true } },
    { text: t('the_game_starts_with_your_crate') },
  ] },
  { id: 'weapon', title: t('change_a_weapon'), steps: [
    { text: t('open_tune'), target: '.rail button[aria-label="Tune"]', done: { screen: 'data' } },
    { text: t('click_a_number_in_a_weapon'), target: '.gd', done: { changes: 1 } },
    { text: t('open_play_to_put_it_in'), target: '.rail button[aria-label="Play"]', done: { screen: 'mods' } },
    { text: t('save_your_mod_then_press_install') },
  ] },
  { id: 'mission', title: t('add_a_mission'), steps: [
    { text: t('open_create_then_mission_templates'), target: '.rail button[aria-label="Create"]', done: { screen: 'mtpl' } },
    { text: t('choose_open_a_sample_then_a'), target: 'btn:Open a sample', done: { textIn: ['.tb button', 'race in the yard'] } },
    { text: t('press_check_and_read_the_result'), target: '.pipe' },
    { text: t('press_build_then_install_with_the'), target: '.pipe' },
  ] },
]
export const lessonById = id => LESSONS.find(l => l.id === id)
