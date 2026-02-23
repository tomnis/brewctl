import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Set browser title based on environment
const isProd = import.meta.env.VITE_COLDBREW_IS_PROD === 'true'
document.title = isProd ? './brewctl --prod' : 'brewctl --dev'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
