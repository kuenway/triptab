import { expect, test } from "@playwright/test";

test("account names default only new Trip identities and password change revokes other sessions", async ({ page, browser }, testInfo) => {
  const email = `account-settings-${Date.now()}@example.com`;
  const oldPassword = "Account settings old password 123", newPassword = "Account settings new password 456";
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await page.goto("/register"); await page.getByLabel("Display name").fill("Original");
  await page.getByLabel("Email", { exact: true }).fill(email); await page.getByLabel("Password", { exact: true }).fill(oldPassword);
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("link", { name: "Account", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    await expect(page.getByRole("navigation", { name: "Trip sections" })).toHaveCount(0);
    await expect(page.getByText(email, { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByLabel("Name", { exact: true }).focus();
    await page.keyboard.press("Tab"); await expect(page.getByRole("button", { name: "Save", exact: true })).toBeFocused();
    expect(await page.getByRole("button", { name: "Save", exact: true }).evaluate(e => getComputedStyle(e).outlineStyle)).toBe("solid");
    for (const button of await page.getByRole("button").all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath(`account-settings-${width}.png`), fullPage: true });
  }
  await page.getByLabel("Name", { exact: true }).fill("Alice Chen"); await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Name saved.");
  await page.getByRole("link", { name: "← All trips" }).click();
  const trigger = page.getByRole("button", { name: "Account menu" }); await expect(trigger).toHaveText("A"); await trigger.click();
  await expect(page.getByRole("group", { name: "Your account" })).toContainText("Alice Chen");
  await page.keyboard.press("Escape");
  const create = async (name: string) => {
    await page.getByRole("button", { name: "+ New trip" }).click(); await page.getByLabel("Trip name").fill(name);
    await page.getByRole("button", { name: "Create trip", exact: true }).click(); await expect(page).toHaveURL(/\/trips\/[^/]+$/); return page.url();
  };
  const first = await create("Account default first trip");
  await page.getByRole("navigation", { name: "Trip sections" }).getByRole("link", { name: "Tripmates" }).click();
  await expect(page.getByRole("group", { name: "Tripmate Alice Chen", exact: true })).toContainText("Owner · You");
  await page.goto("/account"); await page.getByLabel("Name", { exact: true }).fill("Alice"); await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Name saved.");
  await page.getByRole("link", { name: "← All trips" }).click(); await expect(page.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible(); await expect(page).toHaveURL("http://127.0.0.1:3100/"); await page.goBack(); await expect(page).toHaveURL(/\/account$/);
  await page.getByRole("link", { name: "← All trips" }).click();
  await create("Account default second trip");
  await page.getByRole("navigation", { name: "Trip sections" }).getByRole("link", { name: "Tripmates" }).click();
  await expect(page.getByRole("group", { name: "Tripmate Alice", exact: true })).toContainText("Owner · You");
  await page.goto(first + "/travelers"); await expect(page.getByRole("group", { name: "Tripmate Alice Chen", exact: true })).toBeVisible();
  const context = await browser.newContext();
  try {
    const second = await context.newPage(); await second.goto("/login");
    await second.getByLabel("Email", { exact: true }).fill(email); await second.getByLabel("Password", { exact: true }).fill(oldPassword);
    await second.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(second.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
    await page.goto("/account"); await page.reload(); await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Alice");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toHaveCount(0);
    for (const [unsafe, message] of [[oldPassword, "Choose a new password different from your current password."], [email.toUpperCase(), "Choose a password different from your email."]]) {
      await page.getByLabel("Current password", { exact: true }).fill(oldPassword);
      await page.getByLabel("New password", { exact: true }).fill(unsafe);
      await page.getByLabel("Confirm new password").fill(unsafe);
      await page.getByRole("button", { name: "Change password", exact: true }).click();
      await expect(page.locator("#password-error")).toHaveText(message);
      expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
      expect((await second.request.get("/api/v1/auth/me")).status()).toBe(200);
    }
    await page.getByLabel("Current password", { exact: true }).fill(oldPassword); await page.getByLabel("New password", { exact: true }).fill(newPassword);
    await page.getByLabel("Confirm new password").fill(newPassword); await page.getByRole("button", { name: "Change password", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Password changed.");
    await expect(page.getByLabel("Current password", { exact: true })).toHaveValue("");
    expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
    expect((await second.request.get("/api/v1/auth/me")).status()).toBe(401);
    await second.reload(); await expect(second.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    await second.getByLabel("Email", { exact: true }).fill(email); await second.getByLabel("Password", { exact: true }).fill(oldPassword);
    await second.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(second.getByRole("alert").filter({ hasText: "invalid email or password" })).toBeVisible();
    await second.getByLabel("Password", { exact: true }).fill(newPassword); await second.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(second.getByRole("heading", { name: "Your trips", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "← All trips" }).click(); await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click(); await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  } finally { await context.close(); }
});
