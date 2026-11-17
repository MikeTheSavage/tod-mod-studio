// Development hook: with ?build=1 in the address the building tools open on their own page, above the app (see DevMount.jsx).
// App.jsx imports this file only when the address has ?build=1, so it costs nothing otherwise.
import React from 'react'
import { createRoot } from 'react-dom/client'
import DevMount from './DevMount.jsx'

try {
  if (new URLSearchParams(location.search).get('build')) {
    const el = document.createElement('div')
    document.body.appendChild(el)
    createRoot(el).render(<DevMount />)
  }
} catch { /* no window */ }
