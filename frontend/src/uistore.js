import { useSyncExternalStore } from 'react'
import { getUi, subscribeUi, setPrefs } from './uiprefs.js'

// { prefs, resolved ('dark' | 'light' | 'contrast'), base ('dark' | 'light'), reduced } and the setter
export function useUi() {
  const s = useSyncExternalStore(subscribeUi, getUi)
  return { ...s, set: setPrefs }
}
