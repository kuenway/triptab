import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllEnvs());

it("requires an explicit server backend origin in production", async () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("TRIPTAB_API_ORIGIN", undefined);
  await expect(import("../../next.config")).rejects.toThrow("TRIPTAB_API_ORIGIN");
});

it.each(["ftp://example.com", "https://user:secret@example.com", "http://example.com/api", "malformed-secret-value"])("rejects invalid backend configuration without leaking it: %s", async (origin) => {
  vi.stubEnv("TRIPTAB_API_ORIGIN", origin);
  try {
    await import("../../next.config");
    throw new Error("Expected configuration rejection");
  } catch (error) {
    expect((error as Error).message).toContain("TRIPTAB_API_ORIGIN");
    expect((error as Error).message).not.toContain(origin);
  }
});

it("keeps API requests same-origin and supplies compatible browser headers", async () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("TRIPTAB_API_ORIGIN", "http://127.0.0.1:8100");
  const { default: config } = await import("../../next.config");
  expect(config.agentRules).toBe(false);
  expect(config.poweredByHeader).toBe(false);
  expect(await config.rewrites?.()).toEqual([{ source: "/api/:path*", destination: "http://127.0.0.1:8100/api/:path*" }]);
  const rules = await config.headers?.();
  const headers = Object.fromEntries(rules![0].headers.map(({ key, value }) => [key, value]));
  expect(headers["X-Content-Type-Options"]).toBe("nosniff");
  expect(headers["Referrer-Policy"]).toBe("no-referrer");
  expect(headers["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
  expect(headers["Content-Security-Policy"]).not.toContain("unsafe-inline");
});
