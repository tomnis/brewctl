import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  envPrefix: 'COLDBREW_FRONTEND_API_URL',
  server: {
      allowedHosts: [
        'coldbrewer.local',
        'pi4.local'
      ]
    },
})
