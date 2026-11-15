import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Python backend serves the built UI from backend/web. In development, run the backend with
// `python backend/main.py --server --port 8765` and `npm run dev`: /api and /cache are proxied.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: '../backend/web', emptyOutDir: true, chunkSizeWarningLimit: 3000 },
  server: {
    port: 5260,
    proxy: { '/api': 'http://127.0.0.1:8765', '/cache': 'http://127.0.0.1:8765' },
  },
})
