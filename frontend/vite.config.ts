import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const publicBase = env.VITE_PUBLIC_BASE?.trim() || '/'

  return {
    base: publicBase,
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
  }
})
