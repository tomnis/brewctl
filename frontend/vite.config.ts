/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['coldbrewer.local'],
  },
  test: {
    globals: true,
    environment: 'jsdom',
  },
})
