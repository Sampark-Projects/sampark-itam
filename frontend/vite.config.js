import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// Sampark brand green (#1d6838) in place of the blue shipped with PrimeVue's saga-blue theme
const samparkTheme = () => ({
  name: 'sampark-primevue-theme',
  enforce: 'pre',
  transform(code, id) {
    if (!id.includes('themes/saga-blue/theme.css')) return null
    return code
      .replace(/#2196f3/gi, '#1d6838')
      .replace(/#0d89ec/gi, '#185a30')
      .replace(/#0b7ad1/gi, '#154f2a')
      .replace(/#a6d5fa/gi, '#a5c3af')
      .replace(/#e3f2fd/gi, '#e8f0eb')
      .replace(/rgba\(33, 150, 243,/g, 'rgba(29, 104, 56,')
  }
})

export default defineConfig({
  plugins: [samparkTheme(), vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      'vue-i18n': 'vue-i18n/dist/vue-i18n.esm-bundler.js'
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['industrace.local', 'www.industrace.local', 'localhost'],
    hmr: false,
    // Bind mounts from Windows/OneDrive do not deliver file-change events into the
    // container, so Vite kept serving stale modules. Poll for changes instead.
    watch: { usePolling: true, interval: 1000 },
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 1000,
    assetsDir: 'static'
  },
  optimizeDeps: {
    include: ['vis-network']
  }
})

