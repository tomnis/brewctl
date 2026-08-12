/// <reference types="vite/client" />

// Vite's envPrefix is 'BREWCTL_FRONTEND_', so only these reach the bundle.
// Declaring them means a typo becomes a type error rather than a silent
// `undefined` -- which is exactly how VITE_COLDBREW_IS_PROD went unnoticed.
interface ImportMetaEnv {
  /** Dev-time override. Unset in production, where the api serves the bundle same-origin. */
  readonly BREWCTL_FRONTEND_API_URL?: string;
  readonly BREWCTL_FRONTEND_IS_PROD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
