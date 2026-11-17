// The viewport colour of the current theme (three.js clear colour); read when a view mounts.
export const vpColor = () => (typeof document !== 'undefined' && getComputedStyle(document.documentElement).getPropertyValue('--vp').trim()) || '#1a2029'
