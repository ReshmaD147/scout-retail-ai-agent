/**
 * The backend base URL, read from `VITE_SCOUT_API_BASE_URL` (Step 14)
 * - never hardcoded, so the same build can point at a different
 * backend without a code change. Falls back to the local development
 * default only when the variable is entirely unset (e.g. a fresh
 * checkout that has not copied `.env.example` to `.env` yet).
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_SCOUT_API_BASE_URL ?? "http://127.0.0.1:8000";
