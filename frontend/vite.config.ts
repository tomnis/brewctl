import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  envPrefix: 'COLDBREW_FRONTEND_API_URL',
  // TODO need to change when deploying?
  base: "http://localhost:8000/app",
  server: {
      host: '0.0.0.0',
      allowedHosts: [
        'coldbrewer.local',
        'pi4.local'
      ]
    },
})
