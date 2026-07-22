/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SCOUT_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
