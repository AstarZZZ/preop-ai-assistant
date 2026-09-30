import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  root: 'frontend',
  base: '/static/',
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/assets': 'http://127.0.0.1:8765',
      '/media': 'http://127.0.0.1:8765'
    }
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: true
  }
})
