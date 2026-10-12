import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const databaseUrl = process.env.E2E_DATABASE_URL;
if (!databaseUrl) throw new Error("Set E2E_DATABASE_URL to a dedicated local *_e2e_test database.");
const parsed = new URL(databaseUrl);
if (parsed.protocol !== "postgresql+psycopg:" || !["localhost", "127.0.0.1"].includes(parsed.hostname) || !parsed.pathname.endsWith("_e2e_test")) {
  throw new Error("E2E_DATABASE_URL must use postgresql+psycopg and a local *_e2e_test database.");
}

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:3100", browserName: "chromium", trace: "off" },
  webServer: [
    {
      command: "uv run --locked uvicorn recovery_app:app --app-dir tests --host 127.0.0.1 --port 8100" + (process.env.E2E_PRODUCTION === "true" ? " --workers 1 --limit-concurrency 8 --no-access-log --no-proxy-headers" : ""),
      cwd: resolve(__dirname, "../backend"),
      env: { DATABASE_URL: databaseUrl, TRIPTAB_ENV: "test", TRIPTAB_FRONTEND_BASE_URL: "http://127.0.0.1:3100", TRIPTAB_COOKIE_SECURE: "false", TRIPTAB_ALLOWED_ORIGINS: "http://127.0.0.1:3100", TRIPTAB_AUTH_RATE_LIMIT: "100", TRIPTAB_AUTH_GLOBAL_LIMIT: "100" },
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
    },
    {
      command: `${process.env.E2E_PRODUCTION === "true" ? "npm run start" : "npm run dev"} -- --hostname 127.0.0.1 --port 3100`,
      env: { TRIPTAB_API_ORIGIN: "http://127.0.0.1:8100" },
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
    },
  ],
});
