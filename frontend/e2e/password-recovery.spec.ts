import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

const OLD = "Recovery old password 123", NEW = "correct horse battery staple";
async function register(page: Page, email: string) {
  await page.goto("/register"); await page.getByLabel("Display name").fill("Recovery user"); await page.getByLabel("Email", { exact: true }).fill(email); await expect(page.getByText("Use at least 12 characters. Passphrases are welcome. No special symbols are required.")).toBeVisible();
  for (const unsafe of [email, email.toUpperCase()]) {
    await page.getByLabel("Password", { exact: true }).fill(unsafe);
    const response = page.waitForResponse(r => new URL(r.url()).pathname === "/api/v1/auth/register" && r.request().method() === "POST");
    await page.getByRole("button", { name: "Register", exact: true }).click();
    expect((await response).status()).toBe(422);
    await expect(page.getByRole("alert").filter({ hasText: "Choose a password different from your email." })).toHaveText("Choose a password different from your email.");
  }
  await page.getByLabel("Password", { exact: true }).fill(OLD); await page.getByRole("button", { name: "Register", exact: true }).click(); await expect(page.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
}
async function requestReset(page: Page, email: string) {
  await page.goto("/forgot-password"); await page.getByLabel("Email").fill(email); await page.getByRole("button", { name: "Send reset link", exact: true }).click(); await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible(); return page.getByRole("status").innerText();
}
async function emails(request: APIRequestContext, email: string, count: number) {
  const read = async () => (await (await request.get("http://127.0.0.1:8100/__test__/reset-emails", { params: { email } })).json()) as { url: string }[];
  await expect.poll(async () => (await read()).length).toBe(count); return read();
}
async function submitReset(page: Page, url: string) {
  await page.goto(url); await expect(page.getByLabel("New password", { exact: true })).toBeVisible(); expect(new URL(page.url()).hash).toBe(""); expect(new URL(page.url()).search).toBe(""); await page.getByLabel("New password", { exact: true }).fill(NEW); await page.getByLabel("Confirm new password").fill(NEW); await page.getByRole("button", { name: "Reset password", exact: true }).click();
}

test("email recovery revokes all sessions, asks for Sign in and preserves generic public UX", async ({ page, browser, request }, testInfo) => {
  const email = `recovery-${Date.now()}@example.com`; await register(page, email);
  const other = await browser.newContext();
  try {
    const second = await other.newPage(); await second.goto("/login"); await second.getByLabel("Email", { exact: true }).fill(email); await second.getByLabel("Password", { exact: true }).fill(OLD); await second.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(second.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
    const known = await requestReset(page, email), unknown = await requestReset(page, `unknown-${Date.now()}@example.com`); expect(known).toBe(unknown);
    const link = (await emails(request, email, 1))[0]!.url; const parsed = new URL(link); expect(parsed.pathname).toBe("/reset-password"); expect(parsed.search).toBe(""); expect(parsed.hash.startsWith("#token=")).toBe(true);
    const sent: string[] = []; page.on("request", r => sent.push(r.url())); await page.goto(link); await expect(page.getByLabel("New password", { exact: true })).toBeVisible();
    for (const width of [375, 1280]) {
      await page.setViewportSize({ width, height: 812 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.getByLabel("New password", { exact: true }).focus(); await page.keyboard.press("Tab"); await expect(page.getByLabel("Confirm new password")).toBeFocused(); await page.keyboard.press("Tab"); await expect(page.getByRole("button", { name: "Reset password", exact: true })).toBeFocused(); expect(await page.getByRole("button", { name: "Reset password", exact: true }).evaluate(e => getComputedStyle(e).outlineStyle)).toBe("solid"); expect((await page.getByRole("button", { name: "Reset password", exact: true }).boundingBox())!.height).toBeGreaterThanOrEqual(44); await expect(page.getByLabel("New password", { exact: true })).toHaveAttribute("autocomplete", "new-password"); await page.screenshot({ path: testInfo.outputPath(`recovery-${width}.png`) });
    }
    for (const [unsafe, message] of [[OLD, "Choose a new password different from your current password."], [email.toUpperCase(), "Choose a password different from your email."]]) {
      await page.getByLabel("New password", { exact: true }).fill(unsafe);
      await page.getByLabel("Confirm new password").fill(unsafe);
      await page.getByRole("button", { name: "Reset password", exact: true }).click();
      await expect(page.locator("#reset-error")).toHaveText(message);
      expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
      expect((await second.request.get("/api/v1/auth/me")).status()).toBe(200);
    }
    expect(new URL(page.url()).hash).toBe(""); await page.getByLabel("New password", { exact: true }).fill(NEW); await page.getByLabel("Confirm new password").fill("Mismatch password 789"); await page.getByRole("button", { name: "Reset password", exact: true }).click(); await expect(page.locator("#reset-error")).toHaveText("New passwords do not match."); await page.getByLabel("Confirm new password").fill(NEW); await page.getByRole("button", { name: "Reset password", exact: true }).click(); await expect(page.getByRole("heading", { name: "Password reset", exact: true })).toBeVisible(); expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401); expect((await second.request.get("/api/v1/auth/me")).status()).toBe(401);
    expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 }); expect(sent.every(url => !new URL(url).pathname.includes(parsed.hash.slice(7)) && !new URL(url).search.includes(parsed.hash.slice(7)))).toBe(true);
    await page.getByRole("link", { name: "Sign in", exact: true }).click(); await page.getByLabel("Email", { exact: true }).fill(email); await page.getByLabel("Password", { exact: true }).fill(OLD); await page.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(page.getByRole("alert").filter({ hasText: "invalid email or password" })).toBeVisible(); await page.getByLabel("Password", { exact: true }).fill(NEW); await page.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(page.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
  } finally { await other.close(); }
});

test("latest reset email wins; consumed, expired and missing links remain neutral", async ({ page, request }) => {
  const email = `recovery-lifecycle-${Date.now()}@example.com`; await register(page, email); await requestReset(page, email); const first = (await emails(request, email, 1))[0]!.url; await requestReset(page, email); const second = (await emails(request, email, 2))[1]!.url;
  await submitReset(page, first); await expect(page.getByText("This reset link is invalid or has expired.")).toBeVisible(); await submitReset(page, second); await expect(page.getByRole("heading", { name: "Password reset", exact: true })).toBeVisible(); await submitReset(page, second); await expect(page.getByText("This reset link is invalid or has expired.")).toBeVisible();
  await requestReset(page, email); const expired = (await emails(request, email, 3))[2]!.url; const token = new URL(expired).hash.slice(7); const result = await request.post("http://127.0.0.1:8100/__test__/expire-reset", { data: { token, new_password: NEW } }); expect(result.status()).toBe(204); await submitReset(page, expired); await expect(page.getByText("This reset link is invalid or has expired.")).toBeVisible(); await page.goto("/reset-password"); await expect(page.getByText("This reset link is invalid or has expired.")).toBeVisible(); await expect(page.getByRole("button", { name: "Reset password", exact: true })).toHaveCount(0);
  await page.goto("/forgot-password"); for (const width of [375, 1280]) { await page.setViewportSize({ width, height: 812 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.getByLabel("Email").focus(); await page.keyboard.press("Tab"); await expect(page.getByRole("button", { name: "Send reset link", exact: true })).toBeFocused(); expect((await page.getByRole("button", { name: "Send reset link", exact: true }).boundingBox())!.height).toBeGreaterThanOrEqual(44); }
  const response = await request.get("/reset-password"); expect(response.headers()["cache-control"]).toContain("no-store"); expect(response.headers()["referrer-policy"]).toBe("no-referrer");
});
