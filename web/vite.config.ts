import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  // Dev only: the proxy changes Host, so the browser's Origin never matches it and the
  // server's same-origin POST check would refuse everything. Drop Origin on the hop.
  server: {
    proxy: {
      '/api': { target: api, configure: (proxy) => proxy.on('proxyReq', (req) => req.removeHeader('origin')) },
      '/files': api,
    },
  },
})
