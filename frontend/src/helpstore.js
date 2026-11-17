// Small shared state for the Help window and the lessons, plus the few facts kept between runs (localStorage, per viewer).
import { useSyncExternalStore } from 'react'

const KEY = 'todms.help.v1'
const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {} } catch { return {} } }
const write = o => { try { localStorage.setItem(KEY, JSON.stringify(o)) } catch { /* private window */ } }
export const savedHelp = () => read()
export const saveHelp = patch => write({ ...read(), ...patch })

const S = { help: { open: false, tab: 'guide', anchor: null, query: '', n: 0 }, lesson: null, offer: false, subs: new Set(), snap: null }
const snap = () => { S.snap = { help: S.help, lesson: S.lesson, offer: S.offer }; S.subs.forEach(f => f()) }
snap()
const sub = f => { S.subs.add(f); return () => S.subs.delete(f) }
export const useHelpStore = () => useSyncExternalStore(sub, () => S.snap)

// the Help window: tab = guide | lessons | examples | glossary | new
export function openHelp({ tab = 'guide', anchor = null, query = '' } = {}) { S.help = { open: true, tab, anchor, query, n: S.help.n + 1 }; snap() }
export function closeHelp() { S.help = { ...S.help, open: false }; snap() }
export function setHelpTab(tab) { S.help = { ...S.help, tab, anchor: null }; snap() }

// a running lesson: { id, step }
export function startLesson(id) { S.lesson = { id, step: 0, n: Date.now() }; S.help = { ...S.help, open: false }; S.offer = false; snap() }
export function gotoStep(step) { if (S.lesson) { S.lesson = { ...S.lesson, step }; snap() } }
export function endLesson() { S.lesson = null; snap() }

// the walkthrough offer shown once after the first-run setup
export function offerWalkthrough() { if (!read().offered) { S.offer = true; snap() } }
export function answerOffer(start) { S.offer = false; saveHelp({ offered: true }); snap(); if (start) startLesson('crate') }
