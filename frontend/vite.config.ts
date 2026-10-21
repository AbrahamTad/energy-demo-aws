
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    proxy: {
      '/api': mode === 'floci' ? {
        target: 'http://127.0.0.1:4567',
        // Floci uses the Host header to select our existing REST API.
        changeOrigin: false,
        headers: {
          host: '2dc5378b0c.execute-api.localhost.floci.io:4567',
        },
        rewrite: (path) => `/dev${path}`,
      } : {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
