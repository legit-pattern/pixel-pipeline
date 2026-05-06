import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:7861',
        changeOrigin: true,
      },
      '/outputs': {
        target: 'http://localhost:7861',
        changeOrigin: true,
      },
    },
  },
})
