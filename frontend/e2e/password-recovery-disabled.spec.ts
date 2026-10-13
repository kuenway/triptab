import { expect, test } from "@playwright/test";

test.skip(process.env.NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED === "true", "Requires a recovery-disabled build/test backend.");

test("disabled recovery hides forms and rejects API bypasses without disrupting account/trip flows", async ({ page, request }) => {
  const email = `recovery-off-${Date.now()}@example.com`, password = "Recovery disabled test passphrase";
  const calls: string[] = [];
  page.on("request", request => { if (/\/api\/v1\/auth\/(forgot|reset)-password/.test(request.url())) calls.push(request.url()); });
  await page.goto("/login"); await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveCount(0);
  for (const path of ["/forgot-password", "/reset-password#token=" + "a".repeat(43)]) {
    await page.goto(path);
    await expect(page.getByRole("status")).toHaveText("Password recovery is currently unavailable.");
    await expect(page.locator("form")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Back to Sign in" })).toBeVisible();
    await expect.poll(() => new URL(page.url()).hash).toBe("");
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  }
  expect(calls).toEqual([]);
  await page.getByRole("link", { name: "Back to Sign in" }).click();
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Display name").fill("Recovery disabled account");
  await page.getByLabel("Email", { exact: true }).fill(email); await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "+ New trip", exact: true }).click();
  await page.getByLabel("Trip name").fill("Recovery-off disposable trip"); await page.getByRole("button", { name: "Create trip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Expenses", exact: true })).toBeVisible();
  for (const [route, payload] of [
    ["forgot-password", { email }], ["forgot-password", { email: "unknown@example.com" }],
    ["reset-password", { token: "a".repeat(43), new_password: "new disabled test passphrase" }],
  ] as const) {
    const response = await request.post("/api/v1/auth/" + route, { headers: { Origin: "http://127.0.0.1:3100" }, data: payload });
    expect(response.status()).toBe(503); expect(await response.json()).toEqual({ detail: "Password recovery is currently unavailable." });
    expect(response.headers()["cache-control"]).toBe("no-store");
  }
  const missingOrigin = await request.post("/api/v1/auth/forgot-password", { data: { email } });
  expect(missingOrigin.status()).toBe(403);
  expect(await (await request.get("http://127.0.0.1:8100/__test__/reset-emails", { params: { email } })).json()).toEqual([]);
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
  await page.getByRole("link", { name: "← All trips", exact: true }).click();
  await page.getByRole("button", { name: "Account menu", exact: true }).click(); await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(email); await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("link", { name: "Recovery-off disposable trip", exact: true })).toBeVisible();
});
