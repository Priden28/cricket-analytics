import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    proxy: {
      // Forward all /api, /plot, /analysis, /predict, /scrape calls to FastAPI
      '/api':      { target: 'http://localhost:8000', changeOrigin: true },
      '/plot':     { target: 'http://localhost:8000', changeOrigin: true },
      '/analysis': { target: 'http://localhost:8000', changeOrigin: true },
      '/predict':  { target: 'http://localhost:8000', changeOrigin: true },
      '/scrape':   { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
