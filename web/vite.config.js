/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Scout's frontend build/dev/test configuration (Step 14).
// - `server.port` is fixed at 5173 (Vite's own default) so the value
//   documented everywhere else (README, backend CORS_ALLOWED_ORIGINS,
//   CLAUDE.md) stays correct without guessing which port Vite picked.
// - The `test` block runs Vitest in a jsdom environment with React
//   Testing Library's jest-dom matchers loaded globally, and treats
//   this file itself as the single source of truth for both the app
//   build and the test run - no separate vitest.config.ts.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
    },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./src/setupTests.ts"],
        css: true,
    },
});
