import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  webServer: [
    {
      command:
        "cd ../../services/api && .venv/bin/python ../../scripts/e2e_api.py",
      url: "http://127.0.0.1:8107/health",
      timeout: 30000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 3107",
      url: "http://127.0.0.1:3107",
      timeout: 120000,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_DEV_MODE: "true",
        NEXT_PUBLIC_SUPABASE_URL: "",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "",
        NEXT_DIST_DIR: ".next-e2e",
        API_INTERNAL_URL: "http://127.0.0.1:8107",
      },
    },
  ],
  use: {
    baseURL: "http://127.0.0.1:3107",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
