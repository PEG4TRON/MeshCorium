import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import VueDevTools from 'vite-plugin-vue-devtools'

export default defineConfig({
  plugins: [vue(), VueDevTools()],
  base: '/connect-app/',
  build: {
    chunkSizeWarningLimit: 700,
    outDir: 'dist',
    emptyOutDir: true,
  },
})
