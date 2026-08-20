/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Deliberately narrower than 'BREWCTL_': that prefix also covers
  // BREWCTL_INFLUXDB_TOKEN and friends, and anything matching envPrefix in the
  // build environment can reach the client bundle. Only BREWCTL_FRONTEND_* is
  // safe to expose.
  envPrefix: 'BREWCTL_FRONTEND_',
  // Relative, matching the path the api service mounts the bundle at
  // (app.mount("/app/assets", ...) in brewctl/api/server.py). An absolute base
  // would bake one host into every asset URL.
  base: "/app/",
  server: {
      host: '0.0.0.0',
      allowedHosts: [
        'coldbrewer.local',
        'pi4.local'
      ]
    },
  test: {
    globals: true,
    environment: 'jsdom',
  },
})